# Change-contract demo: an API schema update

This example uses filenames only. Paste the policy and changed paths into QNode's
**Preview a change contract** panel; no repository installation or GitHub API call is needed.

Policy (`.qnode.json`):

```json
{
  "version": 1,
  "change_contracts": [
    {
      "id": "api-schema",
      "when": ["openapi/**"],
      "require_all": ["tests/contracts/**"],
      "require_any": ["generated/client/**", "src/client/**"],
      "reason": "Update contract tests and one client representation"
    }
  ]
}
```

First preview these paths:

```text
openapi/api.yaml
src/client/api.ts
```

QNode reports `api-schema: missing`: the client alternative is present, but no changed
`tests/contracts/**` path appears. Add `tests/contracts/api_test.py` to the preview
list, and the contract becomes `present`. If GitHub supplies an incomplete PR file
list, any absent requirement is `unknown` instead. None of these states validates
the test or client implementation; a reviewer must still inspect the code.

For a database migration, use `when: ["supabase/migrations/**"]` and configure
your actual generated-types and query-layer paths. Keep the rules specific to your
repository rather than copying a universal naming convention.
