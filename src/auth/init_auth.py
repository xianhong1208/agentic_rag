
"""認證系統初始化"""

from src.log import get_api_logger
from src.auth.remote_auth import RemoteTokenVerifier
from src.auth.dependencies import set_remote_verifier

api_logger = get_api_logger()


def initialize_auth_system(config):
    """初始化認證系統 - 使用遠端 Token Server"""

    auth_config = getattr(config, 'auth', None)
    auth_enabled = getattr(auth_config, 'enabled', False) if auth_config else False
    token_server_url = getattr(auth_config, 'token_server_url', None) if auth_config else None

    if not auth_enabled:
        api_logger.info("🔧 Authentication system is disabled")
        return

    if not token_server_url:
        api_logger.error("❌ Remote auth requires 'token_server_url' in config")
        raise RuntimeError("token_server_url is required for authentication")

    # 從配置讀取可選參數
    cache_ttl = getattr(auth_config, 'cache_ttl', 60)
    request_timeout = getattr(auth_config, 'request_timeout', 5.0)
    retry_count = getattr(auth_config, 'retry_count', 2)

    api_logger.info(f"🔧 Initializing remote authentication (Token Server: {token_server_url}, cache_ttl: {cache_ttl}s)")

    # 從 server config 取得本服務的 host:port（用於 Token Server 驗證 token 歸屬）
    server_config = getattr(config, 'server', None)

    verifier = RemoteTokenVerifier(
        token_server_url,
        timeout=request_timeout,
        retry_count=retry_count,
        cache_ttl=cache_ttl,
        service_host=getattr(server_config, 'host', None),
        service_port=getattr(server_config, 'port', None)
    )
    set_remote_verifier(verifier)
    api_logger.success("Remote authentication system initialized (supports JWT + Opaque tokens)")
