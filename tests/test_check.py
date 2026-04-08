# SPDX-License-Identifier: Apache-2.0
"""Tests for the check logic."""

from __future__ import annotations

import pytest

from dossier.check import check_diff, CheckResult, Finding
from dossier.git import DiffSnapshot
from dossier.store import GrantStore


@pytest.fixture
def store(tmp_path):
    s = GrantStore(tmp_path / "dossier.db")
    yield s
    s.close()


def _make_snapshot(diff_hash="sha256:abc", files=("src/foo.py",)):
    return DiffSnapshot(
        diff_hash=diff_hash,
        base_ref="main",
        head_ref="deadbeef",
        files_changed=files,
        diff_bytes=100,
    )


class TestCheckDiff:
    def test_no_grants_warns(self, store):
        snap = _make_snapshot()
        result = check_diff(snap, store)
        assert not result.clean or any(f.scar == "no_approval" for f in result.findings)
        assert result.grants_active == 0

    def test_no_grants_required_errors(self, store):
        snap = _make_snapshot()
        result = check_diff(snap, store, require_approval=True)
        errors = [f for f in result.findings if f.severity == "error"]
        assert any(f.scar == "no_approval" for f in errors)

    def test_matching_grant_passes(self, store):
        snap = _make_snapshot()
        store.create_grant(
            diff_hash=snap.diff_hash,
            head_ref=snap.head_ref,
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["src/**"],
            files_reviewed=list(snap.files_changed),
        )
        result = check_diff(snap, store)
        assert result.grants_active == 1
        assert not any(f.scar == "no_approval" for f in result.findings)

    def test_stale_grant_detected(self, store):
        # Grant was for a different diff hash
        store.create_grant(
            diff_hash="sha256:OLD",
            head_ref="oldhead",
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["src/**"],
            files_reviewed=["src/foo.py"],
        )
        snap = _make_snapshot(diff_hash="sha256:NEW")
        result = check_diff(snap, store)
        assert result.grants_stale > 0
        stale_findings = [f for f in result.findings if f.scar == "stale_approval"]
        assert len(stale_findings) > 0

    def test_scope_gap_detected(self, store):
        snap = _make_snapshot(files=("src/foo.py", "src/bar.py"))
        # Grant only covers foo.py
        store.create_grant(
            diff_hash=snap.diff_hash,
            head_ref=snap.head_ref,
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["src/foo.py"],
            files_reviewed=["src/foo.py"],  # only reviewed foo
        )
        result = check_diff(snap, store)
        gap_findings = [f for f in result.findings if f.scar == "scope_gap"]
        assert len(gap_findings) == 1
        assert "src/bar.py" in gap_findings[0].detail["uncovered_files"]

    def test_clean_result_properties(self, store):
        snap = _make_snapshot()
        store.create_grant(
            diff_hash=snap.diff_hash,
            head_ref=snap.head_ref,
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["*"],
            files_reviewed=list(snap.files_changed),
        )
        result = check_diff(snap, store)
        assert result.clean
        assert result.errors == []

    def test_expired_grant_not_counted_as_active(self, store):
        snap = _make_snapshot()
        store.create_grant(
            diff_hash=snap.diff_hash,
            head_ref=snap.head_ref,
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["*"],
            files_reviewed=list(snap.files_changed),
            ttl_hours=0.0,
        )
        result = check_diff(snap, store)
        assert result.grants_active == 0
