# Changelog

All notable changes to QNode are documented here.

## 0.4.0 - 2026-09-12

- Add a pull-request Review Map that groups files into logical ownership lanes.
- Recognize individual app, package, service, module, library, and component boundaries in monorepos.
- Rank review lanes by risk severity and churn, with focused signals and representative paths.
- Route each lane to matching CODEOWNERS handles and expose partially or fully unowned areas.
- Suggest exact ecosystem-aware companion test paths and workspace-aware dependency lockfiles.
- Include the Review Map and companion suggestions in GitHub Check Markdown, public reports, and JSON exports.
- Preserve the privacy model by reading only paths, metadata, and the CODEOWNERS policy—never application source contents and without requesting more permissions.

## 0.3.0 - 2026-09-07

- Accept public GitHub pull-request URLs and `owner/repository#number` in the scanner.
- Show PR metadata and path-only risk signals in the public report.
- Add permanent report links, Markdown copy, and JSON export actions.
- Add prominent GitHub App installation and scanner calls to action.
- Add a production app icon across the website, social metadata, and documentation.

## 0.2.0 — Repository intelligence

- Added a live public-repository scanner with evidence and prioritized recommendations.
- Expanded the audit from seven equal checks to twelve weighted engineering safeguards.
- Added pull-request risk detection for tests, dependency locks, workflows, migrations, large diffs, and credential-like paths.
- Added GitHub Check annotations and a manual re-run action.
- Added webhook delivery deduplication, tree-truncation reporting, response security headers, and public API caching.
- Added community health files, dependency automation, code ownership, and expanded tests.

## 0.1.0 — Initial GitHub App

- Verified signed pull-request webhooks.
- Published advisory GitHub Check runs using minimal repository permissions.
