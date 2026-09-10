"""Unit tests for src/auth (model.py + remote_auth.py)

不依賴 DB / Token Server / 真實網路 — HTTP 全部用 mock httpx client。
快取 TTL 用 monkeypatch 假時鐘控制,不做 sleep。
跑法:cd agentic_rag && uv run pytest tests/test_auth_unit.py -v
"""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

import src.auth.remote_auth as remote_auth_module
from src.auth.model import (
    TokenCreateRequest,
    TokenResponse,
    TokenInfo,
    TokenListResponse,
)
from src.auth.remote_auth import (
    RemoteTokenVerifier,
    TokenVerifyResult,
    get_remote_verifier,
    reset_remote_verifier,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_verifier(**kwargs) -> RemoteTokenVerifier:
    """建立不打真實網路的 verifier(URL 是假的,HTTP client 之後會被 mock)"""
    defaults = dict(timeout=0.1, retry_count=2, cache_ttl=60)
    defaults.update(kwargs)
    return RemoteTokenVerifier("http://token-server.invalid:1/", **defaults)


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    """組一個假的 httpx Response(只帶 status_code 與 .json())"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def _install_mock_client(verifier: RemoteTokenVerifier) -> MagicMock:
    """把 verifier 的持久化 sync client 換成 MagicMock,回傳 mock client"""
    client = MagicMock()
    verifier._sync_client = client
    return client


# ---------------------------------------------------------------------------
# auth/model.py — Pydantic 模型
# ---------------------------------------------------------------------------

def test_token_create_request_defaults():
    """TokenCreateRequest 無參數建立時使用全部預設值 (TC-auth-01)"""
    req = TokenCreateRequest()
    assert req.user_name == "generated_user"
    assert req.scopes == ["read", "write", "admin"]
    assert req.length == 24
    assert req.expires_in_days is None


def test_token_create_request_explicit_none_rejected():
    """expires_in_days 顯式傳 None → ValidationError(欄位型別是 int 非 Optional[int]) (TC-auth-02)

    註:預設值 None 不經驗證所以 TokenCreateRequest() 可通過,但顯式傳 None 會爆。
    此為現行行為;欄位宣告疑似應為 Optional[int]。
    """
    with pytest.raises(ValidationError):
        TokenCreateRequest(expires_in_days=None)


def test_token_response_required_fields():
    """TokenResponse 六個欄位全必填;缺欄位 → ValidationError (TC-auth-03)"""
    resp = TokenResponse(
        token="tok-abc", user_name="u1", scopes=["read"],
        expires_at=1780000000, expires_at_readable="2026-06-01 00:00:00",
        message="created",
    )
    assert resp.token == "tok-abc"
    with pytest.raises(ValidationError) as exc_info:
        TokenResponse(token="tok-abc")
    missing = {e["loc"][0] for e in exc_info.value.errors()}
    assert missing == {"user_name", "scopes", "expires_at", "expires_at_readable", "message"}


def test_token_info_roundtrip():
    """TokenInfo 建立後 model_dump 保留全部欄位值 (TC-auth-04)"""
    info = TokenInfo(
        user_name="u1", scopes=["read"], expires_at=1780000000,
        expires_at_readable="2026-06-01 00:00:00", module=["rag"],
    )
    dumped = info.model_dump()
    assert dumped["user_name"] == "u1"
    assert dumped["module"] == ["rag"]


def test_token_list_response_nested_coercion():
    """TokenListResponse.tokens 巢狀 dict 自動轉成 TokenInfo (TC-auth-05)"""
    resp = TokenListResponse(
        tokens={
            "tok-1": {
                "user_name": "u1", "scopes": ["read"], "expires_at": 1,
                "expires_at_readable": "x", "module": ["rag"],
            }
        },
        source="db", total_count=1, modules=["rag"],
    )
    assert isinstance(resp.tokens["tok-1"], TokenInfo)
    assert resp.tokens["tok-1"].user_name == "u1"


# ---------------------------------------------------------------------------
# remote_auth.py — 快取 key
# ---------------------------------------------------------------------------

def test_get_cache_key_is_sha256():
    """_get_cache_key 回傳該 token 的 SHA-256 hexdigest(64 hex、確定性) (TC-auth-06)"""
    verifier = _make_verifier()
    key = verifier._get_cache_key("my-secret-token")
    assert key == hashlib.sha256(b"my-secret-token").hexdigest()
    assert len(key) == 64
    assert key == verifier._get_cache_key("my-secret-token")  # 同 token 同 key


def test_get_cache_key_no_plaintext_and_distinct():
    """不同 token → 不同 key;key 不包含明文 token (TC-auth-07)"""
    verifier = _make_verifier()
    key_a = verifier._get_cache_key("token-aaaa")
    key_b = verifier._get_cache_key("token-bbbb")
    assert key_a != key_b
    assert "token-aaaa" not in key_a


# ---------------------------------------------------------------------------
# remote_auth.py — 快取 TTL(monkeypatch 假時鐘)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_clock(monkeypatch):
    """把 remote_auth 模組內的 time 換成可控假時鐘"""
    clock = SimpleNamespace(now=1_000_000.0)
    monkeypatch.setattr(
        remote_auth_module, "time", SimpleNamespace(time=lambda: clock.now)
    )
    return clock


def test_cache_hit_within_ttl(fake_clock):
    """TTL 內 _get_from_cache 命中,回傳原 TokenVerifyResult (TC-auth-08)"""
    verifier = _make_verifier(cache_ttl=60)
    result = TokenVerifyResult(valid=True, user_name="u1")
    verifier._set_cache("key1", result)
    fake_clock.now += 59  # 還沒過期
    assert verifier._get_from_cache("key1") is result


def test_cache_expired_after_ttl(fake_clock):
    """超過 TTL → 回 None 且過期項目被移除 (TC-auth-09)"""
    verifier = _make_verifier(cache_ttl=60)
    verifier._set_cache("key1", TokenVerifyResult(valid=True))
    fake_clock.now += 61  # 過期
    assert verifier._get_from_cache("key1") is None
    assert "key1" not in verifier._cache  # 已被清除


def test_clear_cache(fake_clock):
    """clear_cache 清空所有快取項目 (TC-auth-10)"""
    verifier = _make_verifier()
    verifier._set_cache("k1", TokenVerifyResult(valid=True))
    verifier._set_cache("k2", TokenVerifyResult(valid=True))
    verifier.clear_cache()
    assert verifier._cache == {}


# ---------------------------------------------------------------------------
# remote_auth.py — verify() 各 HTTP 路徑(mock httpx,不打網路)
# ---------------------------------------------------------------------------

async def test_verify_success_and_cached(fake_clock):
    """200 + valid:true → 成功結果並寫入快取,第二次 verify 不再打 API (TC-auth-11)"""
    verifier = _make_verifier()
    client = _install_mock_client(verifier)
    client.post.return_value = _mock_response(
        200,
        {"valid": True, "user_name": "u1", "scopes": ["read"], "expires_at": 123},
    )

    result = await verifier.verify("good-token")
    assert result.valid is True
    assert result.user_name == "u1"
    assert result.scopes == ["read"]
    assert result.expires_at == 123
    assert client.post.call_count == 1

    # 第二次走快取,post 不再被呼叫
    result2 = await verifier.verify("good-token")
    assert result2.valid is True
    assert client.post.call_count == 1


async def test_verify_invalid_result_not_cached():
    """200 + valid:false → 不寫快取,第二次 verify 仍會打 API (TC-auth-12)"""
    verifier = _make_verifier()
    client = _install_mock_client(verifier)
    client.post.return_value = _mock_response(200, {"valid": False, "error": "expired"})

    result = await verifier.verify("bad-token")
    assert result.valid is False
    assert result.error == "expired"

    await verifier.verify("bad-token")
    assert client.post.call_count == 2  # 無快取 → 每次都打


async def test_verify_401_no_retry():
    """4xx client error → 立即失敗不重試,error 帶 status code (TC-auth-13)"""
    verifier = _make_verifier(retry_count=2)
    client = _install_mock_client(verifier)
    client.post.return_value = _mock_response(401)

    result = await verifier.verify("unauthorized-token")
    assert result.valid is False
    assert result.error == "token_server_error_401"
    assert client.post.call_count == 1  # 4xx 不 retry


async def test_verify_timeout_retries_then_fails():
    """timeout → 重試 retry_count+1 次後失敗,error='timeout' (TC-auth-14)"""
    verifier = _make_verifier(retry_count=2)
    client = _install_mock_client(verifier)
    client.post.side_effect = httpx.TimeoutException("boom")

    result = await verifier.verify("any-token")
    assert result.valid is False
    assert result.error == "timeout"
    assert client.post.call_count == 3  # 1 次原始 + 2 次重試


async def test_verify_5xx_retries_then_fails():
    """5xx server error → 重試耗盡後失敗,error 帶 status code (TC-auth-15)"""
    verifier = _make_verifier(retry_count=1)
    client = _install_mock_client(verifier)
    client.post.return_value = _mock_response(503)

    result = await verifier.verify("any-token")
    assert result.valid is False
    assert result.error == "token_server_error_503"
    assert client.post.call_count == 2


async def test_verify_connect_error():
    """連線失敗(ConnectError)→ error='connection_error' (TC-auth-16)"""
    verifier = _make_verifier(retry_count=0)
    client = _install_mock_client(verifier)
    client.post.side_effect = httpx.ConnectError("refused")

    result = await verifier.verify("any-token")
    assert result.valid is False
    assert result.error == "connection_error"


def test_verify_sync_success_with_service_identity():
    """verify_sync 同步路徑成功,payload 帶 token 與 service host/port (TC-auth-17)"""
    verifier = _make_verifier(service_host="10.0.0.1", service_port=8080)
    client = _install_mock_client(verifier)
    client.post.return_value = _mock_response(200, {"valid": True, "user_name": "u1"})

    result = verifier.verify_sync("sync-token")
    assert result.valid is True
    payload = client.post.call_args.kwargs["json"]
    assert payload == {
        "token": "sync-token",
        "service_host": "10.0.0.1",
        "service_port": 8080,
    }


def test_get_remote_verifier_singleton_lifecycle():
    """get_remote_verifier 首次無 URL → ValueError;有 URL 後回單例 (TC-auth-18)"""
    reset_remote_verifier()
    try:
        with pytest.raises(ValueError, match="token_server_url is required"):
            get_remote_verifier()
        v1 = get_remote_verifier("http://token-server.invalid:1")
        v2 = get_remote_verifier()  # 之後不需再給 URL
        assert v1 is v2
        assert v1.token_server_url == "http://token-server.invalid:1"  # 尾斜線已去除
    finally:
        reset_remote_verifier()


def test_sync_client_lazy_init_and_reuse():
    """_get_sync_client:首次建立、之後重用同一顆(懶初始化)。"""
    from src.auth.remote_auth import RemoteTokenVerifier
    v = RemoteTokenVerifier(token_server_url="http://localhost:1")
    c1 = v._get_sync_client()
    assert v._get_sync_client() is c1
    v.close()
