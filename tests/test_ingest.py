# SPDX-License-Identifier: Apache-2.0
"""Tests for PR history ingestion and custody analysis."""

from __future__ import annotations

from dossier.ingest import (
    PRData, PRReview, ScarFinding,
    analyze_pr, assign_risk_tier, highest_tier, replay_history,
)


def _make_pr(
    number: int = 1,
    author: str = "alice",
    head_sha: str = "aaa111",
    files: tuple[str, ...] = ("src/foo.py",),
    additions: int = 10,
    deletions: int = 5,
    reviews: tuple[PRReview, ...] = (),
    review_comments: int = 0,
) -> PRData:
    return PRData(
        number=number,
        title=f"PR #{number}",
        author=author,
        merged_at="2026-04-01T00:00:00Z",
        merge_commit_sha="merge123",
        head_sha=head_sha,
        base_ref="main",
        files_changed=files,
        additions=additions,
        deletions=deletions,
        reviews=reviews,
        review_comments=review_comments,
    )


def _make_review(
    reviewer: str = "bob",
    state: str = "APPROVED",
    commit_id: str = "aaa111",
    body: str = "",
) -> PRReview:
    return PRReview(
        reviewer=reviewer,
        state=state,
        commit_id=commit_id,
        submitted_at="2026-04-01T00:00:00Z",
        body=body,
    )


class TestStaleApproval:
    def test_matching_commit_no_finding(self):
        pr = _make_pr(reviews=(_make_review(commit_id="aaa111"),))
        findings = analyze_pr(pr)
        assert not any(f.scar == "stale_approval" for f in findings)

    def test_different_commit_is_stale(self):
        pr = _make_pr(
            head_sha="bbb222",
            reviews=(_make_review(commit_id="aaa111"),),
        )
        findings = analyze_pr(pr)
        stale = [f for f in findings if f.scar == "stale_approval"]
        assert len(stale) == 1
        assert "bob" in stale[0].message

    def test_multiple_stale_approvals(self):
        pr = _make_pr(
            head_sha="ccc333",
            reviews=(
                _make_review(reviewer="bob", commit_id="aaa111"),
                _make_review(reviewer="carol", commit_id="bbb222"),
            ),
        )
        findings = analyze_pr(pr)
        stale = [f for f in findings if f.scar == "stale_approval"]
        assert len(stale) == 2


class TestNoApproval:
    def test_no_reviews_is_finding(self):
        pr = _make_pr()
        findings = analyze_pr(pr)
        assert any(f.scar == "no_approval" for f in findings)

    def test_only_comments_is_no_approval(self):
        pr = _make_pr(reviews=(_make_review(state="COMMENTED"),))
        findings = analyze_pr(pr)
        assert any(f.scar == "no_approval" for f in findings)

    def test_has_approval_no_finding(self):
        pr = _make_pr(reviews=(_make_review(),))
        findings = analyze_pr(pr)
        assert not any(f.scar == "no_approval" for f in findings)


class TestSelfMerge:
    def test_author_approves_own_pr(self):
        pr = _make_pr(
            author="alice",
            reviews=(_make_review(reviewer="alice"),),
        )
        findings = analyze_pr(pr)
        assert any(f.scar == "self_merge" for f in findings)

    def test_different_reviewer_no_finding(self):
        pr = _make_pr(
            author="alice",
            reviews=(_make_review(reviewer="bob"),),
        )
        findings = analyze_pr(pr)
        assert not any(f.scar == "self_merge" for f in findings)


class TestReviewTheater:
    def test_large_pr_no_comments(self):
        pr = _make_pr(
            additions=200,
            deletions=150,
            reviews=(_make_review(body=""),),
            review_comments=0,
        )
        findings = analyze_pr(pr)
        assert any(f.scar == "review_theater" for f in findings)

    def test_large_pr_with_comments_no_finding(self):
        pr = _make_pr(
            additions=200,
            deletions=150,
            reviews=(_make_review(body="Looks good, checked the auth flow"),),
            review_comments=3,
        )
        findings = analyze_pr(pr)
        assert not any(f.scar == "review_theater" for f in findings)

    def test_small_pr_no_finding(self):
        pr = _make_pr(
            additions=10,
            deletions=5,
            reviews=(_make_review(body=""),),
            review_comments=0,
        )
        findings = analyze_pr(pr)
        assert not any(f.scar == "review_theater" for f in findings)


class TestRiskMismatch:
    def test_critical_file_weak_review(self):
        tier_rules = {
            "critical": ["**/auth/**"],
            "structural": [],
            "standard": [],
            "low": ["*.md"],
        }
        pr = _make_pr(
            files=("src/auth/login.py",),
            reviews=(_make_review(),),
            review_comments=0,
        )
        findings = analyze_pr(pr, tier_rules)
        assert any(f.scar == "risk_mismatch" for f in findings)

    def test_low_risk_file_no_finding(self):
        tier_rules = {
            "critical": ["**/auth/**"],
            "structural": [],
            "standard": [],
            "low": ["*.md"],
        }
        pr = _make_pr(
            files=("README.md",),
            reviews=(_make_review(),),
            review_comments=0,
        )
        findings = analyze_pr(pr, tier_rules)
        assert not any(f.scar == "risk_mismatch" for f in findings)


class TestRiskTiers:
    def test_default_low_tier(self):
        assert assign_risk_tier("README.md") == "low"
        assert assign_risk_tier("CHANGELOG.md") == "low"
        assert assign_risk_tier("docs/guide.txt") == "low"

    def test_default_standard_tier(self):
        assert assign_risk_tier("src/foo.py") == "standard"
        assert assign_risk_tier("main.rs") == "standard"

    def test_custom_critical_tier(self):
        rules = {
            "critical": ["**/udf/**", "**/sink/**"],
            "structural": [],
            "standard": [],
            "low": ["*.md"],
        }
        assert assign_risk_tier("src/udf/base.py", rules) == "critical"
        assert assign_risk_tier("worker/sink/output.py", rules) == "critical"
        assert assign_risk_tier("src/labels.py", rules) == "standard"

    def test_highest_tier(self):
        rules = {
            "critical": ["**/auth/**"],
            "structural": [],
            "standard": [],
            "low": ["*.md"],
        }
        assert highest_tier(["README.md", "src/auth/login.py"], rules) == "critical"
        assert highest_tier(["README.md", "src/foo.py"], rules) == "standard"
        assert highest_tier(["README.md"], rules) == "low"


class TestReplayHistory:
    def test_aggregates_findings(self):
        prs = [
            _make_pr(number=1, head_sha="bbb222", reviews=(_make_review(commit_id="aaa111"),)),
            _make_pr(number=2, reviews=(_make_review(),)),
            _make_pr(number=3),  # no approval
        ]
        report = replay_history(prs, "test/repo")
        assert report.prs_analyzed == 3
        assert report.total_findings > 0
        assert "stale_approval" in report.findings_by_scar

    def test_path_prefix_aggregation(self):
        prs = [
            _make_pr(
                number=1,
                files=("osprey_worker/src/foo.py",),
            ),  # no approval finding
        ]
        report = replay_history(
            prs, "test/repo",
            path_prefixes=["osprey_worker/", "osprey_coordinator/"],
        )
        worker_zone = [z for z in report.zone_stats if z.prefix == "osprey_worker/"]
        assert len(worker_zone) == 1
        assert worker_zone[0].prs_touching == 1
        assert worker_zone[0].findings > 0

    def test_zone_stats_no_double_count_per_file(self):
        """A PR with 1 finding and 3 files in a zone should count as 1 finding, not 3."""
        pr = _make_pr(
            number=1,
            files=("src/a.py", "src/b.py", "src/c.py"),
            reviews=(_make_review(commit_id="different"),),  # stale
            head_sha="actual_head",
        )
        report = replay_history(
            [pr], "test/repo",
            path_prefixes=["src/"],
        )
        src_zone = [z for z in report.zone_stats if z.prefix == "src/"]
        assert src_zone[0].findings == 1  # one stale_approval, not 3
