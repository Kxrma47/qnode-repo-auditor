import hashlib
import hmac
import json
from base64 import b64encode

import requests

from qnode_auditor.app import create_app
from qnode_auditor.audit import ChangedFile
from qnode_auditor.github import TreeSnapshot


def signed(secret: str, payload: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def webhook_headers(secret: str, payload: bytes, event: str, delivery: str = "delivery-1"):
    return {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": signed(secret, payload),
    }


def test_health_exposes_operational_capabilities_not_secrets():
    client = create_app(
        {"TESTING": True, "GITHUB_WEBHOOK_SECRET": "super-secret-value"}
    ).test_client()
    response = client.get("/health")
    assert response.json == {
        "public_audit": True,
        "service": "qnode-repo-auditor",
        "status": "ready",
        "version": "0.7.0",
        "webhook_configured": True,
        "owner_metrics_configured": False,
    }
    assert "super-secret-value" not in response.text


def test_owner_metrics_fail_closed_without_secret():
    client = create_app({"TESTING": True, "OWNER_METRICS_TOKEN": ""}).test_client()
    assert client.get("/owner/metrics").status_code == 404


def test_owner_metrics_auth_and_installation_count(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def app_installation_count(self):
            return 7

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    client = create_app(
        {
            "TESTING": True,
            "OWNER_METRICS_TOKEN": "long-test-secret",
            "OWNER_METRICS_USERNAME": "owner",
        }
    ).test_client()
    missing = client.get("/owner/metrics")
    wrong = client.get(
        "/owner/metrics", headers={"Authorization": "Basic " + b64encode(b"owner:wrong").decode()}
    )
    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["WWW-Authenticate"].startswith("Basic realm=")
    valid = client.get(
        "/owner/metrics",
        headers={"Authorization": "Basic " + b64encode(b"owner:long-test-secret").decode()},
    )
    assert valid.status_code == 200
    assert b"7" in valid.data
    assert b"not a count of unique people" in valid.data
    assert valid.headers["Cache-Control"] == "no-store, private"
    assert valid.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_owner_metrics_github_failure_does_not_expose_error(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def app_installation_count(self):
            raise requests.ConnectionError("private upstream detail")

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    client = create_app({"TESTING": True, "OWNER_METRICS_TOKEN": "secret"}).test_client()
    response = client.get(
        "/owner/metrics",
        headers={"Authorization": "Basic " + b64encode(b"Kxrma47:secret").decode()},
    )
    assert response.status_code == 502
    assert b"private upstream detail" not in response.data
    assert response.headers["Cache-Control"] == "no-store, private"


def test_index_is_an_interactive_scanner_with_security_headers():
    client = create_app({"TESTING": True}).test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"Audit a repository or pull request" in response.data
    assert b"Kxrma47/qnode-repo-auditor" in response.data
    assert b"qnode-app-icon.jpg" in response.data
    assert b'id="review-map-section"' in response.data
    assert b'id="companion-section"' in response.data
    assert b'id="delta-section"' in response.data
    assert b'id="policy-warning"' in response.data
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_rules_endpoint_describes_weighted_contract():
    client = create_app({"TESTING": True}).test_client()
    response = client.get("/api/rules")
    assert response.status_code == 200
    assert response.json["total_weight"] == 100
    assert len(response.json["rules"]) == 12


def test_ping_requires_and_accepts_signature():
    secret, payload = "test-secret", b'{"zen":"hello"}'
    client = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret}).test_client()
    assert client.post("/webhook", data=payload).status_code == 401
    response = client.post(
        "/webhook",
        data=payload,
        headers=webhook_headers(secret, payload, "ping"),
    )
    assert response.status_code == 200
    assert response.json["ok"] is True


def test_non_pull_request_event_is_ignored():
    secret, payload = "test-secret", b'{"action":"created"}'
    client = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret}).test_client()
    response = client.post(
        "/webhook",
        data=payload,
        headers=webhook_headers(secret, payload, "issues"),
    )
    assert response.status_code == 200
    assert response.json == {"ignored": True, "ok": True}


def test_pull_request_webhook_publishes_path_and_change_analysis(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def installation_token(self, installation_id):
            calls["installation_id"] = installation_id
            return "token"

        def tree_snapshot(self, repository, sha, token):
            calls["tree"] = (repository, sha)
            return TreeSnapshot(["README.md", "src/app.py", "pyproject.toml"])

        def pull_request_files(self, repository, number, token):
            calls["pull_number"] = number
            return [
                ChangedFile("src/app.py", additions=30),
                ChangedFile("pyproject.toml", additions=2),
            ]

        def pull_request_info(self, repository, number, token):
            return {"base_sha": ""}

        def publish_check(self, repository, sha, audit, token):
            calls["score"] = audit.score
            calls["risks"] = [risk.key for risk in audit.risks]
            return {}

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    secret = "test-secret"
    payload = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "repository": {"full_name": "Kxrma47/qnode-repo-auditor"},
            "pull_request": {"number": 7, "head": {"sha": "abc123"}},
        }
    ).encode()
    client = create_app(
        {
            "TESTING": True,
            "GITHUB_WEBHOOK_SECRET": secret,
            "GITHUB_INSTALLATION_ID": "157859600",
        }
    ).test_client()

    response = client.post(
        "/webhook",
        data=payload,
        headers=webhook_headers(secret, payload, "pull_request"),
    )

    assert response.status_code == 200
    assert response.json["risks"] == 2
    assert calls == {
        "installation_id": 157859600,
        "tree": ("Kxrma47/qnode-repo-auditor", "abc123"),
        "pull_number": 7,
        "score": 20,
        "risks": ["source-without-tests", "manifest-without-lock"],
    }


def test_duplicate_delivery_does_not_publish_twice(monkeypatch):
    published = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def installation_token(self, installation_id):
            return "token"

        def tree_snapshot(self, repository, sha, token):
            return TreeSnapshot(["README.md"])

        def pull_request_files(self, repository, number, token):
            return []

        def pull_request_info(self, repository, number, token):
            return {"base_sha": ""}

        def publish_check(self, repository, sha, audit, token):
            published.append(sha)
            return {}

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    secret = "secret"
    payload = json.dumps(
        {
            "action": "opened",
            "number": 1,
            "installation": {"id": 42},
            "repository": {"full_name": "owner/repo"},
            "pull_request": {"number": 1, "head": {"sha": "sha"}},
        }
    ).encode()
    app = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret})
    client = app.test_client()
    headers = webhook_headers(secret, payload, "pull_request", "same-delivery")
    assert client.post("/webhook", data=payload, headers=headers).status_code == 200
    second = client.post("/webhook", data=payload, headers=headers)
    assert second.json == {"duplicate": True, "ok": True}
    assert published == ["sha"]


def test_requested_check_action_reruns_pull_request_audit(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def installation_token(self, installation_id):
            return "token"

        def tree_snapshot(self, repository, sha, token):
            calls["sha"] = sha
            return TreeSnapshot(["README.md"])

        def pull_request_files(self, repository, number, token):
            calls["number"] = number
            return []

        def pull_request_info(self, repository, number, token):
            return {"base_sha": ""}

        def publish_check(self, repository, sha, audit, token):
            calls["published"] = repository
            return {}

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    secret = "secret"
    payload = json.dumps(
        {
            "action": "requested_action",
            "requested_action": {"identifier": "rerun"},
            "installation": {"id": 42},
            "repository": {"full_name": "owner/repo"},
            "check_run": {"head_sha": "new-sha", "pull_requests": [{"number": 9}]},
        }
    ).encode()
    client = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret}).test_client()
    response = client.post(
        "/webhook",
        data=payload,
        headers=webhook_headers(secret, payload, "check_run", "rerun-delivery"),
    )
    assert response.status_code == 200
    assert calls == {"sha": "new-sha", "number": 9, "published": "owner/repo"}


def test_public_audit_fetches_repository_and_uses_cache(monkeypatch):
    calls = {"info": 0, "tree": 0}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def repository_info(self, repository, token=""):
            calls["info"] += 1
            return {
                "full_name": repository,
                "html_url": f"https://github.com/{repository}",
                "description": "Useful repository",
                "default_branch": "main",
                "visibility": "public",
                "language": "Python",
                "stars": 3,
                "forks": 1,
                "open_issues": 0,
                "archived": False,
                "updated_at": "2026-01-01T00:00:00Z",
            }

        def tree_snapshot(self, repository, ref, token=""):
            calls["tree"] += 1
            return TreeSnapshot(["README.md", "LICENSE", "tests/test.py"])

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    client = create_app({"TESTING": True}).test_client()
    first = client.get("/api/audit?repository=owner/repo")
    second = client.get("/api/audit?repository=owner/repo")
    assert first.status_code == 200
    assert first.json["cached"] is False
    assert first.json["audit"]["score"] == 36
    assert second.json["cached"] is True
    assert calls == {"info": 1, "tree": 1}


def test_public_audit_rejects_invalid_repository_and_ref():
    client = create_app({"TESTING": True}).test_client()
    assert client.get("/api/audit?repository=not-a-repository").status_code == 400
    assert client.get("/api/audit?repository=owner/repo&ref=../../secret").status_code == 400
    assert client.get("/api/audit?repository=owner/repo&pull=zero").status_code == 400
    assert client.get("/api/audit?repository=owner/repo&pull=1&ref=main").status_code == 400


def test_public_scanner_does_not_expose_private_repo_even_with_accessible_token(monkeypatch):
    calls = []

    class PrivateClient:
        def __init__(self, **kwargs):
            pass

        def repository_info(self, repository, token=""):
            calls.append((repository, token))
            return {"visibility": "private", "full_name": repository}

        def tree_snapshot(self, *args, **kwargs):
            raise AssertionError("Private repository tree should never be fetched")

        def pull_request_info(self, *args, **kwargs):
            raise AssertionError("Private pull request should never be fetched")

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", PrivateClient)
    app = create_app({"TESTING": True, "GITHUB_PUBLIC_TOKEN": "private-readable-token"})
    client = app.test_client()
    for target in ("repository=owner/repo", "repository=owner/repo&pull=9"):
        response = client.get(f"/api/audit?{target}")
        assert response.status_code == 404
        assert "private" not in response.text.lower()
    assert calls == [("owner/repo", "private-readable-token")] * 2


def test_public_pull_request_audit_includes_change_risks(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def repository_info(self, repository, token=""):
            return {
                "full_name": repository,
                "html_url": f"https://github.com/{repository}",
                "description": "Useful repository",
                "default_branch": "main",
                "visibility": "public",
                "language": "Python",
                "stars": 3,
                "forks": 1,
                "open_issues": 0,
                "archived": False,
                "updated_at": "2026-01-01T00:00:00Z",
            }

        def pull_request_info(self, repository, number, token=""):
            return {
                "number": number,
                "title": "Change service",
                "html_url": f"https://github.com/{repository}/pull/{number}",
                "state": "open",
                "draft": False,
                "head_sha": "abc123",
                "head_ref": "feature",
                "base_ref": "main",
                "changed_files": 1,
                "additions": 32,
                "deletions": 4,
            }

        def pull_request_files(self, repository, number, token=""):
            return [ChangedFile("src/service.py", additions=32, deletions=4)]

        def tree_snapshot(self, repository, ref, token=""):
            assert ref == "abc123"
            return TreeSnapshot(["README.md", "src/service.py", ".github/CODEOWNERS"])

        def file_text(self, repository, path, ref, token=""):
            assert path == ".github/CODEOWNERS"
            return "/src/ @org/backend\n"

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    response = (
        create_app({"TESTING": True}).test_client().get("/api/audit?repository=owner/repo&pull=42")
    )

    assert response.status_code == 200
    assert response.json["pull_request"]["number"] == 42
    assert response.json["ref"] == "abc123"
    assert response.json["audit"]["risks"][0]["key"] == "source-without-tests"
    assert response.json["audit"]["review_map"][0]["label"] == "src/"
    assert response.json["audit"]["review_map"][0]["attention"] == "medium"
    assert response.json["audit"]["review_map"][0]["owners"] == ["@org/backend"]
    assert response.json["audit"]["companion_suggestions"][0]["suggested_path"] == (
        "tests/test_service.py"
    )
    assert "Engineering readiness" in response.json["audit"]["markdown"]


def test_public_pr_includes_policy_and_review_delta_without_source_content(monkeypatch):
    base, reviewed, head = "a" * 40, "b" * 40, "c" * 40

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def repository_info(self, repository, token=""):
            return {
                "full_name": repository,
                "html_url": f"https://github.com/{repository}",
                "description": "Example",
                "default_branch": "main",
                "visibility": "public",
                "language": "Python",
                "stars": 0,
                "forks": 0,
                "open_issues": 0,
                "archived": False,
                "updated_at": None,
            }

        def pull_request_info(self, repository, number, token=""):
            return {
                "number": number,
                "title": "Add auth change",
                "html_url": f"https://github.com/{repository}/pull/{number}",
                "state": "open",
                "draft": False,
                "head_sha": head,
                "head_ref": "feature",
                "base_ref": "main",
                "base_sha": base,
                "changed_files": 2,
                "additions": 20,
                "deletions": 2,
            }

        def pull_request_files(self, repository, number, token=""):
            return [ChangedFile("src/auth.py", additions=10), ChangedFile("tests/test_auth.py")]

        def tree_snapshot(self, repository, ref, token=""):
            policy_blob = {".qnode.json": "d" * 40}
            if ref == base:
                blobs = policy_blob | {"pyproject.toml": "e" * 40}
            elif ref == reviewed:
                blobs = policy_blob | {"pyproject.toml": "f" * 40}
            else:
                assert ref == head
                blobs = policy_blob | {
                    "pyproject.toml": "e" * 40,
                    "src/auth.py": "1" * 40,
                    "tests/test_auth.py": "2" * 40,
                }
            return TreeSnapshot(list(blobs), blob_shas=blobs)

        def file_text(self, repository, path, ref, token=""):
            assert path == ".qnode.json"
            return '{"version": 1, "critical_paths": ["src/auth.py"]}'

        def latest_submitted_review(self, repository, number, token=""):
            return {"commit_sha": reviewed, "submitted_at": "2026-09-18T00:00:00Z"}

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    response = create_app({"TESTING": True}).test_client().get(
        "/api/audit?repository=owner/repo&pull=42"
    )
    assert response.status_code == 200
    audit = response.json["audit"]
    assert "critical-path" in {signal["key"] for signal in audit["risks"]}
    assert [signal["key"] for signal in audit["review_delta"]["new_signals"]] == [
        "critical-path"
    ]
    assert [signal["key"] for signal in audit["review_delta"]["resolved_signals"]] == [
        "manifest-without-lock"
    ]
    assert audit["review_delta"]["changed_paths"] == [
        "pyproject.toml",
        "src/auth.py",
        "tests/test_auth.py",
    ]


def test_public_pull_request_flags_partial_file_list(monkeypatch):
    class PartialClient:
        def __init__(self, **kwargs):
            pass

        def repository_info(self, repository, token=""):
            return {
                "full_name": repository,
                "html_url": f"https://github.com/{repository}",
                "default_branch": "main",
                "visibility": "public",
            }

        def pull_request_info(self, repository, number, token=""):
            return {"head_sha": "abc", "changed_files": 1001, "number": number}

        def pull_request_files(self, repository, number, token=""):
            return [ChangedFile("src/app.py", additions=1)]

        def tree_snapshot(self, repository, ref, token=""):
            return TreeSnapshot(["README.md", "src/app.py"])

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", PartialClient)
    response = (
        create_app({"TESTING": True}).test_client().get("/api/audit?repository=owner/repo&pull=14")
    )
    assert response.status_code == 200
    assert response.json["audit"]["files_truncated"] is True
    assert "may be incomplete" in response.json["audit"]["markdown"]
