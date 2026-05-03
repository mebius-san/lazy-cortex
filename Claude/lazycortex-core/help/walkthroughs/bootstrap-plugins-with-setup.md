---
chapter_type: walkthrough
summary: Run /lazy-core.setup to install every enabled lazycortex plugin in one command — auto-discovered, dependency-ordered, idempotent.
last_regen: 2026-05-03
diagram_spec:
  anchor: "How the run unfolds"
  request: "Sequence diagram showing the lazy-core.setup flow: user invokes /lazy-core.setup, skill discovers install skills from installed_plugins.json, builds an ordered plan (pre-install → per-plugin → post-install), shows a preview, asks one confirmation question, then runs each child skill in order and prints a final report."
  kind_hint: sequence
source_skills:
  - lazy-core.setup
---
# I just enabled several lazycortex plugins — how do I install them all at once?

When you enable multiple lazycortex plugins and restart Claude Code, none of their project-level artifacts (rule templates, settings scaffolds, configurators) are wired into your project yet. `/lazy-core.setup` is the single command that closes that gap: it reads which plugins are enabled, locates each plugin's install skill, sorts them into the right execution order, shows you the plan, asks once for confirmation, and runs each installer in sequence. You end up with every plugin fully bootstrapped in one go.

## What you need

- At least one lazycortex plugin enabled in `~/.claude/settings.json` and installed via `/plugin update` (so its cache is present and listed in `~/.claude/plugins/installed_plugins.json`).
- Claude Code restarted after enabling the plugin(s) so the skills are available.
- A git-tracked project directory as your working directory (the installers write files relative to it).

## The flow

### Step 1 — Run the command

Type `/lazy-core.setup` in the Claude Code prompt. The skill immediately creates a task checklist so no step can be silently skipped, then moves to discovery.

If you want to see what would run without committing to it, pass the flag: `/lazy-core.setup --dry-run`. The plan renders and the skill stops before asking for confirmation.

### Step 2 — Review the discovery report

The skill reads `~/.claude/plugins/installed_plugins.json` to identify your enabled plugins, then follows each entry's `installPath` to locate skills whose directory name ends in `.install`. It also scans for any skill whose frontmatter declares `lazy_setup_phase:` — these are cross-cutting configurators that opt in without an edit to the core skill. You'll see a one-line summary:

```
discovered: N skills (M install + K configurator)
```

If the count is zero (no enabled plugin ships an install skill), the skill reports `nothing-to-do` and exits without prompting.

### Step 3 — Read the preview

Before asking for confirmation, the skill prints the full ordered plan grouped by phase:

```
pre-install:
  (none)
per-plugin:
  • lazycortex-core:lazy-core.install
  • lazycortex-log:lazy-log.install
  • lazycortex-obsidian:lazy-obsidian.install
post-install:
  • lazycortex-core:lazy-guard.allow-mcp
  • lazycortex-core:lazy-core.agent-models
```

`lazy-core.install` always runs first among the per-plugin installers because it seeds `lazy.settings.json`, which later installers read. Everything else runs alphabetically within its phase.

### Step 4 — Confirm once

A single question appears: "Run the planned setup chain (N skills across pre-install / per-plugin / post-install)?" Answer `run` to proceed or `abort` to stop. If you abort, nothing has been written — re-run whenever you're ready.

### Step 5 — Watch each child run

Each installer runs in sequence. Child skills own their own interactivity: if an installer has its own confirmation prompts or sub-questions, those appear inline. If one child fails, the skill logs the failure and continues with the rest rather than stopping — so you get a complete result even when one installer hits a problem.

### Step 6 — Read the final report

After all children finish, the report lists every child under one of three headings: ran successfully, failed, or skipped. A failed child shows the reason verbatim. If anything failed, the report ends with:

```
Re-run /lazy-core.setup after fixing — idempotent.
```

Fix the reported issue and re-run. Children that already succeeded the first time will complete quickly (they are individually idempotent) and the failed one gets another chance.

## After you're done

Every enabled plugin is now bootstrapped for the current project. You can verify the result by running `/lazy-core.doctor`, which checks that all expected rule files, agents, and settings scaffolds are in place. If you later enable another plugin or run `/plugin update`, re-run `/lazy-core.setup` — it is safe to run as many times as needed.

## How the run unfolds

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
%% intent: lazy-core.setup meta-installer flow — discovery, plan preview, confirmation, phased execution, final report
sequenceDiagram
  participant user as User
  participant setup as /lazy-core.setup
  participant pluginsJson as installed_plugins.json
  participant skillDisc as Skill Discoverer
  participant childSkill as Child Skill (per-plugin)
  participant report as Final Report

  user->>setup: invoke /lazy-core.setup
  setup->>pluginsJson: read enabled lazycortex plugins
  pluginsJson-->>setup: plugin list

  setup->>skillDisc: discover <namespace>.install skills per plugin
  skillDisc-->>setup: ordered skill list

  Note over setup,skillDisc: Phases: pre-install -> per-plugin -> post-install
  setup->>setup: build ordered plan (pre-install + per-plugin + post-install)
  setup-->>user: show plan preview

  setup->>user: AskUserQuestion — confirm execution?
  user-->>setup: confirmed

  loop each child skill in order
    setup->>childSkill: invoke child skill
    alt skill succeeds
      childSkill-->>setup: success outcome
    else skill fails
      childSkill-->>setup: failure outcome
    end
  end

  setup->>report: compile per-skill outcomes
  report-->>user: final report (success and failure per child skill)
```
