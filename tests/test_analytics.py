import hashlib
import sqlite3
from base64 import b64encode
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from qnode_auditor.analytics import PostgresVisitorStore, VisitorStore, metrics_error_category
from qnode_auditor.app import create_app
from qnode_auditor.github import TreeSnapshot


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
        "repository_scans": 0,
        "pull_request_scans": 0,
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


def test_postgres_backend_configuration_and_failure_is_private(monkeypatch):
    with pytest.raises(ValueError, match="PostgreSQL URL"):
        PostgresVisitorStore("/tmp/not-a-postgres-url")
    with pytest.raises(ValueError, match="only one"):
        create_app(
            {
                "TESTING": True,
                "VISITOR_METRICS_DB": "/tmp/visitors.sqlite3",
                "VISITOR_METRICS_URL": "postgresql://example.invalid/qnode",
            }
        )

    class UnavailableStore:
        def __init__(self, url):
            assert url == "postgresql://example.invalid/qnode"

        def record(self, token):
            raise psycopg.OperationalError("credential-must-not-be-shown")

    monkeypatch.setattr("qnode_auditor.app.PostgresVisitorStore", UnavailableStore)
    client = create_app(
        {
            "TESTING": True,
            "VISITOR_METRICS_URL": "postgresql://example.invalid/qnode",
        }
    ).test_client()
    assert client.get("/health").json["visitor_metrics_configured"] is True
    client.get("/")
    response = client.post("/api/visit", headers={"X-QNode-Visit": "1"})
    assert response.status_code == 503
    assert b"credential" not in response.data


def test_metrics_diagnostics_never_echo_connection_details():
    cases = {
        "SSL error: certificate verify failed": "tls_certificate",
        "password authentication failed for user 'private'": "authentication",
        "could not translate host name secret.example": "dns",
        "connection timed out": "timeout",
        "connection refused": "connection_refused",
        "invalid connection URI": "connection_url",
        "permission denied for table visitors": "database_permission",
        "opaque failure with password=private": "other",
    }
    for message, expected in cases.items():
        assert metrics_error_category(psycopg.OperationalError(message)) == expected
        assert "private" not in expected


def test_scan_metrics_are_aggregate_only_and_survive_store_reopen(tmp_path):
    path = tmp_path / "visitors.sqlite3"
    store = VisitorStore(str(path))
    store.record_scan("repository")
    store.record_scan("repository")
    store.record_scan("pull_request")
    assert VisitorStore(str(path)).snapshot()["repository_scans"] == 2
    assert VisitorStore(str(path)).snapshot()["pull_request_scans"] == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_scans").fetchone()[0] == 2
    try:
        store.record_scan("owner/repo")
    except ValueError:
        pass
    else:
        raise AssertionError("only aggregate scan kinds may be stored")


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


def test_successful_public_scans_are_counted_without_repository_names(monkeypatch, tmp_path):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def repository_info(self, repository, token=""):
            return {
                "visibility": "public",
                "default_branch": "main",
                "full_name": repository,
                "html_url": f"https://github.com/{repository}",
                "description": "Demo",
                "language": "Python",
                "updated_at": "2026-09-26T00:00:00Z",
            }

        def tree_snapshot(self, repository, ref, token=""):
            return TreeSnapshot(["README.md"])

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    path = tmp_path / "visitors.sqlite3"
    client = create_app({"TESTING": True, "VISITOR_METRICS_DB": str(path)}).test_client()
    assert client.get("/api/audit?repository=owner/repo").status_code == 200
    assert client.get("/api/audit?repository=owner/repo").json["cached"] is True
    assert client.get("/api/audit?repository=owner/repo", headers={"DNT": "1"}).status_code == 200
    assert client.get("/api/audit?repository=invalid").status_code == 400
    assert VisitorStore(str(path)).snapshot()["repository_scans"] == 2
    with sqlite3.connect(path) as connection:
        schemas = " ".join(
            row[0]
            for row in connection.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
        )
        assert "owner/repo" not in schemas
