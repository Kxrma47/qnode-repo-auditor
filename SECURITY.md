# Security policy

Please report vulnerabilities privately through GitHub's **Report a vulnerability** feature. Do not include secrets, private keys, webhook payloads, or installation tokens in a public issue.

QNode validates every webhook using `X-Hub-Signature-256`, requests only repository metadata and checks write access, never reads file contents, and does not persist repository data or tokens.
