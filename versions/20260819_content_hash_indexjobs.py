"""Adopt runtime-ensured schema into alembic: content_hash columns + IndexJobs table

M13: 這兩塊 schema 原本只由 runtime 自愈補上(fileindexdb.ensure_content_hash_columns
的 ALTER、indexjobdb.ensure_table 的 CREATE),不在 alembic 鏈裡 —— fresh
alembic-only 部署會缺,與 runtime-patched 部署漂移。此 migration 把它們收編:

1. Files.content_hash / FileIndices.content_hash(VARCHAR(64) NULL)
2. IndexJobs 表 + 三個索引(對齊 db/db.py 的 IndexJob ORM)

全部用 IF NOT EXISTS 冪等 SQL:對「runtime 已補過」的現役庫重跑也安全(no-op)。
runtime ensure_* 保留為 fallback,但 canonical 從此是這裡。

Revision ID: 20260819cafe01
Revises: 20250127abcdef
Create Date: 2026-08-19

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '20260819cafe01'
down_revision: Union[str, None] = '20250127abcdef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """content_hash 欄位 + IndexJobs 表(冪等,runtime-patched 庫重跑為 no-op)"""

    # 1. content_hash — 對齊 db.py File.content_hash / FileIndex.content_hash
    op.execute('ALTER TABLE "Files" ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)')
    op.execute('ALTER TABLE "FileIndices" ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)')

    # 2. IndexJobs — 對齊 db.py IndexJob ORM(indexjobdb.ensure_table 原本 runtime 建的)
    #    timestamps 為 ISO 字串(對齊 IndexJobState 序列化),非 timestamp 型別 — 刻意
    op.execute('''
        CREATE TABLE IF NOT EXISTS "IndexJobs" (
            job_id UUID PRIMARY KEY,
            folder_id INTEGER NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            total_files INTEGER DEFAULT 0,
            processed_files INTEGER DEFAULT 0,
            current_index INTEGER DEFAULT 0,
            current_file_id VARCHAR(255),
            current_file_name VARCHAR(255),
            last_file_status VARCHAR(64),
            last_message TEXT,
            message TEXT,
            error TEXT,
            skip_existing BOOLEAN DEFAULT true,
            started_at VARCHAR(64),
            completed_at VARCHAR(64),
            last_updated_at VARCHAR(64),
            result_summary JSONB,
            scope_file_ids JSONB NOT NULL DEFAULT '[]',
            file_timings JSONB NOT NULL DEFAULT '[]'
        )
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS idx_indexjobs_folder_id ON "IndexJobs" (folder_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_indexjobs_status ON "IndexJobs" (status)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_indexjobs_last_updated ON "IndexJobs" (last_updated_at)')


def downgrade() -> None:
    """回退:移除 content_hash 欄位與 IndexJobs 表"""
    op.execute('DROP TABLE IF EXISTS "IndexJobs"')
    op.execute('ALTER TABLE "FileIndices" DROP COLUMN IF EXISTS content_hash')
    op.execute('ALTER TABLE "Files" DROP COLUMN IF EXISTS content_hash')
