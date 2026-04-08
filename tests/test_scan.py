# SPDX-License-Identifier: Apache-2.0
"""Tests for suppression scanner."""

from __future__ import annotations

from pathlib import Path

from dossier.scan import scan_file, scan_directory, SuppressionFinding


class TestScanFile:
    def test_detects_type_ignore(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("x = 1  # type: ignore\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert len(findings) == 1
        assert findings[0].pattern == "type_ignore"

    def test_detects_noqa(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("import os  # noqa: F401\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert len(findings) == 1
        assert findings[0].pattern == "noqa"

    def test_detects_eslint_disable(self, tmp_path):
        f = tmp_path / "foo.js"
        f.write_text("// eslint-disable-next-line no-unused-vars\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert len(findings) == 1
        assert findings[0].pattern == "eslint_disable"

    def test_detects_todo(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("# TODO: fix this later\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert len(findings) == 1
        assert findings[0].pattern == "todo"

    def test_detects_skip_test(self, tmp_path):
        f = tmp_path / "test_foo.py"
        f.write_text("@pytest.mark.skip(reason='broken')\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert len(findings) == 1
        assert findings[0].pattern == "skip_test"

    def test_detects_rust_allow(self, tmp_path):
        f = tmp_path / "foo.rs"
        f.write_text("#[allow(dead_code)]\nfn unused() {}\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert len(findings) == 1
        assert findings[0].pattern == "rust_allow"

    def test_detects_rust_expect(self, tmp_path):
        f = tmp_path / "foo.rs"
        f.write_text("#[expect(unused_variables)]\nlet x = 1;\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert len(findings) == 1
        assert findings[0].pattern == "rust_expect"

    def test_detects_unsafe_rust(self, tmp_path):
        f = tmp_path / "foo.rs"
        f.write_text("unsafe {\n    ptr::read(p)\n}\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert len(findings) == 1
        assert findings[0].pattern == "unsafe"

    def test_multiple_patterns_same_file(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("x = 1  # type: ignore\n# TODO: clean up\ny = 2  # noqa\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert len(findings) == 3
        patterns = {f.pattern for f in findings}
        assert patterns == {"type_ignore", "todo", "noqa"}

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        assert scan_file(f, relative_to=tmp_path) == []

    def test_no_suppressions(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("def hello():\n    return 'world'\n")
        assert scan_file(f, relative_to=tmp_path) == []

    def test_line_numbers_correct(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("line1\nline2\nx = 1  # noqa\nline4\n")
        findings = scan_file(f, relative_to=tmp_path)
        assert findings[0].line_number == 3


class TestScanDirectory:
    def test_scans_specific_files(self, tmp_path):
        (tmp_path / "a.py").write_text("# TODO: fix\n")
        (tmp_path / "b.py").write_text("clean\n")
        findings = scan_directory(tmp_path, files=["a.py"])
        assert len(findings) == 1

    def test_skips_hidden_dirs(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "bad.py").write_text("# TODO: evil\n")
        (tmp_path / "good.py").write_text("# TODO: visible\n")
        findings = scan_directory(tmp_path)
        assert all(f.file_path == "good.py" for f in findings)

    def test_skips_vendor(self, tmp_path):
        vendor = tmp_path / "node_modules"
        vendor.mkdir()
        (vendor / "dep.js").write_text("// eslint-disable\n")
        (tmp_path / "app.js").write_text("// eslint-disable\n")
        findings = scan_directory(tmp_path)
        assert all("node_modules" not in f.file_path for f in findings)
