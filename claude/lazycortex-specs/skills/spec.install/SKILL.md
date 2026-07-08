---
name: spec.install
description: "Bootstrap the lazycortex-specs plugin for the current project (or globally). Ensures the per-category template-override dirs exist (`.claude/templates/spec.feature/`, `spec.change/`, `spec.bug/`, `spec.product/`, `spec.request/`), reads-or-seeds the repo default language into the plugin-owned `spec` settings section, registers the `spec.gate-tick` md-scan routine so the daemon advances asset gates, wires the request-handler runtime (md-scan routines + experts + review class) at project scope, and offers to register the first product via `spec.product-config`. Daemon-routine registrations honor the tracked `daemon.enabled` gate; install scope is derived; file writes follow the absent/merge/conflict policy. Idempotent — safe to re-run."
allowed-tools: Read, Write, Edit, Glob, Skill, Bash(mkdir -p *), Bash(git rev-parse*), Bash(test *), Bash(date *), Bash(PYTHONPATH=* python3 *), Bash(lazycortex-core *), AskUserQuestion
---
# Install lazycortex-specs

Bootstrap the plugin in the right scope: ensure the consumer dir exists where per-product authored-doc template overrides live, read-or-seed the repo default language, register the `spec.gate-tick` routine so the daemon advances each asset's gates, wire the request-handler runtime, and register the first product.

## Install philosophy (read before any action)

- **Plugin enabled = full functionality.** An enabled plugin is installed whole. There is no per-part "wire this?" opt-in — wanting the plugin means wanting its surface. The only questions this skill asks collect GENUINE project config that cannot be derived (the repo authoring language; the first product) and are read-first (Read-first / never re-ask).
- **Daemon gate.** Every step that registers a daemon routine first reads the tracked `daemon.enabled` flag; if the project has opted out of the daemon, that registration is skipped silently (see § Daemon gate). `lazy-core.install` owns the first-time daemon question — this skill never re-asks it.
- **Scope is derived, never asked.** Install scope comes from where the plugin is *enabled* (see Step 1); a project-scope enablement wins even when the install record's `scope` is `user`. Python floor is owned by `lazy-core.install`'s first phase — this skill never re-probes it.

## File-sync policy (applies to every file this skill writes)

Every file this skill creates or updates — settings sections, routine entries, review classes, the `lazy.settings.json` blocks — follows three cases; there is no per-file "install?" prompt and no routine/entry drift wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the shipped / last-known version → write silently. State `installed` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged, but the shipped delta applies without contradicting local edits (new keys / entries / globs added, every local-only chunk left untouched) → merge silently. State `merged`.
3. **Genuine conflict** — the same region (a key, a line, a block) was changed both locally and in the shipped version in ways that cannot be reconciled automatically → the ONLY case that asks. `AskUserQuestion` naming the file, quoting the conflicting region, and showing a unified diff; options `merge-shipped` / `keep-local`.

"Conflict" means you cannot determine what should survive — not merely "the bytes differ". No contradiction → no question. A no-longer-shipped entry (orphan) is left in place silently (`kept-orphan`); this skill never deletes consumer config.

## Daemon gate (read before Steps 5 and 6)

Steps 5 and 6 register daemon routines (`spec.gate-tick`, `spec.request-open`, `spec.request-apply`). Before either writes, read the tracked `daemon.enabled` flag once:

```
Bash(PYTHONPATH=<core-bin> python3 -c "from lazy_settings import load_tracked_section; from pathlib import Path; print(load_tracked_section(Path('<repo-root>/.claude/lazy.settings.json'),'daemon').get('enabled','unset'))")
```

`<core-bin>` is `<installPath-of-lazycortex-core>/bin` (resolve `lazycortex-core@lazycortex`'s `installPath` from `installed_plugins.json`). If the flag prints `False` → skip the routine registration silently, state `skipped-daemon-disabled` for that step. If it prints `unset` or `True` → proceed (do NOT ask — `lazy-core.install` Gate 1 owns the first-time daemon question).

## Execution discipline (MANDATORY — read before any action)

This skill has 10 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical list (titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Ensure consumer dirs`
   - `Step 4 — Seed default language`
   - `Step 5 — Register the gate-tick routine`
   - `Step 6 — Wire the request-handler runtime`
   - `Step 7 — Offer first product registration`
   - `Step 8 — Register the plugin-CLI Bash allow-pattern`
   - `Step 9 — Verify`
   - `Step 10 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `created`, `already-exists`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Detect install scope

Scope = **where the plugin is actually enabled**, not where `/plugin install` last ran. The `scope` field in `installed_plugins.json` records the install command's origin, which drifts from the activation scope — a plugin enabled per-project in `.claude/settings.json` can carry an install record of `scope: "user"`. Enablement is the source of truth for where config belongs.

Resolve it via the core CLI, which reads `enabledPlugins` from the project settings first, then the global settings, and falls back to the install record's own `scope` only when neither settings file enables the plugin:

```
Bash(lazycortex-core detect-scope lazycortex-specs@lazycortex)
```

The command prints exactly one word:
- `project` — enabled in `<repo-root>/.claude/settings.json` (project wins even when the install record's scope is `user`, and when both scopes enable it); Step 2 targets `<repo-root>/.claude/`.
- `user` — enabled only in `~/.claude/settings.json` (or the fallback resolved there); Step 2 targets `~/.claude/` (and the project-scope-only request wiring in Step 6 is skipped).
- `not-installed` — `lazycortex-specs@lazycortex` is absent / has an empty array in `~/.claude/plugins/installed_plugins.json`; the plugin has never been installed on this machine.

The scope is derived — do NOT ask.

**Do NOT compare an entry's `projectPath` against the current working directory.** Step 2 targets `<repo-root>` (i.e. `git rev-parse --show-toplevel` in the current cwd) regardless of any entry's `projectPath`. A `projectPath` mismatch is **never** grounds for aborting.

Abort **only** on `not-installed` — the shared plugin cache is the sole proof of installation, and enablement cannot substitute for missing sources. In that case tell the user to install it first:
```json
"enabledPlugins": { "lazycortex-specs@lazycortex": true }
```
then run `/plugin install lazycortex/lazycortex-specs`.

## Step 2: Determine paths

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — warn the user).

| Scope | Consumer root |
|---|---|
| `user` | `~/.claude/` |
| `project` | `<repo-root>/.claude/` |

The plugin install path (`<installPath>`) is the `installPath` field from `installed_plugins.json` for `lazycortex-specs@lazycortex`. The plugin ships:

- Protocol-contract docs at `${CLAUDE_PLUGIN_ROOT}/references/*.md`
- Default authored-doc templates at `${CLAUDE_PLUGIN_ROOT}/templates/spec.<category>/` (one folder per built-in category: `spec.feature/`, `spec.change/`, `spec.bug/`, `spec.product/`, `spec.request/`; operator-defined categories add their own under `spec.<name>/` via `/spec.add-asset-category`)

These are read directly from the plugin cache at runtime — this skill does NOT copy them into the consumer tree.

## Step 3: Ensure consumer dirs

Create (with `mkdir -p`) the single consumer directory that holds per-project artifacts:

| Path (relative to consumer root) | Purpose |
|---|---|
| `templates/spec.feature/`, `templates/spec.change/`, `templates/spec.bug/`, `templates/spec.product/`, `templates/spec.request/` | One per category; each holds optional `<compound-key>/` per-product override sub-folders for that category's templates |

Report `created` or `already-exists`.

This skill does NOT create `.claude/rules/` — products live in the `products` settings section and repos live in the `repos` settings section now, not in rule files. It does NOT create a `templates/spec.workflows/` dir — workflow machinery has been removed from the plugin.

Project scope only: if a spec output directory is needed (e.g. a `Specs/` vault root), defer that decision to `spec.product-config` — this skill does not create vault content.

## Step 4: Seed default language

Three settings sections back the spec system: `products` (cross-plugin), `repos` (cross-plugin — maps each repo key to its local checkout metadata), and `spec` (plugin-owned, holds `default_language`). All three are registered in lazy-core's `CURRENT_VERSIONS` and **auto-initialize on first `settings-get`**. Install does NOT hand-write any of them — `products` and `repos` records are authored by `spec.product-config`; this step only optionally seeds `spec.default_language`.

The repo authoring language is GENUINE project config — it cannot be derived — so this step keeps its question, but read-first: a language already on record is never re-asked.

**Read first.** Run `Bash(lazycortex-core settings-get spec)` and inspect `default_language`. If the section already carries a non-`en` `default_language` (a prior install or hand-edit set it), state outcome `language-on-record:<code>` and skip the question entirely. Only when nothing is on record (section absent, or `default_language` still the `en` default) do you ask.

The plugin's effective default language is `en` until overridden. Ask via `AskUserQuestion`:

- **question**: `Set a non-default repo language for spec docs? The plugin defaults to en. Pick another only if this repo's specs are authored in a different language.`
- **options**:
  - `keep-en` — accept the `en` default; write nothing.
  - `set-other` — seed a different language code into the `spec` section.

If `keep-en`: outcome `language-default-en`. Skip the write.

If `set-other`: ask the operator for the language code (e.g. `ru`, `de`), then read-patch-write the `spec` section so the auto-init `_version` is preserved:

```
Bash(lazycortex-core settings-get spec)
```

Parse the printed JSON, set `default_language` to the operator's code, and pipe the full object back:

```
Bash(printf '%s' '<patched-spec-section-json>' | lazycortex-core settings-set spec)
```

Outcome: `language-set:<code>`. Why read-patch-write rather than emit a bare `{default_language: <code>}`: `settings-set` persists the whole section, so the auto-init `_version` field must survive the round-trip — drop it and the section reverts to an unversioned shape.

## Step 5: Register the gate-tick routine

The daemon advances each asset's gates by ticking the asset's status folder-note (`spec_role: status`). This step registers the `spec.gate-tick` md-scan routine via the blessed `/lazy-routine.register` skill — it does NOT hand-write the routine JSON into settings.

**Daemon gate.** Read the tracked `daemon.enabled` flag first (see § Daemon gate). If `False` → skip this registration silently, outcome `skipped-daemon-disabled`, continue to Step 6. If `unset` / `True` → proceed.

Invoke `lazycortex-core:lazy-routine.register` via the `Skill` tool, passing a `cfg` dict so the wizard runs programmatically (no per-field prompts). The exact routine:

```json
{
  "name": "spec.gate-tick",
  "cfg": {
    "type": "md-scan",
    "interval_sec": 60,
    "timeout_sec": 60,
    "paths": ["**/*.md"],
    "filter": {
      "frontmatter": {
        "spec_role": {"in": ["status"], "not_in": []},
        "spec_cancelled": {"in": [null, false], "not_in": []},
        "spec_released": {"in": [null, false], "not_in": []}
      }
    },
    "command": ["lazycortex-specs", "gate-tick"]
  }
}
```

The composite `{in: [...], not_in: []}` predicate is the shape the md-scan filter expects (same form as `lazy-review.scan`'s `review_active` / `review_result` clauses): `null` in `in` matches a missing key or explicit null, so an asset whose status note has not yet stamped `spec_cancelled` / `spec_released` still matches. The filter selects every live (un-cancelled, un-released) asset status folder-note across the vault.

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs it as `lazycortex-specs gate-tick <matched-file-path>` — it **appends the matched file's absolute path as the last argv** (same convention `lazy-review.scan`'s `process-file` relies on). `gate-tick <asset_note>` reads the appended status folder-note path and advances that one asset's gates.

If `/lazy-routine.register` reports the routine is already registered, accept its outcome (`unchanged` / `present`) — do not force-overwrite. Outcome: `routine-registered` or `routine-already-present`.

## Step 6: Wire the request-handler runtime

Request files at `<vault-root>/requests/` are processed by three runtime channels:

- **md-scan open (mechanical, command-based)** — fires on naked request files (no `review_active`, no `review_result`). Pure state flip: writes the opt-in frontmatter keys + Waiting banner and commits under the `spec.request-open` bot identity. No LLM spawn, ~1s latency. Routine `routines.spec.request-open` with `command:` shape pointing at `lazycortex-specs open-request`.
- **md-scan apply (mechanical, command-based)** — fires on post-finalize request files (`request_status: draft` + `review_result` in {`approved`, `approved-with-concerns`}). Reads the resolved routing prose, calls `lazycortex-specs scaffold-asset` for spawn targets, distributes the request body across each populated doc (Tier 3 fallback — whole body to the entity's WTR doc), opens a review cycle on every populated doc via `lazycortex-review start`, stamps terminal markers (`request_class`, `request_status`, mirror tag, status callout) and strips `# Routing`, atomic commit under `spec.request-apply` bot identity. No LLM dispatch — the worker is the Python primitive at `claude/lazycortex-specs/bin/apply_request.py`. Routine `routines.spec.request-apply` with `command:` shape pointing at `lazycortex-specs apply-request`.
- **lazy-review specialist** — `spec.request-router` runs all content work (classify, find candidates, surface the routing decision, fold to prose) during the review loop. Requires the agent registered as an expert AND a review class entry mapping `requests/*.md` to `spec.request-router` under `terminal.routing` (the post-approve terminal-action section writer group that owns the `# Routing` heading — surfaces only after the operator approves the body, persists through finalize so the apply worker can read the resolved routing prose, and never triggers revert-to-main since operator choices are not concerns). The class declares a separate `main` chain (the consumer-supplied interpreter expert) plus `history` (`historian`).

Without all three wired, the request inbox is dead from the daemon's perspective. The request runtime is part of the plugin's own surface — enabling the plugin means wanting it — so this step writes the blocks unconditionally; there is no `wire-now` / `skip` opt-in (per § Install philosophy).

**Project-scope only.** Request files live in `<vault-root>/requests/` per-vault; wiring at user scope would point the daemon at the wrong path. If Step 1 detected user scope, skip this step silently — outcome `skipped-user-scope`.

**Daemon gate.** The 6a/6b routines are daemon routines. Read the tracked `daemon.enabled` flag first (see § Daemon gate). If `False` → skip the routine writes (6a, 6b) and the `lazy-review.scan` sync (6f) silently; still write the expert + review classes (6c–6e), which are inert without the daemon but harmless and read by `lazy-review.configure`. State outcome `wiring-applied:<N> (daemon-disabled)`. If `unset` / `True` → write all blocks.

Read `lazy.settings.json` (create the file if missing) and merge the blocks per the File-sync policy: absent → write silently; present and cleanly mergeable → merge silently; genuine conflict (an existing entry whose shape contradicts the shipped one) → the only case that asks. Report `wiring-applied:<count-added>` (count of blocks newly added/merged; 0 means everything was already in place).

### 6a. md-scan open routine (mechanical, command-based)

Under `routines` add the key `spec.request-open` if missing:

```yaml
spec.request-open:
  type: md-scan
  interval_sec: 5
  timeout_sec: 30
  priority: 30
  paths: ["requests/*.md"]
  filter:
    frontmatter:
      review_active: {in: [null], not_in: []}
      review_result: {in: [null], not_in: []}
  command: ["lazycortex-specs", "open-request"]
```

The joint filter `review_active: [null] + review_result: [null]` catches files that have not yet entered the review loop — naked files (no frontmatter at all) AND partial-bootstrap files (`request_status: draft` set but `review_active` missing). The `review_result: [null]` clause excludes post-finalize files: finalize strips `review_active` AND stamps `review_result` (`approved` / `approved-with-concerns`), so those files match `review_active: [null]` alone but must be routed to the apply gate, not re-bootstrapped. The command brings the file to canonical opt-in shape, atomic commit under `spec.request-open` bot identity.

Once the script commits with `review_active: true`, the file falls out of this routine's filter and into `lazy-review.scan`'s loop. After finalize stamps `review_result`, the apply routine (6b) takes over.

If the routine already exists, apply the File-sync policy: byte-identical → `unchanged`; a stale shape that the shipped delta upgrades cleanly (e.g. adding the missing `review_result: [null]` clause without contradicting a local edit) → merge silently (`merged`); only a genuine contradiction (a local edit that the shipped shape would overwrite incompatibly — older `expert:` form replaced by `command:`, a deliberately narrowed `request_status: [null]` filter) triggers an `AskUserQuestion` with a unified diff.

### 6b. md-scan apply routine (mechanical, command-based)

Under `routines` add the key `spec.request-apply` if missing:

```yaml
spec.request-apply:
  type: md-scan
  interval_sec: 5
  timeout_sec: 60
  priority: 20
  paths: ["requests/*.md"]
  filter:
    frontmatter:
      request_status: {in: ["draft"], not_in: []}
      review_result: {in: ["approved", "approved-with-concerns"], not_in: []}
  command: ["lazycortex-specs", "apply-request"]
```

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs it as `lazycortex-specs apply-request <matched-file-path>` — same convention as `spec.request-open`. The worker is a deterministic Python primitive (`claude/lazycortex-specs/bin/apply_request.py`); no LLM dispatch happens at this gate. It parses the `# Routing` section, runs `lazycortex-specs scaffold-asset` for any spawn target, distributes the request body across each entity's WTR doc (Tier 3 fallback — whole body), maintains `spec_source_requests` frontmatter + the `## Requests` projection inside `# Sources`, opens a review cycle on every populated doc via `lazycortex-review start`, then stamps the request file's terminal markers and atomic-commits under `spec.request-apply` bot identity.

The joint filter `request_status: ["draft"] + review_result: ["approved", "approved-with-concerns"]` matches only the post-finalize state: finalize stamped `review_result` (clean approve OR approve-with-concerns) as its last step, and the terminal `request_status` has not been written yet (still `draft`). Stop-aborted reviews (no `review_result` ever written) and mid-review files (transient `review_*` keys present but `review_result` not yet stamped) do not match — apply only fires on a clean finalize. The worker reads the resolved routing prose that `spec.request-router` folded into `# Routing` during review and enacts it.

If the routine already exists, apply the File-sync policy: the older `expert: spec.request-apply` form (LLM-dispatched apply) is superseded by the shipped `command:` shape — when no local edit contradicts the swap, replace it silently (`merged`); only when a local edit on that entry would be lost does it become a genuine conflict and ask with a unified diff.

### 6c. Expert entry

Under `experts` add the key `spec.request-router` if missing:

```yaml
spec.request-router:
  agent: lazycortex-specs:spec.request-router
  git_author:
    name: spec.request-router
    email: spec.request-router@bot.invalid
```

The apply transition does NOT register an expert — its routine is `command:`-shape (the Python primitive). The bot identity for the apply commit is hardcoded as `spec.request-apply` / `spec.request-apply@bot.lazy-cortex` in the worker's CLI defaults — same identity the prior LLM-dispatched apply expert used, preserved across the rewrite so git log identity continuity is unbroken. Override with `--author-name` / `--author-email` if a consumer needs a different identity.

If an older `spec.request-apply` expert entry remains (from a previous install with the LLM apply path), it is now an orphan — the apply routine no longer dispatches an expert. Per the File-sync policy, orphans are left in place silently (`kept-orphan`); this skill never deletes consumer config.

### 6d. Review class

Under `review.classes` append an entry for `requests/*.md` if no existing entry's `paths` already contains that glob:

```yaml
- paths: ["requests/*.md"]
  experts:
    main:
      - name: <consumer-interpreter-expert>
    history:
      name: review.historian
    terminal:
      routing:
        name: spec.request-router
        section: Routing
        position: bottom
```

Writer shapes per the new schema (audit-enforced): `main` is a LIST of `{name}` writer objects; `history` is a SINGLE `{name}` object (no list, no `repo`); each `validation` / `terminal` section is a SINGLE writer object `{name, section, position}` (no list, no `repo` — the deprecated `repo` field is omitted; cross-repo dispatch uses `@<repo>` in `name`). `main` is the body-content interpreter expert the consumer supplies. `terminal.routing` is `spec.request-router`, the post-approve routing-decision writer that owns the `# Routing` heading — it fires only AFTER the operator approves the body, follows `lazy-review.doc-review-protocol` § `mode == terminal` (surfaces the routing decision as a `[!question]`, folds the operator's answer into prose naming the targets), the `# Routing` section persists through finalize so `spec.request-apply` can read the resolved routing prose, and the section never triggers revert-to-main (operator choices are not concerns). The router declares no `frontmatter` block — per the doc-review protocol, terminal-mode writers do not write frontmatter at all; everything the router decides lives in its section body. `request_class` is stamped by `spec.request-apply` post-finalize (it reads the class verdict from the routing prose and writes the field alongside `request_status` and the mirror tag — see the `spec.request-apply` agent body for the full apply contract). `main` writers and validators likewise own the document BODY only; daemon state keys (`review_*`) are written mechanically, never through an expert overlay. `history` declares `review.historian` explicitly (the registered expert key); absent, the dispatcher falls back to its built-in default name.

If the consumer has not yet registered an interpreter expert, omit `main` — the class still dispatches `spec.request-router` on `# Routing` changes and the historian on human commits.

If `review` section is absent, create `{_version: 1, classes: [<entry>]}`. If `classes` is present but no entry covers `requests/*.md`, append.

### 6e. Review classes for spawned spec docs

The `spec.request-apply` worker scaffolds entity folders (`features/<slug>/`, `changes/<slug>/`, `bugs/<slug>/`) under each registered product's `<spec_path>` and opens a review cycle on every populated authored doc. Those docs (`design.md`, `bug.md`, `plan.md`) need their own review classes so the daemon dispatches the right writer for each one — without these classes, spawned docs sit at `[!hint] Waiting #review/in-process` forever because no class matches their paths.

Under `review.classes` append two entries if no existing entry's `paths` already covers them. Glob `<spec_path_prefix>/products/*` is illustrative — the real `paths` glob each consumer writes mirrors the `spec_path` shape they registered (e.g. `Server/products/*` for a `spec_path: Server/products/<key>` product). For a vault with multiple products, the globs cover them all uniformly because the product key is a single path segment under the same prefix.

```yaml
# design.md class — designer writes; no validators (operator approves)
- paths:
    - "<spec_path_prefix>/products/*/features/*/design.md"
    - "<spec_path_prefix>/products/*/changes/*/design.md"
    - "<spec_path_prefix>/products/*/bugs/*/design.md"
  experts:
    main:
      - name: designer
    history:
      name: review.historian
# plan.md class — planner writes; no validators
- paths:
    - "<spec_path_prefix>/products/*/features/*/plan.md"
    - "<spec_path_prefix>/products/*/changes/*/plan.md"
    - "<spec_path_prefix>/products/*/bugs/*/plan.md"
  experts:
    main:
      - name: planner
    history:
      name: review.historian
```

`designer` and `planner` are the consumer-supplied expert agents (typically from `lazycortex-experts` or a project-local override). When the consumer has not registered one of them yet, omit the class until the expert exists — without a registered `main`, the dispatcher logs a no-writer warning per-tick. For built-in `bug.md` docs (bug-kind layout substitutes `bug.md` for `design.md`), extend the design class's `paths` with the matching bug glob or add a separate `bug.md` class with a bug-specific main writer.

No validators are wired — the WTR doc is approved by the operator directly through the standard review UI. No `terminal` block — these classes have no post-approve routing (the apply transition completes the request lifecycle; downstream is the per-asset gate machine, not another review round).

### 6f. Sync `lazy-review.scan` paths (MANDATORY when 6e classes are added)

`lazy-review.scan` is the md-scan routine the daemon uses to discover review-active files. Its `paths:` list is the discovery sieve — the dispatcher only sees files that pass through it. By contract `lazy-review.configure` keeps `routines[lazy-review.scan].paths` in sync with the union of every `review.classes[].paths` glob (see `lazycortex-review/skills/lazy-review.configure/SKILL.md`). When `spec.install` writes classes in 6e DIRECTLY (bypassing `lazy-review.configure`), it MUST also extend `routines[lazy-review.scan].paths` to match — otherwise the daemon never scans the spawned spec docs and the new classes are dead.

The md-scan matcher uses `PurePath.match` semantics where `*` does NOT cross `/`, so each level of nesting needs its own glob. Append the missing globs to `routines.lazy-review.scan.paths`:

```yaml
# product-level files (operator folder-note + product design.md / tech.md)
- "<vault_root>/<spec_path_prefix>/products/*/*.md"
# per-asset dirs (folder-note + authored docs)
- "<vault_root>/<spec_path_prefix>/products/*/features/*/*.md"
- "<vault_root>/<spec_path_prefix>/products/*/changes/*/*.md"
- "<vault_root>/<spec_path_prefix>/products/*/bugs/*/*.md"
# request inbox
- "<vault_root>/requests/*.md"
```

`<vault_root>` is `spec.vault_root` from settings (default `specs`). `<spec_path_prefix>` is the leading segment of every registered product's `spec_path` — e.g. `Server` for `Server/products/<key>`, or empty (no prefix) for `products/<key>`. Append only the globs not already in the list (dedupe).

Outcome: `wiring-applied:<N>` where N is 0..7 (the four 6a–6d blocks plus the two 6e classes plus the 6f paths sync).

### 6g. Offer optional protocols for the spec writer routine

Spec `design.md` / `tech.md` / `plan.md` docs are written by `designer` / `planner` experts dispatched through `lazy-review.scan` (the classes wired in 6e) — there is no separate spec writer routine. That routine is therefore the spec writers' routine too, and optional protocols attached to it reach them. Setting up spec is the moment those writers become relevant, so offer the operator the contextually-relevant optional protocols for `lazy-review.scan`. Delegate to the shared core helper (it judges each flagged candidate's frontmatter essence against the spec context and offers only the relevant ones; the routine config gains no new field — chosen ids are unioned into its existing `protocols` list):

```
Skill(skill: "lazycortex-core:lazy-routine.offer-protocols",
      args: "--routine lazy-review.scan --context 'spec authoring — design / tech / plan documents whose structure (flows, architecture, entities, lifecycles) often warrants a diagram'")
```

Idempotent with the same offer from `lazy-review.install`: already-attached protocols are not re-offered, and nothing is removed. Skip silently when the daemon gate above left `lazy-review.scan` unregistered — the helper returns `routine-absent`; record it and move on.

Outcome: the helper's return — `attached:<n>` / `declined` / `no-relevant-candidates` / `routine-absent`.

## Step 7: Offer first product registration

Ask via `AskUserQuestion`:

- **question**: `Register your first product now?`
- **description**: Every product lives in the `products` settings section; a code-bound product also references a repo record in the `repos` settings section describing its source checkout. The `spec.product-config` skill is the wizard that writes both. You can also run it later by dispatching `spec.product-config` directly.
- **options**:
  - `register-now` — invoke `spec.product-config` via the `Skill` tool to walk through repo cfg + product cfg creation.
  - `skip` — leave the consumer config empty; user runs `spec.product-config` later when ready.

If `register-now`: invoke `spec.product-config` via the `Skill` tool. Report the dispatch outcome. If `skip`: state `skipped-per-user-choice`.

## Step 8: Register the plugin-CLI Bash allow-pattern

The plugin ships `bin/lazycortex-specs` which other skills invoke via `Bash(lazycortex-specs ...)` — `spec.create-asset` resolves a product record, `spec.gate-tick` advances asset gates, etc. Expert subprocesses spawned by the `lazy-core.runtime` daemon run under Claude Code's `dontAsk` permission mode — that mode silently denies any Bash command not on the auto-allow list. Without this entry, every cross-skill CLI invocation from `spec.request-router` / other dispatched expert falls back to `Permission to use Bash has been denied because Claude Code is running in don't ask mode`, and the agent drifts off-protocol mid-step. (The apply routine is a `command:`-shape Python primitive, not an LLM dispatch — it does not pass through `dontAsk` mode but still benefits from the allow-pattern when an operator session runs `/spec.apply-request` manually.)

Per `lazy-core.hygiene` § Settings split, per-tool permissions live in `settings.local.json` (gitignored), never tracked `settings.json`. Target file resolves from Step 1's scope:

- project install → `<repo-root>/.claude/settings.local.json`
- user install → `~/.claude/settings.local.json`

Apply via the `lazycortex-core` CLI (idempotent — already-present patterns are no-ops):

```
Bash(lazycortex-core permission-allow <settings-local> "Bash(lazycortex-specs *)")
```

Outcome: `cli-allow-added` or `cli-allow-already-present`.

## Step 9: Verify

- Confirm the consumer dir from Step 3 now exists.
- Confirm the `spec.gate-tick` routine is present in `lazy.settings.json` (`routines.spec.gate-tick`).
- If Step 4 set a language: confirm `lazycortex-core settings-get spec` reports the chosen `default_language`.
- Unless Step 6 was `skipped-user-scope`: confirm the blocks are present in `lazy.settings.json` (`experts.spec.request-router`, at least one `review.classes[]` entry covering `requests/*.md`; and `routines.spec.request-open` / `routines.spec.request-apply` unless the daemon gate skipped them). Note: no `experts.spec.request-apply` entry — the apply routine is `command:`-shape, not expert-based.
- Report a summary line per task in the canonical Step list, plus:
  - Scope detected
  - Plugin version/commit from `installed_plugins.json` (`<version>` / `<gitCommitSha>`)
  - Consumer dir state from Step 3
  - Step 4 outcome (`language-on-record:<code>`, `language-default-en`, or `language-set:<code>`)
  - Step 5 outcome (`routine-registered`, `routine-already-present`, or `skipped-daemon-disabled`)
  - Step 6 outcome (`wiring-applied:<N>`, `wiring-applied:<N> (daemon-disabled)`, or `skipped-user-scope`)
  - Step 7 outcome (`registered: <compound-key>` or `skipped-per-user-choice`)

## Step 10: Log the run

Log to `./.logs/claude/spec.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then `Write` tool. Never chain with `&&`.

## Failure modes

- **`/spec.install` aborts: plugin not installed** — `lazycortex-specs@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-specs@lazycortex": true` to `enabledPlugins` in your `settings.json` and restart Claude Code, then re-run.
- **`/spec.install` reports `routine spec.gate-tick already registered`** — a prior install already wired the routine → accept the `routine-already-present` outcome; re-running never overwrites it. To change its shape, run `/lazy-routine.unregister spec.gate-tick` first, then re-run install.

## Notes

- **Idempotent**: running this skill multiple times is safe. Every write follows the File-sync policy — absent → write, cleanly mergeable → merge silently, genuine conflict → the only case that asks. The consumer dir is never recreated and orphaned entries are kept, never deleted.
- **Re-run after `/plugin update`**: this skill creates only the one consumer dir (no rule copies). After a plugin update, the plugin's reference docs and templates refresh in cache automatically — no resync needed. Steps 5 and 6 surface any new wiring requirements on the next run.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Per-product overrides** are NOT created by this skill — they live under `.claude/templates/spec.<category>/<compound-key>/` (one folder per category that the operator wants to customize), scaffolded by `spec.product-config` when the user opts into customization.
- **User-scope skip**: Step 6 (request runtime wiring) is a project-scope-only step. Request files live in `<vault-root>/requests/` per-vault; wiring at user scope would point the daemon at the wrong path. The skill detects user scope at Step 1 and silently skips Step 6 (`skipped-user-scope`).
- **Daemon-disabled skip**: Steps 5 and 6 read the tracked `daemon.enabled` flag; when the project has opted out of the daemon, the routine registrations are skipped silently (`skipped-daemon-disabled`). `lazy-core.install` owns the first-time daemon question — this skill never re-asks it.
</content>
</invoke>
