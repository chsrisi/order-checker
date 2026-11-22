"""OTA update endpoints and the publish script (IMPLEMENTATION_PLAN T6.5, V2_DELTA Q5)."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from scripts import publish_client_release as pub
from src import config


@pytest.fixture
def releases(tmp_path, monkeypatch):
    target = tmp_path / "releases"
    monkeypatch.setattr(config, "CLIENT_RELEASES_DIR", str(target))
    return target


@pytest.fixture
def apk(tmp_path):
    def make(content=b"PK\x03\x04fake-apk"):
        path = tmp_path / f"build-{hashlib.md5(content).hexdigest()[:6]}.apk"
        path.write_bytes(content)
        return path

    return make


@pytest.fixture
def client():
    from src.main import app

    return TestClient(app)


def test_latest_is_404_until_something_is_published(client, releases):
    assert client.get("/v2/client/latest").status_code == 404


def test_dry_run_writes_nothing(releases, apk):
    meta = pub.publish(apk(), 1, "2.0.0", releases)
    assert meta["version_code"] == 1
    assert not releases.exists()


def test_publish_then_latest_and_download(client, releases, apk):
    content = b"PK\x03\x04release-one"
    meta = pub.publish(apk(content), 3, "2.0.0", releases, min_supported=2, confirm=True)
    assert meta["sha256"] == hashlib.sha256(content).hexdigest()

    body = client.get("/v2/client/latest").json()
    assert body["version_code"] == 3
    assert body["apk_url"] == "/v2/client/apk/3"
    assert body["sha256"] == meta["sha256"]
    assert body["min_supported_version_code"] == 2
    assert body["size_bytes"] == len(content)

    download = client.get(body["apk_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/vnd.android.package-archive"
    assert download.content == content


def test_update_endpoints_need_no_token_and_no_version_header(client, releases, apk):
    pub.publish(apk(), 5, "2.0.0", releases, min_supported=5, confirm=True)
    # Even an app far below the minimum must reach its update.
    assert client.get("/v2/client/latest").status_code == 200
    assert client.get("/v2/client/apk/5").status_code == 200


def test_unknown_or_invalid_apk_version_is_404_or_422(client, releases, apk):
    pub.publish(apk(), 2, "2.0.0", releases, confirm=True)
    assert client.get("/v2/client/apk/9").status_code == 404
    assert client.get("/v2/client/apk/0").status_code == 422
    assert client.get("/v2/client/apk/..%2Flatest.json").status_code in (404, 422)


def test_version_code_must_increase(releases, apk):
    pub.publish(apk(b"a"), 4, "2.0.0", releases, confirm=True)
    with pytest.raises(SystemExit, match="not higher"):
        pub.publish(apk(b"b"), 4, "2.0.1", releases, confirm=True)
    with pytest.raises(SystemExit, match="not higher"):
        pub.publish(apk(b"c"), 3, "1.9.9", releases, confirm=True)


def test_min_supported_is_kept_and_bounded(releases, apk):
    pub.publish(apk(b"a"), 2, "2.0.0", releases, min_supported=2, confirm=True)
    meta = pub.publish(apk(b"b"), 3, "2.0.1", releases, confirm=True)
    assert meta["min_supported_version_code"] == 2
    with pytest.raises(SystemExit, match="between"):
        pub.publish(apk(b"c"), 4, "2.0.2", releases, min_supported=5, confirm=True)


def test_new_release_raises_the_v2_gate(client, releases, apk):
    pub.publish(apk(b"a"), 2, "2.0.0", releases, confirm=True)
    headers = {"X-Client-Version": "2"}
    assert client.get("/v2/items/find?query=x", headers=headers).status_code in (401, 403)
    pub.publish(apk(b"b"), 3, "2.0.1", releases, min_supported=3, confirm=True)
    response = client.get("/v2/items/find?query=x", headers=headers)
    assert response.status_code == 426


def test_latest_json_is_the_last_file_written(releases, apk, monkeypatch):
    """A failed APK copy leaves the published release untouched."""
    pub.publish(apk(b"a"), 1, "2.0.0", releases, confirm=True)
    before = (releases / "latest.json").read_text()
    monkeypatch.setattr(pub, "sha256_of", lambda p: "x" if p.suffix == ".tmp" else "y")
    with pytest.raises(SystemExit, match="verification failed"):
        pub.publish(apk(b"b"), 2, "2.0.1", releases, confirm=True)
    assert (releases / "latest.json").read_text() == before
    assert json.loads(before)["version_code"] == 1
    assert not (releases / pub.apk_name(2)).exists()


def test_cli_dry_run_exit_code(releases, apk, capsys):
    assert pub.main([str(apk()), "--version-code", "1", "--version-name", "2.0.0"]) == 2
    assert (
        pub.main([str(apk()), "--version-code", "1", "--version-name", "2.0.0", "--confirm"]) == 0
    )
    assert (releases / "latest.json").exists()
