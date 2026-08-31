<div align="center">

# QNODE // REPOSITORY AUDITOR

**A minimal GitHub App for engineering-readiness signals.**

`WEBHOOK::VERIFIED` · `PERMISSIONS::MINIMAL` · `DATA::EPHEMERAL`

</div>

QNode listens for pull-request events, inspects the repository tree, and publishes one compact GitHub Check covering documentation, tests, CI, licensing, dependencies, reproducibility, and security policy.

It is deliberately advisory: a low score is reported as neutral and never blocks a pull request.

## Signal path

```text
pull_request webhook
        │ HMAC-SHA256 verification
        ▼
installation token ──► repository tree paths
        │                        │
        └──────────────► deterministic audit
                                  │
                                  ▼
                         GitHub Check Run
```

## Why this design

- **Least privilege:** read repository contents metadata; write check runs.
- **No source ingestion:** only path names from Git trees are evaluated.
- **No persistence:** payloads, installation tokens, and repository data are not stored.
- **Reproducible:** pure audit rules, automated tests, pinned dependency ranges, and a container definition.
- **Transparent:** every signal includes its detected evidence.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
pytest -q
python -m qnode_auditor.app
```

The service exposes `GET /health` and `POST /webhook`. Environment variables are documented in [.env.example](.env.example); GitHub setup is in [docs/app-registration.md](docs/app-registration.md).

## Operational endpoints

- Service status: [qnode-repo-auditor.onrender.com](https://qnode-repo-auditor.onrender.com)
- Health check: [qnode-repo-auditor.onrender.com/health](https://qnode-repo-auditor.onrender.com/health)

## Deploy

The repository includes a production Docker image and a Render Blueprint. Create a web service from `render.yaml`, provide the GitHub App private key as the encrypted `GITHUB_PRIVATE_KEY` value, and point the GitHub App webhook to `https://YOUR-SERVICE/webhook`. The health check is available at `/health`.

## Audit contract

QNode currently checks seven repository-level signals using file paths only. Scores at or above 70 conclude with `success`; lower scores use `neutral`. This is an engineering prompt, not a security certification.

## Roadmap

- Optional repository policy configuration
- Check annotations with remediation links
- Installation dashboard with aggregate-free, privacy-preserving status

## Support

For installation or operational questions, email [mahidulhaqalif@gmail.com](mailto:mahidulhaqalif@gmail.com) or open a repository issue. Report security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

MIT © 2026 Mahidul Haque
