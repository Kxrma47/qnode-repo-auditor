# Security assurance case

This document explains why QNode's documented security properties are reasonable to
expect from the current implementation. It is an evidence map, not a certification or a
claim that unknown vulnerabilities do not exist. User facing limits are in
[SECURITY.md](../SECURITY.md).

## Assets, threats, and trust boundaries

Assets include the GitHub App private key, webhook secret, installation tokens, optional
owner metrics token, optional PostgreSQL connection secret, and repository metadata read during an audit. Attackers may send
arbitrary public HTTP requests, supply repository names and refs, open pull requests in
repositories where the App is installed, or attempt to forge webhooks. GitHub API data and
repository policy files are treated as untrusted input. The hosting environment and GitHub
service and optional PostgreSQL provider are external trust dependencies.

There are three main boundaries:

1. **Internet to public scanner:** `app.py` allowlists repository, ref, and pull number
   syntax, rejects conflicting query modes, and confirms the GitHub repository is public
   before returning an audit. The GitHub API origin is fixed in `github.py`; user input
   cannot select an arbitrary upstream host.
2. **GitHub to installed App webhook:** `security.py` verifies the raw request body against
   `X-Hub-Signature-256` before JSON event processing. `app.py` processes only supported
   event and action combinations; malformed required fields are rejected. The App requests
   limited GitHub permissions and uses short lived installation tokens for active work.
3. **Browser to owner only metrics:** the optional route requires configured HTTP Basic
   credentials and is absent when the owner token is unset. Authentication comparisons
   use constant time comparison. Responses are marked private, no store, and no index.

## Secure design and common weakness controls

QNode fails closed on missing or invalid webhook signatures and production authentication
secrets below 32 UTF-8 bytes. Configured App RSA keys must parse and have at least 2048
bits before the service starts. GitHub API calls use the Requests library's default TLS
certificate verification; QNode does not disable it. Network calls have timeouts.

Audit findings are constructed from paths and GitHub metadata, not repository source
execution. User supplied path text is rendered through Flask/Jinja autoescaping or
browser DOM `textContent`, not inserted as trusted HTML. `.qnode.json` is parsed as a
bounded policy format, not executed. Both optional visitor stores use parameterized
queries and store hashes of random browser tokens rather than raw tokens. The PostgreSQL
connection verifies the server certificate against system roots. Security
headers include a restrictive Content Security Policy and no sniffing.

Evidence includes the [test suite](../tests/), the [Python static scan and coverage CI](../.github/workflows/tests.yml),
the [JavaScript lint configuration](../eslint.config.mjs), and the published
[privacy model](../README.md#privacy-model). CI has a coverage floor of 85%; the local
September 2026 run measured 92% statement coverage. That figure is test execution
coverage, not proof of vulnerability absence.

## Residual risks and verification limits

Path heuristics can miss defects or flag harmless changes. GitHub may truncate large API
results, and third party service outages can prevent a complete audit. Single maintainer
access is an unresolved operational continuity risk. GitHub and the hosting provider's
security are not proven by this repository's tests. All controls require maintenance as
dependencies and deployment configuration change. Report suspected vulnerabilities
privately as described in [SECURITY.md](../SECURITY.md).
