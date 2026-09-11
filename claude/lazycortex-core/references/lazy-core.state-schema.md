---
description: The daemon's persisted state — the `.runtime/state.json` schema and its ten halt reasons, the working-tree protection invariants, and the `external_dirs` section with its `run_here` gate.
---
# lazy-core.state — persisted state, halt invariants, external dirs

§§ 9, 10 and 15 of `lazy-core.runtime-schema.md`, extracted and read on demand: open this file when a daemon is halted and you need the reason's meaning and its recovery path, when judging whether a routine may leave the working tree dirty, or when a checkout's working directories are symlinked in from outside the repository. The three sections keep the numbers they carried in the parent, and a `§ N` cross-reference below that names no file names a section of that parent.

## 9. State persistence

The daemon persists scheduling and halt state at `<repo>/.runtime/state.json`. Atomic temp+rename writes; load returns an empty schema on absent or unparseable file (so a corrupt state file never crashes the daemon). The directory is bootstrapped alongside `.logs/` by `/lazy-core.install` Step 7 and is listed in `.gitignore`.

Schema:

```json
{
  "last_run": {
    "<routine_name>": <unix_ts>
  },
  "git_watch": {
    "<routine_name>": {
      "last_seen_sha": "<full_hex>",
      "failed_items": [{ "sha": "<full_hex>", "...": "<rest of the item dict>", "reason": "<exit code + trimmed stderr tail>" }]
    }
  },
  "daemon_halted": {
    "halted_since": <unix_ts>,
    "triggered_by": "<routine_name|_git_pre|_git_post|_loop_detect|run|lazy-expert.pump>",
    "reason": "uncommitted_changes|git_pull_diverged|git_push_failed|git_remote_unavailable|git_local_failed|suspected_loop|inbox_collision|routine_config_invalid|config_violation|rate_limit",
    "dirty_paths": ["<git status --porcelain line>", ...],
    "resets_at": <unix_ts, rate_limit only>,
    "expert": "<expert_name|null>",
    "job_id": "<job_id|null>"
  }
}
```

`daemon_halted` is absent when healthy. `git_watch` is absent when no `git`-type routines are registered. `failed_items` is absent (or empty) when nothing has ever failed, or once every prior failure has cleared. A legacy `worktree_tasks` block may linger from the retired routine-side worktree path; nothing reads it anymore. `dirty_paths` is empty for git-related halt reasons (the tree is presumed clean at halt time; the halt cause is in the branch/remote state, not the working tree).

**Halt reasons.** Ten values reach this field. Nine of them are members of `HaltReason` in `bin/constants.py`, whose docstring calls itself the closed set; `config_violation` is the tenth and is **not** a member — the daemon writes it as a bare string literal at the routine-error escalation. Read the enum as the vocabulary of everything except that one value, never as the whole field.

- `uncommitted_changes` — routine left the working tree dirty (see § 10). Recovery: dirt-cleanup wizard via `/lazy-runtime.recover`.
- `git_pull_diverged` — pre-tick fetch found that local and origin both have commits the other doesn't. Recovery: operator repairs branch state manually, then `/lazy-runtime.recover` clears the halt.
- `git_push_failed` — post-tick push retried `POST_TICK_MAX_PUSH_ATTEMPTS` (3) times and kept failing. Recovery: operator investigates push refusal (auth, branch protection, persistent race), then `/lazy-runtime.recover`.
- `git_remote_unavailable` — a pre- or post-tick git failure whose stderr names an unreachable remote (network, DNS, remote read). Recovery: self-clearing — once the halt is ≥1h old, the hourly doctor tick probes `git ls-remote` and resumes the daemon when the remote answers; `/lazy-runtime.recover` clears it earlier.
- `git_local_failed` — a pre- or post-tick git failure whose stderr named no transport marker (a held `index.lock` past the retry backoff, a bad ref, checkout permissions — or a network failure whose stderr the transport classifier didn't recognise). Recovery: when `triggered_by` is a sync step (`_git_pre` / `_git_post`), the same hourly doctor probe clears it once the remote answers; otherwise, or to clear earlier, operator inspects the checkout and runs `/lazy-runtime.recover`.
- `suspected_loop` — loop-detection heuristic fired: one identical diff (`git patch-id --stable`) was committed ≥ `loop_detect_threshold` times by the same registered-bot author within the `loop_detect_window` commit window. Commit volume alone never trips it — only a diff that keeps re-landing unchanged, directly or as one leg of an oscillation. The offending patch-id, author, and repeated commit subjects are in the halt detail — the `halt:<repo>` incident and the runtime journal — not in the halt block, which carries no detail field. Recovery: operator investigates the routine's commit pattern and runs `/lazy-runtime.recover` (mode `manual-fix`) once resolved. The rule reads a commit window rather than a live process, so a resume while the repeated commits are still inside `loop_detect_window` re-halts on the very next iteration even after the producer is fixed.
- `inbox_collision` — the startup collision check found another checkout on this host driving the same physical expert inbox. `triggered_by` is `run` (the daemon's startup path, not a routine) and the halt detail names the colliding checkouts. The halt is symmetric and permanent: both checkouts halt, and retiring the other supervisor unit does not release the survivor. A collision created while a daemon is already running is invisible to it until its next start — the newly started daemon is the one that sees it and halts. Recovery: operator gives one checkout an inbox of its own (or retires that checkout), then `/lazy-runtime.recover` (mode `manual-fix`) clears the halt. This is the one reason a clear is not re-checked on the next tick — the collision check runs only at daemon start, so a halt cleared before the inboxes are separated resumes a daemon that duplicates every dispatch without noticing.
- `routine_config_invalid` — a `routines[*]` entry failed `validate_routine_entry` when the daemon read the registry (see § 10). `triggered_by` names the offending routine; the schema error text is in the routine's own `routine:<name>` incident. Recovery: operator fixes the settings entry, then `/lazy-runtime.recover` (mode `manual-fix`).
- `config_violation` — a routine tick exited with error text `_classify_routine_error` read as a settings-invariant violation: the text carries `config_violation` or `compute_inputs_failed`, typically raised by a plugin CLI the routine drives. The failed tick already lands as a `routine:<name>` incident; the halt escalates it to class 1 so a routine that will keep failing every tick puts the operator on the same `/lazy-runtime.recover` path as git divergence instead of failing quietly forever. `triggered_by` names the routine and the halt detail — in the `halt:<repo>` incident, not in the halt block — is the error text trimmed to 200 characters. This is the one reason the daemon writes as a bare string literal rather than a `HaltReason` member. Recovery: operator fixes whatever the routine's CLI rejected, then `/lazy-runtime.recover` (mode `manual-fix`) clears the halt.
- `rate_limit` — an expert run's `rate_limit_event` frame tripped the rate-limit guard (`daemon.rate_limit_guard`): the subscription window is closed. The block carries `resets_at` — the latest reopening time across the host-local flag records at `${XDG_CACHE_HOME:-$HOME/.cache}/lazycortex/rate-limit/`. Self-lifting: `_run_iteration` clears the halt (and resolves the `halt:<repo>` incident) once `now >= resets_at`; a block with no `resets_at` is treated as already expired. While halted the loop sleeps `min(max(resets_at − now, polling_interval_sec), 3600)` rather than idling at the polling interval the way every other halt does — floored at that interval so an already-past `resets_at` cannot spin the loop, capped at an hour so manual resume, config edits, and self-update lag by at most that. Git sync stays alive, and the self-update restart is NOT skipped for this reason (state survives the restart, a restart burns no tokens). Recovery: none needed; `/lazy-runtime.recover` (mode `manual-fix`) resumes early — safe, the pump's pre-spawn flag check still defers spawns while the flag lives.

**Unpushed-consume record.** `<repo>/.runtime/consumed-unpushed.log` lists, one `<expert>/<job_id>` per line, every job `consume-job` marked `CONSUMED` since the last successful publish; a sibling `.lock` file serialises appends against the rewrite. A publish that lands (or finds nothing to push) drops the entries it started with; a rebase-conflict discard removes the `CONSUMED` marker of every listed job and empties the record, so a result whose landing commit was thrown away is collected again rather than retired. Without remote push configured the record is emptied on every post-iteration step — nothing can be discarded, so nothing is pending.

**Incident cause `cursor_probe_failed`** (kind `routine_error`, key `routine:<name>`): on a discard, git could not judge whether a `git_watch.<name>.last_seen_sha` is still reachable from the new `HEAD` (a sha the repository cannot resolve counts as unreachable and is rewound; this cause is only the lookup itself failing). The cursor is left as it stands and the tick still completes; the routine's next clean tick resolves the incident. If the incident persists, the routine may be stalled on a sha `HEAD` never reaches — inspect `git_watch.<name>` in `state.json`.

Persistence consequences:
- `last_run` survives daemon restart and laptop sleep — slow routines (e.g. every 6h) are honored across restarts.
- `git_watch.<name>.last_seen_sha` survives daemon restart — `git` routines do not re-dispatch already-handled commits after a reboot. A post-tick discard rewinds it to the merge-base with origin when the discarded range held it (`lazy-core.runtime-schema.md` § 2).
- `git_watch.<name>.failed_items` survives daemon restart — a `command`-shape worker crash across a restart still retries on the next tick rather than being lost with the in-memory tick.
- `daemon_halted` survives daemon restart — a halted daemon stays halted across reboots until the operator runs `/lazy-runtime.recover`.

---

## 10. Working-tree protection and halt invariants

The daemon halts (writes a top-level `daemon_halted` block to state.json and stops scheduling routines) on any of these conditions:

- **Dirty working tree after a routine** — `git status --porcelain` non-empty → `reason: uncommitted_changes`. Why daemon-wide rather than per-routine: the daemon rides the operator's base branch directly, so leftover dirt is operator/routine WIP that the next iteration's routines would read as inconsistent tree state (and commit over). If a single routine left dirt, even routines that operate purely in gitignored paths would see that inconsistent state in the next iteration. Halting everything is the safe default.
- **Pre-tick divergence** — local and origin branches both have commits the other doesn't → `reason: git_pull_diverged`. Automatic resolution would risk dropping the operator's commits, so the daemon halts and waits.
- **Post-tick push exhausted retries** — the rebase+push retry loop failed `POST_TICK_MAX_PUSH_ATTEMPTS` times → `reason: git_push_failed`. Indicates either persistent operator-side races (rare) or branch-protection / auth refusal.
- **Other pre- or post-tick git failure** — an unreachable remote → `reason: git_remote_unavailable`; a purely local failure → `reason: git_local_failed`.
- **Malformed registry entry** — an entry under `routines` fails `validate_routine_entry` when the daemon loads the registry, before any scheduling decision reads it → `reason: routine_config_invalid`. The entry is dropped from that iteration's registry and opens a `routine:<name>` incident carrying the schema error verbatim; every further broken entry increments `routine_errors_total{reason="routine_config_invalid"}` under its own routine label, while the halt block keeps the first one's attribution. Why daemon-wide: a schema violation never self-heals — it stands until the operator edits the settings — so skipping it quietly every tick would hide a routine that silently stopped working.

Per-job attribution: when an expert (inside `expert-pump`) is the cause of a dirty-tree halt, the halt block also records `expert` + `job_id`. The job's `response.json` is overridden with `outcome: "error", error.category: "uncommitted_changes"` and `DONE` is touched. Git-related halts carry no expert attribution (the daemon, not a routine, owns remote sync).

A pre-tick rebase conflict during post-tick remote sync is **not** a halt — the daemon discards the current tick's work (`rebase --abort && reset --hard origin/<base_branch>`) and logs `tick discarded: operator-conflict`. The next tick re-runs the routine on top of the operator's commits. Halting on a routine-conflict would block forever for any operator who edits the same files the routine touches.

Recovery for every halt path: `/lazy-runtime.recover`. For `uncommitted_changes` the skill walks the operator through commit / stash / discard / abort. For each of the other nine reasons the skill prints reason-specific repair guidance and asks the operator to fix the cause externally before confirming resume (mode `manual-fix`). Once the tree is clean, the halt block is atomically cleared. See `claude/lazycortex-core/skills/lazy-runtime.recover/SKILL.md`.

The check is read-only on the daemon side — the daemon never cleans the tree itself. The operator authors every commit in the recovery path.

---

## 15. `external_dirs` — externally-sourced working directories

A repository whose working directories are partly untracked declares them across both settings layers. The split follows what travels: the list is a property of the project and rides along with every clone; the location is a property of the machine.

Tracked `lazy.settings.json`:

```json
{
  "external_dirs": {
    "_version": 1,
    "paths": ["Data", "-Inbox", "-config"]
  }
}
```

Gitignored `lazy.settings.local.json`:

```json
{
  "external_dirs": {
    "root": "~/box/Project",
    "declined": false
  }
}
```

| Field | Layer | Meaning |
|---|---|---|
| `paths` | tracked | Repo-relative paths sourced from outside the repository. |
| `root` | local | Absolute path the declared paths are linked from on this machine. `~` and `$VAR` expand on read; a relative value is anchored to the repository root, never to the reading process's working directory. |
| `declined` | local | Records that the operator chose not to configure a source, so install never re-asks. |

Each declared path resolves to `<root>/<path>`. A declared entry that climbs out of the repository (`../…`) is dropped on read: the list is tracked and travels with every clone, while repair creates directories and plants symlinks, so only paths the repository contains are ever acted on.

A path is diagnosed as one of `ok`, `missing`, `dangling`, `wrong_target`, `not_a_symlink`, `source_missing`, or `unconfigured`. Exactly three are repaired by re-linking — `missing`, `dangling`, and `wrong_target`, and the last two only while the source exists. `ok` is already correct and left `unchanged`; `not_a_symlink`, `source_missing`, `unconfigured`, and a `dangling` link whose source is gone are reported to the operator and left untouched. Real content occupying a declared path is never removed. A repair the filesystem refuses is reported like any other unrepairable state, with the reason appended to the observed status, and the remaining paths are still repaired.

Alongside the status, each declared path carries an ignore verdict: `ignored`, `dir_only`, or `absent`. The distinction exists because a repaired slot holds a symlink, which git classifies as a file, while the ordinary `.gitignore` form for a working directory (`Data/`) matches directories only — so a repository whose ignore rules look complete still sees every linked path, its tree is dirty, and the daemon halts on its first tick. `dir_only` names exactly that case and is fixed by adding the anchored slashless line (`/Data`) next to the existing one, never by replacing it; `absent` means no rule covers the name in any form. Install proposes the missing lines after the repair and appends them only with the operator's confirmation, since `.gitignore` is tracked; audit reports the two cases separately and `lazy-core.autocheckup` reports rather than applies.

An absent or empty section is the default and changes no behaviour. Four consequences of a non-empty section:

- The expert sandbox must grant the location each declared slot points at, not the slot itself (`lazy-core.expert-runtime-schema.md`, *Filesystem sandbox*). `sandbox-sync` derives those locations from the planted symlinks, so it runs after the repair, and `sandbox-audit` catches a source root that moves later.

- An `inbox` routine whose `inbox_dir` is declared and does not resolve fails its tick with `exit = -1` and the error tag `external_dir_broken: <path>`, which folds into the routine's own `routine:<name>` incident and carries the metric label `reason="external_dir_broken"`. An **undeclared** missing inbox stays a silent idle tick, unchanged.
- `daemon.run_here` is where the second daemon is refused, and it must name both halves of the answer. See *The run-here gate* below.
- Install refuses to put a supervisor on a checkout whose inbox another daemon on this host already drives, and skips the supervisor, sandbox, and metrics steps entirely rather than installing them and reporting afterwards.

**The inbox-ownership halt is not gated on this section.** Every daemon checks at startup whether another checkout on the host resolves an inbox routine to the same physical directory, including a repository that declares no external directories at all — the collision is reachable through any symlink, not only a declared one. Where it fires the condition is real: two daemons over one inbox import every document twice.

That halt is symmetric and permanent. Both checkouts raise it at their own next start, and removing the stray supervisor unit does not release the survivor — the halt is persisted state, and only a dirty-tree halt auto-clears. Decide which checkout drives the inbox, take the other out of its project's `daemon.run_here`, then run `/lazy-runtime.recover` in the one that should keep going. The check runs once per daemon start, so a collision created while a daemon is already running is seen by the newly started daemon, not by the incumbent.

### The run-here gate

Nothing in this runtime reconciles two daemons driving one project. They duplicate every dispatch, overwrite each other's `last_run` ledger, and commit over each other. `daemon.run_here`, in the **tracked** settings file, is the single answer to which daemon is the real one, and the daemon itself enforces it at startup — not only the install that placed the supervisor, so a leaked or hand-copied unit cannot outlive the answer.

The value maps a hostname to the absolute path of the checkout that machine drives:

```json
"run_here": { "nexus": "~/lazy-runtime/Money" }
```

Both halves are load-bearing, and neither older shape is accepted:

- A boolean cannot say which machine answered it. A project reached from a second machine — a synced path, or an independent clone — reads the same `true` on all of them.
- A bare hostname cannot say which checkout. One machine commonly holds several checkouts of a project, a working copy alongside the one the daemon drives, and a hostname grants a daemon in each.

The key is matched against `hostname -s` lowercased; the value is matched against the checkout the process was started in, with `~` expanded and both sides resolved, so a symlinked path still matches. `{}` names nothing and no machine runs the daemon. The map is tracked rather than local because a gitignored overlay never reaches a machine that cloned the repository independently, which is exactly where a second daemon appears.

A daemon started anywhere the map does not name records a `daemon_error` incident with cause `run_here_denied` and exits non-zero. It raises no halt block: `.runtime/` is shared by every machine reaching a synced checkout, and a halt written there by a machine with no claim would stop the daemon that does have one.
