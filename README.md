# dossier

Your PR was approved Tuesday. The code changed Wednesday. It shipped Thursday. The approval covered code that no longer exists.

This is the normal case. Most code review systems treat approval as a permanent stamp on a moving target. Dossier reconstructs what actually happened and shows you where the official story falls apart.

## The problem

Code review has mechanical failure modes that nobody tracks:

- **Stale approval** — code changes between review and merge, but the approval carries forward
- **Review theater** — 400-line PR, approved in 2 minutes, no comments
- **Risk mismatch** — auth module gets the same review as a README change
- **Self-merge** — only reviewer is the author
- **Suppression creep** — `# noqa`, `# type: ignore`, skipped tests accumulate quietly

These aren't edge cases. XZ Utils passed maintainer review. Log4Shell was merged with review. The review existed. The rigor didn't.

## What dossier does

Content-addresses every diff. Records review approvals as grants with scope, evidence, and TTL. When the diff changes, the grant is stale. When it expires, it must be renewed. Scans for suppression pressure. Replays GitHub PR history to find where review process has already failed.

```bash
pip install -e ".[dev]"
dossier init
dossier check --base main        # is the current diff covered?
dossier pressure --all            # where are suppressions accumulating?
dossier replay owner/repo         # how's the review record across merged PRs?
dossier batch repo1 repo2 ...    # compare repos side by side
```

## What this is not

- Not a code review UI — works alongside GitHub PRs, not instead of them
- Not semantic analysis — that's linters and SAST
- Not "AI code review" — this is forensics on the review process itself

## Scar catalog

Review scars the tool detects, drawn from real-world failure patterns:

| Scar | What's actually happening |
|---|---|
| `stale_approval` | Approval covers code that changed since review |
| `no_approval` | Merged with no approving review at all |
| `self_merge` | Only approval came from the PR author |
| `review_theater` | Large diff, fast approval, zero comments |
| `risk_mismatch` | Critical-tier files with lightweight review |
| `scope_gap` | Files in the diff not covered by any grant |

## CLI

```
dossier init                          Initialize .dossier/ in the repo
dossier check [--base main]          Check if current diff has valid approval
dossier approve --reviewer ID        Record a scoped review approval
dossier pressure [--all]             Scan for suppression pressure
dossier receipts                     Show recent review grant receipts
dossier replay owner/repo            Replay merged PR history for review forensics
dossier batch repo1 repo2 ...        Compare review quality across multiple repos
```

## Architecture

```
git pre-merge hook
       │
       ▼
  ┌──────────────┐     ┌──────────────┐
  │ dossier CLI  │────▶│  grant store │ (SQLite)
  │              │     │  scar scores │
  │  - check     │     │  receipts    │
  │  - approve   │     └──────────────┘
  │  - pressure  │
  │  - replay    │     ┌──────────────┐
  │  - batch     │────▶│  config      │ (TOML)
  └──────────────┘     │  risk tiers  │
                       │  thresholds  │
                       └──────────────┘
```

### Project layout

```
src/dossier/
  cli.py      Click CLI entry point
  check.py    Diff evaluation against grant store
  store.py    SQLite-backed grant store with TTL and receipts
  git.py      Git operations: diff hashing, file listing
  scan.py     Suppression pattern scanner
  ingest.py   GitHub PR history fetch and scar detection
  batch.py    Multi-repo comparative analysis
tests/
  test_*.py   pytest suite (56 tests)
```

## License

Licensed under Apache-2.0.
