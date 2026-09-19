import base64

import pytest

from qnode_auditor.audit import ChangedFile, audit_tree
from qnode_auditor.github import GitHubAppClient


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code
        self.content = b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")

    def json(self):
        return self.data


def test_app_installation_count_uses_app_auth_and_validates_response(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, timeout, **kwargs):
        captured.update(method=method, url=url, headers=headers)
        return FakeResponse({"installations_count": 3})

    monkeypatch.setattr("qnode_auditor.github.requests.request", fake_request)
    monkeypatch.setattr(GitHubAppClient, "_app_jwt", lambda self: "app-jwt")
    client = GitHubAppClient()
    assert client.app_installation_count() == 3
    assert captured["url"] == "https://api.github.com/app"
    assert captured["headers"]["Authorization"] == "Bearer app-jwt"

    def bad_request(method, url, headers, timeout, **kwargs):
        return FakeResponse({"installations_count": "3"})

    monkeypatch.setattr("qnode_auditor.github.requests.request", bad_request)
    with pytest.raises(ValueError, match="installation count"):
        client.app_installation_count()


def test_public_request_omits_authorization_and_returns_tree_metadata(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, timeout, **kwargs):
        captured.update(method=method, url=url, headers=headers, kwargs=kwargs)
        return FakeResponse(
            {
                "truncated": True,
                "tree": [
                    {"type": "blob", "path": "README.md"},
                    {"type": "tree", "path": "src"},
                ],
            }
        )

    monkeypatch.setattr("qnode_auditor.github.requests.request", fake_request)
    snapshot = GitHubAppClient().tree_snapshot("owner/repo", "feature/test")
    assert snapshot.paths == ["README.md"]
    assert snapshot.truncated is True
    assert "Authorization" not in captured["headers"]
    assert captured["url"].endswith("/git/trees/feature%2Ftest")
    assert captured["kwargs"]["params"] == {"recursive": "1"}


def test_missing_visibility_defaults_private_unless_github_explicitly_says_public(monkeypatch):
    data = {
        "full_name": "owner/repo",
        "html_url": "https://github.com/owner/repo",
        "default_branch": "main",
    }

    def fake_request(method, url, headers, timeout, **kwargs):
        return FakeResponse(data)

    monkeypatch.setattr("qnode_auditor.github.requests.request", fake_request)
    assert GitHubAppClient().repository_info("owner/repo")["visibility"] == "private"
    data["private"] = False
    assert GitHubAppClient().repository_info("owner/repo")["visibility"] == "public"


def test_pull_request_files_are_converted_to_domain_objects(monkeypatch):
    def fake_request(method, url, headers, timeout, **kwargs):
        return FakeResponse(
            [
                {
                    "filename": "src/app.py",
                    "status": "modified",
                    "additions": 12,
                    "deletions": 4,
                }
            ]
        )

    monkeypatch.setattr("qnode_auditor.github.requests.request", fake_request)
    files = GitHubAppClient().pull_request_files("owner/repo", 12, "token")
    assert len(files) == 1
    assert files[0].filename == "src/app.py"
    assert files[0].changes == 16


def test_file_text_decodes_codeowners_at_requested_ref(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, timeout, **kwargs):
        captured.update(url=url, params=kwargs["params"])
        content = base64.b64encode(b"/src/ @org/core\n").decode()
        return FakeResponse({"encoding": "base64", "content": content})

    monkeypatch.setattr("qnode_auditor.github.requests.request", fake_request)
    content = GitHubAppClient().file_text("owner/repo", ".github/CODEOWNERS", "feature/test")
    assert content == "/src/ @org/core\n"
    assert captured["url"].endswith("/contents/.github/CODEOWNERS")
    assert captured["params"] == {"ref": "feature/test"}


def test_pull_request_info_returns_public_report_metadata(monkeypatch):
    def fake_request(method, url, headers, timeout, **kwargs):
        return FakeResponse(
            {
                "number": 12,
                "title": "Improve scanner",
                "html_url": "https://github.com/owner/repo/pull/12",
                "state": "open",
                "draft": True,
                "head": {"sha": "abc", "ref": "feature"},
                "base": {"ref": "main"},
                "changed_files": 3,
                "additions": 40,
                "deletions": 7,
            }
        )

    monkeypatch.setattr("qnode_auditor.github.requests.request", fake_request)
    pull = GitHubAppClient().pull_request_info("owner/repo", 12)
    assert pull["head_sha"] == "abc"
    assert pull["base_ref"] == "main"
    assert pull["draft"] is True
    assert pull["changed_files"] == 3


def test_check_run_contains_actionable_output_annotations_and_rerun(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, timeout, **kwargs):
        captured.update(url=url, headers=headers, payload=kwargs["json"])
        return FakeResponse({"id": 1})

    monkeypatch.setattr("qnode_auditor.github.requests.request", fake_request)
    audit = audit_tree(
        ["README.md"],
        [ChangedFile("src/app.py", additions=10)],
        tree_truncated=True,
    )
    GitHubAppClient().publish_check("owner/repo", "abc", audit, "token")
    payload = captured["payload"]
    assert payload["name"] == "QNode repository intelligence"
    assert payload["actions"][0]["identifier"] == "rerun"
    assert payload["output"]["title"].startswith("Readiness 12/100")
    assert payload["output"]["annotations"][0]["path"] == "src/app.py"
    assert captured["headers"]["Authorization"] == "Bearer token"
