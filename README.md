<div align="center">

<img width="116" src="qnode_auditor/static/qnode-app-icon.svg" alt="QNode Repository Auditor app icon">

# QNode Repository Auditor

**Know what to fix in a repository—and what to review carefully in a pull request.**

[Try the scanner](https://qnode-repo-auditor.onrender.com) · [Install the GitHub App](https://github.com/apps/qnode-repository-auditor) · [Suggest a feature](https://github.com/Kxrma47/qnode-repo-auditor/discussions/6) · [Report a bug](https://github.com/Kxrma47/qnode-repo-auditor/issues)

[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14715/badge)](https://www.bestpractices.dev/projects/14715)

</div>

Paste a public `owner/repo` name or GitHub pull-request URL into the [scanner](https://qnode-repo-auditor.onrender.com). No installation or sign-in is needed to try it. QNode answers two practical questions:

1. **What engineering safeguards is this repository missing?**
2. **What deserves extra attention in this pull request?**

The public scanner evaluates a public GitHub repository **or pull-request URL** and returns path evidence plus prioritized improvements. Reports have shareable URLs and can be copied as Markdown or exported as JSON. Install the GitHub App if you want advisory Checks to appear automatically on pull requests. QNode reads file paths and metadata, not application source contents, and never blocks a merge.

Have a real review case QNode missed? [Tell us what signal you need](https://github.com/Kxrma47/qnode-repo-auditor/discussions/6). Include a public example and expected result if you can; [Issues](https://github.com/Kxrma47/qnode-repo-auditor/issues) are best for reproducible bugs.

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

After a human review, QNode can also show paths changed since that review plus new and resolved QNode signals. The delta is omitted if GitHub cannot provide a complete comparison; it is not a claim that code defects were fixed.

Signals appear in the GitHub Check summary and as file annotations. The check remains advisory and offers a **Re-run audit** action after changes are pushed.

### Review map

Every pull-request report also creates a privacy-first review map. Changed files are grouped into logical lanes such as `src/`, `.github/`, or an individual `packages/web/` monorepo package. Lanes are ordered by attention level and churn, and each one shows its file count, line changes, representative paths, relevant risk signals, matching CODEOWNERS, and any ownership gaps. GitHub's last-matching-rule behavior is preserved, including team, user, and email owners. This helps teams delegate a mixed pull request without pretending that one approval covers every area.

Each lane now includes a focused, path-derived review brief: questions about workflow permissions, migrations, dependencies, credential-like files, access control, test evidence, or ownership as applicable. A test-path match counter shows how many changed source files have a conventionally matching test file changed in the PR; it is **not** a coverage result. Tests changed in another monorepo package do not mask a gap in this package. Briefs appear in the website, JSON, Markdown, and GitHub Check without reading source contents or adding permissions.

For monorepos, lanes also show candidate existing test files and any CI jobs declared in the repository's optional [`.qnode.json` policy](docs/policy.md). The policy can suppress noisy heuristic paths and mark critical paths for deeper review. QNode still flags credential-like paths even when ignored. Configured jobs are suggestions, not jobs QNode has executed or verified.

The public scanner accepts `OWNER/REPOSITORY#NUMBER` or a complete GitHub pull-request URL, making the same metadata-and-policy review available before installing the App.

### Share and export

- Every completed scan updates the browser URL, so the report can be reopened or shared.
- **Copy Markdown** produces a review-ready engineering summary.
- **Download JSON** exports the complete evidence, recommendations, and PR signals for automation.

## Privacy model

QNode deliberately analyzes **paths, GitHub metadata, and the repository's CODEOWNERS policy only**.

- It reads CODEOWNERS solely to map changed paths to reviewer handles.
- It reads `.qnode.json` only if the repository opts in, to apply path rules and job labels.
- It does not download or parse application source-file contents; all other analysis uses paths and line counts only.
- It does not persist webhook payloads, installation tokens, repository paths, or reports.
- The owner-only metrics page reads GitHub's current App installation count. Optional website counting stores only a SHA-256 hash of a random browser token and aggregate daily page-view totals in local SQLite. It stores no IP addresses, user agents, repository URLs, or scan results. Do Not Track browsers are excluded. Clearing cookies or switching devices changes the approximate browser count.
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

See the [API reference](docs/api.md) for request parameters, response fields, and error codes.

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
- `OWNER_METRICS_TOKEN` (optional; enables the private owner page)
- `VISITOR_METRICS_DB` (optional; absolute path to a persistent SQLite database file)

Production identifiers:

- `GITHUB_APP_ID`
- `GITHUB_INSTALLATION_ID` (fallback for repository-level webhook setups)

Never place a private key or webhook secret in source control, logs, issues, or browser-visible configuration.
Production rejects configured webhook and owner-dashboard secrets shorter than 32 UTF-8 bytes,
and rejects GitHub App RSA private keys below 2048 bits. Generate each secret independently
with a cryptographically secure generator (for example, `python -c 'import secrets; print(secrets.token_hex(32))'`),
and set the same webhook secret in the GitHub App and the hosting environment. A long but
predictable string is not a secure substitute. Check existing production values before deploying
this validation; otherwise the service will fail startup rather than accept a weak secret.
When a GitHub App private key is configured, startup also parses it and verifies its size,
so a malformed key cannot leave an apparently healthy service with failing PR webhooks.

### Private owner metrics

Set `OWNER_METRICS_TOKEN` to a unique, long random value in the hosting environment. Then open `/owner/metrics` over HTTPS and sign in using `Kxrma47` (or `OWNER_METRICS_USERNAME`) and that token. The route returns 404 while the token is unset, and is excluded from search indexing and caching when enabled. Do not share the token or put it in a URL.

The installation number is **current GitHub App installations (accounts/organizations)**, fetched directly from GitHub. It is not the number of people, visits, or successful scans.

For a local deployment, set `VISITOR_METRICS_DB` to an absolute SQLite file path in a writable directory (for example `/tmp/qnode-visitors.sqlite3` for **development only**). Once enabled, the scanner sets a one-year, same-site, HTTP-only random browser cookie. Its own JavaScript posts one visit after a page load; no external analytics service is used. The database stores token hashes and daily counts, not raw cookies or user identity. The owner page shows approximate unique browsers since tracking began, browsers seen in the last 30 days, and page views. It does not count API-only requests, and it cannot recover visits before activation. Erase the database to delete the history; browser IDs are retained until then and a returning browser with an expired or cleared cookie can be counted again.

**Production:** do not set `VISITOR_METRICS_DB` on Render's free web service. Its local filesystem is erased on sleep, restart, or deploy, so an apparent lifetime count would reset unpredictably. Use a persistent mounted disk (a paid Render service) if you want SQLite for the live site. The published free deployment leaves website counting disabled until such storage is available. Do not commit the database file or put the owner token in a URL.

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
- Review deltas require a submitted human review and complete GitHub comparisons; otherwise they are omitted.

## Support and security

Open a GitHub issue for reproducible bugs or feature requests. For operational help, see [SUPPORT.md](SUPPORT.md). Report vulnerabilities privately according to [SECURITY.md](SECURITY.md).

## License

MIT © 2026 Mahidul Haque
