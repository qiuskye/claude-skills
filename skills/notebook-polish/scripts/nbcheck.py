#!/usr/bin/env python3
"""nbcheck.py — static quality report for Jupyter notebooks (.ipynb).

Usage:
    python3 nbcheck.py notebook.ipynb

Stdlib only (json, sys, re). Parses the notebook JSON and reports:
  - cell counts (code / markdown / empty) and markdown/code ratio
  - unexecuted cells and out-of-order execution counts (reproducibility signal)
  - oversized outputs (> 50 KB, e.g. embedded base64 images)
  - duplicated and late imports
  - very long code cells (> 40 lines, candidates for functions)
  - versioned variable names (df2, df3, final_v2, ...) — naming smell

Exit code: 0 if no warnings, 1 if warnings were found, 2 on usage/parse error.
"""

import json
import re
import sys

MAX_OUTPUT_BYTES = 50 * 1024   # 50 KB
MAX_CELL_LINES = 40
MIN_MARKDOWN_RATIO = 0.20

IMPORT_RE = re.compile(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import\b)")
ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=[^=]")
SMELL_NAME_RE = re.compile(r"^(?:[A-Za-z_]*[A-Za-z]\d+|\w*_v\d+)$")


def cell_source(cell):
    src = cell.get("source", "")
    if isinstance(src, list):
        src = "".join(src)
    return src


def output_size(cell):
    outputs = cell.get("outputs", [])
    if not outputs:
        return 0
    return len(json.dumps(outputs))


def fmt_size(n):
    if n >= 1024 * 1024:
        return "%.1f MB" % (n / (1024 * 1024))
    if n >= 1024:
        return "%.1f KB" % (n / 1024)
    return "%d B" % n


def analyze(path):
    try:
        with open(path, encoding="utf-8") as f:
            nb = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print("ERROR: cannot read notebook: %s" % e, file=sys.stderr)
        sys.exit(2)

    cells = nb.get("cells", [])
    warnings = []

    code_cells = []      # (cell_index_1based, cell)
    md_cells = []
    empty_cells = []     # cell indices
    for i, cell in enumerate(cells, start=1):
        ctype = cell.get("cell_type")
        src = cell_source(cell)
        if not src.strip():
            empty_cells.append(i)
        if ctype == "code":
            code_cells.append((i, cell))
        elif ctype == "markdown":
            md_cells.append((i, cell))

    n_code = len(code_cells)
    n_md = len(md_cells)

    # --- Execution order ----------------------------------------------------
    unexecuted = []
    exec_seq = []  # (cell_index, execution_count) in notebook order
    for i, cell in code_cells:
        if not cell_source(cell).strip():
            continue  # empty code cells are reported separately
        ec = cell.get("execution_count")
        if ec is None:
            unexecuted.append(i)
        else:
            exec_seq.append((i, ec))

    out_of_order = []
    prev = None
    for i, ec in exec_seq:
        if prev is not None and ec <= prev[1]:
            out_of_order.append((i, ec, prev[0], prev[1]))
        prev = (i, ec)

    # --- Outputs -------------------------------------------------------------
    big_outputs = []
    for i, cell in code_cells:
        size = output_size(cell)
        if size > MAX_OUTPUT_BYTES:
            big_outputs.append((i, size))

    # --- Imports -------------------------------------------------------------
    imports = []  # (cell_index, code_cell_position_1based, module, line)
    for pos, (i, cell) in enumerate(code_cells, start=1):
        for line in cell_source(cell).splitlines():
            m = IMPORT_RE.match(line)
            if m:
                module = (m.group(1) or m.group(2)).split(".")[0]
                imports.append((i, pos, module, line.strip()))

    seen = {}
    duplicated = {}  # module -> [cell indices]
    for i, pos, module, line in imports:
        if module in seen and i not in duplicated.get(module, [seen[module]]):
            duplicated.setdefault(module, [seen[module]]).append(i)
        else:
            seen.setdefault(module, i)

    late_threshold = max(3, n_code // 4)
    late_imports = [(i, line) for i, pos, module, line in imports
                    if pos > late_threshold]

    # --- Long cells ----------------------------------------------------------
    long_cells = []
    for i, cell in code_cells:
        n_lines = len([l for l in cell_source(cell).splitlines() if l.strip()])
        if n_lines > MAX_CELL_LINES:
            long_cells.append((i, n_lines))

    # --- Naming smells -------------------------------------------------------
    smells = {}  # name -> set of cell indices
    for i, cell in code_cells:
        for line in cell_source(cell).splitlines():
            m = ASSIGN_RE.match(line)
            if m:
                name = m.group(1)
                if SMELL_NAME_RE.match(name):
                    smells.setdefault(name, set()).add(i)

    # --- Report --------------------------------------------------------------
    print("=" * 60)
    print("Notebook report: %s" % path)
    print("=" * 60)

    print("\n[Cells]")
    print("  Code cells:      %d" % n_code)
    print("  Markdown cells:  %d" % n_md)
    print("  Empty cells:     %d%s" % (
        len(empty_cells),
        "  (cells %s)" % ", ".join(map(str, empty_cells)) if empty_cells else ""))
    ratio = (n_md / n_code) if n_code else 0.0
    print("  Markdown/code ratio: %.2f" % ratio)
    if empty_cells:
        warnings.append("%d empty cell(s): %s — delete them."
                        % (len(empty_cells), ", ".join(map(str, empty_cells))))
    if n_code and ratio < MIN_MARKDOWN_RATIO:
        warnings.append("Markdown/code ratio %.2f is below %.2f — the notebook "
                        "lacks narrative (add a title, section headers and "
                        "conclusions)." % (ratio, MIN_MARKDOWN_RATIO))

    print("\n[Execution order]")
    if unexecuted:
        print("  Unexecuted code cells: %s" % ", ".join(map(str, unexecuted)))
        warnings.append("Code cell(s) never executed: %s — run the whole "
                        "notebook top to bottom."
                        % ", ".join(map(str, unexecuted)))
    else:
        print("  Unexecuted code cells: none")
    if out_of_order:
        for i, ec, pj, pec in out_of_order:
            print("  Out of order: cell %d has execution_count %d but cell %d "
                  "(earlier) has %d" % (i, ec, pj, pec))
        warnings.append("Execution counts are not increasing top-to-bottom — "
                        "the notebook was likely run out of order and may not "
                        "be reproducible. Do Restart & Run All.")
    else:
        print("  Execution counts: in order")

    print("\n[Outputs]")
    if big_outputs:
        for i, size in big_outputs:
            print("  Cell %d: output is %s (> %s)"
                  % (i, fmt_size(size), fmt_size(MAX_OUTPUT_BYTES)))
        warnings.append("%d cell(s) with oversized outputs (often embedded "
                        "images) — clear them before committing."
                        % len(big_outputs))
    else:
        print("  No oversized outputs (limit %s per cell)"
              % fmt_size(MAX_OUTPUT_BYTES))

    print("\n[Imports]")
    if duplicated:
        for module, cells_ in sorted(duplicated.items()):
            print("  Duplicated: '%s' imported in cells %s"
                  % (module, ", ".join(map(str, cells_))))
        warnings.append("Duplicated imports: %s — keep a single import cell "
                        "at the top." % ", ".join(sorted(duplicated)))
    else:
        print("  No duplicated imports")
    if late_imports:
        for i, line in late_imports:
            print("  Late import in cell %d: %s" % (i, line))
        warnings.append("%d late import(s) (after the first %d code cells) — "
                        "move all imports to one cell at the top."
                        % (len(late_imports), late_threshold))
    else:
        print("  No late imports")

    print("\n[Long cells]")
    if long_cells:
        for i, n in long_cells:
            print("  Cell %d: %d lines of code (> %d)" % (i, n, MAX_CELL_LINES))
        warnings.append("%d cell(s) longer than %d lines — extract helper "
                        "functions or split into smaller cells."
                        % (len(long_cells), MAX_CELL_LINES))
    else:
        print("  No code cells over %d lines" % MAX_CELL_LINES)

    print("\n[Naming]")
    if smells:
        for name in sorted(smells):
            print("  '%s' assigned in cell(s) %s"
                  % (name, ", ".join(map(str, sorted(smells[name])))))
        warnings.append("Versioned variable names (%s) — use descriptive names "
                        "(e.g. df_clean, df_features) instead of numbering."
                        % ", ".join(sorted(smells)))
    else:
        print("  No versioned variable names detected")

    print("\n[WARNINGS]")
    if warnings:
        for w in warnings:
            print("  - %s" % w)
    else:
        print("  None. The notebook looks clean.")

    return 1 if warnings else 0


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 nbcheck.py notebook.ipynb", file=sys.stderr)
        sys.exit(2)
    sys.exit(analyze(sys.argv[1]))


if __name__ == "__main__":
    main()
