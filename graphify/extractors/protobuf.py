"""Protobuf (.proto) and gRPC service extractor with OpenAPI gateway cross-referencing.

Extracts:
1. Package declarations: package <package_name>;
2. Enums: enum <EnumName> { ... } -> Proto:Enum:<EnumName>
3. Messages: message <MessageName> { ... } -> Proto:Message:<MessageName>
   - Nested messages and enums
   - Field declarations and references
4. Services: service <ServiceName> { ... } -> Proto:Service:<ServiceName>
5. RPC methods: rpc <MethodName> (<ReqType>) returns (<RespType>) -> Proto:RPC:<ServiceName>.<MethodName>
   - Streaming flags (client_streaming, server_streaming)
   - Accepts edge (RPC -> ReqType message)
   - Returns edge (RPC -> RespType message)
   - google.api.http transcoding options (get, post, put, delete, patch, body, additional_bindings)
6. Cross-resolution: resolve_grpc_openapi_edges(nodes, edges) connects gRPC RPC methods
   to corresponding OpenAPI path/operation nodes via 'transcodes-to' or 'exposes-endpoint'.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _make_id(*parts: str) -> str:
    """Generate deterministic normalized slug ID."""
    clean = [re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(p)).strip("_") for p in parts if p]
    return "_".join(clean)


def _strip_comments_preserving_lines(content: str) -> str:
    """Strip single-line and multi-line comments while preserving newlines and string literals."""
    def _replacer(match: re.Match[str]) -> str:
        s = match.group(0)
        if s.startswith(('"', "'")):
            return s
        return "".join("\n" if c == "\n" else " " for c in s)

    pattern = re.compile(
        r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')|(/\*[\s\S]*?\*/|//[^\n]*)'
    )
    return pattern.sub(_replacer, content)


def is_protobuf_file(path: Path) -> bool:
    """Return True if path is a Protobuf .proto file."""
    return path.suffix.lower() == ".proto"


def parse_google_api_http(text: str) -> list[dict[str, str]]:
    """Parse google.api.http gateway options and return a list of HTTP bindings.

    Each binding is a dict:
      {"method": "GET", "path": "/v1/users/{id}", "body": "*"}
    """
    bindings: list[dict[str, str]] = []

    # 1. Flat options: option (google.api.http).get = "/v1/users/{id}";
    flat_method_match = re.search(
        r"option\s*\(\s*google\.api\.http\s*\)\.(get|post|put|delete|patch)\s*=\s*\"([^\"]+)\"",
        text,
        re.IGNORECASE,
    )
    if flat_method_match:
        method = flat_method_match.group(1).upper()
        route = flat_method_match.group(2)
        body_match = re.search(
            r"option\s*\(\s*google\.api\.http\s*\)\.body\s*=\s*\"([^\"]*)\"",
            text,
            re.IGNORECASE,
        )
        body = body_match.group(1) if body_match else ""
        bindings.append({"method": method, "path": route, "body": body})
        return bindings

    # 2. Block options: option (google.api.http) = { ... };
    block_start_match = re.search(r"option\s*\(\s*google\.api\.http\s*\)\s*=\s*\{", text)
    if not block_start_match:
        return bindings

    start_brace = block_start_match.end() - 1
    depth = 1
    pos = start_brace + 1
    n = len(text)
    in_str = False
    str_char = ""

    while pos < n and depth > 0:
        c = text[pos]
        if in_str:
            if c == "\\":
                pos += 2
                continue
            elif c == str_char:
                in_str = False
        else:
            if c in ('"', "'"):
                in_str = True
                str_char = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        pos += 1

    if depth != 0:
        return bindings

    http_block = text[start_brace + 1 : pos - 1]

    # Find additional_bindings blocks first, then extract them and strip them from main block
    additional_blocks: list[str] = []
    add_match = re.finditer(r"\badditional_bindings\s*(?::\s*)?\{", http_block)
    spans_to_remove: list[tuple[int, int]] = []

    for m in add_match:
        b_start = m.end() - 1
        b_depth = 1
        b_pos = b_start + 1
        b_in_str = False
        b_str_char = ""
        while b_pos < len(http_block) and b_depth > 0:
            bc = http_block[b_pos]
            if b_in_str:
                if bc == "\\":
                    b_pos += 2
                    continue
                elif bc == b_str_char:
                    b_in_str = False
            else:
                if bc in ('"', "'"):
                    b_in_str = True
                    b_str_char = bc
                elif bc == "{":
                    b_depth += 1
                elif bc == "}":
                    b_depth -= 1
            b_pos += 1
        if b_depth == 0:
            additional_blocks.append(http_block[b_start + 1 : b_pos - 1])
            spans_to_remove.append((m.start(), b_pos))

    # Remove additional_bindings from primary block
    primary_block = http_block
    for start, end in reversed(spans_to_remove):
        primary_block = primary_block[:start] + primary_block[end:]

    def _extract_binding_from_chunk(chunk: str) -> dict[str, str] | None:
        verb_match = re.search(
            r"\b(get|post|put|delete|patch)\s*:\s*\"([^\"]+)\"", chunk, re.IGNORECASE
        )
        if verb_match:
            verb = verb_match.group(1).upper()
            route = verb_match.group(2)
            body_m = re.search(r"\bbody\s*:\s*\"([^\"]*)\"", chunk, re.IGNORECASE)
            body_val = body_m.group(1) if body_m else ""
            return {"method": verb, "path": route, "body": body_val}

        custom_match = re.search(
            r"\bcustom\s*:\s*\{[^}]*kind\s*:\s*\"([^\"]+)\"[^}]*path\s*:\s*\"([^\"]+)\"",
            chunk,
            re.IGNORECASE,
        )
        if custom_match:
            verb = custom_match.group(1).upper()
            route = custom_match.group(2)
            body_m = re.search(r"\bbody\s*:\s*\"([^\"]*)\"", chunk, re.IGNORECASE)
            body_val = body_m.group(1) if body_m else ""
            return {"method": verb, "path": route, "body": body_val}

        return None

    primary_binding = _extract_binding_from_chunk(primary_block)
    if primary_binding:
        bindings.append(primary_binding)

    for add_chunk in additional_blocks:
        b = _extract_binding_from_chunk(add_chunk)
        if b:
            bindings.append(b)

    return bindings


def _find_balanced_blocks(content: str, keyword: str) -> list[dict[str, Any]]:
    """Find all balanced blocks for a top-level or nested keyword (message, service, enum)."""
    blocks: list[dict[str, Any]] = []
    pattern = re.compile(r"\b" + keyword + r"\s+([a-zA-Z0-9_]+)\s*\{")

    for match in pattern.finditer(content):
        name = match.group(1)
        start_brace = match.end() - 1
        depth = 1
        pos = start_brace + 1
        n = len(content)
        in_str = False
        str_char = ""

        while pos < n and depth > 0:
            c = content[pos]
            if in_str:
                if c == "\\":
                    pos += 2
                    continue
                elif c == str_char:
                    in_str = False
            else:
                if c in ('"', "'"):
                    in_str = True
                    str_char = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
            pos += 1

        if depth == 0:
            body = content[start_brace + 1 : pos - 1]
            line = content[: match.start()].count("\n") + 1
            blocks.append({
                "name": name,
                "body": body,
                "start": match.start(),
                "end": pos,
                "line": line,
            })

    return blocks


def _parse_fields(message_body: str) -> list[dict[str, Any]]:
    """Parse field declarations from a message body."""
    fields: list[dict[str, Any]] = []
    field_re = re.compile(
        r"^\s*(?:(optional|repeated|required)\s+)?"
        r"([a-zA-Z0-9_.]+)\s+([a-zA-Z0-9_]+)\s*=\s*(\d+)",
        re.MULTILINE,
    )
    for m in field_re.finditer(message_body):
        rule = m.group(1) or "optional"
        ftype = m.group(2)
        fname = m.group(3)
        fnum = int(m.group(4))
        # Skip field keywords like reserved or option
        if ftype in ("reserved", "option", "package", "syntax", "message", "enum", "service", "rpc"):
            continue
        fields.append({
            "name": fname,
            "type": ftype,
            "number": fnum,
            "rule": rule,
            "repeated": rule == "repeated",
        })
    return fields


def extract_protobuf(path: Path) -> dict[str, Any]:
    """Extract Protobuf (.proto) package, messages, enums, services, and RPC methods."""
    str_path = str(path.resolve())
    file_nid = _make_id(str_path)

    nodes: list[dict[str, Any]] = [{
        "id": file_nid,
        "label": path.name,
        "type": "file",
        "file_type": "code",
        "source_file": str_path,
        "source_location": "L1",
        "text": path.name,
    }]
    edges: list[dict[str, Any]] = []

    try:
        raw_content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"nodes": nodes, "edges": edges, "error": str(exc)}

    content = _strip_comments_preserving_lines(raw_content)

    pkg_match = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;", content, re.MULTILINE)
    package_name = pkg_match.group(1) if pkg_match else ""

    seen_node_ids: set[str] = {file_nid}
    known_messages: dict[str, str] = {}  # full_name/name -> node_id

    # 1. Enums
    enum_blocks = _find_balanced_blocks(content, "enum")
    for eb in enum_blocks:
        enum_name = eb["name"]
        full_enum = f"{package_name}.{enum_name}" if package_name else enum_name
        enum_id = _make_id("proto_enum", full_enum)
        line_num = eb["line"]

        # Extract enum values
        val_matches = re.findall(r"\b([a-zA-Z0-9_]+)\s*=\s*[-0-9]+", eb["body"])
        values = [v for v in val_matches if v not in ("option", "reserved")]

        if enum_id not in seen_node_ids:
            seen_node_ids.add(enum_id)
            nodes.append({
                "id": enum_id,
                "label": f"Proto:Enum:{enum_name}",
                "type": "proto_enum",
                "file_type": "code",
                "enum_name": enum_name,
                "package": package_name,
                "full_name": full_enum,
                "values": values,
                "aliases": [f"Proto:Enum:{full_enum}"] if full_enum != enum_name else [],
                "source_file": str_path,
                "source_location": f"L{line_num}",
                "text": f"Protobuf enum {full_enum}",
            })
            edges.append({
                "source": file_nid,
                "target": enum_id,
                "relation": "contains",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": f"L{line_num}",
            })

    # 2. Messages
    msg_blocks = _find_balanced_blocks(content, "message")
    for mb in msg_blocks:
        msg_name = mb["name"]
        full_msg = f"{package_name}.{msg_name}" if package_name else msg_name
        msg_id = _make_id("proto_msg", full_msg)
        line_num = mb["line"]

        known_messages[msg_name] = msg_id
        known_messages[full_msg] = msg_id

        fields = _parse_fields(mb["body"])

        if msg_id not in seen_node_ids:
            seen_node_ids.add(msg_id)
            nodes.append({
                "id": msg_id,
                "label": f"Proto:Message:{msg_name}",
                "type": "proto_message",
                "file_type": "code",
                "message_name": msg_name,
                "package": package_name,
                "full_name": full_msg,
                "fields": fields,
                "aliases": [f"Proto:Message:{full_msg}"] if full_msg != msg_name else [],
                "source_file": str_path,
                "source_location": f"L{line_num}",
                "text": f"Protobuf message {full_msg}",
            })
            edges.append({
                "source": file_nid,
                "target": msg_id,
                "relation": "contains",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": f"L{line_num}",
            })

            # Backward compatibility with Phase 4 Kafka schema labels
            if package_name:
                kafka_id = _make_id("kafka_proto_msg", full_msg)
                if kafka_id not in seen_node_ids:
                    seen_node_ids.add(kafka_id)
                    nodes.append({
                        "id": kafka_id,
                        "label": f"Kafka:Proto:{full_msg}",
                        "type": "proto_message",
                        "file_type": "code",
                        "message_name": msg_name,
                        "package": package_name,
                        "source_file": str_path,
                        "source_location": f"L{line_num}",
                        "text": f"Protobuf message {full_msg}",
                    })
                    edges.append({
                        "source": file_nid,
                        "target": kafka_id,
                        "relation": "contains",
                        "confidence": "EXTRACTED",
                        "weight": 1.0,
                        "source_file": str_path,
                        "source_location": f"L{line_num}",
                    })

    # Helper to resolve message type node
    def _get_or_create_msg_node(type_name: str, src_line: int) -> str:
        clean_type = type_name.strip()
        if clean_type in known_messages:
            return known_messages[clean_type]

        full_type = f"{package_name}.{clean_type}" if (package_name and "." not in clean_type) else clean_type
        if full_type in known_messages:
            return known_messages[full_type]

        mid = _make_id("proto_msg", full_type)
        if mid not in seen_node_ids:
            seen_node_ids.add(mid)
            short_name = clean_type.split(".")[-1]
            nodes.append({
                "id": mid,
                "label": f"Proto:Message:{short_name}",
                "type": "proto_message",
                "file_type": "code",
                "message_name": short_name,
                "package": clean_type.rsplit(".", 1)[0] if "." in clean_type else package_name,
                "full_name": full_type,
                "is_external": True,
                "source_file": str_path,
                "source_location": f"L{src_line}",
                "text": f"Protobuf message {full_type}",
            })
        known_messages[clean_type] = mid
        known_messages[full_type] = mid
        return mid

    # 3. Services & RPCs
    svc_blocks = _find_balanced_blocks(content, "service")
    rpc_sig_re = re.compile(
        r"\brpc\s+([a-zA-Z0-9_]+)\s*"
        r"\(\s*(stream\s+)?([a-zA-Z0-9_.]+)\s*\)\s*"
        r"returns\s*"
        r"\(\s*(stream\s+)?([a-zA-Z0-9_.]+)\s*\)",
        re.MULTILINE,
    )

    for sb in svc_blocks:
        svc_name = sb["name"]
        full_svc = f"{package_name}.{svc_name}" if package_name else svc_name
        svc_id = _make_id("proto_svc", full_svc)
        line_num = sb["line"]

        if svc_id not in seen_node_ids:
            seen_node_ids.add(svc_id)
            nodes.append({
                "id": svc_id,
                "label": f"Proto:Service:{svc_name}",
                "type": "proto_service",
                "file_type": "code",
                "service_name": svc_name,
                "package": package_name,
                "full_name": full_svc,
                "aliases": [f"Proto:Service:{full_svc}"] if full_svc != svc_name else [],
                "source_file": str_path,
                "source_location": f"L{line_num}",
                "text": f"Protobuf service {full_svc}",
            })
            edges.append({
                "source": file_nid,
                "target": svc_id,
                "relation": "contains",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": f"L{line_num}",
            })

            # Backward compatibility with Phase 4 Kafka service labels
            if package_name:
                kafka_svc_id = _make_id("kafka_proto_svc", full_svc)
                if kafka_svc_id not in seen_node_ids:
                    seen_node_ids.add(kafka_svc_id)
                    nodes.append({
                        "id": kafka_svc_id,
                        "label": f"Kafka:ProtoService:{full_svc}",
                        "type": "proto_service",
                        "file_type": "code",
                        "service_name": svc_name,
                        "package": package_name,
                        "source_file": str_path,
                        "source_location": f"L{line_num}",
                        "text": f"Protobuf service {full_svc}",
                    })
                    edges.append({
                        "source": file_nid,
                        "target": kafka_svc_id,
                        "relation": "contains",
                        "confidence": "EXTRACTED",
                        "weight": 1.0,
                        "source_file": str_path,
                        "source_location": f"L{line_num}",
                    })

        # Scan RPCs in service body
        svc_body = sb["body"]
        for match in rpc_sig_re.finditer(svc_body):
            method_name = match.group(1)
            client_streaming = bool(match.group(2))
            req_type = match.group(3).strip()
            server_streaming = bool(match.group(4))
            resp_type = match.group(5).strip()

            rpc_line = line_num + svc_body[: match.start()].count("\n")

            # Check if RPC has a block with options or ends with semicolon
            tail = svc_body[match.end() :]
            rpc_block_body = ""
            tail_stripped = tail.lstrip()
            if tail_stripped.startswith("{"):
                # Balanced scan for RPC options block
                start_offset = match.end() + (len(tail) - len(tail_stripped))
                depth = 1
                pos = start_offset + 1
                in_str = False
                str_char = ""
                n_b = len(svc_body)
                while pos < n_b and depth > 0:
                    c = svc_body[pos]
                    if in_str:
                        if c == "\\":
                            pos += 2
                            continue
                        elif c == str_char:
                            in_str = False
                    else:
                        if c in ('"', "'"):
                            in_str = True
                            str_char = c
                        elif c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                    pos += 1
                if depth == 0:
                    rpc_block_body = svc_body[start_offset + 1 : pos - 1]

            http_bindings = parse_google_api_http(rpc_block_body) if rpc_block_body else []
            primary_http = http_bindings[0] if http_bindings else None
            http_method = primary_http["method"] if primary_http else None
            http_route = primary_http["path"] if primary_http else None
            http_body = primary_http.get("body") if primary_http else None

            rpc_id = _make_id("proto_rpc", full_svc, method_name)
            rpc_node: dict[str, Any] = {
                "id": rpc_id,
                "label": f"Proto:RPC:{svc_name}.{method_name}",
                "type": "proto_rpc",
                "file_type": "code",
                "method_name": method_name,
                "service_name": svc_name,
                "package": package_name,
                "full_name": f"{full_svc}.{method_name}",
                "request_type": req_type,
                "response_type": resp_type,
                "client_streaming": client_streaming,
                "server_streaming": server_streaming,
                "http_method": http_method,
                "http_route": http_route,
                "http_path": http_route,
                "http_body": http_body,
                "http_bindings": http_bindings,
                "aliases": [f"Proto:RPC:{full_svc}.{method_name}"] if full_svc != svc_name else [],
                "source_file": str_path,
                "source_location": f"L{rpc_line}",
                "text": f"gRPC RPC {svc_name}.{method_name} ({req_type}) returns ({resp_type})",
            }

            if rpc_id not in seen_node_ids:
                seen_node_ids.add(rpc_id)
                nodes.append(rpc_node)

            # Service -> RPC edge
            edges.append({
                "source": svc_id,
                "target": rpc_id,
                "relation": "defines_rpc",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": f"L{rpc_line}",
            })

            # RPC -> ReqType message edge (accepts)
            req_id = _get_or_create_msg_node(req_type, rpc_line)
            edges.append({
                "source": rpc_id,
                "target": req_id,
                "relation": "accepts",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": f"L{rpc_line}",
            })

            # RPC -> RespType message edge (returns)
            resp_id = _get_or_create_msg_node(resp_type, rpc_line)
            edges.append({
                "source": rpc_id,
                "target": resp_id,
                "relation": "returns",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": f"L{rpc_line}",
            })

    return {"nodes": nodes, "edges": edges}


def _normalize_route(p: str) -> str:
    """Normalize route pattern for wildcard matching."""
    if not p:
        return ""
    p = p.split("?")[0].strip()
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    # Replace {param} or {param=*} or {name=projects/*/locations/*} with {*}
    return re.sub(r"\{[^{}]*\}", "{*}", p)


def _routes_match(p1: str, p2: str) -> bool:
    """Check if two route patterns match exactly or via normalized parameter placeholders."""
    if not p1 or not p2:
        return False
    c1 = p1.strip().rstrip("/")
    c2 = p2.strip().rstrip("/")
    if c1 == c2:
        return True
    return _normalize_route(c1) == _normalize_route(c2)


def resolve_grpc_openapi_edges(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    relation: str = "transcodes-to",
) -> list[dict[str, Any]]:
    """Connect gRPC RPC methods to corresponding OpenAPI path/operation nodes.

    Finds RPC nodes with google.api.http transcoding annotations and matches them against
    OpenAPI api_operation and api_path nodes. Creates edges with relation (default: 'transcodes-to').
    Mutates edges in place and returns the list of newly created edges.
    """
    seen_edges: set[tuple[str, str, str]] = {
        (str(e.get("source")), str(e.get("target")), str(e.get("relation")))
        for e in edges
    }
    new_edges: list[dict[str, Any]] = []

    # 1. Collect gRPC RPC nodes that have HTTP annotations
    rpc_nodes: list[dict[str, Any]] = []
    for n in nodes:
        if n.get("type") == "proto_rpc" or str(n.get("label", "")).startswith("Proto:RPC:"):
            if n.get("http_bindings") or (n.get("http_method") and (n.get("http_route") or n.get("http_path"))):
                rpc_nodes.append(n)

    if not rpc_nodes:
        return new_edges

    # 2. Collect OpenAPI operation nodes and path nodes
    openapi_ops: list[tuple[dict[str, Any], str, str]] = []  # (node, method_upper, path)
    openapi_paths: list[tuple[dict[str, Any], str]] = []  # (node, path)

    for n in nodes:
        ntype = n.get("type", "")
        label = str(n.get("label", ""))

        if ntype == "api_operation" or label.startswith("API:"):
            method = str(n.get("method") or "").upper()
            path = str(n.get("path") or "")
            if (not method or not path) and label.startswith("API:"):
                # Attempt to parse 'API:GET /v1/users/{id}'
                rest = label[4:].strip()
                if " " in rest:
                    parts = rest.split(" ", 1)
                    if not method:
                        method = parts[0].upper()
                    if not path:
                        path = parts[1].strip()
            if method and path:
                openapi_ops.append((n, method, path))

        if ntype in ("api_path", "path") or label.startswith("API:Path:"):
            path = str(n.get("path") or "")
            if not path and label.startswith("API:Path:"):
                path = label[9:].strip()
            if path:
                openapi_paths.append((n, path))

    # 3. Match RPC bindings to OpenAPI nodes
    for rpc in rpc_nodes:
        bindings = rpc.get("http_bindings") or []
        if not bindings and rpc.get("http_method") and (rpc.get("http_route") or rpc.get("http_path")):
            bindings = [{
                "method": str(rpc["http_method"]),
                "path": str(rpc.get("http_route") or rpc.get("http_path")),
            }]

        for b in bindings:
            b_method = str(b.get("method") or "").upper()
            b_path = str(b.get("path") or "")
            if not b_method or not b_path:
                continue

            # Match against operation nodes
            for op_node, op_method, op_path in openapi_ops:
                if b_method == op_method and _routes_match(b_path, op_path):
                    key = (rpc["id"], op_node["id"], relation)
                    if key not in seen_edges:
                        seen_edges.add(key)
                        edge = {
                            "source": rpc["id"],
                            "target": op_node["id"],
                            "relation": relation,
                            "confidence": "EXTRACTED",
                            "weight": 1.0,
                            "source_file": rpc.get("source_file", ""),
                            "source_location": rpc.get("source_location", "L1"),
                        }
                        edges.append(edge)
                        new_edges.append(edge)

            # Match against path nodes
            for path_node, path_val in openapi_paths:
                if _routes_match(b_path, path_val):
                    key = (rpc["id"], path_node["id"], relation)
                    if key not in seen_edges:
                        seen_edges.add(key)
                        edge = {
                            "source": rpc["id"],
                            "target": path_node["id"],
                            "relation": relation,
                            "confidence": "EXTRACTED",
                            "weight": 1.0,
                            "source_file": rpc.get("source_file", ""),
                            "source_location": rpc.get("source_location", "L1"),
                        }
                        edges.append(edge)
                        new_edges.append(edge)

    return new_edges
