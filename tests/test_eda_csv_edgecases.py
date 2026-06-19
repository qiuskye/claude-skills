"""Deterministic edge-case tests for the CSV IO layer of eda.py.

The existing test_eda.py exercises the pure helpers (is_missing, try_float,
looks_iso_date, infer_type, ascii_histogram, column_values). This file
complements it by driving the IO/integration surface that those tests do not
touch: read_csv (delimiter detection, BOM, header-only, empty, unreadable,
non-utf8 bytes) and main() (header-only and all-missing columns). All cases
are deterministic and stdlib-only.
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


eda = _load_module("eda_csv_under_test", _EDA_PATH)


def _write_tmp(content, mode="w", **open_kwargs):
    """Write content to a temp .csv and return its path (caller deletes)."""
    fh = tempfile.NamedTemporaryFile(mode, suffix=".csv", delete=False, **open_kwargs)
    try:
        fh.write(content)
    finally:
        fh.close()
    return fh.name


def _read_csv(content, mode="w", **open_kwargs):
    path = _write_tmp(content, mode=mode, **open_kwargs)
    try:
        return eda.read_csv(path)
    finally:
        os.unlink(path)


def _run_main(content, mode="w", **open_kwargs):
    path = _write_tmp(content, mode=mode, **open_kwargs)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            eda.main(["eda.py", path])
    finally:
        os.unlink(path)
    return buf.getvalue()


class TestReadCsvDelimiter(unittest.TestCase):
    def test_comma_delimiter(self):
        header, rows, sampled = _read_csv("a,b,c\n1,2,3\n4,5,6\n")
        self.assertEqual(header, ["a", "b", "c"])
        self.assertEqual(rows, [["1", "2", "3"], ["4", "5", "6"]])
        self.assertFalse(sampled)

    def test_semicolon_delimiter_is_detected(self):
        header, rows, _ = _read_csv("a;b;c\n1;2;3\n4;5;6\n7;8;9\n")
        self.assertEqual(header, ["a", "b", "c"])
        self.assertEqual(rows[0], ["1", "2", "3"])

    def test_tab_delimiter_is_detected(self):
        header, rows, _ = _read_csv("a\tb\tc\n1\t2\t3\n4\t5\t6\n7\t8\t9\n")
        self.assertEqual(header, ["a", "b", "c"])
        self.assertEqual(rows[0], ["1", "2", "3"])


class TestReadCsvHeaderOnly(unittest.TestCase):
    def test_header_only_yields_no_rows(self):
        header, rows, sampled = _read_csv("a,b,c\n")
        self.assertEqual(header, ["a", "b", "c"])
        self.assertEqual(rows, [])
        self.assertFalse(sampled)

    def test_header_only_main_warns_no_data(self):
        out = _run_main("a,b,c\n")
        self.assertIn("rows analyzed: 0", out)
        self.assertIn("header but no data rows", out)


class TestReadCsvEmptyAndUnreadable(unittest.TestCase):
    def test_truly_empty_file_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            _read_csv("")
        self.assertIn("empty", str(ctx.exception.code))

    def test_missing_file_exits_cleanly(self):
        # No traceback: read_csv translates OSError into sys.exit(message).
        with self.assertRaises(SystemExit) as ctx:
            eda.read_csv(os.path.join(_HERE, "does-not-exist-xyz.csv"))
        self.assertIn("cannot read", str(ctx.exception.code))


class TestReadCsvBom(unittest.TestCase):
    def test_bom_prefixed_file_parses_data_correctly(self):
        # A file saved with a UTF-8 byte-order mark (common from Excel) must
        # still parse: the data rows and the non-first header cells stay clean,
        # and the first header is the column name with at most a leading BOM.
        header, rows, sampled = _read_csv(
            "a,b\n1,2\n3,4\n", mode="w", encoding="utf-8-sig"
        )
        self.assertEqual(len(header), 2)
        self.assertEqual(header[0].lstrip("\ufeff"), "a")
        self.assertEqual(header[1], "b")
        self.assertEqual(rows, [["1", "2"], ["3", "4"]])
        self.assertFalse(sampled)


class TestReadCsvEncoding(unittest.TestCase):
    def test_invalid_utf8_bytes_are_replaced_not_fatal(self):
        # read_csv opens with errors="replace": undecodable bytes become the
        # U+FFFD replacement char instead of raising UnicodeDecodeError.
        raw = b"name,val\n\xff\xfe,2\n10,3\n"
        header, rows, _ = _read_csv(raw, mode="wb")
        self.assertEqual(header, ["name", "val"])
        self.assertEqual(rows[0][1], "2")
        self.assertIn("�", rows[0][0])


class TestMainAllMissingColumn(unittest.TestCase):
    def test_empty_column_reports_zero_non_null_and_warns(self):
        out = _run_main("id,empty\n1,\n2,\n3,\n")
        self.assertIn("-- empty (categorical)", out)
        self.assertIn("non-null: 0.0%", out)
        self.assertIn("'empty': 100% missing values", out)

    def test_na_token_column_is_all_missing(self):
        # Cells filled only with NA tokens count as missing, not categorical.
        out = _run_main("id,note\n1,NA\n2,n/a\n3,null\n")
        self.assertIn("'note': 100% missing values", out)


if __name__ == "__main__":
    unittest.main()
