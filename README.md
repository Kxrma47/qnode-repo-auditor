<div align="center">

<img width="116" src="qnode_auditor/static/qnode-app-icon.svg" alt="QNode Repository Auditor app icon">

# QNode Repository Auditor

**Actionable repository readiness and pull-request risk intelligence for GitHub.**

[Live scanner](https://qnode-repo-auditor.onrender.com) · [Health](https://qnode-repo-auditor.onrender.com/health) · [Report a bug](https://github.com/Kxrma47/qnode-repo-auditor/issues)

</div>

QNode answers two practical questions:

1. **What engineering safeguards is this repository missing?**
2. **What deserves extra attention in this pull request?**

The public scanner evaluates any public GitHub repository **or pull-request URL** and returns exact path evidence plus prioritized improvements. Reports have permanent share links and can be copied as Markdown or exported as JSON. When installed as a GitHub App, QNode publishes the same readiness map on pull requests and adds focused risk annotations.

## What it reports

### Repository readiness

Twelve weighted checks produce a transparent 0–100 score:

| Area | Signals |
|---|---|
| Quality | Automated tests, continuous integration |
| Security | Security policy, automated dependency updates |
| Supply chain | Dependency manifest, reproducible lock/build file |
| Foundation | Project documentation, license |
| Community | Contribution guide, issue or pull-request templates |
| Governance | Code ownership |
| Operations | Change history |

Every failed check includes a recommendation and its potential score impact. The score is a prioritization aid—not a security certification.

### Pull-request intelligence

QNode inspects changed-file metadata and flags:

- source changes without corresponding test changes;
- dependency manifests changed without a lockfile update;
- CI workflow changes requiring permission and secret review;
- credential-like files such as `.env`, `.pem`, `.key`, or private keys;
- database migrations requiring rollout and rollback planning;
- unusually large review surfaces.

It also names likely companion files for each changed source file. Suggestions follow the
repository's ecosystem and layout—for example `tests/users/test_service.py`,
`src/cart.test.ts`, or `handler_test.go`—and distinguish between adding a missing file and
updating a test that already exists. Manifest changes receive a workspace-aware lockfile
suggestion when the corresponding lockfile was not changed.

Signals appear in the GitHub Check summary and as file annotations. The check remains advisory and offers a **Re-run audit** action after changes are pushed.

### Review map

Every pull-request report also creates a privacy-first review map. Changed files are grouped into logical lanes such as `src/`, `.github/`, or an individual `packages/web/` monorepo package. Lanes are ordered by attention level and churn, and each one shows its file count, line changes, representative paths, relevant risk signals, matching CODEOWNERS, and any ownership gaps. GitHub's last-matching-rule behavior is preserved, including team, user, and email owners. This helps teams delegate a mixed pull request without pretending that one approval covers every area.

Each lane now includes a focused, path-derived review brief: questions about workflow permissions, migrations, dependencies, credential-like files, access control, test evidence, or ownership as applicable. A test-path match counter shows how many changed source files have a conventionally matching test file changed in the PR; it is **not** a coverage result. Tests changed in another monorepo package do not mask a gap in this package. Briefs appear in the website, JSON, Markdown, and GitHub Check without reading source contents or adding permissions.

The public scanner accepts `OWNER/REPOSITORY#NUMBER` or a complete GitHub pull-request URL, making the same metadata-and-policy review available before installing the App.

### Share and export

- Every completed scan updates the browser URL, so the report can be reopened or shared.
- **Copy Markdown** produces a review-ready engineering summary.
- **Download JSON** exports the complete evidence, recommendations, and PR signals for automation.

## Privacy model

QNode deliberately analyzes **paths, GitHub metadata, and the repository's CODEOWNERS policy only**.

- It reads CODEOWNERS solely to map changed paths to reviewer handles.
- It does not download or parse application source-file contents; all other analysis uses paths and line counts only.
- It does not store webhook payloads, installation tokens, repository paths, or reports.
- Public scans are cached in process for five minutes to reduce GitHub API traffic; the cache disappears on restart.
- Installation tokens are created only for the active webhook request.
- A score below the threshold is reported as `neutral`, never as a blocking failure.

## API

Audit a public repository:

```bash
curl 'https://qnode-repo-auditor.onrender.com/api/audit?repository=Kxrma47/qnode-repo-auditor'
```

Audit a specific branch, tag, or commit:

```bash
curl 'https://qnode-repo-auditor.onrender.com/api/audit?repository=OWNER/REPO&ref=REF'
```

Audit a public pull request:

```bash
curl 'https://qnode-repo-auditor.onrender.com/api/audit?repository=OWNER/REPO&pull=42'
```

Inspect the scoring contract:

```bash
curl 'https://qnode-repo-auditor.onrender.com/api/rules'
```

Operational readiness is available at `GET /health`.

## GitHub App flow

```text
pull_request / requested_action webhook
                 │
                 ▼
       HMAC-SHA256 verification
                 │
                 ▼
       short-lived installation token
                 │
          ┌──────┴────────┐
          ▼               ▼
 repository tree     changed-file metadata
          │               │
          └──────┬────────┘
                 ▼
       CODEOWNERS policy (if present)
                 ▼
       deterministic audit engine
                 │
                 ▼
     GitHub Check + annotations + re-run
```

Required repository permissions:

- **Metadata:** read
- **Contents:** read
- **Checks:** read and write
- **Pull requests:** read

Subscribed events:

- **Pull request**
- **Check run** (for the requested re-run action)

See [GitHub App registration](docs/app-registration.md) for the complete setup.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
ruff check .
pytest -q
python -m qnode_auditor.app
```

Open `http://127.0.0.1:8000` for the scanner. Public scanning works without credentials at GitHub's anonymous API rate limit. Set `GITHUB_PUBLIC_TOKEN` to a fine-grained read-only token when a higher rate limit is needed.

## Deploy

The included Dockerfile runs as a non-root user. `render.yaml` defines the web service, health check, and non-secret configuration.

Production secrets:

- `GITHUB_PRIVATE_KEY`
- `GITHUB_WEBHOOK_SECRET`

Production identifiers:

- `GITHUB_APP_ID`
- `GITHUB_INSTALLATION_ID` (fallback for repository-level webhook setups)

Never place a private key or webhook secret in source control, logs, issues, or browser-visible configuration.

## Limits

- Path presence cannot prove that tests, policies, or workflows are correct.
- GitHub may truncate very large recursive trees; QNode marks such reports as potentially incomplete.
- QNode scans up to 1,000 changed PR files and marks larger or partial file lists as incomplete.
- The public scanner refuses non-public repositories even if its configured read token can access them.
- A changed source file without a changed test is a review prompt, not proof that coverage is missing.
- Test-path matches use filename conventions and do not prove that tests cover changed behavior; custom integration suites may not match.
- Suggested test and lockfile paths are deterministic conventions; maintainers should adapt them to project-specific structure.
- CODEOWNERS routing reports declared handles and coverage, but does not verify team membership or review availability.
- Public API calls are subject to GitHub rate limits.

## Support and security

Open a GitHub issue for reproducible bugs or feature requests. For operational help, see [SUPPORT.md](SUPPORT.md). Report vulnerabilities privately according to [SECURITY.md](SECURITY.md).

## License

MIT © 2026 Mahidul Haque
