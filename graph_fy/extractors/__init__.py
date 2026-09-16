"""Per-language extractors, incrementally migrated out of graph_fy/extract.py.

Dispatch still flows through graph_fy.extract (the facade re-exports every
moved name), so importing from graph_fy.extract keeps working unchanged.
LANGUAGE_EXTRACTORS is the registry seed; wiring dispatch through it is a
later, separate step. See MIGRATION.md for how to port another language.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from graph_fy.extractors.apex import extract_apex
from graph_fy.extractors.bash import extract_bash
from graph_fy.extractors.blade import extract_blade
from graph_fy.extractors.commonlisp import extract_commonlisp
from graph_fy.extractors.dart import extract_dart
from graph_fy.extractors.dm import extract_dm, extract_dmf, extract_dmi, extract_dmm
from graph_fy.extractors.elixir import extract_elixir
from graph_fy.extractors.fortran import extract_fortran
from graph_fy.extractors.go import extract_go
from graph_fy.extractors.json_config import extract_json
from graph_fy.extractors.julia import extract_julia
from graph_fy.extractors.markdown import extract_markdown, extract_pdf
from graph_fy.extractors.objc import extract_objc
from graph_fy.extractors.pascal import extract_pascal
from graph_fy.extractors.pascal_forms import extract_delphi_form, extract_lazarus_form
from graph_fy.extractors.powershell import extract_powershell, extract_powershell_manifest
from graph_fy.extractors.razor import extract_razor
from graph_fy.extractors.rust import extract_rust
from graph_fy.extractors.sln import extract_sln
from graph_fy.extractors.sql import extract_sql
from graph_fy.extractors.terraform import extract_terraform
from graph_fy.extractors.verilog import extract_verilog
from graph_fy.extractors.zig import extract_zig

LANGUAGE_EXTRACTORS: dict[str, Callable[[Path], dict]] = {
    "apex": extract_apex,
    "bash": extract_bash,
    "blade": extract_blade,
    "commonlisp": extract_commonlisp,
    "dart": extract_dart,
    "delphi_form": extract_delphi_form,
    "dm": extract_dm,
    "dmf": extract_dmf,
    "dmi": extract_dmi,
    "dmm": extract_dmm,
    "elixir": extract_elixir,
    "fortran": extract_fortran,
    "go": extract_go,
    "json": extract_json,
    "julia": extract_julia,
    "lazarus_form": extract_lazarus_form,
    "markdown": extract_markdown,
    "pdf": extract_pdf,
    "objc": extract_objc,
    "pascal": extract_pascal,
    "powershell": extract_powershell,
    "powershell_manifest": extract_powershell_manifest,
    "razor": extract_razor,
    "rust": extract_rust,
    "sln": extract_sln,
    "sql": extract_sql,
    "terraform": extract_terraform,
    "verilog": extract_verilog,
    "zig": extract_zig,
}
