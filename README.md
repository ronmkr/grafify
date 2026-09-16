<p align="center">
  <a href="https://graphify.com"><img src="https://raw.githubusercontent.com/Graphify-Labs/graphify/v8/docs/graphify-card.png" width="300" height="214" alt="Graphify"/></a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/25296?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-25296" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/25296" alt="Graphify-Labs%2Fgraphify | Trendshift" width="250" height="55"/></a>
</p>



<p align="center">
  <a href="https://pypi.org/project/graphifyy/"><img src="https://img.shields.io/pypi/v/graphifyy" alt="PyPI"/></a>
  <a href="https://pepy.tech/project/graphifyy"><img src="https://img.shields.io/pepy/dt/graphifyy?color=blue&label=downloads" alt="Downloads"/></a>
  <a href="https://discord.gg/2DDrEgvZb4"><img src="https://img.shields.io/badge/Discord-Join-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"/></a>
  <a href="https://www.youtube.com/@graphifylabs"><img src="https://img.shields.io/badge/YouTube-Graphify%20Labs-FF0000?style=flat&logo=youtube&logoColor=white" alt="YouTube"/></a>
  <a href="https://www.linkedin.com/company/graphify-labs"><img src="https://img.shields.io/badge/LinkedIn-Graphify%20Labs-0077B5?logo=linkedin" alt="LinkedIn"/></a>
  <a href="https://www.ycombinator.com/companies/graphify-labs"><img src="https://img.shields.io/badge/Y%20Combinator-S26-F0652F?style=flat&logo=ycombinator&logoColor=white" alt="YC S26"/></a>
</p>

<p align="center">
  <b>Early access to the graphify platform is open before the public v1 launch: <a href="https://app.graphify.com/login">app.graphify.com</a></b>
</p>

Type `/graphify` in your AI coding assistant (Claude Code or GitHub Copilot) to build a **local knowledge graph and retrieval layer** across your code and markdown notes.

- **Zero LLM calls, zero network requests, zero API keys.** Everything runs on your machine.
- **Code + Markdown/Text.** Code is parsed via tree-sitter AST; Markdown and plain text are parsed deterministically (frontmatter, H1-H6 hierarchy, `[[wikilinks]]`, `#tags`, markdown links).
- **SQLite FTS5 + Graph-Augmented Retrieval.** Retrieval uses SQLite FTS5 (BM25 with Porter stemmer) expanded through graph neighbor traversals (GraphRAG without LLMs or embeddings).
- **Every edge is explicit.** Deterministic parse edges are tagged `EXTRACTED` @ 1.0 confidence.

<p align="center">
  <img src="https://raw.githubusercontent.com/Graphify-Labs/graphify/v8/docs/graph-hero.png" alt="graphify's interactive graph.html showing the FastAPI codebase as a force-directed knowledge graph with a legend of detected communities" width="900">
</p>
<p align="center">
  <em>The FastAPI codebase mapped by graphify. Every node is a concept, colors are detected communities, and the whole thing is clickable in graph.html.</em>
</p>

**Get started** (30 seconds):

```bash
uv tool install graphifyy      # install the CLI (or: pipx install graphifyy)
graphify install               # register the skill with your AI assistant
```

Then, in your AI assistant:

```
/graphify .
```

That's it. You get **three files**:

```
graphify-out/
├── index.db         SQLite FTS5 full-text search index (BM25 + Porter stemmer)
├── graph.html       open in any browser — click nodes, filter, search
├── GRAPH_REPORT.md  the highlights: key concepts, surprising connections, community breakdown
└── graph.json       the full graph — query it anytime without re-reading your files
```

**Supported assistants:** Claude Code and GitHub Copilot.

---

## What it does

What you get out of the box:

| Capability | What you get |
|---|---|
| **God nodes** | The most-connected architectural hubs, so you see what everything flows through |
| **Communities** | The graph split into subsystems (Leiden algorithm) with deterministic hub labels and per-node TF-IDF top-terms keyword labeling |
| **Cross-file links** | `calls` / `imports` / `inherits` resolved across ~40 languages via tree-sitter AST |
| **Markdown / Text** | YAML frontmatter, H1–H6 section text, `[[wikilinks]]`, and `#tags` parsed locally |
| **Infra-as-Code & Config** | K8s, Helm, Terraform, CloudFormation, Kafka, GitHub Actions, JSON Schema dialects & registries, Protobuf/gRPC, Docker, OpenAPI, SQL, Bazel, Monorepos, Argo CD |
| **FTS5 + Graph Retrieval** | BM25 statistical search with typo-tolerant fuzzy fallback (Levenshtein) expanded via 1–2 hop neighbor graph traversal |
| **Trace & Explain** | `graphify trace A B` traces shortest paths; `graphify explain` breaks down BM25 & graph centrality |
| **Lint & Drift Detection** | `graphify lint` detects unpinned actions, environment drift, missing secrets, broken `$ref`s |
| **Zero Network, Zero LLM** | 100% deterministic local execution, zero API keys, zero downloaded weights |

---

## Benchmarks

| Benchmark | Metric | graphify | Field |
|---|---|---|---|
| LOCOMO (n=300) | recall@10 | **0.497** | mem0 0.048, supermemory 0.149 |
| LOCOMO (n=300) | QA accuracy | 45.3% | supermemory 49.7%, mem0 27.3% |
| LongMemEval-S (n=50) | QA accuracy | **76%** | tied with dense RAG |
| Graph build | LLM credits | **0** | per-token for most systems |

Every system ran on the same harness with the same model and budgets, scored by a judge blind-validated against a second judge (90.6% agreement, Cohen's kappa 0.81). Full per-system tables, the code-intelligence result, and reproduction commands: **[BENCHMARKS.md](./BENCHMARKS.md)**.

---

## Prerequisites

| Requirement | Minimum | Check | Install |
|---|---|---|---|
| Python | 3.10+ | `python --version` | [python.org](https://www.python.org/downloads/) |
| uv *(recommended)* | any | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| pipx *(alternative)* | any | `pipx --version` | `pip install pipx` |

**macOS quick install (Homebrew):**
```bash
brew install python@3.12 uv
```

**Windows quick install:**
```powershell
winget install astral-sh.uv
```

**Ubuntu/Debian:**
```bash
sudo apt install python3.12 python3-pip pipx
# or install uv:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Install

> **Official package:** The PyPI package is `graphifyy` (double-y). Other `graphify*` packages on PyPI are not affiliated. The CLI command is still `graphify`.

**Step 1 — install the package:**

```bash
# Recommended (isolated env; if 'graphify' isn't found after, run: uv tool update-shell):
uv tool install graphifyy

# Alternatives:
pipx install graphifyy
pip install graphifyy  # may need PATH setup — see note below
```

**Step 2 — register the skill with your AI assistant:**

```bash
graphify install
```

That's it. Open your AI assistant and type `/graphify .`

To install the assistant skill into the current repository instead of your user
profile, add `--project`:

```bash
graphify install --project
graphify install --project --platform copilot
```

Project-scoped installs write under the current directory, for example
`.claude/skills/graphify/SKILL.md` or `.copilot/skills/graphify/SKILL.md` (plus a
`references/` sidecar the skill loads on demand).

> **PowerShell note:** Use `graphify .` not `/graphify .` — the leading slash is a path separator in PowerShell.

> **`graphify: command not found`?** `uv tool install` / `pipx install` put the `graphify` command in their tool bin dir (`~/.local/bin`). If your shell can't find it right after install — common on a fresh macOS + zsh setup — that dir isn't on your `PATH` yet: run `uv tool update-shell` (or `pipx ensurepath`), then open a new terminal. With plain `pip`, add `~/.local/bin` (Linux) or `~/Library/Python/3.x/bin` (Mac) to your PATH, or run `python -m graphify`.

> **Running with `uvx` / `uv tool run` instead of installing?** Name the package, not the command: `uvx --from graphifyy graphify install`. Plain `uvx graphify …` fails (`No solution found … no versions of graphify`) because `uv tool run` reads the first word as a *package*, and the package is `graphifyy` — the `graphify` command lives inside it.

> **Avoid `pip install` on Mac/Windows** if possible. The skill resolves Python at runtime from `graphify-out/.graphify_python`; if that points to a different environment than where `pip` installed the package, you'll get `ModuleNotFoundError: No module named 'graphify'`. `uv tool install` and `pipx install` isolate the package in their own env and avoid this entirely.

> **Git hooks and uv tool / pipx:** `graphify hook install` embeds the current interpreter path directly into the hook scripts at install time, so the post-commit hook fires correctly even in GUI git clients and CI runners where `~/.local/bin` is not on PATH. If you reinstall or upgrade graphify, re-run `graphify hook install` to refresh the embedded path.

> **Strict mode (Claude Code):** `graphify install --project --strict` makes the assistant actually use the graph. The default install *nudges* it to run `graphify query` before reading files; strict mode *blocks* the first raw source read of a session and redirects it to the graph, then reverts to the nudge (so it fires at most once per session and never gets stuck). Toggle at runtime with `GRAPHIFY_HOOK_STRICT=1`/`0`; the default install is unchanged (soft nudge).

### Supported assistants

| Platform | Install command | Description |
|----------|----------------|-------------|
| Claude Code | `graphify install` or `graphify claude install` | Installs skill to `~/.claude/skills/graphify/` and sets up `PreToolUse` hook |
| GitHub Copilot CLI | `graphify install --platform copilot` or `graphify copilot install` | Installs skill to `~/.copilot/skills/graphify/` |
| VS Code Copilot Chat | `graphify vscode install` | Configures `.github/copilot-instructions.md` |

<details>
<summary><b>Optional extras</b> (install only what you need)</summary>

| Extra | What it adds | Install |
|---|---|---|
| `sql` | SQL schema extraction (DDL, tables, foreign keys) | `uv tool install "graphifyy[sql]"` |
| `postgres` | Live PostgreSQL introspection (`--postgres DSN`) | `uv tool install "graphifyy[postgres]"` |
| `terraform` | Terraform / HCL `.tf`/`.tfvars`/`.hcl` AST extraction | `uv tool install "graphifyy[terraform]"` |
| `leiden` | Leiden community detection (graspologic on Python < 3.13; native backend on 3.13+) | `uv tool install "graphifyy[leiden]"` |
| `office` | `.docx` and `.xlsx` support | `uv tool install "graphifyy[office]"` |
| `mcp` | MCP stdio/HTTP server | `uv tool install "graphifyy[mcp]"` |
| `neo4j` | Neo4j export support | `uv tool install "graphifyy[neo4j]"` |
| `falkordb` | FalkorDB export support | `uv tool install "graphifyy[falkordb]"` |
| `svg` | SVG graph export | `uv tool install "graphifyy[svg]"` |
| `watch` | Filesystem watcher for automatic rebuilds | `uv tool install "graphifyy[watch]"` |
| `dm` | BYOND DreamMaker `.dm`/`.dme` AST extraction | `uv tool install "graphifyy[dm]"` |
| `pascal` | Pascal / Delphi `.pas`/`.dpr` AST extraction | `uv tool install "graphifyy[pascal]"` |
| `ocaml` | OCaml `.ml`/`.mli` AST extraction | `uv tool install "graphifyy[ocaml]"` |
| `commonlisp` | Common Lisp `.lisp`/`.cl` AST extraction | `uv tool install "graphifyy[commonlisp]"` |
| `robot` | Robot Framework `.robot`/`.resource` extraction | `uv tool install "graphifyy[robot]"` |
| `chinese` | Chinese query segmentation (jieba) | `uv tool install "graphifyy[chinese]"` |
| `all` | Everything above | `uv tool install "graphifyy[all]"` |

</details>

---

## Make your assistant always use the graph

Run this once in your project after building a graph:

| Platform | Command |
|----------|---------|
| Claude Code | `graphify claude install` |
| GitHub Copilot CLI | `graphify copilot install` |
| VS Code Copilot Chat | `graphify vscode install` |

This writes a small config file that tells your assistant to consult the knowledge graph for codebase questions, preferring scoped queries like `graphify query "<question>"` over reading the full report or grepping raw files.

- **Claude Code**: a `PreToolUse` hook fires automatically before search-style tool calls and before reading source files one by one, nudging your assistant toward `graphify query`.
- **Copilot**: instructions configure Copilot Chat and CLI to orient via the graph before file exploration.

To remove graphify from your assistant: `graphify claude uninstall` or `graphify copilot uninstall` (add `--purge` to also delete `graphify-out/`).

---

## What's in the report

- **God nodes** — the most-connected concepts in your project. Everything flows through these.
- **Surprising connections** — links between things that live in different files or modules. Ranked by how unexpected they are.
- **The "why"** — inline comments (`# NOTE:`, `# WHY:`, `# HACK:`), docstrings, and design rationale from docs are extracted as separate nodes linked to the code they explain.
- **Suggested questions** — 4–5 questions the graph is uniquely positioned to answer.
- **Deterministic confidence** — relationships are tagged `EXTRACTED` @ 1.0 confidence.

---

## What files it handles

| Type | Extensions / Formats | Details |
|------|---------------------|---------|
| **Code** (~40 tree-sitter grammars) | `.py .ts .mts .cts .js .jsx .tsx .mjs .go .rs .java .c .cpp .cc .cxx .h .hpp .cu .cuh .metal .rb .cs .kt .kts .scala .php .swift .lua .zig .ps1 .ex .m .jl .vue .svelte .astro .dart .sql .sh .bash` | Complete AST parsing: classes, functions, methods, calls, imports, inherits |
| **Docs & Notes** | `.md .mdx .txt .rst .yaml .yml` | Frontmatter, H1–H6 hierarchy, `[[wikilinks]]` (with aliases), `#tags`, markdown links |
| **Kubernetes** | `.yaml .yml` manifests | `Deployment`, `Service`, `ConfigMap`, `Secret`, `Ingress`, label/selector matches, image refs |
| **Helm** | `Chart.yaml`, `values.yaml`, `templates/*.yaml` | Sub-charts, template structure extraction, chart-to-resource dependency linkages |
| **Terraform & HCL** | `.tf .tfvars .hcl` | Resources, modules, variables, outputs, provider blocks, interpolation references |
| **AWS CloudFormation** | `.json .yaml .yml` templates | CloudFormation/SAM `Resources`, `Fn::Ref`, `Fn::GetAtt`, `DependsOn` |
| **Kafka & Event Schemas** | `server.properties`, `.avsc`, `.proto` | Topics, brokers, Avro records/fields, Protobuf messages, gRPC service gateways (`google.api.http`), topic-to-schema linkages |
| **GitHub Actions** | `.github/workflows/*.yml` | Workflows, jobs, steps, unpinned `uses:`, reusable workflows, secrets/env refs |
| **JSON Schema** | `*.schema.json`, `$schema` files | Dialects (Draft-04, Draft-07, 2020-12), schema definitions, `$defs`, Schema Registry mappings (Confluent, AWS Glue, Apicurio), local & cross-file `$ref` resolution |
| **Docker & Compose** | `Dockerfile`, `docker-compose.yml` | Base images (`FROM`), source copies (`COPY`/`ADD`), services, `depends_on`, volumes |
| **OpenAPI & AsyncAPI** | OpenAPI / AsyncAPI YAML & JSON specs | Paths/operations, async channels/messages, schema linkages |
| **SQL DDL** | `.sql` schemas | Tables, columns, primary & foreign-key constraints across tables |
| **Package Manifests** | `package.json`, `requirements.txt`, `poetry.lock`, `go.mod`, `Cargo.toml` | Manifest-level dependencies and lockfiles |
| **Bazel Build Graph** | `BUILD`, `BUILD.bazel`, `WORKSPACE`, `MODULE.bazel`, `.bzl` | Rules (`cc_library`, `py_binary`, etc.), targets, labels, `deps`, Bzlmod, Starlark `load()` |
| **Monorepo Workspaces** | `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `project.json`, `lerna.json` | Workspace packages, task pipelines, cross-package internal dependencies |
| **GitOps & Delivery** | `argoproj.io/v1alpha1` manifests | Argo CD `Application` & `ApplicationSet`, source repos, target clusters, cross-resolving to K8s/Helm |
| **Office** | `.docx .xlsx` | Requires `uv tool install graphifyy[office]` |

All files are parsed **100% locally with zero external API calls and zero network requests**.

---

## Common commands

```bash
graphify build .                   # build graph and search index for current folder
/graphify .                        # build graph via assistant slash command
graphify update .                  # incrementally re-extract only changed files
graphify lint                      # scan for drift, unpinned actions, missing secrets, broken refs
graphify trace "NodeA" "NodeB"     # trace shortest cross-format dependency chain
graphify explain "Concept"         # breakdown of BM25 + graph-hop + centrality ranking
graphify query "auth flow"         # FTS5 BM25 search expanded via graph traversal

graphify hook install              # auto-rebuild on git commit and branch switch
graphify merge-graphs a.json b.json # combine two graphs
```

See the [full command reference](#full-command-reference) below.

---

## Ignoring files

Create a `.graphifyignore` in your project root — same syntax as `.gitignore`, including `!` negation.

**`.gitignore` is respected automatically.** graphify reads the `.gitignore` in each directory. If a `.graphifyignore` is also present, the two are **merged** — `.graphifyignore` patterns are evaluated last, so they win on conflicts (including `!` negations). Adding a `.graphifyignore` only ever excludes more; it never re-includes a file your `.gitignore` already excluded. Subdirectory scoping works the same way as git — an ignore file only affects its own subtree.

Pass `--no-gitignore` to `graphify extract` when git-ignored generated or transpiled code belongs in the graph. This disables `.gitignore` and `.git/info/exclude`; `.graphifyignore` still applies.

```
# .graphifyignore
node_modules/
dist/
*.generated.py

# only index src/, ignore everything else
*
!src/
!src/**
```

---

## Team setup

`graphify-out/` is meant to be committed to git so everyone on the team starts with a map.

**Recommended `.gitignore` additions:**
```
graphify-out/cost.json        # local only
# graphify-out/cache/         # optional: commit for speed, skip to keep repo small
```

> `manifest.json` is now portable — keys are stored as relative paths and re-anchored on load, so committing it is safe and avoids a full rebuild on first checkout.

### Recommended workflow

Set this up once per clone. From then on, three of your normal git commands keep the graph current by themselves, and one keeps it in sync with your team:

| you do | graphify does |
|---|---|
| `graphify hook install` (once, right after cloning) | installs the hooks below, plus a merge driver so `graph.json` never shows conflict markers |
| `git commit` | rebuilds automatically — AST only, no API cost |
| `git checkout` / `git switch` (branches) | rebuilds automatically (a file-only `git checkout -- <path>` does not) |
| `git pull` / `git merge` | run `graphify update .` right after |
| `git push` | nothing to do |

The commit and branch-switch rebuilds run in the background and return immediately, so on a large repo the graph can lag the commit by a few seconds — step 5 covers the rare case where you query before it catches up.

**Step by step:**
1. Clone the repo and run `graphify hook install` once.
2. Commit and switch branches as normal — the graph stays current on its own.
3. After every `git pull` (or merge), run `graphify update .` to bring the graph in sync with what you just pulled. On a large or active repo, put it on autopilot with a pull alias:
   ```bash
   git config --global alias.gpull '!git pull && graphify update .'
   ```
4. When docs or papers change, run `/graphify --update` to refresh those nodes too (code and docs update independently).
5. If a query ever seems to be missing something you just added, run `graphify update .` first, then ask again.

---

## Using the graph directly

```bash
# query the graph from the terminal
graphify query "show the auth flow"
graphify query "what connects DigestAuth to Response?" --graph graphify-out/graph.json

# expose the graph as an MCP server (for repeated tool-call access)
python -m graphify.serve graphify-out/graph.json
python -m graphify.serve --graph graphify-out/graph.json  # --graph flag also accepted

# register with Kimi Code:
kimi mcp add --transport stdio graphify -- python -m graphify.serve graphify-out/graph.json

# or serve over HTTP so a whole team points at one URL (no local graphify needed):
python -m graphify.serve graphify-out/graph.json --transport http --port 8080
python -m graphify.serve graphify-out/graph.json --transport http --host 0.0.0.0 --api-key "$SECRET"
```

The MCP server gives your assistant structured access: `query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `list_prs`, `get_pr_impact`, `triage_prs`.

### Shared HTTP server

`--transport stdio` (the default) spawns one local server per developer. `--transport http` serves the same tools over the MCP Streamable HTTP transport, so a single shared process can serve the graph for the whole team — clients point their IDE MCP config at `http://<host>:8080/mcp` instead of running graphify locally.

| Flag | Default | Purpose |
|---|---|---|
| `--transport {stdio,http}` | `stdio` | Transport to serve on |
| `--host` | `127.0.0.1` | HTTP bind host (use `0.0.0.0` to expose beyond localhost) |
| `--port` | `8080` | HTTP bind port |
| `--api-key` | env `GRAPHIFY_API_KEY` | Require `Authorization: Bearer <key>` (or `X-API-Key`) |
| `--path` | `/mcp` | HTTP mount path |
| `--json-response` | off | Return plain JSON instead of SSE streams |
| `--stateless` | off | No per-session state (for load-balanced / CI deployments) |
| `--session-timeout` | `3600` | Reap idle stateful sessions after N seconds (`0` disables) |

The default `127.0.0.1` bind is loopback-only. Set `--host 0.0.0.0` **and** `--api-key` together when exposing on a shared host. Run it in a container:

```bash
docker build -t graphify .
docker run -p 8080:8080 -v "$(pwd)/graphify-out:/data" graphify \
  /data/graph.json --transport http --host 0.0.0.0 --api-key "$SECRET"
```

> **WSL / Linux note:** Ubuntu ships `python3`, not `python`. Use a venv to avoid conflicts:
> ```bash
> python3 -m venv .venv && .venv/bin/pip install "graphifyy[mcp]"
> ```

---

## Configuration & Environment Variables

graphify is 100% local with **zero LLM API calls and zero network requests**. No API keys are needed or read.

| Variable | Used for | Default |
|---|---|---|
| `GRAPHIFY_MAX_WORKERS` | AST extraction parallelism worker count | CPU count (up to 8) |
| `GRAPHIFY_FORCE` | Force graph rebuild even with fewer nodes | `0` |
| `GRAPHIFY_VIZ_NODE_LIMIT` | Node count limit for generating interactive `graph.html` | `5000` |
| `GRAPHIFY_QUERY_LOG_ENABLE` | Set to `1` to enable local query log at `~/.cache/graphify-queries.log` | `0` (off) |
| `GRAPHIFY_QUERY_LOG_DISABLE` | Set to `1` to force query log off | `0` |
| `GRAPHIFY_MAX_GRAPH_BYTES` | Override the 512 MiB graph.json size cap — e.g. `700MB`, `2GB` | `512MB` |

---

## Privacy

- **100% Local Execution** — Code, markdown, and IaC/config files are parsed locally using tree-sitter AST, deterministic YAML/HCL parsers, and SQLite FTS5. Nothing leaves your machine.
- **Zero API Keys** — No external API requests, no Anthropic/OpenAI/Gemini clients, no LLM dependencies.
- **Zero Embedding Models** — Pure statistical BM25 ranking + PageRank graph centrality. No downloaded neural weights or tokenizers.
- **No telemetry**, no usage tracking, no analytics.

---

## Troubleshooting

**`graphify: command not found` after installing**
The CLI is installed but its bin directory isn't on your shell's `PATH`. Pick the fix for how you installed:
- **uv** (`uv tool install graphifyy`): the command lands in uv's tool bin dir (`~/.local/bin`), which a fresh macOS/zsh setup often doesn't have on `PATH`. Run `uv tool update-shell`, then open a new terminal. (Find the dir with `uv tool dir --bin`.)
- **pipx** (`pipx install graphifyy`): run `pipx ensurepath`, then open a new terminal.
- **pip** (`pip install graphifyy`): pip installs scripts to a user bin dir that may not be on `PATH` — add `~/Library/Python/3.x/bin` (macOS) or `~/.local/bin` (Linux) to your `PATH` in `~/.zshrc`/`~/.bashrc`, or just run `python -m graphify`.

**`uvx graphify …` or `uv tool run graphify …` fails to resolve `graphify`**
The PyPI package is `graphifyy`; `graphify` is only the command it provides. `uv tool run` treats the first word as a *package name*, so it looks for a package called `graphify` and reports `No solution found … no versions of graphify`. Name the package explicitly: `uvx --from graphifyy graphify install` (same as `uv tool run --from graphifyy graphify install`). Or `uv tool install graphifyy` once and then call `graphify` directly.

**`uv run --with graphifyy python -m graphify` silently runs an older install**
`uv run` uses your *system* Python, so if an older `graphifyy` also lives there (e.g. a past `pip install graphifyy`), Python can find that copy first on `sys.path` and `--with graphifyy` won't override it. The fingerprint is a `warning: skill is from graphify <newer>, package is <older>` line — that means a different install was loaded, not just a stale skill. Check which copy actually loaded:
```bash
python -c "import graphify; print(graphify.__file__)"
```
Then run the installed command directly (it uses the uv-managed copy), or drop the stale system copy:
```bash
uvx --from graphifyy graphify build .   # names the package explicitly
pip uninstall graphifyy                 # or remove the old system install
```

**`python -m graphify` works but `graphify` command doesn't**
Your shell's `PATH` doesn't include the bin directory the command was installed to. Prefer `uv tool install` / `pipx install` over plain `pip`, then run `uv tool update-shell` / `pipx ensurepath` and open a new terminal (see the install notes above).

**`/graphify .` causes "path not recognized" in PowerShell**
PowerShell treats a leading `/` as a path separator. Use `graphify .` (no slash) on Windows.

**Graph has fewer nodes after `--update` or rebuild**
If a refactor deleted files, the old nodes linger. Pass `--force` (or set `GRAPHIFY_FORCE=1`) to overwrite even when the rebuild has fewer nodes.

**`extract` exits with "extraction was incomplete ... refusing to overwrite"**
When an extraction pass crashes or a walk can't fully read the corpus, the run would be smaller than a complete one, so `graphify extract` refuses to overwrite a larger existing graph with the partial result (protecting your `graph.json`). Fix the underlying failure and re-run, or pass `--allow-partial` to overwrite anyway.

**Graph has duplicate nodes for the same entity (ghost duplicates)**
Ghost duplicates (same symbol appearing twice — once from AST extraction with a source location, once from semantic extraction without) are now automatically merged at build time. If you see this in a graph built before v0.8.33, run a full re-extract to clean up:
```bash
graphify extract . --force
```


**Graph HTML is too large to open in a browser (>5000 nodes)**
Skip HTML generation and use the JSON directly:
```bash
graphify cluster-only ./my-project --no-viz
graphify query "..."
```

**`graph.json` has conflict markers after two devs commit at once**
Run `graphify hook install` — it sets up a git merge driver that union-merges `graph.json` automatically so conflicts never happen.

**Graph doesn't reflect a teammate's recent changes**
Run `graphify update .` right after `git pull` or any merge — see [Recommended workflow](#recommended-workflow). Commits and branch switches update the graph automatically via the installed hooks; syncing with a pull is the one step you run yourself. Fold it into a pull alias so it's one command either way:
```bash
git config --global alias.gpull '!git pull && graphify update .'
```
Confirm the hooks are active with `graphify hook status`; re-run `graphify hook install` after an interpreter upgrade/reinstall to refresh them.

**Skill version mismatch warning in your IDE**
Your installed graphify version is different from the skill file. Update:
```bash
uv tool upgrade graphifyy
graphify install  # overwrites the skill file
```

**Claude Code prompt cache invalidated after every `graphify extract`**
Graphify writes output files (`graph.json`, `graphify-out/`) into the workspace. If those paths aren't ignored, every write invalidates Claude Code's prompt cache, forcing a full re-upload at cache-write rates on the next turn. Add them to `.claudeignore`:
```text
# .claudeignore
graph.json
graphify-out/
```

---

## Full command reference

```bash
# Building & updating the graph
graphify build .                        # build graph and search index for current directory
/graphify .                             # run graphify via assistant slash command
graphify build ./src                    # build graph for a specific folder
graphify update .                       # incrementally re-extract only changed files
graphify build . --no-viz               # skip HTML visualization (generate graph.json + index.db + GRAPH_REPORT.md)
graphify build . --wiki                 # build agent-crawlable markdown wiki

# Search, retrieval & exploration
graphify query "auth flow"              # BM25 statistical search expanded via 1-2 hop graph traversal
graphify query "auth flow" --limit 10   # return top 10 results
graphify explain "UserService"          # breakdown of BM25 score, hop distance, and centrality
graphify trace "Frontend" "Database"    # find shortest path across code, IaC, and config dependencies

# Linting & architecture drift detection
graphify lint                           # detect unpinned actions, environment drift, missing secrets, broken refs

# Git hooks & automation
graphify hook install                   # auto-rebuild on git commit and branch switch
graphify hook uninstall
graphify hook status

# Assistant integrations
graphify install                        # install skill for Claude Code (default)
graphify install --project              # project-scoped install
graphify claude install                 # install Claude Code skill + PreToolUse hook
graphify claude uninstall
graphify copilot install                # install GitHub Copilot CLI skill
graphify copilot uninstall
graphify vscode install                 # configure VS Code Copilot Chat instructions
graphify vscode uninstall
graphify uninstall                      # remove graphify assistant integrations

# Visualization & export
graphify export callflow-html           # generate call-flow HTML visualization
graphify merge-graphs a.json b.json     # combine two graphs into one
graphify cluster-only .                 # rerun Leiden community detection on existing graph

# MCP server (stdio and shared HTTP)
python -m graphify.serve graphify-out/graph.json
python -m graphify.serve graphify-out/graph.json --transport http --port 8080
```

---

## Learn more

- [How it works](docs/how-it-works.md) — the extraction pipeline, community detection, confidence scoring, benchmarks
- [ARCHITECTURE.md](ARCHITECTURE.md) — module breakdown, how to add a language
- [Optional integrations](docs/docker-mcp-sqlite.md) — Docker MCP Toolkit + SQLite
- [The Memory Layer](https://safishamsi.gumroad.com/l/qetvlo) — the book on the ideas behind graphify, the architecture end to end

---

## graphify Enterprise

[**graphify Enterprise**](https://graphify.com) is the always-on layer built on top of graphify — it applies the same graph approach to your entire working context: meetings, files, docs, and code, updating continuously in the background.

Built for people and teams whose work lives across hundreds of conversations and documents they can never fully reconstruct.

**[Join the waitlist at graphify.com](https://graphify.com).** Free trial launching soon.

---

<details>
<summary>Contributing</summary>

### Development setup

The project uses [uv](https://docs.astral.sh/uv/) for dev workflow. Install it once, then:

```bash
git clone https://github.com/safishamsi/graphify.git
cd graphify
git checkout v8                        # active development branch

# Create the project venv and install graphify + all extras + the dev group
# (pytest). uv installs the dev dependency group by default; pass --no-dev to
# skip it.
uv sync --all-extras
```

Verify the editable install:
```bash
uv run graphify --version
uv run python -c "import graphify; print(graphify.__file__)"
```

### Running tests

```bash
uv run pytest tests/ -q                # run the full suite
uv run pytest tests/test_extract.py -q # one module
uv run pytest tests/ -q -k "python"    # filter by name
```

### CI parity checks

The authoritative CI commands live in [`.github/workflows/`](.github/workflows/).
For local CI-style verification, use Python 3.10, 3.12, 3.13, or 3.14 and run:

```bash
uv sync --all-extras --frozen
uv run --frozen pytest tests/ -q --tb=short
uv run --frozen python -m tools.skillgen --check
uv run --frozen python -m tools.skillgen --audit-coverage
uv run --frozen python -m tools.skillgen --schema-singleton
uv run --frozen python -m tools.skillgen --monolith-roundtrip
uv run --frozen python -m tools.skillgen --always-on-roundtrip
uv run --frozen graphify --help
uv run --frozen graphify install
```

Ruff is useful as an additional local check (`uv run --frozen ruff check .`),
but is not currently a blocking CI job. Pyright is also local/advisory unless it
is added to CI later. The Bandit and pip-audit CI steps currently use
`continue-on-error`, so their findings are advisory rather than blocking.

> macOS note: the test suite includes both `sample.f90` and `sample.F90` fixtures. These collide on case-insensitive HFS+ / APFS file systems. Run on Linux or in a Docker container if you need to test both Fortran variants simultaneously.

> Windows note: the native Windows test suite exercises symbolic links, long
> paths, POSIX permissions, path separators, and UTF-8 filesystem behavior.
> Enable Windows Developer Mode to allow unprivileged symbolic-link creation, or
> run the tests from an elevated shell. Enable the Windows `LongPathsEnabled`
> policy before relying on long-path tests. Restart affected shells or applications
> after changing either setting. For exact parity with the blocking GitHub Actions
> test matrix, run the suite in WSL or Linux; CI currently runs on Ubuntu with
> Python 3.10, 3.12, 3.13, and 3.14. Pyright is available as a local advisory check, but it is
> not currently a blocking CI job.

### Git workflow

- Active development happens on the `v8` branch.
- Commit style: `fix: <description>` / `feat: <description>` / `docs: <description>`
- Before opening a PR, run `uv run pytest tests/ -q` and confirm it passes.
- Add a fixture file to `tests/fixtures/` and tests to `tests/test_languages.py` for any new language extractor.

### What to contribute

**Worked examples** are the most useful contribution. Run `/graphify` on a real corpus, save the output to `worked/{slug}/`, write an honest `review.md` covering what the graph got right and wrong, and open a PR.

**Extraction bugs** — open an issue with the input file, the cache entry (`graphify-out/cache/`), and what was missed or wrong.

See [ARCHITECTURE.md](ARCHITECTURE.md) for module responsibilities and how to add a language.

</details>

---

## Community and links

<p align="center">
  <a href="https://graphify.com"><img src="https://img.shields.io/badge/Website-graphify.com-4c1?style=flat&logo=googlechrome&logoColor=white" alt="Website"/></a>
  <a href="https://discord.gg/2DDrEgvZb4"><img src="https://img.shields.io/badge/Discord-Join-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"/></a>
  <a href="https://x.com/graphify"><img src="https://img.shields.io/badge/X-graphify-000000?logo=x&logoColor=white" alt="X"/></a>
  <a href="https://www.youtube.com/@graphifylabs"><img src="https://img.shields.io/badge/YouTube-Graphify%20Labs-FF0000?style=flat&logo=youtube&logoColor=white" alt="YouTube"/></a>
  <a href="https://github.com/sponsors/safishamsi"><img src="https://img.shields.io/badge/sponsor-safishamsi-ea4aaa?logo=github-sponsors" alt="Sponsor"/></a>
  <a href="https://safishamsi.gumroad.com/l/qetvlo"><img src="https://img.shields.io/badge/Book-The%20Memory%20Layer-2ea44f?style=flat&logo=gitbook&logoColor=white" alt="The Memory Layer"/></a>
</p>
