from __future__ import annotations

import subprocess
from pathlib import Path

from qnode_auditor.action import build_report, main


def git(workspace: Path, *arguments: str) -> str:
    return subprocess.check_output(("git", *arguments), cwd=workspace, text=True).strip()


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def repository(tmp_path: Path) -> tuple[Path, str]:
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "qnode@example.invalid")
    git(tmp_path, "config", "user.name", "QNode test")
    write(tmp_path / "README.md", "# Example\n")
    write(tmp_path / "src/service.py", "VALUE = 1\n")
    write(tmp_path / "tests/test_service.py", "def test_value():\n    assert True\n")
    write(tmp_path / ".github/CODEOWNERS", "/src/ @example/backend\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Initial")
    base = git(tmp_path, "rev-parse", "HEAD")
    write(tmp_path / "src/service.py", "VALUE = 2\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Change service")
    return tmp_path, base


def test_action_builds_local_path_only_pr_report(tmp_path):
    workspace, base = repository(tmp_path)
    report = build_report(workspace, base=base, head="HEAD")

    assert report.score > 0
    assert [risk.key for risk in report.risks] == ["source-without-tests"]
    assert report.review_lanes[0].owners == ("@example/backend",)
    assert report.companion_suggestions[0].suggested_path == "tests/test_service.py"


def test_action_writes_summary_and_outputs(tmp_path, monkeypatch):
    workspace, base = repository(tmp_path)
    summary = tmp_path / "summary.md"
    outputs = tmp_path / "outputs.txt"
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.setenv("QNODE_BASE", base)
    monkeypatch.setenv("QNODE_HEAD", "HEAD")

    assert main() == 0
    assert "Engineering readiness" in summary.read_text()
    assert "did not read application source contents" in summary.read_text()
    assert "QNode review intelligence" in summary.read_text()
    assert "score=" in outputs.read_text()
    assert "risk_count=1" in outputs.read_text()
    assert "blast_radius=" in outputs.read_text()
