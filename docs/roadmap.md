# QNode roadmap: September 2026 to September 2027

This roadmap describes intended direction, not a promise that every item will ship on a
fixed date. The maintainer reviews priorities in public issues and discussions as real
users provide examples. Privacy first, explainable, non blocking reviews remain the
project's scope.

## September to December 2026: reliability and clarity

- Keep the GitHub App, public scanner, and documented API aligned with actual behavior.
- Improve regression tests for webhook events, error handling, policy parsing, and
  incomplete GitHub API responses.
- Make false positive and incomplete report explanations easier to understand.
- Review dependency updates and operational security before each release.

## January to April 2027: review signals

- Evaluate user supplied PR examples for missed test, ownership, dependency, and rollout
  signals; add only deterministic rules with reproducible fixtures.
- Refine monorepo review lanes and path aware test suggestions where evidence shows a
  useful improvement.
- Document and measure any new rule's known false positives and limitations.

## May to September 2027: contributor feedback and maintenance

- Review feature suggestions and bug reports in public, with clear decisions and reasons.
- Improve installation, configuration, and troubleshooting documentation based on real
  contributor questions.
- Reassess maintenance continuity and whether a qualified backup maintainer can be added.

## Out of scope for this period

- Reading or storing application source code as part of the ordinary audit.
- Claiming QNode proves a repository is secure or that a path based suggestion is a test
  coverage measurement.
- Blocking pull request merges based only on heuristic findings.
- Advertising a persistent website user count on infrastructure without durable storage.

Propose changes or priorities in [discussions](https://github.com/Kxrma47/qnode-repo-auditor/discussions).
