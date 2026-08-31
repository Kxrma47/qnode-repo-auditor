# GitHub App registration

## App settings

Register a GitHub App with:

- **Homepage URL:** your deployed service root
- **Webhook URL:** `https://YOUR-HOST/webhook`
- **Webhook secret:** a generated high-entropy value
- **Expire user authorization tokens:** irrelevant; QNode does not request user authorization

Repository permissions:

- **Metadata:** read (GitHub grants this baseline permission)
- **Contents:** read
- **Pull requests:** read
- **Checks:** read and write

Subscribe to:

- **Pull request**
- **Check run**

Install the App only on repositories that should receive QNode Checks. The public scanner does not require installation and only works with public repositories.

## Credentials

Generate a private key after registration. Store the PEM outside the repository and configure one of:

- `GITHUB_PRIVATE_KEY` for a deployment secret; or
- `GITHUB_PRIVATE_KEY_PATH` for local development.

Set `GITHUB_APP_ID` to the App ID. `GITHUB_INSTALLATION_ID` is only a fallback for repository-level webhook configurations whose payload does not include an installation object.

Never paste the private key, webhook secret, installation token, or a real webhook payload into an issue, commit, screenshot, or client-visible setting.

## Local webhook testing

1. Run the service on port 8000.
2. Expose it through a trusted HTTPS tunnel.
3. Set the App webhook URL to the tunnel's `/webhook` route.
4. Send a GitHub test ping and confirm HTTP 200.
5. Open a pull request in an installed repository.
6. Confirm **QNode repository intelligence** appears on the head commit.
7. Choose **Re-run audit** and confirm the requested-action delivery completes.

## Production verification

1. `/health` reports `ready` and `webhook_configured: true`.
2. The webhook uses `application/json`, verifies TLS, and has no failing deliveries.
3. A pull request creates one completed Check with a score, evidence, recommendations, and any applicable annotations.
4. Re-delivering the same webhook delivery ID does not create another Check within the same running process.
5. The service logs do not contain payloads, installation tokens, or private keys.
6. The installed App has no permissions beyond those listed above.

## Repository webhook fallback

If an account cannot save an App-level webhook, create a repository webhook with the same URL and secret, subscribe it to pull-request events, and configure `GITHUB_INSTALLATION_ID`. The Check re-run button requires the App's **Check run** event subscription and therefore may not work with a pull-request-only repository webhook.
