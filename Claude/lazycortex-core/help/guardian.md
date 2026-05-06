---
chapter_type: block
summary: Catch secrets, PII, and internal paths before they reach a public repo; stop per-tool allow prompts for new MCP servers in one step.
last_regen: 2026-05-06
diagram_spec:
  anchor: "How the three skills fit together"
  request: "Flow diagram showing how lazy-guard.check-public feeds findings into lazy-repo.mark-public (which creates .guard-waivers.json and activates the pre-commit hook), and how lazy-guard.allow-mcp independently classifies MCP server tools into allow/ask/skip buckets and writes them to settings.local.json"
  kind_hint: flow
source_skills:
  - lazy-repo.mark-public
  - lazy-guard.check-public
  - lazy-guard.allow-mcp
---
# Public-repo guardrails and MCP permission management

Two problems come up whenever you expand what Claude Code can see or share. First, making a repo public without first checking it can silently ship secrets, personal email addresses, internal hostnames, or hardcoded local paths — things that are easy to miss in a normal diff review. Second, every new MCP server floods you with per-tool allow prompts until you've explicitly classified each one.

The guardian block addresses both. `/lazy-guard.check-public` is a parallel, four-category scanner that catches leaks before they commit. `/lazy-repo.mark-public` wraps that scanner in a guided workflow that resolves every finding, writes the waiver file, and optionally flips GitHub visibility. `/lazy-guard.allow-mcp` classifies each MCP server's tools into three buckets — no-prompt, always-prompt, and default — so you stop deciding the same question over and over.

All three skills write to files they own (`.guard-waivers.json`, `settings.local.json`) so you never have to hand-edit config to use them.

## When you'd use this

- You're about to make a repo — or a subtree like `claude/**` — public and want to be sure nothing sensitive is tracked.
- You've added a config file, secret-adjacent script, or deploy artifact and want a one-off scan before committing.
- You want the scan to run automatically on every future commit, blocking secrets from landing without review.
- You just added a new MCP server and are drowning in per-tool prompts every time Claude Code uses it.
- You want Claude Code to prefer MCP tools over Bash equivalents without the deferred-schema round-trip that causes drift.

## What's in this block

**`/lazy-guard.check-public`** is the scanner. It dispatches four Explore agents in parallel — one for secrets (FAIL), one for PII (WARN), one for infrastructure literals (WARN), and one for hardcoded local paths (WARN) — then merges, deduplicates, and applies any waivers you've recorded in `.guard-waivers.json`. After showing you a unified findings report it walks through fix strategies: encrypt, template-ize, redact, or formally waive with a documented reason. You can run it standalone at any time for an ad-hoc audit. When `.guard-waivers.json` exists at the repo root the `lazy-guard.check-public` pre-commit hook activates automatically and runs the same scan on every staged diff, blocking the commit on any unresolved FAIL finding.

**`/lazy-repo.mark-public`** is the guided end-to-end workflow for taking a repo (or subtree) public. It calls `/lazy-guard.check-public` internally, then walks you through resolving every finding before it will proceed. Once all secrets are cleared it writes `.guard-waivers.json` — which both records your waiver decisions and activates the pre-commit hook for all future commits — and in whole-repo mode optionally flips GitHub visibility via `gh`. If you only want a subtree to be public (e.g. `claude/**` ships to the marketplace while the rest stays private), pass the scope glob: the hook then scans only those paths on every commit, and the GitHub visibility step is skipped entirely.

**`/lazy-guard.allow-mcp`** works independently of the other two. It enumerates every tool the target MCP server exposes in your current session and classifies each one: safe or reversible reads and low-risk writes go into `permissions.allow` (no prompt), truly destructive operations go into `permissions.ask` (always prompt), and medium-risk tools are left out of both so Claude Code's default per-call prompt applies when you actually invoke them. Results land in `settings.local.json` — gitignored by default — so your personal permission choices never leak into commits your teammates inherit. For globally defined servers the skill asks whether to register at global scope (all projects on this machine) or project scope (this repo only). It also optionally installs a SessionStart preload hook that resolves MCP tool schemas once at session start, which is what stops Claude Code from drifting to Bash equivalents when schemas feel expensive to fetch mid-session.

## How they work together

The three skills compose around a single shared artifact: `.guard-waivers.json`. That file is the on/off switch for the pre-commit hook and the record of every accepted exception.

When you run `/lazy-repo.mark-public` for the first time, it calls `/lazy-guard.check-public` internally, surfaces all findings, and guides you through them one by one. FAILs (secrets) must be resolved — encrypted, template-ized, or redacted — before the workflow continues. WARNs (PII, infrastructure literals, local paths) can be fixed or formally waived with a justification. At the end of that process `/lazy-repo.mark-public` writes `.guard-waivers.json`, which immediately arms the pre-commit hook. From that point forward every staged commit is scanned automatically, and you only run `/lazy-repo.mark-public` again if you want to re-examine scope or add waivers interactively.

Day-to-day auditing uses `/lazy-guard.check-public` directly. Run it after adding a config file, after pulling in new dependencies, or on any cadence that fits your workflow. It reads the existing `.guard-waivers.json` (including your accepted waivers) and skips everything already resolved.

`/lazy-guard.allow-mcp` is independent of the public-repo flow. Run it once per MCP server, immediately after adding the server to your session. The skill reads the server name from your input, enumerates its live tools, shows you the planned diff (what goes to `allow`, what goes to `ask`, what gets skipped, any cross-scope cleanup), and writes to the gitignored `settings.local.json`. If you need to revisit a prior classification — for example to promote a tool you previously allowed into the always-prompt bucket — re-run `/lazy-guard.allow-mcp` for that server; any reversal of a prior trust choice requires a per-tool explicit confirmation before it lands.

## Common adjustments

**Subtree-only publish.** Pass a glob to `/lazy-repo.mark-public` — for example `claude/**` — and the skill runs in subtree-public mode: it audits only those paths, writes `public_scopes` into `.guard-waivers.json`, and skips the GitHub visibility step. The pre-commit hook limits its checks to files under those globs on every future commit.

**Re-auditing an already-public repo.** Run `/lazy-guard.check-public` directly. It reads the existing waiver file and scans only the paths in scope. Run it after adding configs, after pulling in new dependencies, or before any release.

**Public author identity.** When the scanner finds your real name in a manifest (B4 check), run `/lazy-repo.mark-public` and confirm the public identity you want to use. The skill records it as `public_author` in `.guard-waivers.json`; every future B4 match equal to that name auto-waives without a per-file decision.

**Previewing MCP registrations before writing.** Pass `--dry-run` to `/lazy-guard.allow-mcp` and it prints the full planned diff — what goes to `allow`, what goes to `ask`, what gets skipped, what cross-scope leaks would be cleaned up — without touching any file.

**Reversing a prior allow decision.** Re-run `/lazy-guard.allow-mcp` for the server. If any tool the classifier considers destructive is still sitting in `allow` from a past run, the skill will ask you per-tool whether to promote it to `ask`. Your prior `allow` entry is never silently removed — each reversal requires an explicit confirmation.

## See also

- [install-and-audit](install-and-audit.md) — bootstrap the plugin that ships this block; the pre-commit hook is a Python script installed by `/lazy-core.install`.
- [make-repo-public](walkthroughs/make-repo-public.md) — step-by-step walkthrough that exercises the full `/lazy-repo.mark-public` → `/lazy-guard.check-public` → ongoing hook flow end-to-end.

## How the three skills fit together

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  userRunsCheckPublic[Run lazy-guard.check-public]
  scanFindings{Findings?}
  failSecrets{Secrets found?}
  warnPii[PII / infra / path warnings]
  resolveSecrets[Resolve secrets - encrypt or redact]
  userRunsMarkPublic[Run lazy-repo.mark-public]
  createWaivers[Create .guard-waivers.json]
  activateHook[Pre-commit hook activated]
  commitBlocked{Commit passes scan?}
  publishDone[Repo published - Done]
  commitFailed[Commit blocked - Fix findings]

  userRunsAllowMcp[Run lazy-guard.allow-mcp]
  discoverTools[Discover MCP server tools]
  classifyTools{Classify each tool}
  allowBucket[allow bucket]
  askBucket[ask bucket]
  skipBucket[skip bucket]
  writeSettings[Write to settings.local.json - Done]

  userRunsCheckPublic -->|scan repo| scanFindings
  scanFindings -->|clean| userRunsMarkPublic
  scanFindings -->|findings| failSecrets
  failSecrets -->|secrets FAIL| resolveSecrets
  failSecrets -->|warnings only| warnPii
  resolveSecrets -->|resolved| userRunsMarkPublic
  warnPii -->|waive or fix| userRunsMarkPublic
  userRunsMarkPublic -->|write| createWaivers
  createWaivers -->|enables hook| activateHook
  activateHook -->|on each commit| commitBlocked
  commitBlocked -->|passes| publishDone
  commitBlocked -->|fails| commitFailed

  userRunsAllowMcp -->|enumerate| discoverTools
  discoverTools -->|classify| classifyTools
  classifyTools -->|permit| allowBucket
  classifyTools -->|prompt| askBucket
  classifyTools -->|exclude| skipBucket
  allowBucket -->|merge| writeSettings
  askBucket -->|merge| writeSettings
  skipBucket -->|merge| writeSettings

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef guard fill:#5f4a1e,stroke:#e2a14a,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px
  classDef error fill:#5f1e1e,stroke:#e24a4a,color:#fff,stroke-width:2px
  classDef store fill:#5f3a1e,stroke:#e2904a,color:#fff

  class userRunsCheckPublic entry
  class userRunsAllowMcp entry
  class scanFindings guard
  class failSecrets guard
  class classifyTools guard
  class commitBlocked guard
  class resolveSecrets action
  class warnPii action
  class userRunsMarkPublic action
  class discoverTools action
  class createWaivers store
  class activateHook action
  class allowBucket action
  class askBucket action
  class skipBucket action
  class writeSettings store
  class publishDone success
  class commitFailed error
```
