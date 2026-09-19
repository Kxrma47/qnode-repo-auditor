from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from .policy import AuditPolicy


@dataclass(frozen=True)
class Check:
    key: str
    category: str
    label: str
    passed: bool
    weight: int
    evidence: str
    recommendation: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ChangedFile:
    filename: str
    status: str = "modified"
    additions: int = 0
    deletions: int = 0

    @property
    def changes(self) -> int:
        return self.additions + self.deletions


@dataclass(frozen=True)
class RiskSignal:
    key: str
    severity: str
    title: str
    detail: str
    path: str | None = None
    recommendation: str = ""
    annotate: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CompanionSuggestion:
    kind: str
    source_path: str
    suggested_path: str
    action: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReviewLane:
    key: str
    label: str
    attention: str
    file_count: int
    additions: int
    deletions: int
    signals: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()
    unowned_files: int = 0
    source_files: int = 0
    test_path_matches: int = 0
    review_questions: tuple[str, ...] = ()
    test_targets: tuple[str, ...] = ()
    configured_jobs: tuple[str, ...] = ()

    @property
    def changes(self) -> int:
        return self.additions + self.deletions

    def to_dict(self) -> dict:
        return asdict(self) | {"changes": self.changes}


@dataclass(frozen=True)
class ReviewDelta:
    baseline_sha: str
    reviewed_at: str
    changed_paths: tuple[str, ...]
    changed_path_count: int
    new_signals: tuple[RiskSignal, ...]
    resolved_signals: tuple[RiskSignal, ...]

    def to_dict(self) -> dict:
        return {
            "baseline_sha": self.baseline_sha,
            "reviewed_at": self.reviewed_at,
            "changed_paths": self.changed_paths,
            "changed_path_count": self.changed_path_count,
            "new_signals": [signal.to_dict() for signal in self.new_signals],
            "resolved_signals": [signal.to_dict() for signal in self.resolved_signals],
        }


@dataclass(frozen=True)
class Audit:
    checks: tuple[Check, ...]
    risks: tuple[RiskSignal, ...] = ()
    review_lanes: tuple[ReviewLane, ...] = ()
    companion_suggestions: tuple[CompanionSuggestion, ...] = ()
    tree_truncated: bool = False
    files_truncated: bool = False
    ignored_files: int = 0
    policy_warning: str = ""
    review_delta: ReviewDelta | None = None

    @property
    def score(self) -> int:
        possible = sum(check.weight for check in self.checks)
        earned = sum(check.weight for check in self.checks if check.passed)
        return round(100 * earned / possible) if possible else 0

    @property
    def grade(self) -> str:
        for minimum, grade in ((90, "A"), (80, "B"), (70, "C"), (55, "D")):
            if self.score >= minimum:
                return grade
        return "F"

    @property
    def conclusion(self) -> str:
        return "success" if self.score >= 70 else "neutral"

    @property
    def passed_count(self) -> int:
        return sum(check.passed for check in self.checks)

    @property
    def missing(self) -> tuple[Check, ...]:
        return tuple(
            sorted(
                (check for check in self.checks if not check.passed),
                key=lambda check: check.weight,
                reverse=True,
            )
        )

    def annotations(self) -> list[dict]:
        annotations = []
        for risk in self.risks[:50]:
            if not risk.path or not risk.annotate:
                continue
            annotations.append(
                {
                    "path": risk.path,
                    "start_line": 1,
                    "end_line": 1,
                    "annotation_level": "warning"
                    if risk.severity in {"high", "medium"}
                    else "notice",
                    "title": risk.title[:255],
                    "message": " ".join(
                        part for part in (risk.detail, risk.recommendation) if part
                    )[:65535],
                }
            )
        return annotations

    def markdown(self) -> str:
        lines = [
            f"## Engineering readiness: {self.score}/100 · Grade {self.grade}",
            "",
            f"{self.passed_count} of {len(self.checks)} repository safeguards detected.",
            "",
            "| Category | Signal | Weight | Status | Evidence |",
            "|---|---|---:|:---:|---|",
        ]
        for check in self.checks:
            lines.append(
                f"| {check.category} | {check.label} | {check.weight} | "
                f"{'✓' if check.passed else '○'} | {check.evidence} |"
            )

        if self.missing:
            lines.extend(["", "### Highest-impact improvements"])
            for check in self.missing[:4]:
                lines.append(
                    f"- **+{check.weight} points — {check.label}:** {check.recommendation}"
                )

        if self.risks:
            lines.extend(["", "### Pull-request signals"])
            for risk in self.risks:
                lines.append(f"- **{risk.severity.upper()} · {risk.title}:** {risk.detail}")

        if self.review_delta:
            delta = self.review_delta
            lines.extend(
                [
                    "",
                    "### Since the latest submitted review",
                    f"Compared with `{delta.baseline_sha[:12]}` ({delta.reviewed_at}).",
                    f"{delta.changed_path_count} path(s) changed since that review; "
                    f"{len(delta.new_signals)} new and {len(delta.resolved_signals)} resolved "
                    "QNode signals in the PR-wide report.",
                ]
            )
            for signal in delta.new_signals[:8]:
                lines.append(f"- **New:** {signal.title} (`{signal.path or 'PR'}`)")
            for signal in delta.resolved_signals[:8]:
                lines.append(f"- **Resolved:** {signal.title} (`{signal.path or 'PR'}`)")

        if self.companion_suggestions:
            lines.extend(["", "### Suggested companion changes"])
            for suggestion in self.companion_suggestions[:8]:
                lines.append(
                    f"- **{suggestion.action.title()} `{suggestion.suggested_path}`** for "
                    f"`{suggestion.source_path}` — {suggestion.reason}"
                )

        if self.review_lanes:
            lines.extend(
                [
                    "",
                    "### Review map",
                    "",
                    "| Lane | Owners | Attention | Files | Churn | Tests | "
                    "Configured jobs | Review focus |",
                    "|---|---|:---:|---:|---:|:---:|---|---|",
                ]
            )
            for lane in self.review_lanes[:8]:
                focus = "; ".join(lane.signals) or "Standard review"
                owners = ", ".join(lane.owners) or "Unassigned"
                test_match = (
                    f"{lane.test_path_matches}/{lane.source_files}" if lane.source_files else "n/a"
                )
                lines.append(
                    f"| `{lane.label}` | {owners} | {lane.attention.upper()} | {lane.file_count} | "
                    f"{lane.changes:,} | {test_match} | "
                    f"{', '.join(lane.configured_jobs) or 'None'} | {focus} |"
                )
            if len(self.review_lanes) > 8:
                lines.append(f"\n_{len(self.review_lanes) - 8} additional review lane(s) in JSON._")
            lines.extend(["", "#### Focused review questions"])
            for lane in self.review_lanes[:8]:
                if lane.test_targets:
                    lines.append(
                        f"- **{lane.label} candidate tests:** "
                        + ", ".join(f"`{path}`" for path in lane.test_targets)
                    )
                for question in lane.review_questions:
                    lines.append(f"- **{lane.label}:** {question}")

        if self.policy_warning:
            lines.extend(["", f"> {self.policy_warning}"])
        elif self.ignored_files:
            lines.extend(
                ["", f"_{self.ignored_files} changed file(s) excluded from heuristic warnings "
                 "by .qnode.json; credential-like and critical paths are never suppressed._"]
            )

        if self.tree_truncated:
            lines.extend(
                ["", "> GitHub truncated the recursive tree response. Results may be incomplete."]
            )
        if self.files_truncated:
            lines.extend(
                [
                    "",
                    "> The PR file list exceeded the scan limit. Review signals may be incomplete.",
                ]
            )

        lines.extend(
            [
                "",
                "_Advisory only. QNode reads paths, metadata, CODEOWNERS, "
                "and optional .qnode.json; "
                "never application source contents; and never blocks a pull request._",
            ]
        )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "conclusion": self.conclusion,
            "passed": self.passed_count,
            "total": len(self.checks),
            "tree_truncated": self.tree_truncated,
            "files_truncated": self.files_truncated,
            "ignored_files": self.ignored_files,
            "policy_warning": self.policy_warning,
            "review_delta": self.review_delta.to_dict() if self.review_delta else None,
            "checks": [check.to_dict() for check in self.checks],
            "risks": [risk.to_dict() for risk in self.risks],
            "review_map": [lane.to_dict() for lane in self.review_lanes],
            "companion_suggestions": [
                suggestion.to_dict() for suggestion in self.companion_suggestions
            ],
            "recommendations": [
                {
                    "label": check.label,
                    "points": check.weight,
                    "recommendation": check.recommendation,
                }
                for check in self.missing
            ],
            "markdown": self.markdown(),
        }


MANIFESTS = {
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "package.json",
    "go.mod",
    "cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "gemfile",
}
LOCKFILES = {
    "uv.lock",
    "poetry.lock",
    "pdm.lock",
    "pipfile.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "cargo.lock",
    "go.sum",
    "composer.lock",
    "gemfile.lock",
    "gradle.lockfile",
}
SOURCE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".swift",
    ".scala",
}
MONOREPO_CONTAINERS = {"apps", "components", "libs", "modules", "packages", "services"}
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1, "routine": 0}
CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
LOCKFILE_SUGGESTIONS = {
    "package.json": ("package-lock.json", "pnpm-lock.yaml", "yarn.lock"),
    "pyproject.toml": ("uv.lock", "poetry.lock", "pdm.lock"),
    "go.mod": ("go.sum",),
    "cargo.toml": ("Cargo.lock",),
    "build.gradle": ("gradle.lockfile",),
    "build.gradle.kts": ("gradle.lockfile",),
    "composer.json": ("composer.lock",),
    "gemfile": ("Gemfile.lock",),
}


def _root_file(paths: set[str], names: Iterable[str]) -> str | None:
    names = {name.lower() for name in names}
    return next((path for path in sorted(paths) if path.lower() in names), None)


def _first(paths: set[str], predicate) -> str | None:
    return next((path for path in sorted(paths) if predicate(path.lower())), None)


def _check(
    key: str, category: str, label: str, weight: int, found: str | None, recommendation: str
) -> Check:
    return Check(
        key=key,
        category=category,
        label=label,
        passed=found is not None,
        weight=weight,
        evidence=found or "Not detected",
        recommendation=recommendation,
    )


def _is_test_path(path: str) -> bool:
    pure_path = PurePosixPath(path.lower())
    if any(part in {"test", "tests", "spec", "specs"} for part in pure_path.parts[:-1]):
        return True
    name = pure_path.name
    stem = pure_path.stem
    return (
        stem.startswith("test_") or stem.endswith("_test") or ".test." in name or ".spec." in name
    )


def _review_lane_key(path: str) -> str:
    parts = PurePosixPath(path).parts
    if len(parts) == 1:
        return "."
    if parts[0].lower() in MONOREPO_CONTAINERS and len(parts) >= 3:
        return "/".join(parts[:2])
    return parts[0]


def find_codeowners_path(paths: Iterable[str]) -> str | None:
    available = set(paths)
    return next((path for path in CODEOWNERS_LOCATIONS if path in available), None)


def _codeowners_regex(pattern: str) -> re.Pattern | None:
    pattern = pattern.strip()
    if not pattern or pattern.startswith("!") or "[" in pattern:
        return None
    anchored = pattern.startswith("/")
    pattern = pattern.lstrip("/")
    contains_slash = "/" in pattern
    if pattern.endswith("/"):
        pattern += "**"

    translated = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 1
                if index + 1 < len(pattern) and pattern[index + 1] == "/":
                    index += 1
                    translated.append("(?:.*/)?")
                else:
                    translated.append(".*")
            else:
                translated.append("[^/]*")
        elif char == "?":
            translated.append("[^/]")
        else:
            translated.append(re.escape(char))
        index += 1

    body = "".join(translated)
    prefix = "^" if anchored or contains_slash else "^(?:.*/)?"
    suffix = "$" if contains_slash else r"(?:/.*)?$"
    return re.compile(prefix + body + suffix)


def _codeowners_rules(content: str) -> tuple[tuple[re.Pattern, tuple[str, ...]], ...]:
    rules = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        pattern = _codeowners_regex(fields[0])
        if pattern:
            owners = []
            for field in fields[1:]:
                if field.startswith("#"):
                    break
                if field.startswith("@") or "@" in field:
                    owners.append(field)
            rules.append((pattern, tuple(owners)))
    return tuple(rules)


def _owners_for_path(
    path: str, rules: tuple[tuple[re.Pattern, tuple[str, ...]], ...]
) -> tuple[str, ...]:
    owners: tuple[str, ...] = ()
    for pattern, candidate_owners in rules:
        if pattern.match(path):
            owners = candidate_owners
    return owners


def _candidate_test_paths(source_path: str) -> tuple[str, ...]:
    path = PurePosixPath(source_path)
    suffix = path.suffix.lower()
    parts = list(path.parts)
    prefix: list[str] = []
    relative = parts
    if len(parts) >= 3 and parts[0].lower() in MONOREPO_CONTAINERS:
        prefix, relative = parts[:2], parts[2:]

    relative_path = PurePosixPath(*relative)
    parent = relative_path.parent
    stem = relative_path.stem
    if parent.parts and parent.parts[0].lower() in {"src", "lib", "app"}:
        inner_parent = PurePosixPath(*parent.parts[1:])
    else:
        inner_parent = parent

    def joined(*items: str | PurePosixPath) -> str:
        return str(PurePosixPath(*prefix, *items))

    if suffix == ".py":
        return (
            joined("tests", inner_parent, f"test_{stem}.py"),
            joined(parent, f"test_{stem}.py"),
            joined("tests", f"test_{stem}.py"),
        )
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return (
            joined(parent, f"{stem}.test{suffix}"),
            joined(parent, "__tests__", f"{stem}.test{suffix}"),
        )
    if suffix == ".go":
        return (joined(parent, f"{stem}_test.go"),)
    if suffix == ".rb":
        return (joined("spec", inner_parent, f"{stem}_spec.rb"),)
    if suffix in {".java", ".kt"} and "main" in relative:
        test_parts = ["test" if part == "main" else part for part in relative[:-1]]
        return (joined(*test_parts, f"{stem}Test{suffix}"),)
    if suffix == ".rs":
        return (joined("tests", f"{stem}.rs"),)
    return (joined("tests", inner_parent, f"test_{stem}{suffix}"),)


def _lockfile_candidates(manifest_path: str) -> tuple[str, ...]:
    path = PurePosixPath(manifest_path)
    lockfiles = LOCKFILE_SUGGESTIONS.get(path.name.lower(), tuple(sorted(LOCKFILES)))
    return tuple(
        dict.fromkeys(
            str(location)
            for lockfile in lockfiles
            for location in (path.parent / lockfile, PurePosixPath(lockfile))
        )
    )


def _companion_suggestions(
    paths: set[str], files: tuple[ChangedFile, ...]
) -> tuple[CompanionSuggestion, ...]:
    changed_paths = {file.filename for file in files if file.status != "removed"}
    source_files = [
        file
        for file in files
        if file.status != "removed"
        and PurePosixPath(file.filename).suffix.lower() in SOURCE_SUFFIXES
        and not _is_test_path(file.filename)
    ]
    suggestions: list[CompanionSuggestion] = []
    for file in source_files:
        candidates = _candidate_test_paths(file.filename)
        if any(candidate in changed_paths for candidate in candidates):
            continue
        existing = next((candidate for candidate in candidates if candidate in paths), None)
        suggestions.append(
            CompanionSuggestion(
                kind="test",
                source_path=file.filename,
                suggested_path=existing or candidates[0],
                action="update" if existing else "add",
                reason="Exercise the changed behavior with a focused regression test.",
            )
        )

    for file in files:
        manifest_name = PurePosixPath(file.filename.lower()).name
        lockfiles = LOCKFILE_SUGGESTIONS.get(manifest_name)
        if file.status == "removed" or not lockfiles:
            continue
        candidates = _lockfile_candidates(file.filename)
        if any(candidate in changed_paths for candidate in candidates):
            continue
        existing = next((candidate for candidate in candidates if candidate in paths), None)
        suggestions.append(
            CompanionSuggestion(
                kind="lockfile",
                source_path=file.filename,
                suggested_path=existing or str(PurePosixPath(file.filename).parent / lockfiles[0]),
                action="update" if existing else "add",
                reason="Keep the resolved dependency graph reproducible.",
            )
        )

    return tuple(suggestions[:12])


def _review_questions(
    lane_files: list[ChangedFile],
    sources: list[ChangedFile],
    matched_tests: int,
    unowned_files: int,
    has_codeowners: bool,
) -> tuple[str, ...]:
    """Path-derived prompts, not claims about source behavior or test coverage."""
    paths = [file.filename.lower() for file in lane_files]
    added_or_modified = [file.filename.lower() for file in lane_files if file.status != "removed"]
    questions = []
    if any(path.startswith(".github/workflows/") for path in paths):
        questions.append(
            "Were workflow token permissions and untrusted-PR secret exposure checked?"
        )
    if any(
        any(part in {"migration", "migrations"} for part in PurePosixPath(path).parts)
        for path in added_or_modified
    ):
        questions.append(
            "Is the migration backward-compatible, and is the rollback path documented?"
        )
    if any(PurePosixPath(path).name in MANIFESTS for path in paths):
        questions.append("Was the dependency change reviewed with its corresponding lockfile?")
    if any(
        PurePosixPath(path).name in {".env", "id_rsa", "id_ed25519"}
        or PurePosixPath(path).suffix in {".pem", ".p12", ".pfx", ".key"}
        for path in added_or_modified
    ):
        questions.append("Could any changed credential-like file contain a live secret?")
    if any(
        any(
            part in {"auth", "authentication", "authorization", "permissions"}
            for part in PurePosixPath(file.filename.lower()).parts
        )
        or any(
            token in PurePosixPath(file.filename.lower()).stem for token in ("auth", "permission")
        )
        for file in sources
    ):
        questions.append("Were access-control and negative cases covered by a focused test?")
    if sources and matched_tests < len(sources):
        questions.append(
            "Which tests exercise the changed behavior? "
            "Matching changed test paths were found for "
            f"{matched_tests}/{len(sources)} source files."
        )
    if has_codeowners and unowned_files:
        questions.append(
            f"Who will review the {unowned_files} changed file(s) without a CODEOWNERS match?"
        )
    if not questions:
        questions.append("What behavior changed here, and how was it verified?")
    return tuple(questions[:4])


def _review_map(
    files: tuple[ChangedFile, ...],
    risks: tuple[RiskSignal, ...],
    codeowners_content: str = "",
    paths: set[str] | None = None,
    policy: AuditPolicy | None = None,
) -> tuple[ReviewLane, ...]:
    paths = paths or set()
    policy = policy or AuditPolicy()
    grouped: dict[str, list[ChangedFile]] = {}
    for file in files:
        grouped.setdefault(_review_lane_key(file.filename), []).append(file)

    lane_signals: dict[str, list[RiskSignal]] = {}
    for risk in risks:
        if risk.path:
            lane_signals.setdefault(_review_lane_key(risk.path), []).append(risk)

    owner_rules = _codeowners_rules(codeowners_content)
    changed_paths = {file.filename for file in files if file.status != "removed"}
    test_paths_by_lane: dict[str, list[str]] = {}
    for path in sorted(paths):
        if _is_test_path(path):
            test_paths_by_lane.setdefault(_review_lane_key(path), []).append(path)
    lanes = []
    for key, lane_files in grouped.items():
        signals = lane_signals.get(key, [])
        file_owners = [_owners_for_path(file.filename, owner_rules) for file in lane_files]
        owners = tuple(dict.fromkeys(owner for group in file_owners for owner in group))
        unowned_files = sum(not group for group in file_owners)
        sources = [
            file
            for file in lane_files
            if file.status != "removed"
            and PurePosixPath(file.filename).suffix.lower() in SOURCE_SUFFIXES
            and not _is_test_path(file.filename)
            and not policy.ignored(file.filename)
        ]
        matched = sum(
            any(candidate in changed_paths for candidate in _candidate_test_paths(file.filename))
            for file in sources
        )
        active_lane_files = [file for file in lane_files if not policy.ignored(file.filename)]
        questions = (
            _review_questions(active_lane_files, sources, matched, unowned_files, bool(owner_rules))
            if active_lane_files
            else ("Heuristic warnings for this lane are suppressed by .qnode.json.",)
        )
        attention = max(
            (risk.severity for risk in signals),
            key=lambda severity: SEVERITY_RANK[severity],
            default="routine",
        )
        if sources and matched < len(sources) and attention == "routine":
            attention = "medium"
        targets = tuple(
            dict.fromkeys(
                candidate
                for file in sources
                for candidate in _candidate_test_paths(file.filename)
                if candidate in paths
            )
        )[:5]
        if not targets:
            targets = tuple(test_paths_by_lane.get(key, ())[:3])
        if any(policy.critical(file.filename) for file in lane_files):
            attention = "high"
            questions = (
                "A changed path is marked critical in .qnode.json. "
                "Which downstream behavior and rollback path were checked?",
                *questions,
            )[:4]
        lanes.append(
            ReviewLane(
                key=key,
                label="Repository root" if key == "." else f"{key}/",
                attention=attention,
                file_count=len(lane_files),
                additions=sum(file.additions for file in lane_files),
                deletions=sum(file.deletions for file in lane_files),
                signals=tuple(dict.fromkeys(risk.title for risk in signals)),
                paths=tuple(file.filename for file in lane_files[:5]),
                owners=owners,
                unowned_files=unowned_files,
                source_files=len(sources),
                test_path_matches=matched,
                review_questions=questions,
                test_targets=targets,
                configured_jobs=policy.jobs_for([file.filename for file in lane_files]),
            )
        )

    return tuple(
        sorted(
            lanes,
            key=lambda lane: (-SEVERITY_RANK[lane.attention], -lane.changes, lane.key),
        )
    )


def _pull_request_risks(
    files: tuple[ChangedFile, ...], policy: AuditPolicy | None = None
) -> tuple[RiskSignal, ...]:
    if not files:
        return ()

    policy = policy or AuditPolicy()
    active_files = tuple(file for file in files if not policy.ignored(file.filename))

    def annotation_path(file: ChangedFile) -> str | None:
        return None if file.status == "removed" else file.filename

    source_files = [
        file
        for file in active_files
        if file.status != "removed"
        and PurePosixPath(file.filename).suffix.lower() in SOURCE_SUFFIXES
    ]
    test_files = [file for file in active_files if _is_test_path(file.filename)]
    changed_paths = {file.filename for file in active_files if file.status != "removed"}
    manifest_changes = [
        file
        for file in active_files
        if file.status != "removed"
        and PurePosixPath(file.filename.lower()).name in MANIFESTS
        and not any(path in changed_paths for path in _lockfile_candidates(file.filename))
    ]
    risks: list[RiskSignal] = []

    if source_files and not test_files:
        risks.append(
            RiskSignal(
                "source-without-tests",
                "medium",
                "Source changed without tests",
                f"{len(source_files)} source file(s) changed, but no test file changed.",
                annotation_path(source_files[0]),
                "Add or update focused tests, or explain why existing coverage is sufficient.",
            )
        )

    if manifest_changes:
        risks.append(
            RiskSignal(
                "manifest-without-lock",
                "medium",
                "Dependency manifest changed without lockfile",
                f"{manifest_changes[0].filename} changed without a matching lockfile update.",
                annotation_path(manifest_changes[0]),
                "Regenerate the lockfile or document why the dependency graph is unchanged.",
            )
        )

    workflow = next(
        (file for file in active_files if file.filename.lower().startswith(".github/workflows/")),
        None,
    )
    if workflow:
        risks.append(
            RiskSignal(
                "workflow-change",
                "low",
                "CI workflow changed",
                "Workflow changes can alter permissions, secrets exposure, and release behavior.",
                annotation_path(workflow),
                "Review permissions, pin third-party actions, and test the workflow "
                "on an untrusted pull request.",
            )
        )

    sensitive = next(
        (
            file
            for file in files
            if file.status != "removed"
            and (
                PurePosixPath(file.filename.lower()).name in {".env", "id_rsa", "id_ed25519"}
                or PurePosixPath(file.filename.lower()).suffix in {".pem", ".p12", ".pfx", ".key"}
            )
        ),
        None,
    )
    if sensitive:
        risks.append(
            RiskSignal(
                "credential-path",
                "high",
                "Possible credential material committed",
                f"The path `{sensitive.filename}` resembles a secret or private-key file.",
                sensitive.filename,
                "Remove it, rotate exposed credentials, and provide a redacted "
                "example file instead.",
            )
        )

    total_changes = sum(file.changes for file in active_files)
    if total_changes >= 800:
        largest = max(active_files, key=lambda file: file.changes)
        risks.append(
            RiskSignal(
                "large-change",
                "medium",
                "Large review surface",
                f"This pull request changes {total_changes:,} lines across "
                f"{len(active_files)} non-ignored files.",
                annotation_path(largest),
                "Consider splitting unrelated work and highlight generated or mechanical changes.",
            )
        )

    migration = next(
        (
            file
            for file in active_files
            if any(
                part in {"migration", "migrations"}
                for part in PurePosixPath(file.filename.lower()).parts
            )
        ),
        None,
    )
    if migration:
        risks.append(
            RiskSignal(
                "migration-change",
                "low",
                "Database migration changed",
                "Schema changes may require rollout ordering and rollback planning.",
                annotation_path(migration),
                "Verify backward compatibility, backup requirements, and the rollback path.",
            )
        )

    critical_files = [file for file in files if policy.critical(file.filename)]
    for file in critical_files[:20]:
        risks.append(
            RiskSignal(
                "critical-path",
                "high",
                "Configured critical path changed",
                f"{file.filename} matches a critical path declared in .qnode.json; "
                f"its PR status is {file.status}.",
                file.filename,
                "Ask the responsible reviewer to check downstream impact, test evidence, "
                "and rollback plans.",
                annotate=file.status != "removed",
            )
        )
    if len(critical_files) > 20:
        risks.append(
            RiskSignal(
                "critical-path-overflow",
                "high",
                "Additional critical paths changed",
                f"{len(critical_files) - 20} additional configured critical paths changed.",
            )
        )

    return tuple(risks)


def audit_tree(
    tree_paths: list[str],
    changed_files: Iterable[ChangedFile] = (),
    *,
    codeowners_content: str = "",
    tree_truncated: bool = False,
    files_truncated: bool = False,
    policy: AuditPolicy | None = None,
) -> Audit:
    """Evaluate safeguards using paths, change metadata, and optional CODEOWNERS policy."""
    paths = {str(PurePosixPath(path)) for path in tree_paths if path}
    policy = policy or AuditPolicy()

    readme = _root_file(paths, {"readme", "readme.md", "readme.rst", "readme.txt"})
    license_file = _first(
        paths, lambda path: "/" not in path and path.startswith(("license", "copying"))
    )
    tests = _first(paths, _is_test_path)
    ci = _first(
        paths,
        lambda path: (
            path.startswith((".github/workflows/", ".gitlab-ci"))
            or path in {"circle.yml", ".travis.yml", "azure-pipelines.yml"}
        ),
    )
    manifest = _first(paths, lambda path: PurePosixPath(path).name in MANIFESTS)
    lockfile = _first(
        paths,
        lambda path: (
            PurePosixPath(path).name in LOCKFILES
            or path in {"dockerfile", "makefile", "environment.yml", "environment.yaml"}
        ),
    )
    security = _first(paths, lambda path: path in {"security.md", ".github/security.md"})
    dependency_updates = _first(
        paths,
        lambda path: (
            path == ".github/dependabot.yml"
            or PurePosixPath(path).name in {"renovate.json", "renovate.json5"}
        ),
    )
    contributing = _root_file(
        paths, {"contributing.md", "contributing.rst", ".github/contributing.md"}
    )
    codeowners = _first(
        paths, lambda path: path in {"codeowners", ".github/codeowners", "docs/codeowners"}
    )
    changelog = _root_file(paths, {"changelog.md", "changes.md", "history.md", "releases.md"})
    templates = _first(
        paths,
        lambda path: path.startswith((".github/issue_template/", ".github/pull_request_template")),
    )

    checks = (
        _check(
            "readme",
            "Foundation",
            "Project documentation",
            12,
            readme,
            "Add a concise README with purpose, setup, usage, and support information.",
        ),
        _check(
            "license",
            "Foundation",
            "License",
            10,
            license_file,
            "Choose an OSI-approved license and add its full text at the repository root.",
        ),
        _check(
            "tests",
            "Quality",
            "Automated tests",
            14,
            tests,
            "Add a focused automated test suite covering the project's critical behavior.",
        ),
        _check(
            "ci",
            "Quality",
            "Continuous integration",
            14,
            ci,
            "Run tests and basic quality checks automatically for pushes and pull requests.",
        ),
        _check(
            "manifest",
            "Supply chain",
            "Dependency manifest",
            8,
            manifest,
            "Declare project dependencies in the ecosystem's standard manifest.",
        ),
        _check(
            "lockfile",
            "Supply chain",
            "Reproducible dependency/build file",
            8,
            lockfile,
            "Commit a lockfile or reproducible environment/build definition.",
        ),
        _check(
            "security",
            "Security",
            "Security policy",
            10,
            security,
            "Add SECURITY.md with supported versions and a private reporting channel.",
        ),
        _check(
            "dependency-updates",
            "Security",
            "Automated dependency updates",
            6,
            dependency_updates,
            "Configure Dependabot or Renovate for supported package ecosystems.",
        ),
        _check(
            "contributing",
            "Community",
            "Contribution guide",
            6,
            contributing,
            "Document the development setup, tests, and pull-request expectations.",
        ),
        _check(
            "codeowners",
            "Governance",
            "Code ownership",
            5,
            codeowners,
            "Define CODEOWNERS for high-risk or actively maintained areas.",
        ),
        _check(
            "changelog",
            "Operations",
            "Change history",
            3,
            changelog,
            "Maintain a changelog or release notes for user-visible changes.",
        ),
        _check(
            "templates",
            "Community",
            "Issue or pull-request templates",
            4,
            templates,
            "Add templates that request reproducible reports and verification details.",
        ),
    )

    changed_files = tuple(changed_files)
    risks = _pull_request_risks(changed_files, policy)
    companion_suggestions = _companion_suggestions(
        paths, tuple(file for file in changed_files if not policy.ignored(file.filename))
    )
    return Audit(
        checks=checks,
        risks=risks,
        review_lanes=_review_map(changed_files, risks, codeowners_content, paths, policy),
        companion_suggestions=companion_suggestions,
        tree_truncated=tree_truncated,
        files_truncated=files_truncated,
        ignored_files=sum(policy.ignored(file.filename) for file in changed_files),
        policy_warning=policy.warning,
    )


def audit_rules() -> list[dict]:
    return [
        {
            "key": check.key,
            "category": check.category,
            "label": check.label,
            "weight": check.weight,
            "recommendation": check.recommendation,
        }
        for check in audit_tree([]).checks
    ]


def compare_review_signals(
    baseline: Audit,
    current: Audit,
    *,
    baseline_sha: str,
    reviewed_at: str,
    changed_paths: Iterable[str],
) -> ReviewDelta:
    """Diff path-scoped and PR-wide advisory signals, not source-code behavior."""
    def identity(signal: RiskSignal) -> tuple[str, str | None]:
        return signal.key, signal.path if signal.key == "critical-path" else None

    # Blob IDs reveal changed paths, but not line counts. Churn-based signals
    # cannot be compared fairly with this privacy-preserving baseline.
    before = {identity(signal): signal for signal in baseline.risks if signal.key != "large-change"}
    after = {identity(signal): signal for signal in current.risks if signal.key != "large-change"}
    unique_paths = tuple(dict.fromkeys(changed_paths))
    return ReviewDelta(
        baseline_sha=baseline_sha,
        reviewed_at=reviewed_at,
        changed_paths=unique_paths[:100],
        changed_path_count=len(unique_paths),
        new_signals=tuple(signal for key, signal in after.items() if key not in before),
        resolved_signals=tuple(signal for key, signal in before.items() if key not in after),
    )
