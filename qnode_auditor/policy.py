"""Small, opt-in repository policy; never executes user-provided values."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase

POLICY_PATH = ".qnode.json"
MAX_POLICY_BYTES = 32768
MAX_PATTERNS = 50
MAX_CONTRACTS = 20


@dataclass(frozen=True)
class ChangeContract:
    id: str
    when: tuple[str, ...]
    require_all: tuple[str, ...] = ()
    require_any: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class AuditPolicy:
    ignore_paths: tuple[str, ...] = ()
    critical_paths: tuple[str, ...] = ()
    test_jobs: tuple[tuple[str, tuple[str, ...]], ...] = ()
    change_contracts: tuple[ChangeContract, ...] = ()
    warning: str = ""

    def ignored(self, path: str) -> bool:
        return any(matches(pattern, path) for pattern in self.ignore_paths)

    def critical(self, path: str) -> bool:
        return any(matches(pattern, path) for pattern in self.critical_paths)

    def jobs_for(self, paths: list[str]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                job
                for pattern, jobs in self.test_jobs
                if any(matches(pattern, path) for path in paths)
                for job in jobs
            )
        )[:8]


def matches(pattern: str, path: str) -> bool:
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
        unknown = set(data) - {
            "version",
            "ignore_paths",
            "critical_paths",
            "test_jobs",
            "change_contracts",
        }
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
            if (
                not isinstance(jobs, list)
                or len(jobs) > 8
                or not all(
                    isinstance(job, str)
                    and 0 < len(job) <= 100
                    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./:-]*", job)
                    for job in jobs
                )
            ):
                raise ValueError("test_jobs entries must list up to eight short job names")
            test_jobs.append((pattern, tuple(jobs)))
        contracts_data = data.get("change_contracts", [])
        if not isinstance(contracts_data, list) or len(contracts_data) > MAX_CONTRACTS:
            raise ValueError(f"change_contracts must list at most {MAX_CONTRACTS} rules")
        contracts = []
        ids = set()
        for entry in contracts_data:
            if not isinstance(entry, dict) or set(entry) - {
                "id",
                "when",
                "require_all",
                "require_any",
                "reason",
            }:
                raise ValueError("change_contracts contains an invalid rule")
            name = entry.get("id")
            if not isinstance(name, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", name
            ):
                raise ValueError("change_contracts id must be a short identifier")
            if name in ids:
                raise ValueError("change_contracts ids must be unique")
            ids.add(name)
            when = _patterns(entry.get("when"), f"change_contracts.{name}.when")
            required = _patterns(
                entry.get("require_all", []), f"change_contracts.{name}.require_all"
            )
            alternatives = _patterns(
                entry.get("require_any", []), f"change_contracts.{name}.require_any"
            )
            if not when or not (required or alternatives) or len(required) + len(alternatives) > 8:
                raise ValueError("change_contracts needs a trigger and 1-8 requirements")
            reason = entry.get("reason", "")
            if (
                not isinstance(reason, str)
                or len(reason) > 160
                or not re.fullmatch(r"[A-Za-z0-9 .,/:;()_\-]*", reason)
            ):
                raise ValueError("change_contracts reason contains unsupported characters")
            contracts.append(ChangeContract(name, when, required, alternatives, reason))
        return AuditPolicy(
            ignore_paths=ignore_paths,
            critical_paths=critical_paths,
            test_jobs=tuple(test_jobs),
            change_contracts=tuple(contracts),
        )
    except (json.JSONDecodeError, ValueError, TypeError) as error:
        return AuditPolicy(warning=f"Invalid {POLICY_PATH}: {error}. Using default rules.")
