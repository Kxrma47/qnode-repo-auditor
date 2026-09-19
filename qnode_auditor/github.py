from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .audit import ChangedFile

MAX_PR_FILES = 1000


@dataclass(frozen=True)
class TreeSnapshot:
    paths: list[str]
    truncated: bool = False
    blob_shas: dict[str, str] = field(default_factory=dict)


def compare_trees(base: TreeSnapshot, head: TreeSnapshot) -> tuple[ChangedFile, ...]:
    """Compare blob IDs without downloading either commit's source contents."""
    if base.truncated or head.truncated:
        raise ValueError("GitHub truncated a comparison tree")
    if (
        len(base.blob_shas) != len(base.paths)
        or len(head.blob_shas) != len(head.paths)
        or not all(
            re.fullmatch(r"[0-9a-fA-F]{40}", sha)
            for sha in (*base.blob_shas.values(), *head.blob_shas.values())
        )
    ):
        raise ValueError("GitHub did not provide complete blob IDs")
    changes = []
    for path in sorted(set(base.blob_shas) | set(head.blob_shas)):
        before, after = base.blob_shas.get(path), head.blob_shas.get(path)
        if before == after:
            continue
        status = "added" if before is None else "removed" if after is None else "modified"
        changes.append(ChangedFile(path, status=status))
    return tuple(changes)


class GitHubAppClient:
    api = "https://api.github.com"

    def __init__(
        self,
        app_id: str = "",
        private_key_path: str = "",
        private_key: str = "",
        timeout: int = 15,
    ):
        self.app_id = str(app_id)
        if private_key:
            self.private_key = private_key.replace("\\n", "\n")
        elif private_key_path:
            self.private_key = Path(private_key_path).read_text(encoding="utf-8")
        else:
            self.private_key = ""
        self.timeout = timeout

    def _app_jwt(self) -> str:
        if not self.app_id or not self.private_key:
            raise ValueError(
                "GitHub App ID and private key are required for installation authentication"
            )
        try:
            key = serialization.load_pem_private_key(
                self.private_key.encode("utf-8"), password=None
            )
        except ValueError as error:
            raise ValueError("GitHub App private key must be a valid RSA key") from error
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("GitHub App RSA private key must be at least 2048 bits")
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 9 * 60, "iss": self.app_id},
            key,
            algorithm="RS256",
        )

    def _request(self, method: str, url: str, token: str = "", **kwargs):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "qnode-repo-auditor",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = requests.request(
            method,
            url,
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response.json() if response.content else {}

    def installation_token(self, installation_id: int) -> str:
        data = self._request(
            "POST",
            f"{self.api}/app/installations/{installation_id}/access_tokens",
            self._app_jwt(),
        )
        return data["token"]

    def app_installation_count(self) -> int:
        """Return GitHub's current number of accounts with this App installed."""
        data = self._request("GET", f"{self.api}/app", self._app_jwt())
        count = data.get("installations_count")
        if type(count) is not int or count < 0:
            raise ValueError("GitHub App response did not include an installation count")
        return count

    def repository_info(self, repository: str, token: str = "") -> dict:
        data = self._request("GET", f"{self.api}/repos/{repository}", token)
        return {
            "full_name": data["full_name"],
            "html_url": data["html_url"],
            "description": data.get("description") or "",
            "default_branch": data["default_branch"],
            "visibility": data.get("visibility")
            or ("public" if data.get("private") is False else "private"),
            "language": data.get("language"),
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "archived": data.get("archived", False),
            "updated_at": data.get("updated_at"),
        }

    def tree_snapshot(self, repository: str, ref: str, token: str = "") -> TreeSnapshot:
        safe_ref = quote(ref, safe="")
        data = self._request(
            "GET",
            f"{self.api}/repos/{repository}/git/trees/{safe_ref}",
            token,
            params={"recursive": "1"},
        )
        blobs = {
            node["path"]: node.get("sha", "")
            for node in data.get("tree", [])
            if node.get("type") == "blob" and node.get("path")
        }
        return TreeSnapshot(
            paths=list(blobs), truncated=bool(data.get("truncated")), blob_shas=blobs
        )

    def tree_paths(self, repository: str, sha: str, token: str) -> list[str]:
        """Compatibility wrapper retained for integrations using the original client API."""
        return self.tree_snapshot(repository, sha, token).paths

    def file_text(self, repository: str, path: str, ref: str, token: str = "") -> str:
        """Read a small policy file through GitHub's Contents API."""
        safe_path = quote(path, safe="/")
        data = self._request(
            "GET",
            f"{self.api}/repos/{repository}/contents/{safe_path}",
            token,
            params={"ref": ref},
        )
        if data.get("encoding") != "base64" or not data.get("content"):
            return ""
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def pull_request_files(
        self,
        repository: str,
        number: int,
        token: str,
        *,
        max_files: int = MAX_PR_FILES,
    ) -> list[ChangedFile]:
        files: list[ChangedFile] = []
        page = 1
        while len(files) < max_files:
            data = self._request(
                "GET",
                f"{self.api}/repos/{repository}/pulls/{number}/files",
                token,
                params={"per_page": 100, "page": page},
            )
            for item in data:
                files.append(
                    ChangedFile(
                        filename=item["filename"],
                        status=item.get("status", "modified"),
                        additions=int(item.get("additions", 0)),
                        deletions=int(item.get("deletions", 0)),
                    )
                )
            if len(data) < 100:
                break
            page += 1
        return files[:max_files]

    def pull_request_info(self, repository: str, number: int, token: str = "") -> dict:
        data = self._request(
            "GET",
            f"{self.api}/repos/{repository}/pulls/{number}",
            token,
        )
        return {
            "number": int(data["number"]),
            "title": data.get("title") or "",
            "html_url": data["html_url"],
            "state": data.get("state", "open"),
            "draft": bool(data.get("draft", False)),
            "head_sha": data["head"]["sha"],
            "head_ref": data["head"]["ref"],
            "base_ref": data["base"]["ref"],
            "base_sha": data["base"].get("sha", ""),
            "changed_files": int(data.get("changed_files", 0)),
            "additions": int(data.get("additions", 0)),
            "deletions": int(data.get("deletions", 0)),
        }

    def latest_submitted_review(self, repository: str, number: int, token: str = "") -> dict | None:
        """Latest submitted human review with a commit SHA, up to 1,000 reviews."""
        latest = None
        for page in range(1, 11):
            reviews = self._request(
                "GET",
                f"{self.api}/repos/{repository}/pulls/{number}/reviews",
                token,
                params={"per_page": 100, "page": page},
            )
            for review in reviews:
                if (
                    review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}
                    and review.get("submitted_at")
                    and review.get("commit_id")
                    and (review.get("user") or {}).get("type") != "Bot"
                ):
                    latest = {
                        "commit_sha": review["commit_id"],
                        "submitted_at": review["submitted_at"],
                    }
            if len(reviews) < 100:
                return latest
        return None  # Do not claim a latest review when the listing was truncated.


    def publish_check(self, repository: str, sha: str, audit, token: str) -> dict:
        output = {
            "title": f"Readiness {audit.score}/100 · Grade {audit.grade}",
            "summary": audit.markdown(),
        }
        annotations = audit.annotations()
        if annotations:
            output["annotations"] = annotations

        return self._request(
            "POST",
            f"{self.api}/repos/{repository}/check-runs",
            token,
            json={
                "name": "QNode repository intelligence",
                "head_sha": sha,
                "status": "completed",
                "conclusion": audit.conclusion,
                "output": output,
                "actions": [
                    {
                        "label": "Re-run audit",
                        "description": "Run QNode again against the current commit",
                        "identifier": "rerun",
                    }
                ],
            },
        )
