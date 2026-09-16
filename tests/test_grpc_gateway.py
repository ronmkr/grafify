"""Unit tests for Protobuf and gRPC service extractor and OpenAPI gateway cross-referencing."""
from __future__ import annotations

from pathlib import Path

from graph_fy.detect import FileType, classify_file
from graph_fy.extract import _get_extractor
from graph_fy.cross_resolve import resolve_cross_format_dependencies
from graph_fy.extractors.protobuf import (
    extract_protobuf,
    is_protobuf_file,
    parse_google_api_http,
    resolve_grpc_openapi_edges,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _labels(nodes: list[dict]) -> set[str]:
    return {n["label"] for n in nodes}


def _edge_pairs(edges: list[dict], relation: str | None = None) -> set[tuple[str, str, str]]:
    if relation:
        return {(e["source"], e["target"], e["relation"]) for e in edges if e.get("relation") == relation}
    return {(e["source"], e["target"], e["relation"]) for e in edges}


def test_is_protobuf_file():
    assert is_protobuf_file(Path("service.proto")) is True
    assert is_protobuf_file(Path("SERVICE.PROTO")) is True
    assert is_protobuf_file(Path("service.proto.bak")) is False
    assert is_protobuf_file(Path("service.py")) is False


def test_classify_and_extractor_dispatch(tmp_path: Path):
    proto_file = _write(tmp_path, "test.proto", 'syntax = "proto3";\nmessage Ping {}\n')
    assert classify_file(proto_file) == FileType.CODE
    assert _get_extractor(proto_file) == extract_protobuf


def test_parse_google_api_http():
    # 1. Simple GET
    text_get = """
    option (google.api.http) = {
        get: "/v1/users/{id}"
    };
    """
    b_get = parse_google_api_http(text_get)
    assert len(b_get) == 1
    assert b_get[0]["method"] == "GET"
    assert b_get[0]["path"] == "/v1/users/{id}"
    assert b_get[0]["body"] == ""

    # 2. POST with body
    text_post = """
    option (google.api.http) = {
        post: "/v1/orders"
        body: "*"
    };
    """
    b_post = parse_google_api_http(text_post)
    assert len(b_post) == 1
    assert b_post[0]["method"] == "POST"
    assert b_post[0]["path"] == "/v1/orders"
    assert b_post[0]["body"] == "*"

    # 3. Additional bindings
    text_multi = """
    option (google.api.http) = {
        patch: "/v1/users/{id}"
        body: "user"
        additional_bindings {
            put: "/v1/users/{id}"
            body: "*"
        }
        additional_bindings: {
            post: "/v1/users/{id}:deactivate"
            body: ""
        }
    };
    """
    b_multi = parse_google_api_http(text_multi)
    assert len(b_multi) == 3
    assert b_multi[0] == {"method": "PATCH", "path": "/v1/users/{id}", "body": "user"}
    assert b_multi[1] == {"method": "PUT", "path": "/v1/users/{id}", "body": "*"}
    assert b_multi[2] == {"method": "POST", "path": "/v1/users/{id}:deactivate", "body": ""}

    # 4. Flat syntax
    text_flat = """
    option (google.api.http).get = "/v1/items/{item_id}";
    option (google.api.http).body = "item";
    """
    b_flat = parse_google_api_http(text_flat)
    assert len(b_flat) == 1
    assert b_flat[0]["method"] == "GET"
    assert b_flat[0]["path"] == "/v1/items/{item_id}"
    assert b_flat[0]["body"] == "item"

    # 5. Custom method
    text_custom = """
    option (google.api.http) = {
        custom: {
            kind: "HEAD"
            path: "/v1/ping"
        }
    };
    """
    b_custom = parse_google_api_http(text_custom)
    assert len(b_custom) == 1
    assert b_custom[0]["method"] == "HEAD"
    assert b_custom[0]["path"] == "/v1/ping"


def test_extract_protobuf_messages_and_enums(tmp_path: Path):
    proto_content = """syntax = "proto3";
package acme.store.v1;

// Product state enum
enum ProductStatus {
    UNKNOWN = 0;
    ACTIVE = 1;
    DISCONTINUED = 2;
}

message Product {
    string id = 1;
    string title = 2;
    repeated string tags = 3;
    ProductStatus status = 4;
    optional double price = 5;
}
"""
    p = _write(tmp_path, "product.proto", proto_content)
    result = extract_protobuf(p)
    nodes = result["nodes"]
    edges = result["edges"]

    labels = _labels(nodes)
    assert "Proto:Enum:ProductStatus" in labels
    assert "Proto:Message:Product" in labels

    # Check enum node
    enum_node = next(n for n in nodes if n["label"] == "Proto:Enum:ProductStatus")
    assert enum_node["type"] == "proto_enum"
    assert enum_node["enum_name"] == "ProductStatus"
    assert enum_node["package"] == "acme.store.v1"
    assert "ACTIVE" in enum_node["values"]
    assert "DISCONTINUED" in enum_node["values"]

    # Check message node
    msg_node = next(n for n in nodes if n["label"] == "Proto:Message:Product")
    assert msg_node["type"] == "proto_message"
    assert msg_node["message_name"] == "Product"
    assert msg_node["package"] == "acme.store.v1"
    fields = {f["name"]: f for f in msg_node["fields"]}
    assert fields["title"]["type"] == "string"
    assert fields["tags"]["repeated"] is True
    assert fields["price"]["rule"] == "optional"

    # Check containment edges from file
    file_node = next(n for n in nodes if n["type"] == "file")
    contains_edges = {e["target"] for e in edges if e["source"] == file_node["id"] and e["relation"] == "contains"}
    assert enum_node["id"] in contains_edges
    assert msg_node["id"] in contains_edges


def test_extract_protobuf_service_and_rpcs(tmp_path: Path):
    proto_content = """syntax = "proto3";
package acme.user.v1;

message GetUserRequest {
    string user_id = 1;
}

message User {
    string user_id = 1;
    string email = 2;
}

message StreamUsersRequest {
    string role = 1;
}

service UserService {
    rpc GetUser (GetUserRequest) returns (User) {
        option (google.api.http) = {
            get: "/v1/users/{id}"
        };
    }

    rpc StreamUsers (StreamUsersRequest) returns (stream User) {
        option (google.api.http) = {
            get: "/v1/users/stream"
        };
    }

    rpc SimplePing (GetUserRequest) returns (User);
}
"""
    p = _write(tmp_path, "user_service.proto", proto_content)
    result = extract_protobuf(p)
    nodes = result["nodes"]
    edges = result["edges"]

    labels = _labels(nodes)
    assert "Proto:Service:UserService" in labels
    assert "Proto:RPC:UserService.GetUser" in labels
    assert "Proto:RPC:UserService.StreamUsers" in labels
    assert "Proto:RPC:UserService.SimplePing" in labels

    svc_node = next(n for n in nodes if n["label"] == "Proto:Service:UserService")
    assert svc_node["type"] == "proto_service"
    assert svc_node["service_name"] == "UserService"
    assert svc_node["package"] == "acme.user.v1"

    # Check GetUser RPC
    rpc_get = next(n for n in nodes if n["label"] == "Proto:RPC:UserService.GetUser")
    assert rpc_get["type"] == "proto_rpc"
    assert rpc_get["method_name"] == "GetUser"
    assert rpc_get["service_name"] == "UserService"
    assert rpc_get["http_method"] == "GET"
    assert rpc_get["http_route"] == "/v1/users/{id}"
    assert rpc_get["client_streaming"] is False
    assert rpc_get["server_streaming"] is False

    # Check StreamUsers RPC
    rpc_stream = next(n for n in nodes if n["label"] == "Proto:RPC:UserService.StreamUsers")
    assert rpc_stream["client_streaming"] is False
    assert rpc_stream["server_streaming"] is True

    # Check edges
    # Service -> RPC (defines_rpc)
    svc_edges = {(e["source"], e["target"]) for e in edges if e["relation"] == "defines_rpc"}
    assert (svc_node["id"], rpc_get["id"]) in svc_edges
    assert (svc_node["id"], rpc_stream["id"]) in svc_edges

    # RPC -> accepts -> Request message
    req_node = next(n for n in nodes if n["label"] == "Proto:Message:GetUserRequest")
    resp_node = next(n for n in nodes if n["label"] == "Proto:Message:User")
    accepts_edges = {(e["source"], e["target"]) for e in edges if e["relation"] == "accepts"}
    returns_edges = {(e["source"], e["target"]) for e in edges if e["relation"] == "returns"}

    assert (rpc_get["id"], req_node["id"]) in accepts_edges
    assert (rpc_get["id"], resp_node["id"]) in returns_edges


def test_resolve_grpc_openapi_edges():
    # 1. Setup gRPC RPC nodes
    rpc_node_1 = {
        "id": "proto_rpc_user_service_get_user",
        "label": "Proto:RPC:UserService.GetUser",
        "type": "proto_rpc",
        "method_name": "GetUser",
        "service_name": "UserService",
        "http_method": "GET",
        "http_route": "/v1/users/{id}",
        "http_bindings": [{"method": "GET", "path": "/v1/users/{id}", "body": ""}],
    }
    rpc_node_2 = {
        "id": "proto_rpc_user_service_create_user",
        "label": "Proto:RPC:UserService.CreateUser",
        "type": "proto_rpc",
        "method_name": "CreateUser",
        "service_name": "UserService",
        "http_method": "POST",
        "http_route": "/v1/users",
        "http_bindings": [{"method": "POST", "path": "/v1/users", "body": "*"}],
    }
    rpc_node_3 = {
        "id": "proto_rpc_user_service_update_user",
        "label": "Proto:RPC:UserService.UpdateUser",
        "type": "proto_rpc",
        "method_name": "UpdateUser",
        "service_name": "UserService",
        "http_method": "PATCH",
        "http_route": "/v1/users/{user_id}",
        "http_bindings": [
            {"method": "PATCH", "path": "/v1/users/{user_id}", "body": "user"},
            {"method": "PUT", "path": "/v1/users/{user_id}", "body": "*"},
        ],
    }

    # 2. Setup OpenAPI nodes
    op_get = {
        "id": "api_op_get_v1_users_id",
        "label": "API:GET /v1/users/{id}",
        "type": "api_operation",
        "method": "GET",
        "path": "/v1/users/{id}",
    }
    op_post = {
        "id": "api_op_post_v1_users",
        "label": "API:POST /v1/users",
        "type": "api_operation",
        "method": "POST",
        "path": "/v1/users",
    }
    op_put = {
        "id": "api_op_put_v1_users_userId",
        "label": "API:PUT /v1/users/{userId}",
        "type": "api_operation",
        "method": "PUT",
        "path": "/v1/users/{userId}",  # Note: different param name should match via normalization
    }
    path_node = {
        "id": "api_path_v1_users",
        "label": "API:Path:/v1/users",
        "type": "api_path",
        "path": "/v1/users",
    }

    nodes = [rpc_node_1, rpc_node_2, rpc_node_3, op_get, op_post, op_put, path_node]
    edges: list[dict] = []

    new_edges = resolve_grpc_openapi_edges(nodes, edges, relation="transcodes-to")
    assert len(new_edges) >= 4

    edge_tuples = {(e["source"], e["target"], e["relation"]) for e in edges}

    # Exact operation match
    assert ("proto_rpc_user_service_get_user", "api_op_get_v1_users_id", "transcodes-to") in edge_tuples
    assert ("proto_rpc_user_service_create_user", "api_op_post_v1_users", "transcodes-to") in edge_tuples

    # Parameter normalization match for additional binding PUT /v1/users/{user_id} -> /v1/users/{userId}
    assert ("proto_rpc_user_service_update_user", "api_op_put_v1_users_userId", "transcodes-to") in edge_tuples

    # Path node match
    assert ("proto_rpc_user_service_create_user", "api_path_v1_users", "transcodes-to") in edge_tuples

    # Deduplication check: re-running should add 0 edges
    edges_count = len(edges)
    second_pass = resolve_grpc_openapi_edges(nodes, edges, relation="transcodes-to")
    assert len(second_pass) == 0
    assert len(edges) == edges_count


def test_resolve_grpc_openapi_custom_relation():
    rpc_node = {
        "id": "rpc_1",
        "type": "proto_rpc",
        "http_method": "GET",
        "http_route": "/v1/orders",
    }
    op_node = {
        "id": "op_1",
        "type": "api_operation",
        "method": "GET",
        "path": "/v1/orders",
    }
    nodes = [rpc_node, op_node]
    edges: list[dict] = []

    new_edges = resolve_grpc_openapi_edges(nodes, edges, relation="exposes-endpoint")
    assert len(new_edges) == 1
    assert new_edges[0]["relation"] == "exposes-endpoint"
    assert new_edges[0]["source"] == "rpc_1"
    assert new_edges[0]["target"] == "op_1"


def test_cross_format_dependencies_integrates_grpc_gateway(tmp_path: Path):
    rpc_node = {
        "id": "proto_rpc_ping",
        "label": "Proto:RPC:Health.Ping",
        "type": "proto_rpc",
        "http_method": "GET",
        "http_route": "/healthz",
    }
    op_node = {
        "id": "api_op_healthz",
        "label": "API:GET /healthz",
        "type": "api_operation",
        "method": "GET",
        "path": "/healthz",
    }
    all_nodes = [rpc_node, op_node]
    all_edges: list[dict] = []

    resolve_cross_format_dependencies(all_nodes, all_edges)
    transcode_edges = [e for e in all_edges if e["relation"] == "transcodes-to"]
    assert len(transcode_edges) == 1
    assert transcode_edges[0]["source"] == "proto_rpc_ping"
    assert transcode_edges[0]["target"] == "api_op_healthz"


def test_external_message_types_create_valid_nodes(tmp_path: Path):
    proto_content = """syntax = "proto3";
package acme.events.v1;

service EventHub {
    rpc Publish (google.protobuf.Empty) returns (google.protobuf.Empty);
}
"""
    p = _write(tmp_path, "hub.proto", proto_content)
    res = extract_protobuf(p)
    nodes = res["nodes"]
    edges = res["edges"]

    empty_node = next(n for n in nodes if n["label"] == "Proto:Message:Empty")
    assert empty_node["is_external"] is True

    rpc_node = next(n for n in nodes if n["label"] == "Proto:RPC:EventHub.Publish")
    accepts_targets = [e["target"] for e in edges if e["source"] == rpc_node["id"] and e["relation"] == "accepts"]
    returns_targets = [e["target"] for e in edges if e["source"] == rpc_node["id"] and e["relation"] == "returns"]

    assert empty_node["id"] in accepts_targets
    assert empty_node["id"] in returns_targets


def test_nested_messages_and_comments(tmp_path: Path):
    proto_content = """syntax = "proto3";
// Comment before package
package org.acme;

/* Multi-line
   comment about Outer
*/
message Outer {
    // Nested Inner message
    message Inner {
        string value = 1; // line comment
    }
    Inner inner = 1;
    string url = 2; // e.g. "https://example.com/api"
}
"""
    p = _write(tmp_path, "nested.proto", proto_content)
    res = extract_protobuf(p)
    nodes = res["nodes"]

    labels = _labels(nodes)
    assert "Proto:Message:Outer" in labels
    assert "Proto:Message:Inner" in labels


def test_unreadable_file_handling(tmp_path: Path):
    missing_path = tmp_path / "nonexistent.proto"
    res = extract_protobuf(missing_path)
    assert "error" in res
    assert len(res["nodes"]) == 1  # File node
    assert len(res["edges"]) == 0
