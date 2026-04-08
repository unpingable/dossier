# SPDX-License-Identifier: Apache-2.0
"""Batch replay: run scar analysis across multiple repos for comparison."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from dossier.ingest import (
    PRData, ReplayReport, ZoneStats,
    fetch_merged_prs, replay_history,
)


@dataclass(frozen=True)
class RepoSpec:
    """A repo to include in the batch, with optional zone prefixes."""

    owner_repo: str
    prefixes: list[str] = field(default_factory=list)
    category: str = "control"  # "own", "case_study", "control", "velocity", "peer"


@dataclass
class BatchSummary:
    """Comparative summary across repos."""

    repos: list[RepoSpec]
    reports: dict[str, ReplayReport]  # keyed by owner_repo
    errors: dict[str, str]           # repos that failed to fetch

    @property
    def successful(self) -> list[str]:
        return list(self.reports.keys())

    def comparative_table(self) -> list[dict[str, Any]]:
        """One row per repo with headline metrics for comparison."""
        rows = []
        for spec in self.repos:
            report = self.reports.get(spec.owner_repo)
            if not report:
                rows.append({
                    "repo": spec.owner_repo,
                    "category": spec.category,
                    "prs": 0,
                    "findings": 0,
                    "scar_rate": 0.0,
                    "stale_approval_rate": 0.0,
                    "risk_mismatch_rate": 0.0,
                    "no_approval_rate": 0.0,
                    "self_merge_rate": 0.0,
                    "review_theater_rate": 0.0,
                    "error": self.errors.get(spec.owner_repo, "unknown"),
                })
                continue

            n = report.prs_analyzed or 1
            scars = report.findings_by_scar
            rows.append({
                "repo": spec.owner_repo,
                "category": spec.category,
                "prs": report.prs_analyzed,
                "findings": report.total_findings,
                "scar_rate": round(report.total_findings / n, 2),
                "stale_approval_rate": round(scars.get("stale_approval", 0) / n, 2),
                "risk_mismatch_rate": round(scars.get("risk_mismatch", 0) / n, 2),
                "no_approval_rate": round(scars.get("no_approval", 0) / n, 2),
                "self_merge_rate": round(scars.get("self_merge", 0) / n, 2),
                "review_theater_rate": round(scars.get("review_theater", 0) / n, 2),
            })
        return rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparative": self.comparative_table(),
            "reports": {
                name: report.to_dict()
                for name, report in self.reports.items()
            },
            "errors": self.errors,
        }


def run_batch(
    repos: list[RepoSpec],
    limit: int = 100,
    tier_rules: dict[str, list[str]] | None = None,
) -> BatchSummary:
    """Run scar replay across multiple repos."""
    reports: dict[str, ReplayReport] = {}
    errors: dict[str, str] = {}

    for i, spec in enumerate(repos, 1):
        print(
            f"[{i}/{len(repos)}] {spec.owner_repo} ({spec.category})...",
            file=sys.stderr,
        )
        try:
            prs = fetch_merged_prs(spec.owner_repo, limit=limit)
            prefixes = spec.prefixes or None
            report = replay_history(prs, spec.owner_repo, tier_rules, prefixes)
            reports[spec.owner_repo] = report
            print(
                f"  {report.prs_analyzed} PRs, {report.total_findings} findings",
                file=sys.stderr,
            )
        except Exception as e:
            errors[spec.owner_repo] = str(e)
            print(f"  ERROR: {e}", file=sys.stderr)

    return BatchSummary(repos=repos, reports=reports, errors=errors)
