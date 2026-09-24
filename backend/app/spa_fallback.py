"""Decide which unmatched paths may serve the portal SPA."""


def should_serve_spa(full_path: str) -> bool:
    """Portal HTML is only for browser routes. API and secret-probe paths must 404."""
    path = (full_path or "").lstrip("/")
    if path == "api" or path.startswith("api/"):
        return False
    first = path.split("/", 1)[0]
    if first.startswith("."):
        return False
    return True
