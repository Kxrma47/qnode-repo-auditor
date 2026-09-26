# Optional QNode policy

Add a `.qnode.json` file at the repository root to tune advisory signals. QNode reads this one small configuration file in addition to CODEOWNERS; it does not read application source. The file must be valid JSON, no larger than 32 KiB, with `version: 1`.

```json
{
  "version": 1,
  "ignore_paths": ["packages/web/generated/**"],
  "critical_paths": ["services/api/auth/**", "services/api/migrations/**"],
  "test_jobs": {
    "services/api/**": ["api-unit", "api-integration"],
    "packages/web/**": ["web-test"]
  },
  "change_contracts": [
    {
      "id": "api-schema-client",
      "when": ["services/api/openapi/**"],
      "require_all": ["tests/contracts/**"],
      "require_any": ["packages/client/generated/**", "packages/client/src/**"],
      "reason": "Keep contract tests and the client in sync with the API schema"
    }
  ]
}
```

- `ignore_paths` excludes matching files from heuristic PR warnings and companion suggestions. It does **not** hide credential-like paths or configured critical-path alerts. The Review Map still includes every changed file.
- `critical_paths` marks matching changed paths as high-attention review prompts. It does not establish that the code is defective or determine true downstream impact.
- `test_jobs` lists CI job names your team associates with paths. QNode reports these as **configured suggestions**; it does not run jobs or verify that those workflow jobs exist. Existing candidate test files are also shown per Review Map lane.
- `change_contracts` declares path evidence expected in the **same pull request** when any `when` path changes. Every `require_all` pattern needs a matching changed path; `require_any` needs at least one match across its patterns. Rules are advisory. A present path does not prove the code or tests are correct. `reason` is an optional short explanation, not a note QNode can read or validate.

QNode shows matching changed paths, expected patterns, present/missing/unknown status, review lane, and matching declared CODEOWNERS. On an incomplete PR file list, an absent companion is **unknown**, never "missing." Removed paths do not satisfy a contract or trigger a new one. `ignore_paths` does not suppress explicit contracts. A policy may define at most 20 uniquely named contracts, each with 1–8 total requirements. The usual score remains unchanged.

Try a rule in the scanner's **Preview a change contract** panel before committing `.qnode.json`; the preview accepts a list of changed paths and makes no GitHub request. A [worked example](examples/change-contract-demo.md) shows both a missing and a complete result.

Patterns are case-sensitive, repository-relative glob strings. `*` can match across `/`; `services/api/**` matches that directory's descendants. Invalid or oversized policies are ignored in full and produce a visible warning. QNode never executes the values in this file. The standard repository score is unchanged by the policy.

QNode's own [`.qnode.json`](../.qnode.json) demonstrates critical paths and the real `test` CI job without suppressing any warnings.

## Review delta

If a pull request has a submitted human review, QNode compares Git tree blob IDs at the base, reviewed commit, and current head. It lists paths changed since that review and **new/resolved QNode advisory signals** in the PR-wide report. No application source patches are downloaded. QNode omits the delta when GitHub truncates a tree, the PR file list is incomplete, a comparison exceeds 1,000 changed paths, or an API call fails. No delta means “unavailable,” not “nothing changed.” Churn-based warnings are not included in the signal delta because blob IDs do not reveal line counts. The feature does not verify code behavior or actual test coverage.
