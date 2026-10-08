# QNode in 45 seconds

1. Open the [live scanner](https://qnode-repo-auditor.onrender.com).
2. Paste a public pull-request URL and select **Run audit**.
3. Start with **Pull-request signals** to see missing test, lockfile, workflow, migration,
   credential-path, and large-change prompts.
4. Open **Review Map** to route each path lane to its matching CODEOWNERS and candidate tests.
5. Copy **Editable review handoff** to share observed evidence and the unanswered questions
   without inventing approval, coverage, or merge readiness.

No sign-in or installation is required for the public scanner. QNode reads GitHub paths,
metadata, optional `CODEOWNERS`, and optional `.qnode.json` policy data. It does not fetch
application source contents or retain scan reports.

For repeated use, add the [QNode Action](../README.md#github-action). It runs the same
path-derived audit locally against the checked-out Git tree and writes the result to the
workflow summary.
