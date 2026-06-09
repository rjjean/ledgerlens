---
type: plan
status: active
phase: 0
updated: 2026-06-09
related: ["[[index]]", "[[handoff]]", "[[PHASE_0_BUILD]]"]
---

# Getting Started

The repo starts as a **docs-only** vault. The code does not exist yet — Cursor
builds it, starting with Phase 0. Primary environment: **Cursor + Composer**, with
the same folder open as an **Obsidian vault** for navigation.

## 1. Create the repo
Create a new GitHub repo `ledgerlens` (private to start) and commit this starter:
the docs (`index.md`, `README.md`, `handoff.md`, `Ledgerlens_System_Design_FINAL.md`,
`docs/`), the Cursor rules (`.cursor/rules/`), `.cursorignore`, and `.gitignore`.
No Python yet.

## 2. Open it two ways
- **Cursor (primary):** File -> Open Folder -> the repo root. It loads
  `.cursor/rules/*.mdc` automatically; `/rules` in Composer confirms `00-project`
  is always-active.
- **Obsidian (navigation):** Open folder as vault -> the same repo root.
  `[[index]]` is your home.

## 3. Build Phase 0 with Composer
In Composer (Agent mode), with `docs/PHASE_0_BUILD.md` in context (@-mention it):
> "Build Phase 0 per docs/PHASE_0_BUILD.md and Ledgerlens_System_Design_FINAL.md."
Review the diffs before accepting. It should create `pyproject.toml`, the
`ledgerlens/` package (config + the three interface seams + factory + placeholder
subpackages), `scripts/`, `tests/`, ADR-0001, and flesh out `README.md`.

## 4. Prove Phase 0 works
    python -m venv .venv && source .venv/bin/activate   # Python 3.12
    pip install -e .
    cp .env.example .env                                 # defaults to fake backends
    python scripts/smoke_test.py    # expect: "Phase 0 plumbing is GREEN"
    pytest                          # expect: all pass
Then update `handoff.md` and tick the Phase 0 box in `BUILD_PLAN.md`.

## 5. Accounts (needed by Phase 2/4, not Phase 1)
- Neon project -> connection string into `.env` -> `pip install -e '.[storage]'` -> `python scripts/check_pgvector.py`.
- Anthropic key + a monthly spend cap set *before* any paid call.
- Voyage key (50M tokens free).

## Working in Cursor + Composer
- **Rules load by context.** `00-project` is always in the prompt; the Python and
  docs rules attach by file type. Pull any rule in manually by @-mentioning it.
- **@-mention the doc you're working from** (`@PHASE_0_BUILD.md`, `@handoff.md`) so
  its content — not just a pointer — is in the model's context.
- **Composer / Agent for multi-file work; plain Chat for a quick question.** Review
  Agent diffs before accepting.
- **Edits are shared on disk** with Obsidian — no sync step.

## Read order for a new session
[[index]] -> [[handoff]] -> [[PHASE_0_BUILD]] (until Phase 0 is done) ->
[[Ledgerlens_System_Design_FINAL]] -> [[BUILD_PLAN]].

## The daily loop
1. Read [[handoff]] for current state (`@handoff.md` in Composer).
2. Work the current phase (deps come online per phase: `pip install -e '.[<phase>]'`).
3. Run the smoke test + `pytest` before calling anything done.
4. Update [[handoff]] and tick [[BUILD_PLAN]] boxes.
5. Commit with a clear message; push.
