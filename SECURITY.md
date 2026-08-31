# Security policy

Please report vulnerabilities privately through GitHub's **Report a vulnerability** feature. Do not include secrets, private keys, webhook payloads, or installation tokens in a public issue.

QNode validates every webhook using `X-Hub-Signature-256`, uses short-lived installation tokens, requests only the permissions documented in the README, never reads file contents, and does not persist repository data or tokens.

The public scanner accepts only validated `owner/repository` identifiers and Git refs, and sends requests exclusively to the configured GitHub API origin. Results are cached only in process for a short period and disappear on restart.

Supported security fixes are released from the current default branch. Please include a clear impact description and safe reproduction, but do not include real credentials or private repository information.
