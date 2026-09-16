"""Execution Flow Slicing & Entry-to-Sink Tracing (GitNexus feature).

Traces execution flow from entry points (HTTP routes, gRPC RPCs, CLI entry points,
event consumers) forward through calls, references, imports, and dependencies to
terminal data sinks (SQL tables, Redis cache, Kafka topics, external HTTP endpoints),
identifying intermediary services, middleware, and execution paths.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Iterable
import unicodedata

import networkx as nx

FORWARD_RELATIONS = frozenset({
    "calls",
    "indirect_call",
    "references",
    "imports",
    "imports_from",
    "depends_on",
    "uses",
    "dynamic_import",
    "routes_to",
    "handles",
    "sends_to",
    "publishes_to",
    "subscribes_to",
    "writes_to",
    "reads_from",
    "queries",
    "mutates",
})

ENTRY_POINT_CATEGORIES = frozenset({"route", "rpc", "cli", "consumer"})
TERMINAL_SINK_CATEGORIES = frozenset({"database", "cache", "queue", "external_api"})
INTERMEDIARY_CATEGORIES = frozenset({"middleware", "service", "controller", "function", "module"})


def _normalize(text: str) -> str:
    """Normalize string for fuzzy/case-insensitive matching."""
    return unicodedata.normalize("NFC", text).strip().casefold()


def _bare_name(label: str) -> str:
    """Remove callable decoration or method suffixes."""
    norm = _normalize(label)
    return norm[:-2] if norm.endswith("()") else norm


def classify_node(data: dict[str, Any], node_id: str = "") -> tuple[str, str]:
    """Classify a node into its execution category and display tag.

    Returns:
        tuple of (category, tag), e.g. ('route', 'Route'), ('database', 'DB')
    """
    raw_label = str(data.get("label") or node_id)
    label_lower = raw_label.lower()
    nid_lower = str(node_id).lower()
    node_type = str(
        data.get("node_type")
        or data.get("kind")
        or data.get("type")
        or data.get("category")
        or ""
    ).lower()
    source_file = str(data.get("source_file") or "").lower()

    # 1. Terminal Data Sinks
    # Cache (Redis, Memcached)
    if node_type in {"cache", "redis", "memcached"} or any(
        w in label_lower for w in ("redis", "memcached", "cache")
    ):
        return "cache", "Cache"

    # Queue / Event streaming (Kafka, RabbitMQ, SQS, pubsub)
    if (
        node_type in {"kafka_topic", "topic", "queue", "kafka", "rabbitmq", "sqs", "pubsub"}
        or "kafka" in label_lower
        or "topic" in label_lower
        or "queue" in label_lower
        or "rabbitmq" in label_lower
        or "sqs" in label_lower
        or nid_lower.startswith("kafka_")
    ):
        return "queue", "Queue"

    # External HTTP endpoints / 3rd party APIs
    if (
        node_type in {"external_api", "external_http", "external", "webhook", "remote_service"}
        or label_lower.startswith("http://")
        or label_lower.startswith("https://")
        or nid_lower.startswith("http://")
        or nid_lower.startswith("https://")
        or "webhook" in label_lower
        or "external:" in label_lower
    ):
        return "external_api", "External"

    # Database / SQL Tables
    if (
        node_type in {"table", "sql_table", "database", "db", "sql", "repository", "entity", "model"}
        or source_file.endswith(".sql")
        or nid_lower.startswith("sql_table_")
        or nid_lower.startswith("table_")
        or label_lower.endswith(" table")
        or " table" in label_lower
        or label_lower.endswith("_table")
        or label_lower.startswith("table:")
        or label_lower.startswith("db:")
        or any(
            keyword in label_lower
            for keyword in ("database", "postgres", "mysql", "sqlite", "mongodb", "dynamodb")
        )
    ):
        return "database", "DB"

    # 2. Entry Points
    # HTTP Routes
    http_verbs = ("get ", "post ", "put ", "delete ", "patch ", "head ", "options ")
    if (
        node_type in {"route", "endpoint", "http_route", "api_endpoint", "api", "rest_endpoint"}
        or label_lower.startswith(http_verbs)
        or any(label_lower.startswith(f"route:{v}") for v in http_verbs)
        or "route:" in label_lower
        or label_lower.startswith("route ")
        or data.get("http_method") is not None
        or data.get("http_route") is not None
        or data.get("http_path") is not None
    ):
        return "route", "Route"

    # gRPC RPCs
    if (
        node_type in {"rpc", "grpc", "grpc_rpc", "grpc_service"}
        or label_lower.startswith("rpc:")
        or label_lower.startswith("rpc ")
        or "grpc" in label_lower
        or data.get("rpc_method") is not None
        or data.get("rpc_service") is not None
    ):
        return "rpc", "RPC"

    # CLI Entry Points
    if (
        node_type in {"cli", "cli_command", "command", "entry", "entry_point"}
        or label_lower.startswith("cli:")
        or label_lower.startswith("cmd:")
        or label_lower in {"main", "main()", "run()", "cli()"}
        or "click.command" in label_lower
        or "app.command" in label_lower
    ):
        return "cli", "CLI"

    # Event Consumers
    if (
        node_type in {"consumer", "event_consumer", "listener", "subscriber", "kafka_consumer", "sqs_consumer", "worker", "job"}
        or any(w in label_lower for w in ("consumer", "listener", "subscriber", "on_message", "handle_event"))
    ):
        return "consumer", "Consumer"

    # 3. Intermediaries
    # Middleware
    if (
        node_type in {"middleware", "interceptor", "filter", "guard"}
        or any(w in label_lower for w in ("middleware", "interceptor", "filter", "guard", "cors"))
    ):
        return "middleware", "Middleware"

    # Controllers / Handlers
    if (
        node_type in {"controller", "handler"}
        or any(w in label_lower for w in ("controller", "handler"))
    ):
        return "controller", "Controller"

    # Services / Managers / Processors
    if (
        node_type in {"service", "manager", "processor", "usecase"}
        or any(w in label_lower for w in ("service", "manager", "processor", "usecase"))
    ):
        return "service", "Service"

    # Modules / Files
    if node_type in {"module", "file"} or (source_file and raw_label == Path(source_file).name):
        return "module", "Module"

    # General Functions / Callables
    return "function", "Function"


def _ensure_digraph(graph: Any) -> nx.DiGraph:
    """Ensure the input graph is a directed NetworkX graph with node attributes."""
    if isinstance(graph, (str, Path)):
        from graphify.affected import load_graph
        graph = load_graph(Path(graph))
    elif isinstance(graph, dict):
        from networkx.readwrite import json_graph
        raw = dict(graph, directed=True)
        if "links" not in raw and "edges" in raw:
            raw["links"] = raw["edges"]
        graph = json_graph.node_link_graph(raw, edges="links")

    if hasattr(graph, "is_directed") and graph.is_directed():
        return graph

    # Undirected NetworkX graph: build DiGraph respecting _src / _tgt markers
    dg = nx.DiGraph()
    for n, data in graph.nodes(data=True):
        dg.add_node(n, **data)
    for u, v, data in graph.edges(data=True):
        src = data.get("_src", u)
        tgt = data.get("_tgt", v)
        dg.add_edge(src, tgt, **data)
    return dg


def resolve_entry_points(graph: nx.DiGraph, query: str) -> list[str]:
    """Resolve entry point query to matching node IDs in the graph.

    Supports:
    - Exact node ID
    - Exact label match (case-insensitive)
    - Route / RPC / CLI / Consumer pattern matching
    - Bare name matching (without '()')
    - Substring matching with entry-point category boosting
    """
    query = query.strip()
    if not query:
        return []

    # 1. Exact node ID
    if query in graph:
        return [query]

    query_norm = _normalize(query)
    query_bare = _bare_name(query_norm)

    # 2. Exact label match
    exact_label = [
        str(nid)
        for nid, d in graph.nodes(data=True)
        if _normalize(str(d.get("label", ""))) == query_norm
    ]
    if exact_label:
        return exact_label

    # 3. Bare label match
    bare_label = [
        str(nid)
        for nid, d in graph.nodes(data=True)
        if _bare_name(str(d.get("label", ""))) == query_bare
    ]
    if bare_label:
        return bare_label

    # 4. HTTP route special matching: e.g. path match or verb+path
    parts = query_norm.split(maxsplit=1)
    if len(parts) == 2 and parts[0] in {"get", "post", "put", "delete", "patch", "head", "options"}:
        method, route_path = parts[0].upper(), parts[1]
        route_matches = []
        for nid, d in graph.nodes(data=True):
            lbl = _normalize(str(d.get("label", "")))
            if lbl == f"{method.lower()} {route_path}" or (
                d.get("http_method") == method and str(d.get("http_route") or d.get("http_path") or "") == route_path
            ):
                route_matches.append(str(nid))
        if route_matches:
            return route_matches

    # 5. Scored substring / token matching, prioritizing entry points
    candidates: list[tuple[int, str]] = []
    for nid, d in graph.nodes(data=True):
        lbl_norm = _normalize(str(d.get("label", "")))
        nid_norm = _normalize(str(nid))
        cat, _tag = classify_node(d, str(nid))
        score = 0

        is_ep = cat in ENTRY_POINT_CATEGORIES
        if is_ep:
            score += 100

        if query_norm in lbl_norm or query_norm in nid_norm:
            if lbl_norm == query_norm or nid_norm == query_norm:
                score += 50
            elif lbl_norm.startswith(query_norm) or nid_norm.startswith(query_norm):
                score += 30
            else:
                score += 10
            candidates.append((score, str(nid)))
        elif query_bare and (query_bare in _bare_name(lbl_norm) or query_bare in nid_norm):
            score += 15
            candidates.append((score, str(nid)))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        top_score = candidates[0][0]
        # Return all candidates that share the top score (or top tier)
        return [nid for score, nid in candidates if score == top_score]

    return []


def resolve_sinks(graph: nx.DiGraph, query: str) -> list[str]:
    """Resolve sink query to matching terminal sink node IDs in the graph."""
    query = query.strip()
    if not query:
        return []

    if query in graph:
        return [query]

    query_norm = _normalize(query)
    query_bare = _bare_name(query_norm)

    # Exact label
    exact_label = [
        str(nid)
        for nid, d in graph.nodes(data=True)
        if _normalize(str(d.get("label", ""))) == query_norm
    ]
    if exact_label:
        return exact_label

    candidates: list[tuple[int, str]] = []
    for nid, d in graph.nodes(data=True):
        lbl_norm = _normalize(str(d.get("label", "")))
        nid_norm = _normalize(str(nid))
        cat, _tag = classify_node(d, str(nid))
        score = 0

        if cat in TERMINAL_SINK_CATEGORIES:
            score += 100

        if query_norm in lbl_norm or query_norm in nid_norm or query_bare in _bare_name(lbl_norm):
            if lbl_norm == query_norm or nid_norm == query_norm:
                score += 50
            elif lbl_norm.startswith(query_norm):
                score += 25
            else:
                score += 10
            candidates.append((score, str(nid)))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        top_score = candidates[0][0]
        return [nid for score, nid in candidates if score == top_score]

    return []


def _expand_entry_members(graph: nx.DiGraph, seeds: Iterable[str]) -> set[str]:
    """Expand entry point seeds to include member methods/handlers."""
    expanded = set(seeds)
    for s in seeds:
        for _src, tgt, d in graph.out_edges(s, data=True):
            rel = str(d.get("relation", "")).lower()
            if rel in ("method", "contains"):
                expanded.add(str(tgt))
    return expanded


def _build_step(graph: nx.DiGraph, node_id: str) -> dict[str, Any]:
    """Construct a step dictionary for a node in an execution path."""
    data = graph.nodes[node_id]
    category, tag = classify_node(data, node_id)
    return {
        "id": node_id,
        "label": str(data.get("label") or node_id),
        "tag": tag,
        "category": category,
        "source_file": data.get("source_file"),
        "source_location": data.get("source_location"),
    }


def trace_execution_flow(
    graph: Any,
    entry_point: str,
    sink: str | None = None,
    max_depth: int = 15,
) -> dict[str, Any]:
    """Trace execution flow from entry point to terminal sinks.

    Args:
        graph: NetworkX graph, dict, or path to graph.json
        entry_point: Identifier, label, or pattern for the entry point
        sink: Optional target sink identifier, label, or pattern
        max_depth: Maximum execution path depth (default 15)

    Returns:
        dict containing resolved entry points, sinks, paths, intermediaries, and diagram
    """
    g = _ensure_digraph(graph)
    resolved_eps = resolve_entry_points(g, entry_point)

    if not resolved_eps:
        return {
            "entry_point": entry_point,
            "resolved_entry_points": [],
            "sink": sink,
            "resolved_sinks": [],
            "paths": [],
            "intermediaries": [],
            "terminal_sinks": [],
            "diagram": f"No matching entry point found for '{entry_point}'.",
        }

    resolved_sinks = resolve_sinks(g, sink) if sink else []

    # Filter graph to forward execution relations
    flow_g = nx.DiGraph()
    for n, d in g.nodes(data=True):
        flow_g.add_node(n, **d)

    for u, v, d in g.edges(data=True):
        rel = str(d.get("relation") or d.get("type") or d.get("kind") or "").lower()
        if not rel or rel in FORWARD_RELATIONS:
            flow_g.add_edge(u, v, **d)

    paths: list[list[dict[str, Any]]] = []
    seen_path_signatures: set[tuple[str, ...]] = set()

    # If sink is specified, find paths reaching the target sink(s)
    if sink:
        if not resolved_sinks:
            return {
                "entry_point": entry_point,
                "resolved_entry_points": resolved_eps,
                "sink": sink,
                "resolved_sinks": [],
                "paths": [],
                "intermediaries": [],
                "terminal_sinks": [],
                "diagram": f"No matching sink found for '{sink}'.",
            }

        # Expand entry points to include contained methods if needed
        all_sources = _expand_entry_members(g, resolved_eps)

        for src in all_sources:
            for tgt in resolved_sinks:
                try:
                    for p in nx.all_simple_paths(flow_g, source=src, target=tgt, cutoff=max_depth):
                        # Prepend original entry point if started from an expanded member
                        full_p = list(p)
                        if src not in resolved_eps:
                            for orig_ep in resolved_eps:
                                if g.has_edge(orig_ep, src):
                                    full_p = [orig_ep] + full_p
                                    break
                        sig = tuple(full_p)
                        if sig not in seen_path_signatures:
                            seen_path_signatures.add(sig)
                            paths.append([_build_step(g, nid) for nid in full_p])
                            if len(paths) >= 50:
                                break
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue
                if len(paths) >= 50:
                    break
            if len(paths) >= 50:
                break
    else:
        # Sink not specified: trace forward paths to terminal sinks or leaf nodes
        # Depth-bounded DFS to collect all execution flows
        for ep in resolved_eps:
            queue: deque[tuple[str, list[str]]] = deque([(ep, [ep])])
            while queue:
                current, curr_path = queue.pop()
                cat, _tag = classify_node(g.nodes[current], current)

                # Stop path if current node is a data sink (and not the entry point itself)
                if len(curr_path) > 1 and cat in TERMINAL_SINK_CATEGORIES:
                    sig = tuple(curr_path)
                    if sig not in seen_path_signatures:
                        seen_path_signatures.add(sig)
                        paths.append([_build_step(g, nid) for nid in curr_path])
                    continue

                if len(curr_path) >= max_depth:
                    sig = tuple(curr_path)
                    if sig not in seen_path_signatures:
                        seen_path_signatures.add(sig)
                        paths.append([_build_step(g, nid) for nid in curr_path])
                    continue

                # Explore outgoing forward execution edges
                successors = [
                    v for v in flow_g.successors(current)
                    if v not in curr_path
                ]

                if not successors:
                    # Leaf reached
                    sig = tuple(curr_path)
                    if sig not in seen_path_signatures:
                        seen_path_signatures.add(sig)
                        paths.append([_build_step(g, nid) for nid in curr_path])
                    continue

                for succ in successors:
                    queue.append((succ, curr_path + [succ]))
                    if len(queue) > 500:  # Safeguard against huge breadth
                        break

                if len(paths) >= 50:
                    break

    # Collect unique intermediaries and terminal sinks reached across all paths
    intermediaries_dict: dict[str, dict[str, Any]] = {}
    terminal_sinks_dict: dict[str, dict[str, Any]] = {}

    for p in paths:
        for i, step in enumerate(p):
            nid = step["id"]
            cat = step["category"]
            if i == 0 and cat in ENTRY_POINT_CATEGORIES:
                continue
            if cat in TERMINAL_SINK_CATEGORIES:
                terminal_sinks_dict[nid] = step
            elif cat in INTERMEDIARY_CATEGORIES or (i > 0 and i < len(p) - 1):
                intermediaries_dict[nid] = step
            elif i == len(p) - 1:
                # Terminal node of path
                terminal_sinks_dict[nid] = step

    result = {
        "entry_point": entry_point,
        "resolved_entry_points": resolved_eps,
        "sink": sink,
        "resolved_sinks": resolved_sinks if sink else list(terminal_sinks_dict.keys()),
        "paths": paths,
        "intermediaries": list(intermediaries_dict.values()),
        "terminal_sinks": list(terminal_sinks_dict.values()),
    }
    result["diagram"] = format_flow_diagram(result)
    return result


def format_flow_diagram(flow_data: dict[str, Any]) -> str:
    """Generate an ASCII sequence / execution trace diagram showing flow steps.

    Example output:
        [Route: POST /login] -> [Service: AuthService.authenticate] -> [DB: users table]
    """
    paths = flow_data.get("paths", [])
    if not paths:
        sink = flow_data.get("sink")
        ep = flow_data.get("entry_point", "")
        if sink:
            return f"No execution path found from '{ep}' to sink '{sink}'."
        return f"No execution flow found for '{ep}'."

    lines: list[str] = []
    for i, path in enumerate(paths, 1):
        chain = " -> ".join(f"[{step['tag']}: {step['label']}]" for step in path)
        if len(paths) > 1:
            lines.append(f"Path {i}: {chain}")
        else:
            lines.append(chain)

    return "\n".join(lines)
