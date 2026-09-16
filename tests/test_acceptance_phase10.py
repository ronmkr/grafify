"""Phase 10 Acceptance Test: Multi-format build and deterministic lint with network blocked.

Verifies:
1. `graphify build` completes successfully on a folder containing:
   - Helm charts
   - K8s manifests
   - Terraform files (across environments: staging vs prod)
   - CloudFormation templates
   - Kafka configs and schemas (.properties, .avsc)
   - GitHub Actions workflows (.github/workflows/*.yml)
   - JSON Schemas (*.schema.json)
   - Dockerfile & Docker Compose (compose.yaml)
   - OpenAPI & AsyncAPI specs
   - SQL DDL (*.sql)
   - Package manifests (package.json, requirements.txt, poetry.lock)
   - Bazel (BUILD.bazel)
   - Monorepo configs (pnpm-workspace.yaml, turbo.json)
   - Argo CD GitOps manifests
2. `graphify lint` correctly flags deliberately introduced drift/lint issues:
   - Unpinned GitHub Actions uses: (e.g. actions/checkout@v4)
   - Environment drift (resource in staging missing from prod)
   - Missing secret definitions (referenced secret never defined)
3. Zero outbound network requests during extraction and build.
"""
from __future__ import annotations

import socket
from pathlib import Path
import pytest

from graphify.extract import extract, collect_files
from graphify.build import build_from_json
from graphify.lint import run_lint


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Enforce strictly zero outbound network requests during acceptance testing."""
    def _guarded_connect(*args, **kwargs):
        raise RuntimeError("Network blocked: unexpected outbound network call during local graphify run")

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)


def _write(root: Path, rel_path: str, content: str) -> Path:
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_phase10_full_multiformat_acceptance(tmp_path: Path):
    # 1. Helm Chart
    _write(tmp_path, "charts/web/Chart.yaml", """\
apiVersion: v2
name: web
version: 1.0.0
""")
    _write(tmp_path, "charts/web/templates/deployment.yaml", """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: myorg/web:1.0.0
""")

    # 2. Kubernetes manifests (defined secret!)
    _write(tmp_path, "k8s/service.yaml", """\
apiVersion: v1
kind: Service
metadata:
  name: web-svc
spec:
  selector:
    app: web
  ports:
    - port: 80
""")
    _write(tmp_path, "k8s/secret.yaml", """\
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
stringData:
  password: supersecretpassword
""")

    # 3. Terraform (staging has sqs queue; prod does NOT -> environment drift!)
    _write(tmp_path, "environments/staging/main.tf", """\
resource "aws_sqs_queue" "staging_jobs_queue" {
  name = "staging-jobs-queue"
}
resource "aws_s3_bucket" "app_assets" {
  bucket = "app-assets-staging"
}
""")
    _write(tmp_path, "environments/prod/main.tf", """\
resource "aws_s3_bucket" "app_assets" {
  bucket = "app-assets-prod"
}
""")

    # 4. CloudFormation
    _write(tmp_path, "aws/cfn-template.yaml", """\
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  AssetsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: app-assets-staging
""")

    # 5. Kafka config and Avro schema
    _write(tmp_path, "kafka/server.properties", """\
broker.id=1
listeners=PLAINTEXT://:9092
""")
    _write(tmp_path, "kafka/order.avsc", """\
{
  "type": "record",
  "name": "OrderEvent",
  "namespace": "com.orders",
  "fields": [
    {"name": "orderId", "type": "string"},
    {"name": "amount", "type": "double"}
  ]
}
""")

    # 6. GitHub Actions (unpinned actions/checkout@v4 and missing secret STRIPE_KEY!)
    _write(tmp_path, ".github/workflows/deploy.yml", """\
name: Deploy
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Build
        env:
          PAYMENT_SECRET: ${{ secrets.STRIPE_KEY }}
          DB_PASS: ${{ secrets.db-credentials }}
        run: npm run build
""")

    # 7. JSON Schema
    _write(tmp_path, "schemas/user.schema.json", """\
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "UserProfile",
  "type": "object",
  "properties": {
    "username": {"type": "string"}
  }
}
""")

    # 8. Dockerfile and Docker Compose
    _write(tmp_path, "Dockerfile", """\
FROM node:18-alpine
WORKDIR /app
COPY . .
CMD ["node", "server.js"]
""")
    _write(tmp_path, "compose.yaml", """\
services:
  web:
    image: myorg/web:1.0.0
    ports:
      - "3000:3000"
""")

    # 9. OpenAPI & AsyncAPI specs
    _write(tmp_path, "api/openapi.yaml", """\
openapi: "3.0.3"
info:
  title: Web API
  version: "1.0.0"
paths:
  /users:
    get:
      summary: Get users
      responses:
        '200':
          description: OK
""")
    _write(tmp_path, "api/asyncapi.yaml", """\
asyncapi: "2.6.0"
info:
  title: Events Service
  version: "1.0.0"
channels:
  user.signup:
    publish:
      message:
        name: UserSignup
""")

    # 10. SQL DDL
    _write(tmp_path, "db/schema.sql", """\
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL
);
""")

    # 11. Package manifests
    _write(tmp_path, "package.json", """\
{
  "name": "full-stack-app",
  "version": "1.0.0",
  "dependencies": {
    "react": "^18.2.0"
  }
}
""")
    _write(tmp_path, "requirements.txt", """\
pydantic>=2.0.0
fastapi>=0.100.0
""")

    # 12. Bazel
    _write(tmp_path, "BUILD.bazel", """\
cc_library(
    name = "core_util",
    srcs = ["util.cc"],
    hdrs = ["util.h"],
)
""")

    # 13. Monorepo configs
    _write(tmp_path, "pnpm-workspace.yaml", """\
packages:
  - 'packages/*'
""")
    _write(tmp_path, "turbo.json", """\
{
  "pipeline": {
    "build": {}
  }
}
""")

    # 14. Argo CD manifest
    _write(tmp_path, "argocd/application.yaml", """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: web-gitops
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/myorg/monorepo.git
    path: charts/web
  destination:
    server: https://kubernetes.default.svc
    namespace: default
""")

    # -----------------------------------------------------------------------
    # Step A: Collect and Extract all files
    # -----------------------------------------------------------------------
    files = collect_files(tmp_path, all_formats=True)
    assert len(files) >= 14, f"Expected at least 14 collected files, got {len(files)}"

    extraction = extract(files, root=tmp_path)
    nodes = extraction.get("nodes", [])
    edges = extraction.get("edges", [])

    assert len(nodes) > 15, "Extraction should produce nodes across all formats"
    assert len(edges) > 5, "Extraction should produce edges across formats"

    # Verify nodes exist from diverse formats
    labels = {n.get("label", "") for n in nodes}
    assert any("Helm:Chart:web" in l for l in labels)
    assert any("K8s:Deployment:web-app" in l for l in labels)
    assert any("K8s:Secret:db-credentials" in l for l in labels)
    assert any("API:Web API" in l for l in labels)
    assert any("AsyncAPI:Events Service" in l for l in labels)
    assert any("Docker:Service:web" in l for l in labels)
    assert any("Bazel:core_util" in l for l in labels)
    assert any("Monorepo:pnpm-workspace" in l for l in labels)
    assert any("Argo:Application:web-gitops" in l for l in labels)

    # -----------------------------------------------------------------------
    # Step B: Build NetworkX Graph and Cross-Format Resolution
    # -----------------------------------------------------------------------
    G = build_from_json(extraction, directed=False, root=tmp_path)
    assert G.number_of_nodes() > 15
    assert G.number_of_edges() > 5

    # -----------------------------------------------------------------------
    # Step C: Deterministic Lint Rules on Fixtures
    # -----------------------------------------------------------------------
    lint_res = run_lint(extraction, check_orphans=False)
    findings = lint_res.get("findings", [])
    rules = [f.get("rule") for f in findings]

    # 1. Flag unpinned GitHub Action: actions/checkout@v4
    assert "unpinned_github_action" in rules
    unpinned_findings = [f for f in findings if f["rule"] == "unpinned_github_action"]
    assert any("checkout" in f.get("action", "") and "v4" in f.get("pin", "") for f in unpinned_findings)

    # 2. Flag Environment Drift: staging has SQS jobs queue, prod does not!
    assert "environment_drift" in rules
    drift_findings = [f for f in findings if f["rule"] == "environment_drift"]
    assert any("jobs" in f.get("resource", "") for f in drift_findings)

    # 3. Flag Missing Secret: STRIPE_KEY is referenced in GHA but never defined
    assert "missing_secret_definition" in rules
    missing_secrets = [f.get("name") for f in findings if f["rule"] == "missing_secret_definition"]
    assert "stripe_key" in missing_secrets or "STRIPE_KEY" in missing_secrets
    # Defined secret db-credentials must NOT be flagged as missing
    assert "db-credentials" not in missing_secrets and "db_credentials" not in missing_secrets
