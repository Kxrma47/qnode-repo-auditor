# Public API reference

The public scanner serves JSON over HTTPS. No sign-in or GitHub App installation is required
for a **public** repository. Requests are subject to GitHub API rate limits; QNode caches
completed scans in process for five minutes. It does not store scan reports.

## `GET /api/audit` and `POST /api/audit`

Pass parameters as a query string for `GET` or a JSON object for `POST`:

| Field | Required | Meaning |
| --- | --- | --- |
| `repository` | Yes | GitHub `owner/name`, public repositories only. |
| `ref` | No | Branch, tag, or commit to scan; defaults to the repository's default branch. |
| `pull` | No | Positive pull-request number; scans the PR head and changed-file metadata. |

`ref` and `pull` cannot be combined. For example:

```bash
curl 'https://qnode-repo-auditor.onrender.com/api/audit?repository=Kxrma47/qnode-repo-auditor'
curl -X POST -H 'Content-Type: application/json' \
  -d '{"repository":"Kxrma47/qnode-repo-auditor","pull":"5"}' \
  'https://qnode-repo-auditor.onrender.com/api/audit'
```

A successful response contains `repository` (public GitHub metadata), `ref` (resolved scan
reference), `scanned_paths` (number of paths inspected), `cached` (whether the result came
from the short-lived cache), and `audit`. Pull-request scans also contain `pull_request`
(number, title, URL, state, head/base refs and SHAs, and change counts).
Pull-request scans also contain `ci_evidence`: observed check-run names and states for the
head commit, configured `.qnode.json` job-name matches, and `complete` for the bounded
100-result latest-check listing. `available: false` means QNode could not read checks; `not_observed`
means a configured label was not returned, not that a test failed or did not run.
Legacy commit status contexts are not included.
They also contain `review_handoff`: observed `facts`, unanswered `questions`, a bounded
lane evidence matrix, `total_lanes`, and copy-ready `markdown`. Its questions are prompts
for humans, not assertions that tests, approvals, or branch rules are satisfied.

`audit` contains `score` (0–100), `grade` (A–F), `conclusion` (`success` or advisory
`neutral`), `passed`, `total`, `checks`, `recommendations`, `risks`, `review_map`,
`companion_suggestions`, and `markdown`. It also contains `tree_truncated`,
`change_contracts`, `files_truncated`, `ignored_files`, `policy_warning`, and `review_delta` (an object only
when a complete comparison since a submitted human review is available, otherwise `null`).
`review_delta.changed_lanes` lists path counts per review lane. Each triggered contract includes
`status`, `trigger_paths`, `trigger_count`, `lanes`, declared `owners`, and per-pattern
`requirements` with `present`, `missing`, or `unknown` status.
Each check includes `key`, `category`, `label`, `passed`, `weight`, `evidence`, and
`recommendation`. Scores and path-derived suggestions are review aids, not proof of code
quality, test coverage, or security. See [policy options](policy.md) for `.qnode.json`.

Validation and GitHub upstream errors return JSON with an `error` string. If public scanning
is disabled, Flask returns a standard 404 page instead.

| Status | Meaning |
| --- | --- |
| `400` | Invalid repository, ref, pull number, or combined `ref` and `pull`. |
| `404` | Repository or ref not found or not public; public scanning disabled. |
| `429` | GitHub API rate limit reached. |
| `502` | GitHub request failed or GitHub was temporarily unreachable. |

## Other endpoints

- `GET /api/attention?repository=OWNER/REPO`: five recently updated open PRs in a public
  repository, ordered by observed check failures and changes since the latest submitted
  human review. This is repository-wide, not a personal inbox or merge decision. Review
  and check-listing failures are marked unavailable or incomplete. Results are cached in
  process for up to one minute.
- `GET /api/compare?repository=OWNER/REPO&base=REF&head=REF`: two path-based readiness
  scores, their difference, and changed safeguard outcomes. Reads each ref separately;
  a truncated tree returns `422`. Results use the five-minute in-process cache. It does
  not compare runtime behavior or test results.
- `GET /api/review-followup?repository=OWNER/REPO&pull=NUMBER`: on-demand, read-only
  review-thread metadata for a public PR. Returns up to 50 unresolved thread links and
  observed resolved/unresolved counts from at most 200 threads. `complete: false` means
  counts can be incomplete. GitHub's `isOutdated` flag does not imply resolution. No
  comment text is fetched. Uses a configured server-side GitHub API token or a short-lived
  token from QNode's existing App installation; GitHub may restrict that installation's
  access to unrelated public PRs. Results are cached in process for one minute. Missing
  authentication returns `503`.
- `POST /api/signal-feedback`: optional same-origin feedback for a path-level signal,
  with JSON such as `{"signal":"workflow-change","useful":true}` and header
  `X-QNode-Feedback: 1`. Requires the scanner's random browser cookie and configured
  visitor store. One current vote per browser and signal category is kept; changing a
  vote replaces it. Repositories, paths, and report content are not stored. Do Not Track
  requests are rejected; the private owner page shows category totals only.
- `POST /api/event`: optional same-origin aggregate measurement for one allowlisted browser
  action: `share_report`, `copy_markdown`, `copy_handoff`, `download_json`, `star`, or
  `use_action`. Requires the scanner's random browser cookie, `X-QNode-Event: 1`, and the
  configured visitor store. The database keeps daily event totals only; it does not associate
  an event with a browser hash, repository, URL, report, IP address, or user agent. Do Not Track
  requests are rejected. Counts represent button actions, not unique users or confirmed stars.

- `POST /api/policy-preview`: send JSON with `policy` (the `.qnode.json` object),
  `changed_paths` (up to 1,000 repository-relative paths), and optional
  `files_truncated` (boolean). Returns triggered `change_contracts` without a GitHub request.
  Invalid policy or paths return `400`; bodies over 64 KiB return `413`. For example:

  ```bash
  curl -X POST -H 'Content-Type: application/json' \
    -d '{"policy":{"version":1,"change_contracts":[{"id":"schema","when":["openapi/**"],"require_any":["generated/**"]}]},"changed_paths":["openapi/api.yaml"]}' \
    'https://qnode-repo-auditor.onrender.com/api/policy-preview'
  ```

- `GET /api/rules`: `rules` describes the twelve weighted checks and `total_weight` is 100.
- `GET /health`: `status`, `service`, `version`, and booleans for configured public audit,
  webhook, owner metrics, and visitor metrics. It does not reveal credentials.
- `POST /webhook`: GitHub App delivery endpoint; requires a valid `X-Hub-Signature-256`.
  This is not a public scan endpoint. See [App registration](app-registration.md).
