"""Tests for Bazel build graph and Monorepo workspace extractors (Phase 12).

Tests cover:
- Bazel BUILD / BUILD.bazel (rules, targets, sources, dependencies, loads)
- Bazel WORKSPACE & MODULE.bazel (http_archive, git_repository, bazel_dep)
- pnpm-workspace.yaml
- turbo.json (pipelines & tasks)
- nx.json & project.json (Nx workspaces & projects)
- lerna.json
"""

from pathlib import Path

from graphify.extract import _get_extractor
from graphify.extractors.bazel import extract_bazel, is_bazel_file
from graphify.extractors.monorepo import extract_monorepo, is_monorepo_file


# ---------------------------------------------------------------------------
# Bazel tests
# ---------------------------------------------------------------------------


def test_bazel_build_extractor(tmp_path: Path):
    build_content = """\
load("@rules_cc//cc:defs.bzl", "cc_library", "cc_binary")

cc_library(
    name = "math_util",
    srcs = ["math.cc"],
    hdrs = ["math.h"],
    deps = [
        "//core/base:types",
    ],
)

cc_binary(
    name = "calculator",
    srcs = ["main.cc"],
    deps = [
        ":math_util",
        "@com_google_absl//absl/strings",
    ],
)
"""
    build_file = tmp_path / "BUILD.bazel"
    build_file.write_text(build_content, encoding="utf-8")

    assert is_bazel_file(build_file)
    assert _get_extractor(build_file) == extract_bazel

    res = extract_bazel(build_file)
    nodes = res["nodes"]
    edges = res["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    # Load node
    assert any("rules_cc" in l for l in labels)
    assert "loads" in relations

    # Targets
    assert "Bazel:math_util" in labels
    assert "Bazel:calculator" in labels

    # Target dependency
    assert "depends_on" in relations
    # Sources
    assert "contains_source" in relations


def test_bazel_workspace_extractor(tmp_path: Path):
    workspace_content = """\
workspace(name = "my_monorepo")

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "rules_python",
    sha256 = "9d04041e68960017329c733b300b6f37873190b4a3a1781854810e47c63830f0",
    strip_prefix = "rules_python-0.26.0",
    url = "https://github.com/bazelbuild/rules_python/releases/download/0.26.0/rules_python-0.26.0.tar.gz",
)

git_repository(
    name = "com_google_googletest",
    remote = "https://github.com/google/googletest.git",
    commit = "7029864278eb146de04de36ae5593172b94e96e5",
)
"""
    ws_file = tmp_path / "WORKSPACE"
    ws_file.write_text(workspace_content, encoding="utf-8")

    assert is_bazel_file(ws_file)
    res = extract_bazel(ws_file)
    nodes = res["nodes"]
    edges = res["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    assert "Bazel:Repo:rules_python" in labels
    assert "Bazel:Repo:com_google_googletest" in labels
    assert "declares_external_repo" in relations


def test_bazel_module_extractor(tmp_path: Path):
    module_content = """\
module(
    name = "my_app",
    version = "1.0.0",
)

bazel_dep(name = "rules_cc", version = "0.0.9")
bazel_dep(name = "protobuf", version = "21.7")
"""
    mod_file = tmp_path / "MODULE.bazel"
    mod_file.write_text(module_content, encoding="utf-8")

    assert is_bazel_file(mod_file)
    res = extract_bazel(mod_file)
    nodes = res["nodes"]
    edges = res["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    assert "Bazel:Repo:rules_cc" in labels
    assert "Bazel:Repo:protobuf" in labels
    assert "declares_external_repo" in relations


# ---------------------------------------------------------------------------
# Monorepo tests
# ---------------------------------------------------------------------------


def test_pnpm_workspace_extractor(tmp_path: Path):
    ws_content = """\
packages:
  - 'packages/*'
  - 'apps/*'
  - '!**/test/**'
"""
    ws_file = tmp_path / "pnpm-workspace.yaml"
    ws_file.write_text(ws_content, encoding="utf-8")

    assert is_monorepo_file(ws_file)
    assert _get_extractor(ws_file) == extract_monorepo

    res = extract_monorepo(ws_file)
    nodes = res["nodes"]
    edges = res["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    assert "Monorepo:pnpm-workspace" in labels
    assert "Workspace:Pattern:packages/*" in labels
    assert "Workspace:Pattern:apps/*" in labels
    assert "includes_pattern" in relations


def test_turborepo_extractor(tmp_path: Path):
    turbo_content = """{
  "$schema": "https://turbo.build/schema.json",
  "pipeline": {
    "build": {
      "dependsOn": ["^build"],
      "outputs": [".next/**", "dist/**"]
    },
    "test": {
      "dependsOn": ["build"]
    },
    "lint": {}
  }
}"""
    turbo_file = tmp_path / "turbo.json"
    turbo_file.write_text(turbo_content, encoding="utf-8")

    assert is_monorepo_file(turbo_file)
    res = extract_monorepo(turbo_file)
    nodes = res["nodes"]
    edges = res["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    assert "Monorepo:Turborepo" in labels
    assert "Turbo:Task:build" in labels
    assert "Turbo:Task:test" in labels
    assert "defines_task" in relations
    assert "depends_on" in relations


def test_nx_extractor(tmp_path: Path):
    nx_content = """{
  "targetDefaults": {
    "build": {
      "cache": true
    }
  }
}"""
    nx_file = tmp_path / "nx.json"
    nx_file.write_text(nx_content, encoding="utf-8")

    assert is_monorepo_file(nx_file)
    res_nx = extract_monorepo(nx_file)
    labels = {n["label"] for n in res_nx["nodes"]}
    assert "Monorepo:Nx" in labels
    assert "Nx:TargetDefault:build" in labels

    # Project
    proj_content = """{
  "name": "auth-service",
  "projectType": "application",
  "targets": {
    "build": {
      "executor": "@nx/webpack:webpack"
    },
    "test": {
      "executor": "@nx/jest:jest"
    }
  }
}"""
    proj_file = tmp_path / "apps" / "auth" / "project.json"
    proj_file.parent.mkdir(parents=True)
    proj_file.write_text(proj_content, encoding="utf-8")

    res_proj = extract_monorepo(proj_file)
    labels_proj = {n["label"] for n in res_proj["nodes"]}
    relations_proj = {e["relation"] for e in res_proj["edges"]}

    assert "Nx:Project:auth-service" in labels_proj
    assert "Nx:Target:auth-service:build" in labels_proj
    assert "defines_target" in relations_proj


def test_lerna_extractor(tmp_path: Path):
    lerna_content = """{
  "version": "1.0.0",
  "packages": [
    "packages/*"
  ]
}"""
    lerna_file = tmp_path / "lerna.json"
    lerna_file.write_text(lerna_content, encoding="utf-8")

    assert is_monorepo_file(lerna_file)
    res = extract_monorepo(lerna_file)
    labels = {n["label"] for n in res["nodes"]}
    assert "Monorepo:Lerna" in labels
