# SPDX-License-Identifier: Apache-2.0
"""Tests for the grant store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dossier.store import GrantStore, ReviewGrant, _compute_receipt_hash


@pytest.fixture
def store(tmp_path):
    s = GrantStore(tmp_path / "dossier.db")
    yield s
    s.close()


class TestGrantStore:
    def test_create_grant(self, store):
        g = store.create_grant(
            diff_hash="sha256:abc123",
            head_ref="deadbeef",
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["src/**"],
            files_reviewed=["src/foo.py"],
        )
        assert g.grant_id
        assert g.diff_hash == "sha256:abc123"
        assert g.reviewer_id == "jbeck"
        assert g.is_active

    def test_get_active_grants(self, store):
        store.create_grant(
            diff_hash="sha256:abc",
            head_ref="dead",
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["*"],
            files_reviewed=["foo.py"],
        )
        active = store.get_active_grants("sha256:abc")
        assert len(active) == 1
        assert active[0].reviewer_id == "jbeck"

    def test_different_diff_hash_not_found(self, store):
        store.create_grant(
            diff_hash="sha256:abc",
            head_ref="dead",
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["*"],
            files_reviewed=["foo.py"],
        )
        active = store.get_active_grants("sha256:different")
        assert len(active) == 0

    def test_expired_grant_not_active(self, store):
        store.create_grant(
            diff_hash="sha256:abc",
            head_ref="dead",
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["*"],
            files_reviewed=["foo.py"],
            ttl_hours=0.0,  # expires immediately
        )
        active = store.get_active_grants("sha256:abc")
        assert len(active) == 0

    def test_revoke_grant(self, store):
        g = store.create_grant(
            diff_hash="sha256:abc",
            head_ref="dead",
            base_ref="main",
            reviewer_id="jbeck",
            reviewer_label="James",
            scope=["*"],
            files_reviewed=["foo.py"],
        )
        assert store.revoke_grant(g.grant_id, "changed my mind")
        active = store.get_active_grants("sha256:abc")
        assert len(active) == 0

    def test_receipt_hash_deterministic(self):
        h1 = _compute_receipt_hash("d", "r", ["a"], ["b"], {}, "t1", "t2")
        h2 = _compute_receipt_hash("d", "r", ["a"], ["b"], {}, "t1", "t2")
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_receipt_hash_changes_with_diff(self):
        h1 = _compute_receipt_hash("d1", "r", ["a"], ["b"], {}, "t1", "t2")
        h2 = _compute_receipt_hash("d2", "r", ["a"], ["b"], {}, "t1", "t2")
        assert h1 != h2

    def test_get_all_grants(self, store):
        for i in range(3):
            store.create_grant(
                diff_hash=f"sha256:{i}",
                head_ref="dead",
                base_ref="main",
                reviewer_id="jbeck",
                reviewer_label="James",
                scope=["*"],
                files_reviewed=["foo.py"],
            )
        all_grants = store.get_all_grants()
        assert len(all_grants) == 3


class TestSuppressionTracking:
    def test_record_and_query(self, store):
        findings = [
            {"file_path": "src/foo.py", "pattern": "noqa", "line_number": 10},
            {"file_path": "src/foo.py", "pattern": "type_ignore", "line_number": 20},
            {"file_path": "src/bar.py", "pattern": "noqa", "line_number": 5},
        ]
        gen = store.record_suppressions(findings, head_ref="abc123")
        assert gen is not None

        pressure = store.suppression_pressure(gen)
        assert len(pressure) == 3  # 3 (file, pattern) combos

    def test_latest_generation_default(self, store):
        findings = [{"file_path": "a.py", "pattern": "todo", "line_number": 1}]
        store.record_suppressions(findings, head_ref="abc")
        pressure = store.suppression_pressure()
        assert len(pressure) == 1
