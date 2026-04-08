# SPDX-License-Identifier: Apache-2.0
"""CLI for dossier: code review forensics."""

from __future__ import annotations

import json
from pathlib import Path

import click

DOSSIER_DIR = ".dossier"


def _ensure_init() -> Path:
    dossier_dir = Path(DOSSIER_DIR)
    if not dossier_dir.exists():
        raise click.ClickException(
            "Not initialized. Run 'dossier init' first."
        )
    return dossier_dir


def _get_store():
    from dossier.store import GrantStore
    dossier_dir = _ensure_init()
    return GrantStore(dossier_dir / "dossier.db")


@click.group()
def main():
    """dossier: code review forensics — detect mechanical failures in review process."""
    pass


@main.command()
def init():
    """Initialize .dossier/ in the current repository."""
    dossier_dir = Path(DOSSIER_DIR)
    if dossier_dir.exists():
        click.echo("Already initialized.")
        return

    dossier_dir.mkdir()
    (dossier_dir / ".gitignore").write_text("dossier.db\ndossier.db-wal\ndossier.db-shm\n")

    # Initialize the store (creates tables)
    from dossier.store import GrantStore
    store = GrantStore(dossier_dir / "dossier.db")
    store.close()

    click.echo(f"Initialized {dossier_dir}/")
    click.echo("")
    click.echo("Next:")
    click.echo("  dossier check          Check current branch")
    click.echo("  dossier approve        Record a review approval")
    click.echo("  dossier pressure       Scan for suppression pressure")


@main.command()
@click.option("--base", default="main", help="Base branch to diff against")
@click.option("--require", is_flag=True, help="Fail if no approval exists")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def check(base: str, require: bool, as_json: bool):
    """Check if the current diff has valid review approval."""
    from dossier.git import snapshot_diff
    from dossier.check import check_diff

    store = _get_store()
    try:
        snapshot = snapshot_diff(base_ref=base)
        result = check_diff(snapshot, store, require_approval=require)
    finally:
        store.close()

    if as_json:
        click.echo(json.dumps({
            "diff_hash": result.diff_hash,
            "head_ref": result.head_ref,
            "clean": result.clean,
            "grants_active": result.grants_active,
            "grants_stale": result.grants_stale,
            "findings": [
                {"scar": f.scar, "severity": f.severity, "message": f.message, "detail": f.detail}
                for f in result.findings
            ],
        }, indent=2))
        return

    # Text output
    if result.clean and not result.findings:
        click.echo(f"PASS  diff={snapshot.short_hash}  {result.grants_active} active grant(s)")
        return

    for f in result.findings:
        color = {"error": "red", "warn": "yellow", "info": "blue"}.get(f.severity, "white")
        click.secho(f"  [{f.severity:5s}] {f.scar}: {f.message}", fg=color)
        if f.detail.get("uncovered_files"):
            for uf in f.detail["uncovered_files"]:
                click.echo(f"          {uf}")

    if result.errors:
        click.echo("")
        click.secho(f"BLOCK  {len(result.errors)} error(s), {len(result.warnings)} warning(s)", fg="red")
    elif result.warnings:
        click.echo("")
        click.secho(f"WARN   {len(result.warnings)} warning(s)", fg="yellow")


@main.command()
@click.option("--base", default="main", help="Base branch to diff against")
@click.option("--reviewer", required=True, help="Reviewer ID (e.g., 'jbeck')")
@click.option("--label", default=None, help="Reviewer display name")
@click.option("--scope", multiple=True, help="File patterns covered (default: all changed files)")
@click.option("--ttl", default=24.0, help="Hours until expiry (default: 24)")
@click.option("--evidence", default=None, help="Evidence JSON string")
def approve(base: str, reviewer: str, label: str | None, scope: tuple[str, ...], ttl: float, evidence: str | None):
    """Record a scoped review approval for the current diff."""
    from dossier.git import snapshot_diff

    store = _get_store()
    try:
        snapshot = snapshot_diff(base_ref=base)

        files = list(snapshot.files_changed)
        scope_list = list(scope) if scope else files
        evidence_dict = json.loads(evidence) if evidence else {"method": "manual_review"}

        grant = store.create_grant(
            diff_hash=snapshot.diff_hash,
            head_ref=snapshot.head_ref,
            base_ref=base,
            reviewer_id=reviewer,
            reviewer_label=label or reviewer,
            scope=scope_list,
            files_reviewed=files,
            evidence=evidence_dict,
            ttl_hours=ttl,
        )
    finally:
        store.close()

    click.echo(f"Approved  grant={grant.grant_id}  diff={snapshot.short_hash}")
    click.echo(f"  reviewer: {grant.reviewer_label}")
    click.echo(f"  files:    {len(files)}")
    click.echo(f"  expires:  {grant.expires_at[:19]}")
    click.echo(f"  receipt:  {grant.receipt_hash[:16]}")


@main.command()
@click.option("--base", default="main", help="Base branch to diff against")
@click.option("--all", "scan_all", is_flag=True, help="Scan all files, not just changed")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def pressure(base: str, scan_all: bool, as_json: bool):
    """Scan for suppression pressure (lint ignores, TODOs, skipped tests)."""
    from dossier.git import changed_files, current_head
    from dossier.scan import scan_directory

    root = Path(".")
    files = None if scan_all else changed_files(base_ref=base)

    findings = scan_directory(root, files=files)

    if as_json:
        click.echo(json.dumps([f.to_dict() for f in findings], indent=2))
        return

    if not findings:
        click.echo("No suppressions found.")
        return

    # Group by file
    by_file: dict[str, list] = {}
    for f in findings:
        by_file.setdefault(f.file_path, []).append(f)

    click.echo(f"Suppression pressure ({len(findings)} findings in {len(by_file)} files):\n")
    for fp, ff in sorted(by_file.items(), key=lambda x: -len(x[1])):
        click.echo(f"  {fp}  ({len(ff)} suppressions)")
        # Group by pattern
        patterns: dict[str, int] = {}
        for f in ff:
            patterns[f.pattern] = patterns.get(f.pattern, 0) + 1
        for p, c in sorted(patterns.items(), key=lambda x: -x[1]):
            click.echo(f"    {p}: {c}")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def receipts(as_json: bool):
    """Show recent review grant receipts."""
    store = _get_store()
    try:
        grants = store.get_all_grants(limit=20)
    finally:
        store.close()

    if as_json:
        click.echo(json.dumps([
            {
                "grant_id": g.grant_id,
                "diff_hash": g.diff_hash[:16],
                "reviewer": g.reviewer_label,
                "created_at": g.created_at[:19],
                "expires_at": g.expires_at[:19],
                "active": g.is_active,
                "files": len(g.files_reviewed),
                "receipt_hash": g.receipt_hash[:16],
            }
            for g in grants
        ], indent=2))
        return

    if not grants:
        click.echo("No grants recorded.")
        return

    click.echo("Recent review grants:\n")
    for g in grants:
        status = "ACTIVE" if g.is_active else "EXPIRED" if g.is_expired else "REVOKED"
        color = "green" if g.is_active else "red"
        click.secho(
            f"  {g.grant_id}  {status:8s}  {g.reviewer_label:<16s}  "
            f"diff={g.diff_hash[:12]}  files={len(g.files_reviewed)}  "
            f"receipt={g.receipt_hash[:12]}",
            fg=color,
        )


@main.command()
@click.argument("owner_repo")
@click.option("--limit", default=100, help="Max PRs to fetch (default: 100)")
@click.option("--tier", multiple=True, help="Risk tier rule: 'critical:pattern1,pattern2'")
@click.option("--prefix", multiple=True, help="Path prefixes to aggregate by")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def replay(owner_repo: str, limit: int, tier: tuple[str, ...], prefix: tuple[str, ...], as_json: bool):
    """Replay merged PR history for review forensics.

    Fetches recent merged PRs from OWNER_REPO (e.g. roostorg/osprey)
    and detects review scars: stale approvals, review theater,
    self-merges, risk mismatches.

    \b
    Examples:
      dossier replay roostorg/osprey --limit 50
      dossier replay roostorg/osprey --tier "critical:**/auth/**,**/crypto/**"
      dossier replay roostorg/osprey --prefix osprey_worker/ --prefix osprey_coordinator/
    """
    from dossier.ingest import fetch_merged_prs, replay_history

    # Parse tier rules
    tier_rules = None
    if tier:
        from dossier.ingest import DEFAULT_TIER_RULES
        tier_rules = dict(DEFAULT_TIER_RULES)
        for t in tier:
            name, _, patterns = t.partition(":")
            if name in tier_rules:
                tier_rules[name] = [p.strip() for p in patterns.split(",")]

    path_prefixes = list(prefix) if prefix else None

    click.echo(f"Fetching up to {limit} merged PRs from {owner_repo}...")
    prs = fetch_merged_prs(owner_repo, limit=limit)
    click.echo(f"Fetched {len(prs)} merged PRs. Scanning for scars...")

    report = replay_history(prs, owner_repo, tier_rules, path_prefixes)

    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2))
        return

    # Text output
    click.echo("")
    click.echo(f"=== Dossier: {owner_repo} ===")
    click.echo(f"PRs analyzed: {report.prs_analyzed}")
    click.echo(f"Total findings: {report.total_findings}")
    click.echo("")

    if report.findings_by_scar:
        click.echo("Findings by scar:")
        for scar, count in sorted(report.findings_by_scar.items(), key=lambda x: -x[1]):
            click.echo(f"  {scar:<20s} {count}")
        click.echo("")

    if report.findings_by_tier:
        click.echo("Findings by risk tier:")
        for t in ("critical", "structural", "standard", "low"):
            if t in report.findings_by_tier:
                click.echo(f"  {t:<14s} {report.findings_by_tier[t]}")
        click.echo("")

    if report.zone_stats:
        click.echo("Zone breakdown (sorted by scar rate):")
        click.echo(f"  {'zone':<50s} {'PRs':>4s} {'scarred':>7s} {'findings':>8s} {'rate':>6s}")
        click.echo(f"  {'─'*50} {'─'*4} {'─'*7} {'─'*8} {'─'*6}")
        for z in report.zone_stats:
            click.echo(
                f"  {z.prefix:<50s} {z.prs_touching:>4d} {z.prs_with_findings:>7d}"
                f" {z.findings:>8d} {z.scar_rate:>5.2f}"
            )
        click.echo("")
        click.echo("  (A PR touching multiple zones is counted in each. Scar rate = findings / PRs touching zone.)")
        click.echo("")

    if report.weakest_prs:
        click.echo("Most scarred PRs:")
        for entry in report.weakest_prs[:10]:
            click.secho(
                f"  #{entry['pr']:<6d} {entry['findings']} finding(s)  {entry['title'][:60]}",
                fg="red" if entry["findings"] >= 3 else "yellow",
            )
        click.echo("")

    # Per-finding detail
    if report.all_findings:
        click.echo("All findings:")
        for f in report.all_findings:
            color = {"error": "red", "warn": "yellow", "info": "blue"}.get(f.severity, "white")
            click.secho(f"  #{f.pr_number:<6d} [{f.severity:5s}] {f.scar}: {f.message}", fg=color)


@main.command()
@click.argument("repos", nargs=-1, required=True)
@click.option("--limit", default=100, help="Max PRs per repo (default: 100)")
@click.option("--category", multiple=True, help="Category per repo: 'owner/repo:category' (own, case_study, control, velocity, peer)")
@click.option("--prefix", multiple=True, help="Zone prefix for all repos: 'owner/repo:prefix/path/'")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def batch(repos: tuple[str, ...], limit: int, category: tuple[str, ...], prefix: tuple[str, ...], as_json: bool):
    """Run replay across multiple repos for comparison.

    Each REPO is an owner/repo string (e.g. roostorg/osprey caddyserver/caddy).

    \b
    Examples:
      dossier batch roostorg/osprey caddyserver/caddy sharkdp/fd --limit 50
      dossier batch roostorg/osprey --category "roostorg/osprey:case_study"
      dossier batch my/repo --category "my/repo:own"
    """
    from dossier.batch import RepoSpec, run_batch

    # Parse categories
    cat_map: dict[str, str] = {}
    for c in category:
        repo_name, _, cat = c.partition(":")
        if cat:
            cat_map[repo_name] = cat

    # Parse prefixes
    prefix_map: dict[str, list[str]] = {}
    for p in prefix:
        repo_name, _, ppath = p.partition(":")
        if ppath:
            prefix_map.setdefault(repo_name, []).append(ppath)

    specs = [
        RepoSpec(
            owner_repo=r,
            prefixes=prefix_map.get(r, []),
            category=cat_map.get(r, "control"),
        )
        for r in repos
    ]

    summary = run_batch(specs, limit=limit)

    if as_json:
        click.echo(json.dumps(summary.to_dict(), indent=2))
        return

    # Comparative table
    table = summary.comparative_table()

    click.echo("")
    click.echo(f"=== Dossier Batch: {len(summary.successful)} repos, {limit} PRs each ===")
    click.echo("")

    # Header
    click.echo(
        f"  {'repo':<35s} {'cat':<12s} {'PRs':>4s} "
        f"{'scars':>5s} {'rate':>5s} "
        f"{'stale':>5s} {'r.mis':>5s} {'no_ap':>5s} {'self':>5s} {'thtr':>5s}"
    )
    click.echo(f"  {'─'*35} {'─'*12} {'─'*4} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*5}")

    for row in sorted(table, key=lambda r: -r["scar_rate"]):
        if row.get("error"):
            click.secho(f"  {row['repo']:<35s} {'ERROR':<12s} {row['error']}", fg="red")
            continue
        click.echo(
            f"  {row['repo']:<35s} {row['category']:<12s} {row['prs']:>4d} "
            f"{row['findings']:>5d} {row['scar_rate']:>5.2f} "
            f"{row['stale_approval_rate']:>5.2f} {row['risk_mismatch_rate']:>5.2f} "
            f"{row['no_approval_rate']:>5.2f} {row['self_merge_rate']:>5.2f} "
            f"{row['review_theater_rate']:>5.2f}"
        )

    click.echo("")
    click.echo("  Columns: scars=total findings, rate=findings/PR, stale=stale_approval/PR,")
    click.echo("  r.mis=risk_mismatch/PR, no_ap=no_approval/PR, self=self_merge/PR, thtr=review_theater/PR")

    if summary.errors:
        click.echo("")
        click.echo("Errors:")
        for repo, err in summary.errors.items():
            click.secho(f"  {repo}: {err}", fg="red")

    # Per-repo zone breakdown if any have zones
    for spec in specs:
        report = summary.reports.get(spec.owner_repo)
        if report and report.zone_stats:
            click.echo("")
            click.echo(f"  Zone breakdown: {spec.owner_repo}")
            click.echo(f"    {'zone':<45s} {'PRs':>4s} {'scarred':>7s} {'findings':>8s} {'rate':>6s}")
            click.echo(f"    {'─'*45} {'─'*4} {'─'*7} {'─'*8} {'─'*6}")
            for z in report.zone_stats:
                click.echo(
                    f"    {z.prefix:<45s} {z.prs_touching:>4d} {z.prs_with_findings:>7d}"
                    f" {z.findings:>8d} {z.scar_rate:>5.2f}"
                )
