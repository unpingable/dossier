# CLAUDE.md — Instructions for Claude Code

## What This Is

dossier: code review forensics — detect mechanical failures in review process (stale approvals, review theater, suppression pressure, risk mismatches).

## What This Is Not

- Not a code review UI or replacement for GitHub PR reviews
- Not semantic code analysis or a linter — that's SAST tools
- Not "AI code review" — this is forensics on the review process itself

## Invariants

1. If the diff changed after review, the approval is stale — no exceptions
2. Review grants expire (default 24h) — there are no permanent approvals
3. Receipt hashes are deterministic — same inputs always produce the same hash

## Quick Start

```bash
pip install -e ".[dev]"
python3 -m pytest tests/
dossier check --base main
```

## Project Structure

- `src/dossier/` — Core package: CLI, grant store, diff hashing, scar detection, suppression scanning, GitHub ingestion, batch analysis
- `tests/` — pytest suite (56 tests), no external service dependencies

## Conventions

- License: Apache-2.0
- Python >=3.10, type hints throughout, `from __future__ import annotations`
- Testing: pytest >=8.0, 60s timeout per test
- Entry point: `dossier` CLI via Click (`dossier.cli:main`)
- Data store: SQLite with WAL mode, stored in `.dossier/dossier.db`

## Don't

- Don't mock the grant store in tests — use real SQLite via `tmp_path`
- Don't add interactive prompts to the CLI — all commands should work non-interactively for CI use
- Don't treat scar detection as enforcement — v0.1 reports findings, it does not block merges
