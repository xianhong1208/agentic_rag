
"""Token 管理 API 模型定義"""

from pydantic import BaseModel
from typing import List


class TokenCreateRequest(BaseModel):
    """Token 創建請求模型"""
    user_name: str = "generated_user"
    scopes: List[str] = ["read", "write", "admin"]
    length: int = 24
    expires_in_days: int = None


class TokenResponse(BaseModel):
    """Token 響應模型"""
    token: str
    user_name: str
    scopes: List[str]
    expires_at: int
    expires_at_readable: str
    message: str


class TokenInfo(BaseModel):
    """Token 信息模型"""
    user_name: str
    scopes: List[str]
    expires_at: int
    expires_at_readable: str
    module: List[str]


class TokenListResponse(BaseModel):
    """Token 列表響應模型"""
    tokens: dict[str, TokenInfo]  # 扁平化: token_string -> TokenInfo
    source: str
    total_count: int
    modules: List[str]
