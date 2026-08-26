"""RFC 9457 problem+json errors for the api.

Every error body the api emits is ``application/problem+json``. Routes raise
:class:`Problem`; app-wide handlers registered by :func:`register_handlers`
convert it — and FastAPI's own 404/422/500 paths — so nothing ever emits the
default ``{"detail": ...}`` shape.

Problem ``type`` URIs follow ``urn:meetingminer:problem:<slug>``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"

# One misconfiguration, one problem type. `MM_DROPS_ROOT` is reachable through
# two doors — intake converting a posted path, and replay resolving a recorded
# one — and an operator reading the response has to be able to tell *which*
# root is broken, so the drops root has its own slug and the content root keeps
# `media-root-unconfigured`. Defined here because both routers already import
# this module and neither should import the other for a string.
DROPS_ROOT_UNCONFIGURED = "drops-root-unconfigured"


class ProblemDetails(BaseModel):
    """OpenAPI shape of an RFC 9457 error body (extension members allowed)."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str

_STATUS_TITLES = {
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    422: "Unprocessable Content",
    500: "Internal Server Error",
}


class Problem(Exception):
    """An RFC 9457 problem a route raises; the app-wide handler serializes it."""

    def __init__(
        self,
        status: int,
        slug: str,
        detail: str,
        title: str | None = None,
        **extensions: Any,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.slug = slug
        self.detail = detail
        self.title = title or _STATUS_TITLES.get(status, "Error")
        self.extensions = extensions


_RESERVED_MEMBERS = frozenset({"type", "title", "status", "detail"})


def problem_response(
    status: int,
    slug: str,
    detail: str,
    title: str | None = None,
    headers: dict[str, str] | None = None,
    **extensions: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"urn:meetingminer:problem:{slug}",
        "title": title or _STATUS_TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
    }
    # Extensions may never overwrite the RFC 9457 members.
    body.update({k: v for k, v in extensions.items() if k not in _RESERVED_MEMBERS})
    return JSONResponse(
        status_code=status, content=body, media_type=PROBLEM_MEDIA_TYPE, headers=headers
    )


async def _handle_problem(_request: Request, exc: Problem) -> JSONResponse:
    return problem_response(
        exc.status, exc.slug, exc.detail, title=exc.title, **exc.extensions
    )


async def _handle_http_exception(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    slug = "not-found" if exc.status_code == 404 else "http-error"
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    # Preserve headers such as Allow on 405 responses.
    return problem_response(exc.status_code, slug, detail, headers=exc.headers)


async def _handle_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "location": ".".join(str(part) for part in error.get("loc", ())),
            "message": str(error.get("msg", "invalid value")),
        }
        for error in exc.errors()
    ]
    return problem_response(
        422,
        "invalid-request",
        "request failed validation: "
        + "; ".join(f"{e['location']}: {e['message']}" for e in errors),
        errors=errors,
    )


async def _handle_unexpected(_request: Request, _exc: Exception) -> JSONResponse:
    return problem_response(
        500, "internal-error", "an unexpected error occurred", title="Internal Server Error"
    )


def register_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Problem, _handle_problem)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected)
