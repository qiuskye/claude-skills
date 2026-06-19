#!/usr/bin/env python3
"""nbcheck.py — static quality report for Jupyter notebooks (.ipynb).

Usage:
    python3 nbcheck.py notebook.ipynb

Stdlib only (json, sys, re). Parses the notebook JSON and reports:
  - cell counts (code / markdown / empty) and markdown/code ratio
  - unexecuted cells and out-of-order execution counts (reproducibility signal)
  - error outputs saved in the file (a cell raised an exception when last run)
  - oversized outputs (> 50 KB, e.g. embedded base64 images)
  - duplicated and late imports
  - very long code cells (> 40 lines, candidates for functions)
  - versioned variable names (df + df2, final + final_v2, ...) — naming smell

Exit code: 0 if no warnings, 1 if warnings were found, 2 on usage/parse error.
"""

import io
import json
import re
import sys
import tokenize
from typing import Any, List, Optional

MAX_OUTPUT_BYTES = 50 * 1024   # 50 KB
MAX_CELL_LINES = 40
MIN_MARKDOWN_RATIO = 0.20

IMPORT_RE = re.compile(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import\b)")
ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=[^=]")
# A *candidate* versioned name: an alphabetic base followed by either an
# explicit "_v<num>" suffix (final_v2 -> base "final") or a small number
# directly (df2 -> base "df"). The "_v" alternative is matched first and its
# base captured separately so it is not swallowed by the generic base group.
# A candidate is only reported as a smell once the un-numbered base is also
# assigned in the notebook (see version_base), which avoids false positives on
# identifiers whose trailing digit is intrinsic (utf8, base64, sha256, col2,
# x1, model123).
SMELL_NAME_RE = re.compile(
    r"^(?:(?P<vbase>[A-Za-z_]*[A-Za-z])_v\d{1,3}"
    r"|(?P<nbase>[A-Za-z_]*[A-Za-z])\d{1,3})$")


def version_base(name: str) -> Optional[str]:
    """Return the un-numbered base of a versioned candidate name, or None."""
    m = SMELL_NAME_RE.match(name)
    if not m:
        return None
    return m.group("vbase") or m.group("nbase")


def cell_source(cell: Any) -> str:
    """Return a cell's source as a single string, tolerating malformed cells.

    A well-formed notebook stores ``source`` as a string or a list of strings,
    but third-party tooling sometimes emits other shapes (a bare number, a list
    containing nulls, a missing key). We coerce defensively so a single bad
    cell never aborts the whole report.
    """
    if not isinstance(cell, dict):
        return ""
    src = cell.get("source", "")
    if isinstance(src, list):
        return "".join(s for s in src if isinstance(s, str))
    if isinstance(src, str):
        return src
    return ""


def code_lines(src: str) -> List[str]:
    """Return ``src`` split into physical lines with strings/comments blanked.

    The import/assignment checks below scan line by line with regexes, which
    cannot tell real code from text inside a string or comment — so an
    assignment written inside a triple-quoted SQL block (``query = '''... x =
    1 ...'''``) used to fire a false "versioned variable" warning. We tokenize
    the source and overwrite every string- and comment-token's span with
    spaces (keeping newlines so line numbers and indentation are preserved),
    leaving only genuine code for the regexes. If the cell does not parse
    (partial snippets, magics, Python 2), we fall back to the raw lines so the
    previous best-effort behavior is retained.
    """
    raw = src.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return src.splitlines()

    # Work on a mutable list of characters per line so we can blank spans.
    chars = [list(line) for line in raw]
    blank_types = (tokenize.STRING, tokenize.COMMENT)
    if hasattr(tokenize, "FSTRING_START"):
        blank_types += (tokenize.FSTRING_START, tokenize.FSTRING_MIDDLE,
                        tokenize.FSTRING_END)
    for tok in tokens:
        if tok.type not in blank_types:
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        for row in range(srow, erow + 1):
            idx = row - 1
            if idx < 0 or idx >= len(chars):
                continue
            line_chars = chars[idx]
            lo = scol if row == srow else 0
            hi = ecol if row == erow else len(line_chars)
            for c in range(lo, min(hi, len(line_chars))):
                if line_chars[c] != "\n":
                    line_chars[c] = " "
    blanked = "".join("".join(lc) for lc in chars)
    return blanked.splitlines()


def output_size(cell: dict) -> int:
    """Return the serialized byte length of a code cell's saved outputs.

    Approximates how much weight the outputs add to the notebook file by
    re-serializing them; 0 when the cell has no outputs. Used to flag oversized
    outputs (e.g. embedded base64 images) that bloat the file and pollute diffs.
    """
    outputs = cell.get("outputs", [])
    if not isinstance(outputs, list):
        return 0
    if not outputs:
        return 0
    return len(json.dumps(outputs))


def has_error_output(cell: dict) -> bool:
    """Return True if a code cell has a saved error output (an exception).

    Jupyter records an uncaught exception as an output with
    ``output_type == "error"``. Its presence means the cell raised the last
    time it ran, so the committed notebook does not run cleanly top to bottom —
    a strong, deterministic reproducibility signal. Malformed (non-dict)
    outputs are ignored so a single bad entry never aborts the report.
    """
    outputs = cell.get("outputs", [])
    if not isinstance(outputs, list):
        return False
    return any(isinstance(o, dict) and o.get("output_type") == "error"
               for o in outputs)


def fmt_size(n: int) -> str:
    """Format a byte count as a human-readable string (B / KB / MB)."""
    if n >= 1024 * 1024:
        return "%.1f MB" % (n / (1024 * 1024))
    if n >= 1024:
        return "%.1f KB" % (n / 1024)
    return "%d B" % n


def analyze(path: str) -> int:
    """Run all static checks on the notebook at ``path`` and print the report.

    Returns the would-be exit code: 1 if any warnings were found, 0 otherwise.
    Calls ``sys.exit(2)`` directly on unreadable or malformed notebook files.
    """
    try:
        with open(path, encoding="utf-8") as f:
            nb = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print("ERROR: cannot read notebook: %s" % e, file=sys.stderr)
        sys.exit(2)

    if not isinstance(nb, dict):
        print("ERROR: %s is not a notebook (top-level JSON is %s, expected an "
              "object)" % (path, type(nb).__name__), file=sys.stderr)
        sys.exit(2)

    # nbformat 4+ stores cells at the top level. Older notebooks (nbformat 3
    # and earlier) nest them under worksheets[].cells, which this tool does not
    # support; silently treating such a file as having zero cells would report
    # it "clean", so fail loudly instead.
    nbformat_major = nb.get("nbformat")
    if "cells" not in nb and (
        "worksheets" in nb
        or (isinstance(nbformat_major, int) and nbformat_major < 4)
    ):
        print("ERROR: %s uses an unsupported notebook format (nbformat %s with "
              "worksheets[].cells); convert it to nbformat 4+ first "
              "(e.g. `jupyter nbconvert --to notebook`)."
              % (path, nbformat_major), file=sys.stderr)
        sys.exit(2)

    cells = nb.get("cells", [])
    if not isinstance(cells, list):
        print("ERROR: %s has a malformed 'cells' field (expected a list, got "
              "%s)" % (path, type(cells).__name__), file=sys.stderr)
        sys.exit(2)

    warnings = []

    code_cells = []      # (cell_index_1based, cell)
    md_cells = []
    empty_cells = []     # cell indices
    for i, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict):
            continue  # skip malformed (non-object) cell entries
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
        elif isinstance(ec, int) and not isinstance(ec, bool):
            exec_seq.append((i, ec))
        # A non-integer execution_count is malformed; ignore it for the
        # ordering check rather than crashing on the comparison below.

    out_of_order = []
    prev = None
    for i, ec in exec_seq:
        if prev is not None and ec <= prev[1]:
            out_of_order.append((i, ec, prev[0], prev[1]))
        prev = (i, ec)

    # --- Outputs -------------------------------------------------------------
    big_outputs = []
    error_outputs = []  # cell indices whose saved output is an exception
    for i, cell in code_cells:
        size = output_size(cell)
        if size > MAX_OUTPUT_BYTES:
            big_outputs.append((i, size))
        if has_error_output(cell):
            error_outputs.append(i)

    # --- Imports -------------------------------------------------------------
    imports = []  # (cell_index, code_cell_position_1based, module, line)
    for pos, (i, cell) in enumerate(code_cells, start=1):
        for line in code_lines(cell_source(cell)):
            m = IMPORT_RE.match(line)
            if m:
                module = (m.group(1) or m.group(2)).split(".")[0]
                imports.append((i, pos, module, line.strip()))

    # A module is "duplicated" if it is imported more than once, whether across
    # cells (import in cell 1 and cell 5) or twice within the same cell. Track
    # every cell index that imports each module, keeping repeats so two imports
    # in one cell surface that cell twice.
    module_cells = {}  # module -> [cell indices, with repeats]
    for i, pos, module, line in imports:
        module_cells.setdefault(module, []).append(i)
    duplicated = {module: cells_
                  for module, cells_ in module_cells.items()
                  if len(cells_) > 1}

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
    # First collect every assigned name, then only flag numbered names whose
    # un-numbered base is also assigned (df + df2, final + final_v2). This
    # confirms genuine versioning instead of flagging any identifier ending in
    # a digit (utf8, base64, col2, ...), which produced noisy false positives.
    assigned = {}     # name -> set of cell indices
    candidates = {}   # numbered name -> (base, set of cell indices)
    for i, cell in code_cells:
        for line in code_lines(cell_source(cell)):
            m = ASSIGN_RE.match(line)
            if not m:
                continue
            name = m.group(1)
            assigned.setdefault(name, set()).add(i)
            base = version_base(name)
            if base is not None:
                _, cells_set = candidates.get(name, (base, set()))
                cells_set.add(i)
                candidates[name] = (base, cells_set)

    smells = {}  # name -> set of cell indices
    for name, (base, cells_set) in candidates.items():
        if base in assigned:
            smells[name] = cells_set

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
    if error_outputs:
        print("  Cells with saved error output: %s"
              % ", ".join(map(str, error_outputs)))
        warnings.append("%d cell(s) raised an exception when last run: %s — the "
                        "notebook does not run cleanly top to bottom; fix the "
                        "error(s) and re-run before committing."
                        % (len(error_outputs),
                           ", ".join(map(str, error_outputs))))
    else:
        print("  No cells with saved error output")
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


def main() -> None:
    """CLI entry point: validate args, analyze the notebook, set the exit code."""
    if len(sys.argv) != 2:
        print("Usage: python3 nbcheck.py notebook.ipynb", file=sys.stderr)
        sys.exit(2)
    sys.exit(analyze(sys.argv[1]))


if __name__ == "__main__":
    main()
