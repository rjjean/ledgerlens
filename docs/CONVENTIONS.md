---
type: plan
status: active
phase: 0
updated: 2026-06-09
related: ["[[index]]", "[[GETTING_STARTED]]", "[[PHASE_0_BUILD]]"]
---

# Conventions

How this vault/repo is organized and maintained, so the human view (Obsidian),
the code (GitHub), and the AI (Cursor + Composer) stay in sync.

## Target folder structure
This is the layout the project builds toward. **At repo init only the docs/config
layer exists; Phase 0 creates the package, scripts, tests, and `pyproject.toml`**
(see `docs/PHASE_0_BUILD.md`). Items marked (P0) are produced during Phase 0.

    ledgerlens/                              # repo root = Obsidian vault = Cursor workspace
    |-- index.md                             # Obsidian home / map of content
    |-- README.md                            # GitHub front door (code + setup)
    |-- handoff.md                           # rolling session state -- read first
    |-- Ledgerlens_System_Design_FINAL.md    # locked architecture (authoritative)
    |-- pyproject.toml                        # (P0) package + phased optional-deps
    |-- .env.example                          # (P0)
    |-- ledgerlens/                          # (P0) the Python package
    |   |-- config.py                        #      single source of truth
    |   |-- interfaces/                      #      the seams + factory
    |   `-- ingestion/ retrieval/ api/ eval/ observability/   # phase placeholders
    |-- scripts/   tests/                    # (P0) smoke test, pgvector check, pytest
    |-- .cursor/
    |   `-- rules/
    |       |-- 00-project.mdc               # ALWAYS on: identity + hard guardrails
    |       |-- 10-python.mdc                # attaches for **/*.py
    |       `-- 20-obsidian-notes.mdc        # attaches for **/*.md
    |-- .cursorignore   .gitignore
    `-- docs/
        |-- GETTING_STARTED.md               # setup + Cursor/Composer workflow
        |-- CONVENTIONS.md                   # this file
        |-- PHASE_0_BUILD.md                 # the first build task
        |-- BUILD_PLAN.md                    # phase tracker
        |-- architecture.md                  # (P0) placeholder -> design doc
        |-- adr/                             # 0000-template; 0001 written in P0
        `-- planning/                        # strategy + outline docs
            `-- 01_Ledgerlens_Project_Outline.md


## How the AI reads this repo (Cursor)
- `.cursor/rules/` is the canonical guardrail set. `00-project.mdc` is always
  injected into Composer/Agent; `10-python.mdc` and `20-obsidian-notes.mdc` attach
  by file type. Verify with `/rules` in Composer.
- Change a guardrail in `00-project.mdc` first — it is the single source of truth.
- `.cursorignore` keeps `.obsidian/`, `.env`, virtualenvs, caches, and `data/raw/`
  out of Cursor's index.
- For real tasks, @-mention the relevant doc (`@PHASE_0_BUILD.md`) so its content —
  not just a pointer — is in context.
- `CLAUDE.md` is not part of this repo by default; add one only if you also use
  Claude Code, and keep it in sync with `00-project.mdc`.

## README vs index
- `README.md` is the **GitHub front door** — what the project is, setup, status.
- `index.md` is the **Obsidian home** — a wiki-linked map for *working* in the vault.

## Markdown / Obsidian
- Link notes with wiki-links: `[[handoff]]`, `[[BUILD_PLAN]]`. Obsidian resolves
  by note name across folders, so the path doesn't matter as long as names are unique.
- Keep filenames link-safe: avoid `: / # | [ ]`. Underscores and hyphens are fine.
- Every doc opens with YAML frontmatter (schema below). Bump `updated:` on every edit.

## Frontmatter schema
- `type`: index | handoff | adr | design | plan | blueprint
- `status`: active | accepted | superseded
- `phase`: 0-8 (the build phase the doc belongs to)
- `updated`: YYYY-MM-DD
- `related`: list of wiki-links to connected notes

## ADRs (decision records)
- One file per decision in `docs/adr/`, numbered `NNNN-kebab-title.md`, from
  `0000-adr-template.md`. Always record the rejected alternatives.
- **ADR-0002 (chunking) is authored by hand by Ryan**, not auto-generated — a
  deliberate IC->lead portfolio signal.

## Session hygiene
- Start: read [[handoff]]. End: update [[handoff]] and tick [[BUILD_PLAN]] boxes. Commit.

## Git
- `.gitignore` excludes `.env`, `.obsidian/`, `.trash/`, virtualenvs, caches, `data/raw/`.
- Commit docs and code together so the decision trail and the code move in lockstep.
