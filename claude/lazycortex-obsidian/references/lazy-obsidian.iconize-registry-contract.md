---
description: Contract for plugin-shipped iconize registries — file location and schema, the five semantic priority bands, layer-composition order, shipped-callback resolution, and the review checklist a registry must pass.
---
# Iconize plugin-registry contract

A plugin that knows the meaning of its own frontmatter ships that knowledge as an **iconize registry** — a JSON file of matchers the `iconize_sync` worker reads live on every run. The vault's personal icon-map (`.claude/iconize/obsidian-icon-map.json`) stays what it always was: operator rules the plugins cannot know, and overrides. Nothing is merged at install time; installing, updating, or removing a plugin changes what gets painted on the next worker run, automatically.

## 1. File location and discovery

- Path: `claude/<plugin>/references/<ns>.iconize-registry.json` — `<ns>` is the plugin's canonical namespace (`lazy-spec`, `lazy-review`, `lazy-wiki`, …). A plugin may ship several registry files (one per namespace).
- Discovery: the worker walks the plugin roots in `$LAZYCORTEX_PLUGIN_DIRS` (exported by the lazycortex-core runtime daemon) and reads every `references/*.iconize-registry.json`. Outside a daemon context it falls back to the dev-vault sibling layout `<vault>/claude/*`.
- Best-effort, always: an absent plugin contributes no rules; an unreadable or malformed registry is skipped with a stderr diagnostic; nothing ever blocks a commit or a run.

## 2. File schema

```json
{
  "schema_version": 1,
  "matchers": [
    {
      "when": { "frontmatter.spec_halted": true },
      "resolve": { "iconName": "{{frontmatter.iconize_icon}}", "iconColor": "#fca5a5" },
      "priority": 550
    }
  ],
  "registries": { "optional-lookup-tables": {} }
}
```

- `schema_version` — integer, currently `1`. A registry declaring any other value is skipped whole.
- `matchers[]` — the same `when` / `resolve` shapes the personal icon-map uses (see the iconize protocol), plus a **mandatory** matcher-level `priority`.
- `registries` — optional lookup tables, merged under the personal map's tables (the operator's keys win on collision).

## 3. Semantic priority bands

The band is assigned to a **rule** by the class of its signal, never to a plugin. One plugin's registry spreads its rules across every band its signals belong to.

| Band | Range | Signal class | Examples |
|---|---|---|---|
| 1. Error / blocker | 500–599 | red visible through everything | `spec_halted`, dead job, upstream source failing |
| 2. Operator action needed | 400–499 | orange stripe | review `action-needed`, concerns pause, upstream `Take into work` |
| 3. Transient process | 300–399 | overrides status, yields to 1–2 | review `in-process`, job in flight |
| 4. Permanent status | 200–299 | stage / kind | asset stage, upstream unit status, wiki note kind, plugin versions |
| 5. Base / decor | 100–199 | defaults | icon by file type, folder color |

A registry matcher whose `priority` is missing, non-integer, or outside 100–599 is **skipped with a stderr diagnostic** — the band is the contract, not a suggestion.

The key consequence: precedence is by meaning, not by plugin. Review's `in-process` (band 3) yields to specs' `spec_halted` (band 1) on the same file; a halted asset stays red even while under review.

## 4. Layer composition and ordering

The worker folds all discovered registries under the personal map into one matcher list and evaluates it first-match-wins in this order:

1. Higher `priority` first.
2. On equal priority, the **operator's matcher beats any plugin's**.
3. Between two plugins at equal priority: plugin name, then declaration order — deterministic, but two plugin rules overlapping on the same files at equal priority are a **registry bug**, not a supported layering.

Personal-map matchers without a `priority` default to `1000` — above every band, preserving the pre-layering behavior of existing vaults. The operator opts a personal rule into the band scale by writing an explicit `priority`.

The worker never strips icon keys from a note no matcher claims: sibling plugins write managed `iconize_icon` / `iconize_color` keys of their own, and the absence of a rule is not an instruction to remove them.

## 5. Shipped callbacks

A registry matcher's `callback: <id>` resolves against the vault's `.claude/callbacks/<id>` first — the operator overrides a shipped callback the same way an operator matcher beats a plugin matcher — falling back to the shipping plugin's own `claude/<plugin>/callbacks/<id>` (executable, stdin/stdout JSON per the iconize protocol), which is what makes registry callbacks work with zero vault setup. Personal-map matchers resolve from the vault directory only.

## 6. Registry review checklist

Reviewing a registry (in code review or `lazy-obsidian.audit`) means checking:

- every matcher's `priority` sits inside the band its signal class belongs to (table above) — a transient process at 550 or a blocker at 250 is a finding;
- no two matchers of the same registry can claim the same file at the same priority;
- `when` predicates key on the plugin's own frontmatter/callbacks, not on vault-specific paths — consumer content roots are configurable, so `path_glob` on a hardcoded root is a finding;
- colors are lowercase `#rgb` / `#rrggbb`; icon names pass the worker's `--validate-entry` shapes;
- callbacks referenced by the registry ship in the plugin's `callbacks/` dir (or are documented as operator-provided).
