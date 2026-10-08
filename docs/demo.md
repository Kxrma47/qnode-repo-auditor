# QNode in 45 seconds

1. Open the [instant demonstration](https://qnode-repo-auditor.onrender.com/?demo=1#scanner).
2. Review the clearly labelled synthetic report, or paste a public pull-request URL and select
   **Run audit** for live GitHub evidence.
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
