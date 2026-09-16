# How graphify works

graphify builds a queryable, persistent knowledge graph across your codebase, infrastructure-as-code, configuration files, and markdown documentation with **zero external API calls, zero LLM dependencies, and zero network requests**.

---

## The Extraction Pipeline

graphify extracts symbols, configurations, and relationships across three deterministic local passes:

### Pass 1 — Code AST Extraction (~40 languages)
Code files are not sent to the LLM semantic extractor. For repositories consisting purely of code files, Pass 3 is skipped entirely if no IaC or documents are present. Tree-sitter parses source code files directly into concrete syntax trees (CST/AST) and extracts:
- Definitions: classes, interfaces, traits, functions, methods, structs, enums.
- Relationships: `calls`, `imports`, `inherits`, `implements`, `defines`.
- Rationale: docstrings, inline design comments (`# NOTE:`, `# WHY:`, `# HACK:`).
- Multiprocessing: extracted in parallel across CPU cores using `ProcessPoolExecutor`.

### Pass 2 — Markdown & Documentation
Local text parsing without model-based NER (handling docs, papers, images, and transcripts deterministically without remote APIs):
- Frontmatter: YAML frontmatter parsed into node metadata attributes.
- Structure: H1–H6 section headings hierarchically nested under document nodes.
- Links & Tags: `[[wikilinks]]` (including `[[Note#Heading]]` and alias syntax `[[Note|display]]`), markdown `[text](url)` links, and `#tags`.

### Pass 3 — Infra-as-Code, Config & Build Systems
Dedicated local parsers extract nodes and dependency relationships from architecture and deployment files:
- **Kubernetes**: manifests, Deployments, Services, ConfigMaps, Secrets, Ingresses, label/selector matching, image refs.
- **Helm**: `Chart.yaml`, `values.yaml`, `templates/*.yaml` best-effort Go-template structural extraction.
- **Terraform & HCL**: `.tf` resources, modules, variables, provider blocks, interpolation dependencies.
- **AWS CloudFormation**: SAM & CloudFormation templates, `Fn::Ref`, `Fn::GetAtt`, `DependsOn`.
- **Kafka & Event Schemas**: `server.properties`, Avro `.avsc` schemas, Protobuf `.proto` messages and gRPC services.
- **GitHub Actions**: `.github/workflows/*.yml` workflows, jobs, steps, unpinned `uses:`, secrets/env refs.
- **JSON Schema**: `*.schema.json` and `$schema` files with cross-file `$ref` resolution across Draft-04/07/2020-12 dialects.
- **Docker & Compose**: `Dockerfile` base images and source copies (`COPY`/`ADD`), `docker-compose.yml` services, volumes, networks.
- **OpenAPI & AsyncAPI**: endpoints, operations, schema linkages, event channels.
- **SQL DDL**: `CREATE TABLE`, columns, primary and foreign key constraints across tables.
- **Package Manifests**: `package.json`, `requirements.txt`, `poetry.lock`, `go.mod`, `Cargo.toml`.
- **Bazel Build Graphs**: `BUILD.bazel`, `WORKSPACE`, `MODULE.bazel` rules, targets, labels, `deps`, external repositories.
- **Monorepo Workspaces**: Nx, Turborepo, pnpm/Yarn/npm workspaces, Lerna packages and internal pipeline dependencies.
- **GitOps & Delivery**: Argo CD `Application` and `ApplicationSet` manifests linking source repositories to target clusters.

---

## Cross-Format Dependency Resolution

After extraction, a cross-format resolution pass connects infrastructure and code definitions into end-to-end dependency chains:
1. **GitHub Actions -> IaC**: Workflows executing deployment steps link to targeted Terraform modules or Helm charts.
2. **Terraform -> Helm / Kubernetes**: `helm_release` and `kubernetes_*` Terraform resources link to their respective chart and manifest nodes.
3. **Helm -> Kubernetes**: Helm charts link to the Kubernetes resources declared in their templates.
4. **Kubernetes -> Docker**: Kubernetes Pod container `image:` references link to matching Dockerfile image build nodes.
5. **gRPC -> OpenAPI**: Protobuf `google.api.http` gateway annotations link gRPC RPC methods to OpenAPI endpoints.
6. **Config -> Schemas**: Kafka topics and serializers link to Avro, Protobuf, and JSON Schema definitions.
7. **Environment & Secret Cross-Referencing**: Identical secret and environment variable names are tracked across Terraform, Kubernetes, GitHub Actions, and Docker Compose to detect missing definitions and drift.

---

## Indexing & Graph-Augmented Retrieval (GraphRAG without LLMs)

1. **SQLite FTS5 Inverted Index**: Node labels, headings, tags, and text content are indexed into a local SQLite database (`graphify-out/index.db`) using BM25 ranking and Porter stemming. Multi-word phrases and proximity queries (`NEAR()`) reward closely co-occurring terms.
2. **Seed Querying**: User queries first match seed nodes via BM25 statistical scoring.
3. **Graph Traversal Expansion**: The retrieval engine expands 1–2 hops outward along dependency edges to bring in architectural context.
4. **Graph Centrality & Re-Ranking**: Build-time PageRank centrality and graph hop distance are combined with BM25 match scores to produce a deterministic, ranked subgraph.
5. **Typo Tolerance**: Fast local Levenshtein/RapidFuzz expansion matches misspelled query terms against the indexed vocabulary.

---

## Community Detection

The graph is partitioned into subsystems using the [Leiden algorithm](https://www.nature.com/articles/s41598-019-41695-z) (via `graspologic` or native backend).
- Nodes with high edge density form architectural communities.
- Community hub nodes are deterministically identified from degree centrality.
- Zero embeddings or vector databases are used; community boundaries are derived purely from structural edge topology.

---

## Deterministic Confidence Scoring

- All parse-extracted relationships are tagged `EXTRACTED` with confidence **1.0**.
- Near-duplicate label merges and heuristic mappings are assigned calibrated confidence scores (<1.0) and surfaced during linting.

---

## Performance & Incremental Builds

- **Hash & Mtime Checking**: Files are fingerprinted by content hash and modification timestamp (`graphify/detect.py`). Re-runs skip untouched files and update only modified subgraphs.
- **Deterministic Node IDs**: Node IDs use canonical slug-based identifiers rather than insertion-order integers, ensuring clean, predictable git diffs between builds.
