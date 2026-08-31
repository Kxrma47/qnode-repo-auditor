<div align="center">

# QNode Repository Auditor

**Actionable repository readiness and pull-request risk intelligence for GitHub.**

[Live scanner](https://qnode-repo-auditor.onrender.com) · [Health](https://qnode-repo-auditor.onrender.com/health) · [Report a bug](https://github.com/Kxrma47/qnode-repo-auditor/issues)

</div>

QNode answers two practical questions:

1. **What engineering safeguards is this repository missing?**
2. **What deserves extra attention in this pull request?**

The public scanner evaluates any public GitHub repository and returns exact path evidence plus prioritized improvements. When installed as a GitHub App, QNode publishes the same readiness map on pull requests and adds focused risk annotations.

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

Signals appear in the GitHub Check summary and as file annotations. The check remains advisory and offers a **Re-run audit** action after changes are pushed.

## Privacy model

QNode deliberately analyzes **paths and GitHub metadata only**.

- It does not download or parse source-file contents.
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
          └──────┬────────┘
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
- A changed source file without a changed test is a review prompt, not proof that coverage is missing.
- Public API calls are subject to GitHub rate limits.

## Support and security

Open a GitHub issue for reproducible bugs or feature requests. For operational help, see [SUPPORT.md](SUPPORT.md). Report vulnerabilities privately according to [SECURITY.md](SECURITY.md).

## License

MIT © 2026 Mahidul Haque
