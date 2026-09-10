
"""資料夾數據庫操作模組

提供資料夾的數據庫操作功能，包括創建、查詢、更新和刪除資料夾。
"""

from .db import Folder
from .baseDB import BaseDB
from src.log import get_db_logger

# 獲取日誌實例
log = get_db_logger()


class FolderDB(BaseDB):
    """資料夾數據庫操作類
    
    提供資料夾的 CRUD 操作
    """
    
    @classmethod
    def get_orm_class(cls) -> type:
        """獲取 ORM 類"""
        return Folder
    
    @classmethod
    def get_log(cls):
        """獲取日誌實例"""
        return log