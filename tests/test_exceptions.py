"""Unit tests for src/domain/exceptions.py — Domain 例外階層 + HTTP 狀態映射

不依賴 DB / vLLM / 任何外部服務 — 純邏輯測試。
跑法:cd agentic_rag && uv run pytest tests/test_exceptions.py -v
對應文件:docs/testing/specs/SPEC-exceptions.md、docs/testing/test-cases/TC-exceptions.md
"""

import pytest

from src.domain.exceptions import (
    DomainException,
    ResourceNotFoundError,
    FolderNotFoundError,
    RAGFileNotFoundError as DomainFileNotFoundError,  # M11: 已改名不再遮蔽 builtin
    FileIndexNotFoundError,
    UnauthorizedAccessError,
    InvalidTokenError,
    ValidationError,
    ConflictError,
    RAGOperationError,
    FileIndexingError,
    QueryExecutionError,
    get_http_status_for_exception,
)


# ============================================================================
# DomainException 基底
# ============================================================================

def test_domain_exception_attributes_and_default_details():
    """message / error_code 正確保存,details 未給時預設空 dict (TC-exceptions-01)"""
    exc = DomainException(message="something broke", error_code="SOME_CODE")
    assert exc.message == "something broke"
    assert exc.error_code == "SOME_CODE"
    assert exc.details == {}


def test_domain_exception_str_and_inheritance():
    """str(exc) 等於 message,且為標準 Exception 子類 (TC-exceptions-02)"""
    exc = DomainException(message="msg here", error_code="X")
    assert str(exc) == "msg here"
    assert isinstance(exc, Exception)


def test_to_dict_without_details():
    """details 為空時 to_dict 只含 error 與 message 兩鍵 (TC-exceptions-03)"""
    exc = DomainException(message="m", error_code="CODE")
    assert exc.to_dict() == {"error": "CODE", "message": "m"}


def test_to_dict_with_details():
    """details 非空時 to_dict 附帶 details 鍵 (TC-exceptions-04)"""
    exc = DomainException(message="m", error_code="CODE", details={"k": "v"})
    assert exc.to_dict() == {"error": "CODE", "message": "m", "details": {"k": "v"}}


# ============================================================================
# ResourceNotFoundError 家族 (404)
# ============================================================================

def test_resource_not_found_default_message_and_code():
    """自動組 message、error_code 為 {TYPE}_NOT_FOUND,details 含 str 化 identifier (TC-exceptions-05)"""
    exc = ResourceNotFoundError(resource_type="folder", identifier=42)
    assert exc.message == "folder not found: 42"
    assert exc.error_code == "FOLDER_NOT_FOUND"
    assert exc.details == {"resource_type": "folder", "identifier": "42"}


def test_resource_not_found_custom_message():
    """自訂 message 覆蓋預設格式 (TC-exceptions-06)"""
    exc = ResourceNotFoundError(resource_type="file", identifier="abc", message="custom words")
    assert exc.message == "custom words"
    assert exc.error_code == "FILE_NOT_FOUND"


def test_folder_not_found_by_id():
    """以 folder_id 建立時 identifier 用 id (TC-exceptions-07)"""
    exc = FolderNotFoundError(folder_id=7)
    assert exc.error_code == "FOLDER_NOT_FOUND"
    assert exc.details["identifier"] == "7"


def test_folder_not_found_by_name():
    """只給 folder_name 時 identifier 用名稱 (TC-exceptions-08)"""
    exc = FolderNotFoundError(folder_name="財報")
    assert exc.details["identifier"] == "財報"
    assert "財報" in exc.message


def test_file_not_found():
    """FILE_NOT_FOUND code 與 file_id identifier (TC-exceptions-09)"""
    exc = DomainFileNotFoundError(file_id="f-123")
    assert exc.error_code == "FILE_NOT_FOUND"
    assert exc.details == {"resource_type": "file", "identifier": "f-123"}


def test_file_index_not_found():
    """FILE_INDEX_NOT_FOUND code 與「尚未索引」語意 message (TC-exceptions-10)"""
    exc = FileIndexNotFoundError(file_id="f-9")
    assert exc.error_code == "FILE_INDEX_NOT_FOUND"
    assert exc.message == "File f-9 has not been indexed yet"
    assert exc.details["identifier"] == "f-9"


# ============================================================================
# 授權類 (401 / 403)
# ============================================================================

def test_unauthorized_without_reason():
    """無 reason 時 message 只含資源資訊 (TC-exceptions-11)"""
    exc = UnauthorizedAccessError(resource_type="folder", resource_id=5)
    assert exc.error_code == "UNAUTHORIZED_ACCESS"
    assert exc.message == "Not authorized to access folder: 5"
    assert exc.details == {"resource_type": "folder", "resource_id": "5"}


def test_unauthorized_with_reason():
    """有 reason 時附加至 message 尾端 (TC-exceptions-12)"""
    exc = UnauthorizedAccessError(resource_type="file", resource_id="x", reason="not owner")
    assert exc.message == "Not authorized to access file: x - not owner"


def test_invalid_token_default_and_custom_reason():
    """INVALID_TOKEN code;預設與自訂 reason 均直接作為 message (TC-exceptions-13)"""
    default_exc = InvalidTokenError()
    assert default_exc.error_code == "INVALID_TOKEN"
    assert default_exc.message == "Invalid or expired token"
    custom_exc = InvalidTokenError(reason="token revoked")
    assert custom_exc.message == "token revoked"


# ============================================================================
# ValidationError (400)
# ============================================================================

def test_validation_error_with_value():
    """value 非 None 時 details 含 str 化 invalid_value (TC-exceptions-14)"""
    exc = ValidationError(field="top_k", message="must be positive", value=-3)
    assert exc.error_code == "VALIDATION_ERROR"
    assert exc.message == "Validation failed for top_k: must be positive"
    assert exc.details == {"field": "top_k", "invalid_value": "-3"}


def test_validation_error_without_value():
    """value 為 None 時 details 不含 invalid_value (TC-exceptions-15)"""
    exc = ValidationError(field="query", message="empty")
    assert exc.details == {"field": "query"}
    assert "invalid_value" not in exc.details


# ============================================================================
# ConflictError (409)
# ============================================================================

def test_conflict_with_resource():
    """有 resource 時進 details (TC-exceptions-16)"""
    exc = ConflictError(message="already indexing", resource="file f-1")
    assert exc.error_code == "CONFLICT"
    assert exc.details == {"resource": "file f-1"}


def test_conflict_without_resource():
    """無 resource 時 details 為空 dict (TC-exceptions-17)"""
    exc = ConflictError(message="state conflict")
    assert exc.details == {}


# ============================================================================
# RAG 操作類 (500)
# ============================================================================

def test_rag_operation_error_code_from_operation():
    """error_code 由 operation 大寫組出 RAG_{OP}_ERROR (TC-exceptions-18)"""
    exc = RAGOperationError(operation="indexing", reason="disk full")
    assert exc.error_code == "RAG_INDEXING_ERROR"
    assert exc.message == "RAG indexing failed: disk full"
    assert exc.details == {}


def test_file_indexing_error():
    """RAG_INDEXING_ERROR code,details 含 file_id (TC-exceptions-19)"""
    exc = FileIndexingError(file_id="f-7", reason="parse failed")
    assert exc.error_code == "RAG_INDEXING_ERROR"
    assert exc.details == {"file_id": "f-7"}
    assert "parse failed" in exc.message


def test_query_execution_error_with_folder():
    """有 folder_id 時 details 同時含 query 與 folder_id (TC-exceptions-20)"""
    exc = QueryExecutionError(query="財報重點", reason="timeout", folder_id=3)
    assert exc.error_code == "RAG_QUERY_ERROR"
    assert exc.details == {"query": "財報重點", "folder_id": 3}


def test_query_execution_error_without_folder():
    """無 folder_id 時 details 只含 query (TC-exceptions-21)"""
    exc = QueryExecutionError(query="q", reason="r")
    assert exc.details == {"query": "q"}
    assert "folder_id" not in exc.details


# ============================================================================
# get_http_status_for_exception
# ============================================================================

@pytest.mark.parametrize(
    "exc, expected_status",
    [
        (ValidationError(field="f", message="bad"), 400),
        (InvalidTokenError(), 401),
        (UnauthorizedAccessError(resource_type="folder", resource_id=1), 403),
        (FolderNotFoundError(folder_id=1), 404),
        (DomainFileNotFoundError(file_id="f1"), 404),
        (FileIndexNotFoundError(file_id="f1"), 404),
        (ConflictError(message="c"), 409),
        (FileIndexingError(file_id="f1", reason="r"), 500),
        (QueryExecutionError(query="q", reason="r"), 500),
    ],
    ids=[
        "validation-400", "token-401", "unauthorized-403",
        "folder-404", "file-404", "file-index-404",
        "conflict-409", "indexing-500", "query-500",
    ],
)
def test_http_status_mapping(exc, expected_status):
    """每個已知 error_code 映射到對應 HTTP status (TC-exceptions-22)"""
    assert get_http_status_for_exception(exc) == expected_status


def test_http_status_unknown_code_defaults_to_500():
    """未知 error_code(含未列表的 RAG 操作)一律回 500 (TC-exceptions-23)"""
    assert get_http_status_for_exception(DomainException("m", "TOTALLY_UNKNOWN")) == 500
    # RAG_EMBEDDING_ERROR 不在映射表,也走預設 500
    assert get_http_status_for_exception(RAGOperationError("embedding", "r")) == 500


def test_all_exceptions_inherit_domain_exception():
    """全家族皆為 DomainException 子類,可被單一 except 捕捉 (TC-exceptions-24)"""
    instances = [
        ResourceNotFoundError("folder", 1),
        FolderNotFoundError(folder_id=1),
        DomainFileNotFoundError(file_id="f"),
        FileIndexNotFoundError(file_id="f"),
        UnauthorizedAccessError("file", "x"),
        InvalidTokenError(),
        ValidationError("f", "m"),
        ConflictError("m"),
        RAGOperationError("query", "r"),
        FileIndexingError("f", "r"),
        QueryExecutionError("q", "r"),
    ]
    for exc in instances:
        assert isinstance(exc, DomainException)
