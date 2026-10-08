# QNode v1 launch copy

## Short post

QNode is a privacy-first pull-request review map. Paste a public PR URL to see risky files,
missing tests, ownership gaps, and forgotten companion changes. It reads paths and metadata,
not application source contents. The new local GitHub Action adds the same advisory brief to
workflow summaries without sending source code to QNode.

Try it: https://qnode-repo-auditor.onrender.com

Source and Action: https://github.com/Kxrma47/qnode-repo-auditor

Feedback: https://github.com/Kxrma47/qnode-repo-auditor/discussions/6

## Pilot invitation

I am looking for a few maintainers willing to test QNode on one public pull request. I will
send a path-only review map and would value feedback on false positives, missed signals, and
whether the handoff changed what you reviewed. No installation is needed for the first scan.
