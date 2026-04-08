# SPDX-License-Identifier: Apache-2.0
"""GitHub PR history ingestion for scar replay.

Pulls merged PRs via `gh api`, reconstructs review history,
and detects mechanical scar patterns from historical data.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Any


@dataclass(frozen=True)
class PRReview:
    """A single review event on a PR."""

    reviewer: str
    state: str  # APPROVED, CHANGES_REQUESTED, COMMENTED, DISMISSED
    commit_id: str  # HEAD commit when review was submitted
    submitted_at: str
    body: str = ""


@dataclass(frozen=True)
class PRData:
    """A merged PR with its review history."""

    number: int
    title: str
    author: str
    merged_at: str
    merge_commit_sha: str
    head_sha: str  # final HEAD of PR branch at merge time
    base_ref: str
    files_changed: tuple[str, ...]
    additions: int
    deletions: int
    reviews: tuple[PRReview, ...]
    review_comments: int = 0

    @property
    def diff_size(self) -> int:
        return self.additions + self.deletions

    @property
    def approvals(self) -> list[PRReview]:
        return [r for r in self.reviews if r.state == "APPROVED"]


@dataclass(frozen=True)
class ScarFinding:
    """A review scar detected in a merged PR."""

    pr_number: int
    scar: str
    severity: str  # "error", "warn", "info"
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


# -- Risk tiers --

DEFAULT_TIER_RULES: dict[str, list[str]] = {
    "critical": [],
    "structural": [],
    "standard": [],  # default fallback — no explicit patterns needed
    "low": ["*.md", "*.txt", "*.rst", "LICENSE*", "CHANGELOG*", ".gitignore"],
}

TIER_SEVERITY_ORDER = ["critical", "structural", "standard", "low"]


def assign_risk_tier(
    path: str,
    tier_rules: dict[str, list[str]] | None = None,
) -> str:
    """Assign a risk tier to a file path. First match in priority order wins."""
    rules = tier_rules or DEFAULT_TIER_RULES
    basename = path.split("/")[-1]
    for tier in TIER_SEVERITY_ORDER:
        for pattern in rules.get(tier, []):
            if fnmatch(path, pattern) or fnmatch(basename, pattern):
                return tier
    return "standard"


def highest_tier(files: list[str], tier_rules: dict[str, list[str]] | None = None) -> str:
    """Return the highest risk tier among a set of files."""
    tiers = {assign_risk_tier(f, tier_rules) for f in files}
    for t in TIER_SEVERITY_ORDER:
        if t in tiers:
            return t
    return "standard"


# -- GitHub API --

def _gh_api(endpoint: str, paginate: bool = False) -> Any:
    """Call gh api. Raises on failure."""
    cmd = ["gh", "api", endpoint, "--header", "Accept: application/vnd.github+json"]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {endpoint} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _gh_graphql(query: str, variables: dict[str, Any] | None = None) -> Any:
    """Call gh api graphql."""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    if variables:
        for k, v in variables.items():
            cmd.extend(["-f", f"{k}={v}"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api graphql failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def fetch_merged_prs(
    owner_repo: str,
    limit: int = 100,
) -> list[PRData]:
    """Fetch recent merged PRs with review data.

    Uses REST API: pulls list, then reviews + files per PR.
    """
    prs: list[PRData] = []
    page = 1
    per_page = min(limit, 100)

    while len(prs) < limit:
        pr_list = _gh_api(
            f"/repos/{owner_repo}/pulls?state=closed&sort=updated"
            f"&direction=desc&per_page={per_page}&page={page}"
        )
        if not pr_list:
            break

        for pr in pr_list:
            if len(prs) >= limit:
                break
            if not pr.get("merged_at"):
                continue

            number = pr["number"]

            # Fetch reviews
            raw_reviews = _gh_api(f"/repos/{owner_repo}/pulls/{number}/reviews")
            reviews = tuple(
                PRReview(
                    reviewer=r.get("user", {}).get("login", "unknown"),
                    state=r["state"],
                    commit_id=r.get("commit_id", ""),
                    submitted_at=r.get("submitted_at", ""),
                    body=r.get("body", "") or "",
                )
                for r in raw_reviews
            )

            # Fetch files changed
            raw_files = _gh_api(f"/repos/{owner_repo}/pulls/{number}/files")
            files = tuple(f["filename"] for f in raw_files)

            prs.append(PRData(
                number=number,
                title=pr["title"],
                author=pr.get("user", {}).get("login", "unknown"),
                merged_at=pr["merged_at"],
                merge_commit_sha=pr.get("merge_commit_sha", ""),
                head_sha=pr.get("head", {}).get("sha", ""),
                base_ref=pr.get("base", {}).get("ref", "main"),
                files_changed=files,
                additions=pr.get("additions", 0),
                deletions=pr.get("deletions", 0),
                reviews=reviews,
                review_comments=pr.get("review_comments", 0),
            ))

        page += 1
        if len(pr_list) < per_page:
            break

    return prs


# -- Scar detection --

def _detect_stale_approval(pr: PRData) -> list[ScarFinding]:
    """Scar 1: approval commit != final HEAD at merge."""
    findings = []
    for review in pr.approvals:
        if review.commit_id and review.commit_id != pr.head_sha:
            findings.append(ScarFinding(
                pr_number=pr.number,
                scar="stale_approval",
                severity="error",
                message=(
                    f"Approval by {review.reviewer} was against "
                    f"{review.commit_id[:8]}, but PR merged at {pr.head_sha[:8]}"
                ),
                detail={
                    "reviewer": review.reviewer,
                    "approved_commit": review.commit_id,
                    "merged_head": pr.head_sha,
                    "submitted_at": review.submitted_at,
                },
            ))
    return findings


def _detect_no_approval(pr: PRData) -> list[ScarFinding]:
    """No approval at all — merged without review."""
    if not pr.approvals:
        return [ScarFinding(
            pr_number=pr.number,
            scar="no_approval",
            severity="error",
            message="PR merged with no approving review",
        )]
    return []


def _detect_self_merge(pr: PRData) -> list[ScarFinding]:
    """Scar 5: only approvals are from the PR author."""
    if not pr.approvals:
        return []
    if all(r.reviewer == pr.author for r in pr.approvals):
        return [ScarFinding(
            pr_number=pr.number,
            scar="self_merge",
            severity="warn",
            message=f"Only approval(s) by PR author {pr.author}",
        )]
    return []


def _detect_review_theater(
    pr: PRData,
    large_diff_threshold: int = 300,
    fast_approval_minutes: int = 5,
) -> list[ScarFinding]:
    """Scar 4: large PR, fast approval, minimal engagement."""
    if pr.diff_size < large_diff_threshold:
        return []
    if not pr.approvals:
        return []

    findings = []
    for review in pr.approvals:
        if not review.submitted_at:
            continue
        # We can't easily get PR creation time from this data,
        # but we can check: no body + no review comments + large diff
        if (
            not review.body.strip()
            and pr.review_comments == 0
            and pr.diff_size >= large_diff_threshold
        ):
            findings.append(ScarFinding(
                pr_number=pr.number,
                scar="review_theater",
                severity="warn",
                message=(
                    f"Large PR ({pr.diff_size} lines), "
                    f"approval by {review.reviewer} with no comments"
                ),
                detail={
                    "diff_size": pr.diff_size,
                    "reviewer": review.reviewer,
                    "review_comments": pr.review_comments,
                },
            ))
    return findings


def _detect_risk_mismatch(
    pr: PRData,
    tier_rules: dict[str, list[str]] | None = None,
) -> list[ScarFinding]:
    """Scar 8: critical files with lightweight review."""
    tier = highest_tier(list(pr.files_changed), tier_rules)
    if tier not in ("critical", "structural"):
        return []

    # Lightweight = no comments and only one approval
    if len(pr.approvals) <= 1 and pr.review_comments == 0:
        return [ScarFinding(
            pr_number=pr.number,
            scar="risk_mismatch",
            severity="warn",
            message=(
                f"PR touches {tier}-tier files but has "
                f"{len(pr.approvals)} approval(s) and {pr.review_comments} comments"
            ),
            detail={
                "tier": tier,
                "approvals": len(pr.approvals),
                "review_comments": pr.review_comments,
                "critical_files": [
                    f for f in pr.files_changed
                    if assign_risk_tier(f, tier_rules) in ("critical", "structural")
                ][:10],
            },
        )]
    return []


def analyze_pr(
    pr: PRData,
    tier_rules: dict[str, list[str]] | None = None,
) -> list[ScarFinding]:
    """Run all scar detectors against a single PR."""
    findings: list[ScarFinding] = []
    findings.extend(_detect_stale_approval(pr))
    findings.extend(_detect_no_approval(pr))
    findings.extend(_detect_self_merge(pr))
    findings.extend(_detect_review_theater(pr))
    findings.extend(_detect_risk_mismatch(pr, tier_rules))
    return findings


# -- Aggregation --

@dataclass(frozen=True)
class ZoneStats:
    """Scar statistics for a single path-prefix zone."""

    prefix: str
    prs_touching: int       # PRs that changed files in this zone
    prs_with_findings: int  # PRs touching this zone that had >=1 finding
    findings: int           # findings from PRs touching this zone (each counted once per zone)
    scar_rate: float        # findings / prs_touching

    def to_dict(self) -> dict[str, Any]:
        return {
            "prefix": self.prefix,
            "prs_touching": self.prs_touching,
            "prs_with_findings": self.prs_with_findings,
            "findings": self.findings,
            "scar_rate": round(self.scar_rate, 2),
        }


@dataclass
class ReplayReport:
    """Aggregated results from replaying PR history."""

    owner_repo: str
    prs_analyzed: int
    total_findings: int
    findings_by_scar: dict[str, int]
    findings_by_tier: dict[str, int]
    zone_stats: list[ZoneStats]
    weakest_prs: list[dict[str, Any]]  # top N PRs by finding count
    all_findings: list[ScarFinding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_repo": self.owner_repo,
            "prs_analyzed": self.prs_analyzed,
            "total_findings": self.total_findings,
            "findings_by_scar": self.findings_by_scar,
            "findings_by_tier": self.findings_by_tier,
            "zone_stats": [z.to_dict() for z in self.zone_stats],
            "weakest_prs": self.weakest_prs,
            "all_findings": [
                {
                    "pr": f.pr_number,
                    "scar": f.scar,
                    "severity": f.severity,
                    "message": f.message,
                    "detail": f.detail,
                }
                for f in self.all_findings
            ],
        }


def _pr_touches_prefix(pr: PRData, prefix: str) -> bool:
    """Does this PR have any changed files under this prefix?"""
    return any(f.startswith(prefix) for f in pr.files_changed)


def replay_history(
    prs: list[PRData],
    owner_repo: str,
    tier_rules: dict[str, list[str]] | None = None,
    path_prefixes: list[str] | None = None,
) -> ReplayReport:
    """Replay PR history and aggregate findings.

    Counting units:
    - A "finding" is a single scar detection on a single PR.
    - "findings_by_scar" and "findings_by_tier" count each finding exactly once.
    - "zone_stats" counts per prefix: how many PRs touched the zone,
      how many of those had findings, and total findings from those PRs.
      A PR touching multiple zones is counted in each zone it touches,
      so zone totals may exceed total_findings. This is deliberate:
      it measures custody *per zone*, not overall.
    """
    all_findings: list[ScarFinding] = []
    pr_finding_counts: dict[int, int] = {}
    pr_titles: dict[int, str] = {}
    pr_map: dict[int, PRData] = {}

    for pr in prs:
        findings = analyze_pr(pr, tier_rules)
        all_findings.extend(findings)
        pr_finding_counts[pr.number] = len(findings)
        pr_titles[pr.number] = pr.title
        pr_map[pr.number] = pr

    # Aggregate by scar type — each finding counted exactly once
    by_scar: dict[str, int] = {}
    for f in all_findings:
        by_scar[f.scar] = by_scar.get(f.scar, 0) + 1

    # Aggregate by risk tier — each finding counted once, attributed
    # to the highest tier among the PR's changed files
    by_tier: dict[str, int] = {}
    for pr in prs:
        pr_findings = pr_finding_counts.get(pr.number, 0)
        if pr_findings:
            tier = highest_tier(list(pr.files_changed), tier_rules)
            by_tier[tier] = by_tier.get(tier, 0) + pr_findings

    # Zone stats — per-prefix custody analysis
    prefixes = path_prefixes or []
    zone_stats: list[ZoneStats] = []
    for prefix in prefixes:
        prs_touching = [pr for pr in prs if _pr_touches_prefix(pr, prefix)]
        prs_with_findings = [pr for pr in prs_touching if pr_finding_counts.get(pr.number, 0) > 0]
        zone_finding_count = sum(pr_finding_counts.get(pr.number, 0) for pr in prs_touching)
        zone_stats.append(ZoneStats(
            prefix=prefix,
            prs_touching=len(prs_touching),
            prs_with_findings=len(prs_with_findings),
            findings=zone_finding_count,
            scar_rate=zone_finding_count / len(prs_touching) if prs_touching else 0.0,
        ))
    zone_stats.sort(key=lambda z: -z.scar_rate)

    # Top N weakest PRs
    worst = sorted(pr_finding_counts.items(), key=lambda x: -x[1])[:20]
    weakest = [
        {"pr": num, "findings": count, "title": pr_titles.get(num, "")}
        for num, count in worst
        if count > 0
    ]

    return ReplayReport(
        owner_repo=owner_repo,
        prs_analyzed=len(prs),
        total_findings=len(all_findings),
        findings_by_scar=by_scar,
        findings_by_tier=by_tier,
        zone_stats=zone_stats,
        weakest_prs=weakest,
        all_findings=all_findings,
    )
