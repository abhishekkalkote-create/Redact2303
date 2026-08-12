from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import (
    ApiError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.routers import (
    audit,
    auth,
    billing,
    billing_webhooks,
    dashboard,
    documents,
    exemption_codes,
    exports,
    health,
    internal_cron,
    invites,
    manuals,
    members,
    orgs,
    platform,
    requests,
    review,
    rules,
    support_grants,
    usage,
    webhooks,
)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "AI-assisted, human-verified document redaction. Every endpoint below is org-scoped: "
        "authenticate with `POST /v1/auth/dev-login` (local/dev only) or a real Cognito token, "
        "then pass it as `Authorization: Bearer <token>`. Multi-org users additionally pass "
        "`X-Org-Id` to select which org a request applies to. See the docs site "
        "(redactproof.com/docs) for a narrative walkthrough of the upload -> review -> export flow."
    ),
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Starlette's add_exception_handler stub wants Callable[[Request, Exception], ...] exactly;
# our handlers are correctly typed for their specific exception, which mypy sees as a
# contravariance mismatch even though this is FastAPI's own documented pattern.
app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(health.router)
app.include_router(internal_cron.router)
app.include_router(billing_webhooks.router)
app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(orgs.router, prefix=settings.api_v1_prefix)
app.include_router(members.router, prefix=settings.api_v1_prefix)
app.include_router(invites.router, prefix=settings.api_v1_prefix)
app.include_router(documents.router, prefix=settings.api_v1_prefix)
app.include_router(review.router, prefix=settings.api_v1_prefix)
app.include_router(exports.router, prefix=settings.api_v1_prefix)
app.include_router(exemption_codes.router, prefix=settings.api_v1_prefix)
app.include_router(requests.router, prefix=settings.api_v1_prefix)
app.include_router(audit.router, prefix=settings.api_v1_prefix)
app.include_router(dashboard.router, prefix=settings.api_v1_prefix)
app.include_router(webhooks.router, prefix=settings.api_v1_prefix)
app.include_router(rules.router, prefix=settings.api_v1_prefix)
app.include_router(manuals.router, prefix=settings.api_v1_prefix)
app.include_router(billing.router, prefix=settings.api_v1_prefix)
app.include_router(usage.router, prefix=settings.api_v1_prefix)
app.include_router(platform.router, prefix=settings.api_v1_prefix)
app.include_router(support_grants.router, prefix=settings.api_v1_prefix)
