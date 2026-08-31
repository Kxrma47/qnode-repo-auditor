from qnode_auditor.audit import ChangedFile, audit_tree

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
