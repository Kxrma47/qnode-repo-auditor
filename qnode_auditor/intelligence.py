"""Path-only pull-request intelligence built from bounded repository metadata."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import PurePosixPath

from .audit import Audit, ChangedFile

MAX_HISTORY_COMMITS = 24
MAX_HISTORY_PATHS = 120
MAX_GRAPH_NODES = 160
MAX_GRAPH_EDGES = 260


def _lane_key(path: str) -> str:
    parts = PurePosixPath(path).parts
    if len(parts) == 1:
        return "."
    if parts[0].lower() in {"apps", "components", "libs", "modules", "packages", "services"}:
        return "/".join(parts[:2]) if len(parts) >= 3 else parts[0]
    return parts[0]


def _history_paths(item: dict | Iterable[str]) -> tuple[str, ...]:
    values = item.get("paths", ()) if isinstance(item, dict) else item
    return tuple(dict.fromkeys(str(path) for path in values if path))[:MAX_HISTORY_PATHS]


def change_memory(
    changed_files: Iterable[ChangedFile], history: Iterable[dict | Iterable[str]] = ()
) -> dict:
    """Find frequently co-changed paths without reading blobs or patches."""
    current = {file.filename for file in changed_files if file.status != "removed"}
    commits = [_history_paths(item) for item in history][:MAX_HISTORY_COMMITS]
    commits = [paths for paths in commits if paths]
    trigger_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    for paths in commits:
        path_set = set(paths)
        relevant = current & path_set
        for trigger in relevant:
            trigger_counts[trigger] += 1
            for companion in path_set - {trigger}:
                pair_counts[(trigger, companion)] += 1

    links = []
    for (trigger, companion), support in pair_counts.items():
        observations = trigger_counts[trigger]
        confidence = support / observations if observations else 0
        if support < 2 or confidence < 0.4:
            continue
        links.append(
            {
                "source": trigger,
                "target": companion,
                "support": support,
                "observations": observations,
                "confidence": round(confidence, 2),
                "present": companion in current,
            }
        )
    links.sort(key=lambda link: (-link["confidence"], -link["support"], link["target"]))
    links = links[:30]
    suggestions = [
        {
            "source_path": link["source"],
            "suggested_path": link["target"],
            "support": link["support"],
            "observations": link["observations"],
            "confidence": link["confidence"],
            "reason": (
                f"Changed together in {link['support']} of {link['observations']} sampled commits "
                "that touched the source path."
            ),
        }
        for link in links
        if not link["present"]
    ][:12]
    return {
        "available": bool(commits),
        "sampled_commits": len(commits),
        "links": links,
        "suggestions": suggestions,
        "note": (
            "Bounded co-change history from filenames only; correlation is not a dependency."
            if commits
            else "No bounded filename history was available; no co-change claim was made."
        ),
    }


def _deployment_area(path: str) -> str | None:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    if lowered.startswith(".github/workflows/"):
        return "GitHub Actions"
    if name in {"dockerfile", "render.yaml", "fly.toml", "procfile"}:
        return "Runtime delivery"
    if any(
        part in {"terraform", "infra", "infrastructure"} for part in PurePosixPath(lowered).parts
    ):
        return "Infrastructure"
    if any(part in {"migration", "migrations"} for part in PurePosixPath(lowered).parts):
        return "Database rollout"
    if any(part in {"k8s", "kubernetes", "helm"} for part in PurePosixPath(lowered).parts):
        return "Cluster delivery"
    return None


def impact_graph(audit: Audit, changed_files: Iterable[ChangedFile], memory: dict) -> dict:
    """Build a bounded visual graph of observed path relationships."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(node_id: str, kind: str, label: str, **metadata) -> None:
        if len(nodes) < MAX_GRAPH_NODES or node_id in nodes:
            nodes[node_id] = {"id": node_id, "kind": kind, "label": label} | metadata

    def edge(source: str, target: str, kind: str, **metadata) -> None:
        if len(edges) < MAX_GRAPH_EDGES and source in nodes and target in nodes:
            value = {"source": source, "target": target, "kind": kind} | metadata
            if value not in edges:
                edges.append(value)

    for lane in audit.review_lanes:
        lane_id = f"lane:{lane.key}"
        node(lane_id, "lane", lane.label, attention=lane.attention)
        for path in lane.paths:
            path_id = f"path:{path}"
            node(path_id, "path", path, lane=lane.key)
            edge(lane_id, path_id, "contains")
            area = _deployment_area(path)
            if area:
                area_id = f"deployment:{area}"
                node(area_id, "deployment", area)
                edge(path_id, area_id, "affects")
        for owner in lane.owners:
            owner_id = f"owner:{owner}"
            node(owner_id, "owner", owner)
            edge(lane_id, owner_id, "owned-by")
        for target in lane.test_targets:
            target_id = f"test:{target}"
            node(target_id, "test", target)
            edge(lane_id, target_id, "tested-by-candidate")
        for job in lane.configured_jobs:
            job_id = f"job:{job}"
            node(job_id, "job", job)
            edge(lane_id, job_id, "maps-to")

    for index, contract in enumerate(audit.change_contracts):
        contract_id = f"contract:{index}:{contract.id}"
        node(contract_id, "contract", contract.id, status=contract.status)
        for lane in contract.lanes:
            lane_id = f"lane:{lane}"
            if lane_id in nodes:
                edge(lane_id, contract_id, "declares")

    for link in memory["links"]:
        source = f"path:{link['source']}"
        target = f"path:{link['target']}"
        node(target, "path", link["target"], historical=True)
        edge(
            source,
            target,
            "co-changed",
            confidence=link["confidence"],
            support=link["support"],
            present=link["present"],
        )

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "truncated": len(nodes) >= MAX_GRAPH_NODES or len(edges) >= MAX_GRAPH_EDGES,
        "note": (
            "Graph edges are path, policy, ownership, CI mapping, and co-change evidence; "
            "not source-code dependencies."
        ),
    }


def ci_plan(audit: Audit) -> dict:
    jobs: list[dict] = []
    seen: set[str] = set()
    for lane in audit.review_lanes:
        paths = [path.lower() for path in lane.paths]
        candidates = [
            (job, "Configured for this lane in .qnode.json", "configured")
            for job in lane.configured_jobs
        ]
        if lane.source_files:
            candidates.append(
                ("focused-tests", "Changed source paths need focused verification", "heuristic")
            )
        if any(path.startswith(".github/workflows/") for path in paths):
            candidates.append(
                ("workflow-security-review", "GitHub Actions workflow changed", "heuristic")
            )
        if any(
            any(part in {"migration", "migrations"} for part in PurePosixPath(path).parts)
            for path in paths
        ):
            candidates.append(
                ("migration-compatibility", "Database migration path changed", "heuristic")
            )
        if any(
            PurePosixPath(path).name in {"package.json", "pyproject.toml", "go.mod", "cargo.toml"}
            for path in paths
        ):
            candidates.append(("dependency-review", "Dependency manifest changed", "heuristic"))
        if paths and all(PurePosixPath(path).suffix in {".md", ".rst", ".txt"} for path in paths):
            candidates.append(
                ("docs-check", "Only documentation-like paths changed in this lane", "heuristic")
            )
        for name, reason, evidence in candidates:
            key = f"{name}:{lane.key}"
            if key in seen:
                continue
            seen.add(key)
            jobs.append(
                {
                    "name": name,
                    "lane": lane.label,
                    "reason": reason,
                    "evidence": evidence,
                    "paths": list(lane.paths[:5]),
                }
            )
    return {
        "jobs": jobs[:24],
        "note": (
            "A minimal advisory plan; QNode did not run these jobs or verify that heuristic "
            "job names exist."
        ),
    }


def review_freshness(audit: Audit, pull: dict | None, ci: dict | None) -> dict:
    if not pull:
        return {
            "status": "not-applicable",
            "reasons": [],
            "note": "Freshness applies to pull requests.",
        }
    reasons = []
    delta = audit.review_delta
    if delta is None:
        reasons.append(
            {"level": "unknown", "text": "No complete submitted-review comparison is available."}
        )
    elif delta.changed_path_count:
        reasons.append(
            {
                "level": "stale",
                "text": (
                    f"{delta.changed_path_count} repository paths differ from the latest "
                    "reviewed commit."
                ),
            }
        )
        if delta.new_signals:
            reasons.append(
                {
                    "level": "stale",
                    "text": (
                        f"{len(delta.new_signals)} new QNode signal(s) appeared after that review."
                    ),
                }
            )
    else:
        reasons.append(
            {"level": "current", "text": "The PR head matches the latest submitted review commit."}
        )

    if ci is None or not ci.get("available"):
        reasons.append({"level": "unknown", "text": "Current-head CI evidence was unavailable."})
    else:
        states = [item.get("state") for item in ci.get("observed", [])]
        if "failed" in states:
            reasons.append({"level": "stale", "text": "A current-head check is failing."})
        if "pending" in states:
            reasons.append({"level": "pending", "text": "A current-head check is still pending."})
        if ci.get("not_observed"):
            reasons.append(
                {
                    "level": "unknown",
                    "text": (
                        f"{len(ci['not_observed'])} configured check label(s) were not observed."
                    ),
                }
            )
    levels = {reason["level"] for reason in reasons}
    status = (
        "stale"
        if "stale" in levels
        else "pending"
        if "pending" in levels
        else "unknown"
        if "unknown" in levels
        else "current"
    )
    return {
        "status": status,
        "reasons": reasons,
        "reviewed_sha": delta.baseline_sha if delta else "",
        "head_sha": pull.get("head_sha", ""),
        "note": (
            "Freshness uses submitted-review commit and current-head check metadata; it is "
            "not an approval decision."
        ),
    }


def merge_readiness(pull: dict | None, ci: dict | None, gate_context: dict | None = None) -> dict:
    """Explain observed PR gates without claiming access to every repository rule."""
    if not pull:
        return {
            "status": "not-applicable",
            "headline": "NOT A PULL REQUEST",
            "blockers": [],
            "waiting": [],
            "warnings": [],
            "satisfied": [],
            "next_actions": [],
            "complete": False,
            "note": "Merge readiness applies only to pull requests.",
        }

    blockers: list[dict] = []
    waiting: list[dict] = []
    warnings: list[dict] = []
    satisfied: list[dict] = []
    actions: list[str] = []

    def add(target: list[dict], code: str, label: str, detail: str, evidence: str) -> None:
        target.append({"code": code, "label": label, "detail": detail, "evidence": evidence})

    if pull.get("draft"):
        add(
            blockers,
            "draft",
            "Draft pull request",
            "Mark it ready for review when complete.",
            "pull-request",
        )
        actions.append("Mark the pull request ready for review.")
    else:
        add(
            satisfied,
            "not-draft",
            "Ready for review",
            "The pull request is not a draft.",
            "pull-request",
        )

    if gate_context:
        mergeable = gate_context.get("mergeable", "unknown")
        merge_state = gate_context.get("merge_state_status", "unknown")
        decision = gate_context.get("review_decision", "")
        if mergeable == "conflicting" or merge_state == "dirty":
            add(
                blockers,
                "conflicts",
                "Merge conflicts",
                "GitHub reports conflicting changes.",
                "github-merge-state",
            )
            actions.append("Resolve merge conflicts against the base branch.")
        elif mergeable == "mergeable":
            add(
                satisfied,
                "mergeable",
                "No merge conflict observed",
                "GitHub reports the branches as mergeable.",
                "github-merge-state",
            )
        else:
            add(
                warnings,
                "mergeability-unknown",
                "Mergeability still computing",
                "GitHub has not produced a definitive mergeability result.",
                "github-merge-state",
            )

        if decision == "changes_requested":
            add(
                blockers,
                "changes-requested",
                "Changes requested",
                "At least one submitted review requests changes.",
                "github-review-decision",
            )
            actions.append("Address the requested changes and ask for re-review.")
        elif decision == "review_required":
            add(
                waiting,
                "review-required",
                "Approval required",
                "GitHub reports that an approving review is still required.",
                "github-review-decision",
            )
            actions.append("Request or wait for the required approving review.")
        elif decision == "approved":
            add(
                satisfied,
                "approved",
                "Review approved",
                "GitHub reports an approved review decision.",
                "github-review-decision",
            )
        else:
            add(
                warnings,
                "review-decision-unknown",
                "Review requirement unknown",
                "No aggregate review decision was available.",
                "github-review-decision",
            )

        unresolved = int(gate_context.get("unresolved_threads", 0))
        if unresolved:
            outdated = int(gate_context.get("outdated_unresolved_threads", 0))
            detail = f"{unresolved} review thread(s) are unresolved"
            if outdated:
                detail += f", including {outdated} marked outdated"
            add(
                blockers,
                "unresolved-threads",
                "Unresolved review threads",
                detail + ".",
                "github-review-threads",
            )
            actions.append("Resolve or answer every unresolved review thread.")
        elif gate_context.get("threads_complete"):
            add(
                satisfied,
                "threads-resolved",
                "Review threads clear",
                "No unresolved review threads were observed.",
                "github-review-threads",
            )
        else:
            add(
                warnings,
                "threads-incomplete",
                "Thread listing incomplete",
                "GitHub returned more review threads than QNode's bounded scan inspected.",
                "github-review-threads",
            )

        if gate_context.get("in_merge_queue"):
            add(
                waiting,
                "merge-queue",
                "In merge queue",
                "The pull request is waiting in GitHub's merge queue.",
                "github-merge-queue",
            )
        elif merge_state == "behind":
            add(
                waiting,
                "base-behind",
                "Base branch moved",
                "GitHub reports that the head branch is behind the base branch.",
                "github-merge-state",
            )
            actions.append("Update the branch from the current base branch.")
        elif merge_state == "unstable":
            add(
                waiting,
                "unstable",
                "Checks are not settled",
                "GitHub reports an unstable merge state.",
                "github-merge-state",
            )
        elif merge_state == "blocked" and not blockers:
            add(
                warnings,
                "github-blocked",
                "Another GitHub rule is blocking",
                (
                    "GitHub reports BLOCKED, but the accessible metadata does not identify "
                    "the exact rule."
                ),
                "github-merge-state",
            )
            actions.append("Open GitHub's merge box to inspect repository or ruleset requirements.")

    checks = (ci or {}).get("observed", []) if (ci or {}).get("available") else []
    failed = [check for check in checks if check.get("state") == "failed"]
    pending = [check for check in checks if check.get("state") == "pending"]
    if failed:
        add(
            blockers,
            "checks-failed",
            "Checks failing",
            f"{len(failed)} observed current-head check(s) failed.",
            "observed-checks",
        )
        actions.append("Fix or rerun the failing current-head checks.")
    if pending:
        add(
            waiting,
            "checks-pending",
            "Checks running",
            f"{len(pending)} observed current-head check(s) are pending.",
            "observed-checks",
        )
    if checks and not failed and not pending:
        add(
            satisfied,
            "checks-passed",
            "Observed checks passed",
            f"All {len(checks)} observed current-head check(s) passed.",
            "observed-checks",
        )
    if not ci or not ci.get("available"):
        add(
            warnings,
            "checks-unavailable",
            "Check evidence unavailable",
            "Current-head check runs could not be inspected.",
            "observed-checks",
        )
    elif not ci.get("complete"):
        add(
            warnings,
            "checks-incomplete",
            "Check listing incomplete",
            "The bounded check-run listing may omit checks.",
            "observed-checks",
        )
    if ci and ci.get("not_observed"):
        add(
            warnings,
            "configured-checks-unseen",
            "Configured labels not observed",
            (
                f"{len(ci['not_observed'])} configured check label(s) were not found on "
                "the current head."
            ),
            "qnode-policy",
        )

    complete = bool(
        gate_context
        and gate_context.get("threads_complete")
        and ci
        and ci.get("available")
        and ci.get("complete")
    )
    if blockers:
        status, headline = "blocked", f"{len(blockers)} OBSERVED BLOCKER(S)"
    elif gate_context and gate_context.get("in_merge_queue"):
        status, headline = "queued", "IN MERGE QUEUE"
    elif waiting:
        status, headline = "waiting", f"WAITING ON {len(waiting)} GATE(S)"
    elif complete and not warnings:
        status, headline = "clear-observed", "OBSERVED GATES CLEAR"
    else:
        status, headline = "unknown", "NEEDS GITHUB CONFIRMATION"
    return {
        "status": status,
        "headline": headline,
        "blockers": blockers,
        "waiting": waiting,
        "warnings": warnings,
        "satisfied": satisfied,
        "next_actions": list(dict.fromkeys(actions)),
        "complete": complete,
        "auto_merge_enabled": bool(gate_context and gate_context.get("auto_merge_enabled")),
        "note": (
            "A receipt of accessible GitHub metadata, not a merge authorization. Private rulesets, "
            "required deployments, and checks outside the bounded response may still apply."
        ),
    }


def blast_radius(audit: Audit, changed_files: Iterable[ChangedFile], memory: dict) -> dict:
    files = tuple(changed_files)
    score = 5
    factors = []

    def add(points: int, label: str, evidence: str) -> None:
        nonlocal score
        score += points
        factors.append({"points": points, "label": label, "evidence": evidence})

    high = sum(risk.severity == "high" for risk in audit.risks)
    medium = sum(risk.severity == "medium" for risk in audit.risks)
    if high:
        add(min(30, high * 15), "Critical-path signals", f"{high} high-attention path signal(s)")
    if medium:
        add(min(20, medium * 8), "Review uncertainty", f"{medium} medium-attention path signal(s)")
    if len(audit.review_lanes) > 1:
        add(
            min(18, (len(audit.review_lanes) - 1) * 5),
            "Cross-area change",
            f"{len(audit.review_lanes)} review lanes",
        )
    deployment = sorted({area for file in files if (area := _deployment_area(file.filename))})
    if deployment:
        add(min(20, len(deployment) * 8), "Operational reach", ", ".join(deployment))
    auth_paths = [
        file.filename
        for file in files
        if any(
            token in file.filename.lower() for token in ("auth", "permission", "access", "session")
        )
    ]
    if auth_paths:
        add(15, "Identity or access surface", auth_paths[0])
    historical = [link for link in memory["links"] if link["confidence"] >= 0.6]
    if historical:
        add(
            min(15, len(historical) * 3),
            "Historical co-change reach",
            f"{len(historical)} strong filename relationship(s)",
        )
    score = min(100, score)
    level = (
        "critical" if score >= 75 else "high" if score >= 55 else "medium" if score >= 30 else "low"
    )
    return {
        "score": score,
        "level": level,
        "factors": factors,
        "note": (
            "Transparent path-metadata heuristic for review prioritization, not defect probability."
        ),
    }


def split_plan(audit: Audit, memory: dict) -> dict:
    lanes = {lane.key: lane for lane in audit.review_lanes}
    parent = {key: key for key in lanes}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    couplings = []
    for contract in audit.change_contracts:
        keys = [lane for lane in contract.lanes if lane in lanes]
        for key in keys[1:]:
            union(keys[0], key)
        if len(keys) > 1:
            couplings.append({"kind": "contract", "lanes": keys, "label": contract.id})
    for link in memory["links"]:
        if link["confidence"] < 0.6:
            continue
        left, right = _lane_key(link["source"]), _lane_key(link["target"])
        if left in lanes and right in lanes and left != right:
            union(left, right)
            couplings.append(
                {
                    "kind": "history",
                    "lanes": [left, right],
                    "label": f"{link['confidence']:.0%} co-change",
                }
            )

    grouped: dict[str, list] = {}
    for key, lane in lanes.items():
        grouped.setdefault(find(key), []).append(lane)
    groups = []
    for index, members in enumerate(sorted(grouped.values(), key=lambda group: group[0].key), 1):
        paths = [path for lane in members for path in lane.paths]
        groups.append(
            {
                "id": f"part-{index}",
                "title": " + ".join(lane.label for lane in members),
                "lanes": [lane.label for lane in members],
                "paths": paths[:40],
                "file_count": len(paths),
                "attention": max(
                    (lane.attention for lane in members),
                    key=lambda value: {"routine": 0, "low": 1, "medium": 2, "high": 3}[value],
                ),
            }
        )
    changed_count = sum(lane.file_count for lane in audit.review_lanes)
    recommended = len(groups) >= 2 and (changed_count >= 6 or len(audit.review_lanes) >= 3)
    return {
        "recommended": recommended,
        "groups": groups,
        "couplings": couplings[:20],
        "note": (
            "Suggested review/PR boundaries from lanes and observed coupling; no branch was "
            "modified."
        ),
    }


def reviewer_router(audit: Audit, observed_load: dict[str, int] | None = None) -> dict:
    load_available = observed_load is not None
    load = observed_load or {}
    routes = []
    for lane in audit.review_lanes:
        candidates = sorted(
            lane.owners,
            key=lambda owner: (load.get(owner, 0) if load_available else 10**6, owner.casefold()),
        )
        routes.append(
            {
                "lane": lane.label,
                "attention": lane.attention,
                "candidates": [
                    {
                        "owner": owner,
                        "observed_open_requests": load.get(owner, 0) if load_available else None,
                        "kind": "team" if owner.count("/") else "user-or-email",
                    }
                    for owner in candidates
                ],
                "suggested": candidates[0] if candidates else "",
                "unowned_files": lane.unowned_files,
            }
        )
    return {
        "routes": routes,
        "load_available": load_available,
        "note": (
            "Declared CODEOWNERS are ordered by bounded observed open review requests; team "
            "membership and availability are not inferred."
        ),
    }


def reviewer_load_snapshot(pulls: Iterable[dict]) -> dict[str, int]:
    """Count only reviewer requests visible in one bounded open-PR listing."""
    counts: Counter[str] = Counter()
    for pull in pulls:
        counts.update(pull.get("requested_reviewers", ()))
        counts.update(pull.get("requested_teams", ()))
    return dict(counts)


def maintainer_decision_pack(
    audit: Audit,
    changed_files: Iterable[ChangedFile],
    *,
    ci: dict | None,
    memory: dict,
    readiness: dict,
    router: dict,
    gate_context: dict | None,
) -> dict:
    """Build ten bounded, path-metadata decision lenses for maintainers."""
    files = tuple(changed_files)
    paths = [file.filename for file in files if file.status != "removed"]
    total_files = len(paths)
    total_sources = sum(lane.source_files for lane in audit.review_lanes)
    test_matches = sum(lane.test_path_matches for lane in audit.review_lanes)
    unowned = sum(lane.unowned_files for lane in audit.review_lanes)
    configured_unseen = len((ci or {}).get("not_observed", ()))

    def lens(
        key: str,
        title: str,
        status: str,
        value: str,
        detail: str,
        action: str,
        evidence: str,
    ) -> dict:
        return {
            "key": key,
            "title": title,
            "status": status,
            "value": value,
            "detail": detail,
            "action": action,
            "evidence": evidence,
        }

    source_gaps = max(0, total_sources - test_matches)
    verification_status = "attention" if source_gaps or configured_unseen else "clear"
    verification = lens(
        "verification-debt",
        "Verification debt",
        verification_status,
        f"{source_gaps} source gap(s)",
        f"{test_matches}/{total_sources} changed source path(s) have a matching changed test path; "
        f"{configured_unseen} configured check label(s) were not observed.",
        "Add focused tests or confirm why the mapped verification is not required.",
        "review-map + observed-checks",
    )

    owned = max(0, total_files - unowned)
    ownership_pct = round(owned * 100 / total_files) if total_files else 100
    ownership = lens(
        "ownership-coverage",
        "Ownership coverage",
        "attention" if unowned else "clear",
        f"{ownership_pct}% owned",
        f"{unowned} of {total_files} changed path(s) have no matching declared CODEOWNER.",
        "Assign an owner or explain the reviewer responsible for uncovered paths.",
        "CODEOWNERS last-match rules",
    )

    largest_lane = max(audit.review_lanes, key=lambda item: item.file_count, default=None)
    largest_share = (
        round(largest_lane.file_count * 100 / total_files) if largest_lane and total_files else 0
    )
    concentration = lens(
        "change-concentration",
        "Change concentration",
        "watch" if len(audit.review_lanes) >= 3 else "clear",
        f"{largest_share}% largest lane",
        (
            f"{len(audit.review_lanes)} lane(s); "
            f"{largest_lane.label if largest_lane else 'none'} carries the largest file share."
        ),
        "Use the split plan when unrelated lanes can be reviewed independently.",
        "changed-path lanes",
    )

    rollout_areas = sorted({area for path in paths if (area := _deployment_area(path))})
    rollout = lens(
        "rollout-surface",
        "Rollout surface",
        "attention" if rollout_areas else "clear",
        f"{len(rollout_areas)} area(s)",
        ", ".join(rollout_areas) if rollout_areas else "No deployment-like path was observed.",
        "Confirm staging, health checks, concurrency, and production approval for rollout paths.",
        "deployment-path heuristic",
    )

    rollback_tokens = ("rollback", "revert", "restore", ".down.", "down.sql")
    rollback_paths = [
        path for path in paths if any(token in path.lower() for token in rollback_tokens)
    ]
    rollback = lens(
        "rollback-evidence",
        "Rollback evidence",
        "attention"
        if rollout_areas and not rollback_paths
        else "clear"
        if rollout_areas
        else "unknown",
        f"{len(rollback_paths)} path(s)",
        (
            ", ".join(rollback_paths[:3])
            if rollback_paths
            else "No rollback-labelled changed path was observed."
        ),
        "Document or test the rollback path when this change affects delivery or migrations.",
        "filename evidence only",
    )

    contract_tokens = ("openapi", "swagger", ".proto", "graphql", "schema", "public/api")
    contract_paths = [
        path for path in paths if any(token in path.lower() for token in contract_tokens)
    ]
    contract_missing = [
        contract for contract in audit.change_contracts if contract.status in {"missing", "unknown"}
    ]
    contract_watch = lens(
        "contract-surface",
        "Contract surface",
        "attention"
        if contract_paths and contract_missing
        else "watch"
        if contract_paths
        else "clear",
        f"{len(contract_paths)} contract path(s)",
        (
            f"{len(contract_missing)} declared contract(s) lack complete companion evidence."
            if contract_paths
            else "No API or schema-like changed path was observed."
        ),
        "Verify compatibility, generated clients, documentation, and contract tests.",
        "paths + .qnode.json contracts",
    )

    manifest_names = {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
    }
    manifests = [path for path in paths if PurePosixPath(path.lower()).name in manifest_names]
    lock_gaps = [item for item in audit.companion_suggestions if item.kind == "lockfile"]
    dependency = lens(
        "dependency-sync",
        "Dependency synchronization",
        "attention" if lock_gaps else "watch" if manifests else "clear",
        f"{len(lock_gaps)} lock gap(s)",
        (
            f"{len(manifests)} dependency manifest(s) changed; "
            f"{len(lock_gaps)} need lockfile attention."
        ),
        "Update the workspace-matched lockfile or document why resolution is unchanged.",
        "manifest + companion-path heuristic",
    )

    routed = [route for route in router["routes"] if route["candidates"]]
    single_candidate = sum(len(route["candidates"]) == 1 for route in routed)
    routing = lens(
        "reviewer-resilience",
        "Reviewer resilience",
        "attention"
        if routed and single_candidate == len(routed)
        else "unknown"
        if not routed
        else "clear",
        f"{single_candidate}/{len(routed)} single-owner lane(s)",
        "Counts declared candidates only; team membership and availability are not inferred.",
        "Add a second declared owner for critical lanes with one visible candidate.",
        "CODEOWNERS + bounded reviewer load",
    )

    friction_count = len(readiness["blockers"]) + len(readiness["waiting"])
    friction = lens(
        "queue-friction",
        "Merge queue friction",
        "attention" if readiness["blockers"] else "watch" if readiness["waiting"] else "clear",
        f"{friction_count} active gate(s)",
        readiness["headline"],
        readiness["next_actions"][0]
        if readiness["next_actions"]
        else "Keep observing GitHub merge state.",
        "merge-readiness receipt",
    )

    evidence_checks = {
        "checks": bool(ci and ci.get("available") and ci.get("complete")),
        "merge gates": bool(gate_context and gate_context.get("threads_complete")),
        "history": bool(memory.get("available")),
        "review delta": audit.review_delta is not None,
        "reviewer load": bool(router.get("load_available")),
        "complete paths": not audit.tree_truncated and not audit.files_truncated,
    }
    known = sum(evidence_checks.values())
    confidence = lens(
        "evidence-confidence",
        "Evidence confidence",
        "clear" if known == len(evidence_checks) else "watch" if known >= 3 else "unknown",
        f"{known}/{len(evidence_checks)} sources",
        ", ".join(
            f"{name}: {'yes' if available else 'unknown'}"
            for name, available in evidence_checks.items()
        ),
        "Treat unknown evidence as unknown; do not convert it into a pass.",
        "bounded-input ledger",
    )

    items = [
        verification,
        ownership,
        concentration,
        rollout,
        rollback,
        contract_watch,
        dependency,
        routing,
        friction,
        confidence,
    ]
    return {
        "items": items,
        "attention_count": sum(item["status"] == "attention" for item in items),
        "note": (
            "Ten deterministic decision lenses from bounded paths and GitHub metadata; statuses "
            "are review prompts, not proof of defects, coverage, ownership availability, or safety."
        ),
    }


def build_review_intelligence(
    audit: Audit,
    changed_files: Iterable[ChangedFile],
    *,
    pull: dict | None = None,
    ci: dict | None = None,
    history: Iterable[dict | Iterable[str]] = (),
    reviewer_load: dict[str, int] | None = None,
    gate_context: dict | None = None,
) -> dict:
    files = tuple(changed_files)
    memory = change_memory(files, history)
    readiness = merge_readiness(pull, ci, gate_context)
    router = reviewer_router(audit, reviewer_load)
    return {
        "change_memory": memory,
        "impact_graph": impact_graph(audit, files, memory),
        "ci_plan": ci_plan(audit),
        "review_freshness": review_freshness(audit, pull, ci),
        "blast_radius": blast_radius(audit, files, memory),
        "split_plan": split_plan(audit, memory),
        "reviewer_router": router,
        "merge_readiness": readiness,
        "decision_pack": maintainer_decision_pack(
            audit,
            files,
            ci=ci,
            memory=memory,
            readiness=readiness,
            router=router,
            gate_context=gate_context,
        ),
    }


def intelligence_markdown(data: dict) -> str:
    blast = data["blast_radius"]
    freshness = data["review_freshness"]
    memory = data["change_memory"]
    readiness = data["merge_readiness"]
    decision_pack = data["decision_pack"]
    lines = [
        "## QNode review intelligence",
        "",
        f"- **Blast radius:** {blast['score']}/100 ({blast['level']}); path-metadata heuristic.",
        f"- **Review freshness:** {freshness['status']}; not an approval decision.",
        f"- **Merge readiness:** {readiness['headline'].lower()}; observed metadata only.",
        f"- **Decision pack:** {decision_pack['attention_count']}/10 lens(es) need attention.",
        f"- **CI plan:** {len(data['ci_plan']['jobs'])} configured or heuristic job suggestion(s).",
        "- **Split plan:** "
        f"{'suggested' if data['split_plan']['recommended'] else 'not suggested'} across "
        f"{len(data['split_plan']['groups'])} coupled group(s).",
        f"- **Change memory:** {len(memory['suggestions'])} possible missing historical "
        f"companion(s) from {memory['sampled_commits']} sampled commit(s).",
    ]
    for suggestion in memory["suggestions"][:5]:
        lines.append(
            f"  - `{suggestion['source_path']}` often changed with "
            f"`{suggestion['suggested_path']}` "
            f"({suggestion['support']}/{suggestion['observations']} sampled occurrences)."
        )
    for item in (readiness["blockers"] + readiness["waiting"] + readiness["warnings"])[:6]:
        lines.append(f"  - **{item['label']}:** {item['detail']} ({item['evidence']})")
    for item in [item for item in decision_pack["items"] if item["status"] == "attention"][:5]:
        lines.append(
            f"  - **{item['title']}:** {item['value']}. {item['action']} ({item['evidence']})"
        )
    lines.extend(
        [
            "",
            "_All relationships are filename, history, ownership, policy, and check metadata. "
            "They do not prove code dependencies, test coverage, reviewer availability, or "
            "defects._",
        ]
    )
    return "\n".join(lines)
