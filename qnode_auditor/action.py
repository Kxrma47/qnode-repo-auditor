"""Local, content-private entrypoint for the QNode GitHub Action."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .audit import ChangedFile, audit_tree, find_codeowners_path
from .policy import POLICY_PATH, AuditPolicy, parse_policy


def _git(*arguments: str, cwd: Path) -> bytes:
    return subprocess.check_output(("git", *arguments), cwd=cwd)


def tracked_paths(workspace: Path, head: str) -> list[str]:
    output = _git("ls-tree", "-r", "--name-only", "-z", head, cwd=workspace)
    return [path.decode("utf-8", "surrogateescape") for path in output.split(b"\0") if path]


def changed_files(workspace: Path, base: str, head: str) -> list[ChangedFile]:
    if not base:
        return []
    output = _git("diff", "--numstat", "--no-renames", "-z", f"{base}...{head}", cwd=workspace)
    changes = []
    for row in output.split(b"\0"):
        if not row:
            continue
        fields = row.decode("utf-8", "surrogateescape").split("\t", 2)
        if len(fields) != 3:
            raise ValueError("Git returned an unexpected diff row")
        additions, deletions, path = fields
        changes.append(
            ChangedFile(
                filename=path,
                additions=int(additions) if additions.isdigit() else 0,
                deletions=int(deletions) if deletions.isdigit() else 0,
                status="modified",
            )
        )
    return changes


def file_at_ref(workspace: Path, ref: str, path: str) -> str:
    try:
        return _git("show", f"{ref}:{path}", cwd=workspace).decode("utf-8")
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        return ""


def build_report(workspace: Path, *, base: str = "", head: str = "HEAD"):
    paths = tracked_paths(workspace, head)
    changes = changed_files(workspace, base, head)
    codeowners_path = find_codeowners_path(paths)
    codeowners = file_at_ref(workspace, head, codeowners_path) if codeowners_path else ""
    policy = AuditPolicy()
    if POLICY_PATH in paths:
        policy_text = file_at_ref(workspace, head, POLICY_PATH)
        policy = parse_policy(policy_text) if policy_text else AuditPolicy()
    return audit_tree(paths, changes, codeowners_content=codeowners, policy=policy)


def _append(path: str, text: str) -> None:
    if path:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(text)


def main() -> int:
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    base = os.environ.get("QNODE_BASE", "").strip()
    head = os.environ.get("QNODE_HEAD", "HEAD").strip() or "HEAD"
    audit = build_report(workspace, base=base, head=head)
    context = f"Compared `{base[:12]}` with `{head[:12]}`." if base else f"Scanned `{head}`."
    summary = (
        f"{audit.markdown()}\n\n---\n{context} QNode inspected tracked paths, optional policy, "
        "and CODEOWNERS only; it did not read application source contents. Signals are advisory.\n"
    )
    _append(os.environ.get("GITHUB_STEP_SUMMARY", ""), summary)
    _append(
        os.environ.get("GITHUB_OUTPUT", ""),
        f"score={audit.score}\ngrade={audit.grade}\nrisk_count={len(audit.risks)}\n",
    )
    print(f"QNode: {audit.score}/100, grade {audit.grade}, {len(audit.risks)} risk signal(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
