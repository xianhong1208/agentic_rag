
"""資料夾適配器模組

提供資料夾的 CRUD 功能，包括創建、查詢、更新和刪除資料夾。
支持資料夾的元數據管理和檔案統計功能。
支持動態註冊/移除 MCP tools。
"""

from typing import Optional

from db.folderdb import FolderDB
from db.filedb import FileDB
from db.db import get_engine
from sqlalchemy import text
from sqlalchemy.exc import NoResultFound
from src.log import get_adapter_logger, log_op, log_err, log_warn, mask_token
from src.adapter.model import FolderConfigData
from src.domain.rag.vector_store_manager import VectorStoreManager  # M5: 物理表刪除收斂於此
from src.storage.file_storage import FileStorage
# MCP 工具註冊:從前一版 flat RAG 的 rag_tools 換成 agentic_tools。
# 兩者函數簽名相容(folder_name, description, user_token),但 agentic_tools 註冊的是
# 單一工具含 mode 參數(search/list/read),取代前一版 flat RAG 的純 search 工具。
# M6: 不再直接 import fastmcp 交付層(舊環:adapter/folder ↔ agentic_tools)。
# MCP tool 掛/卸走 folder_events hooks,由 app.py 啟動時 wiring。
from src.adapter.folder_events import (
    notify_folder_created,
    notify_folder_deleted,
    notify_folder_renamed,
)


# 獲取日誌實例
logger = get_adapter_logger()


class FolderAdapter:
    @staticmethod
    def create_folder(
        name: str,
        user_token: str,
        description: Optional[str] = None
    ) -> Optional[list[FolderConfigData]]:
        """創建新資料夾

        Args:
            name: 資料夾名稱
            user_token: 使用者 Token
            description: 資料夾描述

        Returns:
            包含創建結果和資料夾信息的字典
        """
        logger.info(f"Creating folder: {name} for user: {user_token[:8] if user_token else 'N/A'}...")
        try:
            # fail-fast:名稱/token 白名單先驗(路徑安全同一套規則)。
            # 修:原本 DB row 先建、storage 驗證後炸 → 422 回給呼叫端但
            # 幽靈 row 已留在 DB(且因名稱非法連刪都刪不掉)。
            from src.storage.file_storage import _validate_safe_name
            _validate_safe_name(user_token, "user_token")
            _validate_safe_name(name, "folder_name")

            folder = FolderDB.get(name=name, user_token=user_token)
            if folder:
                raise ValueError(f"Folder with name '{name}' already exists for this user.")
            folder_dict = FolderDB.create(
                user_token=user_token,
                name=name,
                description=description)
            
            FileStorage._get_folder_storage_path(user_token, name)

            logger.info(f"Successfully created folder: {folder_dict.name}")
            
            # 註冊動態 MCP tool(hooks 內部兜底:失敗只 log、不阻斷 CRUD)
            notify_folder_created(name, description, user_token)
            
            return [FolderConfigData(
                id=folder_dict.id,
                user_token=str(folder_dict.user_token) if folder_dict.user_token else None,
                name=folder_dict.name,
                description=folder_dict.description,
                file_count=folder_dict.file_count,
                total_size=folder_dict.total_size,
                created_at=folder_dict.created_at,
                updated_at=folder_dict.updated_at,
            )]
        except Exception as e:
            logger.error(f"Failed to create folder {name}: {e}")
            raise

    @staticmethod
    async def get_folder(user_token: str, **kwargs) -> Optional[list[FolderConfigData]]:
        """查詢資料夾

        Args:
            user_token: 使用者 Token (必填)
            **kwargs: 其他查詢條件（如 folder_id, name 等）

        Returns:
            包含資料夾信息的字典
        """
        logger.info(f"Querying folder with parameters: {kwargs}")
        try:
            # 確保查詢時必須包含 user_token
            kwargs['user_token'] = user_token
            folder_dicts = FolderDB.get(**kwargs)

            return [FolderConfigData(
                id=folder.id,
                user_token=str(folder.user_token) if folder.user_token else None,
                name=folder.name,
                description=folder.description,
                file_count=folder.file_count,
                total_size=folder.total_size,
                created_at=folder.created_at,
                updated_at=folder.updated_at,
            ) for folder in folder_dicts]
            
        except Exception as e:
            logger.error(f"Failed to query folder with filters: {e}")
            raise
        
    @staticmethod
    async def update_folder(
        folder_id: int,
        user_token: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[list[FolderConfigData]]:
        """更新資料夾名稱和描述

        Args:
            folder_id: 資料夾 ID
            user_token: 使用者 token
            name: 新的資料夾名稱（可選）
            description: 新的資料夾描述（可選）

        Returns:
            包含更新結果和資料夾信息的字典
        """
        logger.info(f"Updating folder: folder_id: {folder_id}, name: {name}, description: {description}")
        try:
            # Check if folder exists
            folder_check = FolderDB.get(id=folder_id, user_token=user_token)
            if not folder_check:
                raise NoResultFound(f"Folder id {folder_id} does not exist")
            
            old_folder = folder_check[0]
            old_name = old_folder.name
            
            # 如果 name 有改變，需要更新 storage 和檔案路徑
            if name is not None and name != old_name:
                # 1. 重新命名 storage 目錄
                if old_folder.user_token:
                    renamed = FileStorage.rename_folder(old_folder.user_token, old_name, name)
                    if renamed:
                        logger.info(f"Storage folder renamed: {old_name} -> {name}")
                    else:
                        logger.warning(f"Storage folder rename failed or not exists: {old_name}")
                
                # 2. 更新資料庫中所有檔案的 file_path
                try:
                    engine = get_engine()
                    with engine.connect() as conn:
                        # 將 file_path 中的舊 folder name 替換為新的
                        conn.execute(
                            text('''
                                UPDATE "Files" 
                                SET file_path = REPLACE(file_path, :old_path, :new_path)
                                WHERE folder_id = :folder_id
                            '''),
                            {
                                "old_path": f"storage/{user_token}/{old_name}/",
                                "new_path": f"storage/{user_token}/{name}/",
                                "folder_id": folder_id
                            }
                        )
                        conn.commit()
                        logger.info(f"Updated file paths for folder {folder_id}: {old_name} -> {name}")
                except Exception as e:
                    logger.error(f"Failed to update file paths: {e}")
            
            # 構建更新參數
            update_kwargs = {"id": folder_id, "user_token": user_token}
            if name is not None:
                update_kwargs["name"] = name
            if description is not None:
                update_kwargs["description"] = description
            
            updated_folder = FolderDB.update(**update_kwargs)
            
            logger.info(f"Successfully updated folder: {folder_id}")

            # 重新註冊 MCP tool(如果 name 或 description 改變了)。
            # hooks 的 renamed = 先卸舊再掛新;卸舊失敗仍會嘗試掛新(舊寫法同一個
            # try 會跳過掛新,工具面卡在舊狀態 —— 這裡是刻意修正)。
            if notify_folder_renamed(
                old_name, updated_folder.name,
                updated_folder.description, updated_folder.user_token,
            ):
                logger.info(f"Successfully refreshed MCP tool for folder: {updated_folder.name}")

            return [FolderConfigData(
                id=updated_folder.id,
                user_token=str(updated_folder.user_token) if updated_folder.user_token else None,
                name=updated_folder.name,
                description=updated_folder.description,
                file_count=updated_folder.file_count,
                total_size=updated_folder.total_size,
                created_at=updated_folder.created_at,
                updated_at=updated_folder.updated_at,
            )]
        
        except Exception as e:
            logger.error(f"Failed to update folder description: {e}")
            raise 

    @staticmethod
    async def delete_folder(
        folder_id: int,
        user_token: Optional[str] = None
    ) -> bool:
        """刪除資料夾

        刪除資料夾時會自動刪除其中的所有文件。

        Args:
            folder_id: 資料夾 ID

        Returns:
            包含刪除結果的字典
        """
        logger.info(f"Deleting folder: {folder_id}")

        try:
            # 獲取資料夾信息
            folder_check = FolderDB.get(id=folder_id, user_token=user_token)
            if not folder_check:
                raise NoResultFound(f"Folder id {folder_id} does not exist")
            
            folder = folder_check[0]

            # 先取消該 folder 的 in-flight indexing job — 不取消的話,
            # 下面 DROP TABLE 後 job 還在對一張不存在的表寫入
            try:
                from src.domain.rag.index_job_manager import IndexingJobManager
                job_manager = IndexingJobManager.get_instance()
                cancelled = await job_manager.cancel_jobs_for_folder(folder_id)
                if cancelled:
                    logger.info(
                        f"Cancelled {len(cancelled)} in-flight indexing job(s) "
                        f"before deleting folder {folder_id}"
                    )
            except Exception as e:
                logger.warning(f"Failed to cancel jobs for folder {folder_id}: {e}")

            # 檢查是否有文件需要刪除
            try:
                # 先查詢是否有文件
                files = FileDB.get(folder_id=folder_id)
                
                # M5: DROP 收斂進 VectorStoreManager。folder.py 是無 ctx 的 static
                # adapter、拿不到 VSM instance;刪整個 folder 故 cache 失效無所謂,
                # 用不碰 cache 的 static drop_table_by_name。
                vector_table_name = VectorStoreManager.physical_table_name(
                    folder.id, folder.vector_table_uuid)
                VectorStoreManager.drop_table_by_name(vector_table_name)

                if files:
                    # 刪除每個文件的索引記錄，然後刪除文件
                    for file in files:
                        # 先清理 FileIndex 記錄（如果有）
                        try:
                            from db.fileindexdb import FileIndexDB
                            FileIndexDB.delete_by_file(file.id)
                        except Exception as e:
                            logger.warning(f"Failed to delete FileIndex record for file {file.id}: {e}")
                        
                        # 刪除文件在文件系統中的存儲
                        FileStorage.delete_file(file.file_path)
                    
                    # 刪除數據庫中的文件記錄 - 使用批量刪除方法
                    deleted_count = FileDB.delete_by_folder_id(folder_id)          
                    logger.info(f"Successfully deleted {deleted_count} files from folder {folder_id}")
            except Exception as e:
                # 如果文件刪除失敗，記錄但嘗試繼續刪除資料夾
                logger.error(f"Failed to delete files in folder {folder_id}: {e}")
                # 不再 raise，而是繼續執行

            # 移除動態 MCP tool(在刪除資料庫記錄之前;hooks 內部兜底不阻斷)
            notify_folder_deleted(folder.name, folder.user_token)

            # 刪除資料夾在文件系統中的目錄 — best-effort:名稱非法(歷史
            # 幽靈 row)或目錄不存在時**不得**阻斷 DB 記錄刪除,否則該
            # folder 永遠刪不掉(storage 驗證 ValueError 會一路 raise)
            try:
                FileStorage.delete_folder(folder.user_token, folder.name)
            except ValueError as e:
                logger.warning(
                    f"Storage cleanup skipped for folder {folder_id} "
                    f"(invalid name, likely ghost row): {e}")

            # 刪除資料夾記錄
            FolderDB.delete(id=folder_id)
            logger.info(f"Successfully deleted folder: {folder_id} ({folder.name})")

            # 最後清掉該 folder 的 job 記錄(in-memory + DB)。不清的話孤兒 job
            # 會留在 /index/jobs 列表,前端順著它輪詢已刪除的 folder →
            # FOLDER_NOT_FOUND 無限刷
            try:
                from src.domain.rag.index_job_manager import IndexingJobManager
                IndexingJobManager.get_instance().purge_jobs_for_folder(folder_id)
            except Exception as e:
                logger.warning(f"Failed to purge job records for folder {folder_id}: {e}")

            return True

        except Exception as e:
            logger.error(f"Failed to delete folder {folder_id}: {e}")
            raise
