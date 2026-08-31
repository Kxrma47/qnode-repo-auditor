from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Check:
    label: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Audit:
    checks: tuple[Check, ...]

    @property
    def score(self) -> int:
        return round(100 * sum(check.passed for check in self.checks) / len(self.checks))

    @property
    def conclusion(self) -> str:
        return "success" if self.score >= 70 else "neutral"

    def markdown(self) -> str:
        rows = ["| Signal | Status | Evidence |", "|---|---:|---|"]
        for check in self.checks:
            rows.append(
                f"| {check.label} | {'✓' if check.passed else '○'} | {check.detail} |"
            )
        rows.append(f"\n**Engineering-readiness score: {self.score}/100**")
        rows.append("\n_Advisory only: QNode never blocks a pull request._")
        return "\n".join(rows)


def _matches(paths: set[str], names: set[str], prefixes: tuple[str, ...] = ()) -> bool:
    lowered = {path.lower() for path in paths}
    return bool(lowered & names) or any(
        path.startswith(prefix) for path in lowered for prefix in prefixes
    )


def audit_tree(tree_paths: list[str]) -> Audit:
    """Evaluate engineering signals using repository paths only—never file contents."""
    paths = {str(PurePosixPath(path)) for path in tree_paths if path}
    lower = {path.lower() for path in paths}

    checks = (
        Check("Documentation", _matches(paths, {"readme.md", "readme.rst", "readme"}), "README detected"),
        Check("License", any(path.startswith(("license", "copying")) for path in lower), "license file detected"),
        Check("Automated tests", any("test" in PurePosixPath(path).name for path in lower) or any(path.startswith("tests/") for path in lower), "test suite detected"),
        Check("Continuous integration", any(path.startswith(".github/workflows/") for path in lower), "GitHub Actions workflow detected"),
        Check("Dependency manifest", _matches(paths, {"pyproject.toml", "requirements.txt", "package.json", "go.mod", "cargo.toml", "pom.xml", "build.gradle"}), "dependency manifest detected"),
        Check("Reproducible environment", _matches(paths, {"dockerfile", "makefile", "poetry.lock", "package-lock.json", "uv.lock", "environment.yml"}), "build or lock file detected"),
        Check("Security policy", ".github/security.md" in lower or "security.md" in lower, "security policy detected"),
    )
    return Audit(checks)
