---
chapter_type: block
summary: Keep a human-readable changelog current with lazy-log.distill, then cut release-ready CHANGELOG bullets with lazy-log.bullets when you ship.
last_regen: 2026-05-08
no_diagram: true
source_skills:
  - lazy-log.distill
  - lazy-log.bullets
---
# Changelog: ongoing distillation and release drafting

`lazycortex-log` maintains two complementary views of your project's history. The first is a private, continuously-updated prose changelog in `.logs/changelog.md` — a human-readable record that accumulates after every meaningful commit. The second is a public release block you produce when you ship, summarising only the changes a user installing the plugin would care about. Two agents handle these two phases: `lazy-log.distill` owns the first; `lazy-log.bullets` owns the second.

## What's in this block

- **`lazy-log.distill`** — reads raw commit entries from `.logs/commits.jsonl` (written by the `lazy-log.commit-recorder` hook on every `git commit`) and converts them into themed functional prose in `.logs/changelog.md`. Organised theme-first (`## <theme>`) with one paragraph per day under each theme. Same-day re-runs rewrite today's paragraph in place rather than appending a fragment, so the file stays clean. Touched theme blocks float to the top so the freshest work is always visible first. A 4-hour throttle prevents noise on mechanical commit runs; passing `force` or `manual catch-up` in the invocation prompt bypasses it.

- **`lazy-log.bullets`** — takes a plugin name, a commit range, a new version, and a date. It reads the commits in that range scoped to the plugin tree, drops internal-only commits (`chore:`, `style:`, `test:`, docs-only regeneration, plumbing changes), and rewrites the survivors as outcome-led bullets grouped by Conventional-commits scope. The rendered block — a `### <version> — <date> UTC` section with one bullet per user-visible change — is the agent's primary return value, ready to prepend to your public `CHANGELOG.public.md`. The agent does not touch that file; the prepend step is yours.

## How they work together

Distill runs continuously, throughout development. Every time you land a commit that represents a real change — a new feature, a fix, a meaningful refactor — the `lazy-log.logging` rule (applied by every skill and agent in the repo) calls `lazy-log.distill` at the end of the turn when a qualifying commit lands. You do not need to invoke it manually most of the time; the cadence gate in the logging rule fires automatically.

What accumulates in `.logs/changelog.md` is the private record: detailed, themed, with SHAs so you can `git show` back to any moment. This file is gitignored by default (`.logs/` is a per-contributor artifact), so it never leaves your machine.

When you are ready to ship, you run the cut-a-release walkthrough. At the point where release notes are needed, you (or the release workflow) dispatch `lazy-log.bullets` with the commit range since the previous release anchor. The agent reads the same commits that distill already narrated in prose, but it applies a stricter filter — anything a user would not feel is dropped — and rewrites the survivors in headline style. The resulting block is what you prepend to `CHANGELOG.public.md`.

The pipeline is therefore: `commit-recorder` captures → `distill` narrates (private, ongoing) → `bullets` filters and condenses (public, on demand).

## Where this fits

**The cut-a-release walkthrough** (`cut-a-release.md`) uses `lazy-log.bullets` as its release-notes step. If you are cutting a release end-to-end, follow that walkthrough; this block describes what the two agents do and why the split exists.

**The commit-recorder hook** (`lazy-log.commit-recorder`) is what feeds `.logs/commits.jsonl`. Without it, `distill` has nothing to read. The hook is installed by `/lazy-log.install` and fires on every `git commit` — it writes a single JSON line per commit with SHA, date, author, branch, subject, body, file list, and diff stats. No LLM call; no prompt.

**The private changelog as a recall source** — `.logs/changelog.md` is not just for reading before a release. It is one of the sources `lazy-log.recall` searches when you ask "why did we change X?" The themed, prose-first structure makes it easier to rank than raw commit subjects, so recall results tend to surface the right context faster. If you have undistilled commits from before a long gap, run `/lazy-log.distill` with `manual catch-up` before querying recall on that period.
