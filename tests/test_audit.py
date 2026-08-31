from qnode_auditor.audit import audit_tree


def test_complete_repository_scores_full_marks():
    audit = audit_tree([
        "README.md", "LICENSE", "tests/test_app.py", ".github/workflows/test.yml",
        "pyproject.toml", "Dockerfile", "SECURITY.md",
    ])
    assert audit.score == 100
    assert audit.conclusion == "success"


def test_sparse_repository_is_advisory():
    audit = audit_tree(["main.py"])
    assert audit.score == 0
    assert audit.conclusion == "neutral"
    assert "never blocks" in audit.markdown()
