from dataclasses import replace

from qnode_auditor.audit import ChangedFile, ReviewDelta, audit_tree
from qnode_auditor.intelligence import (
    build_review_intelligence,
    change_memory,
    intelligence_markdown,
    merge_readiness,
    reviewer_load_snapshot,
)
from qnode_auditor.policy import parse_policy


def fixture():
    paths = [
        ".github/CODEOWNERS",
        ".github/workflows/release.yml",
        "database/migrations/002_sessions.sql",
        "src/auth/session.py",
        "src/api/client.py",
        "tests/auth/test_session.py",
        "tests/api/test_client.py",
    ]
    files = (
        ChangedFile("src/auth/session.py", additions=12, deletions=2),
        ChangedFile("src/api/client.py", additions=8, deletions=1),
        ChangedFile("database/migrations/002_sessions.sql", additions=20),
        ChangedFile(".github/workflows/release.yml", additions=3),
    )
    policy = parse_policy(
        '{"version":1,"test_jobs":{"src/**":["unit"]},'
        '"change_contracts":[{"id":"auth-contract","when":["src/auth/**"],'
        '"require_all":["tests/auth/**"]}]}'
    )
    audit = audit_tree(
        paths,
        files,
        codeowners_content=(
            "/src/auth/ @org/security @alice\n"
            "/src/api/ @org/platform @bob\n"
            "/database/ @org/data\n"
            "/.github/ @org/release\n"
        ),
        policy=policy,
    )
    return audit, files


def test_change_memory_requires_repeated_bounded_filename_evidence():
    _, files = fixture()
    memory = change_memory(
        files,
        [
            ["src/auth/session.py", "tests/auth/test_session.py", "docs/auth.md"],
            ["src/auth/session.py", "tests/auth/test_session.py"],
            ["src/auth/session.py", "unrelated.txt"],
        ],
    )
    assert memory["available"] is True
    suggestion = next(
        item
        for item in memory["suggestions"]
        if item["suggested_path"] == "tests/auth/test_session.py"
    )
    assert suggestion["support"] == 2
    assert suggestion["observations"] == 3
    assert suggestion["confidence"] == 0.67
    assert all(item["suggested_path"] != "unrelated.txt" for item in memory["suggestions"])


def test_all_review_intelligence_features_are_evidence_labelled():
    audit, files = fixture()
    audit = replace(
        audit,
        review_delta=ReviewDelta(
            baseline_sha="reviewed",
            reviewed_at="2026-10-08T00:00:00Z",
            changed_paths=("src/auth/session.py",),
            changed_path_count=1,
            new_signals=audit.risks[:1],
            resolved_signals=(),
        ),
    )
    history = [
        ["src/auth/session.py", "tests/auth/test_session.py"],
        ["src/auth/session.py", "tests/auth/test_session.py"],
        ["src/api/client.py", "tests/api/test_client.py"],
        ["src/api/client.py", "tests/api/test_client.py"],
    ]
    ci = {
        "available": True,
        "complete": True,
        "observed": [{"name": "unit", "state": "failed"}],
        "not_observed": [],
    }
    data = build_review_intelligence(
        audit,
        files,
        pull={"head_sha": "head", "base_sha": "base"},
        ci=ci,
        history=history,
        reviewer_load={"@alice": 3, "@org/security": 1, "@bob": 0},
        gate_context={
            "mergeable": "mergeable",
            "merge_state_status": "blocked",
            "review_decision": "changes_requested",
            "unresolved_threads": 1,
            "outdated_unresolved_threads": 1,
            "threads_complete": True,
        },
    )

    assert set(data) == {
        "change_memory",
        "impact_graph",
        "ci_plan",
        "review_freshness",
        "blast_radius",
        "split_plan",
        "reviewer_router",
        "merge_readiness",
        "decision_pack",
    }
    assert data["impact_graph"]["nodes"]
    assert any(edge["kind"] == "co-changed" for edge in data["impact_graph"]["edges"])
    assert any(
        job["name"] == "unit" and job["evidence"] == "configured" for job in data["ci_plan"]["jobs"]
    )
    assert data["review_freshness"]["status"] == "stale"
    assert data["blast_radius"]["score"] > 30
    assert data["split_plan"]["recommended"] is True
    auth_route = next(
        route for route in data["reviewer_router"]["routes"] if route["lane"] == "src/"
    )
    assert auth_route["suggested"] in {"@alice", "@bob", "@org/platform", "@org/security"}
    assert "not defect probability" in data["blast_radius"]["note"]
    assert "not source-code dependencies" in data["impact_graph"]["note"]
    assert "QNode review intelligence" in intelligence_markdown(data)
    assert data["merge_readiness"]["status"] == "blocked"
    assert {item["code"] for item in data["merge_readiness"]["blockers"]} == {
        "changes-requested",
        "checks-failed",
        "unresolved-threads",
    }
    assert len(data["decision_pack"]["items"]) == 10
    assert {item["key"] for item in data["decision_pack"]["items"]} == {
        "verification-debt",
        "ownership-coverage",
        "change-concentration",
        "rollout-surface",
        "rollback-evidence",
        "contract-surface",
        "dependency-sync",
        "reviewer-resilience",
        "queue-friction",
        "evidence-confidence",
    }
    assert all(
        item["detail"] and item["action"] and item["evidence"]
        for item in data["decision_pack"]["items"]
    )


def test_reviewer_load_counts_only_visible_requests():
    assert reviewer_load_snapshot(
        [
            {"requested_reviewers": ["@alice"], "requested_teams": ["@org/core"]},
            {"requested_reviewers": ["@alice", "@bob"], "requested_teams": []},
        ]
    ) == {"@alice": 2, "@org/core": 1, "@bob": 1}


def test_successful_empty_reviewer_snapshot_reports_zero_not_unavailable():
    audit, files = fixture()
    router = build_review_intelligence(audit, files, reviewer_load={})["reviewer_router"]
    assert router["load_available"] is True
    assert all(
        candidate["observed_open_requests"] == 0
        for route in router["routes"]
        for candidate in route["candidates"]
    )


def test_missing_history_and_review_evidence_remain_unknown():
    audit, files = fixture()
    data = build_review_intelligence(
        audit,
        files,
        pull={"head_sha": "head", "base_sha": "base"},
    )
    assert data["change_memory"]["available"] is False
    assert data["change_memory"]["suggestions"] == []
    assert data["review_freshness"]["status"] == "unknown"
    assert data["reviewer_router"]["load_available"] is False
    assert data["merge_readiness"]["status"] == "unknown"


def test_merge_readiness_reports_clear_only_with_complete_observed_evidence():
    pull = {"draft": False}
    ci = {
        "available": True,
        "complete": True,
        "observed": [{"name": "test", "state": "success"}],
        "not_observed": [],
    }
    gate = {
        "mergeable": "mergeable",
        "merge_state_status": "clean",
        "review_decision": "approved",
        "in_merge_queue": False,
        "unresolved_threads": 0,
        "threads_complete": True,
    }
    receipt = merge_readiness(pull, ci, gate)
    assert receipt["status"] == "clear-observed"
    assert receipt["complete"] is True
    assert receipt["blockers"] == []
    assert {item["code"] for item in receipt["satisfied"]} >= {
        "not-draft",
        "mergeable",
        "approved",
        "threads-resolved",
        "checks-passed",
    }


def test_merge_readiness_separates_queue_waiting_from_blockers():
    receipt = merge_readiness(
        {"draft": False},
        {"available": True, "complete": True, "observed": [], "not_observed": []},
        {
            "mergeable": "mergeable",
            "merge_state_status": "blocked",
            "review_decision": "approved",
            "in_merge_queue": True,
            "unresolved_threads": 0,
            "threads_complete": True,
        },
    )
    assert receipt["status"] == "queued"
    assert receipt["blockers"] == []
    assert receipt["waiting"][0]["code"] == "merge-queue"


def test_decision_pack_keeps_unknown_inputs_honest_and_flags_path_evidence():
    audit, files = fixture()
    data = build_review_intelligence(audit, files, pull={"draft": False})
    items = {item["key"]: item for item in data["decision_pack"]["items"]}
    assert items["rollout-surface"]["status"] == "attention"
    assert items["rollback-evidence"]["status"] == "attention"
    assert items["evidence-confidence"]["status"] == "unknown"
    assert items["ownership-coverage"]["value"] == "100% owned"
    assert items["queue-friction"]["detail"] == "NEEDS GITHUB CONFIRMATION"


def test_all_ten_decision_lenses_have_independent_trigger_coverage():
    files = (
        ChangedFile("src/app.py", additions=20),
        ChangedFile("openapi/schema.yaml", additions=4),
        ChangedFile("package.json", additions=2),
        ChangedFile("infra/rollback.sql", additions=8),
        ChangedFile(".github/workflows/release.yml", additions=3),
    )
    audit = audit_tree(
        [file.filename for file in files] + ["README.md", "LICENSE", "SECURITY.md"],
        files,
    )
    data = build_review_intelligence(
        audit,
        files,
        pull={"draft": False},
        ci={
            "available": True,
            "complete": True,
            "observed": [{"name": "test", "state": "failed"}],
            "not_observed": ["integration"],
        },
        history=[
            ["src/app.py", "tests/test_app.py"],
            ["src/app.py", "tests/test_app.py"],
        ],
        gate_context={
            "mergeable": "conflicting",
            "merge_state_status": "dirty",
            "review_decision": "review_required",
            "in_merge_queue": False,
            "unresolved_threads": 0,
            "threads_complete": True,
        },
    )
    items = {item["key"]: item for item in data["decision_pack"]["items"]}
    assert items["verification-debt"]["status"] == "attention"
    assert items["ownership-coverage"]["status"] == "attention"
    assert items["change-concentration"]["status"] == "watch"
    assert items["rollout-surface"]["status"] == "attention"
    assert items["rollback-evidence"]["status"] == "clear"
    assert items["contract-surface"]["status"] == "watch"
    assert items["dependency-sync"]["status"] == "attention"
    assert items["reviewer-resilience"]["status"] == "unknown"
    assert items["queue-friction"]["status"] == "attention"
    assert items["evidence-confidence"]["status"] == "watch"
