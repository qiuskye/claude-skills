---
name: eda-quicklook
description: Fast exploratory data analysis (EDA) of a CSV file using a zero-dependency Python script, followed by an interpretation of data-quality problems and suggested next steps. Use when the user says things like "explore this CSV", "EDA", "what does this data look like", or hands you a CSV and asks for a first impression.
---

# eda-quicklook

Quick, dependency-free profiling of a CSV file. The heavy lifting is done by a
deterministic script; your job afterwards is **interpretation**, not number
crunching.

## Step 1 — Run the profiler

```bash
python3 scripts/eda.py "<file.csv>"
```

(Resolve `scripts/eda.py` relative to this skill's directory. **Always quote the
supplied path** so spaces or shell globs are not expanded — e.g.
`python3 scripts/eda.py "my data.csv"`. The script takes exactly one positional
path argument, so do not add a `--` separator.)

The script uses only the Python standard library and:

- Detects the delimiter automatically (`csv.Sniffer`, falling back to comma).
- Samples up to 50,000 rows on large files (it says so in the header when it does).
- Infers a type per column: numeric, categorical, or ISO date.
- Prints per column: non-null %, unique count, and either numeric stats
  (min/max/mean/median/stdev + an 8-bin ASCII histogram) or the top-5 values
  with counts.
- Ends with a `WARNINGS` section (>30% missing, constant columns,
  cardinality ≈ row count → likely an ID).

If the command fails (wrong path, not a CSV, encoding error), report the actual
error and fix the invocation — do not hand-roll a replacement analysis.

## Step 2 — Interpret the output

Read the report and give the user a short, opinionated summary:

1. **Shape and sampling**: rows × columns, and whether stats come from a sample.
2. **Problems**, in order of severity. Flag explicitly:
   - Columns with high missing rates (especially the >30% ones from WARNINGS) —
     can they be dropped, imputed, or is missingness informative?
   - Constant columns — dead weight, candidates for removal.
   - Likely ID columns (cardinality ≈ row count) — exclude from modeling,
     useful as join keys.
   - Numeric outliers: histograms with almost everything in one bin, or
     min/max wildly far from the median, suggest outliers or mixed units.
   - Suspicious typing: a "numeric-looking" column inferred as categorical
     often means dirty values (e.g. `"N/A"`, thousands separators).
3. **Next steps**, concrete and tailored to what was found. Typical examples:
   deduplicate on the ID column, parse the date column and check the time
   range, investigate the top categories of a skewed categorical, decide an
   imputation strategy, or plot the heavy-tailed numerics on a log scale.

Keep the interpretation grounded in the printed report — do not claim patterns
the output does not show. If the user wants deeper analysis (correlations,
plots, group-bys), propose it as a follow-up rather than guessing.

## Example output

Profiler output (`python3 scripts/eda.py "users.csv"`, abridged):

```
============================================================
EDA quicklook: users.csv
rows analyzed: 8   columns: 5
============================================================

-- id (numeric)
    non-null: 100.0%   unique: 8
    min=1  max=8  mean=4.5  median=4.5  stdev=2.44949

-- age (numeric)
    non-null: 87.5%   unique: 7
    min=28  max=52  mean=36.7143  median=34  stdev=8.93895
    [        28,         31) ############################## 2
    [        31,         34) ###############                1
    ...

-- city (categorical)
    non-null: 87.5%   unique: 3
         4  Madrid
         2  Barcelona
         1  Valencia

============================================================
WARNINGS
  ! 'id': cardinality ~= row count (8/8) -> possible ID column
```

Interpretation handed to the user (Step 2):

> 8 rows × 5 columns, full read (no sampling). `id` is a join key, not a
> feature — drop it from any model. `age` and `city` are ~12% missing; small
> here, but decide impute vs. drop before modeling. `plan` is dominated by
> `free` (4/8) — watch for class imbalance. Next: parse `signup_date` to check
> the time range and look for duplicate users.
