# Recommended `agent_models` entries

Copy-paste reference for well-known third-party subagents. No runtime effect
on its own — you paste the blocks you want into your
`.claude/lazy.settings.json` (project) or `~/.claude/lazy.settings.json`
(user), and `lazy-core.agent-model-router` routes dispatches to the listed
tier.

## How it works

The router reads `agent_models` as a grouped map:

```json
{
  "version": 1,
  "agent_models": {
    "_builtin":   { "Explore": "haiku", "Plan": "opus" },
    "_user":      { },
    "_project":   { },
    "lazycortex": { "lazycortex-log:lazy-log.distill": "haiku" }
  }
}
```

Groups:

- `_builtin` — Claude Code built-in subagents. Keys = bare dispatch names.
- `_user` — user-authored agents under `~/.claude/agents/*.md`. Keys = bare stems.
- `_project` — user-authored agents under `./.claude/agents/*.md`. Keys = bare stems.
- `<domain>` — vendor prefix of the plugin name (up to the first `-`).
  Keys = full plugin-qualified dispatch strings (`<plugin>:<stem>`).

Values: `"haiku" | "sonnet" | "opus" | "inherit"`. Unknown values log a
warning and fall through to `inherit`.

Session-wide cap: set `LAZY_AGENT_MODEL_FLOOR=haiku|sonnet|opus` to cap
every dispatch at that tier. Floor wins over caller-supplied `model` and
over config.

## Built-ins

```json
{
  "_builtin": {
    "Explore":         "haiku",
    "Plan":            "opus",
    "general-purpose": "inherit",
    "statusline-setup": "haiku"
  }
}
```

Rationale: `Explore` does mechanical grep/read work (haiku); `Plan` does
architecture-level reasoning (opus); `general-purpose` defaults to the
caller's model (inherit); `statusline-setup` is a one-shot config writer
(haiku).

## lazycortex-log (shipped defaults)

Seeded automatically by `/lazy-log.install`. Shown here for reference.

```json
{
  "lazycortex": {
    "lazycortex-log:lazy-log.distill":  "haiku",
    "lazycortex-log:lazy-log.timeline": "haiku",
    "lazycortex-log:lazy-log.recall":   "sonnet",
    "lazycortex-log:lazy-log.summary":  "sonnet"
  }
}
```

Rationale: `distill` and `timeline` are mechanical rewriters (haiku);
`recall` and `summary` do ranked retrieval / synthesis (sonnet).

## lazycortex-obsidian (shipped default)

Seeded automatically by `/lazy-obsidian.install`. Shown here for reference.

```json
{
  "lazycortex": {
    "lazycortex-obsidian:obsidian.gen-tag-pages": "sonnet"
  }
}
```

Rationale: tag-page generation blends mechanical indexing with curated
summaries (sonnet).

## superpowers (third-party)

```json
{
  "superpowers": {
    "superpowers:code-reviewer":              "opus",
    "superpowers:brainstorming":              "opus",
    "superpowers:writing-plans":              "opus",
    "superpowers:subagent-driven-development": "sonnet",
    "superpowers:requesting-code-review":     "sonnet"
  }
}
```

Rationale: design / review / planning agents benefit from opus reasoning;
implementation and meta-coordination run fine on sonnet.

## claude-code-guide (third-party)

```json
{
  "claude": {
    "claude-code-guide:claude-code-guide": "sonnet"
  }
}
```

Rationale: documentation lookup agent — sonnet is a safe middle.

## memory.optimise (third-party)

```json
{
  "_project": {
    "memory.optimise": "sonnet"
  }
}
```

(Adjust group to `_user` if the agent lives under `~/.claude/agents/`.)

## tool.plugin-extractor (third-party planner)

```json
{
  "_project": {
    "tool.plugin-extractor": "opus"
  }
}
```

Rationale: planner / design agent — opus.

## Notes

- Entries marked `"inherit"` explicitly opt out of router injection. The
  caller's model (or the absence of one) wins.
- Floor caps apply to known tiers only. A caller-supplied `"inherit"` is
  passed through; the floor only affects entries in `{haiku, sonnet, opus}`.
- Run `/lazy-core.optimize` to interactively fill gaps (one agent at a
  time wizard). Run `/lazy-core.audit` to see the merged-with-provenance
  table and orphan/gap findings.
