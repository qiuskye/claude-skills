"""Regression tests for the fixed eda.py findings.

Each test pins a specific bug that was reported and fixed so it cannot silently
come back:

  - try_float must NOT corrupt US thousands-grouped integers (``1,000`` ->
    1000.0, never 1.0).
  - main() must WARN when data rows have a field count different from the
    header (ragged rows).

Loaded by path via importlib (the script is not a package). Stdlib only,
fully deterministic.
"""

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

_HERE = os.path.dirname(os.path.abspath(__file__))
_EDA_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "skills", "eda-quicklook", "scripts", "eda.py")
)


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eda = _load_module("eda_regressions_under_test", _EDA_PATH)


def _run_main(content):
    fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    try:
        fh.write(content)
    finally:
        fh.close()
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            eda.main(["eda.py", fh.name])
    finally:
        os.unlink(fh.name)
    return buf.getvalue()


class TestTryFloatUsThousands(unittest.TestCase):
    """try_float must strip US thousands commas, never read them as decimals."""

    def test_thousand_is_not_one(self):
        # The bug: "1,000" was read as the European decimal "1.0".
        self.assertEqual(eda.try_float("1,000"), 1000.0)

    def test_multi_group_thousands(self):
        self.assertEqual(eda.try_float("10,000,000"), 10_000_000.0)

    def test_signed_thousands(self):
        self.assertEqual(eda.try_float("-1,234"), -1234.0)
        self.assertEqual(eda.try_float("+2,000"), 2000.0)

    def test_european_decimal_still_works(self):
        # Single comma with no grouping is still a decimal comma.
        self.assertEqual(eda.try_float("1,5"), 1.5)

    def test_not_a_valid_grouping_is_decimal_comma(self):
        # "1,23" is not 1-3 digits + groups of 3, so it stays a decimal comma.
        self.assertEqual(eda.try_float("1,23"), 1.23)

    def test_thousands_column_stats_are_not_corrupted(self):
        # A semicolon-delimited file so the US thousands comma is NOT the
        # field delimiter: the cells reach try_float intact as "1,000" etc.
        out = _run_main("label;amount\na;1,000\nb;2,000\nc;3,000\n")
        # Mean of 1000/2000/3000 is 2000; the buggy 1.0/2.0/3.0 gave mean 2.
        self.assertIn("mean=2000", out)
        self.assertNotIn("mean=2 ", out)


class TestTryFloatUsCurrencyDecimals(unittest.TestCase):
    """try_float must parse US thousands-grouped values WITH a decimal part.

    Regression: values like ``1,000.50`` (grouping comma + decimal point) must
    parse to their real numeric value, not be rejected or mis-read. The earlier
    cases without decimals (``1,000``) and the European decimal comma (``1,5``)
    must keep working unchanged.
    """

    def test_thousands_with_decimal(self):
        self.assertEqual(eda.try_float("1,000.50"), 1000.50)

    def test_multi_group_thousands_with_decimal(self):
        self.assertEqual(eda.try_float("1,234,567.89"), 1234567.89)

    def test_signed_thousands_with_decimal(self):
        self.assertEqual(eda.try_float("-2,500.00"), -2500.00)

    def test_plain_thousands_still_ok(self):
        self.assertEqual(eda.try_float("1,000"), 1000.0)

    def test_european_decimal_comma_still_ok(self):
        self.assertEqual(eda.try_float("1,5"), 1.5)

    def test_currency_column_stats_are_correct(self):
        # Semicolon-delimited so the US thousands comma is not the delimiter and
        # cells reach try_float intact as "1,000.50" etc.
        out = _run_main(
            "label;amount\na;1,000.50\nb;1,234,567.89\nc;-2,500.00\n"
        )
        self.assertIn("(numeric)", out)
        # mean = (1000.50 + 1234567.89 - 2500.00) / 3 = 411022.7966...
        self.assertIn("mean=411023", out)
        self.assertIn("min=-2500", out)
        self.assertIn("max=1.23457e+06", out)


class TestRaggedRowsWarn(unittest.TestCase):
    """main() must surface rows whose field count differs from the header."""

    def test_short_and_long_rows_are_counted(self):
        # header has 3 cols; row 2 has 2 (short), row 3 has 4 (long).
        out = _run_main("a,b,c\n1,2,3\n4,5\n6,7,8,9\n")
        self.assertIn("WARNINGS", out)
        self.assertIn("filas con nº de campos distinto al header", out)
        self.assertIn("2 filas", out)

    def test_well_formed_file_has_no_ragged_warning(self):
        out = _run_main("a,b,c\n1,2,3\n4,5,6\n")
        self.assertNotIn("distinto al header", out)


class TestBooleanColumnEndToEnd(unittest.TestCase):
    """main() must label two-state flag columns 'boolean' and count their values."""

    def test_yes_no_column_reports_boolean_with_counts(self):
        out = _run_main("active\nyes\nno\nyes\nyes\n")
        self.assertIn("-- active (boolean)", out)
        self.assertIn("3  yes", out)  # categorical-style value counts
        self.assertIn("1  no", out)

    def test_zero_one_flag_is_boolean_not_numeric(self):
        out = _run_main("flag\n0\n1\n1\n0\n")
        self.assertIn("-- flag (boolean)", out)
        self.assertNotIn("(numeric)", out)  # must not fall into the numeric path


if __name__ == "__main__":
    unittest.main()
