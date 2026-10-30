"""Stable, machine-readable API errors. Never leak tracebacks to clients."""

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class AppError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or {}


def not_found(what: str) -> AppError:
    return AppError(404, "not_found", f"{what} not found")


def forbidden(message: str = "You do not have permission for this action") -> AppError:
    return AppError(403, "forbidden", message)


def conflict(error_code: str, message: str, details: dict | None = None) -> AppError:
    return AppError(409, error_code, message, details)


def _body(error_code: str, message: str, details: dict | None = None) -> dict:
    body: dict[str, Any] = {"error_code": error_code, "message": message, "request_id": request_id_var.get()}
    if details:
        body["details"] = details
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_var.set(rid[:64])
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = rid[:64]
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.error_code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(
            status_code=422, content=_body("validation_error", "Request validation failed", {"errors": errors})
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException):
        code = {401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content=_body("internal_error", "Unexpected server error"))
