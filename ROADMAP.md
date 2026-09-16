# To-Do: Local, No-LLM Graphify Build (Copilot + Claude Code only)

A build checklist consolidating the strip-down, IaC/config parsing, retrieval, labeling, and deep-dive work discussed.

---

## Phase 1 — Strip out non-local pipelines

- [x] Remove all LLM API client code (Anthropic/OpenAI SDKs, `mcp_servers` config)
- [x] Remove any code reading `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from env
- [x] Delete PDF ingestion path + its dependencies
- [x] Delete image/screenshot ingestion path + its dependencies
- [x] Delete audio/video ingestion path (Whisper calls, temp audio extraction) + its dependencies
- [x] Remove any "route through IDE session's model" fallback logic
- [x] Remove/rewrite docs and README claims about multimodal or semantic capabilities
- [x] Confirm tree-sitter code-parsing pipeline is untouched and has no LLM fallback for ambiguous cases

## Phase 2 — Restrict platform/assistant scope to Copilot + Claude Code

- [x] Remove skill/integration registration for every platform except GitHub Copilot and Claude Code (drop Cursor, Codex, OpenCode, Gemini CLI, Aider, OpenClaw, Factory Droid, Trae, Hermes, Kiro, Google Antigravity, etc.)
- [x] Delete platform-detection/dispatch code branches for removed platforms
- [x] Keep the `/graphify` skill invocation working in Claude Code as-is
- [x] Confirm the Copilot integration path (CLI or Copilot Chat, whichever this fork uses) still registers and runs correctly
- [x] Update `graphify install` (or equivalent setup command) to only offer/detect Copilot and Claude Code
- [x] Update README/docs to list only Copilot and Claude Code as supported assistants
- [x] Remove any dependencies that were only needed for the dropped platforms' integration shims

## Phase 3 — Local markdown/text parsing

- [x] Parse YAML frontmatter → node metadata
- [x] Parse headings (H1–H6) → nodes nested under parent heading
- [x] Parse `[[wikilinks]]` (incl. `[[Note#Heading]]` and `[[Note|display text]]` alias syntax) → edges
- [x] Parse `[markdown links](...)` → edges
- [x] Parse `#tags` → tag nodes + edges to notes using them
- [x] Confirm no NER/model-based entity extraction remains anywhere in this path
- [x] Change edge confidence scheme: drop `INFERRED`/`AMBIGUOUS`, default to `EXTRACTED` @ 1.0 (or reserve <1.0 only for fuzzy/heuristic matches, e.g. label merging)

## Phase 4 — Infra-as-code & config parsing

**Kubernetes**
- [x] Parse Kubernetes manifest YAML: `apiVersion`/`kind`/`metadata`/`spec` → one node per resource (Deployment, Service, ConfigMap, Secret, Ingress, etc.)
- [x] Extract intra-file relationships: label/selector matches (Service → Pod), `ownerReferences`, volume mounts → ConfigMap/Secret refs, container image refs

**Helm**
- [x] Parse `Chart.yaml` metadata and `values.yaml` defaults
- [x] Parse `templates/*.yaml` as best-effort structural YAML, treating Go-template `{{ }}` blocks as opaque placeholders — extract static `kind`/`name`/structure where resolvable without rendering
- [x] Link chart → sub-chart dependencies (`Chart.yaml` → `dependencies:`)
- [x] Link chart → the K8s resource nodes its templates define

**Terraform**
- [x] Add a local HCL2 parser (e.g. an HCL parsing library, no network calls) for `.tf` files
- [x] Parse `resource`, `module`, `variable`, `output`, `provider` blocks as nodes
- [x] Extract interpolation references (`aws_instance.foo.id`, module inputs/outputs) as edges
- [x] Tag `aws_*` resource types with an `AWS:` label namespace (per Phase 8 labeling convention)

**AWS**
- [x] Add a CloudFormation/SAM template parser (JSON/YAML): `Resources` section → nodes
- [x] Extract `Fn::Ref` / `Fn::GetAtt` / `DependsOn` as edges
- [x] Confirm Terraform `aws_*` resources (above) and CloudFormation resources share a consistent AWS node labeling scheme

**Kafka**
- [x] Add a config parser for `server.properties` / topic-definition YAML or JSON → broker/topic/config nodes
- [x] Add a schema parser for `.avsc` (Avro) and `.proto` (Protobuf) → record/message nodes with field-level structure
- [x] Link topics to schemas where discoverable (naming convention, schema-registry config references)

**GitHub Actions**
- [x] Parse `.github/workflows/*.yml`: jobs, steps, `on:` triggers, matrix strategies → nodes
- [x] Extract `uses:` action references (incl. version/SHA pin) as edges to external action nodes
- [x] Extract `workflow_call`/reusable-workflow references as edges between workflow files
- [x] Extract `secrets:`/`env:` references for later cross-referencing (Phase 7)

**JSON Schema**
- [x] Parse `*.schema.json` / files with a `$schema` key: `definitions`/`$defs` → nodes
- [x] Resolve `$ref` (including cross-file refs) → edges between schema nodes
- [x] Link schema files to the JSON/YAML config files that declare `$schema` against them

**Docker**
- [x] Parse `Dockerfile`: `FROM` base image, `COPY`/`ADD` source refs → nodes/edges
- [x] Parse `docker-compose.yml`: services, `depends_on`, networks, volumes → nodes/edges
- [x] Link Dockerfile image build output to any K8s Deployment/Terraform resource that references the same image name (ties into Phase 7)

**OpenAPI / AsyncAPI**
- [x] Parse OpenAPI specs: paths/operations → nodes, `$ref` → edges into JSON Schema definitions
- [x] Parse AsyncAPI specs: channels/messages → nodes, link messages to Kafka topics/schemas where names match

**SQL DDL**
- [x] Parse `CREATE TABLE` statements (local SQL parser, no DB connection): table/column → nodes
- [x] Extract foreign-key constraints → edges between table nodes

**Package manifests**
- [x] Parse `package.json`+lockfile, `requirements.txt`/`poetry.lock`, `go.mod`, `Cargo.toml`: declared dependencies → nodes/edges
- [x] Keep this distinct from tree-sitter's per-file `import`/`require` parsing — this is manifest-level, not usage-level

**General**
- [x] Confirm every new parser is a local-only library with no network calls
- [x] Confirm none of these formats trigger the code-parsing (tree-sitter) path incorrectly, or vice versa

## Phase 5 — Indexing layer (BM25, no vectors)

- [x] Set up SQLite FTS5 (or equivalent local inverted index) — no external services
- [x] Index at node level: one document per note, heading-section, tag, code symbol, and each IaC/config/schema/manifest resource node
- [x] Apply text normalization: lowercasing, stopword removal, stemming/lemmatization (rules-based, e.g. Porter stemmer)
- [x] Confirm no vector storage or embedding calls anywhere in the indexing path

## Phase 6 — Graph-augmented retrieval

- [x] Build seed-query step: FTS5/BM25 top-N match against query
- [x] Build expand step: 1–2 hop graph traversal from seed nodes via edges
- [x] Precompute static graph-centrality metric (PageRank or degree) at build time
- [x] Build re-rank step combining BM25 score + graph proximity + centrality
- [x] Return structured results: `{ node_id, score, text, source_path, connected_via }[]`
- [x] Confirm zero network calls and zero model-load latency at query time

## Phase 7 — Deep-dive: cross-resource dependency chains & trace

- [x] Build a cross-format edge-resolution pass: connect Terraform `helm_release`/`kubernetes_*` resources to their corresponding Helm chart / K8s manifest nodes where identifiable by name
- [x] Connect K8s Deployment container `image:` references to matching Dockerfile/docker-compose image-build nodes (Phase 4)
- [x] Connect CloudFormation and Terraform AWS resources referenced by matching name/ARN pattern across files
- [x] Connect GitHub Actions workflows to the resources they deploy (e.g. a workflow step invoking Terraform/Helm against a specific path)
- [x] Build env-var/secret-name cross-referencing: match identical env var or secret names across Terraform, K8s, GitHub Actions, and docker-compose, and surface them as edges or a dedicated "referenced by" index
- [x] Build `graphify trace <node-a> <node-b>`: shortest-path traversal across the whole graph, spanning code, markdown, and all IaC/config formats
- [x] Extend `graphify explain <query>` (Phase 11) to show cross-format hops in its score breakdown, not just same-format hops
- [x] Add a test fixture chain (e.g. GitHub Actions → Terraform module → Helm release → K8s Deployment → container image) and confirm it resolves as one connected path

## Phase 8 — Labeling improvements

- [x] Add stable internal slug ID separate from human-facing display label
- [x] Add label-merging pass: string similarity (Levenshtein/token-Jaccard) to fold near-duplicates
- [x] Support `aliases:`/`type:`/`category:` frontmatter fields as authoritative labels
- [x] Support `[[Note|display text]]` alias syntax (should already be covered by Phase 3, verify here)
- [x] Add optional root-level `aliases.yaml`/`labels.yaml` for user-controlled synonym mapping
- [x] Namespace labels by node type (`Note:`, `Tag:`, `Heading:`, `Code:`, `K8s:`, `Helm:`, `Terraform:`, `AWS:`, `Kafka:`, `Action:`, `Schema:`, `Docker:`, `API:`, `Table:`, `Pkg:`) to avoid collisions
- [x] Derive typed edge labels from parse context (`contains`, `tagged-as`, `references-heading`, `imports`, `selects`, `mounts`, `depends-on`, `owns`, `uses-action`, `builds-image`, `references-schema`, `foreign-key`) instead of a generic "linked-to"
- [x] Attach folder-path-derived category metadata to nodes
- [x] (Optional) Add per-node TF-IDF top-terms as a lightweight keyword label for display

## Phase 9 — Interface

- [x] Build `graphify build <path>` command: parse → graph → FTS5 index → precomputed metrics → `graphify-out/` bundle
- [x] Build `graphify query "<text>" --limit N --hops N` command: prebuilt index/graph in, ranked JSON out
- [x] Build `graphify trace <node-a> <node-b>` command (Phase 7)
- [x] Build `graphify lint` command (Phase 11) surfacing drift/lint findings
- [x] Expose retrieval, trace, and lint as importable library functions, not just CLI
- [x] Confirm no UI/HTTP server is introduced (index + callable API only, per current scope)
- [x] Keep `GRAPH_REPORT.md` and graph JSON output formats intact

## Phase 10 — Acceptance testing (network fully blocked)

- [x] `graphify build ./notes` completes successfully on markdown/text-only folder
- [x] `graphify build` completes successfully on mixed code + markdown folder
- [x] `graphify build` completes successfully on a folder containing Helm charts, K8s manifests, Terraform, CloudFormation, Kafka configs/schemas, GitHub Actions workflows, JSON Schemas, Dockerfiles/docker-compose, OpenAPI/AsyncAPI specs, SQL DDL, and package manifests
- [x] `graphify query "some phrase"` returns ranked, graph-expanded JSON results
- [x] `graphify trace <a> <b>` resolves a known cross-format dependency chain correctly
- [x] `graphify lint` correctly flags a deliberately-introduced drift/lint issue in the test fixtures
- [x] Confirm zero outbound network requests during build and query (run with network blocked)
- [x] Confirm no dependency in the tree pulls in a model weight, tokenizer file, or API client
- [x] Spot-check label merging on a few known near-duplicate terms in the test vault
- [x] Confirm `/graphify` works correctly invoked from Claude Code
- [x] Confirm equivalent invocation works correctly from Copilot
- [x] Confirm no leftover references (docs, code, config) to removed platforms

## Phase 11 — Further improvements (still no models)

**Retrieval quality**
- [x] Index title/heading/tag text and body text in separate FTS5 columns, weight heading/tag matches higher than body matches
- [x] Use FTS5 phrase/`NEAR()` queries to reward multi-word queries where terms appear close together
- [x] Expand queries using the `aliases.yaml` synonym dictionary before searching
- [x] Add `spellfix1` (or equivalent) for typo-tolerant fuzzy matching

**Graph quality & deterministic lint/drift rules**
- [x] Build `graphify lint`: report dangling wikilinks/references (incl. broken Terraform/K8s/JSON Schema `$ref`s), orphan nodes, and ambiguous label merges flagged for human review
- [x] Add rule: flag GitHub Actions `uses:` references that aren't pinned to a version/SHA
- [x] Add rule: flag a Terraform/CloudFormation resource with no corresponding counterpart across expected environments (e.g. staging defines a resource prod doesn't)
- [x] Add rule: flag env-var/secret names referenced in code or config but never defined anywhere (or vice versa) — built directly on the Phase 7 cross-referencing pass
- [x] Store explicit backlink (reverse) edges alongside forward edges for O(1) "what links here" lookups

**Debuggability**
- [x] Build `graphify explain <query>`: show per-result score breakdown (BM25 score, hop distance, centrality contribution)

**Performance**
- [x] Add incremental builds: hash/mtime-check files so only changed files are reprocessed (in `graphify/detect.py`)

**Stability**
- [x] Make node IDs deterministic (slug-based, not insertion-order-dependent) so `graphify-out/` diffs cleanly in git between builds

---

## Phase 12 — Future Expansions (GitOps, Monorepos, & Build Systems)

**GitOps & Continuous Delivery**
- [x] Argo CD Application & ApplicationSet YAML parser:
  - Extract `apiVersion: argoproj.io/v1alpha1`, `kind: Application` / `ApplicationSet`
  - Map `spec.source.repoURL`, `targetRevision`, and `path` to source Helm charts or K8s directories
  - Map `spec.destination.server` and `namespace` to target cluster/namespace environments
  - Extract generators (Git generator, List generator, Matrix generator) in `ApplicationSet`
  - Link Argo CD Applications to the K8s manifests and Helm charts they manage

**Build Systems & Monorepos**
- [x] Bazel build graph extractor:
  - Parse `BUILD` / `BUILD.bazel`, `WORKSPACE` / `WORKSPACE.bazel`, and `MODULE.bazel`
  - Extract rule declarations (`cc_library`, `py_binary`, `java_test`, `go_image`, etc.)
  - Map target labels (`//path/to/pkg:target`), `deps`, and `visibility` into dependency edges
  - Link external repositories (`http_archive`, `git_repository`, Bzlmod modules) to packages
- [x] Monorepo workspace & task pipeline extractors:
  - Nx: Parse `nx.json` and `project.json` (targets, executor configurations, `dependsOn`)
  - Turborepo: Parse `turbo.json` (pipeline dependencies, task caching boundaries)
  - Workspaces: Parse `pnpm-workspace.yaml`, Yarn/npm `workspaces` arrays in `package.json`, and Lerna (`lerna.json`)
  - Cross-link internal package dependencies across monorepo packages

**Extended API & Schema Systems**
- [x] Extended JSON Schema support:
  - Full Draft-04 / Draft-07 / 2020-12 dialect normalization
  - Schema registry mappings (Confluent Schema Registry, AWS Glue, Apicurio)
- [x] Protobuf & gRPC service cross-referencing:
  - Link gRPC service definitions to REST/OpenAPI gateway mappings (e.g. `google.api.http` annotations)

---

## Phase 13 — Code Intelligence & Deep Agent Tooling (CodeGraph & GitNexus Features)

**Predictive Impact Analysis & Blast Radius Engine (GitNexus)**
- [x] Implement `graphify impact <symbol_or_file>` and `graphify blast <symbol_or_file>`:
  - Traverse downstream transitive dependency edges (`calls`, `imports`, `inherits`, `references`) to compute full blast radius of proposed code changes
  - Identify affected unit and integration test files exercising the target symbols
  - Surface exposed outward-facing API endpoints (HTTP routes, gRPC RPCs, GraphQL resolvers) impacted by changes
  - Trace impacted IaC & deployment resources (Kubernetes deployments, Terraform resources, Kafka topic consumers)
  - Compute Blast Radius Risk Score (combining PageRank centrality, degree fan-out, and community boundary crossings: LOW, MEDIUM, HIGH, CRITICAL)
  - Expose `get_impact_analysis` / `get_blast_radius` tool in the MCP server (`graphify/mcp.py`) so agents can inspect downstream impacts before modifying code

**Fine-Grained Symbol & Call-Graph Navigation MCP Tooling (CodeGraph)**
- [x] Expose specialized AST code navigation tools via MCP server (`graphify/mcp.py`):
  - `find_definitions`: Direct symbol declaration lookup with file path and exact line range (eliminates reading full source files)
  - `get_callers` & `get_callees`: Query inbound and outbound function/method call hierarchies directly from AST edges
  - `find_references`: Enumerate all cross-file usages, calls, and imports of a specific class, function, or variable
  - `find_implementations`: Query interfaces, abstract base classes, and their concrete implementing classes/structs
- [x] Token & Exploration Savings Metrics:
  - Compute and report estimated tokens saved vs raw file reads in `graphify query`, `graphify explain`, and MCP tool responses

**Execution Flow Slicing & Entry-to-Sink Tracing (GitNexus)**
- [x] Implement `graphify flow <entry_point> [--sink <data_sink>]`:
  - Automatically identify system entry points (HTTP handlers, CLI commands, event listeners, gRPC RPCs)
  - Trace execution paths from entry points through middleware, domain services, and database queries down to data sinks (database tables, message queues, external APIs)
  - Render ASCII execution flow diagrams for agent context

**Zero-Server Browser WebAssembly (WASM) Graph Explorer (GitNexus)**
- [x] Embed client-side SQLite WASM / in-browser query engine directly into `graph.html`:
  - Enable ad-hoc SQL / graph querying, neighborhood filtering, and blast radius exploration directly in any browser tab without a running server

**Hot Watcher & Instant Re-Indexing Daemon (CodeGraph)**
- [ ] Optimize `graphify watch` / daemon mode:
  - Low-latency in-memory graph patching on file-save events without full rebuild overhead

---

## Phase 14 — Next-Gen Agent Skills: Ponytail & Caveman Integration

**Ponytail Anti-Overengineering Decision Ladder (The Laziest Senior Dev)**
- [x] Embed the Ponytail 5-step decision ladder into `skill.md`, `skill-copilot.md`, `skill-vscode.md`, `AGENTS.md`, and `CLAUDE.md`:
  - Step 1: **YAGNI** — Challenge unnecessary abstractions, speculative generality, and redundant configurations
  - Step 2: **Graphify Code Reuse Check** — Before writing *any* new helper, class, or utility, query `graphify query "<concept>"` or check `graphify-out/wiki/index.md` to locate existing implementations in the codebase
  - Step 3: **Standard Library First** — Prefer built-in language standard libraries over adding third-party dependencies
  - Step 4: **Native Platform First** — Use native runtime/framework capabilities before writing custom wrappers
  - Step 5: **Surgical Minimal Diff** — Write the smallest necessary diff that solves the task; never refactor untouched surrounding code
- [x] Add anti-bloat guard: skill explicitly instructs agents that "the best code is the code you never wrote"

**Caveman Ultra-Terse Communication & Token Conservation Mode**
- [x] Embed Caveman token-saving prompting rules into assistant skills (`skill.md`, `skill-copilot.md`, `skill-vscode.md`):
  - Strip conversational pleasantries, preambles, apologies, filler, and repetitive restatements
  - Enforce dense, high-signal bullet points and concise technical fragments (cutting output token usage by 65–75%)
  - Preserve 100% technical fidelity: exact file paths, line ranges, symbol identifiers, CLI commands, and code blocks must NEVER be shortened or omitted
- [x] Add `--terse` / `--caveman` flag to `graphify query` and `graphify explain`:
  - Returns compact, token-dense answers tailored for agent context windows without boilerplate

---

## Phase 15 — Frontend State & Client API Architecture (Redux Toolkit & RTK Query)

**Redux Toolkit (RTK) State Management Extractor**
- [ ] Parse `createSlice(...)` definitions in TypeScript/JavaScript (`.ts`, `.tsx`, `.js`, `.jsx`):
  - Extract slice nodes with initial state shape and declared reducer actions (`reducers: { ... }`)
  - Parse `createAsyncThunk(...)`: extract thunk actions (`pending`, `fulfilled`, `rejected`) and link to dispatching components
  - Parse `configureStore(...)`: extract store nodes linking root reducers, slice states, and middleware
  - Extract selectors (`createSelector`, `useSelector`) linking React component nodes to specific slice properties
  - Connect UI component `dispatch(...)` calls to corresponding slice reducer actions

**RTK Query (RTKQ) Client Data Layer & Cache Invalidation Graph**
- [ ] Parse `createApi(...)` declarations:
  - Extract API slice nodes (`reducerPath`, `baseQuery`, `tagTypes`)
  - Parse `builder.query(...)` and `builder.mutation(...)` endpoint definitions:
    - Extract endpoint URL paths, HTTP methods (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`), and parameters
    - Extract cache tag definitions: `providesTags` on queries and `invalidatesTags` on mutations
    - Generate `invalidates_cache` edges between mutations and queries connected via shared cache tags
  - Map auto-generated React hooks (`use...Query`, `use...Mutation`) to the UI components invoking them
- [ ] Cross-Layer Frontend-to-Backend Resolution:
  - Match RTK Query endpoint URL paths with backend routes (OpenAPI endpoints, Express/FastAPI handlers, and Protobuf/gRPC HTTP gateway mappings)
  - Enable full end-to-end execution flow tracing: UI Component -> RTK Query Hook -> HTTP Route -> Backend Controller -> Database / Cache / Message Queue
- [ ] State & Cache Linting Rules (`graphify lint`):
  - Flag undeclared cache tags used in `providesTags`/`invalidatesTags` that are missing from `tagTypes`
  - Flag orphaned mutations invalidating tags that no active query provides
  - Flag RTK Query endpoints calling backend routes that are not defined in any OpenAPI spec or server controller



