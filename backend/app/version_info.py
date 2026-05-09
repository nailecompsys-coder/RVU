"""Runtime RVU version and build metadata for /api/version and tooling."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app import __version__


def _repo_root() -> Path:
    # backend/app/version_info.py -> rvu repository root
    return Path(__file__).resolve().parents[2]


def _git_revision(repo: Path) -> tuple[str | None, bool]:
    """Return (short_sha_or_none, is_dirty)."""
    try:
        cp = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        sha = (cp.stdout or "").strip() or None
        if cp.returncode != 0:
            sha = None
        st = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        dirty = bool((st.stdout or "").strip())
        return sha, dirty
    except (OSError, subprocess.TimeoutExpired):
        return None, False


def _frontend_package_version(repo: Path) -> str | None:
    pkg = repo / "frontend" / "package.json"
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
        v = data.get("version")
        return str(v).strip() if v else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def version_payload() -> dict[str, Any]:
    """Serializable version bundle (safe for JSON)."""
    repo = _repo_root()
    sha, dirty = _git_revision(repo)
    out: dict[str, Any] = {
        "service": "rvu",
        "version": __version__,
        "api_prefix": "/api/v1",
    }
    if sha:
        out["git_commit"] = sha
    out["git_dirty"] = dirty
    bid = os.environ.get("RVU_BUILD_ID", "").strip()
    if bid:
        out["build_id"] = bid
    fv = _frontend_package_version(repo)
    if fv:
        out["frontend_package_version"] = fv
    return out
