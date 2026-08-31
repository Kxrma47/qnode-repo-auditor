import time
from pathlib import Path

import jwt
import requests


class GitHubAppClient:
    api = "https://api.github.com"

    def __init__(self, app_id: str, private_key_path: str, timeout: int = 15):
        self.app_id = app_id
        self.private_key = Path(private_key_path).read_text(encoding="utf-8")
        self.timeout = timeout

    def _app_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 9 * 60, "iss": self.app_id},
            self.private_key,
            algorithm="RS256",
        )

    def _request(self, method: str, url: str, token: str, **kwargs):
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def installation_token(self, installation_id: int) -> str:
        data = self._request(
            "POST",
            f"{self.api}/app/installations/{installation_id}/access_tokens",
            self._app_jwt(),
        )
        return data["token"]

    def tree_paths(self, repository: str, sha: str, token: str) -> list[str]:
        data = self._request(
            "GET", f"{self.api}/repos/{repository}/git/trees/{sha}?recursive=1", token
        )
        return [node["path"] for node in data.get("tree", []) if node.get("type") == "blob"]

    def publish_check(self, repository: str, sha: str, audit, token: str) -> None:
        self._request(
            "POST",
            f"{self.api}/repos/{repository}/check-runs",
            token,
            json={
                "name": "QNode engineering readiness",
                "head_sha": sha,
                "status": "completed",
                "conclusion": audit.conclusion,
                "output": {
                    "title": f"Repository signal: {audit.score}/100",
                    "summary": audit.markdown(),
                },
            },
        )
