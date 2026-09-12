---
name: lazy-spec.status-note-protocol
version: 5
description: The body shape of the two plugin-owned folder-notes — an asset's status note (frontmatter gates, the seven protected H1 sections, the shared primitive pointers) and a level note at a product root or the catalog root (four level gates, the stricter section roster).
---
# Status-note protocol — asset status folder-note and level note shape

Parts 4 and 4b of the [layout protocol](./lazy-spec.layout-protocol.md), split out at 75 KB and kept under their original numbers so existing `Part N` citations still resolve. The frontmatter shape and body layout of the two folder-notes the plugin owns; it does NOT restate the gate rules, which are [lifecycle](./lazy-spec.lifecycle-protocol.md)'s. Where these notes sit in the tree is the layout protocol's Part 1; what a role is and which path it is legal at is the [file-roles protocol](./lazy-spec.file-roles-protocol.md)'s Parts 2 and 3.

## Part 4 — Status file (folder-note) shape

Every asset folder (`features/<feat>/`, `changes/<change-name>/`, `bugs/<bug-name>/`) MUST contain exactly one folder-note — a file whose basename matches the parent folder (e.g., `features/chapter-log/chapter-log.md`, `changes/Rename Chapter Log/Rename Chapter Log.md`, `bugs/login-accepts-empty-password/login-accepts-empty-password.md`). It carries the asset's progression in a machine-consumable form for `spec.*` skills. The folder-note is identified by `spec_role: status` in frontmatter; `lazy-spec.audit` also enforces the basename-matches-parent invariant.

The status file owns the asset's **gates** — five flat top-level booleans plus a `spec_cancelled` overlay. There is no `gates:` dict, no `stage:`, no `awaits_human:`, and no `## Workflow` section: the gate booleans are the entire progression model. The authoritative gate semantics — the linear S0..S5 ladder, the precondition table, derived-vs-human-signal mechanics, and the single mutation channel — live in [lifecycle](./lazy-spec.lifecycle-protocol.md). This section covers only the file's frontmatter shape and body layout; it does NOT restate the gate rules.

### Status frontmatter schema

The status folder-note carries the asset's type, five flat boolean gates and one overlay flag — no nesting, no `gates:` dict. This matches the shipped template `${CLAUDE_PLUGIN_ROOT}/templates/spec.<type>/asset-note.md` (or `spec.asset/asset-note.md` for a type with no folder of its own):

```yaml
---
tags:
  - <product_tag>
  - spec/status
spec_role: status
spec_asset_type: <the asset's type>
spec_design_done: false
spec_plan_done: false
spec_develop_done: false
spec_tests_passing: false
spec_released: false
spec_cancelled: false
iconize_icon: <inherited from the asset's type declaration>
iconize_color: <inherited from the asset's type declaration>
---
```

- `spec_asset_type` is what makes the asset an asset OF a type — the folder it sits in is a place, not a fact, and everything that resolves the asset's law (the coordinator, the playbook lookup) reads this key, never the path. Written at scaffold time alongside `spec_tools`, the list of tools the asset is realised and checked with when its type declares any.
- The five gate booleans (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`) and the `spec_cancelled` overlay are the asset's whole progression state. Their ladder, preconditions, and flip rules are owned by [lifecycle](./lazy-spec.lifecycle-protocol.md).
- `iconize_icon` / `iconize_color` are managed keys, inherited from the asset's type declaration (`asset_types[<type>]`, the product's own merged over the shipped set); they paint the folder icon in the Obsidian file explorer. Not authored by hand.
- This is distinct from the per-file `spec_stage` on sibling authored docs (`design.md` / `bug.md` / `code-plan.md` / `test-plan.md`) — see [lifecycle](./lazy-spec.lifecycle-protocol.md). The folder-note carries gates, not a stage. The sibling `code-report.md` / `test-report.md` journals carry neither gates nor a stage.

### Status body format

The status folder-note body carries seven H1 sections, in order, matching the shipped `asset-note.md` template byte-for-byte. All seven are plugin-owned and protected — each seeds EMPTY (no placeholder HTML comment; prose explanations live in this doc and the playbook, not in the scaffolded note itself). There is no title H1, no `## Current`, no `## Workflow`, no `## Log`, no H2-level Gates or History.

Each protected section's **first content line** is the ownership tag `#protected/spec/<region>`. This tag tells every other plugin (reviewer, wiki, etc.) that the section is owned by the spec plugin and must be preserved byte-for-byte across any edit those plugins make to the note. Ownership by the `spec` plugin domain is not the same as a single writer — the protected-sections obligation binds every OTHER plugin to leave the section alone; within the spec domain, who actually writes each section still varies (below).

1. **`# Summary`** (protected, `#protected/spec/summary`) — a one-line précis of the asset (written by `lazy-spec.create-asset` / `lazy-spec.product-config` at scaffold time; on container notes it carries `<!-- spec:precis:* -->` and `<!-- spec:stats:* -->` markers filled by `summary_render`).
2. **`# Gates`** (protected, `#protected/spec/gates`) — the launch checkboxes `spec.coordinator` hangs and reconciles, as `[!gate]` blocks. Nothing else lives here: `bin/flip_gate.py` writes no callout, a gate's state is its frontmatter boolean.
3. **`# Attachments`** (protected, `#protected/spec/attachments`) — the coordinator's registry of the asset's non-markdown attachments, one line per file: a link to the file and the document that owns it. **The one optional section**: the shipped templates seed it, so every freshly scaffolded note carries it empty, but a note created before it existed does not have it — `note-check` reports its absence as nothing at all, and only validates the owner tag when the heading is present. A markdown attachment is never listed here; its ownership lives in its own `spec_owner_doc` frontmatter, and duplicating it would create two sources of truth that can disagree.
4. **`# Status brief`** (protected, `#protected/spec/status-brief`) — `spec.coordinator`'s own prose, rewritten (not appended) on every invocation: what's happening on the asset, why it's stalled (if it is), what happens next. Placeholder before the coordinator's first pass: `_Not yet assessed by the coordinator._`.
5. **`# Coordinator rules`** (protected, `#protected/spec/coordinator-rules`) — operator-authored, persistent constraints scoped to this asset; `spec.coordinator` reads it before every decision but never writes it. The operator writes it by hand — the protected-section contract binds every other PLUGIN to preserve it byte-for-byte, not the operator. Seeded empty.
6. **`# Coordinator commands`** (protected, `#protected/spec/coordinator-commands`) — operator-authored one-shot instructions; the coordinator, as this section's owning persona, unfolds a command into a numbered mini-plan written into this same section, locks progress marks into it while the command runs, then moves the finished block into `# History` on completion (`lazy-spec.coordination-playbook.md` Chapter 5). Seeded empty.
7. **`# History`** (protected, `#protected/spec/history`) — one line per gate or stage transition, appended chronologically. Earlier lines are never rewritten.

```markdown
# Summary
#protected/spec/summary

<one-line précis of the asset>

# Gates
#protected/spec/gates

> [!gate] Review design.md
> - [ ] Review design.md
>
> tick to open review: `design.md` re-enters the loop at the reviewer round

# Attachments
#protected/spec/attachments

- [mockup.html](mockup.html) — design.md
- [palette.svg](palette.svg) — design.md

# Status brief
#protected/spec/status-brief

<the coordinator's current narration>

# Coordinator rules
#protected/spec/coordinator-rules

<operator-authored constraints scoped to this asset, once written>

# Coordinator commands
#protected/spec/coordinator-commands

# History
#protected/spec/history

- 2026-05-01 — lazy-spec.flip-gate · spec_design_done → true
- 2026-05-02 — lazy-spec.flip-gate · spec_plan_done → true
```

**Rules**:

- `# Gates` carries the launch checkboxes `spec.coordinator` hangs and reconciles (`lazy-spec.coordination-playbook.md` Chapter 5) and nothing else. `bin/flip_gate.py` writes no callout here: a gate's state is its frontmatter boolean, its transition is the `# History` line, and the flip's reason is in the run log.
  - **Launch checkbox** — head line with the label, the `- [ ] <label>` line directly under it, then a blank quoted line (`>`) before any hint text. The blank line is structural, not style: a line glued to a checklist item is that item's continuation, and Obsidian's task renderer shows an item's first line only, so a glued hint is invisible in reading view. The same shape binds every checkbox-carrying callout in a note, `[!question]` options and their attribution included.
  - There is no `[!ready]` / `[!info]` readiness callout anymore — `bin/gate_tick.py` no longer evaluates gate readiness or drops one. Readiness reasoning now lives in `spec.coordinator`'s own narration, in `# Status brief`, per `lazy-spec.coordination-playbook.md`.
- `# Attachments` is `spec.coordinator`'s own registry, one line per non-markdown attachment in the form `- [<file>](<file>) — <owner>.md`. It stays absent or empty on an asset that has none, and a line whose file no longer exists is removed on the next reconciliation. `note-check` treats the section as optional — no finding when the heading is absent, a `missing-marker` finding when the heading is present without `#protected/spec/attachments` as its very next line.
- `# Status brief`, `# Coordinator rules`, and `# Coordinator commands` are `spec.coordinator`'s own sections to reason from (write-once-per-invocation for the brief; read-only / lock-and-clear for the other two) — see `lazy-spec.coordination-playbook.md` §§ 1, 5, 9 for the full contract. `note-check` (`bin/note_ops.py`) validates all three are present, in order, and that each carries its own protected marker as the line immediately following its heading; `lazy-spec.audit` delegates to it rather than re-deriving the check.
- `# History` is one line per gate (or stage) transition, appended chronologically. `flip_gate` writes `- <date> — lazy-spec.flip-gate · <gate> → <true|false>`; `lazy-spec.set-stage` writes its own per-file stage-transition lines here too. Earlier lines are never rewritten.

### Shared primitives — pointers

Skills touching status files or authored-doc stages use these named primitives rather than restating the mechanics:

- **`lazy-spec.flip-gate`** (`bin/flip_gate.py`) — the only writer of gate booleans. Flips unconditionally on call (refusing only a cancelled asset), rewrites the gate in frontmatter and appends a `# History` line. Deciding WHEN a gate is ready is `spec.coordinator`'s call, not this primitive's. See [lifecycle](./lazy-spec.lifecycle-protocol.md) → "The single mutation channel".
- **`lazy-spec.gate-tick`** (`bin/gate_tick.py`) — a pure poller now: clears a finished expert job's `active_job` marker in the runtime sidecar and runs a structural `note-check` on the folder-note. It no longer flips gates, evaluates readiness, or drops any callout. See [lifecycle](./lazy-spec.lifecycle-protocol.md) → "The `gate-tick` md-scan worker".
- **`lazy-spec.set-stage`** — change a per-file stage on an authored doc; see [lifecycle](./lazy-spec.lifecycle-protocol.md). Every per-file stage change in the system MUST go through this primitive.
- **`lazy-spec.resolve-dependency`** — resolve a dep entry to `{kind, spec_link, dev_link, local_spec_path?}`; see [sources](./lazy-spec.sources-protocol.md) Part 3.
- **`lazy-spec.resolve-repo`** — turn a repo-config key into `{local_path, branch, remote_url, host, owner, repo, forge, base_url}` by inspecting the local checkout's git remote and applying the known-forges table; see [sources](./lazy-spec.sources-protocol.md) Part 2.
- **`lazy-spec.source-url`** — build a forge-correct source URL for `(repo_key, path, kind, branch?)` via the known-forges table. EVERY source URL emitted by any skill or agent MUST go through this primitive; see [sources](./lazy-spec.sources-protocol.md) Part 2.

Skills MUST reference these primitive names rather than restate the mechanics.

## Part 4b — Level note (product root and catalog root) shape

Two folder-notes carry a LEVEL role instead of `status`, and `spec.catalog-coordinator` owns both in full (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md`):

- **Product level note** — `<spec_path>/<leaf>.md`, where `<leaf>` is the final segment of the product's `spec_path`. `spec_role: product`. One per registered product.
- **Catalog level note** — `<content-root>/<basename of content-root>.md` (`specs/specs.md` under the default `spec.vault_root`). `spec_role: catalog`. Exactly one per vault.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/`, or `claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

Both are created and brought to schema by one verb, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> catalog-note backfill <product>` / `--root`, from the shipped template `${CLAUDE_PLUGIN_ROOT}/templates/spec.product/level-note.md`. Neither is ever hand-written: the verb adds what a note lacks and rewrites nothing, so an operator's `# Coordinator rules` and the rendered `# Summary` survive every run byte-for-byte.

### Level frontmatter schema

```yaml
---
spec_role: product            # or `catalog` on the vault's one root note
spec_vision_done: false
spec_design_done: false
spec_ui_design_done: false
spec_tech_done: false
spec_halted: false
iconize_icon: <from the level's registry entry>
iconize_color: <from the level's registry entry, or the product's own colour>
---
```

- The four gate booleans are the level's whole progression state. Every one is derived from the stage of one system document beside the note; their semantics live in [lifecycle](./lazy-spec.lifecycle-protocol.md) Part 2b.
- A level note carries **no** `spec_asset_type` and **no** `spec_tools`: the level's type IS its role, and the ladder comes from the level playbook, not from a per-type declaration. It carries no `spec_cancelled` and no `spec_released` either — a level is not abandoned and not shipped; `spec_halted` is its only overlay.
- `spec_design_done` shares its name with the asset gate of the same name. They are different objects on different notes, and nothing that reads asset gates ever reads a level note.
- The coordinator's recorded review state of the level's documents lives here too, under the same closed-schema marker key a status note uses; `note-check` validates it.

### Level body format

Seven plugin-owned H1 sections, each with its `#protected/spec/<region>` tag as its first content line, in this order: `# Summary`, `# Gates`, `# Status brief`, `# Coordinator rules`, `# Coordinator commands`, `# History`, `# Attachments`. `# Summary` carries the same `<!-- spec:precis:* -->` and `<!-- spec:stats:* -->` marker pairs every container note has, filled by `summary_render`.

**What `note-check` requires differs from what the template seeds, and the level roster is the stricter one.** On a status note, five sections are required — `# Gates`, `# Status brief`, `# Coordinator rules`, `# Coordinator commands`, `# History` — with `# Attachments` optional (a note predating the section is not a finding) and `# Summary` outside the check. On a LEVEL note `# Attachments` joins the required five, because every level note is brought to shape by `catalog-note backfill`: an absent section there means the backfill was never run, which is exactly what the check should say.

What each section is for is identical to the status note's (Part 4 above), read at the level's altitude: `# Gates` holds the level's launch checkboxes, `# History` takes the level documents' own stage transitions (`lazy-spec.set-stage` writes them here — a system document's nearest folder-note is its level note, not an absent status note), and `# Attachments` registers the level's non-markdown attachments.

The level's four system documents — `vision.md`, `design.md`, `ui-design.md`, `tech.md` — sit loose beside the note, exactly as [file-roles](./lazy-spec.file-roles-protocol.md) Part 2's path constraints already describe, and are the only documents the level note coordinates.

