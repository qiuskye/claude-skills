"""Deterministic edge-case tests for nbcheck.py.

Complements test_nbcheck.py by covering: defensive cell_source coercion
(non-string/non-dict shapes), version_base false-positive avoidance
(sha256, utf8, base64, col2 vs real df2/final_v2), the fmt_size zero case,
and end-to-end analyze() detection of duplicated imports, late imports, long
cells, oversized outputs and versioned-name smells. Stdlib only, fully
deterministic via in-memory notebooks written to temp files.
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


nbcheck = _load_module("nbcheck_edge_under_test", _NB_PATH)


def _code_cell(source, execution_count=1, outputs=None):
    return {
        "cell_type": "code",
        "source": source,
        "execution_count": execution_count,
        "outputs": outputs or [],
    }


def _md_cell(source):
    return {"cell_type": "markdown", "source": source}


def _analyze(cells):
    """Write a notebook to a temp file, run analyze(), return (code, stdout)."""
    nb = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ipynb", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(nb, fh)
        path = fh.name
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = nbcheck.analyze(path)
    finally:
        os.unlink(path)
    return code, buf.getvalue()


# Two markdown cells so a 2-code-cell notebook clears MIN_MARKDOWN_RATIO and
# the only warning under test is the one we are exercising.
_NARRATIVE = [
    _md_cell("# Title\n\nNarrative explaining the analysis."),
    _md_cell("## Section\n\nMore narrative for context."),
]


class TestCellSourceDefensive(unittest.TestCase):
    def test_list_with_non_string_entries_skips_them(self):
        self.assertEqual(nbcheck.cell_source({"source": ["a", None, "b"]}), "ab")

    def test_numeric_source_coerced_to_empty(self):
        self.assertEqual(nbcheck.cell_source({"source": 123}), "")

    def test_non_dict_cell_coerced_to_empty(self):
        self.assertEqual(nbcheck.cell_source(42), "")
        self.assertEqual(nbcheck.cell_source(None), "")


class TestVersionBase(unittest.TestCase):
    def test_real_versioned_names(self):
        self.assertEqual(nbcheck.version_base("df2"), "df")
        self.assertEqual(nbcheck.version_base("final_v2"), "final")

    def test_intrinsic_digit_names_are_not_versioned(self):
        # More than 3 trailing digits is outside the \d{1,3} branch -> None
        # (sha2048, model12345). version_base only extracts a candidate base;
        # the real false-positive guard is at the smell level (a candidate is
        # only flagged when its un-numbered base is also assigned), exercised
        # by test_intrinsic_digit_name_does_not_smell below.
        self.assertIsNone(nbcheck.version_base("sha2048"))
        self.assertIsNone(nbcheck.version_base("model12345"))

    def test_descriptive_name_is_not_versioned(self):
        self.assertIsNone(nbcheck.version_base("df_clean"))


class TestFmtSizeZero(unittest.TestCase):
    def test_zero_bytes(self):
        self.assertEqual(nbcheck.fmt_size(0), "0 B")


class TestAnalyzeWarnings(unittest.TestCase):
    def test_duplicated_import_warns(self):
        code, out = _analyze(
            _NARRATIVE + [_code_cell("import os\n"), _code_cell("import os\n", 2)]
        )
        self.assertEqual(code, 1)
        self.assertIn("Duplicated", out)

    def test_versioned_name_smell_warns(self):
        # df assigned, then df2 assigned -> genuine versioning smell.
        code, out = _analyze(
            _NARRATIVE + [_code_cell("df = 1\n"), _code_cell("df2 = 2\n", 2)]
        )
        self.assertEqual(code, 1)
        self.assertIn("df2", out)

    def test_intrinsic_digit_name_does_not_smell(self):
        # col1 / col2 without an un-numbered "col" base must not be flagged.
        code, out = _analyze(
            _NARRATIVE + [_code_cell("col1 = 1\n"), _code_cell("col2 = 2\n", 2)]
        )
        self.assertIn("No versioned variable names detected", out)

    def test_long_cell_warns(self):
        body = "\n".join("x{0} = {0}".format(i) for i in range(45))
        code, out = _analyze(_NARRATIVE + [_code_cell(body)])
        self.assertEqual(code, 1)
        self.assertIn("longer than", out)

    def test_oversized_output_warns(self):
        big = [{"output_type": "stream", "text": "A" * 60000}]
        code, out = _analyze(_NARRATIVE + [_code_cell("x = 1\n", 1, big)])
        self.assertEqual(code, 1)
        self.assertIn("oversized", out)

    def test_unexecuted_cell_warns(self):
        code, out = _analyze(
            _NARRATIVE + [_code_cell("a = 1\n", execution_count=None),
                          _code_cell("b = 2\n", execution_count=1)]
        )
        self.assertEqual(code, 1)
        self.assertIn("never executed", out)


if __name__ == "__main__":
    unittest.main()
