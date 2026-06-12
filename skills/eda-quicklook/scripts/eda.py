#!/usr/bin/env python3
"""eda.py — quick exploratory data analysis of a CSV file, stdlib only.

Usage:
    python3 eda.py <file.csv>

Features:
    - Delimiter detection via csv.Sniffer (falls back to comma).
    - Samples the first MAX_ROWS rows of large files.
    - Per-column type inference: numeric, ISO date, or categorical.
    - Per-column report: non-null %, unique count, and either numeric stats
      with an 8-bin ASCII histogram or the top-5 categorical values.
    - Final WARNINGS section: high missing rate, constant columns, and
      likely ID columns (cardinality ~= row count).

No third-party dependencies.
"""

import csv
import statistics
import sys
from collections import Counter

MAX_ROWS = 50_000
SNIFF_BYTES = 64 * 1024
HIST_BINS = 8
HIST_WIDTH = 30
TOP_K = 5
MISSING_THRESHOLD = 0.30
ID_CARDINALITY_RATIO = 0.99
MISSING_TOKENS = {"", "na", "n/a", "nan", "null", "none", "-"}


def detect_dialect(path):
    """Return a csv dialect sniffed from the file head, or excel (comma)."""
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as fh:
        head = fh.read(SNIFF_BYTES)
    try:
        return csv.Sniffer().sniff(head, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def is_missing(value):
    """Treat empty strings and common NA tokens as missing."""
    return value is None or value.strip().lower() in MISSING_TOKENS


def try_float(value):
    """Parse a float, accepting a decimal comma; return None on failure."""
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    if "," in text and "." not in text:
        try:
            return float(text.replace(",", "."))
        except ValueError:
            pass
    return None


def looks_iso_date(value):
    """Cheap check for ISO-8601 dates: YYYY-MM-DD with optional time part."""
    text = value.strip()
    if len(text) < 10:
        return False
    date_part = text[:10]
    if date_part[4] != "-" or date_part[7] != "-":
        return False
    digits = date_part[:4] + date_part[5:7] + date_part[8:10]
    if not digits.isdigit():
        return False
    month, day = int(digits[4:6]), int(digits[6:8])
    return 1 <= month <= 12 and 1 <= day <= 31


def infer_type(values):
    """Classify non-missing values as 'numeric', 'date', or 'categorical'.

    A column qualifies as numeric/date when >=90% of its non-missing values
    parse as such, which tolerates a few dirty cells.
    """
    if not values:
        return "categorical"
    numeric = sum(1 for v in values if try_float(v) is not None)
    if numeric >= 0.9 * len(values):
        return "numeric"
    dates = sum(1 for v in values if looks_iso_date(v))
    if dates >= 0.9 * len(values):
        return "date"
    return "categorical"


def ascii_histogram(numbers, bins=HIST_BINS, width=HIST_WIDTH):
    """Return histogram lines: one '[lo, hi) bar count' line per bin."""
    lo, hi = min(numbers), max(numbers)
    if lo == hi:
        return ["  all values equal to {:g}".format(lo)]
    step = (hi - lo) / bins
    counts = [0] * bins
    for x in numbers:
        idx = min(int((x - lo) / step), bins - 1)
        counts[idx] += 1
    peak = max(counts)
    lines = []
    for i, count in enumerate(counts):
        left, right = lo + i * step, lo + (i + 1) * step
        bar = "#" * max(1 if count else 0, round(count / peak * width))
        lines.append(
            "  [{:>10.4g}, {:>10.4g}) {:<{w}} {}".format(left, right, bar, count, w=width)
        )
    return lines


def read_csv(path):
    """Read up to MAX_ROWS rows; return (header, rows, sampled_flag)."""
    dialect = detect_dialect(path)
    rows, sampled = [], False
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh, dialect)
        header = next(reader, None)
        if header is None:
            sys.exit("error: file appears to be empty")
        for i, row in enumerate(reader):
            if i >= MAX_ROWS:
                sampled = True
                break
            rows.append(row)
    return header, rows, sampled


def column_values(rows, index):
    """Extract the values of one column, padding short rows with ''."""
    return [row[index] if index < len(row) else "" for row in rows]


def report_numeric(numbers):
    """Print summary stats and a histogram for parsed numeric values."""
    print("    min={:g}  max={:g}  mean={:g}  median={:g}  stdev={:g}".format(
        min(numbers),
        max(numbers),
        statistics.fmean(numbers),
        statistics.median(numbers),
        statistics.stdev(numbers) if len(numbers) > 1 else 0.0,
    ))
    for line in ascii_histogram(numbers):
        print("  " + line)


def report_categorical(values):
    """Print the TOP_K most frequent values with counts."""
    for value, count in Counter(values).most_common(TOP_K):
        shown = value if len(value) <= 40 else value[:37] + "..."
        print("    {:>6}  {}".format(count, shown))


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: python3 eda.py <file.csv>")
    path = argv[1]

    header, rows, sampled = read_csv(path)
    n_rows = len(rows)
    print("=" * 60)
    print("EDA quicklook: {}".format(path))
    print("rows analyzed: {}{}   columns: {}".format(
        n_rows, " (sampled, first {})".format(MAX_ROWS) if sampled else "", len(header)
    ))
    print("=" * 60)

    warnings = []
    for index, name in enumerate(header):
        values = column_values(rows, index)
        present = [v for v in values if not is_missing(v)]
        non_null_pct = 100.0 * len(present) / n_rows if n_rows else 0.0
        unique = len(set(present))
        col_type = infer_type(present)

        print("\n-- {} ({})".format(name, col_type))
        print("    non-null: {:.1f}%   unique: {}".format(non_null_pct, unique))

        if col_type == "numeric" and present:
            numbers = [f for f in (try_float(v) for v in present) if f is not None]
            if numbers:
                report_numeric(numbers)
        elif present:
            report_categorical(present)

        missing_ratio = 1.0 - (len(present) / n_rows) if n_rows else 1.0
        if missing_ratio > MISSING_THRESHOLD:
            warnings.append("'{}': {:.0f}% missing values".format(name, 100 * missing_ratio))
        if present and unique == 1:
            warnings.append("'{}': constant column (single value)".format(name))
        if n_rows > 1 and unique >= ID_CARDINALITY_RATIO * n_rows:
            warnings.append(
                "'{}': cardinality ~= row count ({}/{}) -> possible ID column".format(
                    name, unique, n_rows
                )
            )

    print("\n" + "=" * 60)
    print("WARNINGS" if warnings else "WARNINGS: none")
    for warning in warnings:
        print("  ! " + warning)


if __name__ == "__main__":
    main(sys.argv)
