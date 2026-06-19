"""Regression tests for the fixed nbcheck.py findings.

Each test pins a specific reported-and-fixed bug:

  - output_size must return 0 when ``outputs`` is present but not a list
    (a malformed notebook used to crash or miscount).
  - nbformat 3 (worksheets[].cells) / nbformat < 4 must error out with
    exit code 2 instead of being silently reported "clean" (0 cells).
  - df100 (and other 1-3 digit suffixes) must be detected as a versioned
    name when the un-numbered base is also assigned.
  - An assignment written INSIDE a string literal must NOT trigger a
    versioned-variable false positive (string/comment spans are blanked
    before the regex scan).

Loaded by path via importlib. Stdlib only, deterministic in-memory notebooks.
"""

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

_HERE = os.path.dirname(os.path.abspath(__file__))
_NB_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "skills", "notebook-polish", "scripts", "nbcheck.py")
)


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nbcheck = _load_module("nbcheck_regressions_under_test", _NB_PATH)


def _code_cell(source, execution_count=1, outputs=None):
    return {
        "cell_type": "code",
        "source": source,
        "execution_count": execution_count,
        "outputs": outputs or [],
    }


def _md_cell(source):
    return {"cell_type": "markdown", "source": source}


_NARRATIVE = [
    _md_cell("# Title\n\nNarrative explaining the analysis."),
    _md_cell("## Section\n\nMore narrative for context."),
]


def _write_notebook(nb_dict):
    fh = tempfile.NamedTemporaryFile(
        "w", suffix=".ipynb", delete=False, encoding="utf-8"
    )
    try:
        json.dump(nb_dict, fh)
    finally:
        fh.close()
    return fh.name


def _analyze_cells(cells):
    """Standard nbformat-4 notebook -> (exit_code, stdout)."""
    nb = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    path = _write_notebook(nb)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = nbcheck.analyze(path)
    finally:
        os.unlink(path)
    return code, buf.getvalue()


def _analyze_raw(nb_dict):
    """Analyze an arbitrary top-level dict; capture SystemExit if raised."""
    path = _write_notebook(nb_dict)
    buf, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(err):
            try:
                code = nbcheck.analyze(path)
                return code, buf.getvalue(), err.getvalue()
            except SystemExit as exc:
                return exc.code, buf.getvalue(), err.getvalue()
    finally:
        os.unlink(path)


class TestOutputSizeNonListIsZero(unittest.TestCase):
    """output_size must be 0 when outputs is present but not a list."""

    def test_dict_outputs(self):
        self.assertEqual(nbcheck.output_size({"outputs": {"a": 1}}), 0)

    def test_string_outputs(self):
        self.assertEqual(nbcheck.output_size({"outputs": "not a list"}), 0)

    def test_none_outputs(self):
        self.assertEqual(nbcheck.output_size({"outputs": None}), 0)

    def test_int_outputs(self):
        self.assertEqual(nbcheck.output_size({"outputs": 5}), 0)


class TestNbformat3Errors(unittest.TestCase):
    """nbformat 3 / worksheets must fail loudly with exit code 2."""

    def test_worksheets_nbformat3_exits_two(self):
        code, _out, err = _analyze_raw({"nbformat": 3, "worksheets": [{"cells": []}]})
        self.assertEqual(code, 2)
        self.assertIn("unsupported notebook format", err)

    def test_low_nbformat_without_cells_exits_two(self):
        code, _out, err = _analyze_raw({"nbformat": 2})
        self.assertEqual(code, 2)
        self.assertIn("unsupported notebook format", err)


class TestDf100Detected(unittest.TestCase):
    """A 1-3 digit numbered name with an assigned base is a versioned smell."""

    def test_version_base_df100(self):
        self.assertEqual(nbcheck.version_base("df100"), "df")

    def test_df_plus_df100_smells(self):
        code, out = _analyze_cells(
            _NARRATIVE + [_code_cell("df = 1\n"), _code_cell("df100 = 2\n", 2)]
        )
        self.assertEqual(code, 1)
        self.assertIn("df100", out)
        self.assertIn("Versioned variable names", out)


class TestAssignmentInsideStringNoFalsePositive(unittest.TestCase):
    """An assignment inside a string literal must not be flagged."""

    def test_df2_only_inside_string_is_not_a_smell(self):
        q3 = "'''"
        src = "df = load()\nquery = " + q3 + "\nSELECT * WHERE df2 = 1\n" + q3 + "\n"
        code, out = _analyze_cells(_NARRATIVE + [_code_cell(src)])
        self.assertNotIn("df2", out)
        self.assertIn("No versioned variable names detected", out)

    def test_assignment_in_comment_is_not_a_smell(self):
        # df assigned for real, but df2 only appears in a comment.
        src = "df = load()\n# df2 = 2  note for later\n"
        code, out = _analyze_cells(_NARRATIVE + [_code_cell(src)])
        self.assertNotIn("df2", out)
        self.assertIn("No versioned variable names detected", out)


if __name__ == "__main__":
    unittest.main()
