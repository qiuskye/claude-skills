---
name: notebook-polish
description: Review and polish Jupyter notebooks (.ipynb) for Data Science work. Use when the user asks to review, clean up or make a notebook presentable — e.g. "revisa mi notebook", "limpia este .ipynb", "deja el notebook presentable", "review my notebook", "clean up this notebook".
---

# Notebook Polish

Help a Data Science student turn a working-but-messy Jupyter notebook into a
clean, reproducible, presentable one. The workflow is: run the checker, read
the report, then guide the cleanup in priority order.

## Step 1 — Run the checker

```bash
python3 scripts/nbcheck.py "<path/al/notebook.ipynb>"
```

(Resolve `scripts/nbcheck.py` relative to this skill's directory. **Always quote
the supplied path** so spaces or shell globs are not expanded — e.g.
`python3 scripts/nbcheck.py "my notebook.ipynb"`. The script takes exactly one
positional path argument, so do not add a `--` separator.)

The report has sections: Cells, Execution order, Outputs, Imports, Long
cells, Naming, and a final WARNINGS summary. Exit code 1 means warnings were
found; 0 means clean; 2 means the file could not be parsed.

## Step 2 — Interpret the report

Translate each finding into plain language for the user:

- **Unexecuted / out-of-order execution counts**: the notebook was probably
  run by jumping around, so re-running it top to bottom may break or give
  different results. This is the strongest signal of a non-reproducible
  notebook.
- **Empty cells**: leftover clutter; safe to delete.
- **Oversized outputs (> 50 KB)**: usually base64-embedded images or huge
  printed dataframes; they bloat the file and pollute diffs/commits.
- **Duplicated / late imports**: imports scattered through the notebook
  instead of one import cell at the top.
- **Low markdown/code ratio (< 20%)**: the notebook lacks narrative — a
  reader cannot follow the reasoning.
- **Cells over 40 lines**: candidates to extract into named functions.
- **Versioned variable names (`df2`, `df3`, `final_v2`)**: the name says
  nothing about the content; rename to describe the transformation
  (`df_clean`, `df_features`, `model_tuned`).

## Step 3 — Guide the cleanup, in this priority order

1. **Reproducibility first.** Ask the user to mentally do "Restart & Run
   All": would the notebook run top to bottom without errors? Fix execution
   order, move all imports to a single cell at the top, remove duplicated
   imports, and make sure every cell that matters is actually executed in
   order.
2. **Structure and narrative.** Add a title cell, markdown section headers
   (e.g. Data loading, Cleaning, EDA, Modeling, Conclusions), short
   explanations before non-obvious code, and a conclusions section at the
   end. This is what fixes a low markdown/code ratio.
3. **Code quality.** Split or refactor cells over 40 lines into functions,
   delete empty cells, and clear oversized outputs before committing
   (Cell > All Output > Clear, or `jupyter nbconvert --clear-output`).
4. **Naming.** Rename versioned variables to descriptive names, updating all
   usages consistently.

## Rules

- **Never claim anything the report does not show.** If the script reports
  no out-of-order cells, do not say the notebook is unreproducible; if it
  flags nothing in a section, say that section looks fine. The checker is
  static — it cannot know whether the code actually runs, so phrase runtime
  claims as suggestions to verify ("try Restart & Run All to confirm").
- **Offer fixes cell by cell, not mass rewrites.** Propose one concrete
  change at a time (e.g. "move these two imports from cell 7 into cell 1")
  and let the user accept or skip each one. Do not rewrite large parts of
  the notebook without explicit permission.
- After each round of edits, re-run `nbcheck.py` to confirm the warnings are
  gone and show the user the before/after difference.

## Example output

Checker output (`python3 scripts/nbcheck.py "analysis.ipynb"`, abridged):

```
[Cells]
  Code cells:      4
  Markdown cells:  0
  Markdown/code ratio: 0.00

[Execution order]
  Unexecuted code cells: 3
  Out of order: cell 2 has execution_count 1 but cell 1 (earlier) has 3

[WARNINGS]
  - Markdown/code ratio 0.00 is below 0.20 — the notebook lacks narrative.
  - Execution counts are not increasing top-to-bottom — likely run out of
    order and may not be reproducible. Do Restart & Run All.
  - Versioned variable names (df2) — use descriptive names instead.
```

Exit code `1` (warnings found). Interpretation handed to the user (Step 2):

> Three issues, reproducibility first: the cells were run out of order, so
> Restart & Run All may break — fix that before anything else. No markdown at
> all, so add a title and section headers. Finally, rename `df2` to something
> descriptive like `df_clean`. Want me to walk through them one cell at a time?
