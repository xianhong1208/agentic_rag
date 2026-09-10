
"""Contextual Retrieval — Context Generator

為每個 chunk 生成上下文前綴，解決 chunk 脫離原文後語義模糊的問題。
參考：Anthropic "Introducing Contextual Retrieval" (2024-09)

用法：
    generator = ContextGenerator.from_config(rag_config)
    contextualized_texts = await generator.generate_batch(
        chunks=["前項所述之情形，不適用本條規定。", ...],
        full_document="《員工差旅管理辦法》全文...",
        file_name="員工差旅管理辦法.docx",
    )

效能：
    使用 sync OpenAI client + asyncio.to_thread 並行呼叫 LLM，
    搭配 asyncio.Semaphore 限流，最大化 vLLM continuous batching 效率。
    使用 sync client 可避免 PyInstaller 打包環境下 AsyncOpenAI 的 event loop 問題。
"""

from __future__ import annotations

import os
import asyncio
from typing import Callable, Optional, List

from src.log import get_api_logger

logger = get_api_logger()

# Prompt — written in English for i18n maintainability.
# CRITICAL DESIGN: the LLM is instructed to output in the SAME language as the source
# document (not English). This keeps the generated context prefix embedding-aligned
# with the chunk it precedes — hard-coding English output would break cross-language
# retrieval (e.g. Chinese chunk with English prefix drifts in bge-m3 vector space).
#
# Strengthened with few-shot examples + harder language rule because gemma-3-27b
# tends to slip into English for Chinese transcripts otherwise.
_CONTEXT_PROMPT = """\
You are a document analysis assistant. Generate a short context line (1-2 sentences) \
describing where the given chunk sits in the document, so a downstream retriever can \
understand it in isolation.

═══ ABSOLUTE LANGUAGE RULE (NON-NEGOTIABLE) ═══
The output MUST be in the EXACT SAME language/script as the chunk text.
- If chunk contains Chinese (中文), output ONLY in 中文. No English allowed.
- If chunk contains Japanese (日本語), output ONLY in 日本語.
- If chunk is in English, output in English.
Mixed-language output is FORBIDDEN. Output language is NOT optional.

═══ FEW-SHOT EXAMPLES (注意輸出語言對應)═══
Example 1 (Chinese chunk → Chinese output):
  Chunk: "本條規定建築物起造人應於申請建造執照時,檢附建築計畫..."
  Output: 營造業法第三條延伸規定,本段說明建築物起造人申請建造執照時應檢附之文件

Example 2 (English chunk → English output):
  Chunk: "Article 3 defines terms used in this Act, including 'construction work'..."
  Output: Article 3 of the Act, listing core terminology definitions

Example 3 (Chinese transcript chunk → Chinese output):
  Chunk: "副組長:這是我們現在的SOP 並沒有為這一項去創造新的做法"
  Output: 健保署副組長回應主席質詢,說明本案處理依現行 SOP,未新增作業流程

═══ OUTPUT CONSTRAINTS ═══
- Identify the speaker if obvious (transcripts) — e.g., 主席 / 副組長 / 代表
- Include the document name or topic title if relevant
- State WHAT the chunk discusses (do not paraphrase the chunk itself)
- Maximum {max_length} characters
- No quotation marks, no English "This chunk..." preamble
- If you cannot determine context, output a short topic in the same language as chunk

═══ NOW PROCESS ═══
Document name: {file_name}

<full_document>
{document_text}
</full_document>

<chunk>
{chunk_text}
</chunk>

Output the context line directly (remember: SAME LANGUAGE AS CHUNK):"""


def _detect_scripts(text: str) -> set:
    """偵測 text 中存在的主要 Unicode 字符 scripts 集合

    通用設計 — 不寫死任何特定語言,直接由 Unicode block 判定。
    支援 Latin / CJK / Hiragana / Katakana / Hangul / Cyrillic /
    Arabic / Devanagari / Hebrew / Thai 等所有主流 script。

    Returns:
        set of script names, e.g., {"Latin", "CJK"}, {"Hiragana", "CJK"} 等
    """
    scripts: set = set()
    for ch in text:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        # 排前面的常見 block(可隨需擴充,新增 script 不影響既有判斷)
        if cp < 0x0080:                              scripts.add("Latin")
        elif 0x00C0 <= cp < 0x0250:                  scripts.add("Latin")    # Latin Extended
        elif 0x0400 <= cp < 0x0500:                  scripts.add("Cyrillic")
        elif 0x0590 <= cp < 0x0600:                  scripts.add("Hebrew")
        elif 0x0600 <= cp < 0x0700:                  scripts.add("Arabic")
        elif 0x0900 <= cp < 0x0980:                  scripts.add("Devanagari")
        elif 0x0E00 <= cp < 0x0E80:                  scripts.add("Thai")
        elif 0x3040 <= cp < 0x30A0:                  scripts.add("Hiragana")
        elif 0x30A0 <= cp < 0x3100:                  scripts.add("Katakana")
        elif 0xAC00 <= cp < 0xD7B0:                  scripts.add("Hangul")
        elif 0x4E00 <= cp < 0xA000:                  scripts.add("CJK")
    return scripts


def _is_script_mismatch(chunk_text: str, candidate_prefix: str) -> bool:
    """判斷 LLM 產的 prefix 跟 chunk 主腳本是否不一致(避免向量飄移)。

    chunk 含非拉丁主腳本(CJK / Hangul / Arabic / Cyrillic …) 但 prefix 全 Latin → mismatch。
    Latin 容差容許各語文本內雜英數標點。

    Args:
        chunk_text: 原始 chunk。
        candidate_prefix: LLM 生的 prefix。

    Returns:
        True = mismatch(應 fallback);False = 一致或不確定。
    """
    chunk_scripts = _detect_scripts(chunk_text)
    prefix_scripts = _detect_scripts(candidate_prefix)

    # chunk 主腳本(排除 Latin)— 若 chunk 是純 Latin,prefix 是 Latin 沒問題
    chunk_main = chunk_scripts - {"Latin"}
    prefix_main = prefix_scripts - {"Latin"}

    # chunk 有非拉丁主腳本但 prefix 完全沒有 → mismatch
    return bool(chunk_main) and not prefix_main


def _safe_fallback_prefix(chunk_text: str, file_name: str) -> str:
    """LLM 失敗時的 fallback prefix(用 file_name 當 prefix,語言中性)。

    不加任何自然語言 wrapper(如 "[From file: X]"),讓 prefix 跟 chunk 語言一致。
    檔名跨語時 bge-m3 對命名類噪音較不敏感。

    Args:
        chunk_text: 原始 chunk(目前僅 logging 用)。
        file_name: 檔名,直接用為 prefix。

    Returns:
        "{file_name}\n\n{chunk_text}" 格式的 fallback string。
    """
    return f"{file_name}\n\n{chunk_text}"


class ContextGenerator:
    """使用 LLM 為 chunk 生成上下文前綴

    使用 sync OpenAI client + asyncio.to_thread() 並行呼叫，
    避免 PyInstaller 打包環境下 AsyncOpenAI 的 event loop 相容問題。
    """

    def __init__(
        self,
        llm_config,
        model: str,
        max_context_length: int = 150,
        max_concurrent: int = 50,
        max_doc_chars: int = 60000,
        max_tokens: int = 1024,
        reasoning_effort: Optional[str] = None,
    ):
        self._llm_config = llm_config
        self._model = model
        self._max_context_length = max_context_length
        self._max_concurrent = max_concurrent
        self._max_doc_chars = max_doc_chars
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        logger.info(
            f"ContextGenerator initialized (model={model}, max_length={max_context_length}, "
            f"max_concurrent={max_concurrent}, max_doc_chars={max_doc_chars}, "
            f"max_tokens={max_tokens}, reasoning_effort={reasoning_effort})"
        )

    @classmethod
    def from_config(cls, rag_config) -> Optional["ContextGenerator"]:
        """從 RAG config 建立 ContextGenerator

        Returns:
            ContextGenerator instance, or None if not configured/enabled
        """
        cr_config = getattr(rag_config, 'contextual_retrieval', None)
        if not cr_config or not cr_config.enabled:
            logger.info("Contextual Retrieval is disabled")
            return None

        llm_config = getattr(rag_config, 'llm', None)
        if not llm_config:
            logger.warning("Contextual Retrieval enabled but no LLM config found")
            return None

        try:
            model = llm_config.azure_deployment or llm_config.model

            return cls(
                llm_config=llm_config,
                model=model,
                max_context_length=cr_config.max_context_length,
                max_concurrent=getattr(cr_config, 'max_concurrent', 50),
                max_doc_chars=getattr(cr_config, 'max_doc_chars', 60000),
                max_tokens=getattr(cr_config, 'max_tokens', 1024),
                reasoning_effort=getattr(cr_config, 'reasoning_effort', None),
            )
        except Exception as e:
            logger.error(f"Failed to create ContextGenerator: {e}")
            return None

    @staticmethod
    def _create_sync_client(llm_config):
        """建立 sync OpenAI client（支援 Azure / OpenAI / vLLM / Ollama）"""
        from openai import OpenAI

        provider = llm_config.provider.lower()

        if provider == "azure":
            from openai import AzureOpenAI

            api_key = llm_config.api_key or os.environ.get("AZURE_OPENAI_API_KEY")
            if not api_key:
                raise ValueError("Azure LLM api_key is required")

            azure_endpoint = llm_config.base_url or os.environ.get("AZURE_OPENAI_ENDPOINT")
            if not azure_endpoint:
                raise ValueError("Azure endpoint (base_url) is required")

            return AzureOpenAI(
                api_key=api_key,
                api_version=llm_config.api_version or "2024-12-01-preview",
                azure_endpoint=azure_endpoint,
            )

        elif provider in ("vllm", "ollama"):
            base_url = llm_config.base_url
            if not base_url:
                raise ValueError(f"{provider} requires base_url (e.g., http://localhost:8000/v1)")
            api_key = llm_config.api_key or "not-needed"

            return OpenAI(api_key=api_key, base_url=base_url)

        elif provider == "openai":
            api_key = llm_config.api_key or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OpenAI api_key is required")
            return OpenAI(api_key=api_key)

        else:
            raise ValueError(
                f"Unsupported LLM provider: '{provider}'. "
                f"Supported: azure, openai, vllm, ollama"
            )

    def _call_llm_sync(self, prompt: str, client) -> str:
        """同步呼叫 LLM（由 asyncio.to_thread 在 thread pool 中執行）"""
        kwargs = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self._max_tokens,
            "temperature": 0,
        }
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort

        response = client.chat.completions.create(**kwargs)
        msg = response.choices[0].message
        # 先讀 content，若為空則 fallback 到 reasoning_content（reasoning model）
        raw_content = msg.content
        if not raw_content:
            raw_content = getattr(msg, 'reasoning_content', None)
        return raw_content

    async def _generate_one(
        self,
        chunk_text: str,
        full_document: str,
        file_name: str,
        client,
        semaphore: asyncio.Semaphore,
        should_abort: Optional[Callable[[], bool]] = None,
    ) -> str:
        """為單個 chunk 生成帶有上下文前綴的文字

        should_abort 成立時直接回傳原 chunk_text 跳過 LLM — abort 後整批結果
        會被 indexer 丟棄(raise IndexingAbortedError),這裡只求快速讓
        gather 收尾,不浪費 LLM 呼叫。
        """
        try:
            if should_abort and should_abort():
                return chunk_text

            doc_text = full_document[:self._max_doc_chars]
            if len(full_document) > self._max_doc_chars:
                doc_text += "\n...(文件過長，已截斷)"

            prompt = _CONTEXT_PROMPT.format(
                max_length=self._max_context_length,
                file_name=file_name,
                document_text=doc_text,
                chunk_text=chunk_text,
            )

            async with semaphore:
                # 排在 semaphore 後面的 chunk 可能等了很久,取得執行權後再確認一次
                if should_abort and should_abort():
                    return chunk_text
                raw_content = await asyncio.to_thread(self._call_llm_sync, prompt, client)

            if not raw_content:
                logger.warning(
                    f"LLM returned empty content for chunk in '{file_name}',"
                    f" using safe fallback prefix"
                )
                return _safe_fallback_prefix(chunk_text, file_name)

            context = raw_content.strip()

            # 通用 script 不一致偵測 — 不寫死任何特定語言
            # bge-m3 embed 時 prefix+chunk 主腳本錯位會讓向量飄移,該 chunk 在
            # 對應語言 query 下命中率劇降。寧可用 fallback,不要錯位 prefix。
            if _is_script_mismatch(chunk_text, context):
                logger.warning(
                    f"LLM produced script-mismatched prefix for chunk in '{file_name}',"
                    f" discarding. context_preview={context[:60]!r}"
                )
                return _safe_fallback_prefix(chunk_text, file_name)

            if len(context) > self._max_context_length:
                context = context[:self._max_context_length]

            return f"{context}\n\n{chunk_text}"

        except Exception as e:
            logger.warning(f"Context generation failed for chunk in '{file_name}': {e}")
            return _safe_fallback_prefix(chunk_text, file_name)

    async def generate_batch(
        self,
        chunks: List[str],
        full_document: str,
        file_name: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
        should_abort: Optional[Callable[[], bool]] = None,
    ) -> List[str]:
        """批量為 chunks 生成 contextual prefix(並行 LLM 呼叫)。

        sync OpenAI client + asyncio.to_thread 並行;asyncio.Semaphore 限流。

        Args:
            chunks: 要產 prefix 的 chunk text list。
            full_document: 完整文件內容(LLM 需要這個推理 chunk 上下文)。
            file_name: 檔名 tag(logging + fallback 用)。
            on_progress: ``(done, total)`` 進度回呼;每完成 10 個 chunk 或最後
                一個呼叫一次(節流,讓 job 狀態能顯示「切到多少 ?/?」)。None 靜默。
            should_abort: 回傳 True 時剩餘 chunk 跳過 LLM 快速收尾(檔案途中
                被刪的 cooperative cancellation)。caller 保證此 callable 不 raise;
                中止判定與丟棄結果由 indexer 負責,本方法照常回傳。

        Returns:
            跟 chunks 等長的 list;每個元素是 `prefix\n\nchunk_text` 已合成字串。
        """
        total = len(chunks)

        # 建立 sync client（thread-safe，可跨 thread 共用）。每檔一個 client,
        # 用完必關 — long-running server 不關的話 socket/fd 隨檔案數線性洩漏
        client = self._create_sync_client(self._llm_config)
        semaphore = asyncio.Semaphore(self._max_concurrent)

        # gather 完成順序 ≠ 提交順序,進度要用完成計數,不能用 chunk index。
        # counter 只在 event loop 內遞增(await 之後),單執行緒安全免鎖。
        done_count = 0

        def _on_one_done() -> None:
            nonlocal done_count
            done_count += 1
            if done_count % 10 == 0 or done_count == total:
                logger.info(f"Context generation progress: {done_count}/{total} chunks")
                if on_progress is not None:
                    try:
                        on_progress(done_count, total)
                    except Exception as e:
                        logger.debug(f"context-gen progress callback failed (ignored): {e}")

        # abort 監看:檔案被刪時不只停「後續」呼叫(_generate_one 的檢查點),
        # 還立刻 close client 把「飛行中」的請求連線切斷 — vLLM 偵測到 client
        # disconnect 會中止該請求的生成,GPU 不再為註定被丟棄的結果燒。
        # (單檔 job 走 task.cancel() 本來就會斷;這裡補的是多檔 job 用
        # per-file abort flag 的路徑,原本飛行中 ≤max_concurrent 個請求會跑完。)
        _abort_stop = asyncio.Event()

        async def _abort_watcher():
            while not _abort_stop.is_set():
                if should_abort and should_abort():
                    logger.info(
                        f"Abort detected for '{file_name}' — closing LLM client "
                        f"to cut in-flight generations"
                    )
                    try:
                        client.close()
                    except Exception:
                        pass
                    return
                try:
                    await asyncio.wait_for(_abort_stop.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

        watcher = asyncio.create_task(_abort_watcher()) if should_abort else None

        try:
            tasks = []
            for chunk_text in chunks:
                tasks.append(self._generate_with_progress(
                    chunk_text, full_document, file_name,
                    client, semaphore, _on_one_done, should_abort,
                ))

            results = await asyncio.gather(*tasks)
        finally:
            _abort_stop.set()
            if watcher is not None:
                try:
                    await watcher
                except Exception:
                    pass
            try:
                client.close()
            except Exception as e:
                logger.debug(f"LLM client close failed (ignored): {e}")

        logger.info(f"Context generation completed: {total} chunks for {file_name}")
        return results

    async def _generate_with_progress(
        self,
        chunk_text: str,
        full_document: str,
        file_name: str,
        client,
        semaphore: asyncio.Semaphore,
        on_done: Callable[[], None],
        should_abort: Optional[Callable[[], bool]] = None,
    ) -> str:
        """生成一個 chunk 的 context 並回報完成"""
        result = await self._generate_one(
            chunk_text, full_document, file_name, client, semaphore, should_abort
        )
        on_done()
        return result
