
"""文件記錄數據庫模型

提供文件記錄的數據庫表定義和相關的數據庫操作，支持階層管理 (Folder -> File)。
"""

import hashlib
import os
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import re
import unicodedata

from .db import File
from db.db import Session as DBSession
from .baseDB import BaseDB
from src.log import get_db_logger

# 獲取日誌實例
log = get_db_logger()


class ToolError(Exception):
    """工具相關錯誤"""
    pass


class FileDB(BaseDB):
    """文件記錄數據庫操作類
    
    提供文件上傳、驗證、存儲等功能
    """
    
    # 常量定義
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    ALLOWED_EXTENSIONS = {
        # 純文字 (直讀;text_io.read_text_robust 自動處理 UTF-8/16/Big5 等編碼)
        'txt', 'text', 'json', 'csv',
        'yaml', 'yml', 'xml', 'conf', 'log',
        # Office Open XML(含範本/巨集變體;走 Docling 結構化解析)
        'pdf', 'docx', 'dotx', 'docm', 'dotm',
        'pptx', 'ppsx', 'pptm', 'potm', 'ppsm',  # potx 實測 docling 打不開,不收
        'xlsx', 'xlsm',
        # 格式 v3(docling 2.124 官網全對標):OpenDocument(含範本)/ 電子書 /
        # LaTeX / MIME 郵件 / 字幕;程式化對標測試見 test_upload_formats
        'odt', 'ods', 'odp',  # 範本變體 ott/ots/otp 實測 docling 打不開,不收
        'epub', 'tex', 'latex', 'eml', 'vtt', 'qmd', 'rmd',
        # Legacy Office (docling 2.119+ 經 LibreOffice 轉檔解析。
        # 2026-08 前曾因無解析器移除 'doc'(a64641d);現已有真解析器且品質
        # 實測通過。⚠️ 部署前提:映像/機器裝 libreoffice-writer,缺了索引時
        # 明確報錯,不會靜默亂碼)
        'doc', 'dot', 'xls', 'xlt', 'ppt', 'pot', 'pps',
        # Outlook 郵件 (docling 2.119+,python-oxmsg 純 Python,零系統依賴)
        'msg',
        # 標記語言
        'md', 'html', 'htm', 'xhtml', 'adoc', 'asciidoc', 'asc',
        # 圖片 (Docling + RapidOcr)
        'png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp', 'webp',
        # 音訊 (AsrProvider:本地 docling whisper 或雲端;對齊 docling 官方 6 種)
        'wav', 'mp3', 'm4a', 'aac', 'ogg', 'flac',
    }
    
    @classmethod
    def get_orm_class(cls) -> type:
        """獲取 ORM 類"""
        return File
    
    @classmethod
    def get_log(cls):
        """獲取日誌實例"""
        return log

    @classmethod
    def get_by_ids(cls, file_ids: List[str]) -> Dict[str, "File"]:
        """批量獲取文件記錄,避免 N+1 查詢。

        Args:
            file_ids: vector store metadata 來的 str list;內部轉成 UUID 過濾,
                格式不合的 ID 會 skip + log warning。

        Returns:
            ``{str(uuid): File}`` dict;沒命中的 file_id 不在 dict 內。
        """
        if not file_ids:
            return {}

        # str → uuid.UUID，跳過格式不合法的 ID
        uuid_ids = []
        for fid in file_ids:
            try:
                uuid_ids.append(uuid.UUID(fid) if not isinstance(fid, uuid.UUID) else fid)
            except (ValueError, AttributeError):
                log.warning(f"Invalid UUID format, skipping: {fid}")
        if not uuid_ids:
            return {}

        unique_ids = list(set(uuid_ids))

        with DBSession() as session:
            rows = (
                session.query(cls.get_orm_class())
                .filter(cls.get_orm_class().id.in_(unique_ids))
                .all()
            )

        # key 用 str，讓 caller 可以直接用 metadata 中的 string file_id 查找
        return {str(row.id): row for row in rows}


    @classmethod
    def delete_by_folder_id(
        cls, 
        folder_id: int
        ) -> int:
        """Delete all files in a folder by folder ID
        
        Args:
            folder_id: The ID of the folder whose files should be deleted
            
        Returns:
            Number of files deleted
        """
        try:
            with DBSession() as session:
                # Delete all files in the folder
                deleted_count = session.query(cls.get_orm_class()).filter_by(folder_id=folder_id).delete(synchronize_session=False)
                session.commit()
                cls.get_log().info(f"Successfully deleted {deleted_count} files from folder {folder_id}")
                return deleted_count
        except Exception as e:
            cls.get_log().error(f"Failed to delete files from folder {folder_id}: {e}")
            raise
    
    @classmethod
    def _validate_file_content(cls, file_content: bytes, file_name: str) -> Dict[str, Any]:
        """驗證文件內容
        
        Args:
            file_content: 文件二進制內容
            file_name: 文件名
            
        Returns:
            包含文件信息的字典
            
        Raises:
            ToolError: 文件驗證失敗時抛出
        """
        # 檢查文件大小
        file_size = len(file_content)
        if file_size > cls.MAX_FILE_SIZE:
            max_size_mb = cls.MAX_FILE_SIZE / (1024 * 1024)
            raise ValueError(f"文件大小超過限制 ({max_size_mb:.1f}MB)")

        # 檢查文件擴展名
        ext = Path(file_name).suffix.lower().lstrip('.')
        if ext not in cls.ALLOWED_EXTENSIONS:
            raise ValueError(f"Not supported file type: {ext}")
        
        # 獲取 MIME 類型
        mime_type = mimetypes.guess_type(file_name)[0]

        # sha256 content hash for idempotent re-indexing. Computed once
        # at upload so re-index can skip when File.content_hash == FileIndex.content_hash.
        content_hash = hashlib.sha256(file_content).hexdigest()

        return {
            'file_size': file_size,
            'mime_type': mime_type,
            'extension': ext,
            'content_hash': content_hash,
        }
