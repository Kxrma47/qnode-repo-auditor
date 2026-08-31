# GitHub App registration

Register a GitHub App with these minimum settings:

- Webhook URL: `https://YOUR-HOST/webhook`
- Webhook secret: a generated random value
- Repository permissions: **Contents: read**, **Checks: read and write**, **Metadata: read**
- Subscribe to events: **Pull request**
- Installation scope: only selected repositories while testing

If an account cannot save an App-level webhook, create a repository webhook for the installed test repository with the same URL and secret. Subscribe it only to **Pull requests**, then set `GITHUB_INSTALLATION_ID` to the App installation ID. This repository uses that scoped configuration.

Generate a private key only after registration. Store the PEM outside the repository and point `GITHUB_PRIVATE_KEY_PATH` to it. Never paste the key into an issue, log, commit, or deployment variable visible to clients.

For local development, expose port 8000 using a trusted HTTPS tunnel and update the webhook URL. Send a GitHub test ping, then open a pull request in an installed test repository and confirm that the **QNode engineering readiness** check appears.

## Production verification

1. Confirm the webhook is active, uses `application/json`, and verifies TLS.
2. Confirm a GitHub ping returns HTTP 200.
3. Open a pull request and confirm its delivery returns HTTP 200.
4. Confirm the **QNode engineering readiness** check completes on the pull request head commit.
