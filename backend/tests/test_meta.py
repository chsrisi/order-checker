"""T4.7: GET /meta is public and carries only non-sensitive fields."""

from fastapi.testclient import TestClient

from src import config
from src.main import app


def test_meta_is_public_and_minimal(monkeypatch):
    monkeypatch.setenv("STOCK_LOCATION_MODE", "single")
    body = TestClient(app).get("/meta").json()  # no Authorization header
    assert set(body) == {
        "api_version",
        "client_contract",
        "app_env",
        "stock_location_mode",
        "features",
    }
    assert body["api_version"] == config.API_VERSION
    assert body["client_contract"] == {"min": 1, "max": 1}
    assert body["app_env"] == "development"
    assert body["stock_location_mode"] == "single"
    assert all(isinstance(v, bool) for v in body["features"].values())


def test_meta_leaks_no_configuration_values():
    text = TestClient(app).get("/meta").text.lower()
    for needle in ("postgres", "redis", "password", "secret", "token", "http://", "https://"):
        assert needle not in text
