---
name: lazy-core.audit
description: "Run when the operator asks why sessions start heavy, what is loaded into context at startup, or whether this repo's skills / agents / rules follow the authoring and logging rules. Read-only, reports only — the sibling `/lazy-core.doctor` is the one that checks cross-artifact consistency and offers fixes."
allowed-tools: Read, Write, Glob, Grep, Bash(wc *), Bash(command -v python3), Bash(python3 --version), Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(test *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Agent
---
# Context Audit

Coordinator skill. Runs inline logging compliance checks, then dispatches four **Explore** subagents in parallel to measure context weight and hygiene. Read-only — no changes made.

This skill follows the shared audit form in `plugins/claude/lazycortex-core/references/lazy-core.audit-contract.md` — `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.audit-contract.md` in an install: read-only, the four severity words, the repair route standing in the finding line itself, no estimate of what a repair would save. Read it before adding or rewording a check here. The one file this skill writes is its own run log under `./.logs/claude/lazy-core.audit/`, which `lazy-log.logging` mandates for every run.

Read `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` before dispatching for the coordinator pattern.

**CRITICAL PATH RULE** (applies to every dispatched agent): `$HOME/.claude/` is protected from Bash access. Agents must use ONLY Glob and Read under `$HOME/.claude/`. `wc -c` via Bash is allowed ONLY for paths under the project root.

**Path expansion** (mandatory): Glob and Read do **not** shell-expand `~` or `$HOME`. Before any Glob/Read targeting a home-relative path, run `Bash(echo $HOME)` once and substitute the result (or read the absolute home path from the session env block). A literal `~/.claude/rules/*.md` or `$HOME/.claude/rules/*.md` passed to Glob will match nothing and silently report "empty".

**Size estimation**: for Read-measured files use `size ~ lines × 45 bytes`; for `wc -c` use exact bytes.

## Finding shape

Every finding this skill emits carries three fields: **severity**, **path** (the artifact the finding is about), and **resolution**.

Severity is the shared vocabulary of `lazy-core.audit-contract.md` and nothing else: `PASS` (the check ran and found nothing wrong), `INFO` (a measurement or observation needing no action), `WARN` (a divergence), `FAIL` (a violation). Each finding line also names its own repair route — the route is never lifted into a separate section at the end of the report.

Resolution says what kind of change the finding implies, and `/lazy-core.checkup` reads it to decide whether to offer a fix-flow at all:

- **`mechanical`** — the repair follows unambiguously from what the check already read; there is no second defensible answer. Checks: L1 consumer-scope copy absent, L2, L3; Agent B scaffold-registry `plugin_root_var`, path hygiene, Python runtime FAIL, rule-writing 3 (inline-array `paths:`) and 9 (missing template pointer), model routing 4 (orphans) and 5 (gaps), audit-shape S4 (contract not named); Agent D D3, D4, D10 index desync, D11 rows other than `not_a_symlink` / `source_missing`, D13.
- **`selective`** — a repair exists, but which one is right is the operator's call. Checks: L1 missing plugin-source `description:`, L4; Agent A oversize rule and oversize `MEMORY.md`; Agent B MCP enablement, scaffold-registry `parse_error` / `bad_shape` / `glob_overlap` / `missing_template` / `orphan_key`, naming hygiene, every skill-writing, agent-writing and rule-writing check not listed as mechanical above, dirty-tree write-without-commit, reference-writing 11 and 12, audit-shape S1–S3; Agent D D1, D2, D5, D7, D8, D9, D11 `not_a_symlink` / `source_missing`, D12, D14, D15, D16.
- **`report-only`** — a measurement or an observation with no change expected. Checks: every sizing row and `total_kb` line from Agents A and B, the Python-runtime `[INFO]` line, model routing 1 (`_version` provenance), 3 (merged entries) and 7 (env var), every visible-waiver `[INFO]` (execution-discipline, `size-waiver:`, dirty-tree), Agent C H1 and H2 (both clear at the next publish bump — there is no manual route), D1's experts-count line, D3's absent-section lines, and D10's persona-but-empty line.

A check added here is assigned a resolution in the same edit; an unassigned finding counts as `report-only` downstream, which silently drops a real repair out of `/lazy-core.checkup`'s question.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Inline logging compliance checks`
   - `Phase 2 — Dispatch parallel scans`
   - `Phase 3 — Render (Report)`
   - `Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Inline logging compliance checks

Absorbed from the retired `lazy-log.audit` skill. These four checks run inline (no subagent dispatch) before Phase 2's parallel scan. Record findings in a local list for inclusion in the Phase 3 render.

Severity vocabulary: the four words from **Finding shape** above — `PASS` / `INFO` / `WARN` / `FAIL`. A check that ran clean emits `PASS`; the Phase 3 render folds the `PASS` lines into the section's summary line.

### L1 — Logging rule presence

Check two paths: `${CLAUDE_PLUGIN_ROOT}/rules/lazy-log.logging.md` (plugin source) and at least one consumer scope.

- Read `${CLAUDE_PLUGIN_ROOT}/rules/lazy-log.logging.md`. If absent → `[FAIL] logging rule missing from plugin source at ${CLAUDE_PLUGIN_ROOT}/rules/lazy-log.logging.md`.
- Glob `.claude/rules/lazy-log.logging.md`. If absent, also Glob `$HOME/.claude/rules/lazy-log.logging.md` (expand `$HOME` first via `Bash(echo $HOME)`). If neither consumer path exists → `[WARN] lazy-log.logging.md not installed in any consumer scope (.claude/rules/ or ~/.claude/rules/) — run /lazy-core.setup`.
- If the rule file at the plugin source path exists but has no YAML frontmatter `description:` key → `[WARN] lazy-log.logging.md plugin source has no frontmatter description | ${CLAUDE_PLUGIN_ROOT}/rules/lazy-log.logging.md`.

### L2 — `.logs/` and `.runtime/` directory state

- `Bash(test -d .logs && echo present || echo absent)`. If absent → `[WARN] .logs/ directory missing at repo root — run /lazy-core.setup to bootstrap`.
- `Bash(test -d .runtime && echo present || echo absent)`. If absent → `[WARN] .runtime/ directory missing at repo root — run /lazy-core.setup to bootstrap`.

### L3 — `.gitignore` covers `.logs/` and `.runtime/`

- Read `.gitignore`. If absent → `[WARN] .gitignore not found — cannot verify .logs/ or .runtime/ coverage | .gitignore`.
- If present but neither `.logs/` nor `.logs` appears in the file → `[WARN] .gitignore does not exclude .logs/ — commits will include runtime journal | .gitignore`.
- If present but neither `.runtime/` nor `.runtime` appears in the file → `[WARN] .gitignore does not exclude .runtime/ — commits will include daemon state.json | .gitignore`.

### L4 — `logging-waiver:` value validation

Glob `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`, `.claude/commands/*.md`. For each file, parse YAML frontmatter and inspect `logging-waiver:` if present:

- `[FAIL]` if value is the empty string, the literal `true`, or the literal `yes`.
- `[FAIL]` if the key is present but no value follows (key + colon with empty mapping value).

Valid concrete strings → no finding.

## Phase 2 — Dispatch parallel scans

Dispatch these four Explore agents **in a single message with four Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Each returns the structured report from `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md`. Budget: "Report under 350 words".

Severity vocabulary for every dispatched agent: the four words from **Finding shape** above and no others. `PASS` (the check ran clean — carried as a count, not a printed line) / `INFO` (measurement row or visible waiver, including dirty-tree waiver acknowledgements) / `WARN` (divergence or heuristic flag, including dirty-tree write-without-commit findings) / `FAIL` (structural violation — Agent B compliance checks across skill-writing, agent-writing, hook-writing, and rule-writing: missing preamble, invalid waiver, "Optional" heading, missing rule frontmatter or scope, oversize rule, code block > 10 lines, `AskUserQuestion` inside agent body, hook script missing shebang, hook script crashing on malformed stdin). Every finding names its repair route in its own line; no agent returns a recommendations block.

### Agent A — always-loaded context

Measure everything that loads at conversation start. Include these sources as one `[INFO]` finding per source, sorted by size desc:

- **Global CLAUDE.md** (`$HOME/.claude/CLAUDE.md`) — Read, estimate size.
- **Project CLAUDE.md** (`CLAUDE.md`) — Read, estimate size.
- **Global rules** (`$HOME/.claude/rules/*.md`) — Glob + Read. If the directory is a symlink, resolve and follow it. Only rules **without** a `paths` frontmatter field count as always-loaded; rules with `paths` are on-demand and belong to Agent B.
- **Project rules** (`.claude/rules/*.md`) — `wc -c` via Bash. Same `paths` filtering rule.
- **Memory index** (`$HOME/.claude/projects/*/memory/MEMORY.md`) — Read, estimate size.

Also emit `[WARN]` findings for:

- Any rules file > 3 KB (suggest `/lazy-core.slim-context`).
- `MEMORY.md` > 5 KB (suggest consolidation).

Include a `total_kb` line in the summary block.

### Agent B — on-demand assets, MCP, path + naming hygiene

Scope covers everything not loaded at startup, plus hygiene grep work.

**On-demand sizing** (one `[INFO]` per source):

- Agents (`.claude/agents/*.md`) — `wc -c` via Bash.
- Project commands (`.claude/commands/*.md`) — `wc -c` via Bash.
- Global commands (`$HOME/.claude/commands/*.md`) — Glob + Read.
- Project skills (`.claude/skills/*/SKILL.md`) — `wc -c` via Bash.
- Global skills (`$HOME/.claude/skills/*/SKILL.md`) — Glob + Read.
- Memory files (individual `$HOME/.claude/projects/*/memory/*.md` except `MEMORY.md`) — Glob to count.
- On-demand rules (rules files with a `paths` frontmatter field).
- References (`.claude/references/*.md`, `$HOME/.claude/references/*.md`, `plugins/claude/*/references/*.md`) — `wc -c` via Bash.

Include a `total_kb` line for on-demand sources in the summary block.

**MCP enablement** — read `$HOME/.mcp.json`, `.mcp.json`, `$HOME/.claude/settings.json`, `$HOME/.claude/settings.local.json`, `.claude/settings.json`, `.claude/settings.local.json`. Determine mode:

- Mode A: global `enableAllProjectMcpServers: true` → every project `.mcp.json` entry is implicitly enabled; suppress "declared but unused" warnings.
- Mode B: `enableAllProjectMcpServers` false or missing → server enabled only if its name appears in `enabledMcpjsonServers` of project settings.

Emit one `[INFO]` per enabled server. Emit `[WARN]`:

- Mode B only: server in project `.mcp.json` not enabled under any rule above.
- Mode B only: non-empty project `.mcp.json` but no `enabledMcpjsonServers` anywhere.
- Always: name in `enabledMcpjsonServers` with no definition in `.mcp.json` or `$HOME/.mcp.json`.

**Python runtime** — every `lazycortex-*` plugin ships hooks that shebang `python3`, and project hooks invoked as `python3 ...` from `settings.json` rely on the same interpreter. If `python3` is missing or too old, hooks silently fail and the user loses distill-after-commit, settings/public guards, agent-model routing, and autobump. Run two short Bash probes:

- `command -v python3` — empty output → `[FAIL] python3 not in PATH — every hook in .claude/settings.json and every plugin-shipped hooks/*.py will fail to execute; fix: install Python ≥ 3.12 and re-run /lazy-core.install.`
- `python3 --version 2>&1` — parse `Python X.Y.Z`. Floor is **3.12** (shipped Python uses `pathlib` semantics that shifted in 3.12; per-plugin `<ns>.install` skills inherit the floor and must NOT re-probe). Emit:
  - `[INFO] python3 path=<path> version=<X.Y.Z>` when found and ≥ 3.12.
  - `[FAIL] python3 version <X.Y.Z> below floor 3.12 — every shipped hook fails on startup. Run /lazy-core.install to walk the install path.` when found and < 3.12.

Skip both probes silently if neither runs (sandbox restriction); the renderer treats the section as absent.

**Scaffold registry validation** — for each in-scope `lazy-core.scaffold.md` (`.claude/rules/`, `$HOME/.claude/rules/`), run `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" scaffold validate --registry <path>` (`${CLAUDE_PLUGIN_ROOT}` is this plugin's own root, so in a checkout that authors the plugin that is `plugins/claude/lazycortex-core/` and in a consumer the installed copy; skip silently if the file is missing). Map each returned finding: `parse_error` / `bad_shape` / `plugin_root_var` → `[FAIL]`; `glob_overlap` / `missing_template` / `orphan_key` → `[WARN]`. The primitive's deterministic parse is the single source of structural truth — do not also eyeball the YAML.

**Path hygiene** — grep every project-level config file (`.claude/agents/*.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `CLAUDE.md`) and emit `[WARN]` for:

- `/Users/` or `/home/` — hardcoded absolute paths.
- `<project>/` prefix — should be relative.
- `~/Dropbox/` or other user-specific home subdirectories.
- `$HOME/.claude/` used for items that are actually project-local (project agents / rules / settings) instead of relative `.claude/`.

**Exclusions** (suppress the match — do not emit a WARN if any gate matches):

- **Inside backticks on the line** — `` `~/Dropbox/` ``, `` `/Users/foo` ``, etc. Backticked strings are code/pattern literals, not operational paths the file uses at runtime.
- **Inside a fenced code block** (between ` ``` ` fences) where the line or the block's preceding prose contains `e.g.` — illustrative examples in documentation, not operational config.
- **Any line containing `e.g.`** — the author has explicitly marked the path as an example.

Emit WARN only when the match survives all three gates.

**Naming hygiene** — for `.claude/skills/*/`, `.claude/agents/*.md`, `.claude/commands/*.md`, `.claude/hooks/*`, `.claude/rules/*.md`: filename (or directory name for skills) must use dot-namespace (`namespace.name`). `[WARN]` for anything missing a dot (e.g., `logging.md` → `<namespace>.logging.md`).

**Skill-writing compliance** — see `lazy-core.skill-writing`. File set: `.claude/skills/*/SKILL.md`, `plugins/claude/*/skills/*/SKILL.md` (commands exempt from the preamble check). Eight checks:

1. **Preamble present** — grep each file for `^## Execution discipline (MANDATORY`. Absent AND no `execution-discipline-waiver:` in frontmatter → `[FAIL]`. Frontmatter carries a non-empty `execution-discipline-waiver: "<reason>"` string → `[INFO]` with the waiver reason (visible, not silent). Frontmatter carries `execution-discipline-waiver: true` / `yes` / `""` → `[FAIL]` (invalid waiver).
2. **No "Optional" in phase/step headings** — grep for `^##+ .*[Pp]hase.*[Oo]ptional`, `^##+ .*[Ss]tep.*[Oo]ptional`, and any `^### .*[Oo]ptional`. Match → `[FAIL]`.
3. **Narrative padding (heuristic)** — grep the body (exclude frontmatter) for the denylist: `\bv\d+\.\d+\.\d+`, `user had to`, `we got burned`, `in a past session`, `in a previous run`, `user had to patch`. Match → `[WARN]` with the offending line. Final decision is the author's — heuristic, not structural.
4. **Valid `lazy_setup_phase` value** — grep frontmatter for `^lazy_setup_phase:`. Value outside `{pre-install, per-plugin, post-install}` → `[WARN]` with the offending value. See `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.setup-phases-contract.md` for the contract.
5. **`description:` present** — **Commands are in scope for this check**, unlike the preamble check above: widen the file set to `.claude/commands/*.md` and `plugins/claude/*/commands/*.md`. Grep each file's frontmatter for `^description:`. Absent → `[FAIL]`. Judging the description's *content* against the trigger shapes is deliberately NOT an audit check — that reading happens at authoring time per `lazy-core.skill-writing § 8` and `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.description-triggers.md`, not on every audit pass.
6. **`allowed-tools` missing `Agent`** — grep frontmatter for `^allowed-tools:`. When present and `Agent` is absent from the list → `[WARN]` (`lazy-core.skill-writing § 9` — mandatory member when the field is used at all). A skill with no `allowed-tools:` field is untouched (inherits the caller's tools, per operator decision). Never flag `Agent`'s presence.
7. **Research-marker semantics** — see `lazy-core.skill-writing § 10`. Judgement call (read the skill, don't just grep): a skill whose contract is search/pull-shaped (a mode that returns a bounded knowledge slice — a query over a map, tree, dictionary, or index) but carries neither `research: true` frontmatter nor the word "research" in its `description:` → `[WARN] skill has research-skill shape without the research marker | <path>`. A skill carrying the marker (frontmatter or description word) whose body documents no query-mode contract (no invocation shape returning a bounded slice rather than the whole document) → `[WARN] research marker present but no query-contract documented | <path>`.
8. **Question context** — see `lazy-core.skill-writing § 11`. Widen to `.claude/commands/*.md` and `plugins/claude/*/commands/*.md`. For every body site that instructs the agent to raise an `AskUserQuestion` (skip `allowed-tools:` lists, negations such as "do NOT open an AskUserQuestion", and mentions of other skills), check that a `Context (print before asking):` block precedes it, or — for a policy paragraph describing a class of question — that the paragraph names the four items (where, found, why asking, answers). Missing → `[WARN] AskUserQuestion site without a context block | <path>:<line>`.

**Agent-writing compliance** — see `lazy-core.agent-writing`. File set: `.claude/agents/*.md`, `plugins/claude/*/agents/*.md`. Checks:

1. **Frontmatter complete** — `name`, `description`, `tools` all present. Missing any → `[FAIL]`.
2. **Preamble present** (for multi-phase agents) — same check as skill-writing §1. Agents with `## Phase N` or `## Process` sections must carry the preamble OR a valid `execution-discipline-waiver:` string. Same FAIL/INFO vocabulary.
3. **No `AskUserQuestion` in agent body** — grep for `AskUserQuestion` outside fenced code/frontmatter. Match → `[FAIL]` (agents have no user channel).
4. **Tool allowlist hygiene** — `tools: ["*"]` → `[WARN]` (unless a justification comment on the same line). `tools:` present but missing `Agent` → `[WARN]` (`Agent` is a mandatory member per `lazy-core.agent-writing § 5`); never flag its presence.
5. **No "Optional" in phase/step headings** — same as skill-writing §2 → `[FAIL]`.
7. **Narrative padding (heuristic)** — same denylist as skill-writing §3 → `[WARN]`.

**Audit-shape conformance** — see `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.audit-contract.md`. File set: `plugins/claude/*/skills/*.audit/SKILL.md` (every audit this repo ships, this skill included) plus `.claude/skills/*.audit/SKILL.md` when the consumer authors one. Four checks:

**S1 — severity words inside the shared vocabulary.** Collect every token standing in a severity slot: a bracketed token (`[WARN]`), and an uppercase word opening a finding or outcome (directly after `→`, or at the head of a finding line, as in `FAIL agent-missing: …` / `PASS <N> roles resolve`). Any such token outside `PASS` / `INFO` / `WARN` / `FAIL` → `[FAIL] audit <name> uses severity word <token> outside the shared vocabulary | <path>:<line>`; `fix: reword the finding to one of PASS / INFO / WARN / FAIL per lazy-core.audit-contract.md`. Uppercase words that are not in a severity slot (`MANDATORY`, `TODO`, a shouted clause in prose) are not severities and are never flagged.

**S2 — read-only.** Three grounds, each on its own finding:

- A body site instructing a `Write`, `Edit`, or `NotebookEdit` whose target is anything other than the skill's own run log under `./.logs/claude/<name>/` → `[FAIL] audit <name> writes <target> — an audit reports, it does not repair | <path>:<line>`; `fix: move the write into the repair skill the finding names, and leave the audit naming the route`.
- An apply-style flag or mode on the audit's **own** invocation (`--apply`, `--fix`, a `fix` argument the skill itself executes) → `[FAIL] audit <name> declares the apply-style flag <flag> | <path>:<line>`; `fix: drop the flag; the repair is a separate run the operator starts`. A flag named in a repair route the operator runs elsewhere (`… doctor <scope> --apply`) is the route, not the audit's own flag, and is never flagged.
- `AskUserQuestion` in `allowed-tools:`, or a body site instructing this skill to raise one → `[FAIL] audit <name> asks the operator a question | <path>:<line>`; `fix: delete the question and its step; an audit ends at its report`. Skip the exclusions `lazy-core.skill-writing § 11` already names — negations, mentions of another artifact — and skip a line whose subject is the token itself (a check that greps for `AskUserQuestion` names it without raising one).

**S3 — no separate recommendations section in the report.** Any heading whose text names recommendations, saving opportunities, or repair routes (grep `^#{2,}\s.*\b([Rr]ecommend|[Ss]aving|[Oo]pportunit|[Rr]epair route)`) → `[WARN] audit <name> lifts repair routes into the section "<heading>" | <path>:<line>`; `fix: move each line into the finding it belongs to, and delete the section`.

The check is about what the operator reads. A section the skill states is an internal lookup, used while composing finding lines and never rendered into the report, is not a finding — the section body must say so in its own first sentence for the carve-out to apply.

**S4 — the shared form is named.** The body must reference `lazy-core.audit-contract.md`. Absent → `[WARN] audit <name> does not name the shared audit contract | <path>`; `fix: add one line to the skill body stating it follows ${CLAUDE_PLUGIN_ROOT}/references/lazy-core.audit-contract.md`.

**Model routing** — load both settings files via the core CLI (the verb goes through `bin/lazy_settings.py`, so pending migrations apply); each call prints the section as JSON:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get agent_models)
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get agent_models --home)
```

Missing files are a silent no-op — the verb prints a stub with `_version` intact. Do not add a manual file-existence guard. Build a merged-with-provenance view of `agent_models`:

1. **Files present / `_version` provenance** — emit `[INFO]` per scope: `lazy.settings.json scope=project path=<path> agent_models._version=<N>` or `lazy.settings.json scope=project (missing)`; same for `global`. Surfacing `_version` makes settings-version drift visible — e.g. a global file at `agent_models._version: 1` while the project file is at `_version: 2` after a migration.
2. **No config anywhere** — if BOTH scopes are missing (both returned only the stub `_version` key and nothing else), emit `[WARN] no lazy.settings.json found (project: <path>, global: <path>) — agent routing disabled. Run /lazy-core.slim-context to create and fill.` Skip the remaining checks (merged view / orphans / gaps / invalid values) since there is nothing to validate.
3. **Merged entries** — for every dispatch-string key across both scopes, emit one `[INFO]`: `agent_models <group>.<key> = <value> (<provenance>)`. Provenance is `project`, `global`, or `project, overrides global=<other>` when both scopes carry the same key with different values. Group entries together in the report render by their top-level group name. Skip any top-level key whose value is not a dict (e.g. `_version: int`) — only group sub-dicts carry dispatch mappings. (Filter by shape, not by name, because `_user` / `_project` / `_builtin` are legitimate group-name keys that share the underscore prefix.)
4. **Orphans** — any key in either scope that does NOT resolve to a discovered agent (see Agent discovery below). Finding: `[WARN] orphan agent_models entry: <group>.<key> (<scope>)`.
5. **Gaps** — discovered agents with no entry in any scope (exclude agents explicitly set to `"default"` in either scope — those are explicit decisions, not gaps). Finding: `[INFO] no agent_models entry for <dispatch-string> (from <source>) — run /lazy-core.slim-context to fill`.
6. **Invalid values** — any value not in `{"haiku", "sonnet", "opus", "default"}`. Finding: `[WARN] invalid value <x> for <group>.<key> (<scope>)`.
7. **Env-var status** — emit `[INFO]` with `LAZY_AGENT_MODEL_FLOOR=<value>` and a tier-order note (`haiku < sonnet < opus`), else `LAZY_AGENT_MODEL_FLOOR=(unset)`.

**Agent discovery (shared helper — used by audit, optimize, doctor)**. Deduped by full dispatch string:

1. **Built-ins** — hardcoded list: `Explore`, `Plan`, `general-purpose`, `statusline-setup`. Group: `_builtin`. Dispatch string: bare name.
2. **User-authored, global** — `$HOME/.claude/agents/*.md`. Group: `_user`. Dispatch string: bare filename stem.
3. **User-authored, project** — `./.claude/agents/*.md`. Group: `_project`. Dispatch string: bare filename stem. (Project entries shadow global entries of the same stem — both still listed separately with provenance.)
4. **Plugin-shipped** — for every plugin name `installed_plugins.json` records (plus, in a repo that authors plugins, every `plugins/claude/<name>/` carrying a manifest), glob `<root>/agents/*.md` where `<root>` is what `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" plugin-root <name>` prints — the authoring repo's tree first, then the exported dir, then the newest cached version; a walk of `$HOME/.claude/plugins/cache/**` alone never sees an agent added since the last publish. Group: **domain** derived from plugin name via the domain-extraction rule (first `-`-delimited segment, or full name if no `-`). Dispatch string: `<plugin-name>:<stem>`. **Install-scope filter:** the cache is machine-global — keep a plugin's agents only when `~/.claude/plugins/installed_plugins.json` shows it installed at `user` scope, or at `project` scope with a `projectPath` equal to the current repo root; a plugin installed only into another project's scope is not part of this repo's surface and its agents are never flagged missing here.

**Rule-writing compliance** — see `lazy-core.rule-writing`. File set: `.claude/rules/*.md`, `$HOME/.claude/rules/*.md`, `plugins/claude/*/rules/*.md`. **Exclude** `**/templates/**/*-template.md` from every check below — templates are skeletons, not rules; their placeholder frontmatter and example clauses would otherwise misfire. Checks:

1. **Frontmatter present** — YAML frontmatter with at minimum `description:`. Absent → `[FAIL]`.
2. **Scope or waiver** — frontmatter must carry EITHER `paths:` (YAML block-list of globs, per Claude Code docs) OR `always_loaded: "<reason>"`. Neither present → `[FAIL]`. `always_loaded: true` / `always_loaded: ""` → `[FAIL]` (invalid waiver).
3. **Canonical `paths:` shape** — when `paths:` is present, it MUST be a YAML **block-list** (one `- "<glob>"` per line). Inline-array shape (`paths: ["<glob>", ...]`) → `[FAIL]`. Detection: any line in the frontmatter matching `^paths:\s*\[`. This includes single-element inline arrays (`paths: ["x"]`); the canonical form has the `paths:` key on its own line followed by hyphen-prefixed entries. Per `lazy-core.rule-writing § 1`. Finding text: `non-canonical paths: shape — inline-array form, must be block-list per code.claude.com/docs/en/memory#path-specific-rules`.
4. **Size budget** — `always_loaded:` rule > 3 KB → `[FAIL]`. `paths:`-scoped rule > 10 KB → `[WARN]`. `paths:`-scoped rule > 25 KB → `[FAIL]`.
5. **Code-block size** — any fenced code block > 10 lines → `[FAIL]`. **Exemption** per `lazy-core.rule-writing § 3`: fenced `yaml`, `json`, or `toml` blocks that constitute the rule's primary payload (e.g. a registry or schema the rule exists to publish) are not subject to the cap. Heuristic for "primary payload": the rule's prose introduces the block as authoritative content (phrases like "registry", "schema", "canonical mapping") rather than as an example or illustration.
6. **Dot-namespace filename** — filename without dot separator → `[WARN]`.
7. **Broken artifact reference** — slash-commands, subagent-types, rule filenames, `references/…` paths, hook paths, `skills/<name>/SKILL.md` paths that don't resolve on disk → `[WARN]`. Markdown section headings (`## Phase 2.5`) are NOT checked.
8. **Narrative padding (heuristic)** — same denylist as skill-writing §3 → `[WARN]`.
9. **Authoring contract without template** — a rule counts as an *authoring contract* when its filename matches `*.writing.md` OR its body contains a heading line matching `^##\s.*[Aa]uthoring`. Authoring contracts MUST reference a template path under `<plugin>/templates/`; detection: grep the body for `templates/.*-template\.md`. No match → `[WARN]`. Finding text: `authoring rule has no template reference — Claude composing a new artifact from scratch can't see the contract; add a **Template:** pointer per lazy-core.scaffold`.

**Dirty-tree write-without-commit (cross-cutting)** — applies to skill/command bodies, agent bodies, and hook scripts in scope:

10. **Dirty-tree write-without-commit** — for every skill/command body, agent body, and hook script in scope, scan for write paths and verify each is paired with a commit:

    - **Write paths to flag:** Markdown skill/agent/command bodies that invoke the `Write`, `Edit`, or `NotebookEdit` tools without an accompanying `mcp__git__git_commit` / Bash `git commit` reference in the same file. Python source bodies (`.py` files under hooks or skill `bin/` dirs) where `.write_text(`, `.write(`, or `subprocess.run(["git", ..., "add"`, etc., calls have no matching `subprocess.run(["git", ..., "commit"`, etc., reference.
    - **Severity:** `[WARN]` by default. Downgrade to `[INFO]` when the file declares `dirty-tree-waiver: "<reason>"` in frontmatter (skills/agents/commands) or `# dirty-tree-waiver: <reason>` as a comment header (hooks/scripts).
    - **Reference:** `lazy-core.skill-writing § 6` (canonical clause) and `lazy-core.hook-writing § 4` (hook-specific framing).
    - **Heuristic note:** the check is a regex/grep heuristic, not a static analyzer. False positives (e.g., a write that is committed by a parent caller in a different file) can be silenced via the waiver. Author judgement governs.

**Reference-writing size budget** — see `lazy-core.reference-writing § 4`. File set: the same one already measured under **On-demand sizing** above (`.claude/references/*.md`, `$HOME/.claude/references/*.md`, `plugins/claude/*/references/*.md`); reuse those `wc -c` byte counts rather than re-measuring.

11. **Size budget** — reference > 50 KB → `[FAIL]`; > 25 KB → `[WARN]`. Finding text: `reference <N> KB over the <25|50> KB budget — split per lazy-core.reference-writing § 4.1, or declare size-waiver: when the file is genuinely read whole`.
12. **`size-waiver:` honoured** — read each reference's frontmatter *before* emitting a size finding. A file carrying `size-waiver: "<reason>"` is **never** reported over budget at any size: emit `[INFO] <path> <N> KB — size waived: <reason>` instead, so the real size stays visible while the finding stands down. `size-waiver: true` / `size-waiver: ""` → `[FAIL] invalid size-waiver value — an empty or boolean waiver waives nothing (lazy-core.reference-writing § 4.2)`, and the underlying size finding is emitted as normal. The waiver covers the size budget alone; every other check still applies to a waived file.

### Agent C — help-doc coverage and staleness

Per-plugin scan of `plugins/claude/<plugin>/` for help-doc completeness against `## Scenarios` and chapter staleness against source-skill mtime. Both checks emit `[WARN]` only — there is no manual fix path; chapters are regenerated by the publish pipeline at the next version bump.

Discover plugins: `plugins/claude/*/.claude-plugin/plugin.json`. For each plugin:

#### Check H1 — Help-doc scenario coverage

For every plugin under `plugins/claude/<plugin>/`:

- Read each bullet under `## Scenarios` in `plugins/claude/<plugin>/README.md`. Skip the plugin if the README has no `## Scenarios` section.
- For each bullet, look for a corresponding `plugins/claude/<plugin>/help/walkthroughs/<slug>.md`. Slug-match: lowercase the first 4–6 keywords of the bullet, hyphenate, strip non-alphanumeric. A walkthrough chapter also matches when its frontmatter `summary` substring-matches the bullet text.
- Missing match → `[WARN]` with detail `scenario "<bullet>" has no walkthrough chapter in plugins/claude/<plugin>/help/walkthroughs/`.

#### Check H2 — Help-doc staleness

For every chapter under `plugins/claude/<plugin>/help/**/*.md`:

- Read the chapter's frontmatter `last_regen` and `source_skills`. Skip the chapter if either field is absent.
- For each skill in `source_skills`, find the most recent commit mtime via `git log -1 --format=%cI -- plugins/claude/<plugin>/skills/<skill>/SKILL.md`. Also include `plugins/claude/<plugin>/README.md`'s mtime.
- If any source's mtime is newer than `last_regen` → `[WARN]` with detail `chapter <path> is stale; clears at next publish bump for <plugin>`.

These warnings are advisory — there is no manual fix path. The publish pipeline regenerates chapters at the next version bump (subject to its patch-bump short-circuit). The mtime probe uses `git log -1` and therefore detects only *committed* edits; uncommitted local changes do not register as stale here.

Severity vocabulary: `INFO` (advisory note about a passing chapter or scenario, optional) / `WARN` (H1 missing chapter, H2 stale chapter). Never emit `FAIL` from this agent.

### Agent D — expert runtime

Scope: `lazy.settings.json[experts]`, the flat `lazy.settings.json[daemon]` and `lazy.settings.json[routines]` sections, `.jobs/` directories, runtime daemon liveness. Severity vocabulary: `INFO` (informational, non-actionable) / `WARN` (advisory or degraded state) / `FAIL` (structural violation or unresolvable reference).

**CRITICAL PATH RULE** applies: no Bash under `$HOME/.claude/`. Expand `$HOME` once via `Bash(echo $HOME)` then substitute.

**Path layout constant**: plugin cache lives under `$HOME/.claude/plugins/cache/<registry>/<plugin>/<version>/bin/<plugin>`.

Perform these 16 sub-checks in order:

**D1 — `lazy.settings.json[experts]` schema**

Read `.claude/lazy.settings.json`. If the file is absent or the `experts` section is missing/empty (after stripping `_version`): emit `[INFO] lazy.settings.json[experts] absent — no experts configured` and skip D2, D5 (D4 runs regardless — routines can exist without experts). If the file is present but not valid JSON: `[FAIL] lazy.settings.json is not valid JSON | .claude/lazy.settings.json`.

For every top-level key that is not `_version` (filter by shape — skip keys whose value is not an object, so `_version: int` is excluded without name-checking):

- Verify the expert entry has all three required fields: `agent`, `git_author.name`, `git_author.email`. Missing any field → `[FAIL] expert <key> missing required field(s): <list> | lazy.settings.json[experts]`. Note: `protocol` is NOT an expert field — protocols are declared by routines, not by experts. Optional fields: `aspects` (list of `<plugin>:<name>-aspect` refs) and `arguments` (dict of `<lowercase_snake>: <json-value>`). Unknown extra fields → `[WARN] expert <key> has unknown field(s): <list>`.

Emit `[INFO] lazy.settings.json[experts]: <N> experts defined` when at least one expert passes.

**D2 — Reference resolution (agent)**

For each expert entry (from D1 that passed schema):

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" resolve-ref '<expert.agent value>' --category agents)
```

The verb prints a JSON list with one `{ref, ok, path, error}` row. Failure (non-zero exit or `ok: false`) → `[FAIL] expert <key>: agent reference '<value>' did not resolve | lazy.settings.json[experts]` (category: logical).

**D8 — Reference resolution (aspects)**

For each expert entry with a non-empty `aspects[]`:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" resolve-ref '<aspect-ref-1>' '<aspect-ref-2>' ... --category aspects)
```

One call per expert; the verb prints a JSON list with one `{ref, ok, path, error}` row per ref and exits non-zero when any row fails. Every row with `ok: false` → `[FAIL] expert <key>: aspect reference '<value>' did not resolve | lazy.settings.json[experts]`.

**D9 — Arguments validation**

For each expert entry carrying `arguments`:

- Every key must match `^[a-z][a-z0-9_]*$`. Mismatch → `[FAIL] expert <key>: arguments-key-invalid: <bad-key> | lazy.settings.json[experts]`. Fix: rename the key.
- Every value must round-trip through `json.dumps`/`json.loads` cleanly (guaranteed since settings is JSON, but re-verified as a sanity check).
- Total stringified `arguments` size: ≥ 4 KiB → `[WARN] expert <key>: arguments payload <N> bytes — consider a source/ file or protocol reference instead of inlining`.

**D10 — Memory hygiene**

For every directory under `.memory/<expert>/` (skip `.tags/` and the global `.memory/.tags/`):

- If the directory's `<expert>` is not a key in `lazy.settings.json[experts]` → `[WARN] .memory/<expert>/ orphan — expert not in lazy.settings.json[experts] | .memory/<expert>/`.
- If the expert IS registered but `aspects[]` lacks `lazycortex-core:lazy-memory.persona-aspect` → `[FAIL] .memory/<expert>/ exists but expert is not marked persona | lazy.settings.json[experts][<expert>].aspects`. Fix options: (a) run `/lazy-memory.mark-persona <expert>`; (b) delete the orphan directory.

For every memory note (`.memory/<expert>/*.md` excluding `.tags/`):

- Required frontmatter present (`title`, `tags`, `type`, `summary`). Missing → `[FAIL] memory note missing required frontmatter: <field> | <path>`.
- Every tag prefixed `memory/`. Unprefixed → `[FAIL] memory note tag missing `memory/` prefix: <tag> | <path>`.
- Note slug matches `^[a-z0-9-]+$`. Mismatch → `[WARN] memory note slug non-canonical (expected lowercase + dashes): <path>`.

For every persona-marked expert with no `.memory/<expert>/` directory:

- `[INFO] expert <key> is persona but has not written memory yet | .memory/`.

For every local tag file (`.memory/<expert>/.tags/<topic>.md`):

- Every note referenced by `../<slug>.md` must exist → `[WARN] tag file references missing note: <slug> | <tag-file>`.
- Cross-check: every note's frontmatter `tags:` that includes `memory/<topic>` must appear in the local tag file → `[WARN] note <slug> carries `memory/<topic>` but is not listed in <tag-file>`. Fix: run `/lazy-memory.index`.

For every global tag file (`.memory/.tags/<topic>.md`):

- Every expert pointer (`../<expert>/.tags/<topic>.md`) must exist → `[WARN] global tag file references missing local file: <expert> | <global-tag-file>`. Fix: run `/lazy-memory.index`.

**D3 — flat `daemon` / `routines` section schema**

The runtime config lives in two flat top-level sections of `lazy.settings.json` — `daemon` (daemon-process settings) and `routines` (the routine map). There is no nested `lazy-core.runtime` object; `runtime_daemon.py` reads these via `load_section(path, "daemon")` / `load_section(path, "routines")`.

Read `.claude/lazy.settings.json`. If absent: `[INFO] lazy.settings.json absent — runtime sections not configured` and skip D3 sub-checks. If present, extract both sections separately. `load_section` returns a `{"_version": <current>}` stub when a section is absent, so a section carrying only `_version` (no other keys) means "not configured" — treat that as INFO/skip, not FAIL:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get daemon)
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get routines)
```

Validate the returned sections (`daemon_version` / `routines_version` below are the `_version` key each returned section carries — the loader stamps the current schema version on it; compare against those, do not hardcode):

- **`daemon` section.** When the section carries only `_version` (no daemon keys), it is not configured — `[INFO] daemon section absent — daemon not configured (git-sync off or routines-only repo) | .claude/lazy.settings.json` and skip the remaining daemon checks. Otherwise:
  - `daemon._version` must equal `daemon_version` (current `CURRENT_VERSIONS['daemon']`, presently 2). Wrong value or absent → `[FAIL] daemon section _version mismatch (expected <daemon_version>) | .claude/lazy.settings.json`.
  - The `daemon` section must contain: `git` (object or null), `polling_interval_sec` (positive int), `cleanup_completed_after` (string or int), `cleanup_failed_after` (string or int), `cleanup_dead_after` (string or int). Any missing key → `[FAIL] daemon section missing key(s): <list> | .claude/lazy.settings.json`.
  - The `git` block must be a non-empty object carrying `base_branch` (the sole required field per `lazy-core.runtime-schema`), whatever `daemon.enabled` says — a manual `/lazy-runtime.tick` commits through the same block. A `null` / absent block → `[FAIL] daemon.git is null — routine commits ride no branch and never sync with origin, so their output stays unpublished in this checkout | .claude/lazy.settings.json`; `fix: re-run /lazy-core.install (Step 9c derives it), or accept Fix L6 in /lazy-core.doctor`. A block present but missing `base_branch` → `[FAIL] daemon.git missing required field base_branch | .claude/lazy.settings.json` with the same fix. A block carrying `base_branch` but no `remote_sync` is **not** a finding — a checkout without an `origin` remote gets exactly that shape, and an operator may drop `remote_sync` deliberately.
  - Each `cleanup_*_after` value must parse as `<N>d` (days), `<N>h` (hours), or a raw non-negative integer (seconds). Anything else → `[FAIL] daemon.<key> has malformed value '<value>' (expected <N>d / <N>h / int) | .claude/lazy.settings.json` — D6 below would otherwise silently fail to parse and apply a default.
- **`routines` section.** The section IS the routines map (each key is a routine name; `_version` is the lone reserved key). `routines._version` must equal `routines_version` (current `CURRENT_VERSIONS['routines']`, presently 2). Wrong value or absent → `[FAIL] routines section _version mismatch (expected <routines_version>) | .claude/lazy.settings.json`. The section must be a dict — a non-dict value → `[FAIL] routines section is not a dict | .claude/lazy.settings.json`.
- When D1 found at least one expert AND `routines` does not contain a `lazy-expert.pump` entry → `[WARN] experts configured but lazy-expert.pump routine absent from routines | .claude/lazy.settings.json`.

**D4 — Routine worker resolvability**

For each key/value in `routines` (skip if D3 found the section absent):

- A routine names its worker in one of two shapes, and the registry validator accepts exactly one of them per routine: a `command` list, or an `expert` name together with a `request` template. Carrying neither, or carrying both, → `[FAIL] routine <name> names neither a command nor an expert + request | .claude/lazy.settings.json` (respectively `... names both a command and an expert`). Do not report a missing `command` on a routine that correctly carries `expert` + `request` — that is the shape every curator and coordinator routine ships in.
- **`command` shape only.** The `command` value must be a plugin bin path under the 4-level plugin cache layout: `$HOME/.claude/plugins/cache/<registry>/<plugin>/<version>/bin/<plugin>`. Resolve `$HOME` via `Bash(echo $HOME)`. Check path existence via `Bash(test -f '<path>' && echo ok || echo missing)`. Missing → `[FAIL] routine <name> command path does not exist: <path> | .claude/lazy.settings.json`.
- **`expert` shape only.** The named expert must be a key in `lazy.settings.json[experts]` (from D1). Absent → `[FAIL] routine <name> dispatches unregistered expert <expert> | .claude/lazy.settings.json`.

**D5 — Orphan jobs**

Glob `.jobs/*/` (one level deep). For each subdirectory name `<expert>`:

- If `<expert>` is not a key in `lazy.settings.json[experts]` (from D1) → `[WARN] orphan job directory .jobs/<expert>/ — expert not in lazy.settings.json[experts] | .jobs/<expert>/`.

**D6 — Stale DONE jobs**

From D3, obtain `cleanup_completed_after` and `cleanup_failed_after` (default to `"7d"` if absent or D3 was skipped). Convert to seconds (parse `<N>d` → `N*86400`, `<N>h` → `N*3600`, int → use directly).

For each job dir under `.jobs/*/` (recurse one more level: `.jobs/<expert>/<job-id>/`): determine status by the presence of marker files written by the pump — `DONE` indicates the expert finished (success or `outcome=error` — read `response.json` to distinguish), `DEAD` indicates the pump killed the process as stuck. For jobs carrying either marker:

```
Bash(find '.jobs/<expert>/<job-id>' -maxdepth 0 -mmin +<threshold-minutes>)
```

`<threshold-minutes>` is the threshold in seconds divided by 60, rounded down. The command prints the path when the directory is older than the threshold (`stale`) and nothing when it is not (`ok`).

Stale → `[WARN] stale completed/failed job not yet cleaned: .jobs/<expert>/<job-id>/ (age > threshold) — pump may not be running | .jobs/<expert>/<job-id>/`.

**D7 — Daemon liveness**

Best-effort check. Three signals (any one passing = alive):

1. `Bash(pgrep -f bin/runner 2>/dev/null && echo running || echo stopped)` → `running`.
2. `Bash(launchctl list com.lazycortex.runtime.$(basename $(pwd)) 2>/dev/null | grep -q '"PID"' && echo running || echo stopped)` → `running`.
3. Compute `5 × max(polling_interval_sec)` across all routines (default 300 s if not available). Find newest `.logs/lazy-core/runtime/*.jsonl` via `Bash(ls -t .logs/lazy-core/runtime/*.jsonl 2>/dev/null | head -1)`. If a file is found, check its mtime: `Bash(find '<newest jsonl>' -maxdepth 0 -mmin +<threshold-minutes>)` prints the path when the file is older than the threshold (`stale`) and nothing when it is fresh (`ok`, → alive); `<threshold-minutes>` is the threshold in seconds divided by 60, rounded down.

If all three signals indicate stopped/stale/absent → `[WARN] runtime daemon appears stale — no pgrep match, no launchctl PID, and no JSONL log line in the last <threshold>s | .logs/lazy-core/runtime/`.

If none of the three probes run (e.g. not on macOS, no runtime configured) → skip silently.

**D11 — External working directories**

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" external-dirs check)
```

The verb prints JSON rows `{path, status, source, gitignored, ignore_rule}`. Empty list → emit nothing (the repo declares no external directories; this is the common case). Otherwise, one finding per non-`ok` row:

- `[FAIL]` status `dangling` / `missing` / `wrong_target` — `external dir <path> is <status> | <source>`; `fix: run /lazy-core.doctor and accept Fix L4, or re-run /lazy-core.install`.
- `[WARN]` status `unconfigured` — `external dirs declared but no source root on record for this checkout | .claude/lazy.settings.local.json`; `fix: re-run /lazy-core.install and answer the external-dirs question`.
- `[WARN]` status `not_a_symlink` — `external dir <path> holds real content, not a link | <path>`; no automatic fix: whether that content is authoritative is the operator's call.
- `[WARN]` status `source_missing` — `external dir <path> has no source at <source> | <source>`; `fix: mount / restore the source, or correct external_dirs.root`.
- `[WARN]` any row whose `ignore_rule` is `absent` — `external dir <path> is not gitignored — linked content would dirty the tree and halt the daemon | .gitignore`; `fix: add /<path> to .gitignore`.
- `[WARN]` any row whose `ignore_rule` is `dir_only` — `external dir <path> is covered by a directory-only ignore rule, which cannot match the symlink the repair plants | .gitignore`; `fix: add /<path> to .gitignore next to the existing <path>/ line — do not replace it`.

Read the verdict from `ignore_rule`, never from `gitignored` alone: a repo whose `.gitignore` already carries `<path>/` reads as not-ignored the moment the slot holds a symlink, and telling that operator to "add `<path>`" points at a line already in the file. The `gitignored` boolean stays in the row for callers that only need "does this dirty the tree"; the two findings above are what the operator acts on.

**D12 — Shared-inbox ownership**

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" inbox-check)
```

The verb prints a JSON list of collisions (exit 1 when non-empty). It reports nothing in a checkout that would never run a daemon (`daemon.enabled` false, or `daemon.run_here` not mapping this host to this checkout) — the runtime's own start-gate already refuses a daemon there, so a shared inbox is uncontested by construction.

- `[FAIL]` kind `inbox_collision` — `<detail>`; `fix: daemon.run_here is a {hostname: checkout-path} map, not a boolean — in the checkout that should NOT run the daemon, point this host's entry at the OTHER checkout's path (or drop this host's key entirely) so the runtime's own start-gate refuses it here` (never auto-applied — which checkout drives it is the operator's decision).

**D13 — Sandbox scope resolves**

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" sandbox-audit --repo-root "$PWD")
```

The verb prints `{path, present, enabled, allow_unsandboxed, missing_read, missing_write}`. `present: false` → emit nothing (no sandbox file, so expert spawns run unconfined). `enabled: false` → emit nothing (confinement is off; the allowlist neither grants nor denies). Otherwise:

- `[FAIL]` `allow_unsandboxed` is not `false` — `sandbox allowUnsandboxedCommands is not recorded false, so a command the sandbox blocks is retried unsandboxed | .runtime/sandbox.settings.json`; `fix: run "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" sandbox-sync --repo-root "$PWD"` when the key is absent (a recorded `true` is the operator's decision — report it, never flip it).
- `[FAIL]` each entry of `missing_write` — `sandbox allowWrite does not cover <path>, which its own entries resolve to | .runtime/sandbox.settings.json`; `fix: run "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" sandbox-sync --repo-root "$PWD"`.
- `[WARN]` each entry of `missing_read` — `sandbox allowRead does not cover <path> | .runtime/sandbox.settings.json`; same fix.

The confinement is checked against the resolved path, so an allowlist entry naming a directory reached through a symlink grants nothing where the data lives: every write there fails with `Operation not permitted` while the recorded config still reads as correct. The sync appends only what is missing and drops nothing.

**D14 — Protocol response envelope**

`outcome` / `error` / `result` belong to `lazy-core.expert-runtime-contract.md`; a protocol declares the *values* `outcome` takes, never a status key of its own. A protocol that prescribes one disarms the runtime silently — the expert obeys the protocol over the system prompt, the response carries no discriminator, and every failure it reports classifies as success. Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" protocol-audit)
```

The verb prints a JSON list `[{path, detail}]`. The audit scans `.claude/references/*-protocol.md` (plus the same directory under `\$HOME/.claude/`), skipping the meta-contract itself. For every entry returned:

- `[FAIL] protocol <name> overrides the response envelope: <detail> | <path>`; `fix: delete the envelope block from the protocol and declare only the outcome values under \`## Outcome by kind\`; the envelope reaches the expert through the runtime contract`.

No entries → emit nothing.

**D15 — Operator git hooks undecided under the runtime**

A hook the operator keeps in this repo is written for a person at a keyboard. Under the runtime the same hook fires on autonomous commits, and one that rewrites files after the commit is assembled leaves a dirty tree the runtime halts on. The daemon therefore runs only the hooks named in `daemon.git.allowed_hooks`; every other one is silently absent from its filtered directory. Silently is the problem — an operator who adds a guard hook expecting it to gate the daemon's commits gets no signal that it never ran.

The filtered hook directory is the routine subprocess's, so this applies to a manually ticked checkout exactly as to a supervised one; `daemon.enabled` does not gate it. Resolve the operator's hook directory — `core.hooksPath` when set (relative values resolve against the repo root), else `<git-common-dir>/hooks` — and list the executable files in it, ignoring `*.sample`.

- `[WARN]` per executable hook whose filename is absent from `daemon.git.allowed_hooks` — `operator hook <name> does not run under the daemon | <hooks-dir>/<name>`; `fix: add "<name>" to daemon.git.allowed_hooks, or leave it out deliberately — the daemon runs no unlisted hook`.

A hook the plugin family itself installs is still reported: whether a shipped shim should run under the daemon is the operator's decision, not the plugin's, and the shim's own allow-list check is a second, independent gate.

No hook directory, or every hook already listed → emit nothing.

**D16 — Review-class self-validation**

A review class whose validator shares the main writer's expert key proves nothing — the same persona checks its own work. Read `lazy.settings.json[review].classes` (absent or empty → emit nothing). For each class entry: collect the expert names under `experts.main[].name` and the names under `experts.validation.*.name`; a non-empty intersection → `[FAIL] review class <class> is validated by its own main writer <key> | .claude/lazy.settings.json[review.classes]`; `fix: point the validation slot at a different expert, or drop the slot — a class with no validators is legal`. Expert composition is operator content — report only, never auto-repair.

### Structured report shape (Agents A, B, C — unchanged)

```
## scan: lazy-core.audit/help-docs

### help_doc_coverage
- [WARN] scenario "<bullet>" has no walkthrough chapter | plugins/claude/<plugin>/README.md
  detail: <bullet text>
  fix: regenerated automatically by the publish pipeline on next bump

### help_doc_staleness
- [WARN] chapter <path> is stale | plugins/claude/<plugin>/help/walkthroughs/<slug>.md
  detail: source_skills mtime > last_regen
  fix: regenerated automatically by the publish pipeline on next bump

### summary
plugins_scanned: <n>  warn: <m>
```

### Structured report shape (Agent D)

```
## scan: lazy-core.audit/expert-runtime

### experts_settings
- [INFO] lazy.settings.json[experts]: <N> experts defined
- [FAIL] lazy.settings.json is not valid JSON | .claude/lazy.settings.json
- [FAIL] expert <key> missing required field(s): <list> | lazy.settings.json[experts]

### reference_resolution
- [FAIL] expert <key>: agent reference '<value>' did not resolve | lazy.settings.json[experts]

### runtime_settings
- [INFO] lazy.settings.json absent — runtime sections not configured
- [INFO] daemon section absent — daemon not configured (git-sync off or routines-only repo) | .claude/lazy.settings.json
- [FAIL] daemon section _version mismatch (expected <daemon_version>) | .claude/lazy.settings.json
- [FAIL] daemon section missing key(s): <list> | .claude/lazy.settings.json
- [FAIL] routines section _version mismatch (expected <routines_version>) | .claude/lazy.settings.json
- [FAIL] routines section is not a dict | .claude/lazy.settings.json
- [WARN] experts configured but lazy-expert.pump routine absent from routines | .claude/lazy.settings.json
- [FAIL] routine <name> has no command field | .claude/lazy.settings.json
- [FAIL] routine <name> command path does not exist: <path> | .claude/lazy.settings.json

### orphan_jobs
- [WARN] orphan job directory .jobs/<expert>/ — expert not in lazy.settings.json[experts] | .jobs/<expert>/

### stale_jobs
- [WARN] stale completed/failed job not yet cleaned: .jobs/<expert>/<job-id>/ (age > threshold) — pump may not be running | .jobs/<expert>/<job-id>/

### daemon_liveness
- [WARN] runtime daemon appears stale — no pgrep match, no launchctl PID, and no JSONL log line in the last <threshold>s | .logs/lazy-core/runtime/

### review_self_validation
- [FAIL] review class <class> is validated by its own main writer <key> | .claude/lazy.settings.json[review.classes]

### aspect_resolution
- [FAIL] expert <key>: aspect reference '<value>' did not resolve | lazy.settings.json[experts]

### arguments_validation
- [FAIL] expert <key>: arguments-key-invalid: <bad-key> | lazy.settings.json[experts]
- [WARN] expert <key>: arguments payload <N> bytes

### memory_hygiene
- [WARN] .memory/<expert>/ orphan
- [FAIL] .memory/<expert>/ exists but expert is not marked persona
- [FAIL] memory note missing required frontmatter
- [FAIL] memory note tag missing memory/ prefix
- [WARN] tag file references missing note
- [WARN] note carries tag but is not listed in tag file
- [INFO] expert is persona but has not written memory yet

### external_dirs
- [FAIL] external dir <path> is <status> | <source>
- [WARN] external dirs declared but no source root on record for this checkout | .claude/lazy.settings.local.json
- [WARN] external dir <path> holds real content, not a link | <path>
- [WARN] external dir <path> has no source at <source> | <source>
- [WARN] external dir <path> is not gitignored — linked content would dirty the tree and halt the daemon | .gitignore
- [WARN] external dir <path> is covered by a directory-only ignore rule, which cannot match the symlink the repair plants | .gitignore

### inbox_ownership
- [FAIL] <detail>
- [WARN] <detail>

### protocol_envelope
- [FAIL] protocol <name> overrides the response envelope: <detail> | <path>

### summary
pass: <n>  warn: <n>  fail: <n>
```

The `external_dirs` and `inbox_ownership` groups are omitted entirely when they carry no findings — a repo that declares no external directories is the common case.

## Phase 3 — Render

Parse all four returned blocks plus the Phase 1 inline findings. Every rendered finding line carries all four of: severity, the path it is about, its repair route, and its `resolution` value from **Finding shape** above — the resolution travels with the finding when `/lazy-core.checkup` merges this report, and a finding that arrives without it counts as `report-only` there. The report ends with the last finding section: there is no recommendations block, and no line states what a repair would save. Produce:

### Always loaded (startup cost)

| Source | Path | Size | Files |
|---|---|---|---|
| (one row per Agent A `[INFO]` finding, sorted by size descending) |

**Total always-loaded**: ~X KB

`[INFO]` the system prompt, the skill registry, the MCP instructions and the deferred-tool list are injected by Claude Code, are not measured here, and no repair reduces them.

### On-demand (no startup cost)

| Source | Path | Size | Files |
|---|---|---|---|
| (one row per Agent B on-demand `[INFO]` finding, sorted by size descending) |

**Total on-demand**: ~X KB

### MCP servers

List enabled servers and the mode in effect. One line per WARN finding from Agent B's MCP section, each naming its route: enable the server for this project (`enabledMcpjsonServers`, or global `enableAllProjectMcpServers`), or drop the stale name — which servers this project trusts is the operator's call.

### Python runtime

One line for the `[INFO]` finding (path + version), or the `[FAIL]` / `[WARN]` if the probe found a problem — a problem line carries its route: install or upgrade to Python ≥ 3.12, then run `/lazy-core.install`, so the shipped hooks execute again. Omit the section if Agent B reported neither.

### Path hygiene

One line per Agent B path-hygiene `[WARN]`, each naming its route: replace the hardcoded path with its relative or `$HOME`-anchored equivalent — `/lazy-core.doctor` applies that rewrite per finding.

### Naming hygiene

One line per Agent B naming `[WARN]`, each naming its route: rename the file to `<namespace>.<name>` per `lazy-core.hygiene` § Naming and update every reference to it.

### Skill-writing compliance

Every line carries its own route; there is no routes section after the report.

- **Missing Execution-Discipline preamble** (FAIL) — one line per finding (skills only); route: add the preamble per `lazy-core.skill-writing § 1`, or declare `execution-discipline-waiver: "<concrete reason>"` in frontmatter.
- **"Optional" in phase/step heading** (FAIL) — one line per match; route: rename the heading — the accept/decline choice belongs inside an `AskUserQuestion`, not at heading level.
- **Waivered files** (INFO) — one line per file with `execution-discipline-waiver: "<reason>"`; no route, the waiver is the decision.
- **Narrative-padding heuristic** (WARN) — one line per match with the offending line; route: drop the passage when its removal leaves executable behaviour unchanged — author's call.
- **Invalid `lazy_setup_phase` value** (WARN) — one line per match with the offending value; route: set it to one of `pre-install` / `per-plugin` / `post-install` per `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.setup-phases-contract.md`.
- **`description:` absent** (FAIL) — one line per skill or command missing the frontmatter key; route: write one opening with the invocation condition per `lazy-core.skill-writing § 8` and the shapes in `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.description-triggers.md`.
- **`allowed-tools` missing `Agent`** (WARN) — one line per file that declares `allowed-tools:` without `Agent` in the list; route: add `Agent` to the list per `lazy-core.skill-writing § 9`.
- **Research-marker semantics** (WARN) — one line per skill with a research-shaped contract missing the marker, or the marker present without a documented query contract; route: add `research: true` (or the word in the description), or document the query mode, per `lazy-core.skill-writing § 10`.

### Audit-shape conformance

One line per Agent B S1–S4 finding, each naming its route as the check defines it.

- **Severity word outside the vocabulary** (FAIL) — one line per token.
- **Audit writes, carries an apply-style flag, or asks a question** (FAIL) — one line per site.
- **Repair routes lifted into their own section** (WARN) — one line per heading.
- **Shared contract not named** (WARN) — one line per audit.

Omit the whole subsection when S1–S4 produced no findings.

### Agent-writing compliance

- **Frontmatter incomplete** (FAIL) — one line per agent missing `name`/`description`/`tools`; route: fill the missing key per `lazy-core.agent-writing`.
- **Missing preamble** (FAIL) — multi-phase agents without preamble and without valid waiver; route: add the preamble per `lazy-core.agent-writing § 4`, or declare a concrete `execution-discipline-waiver:` string.
- **`AskUserQuestion` in agent body** (FAIL) — one line per match; route: delete the question — an agent has no user channel; return the choice to its caller instead.
- **`tools: ["*"]` without justification** (WARN) — one line per match; route: enumerate the tools the agent actually uses, or justify the wildcard on the same line.
- **`tools:` missing `Agent`** (WARN) — one line per agent whose `tools:` list omits it; route: add `Agent` per `lazy-core.agent-writing § 5`.
- **"Optional" in heading** (FAIL) — one line per match; route: rename the heading, as in the skill-writing case above.
- **Narrative-padding heuristic** (WARN) — one line per match; route: drop the passage when its removal leaves executable behaviour unchanged.

### Help-doc compliance

- **Missing walkthrough chapter** (WARN) — one line per Agent C H1 finding (scenario without a chapter); no manual route — it clears at the next publish bump for the plugin.
- **Stale chapter** (WARN) — one line per Agent C H2 finding (source_skills mtime newer than chapter `last_regen`); no manual route — same bump clears it.

### Model routing

Render the `_version` provenance line first — one line per scope that was present:

```
lazy.settings.json scope=project  agent_models._version=<N>
lazy.settings.json scope=global   agent_models._version=<N>
```

Then render the merged-with-provenance view grouped by top-level group name:

```
[_builtin]
  <dispatch-string>                        <value>    (<provenance>)

[_user]
  <dispatch-string>                        <value>    (<provenance>)

[_project]
  <dispatch-string>                        <value>    (<provenance>)

[<domain>]
  <dispatch-string>                        <value>    (<provenance>)
```

One line per entry. Below the table:

- **Orphans** (WARN) — one line per `orphan agent_models entry` finding; route: run `/lazy-core.agent-models`, which prunes entries whose agent is gone.
- **Gaps** (INFO) — one line per `no agent_models entry for ...` finding; route: run `/lazy-core.agent-models` to fill the tier, or set the agent to `"default"` deliberately.
- **Invalid values** (WARN) — one line per invalid-value finding; route: rewrite the value to one of `haiku` / `sonnet` / `opus` / `default`.
- **Env-var** (INFO) — `LAZY_AGENT_MODEL_FLOOR=<value>` with tier-order note, or `(unset)`; no route.

### Rule-writing compliance

- **Missing frontmatter** (FAIL) — one line per rule without YAML frontmatter; route: add at minimum a `description:` key per `lazy-core.rule-writing § 1`.
- **Missing scope or waiver** (FAIL) — neither `paths:` nor `always_loaded:`, or invalid `always_loaded` (true/empty); route: add a `paths:` block-list (preferred) or a concrete `always_loaded: "<reason>"` per `lazy-core.rule-writing § 1` — `/lazy-core.doctor` asks per rule which of the two the rule's audience calls for.
- **Non-canonical `paths:` shape** (FAIL) — one line per rule using inline-array form (`paths: [...]`) instead of the canonical YAML block-list; route: migrate to the block-list shape — `/lazy-core.doctor` applies that migration in place, preserving every glob.
- **Size over budget** (FAIL / WARN) — `always_loaded:` > 3 KB; `paths:` > 10 KB (WARN) or > 25 KB (FAIL); route: move the long guidance into `<plugin>/skills/<skill>/references/*.md` per `lazy-core.rule-writing § 2`, or run `/lazy-core.slim-context`.
- **Code block > 10 lines** (FAIL) — one line per match; route: shorten the block, or move it to a reference the rule points at, per `lazy-core.rule-writing § 3`.
- **Filename lacks dot separator** (WARN) — one line per match; route: rename to `<namespace>.<name>.md` and update every reference.
- **Broken artifact reference** (WARN) — one line per unresolved reference; route: correct the reference, or delete it when the artifact is retired.
- **Narrative-padding heuristic** (WARN) — one line per match; route: drop the passage when its removal leaves executable behaviour unchanged.
- **Authoring rule without template reference** (WARN) — one line per authoring rule with no `templates/**/*-template.md` mention in the body; route: create `<plugin>/templates/<group>/<artifact>-template.md` and add a `**Template:** <path>` pointer at the top of the rule body per `lazy-core.scaffold` — `/lazy-core.doctor` scaffolds both.

### Reference-writing compliance

- **Size over budget** (FAIL / WARN) — reference > 50 KB (FAIL); > 25 KB (WARN). One line per file; route: split the subjects no reader needs together into siblings, leaving a numbered stub per extracted section, per `lazy-core.reference-writing § 4.1` — or declare `size-waiver: "<reason naming the reader>"` when the file is genuinely read whole (§ 4.2).
- **Size waived** (INFO) — one line per reference carrying a valid `size-waiver:`, showing its size and the declared reason; no route. Omit the whole subsection when there are no findings of either kind.
- **Invalid `size-waiver:` value** (FAIL) — one line per reference whose waiver is boolean or empty; route: replace it with a concrete string reason, or remove the key and act on the size finding.

### Expert runtime

Render Agent D findings, grouped by sub-check. Omit any sub-check whose findings are all `[INFO]` and print only the summary line instead.

**Expert configuration** — one line per `[FAIL]` from D1 (schema) and D2 (agent reference resolution); route on D1: add the missing fields per the expert schema, or re-run `/lazy-core.install` to re-scaffold the entry. Route on D2: correct the `agent` ref to a resolvable format (`<plugin>:<name>`, `user:<name>`, bare `<name>`), or delete the entry. Show the `[INFO]` experts count line when all schema checks pass.

**Loop settings** — one line per `[FAIL]` or `[WARN]` from D3 (runtime schema) and D4 (routine command resolvability); route on D3: re-run `/lazy-core.install` to scaffold or repair the flat `daemon` and `routines` sections. Route on D4: install the missing plugin, or unregister the routine via `/lazy-routine.unregister`. Omit the section if all pass.

**Job hygiene** — one line per `[WARN]` from D5 (orphan jobs) and D6 (stale DONE/DEAD jobs); route on D5: delete the orphan directory once its output is no longer wanted, or re-register the expert. Route on D6: start the pump so cleanup runs. Omit the section if no warnings.

**Daemon liveness** — one line per `[WARN]` from D7; route: restart the daemon through its supervisor — `/lazy-core.doctor` offers that restart. Omit the section if no warnings.

**Aspect resolution** — one line per `[FAIL]` from D8. Omit the section if all pass.

**Arguments validation** — one line per `[FAIL]` or `[WARN]` from D9. Omit if all pass.

**Memory hygiene** — one line per `[FAIL]` or `[WARN]` from D10. INFO findings (persona-but-empty) appear only when the full report would otherwise be empty.

**External dirs** — one line per `[FAIL]` or `[WARN]` from D11. Omit the section when D11 produced no findings.

**Inbox ownership** — one line per `[FAIL]` or `[WARN]` from D12. Omit the section when D12 produced no findings.

**Sandbox scope** — one line per `[FAIL]` or `[WARN]` from D13. Omit the section when D13 produced no findings.

**Operator git hooks** — one line per `[WARN]` from D15. Omit the section when D15 produced no findings.

**Expert runtime summary**: `PASS: <n> | WARN: <n> | FAIL: <n>` (count across all D1–D16 findings).

### Logging compliance

Render Phase 1 inline findings.

- **Logging rule presence** (FAIL / WARN) — one line per L1 finding; route: run `/lazy-core.setup` to copy `lazy-log.logging.md` into the consumer scope, or write the missing frontmatter `description:` in the plugin source. Omit the sub-section if all pass.
- **`.logs/` and `.runtime/` directories** (WARN) — one line per L2 finding (each directory is checked independently); route: run `/lazy-core.setup` to bootstrap the directory. Omit if both present.
- **`.gitignore` coverage** (WARN) — one line per L3 finding (`.logs/` and `.runtime/` are checked independently); route: add the missing line to `.gitignore`, by hand or via `/lazy-core.setup`. Omit if both covered.
- **`logging-waiver:` value** (FAIL) — one line per L4 finding; route: replace the empty or boolean value with a concrete string reason per `lazy-log.logging` § Waiver. Omit if all valid.

If all L1–L4 checks pass: emit a single `PASS: logging rule installed, .logs/ + .runtime/ present, .gitignore covers both, all waiver values valid` summary line.

### Verdict

Close the report with the contract's summary line — `audit: <LEVEL> (<N> findings)`, where `<LEVEL>` is the highest severity present with `INFO` counted as `PASS`, and `<N>` counts every finding rendered above. Nothing follows it.

## Logging

Log the run to `./.logs/claude/lazy-core.audit/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Read-only is not an exemption: the finding set this skill produces is variable-shaped, so it is `should-log`, never a waiver candidate.

1. `Bash(mkdir -p ./.logs/claude/lazy-core.audit)` — a separate step from the `Write`, never chained.
2. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` for the filename; `Bash(git rev-parse HEAD)` and `Bash(git rev-parse --abbrev-ref HEAD)` for `git_sha` / `git_branch` (`no-git` when either fails).
3. `Write` the file. Frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input` (the arguments passed, or `none`).
4. Body: `# lazy-core.audit` heading, then `## Actions` — one line per Phase with its outcome word, plus the per-severity and per-resolution finding counts — and `## Result` with the outcome word and a one-sentence summary.

## Failure modes

- **`/lazy-core.audit` exits with "lazy.settings.json is not valid JSON"** — the file was hand-edited and broke JSON syntax → fix the syntax or re-scaffold via `/lazy-core.install`.
- **Agent D reports "reference did not resolve" for an expert** — the `agent` field uses an unrecognised format or points to a non-existent artifact. Check the reference format (`<plugin>:<name>`, `user:<name>`, or bare `<name>`) and verify the artifact is installed → run `/lazy-core.install` to re-register.
- **Routine command FAIL when the plugin is installed** — the plugin cache uses a 4-level path `<registry>/<plugin>/<version>/bin/<plugin>`; an older install used a 3-level layout. Re-install the plugin to refresh the bin path in the routine entry.
- **D7 daemon liveness check always WARN on first use** — the runtime hasn't been started yet; this is expected after initial install → start the daemon via `launchctl load` or `systemctl --user start` as offered by `/lazy-core.install`.
- **Agent D silently reports nothing** — `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin` was not resolved (sandboxed environment or missing plugin path). Verify `${CLAUDE_PLUGIN_ROOT}` resolves to the plugin install path and `bin/lazy_settings.py` is present.
