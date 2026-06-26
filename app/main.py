"""
FastAPI application entry point.

Startup:
  - Creates all DB tables (SQLModel.metadata.create_all).
  - Mounts asset and AI routers.
  - OpenAPI docs available at /docs.
"""
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.db import create_db_and_tables
from app.routers.assets import router as assets_router
from app.routers.ai import router as ai_router
from app.routers.graph import router as graph_router
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup."""
    create_db_and_tables()
    yield


app = FastAPI(
    title="DarkAtlas Asset Management System",
    description=(
        "A self-contained slice of the DarkAtlas Attack Surface Monitoring platform. "
        "Provides bulk asset ingest, deduplication, lifecycle tracking, and a "
        "LangChain-powered AI analysis layer (NL query, risk scoring, enrichment, report generation)."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(assets_router)
app.include_router(ai_router)
app.include_router(graph_router)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/", tags=["Health"])
def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "DarkAtlas Asset Management System",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health():
    """Detailed health check."""
    return {"status": "healthy", "version": "1.0.0"}
