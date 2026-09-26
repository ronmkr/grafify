```powershell
# Detect Python with graph_fy — uv/pipx-aware (fixes #831)
New-Item -ItemType Directory -Force -Path graph_fy_out | Out-Null
$GRAPHIFY_PYTHON = $null

function Find-GraphifyPython {
    # 1. uv tool install — 'uv tool dir' is authoritative, respects UV_TOOL_DIR automatically
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $uvDir = (uv tool dir 2>$null).Trim()
        if ($uvDir) {
            $py = Join-Path $uvDir "graphifyy\Scripts\python.exe"
            if (Test-Path $py) {
                & $py -c "import graph_fy" 2>$null
                if ($LASTEXITCODE -eq 0) { return $py }
            }
        }
    }
    # 2. pipx install — 'pipx environment' respects PIPX_HOME automatically
    if (Get-Command pipx -ErrorAction SilentlyContinue) {
        $venvs = (pipx environment --value PIPX_LOCAL_VENVS 2>$null).Trim()
        if ($venvs) {
            $py = Join-Path $venvs "graphifyy\Scripts\python.exe"
            if (Test-Path $py) {
                & $py -c "import graph_fy" 2>$null
                if ($LASTEXITCODE -eq 0) { return $py }
            }
        }
    }
    # 3. Active venv / conda / pip-into-current-env
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd) {
        & $pyCmd.Source -c "import graph_fy" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return (& $pyCmd.Source -c "import sys; print(sys.executable)").Trim()
        }
    }
    return $null
}

# Try to find the right Python (uv → pipx → active env)
$GRAPHIFY_PYTHON = Find-GraphifyPython

# Not found — install then re-detect
if (-not $GRAPHIFY_PYTHON) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv tool install --upgrade graphifyy -q 2>&1 | Select-Object -Last 3
    } else {
        pip install graphifyy -q 2>&1 | Select-Object -Last 3
    }
    $GRAPHIFY_PYTHON = Find-GraphifyPython
}

# Save interpreter path — all subsequent steps read this.
# `Out-File -Encoding utf8` always writes a BOM on Windows PowerShell 5.1 (utf8NoBOM
# only exists from PowerShell 6), and that BOM rides into the saved path, so the hook
# rebuild fails with WinError 123 (#3028). WriteAllText with an explicit BOM-less
# encoding writes the bytes POSIX writes, and adds no trailing newline.
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText((Join-Path $PWD 'graph_fy_out\.graphify_python'), [string]$GRAPHIFY_PYTHON, $Utf8NoBom)
# Save scan root so `graph_fy update` (no args) knows where to look next time.
# INPUT_PATH is captured through a single-quoted (literal) here-string, never
# substituted directly into the command line: an unquoted bareword argument
# substituted here would let a malicious path (a stray `;`, `|`, or `$(...)`)
# execute as script code the moment this line runs.
$InputPathRaw = @'
INPUT_PATH
'@
[System.IO.File]::WriteAllText((Join-Path $PWD 'graph_fy_out\.graphify_root'), (Resolve-Path $InputPathRaw.Trim()).Path, $Utf8NoBom)
# Ensure graph_fy_out/ is in .gitignore if in a git repository
if (Test-Path -Path '.git') {
    $giPath = Join-Path $PWD '.gitignore'
    if (-not (Test-Path $giPath) -or -not (Select-String -Path $giPath -Pattern 'graph_fy_out' -SimpleMatch -Quiet)) {
        Add-Content -Path $giPath -Value "`n# graph_fy output`ngraph_fy_out/`ngraph_fy_out/`n.graphify_*`n.graphify_python`n.graphify_root"
    }
}
```

If the import succeeds, print nothing and move straight to Step 2.

**In every subsequent block, run Python through the saved interpreter — `& (Get-Content graph_fy_out\.graphify_python)` in place of a bare `python3` — so every step uses the interpreter that actually has graph_fy.**
