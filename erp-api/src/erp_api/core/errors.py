import logging
import math

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokClientError,
    TikTokRateLimitError,
    TikTokTimeoutError,
)

logger = logging.getLogger("erp_api.errors")


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "code": code,
            "message": message,
            "requestId": _request_id(request),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(TikTokRateLimitError)
    async def handle_tiktok_rate_limit(
        request: Request, exc: TikTokRateLimitError
    ) -> JSONResponse:
        headers = (
            {"Retry-After": str(math.ceil(exc.retry_after_seconds))}
            if exc.retry_after_seconds is not None
            else None
        )
        return _error_response(
            request,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "upstream_rate_limited",
            "External shop API rate limit reached.",
            headers,
        )

    @app.exception_handler(TikTokTimeoutError)
    async def handle_tiktok_timeout(
        request: Request, exc: TikTokTimeoutError
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_504_GATEWAY_TIMEOUT,
            "upstream_timeout",
            "External shop API timed out.",
        )

    @app.exception_handler(TikTokApiError)
    async def handle_tiktok_api_error(
        request: Request, exc: TikTokApiError
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_502_BAD_GATEWAY,
            "upstream_error",
            "External shop API rejected the request.",
        )

    @app.exception_handler(TikTokClientError)
    async def handle_tiktok_client_error(
        request: Request, exc: TikTokClientError
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_502_BAD_GATEWAY,
            "upstream_error",
            "External shop API request failed.",
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        messages = {
            status.HTTP_400_BAD_REQUEST: ("bad_request", "Request is invalid."),
            status.HTTP_404_NOT_FOUND: ("not_found", "Resource not found."),
            status.HTTP_405_METHOD_NOT_ALLOWED: (
                "method_not_allowed",
                "Method not allowed.",
            ),
            status.HTTP_409_CONFLICT: (
                "conflict",
                "Request conflicts with the current state.",
            ),
            status.HTTP_401_UNAUTHORIZED: ("unauthorized", "Authentication failed."),
            status.HTTP_403_FORBIDDEN: ("forbidden", "Permission denied."),
            status.HTTP_429_TOO_MANY_REQUESTS: (
                "too_many_requests",
                "Too many requests.",
            ),
            status.HTTP_503_SERVICE_UNAVAILABLE: (
                "service_unavailable",
                "Service is unavailable.",
            ),
            status.HTTP_502_BAD_GATEWAY: ("upstream_error", "External service failed."),
            status.HTTP_501_NOT_IMPLEMENTED: (
                "not_implemented",
                "This integration is not configured yet.",
            ),
        }
        code, message = messages.get(
            exc.status_code, ("request_failed", "Request failed.")
        )
        return _error_response(
            request, exc.status_code, code, message, dict(exc.headers or {})
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        logger.info(
            "request_validation_failed",
            extra={
                "event": "request_validation_failed",
                "method": request.method,
                "path": request.url.path,
                "request_id": _request_id(request),
                "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
            },
        )
        del exc
        return _error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "Request validation failed.",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "unhandled_exception",
            extra={
                "event": "unhandled_exception",
                "method": request.method,
                "path": request.url.path,
                "request_id": _request_id(request),
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            },
        )
        del exc
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected error occurred.",
        )
