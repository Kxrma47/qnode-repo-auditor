# Contributing

Thank you for improving QNode. Open an issue before a substantial behavioral or permission change.

## Principles

- Keep analysis deterministic, explainable, path-based, and advisory.
- Every signal must include evidence and a concrete remediation.
- Avoid permissions beyond Contents read, Pull requests read, and Checks write unless a feature has a documented need.
- Never persist webhook payloads, installation tokens, private repository data, or source contents.
- Treat path-based findings as review prompts, not proof of a vulnerability or defect.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=qnode_auditor --cov-report=term-missing
```

Add tests for every rule, API response, and webhook behavior. Update the README and changelog when user-visible behavior changes.
