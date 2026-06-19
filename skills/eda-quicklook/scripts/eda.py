#!/usr/bin/env python3
"""eda.py — quick exploratory data analysis of a CSV file, stdlib only.

Usage:
    python3 eda.py <file.csv>

Features:
    - Delimiter detection via csv.Sniffer (falls back to comma).
    - BOM-safe UTF-8 reading; undecodable bytes are replaced, never fatal.
    - Samples the first MAX_ROWS rows of large files (read lazily, capped early
      so huge files are never fully loaded into memory).
    - Per-column type inference: numeric, ISO date, or categorical.
    - Per-column report: non-null %, unique count, and either numeric stats
      with an 8-bin ASCII histogram or the top-5 categorical values.
    - Final WARNINGS section: high missing rate, constant columns, and
      likely ID columns (cardinality ~= row count).

No third-party dependencies.
"""

import csv
import math
import re
import statistics
import sys
from collections import Counter
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

MAX_ROWS = 50_000          # cap rows read so huge files stay fast; rest is sampled
SNIFF_BYTES = 64 * 1024    # bytes fed to csv.Sniffer for delimiter detection
HIST_BINS = 8              # number of buckets in the ASCII histogram
HIST_WIDTH = 30            # max width (chars) of the longest histogram bar
TOP_K = 5                  # how many top values to show for categorical columns
MISSING_THRESHOLD = 0.30   # warn when more than 30% of a column is missing
ID_CARDINALITY_RATIO = 0.99  # unique/rows above this flags a likely ID column
ID_MIN_ROWS = 20           # skip the ID heuristic below this many rows: on tiny
                           # datasets almost every column is all-unique (false IDs)
NUMERIC_TYPE_RATIO = 0.9   # share of cells that must parse to call a column numeric/date
# Tokens treated as missing; 'inf'/'-inf'/'infinity' included so non-finite
# floats are never counted as numeric (they break stats and the histogram).
MISSING_TOKENS = {
    "", "na", "n/a", "nan", "null", "none", "-",
    "inf", "-inf", "+inf", "infinity", "-infinity", "+infinity",
}


def detect_dialect(head: str) -> csv.Dialect:
    """Return a csv dialect sniffed from the file head, or excel (comma).

    ``head`` is a chunk of the file's text. csv.Sniffer can raise on ambiguous
    or single-column input, in which case we fall back to the comma dialect.
    """
    try:
        return csv.Sniffer().sniff(head, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def is_missing(value: Optional[str]) -> bool:
    """Return True for None, empty strings, or common NA tokens.

    Matching is whitespace- and case-insensitive, so ``" N/A "`` counts as
    missing just like ``"na"``.
    """
    return value is None or value.strip().lower() in MISSING_TOKENS


# US thousands grouping, e.g. '1,000' or '10,000,000' (no decimal part).
# Such values must NOT have the comma read as a decimal point.
_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})+$")


def try_float(value: str) -> Optional[float]:
    """Parse a finite float, accepting a decimal comma; return None on failure.

    Rejects inf/-inf/nan so non-finite values are never treated as numeric
    (they would corrupt the stats and crash the histogram). Surrounding
    whitespace is ignored so values like ``" 1.5 "`` still parse.

    A comma is only treated as a European decimal separator when the value is
    not a US thousands-grouped integer (``1,000``): those are parsed by
    stripping the commas, so they are never silently turned into ``1.0``.
    """
    text = value.strip()
    if _THOUSANDS_RE.match(text):
        try:
            f = float(text.replace(",", ""))
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    for candidate in (text, text.replace(",", ".") if "," in text and "." not in text else None):
        if candidate is None:
            continue
        try:
            f = float(candidate)
        except ValueError:
            continue
        if math.isfinite(f):
            return f
    return None


def has_locale_ambiguity(values: Sequence[str]) -> bool:
    """True when a numeric column mixes comma-grouping and comma-decimal styles.

    A single column should use one convention. If some values look like US
    thousands grouping (``1,000``) while others look like a European decimal
    comma (``1,5``), we cannot safely tell them apart, so the caller should
    warn instead of silently picking one interpretation.
    """
    thousands = decimal_comma = False
    for v in values:
        text = v.strip()
        if "," not in text:
            continue
        if _THOUSANDS_RE.match(text):
            thousands = True
        elif "." not in text:
            decimal_comma = True
    return thousands and decimal_comma


def looks_iso_date(value: str) -> bool:
    """Check for a real ISO-8601 date: YYYY-MM-DD with an optional time part.

    Validates against the actual calendar via datetime.strptime, so impossible
    dates like 2026-02-30 are rejected (not just range-checked). Surrounding
    whitespace is ignored.
    """
    text = value.strip()
    if len(text) < 10:
        return False
    try:
        datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return True


def infer_type(values: Sequence[str]) -> str:
    """Classify non-missing values as 'numeric', 'date', or 'categorical'.

    A column qualifies as numeric/date when at least NUMERIC_TYPE_RATIO of its
    non-missing values parse as such, which tolerates a few dirty cells. An
    empty column (no non-missing values) is treated as categorical.
    """
    if not values:
        return "categorical"
    numeric = sum(1 for v in values if try_float(v) is not None)
    if numeric >= NUMERIC_TYPE_RATIO * len(values):
        return "numeric"
    dates = sum(1 for v in values if looks_iso_date(v))
    if dates >= NUMERIC_TYPE_RATIO * len(values):
        return "date"
    return "categorical"


def ascii_histogram(
    numbers: Sequence[float], bins: int = HIST_BINS, width: int = HIST_WIDTH
) -> List[str]:
    """Return histogram lines: one '[lo, hi) bar count' line per bin.

    Returns an empty list for no input, and a single "all values equal" line
    when every value is identical (a zero-width range has no meaningful bins).
    """
    if not numbers:
        return []
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
        # The last bin is inclusive of the maximum, so close it with ']'.
        closing = "]" if i == bins - 1 else ")"
        lines.append(
            "  [{:>10.4g}, {:>10.4g}{} {:<{w}} {}".format(
                left, right, closing, bar, count, w=width
            )
        )
    return lines


def read_csv(path: str) -> Tuple[List[str], List[List[str]], bool]:
    """Read up to MAX_ROWS rows; return (header, rows, sampled_flag).

    The file is opened with the ``utf-8-sig`` codec so a leading UTF-8 BOM is
    stripped transparently (otherwise it would corrupt the first column name);
    files without a BOM are read exactly as plain UTF-8. Undecodable bytes are
    replaced rather than raising, so a mis-encoded file is still profiled.

    Only the first MAX_ROWS data rows are kept in memory: the reader streams the
    file lazily and stops early once the cap is hit, so an enormous file never
    forces the whole thing to be loaded. ``sampled`` is True when that cap was
    reached and trailing rows were skipped.

    Exits with a clean stderr message (no traceback) if the file cannot be
    opened or read, e.g. it is missing, a directory, or not readable.
    """
    try:
        with open(path, "r", newline="", encoding="utf-8-sig", errors="replace") as fh:
            head = fh.read(SNIFF_BYTES)
            dialect = detect_dialect(head)
            fh.seek(0)
            reader = csv.reader(fh, dialect)
            header = next(reader, None)
            if header is None:
                sys.exit("error: file appears to be empty")
            rows: List[List[str]] = []
            sampled = False
            for i, row in enumerate(reader):
                if i >= MAX_ROWS:
                    sampled = True
                    break
                rows.append(row)
    except OSError as exc:
        sys.exit("error: cannot read {}: {}".format(path, exc))
    return header, rows, sampled


def column_values(rows: Sequence[Sequence[str]], index: int) -> List[str]:
    """Extract the values of one column, padding short rows with ''.

    Ragged rows (fewer fields than the header) yield '' for the missing
    column instead of raising an IndexError.
    """
    return [row[index] if index < len(row) else "" for row in rows]


def report_numeric(numbers: Sequence[float]) -> None:
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


def report_categorical(values: Sequence[str]) -> None:
    """Print the TOP_K most frequent values with counts.

    Long values are truncated to keep the output aligned and compact.
    """
    for value, count in Counter(values).most_common(TOP_K):
        shown = value if len(value) <= 40 else value[:37] + "..."
        print("    {:>6}  {}".format(count, shown))


def main(argv: Sequence[str]) -> None:
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

    if n_rows == 0:
        print("\nwarning: file has a header but no data rows")
        return

    warnings = []

    # Rows whose field count differs from the header are profiled only up to the
    # header width: extra trailing fields are otherwise dropped silently and
    # short rows are padded. Count them so the discrepancy is surfaced.
    n_header = len(header)
    ragged = sum(1 for row in rows if len(row) != n_header)
    if ragged:
        warnings.append(
            "{} filas con nº de campos distinto al header".format(ragged)
        )

    for index, name in enumerate(header):
        values = column_values(rows, index)
        present = [v for v in values if not is_missing(v)]
        non_null_pct = 100.0 * len(present) / n_rows if n_rows else 0.0
        unique = len(set(present))
        col_type = infer_type(present)

        print("\n-- {} ({})".format(name, col_type))
        print("    non-null: {:.1f}%   unique: {}".format(non_null_pct, unique))

        if col_type == "numeric" and present:
            if has_locale_ambiguity(present):
                warnings.append(
                    "'{}': comas ambiguas (¿miles US o decimal EU?), "
                    "stats podrían ser incorrectas".format(name)
                )
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
        if n_rows >= ID_MIN_ROWS and unique >= ID_CARDINALITY_RATIO * n_rows:
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
