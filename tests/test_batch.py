# SPDX-License-Identifier: Apache-2.0
"""Tests for batch replay."""

from __future__ import annotations

from dossier.batch import RepoSpec, BatchSummary
from dossier.ingest import ReplayReport, ZoneStats, ScarFinding


def _make_report(
    owner_repo: str = "test/repo",
    prs: int = 50,
    findings: int = 10,
    scars: dict | None = None,
) -> ReplayReport:
    scars = scars or {"stale_approval": findings}
    return ReplayReport(
        owner_repo=owner_repo,
        prs_analyzed=prs,
        total_findings=findings,
        findings_by_scar=scars,
        findings_by_tier={"standard": findings},
        zone_stats=[],
        weakest_prs=[],
        all_findings=[],
    )


class TestBatchSummary:
    def test_comparative_table_basic(self):
        specs = [
            RepoSpec(owner_repo="a/repo", category="control"),
            RepoSpec(owner_repo="b/repo", category="case_study"),
        ]
        reports = {
            "a/repo": _make_report("a/repo", prs=50, findings=10),
            "b/repo": _make_report("b/repo", prs=50, findings=25),
        }
        summary = BatchSummary(repos=specs, reports=reports, errors={})
        table = summary.comparative_table()

        assert len(table) == 2
        a_row = [r for r in table if r["repo"] == "a/repo"][0]
        b_row = [r for r in table if r["repo"] == "b/repo"][0]
        assert a_row["scar_rate"] == 0.2
        assert b_row["scar_rate"] == 0.5
        assert a_row["category"] == "control"
        assert b_row["category"] == "case_study"

    def test_comparative_table_with_error(self):
        specs = [
            RepoSpec(owner_repo="a/repo"),
            RepoSpec(owner_repo="broken/repo"),
        ]
        reports = {"a/repo": _make_report("a/repo")}
        errors = {"broken/repo": "not found"}
        summary = BatchSummary(repos=specs, reports=reports, errors=errors)
        table = summary.comparative_table()

        assert len(table) == 2
        broken = [r for r in table if r["repo"] == "broken/repo"][0]
        assert broken["error"] == "not found"
        assert broken["prs"] == 0

    def test_scar_type_rates(self):
        specs = [RepoSpec(owner_repo="x/y")]
        reports = {
            "x/y": _make_report(
                "x/y", prs=100, findings=20,
                scars={"stale_approval": 10, "self_merge": 5, "no_approval": 5},
            ),
        }
        summary = BatchSummary(repos=specs, reports=reports, errors={})
        row = summary.comparative_table()[0]
        assert row["stale_approval_rate"] == 0.10
        assert row["self_merge_rate"] == 0.05
        assert row["no_approval_rate"] == 0.05

    def test_to_dict(self):
        specs = [RepoSpec(owner_repo="a/b")]
        reports = {"a/b": _make_report("a/b")}
        summary = BatchSummary(repos=specs, reports=reports, errors={})
        d = summary.to_dict()
        assert "comparative" in d
        assert "reports" in d
        assert "a/b" in d["reports"]
