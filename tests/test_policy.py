import json
from pathlib import Path

from qnode_auditor.audit import ChangedFile, audit_tree, compare_review_signals
from qnode_auditor.policy import AuditPolicy, parse_policy


def test_policy_parses_bounded_config_and_maps_jobs():
    policy = parse_policy(
        json.dumps(
            {
                "version": 1,
                "ignore_paths": ["packages/web/generated/**"],
                "critical_paths": ["services/api/auth/**"],
                "test_jobs": {
                    "services/api/**": ["api-unit", "api-integration"],
                    "services/**": ["api-unit"],
                },
            }
        )
    )
    assert not policy.warning
    assert policy.ignored("packages/web/generated/client.ts")
    assert policy.critical("services/api/auth/login.py")
    assert policy.jobs_for(["services/api/auth/login.py"]) == (
        "api-unit",
        "api-integration",
    )


def test_invalid_policy_fails_closed_without_partial_rules():
    for data in (
        "{bad json",
        '{"version": true, "ignore_paths": ["**"]}',
        '{"version": 1, "test_jobs": {"**": ["bad\njob"]}}',
        '{"version": 1, "ignore_paths": ["../**"]}',
        '{"version": 1, "unexpected": 1}',
        "x" * 32769,
    ):
        policy = parse_policy(data)
        assert policy.warning.startswith("Invalid .qnode.json:")
        assert policy.ignore_paths == ()
        assert policy.critical_paths == ()
        assert policy.test_jobs == ()


def test_ignore_suppresses_heuristics_but_not_credentials_or_critical_paths():
    policy = AuditPolicy(
        ignore_paths=("generated/**", "secrets/**"),
        critical_paths=("generated/**",),
    )
    audit = audit_tree(
        ["generated/client.ts", "secrets/prod.pem"],
        [
            ChangedFile("generated/client.ts", additions=900),
            ChangedFile("secrets/prod.pem", additions=5),
        ],
        policy=policy,
    )
    keys = {signal.key for signal in audit.risks}
    assert keys == {"credential-path", "critical-path"}
    assert audit.ignored_files == 2
    assert not audit.companion_suggestions
    assert "excluded from heuristic warnings" in audit.markdown()


def test_monorepo_test_targets_and_configured_jobs_are_reported():
    policy = AuditPolicy(test_jobs=(("services/api/**", ("api-unit",)),))
    audit = audit_tree(
        ["services/api/src/users.py", "services/api/tests/test_users.py"],
        [ChangedFile("services/api/src/users.py", additions=12)],
        policy=policy,
    )
    lane = audit.review_lanes[0]
    assert lane.test_targets == ("services/api/tests/test_users.py",)
    assert lane.configured_jobs == ("api-unit",)
    assert lane.test_path_matches == 0
    assert audit.to_dict()["review_map"][0]["test_targets"]
    assert "api-unit" in audit.markdown()


def test_repository_example_policy_maps_its_real_test_job():
    root = Path(__file__).resolve().parents[1]
    policy = parse_policy((root / ".qnode.json").read_text(encoding="utf-8"))
    audit = audit_tree(
        ["qnode_auditor/app.py", "tests/test_app.py"],
        [ChangedFile("qnode_auditor/app.py", additions=2)],
        policy=policy,
    )
    lane = audit.review_lanes[0]
    assert lane.test_targets == ("tests/test_app.py",)
    assert lane.configured_jobs == ("test",)
    assert lane.attention == "high"
    assert not policy.warning


def test_removed_critical_path_is_reported_without_invalid_annotation():
    policy = AuditPolicy(critical_paths=("src/auth/**",))
    audit = audit_tree(
        ["README.md"],
        [ChangedFile("src/auth/login.py", status="removed", deletions=20)],
        policy=policy,
    )
    assert [signal.key for signal in audit.risks] == ["critical-path"]
    assert audit.review_lanes[0].attention == "high"
    assert audit.annotations() == []


def test_review_delta_reports_new_and_resolved_signals():
    tree = ["src/app.py", "tests/test_app.py", "pyproject.toml"]
    baseline = audit_tree(
        tree,
        [ChangedFile("src/app.py", additions=3), ChangedFile("pyproject.toml", additions=2)],
    )
    current = audit_tree(
        tree,
        [ChangedFile("src/app.py", additions=5), ChangedFile("tests/test_app.py", additions=4)],
    )
    delta = compare_review_signals(
        baseline,
        current,
        baseline_sha="a" * 40,
        reviewed_at="2026-09-19T00:00:00Z",
        changed_paths=["tests/test_app.py", "pyproject.toml"],
    )
    assert [signal.key for signal in delta.resolved_signals] == [
        "source-without-tests",
        "manifest-without-lock",
    ]
    assert delta.new_signals == ()
    assert delta.changed_paths == ("tests/test_app.py", "pyproject.toml")
    assert delta.changed_lanes == (("tests", 1), (".", 1)) or delta.changed_lanes == (
        (".", 1),
        ("tests", 1),
    )


def test_change_contracts_present_missing_and_declared_owners():
    policy = parse_policy(
        json.dumps(
            {
                "version": 1,
                "change_contracts": [
                    {
                        "id": "api-schema",
                        "when": ["services/api/openapi/**"],
                        "require_all": ["packages/client/generated/**", "tests/contracts/**"],
                        "require_any": ["docs/api/**", "CHANGELOG.md"],
                        "reason": "Update generated client and contract tests",
                    }
                ],
            }
        )
    )
    files = [
        ChangedFile("services/api/openapi/api.yaml"),
        ChangedFile("packages/client/generated/api.ts"),
        ChangedFile("CHANGELOG.md"),
    ]
    audit = audit_tree(
        [file.filename for file in files],
        files,
        policy=policy,
        codeowners_content="/services/api/** @org/api\n",
    )
    contract = audit.change_contracts[0]
    assert contract.status == "missing"
    assert contract.lanes == ("services/api",)
    assert contract.owners == ("@org/api",)
    assert [item.status for item in contract.requirements] == ["present", "missing", "present"]
    assert contract.requirements[0].matched_paths == ("packages/client/generated/api.ts",)
    assert "api-schema · MISSING" in audit.markdown()
    assert audit.to_dict()["change_contracts"][0]["id"] == "api-schema"
    completed = audit_tree(
        [file.filename for file in files] + ["tests/contracts/api_test.py"],
        files + [ChangedFile("tests/contracts/api_test.py")],
        policy=policy,
    )
    assert completed.change_contracts[0].status == "present"


def test_change_contracts_partial_list_is_unknown_not_missing():
    policy = parse_policy(
        json.dumps(
            {
                "version": 1,
                "change_contracts": [
                    {
                        "id": "migration",
                        "when": ["supabase/migrations/**"],
                        "require_all": ["src/database.types.ts"],
                    }
                ],
            }
        )
    )
    files = [ChangedFile("supabase/migrations/001.sql")]
    partial = audit_tree(
        ["supabase/migrations/001.sql"], files, policy=policy, files_truncated=True
    )
    assert partial.change_contracts[0].status == "unknown"
    assert partial.change_contracts[0].requirements[0].status == "unknown"
    complete = audit_tree(["supabase/migrations/001.sql"], files, policy=policy)
    assert complete.change_contracts[0].status == "missing"
    removed = audit_tree(
        [], [ChangedFile("supabase/migrations/001.sql", status="removed")], policy=policy
    )
    assert removed.change_contracts == ()


def test_change_contracts_invalid_rules_fail_as_a_whole():
    rules = [
        {"id": "x", "when": [], "require_all": ["docs/**"]},
        {"id": "x", "when": ["src/**"]},
        {"id": "x", "when": ["src/**"], "require_all": ["../secret"]},
        {"id": "x", "when": ["src/**"], "require_all": ["docs/**"], "reason": "bad | text"},
        {"id": "x", "when": ["src/**"], "require_all": ["docs/**"], "extra": True},
    ]
    for rule in rules:
        policy = parse_policy(json.dumps({"version": 1, "change_contracts": [rule]}))
        assert policy.warning.startswith("Invalid .qnode.json:")
        assert policy.change_contracts == ()
    duplicate = parse_policy(
        json.dumps(
            {
                "version": 1,
                "change_contracts": [
                    {"id": "x", "when": ["src/**"], "require_all": ["tests/**"]},
                    {"id": "x", "when": ["docs/**"], "require_any": ["README.md"]},
                ],
            }
        )
    )
    assert duplicate.warning
