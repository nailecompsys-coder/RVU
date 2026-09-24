from app.spa_fallback import should_serve_spa


def test_portal_routes_serve_spa():
    assert should_serve_spa("") is True
    assert should_serve_spa("login") is True
    assert should_serve_spa("staff/history") is True


def test_unknown_api_paths_do_not_serve_spa():
    assert should_serve_spa("api") is False
    assert should_serve_spa("api/health") is False
    assert should_serve_spa("api/v1/rvu/health") is False
    assert should_serve_spa("api/v1/rvu/dashboard") is False
    assert should_serve_spa("api/v1/auth/session") is False
    assert should_serve_spa("/api/v1/rvu/me") is False


def test_secret_probe_paths_do_not_serve_spa():
    assert should_serve_spa(".env") is False
    assert should_serve_spa(".git/HEAD") is False
    assert should_serve_spa(".ssh/id_rsa") is False
