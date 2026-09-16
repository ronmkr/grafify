"""Tests for extended config & IaC parsers (Option A).

Tests cover:
- GitHub Actions workflows (.github/workflows/*.yml)
- Docker Compose (compose.yaml / docker-compose.yml)
- OpenAPI 3.x, JSON Schema, and AsyncAPI specs
- Package manifests (package.json, requirements.txt, poetry.lock)
"""

from pathlib import Path
from graphify.extract import _get_extractor
from graphify.extractors.github_actions import extract_github_workflow, is_github_workflow
from graphify.extractors.docker import extract_docker_compose, is_docker_compose
from graphify.extractors.api_schema import (
    extract_api_or_schema,
    is_api_or_schema,
)
from graphify.manifest_ingest import extract_package_manifest, is_package_manifest_path


# ---------------------------------------------------------------------------
# GitHub Actions tests
# ---------------------------------------------------------------------------


def test_github_actions_extractor(tmp_path: Path):
    workflow_yaml = """
name: CI Workflow
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@0a5c61591373683505ea898e09a3ea4f39ef2b9c
      - name: Run Build
        env:
          DATABASE_URL: ${{ secrets.DB_URL }}
          API_KEY: ${{ secrets.PROD_API_KEY }}
          APP_ENV: ${{ env.ENVIRONMENT }}
        run: make build

  deploy:
    needs: [build]
    runs-on: ubuntu-latest
    steps:
      - name: Terraform Apply
        run: terraform apply -auto-approve
"""
    wf_file = tmp_path / "ci.yml"
    wf_file.write_text(workflow_yaml, encoding="utf-8")

    result = extract_github_workflow(wf_file)
    nodes = result["nodes"]
    edges = result["edges"]

    labels = {n["label"] for n in nodes}
    node_types = {n["type"] for n in nodes}
    relations = {e["relation"] for e in edges}

    # Workflow node
    assert "Workflow:CI Workflow" in labels
    assert "workflow" in node_types

    # Triggers
    assert "Trigger:push" in labels
    assert "Trigger:workflow_dispatch" in labels

    # Jobs
    assert "Job:build" in labels
    assert "Job:deploy" in labels

    # Job dependency (needs)
    assert "depends_on" in relations
    dep_edge = next(e for e in edges if e["relation"] == "depends_on")
    assert "deploy" in dep_edge["source"] and "build" in dep_edge["target"]

    # Action pins
    checkout_node = next(n for n in nodes if "checkout" in n["label"])
    assert checkout_node.get("is_sha_pinned") is False
    assert checkout_node.get("pinned_version") == "v4"

    python_node = next(n for n in nodes if "setup-python" in n["label"])
    assert python_node.get("is_sha_pinned") is True
    assert python_node.get("pinned_version") == "0a5c61591373683505ea898e09a3ea4f39ef2b9c"

    # Secret references
    assert "Secret:DB_URL" in labels
    assert "Secret:PROD_API_KEY" in labels
    assert "references_secret" in relations


# ---------------------------------------------------------------------------
# Docker Compose tests
# ---------------------------------------------------------------------------


def test_docker_compose_extractor(tmp_path: Path):
    compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
    depends_on:
      - api
    networks:
      - app-net
    volumes:
      - web-data:/usr/share/nginx/html

  api:
    build:
      context: ./backend
    environment:
      - DATABASE_URL=postgres://user:password@db:5432/app
      - SECRET_KEY
    secrets:
      - db_password
    networks:
      - app-net
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: password
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - app-net

networks:
  app-net:
    driver: bridge

volumes:
  web-data:
  pgdata:

secrets:
  db_password:
    file: ./secrets/db_password.txt
"""
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(compose_yaml, encoding="utf-8")

    assert is_docker_compose(compose_file)

    result = extract_docker_compose(compose_file)
    nodes = result["nodes"]
    edges = result["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    # Services
    assert "Docker:Service:web" in labels
    assert "Docker:Service:api" in labels
    assert "Docker:Service:db" in labels

    # Dependencies
    assert "depends_on" in relations

    # Networks & Volumes
    assert "Docker:Network:app-net" in labels
    assert "Docker:Volume:web-data" in labels
    assert "Docker:Volume:pgdata" in labels

    # Secrets & Images
    assert "Secret:db_password" in labels
    assert "Image:nginx:alpine" in labels
    assert "Image:postgres:15" in labels
    assert "uses_image" in relations
    assert "mounts" in relations
    assert "connects_to" in relations


# ---------------------------------------------------------------------------
# API Schema tests (OpenAPI, JSON Schema, AsyncAPI)
# ---------------------------------------------------------------------------


def test_openapi_spec_extractor(tmp_path: Path):
    openapi_yaml = """
openapi: "3.0.3"
info:
  title: Petstore API
  version: "1.0.0"
paths:
  /pets:
    get:
      summary: List pets
      operationId: listPets
      responses:
        '200':
          description: A list of pets
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Pet'
    post:
      summary: Create a pet
      operationId: createPet
      responses:
        '201':
          description: Created
components:
  schemas:
    Pet:
      type: object
      required:
        - id
        - name
      properties:
        id:
          type: integer
        name:
          type: string
"""
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(openapi_yaml, encoding="utf-8")

    assert is_api_or_schema(spec_file)

    result = extract_api_or_schema(spec_file)
    nodes = result["nodes"]
    edges = result["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    # API Root
    assert "API:Petstore API" in labels

    # Endpoints
    assert "API:GET /pets" in labels
    assert "API:POST /pets" in labels

    # Schemas
    assert "Schema:Pet" in labels

    # References edge
    assert "references_schema" in relations
    assert "defines_operation" in relations


def test_asyncapi_spec_extractor(tmp_path: Path):
    asyncapi_yaml = """
asyncapi: '2.6.0'
info:
  title: Order Processing Service
  version: '1.0.0'
channels:
  orders.created:
    publish:
      operationId: onOrderCreated
      message:
        $ref: '#/components/messages/OrderCreated'
components:
  messages:
    OrderCreated:
      payload:
        type: object
        properties:
          orderId:
            type: string
"""
    spec_file = tmp_path / "asyncapi.yaml"
    spec_file.write_text(asyncapi_yaml, encoding="utf-8")

    assert is_api_or_schema(spec_file)

    result = extract_api_or_schema(spec_file)
    nodes = result["nodes"]
    edges = result["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    assert "AsyncAPI:Order Processing Service" in labels
    assert "Channel:orders.created" in labels
    assert "Kafka:Topic:orders.created" in labels
    assert "defines_channel" in relations
    assert "maps_to_topic" in relations


def test_json_schema_extractor(tmp_path: Path):
    schema_json = """{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "User",
  "type": "object",
  "properties": {
    "address": {
      "$ref": "#/definitions/Address"
    }
  },
  "definitions": {
    "Address": {
      "type": "object",
      "properties": {
        "city": {"type": "string"}
      }
    }
  }
}"""
    schema_file = tmp_path / "user.schema.json"
    schema_file.write_text(schema_json, encoding="utf-8")

    assert is_api_or_schema(schema_file)

    result = extract_api_or_schema(schema_file)
    nodes = result["nodes"]
    edges = result["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    assert "Schema:User" in labels
    assert "Schema:Def:Address" in labels
    assert "defines_schema" in relations
    assert "references_schema" in relations


# ---------------------------------------------------------------------------
# Package Manifest tests
# ---------------------------------------------------------------------------


def test_manifest_package_json(tmp_path: Path):
    pkg_json = """{
  "name": "my-app",
  "version": "1.0.0",
  "dependencies": {
    "express": "^4.18.2",
    "cors": "~2.8.5"
  },
  "devDependencies": {
    "typescript": "^5.0.0"
  },
  "scripts": {
    "build": "tsc",
    "start": "node dist/index.js"
  }
}"""
    f = tmp_path / "package.json"
    f.write_text(pkg_json, encoding="utf-8")

    assert is_package_manifest_path(f)
    result = extract_package_manifest(f)
    nodes = result["nodes"]
    edges = result["edges"]

    assert len(nodes) == 1
    assert nodes[0]["label"] == "my-app"
    assert nodes[0]["ecosystem"] == "npm"
    assert len(edges) == 3  # express, cors, typescript
    relations = {e["relation"] for e in edges}
    assert "depends_on" in relations


def test_manifest_requirements_txt(tmp_path: Path):
    reqs = """
# Production dependencies
requests>=2.28.0
fastapi==0.95.0
pydantic<2.0.0,>=1.10.0
# Comment line
-r other-requirements.txt
uvicorn[standard]>=0.20.0
"""
    f = tmp_path / "requirements.txt"
    f.write_text(reqs, encoding="utf-8")

    assert is_package_manifest_path(f)
    result = extract_package_manifest(f)
    nodes = result["nodes"]
    edges = result["edges"]

    assert len(nodes) == 1
    assert nodes[0]["label"] == "requirements"
    assert nodes[0]["ecosystem"] == "requirements"
    assert len(edges) == 4  # requests, fastapi, pydantic, uvicorn


def test_manifest_poetry_lock(tmp_path: Path):
    poetry_lock = """
[[package]]
name = "flask"
version = "2.3.2"
description = "A simple framework building complex web applications."
optional = false
python-versions = ">=3.8"
files = []

[[package]]
name = "werkzeug"
version = "2.3.3"
description = "The comprehensive WSGI web application library."
optional = false
python-versions = ">=3.8"
files = []
"""
    f = tmp_path / "poetry.lock"
    f.write_text(poetry_lock, encoding="utf-8")

    assert is_package_manifest_path(f)
    result = extract_package_manifest(f)
    nodes = result["nodes"]
    edges = result["edges"]

    assert len(nodes) == 1
    assert nodes[0]["label"] == "poetry.lock"
    assert nodes[0]["ecosystem"] == "poetry_lock"
    assert len(edges) == 2  # flask, werkzeug



# ---------------------------------------------------------------------------
# Dispatch test
# ---------------------------------------------------------------------------


def test_extractor_dispatch_detection(tmp_path: Path):
    wf_file = tmp_path / ".github" / "workflows" / "deploy.yml"
    wf_file.parent.mkdir(parents=True)
    wf_file.write_text("name: Deploy\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n", encoding="utf-8")

    assert is_github_workflow(wf_file)
    assert _get_extractor(wf_file) == extract_github_workflow

    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services:\n  web:\n    image: nginx\n", encoding="utf-8")
    assert is_docker_compose(compose_file)
    assert _get_extractor(compose_file) == extract_docker_compose

    schema_file = tmp_path / "api.schema.json"
    schema_file.write_text('{"$schema": "http://json-schema.org/draft-07/schema#"}\n', encoding="utf-8")
    assert is_api_or_schema(schema_file)
    assert _get_extractor(schema_file) == extract_api_or_schema
