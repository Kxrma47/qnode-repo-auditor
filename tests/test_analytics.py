import hashlib
import sqlite3
from base64 import b64encode
from datetime import UTC, datetime, timedelta

from qnode_auditor.analytics import VisitorStore
from qnode_auditor.app import create_app


def test_store_counts_browsers_and_page_views_across_connections(tmp_path):
    path = tmp_path / "visitors.sqlite3"
    store = VisitorStore(str(path))
    now = datetime(2026, 9, 19, tzinfo=UTC)
    store.record("a" * 32, now=now - timedelta(days=31))
    store.record("a" * 32, now=now)
    store.record("b" * 32, now=now)
    assert VisitorStore(str(path)).snapshot(now=now) == {
        "unique_browsers": 2,
        "recent_browsers": 2,
        "page_views": 3,
        "since": (now - timedelta(days=31)).isoformat(),
    }
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT visitor_hash FROM visitors").fetchall()
    assert {row[0] for row in rows} == {
        hashlib.sha256(token.encode()).hexdigest() for token in ("a" * 32, "b" * 32)
    }


def test_empty_store_and_invalid_path(tmp_path):
    assert VisitorStore(str(tmp_path / "empty.sqlite3")).snapshot()["page_views"] == 0
    try:
        VisitorStore("relative.sqlite3")
    except ValueError as error:
        assert "absolute" in str(error)
    else:
        raise AssertionError("relative storage path must be rejected")


def test_private_website_metrics_and_beacon_validation(monkeypatch, tmp_path):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def app_installation_count(self):
            return 7

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    path = tmp_path / "visitors.sqlite3"
    app = create_app(
        {
            "TESTING": True,
            "VISITOR_METRICS_DB": str(path),
            "OWNER_METRICS_TOKEN": "owner-secret",
        }
    )
    first = app.test_client()
    second = app.test_client()
    auth = {"Authorization": "Basic " + b64encode(b"Kxrma47:owner-secret").decode()}
    assert first.get("/owner/metrics").status_code == 401
    assert first.post("/api/visit", headers={"X-QNode-Visit": "1"}).status_code == 403
    index = first.get("/")
    assert b'data-visitor-metrics="true"' in index.data
    assert "HttpOnly" in index.headers["Set-Cookie"]
    assert first.post("/api/visit").status_code == 403
    wrong_origin = {"X-QNode-Visit": "1", "Origin": "https://other.example"}
    assert first.post("/api/visit", headers=wrong_origin).status_code == 403
    headers = {"X-QNode-Visit": "1", "Origin": "https://localhost"}
    assert first.post("/api/visit", headers=headers).status_code == 204
    assert first.post("/api/visit", headers=headers).status_code == 204
    second.get("/")
    assert second.post("/api/visit", headers=headers).status_code == 204
    assert first.post("/api/visit", headers={**headers, "DNT": "1"}).status_code == 403
    response = first.get("/owner/metrics", headers=auth)
    assert response.status_code == 200
    assert b"2 <small>approximate unique browsers</small>" in response.data
    assert b"3 page views" in response.data
    assert response.headers["Cache-Control"] == "no-store, private"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 2


def test_tracking_disabled_or_dnt_without_persistent_db(tmp_path):
    disabled = create_app({"TESTING": True, "VISITOR_METRICS_DB": ""}).test_client()
    assert disabled.get("/").headers.get("Set-Cookie") is None
    assert disabled.post("/api/visit").status_code == 404
    client = create_app(
        {"TESTING": True, "VISITOR_METRICS_DB": str(tmp_path / "visitors.sqlite3")}
    ).test_client()
    assert client.get("/", headers={"DNT": "1"}).headers.get("Set-Cookie") is None
    assert not (tmp_path / "visitors.sqlite3").exists()


def test_visitor_store_failure_does_not_break_scanner(tmp_path):
    client = create_app(
        {"TESTING": True, "VISITOR_METRICS_DB": str(tmp_path / "missing" / "db.sqlite3")}
    ).test_client()
    assert client.get("/").status_code == 200
    assert client.post("/api/visit", headers={"X-QNode-Visit": "1"}).status_code == 503
