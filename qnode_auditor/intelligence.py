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


def build_review_intelligence(
    audit: Audit,
    changed_files: Iterable[ChangedFile],
    *,
    pull: dict | None = None,
    ci: dict | None = None,
    history: Iterable[dict | Iterable[str]] = (),
    reviewer_load: dict[str, int] | None = None,
) -> dict:
    files = tuple(changed_files)
    memory = change_memory(files, history)
    return {
        "change_memory": memory,
        "impact_graph": impact_graph(audit, files, memory),
        "ci_plan": ci_plan(audit),
        "review_freshness": review_freshness(audit, pull, ci),
        "blast_radius": blast_radius(audit, files, memory),
        "split_plan": split_plan(audit, memory),
        "reviewer_router": reviewer_router(audit, reviewer_load),
    }


def intelligence_markdown(data: dict) -> str:
    blast = data["blast_radius"]
    freshness = data["review_freshness"]
    memory = data["change_memory"]
    lines = [
        "## QNode review intelligence",
        "",
        f"- **Blast radius:** {blast['score']}/100 ({blast['level']}); path-metadata heuristic.",
        f"- **Review freshness:** {freshness['status']}; not an approval decision.",
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
    lines.extend(
        [
            "",
            "_All relationships are filename, history, ownership, policy, and check metadata. "
            "They do not prove code dependencies, test coverage, reviewer availability, or "
            "defects._",
        ]
    )
    return "\n".join(lines)
