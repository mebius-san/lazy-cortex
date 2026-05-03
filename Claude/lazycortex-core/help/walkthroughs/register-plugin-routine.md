---
chapter_type: walkthrough
summary: Register a dot-namespaced routine with the runtime daemon so your plugin runs a periodic check automatically — and remove it cleanly when you no longer need it.
last_regen: 2026-05-03
diagram_spec:
  anchor: "How the daemon picks up the routine"
  request: "Sequence diagram showing: user invokes /lazy-routine.register → skill writes routine entry to lazy.settings.json → daemon's next cycle reads lazy-core.runtime.routines → daemon executes the command at interval_sec cadence → user invokes /lazy-routine.unregister → skill removes entry from lazy.settings.json → daemon's next cycle skips the removed routine"
source_skills:
  - lazy-routine.register
  - lazy-routine.unregister
---
# How do I make my plugin run a periodic check via the runtime daemon?

This walkthrough is for plugin authors who want a named routine — such as a lint tick, a sync check, or any scheduled command — to run on a fixed cadence inside the runtime daemon. `/lazy-routine.register` writes the routine into `lazy-core.runtime` in `lazy.settings.json`; the daemon picks it up on its next cycle without a restart. When the routine is no longer needed, `/lazy-routine.unregister` removes it cleanly.

## What you need

- The `lazycortex-core` plugin installed and the runtime daemon enabled for the repo (run `/lazy-core.install` and answer yes to the expert runtime wizard if you have not done this yet).
- The daemon running (`./run.sh` from the repo root, or the launchd/systemd service if you set that up).
- A dot-namespaced routine name following `<plugin>.<verb>` format, for example `acme-lint.tick`.
- The command you want the daemon to invoke, expressed as a list of strings (e.g. `["python3", "bin/lint_tick.py"]`).
- The polling interval in seconds (e.g. `300` for every five minutes).

## The flow

### Step 1 — Choose a name

Pick a routine name in `<plugin>.<verb>` format. Both the plugin segment and the verb segment must be non-empty, and the name must contain exactly one dot. Examples: `acme-lint.tick`, `lazy-review.tick`, `my-plugin.sync`.

If you pass a name that does not match this pattern, the skill aborts immediately with a message explaining the format. Rename and retry.

### Step 2 — Register the routine

Run:

```
/lazy-routine.register
```

When prompted, provide:

- `name` — the dot-namespaced name from Step 1 (e.g. `acme-lint.tick`).
- `command` — the command the daemon should run, as a list of strings (e.g. `["python3", "bin/lint_tick.py"]`).
- `interval_sec` — how often the daemon should run it, in seconds (e.g. `300`).
- `timeout_sec` — optional per-run timeout; omit to use the daemon default.

The skill writes the routine entry into the `lazy-core.runtime.routines` map in `.claude/lazy.settings.json`. It refuses to overwrite an existing registration unless you pass `--force`. If you need to update an already-registered routine, run `/lazy-routine.unregister acme-lint.tick` first, then re-register.

### Step 3 — Verify the registration

After the skill reports "registered routine `<name>`", you can confirm by checking that the entry appears in `lazy.settings.json` under `lazy-core.runtime.routines`. The daemon does not need to be restarted — it reads settings on every cycle.

### Step 4 — Unregister when done

To remove the routine:

```
/lazy-routine.unregister acme-lint.tick
```

The skill removes the entry from `lazy-core.runtime.routines`. If the name is not present, the skill treats that as a no-op (INFO, not an error). The daemon's next cycle will skip the removed routine.

Note: the built-in `lazy-expert.pump` routine is protected. Attempting to unregister it without `--force` aborts with a warning. Only pass `--force` if you intend to stop expert job processing — expert jobs will not be processed until `lazy-expert.pump` is re-registered or you re-run `/lazy-core.install`.

## After you're done

Your routine is running. The daemon logs each cycle, so you can inspect `.logs/` for execution records. If you want to adjust `interval_sec` or the `command`, unregister the old entry with `/lazy-routine.unregister` and re-register with the new values. Plugin install skills (e.g. in your own plugin's `<plugin>.install` skill) can call `/lazy-routine.register` programmatically so the routine is set up automatically whenever someone installs your plugin.

## How the daemon picks up the routine

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant user as User
  participant registerSkill as /lazy-routine.register
  participant settings as lazy.settings.json
  participant daemon as lazy-core.runtime daemon
  participant unregisterSkill as /lazy-routine.unregister

  user->>registerSkill: invoke /lazy-routine.register
  registerSkill->>settings: write routine entry (command + interval_sec)
  settings-->>registerSkill: entry persisted
  registerSkill-->>user: routine registered

  loop every interval_sec
    daemon->>settings: read lazy-core.runtime.routines
    settings-->>daemon: routine list with interval_sec
    daemon->>daemon: execute registered command
    Note over daemon: command runs at interval_sec cadence
  end

  user->>unregisterSkill: invoke /lazy-routine.unregister
  unregisterSkill->>settings: remove routine entry
  settings-->>unregisterSkill: entry removed
  unregisterSkill-->>user: routine unregistered

  daemon->>settings: read lazy-core.runtime.routines on next cycle
  settings-->>daemon: routine absent from list
  Note over daemon: removed routine skipped - no execution
```
