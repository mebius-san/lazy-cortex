---
name: lazy-core.providers
description: "Run when the operator asks to add, change, remove, or list the LLM providers the expert-job runtime can spawn against — an expert's `provider` field in `experts{}` points at a name registered here. Interactive wizard over the machine-local `providers` block in `.claude/lazy.settings.local.json`; validates each entry against the same rules the runtime's dispatch-time resolver enforces before it ever writes."
argument-hint: "[list|add|update|remove] [<provider-name>]"
allowed-tools: Read, Write, AskUserQuestion, Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Bash(git check-ignore *), Bash(python3 *), Bash(curl *), Agent
---
# Provider Registry

Manages the `providers` block: named LLM endpoints (base URL, token variable, four-tier model map) an expert-job spawn can be pointed at instead of Anthropic. Each entry is a machine fact — the endpoint and its credential name — not a shared team decision, so it lives only in the gitignored local overlay, never in the tracked settings file. Which expert uses which provider is a separate, content-level decision recorded on the expert's own entry and out of scope here.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Parse mode and target`
   - `Step 2 — Load current registry`
   - `Step 3 — Mode: list`
   - `Step 4 — Mode: remove`
   - `Step 5 — Mode: add/update wizard`
   - `Step 6 — Validate before write`
   - `Step 7 — Write back`
   - `Step 8 — Report`
   - `Step 9 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". Steps 3–7 that don't apply to the resolved mode are `skipped — mode is <mode>`; that counts as a valid outcome.
3. **Do not reach Step 8 until every prior step is `completed` or explicitly `skipped` with an outcome.** A still-`pending` step is a bug — stop and execute it first.
4. **Step 8 is a structural verifier.** Its output MUST contain one line per step above. A missing line is a bug.

## Step 1 — Parse mode and target

Parse `$ARGUMENTS`: first token is the mode, one of `list` (default when empty), `add`, `update`, `remove`. Second token, when present, is the provider name.

- Anything else as the first token → FAIL with usage: `mode must be one of list|add|update|remove`.
- `add`/`update`/`remove` with no name given → ask for it in Step 5/Step 4 respectively, don't fail here.

Outcome: `parsed`.

## Step 2 — Load current registry

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json
from pathlib import Path
from lazy_settings import load_tracked_section, load_local_only_section
tracked = load_tracked_section(Path('.claude/lazy.settings.json'), 'providers')
local = load_local_only_section(Path('.claude/lazy.settings.json'), 'providers')
print(json.dumps({'tracked': tracked, 'local': local}))
")
```

Keep both views distinct — the entries reported under `tracked` are a `WARN`: `providers` is a machine-fact section and a tracked entry means someone committed a base URL/token-variable name into shared config by hand. Build a merged-by-name map for Steps 4–6 (local wins over tracked per key, per the section's own merge rule), noting each key's source.

Outcome: `loaded (N tracked, M local)`.

## Step 3 — Mode: list

Only when mode = `list`.

Render one line per provider: `<name>` — `<base_url>` (token_env=`<token_env>`, tiers: fable/opus/sonnet/haiku) `[tracked|local]`. Flag every `tracked`-sourced entry with a trailing `WARN: providers belong in the local overlay — see Step 7`. Empty registry → `no providers registered`.

Stop here — do not proceed to Steps 4–6. Continue at Step 7 (skipped) → Step 8.

Outcome: `listed (N entries)` or `skipped — mode is <other>`.

## Step 4 — Mode: remove

Only when mode = `remove`.

1. If no name was given in Step 1, and the registry has more than one entry, ask which one to remove. Context (print before asking) — Where: `/lazy-core.providers · Step 4 — Mode: remove`, target `.claude/lazy.settings.local.json[providers]`; Found: the registry's entries, one line each `<name> — <base_url> [tracked|local]`; Why asking: `remove` was invoked without a name; Answers: one option per provider name — the chosen one goes to the confirmation in item 4, nothing written yet. `AskUserQuestion`: header "Which provider", question "Which provider should be removed from .claude/lazy.settings.local.json?", options = provider names, each described by its `base_url`. A single-entry registry with no name given is unambiguous — use it.
2. Name not found in the merged map → FAIL: provider `<name>` is not registered.
3. **Reference check** — load the merged `experts` section (`load_section(path, 'experts')`) and scan every entry's `provider` field for a match. Any hit is informational, never blocking: report `WARN: expert <key> still references provider <name>` for each (both placeholders substituted, not literal).
4. Confirm:

```
Context (print before asking):
- Where: /lazy-core.providers · Step 4 — Mode: remove; target .claude/lazy.settings.local.json[providers.<name>]
- Found: `<name>` — `<base_url>` (token_env=`<token_env>`) [<tracked|local>]; experts still referencing it: <list, or none>
- Why asking: removing the entry breaks every expert still pointing at it at dispatch time
- Answers: `remove` — entry dropped from the local overlay in Step 7, never re-asked; `cancel` — nothing written, run ends with outcome `aborted`
AskUserQuestion: header "Remove provider", question "Remove provider `<name>` (`<base_url>`) from .claude/lazy.settings.local.json?", options with descriptions.
```

   `cancel` → outcome `aborted`, skip Steps 5–6, go to Step 7 (skipped).
5. On `remove` → record the removal for Step 7.

Outcome: `removal-confirmed`, `aborted`, or `skipped — mode is <other>`.

## Step 5 — Mode: add/update wizard

Only when mode = `add` or `update`.

1. If no name was given in Step 1, ask for it. Context (print before asking) — Where: `/lazy-core.providers · Step 5 — Mode: add/update wizard`, target `.claude/lazy.settings.local.json[providers]`; Found: registered names `<list, or none>`; Why asking: `<add|update>` was invoked without a name; Answers: free-form text becomes the entry key, validated in Step 6, written in Step 7. `AskUserQuestion`: header "Provider name", question "Which provider name should this `<add|update>` target in .claude/lazy.settings.local.json?" (free-form text).
2. `add` with a name already in the merged map, or `update` with a name absent from it:

```
Context (print before asking):
- Where: /lazy-core.providers · Step 5 — Mode: add/update wizard; target .claude/lazy.settings.local.json[providers.<name>]
- Found: mode `<add|update>`, but `<name>` is <already registered — `<base_url>` [tracked|local] | not registered>
- Why asking: the mode and the registry disagree — creating or overwriting silently would hide a typo
- Answers: `<switch to update | register it as new>` — wizard continues in the other mode for `<name>` (fields pre-filled from the existing entry on update), nothing written yet; `pick a different name` — item 1 re-asked for a new name, nothing written yet
AskUserQuestion: header "Name conflict", question "Provider `<name>` is <already registered | not registered> in .claude/lazy.settings.local.json — <switch to update | register it as new>, or pick a different name?", options with descriptions.
```

3. Ask one question at a time, pre-filling each field's current value as the default when in `update` on an existing entry. One context block, filled per field:

```
Context (print before asking):
- Where: /lazy-core.providers · Step 5 — Mode: add/update wizard; target .claude/lazy.settings.local.json[providers.<name>.<field>]
- Found: current value `<value, or (unset)>`
- Why asking: an endpoint, its credential variable, and its model names are machine facts nothing on disk can derive
- Answers: free-form text — becomes the field's value in the candidate entry, validated in Step 6, written in Step 7 only if every check passes; asked again on every `update`
AskUserQuestion: header "<field>", question "<field> for provider `<name>` in .claude/lazy.settings.local.json? (current: <value, or unset>)" plus the field's note below, free-form text.
```
   - **base_url** — the endpoint's base URL. Note in the question body: the current `claude` CLI rejects non-`claude-*` model names against a public `ANTHROPIC_BASE_URL` before any network call (localhost is exempt) — a provider that isn't `api.anthropic.com` and isn't a local proxy (`http://localhost:<port>` / `http://127.0.0.1:<port>`) will fail to spawn regardless of what this wizard writes.
   - **token_env** — the environment variable name carrying the credential (never the credential itself).
   - **fable**, **opus**, **sonnet**, **haiku** — one model-name string each, in that order.
4. Assemble the candidate entry: `{base_url, token_env, models: {fable, opus, sonnet, haiku}}`.

Outcome: `collected` or `skipped — mode is <other>`.

## Step 6 — Validate before write

Only when mode = `add` or `update`. Every check below fails closed — the first failing check aborts with its message; no entry is written.

1. **Structural checks** — call `provider_env.validate_entry` directly (the same disk-free function `resolve_provider` calls at dispatch time), so the wizard's checks can never drift from the runtime's:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, sys
from provider_env import validate_entry, ProviderConfigError
entry = json.loads(sys.argv[1])
name = sys.argv[2]
try:
  validate_entry(name, entry)
  print(json.dumps([]))
except ProviderConfigError as exc:
  print(json.dumps([str(exc)]))
" '<entry-json>' '<name>')
```

   Any non-empty result → FAIL, list every message verbatim, no write.

2. **Token variable presence** — reuse `provider_env.resolve_token` (same env-then-`~/.claude/.env` precedence the runtime uses) rather than re-implementing the lookup. Print a presence verdict only — never the token itself, which would otherwise sit in the tool-call transcript:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from provider_env import resolve_token
print('present' if resolve_token('<token_env>') else 'missing')
")
```

   `missing` → FAIL: token variable `<token_env>` not found in the environment or `~/.claude/.env`.

3. **Liveness probe** — resolve the token inline via command substitution so the literal value never appears in the Bash call or its output:

```
Bash(curl -sS -m 10 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from provider_env import resolve_token
print(resolve_token('<token_env>') or '')
")" '<base_url>/v1/models')
```

   Anything other than `200` → FAIL: endpoint `<base_url>`/v1/models returned `<code>`, expected 200 (or `curl` itself failing → endpoint `<base_url>` unreachable). Reiterate the CLI's localhost/api.anthropic.com constraint from Step 5 if the base URL is neither.

Outcome: `validated` or `skipped — mode is <other>`; a FAIL here ends the run with no write (report the failing check(s) and stop before Step 7).

## Step 7 — Write back

Applies to `add`, `update` (validated in Step 6), and `remove` (confirmed in Step 4). Skipped for `list`.

1. **Gitignore check** — `Bash(git check-ignore -q -- .claude/lazy.settings.local.json)`. Exit 1 (not ignored) → STOP, do not write, report: `.claude/lazy.settings.local.json` is not gitignored — add it to `.gitignore` before this skill can write provider entries (they may carry machine-local endpoint facts).
2. Read-modify-write, touching only the `providers` key — every other section in the local overlay file is preserved untouched:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json
from pathlib import Path
from lazy_settings import load_local_only_section, save_local_section
path = Path('.claude/lazy.settings.json')
section = load_local_only_section(path, 'providers')
# add/update:
section['<name>'] = <entry-json>
# remove:
# section.pop('<name>', None)
save_local_section(path, 'providers', section)
")
```

   `save_local_section` creates the local overlay file when absent and never touches the tracked file.

Outcome: `written (<name> added|updated)`, `written (<name> removed)`, or `skipped — mode is list`.

## Step 8 — Report

One line per step in the canonical list, with its outcome word. For `add`/`update`/`remove` add a final summary line naming the provider and the resulting state; for `list`, the rendered table from Step 3.

## Step 9 — Log the run

```
Bash(mkdir -p .logs/claude/lazy-core.providers)
```

Then `Write` to `.logs/claude/lazy-core.providers/<UTC-timestamp>.md`:

```yaml
---
git_sha: <git rev-parse HEAD>
git_branch: <git rev-parse --abbrev-ref HEAD>
date: <YYYY-MM-DD HH:MM:SS UTC>
input: "<mode> <name, if any>"
---
```

`# lazy-core.providers`

`## Actions` — bullet per step actually taken (parsed mode, loaded registry, validated, wrote/removed entry, ...).

`## Result` `<success|failure>` — `<mode> <name>`.

## Failure modes

- **"mode must be one of list|add|update|remove"** — first argument isn't a recognised mode → re-run with a valid one, or omit for `list`.
- **"provider `<name>` is not registered"** — `remove` (or `update` used on a name that doesn't exist) named a provider not in the merged registry → check `/lazy-core.providers list` for the actual names.
- **"`base_url` is required" / "`token_env` is required"** — the wizard left a mandatory field empty → re-run and answer both.
- **"models must cover tiers [...]"** — one or more of `fable`/`opus`/`sonnet`/`haiku` is missing or blank → supply all four.
- **"claude-\* literal in tiers [...]"** — a tier was given a `claude-*` model name, which cannot pass through a foreign endpoint or the local proxy → use the provider's own model identifier.
- **"openai tiers [...] must use the rt-openai/ prefix"** — the `openai` provider's tiers must route through the proxy's `rt-openai/` wildcard, never the bare `openai/*` interactive-key route → prefix every tier value with `rt-openai/`.
- **"token variable `<token_env>` not found in the environment or ~/.claude/.env"** — neither location defines it → export it or add it to `~/.claude/.env`, then retry.
- **"endpoint ... returned \<code\>, expected 200" / "endpoint ... unreachable"** — the base URL doesn't answer `/v1/models` with a 200 for this token → check the URL and the token, or if the endpoint is a public Anthropic-compatible host that isn't `api.anthropic.com`, point it at a local proxy instead (the `claude` CLI rejects non-`claude-*` model names against public base URLs before making the call; only `localhost`/`127.0.0.1` and `api.anthropic.com` are exempt).
- **".claude/lazy.settings.local.json is not gitignored"** — the local overlay path was removed from `.gitignore` or never added → restore the `.gitignore` entry before retrying; this skill refuses to write machine-local endpoint facts into a path git would track.

## Notes

- **Local-only by design**: this skill never writes `.claude/lazy.settings.json` — only the gitignored local overlay. A `tracked`-sourced entry surfaced in Step 2/3 was written by hand outside this skill and is flagged, never auto-migrated.
- **Assigning a provider to an expert is out of scope** — that's the `provider` key on the expert's own `experts{}` entry, a content decision made where the expert is configured, not here.
