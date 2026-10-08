<div align="center">

<img width="116" src="qnode_auditor/static/qnode-app-icon.svg" alt="QNode Repository Auditor app icon">

# QNode Repository Auditor

**Paste a PR URL. See what deserves review.**

[Try the scanner](https://qnode-repo-auditor.onrender.com) · [Run the instant demo](https://qnode-repo-auditor.onrender.com/?demo=1#scanner) · [Add the Action](#github-action) · [Suggest a signal](https://github.com/Kxrma47/qnode-repo-auditor/discussions/6)

[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14715/badge)](https://www.bestpractices.dev/projects/14715)

</div>

![QNode maps a pull request into review lanes and ownership handoffs](qnode_auditor/static/qnode-social-preview.png)

QNode maps risky files, missing tests, ownership gaps, and forgotten companion changes
without reading application source contents. Try it in the browser without signing in, or
run the local Action inside a pull-request workflow.

## GitHub Action

The Action analyzes the already checked-out Git tree locally and writes an advisory risk brief
to the workflow summary. It reads tracked paths plus optional `CODEOWNERS` and `.qnode.json`
files; it does not upload source contents, require a token, post comments, or block a merge.

```yaml
name: QNode review brief

on:
  pull_request:

permissions:
  contents: read

jobs:
  qnode:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: Kxrma47/qnode-repo-auditor@v1
        with:
          base: ${{ github.event.pull_request.base.sha }}
          head: ${{ github.event.pull_request.head.sha }}
```

Outputs are `score`, `grade`, and `risk-count`. QNode stays advisory even when it reports a
low score or a risk signal. See the [45-second walkthrough](docs/demo.md) and
[pilot guide](docs/pilot.md).

Paste a public `owner/repo` name or GitHub pull-request URL into the [scanner](https://qnode-repo-auditor.onrender.com). No installation or sign-in is needed to try it. QNode answers two practical questions:

1. **What engineering safeguards is this repository missing?**
2. **What deserves extra attention in this pull request?**

For teams with repeatable cross-file expectations, QNode can now answer a third question:
**which companion changes did this repository explicitly require, and which appeared in the PR?**
Try the [interactive change-contract preview](https://qnode-repo-auditor.onrender.com/#policy-simulator)
or see the [worked example](docs/examples/change-contract-demo.md).

The scanner also offers an on-demand, repository-wide queue of five recently updated open PRs,
observed GitHub check states for a PR, Review Map path filters, and a two-ref before/after
score chart. The queue is not a personal inbox. A configured CI job is not necessarily required,
and a missing check is not proof that its tests did not run.

For a PR, **Review Handoff** combines the observed file and check metadata with a lane-by-lane
owner, test-path, and mapped-check view. It generates an editable Markdown checklist of the
questions a contributor still needs to answer, such as why the change is needed, what behavior
was tested, and who should review unowned paths. The checklist is never posted automatically;
it does not invent test results, approval, or merge readiness.

The on-demand **Review Follow-up** view lists unresolved GitHub review threads and links to
them, including threads GitHub marks outdated after later edits. It reads thread status and
file paths, not comment text. An outdated thread is not necessarily addressed; QNode never
replies to or resolves one. This view uses a configured GitHub API token or a short-lived
token from QNode's existing App installation; it reports unavailable if GitHub does not
permit that installation to read a requested public PR.
Visitors can also mark a path-level signal useful or not useful. The private owner dashboard
shows one current vote per browser and signal category, not a public popularity score.

The public scanner evaluates a public GitHub repository **or pull-request URL** and returns path evidence plus prioritized improvements. Reports have shareable URLs and can be copied as Markdown or exported as JSON. No App installation is needed. The hosted GitHub App is currently private and only provides automatic advisory Checks on the owner's installed repositories. QNode reads file paths and metadata, not application source contents, and never blocks a merge.

Have a real review case QNode missed? [Tell us what signal you need](https://github.com/Kxrma47/qnode-repo-auditor/discussions/6). Include a public example and expected result if you can; [Issues](https://github.com/Kxrma47/qnode-repo-auditor/issues) are best for reproducible bugs.

Project policies: [contributing](CONTRIBUTING.md) · [governance](GOVERNANCE.md) ·
[code of conduct](CODE_OF_CONDUCT.md) · [security](SECURITY.md) ·
[architecture](docs/architecture.md) · [security assurance](docs/security-assurance.md) ·
[roadmap](docs/roadmap.md).

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
The website also plots counts by review lane so reviewers can see which areas changed again.

Repositories can opt into [change contracts](docs/policy.md): a migration, schema, or other
path can require specific changed companion paths or one of several alternatives. The visual
Review Evidence Map links the triggering paths to present/missing/unknown companions and
declared CODEOWNERS. It never treats filename matching as proof of test coverage or actual
runtime dependency. Incomplete PR file lists produce **unknown**, not false missing results.

Signals appear in the GitHub Check summary and as file annotations. The check remains advisory and offers a **Re-run audit** action after changes are pushed.

### Review map

Every pull-request report also creates a privacy-first review map. Changed files are grouped into logical lanes such as `src/`, `.github/`, or an individual `packages/web/` monorepo package. Lanes are ordered by attention level and churn, and each one shows its file count, line changes, representative paths, relevant risk signals, matching CODEOWNERS, and any ownership gaps. GitHub's last-matching-rule behavior is preserved, including team, user, and email owners. This helps teams delegate a mixed pull request without pretending that one approval covers every area.

Each lane now includes a focused, path-derived review brief: questions about workflow permissions, migrations, dependencies, credential-like files, access control, test evidence, or ownership as applicable. A test-path match counter shows how many changed source files have a conventionally matching test file changed in the PR; it is **not** a coverage result. Tests changed in another monorepo package do not mask a gap in this package. Briefs appear in the website, JSON, Markdown, and GitHub Check without reading source contents or adding permissions.

For monorepos, lanes also show candidate existing test files and any CI jobs declared in the repository's optional [`.qnode.json` policy](docs/policy.md). The policy can suppress noisy heuristic paths and mark critical paths for deeper review. QNode still flags credential-like paths even when ignored. Configured jobs are suggestions, not jobs QNode has executed or verified.

Use the Review Map filters to show source paths, hide likely generated paths, or show only
paths changed since the latest submitted human review. Filtering changes the on-screen view,
not the audit, score, or JSON export. If the review comparison is unavailable, QNode says so.
For a PR, QNode separately shows the check runs GitHub reports for its head commit. A mapped
job name is highlighted, but QNode does not infer required branch checks or claim a skipped or
unobserved job ran. GitHub's latest-check listing is limited to 100 results and marked incomplete
when more exist.
This view covers GitHub check runs, not legacy commit status contexts.

The public scanner accepts `OWNER/REPOSITORY#NUMBER` or a complete GitHub pull-request URL, making the same metadata-and-policy review available before installing the App. You can also preview a proposed `.qnode.json` rule against sample paths without a GitHub call.

The on-demand before/after chart compares safeguard scores and changed check outcomes for two
public Git refs. It reads each ref's paths and policy metadata separately and refuses truncated
trees. It is not a code-behavior or test-execution comparison.

### Share and export

- Every completed scan updates the browser URL, so the report can be reopened or shared.
- **Copy Markdown** produces a review-ready engineering summary.
- **Copy editable handoff** copies observed evidence and unanswered contributor questions for a PR.
- **Download JSON** exports the complete evidence, recommendations, and PR signals for automation.

## Privacy model

QNode deliberately analyzes **paths, GitHub metadata, and the repository's CODEOWNERS policy only**.

- It reads CODEOWNERS solely to map changed paths to reviewer handles.
- It reads `.qnode.json` only if the repository opts in, to apply path rules and job labels.
- It does not download or parse application source-file contents; all other analysis uses paths and line counts only.
- It does not persist webhook payloads, installation tokens, repository paths, or reports.
- The owner-only metrics page reads GitHub's current App installation count. Optional website counting stores a SHA-256 hash of a random browser token, aggregate daily page-view and scan-request totals, allowlisted aggregate report/share/Action button counts, and—if a visitor votes—one current useful/not-useful response per signal category and browser. Button counts are not associated with browser hashes. It stores no IP addresses, user agents, repository URLs, comment text, or scan results. If PostgreSQL is configured, those limited metrics and votes leave Render for that provider; no browser-side third-party tracker is used. Do Not Track browsers are excluded. Clearing cookies or switching devices changes the approximate browser count.
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

The hosted App is private. This section documents its behavior and the setup for someone
running their own App; visitors can use the public scanner without installing anything.

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
- `VISITOR_METRICS_URL` (optional; durable PostgreSQL URL for private usage counts)
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

For a local deployment, set `VISITOR_METRICS_DB` to an absolute SQLite file path in a writable directory (for example `/tmp/qnode-visitors.sqlite3` for **development only**). Once enabled, the scanner sets a one-year, same-site, HTTP-only random browser cookie. Its own JavaScript posts one visit after a page load. The database stores token hashes and daily counts, not raw cookies or user identity. Optional signal feedback stores that hash with a signal category, current useful/not-useful vote, and update time; a changed vote replaces the old one. Allowlisted report sharing, export, star-link, and Action-link events are stored only as aggregate daily totals without browser hashes. The owner page shows approximate unique browsers since tracking began, browsers seen in the last 30 days, page views, successful public repository/PR scans (including cached requests), conversion-button totals, and category-level feedback. Scan and button counts are requests, not people or confirmed conversions, and do not store repository names. Do Not Track requests are excluded. It cannot recover activity before activation. Erase the database to delete the history; browser IDs are retained until then and a returning browser with an expired or cleared cookie can be counted again.

**Free production storage:** Render Free erases local SQLite on sleep, restart, and deploy. Create a dedicated free PostgreSQL database (for example, a [Neon Free project](https://neon.com/pricing)) and put its connection string in Render's secret `VISITOR_METRICS_URL`. Keep `VISITOR_METRICS_DB` unset. QNode forces server-certificate verification and sends only random-browser-token SHA-256 hashes, timestamps, aggregate daily counts, and optional category-level feedback to the database. It does **not** send IP addresses, user agents, repository names, source code, comment text, or scan results to Neon. No third-party browser script is added. The owner dashboard remains protected by `OWNER_METRICS_TOKEN`. The count starts at zero when the database is connected; previous visits cannot be reconstructed. Free database limits and availability are controlled by the provider, so check its current terms before relying on it. Do not commit or share either secret.

## Limits

- Path presence cannot prove that tests, policies, or workflows are correct.
- GitHub may truncate very large recursive trees; QNode marks such reports as potentially incomplete.
- QNode scans up to 1,000 changed PR files and marks larger or partial file lists as incomplete.
- The public scanner refuses non-public repositories even if its configured read token can access them.
- A changed source file without a changed test is a review prompt, not proof that coverage is missing.
- Test-path matches use filename conventions and do not prove that tests cover changed behavior; custom integration suites may not match.
- Suggested test and lockfile paths are deterministic conventions; maintainers should adapt them to project-specific structure.
- CODEOWNERS routing reports declared handles and coverage, but does not verify team membership or review availability.
- A declared change contract verifies matching changed paths only; it does not inspect source content, verify tests, or confirm a reviewer approved the change.
- Public API calls are subject to GitHub rate limits.
- Review deltas require a submitted human review and complete GitHub comparisons; otherwise they are omitted.
- The attention queue samples only five recently updated open PRs and cannot infer who is assigned to review them.
- Observed check runs do not reveal a repository's required-check rules; unobserved and skipped checks are not reported as passed.

## Support and security

Open a GitHub issue for reproducible bugs or feature requests. For operational help, see [SUPPORT.md](SUPPORT.md). Report vulnerabilities privately according to [SECURITY.md](SECURITY.md).

## License

MIT © 2026 Mahidul Haque
