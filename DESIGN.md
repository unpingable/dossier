# dossier: code review forensics

**Status:** Design spike
**Date:** 2026-04-08

## One-line pitch

Code review is a forensics problem pretending to be a reading comprehension problem.

## Problem

Code review as practiced has failure modes that map directly onto the
cybernetic failure taxonomy:

| Failure | Δ-domain | What happens |
|---|---|---|
| Approval outlives the code it reviewed | **Δt** | Code changes between review and merge (TOCTOU) |
| "LGTM" is a bearer token | **Δw** | Anyone who can push the merge button holds the grant |
| Review intensity doesn't match risk | **Δg** | README gets same scrutiny as auth module |
| Lint suppressions accumulate | **Δh** | "Temporary" exceptions normalize |
| Copy-paste patterns propagate | **Δr** | One bad pattern feeds on its own output |
| Wrong review boundary | **Δb** | File-by-file review misses cross-file interaction risk |
| Can't name the anti-pattern | **Δn** | Team lacks vocabulary for what's wrong |
| Reviewer fatigue under pressure | **Δe** | Knows what to look for, lacks energy to look |

These aren't exotic. They're the base rate. XZ Utils passed maintainer
review. Log4Shell was merged with review. SolarWinds passed CI.

## Thesis

Apply three things from the Governor/standing ecosystem:

1. **Scar catalog methodology** (from standing) — enumerate known failure
   modes from real systems, score against each, derive invariants
2. **Receipt-producing custody** (from Governor) — review approvals are
   short-lived scoped grants with evidence, not immortal rubber stamps
3. **Δt enforcement** (from the paper series) — commitment cannot precede
   verification; if the code changed after review, the approval is stale

## Core concepts

### Review as a grant

A code review approval is a **short-lived, scoped, evidence-bearing grant**:

- **Subject**: the specific diff (content-addressed)
- **Scope**: which files/modules the reviewer is qualified to assess
- **TTL**: approval expires (configurable, default 24h or on force-push)
- **Evidence**: what the reviewer actually checked (not just "LGTM")
- **Principal**: who reviewed (verified identity, not just GitHub username)

When the diff changes after approval, the grant is stale. When the
approval expires, it must be renewed or the merge is blocked.

### Δt at the merge boundary

The merge is the commitment boundary. Δt = T_merge - (T_review + T_staleness_check).

If the code hash at merge time differs from the code hash at review time,
Δt > 0 and the approval is invalid. This is a mechanical check, not a
judgment call.

### Risk-proportional review (Δg calibration)

Not all files deserve equal scrutiny. Risk classification:

| Risk tier | Examples | Review requirements |
|---|---|---|
| **Critical** | auth, crypto, permissions, secrets handling | Domain expert + evidence |
| **Structural** | API surface, schema migrations, config | Architectural review |
| **Standard** | Business logic, features | Normal review |
| **Low** | Docs, comments, formatting | Automated or lightweight |

File → tier mapping is configurable. The tool enforces that critical files
get critical review, not that everything gets the same rubber stamp.

### Suppression pressure (Δw tracking)

Track lint/type/safety suppressions per file over time:

- `# type: ignore` / `# noqa` / `@SuppressWarnings` / `// eslint-disable`
- `TODO` / `FIXME` / `HACK` density
- Test skip markers (`@pytest.mark.skip`, `xit()`, etc.)

These are overrides. When they accumulate, the file is under suppression
pressure. Same concept as Governor's override accumulation signal.

### Code scar catalog

Enumerate known code-custody failure modes, score the codebase against each:

| Scar | What | Detection |
|---|---|---|
| 1. Stale approval | Diff changed since review | Content-address diff at review time, compare at merge |
| 2. Scope creep | PR grew after initial approval | Track diff size at approval vs at merge |
| 3. Bearer approval | Approval not bound to reviewer identity | Verify reviewer principal, not just username |
| 4. Review theater | Large PR, fast approval, no comments | Time-to-approve vs diff size ratio |
| 5. Self-merge | Author and merger are same principal | Principal comparison |
| 6. Suppression debt | Accumulated lint/type suppressions | Pattern scan + density tracking |
| 7. Copy-paste spread | Duplicated code blocks propagating | Similarity detection across PRs |
| 8. Risk mismatch | Critical file, lightweight review | File risk tier vs review depth |
| 9. Ghost approval | Reviewer no longer has access/employment | Principal standing verification |
| 10. Partial review | Only some files in PR were examined | Per-file review evidence |
| 11. CI-only review | No human review, only automated checks | Distinguish CI pass from human approval |
| 12. Rebase amnesia | Force-push after approval invalidated review | Detect push events between approval and merge |

## Architecture

```
git pre-merge hook
       │
       ▼
  ┌─────────────┐     ┌──────────────┐
  │ dossier CLI │────▶│  grant store │ (SQLite)
  │             │     │  scar scores │
  │  - check    │     │  receipts    │
  │  - approve  │     └──────────────┘
  │  - score    │
  │  - scars    │     ┌──────────────┐
  │  - pressure │────▶│  config      │ (TOML)
  └─────────────┘     │  risk tiers  │
                      │  thresholds  │
                      └──────────────┘
```

### CLI surface (sketch)

```bash
dossier init                          # Initialize .dossier/ in repo
dossier check                         # Check current PR/branch against policy
dossier approve [--scope files...]    # Record a scoped review approval
dossier score                         # Score codebase against scar catalog
dossier scars                         # Show scar catalog with current scores
dossier pressure                      # Show suppression pressure by file/module
dossier receipts                      # Show review grant receipts
dossier config                        # Show/edit risk tiers and thresholds
```

### Integration points

- **Git pre-merge hook**: block merge if approval is stale/missing/insufficient
- **GitHub Actions**: `dossier check` as CI step
- **Governor**: dossier receipts feed into Governor's evidence pipeline
- **Standing**: reviewer identity verified via standing tokens (optional)

## Non-goals

- Not replacing GitHub PR review UI
- Not doing semantic code analysis (that's linters/SAST)
- Not scoring "code quality" (that's subjective and tools already exist)
- Not managing reviewer assignment (that's a workflow problem)

The tool answers: **was this code change reviewed with sufficient standing,
evidence, scope, and freshness to be admissible for merge?**

## MVP

1. Content-addressed diff hashing (detect stale approvals)
2. File risk tiers (configurable)
3. Suppression pressure scanning
4. Review grant store (SQLite, scoped, TTL)
5. `dossier check` as pre-merge gate
6. Scar catalog scoring

## What this is not

This is not "AI code review." It's the forensic infrastructure that makes
review failures visible instead of decorative.
