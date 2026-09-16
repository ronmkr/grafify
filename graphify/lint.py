"""Deterministic lint and drift rules (Phase 11).

Deterministic, model-free rules:
1. Unpinned GitHub Actions: flag action references not pinned to a 40-char commit SHA.
2. Environment drift: flag resources defined in one environment (e.g. staging) but missing in another (prod).
3. Missing secret/env definitions: flag secrets/envs referenced in code or config but never defined.
4. Dangling references & orphan nodes: report unresolvable edges and isolated entities.
5. Explicit reverse backlink edges: store backlinks for O(1) "what links here" queries.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import networkx as nx

from graphify.cross_resolve import find_secret_and_env_cross_references

_ENV_NAMES = frozenset({
    "dev", "development",
    "staging", "stage",
    "prod", "production",
    "test", "qa", "uat",
})


def _detect_env_from_path(path_str: str) -> str | None:
    """Extract environment name (staging, prod, dev, etc.) from a file path."""
    parts = Path(path_str.replace("\\", "/")).parts
    for part in parts:
        lower_p = part.lower()
        if lower_p in _ENV_NAMES:
            return lower_p
        for env in _ENV_NAMES:
            if lower_p.startswith(f"{env}-") or lower_p.endswith(f"-{env}") or lower_p == env:
                return env
    return None


def check_unpinned_actions(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag GitHub Actions references that are not pinned to a 40-character commit SHA."""
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()

    for n in nodes:
        if n.get("type") == "action" or n.get("label", "").startswith("Action:"):
            act_name = n.get("action_name") or n.get("label", "").replace("Action:", "")
            pin = n.get("pinned_version", "")
            is_sha = n.get("is_sha_pinned", False)
            if not is_sha and pin:
                is_sha = bool(re.match(r"^[0-9a-fA-F]{40}$", pin))

            if not is_sha:
                key = f"{act_name}@{pin}"
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "rule": "unpinned_github_action",
                        "severity": "warning",
                        "action": act_name,
                        "pin": pin or "unversioned",
                        "source_file": n.get("source_file", ""),
                        "source_location": n.get("source_location", "L1"),
                        "message": (
                            f"GitHub Action '{act_name}' is pinned to '{pin or 'unversioned'}', "
                            f"not a 40-character commit SHA."
                        ),
                    })

    # Also inspect edge pinned_version markers
    for e in edges:
        if e.get("relation") == "uses_action":
            pin = e.get("pinned_version", "")
            is_sha = e.get("is_sha_pinned", False)
            if pin and not is_sha and not re.match(r"^[0-9a-fA-F]{40}$", pin):
                tgt = str(e.get("target", ""))
                if tgt not in seen:
                    seen.add(tgt)
                    findings.append({
                        "rule": "unpinned_github_action",
                        "severity": "warning",
                        "action": tgt,
                        "pin": pin,
                        "source_file": e.get("source_file", ""),
                        "source_location": e.get("source_location", "L1"),
                        "message": f"Action invocation target '{tgt}' uses unpinned pin '{pin}'.",
                    })

    return findings


def check_environment_drift(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag resources defined in one environment (e.g. staging) missing from another (e.g. prod)."""
    findings: list[dict[str, Any]] = []

    # Map: env -> dict[resource_identifier, node]
    env_resources: dict[str, dict[str, dict[str, Any]]] = {}

    for n in nodes:
        sf = n.get("source_file", "")
        if not sf:
            continue
        env = _detect_env_from_path(sf)
        if not env:
            continue

        res_key = n.get("resource_name") or n.get("label", "")
        if not res_key or n.get("type") in ("file", "package"):
            continue

        # Canonical identifier: resource type + simple name (stripped of env prefix/suffix)
        clean_name = re.sub(rf"[-_]{env}|{env}[-_]", "", str(res_key), flags=re.IGNORECASE)
        rtype = n.get("resource_kind") or n.get("resource_type") or n.get("type") or "resource"
        norm_id = f"{rtype}::{clean_name.lower()}"

        env_resources.setdefault(env, {})[norm_id] = n

    envs = sorted(env_resources.keys())
    # Compare staging vs prod or pairs of envs
    if "staging" in env_resources and "prod" in env_resources:
        pairs = [("staging", "prod")]
    elif len(envs) >= 2:
        pairs = [(envs[0], envs[1])]
    else:
        pairs = []

    for env_a, env_b in pairs:
        res_a = env_resources[env_a]
        res_b = env_resources[env_b]

        # Present in A but missing in B
        for rid, node_a in res_a.items():
            if rid not in res_b:
                findings.append({
                    "rule": "environment_drift",
                    "severity": "warning",
                    "resource": rid,
                    "present_in": env_a,
                    "missing_in": env_b,
                    "source_file": node_a.get("source_file", ""),
                    "message": f"Resource '{rid}' defined in environment '{env_a}' is missing in '{env_b}'.",
                })

        # Present in B but missing in A
        for rid, node_b in res_b.items():
            if rid not in res_a:
                findings.append({
                    "rule": "environment_drift",
                    "severity": "warning",
                    "resource": rid,
                    "present_in": env_b,
                    "missing_in": env_a,
                    "source_file": node_b.get("source_file", ""),
                    "message": f"Resource '{rid}' defined in environment '{env_b}' is missing in '{env_a}'.",
                })

    return findings


def check_missing_secrets_and_envs(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flag secrets or environment variables referenced in code/config but never defined."""
    findings: list[dict[str, Any]] = []
    ref_data = find_secret_and_env_cross_references(nodes, edges)

    for sec in ref_data["secrets"]["missing"]:
        findings.append({
            "rule": "missing_secret_definition",
            "severity": "error",
            "name": sec,
            "message": f"Secret '{sec}' is referenced in configuration/code but has no matching secret definition.",
        })

    for ev in ref_data["envs"]["missing"]:
        findings.append({
            "rule": "missing_env_definition",
            "severity": "warning",
            "name": ev,
            "message": f"Environment variable '{ev}' is referenced but not declared in any ConfigMap or environment specification.",
        })

    return findings


def check_dangling_and_orphans(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Report dangling edge targets and orphan nodes."""
    findings: list[dict[str, Any]] = []
    node_ids = {str(n.get("id")) for n in nodes if "id" in n}

    connected_nodes: set[str] = set()

    for e in edges:
        src = str(e.get("source", ""))
        tgt = str(e.get("target", ""))
        rel = str(e.get("relation", ""))

        if src not in node_ids:
            findings.append({
                "rule": "dangling_reference",
                "severity": "error",
                "endpoint": "source",
                "node_id": src,
                "relation": rel,
                "source_file": e.get("source_file", ""),
                "message": f"Edge references nonexistent source node '{src}'.",
            })
        else:
            connected_nodes.add(src)

        if tgt not in node_ids:
            findings.append({
                "rule": "dangling_reference",
                "severity": "error",
                "endpoint": "target",
                "node_id": tgt,
                "relation": rel,
                "source_file": e.get("source_file", ""),
                "message": f"Edge references nonexistent target node '{tgt}'.",
            })
        else:
            connected_nodes.add(tgt)

    for n in nodes:
        nid = str(n.get("id", ""))
        if nid and nid not in connected_nodes:
            findings.append({
                "rule": "orphan_node",
                "severity": "info",
                "node_id": nid,
                "label": n.get("label", nid),
                "source_file": n.get("source_file", ""),
                "message": f"Node '{n.get('label', nid)}' is an orphan with no connections.",
            })

    return findings


def add_explicit_backlink_edges(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Store explicit reverse backlink edges for O(1) 'what links here' traversal.

    For every forward edge (u -> v, relation=R), emits a reverse edge
    (v -> u, relation=backlink:R, is_backlink=True).
    """
    seen: set[tuple[str, str, str]] = {
        (str(e.get("source")), str(e.get("target")), str(e.get("relation")))
        for e in edges
    }
    backlinks: list[dict[str, Any]] = []

    for e in edges:
        if e.get("is_backlink"):
            continue
        src = str(e.get("source", ""))
        tgt = str(e.get("target", ""))
        rel = str(e.get("relation", ""))
        rev_rel = f"backlink:{rel}"

        key = (tgt, src, rev_rel)
        if key not in seen:
            seen.add(key)
            backlink_edge = {
                "source": tgt,
                "target": src,
                "relation": rev_rel,
                "forward_relation": rel,
                "is_backlink": True,
                "confidence": e.get("confidence", "EXTRACTED"),
                "weight": e.get("weight", 1.0),
                "source_file": e.get("source_file", ""),
                "source_location": e.get("source_location", "L1"),
            }
            backlinks.append(backlink_edge)

    return edges + backlinks


def run_lint(
    graph_or_extraction: nx.Graph | dict[str, Any],
    check_orphans: bool = True,
) -> dict[str, Any]:
    """Execute all deterministic lint and drift rules against a graph or extraction dict.

    Returns structured findings and a summary with error/warning counts.
    """
    if isinstance(graph_or_extraction, nx.Graph):
        nodes = [
            {"id": n, **attrs} for n, attrs in graph_or_extraction.nodes(data=True)
        ]
        edges = [
            {"source": u, "target": v, **attrs}
            for u, v, attrs in graph_or_extraction.edges(data=True)
        ]
    else:
        nodes = graph_or_extraction.get("nodes", [])
        edges = graph_or_extraction.get("edges", [])

    findings: list[dict[str, Any]] = []

    # 1. Unpinned GitHub Actions
    findings.extend(check_unpinned_actions(nodes, edges))

    # 2. Environment Drift
    findings.extend(check_environment_drift(nodes))

    # 3. Missing Secrets and Envs
    findings.extend(check_missing_secrets_and_envs(nodes, edges))

    # 4. Dangling edges & orphan nodes
    if check_orphans:
        findings.extend(check_dangling_and_orphans(nodes, edges))

    errors = sum(1 for f in findings if f.get("severity") == "error")
    warnings = sum(1 for f in findings if f.get("severity") == "warning")
    info = sum(1 for f in findings if f.get("severity") == "info")

    return {
        "status": "failed" if errors > 0 else ("warning" if warnings > 0 else "passed"),
        "findings": findings,
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "info": info,
            "total": len(findings),
        },
    }
