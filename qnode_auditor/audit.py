from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath


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

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Audit:
    checks: tuple[Check, ...]
    risks: tuple[RiskSignal, ...] = ()
    tree_truncated: bool = False

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
            if not risk.path:
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

        if self.tree_truncated:
            lines.extend(
                ["", "> GitHub truncated the recursive tree response. Results may be incomplete."]
            )

        lines.extend(
            [
                "",
                "_Advisory only. QNode reads repository metadata and paths, "
                "never source contents, and never blocks a pull request._",
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
            "checks": [check.to_dict() for check in self.checks],
            "risks": [risk.to_dict() for risk in self.risks],
            "recommendations": [
                {
                    "label": check.label,
                    "points": check.weight,
                    "recommendation": check.recommendation,
                }
                for check in self.missing
            ],
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


def _pull_request_risks(files: tuple[ChangedFile, ...]) -> tuple[RiskSignal, ...]:
    if not files:
        return ()

    def annotation_path(file: ChangedFile) -> str | None:
        return None if file.status == "removed" else file.filename

    source_files = [
        file
        for file in files
        if file.status != "removed"
        and PurePosixPath(file.filename).suffix.lower() in SOURCE_SUFFIXES
    ]
    test_files = [file for file in files if _is_test_path(file.filename)]
    manifest_changes = [
        file for file in files if PurePosixPath(file.filename.lower()).name in MANIFESTS
    ]
    lock_changes = [
        file for file in files if PurePosixPath(file.filename.lower()).name in LOCKFILES
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

    if manifest_changes and not lock_changes:
        risks.append(
            RiskSignal(
                "manifest-without-lock",
                "medium",
                "Dependency manifest changed without lockfile",
                f"{manifest_changes[0].filename} changed without a recognized lockfile update.",
                annotation_path(manifest_changes[0]),
                "Regenerate the lockfile or document why the dependency graph is unchanged.",
            )
        )

    workflow = next(
        (file for file in files if file.filename.lower().startswith(".github/workflows/")), None
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

    total_changes = sum(file.changes for file in files)
    if total_changes >= 800:
        largest = max(files, key=lambda file: file.changes)
        risks.append(
            RiskSignal(
                "large-change",
                "medium",
                "Large review surface",
                f"This pull request changes {total_changes:,} lines across {len(files)} files.",
                annotation_path(largest),
                "Consider splitting unrelated work and highlight generated or mechanical changes.",
            )
        )

    migration = next(
        (
            file
            for file in files
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

    return tuple(risks)


def audit_tree(
    tree_paths: list[str],
    changed_files: Iterable[ChangedFile] = (),
    *,
    tree_truncated: bool = False,
) -> Audit:
    """Evaluate repository safeguards and PR risk using paths only, never file contents."""
    paths = {str(PurePosixPath(path)) for path in tree_paths if path}

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

    return Audit(
        checks=checks,
        risks=_pull_request_risks(tuple(changed_files)),
        tree_truncated=tree_truncated,
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
