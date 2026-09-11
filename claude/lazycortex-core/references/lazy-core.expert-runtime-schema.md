---
description: How the runtime CONFIGURES an expert spawn — commit rights, hermetic MCP servers / settings sources / hooks, `workspace: branch` and its linked worktree, the filesystem sandbox, and foreign providers.
---
# lazy-core.expert-runtime — how the runtime configures an expert spawn

§ 11 of `lazy-core.runtime-schema.md`, extracted and read on demand: open this file when wiring an `experts[<name>]` entry, or when explaining why a spawn behaved as it did — what it was allowed to commit, which MCP servers, settings scopes and hooks reached it, whether it ran on a job branch, what it could read and write, and which endpoint it talked to. A `§ N` cross-reference below that names no file names a section of the parent.

**Not the same file as `lazy-core.expert-runtime-contract.md`.** That one is what the expert AGENT reads: it is appended to every spawn's system prompt and tells the agent how to behave. This one is what the RUNTIME reads: the operator-facing configuration that decides how a spawn is built, before any agent exists. Two audiences, two directions — do not merge them.

## 11. Expert runtime contract

Every expert run receives `claude/lazycortex-core/references/lazy-core.expert-runtime-contract.md` via `claude -p --append-system-prompt-file ...`. The contract is loaded as a system-prompt-level rule on top of the expert's per-protocol contract.

Contract sections:
- **Working tree** — every change must be committed before exit. No push, no branch switching.
- **Input** — `request.json` schema (required `role`, plus protocol-specific fields).
- **Output** — `response.json` schema (`outcome`, `result`, `error`).
- **What you must not touch** — `DONE`, other experts' job dirs, state.json, branches.

### Commit rights — foreign-execution by default

An expert may not commit in the repository it runs against unless its own entry says so:

```
experts:
  <name>:
    can_commit_in_repo: true
```

Absent or `false`, the pump appends the foreign-execution no-commit clause to the spawn prompt: the expert must not edit the document it was given, anything under `source/`, or any other working-tree file, and must not commit — it returns such changes as data in `response.json` and the dispatcher applies them locally. Its own persona side-channels (persona memory under `.memory/<self>/`, run logs under `.logs/`) are exempt and self-commit under their own bot identity. `true` drops the clause, so the expert lands its work in the tree itself — what `/lazy-experts.install` seeds for the writing roles.

A dispatching routine may override the entry's value for its own jobs; today only `md-scan` does — see `lazy-core.routine-types-schema.md`.

### MCP servers — hermetic by default

Expert spawns always run `claude -p --strict-mcp-config`, so **ambient operator MCP servers are never inherited** (`~/.claude.json`, project `.mcp.json`). This is deliberate: the daemon spawns experts headless with no TTY, and an interactively-authenticated MCP server (OAuth / claude.ai connectors) blocks on initialization until the job hits its routine timeout and dies. Expert memory is file-based (`.memory/<self>/`, see `lazy-memory.persona-aspect`), not MCP — hermetic spawns lose no capability by default.

An expert that genuinely needs one or more MCP servers declares them per-expert:

```
experts:
  <name>:
    mcp_config: .claude/mcp/<name>.json          # single path
    # or: mcp_config: [.claude/mcp/a.json, .claude/mcp/b.json]
```

Each path (relative to the repo root) is passed as `--mcp-config <path>`; under `--strict-mcp-config` the spawn loads **only** those servers. The referenced files use the standard MCP-config JSON shape. Only headless-safe servers work here (token/env auth, no interactive login, launcher on `PATH`); an interactive-auth server declared this way still blocks. Validate a config's launchability with `/lazy-runtime.preflight` before wiring it into a live routine.

### Settings sources — hermetic by default

Expert spawns always pass `claude -p --setting-sources project,local`, so **operator user-scope settings are never loaded** by default. This is the settings-file analogue of `--strict-mcp-config`: user-scope (`~/.claude/settings.json` and the plugins it enables) is where interactively-oriented operator plugins and their hooks live, and a headless spawn that inherits them can hang. For example a `PostToolUse [*]` hook that blocks on a terminal/OAuth round-trip stalls every tool call until the routine timeout kills the job. Dropping `user` scope keeps the project's own skills / agents / plugins (`project`, `local`) while shedding that ambient risk.

An expert that genuinely needs user-scope settings opts back in explicitly:

```
experts:
  <name>:
    setting_sources: [user, project, local]   # or a comma string "user,project,local"
```

Valid scopes are exactly `user`, `project`, `local`; anything else is dropped (surfaced as a `warn` by `/lazy-runtime.preflight`). An absent or empty `setting_sources`, or one that leaves no valid scope, resolves to the hermetic `project,local` default — the flag is always emitted, so every expert is hermetic out of the box with no per-expert config, exactly like `--strict-mcp-config`. The default does not touch authentication: OAuth login keeps working.

### Lazycortex hooks — hermetic by default

`--setting-sources project,local` sheds *operator user-scope* hooks, but the project's own lazycortex hooks (`lazy-core.git-guard`, `lazy-guard.check-public`, `lazy-core.model-router`, `lazy-guard.settings`, `lazy-log.commit-recorder`) still load at `project` scope — and each one runs on every `Bash` boundary of the spawn. For a headless expert that is pure tax: `lazy-guard.check-public` and `lazy-core.git-guard` alone add tens of seconds per tool call and gate nothing the expert needs.

So the daemon exports `LAZYCORTEX_HOOKS_ALLOW_LIST` for every routine it dispatches, from that routine's own `hooks_enabled`, and each lazycortex hook consults it as its first action (`bin/hook_gate.py` for python hooks; shell hooks read the variable directly, since a git hook gets no path into the plugin tree). Expert spawns inherit it from the routine that runs the pump — the pump is itself a routine, so the setting lives in exactly one place. The variable is named for the action it exerts — "these hooks may run" — not for who set it: an operator can export the same variable in a shell to the same effect. Its **presence** flips every hook into allow-list mode; only the named hooks run, so a routine with no config runs none of them.

`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` is pinned to `3` the same way, on every headless expert spawn — daemon-driven or a manual `expert-pump-once` from `/lazy-spec.drive` alike, since both go through this same `env` construction — and on the daemon's own subprocess environment (`EnvVar.SUBAGENT_SPAWN_DEPTH_PIN`). Only the operator's own interactive session, never itself spawned by the pump, inherits whatever the ambient shell already has.

A routine opts specific hooks back in:

```
routines:
  <name>:
    hooks_enabled: [lazy-core.git-guard]   # only the git guard runs in this routine's subprocesses; the rest no-op
```

Absent or empty, the exported allow-list is empty → every lazycortex hook no-ops in anything the routine spawns (the hermetic default, mirroring `setting_sources`). On an `expert`-shape routine the key is inert: that session is spawned by the pump routine and therefore carries the pump's list.

The same gate powers the mirror-image interactive control. In a normal session (no `LAZYCORTEX_HOOKS_ALLOW_LIST`) every hook runs unless the operator silences it by short name in a root-level block-list:

```
hooks:
  disabled: [lazy-core.model-router]   # this hook no-ops in interactive sessions; the rest run
```

`hooks.disabled` reads the tracked value with the local overlay merged on top, so a personal silence can live in the gitignored `lazy.settings.local.json`. The block-list read fails open — a missing or malformed settings file silences nothing. Operator hooks outside the lazycortex tree do not read this variable; user-scope ones are already shed by `--setting-sources`, and operator *git* hooks are handled by a different mechanism — the daemon points `core.hooksPath` at a directory of symlinks to the hooks named in `daemon.git.allowed_hooks`, so an unvetted one never runs under it.

### Workspace — branch enforcement, main by default

An expert's spawn runs on the daemon's base branch by default (`workspace: main`, or the key absent — today's behavior). An expert that carries out the acceptance-cycle work `lazycortex-specs.optional-plan-and-auto-implementation.md` describes (implementer/tester classes on a launch-checkbox job and its continuations) opts into a job-scoped branch instead:

```
experts:
  <name>:
    workspace: branch   # main | branch — default main
    merge: ask           # auto | ask — default ask; consulted by the DISPATCHER's own
                          # merge logic, never read by the pump itself
```

`workspace: branch` is a CAPABILITY the expert opts into, not a mandate every one of its jobs must satisfy: it is enforced by the pump (`expert_pump._process_one`), never by the expert — the expert never runs git worktree or checkout commands itself (`lazy-core.expert-runtime-contract.md` "What you must not touch" already forbids it) — and it activates only when the job's own `request.json` carries a `branch` field. When a `workspace: branch` expert is also dispatched for work that carries no `branch` (an ordinary review-rewrite from `review.coordinator`, say, sharing the same implementer/tester expert the acceptance cycle uses), that job runs on whatever is already checked out, byte-identical to a `workspace: main` job — no refusal. The reverse mismatch — a `branch` present in the payload of a `workspace: main` (or absent) expert's job — is also never a refusal: the field is ignored (a warning line goes to the daemon log) because a main-workspace expert never branches, full stop.

**The token stays `branch`; the mechanism is a linked worktree.** When `branch` IS present and `workspace: branch` applies, the pump runs the job in an isolated git worktree at `<worktree_root>/job-<job_id>/` instead of switching the primary checkout: a fresh dispatch's branch is created off fresh base (`origin/<base_branch>` when the tracking ref exists, else the local base), a continuation's existing branch is reused as-is; the gitignored local config (`settings.local.json`, `lazy.settings.local.json`) is symlinked in; `daemon.git.worktree_bootstrap_cmd` (when configured) runs in the worktree to rebuild the gitignored execution environment (a bootstrap failure fails the job as `transient` before any spawn); the spawn's cwd is the worktree; and the worktree is removed on EVERY outcome — success, failure, crash — with the branch as the only durable product. The primary checkout never leaves base, so the operator's tree and the daemon's `_git_pre` are untouched by isolated jobs. The one refusal left in this path is a missing `daemon.git.base_branch` — a fresh job branch has nothing to fork from — so the job errors (`error`, category `logical`) rather than forking off an arbitrary point.

**Commit obligation and job-failure checks.** The isolated agent's prompt carries the obligation to commit all work to its branch (with resume wording on a continuation: build on the existing commits, never rewrite them). After a clean exit the pump verifies the worktree with a bare `git status --porcelain`: any reported change — modified/added tracked files, or an untracked path nothing ignores — fails the JOB (`error`, category `logical`) — never the daemon; the daemon-wide dirty-tree halt applies only to non-isolated jobs, whose spawns share the operator's tree. This is not a special-cased flag on the probe: `git status --porcelain` already omits ignored paths from its own output, so a bootstrap artefact the worktree's own `.gitignore` covers (see `worktree_bootstrap_cmd` above) is invisible to the check for free, while anything that artefact-recording did not catch still counts as dirt. Zero commits over base with a clean tree also fails the job the same way. Uncommitted dirt disappears with the worktree (operator decision, 2026-08-14); diagnosis lives in the job's transcript and error record.

**Continuation reuses the same branch.** A dispatcher driving the acceptance cycle's comment-and-redo loop passes the SAME `branch` value on every continuation job as the original dispatch — the pump's create-or-reuse check (`git rev-parse --verify`) makes this idempotent; a continuation never gets a fresh branch of its own, though it does get a fresh worktree and a fresh bootstrap run. Only the coordinator ever writes the `branch` field — for a fresh launch-checkbox dispatch and every one of its continuations; every other dispatch to the same expert (review rewrites) simply omits it. The pump itself never persists the branch name anywhere — it is RECOMPUTED by the dispatcher from the asset's own identity on every dispatch (`lazy-spec.coordination-playbook.md` § 6), so a dispatcher whose naming scheme depends on a renameable asset identifier (a slug, a folder path) silently orphans an in-flight branch the moment that identifier changes underneath it; this is the dispatcher's own constraint to document, not something the pump's create-or-reuse check can catch.

**`merge` is dispatcher-owned, not pump-owned.** The pump never merges a branch back — only the coordinating dispatcher does, per its own playbook judgment (see `lazy-spec.coordination-playbook.md` § 6 for the spec-system's own instance of this). `merge: auto` / `merge: ask` (default `ask`) is read by that dispatcher logic alone; it has no runtime effect inside `expert_pump.py`.

**A claimant killed mid-job leaves only an orphan directory.** The primary checkout was never switched, so there is nothing to restore; the abandoned worktree is collected by the hourly `sweep()` (every directory under `worktree_root` is an orphan by definition — a live worktree exists only inside one synchronous pump run, and the serial main loop never sweeps concurrently with one). The same holds in a no-daemon drive session (`lazycortex-specs.lazy-spec.drive` pumping `expert-pump-once` by hand): an interrupted manual pump leaves an orphan worktree and an untouched checkout, nothing more.

**The git guard stands down inside a linked worktree.** `lazy-core.git-guard` skips both the pathspec discipline and the staging-window mutex when the invocation's `--git-dir` differs from `--git-common-dir` — a linked worktree has its own index, so the shared-index premise both rows rest on does not hold there.

### Filesystem sandbox — resolved paths only

Every expert spawn is confined by `.runtime/sandbox.settings.json` (daemon-owned, gitignored, passed as `--settings`; absent file = unconfined spawn). The confinement is checked against the path the OS **resolves**, not the path the allowlist spells: an entry naming a directory reached through a symlink permits nothing where the data actually lives, and every write there fails with `Operation not permitted` while the recorded config still reads as correct.

So the file is written by CLI, never by hand:

```
lazycortex-core sandbox-sync --repo-root <repo> [--allow-read <path>]... [--allow-write <path>]...
```

The repo root is granted read+write implicitly; whatever is writable is also readable. Each entry — recorded, passed, or the root — contributes the location it resolves to, plus the targets of the symlinks directly inside it (the `external_dirs` slots of `lazy-core.state-schema.md` § 15). Recorded entries are never dropped or reordered and a recorded `enabled` or `allowUnsandboxedCommands` is never overwritten, so the call is idempotent; `enabled: false` comes back in the result for the caller to act on. An unrecorded `allowUnsandboxedCommands` is written `false` — Claude Code's default of `true` retries a command the sandbox blocked with the sandbox disabled, subject only to the permission check a bare `Bash` allow passes, which would let a confined spawn write outside its scope on the second try. `/lazy-runtime.preflight` reports the switch as `fail` whenever it is not recorded `false`. `sandbox-audit --repo-root <repo>` is the read-only companion: it reports `missing_read` / `missing_write` — locations the recorded entries resolve to but do not grant. `/lazy-runtime.preflight` folds that audit into its checkout-level findings (`fail` on write, `warn` on read), so a symlink that moves after install surfaces as a finding instead of as a run of jobs failing on every write.

### Providers — Anthropic by default

Every expert job spawns against Anthropic with no configuration at all. An expert that must run against a foreign OpenAI- or Anthropic-compatible endpoint instead points at a named entry in the flat top-level `providers` section:

```
experts:
  <name>:
    provider: <provider-name>   # absent = the Anthropic default
```

The registry is a machine fact — an endpoint plus the *name* of the variable carrying its credential — not a shared team decision, so `/lazy-core.providers` writes it only into the gitignored `lazy.settings.local.json`; an entry found in the tracked file was hand-written and is flagged, never auto-migrated. `providers` carries no `_version`: it is absent from `CURRENT_VERSIONS` (see `lazy-core.settings-schema` § 2).

```json
{
  "providers": {
    "<name>": {
      "base_url": "http://localhost:4000",
      "token_env": "MY_PROXY_TOKEN",
      "models": { "fable": "…", "opus": "…", "sonnet": "…", "haiku": "…" }
    }
  }
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `base_url` | string | **yes** | The endpoint's base URL. Note the `claude` CLI's own constraint: it rejects non-`claude-*` model names against a public `ANTHROPIC_BASE_URL` before any network call, so in practice a provider is either `api.anthropic.com` or a local proxy (`http://localhost:<port>` / `http://127.0.0.1:<port>`). |
| `token_env` | string | **yes** | Name of the environment variable holding the endpoint's credential — never the credential itself. Resolved at spawn time from the process environment first, then from `~/.claude/.env` (last assignment of the variable wins). |
| `models` | object | **yes** | One model alias per tier. All four of `fable`, `opus`, `sonnet`, `haiku` are mandatory: an uncovered tier would leak to the foreign endpoint under its Claude alias name. |

**Validation** — `provider_env.validate_entry`, disk-free and identical at wizard time and dispatch time, raises `ProviderConfigError` when: the entry is missing or is not a dict; `base_url` or `token_env` is blank or not a string; any of the four tiers is missing or blank; any tier value starts with `claude-` (Anthropic's namespace passes through neither a foreign endpoint nor the proxy); or — for the entry named `openai` specifically — any tier value lacks the `rt-openai/` prefix, since the proxy reserves the bare `openai/*` route for the operator's own interactive key and runtime traffic must never borrow it.

**Where it fires.** `dispatch_job` resolves and validates the expert's `provider` **before** writing any part of the job bundle, so a misconfigured endpoint fails the dispatch loudly instead of queueing a job that dies at spawn. The resolved block is snapshotted into the job's `config.json`; the pump consumes that snapshot verbatim, so a registry edit never retargets a job already in the queue.

**What a provider-bound spawn's environment becomes** (`provider_env.build_spawn_env`):

- `ANTHROPIC_BASE_URL` ← `base_url`, `ANTHROPIC_AUTH_TOKEN` ← the resolved token.
- `ANTHROPIC_DEFAULT_FABLE_MODEL` / `…_OPUS_MODEL` / `…_SONNET_MODEL` / `…_HAIKU_MODEL` ← the four tier aliases, covering both `--model` tiers and subagent-frontmatter tiers.
- `CLAUDE_CODE_SUBAGENT_MODEL` ← the `sonnet` alias — a deterministic mid-tier backstop for built-in subagents that carry no `model:` at all.
- `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` are **removed**: neither of the operator's own Anthropic credentials travels to a foreign endpoint.

A `token_env` that resolves in neither the environment nor `~/.claude/.env` fails the job (`error`, category `logical`) before the spawn, naming the variable. A provider-bound run is also exempt from the pump's missing-`rate_limit_event` warning — a foreign endpoint emits no such frames, so silence there is not a swallowed guard signal.
