---
name: lazy-core.audit
description: "Quick read-only audit of what gets loaded into conversation context at startup plus skill-writing, agent-writing, rule-writing, and logging compliance. Shows sizes, loading behavior, optimization opportunities, Execution-Discipline preamble presence, no-Optional headings, narrative-padding heuristics, rule-file frontmatter/size/code-block/scope enforcement, and logging-rule installation state. No changes made."
allowed-tools: Read, Glob, Grep, Bash(wc *), Bash(command -v python3), Bash(python3 --version), Bash(python3 *), Bash(test *)
---
# Context Audit

Coordinator skill. Runs inline logging compliance checks, then dispatches four **Explore** subagents in parallel to measure context weight and hygiene. Read-only — no changes made.

Read `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md` before dispatching for the coordinator pattern.

**CRITICAL PATH RULE** (applies to every dispatched agent): `$HOME/.claude/` is protected from Bash access. Agents must use ONLY Glob and Read under `$HOME/.claude/`. `wc -c` via Bash is allowed ONLY for paths under the project root.

**Path expansion** (mandatory): Glob and Read do **not** shell-expand `~` or `$HOME`. Before any Glob/Read targeting a home-relative path, run `Bash(echo $HOME)` once and substitute the result (or read the absolute home path from the session env block). A literal `~/.claude/rules/*.md` or `$HOME/.claude/rules/*.md` passed to Glob will match nothing and silently report "empty".

**Size estimation**: for Read-measured files use `size ~ lines × 45 bytes`; for `wc -c` use exact bytes.

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Inline logging compliance checks`
   - `Phase 2 — Dispatch parallel scans`
   - `Phase 3 — Render (Report)`
   - `Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Inline logging compliance checks

Absorbed from the retired `lazy-log.audit` skill. These four checks run inline (no subagent dispatch) before Phase 2's parallel scan. Record findings in a local list for inclusion in the Phase 3 render.

Severity vocabulary (same as Phase 2): `INFO` / `WARN` / `FAIL`.

### L1 — Logging rule presence

Check two paths: `claude/lazycortex-core/rules/lazy-log.logging.md` (plugin source) and at least one consumer scope.

- Read `claude/lazycortex-core/rules/lazy-log.logging.md`. If absent → `[FAIL] logging rule missing from plugin source at claude/lazycortex-core/rules/lazy-log.logging.md`.
- Glob `.claude/rules/lazy-log.logging.md`. If absent, also Glob `$HOME/.claude/rules/lazy-log.logging.md` (expand `$HOME` first via `Bash(echo $HOME)`). If neither consumer path exists → `[WARN] lazy-log.logging.md not installed in any consumer scope (.claude/rules/ or ~/.claude/rules/) — run /lazy-core.setup`.
- If the rule file at the plugin source path exists but has no YAML frontmatter `description:` key → `[WARN] lazy-log.logging.md plugin source has no frontmatter description | claude/lazycortex-core/rules/lazy-log.logging.md`.

### L2 — `.logs/` directory state

- `Bash(test -d .logs && echo present || echo absent)`. If absent → `[WARN] .logs/ directory missing at repo root — run /lazy-core.setup to bootstrap`.

### L3 — `.gitignore` covers `.logs/`

- Read `.gitignore`. If absent → `[WARN] .gitignore not found — cannot verify .logs/ coverage | .gitignore`.
- If present but neither `.logs/` nor `.logs` appears in the file → `[WARN] .gitignore does not exclude .logs/ — commits will include runtime state | .gitignore`.

### L4 — `logging-waiver:` value validation

Glob `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`, `.claude/commands/*.md`. For each file, parse YAML frontmatter and inspect `logging-waiver:` if present:

- `[FAIL]` if value is the empty string, the literal `true`, or the literal `yes`.
- `[FAIL]` if the key is present but no value follows (key + colon with empty mapping value).

Valid concrete strings → no finding.

## Phase 2 — Dispatch parallel scans

Dispatch these four Explore agents **in a single message with four Agent tool calls** (`subagent_type: "Explore"`, `mode: "dontAsk"`). Each returns the structured report from `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.parallel-scan.md`. Budget: "Report under 350 words".

Severity vocabulary for this skill: `INFO` (measurement row or visible waiver, including dirty-tree waiver acknowledgements) / `WARN` (recommendation or heuristic flag, including dirty-tree write-without-commit findings) / `FAIL` (structural violation — Agent B compliance checks across skill-writing, agent-writing, hook-writing, and rule-writing: missing preamble, invalid waiver, "Optional" heading, missing rule frontmatter or scope, oversize rule, code block > 10 lines, `AskUserQuestion` inside agent body, hook script missing shebang, hook script crashing on malformed stdin).

### Agent A — always-loaded context

Measure everything that loads at conversation start. Include these sources as one `[INFO]` finding per source, sorted by size desc:

- **Global CLAUDE.md** (`$HOME/.claude/CLAUDE.md`) — Read, estimate size.
- **Project CLAUDE.md** (`CLAUDE.md`) — Read, estimate size.
- **Global rules** (`$HOME/.claude/rules/*.md`) — Glob + Read. If the directory is a symlink, resolve and follow it. Only rules **without** a `paths` frontmatter field count as always-loaded; rules with `paths` are on-demand and belong to Agent B.
- **Project rules** (`.claude/rules/*.md`) — `wc -c` via Bash. Same `paths` filtering rule.
- **Memory index** (`$HOME/.claude/projects/*/memory/MEMORY.md`) — Read, estimate size.

Also emit `[WARN]` findings for:

- Any rules file > 3 KB (suggest `/lazy-core.optimize`).
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

Include a `total_kb` line for on-demand sources in the summary block.

**MCP enablement** — read `$HOME/.mcp.json`, `.mcp.json`, `$HOME/.claude/settings.json`, `$HOME/.claude/settings.local.json`, `.claude/settings.json`, `.claude/settings.local.json`. Determine mode:

- Mode A: global `enableAllProjectMcpServers: true` → every project `.mcp.json` entry is implicitly enabled; suppress "declared but unused" warnings.
- Mode B: `enableAllProjectMcpServers` false or missing → server enabled only if its name appears in `enabledMcpjsonServers` of project settings.

Emit one `[INFO]` per enabled server. Emit `[WARN]`:

- Mode B only: server in project `.mcp.json` not enabled under any rule above.
- Mode B only: non-empty project `.mcp.json` but no `enabledMcpjsonServers` anywhere.
- Always: name in `enabledMcpjsonServers` with no definition in `.mcp.json` or `$HOME/.mcp.json`.

**Python runtime** — every `lazycortex-*` plugin ships hooks that shebang `python3`, and project hooks invoked as `python3 ...` from `settings.json` rely on the same interpreter. If `python3` is missing or too old, hooks silently fail and the user loses distill-after-commit, settings/public guards, agent-model routing, and autobump. Run two short Bash probes:

- `command -v python3` — empty output → `[FAIL] python3 not in PATH — every hook in .claude/settings.json and claude/lazycortex-*/hooks/*.py will fail to execute.`
- `python3 --version 2>&1` — parse `Python X.Y.Z`. Floor is **3.12** (shipped Python uses `pathlib` semantics that shifted in 3.12; per-plugin `<ns>.install` skills inherit the floor and must NOT re-probe). Emit:
  - `[INFO] python3 path=<path> version=<X.Y.Z>` when found and ≥ 3.12.
  - `[FAIL] python3 version <X.Y.Z> below floor 3.12 — every shipped hook fails on startup. Run /lazy-core.install to walk the install path.` when found and < 3.12.

Skip both probes silently if neither runs (sandbox restriction); the renderer treats the section as absent.

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

**Skill-writing compliance** — see `lazy-core.skill-writing`. File set: `.claude/skills/*/SKILL.md`, `claude/*/skills/*/SKILL.md` (commands exempt from the preamble check). Four checks:

1. **Preamble present** — grep each file for `^## Execution discipline (MANDATORY`. Absent AND no `execution-discipline-waiver:` in frontmatter → `[FAIL]`. Frontmatter carries a non-empty `execution-discipline-waiver: "<reason>"` string → `[INFO]` with the waiver reason (visible, not silent). Frontmatter carries `execution-discipline-waiver: true` / `yes` / `""` → `[FAIL]` (invalid waiver).
2. **No "Optional" in phase/step headings** — grep for `^##+ .*[Pp]hase.*[Oo]ptional`, `^##+ .*[Ss]tep.*[Oo]ptional`, and any `^### .*[Oo]ptional`. Match → `[FAIL]`.
3. **Narrative padding (heuristic)** — grep the body (exclude frontmatter) for the denylist: `\bv\d+\.\d+\.\d+`, `user had to`, `we got burned`, `in a past session`, `in a previous run`, `user had to patch`. Match → `[WARN]` with the offending line. Final decision is the author's — heuristic, not structural.
4. **Valid `lazy_setup_phase` value** — grep frontmatter for `^lazy_setup_phase:`. Value outside `{pre-install, per-plugin, post-install}` → `[WARN]` with the offending value. See `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.setup-phases-contract.md` for the contract.

**Agent-writing compliance** — see `lazy-core.agent-writing`. File set: `.claude/agents/*.md`, `claude/*/agents/*.md`. Checks:

1. **Frontmatter complete** — `name`, `description`, `tools` all present. Missing any → `[FAIL]`.
2. **Preamble present** (for multi-phase agents) — same check as skill-writing §1. Agents with `## Phase N` or `## Process` sections must carry the preamble OR a valid `execution-discipline-waiver:` string. Same FAIL/INFO vocabulary.
3. **No `AskUserQuestion` in agent body** — grep for `AskUserQuestion` outside fenced code/frontmatter. Match → `[FAIL]` (agents have no user channel).
4. **Tool allowlist hygiene** — `tools: ["*"]` → `[WARN]` (unless a justification comment on the same line).
5. **No "Optional" in phase/step headings** — same as skill-writing §2 → `[FAIL]`.
6. **Narrative padding (heuristic)** — same denylist as skill-writing §3 → `[WARN]`.

**Model routing** — load both settings files via `bin/lazy_settings.py`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import load_section
from pathlib import Path
proj = load_section(Path('.claude/lazy.settings.json'), 'agent_models')
user = load_section(Path.home() / '.claude/lazy.settings.json', 'agent_models')
# missing file → section dict with only _version returned automatically; no error
")
```

Missing files are a silent no-op — `load_section` returns a stub with `_version` intact. Do not add a manual file-existence guard. Build a merged-with-provenance view of `agent_models`:

1. **Files present / `_version` provenance** — emit `[INFO]` per scope: `lazy.settings.json scope=project path=<path> agent_models._version=<N>` or `lazy.settings.json scope=project (missing)`; same for `global`. Surfacing `_version` makes settings-version drift visible — e.g. a global file at `agent_models._version: 1` while the project file is at `_version: 2` after a migration.
2. **No config anywhere** — if BOTH scopes are missing (both returned only the stub `_version` key and nothing else), emit `[WARN] no lazy.settings.json found (project: <path>, global: <path>) — agent routing disabled. Run /lazy-core.optimize to create and fill.` Skip the remaining checks (merged view / orphans / gaps / invalid values) since there is nothing to validate.
3. **Merged entries** — for every dispatch-string key across both scopes, emit one `[INFO]`: `agent_models <group>.<key> = <value> (<provenance>)`. Provenance is `project`, `global`, or `project, overrides global=<other>` when both scopes carry the same key with different values. Group entries together in the report render by their top-level group name. Skip any top-level key whose value is not a dict (e.g. `_version: int`) — only group sub-dicts carry dispatch mappings. (Filter by shape, not by name, because `_user` / `_project` / `_builtin` are legitimate group-name keys that share the underscore prefix.)
4. **Orphans** — any key in either scope that does NOT resolve to a discovered agent (see Agent discovery below). Finding: `[WARN] orphan agent_models entry: <group>.<key> (<scope>)`.
5. **Gaps** — discovered agents with no entry in any scope (exclude agents explicitly set to `"default"` in either scope — those are explicit decisions, not gaps). Finding: `[INFO] no agent_models entry for <dispatch-string> (from <source>) — run /lazy-core.optimize to fill`.
6. **Invalid values** — any value not in `{"haiku", "sonnet", "opus", "default"}`. Finding: `[WARN] invalid value <x> for <group>.<key> (<scope>)`.
7. **Env-var status** — emit `[INFO]` with `LAZY_AGENT_MODEL_FLOOR=<value>` and a tier-order note (`haiku < sonnet < opus`), else `LAZY_AGENT_MODEL_FLOOR=(unset)`.

**Agent discovery (shared helper — used by audit, optimize, doctor)**. Deduped by full dispatch string:

1. **Built-ins** — hardcoded list: `Explore`, `Plan`, `general-purpose`, `statusline-setup`. Group: `_builtin`. Dispatch string: bare name.
2. **User-authored, global** — `$HOME/.claude/agents/*.md`. Group: `_user`. Dispatch string: bare filename stem.
3. **User-authored, project** — `./.claude/agents/*.md`. Group: `_project`. Dispatch string: bare filename stem. (Project entries shadow global entries of the same stem — both still listed separately with provenance.)
4. **Plugin-shipped** — `$HOME/.claude/plugins/cache/**/agents/*.md`. Extract plugin name from path (`$HOME/.claude/plugins/cache/<marketplace>/<plugin-name>/<version>/agents/<agent>.md` → plugin = `<plugin-name>`). Group: **domain** derived from plugin name via the domain-extraction rule (first `-`-delimited segment, or full name if no `-`). Dispatch string: `<plugin-name>:<stem>`.

**Rule-writing compliance** — see `lazy-core.rule-writing`. File set: `.claude/rules/*.md`, `$HOME/.claude/rules/*.md`, `claude/*/rules/*.md`. **Exclude** `**/templates/**/*-template.md` from every check below — templates are skeletons, not rules; their placeholder frontmatter and example clauses would otherwise misfire. Checks:

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

### Agent C — help-doc coverage and staleness

Per-plugin scan of `claude/<plugin>/` for help-doc completeness against `## Scenarios` and chapter staleness against source-skill mtime. Both checks emit `[WARN]` only — there is no manual fix path; chapters are regenerated by the publish pipeline at the next version bump.

Discover plugins: `claude/*/.claude-plugin/plugin.json`. For each plugin:

#### Check H1 — Help-doc scenario coverage

For every plugin under `claude/<plugin>/`:

- Read each bullet under `## Scenarios` in `claude/<plugin>/README.md`. Skip the plugin if the README has no `## Scenarios` section.
- For each bullet, look for a corresponding `claude/<plugin>/help/walkthroughs/<slug>.md`. Slug-match: lowercase the first 4–6 keywords of the bullet, hyphenate, strip non-alphanumeric. A walkthrough chapter also matches when its frontmatter `summary` substring-matches the bullet text.
- Missing match → `[WARN]` with detail `scenario "<bullet>" has no walkthrough chapter in claude/<plugin>/help/walkthroughs/`.

#### Check H2 — Help-doc staleness

For every chapter under `claude/<plugin>/help/**/*.md`:

- Read the chapter's frontmatter `last_regen` and `source_skills`. Skip the chapter if either field is absent.
- For each skill in `source_skills`, find the most recent commit mtime via `git log -1 --format=%cI -- claude/<plugin>/skills/<skill>/SKILL.md`. Also include `claude/<plugin>/README.md`'s mtime.
- If any source's mtime is newer than `last_regen` → `[WARN]` with detail `chapter <path> is stale; clears at next publish bump for <plugin>`.

These warnings are advisory — there is no manual fix path. The publish pipeline regenerates chapters at the next version bump (subject to its patch-bump short-circuit). The mtime probe uses `git log -1` and therefore detects only *committed* edits; uncommitted local changes do not register as stale here.

Severity vocabulary: `INFO` (advisory note about a passing chapter or scenario, optional) / `WARN` (H1 missing chapter, H2 stale chapter). Never emit `FAIL` from this agent.

### Agent D — expert runtime

Scope: `lazy.settings.json[experts]`, `lazy.settings.json[lazy-core.runtime]`, `.jobs/` directories, runtime daemon liveness. Severity vocabulary: `INFO` (informational, non-actionable) / `WARN` (advisory or degraded state) / `FAIL` (structural violation or unresolvable reference).

**CRITICAL PATH RULE** applies: no Bash under `$HOME/.claude/`. Expand `$HOME` once via `Bash(echo $HOME)` then substitute.

**Path layout constant**: plugin cache lives under `$HOME/.claude/plugins/cache/<registry>/<plugin>/<version>/bin/<plugin>`.

Perform these 7 sub-checks in order:

**D1 — `lazy.settings.json[experts]` schema**

Read `.claude/lazy.settings.json`. If the file is absent or the `experts` section is missing/empty (after stripping `_version`): emit `[INFO] lazy.settings.json[experts] absent — no experts configured` and skip D2, D5 (D4 runs regardless — routines can exist without experts). If the file is present but not valid JSON: `[FAIL] lazy.settings.json is not valid JSON | .claude/lazy.settings.json`.

For every top-level key that is not `_version` (filter by shape — skip keys whose value is not an object, so `_version: int` is excluded without name-checking):

- Verify the expert entry has all three required fields: `agent`, `git_author.name`, `git_author.email`. Missing any field → `[FAIL] expert <key> missing required field(s): <list> | lazy.settings.json[experts]`. Note: `protocol` is NOT an expert field — protocols are declared by routines, not by experts. Optional fields: `aspects` (list of `<plugin>:<name>-aspect` refs) and `arguments` (dict of `<lowercase_snake>: <json-value>`). Unknown extra fields → `[WARN] expert <key> has unknown field(s): <list>`.

Emit `[INFO] lazy.settings.json[experts]: <N> experts defined` when at least one expert passes.

**D2 — Reference resolution (agent)**

For each expert entry (from D1 that passed schema):

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from reference_resolver import resolve
import json, sys
result = resolve(sys.argv[1])
print(json.dumps({'ok': result is not None, 'resolved': str(result) if result else None}))
" '<expert.agent value>')
```

Failure (non-zero exit or `ok: false`) → `[FAIL] expert <key>: agent reference '<value>' did not resolve | lazy.settings.json[experts]` (category: logical).

**D8 — Reference resolution (aspects)**

For each expert entry with a non-empty `aspects[]`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from reference_resolver import resolve, ReferenceError
from pathlib import Path
import sys
ok = True
for ref in sys.argv[1:]:
    try:
        resolve(ref, category='aspects', repo=Path('.'))
    except ReferenceError as e:
        print(f'FAIL: {ref}: {e}')
        ok = False
print('OK' if ok else 'FAIL')
" '<aspect-ref-1>' '<aspect-ref-2>' ...)
```

Any unresolved aspect ref → `[FAIL] expert <key>: aspect reference '<value>' did not resolve | lazy.settings.json[experts]`.

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

**D3 — `lazy.settings.json[lazy-core.runtime]` schema**

Read `.claude/lazy.settings.json`. If absent: `[INFO] lazy.settings.json absent — runtime section not configured` and skip D3 sub-checks. If present, extract the `lazy-core.runtime` section (treat missing section as an empty object):

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import load_section
from pathlib import Path
import json
s = load_section(Path('.claude/lazy.settings.json'), 'lazy-core.runtime')
print(json.dumps(s))
")
```

Validate the returned section:

- `_version` must equal `1`. Wrong value or absent → `[FAIL] lazy-core.runtime section _version mismatch (expected 1) | .claude/lazy.settings.json`.
- `daemon` block must be a dict and contain: `git` (string or bool), `polling_interval_sec` (positive int), `cleanup_completed_after` (string or int), `cleanup_failed_after` (string or int), `cleanup_dead_after` (string or int). Any missing key → `[FAIL] lazy-core.runtime daemon block missing key(s): <list> | .claude/lazy.settings.json`.
- Each `cleanup_*_after` value must parse as `<N>d` (days), `<N>h` (hours), or a raw non-negative integer (seconds). Anything else → `[FAIL] lazy-core.runtime daemon.<key> has malformed value '<value>' (expected <N>d / <N>h / int) | .claude/lazy.settings.json` — D6 below would otherwise silently fail to parse and apply a default.
- `routines` must be a dict (may be empty). Non-dict value → `[FAIL] lazy-core.runtime routines is not a dict | .claude/lazy.settings.json`.
- When D1 found at least one expert AND `routines` does not contain a `lazy-expert.pump` entry → `[WARN] experts configured but lazy-expert.pump routine absent from routines | .claude/lazy.settings.json`.

**D4 — Routine command resolvability**

For each key/value in `routines` (skip if D3 found the section absent):

- Read the routine object's `command` field. If absent → `[FAIL] routine <name> has no command field | .claude/lazy.settings.json`.
- The `command` value must be a plugin bin path under the 4-level plugin cache layout: `$HOME/.claude/plugins/cache/<registry>/<plugin>/<version>/bin/<plugin>`. Resolve `$HOME` via `Bash(echo $HOME)`. Check path existence via `Bash(test -f '<path>' && echo ok || echo missing)`. Missing → `[FAIL] routine <name> command path does not exist: <path> | .claude/lazy.settings.json`.

**D5 — Orphan jobs**

Glob `.jobs/*/` (one level deep). For each subdirectory name `<expert>`:

- If `<expert>` is not a key in `lazy.settings.json[experts]` (from D1) → `[WARN] orphan job directory .jobs/<expert>/ — expert not in lazy.settings.json[experts] | .jobs/<expert>/`.

**D6 — Stale DONE jobs**

From D3, obtain `cleanup_completed_after` and `cleanup_failed_after` (default to `"7d"` if absent or D3 was skipped). Convert to seconds (parse `<N>d` → `N*86400`, `<N>h` → `N*3600`, int → use directly).

For each job dir under `.jobs/*/` (recurse one more level: `.jobs/<expert>/<job-id>/`): determine status by the presence of marker files written by the pump — `DONE` indicates the expert finished (success or `outcome=error` — read `response.json` to distinguish), `DEAD` indicates the pump killed the process as stuck. For jobs carrying either marker:

```
Bash(python3 -c "
import os, time, sys
threshold_sec = int(sys.argv[1])
path = sys.argv[2]
mtime = os.path.getmtime(path)
age_sec = time.time() - mtime
print('stale' if age_sec > threshold_sec else 'ok')
" '<threshold>' '.jobs/<expert>/<job-id>')
```

Stale → `[WARN] stale completed/failed job not yet cleaned: .jobs/<expert>/<job-id>/ (age > threshold) — pump may not be running | .jobs/<expert>/<job-id>/`.

**D7 — Daemon liveness**

Best-effort check. Three signals (any one passing = alive):

1. `Bash(pgrep -f bin/runner 2>/dev/null && echo running || echo stopped)` → `running`.
2. `Bash(launchctl list com.lazycortex.runtime.$(basename $(pwd)) 2>/dev/null | grep -q '"PID"' && echo running || echo stopped)` → `running`.
3. Compute `5 × max(polling_interval_sec)` across all routines (default 300 s if not available). Find newest `.logs/lazy-core/runtime/*.jsonl` via `Bash(ls -t .logs/lazy-core/runtime/*.jsonl 2>/dev/null | head -1)`. If a file is found, check its mtime:
   ```
   Bash(python3 -c "
   import os, time, sys
   path = sys.argv[1]; threshold = int(sys.argv[2])
   age = time.time() - os.path.getmtime(path)
   print('ok' if age < threshold else 'stale')
   " '<newest jsonl>' '<threshold>')
   ```
   `ok` → alive.

If all three signals indicate stopped/stale/absent → `[WARN] runtime daemon appears stale — no pgrep match, no launchctl PID, and no JSONL log line in the last <threshold>s | .logs/lazy-core/runtime/`.

If none of the three probes run (e.g. not on macOS, no runtime configured) → skip silently.

### Structured report shape (Agents A, B, C — unchanged)

```
## scan: lazy-core.audit/help-docs

### help_doc_coverage
- [WARN] scenario "<bullet>" has no walkthrough chapter | claude/<plugin>/README.md
  detail: <bullet text>
  fix: regenerated automatically by the publish pipeline on next bump

### help_doc_staleness
- [WARN] chapter <path> is stale | claude/<plugin>/help/walkthroughs/<slug>.md
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
- [INFO] lazy.settings.json absent — runtime section not configured
- [FAIL] lazy-core.runtime section _version mismatch (expected 1) | .claude/lazy.settings.json
- [FAIL] lazy-core.runtime daemon block missing key(s): <list> | .claude/lazy.settings.json
- [FAIL] lazy-core.runtime routines is not a dict | .claude/lazy.settings.json
- [WARN] experts configured but lazy-expert.pump routine absent from routines | .claude/lazy.settings.json
- [FAIL] routine <name> has no command field | .claude/lazy.settings.json
- [FAIL] routine <name> command path does not exist: <path> | .claude/lazy.settings.json

### orphan_jobs
- [WARN] orphan job directory .jobs/<expert>/ — expert not in lazy.settings.json[experts] | .jobs/<expert>/

### stale_jobs
- [WARN] stale completed/failed job not yet cleaned: .jobs/<expert>/<job-id>/ (age > threshold) — pump may not be running | .jobs/<expert>/<job-id>/

### daemon_liveness
- [WARN] runtime daemon appears stale — no pgrep match, no launchctl PID, and no JSONL log line in the last <threshold>s | .logs/lazy-core/runtime/

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

### summary
pass: <n>  warn: <n>  fail: <n>
```

## Phase 3 — Render

Parse all four returned blocks plus the Phase 1 inline findings. Produce:

### Always loaded (startup cost)

| Source | Path | Size | Files |
|---|---|---|---|
| (one row per Agent A `[INFO]` finding, sorted by size descending) |

**Total always-loaded**: ~X KB

### On-demand (no startup cost)

| Source | Path | Size | Files |
|---|---|---|---|
| (one row per Agent B on-demand `[INFO]` finding, sorted by size descending) |

**Total on-demand**: ~X KB

### MCP servers

List enabled servers and the mode in effect. Flag any WARN findings from Agent B's MCP section.

### Python runtime

One line for the `[INFO]` finding (path + version), or the `[FAIL]` / `[WARN]` if the probe found a problem. Omit the section if Agent B reported neither.

### Path hygiene

One line per Agent B path-hygiene `[WARN]`.

### Naming hygiene

One line per Agent B naming `[WARN]`.

### Skill-writing compliance

- **Missing Execution-Discipline preamble** (FAIL) — one line per finding (skills only).
- **"Optional" in phase/step heading** (FAIL) — one line per match.
- **Waivered files** (INFO) — one line per file with `execution-discipline-waiver: "<reason>"`.
- **Narrative-padding heuristic** (WARN) — one line per match with the offending line.
- **Invalid `lazy_setup_phase` value** (WARN) — one line per match with the offending value.

### Agent-writing compliance

- **Frontmatter incomplete** (FAIL) — one line per agent missing `name`/`description`/`tools`.
- **Missing preamble** (FAIL) — multi-phase agents without preamble and without valid waiver.
- **`AskUserQuestion` in agent body** (FAIL) — one line per match.
- **`tools: ["*"]` without justification** (WARN) — one line per match.
- **"Optional" in heading** (FAIL) — one line per match.
- **Narrative-padding heuristic** (WARN) — one line per match.

### Help-doc compliance

- **Missing walkthrough chapter** (WARN) — one line per Agent C H1 finding (scenario without a chapter).
- **Stale chapter** (WARN) — one line per Agent C H2 finding (source_skills mtime newer than chapter `last_regen`).

Both clear automatically at the next publish bump for the affected plugin — no manual fix path.

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

- **Orphans** (WARN) — one line per `orphan agent_models entry` finding.
- **Gaps** (INFO) — one line per `no agent_models entry for ...` finding.
- **Invalid values** (WARN) — one line per invalid-value finding.
- **Env-var** (INFO) — `LAZY_AGENT_MODEL_FLOOR=<value>` with tier-order note, or `(unset)`.

### Rule-writing compliance

- **Missing frontmatter** (FAIL) — one line per rule without YAML frontmatter.
- **Missing scope or waiver** (FAIL) — neither `paths:` nor `always_loaded:`, or invalid `always_loaded` (true/empty).
- **Non-canonical `paths:` shape** (FAIL) — one line per rule using inline-array form (`paths: [...]`) instead of the canonical YAML block-list.
- **Size over budget** (FAIL / WARN) — `always_loaded:` > 3 KB; `paths:` > 10 KB (WARN) or > 25 KB (FAIL).
- **Code block > 10 lines** (FAIL) — one line per match.
- **Filename lacks dot separator** (WARN) — one line per match.
- **Broken artifact reference** (WARN) — one line per unresolved reference.
- **Narrative-padding heuristic** (WARN) — one line per match.
- **Authoring rule without template reference** (WARN) — one line per authoring rule with no `templates/**/*-template.md` mention in the body.

### Expert runtime

Render Agent D findings, grouped by sub-check. Omit any sub-check whose findings are all `[INFO]` and print only the summary line instead.

**Expert configuration** — one line per `[FAIL]` from D1 (schema) and D2 (agent reference resolution). Show the `[INFO]` experts count line when all schema checks pass.

**Loop settings** — one line per `[FAIL]` or `[WARN]` from D3 (runtime schema) and D4 (routine command resolvability). Omit the section if all pass.

**Job hygiene** — one line per `[WARN]` from D5 (orphan jobs) and D6 (stale DONE/DEAD jobs). Omit the section if no warnings.

**Daemon liveness** — one line per `[WARN]` from D7. Omit the section if no warnings.

**Aspect resolution** — one line per `[FAIL]` from D8. Omit the section if all pass.

**Arguments validation** — one line per `[FAIL]` or `[WARN]` from D9. Omit if all pass.

**Memory hygiene** — one line per `[FAIL]` or `[WARN]` from D10. INFO findings (persona-but-empty) appear only when the full report would otherwise be empty.

**Expert runtime summary**: `PASS: <n> | WARN: <n> | FAIL: <n>` (count across all D1–D7 findings).

### Logging compliance

Render Phase 1 inline findings.

- **Logging rule presence** (FAIL / WARN) — one line per L1 finding. Omit the sub-section if all pass.
- **`.logs/` directory** (WARN) — one line for L2 if absent. Omit if present.
- **`.gitignore` coverage** (WARN) — one line per L3 finding. Omit if covered.
- **`logging-waiver:` value** (FAIL) — one line per L4 finding. Omit if all valid.

If all L1–L4 checks pass: emit a single `PASS: logging rule installed, .logs/ present, .gitignore covers .logs/, all waiver values valid` summary line.

### Recommendations

- Memory index > 5 KB → suggest consolidation.
- `python3` missing or below 3.8 → install/upgrade Python so plugin hooks (distill-trigger, lazy-guard.*, model-router, pub.*) can run.
- Hardcoded paths found → run `/lazy-core.doctor` for details.
- Missing Execution-Discipline preamble → add per `lazy-core.skill-writing § 1` (or `lazy-core.agent-writing § 4`), or declare `execution-discipline-waiver: "<reason>"` in frontmatter with a concrete justification.
- Rule missing scope or waiver → add a `paths:` block-list (preferred) or `always_loaded: "<reason>"` per `lazy-core.rule-writing § 1`.
- Rule using inline-array `paths:` form → migrate to canonical block-list shape per `lazy-core.rule-writing § 1`. `lazy-core.doctor` Phase 4 offers an in-place migration that preserves all globs.
- Authoring rule without template reference → create `<plugin>/templates/<group>/<artifact>-template.md` (e.g. `templates/core/rule-template.md`) and add a `**Template:** <path>` pointer at the top of the rule body, per `lazy-core.scaffold`. `lazy-core.doctor` Phase 4 offers a templated fix.
- Rule over size budget → move long guidance to `<plugin>/skills/<skill>/references/*.md` per `lazy-core.rule-writing § 2`.
- "Optional" in phase/step heading → rename the heading; the user's accept/decline choice belongs inside an `AskUserQuestion`, not at the heading level.
- Narrative-padding match → review and drop the passage if its removal leaves executable behavior unchanged.
- `lazy.settings.json[experts]` FAIL → add missing fields per the expert schema; run `/lazy-core.install` wizard step to re-scaffold.
- Reference resolution FAIL → verify the agent reference uses a valid format (`<plugin>:<name>`, `user:<name>`, or bare `<name>`) and that the referenced artifact exists.
- Loop settings FAIL → re-run `/lazy-core.install` to scaffold or repair the `lazy-core.runtime` section in `lazy.settings.json`.
- Routine command FAIL → install the missing plugin or remove the unresolvable routine entry.
- Daemon stalled → run `/lazy-core.doctor` for the restart fix-offer.
- Logging rule not installed in consumer scope → run `/lazy-core.setup` to copy `lazy-log.logging.md` to `.claude/rules/`.
- `.logs/` missing → run `/lazy-core.setup` to bootstrap the directory.
- `.gitignore` missing `.logs/` entry → add `.logs/` to `.gitignore` manually or via `/lazy-core.setup`.
- `logging-waiver:` FAIL → replace empty/boolean waiver value with a concrete string reason per `lazy-core.skill-writing § 1`.
- Note: system prompt, skill registry, MCP instructions, deferred tool list are injected by Claude Code and cannot be reduced by the user.

## Failure modes

- **`/lazy-core.audit` exits with "lazy.settings.json is not valid JSON"** — the file was hand-edited and broke JSON syntax → fix the syntax or re-scaffold via `/lazy-core.install`.
- **Agent D reports "reference did not resolve" for an expert** — the `agent` field uses an unrecognised format or points to a non-existent artifact. Check the reference format (`<plugin>:<name>`, `user:<name>`, or bare `<name>`) and verify the artifact is installed → run `/lazy-core.install` to re-register.
- **Routine command FAIL when the plugin is installed** — the plugin cache uses a 4-level path `<registry>/<plugin>/<version>/bin/<plugin>`; an older install used a 3-level layout. Re-install the plugin to refresh the bin path in the routine entry.
- **D7 daemon liveness check always WARN on first use** — the runtime hasn't been started yet; this is expected after initial install → start the daemon via `launchctl load` or `systemctl --user start` as offered by `/lazy-core.install`.
- **Agent D silently reports nothing** — `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin` was not resolved (sandboxed environment or missing plugin path). Verify `${CLAUDE_PLUGIN_ROOT}` resolves to the plugin install path and `bin/lazy_settings.py` is present.
