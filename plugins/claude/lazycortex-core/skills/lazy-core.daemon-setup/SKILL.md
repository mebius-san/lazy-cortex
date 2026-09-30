---
name: lazy-core.daemon-setup
description: "Use when the operator wants a background daemon to drive this project, wants to move the daemon to another machine or checkout, or wants its Prometheus metrics endpoint — or when the daemon never starts because no supervisor unit was installed. Sets `daemon.enabled` and `daemon.run_here`, installs or removes the launchd / systemd unit, and provisions metrics. `/lazy-core.install` never touches the daemon; this skill is the one that does, and it is run rarely."
allowed-tools: Read, Write, AskUserQuestion, Bash(mkdir -p *), Bash(git rev-parse*), Bash(ls *), Bash(grep *), Bash(rm *), Bash(launchctl *), Bash(systemctl *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Agent
dirty-tree-waiver: "writes the daemon gates and metrics design into the tracked lazy.settings.json — the operator commits them, as with /lazy-core.install"
---
# Daemon setup

Decide whether a background daemon drives this project and from which checkout, then install or remove its supervisor unit and provision the metrics endpoint the daemon serves. Everything else the runtime needs — routines, `.experts/`, the expert registry, the spawn sandbox — is set up by `/lazy-core.install` and runs by hand through `/lazy-runtime.tick` without any of this. Run `/lazy-core.install` in the repo first.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve the repo`
   - `Step 2 — Daemon enabled gate`
   - `Step 3 — Run-here gate`
   - `Step 4 — Inbox ownership guard`
   - `Step 5 — Supervisor install or teardown`
   - `Step 6 — Provision metrics`
   - `Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Decisions are remembered, never re-asked

Every answer this skill collects lands in the tracked `<repo-root>/.claude/lazy.settings.json` and is read first on the next run; a question returns only while nothing is on record. The gates travel with the project to every clone:

- `daemon.enabled` — does a background daemon supervise this project at all. `/lazy-core.install` seeds it `false`; this skill is the one place that offers to flip it.
- `daemon.run_here` — which machine drives the project and from which checkout on it, as a hostname-to-path map (`{"nexus": "~/lazy-runtime/Money"}`). Never a boolean, never a bare host list: the hostname says which machine, the path says which of that machine's checkouts. A machine or checkout the map does not name gets no supervisor, and the daemon refuses to start there. `{}` names nothing at all.
- `daemon.metrics.enabled` — whether the daemon serves its `/metrics` endpoint.

Everything derivable is derived, not asked: supervisor kind (from platform), dev-mode (from whether this repo ships plugin sources), the per-checkout unit id, the interpreter the unit runs.

## Step 1 — Resolve the repo

`Bash(git rev-parse --show-toplevel)` in cwd. Failure → print `Not inside a git repository — run /lazy-core.install from inside the project first.`, state **not-in-git-repo**, mark Steps 2–6 `skipped-not-in-git-repo`, go to Report.

Hold the path as `<repo-root>`. Then confirm `/lazy-core.install` has run here:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get daemon --cwd <repo-root>)
```

Output `null` → the runtime layer was never installed; print `No daemon section in .claude/lazy.settings.json — run /lazy-core.install first.`, state **core-not-installed**, mark Steps 2–6 `skipped-core-not-installed`, go to Report. Otherwise state **resolved**.

## Step 2 — Daemon enabled gate

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get daemon --key enabled --cwd <repo-root>)
```

- Output `true` → state **enabled** and continue with Step 3. Do NOT ask.
- Output `false` → ask once:

```
Context (print before asking):
- Where: /lazy-core.daemon-setup · Step 2 — Daemon enabled gate; target <repo-root>/.claude/lazy.settings.json (`daemon.enabled`)
- Found: `daemon.enabled` is `false` — the project is ticked by hand through `/lazy-runtime.tick`, no supervisor runs it
- Why asking: whether a background daemon supervises this project is project policy nobody can derive
- Answers: `Yes — enable the daemon` — writes `daemon.enabled = true` into the tracked file now, the next steps pick the driving checkout and install the supervisor; `No — keep ticking by hand` — nothing written, the skill stops here; the flag is the record, so a later run asks again only while it stays `false`
AskUserQuestion:
  header: "Daemon"
  question: "Enable a background daemon for <repo-root>? (today its routines run only when ticked by hand)"
  options:
    - "Yes — enable the daemon" — "Writes `daemon.enabled = true`; continues to choose the driving checkout and install the supervisor."
    - "No — keep ticking by hand" — "Writes nothing; routines keep running through `/lazy-runtime.tick`."
```

  - `Yes` → `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set daemon --key enabled --value true --cwd <repo-root>)`; state **enabled-now** and continue with Step 3.
  - `No` → state **daemon-disabled**, mark Steps 3–6 `skipped-daemon-disabled`, go to Report.

## Step 3 — Run-here gate

Read the map first; ask only when nothing usable is on record.

**The checkout the map names must be a git-only clone outside Dropbox**, such as `~/lazy-runtime/<repo>`. Dropbox syncs bytes outside git and can bring CRLF files and half-written files from other machines, so the daemon refuses to start in any checkout whose resolved path has a component equal to `Dropbox`, starting with `Dropbox` (`Dropbox (Personal)`, `~/Library/CloudStorage/Dropbox…`), or ending in ` Dropbox` (`Auriglaci Dropbox`): it prints a one-line refusal, records a `daemon_error` incident with cause `dropbox_denied`, and exits non-zero — whatever `run_here` says.

The key is compared against `hostname -s` lowercased; the value against the checkout the process runs in, with `~` expanded and both sides resolved, so a symlinked path still matches.

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" daemon-run-here --cwd <repo-root> check)
```

- Output `run-here` → this machine and this checkout are the pair on record. State **run-here**. Do NOT ask.
- Output `not-this-host` → the map is on record and this machine is not in it. State **not-this-host**. Do NOT ask.
- Output `not-this-checkout` → this machine drives a different checkout of the project. State **not-this-checkout** and print the path the map names. Do NOT ask — re-pointing the map is a deliberate edit.
- Output `invalid-shape` → `run_here` is a boolean or a bare host list. Print the offending value and ask the question below — the answer replaces it; the daemon refuses to start until it is replaced.
- Output `unset` → ask once:

```
Context (print before asking):
- Where: /lazy-core.daemon-setup · Step 3 — Run-here gate; target <repo-root>/.claude/lazy.settings.json (`daemon.run_here`)
- Found: `daemon.enabled` is `true`; `daemon.run_here` is `unset` (or `invalid-shape` — offending value: <value>) — no hostname-to-checkout map names a driver
- Why asking: which machine and which checkout drive the daemon is known only to the operator; a wrong guess starts a second daemon on the same project
- Answers: `Yes — this checkout drives it` — maps <hostname> to <repo-root> in the tracked file now and installs a supervisor (launchd on macOS, systemd on Linux); `No — no checkout yet` — records an empty map, nothing starts the daemon until a checkout is named; persisted in the tracked file, never re-asked — change it by editing the map and re-running `/lazy-core.daemon-setup`
AskUserQuestion:
  header: "Run here?"
  question: "Drive the daemon for <repo-root> from THIS checkout on <hostname>? (this names the one checkout that drives it; the daemon refuses to start anywhere else, including a second checkout on this machine)"
  options:
    - "Yes — this checkout drives it" — "Maps this host to this checkout in the tracked `lazy.settings.json` and installs the supervisor."
    - "No — no checkout yet" — "Records an empty map; no supervisor starts anywhere until a checkout is named."
```

  Persist the answer, keeping entries for other machines untouched — `--on` for `Yes`, `--off` for `No` (drops this host from the map, which also replaces an `invalid-shape` value with a map):

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" daemon-run-here --cwd <repo-root> set --on)
```

  - `Yes` → state **run-here**.
  - `No` → state **run-here-declined**.

## Step 4 — Inbox ownership guard

Reached only on **run-here**; any other Step 3 outcome states **not-run-here** here. Two daemons over one physical inbox import every document twice, and the duplicate is not automatically reversible, so the guard runs before any supervisor exists:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" inbox-check --cwd <repo-root>)
```

The verb prints a JSON list of collisions (each with a `detail`) and exits 1 when it is non-empty.

- Empty list → state **inbox-ok**.
- Any row → a refusal, not a warning. State **inbox-conflict**, print each row's `detail` verbatim, and tell the operator that the two projects' `daemon.run_here` maps must not both name a checkout on this host (the other checkout is named in the finding). Mark Steps 5–6 `skipped-inbox-conflict` and go to Report. Which checkout drives a shared inbox is the operator's decision — never resolve it here.

## Step 5 — Supervisor install or teardown

Pick the branch from Step 3's outcome:

- **run-here** (and Step 4 **inbox-ok**) → 5a, then 5b on macOS or 5c on Linux.
- **not-this-host** / **not-this-checkout** → 5a for `<REPO_ID>` only, then 5d (teardown).
- **run-here-declined** → state **supervisor-skipped**.

### 5a. Derive supervisor kind, dev-mode, and the per-checkout unit id (no questions)

- **Supervisor kind** = the platform: macOS (`darwin`) → launchd (5b); Linux → systemd (5c). Any other platform → state **unsupported-platform** and skip to Step 6.
- **`<REPO_ID>`** = `<basename>-<hash>`, the first 8 hex of `sha256(<absolute-repo-root>)` after the basename — unique per checkout, stable across re-runs:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" install-phase --cwd <repo-root> repo-id)
```

  `<REPO_NAME>` (bare basename) is used only for the human-readable systemd `Description`.
- **dev-mode** = True when `Bash(ls <repo-root>/plugins/claude/*/.claude-plugin/plugin.json)` prints at least one path, else False. In dev-mode the shim prefers in-repo plugin sources over the cache. Persist it:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set daemon --key supervisor/dev_mode --value <true|false> --cwd <repo-root>)
```

- **python** = the absolute interpreter the unit hands to the shim: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" install-phase interpreter)`, held as `<PYTHON>`. launchd and systemd exec the shim with a minimal `PATH`, so the unit needs the absolute path. It is written into the unit file only — never into `lazy.settings.json` or `.claude/settings.local.json`.
- **login-shell / env-files** = operator-provided supervisor options, read verbatim from the `daemon.supervisor` block (a missing or `null` key is off / empty):

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get daemon --key supervisor --cwd <repo-root>)
```

  Hold `<login_shell>` (bool) and the ordered `<env_files>` list. Render each `env_files` entry verbatim — the shim expands a leading `~` itself. `login_shell` gives the daemon a login-equivalent environment (token and PATH) on a headless host; `env_files` sources just the named files. They may combine.

### 5b. macOS launchd

1. **Migrate a legacy basename-only unit.** If `~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist` exists and `Bash(grep -F "<repo-root>" ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist)` matches, it is this checkout's old-scheme unit → `Bash(launchctl unload ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist)` then `Bash(rm ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist)`. Absent, or pointing at a different checkout → leave it. State **legacy-unit-migrated** or **no-legacy-unit**.
2. Read `${CLAUDE_PLUGIN_ROOT}/templates/runtime/com.lazycortex.runtime.plist`.
3. Substitute `{REPO_ROOT}` → absolute `<repo-root>`, `{REPO_ID}` → `<REPO_ID>`, `{PYTHON}` → `<PYTHON>`.
4. **Inject the shim flags** into `ProgramArguments`, between the `lazy.runtime.sh` line and the `{REPO_ROOT}` line, each its own `<string>` element indented 8 spaces, in this order, omitting any whose source is unset: `--login-shell` when `<login_shell>` is True; for each `<env_files>` entry a `--env-file` element followed by the verbatim path element; `--dev-mode` when dev-mode is True.
5. `Bash(mkdir -p ~/Library/LaunchAgents/)`
6. Write the rendered plist to `~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_ID>.plist`.
7. `Bash(launchctl bootout gui/$UID/com.lazycortex.runtime.<REPO_ID>)` — a non-zero exit means the unit was not loaded, which is fine. `launchctl load` on a loaded label keeps the old plist in memory, so the unit is always booted out first.
8. `Bash(launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_ID>.plist)`
9. State **launchd-installed** (**launchd-installed-dev-mode** when dev-mode is True; append **-login-shell** / **-env-files** when those flags were injected).

### 5c. Linux systemd

1. **Migrate a legacy basename-only unit.** If `~/.config/systemd/user/lazy-core-runtime-<REPO_NAME>.service` exists and `Bash(grep -F "<repo-root>" ~/.config/systemd/user/lazy-core-runtime-<REPO_NAME>.service)` matches → `Bash(systemctl --user disable --now lazy-core-runtime-<REPO_NAME>.service)` then `Bash(rm ~/.config/systemd/user/lazy-core-runtime-<REPO_NAME>.service)`. Absent, or pointing at a different checkout → leave it. State **legacy-unit-migrated** or **no-legacy-unit**.
2. Read `${CLAUDE_PLUGIN_ROOT}/templates/runtime/lazy-core-runtime.service`.
3. Substitute `{REPO_ROOT}` → absolute `<repo-root>`, `{REPO_NAME}` → basename, `{PYTHON}` → `<PYTHON>`.
4. **Inject the shim flags** into the `ExecStart=` line, between `lazy.runtime.sh` and `{REPO_ROOT}`, in order: `--login-shell`, then `--env-file <path>` per `<env_files>` entry (quote a path containing spaces), then `--dev-mode`. With no flags the line is unchanged.
5. `Bash(mkdir -p ~/.config/systemd/user/)`
6. Write the rendered unit to `~/.config/systemd/user/lazy-core-runtime-<REPO_ID>.service`.
7. `Bash(systemctl --user enable --now lazy-core-runtime-<REPO_ID>.service)`
8. State **systemd-installed** (**systemd-installed-dev-mode** when dev-mode is True).

### 5d. Teardown when the map does not name this checkout

A unit for a checkout that must not run here is a leak or a stale install, and leaving it loaded keeps a duplicate daemon alive. Remove this checkout's unit on this host only.

macOS:
1. `~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_ID>.plist` absent → state **no-stray-unit** and stop.
2. `Bash(launchctl bootout gui/$UID/com.lazycortex.runtime.<REPO_ID>)` — a non-zero exit means it was not loaded.
3. `Bash(rm -f ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_ID>.plist)`
4. State **stray-unit-removed**.

Linux:
1. `~/.config/systemd/user/lazy-core-runtime-<REPO_ID>.service` absent → state **no-stray-unit** and stop.
2. `Bash(systemctl --user disable --now lazy-core-runtime-<REPO_ID>.service)` — a non-zero exit means it was not enabled.
3. `Bash(rm -f ~/.config/systemd/user/lazy-core-runtime-<REPO_ID>.service)`
4. State **stray-unit-removed**.

Never touch a unit whose `<REPO_ID>` differs — it belongs to another checkout.

## Step 6 — Provision metrics

Reached only when Step 5 installed a supervisor; otherwise state **skipped-not-run-here**. The endpoint is an HTTP server the daemon serves in-process, so a checkout with no daemon running here has nothing to scrape.

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get daemon --key metrics/enabled --cwd <repo-root>)
```

- Output `true` → on record; do NOT ask, run the three sub-steps below (idempotent: a recorded port is reused, the scrape file is regenerated).
- Output `false` → on record; state **metrics-declined**.
- Output `null` → ask once:

```
Context (print before asking):
- Where: /lazy-core.daemon-setup · Step 6 — Provision metrics; target <repo-root>/.claude/lazy.settings.json (`daemon.metrics`)
- Found: Step 5 installed the supervisor for this checkout; `daemon.metrics.enabled` is `unset` in the tracked file
- Why asking: whether this checkout's daemon is scraped is project policy — nothing on disk says a Prometheus-compatible scraper exists
- Answers: `Yes — enable metrics` — persists `metrics.enabled = true`, `repo_label` (default: folder basename) and `bind` in the tracked file, allocates a free loopback port into the gitignored local overlay, regenerates the host scrape-targets file, all now; `No — this checkout stays unscraped` — persists `metrics.enabled = false` in the tracked file; either answer is on record and never re-asked (edit the key to change it)
AskUserQuestion:
  header: "Metrics?"
  question: "Enable the Prometheus /metrics endpoint for the daemon of <repo-root> on <hostname>?"
  options:
    - "Yes — enable metrics" — "Exposes routine ticks, errors, tokens, queue depth on a loopback HTTP port; the port is picked automatically and recorded per-machine."
    - "No — this checkout stays unscraped" — "Recorded as `metrics.enabled = false`; never re-asked."
```

  - `No` → `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set daemon --key metrics/enabled --value false --cwd <repo-root>)`; state **metrics-declined**.
  - `Yes` → run the three sub-steps:

1. **Allocate the port** (sequential from 9464; the repo's recorded port is reused unless a second registered daemon records the same one):

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" metrics-alloc-port --repo-root <repo-root>)
```

2. **Persist the split** — design intent into the tracked file, the per-host port into the gitignored overlay, since a port free on one machine may be taken on another. One key per call; a key that keeps an existing value is read first and written only when the read prints `null`:

   - `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get daemon --key metrics/port --cwd <repo-root>)` — must print `null`; anything else is a tracked port leaked from an older install, carried into the outcome as `tracked-port-leaked=<port>` for the operator to remove from the tracked file in that repo's own commit.
   - `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set daemon --key metrics/enabled --value true --cwd <repo-root>)`
   - `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get daemon --key metrics/repo_label --cwd <repo-root>)`, and only when it prints `null`: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set daemon --key metrics/repo_label --value '"<repo_label>"' --cwd <repo-root>)` — default: the folder basename verbatim.
   - `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get daemon --key metrics/bind --cwd <repo-root>)`, and only when it prints `null`: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set daemon --key metrics/bind --value '"127.0.0.1"' --cwd <repo-root>)`
   - `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set daemon --key metrics/port --value <allocated port> --scope local --cwd <repo-root>)`

3. **Regenerate the host scrape-targets file**, so an external Prometheus with a `file_sd_configs` pointer picks the daemon up:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" metrics-scrape-file)
```

State `metrics-enabled port=<port> label=<label> scrape-targets=<count>`, with ` tracked-port-leaked=<port>` appended when sub-step 2 found one.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug. When any step wrote the tracked `<repo-root>/.claude/lazy.settings.json`, end with one line telling the operator to commit it — it carries the gates to every clone.

## Failure modes

- **`/lazy-core.daemon-setup` stops with "run /lazy-core.install first"** — the repo has no `daemon` section in `.claude/lazy.settings.json` → run `/lazy-core.install`, then re-run.
- **Step 5 fails: supervisor template not found** — `templates/runtime/com.lazycortex.runtime.plist` or `lazy-core-runtime.service` is missing from the plugin cache → run `/plugin update lazycortex-core@lazycortex`, then re-run.
- **Step 5 fails: `launchctl bootstrap` error** — the plist was written but `launchctl bootstrap` exited non-zero → inspect the plist in `~/Library/LaunchAgents/` for substitution errors, then re-run.
- **Step 5 fails: `systemctl --user enable --now` error** — the unit was written but `systemctl` exited non-zero → `systemctl --user status lazy-core-runtime-<REPO_ID>.service` names the error; correct it and re-run.
- **Daemon never starts for this checkout** — `daemon.run_here` names a different machine or checkout → point this host's entry at this checkout (`{"<this host>": "<this path>"}`) in the tracked `lazy.settings.json` and re-run.
- **The daemon exits at once with `refuses to start: … inside a Dropbox folder`** — the checkout `run_here` names sits under a Dropbox folder → clone the project with git outside Dropbox (for example `~/lazy-runtime/<repo>`), point this host's entry at the clone, and re-run from the clone.
- **A second machine or checkout started its own daemon for the same project** — the map is a boolean or a bare host list left by an older install → replace it with a hostname-to-path map naming the one driving checkout, and re-run on the others; each removes its stray unit.
- **Step 4 reports `inbox-conflict` and no supervisor is installed** — another checkout on this host drives an inbox that resolves to the same physical directory → point that project's `daemon.run_here` at a checkout on another machine, or empty it to `{}`, then re-run.
- **Both checkouts' daemons are halted with `inbox_collision`** — the halt is symmetric and permanent by design and only a dirty-tree halt auto-clears → take one checkout out of its project's `daemon.run_here`, then run `/lazy-runtime.recover` in the survivor.
