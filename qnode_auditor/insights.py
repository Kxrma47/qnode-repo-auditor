"""Bounded, evidence-labelled review signals from GitHub metadata."""

from __future__ import annotations

import re

FAILURE_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}


def check_state(run: dict) -> str:
    if run.get("status") != "completed":
        return "pending"
    conclusion = run.get("conclusion")
    if conclusion == "success":
        return "passed"
    if conclusion in FAILURE_CONCLUSIONS:
        return "failed"
    if conclusion in {"skipped", "neutral", "cancelled", "stale"}:
        return conclusion
    return "unknown"


def ci_evidence(snapshot: dict | None, lanes: list[dict]) -> dict:
    """Map declared job labels to observed checks without inferring branch requirements."""
    configured = sorted({job for lane in lanes for job in lane.get("configured_jobs", [])})
    if snapshot is None:
        return {
            "available": False,
            "complete": False,
            "configured_jobs": configured,
            "observed": [],
            "not_observed": [],
        }
    runs = snapshot["runs"]
    observed = [
        {
            "name": run["name"],
            "state": check_state(run),
            "html_url": run["html_url"],
            "configured": run["name"] in configured,
        }
        for run in runs
    ]
    names = {run["name"] for run in runs}
    return {
        "available": True,
        "complete": snapshot["complete"],
        "configured_jobs": configured,
        "observed": observed,
        "not_observed": [job for job in configured if job not in names],
    }


def attention_item(
    pull: dict, review: dict | None, checks: dict | None, *, review_available: bool = True
) -> dict:
    runs = checks["runs"] if checks is not None else []
    states = [check_state(run) for run in runs]
    signals = []
    if "failed" in states:
        signals.append("Observed check failure")
    if review and review["commit_sha"] != pull["head_sha"]:
        signals.append("Head differs from latest submitted human review")
    if "pending" in states:
        signals.append("Observed check in progress")
    if not review_available:
        signals.append("Review listing unavailable")
    elif review is None:
        signals.append("No submitted human review found in bounded listing")
    if checks is None or not checks["complete"]:
        signals.append("Check listing unavailable or incomplete")
    elif not runs:
        signals.append("No check runs returned for head commit")
    return {
        "number": pull["number"],
        "title": pull["title"],
        "html_url": pull["html_url"],
        "draft": pull["draft"],
        "updated_at": pull["updated_at"],
        "signals": signals,
        "priority": 0
        if "failed" in states
        else 1
        if review and review["commit_sha"] != pull["head_sha"]
        else 2,
    }


def compare_audits(base, head, base_ref: str, head_ref: str) -> dict:
    base_checks = {check.key: check for check in base.checks}
    head_checks = {check.key: check for check in head.checks}
    changes = [
        {
            "key": key,
            "label": head_checks[key].label,
            "before": base_checks[key].passed,
            "after": head_checks[key].passed,
        }
        for key in sorted(base_checks.keys() & head_checks.keys())
        if base_checks[key].passed != head_checks[key].passed
    ]
    return {
        "base": {"ref": base_ref, "score": base.score, "grade": base.grade},
        "head": {"ref": head_ref, "score": head.score, "grade": head.grade},
        "score_delta": head.score - base.score,
        "changed_checks": changes,
        "note": "Path-based safeguard comparison, not proof that tests ran or behavior improved.",
    }


def _markdown_text(value: str) -> str:
    """Keep untrusted GitHub names and repository policy text inert in copied Markdown."""
    compact = " ".join(str(value).split())[:160]
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", compact)


def review_handoff(pull: dict, audit: dict, ci: dict) -> dict:
    """Separate observed PR metadata from verification questions for a human handoff."""
    lanes = audit["review_map"]
    observed = ci.get("observed", [])
    checks_by_name: dict[str, set[str]] = {}
    for check in observed:
        checks_by_name.setdefault(check["name"], set()).add(check["state"])

    lane_evidence = []
    for lane in lanes[:24]:
        jobs = []
        for name in lane["configured_jobs"]:
            states = sorted(checks_by_name.get(name, ()))
            jobs.append(
                {
                    "name": name,
                    "states": states
                    if states
                    else ["not observed" if ci["available"] else "unknown"],
                }
            )
        lane_evidence.append(
            {
                "label": lane["label"],
                "attention": lane["attention"],
                "files": lane["file_count"],
                "owners": lane["owners"],
                "unowned_files": lane["unowned_files"],
                "source_files": lane["source_files"],
                "test_path_matches": lane["test_path_matches"],
                "jobs": jobs,
                "signals": lane["signals"],
            }
        )

    reported_files = pull.get("changed_files", 0)
    facts = [
        f"GitHub reports {reported_files} changed "
        f"{'file' if reported_files == 1 else 'files'} across {len(lanes)} QNode review "
        f"{'lane' if len(lanes) == 1 else 'lanes'}.",
    ]
    if audit["files_truncated"] or audit["tree_truncated"]:
        facts.append("GitHub data was incomplete; path-based observations may omit files.")
    if audit["risks"]:
        signal_count = len(audit["risks"])
        facts.append(
            f"QNode flagged {signal_count} path-level review "
            f"{'signal' if signal_count == 1 else 'signals'}, not confirmed defects."
        )
    if ci["available"]:
        states = [check["state"] for check in observed]
        if states:
            facts.append(
                f"GitHub returned {len(states)} latest check runs for the PR head: "
                f"{states.count('passed')} passed, {states.count('failed')} failed, "
                f"{states.count('pending')} pending; other conclusions are shown separately."
            )
        else:
            facts.append(
                "GitHub returned no latest check runs for the PR head; "
                "test execution cannot be inferred."
            )
        if not ci["complete"]:
            facts.append("The latest-check listing is incomplete (first 100 results only).")
    else:
        facts.append("GitHub check-run evidence was unavailable to QNode.")
    if audit["review_delta"]:
        facts.append(
            f"{audit['review_delta']['changed_path_count']} repository tree paths differ "
            "from the latest submitted human review commit."
        )

    questions = [
        "Why is this change needed, and which issue or decision provides context?",
        "What behavior changed, and which actual test commands and results verify it?",
    ]
    if any(lane["unowned_files"] for lane in lanes):
        questions.append("Who should review the paths without a declared CODEOWNERS match?")
    if any(lane["source_files"] > lane["test_path_matches"] for lane in lanes):
        questions.append("Which tests exercise the changed behavior beyond filename matches?")
    if not ci["available"] or not observed:
        questions.append("Where can reviewers find CI or manual test results for this head commit?")
    elif any(check["state"] in {"failed", "pending"} for check in observed):
        questions.append("What is the status and follow-up for failed or pending observed checks?")
    if any(contract["status"] == "missing" for contract in audit["change_contracts"]):
        questions.append("Are the missing repository-declared companion changes intentional?")
    if any("migration" in risk["key"] for risk in audit["risks"]):
        questions.append("What are the rollout and rollback steps for the migration?")
    if any(
        path.lower().endswith((".css", ".html", ".tsx", ".jsx"))
        for lane in lanes
        for path in lane["paths"]
    ):
        questions.append("If the interface changed, can you attach a before/after screenshot?")
    for lane in lanes:
        for question in lane["review_questions"]:
            candidate = f"{lane['label']}: {question}"
            if candidate not in questions:
                questions.append(candidate)
            if len(questions) >= 12:
                break
        if len(questions) >= 12:
            break

    number = pull.get("number", "?")
    lines = [
        f"## Review handoff for PR #{number}",
        "",
        "_Generated from paths and GitHub metadata. Fill in answers; no tests or approvals "
        "are claimed by this template._",
        "",
        "### Observed metadata",
    ]
    lines.extend(f"- {_markdown_text(fact)}" for fact in facts)
    lines.extend(["", "### Questions for the contributor", ""])
    lines.extend(f"- [ ] {_markdown_text(question)}" for question in questions)
    if lane_evidence:
        lines.extend(["", "### Review lanes", ""])
        for lane in lane_evidence[:8]:
            owners = ", ".join(lane["owners"]) or "no declared match"
            job_text = (
                ", ".join(f"{job['name']} ({'/'.join(job['states'])})" for job in lane["jobs"])
                or "no job mapping configured"
            )
            lines.append(
                f"- {_markdown_text(lane['label'])}: {lane['files']} "
                f"{'file' if lane['files'] == 1 else 'files'}; "
                f"owners {_markdown_text(owners)}; changed test-path matches "
                f"{lane['test_path_matches']}/{lane['source_files']} source files; "
                f"mapped checks {_markdown_text(job_text)}."
            )
        if len(lanes) > 8:
            lines.append(f"- {len(lanes) - 8} more lanes in the QNode JSON report.")
    return {
        "facts": facts,
        "questions": questions,
        "lanes": lane_evidence,
        "total_lanes": len(lanes),
        "markdown": "\n".join(lines),
        "note": "Advisory metadata only; no test coverage, approvals, or merge readiness inferred.",
    }
