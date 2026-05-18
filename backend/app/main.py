"""
RVU standalone API — runs against the RVU-owned database boundary for identity and scan data.
Run from `backend/`:  uvicorn app.main:app --host 0.0.0.0 --port 3010
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load api/.env before any app imports — rvu_cpt_service reads ANTHROPIC_API_KEY at import time.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Connection, inspect, text

# Register RVU-owned identity ORM + RVU business models
from app import models_identity  # noqa: F401
from app import models_rvu  # noqa: F401
from app.api.routes_auth import router as auth_router
from app.api.routes_rvu import portal_router, router as rvu_router
from app.database import Base, engine
from app.version_info import version_payload

# Dev: repo root `frontend/dist`. Docker: set RVU_STATIC_DIST=/app/frontend/dist
_DIST = os.environ.get("RVU_STATIC_DIST") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)


_SCHEMA_INIT_LOCK_ID = 3045121101


def _ensure_rvu_schema(conn: Connection) -> None:
    inspector = inspect(conn)
    if not inspector.has_table("rvu_scans"):
        return
    columns = {col["name"] for col in inspector.get_columns("rvu_scans")}
    if "patient_name" not in columns:
        conn.execute(text("ALTER TABLE rvu_scans ADD COLUMN IF NOT EXISTS patient_name VARCHAR(255)"))
    if "scan_status" not in columns:
        conn.execute(text("ALTER TABLE rvu_scans ADD COLUMN IF NOT EXISTS scan_status VARCHAR(32) DEFAULT 'verified'"))
    if "main_cpt" not in columns:
        conn.execute(text("ALTER TABLE rvu_scans ADD COLUMN IF NOT EXISTS main_cpt VARCHAR(32)"))
    if "main_cpt_status" not in columns:
        conn.execute(text("ALTER TABLE rvu_scans ADD COLUMN IF NOT EXISTS main_cpt_status VARCHAR(16)"))
    if "review_reason" not in columns:
        conn.execute(text("ALTER TABLE rvu_scans ADD COLUMN IF NOT EXISTS review_reason VARCHAR(255)"))
    if "client_request_id" not in columns:
        conn.execute(text("ALTER TABLE rvu_scans ADD COLUMN IF NOT EXISTS client_request_id VARCHAR(128)"))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_rvu_scans_surgeon_request_id "
            "ON rvu_scans (surgeon_id, client_request_id)"
        )
    )
    conn.execute(text("UPDATE rvu_scans SET scan_status = 'verified' WHERE scan_status IS NULL"))


def _initialize_schema_once() -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": _SCHEMA_INIT_LOCK_ID})
        try:
            Base.metadata.create_all(bind=conn, checkfirst=True)
            _ensure_rvu_schema(conn)
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": _SCHEMA_INIT_LOCK_ID})


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tables may already exist; create_all is safe with checkfirst
    _initialize_schema_once()
    yield


app = FastAPI(title="Mid Florida Surgical — RVU", version="0.1.0", lifespan=lifespan)

_origins = os.environ.get("RVU_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(rvu_router)
app.include_router(portal_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "rvu"}


@app.get("/api/version")
def api_version():
    """Deploy/git/app metadata for native clients, support, and scripts (no auth)."""
    return version_payload()


if os.path.isdir(_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="rvu-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Serve the React SPA index.html for all non-API routes."""
        return FileResponse(os.path.join(_DIST, "index.html"))
