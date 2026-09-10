
"""文件操作 API 路由

提供文件上傳、下載、更新、刪除等 REST API 接口
支援基於空間和資料夾的文件管理
"""
import traceback
from urllib.parse import quote
from uuid import UUID
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends, Request
from fastapi.responses import StreamingResponse
from typing import Optional, List
from sqlalchemy.exc import IntegrityError, NoResultFound
from pydantic import ValidationError
from fastmcp.exceptions import ToolError

from src.auth.dependencies import authenticate_request
from src.api.dependencies.auth import extract_token
from src.api.router.response import (
    BatchDeleteRequest,
    ErrorDetailResponse,
    FileDeletedResponse,
    FileResource,
    FileUploadResponse,
    UpdateFileRequest,
)
from src.adapter.file import FileAdapter
from src.adapter.folder import FolderAdapter
from src.adapter.rag import get_rag_adapter
from src.log import get_api_logger
from db.file_with_index_db import FileWithIndexDB

# 獲取日誌實例
logger = get_api_logger()

router = APIRouter(tags=["Files"], prefix="/folders", dependencies=[Depends(authenticate_request)])

# Resource = File;Response = {file_info: FileResource, indexing: IndexingMetadata, message}
# auto_index=True 時 indexing 區塊含 background job_id;否則 enabled=false
@router.post(
    path="/{folder_id}/file",
    summary="Upload File",
    description="Upload a file to a specified folder",
    response_model=FileUploadResponse,
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder 不存在"},
        409: {"model": ErrorDetailResponse, "description": "同 folder 內檔名已存在"},
        400: {"model": ErrorDetailResponse, "description": "驗證失敗(檔案過大、格式不支援等)"},
        500: {"model": ErrorDetailResponse},
    },
)
async def upload_file(
    folder_id: int,
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),  # Accept comma-separated string, will convert to list
    auto_index: bool = Form(True),  # ✅ NEW: Auto-indexing enabled by default
    user_token: str = Depends(extract_token),
):
    """
    Args:
        folder_id: 資料夾 ID
        file: 要上傳的文件
        description: 文件描述 (可選)
        tags: 文件標籤 (可選，逗號分隔的字符串，如 "tag1,tag2,tag3")
        auto_index: 是否自動索引文件到向量存儲，默認為 True
    """

    logger.info(f"Starting file upload: {file.filename} to folder {folder_id}, auto_index={auto_index})")
    logger.info(f"Received description: {description}, tags: {tags}")

    try:
        result = await FolderAdapter.get_folder(id=folder_id, user_token=user_token)
        if not result:
            raise HTTPException(status_code=404, detail=f"folder {folder_id} not found")
        file_content = await file.read()

        # Convert comma-separated tags string to list
        tags_list = None
        if tags:
            tags_list = [tag.strip() for tag in tags.split(',') if tag.strip()]

        # Construct file data dictionary
        file_data = {
            'file_content': file_content,
            'file_name': file.filename,
            'description': description,
            'tags': tags_list
        }

        # Single file upload via adapter
        upload_result = await FileAdapter.upload_file(
            files_data=file_data,
            folder_id=folder_id,
            user_token=user_token
        )

        logger.info(f"File upload completed: {file.filename} to folder {folder_id}")

        # ✅ NEW: Trigger auto-indexing if enabled
        indexing_metadata = None
        if auto_index:
            try:
                # Extract file ID from upload result
                # upload_result is [FileConfigData] for single file
                if isinstance(upload_result, list):
                    # Single file case: [FileConfigData]
                    uploaded_file_ids = [str(f.id) for f in upload_result]
                else:
                    # This shouldn't happen for single file, but handle gracefully
                    uploaded_file_ids = []

                # Trigger auto-indexing
                if uploaded_file_ids:
                    indexing_metadata = await get_rag_adapter().trigger_auto_index(
                        file_ids=uploaded_file_ids,
                        folder_id=folder_id,
                        token=user_token,
                        auto_index=True
                    )
                    logger.info(f"Auto-indexing triggered for uploaded file: {file.filename}")
            except Exception as e:
                # Log warning but don't fail - file upload succeeded
                logger.warning(f"Auto-indexing failed for uploaded file {file.filename}: {str(e)}")
                indexing_metadata = {
                    "auto_index_enabled": True,
                    "message": f"Warning: Auto-indexing failed: {str(e)}"
                }

        # ✅ NEW: Enhanced response with indexing metadata
        if isinstance(upload_result, list) and len(upload_result) > 0:
            # Convert Pydantic model to dict for proper JSON serialization
            file_info = upload_result[0].model_dump() if hasattr(upload_result[0], 'model_dump') else upload_result[0]
            response = {
                "file_info": file_info,
                "indexing": indexing_metadata if indexing_metadata else {"auto_index_enabled": False, "message": "Auto-indexing disabled"},
                "message": "File uploaded successfully"
            }
        else:
            # Convert Pydantic model to dict for proper JSON serialization
            file_info = upload_result.model_dump() if hasattr(upload_result, 'model_dump') else upload_result
            response = {
                "file_info": file_info,
                "indexing": indexing_metadata if indexing_metadata else {"auto_index_enabled": False, "message": "Auto-indexing disabled"},
                "message": "File uploaded successfully"
            }

        return response

    except IntegrityError as e:
        traceback.print_exc()
        logger.error(f"Database integrity error uploading file {file.filename if file else 'unknown'} to folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=409, detail="file already exists")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed to upload file {file.filename if file else 'unknown'} to folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



# 回傳原檔案 binary stream(non-JSON);Content-Type 視檔案 mime_type
@router.get(
    path="/{folder_id}/files/{file_id}/download",
    summary="Download File",
    description="Download a specified file",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "檔案內容 binary stream(Content-Type 依檔案 mime_type 而定)",
        },
        404: {"model": ErrorDetailResponse, "description": "folder / file 不存在"},
        500: {"model": ErrorDetailResponse},
    },
)
async def download_file(
    folder_id: int,
    file_id: UUID,
    user_token: str = Depends(extract_token),
):
    """
    Args:
        folder_id: 資料夾 ID
        file_id: 文件 ID (UUID)
    """
    try:
        result = await FolderAdapter.get_folder(id=folder_id, user_token=user_token)
        if not result:
            raise HTTPException(status_code=404, detail=f"folder {folder_id} not found")
        
        file_info_result = await FileAdapter.get_file(user_token=user_token, folder_id=folder_id, id=file_id)

        if not file_info_result:
            logger.warning(f"File not found: file_id={file_id}, folder_id={folder_id}")
            raise HTTPException(status_code=404, detail="File not found")

        file_info = file_info_result[0]

        result = await FileAdapter.download_file(
            folder_id=file_info.folder_id,
            file_id=file_id,
            user_token=user_token,
        )

        if not result:
            logger.warning(f"Failed to download file: file_id={file_id}, folder_id={file_info.folder_id}")
            raise HTTPException(status_code=404, detail="File not found")

        file_data = result[0]
        logger.info(f"File downloaded successfully: file_id={file_id}, filename={file_data.file_name}")
        ascii_filename = file_data.file_name.encode('ascii', 'ignore').decode('ascii') or 'download'
        encoded_filename = quote(file_data.file_name)

        # Create streaming response
        def generate():
            yield file_data.file_content

        return StreamingResponse(
            generate(),
            media_type=file_data.mime_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'
            }
        )
    except ToolError as e:
        traceback.print_exc()
        logger.error(f"Tool error downloading file {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except NoResultFound as e:
        traceback.print_exc()
        logger.warning(f"File not found: file_id={file_id}, folder_id={folder_id}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        traceback.print_exc()
        logger.error(f"Validation error downloading file {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Data validation failed: {str(e)}")
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Value error downloading file {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed to download file {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


# Resource = FileResource(更新後)
@router.patch(
    "/{folder_id}/files/{file_id}",
    summary="Update file metadata",
    response_model=FileResource,
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder / file 不存在"},
        409: {"model": ErrorDetailResponse, "description": "改名後撞名"},
        400: {"model": ErrorDetailResponse, "description": "參數錯"},
    },
)
async def update_file(
    folder_id: int,
    file_id: UUID,
    requests: UpdateFileRequest,
    user_token: str = Depends(extract_token),
):
    """更新指定文件的元數據"""
    try:
        result = await FolderAdapter.get_folder(id=folder_id, user_token=user_token)
        if not result:
            raise HTTPException(status_code=404, detail=f"folder {folder_id} not found")
        
        result = await FileAdapter.update_file_metadata(
            folder_id=folder_id,
            file_id=file_id,
            user_token=user_token,
            description=requests.description,
            tags=requests.tags
        )

        logger.info(f"File metadata updated successfully: file_id={file_id}, folder_id={folder_id}")
        # response_model=FileResource(single)→ 直接回 result[0],不要再 wrap
        # `{"file_info": ...}`(那 shape 是 upload_file 的 FileUploadResponse 才有)。
        return result[0]

    except ToolError as e:
        traceback.print_exc()
        logger.error(f"Tool error updating file metadata {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except NoResultFound as e:
        traceback.print_exc()
        logger.error(f"File not found for update: file_id={file_id}, folder_id={folder_id}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        traceback.print_exc()
        logger.error(f"Validation error updating file metadata {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Data validation failed: {str(e)}")
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Value error updating file metadata {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed to update file metadata {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Update file metadata failed: {str(e)}")


# Response = {success: bool, message: str}
@router.delete(
    "/{folder_id}/files/{file_id}",
    summary="Delete file",
    response_model=FileDeletedResponse,
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder / file 不存在"},
        500: {"model": ErrorDetailResponse},
    },
)
async def delete_file(
    folder_id: int,
    file_id: UUID,
    user_token: str = Depends(extract_token),
):
    """刪除指定的文件"""
    try:
        result = await FolderAdapter.get_folder(id=folder_id, user_token=user_token)
        if not result:
            raise HTTPException(status_code=404, detail=f"folder {folder_id} not found")
        
        # 首先獲取文件信息以確認文件存在
        file_info_result = await FileAdapter.get_file(user_token=user_token, folder_id=folder_id, id=file_id)

        if not file_info_result:
            logger.warning(f"File not found for deletion: file_id={file_id}, folder_id={folder_id}")
            raise NoResultFound("File not found")

        file_info = file_info_result[0]

        # 調用合併後的刪除函數（單個文件）
        result = await FileAdapter.delete_file(
            file_ids=file_id,
            folder_id=file_info.folder_id,
            user_token=user_token
        )

        logger.info(f"File deleted successfully: file_id={file_id}, folder_id={folder_id}")
        return {"success": result, "message": "File deleted successfully"}

    except ToolError as e:
        traceback.print_exc()
        logger.error(f"Tool error deleting file {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except NoResultFound as e:
        traceback.print_exc()
        logger.error(f"File not found for deletion: file_id={file_id}, folder_id={folder_id}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        traceback.print_exc()
        logger.error(f"Validation error deleting file {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Data validation failed: {str(e)}")
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Value error deleting file {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed to delete file {file_id} in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Delete file failed: {str(e)}")


# Batch upload — response shape 跟單檔不同:含 successful/failed/skipped lists
# (adapter 內部已 return dict;這裡不強制 response_model 因為 nested batch 結構複雜)
@router.post(
    "/{folder_id}/files",
    summary="Upload multiple files (batch)",
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder 不存在"},
        409: {"model": ErrorDetailResponse, "description": "部分檔案同名衝突"},
        500: {"model": ErrorDetailResponse},
    },
)
async def upload_files(
    folder_id: int,
    files: List[UploadFile] = File(...),
    auto_index: bool = Form(True),  # ✅ NEW: Auto-indexing enabled by default
    user_token: str = Depends(extract_token),
):
    """批次上傳文件到指定資料夾

    Args:
        folder_id: 資料夾 ID
        files: 要上傳的文件列表        
        auto_index: 是否自動索引文件到向量存儲，默認為 True
    """
    try:
        result = await FolderAdapter.get_folder(id=folder_id, user_token=user_token)
        if not result:
            raise HTTPException(status_code=404, detail=f"folder {folder_id} not found")

        # 準備文件數據列表
        files_data = []
        for file in files:
            file_content = await file.read()
            files_data.append({
                'file_content': file_content,
                'file_name': file.filename,
                'description': None,
                'tags': None
            })

        logger.info(f"Starting batch upload: {len(files)} files to folder {folder_id} (auto_index={auto_index})")

        # 調用適配器函數（批次上傳）
        upload_result = await FileAdapter.upload_file(
            files_data=files_data,
            folder_id=folder_id,
            user_token=user_token
        )

        logger.info(f"Batch upload completed: folder={folder_id}")

        # ✅ NEW: Trigger auto-indexing if enabled
        indexing_metadata = None
        if auto_index:
            try:
                # Extract file IDs from upload result
                # For batch uploads, upload_result is a dict with 'successful_uploads' list of dicts
                uploaded_file_ids = []
                if isinstance(upload_result, dict):
                    # Batch upload case: successful_uploads contains dicts
                    if 'successful_uploads' in upload_result:
                        uploaded_file_ids = [str(f['id']) for f in upload_result['successful_uploads']]
                    elif 'files' in upload_result:
                        uploaded_file_ids = [str(f['id']) for f in upload_result['files']]

                if uploaded_file_ids:
                    # Trigger auto-indexing for newly uploaded files only
                    indexing_metadata = await get_rag_adapter().trigger_auto_index(
                        file_ids=uploaded_file_ids,
                        folder_id=folder_id,
                        token=user_token,
                        auto_index=True
                    )
                    logger.info(f"Auto-indexing triggered for {len(uploaded_file_ids)} uploaded files")
                else:
                    # No successfully uploaded files to index
                    indexing_metadata = {
                        "auto_index_enabled": False,
                        "message": "No files were successfully uploaded to index"
                    }
            except Exception as e:
                # Log warning but don't fail - file upload succeeded
                logger.warning(f"Auto-indexing failed for batch upload: {str(e)}")
                indexing_metadata = {
                    "auto_index_enabled": True,
                    "message": f"Warning: Auto-indexing failed: {str(e)}"
                }

        # ✅ NEW: Enhanced response with indexing metadata
        response = {
            **upload_result,  # Include all original fields (successful_uploads, failed_uploads, etc.)
            "indexing": indexing_metadata if indexing_metadata else {"auto_index_enabled": False, "message": "Auto-indexing disabled"}
        }

        return response

    except ToolError as e:
        traceback.print_exc()
        logger.error(f"Tool error in batch upload to folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except NoResultFound as e:
        traceback.print_exc()
        logger.error(f"Folder not found for batch upload: folder_id={folder_id}")
        raise HTTPException(status_code=404, detail=str(e))
    except IntegrityError as e:
        traceback.print_exc()
        logger.error(f"Database integrity error in batch upload to folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=409, detail="File already exists or data conflict")
    except ValidationError as e:
        traceback.print_exc()
        logger.error(f"Validation error in batch upload to folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Data validation failed: {str(e)}")
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Value error in batch upload to folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed batch upload to folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch upload failed: {str(e)}")


# Resource = List[FileResource](或單一,當帶 file_id/file_name 時)
# include_index_status=True 時每筆會多帶 indexed_at / status / num_chunks(走 JOIN)
@router.get(
    "/{folder_id}/files",
    summary="List or get files",
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder / file 不存在"},
        400: {"model": ErrorDetailResponse, "description": "參數錯"},
    },
)
async def list_files(
    folder_id: int,
    file_id: Optional[UUID] = Query(None, description="文件 ID（若提供則返回單個文件資訊）"),
    file_name: Optional[str] = Query(None, description="文件名稱（若提供則根據名稱查找文件）"),
    search_tags: Optional[str] = Query(None, description="搜尋標籤（部分匹配）"),
    mime_type_filter: Optional[str] = Query(None, description="MIME 類型過濾器（部分匹配）"),
    include_index_status: bool = Query(True, description="包含文件索引狀態（使用 JOIN 優化）"),
    user_token: str = Depends(extract_token),
):
    """列出資料夾內檔案,或依 file_id / file_name 取單筆。

    使用 JOIN query 一次抓回 file + index status,避開 N+1(對大 folder 10-100x 加速)。
    若不需 index 資訊可設 include_index_status=False 再加快。

    Args:
        folder_id: 資料夾 id。
        file_id: 給就回單筆;優先序最高。
        file_name: 給就依名稱查;次優先。
        search_tags: tag 部分比對。
        mime_type_filter: MIME 部分比對。
        include_index_status: True → 回傳含 indexed_at / status / num_chunks 等欄位。
        user_token: 使用者 token(權限驗證)。

    Returns:
        list 或 dict(視查詢參數而定);每筆含基本 File 欄位 + 可選 index 欄位。
    """
    try:
        folder_list = await FolderAdapter.get_folder(id=folder_id, user_token=user_token)
        if not folder_list:
            raise HTTPException(status_code=404, detail=f"folder {folder_id} not found")
        
        folder = folder_list[0]  # 取得第一個資料夾記錄

        # 如果提供 file_id，返回單個文件資訊
        if file_id is not None:
            logger.info(f"Fetching file info: file_id={file_id} in folder {folder_id}")
            result = await FileAdapter.get_file(user_token=user_token, folder_id=folder.id, id=file_id)
            
            if not result:
                raise NoResultFound("File not found")
            
            logger.info(f"File info retrieved successfully: file_id={file_id}, folder_id={folder_id}")
            return {"file_info": result[0]}

        # 如果提供 file_name，根據名稱查找文件
        if file_name:
            logger.info(f"Fetching file info by name: file_name={file_name} in folder {folder_id}")
            result = await FileAdapter.get_file(user_token=user_token, folder_id=folder.id, file_name=file_name)
            
            if not result:
                raise NoResultFound(f"File with name '{file_name}' not found")
            
            logger.info(f"File info retrieved successfully by name: file_name={file_name}, folder_id={folder_id}")
            return {"file_info": result[0]}

        # 否則列出所有文件
        # Use optimized JOIN query if index status is requested
        if include_index_status:
            files_with_index = FileWithIndexDB.get_files_with_index_status(folder.id)

            if not files_with_index:
                logger.info(f"No files found in folder: folder_id={folder_id}")
                return {"files": [], "message": "No files found in folder"}

            # Apply filters if provided
            filtered_files = files_with_index
            if search_tags:
                # Search in JSONB array: check if any tag contains the search string
                filtered_files = [
                    f for f in filtered_files
                    if f.get('tags') and isinstance(f['tags'], list) and 
                    any(search_tags.lower() in tag.lower() for tag in f['tags'])
                ]
            if mime_type_filter:
                filtered_files = [
                    f for f in filtered_files
                    if f.get('mime_type') and mime_type_filter.lower() in f['mime_type'].lower()
                ]

            logger.info(f"Files listed successfully with index status: folder_id={folder_id}, count={len(filtered_files)}")
            return {"files": filtered_files}

        else:
            # Legacy behavior: fetch files only (no index status)
            result = await FileAdapter.get_file(user_token=user_token, folder_id=folder.id)

            if not result:
                logger.info(f"No files found in folder: folder_id={folder_id}")
                return {"files": [], "message": "No files found in folder"}

            # 過濾功能（如果需要的話）
            filtered_files = result
            if search_tags:
                # Search in JSONB array: check if any tag contains the search string
                filtered_files = [
                    f for f in filtered_files 
                    if f.tags and isinstance(f.tags, list) and 
                    any(search_tags.lower() in tag.lower() for tag in f.tags)
                ]
            if mime_type_filter:
                filtered_files = [f for f in filtered_files if f.mime_type and mime_type_filter.lower() in f.mime_type.lower()]

            logger.info(f"Files listed successfully: folder_id={folder_id}, count={len(filtered_files)}")
            return {"files": filtered_files}

    except ToolError as e:
        traceback.print_exc()
        logger.error(f"Tool error listing files in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except NoResultFound as e:
        traceback.print_exc()
        logger.error(f"Folder not found for listing files: folder_id={folder_id}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        traceback.print_exc()
        logger.error(f"Validation error listing files in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Data validation failed: {str(e)}")
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Value error listing files in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed to list files in folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"List files failed: {str(e)}")


# Batch delete — body 帶 file_ids list 或 delete_all=true
# Response 為 batch result dict(含 deleted_count / failed list)
@router.delete(
    "/{folder_id}/files",
    summary="Delete multiple files (batch)",
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder 不存在"},
        500: {"model": ErrorDetailResponse},
    },
)
async def delete_files(
    requests: BatchDeleteRequest,
    folder_id: int,
    user_token: str = Depends(extract_token),
):
    """批次刪除指定資料夾中的文件"""
    try:
        folder_list = await FolderAdapter.get_folder(id=folder_id, user_token=user_token)
        if not folder_list:
            raise HTTPException(status_code=404, detail=f"folder {folder_id} not found")
        
        folder = folder_list[0]  # 取得第一個資料夾記錄

        # 調用合併後的刪除函數（批次刪除）
        result = await FileAdapter.delete_file(
            file_ids=requests.file_ids,
            folder_id=folder.id,
            user_token=user_token,
            delete_all=requests.delete_all
        )

        logger.info(f"Batch file deletion completed: folder_id={folder_id}, delete_all={requests.delete_all}")
        return result

    except ToolError as e:
        traceback.print_exc()
        logger.error(f"Tool error in batch file deletion for folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except NoResultFound as e:
        traceback.print_exc()
        logger.error(f"Folder not found for batch deletion: folder_id={folder_id}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        traceback.print_exc()
        logger.error(f"Validation error in batch file deletion for folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Data validation failed: {str(e)}")
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Value error in batch file deletion for folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed batch file deletion for folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch delete files failed: {str(e)}")
