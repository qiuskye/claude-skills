"""Deterministic unit tests for skills/notebook-polish/scripts/nbcheck.py.

The script is loaded by path via importlib (it is not a package). Tests cover
the pure helpers (cell_source, fmt_size, output_size, SMELL_NAME_RE) and the
end-to-end analyze() exit code on minimal in-memory notebooks written to a
temporary file.
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


nbcheck = _load_module("nbcheck_under_test", _NB_PATH)


def _code_cell(source, execution_count=1, outputs=None):
    return {
        "cell_type": "code",
        "source": source,
        "execution_count": execution_count,
        "outputs": outputs or [],
    }


def _md_cell(source):
    return {"cell_type": "markdown", "source": source}


def _analyze_notebook(cells):
    """Write a notebook dict to a temp file, run analyze(), return its code."""
    nb = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ipynb", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(nb, fh)
        path = fh.name
    try:
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            return nbcheck.analyze(path)
    finally:
        os.unlink(path)


class TestCellSource(unittest.TestCase):
    def test_list_source_is_joined(self):
        self.assertEqual(nbcheck.cell_source({"source": ["a", "b"]}), "ab")

    def test_string_source_kept(self):
        self.assertEqual(nbcheck.cell_source({"source": "abc"}), "abc")

    def test_missing_source_defaults_empty(self):
        self.assertEqual(nbcheck.cell_source({}), "")


class TestFmtSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(nbcheck.fmt_size(1023), "1023 B")

    def test_kilobytes_boundary(self):
        self.assertEqual(nbcheck.fmt_size(1024), "1.0 KB")

    def test_megabytes_boundary(self):
        self.assertEqual(nbcheck.fmt_size(1024 * 1024), "1.0 MB")


class TestOutputSize(unittest.TestCase):
    def test_no_outputs(self):
        self.assertEqual(nbcheck.output_size({"outputs": []}), 0)

    def test_missing_outputs_key(self):
        self.assertEqual(nbcheck.output_size({}), 0)

    def test_outputs_size_is_positive(self):
        cell = {"outputs": [{"output_type": "stream", "text": "hello"}]}
        self.assertGreater(nbcheck.output_size(cell), 0)


class TestSmellNameRe(unittest.TestCase):
    def test_versioned_names_match(self):
        for name in ("df2", "df3", "final_v2"):
            self.assertIsNotNone(nbcheck.SMELL_NAME_RE.match(name), name)

    def test_clean_names_do_not_match(self):
        for name in ("df", "df_clean", "df_features"):
            self.assertIsNone(nbcheck.SMELL_NAME_RE.match(name), name)


class TestAnalyzeExitCode(unittest.TestCase):
    def test_clean_notebook_returns_zero(self):
        # Enough markdown to clear the ratio threshold, in-order execution,
        # no smells, no empty cells -> no warnings -> exit 0.
        cells = [
            _md_cell("# Title\n\nNarrative explaining the analysis."),
            _md_cell("## Section\n\nMore narrative for context."),
            _code_cell("x = 1\n", execution_count=1),
            _code_cell("y = x + 1\n", execution_count=2),
        ]
        self.assertEqual(_analyze_notebook(cells), 0)

    def test_out_of_order_execution_returns_one(self):
        # execution_count [2, 1] -> out of order -> warning -> exit 1.
        cells = [
            _md_cell("# Title\n\nNarrative."),
            _md_cell("## More\n\nNarrative."),
            _code_cell("a = 1\n", execution_count=2),
            _code_cell("b = 2\n", execution_count=1),
        ]
        self.assertEqual(_analyze_notebook(cells), 1)

    def test_empty_cell_returns_one(self):
        cells = [
            _md_cell("# Title\n\nNarrative."),
            _md_cell("## More\n\nNarrative."),
            _code_cell("a = 1\n", execution_count=1),
            _code_cell("", execution_count=None),
        ]
        self.assertEqual(_analyze_notebook(cells), 1)


if __name__ == "__main__":
    unittest.main()
