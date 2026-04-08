# SPDX-License-Identifier: Apache-2.0
"""Suppression scanner: detect lint/type/safety suppressions in source files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Patterns that indicate a suppression/override/waiver
SUPPRESSION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("type_ignore", re.compile(r"#\s*type:\s*ignore", re.IGNORECASE)),
    ("noqa", re.compile(r"#\s*noqa", re.IGNORECASE)),
    ("pylint_disable", re.compile(r"#\s*pylint:\s*disable", re.IGNORECASE)),
    ("suppress_warnings", re.compile(r"@SuppressWarnings", re.IGNORECASE)),
    ("eslint_disable", re.compile(r"//\s*eslint-disable", re.IGNORECASE)),
    ("nolint", re.compile(r"//\s*nolint", re.IGNORECASE)),
    ("rust_allow", re.compile(r"#\[allow\(", re.IGNORECASE)),  # Rust #[allow(...)]
    ("rust_expect", re.compile(r"#\[expect\(", re.IGNORECASE)),  # Rust #[expect(...)]
    ("unsafe", re.compile(r"\bunsafe\s*\{", re.IGNORECASE)),  # Rust unsafe blocks
    ("nosec", re.compile(r"#\s*nosec", re.IGNORECASE)),  # bandit
    ("todo", re.compile(r"(?://|#)\s*TODO\b", re.IGNORECASE)),
    ("fixme", re.compile(r"(?://|#)\s*FIXME\b", re.IGNORECASE)),
    ("hack", re.compile(r"(?://|#)\s*HACK\b", re.IGNORECASE)),
    ("skip_test", re.compile(r"@pytest\.mark\.skip|@skip|xit\(|xdescribe\(", re.IGNORECASE)),
    ("no_verify", re.compile(r"--no-verify|--force|--dangerously", re.IGNORECASE)),
]

# File extensions to scan
SCANNABLE_EXTENSIONS = {
    ".py", ".rs", ".go", ".js", ".ts", ".tsx", ".jsx",
    ".java", ".kt", ".rb", ".sh", ".bash", ".yml", ".yaml",
    ".toml", ".json", ".c", ".cpp", ".h", ".hpp",
}


@dataclass(frozen=True)
class SuppressionFinding:
    """A single suppression found in a file."""

    file_path: str
    pattern: str
    line_number: int
    line_text: str

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "pattern": self.pattern,
            "line_number": self.line_number,
        }


def scan_file(path: Path, relative_to: Path | None = None) -> list[SuppressionFinding]:
    """Scan a single file for suppression patterns."""
    try:
        text = path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return []

    rel = str(path.relative_to(relative_to)) if relative_to else str(path)
    findings: list[SuppressionFinding] = []

    for i, line in enumerate(text.splitlines(), 1):
        for name, pattern in SUPPRESSION_PATTERNS:
            if pattern.search(line):
                findings.append(SuppressionFinding(
                    file_path=rel,
                    pattern=name,
                    line_number=i,
                    line_text=line.strip()[:120],
                ))

    return findings


def scan_directory(
    root: Path,
    files: list[str] | None = None,
) -> list[SuppressionFinding]:
    """Scan files for suppression patterns.

    If files is provided, scan only those. Otherwise scan all scannable files.
    """
    findings: list[SuppressionFinding] = []

    if files:
        for f in files:
            path = root / f
            if path.is_file() and path.suffix in SCANNABLE_EXTENSIONS:
                findings.extend(scan_file(path, relative_to=root))
    else:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in SCANNABLE_EXTENSIONS:
                # Skip hidden dirs and common vendor paths
                parts = path.relative_to(root).parts
                if any(p.startswith(".") or p in ("node_modules", "vendor", "target", "dist", "build") for p in parts):
                    continue
                findings.extend(scan_file(path, relative_to=root))

    return findings
