
"""FastAPI error handler middleware for domain exceptions

This middleware catches domain exceptions and converts them to appropriate
HTTP responses with consistent error format.
"""

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
import traceback

from src.domain.exceptions import DomainException, get_http_status_for_exception
from src.log import get_api_logger

logger = get_api_logger()


async def domain_exception_handler(request: Request, exc: DomainException) -> JSONResponse:
    """Handle domain exceptions and convert to HTTP responses

    Args:
        request: FastAPI request object
        exc: Domain exception instance

    Returns:
        JSONResponse with error details
    """
    # Get appropriate HTTP status code
    status_code = get_http_status_for_exception(exc)

    # Build error response
    error_response = {
        "error": exc.error_code,
        "message": exc.message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "path": str(request.url.path)
    }

    # Add details if present
    if exc.details:
        error_response["details"] = exc.details

    # Log the error
    log_message = f"[{exc.error_code}] {exc.message}"
    if status_code >= 500:
        logger.error(f"{log_message} | path={request.url.path} | details={exc.details}")
    elif status_code >= 400:
        logger.warning(f"{log_message} | path={request.url.path}")

    return JSONResponse(status_code=status_code, content=error_response)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """捕捉所有非 DomainException 的例外(全 traceback log + 500 generic 回應)。

    HTTPException 顯式 re-raise,讓 FastAPI 原生 handler 處理 status code;不然會被
    這層 catch-all 吞成 500。

    Args:
        request: 觸發的 FastAPI Request。
        exc: 攔到的 exception。

    Returns:
        JSONResponse(500 + INTERNAL_SERVER_ERROR detail)。
    """
    if isinstance(exc, HTTPException):
        raise exc

    # Log full traceback for debugging
    error_traceback = traceback.format_exc()
    logger.error(
        f"Unhandled exception: {str(exc)}\n"
        f"Path: {request.url.path}\n"
        f"Traceback:\n{error_traceback}"
    )

    # Return generic error to client (don't expose internals)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred. Please try again later.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(request.url.path)
        }
    )


def register_error_handlers(app) -> None:
    """Register all error handlers with the FastAPI app

    Call this function in app.py after creating the FastAPI app instance.

    Args:
        app: FastAPI application instance

    Example:
        from fastapi import FastAPI
        from src.middleware.error_handler import register_error_handlers

        app = FastAPI()
        register_error_handlers(app)
    """
    # Register domain exception handler
    app.add_exception_handler(DomainException, domain_exception_handler)

    # Register generic exception handler (catch-all)
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("Error handlers registered successfully")
