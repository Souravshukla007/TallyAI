"""
TallyAI — FastAPI application entry point.

Start the server:
    uvicorn tallyai.main:app --reload
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Load .env from the backend directory (one level up from this file).
load_dotenv()

# ---------------------------------------------------------------------------
# App metadata
# ---------------------------------------------------------------------------
APP_VERSION = "0.1.0"

app = FastAPI(
    title="TallyAI",
    description="AI database consultant — safe, explainable, grounded.",
    version=APP_VERSION,
)

# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------
# ALLOWED_ORIGINS is a comma-separated list of origins.
# Defaults to the local Next.js dev server if the env var is absent.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
origins: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Tenant resolution middleware (Req 14.1, 14.4)
# ---------------------------------------------------------------------------
# The FastAPI API layer is the fixed trust boundary: the tenant is resolved
# here, once, from the caller's authenticated identity. In production that
# identity comes from a verified bearer token; for the MVP we accept an
# ``X-Tenant-Id`` header as a stand-in for the token-derived tenant.
#
# The resolved tenant is injected into ``request.state.tenant_id`` so any
# downstream handler can read the authenticated tenant without re-parsing the
# request.
#
# Existing MVP endpoints additionally accept ``tenant_id`` as a query parameter
# to scope their reads. When BOTH an authenticated tenant (header) and a
# query-param scope are present they MUST agree: a request authenticated as one
# tenant may not scope itself to — and thereby reach the connections, history,
# or execution-log entries of — a different tenant. A mismatch is denied with
# HTTP 403 (Req 14.4). When no header is supplied the query-param scope is used
# as-is, preserving backward compatibility with the MVP query-param contract.
TENANT_HEADER = "X-Tenant-Id"


@app.middleware("http")
async def tenant_resolution_middleware(request: Request, call_next):
    """Resolve the authenticated tenant and enforce single-tenant scope."""
    # Resolve the tenant from the (stubbed) bearer-token identity.
    authenticated_tenant = request.headers.get(TENANT_HEADER)
    request.state.tenant_id = authenticated_tenant

    # Defense in depth: a request may never reference another tenant's scope.
    if authenticated_tenant:
        requested_tenant = request.query_params.get("tenant_id")
        if requested_tenant is not None and requested_tenant != authenticated_tenant:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": {
                        "code": "cross_tenant_denied",
                        "message": (
                            "request references another tenant's resources; "
                            "the authenticated tenant may only access its own data"
                        ),
                    }
                },
            )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

from tallyai.api.connections import router as connections_router  # noqa: E402
from tallyai.api.eval import router as eval_router  # noqa: E402
from tallyai.api.metrics import router as metrics_router  # noqa: E402
from tallyai.api.runs import router as runs_router  # noqa: E402
from tallyai.api.schema import router as schema_router  # noqa: E402
from tallyai.api.stream import router as stream_router  # noqa: E402

app.include_router(connections_router, prefix="/api/v1")
app.include_router(schema_router, prefix="/api/v1")
app.include_router(runs_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(eval_router, prefix="/api/v1")
app.include_router(stream_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Health check endpoint. Returns 200 with status and version."""
    return {"status": "ok", "version": APP_VERSION}
