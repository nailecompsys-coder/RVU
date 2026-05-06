"""RVU Estimator — standalone FastAPI app on port 8003."""
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .models import RvuScan   # ensure RvuScan table is registered
from .auth import get_current_surgeon
from .routers import auth as auth_router
from .routers import scan as scan_router
from .routers import history as history_router

# Create rvu_scans table if it doesn't exist (other tables already exist in cal's DB)
RvuScan.__table__.create(bind=engine, checkfirst=True)

app = FastAPI(title="RVU Estimator", version="0.1.0", docs_url=None, redoc_url=None)

STATIC = Path(__file__).resolve().parent / "static"

app.include_router(auth_router.router)
app.include_router(scan_router.router)
app.include_router(history_router.router)

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
def root(surgeon_device=Depends(get_current_surgeon)):
    return FileResponse(
        str(STATIC / "scanner.html"),
        headers={"Cache-Control": "no-store, no-cache"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "app": "rvu"}
