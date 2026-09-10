
"""RAG 檢索評測 harness — 把「感覺準不準」變成可比較的指標數據。

用法:
    uv run --no-sync python scripts/rag_eval.py --folder <名稱或ID> --n 20

流程:
    1) generate:從該 folder 已索引的 leaf chunk 隨機抽 N 段,用 config 的 LLM
       各生成一個「答案就在這段裡」的繁中問題 → 標註集(gold = 該 chunk node_id)。
       存到 reports/eval_set_<folder>.jsonl,下次帶 --eval-set 重用(免重生)。
    2) eval:每題分別用 vector / hybrid / hybrid+rerank 三種檢索,算出 gold chunk
       的名次,彙總 Recall@k、MRR、nDCG@k,印對照表 + 寫 reports/rag_eval_<folder>.json。

指標(單一相關 chunk 的檢索評測):
    Recall@k = gold 是否落在 top-k(命中率)
    MRR      = 1 / gold 名次(名次越前越高)
    nDCG@k   = 1 / log2(gold名次+1),gold 不在 top-k 記 0(排序品質,懲罰排後面)

這是「先量測再優化」的基準:改 BM25 斷詞 / rerank 參數後,重跑同一標註集比分數。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve_folder(folder_arg: str):
    from db.folderdb import FolderDB
    if folder_arg.isdigit():
        rows = FolderDB.get(id=int(folder_arg))
    else:
        rows = FolderDB.get(name=folder_arg)
    if not rows:
        raise SystemExit(f"folder not found: {folder_arg}")
    return rows[0]


def _sample_chunks(folder, n: int):
    """從 folder 的 pgvector 物理表隨機抽 n 段 leaf chunk(node_id, text)。"""
    from sqlalchemy import text
    from db.db import get_engine
    from src.domain.rag.vector_store_manager import VectorStoreManager
    table = VectorStoreManager.physical_table_name(folder.id, folder.vector_table_uuid)
    with get_engine().connect() as c:
        rows = c.execute(text(
            f"SELECT node_id, text FROM \"{table}\" "
            f"WHERE COALESCE(metadata_->>'node_role','leaf')='leaf' "
            f"AND length(text) > 80 ORDER BY random() LIMIT :n"), {"n": n}).fetchall()
    return [(r[0], r[1]) for r in rows]


def _gen_question(client, model: str, chunk_text: str) -> str:
    prompt = (
        "以下是一份文件的片段。請生成一個使用者可能會問、且答案明確就在這段文字裡的"
        "繁體中文問題。問題要具體(可含專有名詞),不要用「這段文字」這種指涉詞。"
        "只輸出問題本身,不要任何前綴。\n\n片段:\n" + chunk_text[:1500] + "\n\n問題:")
    # gpt-oss 等 reasoning 模型會先吃 reasoning token,max_tokens 太小會導致
    # content 為 None(reasoning 未留額度給答案)→ 給足 1024。
    r = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=1024, temperature=0.3)
    return (r.choices[0].message.content or "").strip().strip('"').replace("\n", " ")


def generate_eval_set(folder, n: int, out_path: str):
    from src.config.config_manager import Config
    from src.domain.rag.context_generator import ContextGenerator
    llm = Config.get_config_model().rag.llm
    client = ContextGenerator._create_sync_client(llm)
    model = getattr(llm, "azure_deployment", None) or llm.model
    samples = _sample_chunks(folder, n)
    if not samples:
        raise SystemExit("no indexed leaf chunks found — index some files first")
    items = []
    for i, (nid, txt) in enumerate(samples):
        try:
            q = _gen_question(client, model, txt)
            if q:
                items.append({"query": q, "gold_node_id": nid})
                print(f"  [{i+1}/{len(samples)}] {q[:60]}")
        except Exception as e:
            print(f"  [{i+1}] gen failed: {e}")
    try:
        client.close()
    except Exception:
        pass
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"→ wrote {len(items)} eval items to {out_path}")
    return items


async def _retr(index, query: str, vmode: str, k: int):
    from llama_index.core.retrievers import VectorIndexRetriever
    kwargs = {"sparse_top_k": max(k, 20)} if vmode in ("hybrid", "sparse") else {}
    r = VectorIndexRetriever(index=index, similarity_top_k=k,
                             vector_store_query_mode=vmode, vector_store_kwargs=kwargs)
    nodes = await r.aretrieve(query)
    return [n for n in nodes if n.node.metadata.get("node_role", "leaf") == "leaf"]


def _rrf(lists, k, rrf_k=60):
    scores, node_map = {}, {}
    for lst in lists:
        for rank, n in enumerate(lst):
            nid = n.node.node_id
            scores[nid] = scores.get(nid, 0.0) + 1.0 / (rrf_k + rank + 1)
            node_map.setdefault(nid, n)
    return sorted(node_map.values(), key=lambda n: scores[n.node.node_id], reverse=True)[:k]


async def _rank_of_gold(index, reranker, query: str, gold: str, mode: str, k: int):
    """回 gold node_id 在該 mode top-k 的名次(1-based),不在則 None。

    mode:vector(dense)/ hybrid(llama_index concat)/ rrf(dense+sparse RRF)/
         rerank(RRF 候選再 cross-encoder rerank — 對齊 production aquery)。
    """
    retrieve_k = k * 3 if mode == "rerank" else k
    if mode == "vector":
        nodes = (await _retr(index, query, "default", k))[:k]
    elif mode == "hybrid":
        nodes = (await _retr(index, query, "hybrid", k))[:k]
    elif mode in ("rrf", "rerank"):
        dense = await _retr(index, query, "default", retrieve_k)
        sparse = await _retr(index, query, "sparse", retrieve_k)
        nodes = _rrf([dense, sparse], retrieve_k)
        if mode == "rerank" and reranker and nodes:
            nodes = await reranker.arerank(query, nodes, top_n=k)
        else:
            nodes = nodes[:k]
    else:
        nodes = []
    for i, n in enumerate(nodes):
        if n.node.node_id == gold:
            return i + 1
    return None


async def evaluate(folder, items, k: int, progress=None) -> dict:
    """跑三路檢索評測,回報告 dict(不印、不寫檔 — 交給呼叫端)。

    progress(done, total) 選填,供 UI 回報進度。
    """
    from llama_index.core import VectorStoreIndex
    from src.adapter.rag import get_rag_adapter
    ctx = get_rag_adapter()._query_svc._ctx
    vs = ctx.get_vector_store(folder.id, folder.user_token)
    index = VectorStoreIndex.from_vector_store(vs)
    reranker = ctx.reranker
    modes = ["vector", "hybrid", "rrf"] + (["rerank"] if reranker else [])

    agg = {m: {"recall": 0, "mrr": 0.0, "ndcg": 0.0} for m in modes}
    per_item = []
    for j, it in enumerate(items):
        row = {"query": it["query"], "ranks": {}}
        for m in modes:
            rank = await _rank_of_gold(index, reranker, it["query"], it["gold_node_id"], m, k)
            row["ranks"][m] = rank
            if rank is not None and rank <= k:
                agg[m]["recall"] += 1
                agg[m]["mrr"] += 1.0 / rank
                agg[m]["ndcg"] += 1.0 / math.log2(rank + 1)
        per_item.append(row)
        if progress:
            progress(j + 1, len(items))

    n = len(items) or 1
    summary = {m: {"recall@%d" % k: round(agg[m]["recall"] / n, 3),
                   "mrr": round(agg[m]["mrr"] / n, 3),
                   "ndcg@%d" % k: round(agg[m]["ndcg"] / n, 3)} for m in modes}
    return {"folder": folder.name, "n": len(items), "k": k,
            "modes": modes, "summary": summary, "per_item": per_item}


def _print_report(rep: dict):
    k = rep["k"]
    print("\n" + "=" * 56)
    print(f"RAG retrieval eval — folder='{rep['folder']}'  n={rep['n']}  k={k}")
    print("=" * 56)
    print(f"{'mode':<10} {'Recall@%d'%k:>10} {'MRR':>8} {'nDCG@%d'%k:>9}")
    for m in rep["modes"]:
        s = rep["summary"][m]
        print(f"{m:<10} {s['recall@%d'%k]:>10} {s['mrr']:>8} {s['ndcg@%d'%k]:>9}")
    print("=" * 56)


def run_eval(folder_name: str, n: int = 15, k: int = 10,
             regenerate: bool = False, progress=None) -> dict:
    """一站式:載入/生成標註集 → 評測 → 寫報告 → 回 dict(CLI 與 API 共用)。

    regenerate=True 強制重生標註集(reindex 後 node_id 變,舊集失效時用)。
    """
    folder = _resolve_folder(folder_name)
    slug = str(folder.name).replace("/", "_")
    eval_path = f"reports/eval_set_{slug}.jsonl"
    if regenerate or not os.path.exists(eval_path):
        items = generate_eval_set(folder, n, eval_path)
    else:
        with open(eval_path, encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]
    rep = asyncio.run(evaluate(folder, items, k, progress=progress))
    import datetime
    rep["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    out_path = f"reports/rag_eval_{slug}.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    return rep


async def run_eval_async(folder_name: str, n: int = 15, k: int = 10,
                         regenerate: bool = False, progress=None) -> dict:
    """run_eval 的 async 版 — **在呼叫端的 event loop 上**跑 evaluate。

    給伺服器用:必須跑在主 loop(與快取的 PGVectorStore async engine 同 loop),
    否則 asyncpg 會噴『attached to a different loop』。同步阻塞的問題生成丟
    executor,不佔 loop。CLI 仍走 run_eval(asyncio.run 自帶 loop,獨立進程無此問題)。
    """
    import datetime
    folder = _resolve_folder(folder_name)
    slug = str(folder.name).replace("/", "_")
    eval_path = f"reports/eval_set_{slug}.jsonl"
    loop = asyncio.get_event_loop()
    if regenerate or not os.path.exists(eval_path):
        items = await loop.run_in_executor(None, generate_eval_set, folder, n, eval_path)
    else:
        with open(eval_path, encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]
    rep = await evaluate(folder, items, k, progress=progress)
    rep["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    out_path = f"reports/rag_eval_{slug}.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    return rep


def main():
    ap = argparse.ArgumentParser(description="RAG retrieval eval harness")
    ap.add_argument("--folder", required=True, help="folder name or id")
    ap.add_argument("--n", type=int, default=20, help="number of synthetic eval questions to generate")
    ap.add_argument("--k", type=int, default=10, help="top-k cutoff for metrics")
    ap.add_argument("--regenerate", action="store_true",
                    help="force-regenerate the eval set (use after reindex — node_ids change)")
    ap.add_argument("--config", default="config/config.yaml")
    args = ap.parse_args()

    from src.config.config_manager import Config
    Config.set_config(args.config)
    from db.runtime_settings_db import RuntimeSettingsDB
    RuntimeSettingsDB.ensure_table()

    rep = run_eval(args.folder, n=args.n, k=args.k, regenerate=args.regenerate,
                   progress=lambda d, t: print(f"  [{d}/{t}]", end="\r", flush=True))
    _print_report(rep)
    print(f"→ wrote report to reports/rag_eval_{str(rep['folder']).replace('/', '_')}.json")


if __name__ == "__main__":
    main()
