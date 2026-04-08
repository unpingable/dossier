# SPDX-License-Identifier: Apache-2.0
"""Grant store: SQLite-backed review approval grants with TTL and scope."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA = """\
CREATE TABLE IF NOT EXISTS grants (
    grant_id        TEXT PRIMARY KEY,
    diff_hash       TEXT NOT NULL,
    head_ref        TEXT NOT NULL,
    base_ref        TEXT NOT NULL,
    reviewer_id     TEXT NOT NULL,
    reviewer_label  TEXT NOT NULL,
    scope           TEXT NOT NULL,       -- JSON list of file patterns
    files_reviewed  TEXT NOT NULL,        -- JSON list of actual files
    evidence        TEXT NOT NULL,        -- JSON: what was checked
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    revoked         INTEGER NOT NULL DEFAULT 0,
    revoked_at      TEXT,
    revoked_reason  TEXT,
    receipt_hash    TEXT NOT NULL         -- content-addressed receipt
);

CREATE TABLE IF NOT EXISTS suppressions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path       TEXT NOT NULL,
    pattern         TEXT NOT NULL,        -- e.g. "type: ignore", "noqa"
    line_number     INTEGER,
    generation      INTEGER NOT NULL,     -- scan generation for trending
    scanned_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_generations (
    generation      INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at      TEXT NOT NULL,
    head_ref        TEXT NOT NULL,
    files_scanned   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_grants_diff ON grants(diff_hash);
CREATE INDEX IF NOT EXISTS idx_grants_reviewer ON grants(reviewer_id);
CREATE INDEX IF NOT EXISTS idx_suppressions_file ON suppressions(file_path);
CREATE INDEX IF NOT EXISTS idx_suppressions_gen ON suppressions(generation);
"""


@dataclass(frozen=True)
class ReviewGrant:
    """A scoped, time-limited review approval."""

    grant_id: str
    diff_hash: str
    head_ref: str
    base_ref: str
    reviewer_id: str
    reviewer_label: str
    scope: list[str]
    files_reviewed: list[str]
    evidence: dict[str, Any]
    created_at: str
    expires_at: str
    revoked: bool = False
    revoked_at: str | None = None
    revoked_reason: str | None = None
    receipt_hash: str = ""

    @property
    def is_expired(self) -> bool:
        if self.revoked:
            return True
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > exp
        except (ValueError, TypeError):
            return True

    @property
    def is_active(self) -> bool:
        return not self.is_expired and not self.revoked


def _compute_receipt_hash(
    diff_hash: str, reviewer_id: str, scope: list[str],
    files_reviewed: list[str], evidence: dict[str, Any],
    created_at: str, expires_at: str,
) -> str:
    """Content-addressed receipt: same inputs → same hash."""
    payload = json.dumps({
        "diff_hash": diff_hash,
        "reviewer_id": reviewer_id,
        "scope": sorted(scope),
        "files_reviewed": sorted(files_reviewed),
        "evidence": evidence,
        "created_at": created_at,
        "expires_at": expires_at,
    }, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


class GrantStore:
    """SQLite-backed store for review grants and suppression tracking."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def close(self):
        self._conn.close()

    def create_grant(
        self,
        diff_hash: str,
        head_ref: str,
        base_ref: str,
        reviewer_id: str,
        reviewer_label: str,
        scope: list[str],
        files_reviewed: list[str],
        evidence: dict[str, Any] | None = None,
        ttl_hours: float = 24.0,
    ) -> ReviewGrant:
        """Create a new review grant."""
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        expires_at = (now + timedelta(hours=ttl_hours)).isoformat()
        evidence = evidence or {}
        grant_id = uuid.uuid4().hex[:12]

        receipt_hash = _compute_receipt_hash(
            diff_hash, reviewer_id, scope,
            files_reviewed, evidence, created_at, expires_at,
        )

        grant = ReviewGrant(
            grant_id=grant_id,
            diff_hash=diff_hash,
            head_ref=head_ref,
            base_ref=base_ref,
            reviewer_id=reviewer_id,
            reviewer_label=reviewer_label,
            scope=scope,
            files_reviewed=files_reviewed,
            evidence=evidence,
            created_at=created_at,
            expires_at=expires_at,
            receipt_hash=receipt_hash,
        )

        self._conn.execute(
            """INSERT INTO grants
               (grant_id, diff_hash, head_ref, base_ref, reviewer_id, reviewer_label,
                scope, files_reviewed, evidence, created_at, expires_at, receipt_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                grant.grant_id, grant.diff_hash, grant.head_ref, grant.base_ref,
                grant.reviewer_id, grant.reviewer_label,
                json.dumps(grant.scope), json.dumps(grant.files_reviewed),
                json.dumps(grant.evidence), grant.created_at, grant.expires_at,
                grant.receipt_hash,
            ),
        )
        self._conn.commit()
        return grant

    def get_active_grants(self, diff_hash: str) -> list[ReviewGrant]:
        """Get all active (non-expired, non-revoked) grants for a diff."""
        rows = self._conn.execute(
            "SELECT * FROM grants WHERE diff_hash = ? AND revoked = 0",
            (diff_hash,),
        ).fetchall()

        grants = [self._row_to_grant(r) for r in rows]
        return [g for g in grants if g.is_active]

    def get_all_grants(self, limit: int = 50) -> list[ReviewGrant]:
        """Get recent grants."""
        rows = self._conn.execute(
            "SELECT * FROM grants ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_grant(r) for r in rows]

    def revoke_grant(self, grant_id: str, reason: str) -> bool:
        """Revoke a grant. Returns True if found."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "UPDATE grants SET revoked = 1, revoked_at = ?, revoked_reason = ? WHERE grant_id = ?",
            (now, reason, grant_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def _row_to_grant(self, row: sqlite3.Row) -> ReviewGrant:
        return ReviewGrant(
            grant_id=row["grant_id"],
            diff_hash=row["diff_hash"],
            head_ref=row["head_ref"],
            base_ref=row["base_ref"],
            reviewer_id=row["reviewer_id"],
            reviewer_label=row["reviewer_label"],
            scope=json.loads(row["scope"]),
            files_reviewed=json.loads(row["files_reviewed"]),
            evidence=json.loads(row["evidence"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            revoked=bool(row["revoked"]),
            revoked_at=row["revoked_at"],
            revoked_reason=row["revoked_reason"],
            receipt_hash=row["receipt_hash"],
        )

    # ------------------------------------------------------------------
    # Suppression tracking
    # ------------------------------------------------------------------

    def record_suppressions(
        self,
        findings: list[dict[str, Any]],
        head_ref: str,
    ) -> int:
        """Record suppression findings for a new scan generation."""
        now = datetime.now(timezone.utc).isoformat()
        files_scanned = len({f["file_path"] for f in findings})

        cursor = self._conn.execute(
            "INSERT INTO scan_generations (scanned_at, head_ref, files_scanned) VALUES (?, ?, ?)",
            (now, head_ref, files_scanned),
        )
        gen = cursor.lastrowid

        for f in findings:
            self._conn.execute(
                "INSERT INTO suppressions (file_path, pattern, line_number, generation, scanned_at) VALUES (?, ?, ?, ?, ?)",
                (f["file_path"], f["pattern"], f.get("line_number"), gen, now),
            )
        self._conn.commit()
        return gen

    def suppression_pressure(self, generation: int | None = None) -> list[dict[str, Any]]:
        """Get suppression counts by file for a generation (default: latest)."""
        if generation is None:
            row = self._conn.execute(
                "SELECT MAX(generation) as gen FROM scan_generations"
            ).fetchone()
            generation = row["gen"] if row and row["gen"] else 0

        rows = self._conn.execute(
            """SELECT file_path, pattern, COUNT(*) as count
               FROM suppressions WHERE generation = ?
               GROUP BY file_path, pattern
               ORDER BY count DESC""",
            (generation,),
        ).fetchall()

        return [{"file_path": r["file_path"], "pattern": r["pattern"], "count": r["count"]} for r in rows]
