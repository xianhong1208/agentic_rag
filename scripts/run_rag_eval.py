
"""BL-01 — RAG 檢索評測跑分:索引 golden 文件集 → 逐 QA 檢索 → recall@k / MRR。

用法:
    uv run --no-sync python scripts/run_rag_eval.py                # 索引+查詢+出分
    uv run --no-sync python scripts/run_rag_eval.py --keep         # 保留評測 folder(除錯)
    uv run --no-sync python scripts/run_rag_eval.py --baseline evals/baselines/rag_xxx.json

素材(見 evals/README.md):
    evals/rag/documents/*                # 代表性文件集(白名單內任何格式)
    evals/rag/golden_qa.yaml             # QA 集(question / expected_files)

前置:config 指向的 PostgreSQL 與 embedding 服務都要可達。
評測 folder 用獨立 token 'rag-eval',跑完自動清除(--keep 保留)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import date
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DOCS_DIR = REPO / "evals" / "rag" / "documents"
QA_FILE = REPO / "evals" / "rag" / "golden_qa.yaml"
BASELINE_DIR = REPO / "evals" / "baselines"
EVAL_TOKEN = "rag-eval"
TOP_K = 10


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留評測 folder")
    ap.add_argument("--baseline", help="與既有基線 JSON 比較")
    ap.add_argument("--config", default="config/config.yaml")
    args = ap.parse_args()

    docs = [f for f in sorted(DOCS_DIR.iterdir()) if f.is_file()] if DOCS_DIR.is_dir() else []
    qa_items = yaml.safe_load(QA_FILE.read_text(encoding="utf-8")) if QA_FILE.is_file() else None
    qa_items = [q for q in (qa_items or []) if isinstance(q, dict) and q.get("question")]
    if not docs or not qa_items:
        print("❌ 無評測素材。請放置:")
        print(f"   {DOCS_DIR.relative_to(REPO)}/ — 代表性文件集")
        print(f"   {QA_FILE.relative_to(REPO)} — QA 集(格式見檔內註釋)")
        return 2

    from src.config.config_manager import Config
    Config.set_config(args.config)

    # 前置探測:embedding 服務(索引/查詢都要),fail-fast 給明確訊息
    from src.adapter.rag_context import RAGContext
    try:
        ctx = RAGContext.from_config()
    except Exception as e:
        print(f"❌ RAGContext 初始化失敗(embedding/DB 服務未就緒?):{e}")
        return 2

    from db.folderdb import FolderDB
    from db.db import get_engine
    from src.domain.rag.vector_store_manager import VectorStoreManager

    folder = FolderDB.create(
        name=f"eval-{date.today().isoformat()}-{uuid.uuid4().hex[:6]}",
        description="RAG eval run (auto-created)", user_token=EVAL_TOKEN,
    )
    print(f"評測 folder: {folder.name} (id={folder.id})")
    store = ctx.vector_store_manager.get_or_create(
        folder_id=folder.id, vector_table_uuid=str(folder.vector_table_uuid))

    try:
        # ---- 索引 ----
        t0 = time.perf_counter()
        for f in docs:
            doc = ctx.indexer.load_document_from_file(
                file_path=str(f), file_id=str(uuid.uuid4()), file_name=f.name)
            # 檢索命中判定用 file_name — 覆蓋 metadata 保證一致
            doc.metadata["file_name"] = f.name
            r = await ctx.indexer.index_document(doc, store)
            print(f"  索引 {f.name}: {r['leaves']} leaves / {r['parents']} parents")
        index_s = time.perf_counter() - t0

        # ---- 查詢 ----
        from src.domain.rag.auto_merging import AutoMergingRetriever
        from evals.metrics import mrr, recall_at_k
        retr_cfg = Config.get_config_model().rag.retrieval
        retriever = AutoMergingRetriever(
            vector_store=store, reranker=ctx.reranker,
            merge_threshold=ctx.merge_threshold if ctx.auto_merging_enabled else 1.1,
            expand_context_neighbors=ctx.expand_neighbors,
            sparse_top_k=retr_cfg.default_sparse_top_k,
            hybrid_alpha=retr_cfg.default_hybrid_alpha,
        )
        rows = []
        for qa in qa_items:
            results = await retriever.aquery(
                query_text=qa["question"], top_k=TOP_K, similarity_cutoff=0.0)
            retrieved_files = []
            for res in results:  # 保序去重
                if res.file_name not in retrieved_files:
                    retrieved_files.append(res.file_name)
            expected = qa.get("expected_files", [])
            rows.append({
                "id": qa.get("id", qa["question"][:20]),
                "recall_at_5": recall_at_k(retrieved_files, expected, 5),
                "recall_at_10": recall_at_k(retrieved_files, expected, 10),
                "mrr": round(mrr(retrieved_files, expected), 4),
                "retrieved_top5": retrieved_files[:5],
            })
            print(f"  {rows[-1]['id']}: R@5={rows[-1]['recall_at_5']:.2f} MRR={rows[-1]['mrr']:.2f}")

        summary = {
            "date": date.today().isoformat(),
            "embedding_model": ctx.model_name,
            "n_documents": len(docs), "n_queries": len(rows),
            "index_seconds": round(index_s, 1),
            "avg_recall_at_5": round(sum(r["recall_at_5"] for r in rows) / len(rows), 4),
            "avg_recall_at_10": round(sum(r["recall_at_10"] for r in rows) / len(rows), 4),
            "avg_mrr": round(sum(r["mrr"] for r in rows) / len(rows), 4),
            "queries": rows,
        }
        out = BASELINE_DIR / f"rag_{date.today().isoformat()}.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n== avg R@5 {summary['avg_recall_at_5']:.2%} | R@10 "
              f"{summary['avg_recall_at_10']:.2%} | MRR {summary['avg_mrr']:.3f} ==")
        print(f"基線寫入:{out.relative_to(REPO)}")

        if args.baseline:
            base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
            print(f"vs {base['date']}(emb={base.get('embedding_model')}):"
                  f"R@5 {base['avg_recall_at_5']:.2%} → {summary['avg_recall_at_5']:.2%},"
                  f"MRR {base['avg_mrr']:.3f} → {summary['avg_mrr']:.3f}")
        return 0
    finally:
        if args.keep:
            print(f"--keep:保留 folder {folder.id} 與其向量表")
        else:
            ctx.vector_store_manager.drop_table(folder.id, str(folder.vector_table_uuid))
            FolderDB.delete(id=folder.id)
            print("評測 folder 已清除")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
