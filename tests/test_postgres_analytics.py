"""Integration check against a disposable PostgreSQL database."""

import hashlib
import os
import secrets
from base64 import b64encode
from datetime import UTC, datetime

import psycopg
import pytest

from qnode_auditor import analytics
from qnode_auditor.app import create_app


@pytest.mark.skipif(not os.getenv("QNODE_TEST_POSTGRES_URL"), reason="PostgreSQL not configured")
def test_postgres_metrics_are_durable_aggregate_and_tls_is_required(monkeypatch):
    dsn = os.environ["QNODE_TEST_POSTGRES_URL"]
    original_connect = psycopg.connect

    def connect_test_database(conninfo, **kwargs):
        assert kwargs["sslmode"] == "verify-full"
        assert kwargs["sslrootcert"] == "system"
        # Only the disposable CI database accepts local unencrypted connections.
        kwargs["sslmode"] = "disable"
        kwargs.pop("sslrootcert")
        return original_connect(conninfo, **kwargs)

    monkeypatch.setattr(analytics.psycopg, "connect", connect_test_database)
    store = analytics.PostgresVisitorStore(dsn)
    before = store.snapshot()
    token = secrets.token_hex(16)
    now = datetime.now(UTC)
    store.record(token, now=now)
    store.record(token, now=now)
    store.record_scan("repository", now=now)
    store.record_scan("pull_request", now=now)
    after = analytics.PostgresVisitorStore(dsn).snapshot()
    assert after["unique_browsers"] == before["unique_browsers"] + 1
    assert after["page_views"] == before["page_views"] + 2
    assert after["repository_scans"] == before["repository_scans"] + 1
    assert after["pull_request_scans"] == before["pull_request_scans"] + 1
    assert isinstance(after["page_views"], int)
    with original_connect(dsn) as connection:
        (stored_hash,) = connection.execute(
            "SELECT visitor_hash FROM visitors WHERE visitor_hash = %s",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
        assert stored_hash != token

    class FakeGitHubClient:
        def __init__(self, **kwargs):
            pass

        def app_installation_count(self):
            return 3

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeGitHubClient)
    app = create_app(
        {"TESTING": True, "VISITOR_METRICS_URL": dsn, "OWNER_METRICS_TOKEN": "test-only-token"}
    )
    client = app.test_client()
    assert client.get("/").headers.get("Set-Cookie")
    assert client.post("/api/visit", headers={"X-QNode-Visit": "1"}).status_code == 204
    assert client.post("/api/visit", headers={"X-QNode-Visit": "1", "DNT": "1"}).status_code == 403
    auth = {"Authorization": "Basic " + b64encode(b"Kxrma47:test-only-token").decode()}
    assert client.get("/owner/metrics").status_code == 401
    owner = create_app(
        {"TESTING": True, "VISITOR_METRICS_URL": dsn, "OWNER_METRICS_TOKEN": "test-only-token"}
    ).test_client()
    response = owner.get("/owner/metrics", headers=auth)
    assert response.status_code == 200
    assert f'{after["page_views"] + 1} page views'.encode() in response.data
    assert response.headers["Cache-Control"] == "no-store, private"
