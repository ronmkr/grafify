"""Extended JSON Schema extractor with dialect normalization and Schema Registry mappings.

Features:
1. Dialect normalization across:
   - Draft-04: uses `definitions`, `id`, and `#/definitions/` refs.
   - Draft-07: uses `definitions`, `$id`, and `#/definitions/` refs.
   - 2020-12: uses `$defs`, `$id`, `$anchor`, `$dynamicAnchor`, and `$dynamicRef`.
   Uniform resolution ensures `$ref` and `$dynamicRef` link consistently across all dialects.
2. Schema Registry mappings:
   - Confluent Schema Registry (schema.registry.url, schema.registry.subject, subject naming strategies).
   - AWS Glue Schema Registry (schema_arn, schema.registry.url, registry.name, schema.name).
   - Apicurio Schema Registry (apicurio.registry.url, artifactId, groupId).
   - Subject naming strategies: TopicNameStrategy (<topic>-key, <topic>-value), RecordNameStrategy, TopicRecordNameStrategy.
3. Kafka topic and client config integration:
   - Creates Schema Subject nodes (`Schema:Subject:<name>`).
   - Connects Kafka topic nodes to schema subjects with relation `references-schema-subject`.
   - Connects Kafka topic nodes to schema files with relation `conforms-to-schema`.
   - Connects client configs to schema subjects with relation `references-schema-subject` and to schema files with relation `conforms-to-schema`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


def _make_id(*parts: str) -> str:
    clean = [re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(p)).strip("_") for p in parts if p]
    return "_".join(clean)


def detect_dialect(data: dict[str, Any]) -> str:
    """Detect JSON Schema dialect (draft-04, draft-07, 2020-12, etc.)."""
    schema_val = str(data.get("$schema") or "").lower().strip()
    if "draft-04" in schema_val:
        return "draft-04"
    if "draft-06" in schema_val:
        return "draft-06"
    if "draft-07" in schema_val:
        return "draft-07"
    if "2019-09" in schema_val:
        return "2019-09"
    if "2020-12" in schema_val:
        return "2020-12"

    # Heuristic detection when $schema is absent
    if (
        "$defs" in data
        or "$anchor" in data
        or "$dynamicAnchor" in data
        or "$dynamicRef" in data
        or "$vocabulary" in data
    ):
        return "2020-12"
    if "$id" in data:
        return "draft-07"
    if "id" in data and "$id" not in data:
        return "draft-04"
    return "draft-07"


def is_json_schema(path: Path) -> bool:
    """Return True if path is a JSON Schema or schema registry definition/config."""
    name = path.name.lower()
    if name.endswith(".schema.json") or name == "schema.json":
        return True
    if name.endswith(".schema.yaml") or name.endswith(".schema.yml"):
        return True
    if re.search(r"[-.](key|value)(\.schema)?\.(json|yaml|yml|avsc)$", name):
        return True

    ext = path.suffix.lower()
    if ext in (".json", ".yaml", ".yml", ".properties"):
        try:
            sample = path.read_text(encoding="utf-8", errors="replace")[:2000]
            if (
                '"$schema"' in sample
                or "'$schema'" in sample
                or "$schema:" in sample
            ):
                return True
            if (
                "schema.registry.url" in sample
                or "schema_registry_url" in sample
                or "schemaRegistryUrl" in sample
                or "schema_arn" in sample
                or "schemaArn" in sample
                or "schema.registry.subject" in sample
                or "schema_registry_subject" in sample
                or "apicurio.registry.url" in sample
                or "apicurio_registry_url" in sample
            ):
                return True
            if '"$defs"' in sample or "$defs:" in sample or '"definitions"' in sample or "definitions:" in sample:
                if '"type"' in sample or "type:" in sample or '"properties"' in sample or "properties:" in sample:
                    return True
        except Exception:
            pass
    return False


def _parse_subject_naming_strategy(
    subject_or_filename: str, explicit_strategy: str = ""
) -> tuple[str, str, str]:
    """Parse topic name, key/value role, and strategy from a subject or filename.

    Returns (topic_name, role, strategy) where role is 'key' or 'value' (or empty).
    """
    if explicit_strategy:
        strat = explicit_strategy.split(".")[-1]
    else:
        strat = ""

    clean = subject_or_filename
    # Strip common extensions if filename
    for ext in (
        ".schema.json", ".schema.yaml", ".schema.yml",
        ".avsc", ".json", ".yaml", ".yml", ".proto",
    ):
        if clean.endswith(ext):
            clean = clean[: -len(ext)]
            break

    # TopicNameStrategy: <topic>-key, <topic>-value, <topic>.key, <topic>.value
    match = re.match(r"^(.+)[-.](key|value)$", clean)
    if match:
        return match.group(1), match.group(2), strat or "TopicNameStrategy"

    # TopicRecordNameStrategy: <topic>-<record>
    if strat == "TopicRecordNameStrategy" or (not strat and "-" in clean and not clean.endswith(("-key", "-value"))):
        parts = clean.split("-", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], "", strat or "TopicRecordNameStrategy"

    # RecordNameStrategy: e.g. com.example.Order or Order
    if strat == "RecordNameStrategy" or (not strat and "." in clean and clean[0].islower() and any(c.isupper() for c in clean)):
        return "", "", strat or "RecordNameStrategy"

    return clean, "", strat or "CustomStrategy"


def detect_schema_registry_info(
    path: Path, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Extract schema registry, Kafka topic metadata, and schema references."""
    info: dict[str, Any] = {
        "registry_url": "",
        "registry_type": "",
        "schema_arn": "",
        "registry_name": "",
        "subject": "",
        "topic": "",
        "role": "",
        "strategy": "",
        "schema_file": "",
        "references": [],
    }

    file_name = path.name
    # Check filename convention
    topic_from_file, role_from_file, strat_from_file = _parse_subject_naming_strategy(file_name)
    if role_from_file:
        info["topic"] = topic_from_file
        info["role"] = role_from_file
        info["subject"] = f"{topic_from_file}-{role_from_file}"
        info["strategy"] = strat_from_file
        info["registry_type"] = "confluent"

    if not isinstance(data, dict):
        return info

    explicit_strat = str(
        data.get("subject.name.strategy")
        or data.get("subject_naming_strategy")
        or data.get("subjectNamingStrategy")
        or data.get("strategy")
        or ""
    )

    # Confluent Schema Registry fields
    url = (
        data.get("schema.registry.url")
        or data.get("schema_registry_url")
        or data.get("schemaRegistryUrl")
        or data.get("confluent.schema.registry.url")
        or data.get("confluent:schema_registry_url")
    )
    if url:
        info["registry_url"] = str(url)
        info["registry_type"] = "confluent"

    subj = (
        data.get("schema.registry.subject")
        or data.get("schema_registry_subject")
        or data.get("schemaRegistrySubject")
        or data.get("subject")
        or data.get("confluent:subject")
    )
    if subj:
        info["subject"] = str(subj)
        t, r, s = _parse_subject_naming_strategy(str(subj), explicit_strat)
        if t:
            info["topic"] = t
        if r:
            info["role"] = r
        if s:
            info["strategy"] = s

    # AWS Glue Schema Registry fields
    arn = (
        data.get("schema_arn")
        or data.get("schemaArn")
        or data.get("SCHEMA_ARN")
        or data.get("glue.schema.arn")
        or data.get("aws.glue.schema.arn")
    )
    if arn:
        info["schema_arn"] = str(arn)
        info["registry_type"] = "aws_glue"
        # Parse ARN: arn:aws:glue:<region>:<account>:schema/<registry>/<schema>
        m = re.match(r"^arn:aws(?:-[a-z]+)?:glue:[^:]+:[^:]+:schema/(?:([^/]+)/)?([^/]+)$", str(arn))
        if m:
            info["registry_name"] = m.group(1) or "default-registry"
            if not info["subject"]:
                schema_part = m.group(2)
                info["subject"] = schema_part
                t, r, s = _parse_subject_naming_strategy(schema_part, explicit_strat)
                if t:
                    info["topic"] = t
                if r:
                    info["role"] = r
                if s:
                    info["strategy"] = s

    schema_name = (
        data.get("schemaName")
        or data.get("schema_name")
        or data.get("schema.name")
        or data.get("SCHEMA_NAME")
    )
    if schema_name and not info["subject"]:
        info["subject"] = str(schema_name)
        t, r, s = _parse_subject_naming_strategy(str(schema_name), explicit_strat)
        if t:
            info["topic"] = t
        if r:
            info["role"] = r
        if s:
            info["strategy"] = s

    reg_name = (
        data.get("registryName")
        or data.get("registry_name")
        or data.get("registry.name")
        or data.get("REGISTRY_NAME")
    )
    if reg_name:
        info["registry_name"] = str(reg_name)
        if not info["registry_type"]:
            info["registry_type"] = "aws_glue"

    # Apicurio Schema Registry fields
    apicurio_url = data.get("apicurio.registry.url") or data.get("apicurio_registry_url")
    if apicurio_url:
        info["registry_url"] = str(apicurio_url)
        info["registry_type"] = "apicurio"

    artifact_id = data.get("artifactId") or data.get("apicurio.artifactId")
    if artifact_id and not info["subject"]:
        info["subject"] = str(artifact_id)
        info["registry_type"] = "apicurio"
        t, r, s = _parse_subject_naming_strategy(str(artifact_id), explicit_strat)
        if t:
            info["topic"] = t
        if r:
            info["role"] = r
        if s:
            info["strategy"] = s

    # Kafka Topic directly in config
    if data.get("topic") or data.get("kafka_topic") or data.get("kafka.topic"):
        topic_val = str(data.get("topic") or data.get("kafka_topic") or data.get("kafka.topic"))
        info["topic"] = topic_val

    # Schema file reference in client configs
    schema_file = (
        data.get("schema.file")
        or data.get("schema_file")
        or data.get("schemaFile")
        or data.get("schema.path")
        or data.get("schema_path")
    )
    if schema_file:
        info["schema_file"] = str(schema_file)

    # Confluent Schema Registry references
    refs = data.get("references")
    if isinstance(refs, list):
        info["references"] = refs

    return info


def _collect_subschemas_and_anchors(
    data: dict[str, Any],
    str_path: str,
    file_nid: str,
    dialect: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    """Extract definitions and anchors across Draft-04, Draft-07, and 2020-12.

    Returns (def_map, anchor_map) mapping names to node IDs.
    """
    def_map: dict[str, str] = {}
    anchor_map: dict[str, str] = {}

    # Register root schema anchor or ID if present
    root_anchor = data.get("$anchor") or data.get("$dynamicAnchor")
    if root_anchor:
        anchor_map[str(root_anchor)] = file_nid
        anchor_map[f"#{root_anchor}"] = file_nid

    root_id = str(data.get("$id") or data.get("id") or "")
    if root_id:
        if root_id.startswith("#"):
            frag = root_id.lstrip("#")
            anchor_map[frag] = file_nid
            anchor_map[f"#{frag}"] = file_nid
        elif "#" in root_id:
            frag = root_id.split("#", 1)[1]
            if frag:
                anchor_map[frag] = file_nid
                anchor_map[f"#{frag}"] = file_nid

    # Collect definitions recursively across both 'definitions' and '$defs'
    def _scan_definitions(obj_dict: dict[str, Any], prefix: str = "") -> None:
        raw_defs: dict[str, Any] = {}
        if isinstance(obj_dict.get("definitions"), dict):
            raw_defs.update(obj_dict["definitions"])
        if isinstance(obj_dict.get("$defs"), dict):
            raw_defs.update(obj_dict["$defs"])

        for def_name, def_body in raw_defs.items():
            if not isinstance(def_body, dict):
                continue
            full_def_name = f"{prefix}/{def_name}" if prefix else str(def_name)
            def_nid = _make_id("schema_def", str_path, full_def_name)
            def_map[full_def_name] = def_nid
            if str(def_name) not in def_map:
                def_map[str(def_name)] = def_nid

            # Check for anchors or IDs inside definition
            if "$anchor" in def_body:
                a_val = str(def_body["$anchor"])
                anchor_map[a_val] = def_nid
                anchor_map[f"#{a_val}"] = def_nid

            if "$dynamicAnchor" in def_body:
                da_val = str(def_body["$dynamicAnchor"])
                anchor_map[da_val] = def_nid
                anchor_map[f"#{da_val}"] = def_nid

            # Draft-04 id or Draft-07/2020-12 $id as anchor (e.g. "#Address" or "Address")
            inner_id = str(def_body.get("$id") or def_body.get("id") or "")
            if inner_id.startswith("#"):
                frag = inner_id.lstrip("#")
                anchor_map[frag] = def_nid
                anchor_map[f"#{frag}"] = def_nid
            elif "#" in inner_id:
                frag = inner_id.split("#", 1)[1]
                if frag:
                    anchor_map[frag] = def_nid
                    anchor_map[f"#{frag}"] = def_nid
            elif inner_id and not inner_id.startswith(("http://", "https://", "/")):
                anchor_map[inner_id] = def_nid
                anchor_map[f"#{inner_id}"] = def_nid

            def_node = {
                "id": def_nid,
                "label": f"Schema:Def:{def_name}",
                "type": "schema_definition",
                "file_type": "code",
                "def_name": str(def_name),
                "full_name": full_def_name,
                "dialect": dialect,
                "source_file": str_path,
                "source_location": "L1",
                "text": f"Schema definition {def_name} ({dialect})",
            }
            nodes.append(def_node)
            edges.append({
                "source": file_nid,
                "target": def_nid,
                "relation": "defines_schema",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })

            # Recursively scan for nested definitions within this definition
            _scan_definitions(def_body, full_def_name)

    _scan_definitions(data)

    # Recursive scan for nested anchors ($anchor, $dynamicAnchor, or id: "#...")
    def _find_nested_anchors(obj: Any, path_prefix: str = "") -> None:
        if isinstance(obj, dict):
            for anchor_key in ("$anchor", "$dynamicAnchor"):
                if anchor_key in obj:
                    anchor_name = str(obj[anchor_key])
                    if anchor_name not in anchor_map:
                        anchor_nid = _make_id("schema_anchor", str_path, anchor_name)
                        anchor_map[anchor_name] = anchor_nid
                        anchor_map[f"#{anchor_name}"] = anchor_nid
                        nodes.append({
                            "id": anchor_nid,
                            "label": f"Schema:Anchor:{anchor_name}",
                            "type": "schema_anchor",
                            "file_type": "code",
                            "anchor_name": anchor_name,
                            "dialect": dialect,
                            "source_file": str_path,
                            "source_location": "L1",
                            "text": f"Schema anchor {anchor_name} ({dialect})",
                        })
                        edges.append({
                            "source": file_nid,
                            "target": anchor_nid,
                            "relation": "defines_schema",
                            "confidence": "EXTRACTED",
                            "weight": 1.0,
                            "source_file": str_path,
                            "source_location": "L1",
                        })

            inner_id = str(obj.get("$id") or obj.get("id") or "")
            if inner_id.startswith("#"):
                frag = inner_id.lstrip("#")
                if frag and frag not in anchor_map:
                    anchor_nid = _make_id("schema_anchor", str_path, frag)
                    anchor_map[frag] = anchor_nid
                    anchor_map[f"#{frag}"] = anchor_nid
                    nodes.append({
                        "id": anchor_nid,
                        "label": f"Schema:Anchor:{frag}",
                        "type": "schema_anchor",
                        "file_type": "code",
                        "anchor_name": frag,
                        "dialect": dialect,
                        "source_file": str_path,
                        "source_location": "L1",
                        "text": f"Schema anchor {frag} ({dialect})",
                    })
                    edges.append({
                        "source": file_nid,
                        "target": anchor_nid,
                        "relation": "defines_schema",
                        "confidence": "EXTRACTED",
                        "weight": 1.0,
                        "source_file": str_path,
                        "source_location": "L1",
                    })

            for k, v in obj.items():
                _find_nested_anchors(v, f"{path_prefix}/{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _find_nested_anchors(item, f"{path_prefix}[{i}]")

    _find_nested_anchors(data)
    return def_map, anchor_map


def _resolve_and_extract_refs(
    str_path: str,
    source_nid: str,
    obj: Any,
    def_map: dict[str, str],
    anchor_map: dict[str, str],
    edges: list[dict[str, Any]],
) -> None:
    """Traverse subschemas and resolve $ref / $dynamicRef uniformly across dialects."""
    if isinstance(obj, dict):
        ref_target = obj.get("$ref") or obj.get("$dynamicRef")
        if ref_target:
            ref_str = str(ref_target).strip()
            target_nid = ""

            if ref_str.startswith("#"):
                # Internal fragment reference
                # Can be: #/definitions/User, #/$defs/User, #UserAnchor, #/properties/user
                if ref_str.startswith("#/definitions/"):
                    frag = ref_str[len("#/definitions/"):]
                elif ref_str.startswith("#/$defs/"):
                    frag = ref_str[len("#/$defs/"):]
                elif ref_str.startswith("#/"):
                    frag = ref_str[2:]
                else:
                    frag = ref_str.lstrip("#")

                # In case of nested pointer like 'User/properties/name' or '$defs/Address'
                base_name = frag.split("/")[0] if "/" in frag else frag
                leaf_name = frag.split("/")[-1] if "/" in frag else frag

                if frag in anchor_map:
                    target_nid = anchor_map[frag]
                elif ref_str in anchor_map:
                    target_nid = anchor_map[ref_str]
                elif base_name in anchor_map:
                    target_nid = anchor_map[base_name]
                elif leaf_name in anchor_map:
                    target_nid = anchor_map[leaf_name]
                elif frag in def_map:
                    target_nid = def_map[frag]
                elif base_name in def_map:
                    target_nid = def_map[base_name]
                elif leaf_name in def_map:
                    target_nid = def_map[leaf_name]
                else:
                    target_nid = _make_id("schema_def", str_path, base_name or frag)
            else:
                # External reference
                if "#" in ref_str:
                    file_part, frag_part = ref_str.split("#", 1)
                    if frag_part.startswith("/definitions/"):
                        frag_name = frag_part[len("/definitions/"):]
                    elif frag_part.startswith("/$defs/"):
                        frag_name = frag_part[len("/$defs/"):]
                    elif frag_part.startswith("/"):
                        frag_name = frag_part.lstrip("/")
                    else:
                        frag_name = frag_part

                    if "/" in frag_name:
                        frag_name = frag_name.split("/")[0]
                else:
                    file_part = ref_str
                    frag_name = ""

                if file_part and not file_part.startswith(("http://", "https://")):
                    try:
                        resolved_path = (Path(str_path).parent / file_part).resolve()
                        if frag_name:
                            target_nid = _make_id("schema_def", str(resolved_path), frag_name)
                        else:
                            target_nid = _make_id(str(resolved_path))
                    except Exception:
                        target_nid = _make_id("ref", ref_str)
                else:
                    if frag_name:
                        target_nid = _make_id("schema_def", file_part, frag_name)
                    else:
                        target_nid = _make_id("ref", ref_str)

            edges.append({
                "source": source_nid,
                "target": target_nid,
                "relation": "references_schema",
                "ref_uri": ref_str,
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })

        for v in obj.values():
            _resolve_and_extract_refs(str_path, source_nid, v, def_map, anchor_map, edges)
    elif isinstance(obj, list):
        for item in obj:
            _resolve_and_extract_refs(str_path, source_nid, item, def_map, anchor_map, edges)


def extract_json_schema_data(
    str_path: str,
    file_nid: str,
    file_name: str,
    data: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """Core extraction logic for JSON Schema with dialect normalization and registry mappings."""
    # Handle embedded schemas (e.g. Confluent Schema Registry JSON payload or AWS Glue payload)
    inner_schema_data: dict[str, Any] | None = None
    embedded = data.get("schema") or data.get("schemaDefinition")
    if isinstance(embedded, str):
        try:
            parsed = json.loads(embedded)
            if isinstance(parsed, dict):
                inner_schema_data = parsed
        except Exception:
            pass
    elif isinstance(embedded, dict):
        inner_schema_data = embedded

    # Target schema dictionary to extract definitions and refs from
    target_schema = inner_schema_data if inner_schema_data is not None else data

    # Check if this is primarily a client config (has registry url/subject and broker/topic, but no schema keywords)
    is_pure_client_config = False
    has_schema_keywords = any(
        k in target_schema for k in ("$schema", "definitions", "$defs", "type", "properties", "items", "$id", "id", "title")
    )
    has_registry_or_kafka = any(
        k in data
        for k in (
            "schema.registry.url", "schema_registry_url", "schemaRegistryUrl",
            "schema.registry.subject", "schema_registry_subject",
            "schema_arn", "schemaArn", "bootstrap.servers", "broker.id",
        )
    )
    if inner_schema_data is not None:
        is_pure_client_config = False
    elif has_registry_or_kafka and not has_schema_keywords:
        is_pure_client_config = True

    dialect = detect_dialect(target_schema)
    title = target_schema.get("title") or Path(file_name).stem
    schema_id_uri = str(target_schema.get("$id") or target_schema.get("id") or "")

    if is_pure_client_config:
        config_node: dict[str, Any] = {
            "id": file_nid,
            "label": f"Kafka:ClientConfig:{file_name}",
            "type": "kafka_client_config",
            "file_type": "code",
            "source_file": str_path,
            "source_location": "L1",
            "text": f"Kafka client configuration {file_name}",
        }
        nodes.append(config_node)
    else:
        schema_node: dict[str, Any] = {
            "id": file_nid,
            "label": f"Schema:{title}",
            "type": "json_schema",
            "file_type": "code",
            "title": str(title),
            "dialect": dialect,
            "$schema": str(target_schema.get("$schema") or ""),
            "schema_id": schema_id_uri,
            "source_file": str_path,
            "source_location": "L1",
            "text": f"JSON Schema {title} ({dialect}) in {file_name}",
        }
        nodes.append(schema_node)

        # 1. Subschemas and Anchors across dialects
        def_map, anchor_map = _collect_subschemas_and_anchors(
            target_schema, str_path, file_nid, dialect, nodes, edges
        )

        # 2. Uniform $ref and $dynamicRef resolution
        raw_defs: dict[str, Any] = {}
        if isinstance(target_schema.get("definitions"), dict):
            raw_defs.update(target_schema["definitions"])
        if isinstance(target_schema.get("$defs"), dict):
            raw_defs.update(target_schema["$defs"])

        for def_name, def_body in raw_defs.items():
            if isinstance(def_body, dict):
                def_nid = def_map.get(str(def_name), _make_id("schema_def", str_path, str(def_name)))
                _resolve_and_extract_refs(str_path, def_nid, def_body, def_map, anchor_map, edges)

        # At top-level / properties
        _resolve_and_extract_refs(str_path, file_nid, target_schema, def_map, anchor_map, edges)

    # 3. Schema Registry Mappings
    reg_info = detect_schema_registry_info(Path(str_path), data)

    # Create Schema Registry node if URL or AWS Glue config is detected
    registry_nid = ""
    if reg_info["registry_url"]:
        reg_type = reg_info["registry_type"] or "confluent"
        if reg_type == "apicurio":
            registry_nid = _make_id("apicurio_registry", reg_info["registry_url"])
            nodes.append({
                "id": registry_nid,
                "label": f"Apicurio:Registry:{reg_info['registry_url']}",
                "type": "schema_registry",
                "file_type": "code",
                "registry_type": "apicurio",
                "url": reg_info["registry_url"],
                "source_file": str_path,
                "source_location": "L1",
                "text": f"Apicurio Schema Registry at {reg_info['registry_url']}",
            })
        else:
            registry_nid = _make_id("schema_registry", reg_info["registry_url"])
            nodes.append({
                "id": registry_nid,
                "label": f"SchemaRegistry:{reg_info['registry_url']}",
                "type": "schema_registry",
                "file_type": "code",
                "registry_type": "confluent",
                "url": reg_info["registry_url"],
                "source_file": str_path,
                "source_location": "L1",
                "text": f"Confluent Schema Registry at {reg_info['registry_url']}",
            })
        edges.append({
            "source": file_nid,
            "target": registry_nid,
            "relation": "configures_registry",
            "confidence": "EXTRACTED",
            "weight": 1.0,
            "source_file": str_path,
            "source_location": "L1",
        })
    elif reg_info["schema_arn"] or reg_info["registry_name"]:
        reg_name = reg_info["registry_name"] or "default-registry"
        registry_nid = _make_id("aws_glue_registry", reg_name)
        nodes.append({
            "id": registry_nid,
            "label": f"AWS:GlueSchemaRegistry:{reg_name}",
            "type": "schema_registry",
            "file_type": "code",
            "registry_type": "aws_glue",
            "registry_name": reg_name,
            "schema_arn": reg_info["schema_arn"],
            "source_file": str_path,
            "source_location": "L1",
            "text": f"AWS Glue Schema Registry {reg_name}",
        })
        edges.append({
            "source": file_nid,
            "target": registry_nid,
            "relation": "configures_registry",
            "confidence": "EXTRACTED",
            "weight": 1.0,
            "source_file": str_path,
            "source_location": "L1",
        })

    # Create Schema Subject node (`Schema:Subject:<name>`) if subject detected
    subject_nid = ""
    if reg_info["subject"]:
        subj = reg_info["subject"]
        subject_nid = _make_id("schema_subject", subj)
        nodes.append({
            "id": subject_nid,
            "label": f"Schema:Subject:{subj}",
            "type": "schema_subject",
            "file_type": "code",
            "subject_name": subj,
            "registry_type": reg_info["registry_type"] or "confluent",
            "strategy": reg_info["strategy"],
            "schema_arn": reg_info["schema_arn"],
            "source_file": str_path,
            "source_location": "L1",
            "text": f"Schema subject {subj} ({reg_info['strategy'] or 'TopicNameStrategy'})",
        })
        # Link client config or schema file to schema subject
        edges.append({
            "source": file_nid,
            "target": subject_nid,
            "relation": "references-schema-subject",
            "confidence": "EXTRACTED",
            "weight": 1.0,
            "source_file": str_path,
            "source_location": "L1",
        })
        # If this is a schema definition file, link subject to schema file
        if not is_pure_client_config:
            edges.append({
                "source": subject_nid,
                "target": file_nid,
                "relation": "conforms-to-schema",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })

        if registry_nid:
            edges.append({
                "source": registry_nid,
                "target": subject_nid,
                "relation": "registers_subject",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })

    # Confluent Schema Registry references to other subjects
    for ref_item in reg_info["references"]:
        if isinstance(ref_item, dict):
            ref_subj = ref_item.get("subject")
            if ref_subj and subject_nid:
                ref_subj_nid = _make_id("schema_subject", str(ref_subj))
                # Ensure referenced schema subject node exists
                if not any(n["id"] == ref_subj_nid for n in nodes):
                    nodes.append({
                        "id": ref_subj_nid,
                        "label": f"Schema:Subject:{ref_subj}",
                        "type": "schema_subject",
                        "file_type": "code",
                        "subject_name": str(ref_subj),
                        "registry_type": reg_info["registry_type"] or "confluent",
                        "source_file": str_path,
                        "source_location": "L1",
                        "text": f"Referenced Schema subject {ref_subj}",
                    })
                edges.append({
                    "source": subject_nid,
                    "target": ref_subj_nid,
                    "relation": "references-schema-subject",
                    "confidence": "EXTRACTED",
                    "weight": 1.0,
                    "source_file": str_path,
                    "source_location": "L1",
                })

    # Connect client config directly to schema file if specified
    if reg_info["schema_file"]:
        try:
            resolved_schema = (Path(str_path).parent / reg_info["schema_file"]).resolve()
            schema_file_nid = _make_id(str(resolved_schema))
            edges.append({
                "source": file_nid,
                "target": schema_file_nid,
                "relation": "conforms-to-schema",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })
        except Exception:
            pass

    # Connect Kafka topic node if topic is identified
    if reg_info["topic"]:
        topic = reg_info["topic"]
        topic_nid = _make_id("kafka_topic", topic)
        nodes.append({
            "id": topic_nid,
            "label": f"Kafka:Topic:{topic}",
            "type": "kafka_topic",
            "file_type": "code",
            "topic_name": topic,
            "source_file": str_path,
            "source_location": "L1",
            "text": f"Kafka topic {topic}",
        })

        if is_pure_client_config:
            # Client config configures/uses topic
            edges.append({
                "source": file_nid,
                "target": topic_nid,
                "relation": "configures_topic",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })
            # Connect Kafka topic to schema file if schema file is referenced
            if reg_info["schema_file"]:
                try:
                    resolved_schema = (Path(str_path).parent / reg_info["schema_file"]).resolve()
                    schema_file_nid = _make_id(str(resolved_schema))
                    edges.append({
                        "source": topic_nid,
                        "target": schema_file_nid,
                        "relation": "conforms-to-schema",
                        "confidence": "EXTRACTED",
                        "weight": 1.0,
                        "source_file": str_path,
                        "source_location": "L1",
                    })
                except Exception:
                    pass
        else:
            # Connect Kafka topic to schema file with conforms-to-schema
            edges.append({
                "source": topic_nid,
                "target": file_nid,
                "relation": "conforms-to-schema",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })

        # Connect Kafka topic to schema subject with references-schema-subject
        if subject_nid:
            edges.append({
                "source": topic_nid,
                "target": subject_nid,
                "relation": "references-schema-subject",
                "confidence": "EXTRACTED",
                "weight": 1.0,
                "source_file": str_path,
                "source_location": "L1",
            })


def extract_json_schema(path: Path) -> dict[str, Any]:
    """Extract JSON Schema file into graph nodes and edges."""
    str_path = str(path.resolve())
    file_nid = _make_id(str_path)
    file_name = path.name

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    content = path.read_text(encoding="utf-8", errors="replace")
    data: dict[str, Any] | None = None
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(content)
        except Exception:
            pass

    if data is None:
        try:
            loaded = yaml.safe_load(content)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            pass

    if data is None:
        # Check if this is a .properties / key-value file
        props: dict[str, Any] = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
        if props:
            data = props

    if not isinstance(data, dict):
        return {"nodes": nodes, "edges": edges}

    extract_json_schema_data(str_path, file_nid, file_name, data, nodes, edges)
    return {"nodes": nodes, "edges": edges}
