"""Tests for Execution Flow Slicing & Entry-to-Sink Tracing (graphify.flow, cli, mcp)."""
from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph
import pytest

import graphify.__main__ as mainmod
from graphify.flow import (
    classify_node,
    format_flow_diagram,
    resolve_entry_points,
    resolve_sinks,
    trace_execution_flow,
)
from graphify.mcp import TOOL_SPEC, get_execution_flow


def _create_sample_graph() -> nx.DiGraph:
    """Create a sample microservices graph with routes, services, middleware, and sinks."""
    G = nx.DiGraph()

    # Entry points
    G.add_node(
        "route_login",
        label="POST /login",
        node_type="route",
        source_file="api/auth.py",
        source_location="L10",
    )
    G.add_node(
        "route_users",
        label="GET /users",
        node_type="route",
        source_file="api/users.py",
        source_location="L20",
    )
    G.add_node(
        "rpc_get_user",
        label="UserService/GetUser",
        node_type="rpc",
        source_file="proto/user.proto",
        source_location="L5",
    )
    G.add_node(
        "cli_deploy",
        label="cli:deploy",
        node_type="cli",
        source_file="cli/deploy.py",
        source_location="L1",
    )
    G.add_node(
        "consumer_orders",
        label="OrderCreatedConsumer",
        node_type="consumer",
        source_file="workers/order_worker.py",
        source_location="L15",
    )

    # Intermediaries
    G.add_node(
        "mw_auth",
        label="AuthMiddleware",
        node_type="middleware",
        source_file="middleware/auth.py",
        source_location="L5",
    )
    G.add_node(
        "svc_auth",
        label="AuthService.authenticate",
        node_type="service",
        source_file="services/auth.py",
        source_location="L30",
    )
    G.add_node(
        "svc_order",
        label="OrderService.process",
        node_type="service",
        source_file="services/order.py",
        source_location="L40",
    )
    G.add_node(
        "ctrl_user",
        label="UserController.show",
        node_type="controller",
        source_file="controllers/user.py",
        source_location="L12",
    )

    # Terminal Data Sinks
    G.add_node(
        "db_users",
        label="users table",
        node_type="table",
        source_file="db/schema.sql",
        source_location="L100",
    )
    G.add_node(
        "cache_redis",
        label="redis_session_cache",
        node_type="cache",
        source_file="infra/redis.py",
        source_location="L8",
    )
    G.add_node(
        "kafka_topic_orders",
        label="Kafka: orders_topic",
        node_type="kafka_topic",
        source_file="infra/kafka.py",
        source_location="L2",
    )
    G.add_node(
        "ext_stripe",
        label="https://api.stripe.com/v1/charges",
        node_type="external_api",
        source_file="integrations/stripe.py",
        source_location="L50",
    )

    # Edges (flow relations)
    # Flow 1: POST /login -> AuthMiddleware -> AuthService.authenticate -> users table
    #                                                                   -> redis_session_cache
    G.add_edge("route_login", "mw_auth", relation="calls")
    G.add_edge("mw_auth", "svc_auth", relation="calls")
    G.add_edge("svc_auth", "db_users", relation="queries")
    G.add_edge("svc_auth", "cache_redis", relation="writes_to")

    # Flow 2: GET /users -> UserController.show -> users table
    G.add_edge("route_users", "ctrl_user", relation="calls")
    G.add_edge("ctrl_user", "db_users", relation="queries")

    # Flow 3: UserService/GetUser -> UserController.show
    G.add_edge("rpc_get_user", "ctrl_user", relation="calls")

    # Flow 4: OrderCreatedConsumer -> OrderService.process -> https://api.stripe.com/v1/charges
    G.add_edge("consumer_orders", "svc_order", relation="calls")
    G.add_edge("svc_order", "ext_stripe", relation="calls")

    # Flow 5: cli:deploy -> OrderService.process
    G.add_edge("cli_deploy", "svc_order", relation="calls")

    return G


def _write_graph_file(tmp_path: Path, graph: nx.DiGraph | None = None) -> Path:
    """Serialize graph to temporary graph.json."""
    if graph is None:
        graph = _create_sample_graph()
    graph_path = tmp_path / "graph.json"
    data = json_graph.node_link_data(graph, edges="links")
    data["directed"] = True
    graph_path.write_text(json.dumps(data), encoding="utf-8")
    return graph_path


# --- Classification Tests ---

def test_classify_node_types():
    """Verify nodes are correctly classified into categories and display tags."""
    assert classify_node({"label": "POST /login", "node_type": "route"}) == ("route", "Route")
    assert classify_node({"label": "GET /api/v1/items"}) == ("route", "Route")
    assert classify_node({"label": "UserService/GetUser", "node_type": "rpc"}) == ("rpc", "RPC")
    assert classify_node({"label": "cli:backup", "node_type": "cli"}) == ("cli", "CLI")
    assert classify_node({"label": "main()"}) == ("cli", "CLI")
    assert classify_node({"label": "OrderConsumer", "node_type": "consumer"}) == ("consumer", "Consumer")

    assert classify_node({"label": "AuthGuard", "node_type": "middleware"}) == ("middleware", "Middleware")
    assert classify_node({"label": "UserController", "node_type": "controller"}) == ("controller", "Controller")
    assert classify_node({"label": "AuthService.authenticate", "node_type": "service"}) == ("service", "Service")

    assert classify_node({"label": "users table", "node_type": "table"}) == ("database", "DB")
    assert classify_node({"label": "orders", "source_file": "db.sql"}) == ("database", "DB")
    assert classify_node({"label": "redis_cache", "node_type": "cache"}) == ("cache", "Cache")
    assert classify_node({"label": "Kafka: orders_topic", "node_type": "kafka_topic"}) == ("queue", "Queue")
    assert classify_node({"label": "https://api.stripe.com/charges"}) == ("external_api", "External")


# --- Resolution Tests ---

def test_resolve_entry_points():
    """Verify entry point query resolution."""
    G = _create_sample_graph()
    assert resolve_entry_points(G, "route_login") == ["route_login"]
    assert resolve_entry_points(G, "POST /login") == ["route_login"]
    assert resolve_entry_points(G, "post /login") == ["route_login"]
    assert resolve_entry_points(G, "GET /users") == ["route_users"]
    assert resolve_entry_points(G, "UserService/GetUser") == ["rpc_get_user"]
    assert resolve_entry_points(G, "cli:deploy") == ["cli_deploy"]
    assert resolve_entry_points(G, "OrderCreatedConsumer") == ["consumer_orders"]
    assert resolve_entry_points(G, "nonexistent_entry") == []


def test_resolve_sinks():
    """Verify terminal sink query resolution."""
    G = _create_sample_graph()
    assert resolve_sinks(G, "db_users") == ["db_users"]
    assert resolve_sinks(G, "users table") == ["db_users"]
    assert resolve_sinks(G, "users") == ["db_users"]
    assert resolve_sinks(G, "redis_session_cache") == ["cache_redis"]
    assert resolve_sinks(G, "orders_topic") == ["kafka_topic_orders"]
    assert resolve_sinks(G, "stripe") == ["ext_stripe"]
    assert resolve_sinks(G, "nonexistent_sink") == []


# --- Trace Execution Flow Tests ---

def test_trace_execution_flow_linear():
    """Verify tracing execution flow with single entry to sink."""
    G = nx.DiGraph()
    G.add_node("r1", label="POST /login", node_type="route")
    G.add_node("s1", label="AuthService.authenticate", node_type="service")
    G.add_node("d1", label="users table", node_type="table")
    G.add_edge("r1", "s1", relation="calls")
    G.add_edge("s1", "d1", relation="queries")

    flow = trace_execution_flow(G, "POST /login")
    assert flow["resolved_entry_points"] == ["r1"]
    assert len(flow["paths"]) == 1

    path = flow["paths"][0]
    assert len(path) == 3
    assert path[0]["label"] == "POST /login"
    assert path[0]["tag"] == "Route"
    assert path[1]["label"] == "AuthService.authenticate"
    assert path[1]["tag"] == "Service"
    assert path[2]["label"] == "users table"
    assert path[2]["tag"] == "DB"

    diagram = format_flow_diagram(flow)
    assert diagram == "[Route: POST /login] -> [Service: AuthService.authenticate] -> [DB: users table]"


def test_trace_execution_flow_with_middleware_and_branching():
    """Verify tracing execution with middleware and multiple terminal sinks."""
    G = _create_sample_graph()
    flow = trace_execution_flow(G, "POST /login")

    assert flow["resolved_entry_points"] == ["route_login"]
    # Should trace paths to both users table and redis cache
    assert len(flow["paths"]) == 2

    labels_in_paths = [[s["label"] for s in p] for p in flow["paths"]]
    expected_path_db = [
        "POST /login",
        "AuthMiddleware",
        "AuthService.authenticate",
        "users table",
    ]
    expected_path_cache = [
        "POST /login",
        "AuthMiddleware",
        "AuthService.authenticate",
        "redis_session_cache",
    ]

    assert expected_path_db in labels_in_paths
    assert expected_path_cache in labels_in_paths

    # Check intermediaries and sinks identified
    inter_labels = {item["label"] for item in flow["intermediaries"]}
    sink_labels = {item["label"] for item in flow["terminal_sinks"]}

    assert "AuthMiddleware" in inter_labels
    assert "AuthService.authenticate" in inter_labels
    assert "users table" in sink_labels
    assert "redis_session_cache" in sink_labels


def test_trace_execution_flow_with_specific_sink():
    """Verify finding specific execution path connecting entry point to targeted sink."""
    G = _create_sample_graph()

    # Request only paths to users table
    flow_db = trace_execution_flow(G, "POST /login", sink="users table")
    assert len(flow_db["paths"]) == 1
    assert flow_db["paths"][0][-1]["label"] == "users table"
    assert "[DB: users table]" in format_flow_diagram(flow_db)
    assert "redis" not in format_flow_diagram(flow_db)

    # Request only paths to redis cache
    flow_cache = trace_execution_flow(G, "POST /login", sink="redis_session_cache")
    assert len(flow_cache["paths"]) == 1
    assert flow_cache["paths"][0][-1]["label"] == "redis_session_cache"
    assert "[Cache: redis_session_cache]" in format_flow_diagram(flow_cache)


def test_trace_execution_flow_unreachable_sink():
    """Verify graceful handling when target sink is not reachable from entry point."""
    G = _create_sample_graph()
    flow = trace_execution_flow(G, "POST /login", sink="Kafka: orders_topic")
    assert len(flow["paths"]) == 0
    assert "No execution path found" in flow["diagram"]


def test_trace_execution_flow_consumer_to_external_api():
    """Verify event consumer flow to external HTTP endpoint."""
    G = _create_sample_graph()
    flow = trace_execution_flow(G, "OrderCreatedConsumer")
    assert len(flow["paths"]) == 1
    diagram = format_flow_diagram(flow)
    assert "[Consumer: OrderCreatedConsumer]" in diagram
    assert "[Service: OrderService.process]" in diagram
    assert "[External: https://api.stripe.com/v1/charges]" in diagram


def test_trace_execution_flow_cycle_prevention():
    """Verify cyclic execution dependencies do not cause infinite recursion."""
    G = nx.DiGraph()
    G.add_node("r1", label="POST /ping", node_type="route")
    G.add_node("s1", label="PingService.a", node_type="service")
    G.add_node("s2", label="PingService.b", node_type="service")
    G.add_node("db1", label="ping_log table", node_type="table")

    G.add_edge("r1", "s1", relation="calls")
    G.add_edge("s1", "s2", relation="calls")
    G.add_edge("s2", "s1", relation="calls")  # Cycle
    G.add_edge("s2", "db1", relation="writes_to")

    flow = trace_execution_flow(G, "POST /ping", max_depth=10)
    assert len(flow["paths"]) >= 1
    diagram = format_flow_diagram(flow)
    assert "[Route: POST /ping]" in diagram
    assert "[DB: ping_log table]" in diagram


def test_trace_execution_flow_from_file_path(tmp_path):
    """Verify trace_execution_flow can load directly from a graph.json file path."""
    graph_path = _write_graph_file(tmp_path)
    flow = trace_execution_flow(str(graph_path), "POST /login")
    assert len(flow["paths"]) == 2


# --- CLI Integration Tests ---

def test_cli_flow_basic(monkeypatch, tmp_path, capsys):
    """Verify graphify flow <entry_point> CLI output."""
    graph_path = _write_graph_file(tmp_path)
    monkeypatch.setattr(mainmod, "_check_skill_version", lambda _: None)
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "flow", "POST /login", "--graph", str(graph_path)],
    )

    mainmod.main()

    out = capsys.readouterr().out
    assert "[Route: POST /login]" in out
    assert "[Service: AuthService.authenticate]" in out
    assert "[DB: users table]" in out


def test_cli_flow_with_sink_filter(monkeypatch, tmp_path, capsys):
    """Verify graphify flow <entry_point> --sink <sink> CLI output."""
    graph_path = _write_graph_file(tmp_path)
    monkeypatch.setattr(mainmod, "_check_skill_version", lambda _: None)
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        [
            "graphify",
            "flow",
            "POST /login",
            "--sink",
            "users table",
            "--graph",
            str(graph_path),
        ],
    )

    mainmod.main()

    out = capsys.readouterr().out
    assert "[Route: POST /login]" in out
    assert "[DB: users table]" in out
    assert "redis_session_cache" not in out


def test_cli_flow_json_output(monkeypatch, tmp_path, capsys):
    """Verify graphify flow --json outputs valid JSON with structured flow data."""
    graph_path = _write_graph_file(tmp_path)
    monkeypatch.setattr(mainmod, "_check_skill_version", lambda _: None)
    monkeypatch.setattr(
        mainmod.sys,
        "argv",
        ["graphify", "flow", "POST /login", "--json", "--graph", str(graph_path)],
    )

    mainmod.main()

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["entry_point"] == "POST /login"
    assert len(data["paths"]) == 2
    assert "intermediaries" in data
    assert "terminal_sinks" in data


def test_cli_flow_missing_args(monkeypatch, capsys):
    """Verify graphify flow with no args prints usage and exits with code 1."""
    monkeypatch.setattr(mainmod, "_check_skill_version", lambda _: None)
    monkeypatch.setattr(mainmod.sys, "argv", ["graphify", "flow"])

    with pytest.raises(SystemExit) as exc:
        mainmod.main()
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "Usage: graphify flow" in err


# --- MCP Tool Tests ---

def test_mcp_get_execution_flow_tool():
    """Verify graphify.mcp.get_execution_flow works via function call and dict."""
    G = _create_sample_graph()

    # Direct function call
    res = get_execution_flow(entry_point="POST /login", graph=G)
    assert isinstance(res, str)
    assert "[Route: POST /login]" in res
    assert "[DB: users table]" in res
    assert len(res.data["paths"]) == 2

    # Arguments dict call (MCP invocation pattern)
    res_dict = get_execution_flow({"entry_point": "POST /login", "graph": G, "sink": "users table"})
    assert isinstance(res_dict, str)
    assert "[DB: users table]" in res_dict
    assert len(res_dict.data["paths"]) == 1

    # Return structured dict directly
    res_raw = get_execution_flow(entry_point="POST /login", graph=G, as_dict=True)
    assert isinstance(res_raw, dict)
    assert "paths" in res_raw


def test_mcp_tool_spec_defined():
    """Verify MCP TOOL_SPEC defines get_execution_flow schema."""
    assert TOOL_SPEC["name"] == "get_execution_flow"
    assert "entry_point" in TOOL_SPEC["inputSchema"]["properties"]
    assert "sink" in TOOL_SPEC["inputSchema"]["properties"]
    assert TOOL_SPEC["inputSchema"]["required"] == ["entry_point"]
