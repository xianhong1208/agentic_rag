
"""
提供文件上傳、下載、更新和刪除的 CRUD 功能。
支持多種文件類型('txt', 'pdf', 'doc', 'docx', 'csv', 'md', 'json')，包含文件驗證和安全檢查。
"""

from typing import Dict, Any, Optional, List, Union
from db.db import File, Session as DBSession
from db.filedb import FileDB
from db.folderdb import FolderDB
from sqlalchemy.exc import NoResultFound
from uuid import UUID, uuid4
from src.log import get_adapter_logger, log_op, log_err, log_warn, mask_token
from src.adapter.model import FileConfigData, FileDownloadData
from src.storage.file_storage import FileStorage
# 獲取日誌實例
logger = get_adapter_logger()



class FileAdapter():

    @staticmethod
    def _verify_folder_ownership(folder_id: int, user_token: str):
        """驗證資料夾是否屬於指定使用者
        
        Args:
            folder_id: 資料夾 ID
            user_token: 使用者 token
            
        Returns:
            Folder object if authorized
            
        Raises:
            NoResultFound: 如果資料夾不存在或不屬於該使用者
        """
        folder_check = FolderDB.get(id=folder_id, user_token=user_token)
        if not folder_check:
            raise NoResultFound(f"Folder id {folder_id} does not exist or you don't have permission to access it")
        return folder_check[0]

    @staticmethod
    def _update_folder_stats(folder_id: int):
        """更新資料夾統計信息"""
        with DBSession() as session:
            files_in_folder = session.query(File).filter(File.folder_id == folder_id).all()
            actual_file_count = len(files_in_folder)
            actual_total_size = sum(f.file_size for f in files_in_folder)
            FolderDB.update(folder_id, file_count=actual_file_count, total_size=actual_total_size)

    @staticmethod
    def _build_upload_response(is_batch: bool, successful_uploads: list, failed_uploads: list, 
                             skipped_uploads: list, files_list: list, total_size_added: int, 
                             single_file_result: Optional[FileConfigData]) -> Union[list[FileConfigData], Dict[str, Any]]:
        """Construct upload response"""
        if is_batch:
            return {
                "message": f"Batch upload completed: {len(successful_uploads)} succeeded, {len(failed_uploads)} failed, {len(skipped_uploads)} skipped",
                "summary": {
                    "total_files": len(files_list),
                    "successful_count": len(successful_uploads),
                    "failed_count": len(failed_uploads),
                    "skipped_count": len(skipped_uploads),
                    "total_size_added": total_size_added
                },
                "successful_uploads": successful_uploads,
                "failed_uploads": failed_uploads,
                "skipped_uploads": skipped_uploads
            }
        else:
            return [single_file_result]

    @staticmethod
    async def upload_file(
        files_data: Union[Dict[str, Any], List[Dict[str, Any]]],
        folder_id: int,
        user_token: str,
    ) -> Optional[Union[list[FileConfigData], Dict[str, Any]]]:
        """上傳文件到指定資料夾（支持單個或批次上傳）

        Args:
            files_data: 單個文件數據字典或文件數據列表
                      單個文件格式: {
                          'file_content': bytes,
                          'file_name': str,
                          'description': Optional[str],
                          'tags': Optional[List[str]]  # Changed from str to List[str]
                      }
            folder_id: 資料夾 ID
            user_token: 使用者 token

        Returns:
            單個文件: list[FileConfigData] 或錯誤字典
            批次上傳: 包含上傳結果統計的字典
        """

        # Verify folder ownership
        folder = FileAdapter._verify_folder_ownership(folder_id, user_token)
        # 判斷是單個文件還是批次上傳
        is_batch = isinstance(files_data, list)
        files_list = files_data if is_batch else [files_data]

        # 批次上傳的統計變量
        successful_uploads = []
        failed_uploads = []
        skipped_uploads = []
        total_size_added = 0

        for file_data in files_list:
            try:
                file_content = file_data['file_content']
                file_name = file_data['file_name']
                description = file_data.get('description')
                tags = file_data.get('tags')

                # Debug log
                logger.info(f"Processing file: {file_name}, description: {description}, tags: {tags}")

                # 驗證文件內容
                validation_result = FileDB._validate_file_content(file_content, file_name)

                # 先生成 UUID，這樣可以一次性完成文件保存和數據庫記錄創建
                file_id = uuid4()

                # 使用這個 UUID 保存文件到文件系統
                file_path = FileStorage.save_file(folder.user_token, folder.name, str(file_id), file_content)

                # 一次性創建數據庫記錄，包含正確的 file_path
                file_record = FileDB.create(
                    id=file_id,  # 指定 UUID
                    folder_id=folder.id,
                    file_name=file_name,
                    file_path=file_path,  # 使用真實路徑
                    file_size=validation_result['file_size'],
                    mime_type=validation_result['mime_type'],
                    description=description,
                    tags=tags,
                    content_hash=validation_result.get('content_hash'),  # D3
                )
                
                # 累計統計，不立即更新資料夾
                total_size_added += validation_result['file_size']
                
                # 添加到成功上傳列表
                upload_info = {
                    "id": file_record.id,
                    "folder_id": file_record.folder_id,
                    "file_name": file_record.file_name,
                    "file_path": file_record.file_path,
                    "file_size": file_record.file_size,
                    "mime_type": file_record.mime_type,
                    "description": file_record.description,
                    "tags": file_record.tags,
                    "upload_time": file_record.upload_time.isoformat() if is_batch else file_record.upload_time,
                    "updated_time": file_record.updated_time
                }
                
                if is_batch:
                    successful_uploads.append({k: v for k, v in upload_info.items() if k != "updated_time"})
                else:
                    # 單個文件上傳，準備返回數據
                    single_file_result = FileConfigData(**{
                        k: v for k, v in upload_info.items()
                        if k in FileConfigData.model_fields
                    })
                    
            except Exception as e:
                if is_batch:
                    failed_uploads.append({
                        'file_name': file_data.get('file_name', 'Unknown'),
                        'error': str(e)
                    })
                else:
                    raise
        
        # 更新資料夾統計
        if len(successful_uploads) > 0 or not is_batch:
            FileAdapter._update_folder_stats(folder.id)
        
        # 返回結果
        return FileAdapter._build_upload_response(
            is_batch, successful_uploads, failed_uploads, skipped_uploads, 
            files_list, total_size_added, single_file_result if not is_batch else None
        )

    @staticmethod
    async def get_file(user_token: str, **kwargs) -> Optional[list[FileConfigData]]:
        """獲取文件信息
        
        Args:
            user_token: 使用者 token
            **kwargs: 查詢條件（包括 folder_id）
        """
        # Verify folder ownership
        folder = FileAdapter._verify_folder_ownership(kwargs.get('folder_id'), user_token)
        
        file_dict = FileDB.get(**kwargs)
            
        return [FileConfigData(
            id=file.id,
            folder_id=file.folder_id,
            file_name=file.file_name,
            file_path=file.file_path,
            file_size=file.file_size,
            mime_type=file.mime_type,
            description=file.description,
            tags=file.tags,
            upload_time=file.upload_time,
            updated_time=file.updated_time
        ) for file in file_dict]

    @staticmethod
    async def download_file(
        folder_id: int,
        file_id: UUID,
        user_token: str,
    ) -> Optional[list[FileDownloadData]]:
        """下載文件
        
        Args:
            folder_id: 資料夾 ID
            file_id: 文件ID
            user_token: 使用者 token
            
        Returns:
            包含文件內容和信息的字典
        """
        try:
            # Verify folder ownership
            folder = FileAdapter._verify_folder_ownership(folder_id, user_token)

            # Get the file
            file_record = FileDB.get(folder_id=folder_id, id=file_id)

            if not file_record:
                raise NoResultFound(f"File {file_id} not found in folder {folder_id}")
            
            # 從文件系統讀取文件內容
            file_content = FileStorage.read_file(file_record[0].file_path)
            
            return [FileDownloadData(
                id=file_record[0].id,
                folder_id=file_record[0].folder_id,
                file_name=file_record[0].file_name,
                file_content=file_content,
                file_size=file_record[0].file_size,
                mime_type=file_record[0].mime_type,
                description=file_record[0].description,
                tags=file_record[0].tags,
                upload_time=file_record[0].upload_time,
                updated_time=file_record[0].updated_time
            )]
                    
        except Exception as e:
            logger.error(f"File download failed: {str(e)}")
            raise

    @staticmethod
    async def update_file_metadata(
        folder_id: int,
        file_id: UUID,
        user_token: str,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> list[FileConfigData]:
        """更新文件元數據

        Args:
            folder_id: 資料夾 ID
            file_id: 文件ID
            user_token: 使用者 token
            description: 新的文件描述
            tags: 新的文件標籤列表

        Returns:
            更新後的文件配置數據列表
        """
        # Verify folder ownership
        folder = FileAdapter._verify_folder_ownership(folder_id, user_token)
        
        # 確認文件是否存在於指定的資料夾中
        file_list = FileDB.get(folder_id=folder.id, id=file_id)
        if not file_list:
            raise NoResultFound(f"File id {file_id} does not exist in folder {folder_id}")
        
        # 構建更新數據
        update_data = {}
        if description is not None:
            update_data['description'] = description
        if tags is not None:
            update_data['tags'] = tags
        updated_file = FileDB.update(file_id, **update_data)
        logger.info(f"Successfully updated file metadata: file_id={updated_file.id}")
        return [FileConfigData(
            id=updated_file.id,
            folder_id=updated_file.folder_id,
            file_name=updated_file.file_name,
            file_path=updated_file.file_path,
            file_size=updated_file.file_size,
            mime_type=updated_file.mime_type,
            description=updated_file.description,
            tags=updated_file.tags,
            upload_time=updated_file.upload_time,
            updated_time=updated_file.updated_time
        )]
        
    @staticmethod
    async def delete_file(
        file_ids: Optional[Union[UUID, List[UUID]]],
        folder_id: int,
        user_token: str,
        delete_all: bool = False
    ) -> Union[bool, Dict[str, Any]]:
        """刪除文件（支持單個或批次刪除）
        
        Args:
            file_ids: 單個文件ID或文件ID列表
            folder_id: 資料夾ID
            user_token: 使用者 token
            delete_all: 是否刪除資料夾中的所有文件（當為True時忽略file_ids）
            
        Returns:
            單個刪除: bool
            批次刪除: 包含刪除結果統計的字典
        """
        from src.adapter.rag import get_rag_adapter

        # Verify folder ownership
        folder = FileAdapter._verify_folder_ownership(folder_id, user_token)
        # 判斷是單個刪除還是批次刪除
        is_batch = isinstance(file_ids, list) or delete_all

        if delete_all:
            # 刪除資料夾中的所有文件
            with DBSession() as session:
                files_to_delete = session.query(File).filter(
                    File.folder_id == folder.id
                ).all()
            files_to_delete_ids = [f.id for f in files_to_delete]
        elif isinstance(file_ids, list):
            # 批次刪除指定文件
            files_to_delete_ids = file_ids
        else:
            # 單個文件刪除
            files_to_delete_ids = [file_ids]

        # Get RAG adapter singleton for index cleanup
        try:
            rag_adapter = get_rag_adapter()
        except Exception as e:
            logger.warning(f"RAG adapter initialization failed, skipping index cleanup: {e}")
            rag_adapter = None
        
        deleted_files = []
        failed_deletions = []
        total_size_freed = 0
        
        for file_id in files_to_delete_ids:
            try:
                # 獲取文件記錄
                file_record = FileDB.get(folder_id=folder_id, id=file_id)
                
                # 刪除 RAG 索引（如果存在）— 傳入 user_token 走 ACL,不繞過權限驗證
                if rag_adapter:
                    try:
                        await rag_adapter.delete_document_index(file_id=file_id, token=user_token)
                        logger.info(f"Deleted RAG index for file {file_id}")
                    except Exception as idx_error:
                        # Log but don't fail the entire deletion if index cleanup fails
                        logger.warning(f"Failed to delete RAG index for file {file_id}: {idx_error}")
                
                # 刪除文件系統中的文件
                FileStorage.delete_file(file_record[0].file_path)

                # 刪除數據庫記錄
                FileDB.delete(folder_id=folder_id, id=file_id)

                # 通知 job manager:此檔若正在索引中,盡快中止 —
                # 單檔 job 直接 cancel;多檔 job 設 per-file abort flag,
                # 由 indexing 端的 mid-stage probe 在下個檢查點停掉,
                # 不必等整段 context-gen/embedding 白跑完。best-effort。
                try:
                    from src.domain.rag.index_job_manager import IndexingJobManager
                    aborted = await IndexingJobManager.get_instance().abort_indexing_for_file(
                        str(file_id), folder_id=folder_id,
                    )
                    if aborted:
                        logger.info(
                            f"In-flight indexing abort requested for deleted "
                            f"file {file_id}: {aborted}"
                        )
                except Exception as abort_err:
                    logger.warning(
                        f"Indexing-abort notify failed for {file_id} "
                        f"(existence gates will still catch it): {abort_err}"
                    )
                
                if is_batch:
                    deleted_files.append({
                        "id": file_record[0].id,
                        "file_name": file_record[0].file_name,
                        "file_size": file_record[0].file_size
                    })
                
                total_size_freed += file_record[0].file_size
                
            except Exception as e:
                if is_batch:
                    failed_deletions.append({
                        "id": file_id,
                        "error": str(e)
                    })
                else:
                    raise
        
        # 更新資料夾統計
        if total_size_freed > 0:
            FolderDB.update(folder.id,
                        file_count=max(0, folder.file_count - len(deleted_files if is_batch else [file_ids])),
                        total_size=max(0, folder.total_size - total_size_freed))
        
        # 返回結果
        if is_batch:
            return {
                "message": f"Batch deletion completed: {len(deleted_files)} succeeded, {len(failed_deletions)} failed",
                "summary": {
                    "total_requested": len(files_to_delete_ids),
                    "successfully_deleted": len(deleted_files),
                    "failed_deletions": len(failed_deletions),
                    "total_size_freed": total_size_freed
                },
                "deleted_files": deleted_files,
                "failed_deletions": failed_deletions
            }
        else:
            return True
        