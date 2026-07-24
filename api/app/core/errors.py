"""RFC 9457 (problem+json) error model — see specs/04-api-spec.md § Conventions."""

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PROBLEM_JSON = "application/problem+json"


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


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return _problem_response(
        Problem(
            title="Internal Server Error",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
            instance=str(request.url.path),
        )
    )
