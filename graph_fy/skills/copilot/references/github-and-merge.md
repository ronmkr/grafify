# graph_fy reference: GitHub clone and cross-repo merge

Load this when the user passed one or more `https://github.com/...` URLs, or named several local subfolders to merge into one graph.

### Step 0 - Clone GitHub repo(s) (only if a GitHub URL was given)

**Single repo:**
```bash
LOCAL_PATH=$(graph_fy clone <github-url> [--branch <branch>])
# Use LOCAL_PATH as the target for all subsequent steps
```

**Multiple repos (cross-repo graph):**
```bash
# Clone each repo, run the full pipeline on each, then merge
graph_fy clone <url1>   # → ~/.graphify/repos/<owner1>/<repo1>
graph_fy clone <url2>   # → ~/.graphify/repos/<owner2>/<repo2>
# Run /graph_fy on each local path to produce their graph.json files
# Then merge:
graph_fy merge-graphs \
  ~/.graphify/repos/<owner1>/<repo1>/graph_fy_out/graph.json \
  ~/.graphify/repos/<owner2>/<repo2>/graph_fy_out/graph.json \
  --out graph_fy_out/cross-repo-graph.json
```

Graphify clones into `~/.graphify/repos/<owner>/<repo>` and reuses existing clones on repeat runs. Each node in the merged graph carries a `repo` attribute so you can filter by origin.

**Multiple local subfolders (monorepo or multi-service layout):**

The skill pipeline writes all intermediate and final outputs to `graph_fy_out/` in the current working directory. Running the skill on each subfolder separately will clobber the same output dir. Instead, use the CLI directly for each subfolder — it places `graph_fy_out/` *inside* the scanned path:

```bash
graph_fy extract ./core/     # → ./core/graph_fy_out/graph.json
graph_fy extract ./service/  # → ./service/graph_fy_out/graph.json
graph_fy extract ./platform/ # → ./platform/graph_fy_out/graph.json
# Add --backend gemini|kimi|openai|deepseek|claude-cli depending on which API key you have set

# Then merge at the project root:
graph_fy merge-graphs \
  ./core/graph_fy_out/graph.json \
  ./service/graph_fy_out/graph.json \
  ./platform/graph_fy_out/graph.json \
  --out graph_fy_out/graph.json
```

Once `graph_fy_out/graph.json` exists, the fast path above takes over: any codebase question runs `graph_fy query` directly on the merged graph — no re-extraction, no size gate.
