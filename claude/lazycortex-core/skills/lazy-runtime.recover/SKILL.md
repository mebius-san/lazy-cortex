---
name: lazy-runtime.recover
description: "Run when the runtime daemon has stopped scheduling — routines no longer fire, or `.runtime/state.json` carries a `daemon_halted` block. Branches on the halt reason: `uncommitted_changes` walks the operator through commit / stash / discard of the dirt a routine left behind; every other reason — `git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`, `git_local_failed`, `suspected_loop`, `inbox_collision`, `routine_config_invalid`, `config_violation`, `rate_limit` — prints reason-specific guidance and waits for the operator to repair the cause outside the skill. Ends by atomically clearing the halt so the daemon resumes."
allowed-tools: Read, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(git status *), Bash(date -u *), Write, AskUserQuestion, Agent
dirty-tree-waiver: "applies operator-chosen cleanup ops to the working tree (commit/stash/discard) — the operator is the commit author, not this skill"
---
# Runtime Recover

This skill covers two families of halt:

- **`uncommitted_changes`** — a routine or expert left the working tree dirty. The skill walks the operator through commit / stash / discard / abort.
- **`git_pull_diverged` / `git_push_failed` / `git_remote_unavailable` / `git_local_failed` / `suspected_loop` / `inbox_collision` / `routine_config_invalid` / `config_violation` / `rate_limit`** — a pre- or post-tick git step hit a state the daemon refuses to resolve for you, the loop detector caught a bot re-committing one diff, a second checkout drives the same physical inbox, a routine entry failed its schema, a routine's CLI rejected the settings it reads, or the subscription rate-limit window closed. The skill describes the situation and asks the operator to repair it externally (manual git ops, a network fix, a settings edit, stopping the cycling producer) — or, for `rate_limit`, simply to wait or resume early — before confirming resume.

The two families cover the whole halt vocabulary: all ten `reason` values the daemon writes (`${CLAUDE_PLUGIN_ROOT}/references/lazy-core.state-schema.md` § 9) reach a branch in Step 2. In both families the skill ends with an atomic clear of the `daemon_halted` block from `<repo>/.runtime/state.json`. The daemon resumes scheduling on its next iteration.

**The halt block carries no `detail` field.** Only the second family's guidance depends on one, and for every reason there it is read from the `halt:<repo>` incident (`Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" error-list --kind daemon_halt)`) or from the runtime journal at `.logs/lazy-core/runtime/<date>.jsonl`, whose record `name` is the halt's `triggered_by`. Never report a detail the halt block does not hold.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Read halt context`
   - `Step 2 — Choose cleanup mode`
   - `Step 3 — Apply cleanup`
   - `Step 4 — Resume + report`
   - `Step 5 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Read halt context

Load `daemon_halted` from `<repo>/.runtime/state.json`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, sys
from pathlib import Path
import recover
halt = recover.read_halt(Path('.'))
if halt is None:
    print('not_halted')
else:
    print(json.dumps(halt, indent=2))
" )
```

If output is `not_halted`: print "Daemon is not halted. Nothing to recover." and skip to Step 4 with outcome `not-halted`.

Otherwise, parse the JSON and surface to the operator:

- `triggered_by` — which routine name, or `_git_pre` / `_git_post` for daemon-side remote-sync halts, or `lazy-expert.pump` for pump-internal halts.
- `expert` + `job_id` — populated when the dirt came from inside an expert.
- `reason` — the halt reason, one of the ten the daemon writes: `uncommitted_changes` (family one), and `git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`, `git_local_failed`, `suspected_loop`, `inbox_collision`, `routine_config_invalid`, `config_violation`, `rate_limit` (family two). A value outside that set is not a halt this daemon wrote — print the block verbatim and stop rather than guessing a branch.
- `dirty_paths` — captured `git status --porcelain` lines (only populated when `reason == uncommitted_changes`; empty otherwise).
- `resets_at` — epoch seconds when the rate-limit window reopens (only populated when `reason == rate_limit`; the daemon lifts this halt itself at that time).

Outcome: `context-shown` or `not-halted`.

## Step 2 — Choose recovery mode

Branch on `reason`.

### Reason = `uncommitted_changes` — dirt cleanup wizard

```
Context (print before asking):
- Where: /lazy-runtime.recover · Step 2 — Choose recovery mode; target working tree of <repo-root>
- Found: `daemon_halted.reason = uncommitted_changes`, triggered by `<triggered_by>` (expert `<expert>`, job `<job_id>` when set); dirty paths: <dirty_paths lines>
- Why asking: the dirt is a routine's or expert's output — only the operator knows whether it is work to keep or noise to drop, and `discard` is irreversible
- Answers: `commit` — `git add -A && git commit -m <message>` in Step 3, one follow-up asks for the message; `stash` — `git stash push -u` in Step 3, restore by hand later; `discard` — `git checkout -- . && git clean -fd` in Step 3, irreversible; `abort` — nothing changes, daemon stays halted, re-asked on the next run
AskUserQuestion: header "Cleanup mode", question "How should the uncommitted changes that `<triggered_by>` left in <repo-root> be cleaned up before the daemon resumes?", options with descriptions.
```

- **commit** — `git add -A && git commit -m <message>`. Captures every dirty path. You provide the message.
- **stash** — `git stash push -u`. Tucks dirt into a stash you can restore later by hand.
- **discard** — `git checkout -- . && git clean -fd`. Throws away every dirty change. Irreversible.
- **abort** — leave everything as-is and exit. Daemon stays halted.

If `commit`: ask one follow-up via `AskUserQuestion`. Context (print before asking) — Where: same step, target `<repo-root>`; Found: the dirty paths above; Why asking: the operator is the commit author; Answers: free-form message used by Step 3's commit, default `<triggered_by>: recover from halt`. Header "Commit message", question "Commit message for the recovery commit in <repo-root>? (default: `<triggered_by>: recover from halt`)".

Outcome: `commit`, `stash`, `discard`, or `aborted`.

### Reason ∈ {`git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`, `git_local_failed`, `suspected_loop`, `inbox_collision`, `routine_config_invalid`, `config_violation`, `rate_limit`} — manual-fix path

The daemon does NOT attempt to fix remote-sync halts itself — automatic resolution could silently drop the operator's commits. A rejected routine entry is likewise never auto-corrected: an unknown field may be a typo, a leftover of an older schema, or an intent the schema has not grown yet, and only the operator knows which. The same holds for the three reasons that name a producer rather than a file: a cycling bot, a contested inbox, and a settings invariant a plugin's CLI rejected all describe something outside this repository's tree that has to change before resuming means anything. Surface reason-specific guidance and ask the operator to repair the situation by hand, then confirm.

Print the matching guidance block first:

- `git_pull_diverged` — "Local branch and origin have diverged: each side has commits the other doesn't. Inspect with `git log --oneline HEAD origin/<branch>` and `git log --oneline origin/<branch> HEAD`, then either (a) `git reset --hard origin/<branch>` to drop local divergent commits, (b) rebase / merge by hand, or (c) push your local commits with `--force-with-lease` if you intend them to land."
- `git_push_failed` — "Push to origin retried 3 times and kept failing. Likely causes: auth (try `git push origin <branch>` by hand and read the error), force-protection or branch protection rule on the remote, an unusually persistent operator-side push race. Resolve before resuming, or `git reset --hard origin/<branch>` to drop your local commits if you'd rather start over."
- `git_remote_unavailable` — "Could not reach origin. Check network, VPN, and `git remote -v`. Run `git fetch origin <branch>` by hand to confirm the issue is gone before resuming."
- `git_local_failed` — "A pre- or post-tick git command failed and its stderr named no transport marker — a `.git/index.lock` still held past the retry backoff, a bad ref, a permission problem in the checkout, or a network failure whose stderr the transport classifier did not recognise. `triggered_by` names the sync step (`_git_pre` or `_git_post`); git's own stderr is in the halt detail, not the halt block — read it with `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" error-list --kind daemon_halt)` or from the newest `.logs/lazy-core/runtime/<date>.jsonl` record whose `name` is that step. Reproduce the same op by hand (`git status`, `git fetch origin <branch>`) and fix what the message names. If the detail reads as a transport failure after all, no repair is needed: with a sync step as `triggered_by`, the hourly doctor tick probes `git ls-remote` once the halt is an hour old and clears it on its own."
- `suspected_loop` — "The loop detector found one identical diff (`git patch-id --stable`) committed `daemon.loop_detect_threshold` times (default 5) by the same registered-bot author within the last `daemon.loop_detect_window` commits (default threshold × 4). The offending patch-id, the bot's email, and the repeated commit subjects are in the halt detail — `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" error-list --kind daemon_halt)`, or the newest `.logs/lazy-core/runtime/<date>.jsonl` record whose `name` is `_loop_detect`. Match that email against `experts.<name>.git_author.email` and `routines.<name>.git_author.email` in `.claude/lazy.settings.json` to name the producer, then read its recent commits (`git log --oneline --author=<email>`). What to do with it is your call and nobody else's: a diff that keeps re-landing unchanged is a bug in whatever produces it, and only you can say whether the fix is in that producer, in unregistering the routine (`/lazy-routine.unregister <name>`), or in accepting the pattern. **Resuming alone will not hold.** The detector re-tallies the same commit window at the end of the very next iteration, so unless the repeated commits have left the window — land other commits, drop or rewrite them, raise `daemon.loop_detect_threshold` above the recorded count, or narrow `daemon.loop_detect_window` — the daemon halts again with this reason within seconds."
- `inbox_collision` — "Another checkout on this host registers an inbox routine whose directory resolves to the same physical path as one of this repo's, so two daemons drain one inbox and every file is dispatched twice; the duplicated work does not undo itself. `triggered_by` is `run` — the daemon's startup path, not a routine — and the halt detail names both routines and both checkouts (`Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" error-list --kind daemon_halt)`). The repair is to stop the sharing: give one side an inbox of its own by editing that routine's `inbox_dir` in the other checkout's `.claude/lazy.settings.json`, resolve the symlink that made the two paths one, or retire that checkout's supervisor unit. Which side yields is yours to decide — both checkouts are equally halted, and the other one stays halted until someone clears it there too. **This reason alone is not re-detected on the next tick**: the collision check runs once, at daemon startup, so clearing the halt before the inboxes are separated puts a duplicating daemon back to work and it will not notice."
- `routine_config_invalid` — "The `routines.<triggered_by>` entry in `.claude/lazy.settings.json` (or its `.local.json` overlay) does not match its type's schema, so the daemon dropped it and stopped. Read the schema error in the routine's incident — `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" error-list)`, or the newest `.logs/lazy-core/runtime/<date>.jsonl` record whose `name` is `<triggered_by>` — then fix the entry by hand or re-register it via `/lazy-routine.register --force`. Per-type required and optional fields: `${CLAUDE_PLUGIN_ROOT}/references/lazy-core.routine-types-schema.md`."
- `config_violation` — "A routine tick exited with error text the daemon read as a settings-invariant violation — the output carried `config_violation` or `compute_inputs_failed`, typically raised by the plugin CLI that `routines.<triggered_by>.command` drives. It is escalated to a halt because config the CLI rejects once will be rejected identically on every future tick. The rejection text is in the routine's own `routine:<triggered_by>` incident and in the halt detail; `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" error-list)` shows both, and the newest `.logs/lazy-core/runtime/<date>.jsonl` record whose `name` is `<triggered_by>` carries the raw tick output. Fix what that text names — it comes from the plugin, so the setting at fault is in whatever section that plugin reads, not necessarily the routine entry (`/lazy-routine.register --force` helps only when the message points at the entry itself). Re-run the routine's `command` by hand for confirmation before resuming."
- `rate_limit` — "The subscription rate-limit window closed (`resets_at` in Step 1 says when it reopens, epoch seconds). Nothing is broken and no git repair is needed: the daemon lifts this halt itself once the window reopens. Resume early only if you want the queue moving again right away — the pump's pre-spawn flag check still refuses to spawn while the host-local flag at `${XDG_CACHE_HOME:-$HOME/.cache}/lazycortex/rate-limit/` holds a live record, so an early resume burns no tokens."

Then ask:

```
Context (print before asking):
- Where: /lazy-runtime.recover · Step 2 — Choose recovery mode; target <repo-root>/.runtime/state.json[daemon_halted]
- Found: `reason = <reason>`, triggered by `<triggered_by>`<; resets_at <epoch> when reason is rate_limit>; the guidance above names the repair
- Why asking: the skill runs no git or settings commands for this family — only the operator can say the external repair is done
- Answers: `resume` — halt block cleared atomically in Step 4; the daemon re-checks its own condition on the next tick and re-halts if the cause persists, EXCEPT `inbox_collision`, whose check runs only at daemon startup, so an unrepaired collision resumes silently; `abort` — halt stays, nothing written, re-run after repairing
AskUserQuestion: header "Resume daemon", question "Has the `<reason>` halt in <repo-root> been repaired externally — clear the halt block so the daemon resumes?", options with descriptions.
```

- **resume** — operator confirms repair done; halt block will be cleared. Working tree must be clean (the daemon re-verifies on next tick).
- **abort** — leave halt in place and exit.

Outcome: `manual-fix` or `aborted`.

## Step 3 — Apply cleanup

Skip if Step 2 outcome is `aborted` or `manual-fix` (mark this step `skipped-per-user-choice`).

Run `recover.cleanup(repo, mode, message=...)`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import sys
from pathlib import Path
import recover
mode = sys.argv[1]
message = sys.argv[2] if len(sys.argv) > 2 else None
recover.cleanup(Path('.'), mode, message=message)
print('cleaned')
" '<mode>' '<message-or-empty>')
```

Outcome: `cleaned`, `skipped-per-user-choice`, or `error`.

## Step 4 — Resume + report

Skip resume if Step 2 was `aborted`. Otherwise call `recover.resume(repo)`:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
import recover
try:
    recover.resume(Path('.'))
    print('resumed')
except recover.RecoverError as e:
    print(f'still-dirty: {e}')
" )
```

If output starts with `still-dirty`: print the message and tell the operator to inspect manually (`git status`) and re-run the skill. The halt block remains.

Otherwise print: "Daemon halt cleared. The runtime will resume scheduling on its next iteration."

Report block: one line per task in the canonical list, with its outcome word.

Outcome: `resumed`, `still-dirty`, or `aborted`.

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-runtime.recover)
```

Then `Write` to `.logs/claude/lazy-runtime.recover/<UTC-timestamp>.md`:

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "mode=<mode>"
---
```

`# lazy-runtime.recover`

`## Actions`
- Read halt context (`triggered_by=<...>`, `expert=<...>`, `job_id=<...>`)
- Chose cleanup mode (`<mode>`)
- Applied cleanup
- Resumed daemon

`## Result` `<resumed|still-dirty|aborted|not-halted>`

## Failure modes

- **"Daemon is not halted. Nothing to recover."** — the daemon was not in halt state when this skill ran → no action needed; verify with `cat .runtime/state.json`.
- **"working tree still dirty; refusing to resume"** — the cleanup did not produce a clean tree (e.g., submodules left dirt, or the operator chose `abort`) → run `git status` manually, resolve, and re-invoke `/lazy-runtime.recover`.
- **"commit mode requires a non-empty message"** — operator picked commit but provided no message → re-invoke and supply a message.
- **"`.runtime/state.json` unparseable"** — state file is corrupt → inspect manually; the daemon treats unparseable state as "not halted" and resumes on next iteration, but you may have lost `last_run` history.
- **Manual-fix path: halt re-fires immediately after resume** — the operator confirmed they fixed a `git_pull_diverged` / `git_push_failed` halt, but the underlying state was not actually resolved (branch still diverged, push still rejected). The next tick's `_git_pre` / `_git_post` re-detects the same condition and halts again with the same reason → reinspect with `git fetch origin <branch>; git log --oneline HEAD origin/<branch>` and address the actual cause before re-running `/lazy-runtime.recover`.
- **`suspected_loop` re-fires even though the cycling producer was fixed** — the detector reads a commit window, not a live process: the repeated commits are still inside `daemon.loop_detect_window` and re-trip the threshold on the next iteration → land other commits, drop or rewrite the offending ones, raise `daemon.loop_detect_threshold` above the recorded count, or narrow the window, then re-run `/lazy-runtime.recover`.
- **`inbox_collision` resumed and the daemon never re-halted, but files are still processed twice** — the collision check runs only at daemon startup, so a resume before the inboxes were separated is not re-checked → separate the two `inbox_dir` paths (or retire one supervisor unit) and restart the daemon so the check runs again.
