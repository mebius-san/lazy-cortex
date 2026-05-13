---
chapter_type: block
summary: Inspect and manually break the per-repo staging lock that prevents hooks and skills from stomping each other's git index changes.
last_regen: 2026-05-13
diagram_spec:
  anchor: "Lock lifecycle"
  request: "State diagram of the lazy-core.git staging lock lifecycle: NO_LOCK → HELD (a hook or skill acquires the lock before touching the git index) → auto-released when the staging window closes OR auto-broken by heuristics (dead PID / stale-and-idle / different host) → NO_LOCK. Show the manual break path via /lazy-core.git-unlock as an alternative exit from HELD, guarded by /lazy-core.git-status inspection first."
  kind_hint: state
source_skills:
  - lazy-core.git-status
  - lazy-core.git-unlock
---
# git staging coordination

When multiple lazycortex hooks and skills are active in the same repo they can all try to touch the git index at the same moment — a `lazy-guard.check-public` pre-commit scan, a model-router dispatch, a pre-commit pipeline step. Without coordination those concurrent writes corrupt the index or cause one operation to silently overwrite another's staged changes.

The staging lock prevents that. Before any hook or skill modifies the index it acquires `.git/lazy-git.lock`, does its work, then releases it. Anything else that finds the lock held waits or yields rather than ploughing ahead. On a healthy day this is invisible — the lock appears for a fraction of a second and disappears. This block covers the two moments when you need to interact with it: reading the current lock state, and breaking a stuck lock by hand when the automatic heuristics don't apply.

## When you'd use this

- A commit or hook appears to hang and you want to know whether the staging lock is the cause before reaching for a heavier tool.
- `/lazy-core.doctor` surfaces a stale-lock warning and you want to inspect the holder before deciding whether to act.
- A session was interrupted mid-staging-window (crash, forced kill, IDE restart) and you want to confirm the PID is dead before breaking the lock.
- You want to verify the lock has already cleared before re-triggering a blocked operation.

## What's in this block

**`/lazy-core.git-status`** is the read-only inspector. It reads `.git/lazy-git.lock` and prints everything relevant about the current holder: session ID and PID, how long the lock has been held, when the index was last touched, whether the holder process is still alive on the same host, and whether the automatic break-the-lock heuristics would fire if another operation arrived right now. It never writes, never deletes, and never modifies anything. Running it is always safe and leaves no trace.

**`/lazy-core.git-unlock`** is the manual break. It runs the same inspection internally, presents the holder details in a confirmation prompt, waits for you to confirm, then force-deletes the lock file. If you cancel, nothing changes. If you confirm, the lock is gone and any queued operation resumes on its next attempt.

## How they work together

Start with `/lazy-core.git-status`. Three outcomes are possible:

- **"Lock: NONE"** — nothing is held. Whatever stall you were seeing has already resolved; no action needed.
- **"Breakable: YES"** — the heuristics already qualify this lock for removal (dead PID, stale-and-idle, or different host). The next hook invocation will auto-break it; you don't need to act, but you can run `/lazy-core.git-unlock` immediately if you'd rather not wait.
- **"Breakable: NO (within thresholds)"** — the holder process appears alive and the lock is not yet stale. If you have independent knowledge that the holder has genuinely abandoned the staging window — the session was interrupted, the Claude Code instance that held it is no longer running — reach for `/lazy-core.git-unlock`.

When you do run `/lazy-core.git-unlock`, you see the session ID, PID, age, host, branch, and liveness status in the confirmation prompt. The skill captures the same snapshot internally before asking, so you don't need to cross-reference the status output separately. Confirm, and the lock is gone. Cancel, and nothing changes.

If you are uncertain whether the holder is truly stuck, run `/lazy-core.git-status` again after a few seconds. The "Held for" counter will increment; if the index-touch timestamp is also advancing, the holder is still active and you should not interrupt it.

## Common adjustments

The lock's automatic break-the-lock thresholds — how long before "stale-and-idle" fires and the idle-index grace period — are configurable in `lazy.settings.json`. If you find the defaults too aggressive or too conservative for your workflow, run `/lazy-core.install` and navigate to the git-guard configuration section. The skill writes the threshold fields; do not edit `lazy.settings.json` directly for this.

## Where this fits

The staging lock is an infrastructure layer that the rest of the lazycortex-core block set depends on silently — the pre-commit pipeline, the install-and-audit lifecycle, and the expert runtime daemon all pass through it. You will not interact with this block on a healthy day. It becomes relevant when a commit or hook appears to hang, when `/lazy-core.doctor` surfaces a stale-lock warning, or when `/lazy-runtime.recover` notes a staging-lock conflict as part of a daemon halt.

## See also

- [troubleshooting](troubleshooting.md) — failure modes for stuck or missing locks, including symptoms that look like hangs but trace to other causes.
- [install-and-audit](install-and-audit.md) — the install wizard that sets lock thresholds via `/lazy-core.install`.

## Lock lifecycle

```mermaid
%%{init: {'themeVariables':{'background':'transparent','transitionColor':'#000','transitionLabelColor':'#000','labelBackgroundColor':'#fff','edgeLabelBackground':'#fff','stateLabelColor':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','state':{'diagramPadding':5,'useMaxWidth':true}}}%%
stateDiagram-v2
  [*] --> noLock

  noLock --> held : acquire (hook or skill locks index)

  held --> noLock : staging window closes (auto-release)
  held --> noLock : dead PID detected (auto-break)
  held --> noLock : stale-and-idle timeout (auto-break)
  held --> noLock : different host detected (auto-break)

  held --> inspecting : /lazy-core.git-status invoked

  inspecting --> held : status only - no action taken
  inspecting --> noLock : /lazy-core.git-unlock confirmed

  style noLock fill:#1e3a5f,stroke:#4a90e2,color:#fff
  style held fill:#1e5f3a,stroke:#4ae290,color:#fff
  style inspecting fill:#5f4a1e,stroke:#e2a14a,color:#fff
```
