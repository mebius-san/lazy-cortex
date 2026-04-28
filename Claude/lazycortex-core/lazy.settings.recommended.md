# `agent_models` — schema and recommendations

`lazy-core.agent-model-router` reads `agent_models` from `lazy.settings.json` and routes every Agent dispatch to the configured tier. This doc explains the **schema**; the **canonical recommendations** live in
[`skills/lazy-core.agent-models/default-tiers.json`](skills/lazy-core.agent-models/default-tiers.json) — single source of truth for both the wizard ("accept all template defaults" batch) and `lazy-core.agent-writing § 8` (new-agent tier seeding).

## Schema

```json
{
  "version": 1,
  "agent_models": {
    "_builtin":   { "Explore": "haiku", "Plan": "opus" },
    "_user":      { },
    "_project":   { },
    "lazycortex": { "lazycortex-log:lazy-log.distill": "sonnet" }
  }
}
```

Groups:

- `_builtin` — Claude Code built-in subagents. Keys = bare dispatch names (`Explore`, `Plan`, `general-purpose`, `statusline-setup`).
- `_user` — user-authored agents under `~/.claude/agents/*.md`. Keys = bare stems.
- `_project` — user-authored agents under `./.claude/agents/*.md`. Keys = bare stems.
- `<domain>` — vendor prefix of the plugin name (up to the first `-`). Keys = full plugin-qualified dispatch strings (`<plugin>:<stem>`).

Values: `"haiku" | "sonnet" | "opus" | "inherit"`. Unknown values log a warning and fall through to `inherit`.

## Floor cap

`LAZY_AGENT_MODEL_FLOOR=haiku|sonnet|opus` env var caps every dispatch at that tier. Floor wins over caller-supplied `model` and over config. Caller-supplied `"inherit"` is passed through (the floor only affects `{haiku, sonnet, opus}`).

## Filling the file

- `/lazy-core.agent-models` — interactive wizard. Discovers every agent that's actually installed (built-ins, plugins, user/project agents), looks up the suggested tier in `default-tiers.json`, and offers batch + per-agent prompts. Writes to the structurally-correct file (`_user.*` → global, `_project.*` → project, plugin-domain → follows the plugin's install scope).
- `/lazy-core.audit` — surfaces gaps and merged-with-provenance view.
- `/lazy-core.optimize` — runs the wizard as Phase 7 of the full optimize pipeline.

Manual edits are fine — both `~/.claude/lazy.settings.json` and `./.claude/lazy.settings.json` are plain JSON. Don't duplicate the same dispatch in both files unless you intend project to override user.

## Tier-choice heuristic

When `default-tiers.json` doesn't cover a dispatch, the wizard suggests:

- `_builtin` — see `default-tiers.json`.
- Mechanical formatters / chronological merges (rewriter / formatter / timeline / mechanical in description) → `haiku`.
- Review / audit / plan / design / architecture → `opus`.
- Retrieval / synthesis / drafting prose → `sonnet`.
- Catch-all delegators with no own reasoning → `inherit`.

If a dispatch you care about should be a canonical default for everyone, add it to `default-tiers.json` (per `lazy-core.agent-writing § 8`) so future installs pick it up automatically.
