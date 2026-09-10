
"""資料夾操作 API 路由

提供資料夾創建、查詢、更新、刪除等 REST API 接口
"""

from fastapi import APIRouter, HTTPException, Depends, Request, Query
import traceback
from sqlalchemy.exc import IntegrityError, NoResultFound
from pydantic import ValidationError
from typing import Optional
from typing import List, Union

from src.api.router.response import (
    CreateFolderRequest,
    ErrorDetailResponse,
    FolderDeletedResponse,
    FolderResource,
    UpdateFolderRequest,
)
from src.adapter.folder import FolderAdapter
from src.log import get_api_logger
from src.auth.dependencies import authenticate_request
from src.api.dependencies.auth import extract_token
# 獲取日誌實例
logger = get_api_logger()

router = APIRouter(tags=["Folders"], prefix="/folders", dependencies=[Depends(authenticate_request)])

# Resource = FolderResource。Response = List[FolderResource](即使按 ID 查也以 list 包裝,維持 adapter 既有行為)。
@router.get(
    "/",
    summary="List or get folders",
    response_model=List[FolderResource],
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder_id / folder_name 找不到"},
        400: {"model": ErrorDetailResponse, "description": "參數型別錯"},
    },
)
async def list_folders(
    folder_id: Optional[int] = Query(None, description="資料夾 ID"),
    folder_name: Optional[str] = Query(None, description="資料夾名稱"),
    user_token: str = Depends(extract_token),
):
    """列出資料夾或依 ID / 名稱取單筆。

    Args:
        folder_id: 給就回該 ID;優先序最高。
        folder_name: 給就依名稱查;次優先。
        user_token: 使用者 token(權限驗證)。

    Returns:
        FolderResource list(即使按 ID 查也以 list 包裝,維持 adapter 行為)。
    """
    try:
        logger.debug(f'user_token: {user_token[:8] if user_token else "N/A"}...')

        if folder_id is not None:
            result = await FolderAdapter.get_folder(id=folder_id, user_token=user_token)
            if not result:
                raise HTTPException(status_code=404, detail=f"folder {folder_id} not found")
            return result

        if folder_name:
            result = await FolderAdapter.get_folder(name=folder_name, user_token=user_token)
            if not result:
                raise HTTPException(status_code=404, detail=f"folder with name '{folder_name}' not found")
            return result

        result = await FolderAdapter.get_folder(user_token=user_token)
        return result
    except NoResultFound as e:
        traceback.print_exc()
        logger.info(f"No folders found")
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Invalid folder ID or parameters: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as e:
        # Re-raise HTTPExceptions as-is to preserve their status codes
        raise e
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed to list/get folders: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Resource = FolderResource(剛建立的那一筆)。
@router.post(
    "/",
    summary="Create folder",
    response_model=List[FolderResource],
    responses={
        409: {"model": ErrorDetailResponse, "description": "同名 folder 已存在"},
        400: {"model": ErrorDetailResponse, "description": "參數錯"},
        422: {"model": ErrorDetailResponse, "description": "Pydantic 驗證失敗"},
    },
)
async def create_folder(
    folder_request: CreateFolderRequest,
    user_token: str = Depends(extract_token),
):
    """建一個新資料夾(綁在當前 user_token 下)。

    Args:
        folder_request: CreateFolderRequest(name + 可選 description)。
        user_token: 使用者 token(會記在 Folder.user_token,後續權限過濾用)。

    Returns:
        新建的 FolderResource。
    """
    try:
        # 從 Authorization header 提取 token
        logger.debug(f'user_token: {user_token[:8] if user_token else "N/A"}...')

        result = FolderAdapter.create_folder(
            name=folder_request.name,
            user_token=user_token,
            description=folder_request.description
        )

        return result
        
    except IntegrityError as e:
        traceback.print_exc()
        logger.error(f"Data integrity error while creating folder: {str(e)}")
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Value error while creating folder: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except ValidationError as e:
        traceback.print_exc()
        logger.error(f"Pydantic validation error creating folder: {str(e)}")
        raise HTTPException(status_code=422, detail=str(e))
    except NoResultFound as e:
        traceback.print_exc()
        logger.error(f"Folder not found while creating folder: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as e:
        # Re-raise HTTPExceptions as-is to preserve their status codes
        raise e
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed to create folder: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Response = {detail: "Folder X deleted successfully"}(刪 folder 同時 cancel 進行中 indexing job)。
@router.delete(
    "/{folder_id}",
    summary="delete folder",
    response_model=FolderDeletedResponse,
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder 不存在或無權限"},
        400: {"model": ErrorDetailResponse, "description": "參數錯"},
    },
)
async def delete_folder(
    folder_id: int,
    user_token: str = Depends(extract_token),
):
    """刪除指定 ID 的資料夾

    刪除資料夾時會自動刪除其中的所有文件（軟刪除）。
    任何 indexing job 還在跑的會先 cancel,避免它繼續寫入即將消失的 folder。

    Args:
        folder_id: 資料夾 ID
    """
    try:
        logger.debug(f'user_token: {user_token[:8] if user_token else "N/A"}...')

        # ⚠️ 先驗證所有權,再做任何副作用。cancel_jobs_for_folder 只吃 folder_id、
        #    不含 token,若放在驗權前,任一租戶 DELETE 別人的 folder_id 會在拿到
        #    404 之前先杀掉對方 in-flight job(跨租戶 DoS)。fail-closed:無主
        #    (user_token=None)或非本人一律 404,不洩漏 folder 是否存在。
        from db.cached_folderdb import CachedFolderDB
        _folder = CachedFolderDB.get_by_id(folder_id)
        if not _folder or _folder.user_token != user_token:
            raise HTTPException(status_code=404, detail=f"Folder {folder_id} not found")

        # cancel any in-flight indexing jobs for this folder first
        try:
            from src.domain.rag.index_job_manager import IndexingJobManager
            cancelled = await IndexingJobManager.get_instance().cancel_jobs_for_folder(folder_id)
            if cancelled:
                logger.info(f"Cancelled {len(cancelled)} in-flight job(s) before deleting folder {folder_id}")
        except Exception as cancel_err:
            logger.warning(f"Pre-delete job cancellation failed (continuing): {cancel_err}")

        result = await FolderAdapter.delete_folder(folder_id=folder_id, user_token=user_token)
        if result:
            return {"detail": f"Folder {folder_id} deleted successfully"}

    except NoResultFound as e:
        traceback.print_exc()
        logger.info(f"Folder {folder_id} not found for deletion")
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as e:
        raise e
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Value error deleting folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed to delete folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Resource = FolderResource(更新後的)— adapter 回 list 包裝(維持 historical
# behavior),所以 response_model 跟 list_folders / create_folder 一致用 List。
@router.patch(
    "/{folder_id}",
    summary="Update folder details",
    response_model=List[FolderResource],
    responses={
        404: {"model": ErrorDetailResponse, "description": "folder 不存在"},
        409: {"model": ErrorDetailResponse, "description": "改名後撞名"},
        400: {"model": ErrorDetailResponse, "description": "參數錯"},
    },
)
async def update_folder_api(
    folder_id: int,
    requests: UpdateFolderRequest,
    user_token: str = Depends(extract_token),
):
    """更新指定資料夾的 name / description(只 patch 有給的欄位)。

    Args:
        folder_id: 要更新的 folder。
        requests: UpdateFolderRequest(name / description 都可選)。
        user_token: 使用者 token(權限驗證)。

    Returns:
        更新後的 FolderResource。
    """
    try:
        logger.debug(f'user_token: {user_token[:8] if user_token else "N/A"}...')

        # 更新資料夾名稱和描述
        result = await FolderAdapter.update_folder(
            folder_id=folder_id,
            user_token=user_token,
            name=requests.name,
            description=requests.description
        )
        
        return result
        
    except NoResultFound:
        traceback.print_exc()
        logger.info(f"Folder {folder_id} not found for update")
        raise HTTPException(status_code=404)
    except IntegrityError as e:
        traceback.print_exc()
        logger.error(f"Data integrity error updating folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        traceback.print_exc()
        logger.error(f"Value error updating folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except ValidationError as e:
        traceback.print_exc()
        logger.error(f"Pydantic validation error updating folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException as e:
        raise e
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Failed to update folder {folder_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))