"""Tests for Argo CD GitOps extractor and cross-resolution (Phase 12).

Tests cover:
- Argo CD Application manifests (source, destination, automated sync)
- Argo CD ApplicationSet manifests (generators, templates)
- Cross-format resolution (linking Argo Application to Helm chart and K8s manifests)
"""

from pathlib import Path

from graphify.extract import _get_extractor
from graphify.extractors.argocd import extract_argocd, is_argocd_manifest
from graphify.cross_resolve import resolve_cross_format_dependencies


def test_argocd_application_extractor(tmp_path: Path):
    app_yaml = """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: guestbook
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/argoproj/argocd-example-apps.git
    targetRevision: HEAD
    path: guestbook
  destination:
    server: https://kubernetes.default.svc
    namespace: guestbook
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
"""
    app_file = tmp_path / "guestbook-app.yaml"
    app_file.write_text(app_yaml, encoding="utf-8")

    assert is_argocd_manifest(app_file)
    assert _get_extractor(app_file) == extract_argocd

    res = extract_argocd(app_file)
    nodes = res["nodes"]
    edges = res["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    # Application node
    assert "Argo:Application:guestbook" in labels
    # Source node
    assert "Argo:Source:guestbook" in labels
    # Destination node
    assert "Argo:Destination:guestbook" in labels

    # Relations
    assert "defines_application" in relations
    assert "syncs_from" in relations
    assert "deploys_to" in relations

    app_node = next(n for n in nodes if n["label"] == "Argo:Application:guestbook")
    assert app_node.get("automated_sync") is True
    assert app_node.get("dest_namespace") == "guestbook"


def test_argocd_applicationset_extractor(tmp_path: Path):
    appset_yaml = """\
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: cluster-addons
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - cluster: engineering
            url: https://1.2.3.4
          - cluster: production
            url: https://2.3.4.5
    - git:
        repoURL: https://github.com/org/infra.git
        revision: main
        directories:
          - path: addons/*
  template:
    metadata:
      name: '{{cluster}}-addon'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/infra.git
        targetRevision: main
        path: '{{path}}'
      destination:
        server: '{{url}}'
        namespace: kube-system
"""
    appset_file = tmp_path / "addons-appset.yaml"
    appset_file.write_text(appset_yaml, encoding="utf-8")

    assert is_argocd_manifest(appset_file)
    res = extract_argocd(appset_file)
    nodes = res["nodes"]
    edges = res["edges"]

    labels = {n["label"] for n in nodes}
    relations = {e["relation"] for e in edges}

    assert "Argo:ApplicationSet:cluster-addons" in labels
    assert "Argo:Generator:list" in labels
    assert "Argo:Generator:git" in labels

    assert "defines_applicationset" in relations
    assert "uses_generator" in relations


def test_argocd_cross_resolution_to_helm_and_k8s(tmp_path: Path):
    """Test linking Argo CD Application to Helm charts and K8s manifests by path."""
    app_yaml = """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-service
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/myorg/monorepo.git
    path: charts/payment
  destination:
    server: in-cluster
    namespace: payments
"""
    app_file = tmp_path / "app.yaml"
    app_file.write_text(app_yaml, encoding="utf-8")

    argo_res = extract_argocd(app_file)

    # Fake Helm Chart node
    helm_node = {
        "id": "helm_chart_payment",
        "label": "Helm:Chart:payment",
        "chart_name": "payment",
        "type": "helm_chart",
        "file_type": "code",
        "source_file": "charts/payment/Chart.yaml",
    }

    # Fake K8s resource node
    k8s_node = {
        "id": "k8s_deploy_payment",
        "label": "K8s:Deployment:payment-api",
        "resource_kind": "deployment",
        "resource_name": "payment-api",
        "type": "k8s_resource",
        "file_type": "code",
        "source_file": "charts/payment/templates/deployment.yaml",
    }

    all_nodes = argo_res["nodes"] + [helm_node, k8s_node]
    all_edges = argo_res["edges"]

    nodes, edges = resolve_cross_format_dependencies(all_nodes, all_edges)
    relations = {(e["source"], e["target"], e["relation"]) for e in edges}

    app_id = next(n["id"] for n in nodes if "Argo:Application:payment-service" in n["label"])

    # Application manages Helm chart and K8s deployment
    assert (app_id, "helm_chart_payment", "manages") in relations
    assert (app_id, "k8s_deploy_payment", "manages") in relations
