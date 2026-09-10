
"""遠端 Token 驗證客戶端

提供給 MCP Server 使用，透過 HTTP 呼叫 Token Server 進行認證。
"""

import time
import asyncio
import hashlib
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass

import httpx

from src.log import get_auth_logger

logger = get_auth_logger()


@dataclass
class TokenVerifyResult:
    """Token 驗證結果"""
    valid: bool
    user_name: Optional[str] = None
    scopes: Optional[list] = None
    expires_at: Optional[int] = None
    error: Optional[str] = None


class RemoteTokenVerifier:
    """遠端 Token 驗證器

    透過 HTTP 呼叫 Token Server 的 /auth/verify API 進行驗證。

    使用方式:
        verifier = RemoteTokenVerifier("http://localhost:8000")
        result = await verifier.verify("token_string")
        if result.valid:
            print(f"User: {result.user_name}")
    """

    def __init__(
        self,
        token_server_url: str,
        timeout: float = 5.0,
        retry_count: int = 2,
        cache_ttl: int = 60,
        service_host: Optional[str] = None,
        service_port: Optional[int] = None
    ):
        """初始化遠端驗證器

        Args:
            token_server_url: Token Server 的基礎 URL (如 http://localhost:8000)
            timeout: HTTP 請求超時時間（秒）
            retry_count: 失敗重試次數
            cache_ttl: 驗證結果快取時間（秒）
            service_host: 本服務在 Token Server 中註冊的 host
            service_port: 本服務在 Token Server 中註冊的 port
        """
        self.token_server_url = token_server_url.rstrip('/')
        self.verify_url = f"{self.token_server_url}/auth/verify"
        self.timeout = timeout
        self.retry_count = retry_count
        self.service_host = service_host
        self.service_port = service_port

        # 簡單的記憶體快取（減少對 Token Server 的請求）
        self._cache: Dict[str, tuple[TokenVerifyResult, float]] = {}
        self._cache_ttl = cache_ttl
        self._cache_lock = threading.Lock()

        # 持久化的 HTTP 客戶端（避免 Nuitka + anyio cancel scope 問題）
        # 注意：只使用同步客戶端，async 方法透過 asyncio.to_thread 呼叫
        self._sync_client: Optional[httpx.Client] = None

        logger.info(f"RemoteTokenVerifier initialized: {self.verify_url} (cache_ttl: {cache_ttl}s)")

    def _get_cache_key(self, token: str) -> str:
        """產生快取 key（使用 SHA-256 避免原始 token 留在記憶體）"""
        return hashlib.sha256(token.encode()).hexdigest()

    def _get_sync_client(self) -> httpx.Client:
        """取得或建立持久化的 sync HTTP 客戶端"""
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=self.timeout)
        return self._sync_client

    async def verify(self, token: str) -> TokenVerifyResult:
        """驗證 Token

        Args:
            token: 要驗證的 Token 字串

        Returns:
            TokenVerifyResult: 驗證結果
        """
        cache_key = self._get_cache_key(token)

        # 檢查快取
        cached = self._get_from_cache(cache_key)
        if cached:
            logger.debug(f"Token verification cache hit: {token[:8]}...")
            return cached

        # 呼叫 Token Server
        result = await self._call_verify_api(token)

        # 存入快取（只快取有效的結果）
        if result.valid:
            self._set_cache(cache_key, result)

        return result

    def verify_sync(self, token: str) -> TokenVerifyResult:
        """同步版本的 Token 驗證（用於非 async 環境）"""
        cache_key = self._get_cache_key(token)

        # 檢查快取
        cached = self._get_from_cache(cache_key)
        if cached:
            logger.debug(f"Token verification cache hit: {token[:8]}...")
            return cached

        # 呼叫 Token Server
        result = self._call_verify_api_sync(token)

        # 存入快取
        if result.valid:
            self._set_cache(cache_key, result)

        return result

    async def _call_verify_api(self, token: str) -> TokenVerifyResult:
        """非同步呼叫 Token Server API(透過 asyncio.to_thread 包同步 httpx)。

        Nuitka 編譯後 anyio 的 cancel scope(happy eyeballs)會出問題,所以走 sync client。

        Args:
            token: 要驗證的 token。

        Returns:
            TokenVerifyResult(valid + user_name + scopes 或 error)。
        """
        # 使用同步版本在執行緒中執行，完全避開 anyio
        return await asyncio.to_thread(self._call_verify_api_sync, token)

    def _call_verify_api_sync(self, token: str) -> TokenVerifyResult:
        """同步呼叫 Token Server API(用持久化 httpx.Client + 重試)。

        Args:
            token: 要驗證的 token。

        Returns:
            TokenVerifyResult;重試耗盡或非 retryable error 時 valid=False + error 帶細節。
        """
        last_error = None

        # 建構請求 payload（帶上 service_host + service_port 供 Token Server 驗證歸屬）
        payload = {"token": token}
        if self.service_host and self.service_port:
            payload["service_host"] = self.service_host
            payload["service_port"] = self.service_port

        client = self._get_sync_client()

        for attempt in range(self.retry_count + 1):
            try:
                response = client.post(
                    self.verify_url,
                    json=payload
                )

                if response.status_code == 200:
                    data = response.json()
                    return TokenVerifyResult(
                        valid=data.get("valid", False),
                        user_name=data.get("user_name"),
                        scopes=data.get("scopes"),
                        expires_at=data.get("expires_at"),
                        error=data.get("error")
                    )
                elif 400 <= response.status_code < 500:
                    # Client errors are not retryable
                    logger.warning(f"Token Server returned {response.status_code}")
                    return TokenVerifyResult(
                        valid=False,
                        error=f"token_server_error_{response.status_code}"
                    )
                else:
                    # 5xx server errors — retry
                    last_error = f"token_server_error_{response.status_code}"
                    logger.warning(f"Token Server returned {response.status_code} (attempt {attempt + 1})")

            except httpx.TimeoutException:
                last_error = "timeout"
                logger.warning(f"Token Server timeout (attempt {attempt + 1})")
            except httpx.ConnectError:
                last_error = "connection_error"
                logger.warning(f"Cannot connect to Token Server (attempt {attempt + 1})")
            except Exception as e:
                last_error = str(e)
                logger.error(f"Error calling Token Server: {e}")

        # 所有重試都失敗
        logger.error(f"Token verification failed after {self.retry_count + 1} attempts")
        return TokenVerifyResult(valid=False, error=last_error)

    def _get_from_cache(self, cache_key: str) -> Optional[TokenVerifyResult]:
        """從快取取得驗證結果（thread-safe）"""
        with self._cache_lock:
            if cache_key in self._cache:
                result, cached_time = self._cache[cache_key]
                if time.time() - cached_time < self._cache_ttl:
                    return result
                else:
                    # 快取過期，移除
                    del self._cache[cache_key]
            return None

    def _set_cache(self, cache_key: str, result: TokenVerifyResult):
        """存入快取（thread-safe）"""
        with self._cache_lock:
            self._cache[cache_key] = (result, time.time())

            # 清理過期的快取項目（簡單的 LRU）
            if len(self._cache) > 1000:
                current_time = time.time()
                expired_keys = [
                    k for k, (_, t) in self._cache.items()
                    if current_time - t >= self._cache_ttl
                ]
                for k in expired_keys:
                    del self._cache[k]

    def clear_cache(self):
        """清除所有快取（thread-safe）"""
        with self._cache_lock:
            self._cache.clear()
        logger.info("Remote token verifier cache cleared")

    def _health_check_sync(self) -> bool:
        """同步版本的健康檢查"""
        try:
            client = self._get_sync_client()
            response = client.get(f"{self.token_server_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Token Server health check failed: {e}")
            return False

    async def health_check(self) -> bool:
        """檢查 Token Server 是否可用

        使用 asyncio.to_thread 避免 Nuitka + anyio 相容性問題。
        """
        return await asyncio.to_thread(self._health_check_sync)

    def close(self):
        """關閉 HTTP 客戶端連線"""
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None
        logger.debug("RemoteTokenVerifier HTTP client closed")


# 全域實例（可選）
_verifier_instance: Optional[RemoteTokenVerifier] = None


def get_remote_verifier(
    token_server_url: str = None,
    timeout: float = 5.0,
    retry_count: int = 2,
    cache_ttl: int = 60,
    service_host: Optional[str] = None,
    service_port: Optional[int] = None
) -> RemoteTokenVerifier:
    """取得或建立遠端驗證器實例

    Args:
        token_server_url: Token Server URL（首次呼叫時必須提供）
        timeout: HTTP 請求超時時間（秒）
        retry_count: 失敗重試次數
        cache_ttl: 驗證結果快取時間（秒）
        service_host: 本服務在 Token Server 中註冊的 host
        service_port: 本服務在 Token Server 中註冊的 port

    Returns:
        RemoteTokenVerifier 實例
    """
    global _verifier_instance

    if _verifier_instance is None:
        if token_server_url is None:
            raise ValueError("token_server_url is required for first initialization")
        _verifier_instance = RemoteTokenVerifier(
            token_server_url,
            timeout=timeout,
            retry_count=retry_count,
            cache_ttl=cache_ttl,
            service_host=service_host,
            service_port=service_port
        )

    return _verifier_instance


def reset_remote_verifier():
    """重置遠端驗證器實例（會關閉 HTTP 客戶端連線）"""
    global _verifier_instance
    if _verifier_instance is not None:
        _verifier_instance.close()
    _verifier_instance = None
