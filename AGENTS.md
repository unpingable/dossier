# AGENTS.md — Working in this repo

This file is a **travel guide**, not a law.
If anything here conflicts with the user's explicit instructions, the user wins.

> Instruction files shape behavior; the user determines direction.

---

## Quick start

```bash
{{install command}}
{{run command}}
{{test command}}
```

## Tests

```bash
{{test command}}
```

Always run tests before proposing commits. Never claim tests pass without running them.

---

## Safety and irreversibility

### Do not do these without explicit user confirmation
- Push to remote, create/close PRs or issues
- Delete or rewrite git history
- Modify dependency files in ways that change the lock file
- {{Project-specific irreversible actions}}

### Preferred workflow
- Make changes in small, reviewable steps
- Run tests locally before proposing commits
- For any operation that affects external state, require explicit user confirmation

---

## Repository layout

```
{{directory tree with brief descriptions}}
```

---

## Coding conventions

- {{Language version, type hints, formatting}}
- {{Testing framework and approach}}
- {{Module/import conventions}}

---

## Invariants

{{Non-negotiable rules that must hold at all times. If these break, something
is wrong — not "could be improved," wrong.}}

1. {{Invariant 1}}
2. {{Invariant 2}}
3. {{Invariant 3}}

---

## What this is not

{{Scope boundaries. These prevent well-intentioned drift.}}

- {{Not a ...}}
- {{Not a ...}}
- {{Not a ...}}

---

## When you're unsure

Ask for clarification rather than guessing, especially around:
- {{Domain-specific ambiguity 1}}
- {{Domain-specific ambiguity 2}}
- Anything that changes a documented invariant

---

## Agent-specific instruction files

| Agent | File | Role |
|-------|------|------|
| Claude Code | `CLAUDE.md` | Full operational context, build details, conventions |
| Codex | `AGENTS.md` (this file) | Operating context + defaults |
| Any future agent | `AGENTS.md` (this file) | Start here |
