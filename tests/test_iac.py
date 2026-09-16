"""Tests for Infrastructure-as-Code (IaC) and config extractors."""
from __future__ import annotations

import json
from pathlib import Path

from graphify.detect import classify_file, FileType
from graphify.extract import _get_extractor
from graphify.extractors.iac import (
    extract_avro,
    extract_cloudformation,
    extract_helm,
    extract_kafka_properties,
    extract_kubernetes,
    extract_protobuf,
    is_cloudformation_template,
    is_helm_chart_file,
    is_kafka_config,
    is_kubernetes_manifest,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _labels(r: dict) -> list[str]:
    return [n["label"] for n in r["nodes"]]


def _rel_pairs(r: dict, relation: str) -> set[tuple[str, str]]:
    lab = {n["id"]: n["label"] for n in r["nodes"]}
    return {
        (lab.get(e["source"], e["source"]), lab.get(e["target"], e["target"]))
        for e in r["edges"]
        if e["relation"] == relation
    }


def test_kubernetes_multi_doc_manifest(tmp_path):
    k8s_yaml = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  namespace: prod
  labels:
    app: api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
      - name: api
        image: myrepo/api:v1.2.3
        volumeMounts:
        - name: config-volume
          mountPath: /etc/config
      volumes:
      - name: config-volume
        configMap:
          name: api-config
---
apiVersion: v1
kind: Service
metadata:
  name: api-service
  namespace: prod
spec:
  selector:
    app: api
  ports:
  - port: 80
    targetPort: 8080
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: api-config
  namespace: prod
data:
  DB_HOST: "postgres.internal"
"""
    p = _write(tmp_path, "deploy.yaml", k8s_yaml)
    assert is_kubernetes_manifest(p)
    assert classify_file(p) == FileType.CODE
    assert _get_extractor(p) == extract_kubernetes

    res = extract_kubernetes(p)
    assert res.get("error") is None

    labels = set(_labels(res))
    assert "K8s:Deployment:prod/api-server" in labels
    assert "K8s:Service:prod/api-service" in labels
    assert "K8s:ConfigMap:prod/api-config" in labels
    assert "Image:myrepo/api:v1.2.3" in labels

    # Check relationships
    mounts = _rel_pairs(res, "mounts")
    assert ("K8s:Deployment:prod/api-server", "K8s:ConfigMap:prod/api-config") in mounts

    selects = _rel_pairs(res, "selects")
    assert ("K8s:Service:prod/api-service", "K8s:Deployment:prod/api-server") in selects

    uses_img = _rel_pairs(res, "uses_image")
    assert ("K8s:Deployment:prod/api-server", "Image:myrepo/api:v1.2.3") in uses_img


def test_helm_chart_extraction(tmp_path):
    chart_dir = tmp_path / "mychart"
    chart_yaml = """\
apiVersion: v2
name: mychart
description: Helm chart for test service
version: 0.1.0
dependencies:
  - name: postgresql
    version: 12.1.0
    repository: https://charts.bitnami.com/bitnami
  - name: redis
    version: 17.0.0
"""
    values_yaml = """\
replicaCount: 2
image:
  repository: nginx
  tag: stable
service:
  type: ClusterIP
  port: 80
"""
    deploy_tpl = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "mychart.fullname" . }}
  labels:
    {{- include "mychart.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: {{ include "mychart.name" . }}
  template:
    metadata:
      labels:
        app: {{ include "mychart.name" . }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
"""
    chart_p = _write(chart_dir, "Chart.yaml", chart_yaml)
    values_p = _write(chart_dir, "values.yaml", values_yaml)
    deploy_p = _write(chart_dir, "templates/deployment.yaml", deploy_tpl)

    assert is_helm_chart_file(chart_p)
    assert is_helm_chart_file(values_p)
    assert is_helm_chart_file(deploy_p)

    # Chart.yaml extraction
    res_chart = extract_helm(chart_p)
    labels_chart = set(_labels(res_chart))
    assert "Helm:Chart:mychart" in labels_chart
    assert "Helm:Chart:postgresql" in labels_chart
    assert "Helm:Chart:redis" in labels_chart
    dep_pairs = _rel_pairs(res_chart, "depends_on")
    assert ("Helm:Chart:mychart", "Helm:Chart:postgresql") in dep_pairs

    # values.yaml extraction
    res_values = extract_helm(values_p)
    labels_values = set(_labels(res_values))
    assert "Helm:Values:mychart" in labels_values
    defines = _rel_pairs(res_values, "defines")
    assert any(tgt.startswith("Helm:Values:") for _, tgt in defines)

    # masked template extraction
    res_tpl = extract_helm(deploy_p)
    assert res_tpl.get("error") is None
    labels_tpl = set(_labels(res_tpl))
    assert any("Deployment" in l for l in labels_tpl)


def test_cloudformation_sam_template(tmp_path):
    cfn_yaml = """\
AWSTemplateFormatVersion: '2010-09-09'
Transform: 'AWS::Serverless-2016-10-31'
Description: Serverless API sample

Parameters:
  EnvName:
    Type: String
    Default: dev

Resources:
  ApiFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: index.handler
      Runtime: python3.12
      Environment:
        Variables:
          TABLE_NAME: !Ref MainTable
    DependsOn:
      - MainTable

  MainTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub "${EnvName}-items"
      BillingMode: PAY_PER_REQUEST

Outputs:
  ApiUrl:
    Description: Function Arn
    Value: !GetAtt ApiFunction.Arn
"""
    p = _write(tmp_path, "template.yaml", cfn_yaml)
    assert is_cloudformation_template(p)
    assert classify_file(p) == FileType.CODE
    assert _get_extractor(p) == extract_cloudformation

    res = extract_cloudformation(p)
    assert res.get("error") is None
    labels = set(_labels(res))
    assert "AWS:Serverless::Function:ApiFunction" in labels
    assert "AWS:DynamoDB::Table:MainTable" in labels
    assert "AWS:Parameter:EnvName" in labels
    assert "AWS:Output:ApiUrl" in labels

    # DependsOn edge
    depends_on = _rel_pairs(res, "depends_on")
    assert ("AWS:Serverless::Function:ApiFunction", "AWS:DynamoDB::Table:MainTable") in depends_on

    # Fn::Ref edge
    refs = _rel_pairs(res, "references")
    assert ("AWS:Serverless::Function:ApiFunction", "AWS:DynamoDB::Table:MainTable") in refs


def test_kafka_properties_config(tmp_path):
    server_props = """\
broker.id=1
listeners=PLAINTEXT://:9092
zookeeper.connect=localhost:2181
num.partitions=3
default.replication.factor=1
log.dirs=/var/lib/kafka/data
"""
    p = _write(tmp_path, "server.properties", server_props)
    assert is_kafka_config(p)
    assert classify_file(p) == FileType.CODE
    assert _get_extractor(p) == extract_kafka_properties

    res = extract_kafka_properties(p)
    labels = set(_labels(res))
    assert "Kafka:Broker:1" in labels
    assert "Kafka:Zookeeper:localhost:2181" in labels
    connects_to = _rel_pairs(res, "connects_to")
    assert ("Kafka:Broker:1", "Kafka:Zookeeper:localhost:2181") in connects_to


def test_avro_schema_extraction(tmp_path):
    avro_json = {
        "type": "record",
        "name": "UserOrderEvent",
        "namespace": "com.example.events",
        "doc": "User order placement event",
        "fields": [
            {"name": "order_id", "type": "string"},
            {"name": "user_id", "type": "string"},
            {"name": "amount", "type": "double"}
        ]
    }
    p = _write(tmp_path, "UserOrderEvent.avsc", json.dumps(avro_json))
    assert classify_file(p) == FileType.CODE
    assert _get_extractor(p) == extract_avro

    res = extract_avro(p)
    labels = set(_labels(res))
    assert "Kafka:Avro:com.example.events.UserOrderEvent" in labels


def test_protobuf_schema_extraction(tmp_path):
    proto_body = """\
syntax = "proto3";

package analytics.stream;

message EventPayload {
  string event_id = 1;
  string timestamp = 2;
  bytes data = 3;
}

service IngestionService {
  rpc PublishEvent (EventPayload) returns (EventResponse);
}
"""
    p = _write(tmp_path, "events.proto", proto_body)
    assert classify_file(p) == FileType.CODE
    assert _get_extractor(p) == extract_protobuf

    res = extract_protobuf(p)
    labels = set(_labels(res))
    assert "Kafka:Proto:analytics.stream.EventPayload" in labels
    assert "Kafka:ProtoService:analytics.stream.IngestionService" in labels
