---
name: lazy-expert.dispatch-job
description: "Run when a task should be handed to a named expert to run in the background instead of blocking the session — long work the operator wants queued and picked up later. Returns a job_id in seconds; the runtime daemon executes the job and `/lazy-expert.collect-job` retrieves the output."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date -u *), Bash(test *), Write, AskUserQuestion, Agent
---
# Expert Dispatch Job

Submit a job to a named expert's queue. The skill validates the payload against the protocol contract, writes the job to `.experts/.jobs/<expert_name>/`, and returns `{job_id, queue_path}` to the caller.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Validate inputs`
   - `Step 2 — Verify experts directory`
   - `Step 3 — Dispatch job`
   - `Step 4 — Report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Validate inputs

Required inputs from the caller:
- `expert_name` (string) — the key in `lazy.settings.json[experts]`.
- `payload` (dict) — the request body.
- `protocols` (list of strings, optional, default `[]`) — protocol refs for this job. May be empty if the caller knows the expert ships without protocols.
- `source` / `context` (lists of strings, optional) — repo-relative **path manifests**, never file content. They are recorded into the job's `config.json`; nothing is copied at dispatch. The pump copies each entry into `<job_dir>/source/` or `<job_dir>/context/` when it claims the job — a directory under `<parent-directory-name>-<directory-name>`, a file under its basename — so the expert reads the tree as it stands at claim, not at dispatch. An entry that escapes the work tree, or that no longer exists at claim, fails the job with a `logical` error.
- `source_inline` / `context_inline` (dicts of filename → text, optional) — content that exists in no file, written into the same two buckets at dispatch time.
- `result` (list of strings, optional) — filenames created as empty placeholders under `<job_dir>/result/` for the expert to fill.

Pre-flight checks:
1. `expert_name` must be a non-empty string. If absent → abort: "`expert_name` is required."
2. `payload` must be a dict containing all three standard fields: `kind`, `role`, `request`. If any field is missing → abort with: "payload missing required field(s): <list>. See `claude/lazycortex-core/references/lazy-core.expert-protocols-contract.md` for the protocol contract."
3. Every entry of `source` / `context` must be a repo-relative path string. A caller holding text that no file carries passes it as `source_inline` / `context_inline` instead — those are written at dispatch, not copied at claim.

Optional payload fields: the `source` / `context` / `result` file-list arrays of `{path, description}` entries, which tell the expert what it will find under the job dir, plus protocol-specific extras. These are `request.json` prose — not the path manifests above.

Outcome: `validated` or `aborted`.

## Step 2 — Verify experts directory

Check that `.experts/` exists in the current repo:

```
Bash(test -d .experts && echo ok || echo missing)
```

If output is `missing` → abort: "`.experts/` not initialised — run `/lazy-core.install` first."

Outcome: `asserted` or `aborted`.

## Step 3 — Dispatch job

Shell out to `expert_runtime.dispatch_job` with the validated payload:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, sys
from pathlib import Path
from expert_runtime import dispatch_job
from lazy_settings import load_section
payload = json.loads(sys.argv[1])
expert = sys.argv[2]
# Pass '[]' for empty protocols; bare empty string raises JSONDecodeError.
protocols = json.loads(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else []
# Pass '{}' for a job with no work files; keys are source/context/result and the two _inline maps.
io = json.loads(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else {}
repo = Path('.')
experts = load_section(repo / '.claude/lazy.settings.json', 'experts')
if not experts.get(expert):
    print(json.dumps({
        'outcome': 'aborted-no-experts-entry',
        'message': f'{expert!r} is not registered in lazy.settings.json[experts]',
    }))
    sys.exit(0)
print(json.dumps(dispatch_job(repo, expert, payload, protocols = protocols, **io)))
" '<payload-json>' '<expert_name>' '<protocols-json>' '<io-json>')
```

Capture and parse the JSON output: `{job_id, queue_path}`.

`dispatch_job` writes `<jdir>/config.json` itself — agent ref, protocols, aspects, arguments, git_author, plus the `source_paths` / `context_paths` manifests the pump copies at claim — and touches `READY` last. Do not write that file a second time from here: a later write lands after the primitive's own and drops the manifests, leaving the pump with empty buckets. Aspects, arguments, and git_author are read from `lazy.settings.json[experts][<expert_name>]` by the primitive; the caller passes none of them. Protocols are the dispatching routine's own plus whatever the caller passed.

Outcome: `dispatched`, `aborted-no-experts-entry` (when the expert is not in `lazy.settings.json[experts]`), or `error`. Before dispatching, the skill must verify the expert entry exists; if `entry` is empty, abort with `aborted-no-experts-entry` and the message "`<expert_name>` is not registered in `lazy.settings.json[experts]`."

## Step 4 — Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

Print to the caller:

```
job_id:     <job_id>
queue_path: <queue_path>
```

## Step 5 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-expert.dispatch-job)
```

Then `Write` to `.logs/claude/lazy-expert.dispatch-job/<UTC-timestamp>.md`:

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "expert_name=<expert_name>"
---
```

`# lazy-expert.dispatch-job`

`## Actions`
- Validated payload fields
- Verified .experts/ directory
- Dispatched job to expert queue

`## Result` `<success|failure>` — job_id=`<job_id>`, queue_path=`<queue_path>`.

## Failure modes

- **"payload missing required field(s): kind"** (or `role`, `request`) — payload does not conform to the protocol contract → add the missing fields; see `claude/lazycortex-core/references/lazy-core.expert-protocols-contract.md`.
- **"`.experts/` not initialised"** — the experts directory has not been bootstrapped in this repo → run `/lazy-core.install` to create the required directory layout.
- **Python `FileNotFoundError` or `ModuleNotFoundError`** — `${CLAUDE_PLUGIN_ROOT}/bin` is not on the path or `expert_runtime.py` is absent → verify the plugin is installed (`/lazy-core.install`) and `${CLAUDE_PLUGIN_ROOT}` resolves correctly.
- **"`<expert_name>` is not registered in `lazy.settings.json[experts]`"** — the expert was never added or the name is a typo → register via `/lazy-core.install` expert wizard, or correct the name and re-run.
- **`JSONDecodeError` from `sys.argv[3]` or `sys.argv[4]`** — caller passed `<protocols-json>` as something other than a JSON array literal, or `<io-json>` as something other than a JSON object literal → pass `'[]'` / `'{}'` for the empty cases, or a JSON literal like `'["plug:proto"]'` / `'{"source": ["docs/spec.md"]}'`. The skill's argparse-style invocation expects a JSON-serializable string.
- **Job fails with `logical` — "declared path … does not exist at claim time"** — a `source` / `context` entry was deleted or renamed between dispatch and the pump's claim → re-dispatch with the path the file lives at now, or pass the content as `source_inline` / `context_inline` when no file holds it.
