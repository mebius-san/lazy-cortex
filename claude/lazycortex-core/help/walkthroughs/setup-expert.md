---
chapter_type: walkthrough
summary: Add a named expert role and dispatch your first async job — keep working while the daemon runs it, then collect the result.
last_regen: 2026-08-05
diagram_spec:
  anchor: "How the pieces fit"
  request: "Sequence diagram showing a user dispatching a job via /lazy-expert.dispatch-job, the daemon picking it up from the .experts/.jobs/ queue, the expert agent writing response.json + DONE marker, and the user collecting the result via /lazy-expert.collect-job. Nodes: User, Claude session, .experts/.jobs/ queue, daemon (runner), expert agent."
  kind_hint: sequence
source_skills:
  - lazy-core.install
  - lazy-expert.dispatch-job
  - lazy-expert.list-jobs
  - lazy-expert.collect-job
---
# Add a named expert and dispatch your first async job

Think of experts as named coworkers on your async team. You hand one a task, it works in the background, and you carry on with something else. When the daemon finishes the job you pick up the result. This walkthrough takes you through the full loop — bootstrap the expert registration via `/lazy-core.install`, dispatch a first job to a named expert role, watch its status while it runs, and collect the finished result.

## Outcome

After this walkthrough you have:

- At least one dispatched job with a collected result you can read.
- A working mental model of the queue's status values, so you know when to check back — including the difference between a job that failed and one the expert deliberately postponed.

## What you need

- `lazycortex-core` installed and restarted in Claude Code.
- A git repo to run async jobs in (the runtime is always per-repo).
- The daemon running (a supervisor unit, or the `.claude/bin/lazy.runtime.sh` shim started manually) — see Step 1 below if you're not sure.

## The journey

### Step 1 — Bootstrap the expert runtime

Run `/lazy-core.install` in the repo you want the async team to work in. Alongside the rest of its bootstrap, the install skill:

- Creates `.experts/` and registers every expert candidate it finds — any installed plugin's agent carrying `expert_protocol:` frontmatter is registered automatically in `lazy.settings.json[experts]`, no per-candidate prompt.
- Walks you through the daemon gates (project-wide "does this project use the daemon at all", then per-checkout "start it here") and installs the supervisor (launchd on macOS, systemd on Linux) when you say yes to both.
- Seeds the `git` section of the project's `lazy.settings.json` with the git-guard's `enabled`, `pathspec_enabled`, and `mutex_enabled` flags — defaults that match the guard's current behavior, written down so you (or the expert's dispatched work) can tune them later without reading the hook source.

Confirm two things are in place before dispatching:

- **At least one expert is registered.** Check `lazy.settings.json[experts]` for a key besides `_version`. If it's empty, no plugin you have installed ships an expert candidate yet — install one, or re-run `/lazy-core.install` after adding your own agent with `expert_protocol:` frontmatter.
- **The daemon is running.** If you said yes to both gates during install, it's already running — skip to Step 2. Otherwise, in a terminal outside Claude Code run the shim:

```
.claude/bin/lazy.runtime.sh
```

The shim resolves the runner from the plugin cache and starts it. The daemon logs to stdout; it wakes on each polling cycle, drains any queued jobs, and runs registered routines. Leave it running in a `tmux` or `screen` pane — you do not need to restart it for each job.

**Verification gate**: `lazy.settings.json[experts]` contains at least one expert key besides `_version`, and the daemon prints its startup message and enters its polling loop without errors.

### (Optional) Aspects and arguments

Two additional fields can be set on a registered expert in `lazy.settings.json[experts][<expert>]`, and both flow through to every dispatched job's `config.json`:

- `aspects[]` — adds behavior layers. The most commonly used aspect is `lazycortex-core:lazy-memory.persona-aspect` (long-term memory). Run `/lazy-memory.mark-persona <expert>` to opt in; the skill writes the aspects array for you — do not edit it by hand.
- `arguments{}` — pinned named values rendered into every job's prompt for this expert. These are static values that should follow the expert across all dispatches (e.g. a preferred code style, a target language, a review rubric). For one-off overrides, pass extra fields in the job `payload` instead.

### Step 2 — Dispatch a job

Run `/lazy-expert.dispatch-job` and supply the required inputs:

- `expert_name` — the local key you defined in `lazy.settings.json[experts]` (e.g. `designer`).
- `payload` — a dict with three required fields:
  - `kind` — the protocol kind string defined by the expert's contract (e.g. `doc-review`).
  - `role` — a role label for this job (often matches the expert name or describes the task type).
  - `request` — the human-readable task description (e.g. `Review docs/api.md for clarity and completeness`).

One optional input:

- `protocols` — a JSON array of protocol reference strings (e.g. `["lazycortex-core:lazy-core.expert-protocols-contract"]`). Defaults to `[]` when omitted. Pass this when the expert's agent requires an explicit protocol reference written into `config.json` alongside the request.

Example:

```
/lazy-expert.dispatch-job expert_name=designer payload={"kind":"doc-review","role":"designer","request":"Review docs/api.md for clarity and completeness"}
```

The skill validates the payload against the protocol contract, writes the job directory under `.experts/.jobs/<expert_name>/<job_id>/` with a `request.json`, a `READY` marker, and a `config.json` capturing the expert's full configuration (agent ref, protocols, aspects, arguments, git author). It then prints:

```
job_id:     <job_id>
queue_path: .experts/.jobs/designer/<job_id>
```

Note the `job_id` — you need it to collect the result.

**Verification gate**: the `queue_path` directory exists and contains `request.json`, `config.json`, and a `READY` marker.

### Step 3 — Check the queue while you wait

The daemon picks up queued jobs on its next polling cycle. While it runs you can check progress at any time with `/lazy-expert.list-jobs`:

```
/lazy-expert.list-jobs
```

To narrow to a specific expert or status:

```
/lazy-expert.list-jobs expert=designer
/lazy-expert.list-jobs status=queued
/lazy-expert.list-jobs status=active
/lazy-expert.list-jobs status=done
/lazy-expert.list-jobs status=failed
/lazy-expert.list-jobs status=cancelled
```

The output is a table with `expert`, `job_id`, `status`, and `age_sec` columns. Status values:

| Status | Meaning |
|--------|---------|
| `queued` | `READY` marker written; daemon has not yet picked this job up |
| `active` | Daemon is running the expert agent for this job right now |
| `cancelled` | Job was cancelled via `/lazy-expert.cancel-job` — its bundle stays on disk for forensics |
| `dead` | Daemon wrote a `DEAD` marker — job stalled or was interrupted |
| `done` | Expert finished and its response reports an explicit, non-error, non-deferred outcome |
| `deferred` | Expert finished but reported the reserved `deferred` outcome — it deliberately postponed the work and left its inputs untouched. Appears in an unfiltered listing; it is neither `done` nor `failed`. |
| `failed` | Expert finished but its response reports an error outcome — or omits an outcome entirely, is empty, or fails to parse. A finished job is only `done` when it explicitly says so; anything else counts as `failed` |

The `age_sec` column counts seconds since the relevant marker's modification time — useful for spotting jobs that have been sitting a long time.

You can dispatch additional jobs, continue working on the codebase, or run other skills — the daemon drains the queue in the background regardless.

### Step 4 — Collect the result

Once `/lazy-expert.list-jobs` shows `status=done` for your job, run:

```
/lazy-expert.collect-job expert_name=designer job_id=<job_id>
```

The skill prints:

```
status: done
result files (Read these to retrieve output):
  - .experts/.jobs/designer/<job_id>/result/<file>
```

Open the listed result files to read the expert's output. If status comes back as `pending`, the daemon has not finished yet — wait a polling cycle and re-run `/lazy-expert.collect-job`.

If status comes back as `failed`, the skill prints the error message from `response.json` when the expert set one. A response that never explicitly reported a finished outcome — missing, empty, or unreadable — has no error field to show; inspect `.experts/.jobs/designer/<job_id>/response.json` directly to see what the expert actually wrote.

If status comes back as `deferred`, the expert deliberately postponed the work rather than finishing or failing it, and left every input untouched — this is not a failure, and there is no result file to read. Check `response.json` for the reason, then re-dispatch a fresh `/lazy-expert.dispatch-job` for the same task when you're ready to retry; a job you dispatched directly has no automatic retry.

If status is `missing`, the `job_id` or `expert_name` is wrong — verify against the output from Step 2.

If `/lazy-expert.list-jobs` shows the job as `dead` but `/lazy-expert.collect-job` returns `pending`, the daemon stalled before writing the DONE marker — the job needs to be re-dispatched or recovered. Run `/lazy-runtime.recover` to clear any daemon halt, then re-dispatch the job.

## After you're done

- **Dispatch more jobs any time** — the daemon keeps running. Any job you send with `/lazy-expert.dispatch-job` goes into the queue and is picked up on the next polling cycle.
- **Check the full queue** — `/lazy-expert.list-jobs` shows all jobs across all experts. Pass `status=done` to review completed work, `status=failed` to find errors, or `status=cancelled` to review jobs you stopped.
- **Register more experts** — install a plugin that ships an `expert_protocol:`-tagged agent, then re-run `/lazy-core.install`; the new candidate registers automatically.
- **Cancel a job you no longer need** — run `/lazy-expert.cancel-job expert_name=designer job_id=<job_id>` for any job that is still queued or in progress. Cancellation stops the running executor immediately and marks the bundle `CANCELLED`; nothing is deleted, so the job stays visible in `/lazy-expert.list-jobs` for forensics.
- **Add memory to an expert** — run `/lazy-memory.mark-persona <expert>` to opt an expert into the long-term memory subsystem. After a few dispatches accumulate run logs, run `/lazy-memory.reflect <expert>` to have the expert write its first memory notes under `.memory/<expert>/`. See the *add-memory-to-expert* walkthrough for the full flow.
- **Register plugin routines** — if a plugin also needs periodic background work, run `/lazy-routine.register` to add it to the daemon's rotation alongside `lazy-expert.pump`.
- **Daemon stopped?** — if you did not install a supervisor, re-run `.claude/bin/lazy.runtime.sh`. The daemon is stateless between restarts; jobs that were queued when it stopped will be picked up on the next cycle. If the daemon halted on a dirty working tree, run `/lazy-runtime.recover` first.

## How the pieces fit

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant user as User
  participant claudeSession as Claude session
  participant jobsQueue as .experts/.jobs/ queue
  participant daemon as Daemon runner
  participant expertAgent as Expert agent

  user->>claudeSession: /lazy-expert.dispatch-job
  claudeSession->>jobsQueue: write job payload
  loop poll for new jobs
    daemon->>jobsQueue: check queue
  end
  jobsQueue-->>daemon: job found
  daemon->>expertAgent: spawn expert agent
  expertAgent->>jobsQueue: write response.json
  expertAgent->>jobsQueue: touch DONE marker
  Note over jobsQueue,expertAgent: job complete
  user->>claudeSession: /lazy-expert.collect-job
  claudeSession->>jobsQueue: check DONE marker
  jobsQueue-->>claudeSession: response.json
  claudeSession-->>user: return result
```
