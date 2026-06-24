---
chapter_type: walkthrough
summary: Register a dot-namespaced periodic routine with the runtime daemon and remove it cleanly when it is no longer needed.
last_regen: 2026-06-24
diagram_spec:
  anchor: "How registration and pickup flow"
  request: "Sequence diagram showing the user running /lazy-routine.register, the skill writing lazy.settings.json, the daemon picking up the new routine on its next cycle without restart, and the user later running /lazy-routine.unregister to remove it. Include the built-in protection check for lazy-expert.pump."
  kind_hint: sequence
source_skills:
  - lazy-routine.register
  - lazy-routine.unregister
---
# Register a periodic routine with the runtime daemon

The runtime daemon runs registered plugin routines in serial order on a schedule you control — no two routines ever contend over the working tree or git state. This walkthrough covers the full round-trip: add a routine for your plugin, confirm the daemon picks it up on its next cycle without a restart, and remove it cleanly when the work is done. The two skills are `/lazy-routine.register` (a type-aware wizard that validates and writes to `lazy.settings.json`) and `/lazy-routine.unregister` (an idempotent removal that protects the built-in `lazy-expert.pump` from accidental deletion).

## Outcome

After this walkthrough you know how to register any of the five routine types, verify the daemon picks the new routine up without a restart, and remove it cleanly. At the end of the register path the routine's name appears in the `routines` map in `.claude/lazy.settings.json` and the daemon is scheduling it automatically. At the end of the unregister path the entry is gone and the daemon skips it from the next cycle forward.

## What you need

- `lazycortex-core` installed in the project with the expert runtime enabled (`/lazy-core.install` with daemon opt-in complete, `run.sh` present).
- `.claude/lazy.settings.json` already bootstrapped and writable — re-run `/lazy-core.install` if it is absent.
- A dot-namespaced routine name in `<plugin>.<verb>` form (e.g. `lazy-review.tick`, `acme-lint.sweep`).
- For `inbox`-type routines: the inbox directory should be gitignored — the wizard checks and offers to add it if not.

## The journey

### Step 1 — Decide which routine type fits your use case

Before running the wizard, decide which of the five types matches what your routine does. All types share the same serial no-contention guarantee — the daemon runs one routine at a time.

Every type also takes one of two dispatch shapes:

- `command` — spawn a subprocess on each fire, with PID-based dedup for per-item types so a slow consumer is not re-spawned for the same item.
- `expert` + `request` — dispatch one job to a named expert via the expert-runtime queue.

The validator enforces exactly-one of the two dispatch shapes. Choose the type, then you will be asked for the type-specific fields followed by the dispatch shape question.

- **subprocess** — fire on a fixed interval (e.g. every 300 seconds). Required: `interval_sec`. Good for lint sweeps, data refreshes, and any periodic invocation.
- **inbox** — watch a directory and fire once per file found. With `expert + request` the file is moved into job staging; with `command` it stays in the inbox until the consumer removes it. Required: `inbox_dir`, `interval_sec`.
- **schedule** — fire once per cron boundary (5-field cron expression). Required: `cron`. Use when wall-clock timing matters more than a fixed cadence.
- **git** — watch local HEAD for new commits, new files, changed files, deleted files, or renamed files; fire once per item. Required: `watch`, `interval_sec`. The `branch` and `remote` fields are vestigial — the watch always targets local HEAD regardless of their values, and remote sync is the daemon's own job. The wizard may surface them for schema compatibility; leave them blank or skip them.
- **md-scan** — scan markdown files matching vault-relative globs, filter by frontmatter values, and fire once per match. Files are edited in place by the consumer — no move. Required: `paths` (list of globs), `interval_sec`. Optional: `filter` (composite filter block, e.g. `{"frontmatter": {"key": {"in": [...], "not_in": [...]}}}`) — a `null` value in the `in` list matches files where the key is absent or explicitly null, which is useful for picking up files that have never been processed; an absent `filter` matches all files.

### Step 2 — Run the register wizard

Run `/lazy-routine.register`. The wizard asks for a name, then the type, then the type-specific fields in sequence.

For a `subprocess` routine the minimal exchange looks like:

```
Name:         lazy-review.tick
Type:         subprocess
Command:      ["python3", "bin/review_tick.py"]
interval_sec: 300
```

For an `inbox` routine the wizard additionally checks whether `inbox_dir` is gitignored. If it is not, it offers to append the path to `.gitignore` — accept this. Inbox routines move files between iterations; a tracked inbox directory dirties the working tree and triggers the daemon's halt protection.

For an `md-scan` routine the wizard asks for the glob list, the optional frontmatter filter dict, and the dispatch shape. A `null` value in the filter's `in` list matches files where the key is absent — useful for picking up files that have never been processed (e.g. `{"frontmatter": {"request_status": {"in": [null, "draft"], "not_in": []}}}`).

For a `git` routine, supply `watch` (one of `new_commits` / `new_files` / `changed_files` / `deleted_files` / `renamed_files`) and `interval_sec`. The `branch` and `remote` fields are accepted by the schema for compatibility but have no effect on which changes the watch observes — skip them.

The skill validates the `<plugin>.<verb>` naming pattern and the per-type schema before writing anything. If validation fails it aborts with a clear message — fix the reported field and re-run.

### Step 3 — Confirm the routine is registered

After the wizard completes it prints:

```
registered routine `<name>` (type=<type>, <key params>)
```

To double-check, run `/lazy-core.doctor` to inspect the current routine registry, or attempt to re-run `/lazy-routine.register` with the same name — it refuses with "already registered", which confirms the entry exists.

### Step 4 — Let the daemon pick it up

No restart is needed. The daemon re-reads `lazy.settings.json` at the start of every sleep cycle. On the next cycle after registration it begins scheduling the new routine according to its `interval_sec` or `cron` expression.

If the daemon is not yet running, start it:

```
./run.sh
```

If the daemon has halted on a dirty working tree, run `/lazy-runtime.recover` to walk through cleanup and clear the halt block before starting.

### Step 5 — Verify the routine fires

For `subprocess` routines, watch for the command's output in the daemon's log (the standard output of `./run.sh`). For `inbox`, `git`, and `md-scan` routines the daemon dispatches agent jobs — run `/lazy-expert.list-jobs` to confirm jobs are appearing after the first cycle fires.

### Step 6 — Remove the routine when no longer needed

Run `/lazy-routine.unregister <name>` (e.g. `/lazy-routine.unregister lazy-review.tick`).

The skill checks the settings file, prints a confirmation, and removes the entry. Unregistering a routine that does not exist is a no-op — it prints an INFO message and exits cleanly without an error.

The built-in `lazy-expert.pump` routine is protected from accidental removal. Attempting to unregister it without `--force` aborts with a warning. Only pass `--force` if you intentionally want to stop expert-job processing; re-run `/lazy-core.install` to restore it.

The daemon picks up the removal on its next cycle — no restart needed.

## After you're done

The routine is no longer in `routines` and the daemon skips it from the next cycle forward. To bring it back, call `/lazy-routine.register` again with the same name and configuration. Plugin install skills can re-register their routines automatically on the next install pass. Run `/lazy-core.doctor` at any time to verify the current routine registry and daemon state are consistent.

## How registration and pickup flow
