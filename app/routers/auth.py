"""
Minimal auth router for the RVU app.
Surgeons authenticate via the shared surgeon_token cookie from cal.
If they don't have one, they're sent to cal to register.
"""
import os

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from ..auth import get_current_surgeon

router = APIRouter()

CAL_URL = os.environ.get("CAL_URL", "https://cal.midfloridasurgical.com")


@router.get("/logout")
def logout():
    """Log out — send back to cal's logout so the shared cookie is cleared."""
    return RedirectResponse(f"{CAL_URL}/surgeon/logout", status_code=302)
