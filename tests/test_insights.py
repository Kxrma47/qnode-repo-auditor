from qnode_auditor.audit import audit_tree
from qnode_auditor.insights import (
    attention_item,
    check_state,
    ci_evidence,
    compare_audits,
    review_handoff,
)


def test_check_states_and_ci_evidence_do_not_infer_required_checks():
    assert check_state({"status": "queued", "conclusion": None}) == "pending"
    assert check_state({"status": "completed", "conclusion": "failure"}) == "failed"
    assert check_state({"status": "completed", "conclusion": "skipped"}) == "skipped"
    snapshot = {
        "complete": False,
        "runs": [
            {
                "name": "unit",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/owner/repo/runs/1",
            },
        ],
    }
    evidence = ci_evidence(snapshot, [{"configured_jobs": ["unit", "integration"]}])
    assert evidence["complete"] is False
    assert evidence["observed"][0]["state"] == "passed"
    assert evidence["observed"][0]["configured"] is True
    assert evidence["not_observed"] == ["integration"]
    assert ci_evidence(None, [])["available"] is False


def test_attention_queue_labels_only_observed_conditions():
    pull = {
        "number": 3,
        "title": "Fix",
        "html_url": "https://github.com/o/r/pull/3",
        "draft": False,
        "head_sha": "new",
        "updated_at": "2026-09-27T00:00:00Z",
    }
    checks = {
        "complete": True,
        "runs": [{"name": "unit", "status": "completed", "conclusion": "failure"}],
    }
    item = attention_item(pull, {"commit_sha": "old"}, checks)
    assert item["priority"] == 0
    assert "Observed check failure" in item["signals"]
    assert "Head differs from latest submitted human review" in item["signals"]
    unknown = attention_item(pull, None, None, review_available=False)
    assert "Review listing unavailable" in unknown["signals"]
    assert not any("No submitted" in signal for signal in unknown["signals"])
    empty = attention_item(pull, {"commit_sha": "new"}, {"complete": True, "runs": []})
    assert empty["signals"] == ["No check runs returned for head commit"]


def test_compare_audits_reports_only_check_transitions():
    base = audit_tree(["README.md"])
    head = audit_tree(["README.md", "LICENSE"])
    comparison = compare_audits(base, head, "old", "new")
    assert comparison["head"]["score"] > comparison["base"]["score"]
    assert len(comparison["changed_checks"]) == 1
    assert comparison["changed_checks"][0]["after"] is True
    assert "not proof" in comparison["note"]


def test_review_handoff_separates_observations_from_unverified_questions():
    pull = {"number": 42, "changed_files": 2}
    audit = {
        "review_map": [
            {
                "label": "src/",
                "attention": "high",
                "file_count": 2,
                "owners": ["@team"],
                "unowned_files": 1,
                "source_files": 2,
                "test_path_matches": 0,
                "configured_jobs": ["unit [special]"],
                "signals": ["Critical path"],
                "paths": ["src/view.tsx"],
                "review_questions": ["Which downstream behavior was checked?"],
            },
        ],
        "files_truncated": False,
        "tree_truncated": False,
        "risks": [{"key": "migration-review"}],
        "review_delta": {"changed_path_count": 1},
        "change_contracts": [{"status": "missing"}],
    }
    ci = {
        "available": True,
        "complete": True,
        "observed": [{"name": "unit [special]", "state": "failed"}],
    }
    handoff = review_handoff(pull, audit, ci)
    assert handoff["total_lanes"] == 1
    assert handoff["facts"][0] == "GitHub reports 2 changed files across 1 QNode review lane."
    assert "1 path-level review signal" in handoff["facts"][1]
    assert handoff["lanes"][0]["jobs"] == [{"name": "unit [special]", "states": ["failed"]}]
    assert any("without a declared CODEOWNERS" in question for question in handoff["questions"])
    assert any("rollout and rollback" in question for question in handoff["questions"])
    assert any("screenshot" in question for question in handoff["questions"])
    assert "no tests or approvals" in handoff["markdown"]
    assert "src/: 2 files" in handoff["markdown"]
    assert "unit \\[special\\]" in handoff["markdown"]


def test_review_handoff_does_not_treat_missing_ci_as_passing():
    pull = {"number": 3, "changed_files": 100}
    audit = {
        "review_map": [],
        "files_truncated": True,
        "tree_truncated": False,
        "risks": [],
        "review_delta": None,
        "change_contracts": [],
    }
    ci = {"available": False, "complete": False, "observed": []}
    handoff = review_handoff(pull, audit, ci)
    assert any("incomplete" in fact for fact in handoff["facts"])
    assert any("unavailable" in fact for fact in handoff["facts"])
    assert "passed" not in handoff["markdown"]
