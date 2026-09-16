"""JSON Schema, OpenAPI, and AsyncAPI specification extractor.

Extracts:
1. JSON Schema: definitions, $defs, properties, and $ref links.
2. OpenAPI 3.x / Swagger: endpoints, operations, tags, request/response bodies, $refs.
3. AsyncAPI: channels, messages, publish/subscribe operations, mapping to Kafka topics.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from graph_fy.extractors.jsonschema import extract_json_schema_data, is_json_schema


def _make_id(*parts: str) -> str:
    clean = [re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(p)).strip("_") for p in parts if p]
    return "_".join(clean)


def is_api_or_schema(path: Path) -> bool:
    """Return True if path is an OpenAPI spec, AsyncAPI spec, or JSON Schema."""
    if is_json_schema(path):
        return True
    name = path.name.lower()
    if name.endswith(".schema.json") or name == "schema.json":
        return True
    if name in (
        "openapi.json", "openapi.yaml", "openapi.yml",
        "swagger.json", "swagger.yaml", "swagger.yml",
        "asyncapi.json", "asyncapi.yaml", "asyncapi.yml",
    ):
        return True

    # Quick sniff of YAML/JSON files for top-level keys
    ext = path.suffix.lower()
    if ext in (".json", ".yaml", ".yml"):
        try:
            sample = path.read_text(encoding="utf-8", errors="replace")[:1000]
            if '"$schema"' in sample or "'$schema'" in sample or "$schema:" in sample:
                return True
            if '"openapi"' in sample or "openapi:" in sample:
                return True
            if '"swagger"' in sample or "swagger:" in sample:
                return True
            if '"asyncapi"' in sample or "asyncapi:" in sample:
                return True
        except Exception:
            pass
    return False


def _load_data(path: Path) -> dict[str, Any] | None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".json":
            try:
                return json.loads(content)
            except Exception:
                pass
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def extract_api_or_schema(path: Path) -> dict[str, Any]:
    """Extract JSON Schema, OpenAPI, or AsyncAPI specs into graph nodes and edges."""
    str_path = str(path.resolve())
    file_nid = _make_id(str_path)
    file_name = path.name

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    data = _load_data(path)
    if not isinstance(data, dict):
        return {"nodes": nodes, "edges": edges}

    # Detect spec kind
    if "openapi" in data or "swagger" in data:
        _extract_openapi(str_path, file_nid, file_name, data, nodes, edges)
    elif "asyncapi" in data:
        _extract_asyncapi(str_path, file_nid, file_name, data, nodes, edges)
    elif "$schema" in data or "definitions" in data or "$defs" in data or path.name.lower().endswith(".schema.json"):
        _extract_json_schema(str_path, file_nid, file_name, data, nodes, edges)
    else:
        # Fallback generic schema
        _extract_json_schema(str_path, file_nid, file_name, data, nodes, edges)

    return {"nodes": nodes, "edges": edges}


def _extract_json_schema(
    str_path: str,
    file_nid: str,
    file_name: str,
    data: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    extract_json_schema_data(str_path, file_nid, file_name, data, nodes, edges)


def _extract_refs(str_path: str, source_nid: str, obj: Any, edges: list[dict[str, Any]]) -> None:
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref_target = str(obj["$ref"])
            # Resolve target ID
            # e.g. "#/definitions/User" -> User
            # or "./common.schema.json#/definitions/Role"
            target_name = ref_target.split("/")[-1]
            target_nid = _make_id("schema_def", str_path, target_name) if ref_target.startswith("#") else _make_id("ref", ref_target)
            edges.append({
                "source": source_nid,
                "target": target_nid,
                "relation": "references_schema",
                "ref_uri": ref_target,
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })
        for v in obj.values():
            _extract_refs(str_path, source_nid, v, edges)
    elif isinstance(obj, list):
        for item in obj:
            _extract_refs(str_path, source_nid, item, edges)


def _extract_openapi(
    str_path: str,
    file_nid: str,
    file_name: str,
    data: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    info = data.get("info") or {}
    title = info.get("title") or Path(file_name).stem
    api_node: dict[str, Any] = {
        "id": file_nid,
        "label": f"API:{title}",
        "type": "openapi_spec",
        "file_type": "code",
        "title": str(title),
        "version": str(info.get("version") or ""),
        "source_file": str_path,
        "source_location": "L1",
        "text": f"OpenAPI specification {title}",
    }
    nodes.append(api_node)

    # Components / Schemas
    components = data.get("components") or {}
    schemas = components.get("schemas") or data.get("definitions") or {}
    if isinstance(schemas, dict):
        for schema_name, schema_body in schemas.items():
            if not isinstance(schema_body, dict):
                continue
            schema_nid = _make_id("schema_def", str_path, str(schema_name))
            nodes.append({
                "id": schema_nid,
                "label": f"Schema:{schema_name}",
                "type": "schema_definition",
                "file_type": "code",
                "schema_name": str(schema_name),
                "source_file": str_path,
                "source_location": "L1",
                "text": f"API component schema {schema_name}",
            })
            edges.append({
                "source": file_nid,
                "target": schema_nid,
                "relation": "defines_schema",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })
            _extract_refs(str_path, schema_nid, schema_body, edges)

    # Paths & Operations
    paths = data.get("paths") or {}
    if isinstance(paths, dict):
        for path_str, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method in ("get", "post", "put", "delete", "patch", "options", "head"):
                op_data = path_item.get(method)
                if not isinstance(op_data, dict):
                    continue

                op_id = op_data.get("operationId") or f"{method}_{path_str}"
                op_nid = _make_id("api_op", str_path, method, path_str)
                op_label = f"API:{method.upper()} {path_str}"

                nodes.append({
                    "id": op_nid,
                    "label": op_label,
                    "type": "api_operation",
                    "file_type": "code",
                    "method": method.upper(),
                    "path": path_str,
                    "operation_id": str(op_id),
                    "source_file": str_path,
                    "source_location": "L1",
                    "text": f"{method.upper()} {path_str} - {op_data.get('summary') or ''}",
                })
                edges.append({
                    "source": file_nid,
                    "target": op_nid,
                    "relation": "defines_operation",
                    "confidence": "EXTRACTED",
                    "weight": 1.0,
                    "source_file": str_path,
                    "source_location": "L1",
                })

                # Link operation to schemas via $ref
                _extract_refs(str_path, op_nid, op_data, edges)


def _extract_asyncapi(
    str_path: str,
    file_nid: str,
    file_name: str,
    data: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    info = data.get("info") or {}
    title = info.get("title") or Path(file_name).stem
    async_node: dict[str, Any] = {
        "id": file_nid,
        "label": f"AsyncAPI:{title}",
        "type": "asyncapi_spec",
        "file_type": "code",
        "title": str(title),
        "source_file": str_path,
        "source_location": "L1",
        "text": f"AsyncAPI specification {title}",
    }
    nodes.append(async_node)

    # Channels
    channels = data.get("channels") or {}
    if isinstance(channels, dict):
        for chan_name, chan_data in channels.items():
            if not isinstance(chan_data, dict):
                continue
            chan_nid = _make_id("channel", str_path, str(chan_name))
            nodes.append({
                "id": chan_nid,
                "label": f"Channel:{chan_name}",
                "type": "channel",
                "file_type": "code",
                "channel_name": str(chan_name),
                "source_file": str_path,
                "source_location": "L1",
                "text": f"AsyncAPI channel {chan_name}",
            })
            edges.append({
                "source": file_nid,
                "target": chan_nid,
                "relation": "defines_channel",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })

            # Also create topic node mapping to Kafka topics
            topic_nid = _make_id("kafka_topic", str(chan_name))
            nodes.append({
                "id": topic_nid,
                "label": f"Kafka:Topic:{chan_name}",
                "type": "kafka_topic",
                "file_type": "code",
                "topic_name": str(chan_name),
                "source_file": str_path,
                "source_location": "L1",
                "text": f"Kafka topic mapped from AsyncAPI channel {chan_name}",
            })
            edges.append({
                "source": chan_nid,
                "target": topic_nid,
                "relation": "maps_to_topic",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })

            # Check messages and $ref
            _extract_refs(str_path, chan_nid, chan_data, edges)
