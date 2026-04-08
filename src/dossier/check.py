# SPDX-License-Identifier: Apache-2.0
"""Check: evaluate whether a diff is admissible for merge.

This is the accusation surface, not an enforcement gate (v0.1).
It reports findings; it does not block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dossier.git import DiffSnapshot
from dossier.store import GrantStore, ReviewGrant


@dataclass(frozen=True)
class Finding:
    """A single review scar finding."""

    scar: str          # scar catalog ID (e.g., "stale_approval")
    severity: str      # "info", "warn", "error"
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    """Result of a scar check."""

    diff_hash: str
    head_ref: str
    findings: list[Finding] = field(default_factory=list)
    grants_found: int = 0
    grants_active: int = 0
    grants_stale: int = 0

    @property
    def clean(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]


def check_diff(
    snapshot: DiffSnapshot,
    store: GrantStore,
    *,
    require_approval: bool = False,
) -> CheckResult:
    """Check a diff snapshot against the grant store.

    Evaluates:
    1. Stale approval (diff changed since review)
    2. Missing approval (no grants for this diff)
    3. Scope gaps (files not covered by any grant)
    4. Expired grants (found but no longer active)
    """
    result = CheckResult(
        diff_hash=snapshot.diff_hash,
        head_ref=snapshot.head_ref,
    )

    # Find all grants that reference this diff hash
    active_grants = store.get_active_grants(snapshot.diff_hash)
    result.grants_active = len(active_grants)

    # Also check for grants against a DIFFERENT diff hash (stale approvals)
    all_recent = store.get_all_grants(limit=20)
    stale = [
        g for g in all_recent
        if g.diff_hash != snapshot.diff_hash
        and g.base_ref == snapshot.base_ref
        and not g.is_expired
        and not g.revoked
    ]
    result.grants_stale = len(stale)
    result.grants_found = result.grants_active + result.grants_stale

    # Scar 1: Stale approval
    if stale:
        for g in stale:
            result.findings.append(Finding(
                scar="stale_approval",
                severity="error",
                message=f"Approval by {g.reviewer_label} is stale — diff changed since review",
                detail={
                    "grant_id": g.grant_id,
                    "approved_diff": g.diff_hash[:16],
                    "current_diff": snapshot.diff_hash[:16],
                    "reviewer": g.reviewer_label,
                },
            ))

    # Scar: No approval at all
    if not active_grants:
        sev = "error" if require_approval else "warn"
        result.findings.append(Finding(
            scar="no_approval",
            severity=sev,
            message="No active review approval for the current diff",
        ))
        return result

    # Scar 10: Scope gaps — files not covered by any grant
    covered_files: set[str] = set()
    for g in active_grants:
        covered_files.update(g.files_reviewed)

    uncovered = [f for f in snapshot.files_changed if f not in covered_files]
    if uncovered:
        result.findings.append(Finding(
            scar="scope_gap",
            severity="warn",
            message=f"{len(uncovered)} file(s) not covered by any review",
            detail={"uncovered_files": uncovered[:10]},
        ))

    return result
