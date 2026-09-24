---
name: lazy-routine.register
description: "Run when the daemon should start doing something on its own — the operator asks to schedule recurring work, watch an inbox directory, react to local git HEAD, or scan markdown files by frontmatter. Also dispatched by plugin install skills (`lazy-spec.install`) to wire their own routines instead of hand-writing settings JSON. Type-aware wizard; refuses to overwrite an existing routine without `--force`."
allowed-tools: Read, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date -u *), Bash(git check-ignore *), Write, AskUserQuestion, Agent
dirty-tree-waiver: "registers a routine in lazy.settings.json — operator commits explicitly to coordinate with sibling routines / install steps"
---
# Routine Register

Register a named routine in the flat `routines` section of `.claude/lazy.settings.json`. Enforces `<plugin>.<verb>` naming. Refuses to overwrite an existing routine unless `--force` is set. Validates the per-type schema through the `routine-register` verb.

Used by plugin install skills (programmatic call) and by humans via `/lazy-routine.register` (wizard mode).

## Execution discipline (MANDATORY — read before any action)

This skill has 4 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Collect + validate inputs`
   - `Step 2 — Check for existing registration`
   - `Step 3 — Register routine`
   - `Step 4 — Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Collect + validate inputs

Required: `name` (string, `<plugin>.<verb>` pattern).

The remaining fields depend on the routine **type**. Allowed types: `subprocess` (default), `inbox`, `schedule`, `git`, `md-scan`.

### 1a. Resolve the type

If the caller passed a `cfg` dict, take `cfg.get("type", "subprocess")` and skip to 1c with the dict.

In wizard mode (no `cfg`), ask:

```
Context (print before asking):
- Where: /lazy-routine.register · Step 1a — Resolve the type; target routine `<name>` in `.claude/lazy.settings.json`
- Found: no `cfg` dict passed — wizard mode; name `<name>` given, no type on record
- Why asking: the type decides which fields Step 1b collects and how the daemon fires the routine; nothing derives it
- Answers: `subprocess` — periodic command (default); `inbox` — scan a dir, fire once per file (job-queue moves the file; command leaves it in place); `schedule` — cron-driven, one fire per cron boundary; `git` — watch local HEAD, fire once per item; `md-scan` — scan markdown files matching globs, filter by frontmatter, fire in-place (no file move). Persisted as `routines.<name>.type` in Step 3; never re-asked (re-registration refuses without `--force`)
AskUserQuestion: header "Routine type", question "Which routine type should `<name>` be registered as in `.claude/lazy.settings.json`?", options `subprocess` / `inbox` / `schedule` / `git` / `md-scan`, each with the description above.
```

### 1b. Collect type-specific fields

Per type, ask only the required + commonly-needed optional fields. Schemas live in `${CLAUDE_PLUGIN_ROOT}/bin/routine_types.py::SCHEMAS`. Wizard prompts:

Every type ends with the same EITHER/OR question — `command` (list) OR `expert` (name) + `request` (JSON-shaped block). The validator enforces exactly-one; the wizard asks the question once at the end of the type-specific fields.

- **subprocess** — `interval_sec` (int), `timeout_sec?` (int). Then EITHER `command` OR `expert` + `request`.
- **inbox** — `inbox_dir` (path relative to repo), `interval_sec`, `timeout_sec?`. Then EITHER `command` OR `expert` + `request`. With `expert + request`: files are moved into job staging; with `command`: files stay in the inbox until the consumer removes them.
- **schedule** — `cron` (5-field expression). Then EITHER `command` OR `expert` + `request`.
- **git** — `repo_dir?` (default `.`), `remote?` (vestigial/ignored — remote sync is the daemon's job; accepted for schema compatibility but has no effect on the watch), `branch` (vestigial — the watch target is always local HEAD; the field is retained in the schema for legacy round-trip compatibility), `watch` (one of `new_commits` / `new_files` / `changed_files` / `deleted_files` / `renamed_files`), `path_filter?` (a git pathspec narrowing the watch before any item exists — one pattern or a list of them, exclude magic such as `:(exclude)<glob>` included), `filter?` (same composite frontmatter block md-scan takes), `watch_runtime_trees?` (boolean, default false — true lets the watch see the runtime's own tracked trees, which are subtracted from every watch otherwise), `group?` (the unit of work: `"all"` — the default when absent — folds every changed path of the tick into one unit carrying `dir: "."` and `paths`; `"file"` is one unit per changed file; `"dir"` one per parent directory; a list of directory globs one per matched directory, the deepest matching glob winning and list order carrying nothing. The same key governs `command` and `expert` routines; rejected with `new_commits`. A boolean value and the retired `group_globs` key fail validation — `routine-migrate --apply` rewrites them). Independently of the mode, a commit whose message ends with the git trailer `Lazy-Watch: skip` is invisible to every git routine: its items are dropped and the cursor moves past it, `interval_sec`. Then EITHER `command` OR `expert` + `request`.
- **md-scan** — `paths` (list of vault-relative globs, e.g. `["requests/*.md"]`), `filter` (optional composite filter block; e.g. `{"frontmatter": {"request_status": {"in": [null, "draft"], "not_in": []}}}`; `null` in `in` matches a missing key or explicit null), `interval_sec`, `timeout_sec?`. Then EITHER `command` OR `expert` + `request`. No file move — the consumer gets the absolute path of each match and edits in place.

Three common fields are asked for every type, after the type-specific ones:

- `hooks_enabled?` (list of lazycortex hook short names) — which hooks may run inside this routine's own subprocesses. Default empty: the daemon exports an empty allow-list and every lazycortex hook stays silent, which is what keeps a tree-writing hook from dirtying the worktree behind an autonomous commit. Ask only when the operator says the routine needs one.
- `ignore_halt?` (bool, default false) — let the routine tick while the daemon is halted. It also skips the post-tick working-tree check for that routine, so offer it only for work whose whole point is clearing a stuck state.
- `git_author?` (`{name, email}`) — the bot identity stamped on any commits the routine's own subprocess makes (exported as `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL`). Offer it whenever the routine's `command:` consumer commits; canonical form is `{name: <routine-family>, email: <routine-family>@bot.invalid}` — never the operator's identity, and never a domain other than `@bot.invalid` (loop-detect and coordinator operator-vs-bot checks key on it). Absent = the routine commits under the daemon process's identity.

Build a single `cfg` dict carrying `type` + the collected fields.

### 1c. Pre-flight validation

1. `name` matches `<plugin>.<verb>` or `<plugin>.<verb>.<scope>` (two or three non-empty dot-separated parts). `<plugin>` is the plugin's own namespace — `lazy-wiki`, `lazy-core`, and so on per `lazy-core.hygiene` § Naming; the third segment exists for routines registered per scope, one instance each (`lazy-wiki.mirror-sync.<scope-id>`). Else abort: "routine names must be `<plugin>.<verb>[.<scope>]` format. Got: `<name>`."
2. The per-type schema is enforced by the `routine-register` verb itself (Step 3): a schema violation prints the `RoutineConfigError` message and exits 1, and nothing is written. Abort with that message verbatim.
3. **Working-area gitignore check** — for `inbox` routines, run `git check-ignore -q -- <inbox_dir>` (the `--` is mandatory: an inbox directory whose name starts with a dash, e.g. `-Inbox`, is otherwise parsed as options and git fails with `unknown switch`). Exit 0 = ignored. Exit 1 = tracked → ask:

   ```
   Context (print before asking):
   - Where: /lazy-routine.register · Step 1c — Pre-flight validation; target `<inbox_dir>` (inbox of routine `<name>`)
   - Found: `git check-ignore -q -- <inbox_dir>` exited 1 — the directory is tracked, not gitignored
   - Why asking: inbox routines move tracked files between iterations, which dirties the working tree and triggers the daemon's halt protection; touching `.gitignore` is the operator's call
   - Answers: `Add <inbox_dir>/ to .gitignore now` — appended to `.gitignore` now, not committed (operator commits when ready); `Continue anyway — I will commit moves manually` — registered as is, nothing written to `.gitignore`; `Abort registration` — nothing written, outcome `aborted`
   AskUserQuestion: header "Inbox gitignore", question "`<inbox_dir>` is not gitignored — add `<inbox_dir>/` to `.gitignore` before registering inbox routine `<name>`?", options `Add <inbox_dir>/ to .gitignore now` (recommended) / `Continue anyway — I will commit moves manually` / `Abort registration`, each with the description above.
   ```

   On "Add" → append to `.gitignore`; do not auto-commit (operator commits when ready). On "Abort" → outcome `aborted`.

Outcome: `validated`, `aborted`, or `gitignore-warned`.

## Step 2 — Check for existing registration

Load the flat `routines` section and check if `name` is already a key (the section IS the routines map — each key is a routine name, with `_version` the lone reserved key):

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" routine-show '<name>')
```

It prints `absent`, or `present` followed by the entry JSON on a second line.

If `present` and `--force` not set and no `--managed` list was passed → abort: "routine `<name>` already registered. Use `--force` to overwrite, `--managed <key>,<key>` to reconcile the caller's own keys, or call `/lazy-routine.unregister` first."

If `present` and `--force` is set → proceed (will overwrite).

If `--managed <key>,<key>` was passed → proceed in reconcile mode whether the entry is present or absent. **This is the shape a plugin install skill uses**, and it is the only one that keeps an old registration current. The caller names the keys its plugin owns — the request template, the path mask, the filter block, the protocol list. Every other key the entry already carries is the operator's answer and is left exactly as it stands; a shipped key the entry never carried is filled in.

Outcome: `absent`, `overwrite-forced`, `reconciling`, or `aborted`.

## Step 3 — Register routine

Without `--managed`, pass the typed cfg dict to the core `routine-register` verb (prints `registered`):

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" routine-register '<name>' --cfg '<cfg-json>')
```

With `--managed`, pass the same cfg plus the owned-key list to the core `reconcile-routine` verb (prints `{"status": "registered|refreshed|unchanged"}`):

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" reconcile-routine '<name>' --cfg-json '<cfg-json>' --managed '<managed-keys>')
```

Both validate again before write; if anything slipped past Step 1, they print the schema error (`routine-register` as a bare line, `reconcile-routine` as `{"status": "error", "reason": …}`) and exit 1.

Outcome: `registered`, `refreshed`, `unchanged`, or `error`.

## Step 4 — Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

Print: "registered routine `<name>` (type=<type>, <key params>)", or in reconcile mode "`<outcome>` routine `<name>` (managed: <keys>)".

## Failure modes

- **"routine names must be `<plugin>.<verb>` format"** — name does not contain a dot or has an empty part → rename to follow the convention (e.g. `lazy-review.tick`).
- **"routine `<name>` already registered"** — a routine with this name exists in settings → call `/lazy-routine.unregister` first, or retry with `--force`.
- **"unknown type 'X'"** — `cfg.type` is not one of `subprocess`/`inbox`/`schedule`/`git`/`md-scan` → fix the type or upgrade `lazycortex-core` to a version that supports it.
- **"missing required field(s): […]"** — per-type schema rejected the input → fill the missing fields and retry.
- **"`<inbox_dir>` is not gitignored"** — inbox-type routine working area is tracked → add it to `.gitignore` (the wizard offers this) or restructure the routine to operate in a gitignored path.
- **"`.claude/lazy.settings.json` unwritable"** — file permissions or directory absent → check that `/lazy-core.install` has bootstrapped the file and it is not read-only.
