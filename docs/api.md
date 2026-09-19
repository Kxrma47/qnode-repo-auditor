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

`audit` contains `score` (0–100), `grade` (A–F), `conclusion` (`success` or advisory
`neutral`), `passed`, `total`, `checks`, `recommendations`, `risks`, `review_map`,
`companion_suggestions`, and `markdown`. It also contains `tree_truncated`,
`files_truncated`, `ignored_files`, `policy_warning`, and `review_delta` (an object only
when a complete comparison since a submitted human review is available, otherwise `null`).
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

- `GET /api/rules`: `rules` describes the twelve weighted checks and `total_weight` is 100.
- `GET /health`: `status`, `service`, `version`, and booleans for configured public audit,
  webhook, owner metrics, and visitor metrics. It does not reveal credentials.
- `POST /webhook`: GitHub App delivery endpoint; requires a valid `X-Hub-Signature-256`.
  This is not a public scan endpoint. See [App registration](app-registration.md).
