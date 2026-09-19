# Security policy

Please report vulnerabilities privately through GitHub's **Report a vulnerability** feature. Do not include secrets, private keys, webhook payloads, or installation tokens in a public issue.

QNode validates every webhook using `X-Hub-Signature-256`, uses short-lived installation tokens, requests only the permissions documented in the README, never reads file contents, and does not persist repository data or tokens.

The public scanner accepts only validated `owner/repository` identifiers and Git refs, and sends requests exclusively to the configured GitHub API origin. Results are cached only in process for a short period and disappear on restart.

Supported security fixes are released from the current default branch. Please include a clear impact description and safe reproduction, but do not include real credentials or private repository information.

## Response process

The maintainer reviews private reports, asks for a minimal safe reproduction when needed,
assesses affected versions and impact, and tracks remediation privately until disclosure
is safe. A confirmed issue is fixed and tested before release; affected users are given a
clear description of impact and the fix or mitigation. The reporter is credited in the
advisory or release note unless they request anonymity. There is no guaranteed response
or fix time, and an unconfirmed report is not described as a vulnerability.

## What users can and cannot expect

QNode verifies GitHub webhook signatures before handling events, validates public scanner
identifiers and refs, uses short lived installation tokens, and restricts the public
scanner to public repositories. Secrets are configured outside source control; production
rejects weak configured webhook and owner tokens and invalid or undersized App keys.

QNode's scores and path based review signals are **not** vulnerability detection, source
code review, or a guarantee of secure software. A missing path or unmatched test name can
be a false positive; a present path does not establish that a safeguard works. GitHub API
limits or truncated responses can make an audit incomplete. Installed App Checks are
advisory and do not prevent a merge. Users remain responsible for reviewing code,
permissions, dependencies, and deployment settings.
