"""T2.3 / F-M14 and T2.4: CORS and API docs per environment profile."""

from src.main import cors_options


def test_production_without_origins_has_no_cors():
    assert cors_options(True, None, None) is None
    assert cors_options(True, "", None) is None
    assert cors_options(True, "*", None) is None


def test_production_explicit_origins_only_and_no_localhost_regex():
    opts = cors_options(True, "https://admin.example", r".*")
    assert opts["allow_origins"] == ["https://admin.example"]
    assert "allow_origin_regex" not in opts


def test_development_keeps_permissive_defaults():
    assert cors_options(False, "*", None)["allow_origins"] == ["*"]
    opts = cors_options(False, "http://10.0.0.5:3000", None)
    assert opts["allow_origin_regex"].startswith("^https?://(localhost")


def test_docs_follow_expose_flag(monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    import src.config as config
    import src.main as main

    monkeypatch.setattr(config, "EXPOSE_API_DOCS", False)
    try:
        app = importlib.reload(main).app
        client = TestClient(app)
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/docs").status_code == 404
        assert app.openapi()["info"]["title"]  # schema still buildable for contract tests
    finally:
        monkeypatch.undo()
        importlib.reload(main)
