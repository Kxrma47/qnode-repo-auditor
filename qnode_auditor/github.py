from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import jwt
import requests

from .audit import ChangedFile


@dataclass(frozen=True)
class TreeSnapshot:
    paths: list[str]
    truncated: bool = False


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
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 9 * 60, "iss": self.app_id},
            self.private_key,
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

    def repository_info(self, repository: str, token: str = "") -> dict:
        data = self._request("GET", f"{self.api}/repos/{repository}", token)
        return {
            "full_name": data["full_name"],
            "html_url": data["html_url"],
            "description": data.get("description") or "",
            "default_branch": data["default_branch"],
            "visibility": data.get("visibility", "public"),
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
        paths = [
            node["path"]
            for node in data.get("tree", [])
            if node.get("type") == "blob" and node.get("path")
        ]
        return TreeSnapshot(paths=paths, truncated=bool(data.get("truncated")))

    def tree_paths(self, repository: str, sha: str, token: str) -> list[str]:
        """Compatibility wrapper retained for integrations using the original client API."""
        return self.tree_snapshot(repository, sha, token).paths

    def pull_request_files(
        self,
        repository: str,
        number: int,
        token: str,
        *,
        max_files: int = 1000,
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
