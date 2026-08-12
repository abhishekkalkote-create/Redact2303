"""RFC 9457 (problem+json) error model — see specs/04-api-spec.md § Conventions."""

import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import StatementError

PROBLEM_JSON = "application/problem+json"

logger = logging.getLogger(__name__)

# specs/02-architecture.md § Observability: "RLS policy violation attempts (log + page
# on-call)." A WITH CHECK failure (INSERT/UPDATE) is the one RLS outcome that raises an
# exception at all — SELECT/UPDATE/DELETE just silently filter rows, nothing to catch
# here for those. This is Postgres's own fixed error text, not app-controlled.
_RLS_VIOLATION_MARKER = "row-level security policy"


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[dict] | None = None


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        errors: list[dict] | None = None,
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.type = type_
        self.errors = errors


class NotFoundError(ApiError):
    """Used for both missing resources AND cross-tenant foreign IDs (never leak existence)."""

    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, "Not Found", detail)


class ConflictError(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(status.HTTP_409_CONFLICT, "Conflict", detail)


class ForbiddenError(ApiError):
    def __init__(self, detail: str = "Forbidden") -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, "Forbidden", detail)


def _problem_response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_JSON,
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _problem_response(
        Problem(
            type=exc.type,
            title=exc.title,
            status=exc.status_code,
            detail=exc.detail,
            instance=str(request.url.path),
            errors=exc.errors,
        )
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _problem_response(
        Problem(
            title="Validation Error",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One or more fields failed validation.",
            instance=str(request.url.path),
            errors=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
        )
    )


def _safe_exception_summary(exc: Exception) -> str:
    """SQLAlchemy's StatementError.__str__ appends "[SQL: ...] [parameters: (...)]" to
    the underlying driver error — the parameters half is the literal bound values of
    whatever INSERT/UPDATE failed, which can be customer content (a name, a
    justification, anything that statement was carrying). `.orig` is the bare DBAPI
    exception underneath, with no such appendage — safe to log. NEVER log str(exc)
    directly for a StatementError, and never pass one to logger's exc_info= either:
    traceback rendering's last line calls that same unsafe __str__."""
    if isinstance(exc, StatementError):
        return str(exc.orig)
    return str(exc)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    summary = _safe_exception_summary(exc)
    context = {
        "path": request.url.path,
        "method": request.method,
        "org_id": request.headers.get("x-org-id"),
    }
    if _RLS_VIOLATION_MARKER in summary:
        logger.warning("rls_violation", extra={"event": "rls_violation", **context})
    elif isinstance(exc, StatementError):
        logger.error(
            "database_error",
            extra={"event": "database_error", "exception_type": type(exc.orig).__name__, **context},
        )
    else:
        logger.error(
            "unhandled_exception",
            extra={"event": "unhandled_exception", "exception_type": type(exc).__name__, **context},
            exc_info=exc,
        )
    return _problem_response(
        Problem(
            title="Internal Server Error",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
            instance=str(request.url.path),
        )
    )
