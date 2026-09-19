from qnode_auditor.audit import ChangedFile, audit_tree, find_codeowners_path

COMPLETE_TREE = [
    "README.md",
    "LICENSE",
    "tests/test_app.py",
    ".github/workflows/test.yml",
    "pyproject.toml",
    "Dockerfile",
    "SECURITY.md",
    ".github/dependabot.yml",
    "CONTRIBUTING.md",
    ".github/CODEOWNERS",
    "CHANGELOG.md",
    ".github/ISSUE_TEMPLATE/bug.yml",
]


def test_complete_repository_scores_full_marks():
    audit = audit_tree(COMPLETE_TREE)
    assert audit.score == 100
    assert audit.grade == "A"
    assert audit.conclusion == "success"
    assert audit.passed_count == 12
    assert next(check for check in audit.checks if check.key == "tests").evidence == (
        "tests/test_app.py"
    )


def test_workflow_named_tests_is_not_a_test_suite():
    audit = audit_tree([".github/workflows/tests.yml"])
    tests = next(check for check in audit.checks if check.key == "tests")
    assert tests.passed is False


def test_sparse_repository_is_advisory_and_actionable():
    audit = audit_tree(["main.py"])
    assert audit.score == 0
    assert audit.grade == "F"
    assert audit.conclusion == "neutral"
    assert audit.missing[0].weight == 14
    assert "Highest-impact improvements" in audit.markdown()
    assert "never blocks" in audit.markdown()


def test_pull_request_risk_signals_are_specific_and_annotated():
    files = [
        ChangedFile("src/service.py", additions=500, deletions=350),
        ChangedFile("pyproject.toml", additions=5),
        ChangedFile(".github/workflows/release.yml", additions=20),
        ChangedFile("secrets/production.pem", additions=20),
        ChangedFile("migrations/002_users.py", additions=40),
    ]
    audit = audit_tree(COMPLETE_TREE, files)
    keys = {risk.key for risk in audit.risks}
    assert keys == {
        "source-without-tests",
        "manifest-without-lock",
        "workflow-change",
        "credential-path",
        "large-change",
        "migration-change",
    }
    assert any(item["annotation_level"] == "warning" for item in audit.annotations())
    assert all(item["start_line"] == 1 for item in audit.annotations())


def test_tests_and_lockfile_suppress_related_risks():
    audit = audit_tree(
        COMPLETE_TREE,
        [
            ChangedFile("src/service.py", additions=12),
            ChangedFile("tests/test_service.py", additions=20),
            ChangedFile("pyproject.toml", additions=2),
            ChangedFile("uv.lock", additions=8, deletions=3),
        ],
    )
    keys = {risk.key for risk in audit.risks}
    assert "source-without-tests" not in keys
    assert "manifest-without-lock" not in keys


def test_removed_credentials_are_not_reported_as_new_exposure():
    audit = audit_tree(
        COMPLETE_TREE,
        [ChangedFile("secrets/old.pem", status="removed", deletions=20)],
    )
    assert "credential-path" not in {risk.key for risk in audit.risks}


def test_json_report_includes_ranked_recommendations_and_truncation():
    report = audit_tree(["README.md"], tree_truncated=True).to_dict()
    assert report["score"] == 12
    assert report["tree_truncated"] is True
    assert report["recommendations"][0]["points"] == 14
    assert report["checks"][0]["evidence"] == "README.md"


def test_review_map_groups_monorepo_areas_and_ranks_attention():
    audit = audit_tree(
        COMPLETE_TREE,
        [
            ChangedFile("packages/web/src/app.ts", additions=40, deletions=5),
            ChangedFile("packages/web/src/app.test.ts", additions=18),
            ChangedFile("services/api/src/auth.py", additions=25),
            ChangedFile("services/api/secrets/signing.key", additions=3),
            ChangedFile("docs/authentication.md", additions=12),
            ChangedFile("README.md", additions=2),
        ],
    )

    lanes = audit.review_lanes
    assert [lane.key for lane in lanes] == ["services/api", "packages/web", "docs", "."]
    assert lanes[0].attention == "high"
    assert lanes[0].signals == ("Possible credential material committed",)
    assert lanes[0].file_count == 2
    assert lanes[0].changes == 28
    assert lanes[-1].label == "Repository root"


def test_review_map_is_available_in_json_and_markdown():
    report = audit_tree(
        COMPLETE_TREE,
        [ChangedFile("src/service.py", additions=20), ChangedFile("docs/api.md", additions=8)],
    ).to_dict()

    assert report["review_map"][0]["key"] == "src"
    assert report["review_map"][0]["attention"] == "medium"
    assert report["review_map"][0]["paths"] == ("src/service.py",)
    assert "### Review map" in report["markdown"]
    assert "Source changed without tests" in report["markdown"]


def test_repository_audit_without_pull_request_has_no_review_map():
    assert audit_tree(COMPLETE_TREE).to_dict()["review_map"] == []


def test_companion_suggestions_are_path_aware_in_monorepos():
    audit = audit_tree(
        COMPLETE_TREE + ["packages/api/tests/users/test_service.py"],
        [
            ChangedFile("packages/api/src/users/service.py", additions=12),
            ChangedFile("packages/web/src/cart.ts", additions=8),
        ],
    )

    suggestions = {item.source_path: item for item in audit.companion_suggestions}
    assert suggestions["packages/api/src/users/service.py"].suggested_path == (
        "packages/api/tests/users/test_service.py"
    )
    assert suggestions["packages/api/src/users/service.py"].action == "update"
    assert suggestions["packages/web/src/cart.ts"].suggested_path == (
        "packages/web/src/cart.test.ts"
    )
    assert suggestions["packages/web/src/cart.ts"].action == "add"


def test_changed_matching_test_suppresses_only_its_companion_suggestion():
    audit = audit_tree(
        COMPLETE_TREE,
        [
            ChangedFile("src/auth.py", additions=5),
            ChangedFile("tests/test_auth.py", additions=9),
            ChangedFile("src/billing.py", additions=7),
        ],
    )
    sources = {item.source_path for item in audit.companion_suggestions}
    assert "src/auth.py" not in sources
    assert "src/billing.py" in sources


def test_lockfile_suggestion_uses_matching_workspace_not_unrelated_package():
    audit = audit_tree(
        COMPLETE_TREE + ["packages/other/package-lock.json"],
        [ChangedFile("packages/web/package.json", additions=2)],
    )
    suggestion = audit.companion_suggestions[0]
    assert suggestion.kind == "lockfile"
    assert suggestion.suggested_path == "packages/web/package-lock.json"
    assert suggestion.action == "add"


def test_codeowners_routes_lanes_and_reports_partial_coverage():
    codeowners = """
* @org/default
/packages/web/ @org/web
/services/api/** @org/api @alice
/services/api/generated/**
"""
    audit = audit_tree(
        COMPLETE_TREE,
        [
            ChangedFile("packages/web/src/app.ts", additions=4),
            ChangedFile("services/api/src/auth.py", additions=5),
            ChangedFile("services/api/generated/client.py", additions=6),
        ],
        codeowners_content=codeowners,
    )
    lanes = {lane.key: lane for lane in audit.review_lanes}
    assert lanes["packages/web"].owners == ("@org/web",)
    assert lanes["packages/web"].unowned_files == 0
    assert lanes["services/api"].owners == ("@org/api", "@alice")
    assert lanes["services/api"].unowned_files == 1
    assert "@org/web" in audit.markdown()


def test_codeowners_location_precedence_matches_github():
    assert find_codeowners_path(["CODEOWNERS", ".github/CODEOWNERS"]) == (".github/CODEOWNERS")


def test_codeowners_single_star_does_not_cross_directories_but_double_star_does():
    audit = audit_tree(
        COMPLETE_TREE,
        [
            ChangedFile("docs/guide.md"),
            ChangedFile("docs/guides/deep.md"),
        ],
        codeowners_content="/docs/* @writers\n",
    )
    lane = audit.review_lanes[0]
    assert lane.owners == ("@writers",)
    assert lane.unowned_files == 1

    recursive = audit_tree(
        COMPLETE_TREE,
        [ChangedFile("docs/guides/deep.md")],
        codeowners_content="/docs/** @docs-team\n",
    )
    assert recursive.review_lanes[0].owners == ("@docs-team",)


def test_codeowners_accepts_email_owners_and_ignores_inline_comments():
    audit = audit_tree(
        COMPLETE_TREE,
        [ChangedFile("security/policy.md")],
        codeowners_content="/security/ security@example.com # ask @inactive\n",
    )
    assert audit.review_lanes[0].owners == ("security@example.com",)


def test_review_brief_does_not_count_unrelated_monorepo_tests():
    audit = audit_tree(
        COMPLETE_TREE,
        [
            ChangedFile("packages/web/src/cart.ts", additions=8),
            ChangedFile("packages/web/src/cart.test.ts", additions=12),
            ChangedFile("services/api/src/auth.py", additions=10),
        ],
    )
    lanes = {lane.key: lane for lane in audit.review_lanes}
    assert (lanes["packages/web"].test_path_matches, lanes["packages/web"].source_files) == (1, 1)
    assert (lanes["services/api"].test_path_matches, lanes["services/api"].source_files) == (0, 1)
    assert lanes["services/api"].attention == "medium"
    assert any("negative cases" in question for question in lanes["services/api"].review_questions)
    assert "0/1" in audit.markdown()
    assert audit.to_dict()["review_map"][0]["review_questions"]


def test_review_brief_reports_partial_test_path_matches():
    audit = audit_tree(
        COMPLETE_TREE,
        [
            ChangedFile("src/auth.py", additions=3),
            ChangedFile("tests/test_auth.py", additions=4),
            ChangedFile("src/billing.py", additions=6),
        ],
    )
    lane = next(lane for lane in audit.review_lanes if lane.key == "src")
    assert (lane.test_path_matches, lane.source_files) == (1, 2)
    assert any("1/2 source files" in question for question in lane.review_questions)


def test_review_brief_follows_workflow_and_migration_paths_without_source_contents():
    audit = audit_tree(
        COMPLETE_TREE,
        [
            ChangedFile(".github/workflows/release.yml", additions=6),
            ChangedFile("migrations/003_users.py", additions=7),
        ],
    )
    lanes = {lane.key: lane for lane in audit.review_lanes}
    assert any("token permissions" in q for q in lanes[".github"].review_questions)
    assert any("rollback" in q for q in lanes["migrations"].review_questions)
    assert lanes[".github"].source_files == 0
    assert lanes[".github"].test_path_matches == 0


def test_review_brief_does_not_treat_removed_source_as_needing_new_tests():
    audit = audit_tree(COMPLETE_TREE, [ChangedFile("src/obsolete.py", status="removed")])
    lane = audit.review_lanes[0]
    assert lane.source_files == 0
    assert lane.test_path_matches == 0
    assert not any("Matching changed test paths" in q for q in lane.review_questions)

    removed_key = audit_tree(COMPLETE_TREE, [ChangedFile("secrets/old.pem", status="removed")])
    assert not any(
        "live secret" in question for question in removed_key.review_lanes[0].review_questions
    )
