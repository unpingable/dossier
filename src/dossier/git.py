# SPDX-License-Identifier: Apache-2.0
"""Git operations: diff hashing, file listing, branch detection."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiffSnapshot:
    """Content-addressed snapshot of a diff."""

    diff_hash: str       # sha256 of the unified diff
    base_ref: str        # what we're diffing against (e.g. "main")
    head_ref: str        # current HEAD sha
    files_changed: tuple[str, ...]
    diff_bytes: int      # size of the diff

    @property
    def short_hash(self) -> str:
        return self.diff_hash[:12]


def run_git(*args: str, cwd: str | Path | None = None) -> str:
    """Run a git command, return stdout. Raises on failure."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True,
        cwd=str(cwd) if cwd else None,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def current_head(cwd: str | Path | None = None) -> str:
    """Get current HEAD sha."""
    return run_git("rev-parse", "HEAD", cwd=cwd).strip()


def current_branch(cwd: str | Path | None = None) -> str:
    """Get current branch name, or HEAD if detached."""
    try:
        return run_git("symbolic-ref", "--short", "HEAD", cwd=cwd).strip()
    except RuntimeError:
        return "HEAD"


def merge_base(ref: str = "main", cwd: str | Path | None = None) -> str:
    """Find the merge base between current HEAD and ref."""
    return run_git("merge-base", ref, "HEAD", cwd=cwd).strip()


def diff_against(base_ref: str = "main", cwd: str | Path | None = None) -> str:
    """Get the unified diff between merge-base and HEAD."""
    base = merge_base(base_ref, cwd=cwd)
    return run_git("diff", base, "HEAD", cwd=cwd)


def snapshot_diff(base_ref: str = "main", cwd: str | Path | None = None) -> DiffSnapshot:
    """Create a content-addressed snapshot of the current diff against base."""
    diff_text = diff_against(base_ref, cwd=cwd)
    diff_hash = "sha256:" + hashlib.sha256(diff_text.encode()).hexdigest()
    head = current_head(cwd=cwd)

    # Extract changed files from diff
    files_output = run_git(
        "diff", "--name-only", merge_base(base_ref, cwd=cwd), "HEAD",
        cwd=cwd,
    )
    files = tuple(f for f in files_output.strip().splitlines() if f)

    return DiffSnapshot(
        diff_hash=diff_hash,
        base_ref=base_ref,
        head_ref=head,
        files_changed=files,
        diff_bytes=len(diff_text.encode()),
    )


def changed_files(base_ref: str = "main", cwd: str | Path | None = None) -> list[str]:
    """List files changed between merge-base and HEAD."""
    base = merge_base(base_ref, cwd=cwd)
    output = run_git("diff", "--name-only", base, "HEAD", cwd=cwd)
    return [f for f in output.strip().splitlines() if f]
