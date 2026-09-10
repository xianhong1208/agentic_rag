
"""Reusable API dependencies for authentication and authorization

These dependencies can be used with FastAPI's Depends() to eliminate
duplicate code across API endpoints.

Benefits:
- Single source of truth for auth logic
- Automatic validation and error handling
- Easy to test and mock
- Consistent behavior across all endpoints
"""

from uuid import UUID
from fastapi import Request, Depends
from typing import Optional

from db.cached_folderdb import CachedFolderDB
from db.filedb import FileDB
from db.db import Folder, File
from src.domain.exceptions import (
    InvalidTokenError,
    FolderNotFoundError,
    UnauthorizedAccessError,
    RAGFileNotFoundError
)


async def extract_token(request: Request) -> str:
    """Extract and validate Bearer token from Authorization header

    Args:
        request: FastAPI request object

    Returns:
        The extracted token string

    Raises:
        InvalidTokenError: If token is missing or invalid format

    Usage:
        @router.get("/endpoint")
        async def my_endpoint(token: str = Depends(extract_token)):
            # Use token directly
            ...
    """
    auth_header = request.headers.get('Authorization', '')

    if not auth_header:
        raise InvalidTokenError("Missing Authorization header")

    if not auth_header.startswith('Bearer '):
        raise InvalidTokenError("Invalid Authorization header format. Expected: Bearer <token>")

    parts = auth_header.split(' ')
    if len(parts) != 2:
        raise InvalidTokenError("Invalid Authorization header format")

    token = parts[1]

    if not token:
        raise InvalidTokenError("Token is empty")

    return token


async def get_folder_by_id(
    folder_id: int,
    token: str = Depends(extract_token)
) -> Folder:
    """Get folder by ID and verify user has access

    Args:
        folder_id: Folder ID to retrieve
        token: User token (automatically extracted)

    Returns:
        Folder object

    Raises:
        FolderNotFoundError: If folder doesn't exist
        UnauthorizedAccessError: If user doesn't have access

    Usage:
        @router.get("/folders/{folder_id}/endpoint")
        async def my_endpoint(
            folder_id: int,
            folder: Folder = Depends(get_folder_by_id)
        ):
            # folder is already validated and user has access
            ...
    """
    # Get folder from cache/database
    folder = CachedFolderDB.get_by_id(folder_id)

    if not folder:
        raise FolderNotFoundError(folder_id=folder_id)

    # Verify user has access to this folder
    # fail-closed:user_token 為 NULL/空(理論上不該存在的無主 folder)時
    # 一律拒絕 — 「無主 = 誰都不行」,不是「無主 = 誰都可以」
    if folder.user_token != token:
        raise UnauthorizedAccessError(
            resource_type="folder",
            resource_id=folder_id,
            reason="This folder belongs to another user"
        )

    return folder


async def get_folder_by_name(
    folder_name: str,
    token: str = Depends(extract_token)
) -> Folder:
    """Get folder by name and verify user has access

    Args:
        folder_name: Folder name to retrieve
        token: User token (automatically extracted)

    Returns:
        Folder object

    Raises:
        FolderNotFoundError: If folder doesn't exist
        UnauthorizedAccessError: If user doesn't have access

    Usage:
        @router.post("/query")
        async def query_endpoint(
            query_request: QueryRequest,
            folder: Folder = Depends(get_folder_by_name)
        ):
            # folder is already validated
            ...
    """
    # Get folder from cache/database
    folder = CachedFolderDB.get_by_name_and_token(folder_name, token)

    if not folder:
        raise FolderNotFoundError(folder_name=folder_name)

    return folder


async def get_file_by_id(
    file_id: UUID,
    token: str = Depends(extract_token)
) -> File:
    """Get file by ID and verify user has access to its folder

    Args:
        file_id: File ID to retrieve (UUID)
        token: User token (automatically extracted)

    Returns:
        File object

    Raises:
        RAGFileNotFoundError: If file doesn't exist
        UnauthorizedAccessError: If user doesn't have access to the file's folder

    Usage:
        @router.post("/files/{file_id}/index")
        async def index_file(
            file_id: UUID,
            file: File = Depends(get_file_by_id)
        ):
            # file is already validated and user has access
            ...
    """
    # Get file from database
    files = FileDB.get(id=file_id)
    
    if not files or len(files) == 0:
        raise RAGFileNotFoundError(file_id=file_id)
    
    file = files[0]
    
    # Get the file's folder to check access
    folder = CachedFolderDB.get_by_id(file.folder_id)
    
    if not folder:
        raise FolderNotFoundError(folder_id=file.folder_id)
    
    # Verify user has access to this file's folder
    # fail-closed:同 get_folder_by_id,無主 folder 一律拒絕
    if folder.user_token != token:
        raise UnauthorizedAccessError(
            resource_type="file",
            resource_id=file_id,
            reason="This file belongs to a folder owned by another user"
        )
    
    return file
