# Architecture and trust boundaries

QNode is a Flask service with two entry points: a public repository or pull request
scanner, and a GitHub App webhook. The same deterministic audit engine powers both.

1. `qnode_auditor/app.py` validates HTTP input, controls the public endpoints, and verifies
   webhook signatures before processing GitHub events.
2. `qnode_auditor/github.py` calls the configured GitHub API and retrieves repository tree
   paths, pull request file metadata, and the few policy files QNode needs.
3. `qnode_auditor/policy.py` validates the repository's optional `.qnode.json` rules.
4. `qnode_auditor/audit.py` scores repository safeguards and produces path based review
   signals, companion suggestions, ownership lanes, and report data.
5. The public web page renders that data in the browser. Installed App requests also
   publish an advisory GitHub Check on the pull request head commit.

The public scanner requires a public GitHub repository; a configured API token is used
only to raise the GitHub API rate limit. The installed App obtains short lived installation
tokens for the active webhook request. GitHub App permissions and events are listed in the
[README](../README.md#github-app-flow).

## Data flow and storage

QNode reads repository paths, pull request metadata, CODEOWNERS, and optionally
`.qnode.json`. It does not fetch application source contents for analysis. Public results
are cached in process for up to five minutes and disappear on restart. The optional owner
metrics page obtains the current installation count from GitHub; optional visitor counting
uses a separately configured SQLite file and does not run on the published free deployment.
The [README privacy model](../README.md#privacy-model) describes retained fields and
limitations. Reports, installation tokens, and webhook payloads are not persisted.

## Failure behavior

Invalid public inputs return a client error. GitHub API failures and incomplete GitHub
trees are surfaced rather than silently treated as complete audits. A missing optional
policy uses default analysis; a malformed policy is reported as a warning. Review deltas
are omitted when their baseline cannot be verified. QNode Checks are advisory and do not
block merging. See the [API reference](api.md) for response fields and errors.
