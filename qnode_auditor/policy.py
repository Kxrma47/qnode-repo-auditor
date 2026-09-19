"""Small, opt-in repository policy; never executes user-provided values."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase

POLICY_PATH = ".qnode.json"
MAX_POLICY_BYTES = 32768
MAX_PATTERNS = 50


@dataclass(frozen=True)
class AuditPolicy:
    ignore_paths: tuple[str, ...] = ()
    critical_paths: tuple[str, ...] = ()
    test_jobs: tuple[tuple[str, tuple[str, ...]], ...] = ()
    warning: str = ""

    def ignored(self, path: str) -> bool:
        return any(_matches(pattern, path) for pattern in self.ignore_paths)

    def critical(self, path: str) -> bool:
        return any(_matches(pattern, path) for pattern in self.critical_paths)

    def jobs_for(self, paths: list[str]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                job
                for pattern, jobs in self.test_jobs
                if any(_matches(pattern, path) for path in paths)
                for job in jobs
            )
        )[:8]


def _matches(pattern: str, path: str) -> bool:
    if pattern.endswith("/**") and path == pattern[:-3]:
        return True
    return fnmatchcase(path, pattern)


def _patterns(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_PATTERNS:
        raise ValueError(f"{field} must be a list of at most {MAX_PATTERNS} paths")
    if not all(
        isinstance(item, str)
        and 0 < len(item) <= 200
        and not item.startswith("/")
        and ".." not in item.split("/")
        and "\\" not in item
        and all(ord(char) >= 32 and char not in "|`" for char in item)
        for item in value
    ):
        raise ValueError(f"{field} contains an invalid repository-relative path pattern")
    return tuple(value)


def parse_policy(content: str) -> AuditPolicy:
    if not content:
        return AuditPolicy()
    try:
        if len(content.encode("utf-8")) > MAX_POLICY_BYTES:
            raise ValueError("policy exceeds the 32 KiB limit")
        data = json.loads(content)
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data["version"] != 1
        ):
            raise ValueError("version must be 1")
        unknown = set(data) - {"version", "ignore_paths", "critical_paths", "test_jobs"}
        if unknown:
            raise ValueError("unknown policy field(s)")
        ignore_paths = _patterns(data.get("ignore_paths", []), "ignore_paths")
        critical_paths = _patterns(data.get("critical_paths", []), "critical_paths")
        jobs_data = data.get("test_jobs", {})
        if not isinstance(jobs_data, dict) or len(jobs_data) > MAX_PATTERNS:
            raise ValueError("test_jobs must be a path-to-job mapping")
        test_jobs = []
        for pattern, jobs in jobs_data.items():
            _patterns([pattern], "test_jobs")
            if not isinstance(jobs, list) or len(jobs) > 8 or not all(
                isinstance(job, str)
                and 0 < len(job) <= 100
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./:-]*", job)
                for job in jobs
            ):
                raise ValueError("test_jobs entries must list up to eight short job names")
            test_jobs.append((pattern, tuple(jobs)))
        return AuditPolicy(ignore_paths, critical_paths, tuple(test_jobs))
    except (json.JSONDecodeError, ValueError, TypeError) as error:
        return AuditPolicy(warning=f"Invalid {POLICY_PATH}: {error}. Using default rules.")
