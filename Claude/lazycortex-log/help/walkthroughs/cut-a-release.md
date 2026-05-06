---
chapter_type: walkthrough
summary: Take a fresh batch of commits all the way to a published CHANGELOG bullet block — distill themed prose, then generate outcome-led bullets filtered for public release.
last_regen: 2026-05-05
diagram_spec:
  anchor: "How the pieces fit together"
  request: "Sequence diagram showing the cut-a-release journey: user runs lazy-log.distill which reads commits.jsonl and writes changelog.md; user reviews changelog.md; user dispatches lazy-log.bullets agent with plugin name, commit range, and new version; lazy-log.bullets reads git log and renders a release block; user prepends the release block to CHANGELOG.public.md and commits."
source_skills:
  - lazy-log.distill
  - lazy-log.bullets
---
# How do I cut a release and publish a CHANGELOG entry?

You have landed a batch of commits and are ready to ship a version. This walkthrough takes you from raw commits all the way to a clean `### <version> — <date> UTC` block prepended to `CHANGELOG.public.md`. Two agents do the heavy lifting: `lazy-log.distill` turns the raw commit stream into readable themed prose you can review, and `lazy-log.bullets` reads a specific commit range, drops internal-only work, and rewrites what remains as outcome-led bullets that users installing the plugin will care about.

## What you need

- `lazycortex-log` installed in the project — run `/lazy-log.install` if you have not done so yet.
- `.logs/changelog.md` present (created by `/lazy-log.install`).
- At least one commit recorded in `.logs/commits.jsonl` since the last release — the `lazy-log.commit-recorder` hook captures every commit automatically.
- The git SHA of the previous release anchor (the last commit that was already public). If this is the first release, use the SHA of the initial project commit.
- The new version string in SemVer form (`X.Y.Z`) and the release date.

## The flow

### Step 1 — Refresh the functional changelog with lazy-log.distill

Run `/lazy-log.distill` (or ask Claude to dispatch it). The agent reads `.logs/commits.jsonl`, groups new commits by theme, and writes human-readable prose into `.logs/changelog.md`. Each theme gets a `## <theme>` block with dated paragraphs; touched themes bump to the top. SHA citations are embedded so you can `git show <sha>` on anything that looks interesting.

If you ran distill within the last four hours and want to force a refresh anyway, include `force` in your invocation prompt.

When distill finishes, open `.logs/changelog.md` and read through the themes that cover your pending release range. This is your chance to verify that the agent captured everything meaningful and that the prose accurately represents what changed. If a paragraph is wrong or a theme is missing, re-run distill after adding the relevant commits — do not hand-edit bullets in a later step to compensate for a bad changelog.

### Step 2 — Decide your commit range

Identify the two boundaries of the release:

- **Old anchor** — the short SHA of the last commit that was already included in your previous public release. If this is the very first release, use the initial commit SHA (`git log --oneline | tail -1`).
- **New anchor** — `HEAD` (or the specific SHA you are cutting to, if you are not releasing from the tip).

The range you will pass to `lazy-log.bullets` is `<old-sha>..HEAD`.

### Step 3 — Dispatch lazy-log.bullets to generate the release block

Ask Claude to dispatch the `lazy-log.bullets` agent. Provide all four fields on separate lines in the prompt:

```
plugin: <plugin-name>
plugin_dir: claude/<plugin-name>/
range: <old-sha>..HEAD
new_version: <X.Y.Z>
date: <YYYY-MM-DD>
```

The agent reads commits in that range scoped to the plugin directory, drops every commit whose type is `chore:`, `style:`, `test:`, or a docs-only sync, and rewrites surviving commits as outcome-led bullets. Commits sharing a Conventional-commits scope are grouped into a single bullet when they describe one user-visible change. Breaking changes are prefixed with **Breaking:**.

The agent's final output is the rendered release block:

```
### <X.Y.Z> — <YYYY-MM-DD> UTC

- <bullet 1>
- <bullet 2>
```

Review the bullets. Each one should describe what a user installing or upgrading the plugin will experience — not what files changed or what internal refactoring was done. If the scope of the release has shifted (a commit was merged late, a commit was reverted), adjust your range and re-run rather than hand-editing the bullets.

### Step 4 — Prepend the release block to CHANGELOG.public.md

Open `CHANGELOG.public.md` at the project root. Paste the rendered release block directly below the file's top-level heading, above any previous release entries. The expected structure is:

```
# Changelog

### <new_version> — <date> UTC

- <bullet 1>
- <bullet 2>

### <previous_version> — <previous_date> UTC

...
```

Save the file.

### Step 5 — Verify and commit

Run a quick sanity check: confirm the version heading is correct, the date matches today's (or your intended release date), and no internal jargon or SHA references slipped through into the bullets.

Then stage and commit `CHANGELOG.public.md` as part of your release commit alongside any version-bump changes in `plugin.json` or `package.json`.

## After you're done

Your `CHANGELOG.public.md` now has a clean public entry at the top. For the next release, run the same path: distill whenever you land meaningful commits to keep `.logs/changelog.md` fresh, then dispatch `lazy-log.bullets` at release time with the new range. Because distill captures new commits in themed prose as you go, the next release review step is fast — you are confirming prose you have already read, not reconstructing history from scratch.

If you re-run `lazy-log.bullets` for the same range (to adjust wording or because the scope changed), the agent regenerates the block from the live git history — do not hand-edit a block that may be regenerated. Either accept the generated output or adjust your input range.

## How the pieces fit together
