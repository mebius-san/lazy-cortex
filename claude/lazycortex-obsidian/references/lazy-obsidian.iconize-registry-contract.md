---
description: Contract for plugin-shipped iconize registries — file location and schema, the five semantic priority bands, layer-composition order, shipped-callback resolution, and the review checklist a registry must pass.
---
# Iconize plugin-registry contract

A plugin that knows the meaning of its own frontmatter ships that knowledge as an **iconize registry** — a JSON file of matchers the `iconize_sync` worker reads live on every run. The vault's personal icon-map (`.claude/iconize/obsidian-icon-map.json`) stays what it always was: operator rules the plugins cannot know, and overrides. Nothing is merged at install time; installing, updating, or removing a plugin changes what gets painted on the next worker run, automatically.

## 1. File location and discovery

- Path: `claude/<plugin>/references/<ns>.iconize-registry.json` — `<ns>` is the plugin's canonical namespace (`lazy-spec`, `lazy-review`, `lazy-wiki`, …). A plugin may ship several registry files (one per namespace).
- Discovery: the worker walks the plugin roots in `$LAZYCORTEX_PLUGIN_DIRS` (exported by the lazycortex-core runtime daemon) and reads every `references/*.iconize-registry.json`. Outside a daemon context it falls back to the dev-vault sibling layout `<vault>/claude/*`, then — when the worker itself runs from the plugin cache — to the newest cached version of every installed plugin.
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

## 3a. The icon is the type; state changes only the colour

A note's **icon** says what the note IS — its asset type, its document type, its role. Every **state** a matcher can key on — a review phase, a `review_result`, a `spec_stage`, a `spec_state`, an upstream status, a gate — may change only its **colour**. A state matcher therefore never resolves a literal `iconName`: it writes `"{{frontmatter.iconize_icon}}"`, borrowing whatever icon the note already carries, and pairs it with the colour that state deserves. A literal icon name in a `resolve` block is legal only when that literal IS the type's own icon, in which case every matcher for that type carries the same literal and they differ only in colour — the three `spec_role: request` matchers of `lazy-spec.iconize-registry.json` are the shipped example: one `LiMail`, three statuses, three colours.

The reason is that a folder full of notes reads as a shape first and a colour second. Repainting the icon by state destroys the only stable signal a reader has for what each note is, and it destroys it exactly when the folder is busiest. Colour carries state perfectly well and costs nothing.

**The borrow token means "whatever this note's type gives it", never "whatever this note currently carries".** A matcher resolving `iconName` through `{{frontmatter.iconize_icon}}` names no icon at any time, however the note happens to be painted: the worker keeps its colour and carries the walk on to the lower-priority matcher that does own an icon, which re-resolves it from the type's own declaration (`iconize_sync._build_entry` / `resolve_matchers`). So a note whose `iconize_icon` is stale — the type's declared icon changed after the note was scaffolded — or absent is **corrected on the next reconcile**, and the state's colour is painted over the corrected icon. A type icon is repairable from its declaration, not written once and frozen.

When no matcher below the state one names an icon either, the note's existing key is kept exactly as it stands and only the colour lands — the repaint is never skipped and the key is never blanked (`iconize_sync._resolve_icon_pair`). Which icon a note gets *in the first place* is still the scaffolding writer's business; what a reconcile does is bring it back in line with the declaration whenever one claims the note.

## 4. Layer composition and ordering

The worker folds all discovered registries under the personal map into one matcher list and evaluates it first-match-wins in this order:

1. Higher `priority` first.
2. On equal priority, the **operator's matcher beats any plugin's**.
3. Between two plugins at equal priority: plugin name, then declaration order — deterministic, but two plugin rules overlapping on the same files at equal priority are a **registry bug**, not a supported layering.

Personal-map matchers without a `priority` default to `1000` — above every band, preserving the pre-layering behavior of existing vaults. The operator opts a personal rule into the band scale by writing an explicit `priority`.

The worker never strips icon keys from a note no matcher claims: sibling plugins write managed `iconize_icon` / `iconize_color` keys of their own, and the absence of a rule is not an instruction to remove them.

## 5. Shipped callbacks

A registry matcher's `callback: <id>` resolves against the vault's `.claude/callbacks/<id>` first — the operator overrides a shipped callback the same way an operator matcher beats a plugin matcher — falling back to the shipping plugin's own `claude/<plugin>/callbacks/<id>` (any language — its first line is a shebang and the worker launches it through that interpreter; the exec bit is never required — stdin/stdout JSON per the iconize protocol), which is what makes registry callbacks work with zero vault setup. Personal-map matchers resolve from the vault directory only.

Both callback ops carry the candidate's vault-relative `path`. A `when` callback receives `{op, path, frontmatter}` and answers `{"match": <bool>}`; a `resolve` callback receives `{op, path, frontmatter, icon_map}` and answers `{"iconName", "iconColor"?}` — or `{}` to decline, which leaves the note unclaimed exactly as an empty resolution does. The `path` is what lets a resolve callback answer from where the note sits (which product owns it, which content root it falls under) rather than from frontmatter alone.

## 6. Registry review checklist

Reviewing a registry (in code review, or in the plugin maintainer's own audit tooling) means checking:

- every matcher's `priority` sits inside the band its signal class belongs to (table above) — a transient process at 550 or a blocker at 250 is a finding;
- no state matcher resolves a literal `iconName` (§ 3a) — a literal is legal only as a type's own icon, carried identically by every matcher of that type;
- no two matchers of the same registry can claim the same file at the same priority;
- `when` predicates key on the plugin's own frontmatter/callbacks, not on vault-specific paths — consumer content roots are configurable, so `path_glob` on a hardcoded root is a finding;
- colors are lowercase `#rgb` / `#rrggbb`; icon names pass the worker's `--validate-entry` shapes;
- callbacks referenced by the registry ship in the plugin's `callbacks/` dir (or are documented as operator-provided).
