"""Unit tests for Extended JSON Schema dialects and Schema Registry mappings."""
from __future__ import annotations

import json
from pathlib import Path

from graphify.extractors.jsonschema import (
    detect_dialect,
    detect_schema_registry_info,
    extract_json_schema,
    is_json_schema,
)


def _rel_pairs(result: dict, relation: str) -> list[tuple[str, str]]:
    id_to_label = {n["id"]: n["label"] for n in result["nodes"]}
    return [
        (id_to_label.get(e["source"], e["source"]), id_to_label.get(e["target"], e["target"]))
        for e in result["edges"]
        if e["relation"] == relation
    ]


# ---------------------------------------------------------------------------
# Dialect Normalization Tests (Draft-04, Draft-07, 2020-12)
# ---------------------------------------------------------------------------


def test_draft04_normalization(tmp_path: Path):
    """Draft-04 uses `definitions`, `id`, and `#/definitions/` refs."""
    schema = {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "id": "http://example.com/order.schema.json",
        "title": "Order",
        "type": "object",
        "properties": {
            "item": {
                "$ref": "#/definitions/OrderItem",
            },
            "item_by_id": {
                "$ref": "#item_id",
            },
        },
        "definitions": {
            "OrderItem": {
                "id": "#item_id",
                "type": "object",
                "properties": {
                    "itemId": {"type": "string"},
                },
            }
        },
    }
    schema_file = tmp_path / "order.schema.json"
    schema_file.write_text(json.dumps(schema), encoding="utf-8")

    assert is_json_schema(schema_file)
    assert detect_dialect(schema) == "draft-04"

    res = extract_json_schema(schema_file)
    nodes = {n["id"]: n for n in res["nodes"]}
    labels = {n["label"] for n in res["nodes"]}

    assert "Schema:Order" in labels
    assert "Schema:Def:OrderItem" in labels

    # Both $ref to #/definitions/OrderItem and #item_id resolve to Schema:Def:OrderItem
    ref_edges = [e for e in res["edges"] if e["relation"] == "references_schema"]
    assert len(ref_edges) >= 2
    for edge in ref_edges:
        target_node = nodes.get(edge["target"])
        assert target_node is not None
        assert target_node["label"] == "Schema:Def:OrderItem"


def test_draft07_normalization(tmp_path: Path):
    """Draft-07 uses `definitions`, `$id`, and `#/definitions/` refs."""
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "http://example.com/user.schema.json",
        "title": "User",
        "type": "object",
        "properties": {
            "address": {
                "$ref": "#/definitions/Address",
            },
            "address_by_anchor": {
                "$ref": "#address_anchor",
            },
        },
        "definitions": {
            "Address": {
                "$id": "#address_anchor",
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                },
            }
        },
    }
    schema_file = tmp_path / "user.schema.json"
    schema_file.write_text(json.dumps(schema), encoding="utf-8")

    assert is_json_schema(schema_file)
    assert detect_dialect(schema) == "draft-07"

    res = extract_json_schema(schema_file)
    nodes = {n["id"]: n for n in res["nodes"]}
    labels = {n["label"] for n in res["nodes"]}

    assert "Schema:User" in labels
    assert "Schema:Def:Address" in labels

    ref_edges = [e for e in res["edges"] if e["relation"] == "references_schema"]
    assert len(ref_edges) >= 2
    for edge in ref_edges:
        target_node = nodes.get(edge["target"])
        assert target_node is not None
        assert target_node["label"] == "Schema:Def:Address"


def test_draft2020_12_normalization(tmp_path: Path):
    """2020-12 uses `$defs`, `$id`, `$anchor`, and dynamic `$ref`."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.com/customer.schema.json",
        "title": "Customer",
        "type": "object",
        "properties": {
            "primary": {
                "$ref": "#/$defs/Profile",
            },
            "by_anchor": {
                "$ref": "#profile_anchor",
            },
            "dynamic": {
                "$dynamicRef": "#profile_dyn",
            },
        },
        "$defs": {
            "Profile": {
                "$anchor": "profile_anchor",
                "$dynamicAnchor": "profile_dyn",
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                },
            }
        },
    }
    schema_file = tmp_path / "customer.schema.json"
    schema_file.write_text(json.dumps(schema), encoding="utf-8")

    assert is_json_schema(schema_file)
    assert detect_dialect(schema) == "2020-12"

    res = extract_json_schema(schema_file)
    nodes = {n["id"]: n for n in res["nodes"]}
    labels = {n["label"] for n in res["nodes"]}

    assert "Schema:Customer" in labels
    assert "Schema:Def:Profile" in labels

    ref_edges = [e for e in res["edges"] if e["relation"] == "references_schema"]
    assert len(ref_edges) >= 3
    for edge in ref_edges:
        target_node = nodes.get(edge["target"])
        assert target_node is not None
        assert target_node["label"] == "Schema:Def:Profile"


def test_cross_dialect_transparent_ref_resolution(tmp_path: Path):
    """Ensure resolving `#/definitions/...` in a 2020-12 schema and `#/$defs/...` in a Draft-07 schema work transparently."""
    # 2020-12 schema defines $defs, but consumer uses legacy #/definitions/ path
    schema2020 = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Vehicle",
        "type": "object",
        "properties": {
            "engine": {
                "$ref": "#/definitions/Engine",  # legacy pointer targeting $defs
            }
        },
        "$defs": {
            "Engine": {
                "type": "object",
                "properties": {"cylinders": {"type": "integer"}},
            }
        },
    }
    f1 = tmp_path / "vehicle.schema.json"
    f1.write_text(json.dumps(schema2020), encoding="utf-8")
    res1 = extract_json_schema(f1)
    nodes1 = {n["id"]: n for n in res1["nodes"]}
    ref_edges1 = [e for e in res1["edges"] if e["relation"] == "references_schema"]
    assert len(ref_edges1) == 1
    assert nodes1[ref_edges1[0]["target"]]["label"] == "Schema:Def:Engine"

    # Draft-07 schema defines definitions, but consumer uses modern #/$defs/ path
    schema_draft7 = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Device",
        "type": "object",
        "properties": {
            "battery": {
                "$ref": "#/$defs/Battery",  # modern pointer targeting definitions
            }
        },
        "definitions": {
            "Battery": {
                "type": "object",
                "properties": {"capacity": {"type": "integer"}},
            }
        },
    }
    f2 = tmp_path / "device.schema.json"
    f2.write_text(json.dumps(schema_draft7), encoding="utf-8")
    res2 = extract_json_schema(f2)
    nodes2 = {n["id"]: n for n in res2["nodes"]}
    ref_edges2 = [e for e in res2["edges"] if e["relation"] == "references_schema"]
    assert len(ref_edges2) == 1
    assert nodes2[ref_edges2[0]["target"]]["label"] == "Schema:Def:Battery"


def test_nested_definitions_and_anchors(tmp_path: Path):
    """Verify recursive scanning for nested definitions and nested anchors."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Organization",
        "type": "object",
        "properties": {
            "hq": {
                "$ref": "#/$defs/Dept/Location",
            },
            "security": {
                "$ref": "#SecurityBadgeAnchor",
            },
        },
        "$defs": {
            "Dept": {
                "type": "object",
                "$defs": {
                    "Location": {
                        "type": "object",
                        "properties": {
                            "badge": {
                                "$anchor": "SecurityBadgeAnchor",
                                "type": "string",
                            }
                        },
                    }
                },
            }
        },
    }
    schema_file = tmp_path / "org.schema.json"
    schema_file.write_text(json.dumps(schema), encoding="utf-8")

    res = extract_json_schema(schema_file)
    labels = {n["label"] for n in res["nodes"]}
    assert "Schema:Organization" in labels
    assert "Schema:Def:Dept" in labels
    assert "Schema:Def:Location" in labels
    assert "Schema:Anchor:SecurityBadgeAnchor" in labels

    nodes = {n["id"]: n for n in res["nodes"]}
    ref_targets = [nodes[e["target"]]["label"] for e in res["edges"] if e["relation"] == "references_schema"]
    assert "Schema:Def:Location" in ref_targets
    assert "Schema:Anchor:SecurityBadgeAnchor" in ref_targets


def test_external_cross_file_ref_resolution(tmp_path: Path):
    """Verify uniform resolution of external schema references across files."""
    common_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Common",
        "$defs": {
            "Timestamp": {"type": "string", "format": "date-time"},
        },
    }
    common_file = tmp_path / "common.schema.json"
    common_file.write_text(json.dumps(common_schema), encoding="utf-8")

    # Order schema references common using #/definitions/Timestamp
    order_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Order",
        "properties": {
            "created_at": {
                "$ref": "./common.schema.json#/definitions/Timestamp",
            },
            "updated_at": {
                "$ref": "./common.schema.json#/$defs/Timestamp",
            },
        },
    }
    order_file = tmp_path / "order.schema.json"
    order_file.write_text(json.dumps(order_schema), encoding="utf-8")

    res_common = extract_json_schema(common_file)
    res_order = extract_json_schema(order_file)

    common_def_nid = next(n["id"] for n in res_common["nodes"] if n["label"] == "Schema:Def:Timestamp")
    order_refs = [e for e in res_order["edges"] if e["relation"] == "references_schema"]

    assert len(order_refs) == 2
    # Both ./common.schema.json#/definitions/Timestamp and #/$defs/Timestamp point to identical node ID
    for edge in order_refs:
        assert edge["target"] == common_def_nid


# ---------------------------------------------------------------------------
# Schema Registry Mappings Tests
# ---------------------------------------------------------------------------


def test_confluent_schema_registry_properties(tmp_path: Path):
    """Detect Confluent Schema Registry configuration, create subject nodes and Kafka topic edges."""
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "PaymentEvent",
        "type": "object",
        "schema.registry.url": "http://schema-registry.prod:8081",
        "schema.registry.subject": "payments-value",
        "properties": {
            "paymentId": {"type": "string"},
            "amount": {"type": "number"},
        },
    }
    schema_file = tmp_path / "payment-event.json"
    schema_file.write_text(json.dumps(schema), encoding="utf-8")

    res = extract_json_schema(schema_file)
    labels = {n["label"] for n in res["nodes"]}

    assert "SchemaRegistry:http://schema-registry.prod:8081" in labels
    assert "Schema:Subject:payments-value" in labels
    assert "Kafka:Topic:payments" in labels

    # Verify relations
    ref_subjs = _rel_pairs(res, "references-schema-subject")
    conforms = _rel_pairs(res, "conforms-to-schema")
    registers = _rel_pairs(res, "registers_subject")

    assert ("Kafka:Topic:payments", "Schema:Subject:payments-value") in ref_subjs
    assert ("Kafka:Topic:payments", "Schema:PaymentEvent") in conforms
    assert ("Schema:Subject:payments-value", "Schema:PaymentEvent") in conforms
    assert ("SchemaRegistry:http://schema-registry.prod:8081", "Schema:Subject:payments-value") in registers


def test_confluent_filename_conventions(tmp_path: Path):
    """Filename conventions like <topic>-value.json and <topic>-key.json infer topic and subject."""
    val_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "UserCreatedValue",
        "type": "object",
        "properties": {"userId": {"type": "string"}},
    }
    val_file = tmp_path / "user.events-value.schema.json"
    val_file.write_text(json.dumps(val_schema), encoding="utf-8")

    res = extract_json_schema(val_file)
    labels = {n["label"] for n in res["nodes"]}

    assert "Schema:Subject:user.events-value" in labels
    assert "Kafka:Topic:user.events" in labels

    conforms = _rel_pairs(res, "conforms-to-schema")
    ref_subjs = _rel_pairs(res, "references-schema-subject")
    assert ("Kafka:Topic:user.events", "Schema:Subject:user.events-value") in ref_subjs
    assert ("Kafka:Topic:user.events", "Schema:UserCreatedValue") in conforms


def test_subject_naming_strategies(tmp_path: Path):
    """Support TopicNameStrategy, RecordNameStrategy, and TopicRecordNameStrategy."""
    # 1. TopicNameStrategy
    info1 = detect_schema_registry_info(
        tmp_path / "orders-value.json",
        {"subject": "orders-value", "subject.name.strategy": "TopicNameStrategy"},
    )
    assert info1["topic"] == "orders"
    assert info1["role"] == "value"
    assert info1["strategy"] == "TopicNameStrategy"

    # 2. RecordNameStrategy
    info2 = detect_schema_registry_info(
        tmp_path / "schema.json",
        {"subject": "com.example.orders.OrderCompleted", "strategy": "RecordNameStrategy"},
    )
    assert info2["subject"] == "com.example.orders.OrderCompleted"
    assert info2["strategy"] == "RecordNameStrategy"

    # 3. TopicRecordNameStrategy
    info3 = detect_schema_registry_info(
        tmp_path / "schema.json",
        {"subject": "orders-OrderCompleted", "strategy": "TopicRecordNameStrategy"},
    )
    assert info3["topic"] == "orders"
    assert info3["strategy"] == "TopicRecordNameStrategy"


def test_confluent_embedded_schema_payload(tmp_path: Path):
    """Extract embedded schema string from Confluent Schema Registry HTTP JSON response payload."""
    payload = {
        "subject": "telemetry-value",
        "version": 2,
        "id": 104,
        "schemaType": "JSON",
        "schema": json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "DeviceTelemetry",
            "type": "object",
            "$defs": {
                "GPS": {"type": "object", "properties": {"lat": {"type": "number"}}},
            },
            "properties": {
                "location": {"$ref": "#/$defs/GPS"},
            },
        }),
    }
    payload_file = tmp_path / "telemetry-payload.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")

    res = extract_json_schema(payload_file)
    labels = {n["label"] for n in res["nodes"]}

    assert "Schema:DeviceTelemetry" in labels
    assert "Schema:Def:GPS" in labels
    assert "Schema:Subject:telemetry-value" in labels
    assert "Kafka:Topic:telemetry" in labels


def test_confluent_schema_references(tmp_path: Path):
    """Extract schema references connecting subjects in Confluent Schema Registry."""
    payload = {
        "subject": "orders-value",
        "schema": json.dumps({
            "title": "Order",
            "properties": {"customer": {"$ref": "Customer.json"}},
        }),
        "references": [
            {
                "name": "Customer.json",
                "subject": "customer-value",
                "version": 1,
            }
        ],
    }
    payload_file = tmp_path / "orders-value.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")

    res = extract_json_schema(payload_file)
    labels = {n["label"] for n in res["nodes"]}

    assert "Schema:Subject:orders-value" in labels
    ref_subjs = _rel_pairs(res, "references-schema-subject")
    assert ("Schema:Subject:orders-value", "Schema:Subject:customer-value") in ref_subjs


def test_aws_glue_schema_registry(tmp_path: Path):
    """Detect AWS Glue Schema Registry ARN, extract registry name, subject, and topic."""
    glue_schema = {
        "schemaArn": "arn:aws:glue:us-east-1:123456789012:schema/CoreRegistry/CustomerFeedback-value",
        "schemaName": "CustomerFeedback-value",
        "registryName": "CoreRegistry",
        "dataFormat": "JSON",
        "schemaDefinition": json.dumps({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "CustomerFeedback",
            "type": "object",
            "properties": {"score": {"type": "integer"}},
        }),
    }
    glue_file = tmp_path / "glue_schema.json"
    glue_file.write_text(json.dumps(glue_schema), encoding="utf-8")

    res = extract_json_schema(glue_file)
    labels = {n["label"] for n in res["nodes"]}

    assert "AWS:GlueSchemaRegistry:CoreRegistry" in labels
    assert "Schema:Subject:CustomerFeedback-value" in labels
    assert "Kafka:Topic:CustomerFeedback" in labels
    assert "Schema:CustomerFeedback" in labels

    ref_subjs = _rel_pairs(res, "references-schema-subject")
    conforms = _rel_pairs(res, "conforms-to-schema")
    assert ("Kafka:Topic:CustomerFeedback", "Schema:Subject:CustomerFeedback-value") in ref_subjs
    assert ("Kafka:Topic:CustomerFeedback", "Schema:CustomerFeedback") in conforms


def test_apicurio_schema_registry(tmp_path: Path):
    """Detect Apicurio Schema Registry configuration."""
    apicurio_conf = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "SensorMetric",
        "apicurio.registry.url": "http://apicurio.local:8080/apis/registry/v2",
        "artifactId": "sensors-data-value",
        "properties": {"temp": {"type": "number"}},
    }
    f = tmp_path / "sensors.schema.json"
    f.write_text(json.dumps(apicurio_conf), encoding="utf-8")

    res = extract_json_schema(f)
    labels = {n["label"] for n in res["nodes"]}

    assert "Apicurio:Registry:http://apicurio.local:8080/apis/registry/v2" in labels
    assert "Schema:Subject:sensors-data-value" in labels
    assert "Kafka:Topic:sensors-data" in labels


def test_kafka_client_config_properties(tmp_path: Path):
    """Kafka client config file linking to schema registry, schema subjects, and schema files."""
    schema_file = tmp_path / "orders.schema.json"
    schema_file.write_text(json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "OrderSchema",
    }), encoding="utf-8")

    client_props = f"""
bootstrap.servers=kafka.prod:9092
schema.registry.url=http://schema-registry.prod:8081
schema.registry.subject=orders-value
topic=orders
schema.file=./orders.schema.json
"""
    props_file = tmp_path / "producer.properties"
    props_file.write_text(client_props.strip(), encoding="utf-8")

    assert is_json_schema(props_file)

    res = extract_json_schema(props_file)
    labels = {n["label"] for n in res["nodes"]}

    assert "Kafka:ClientConfig:producer.properties" in labels
    assert "SchemaRegistry:http://schema-registry.prod:8081" in labels
    assert "Schema:Subject:orders-value" in labels
    assert "Kafka:Topic:orders" in labels

    ref_subjs = _rel_pairs(res, "references-schema-subject")
    assert ("Kafka:Topic:orders", "Schema:Subject:orders-value") in ref_subjs
    assert ("Kafka:ClientConfig:producer.properties", "Schema:Subject:orders-value") in ref_subjs

    conforms = _rel_pairs(res, "conforms-to-schema")
    # File ID for orders.schema.json
    from graphify.extractors.jsonschema import _make_id
    schema_file_id = _make_id(str(schema_file.resolve()))
    conforms_targets = [e["target"] for e in res["edges"] if e["relation"] == "conforms-to-schema"]
    assert schema_file_id in conforms_targets
