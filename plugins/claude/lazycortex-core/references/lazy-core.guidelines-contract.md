---
description: "Meta-spec for the `provides_guidelines` field of a plugin manifest and the `guidelines-resolve` verb that turns a job role into the guideline files the job reads."
---
# Guidelines contract

A plugin may declare, in its own manifest, the guideline files each expert role reads in every repository that enables the plugin: a language plugin declares its canon this way, so the canon reaches every job with no per-repository setting. Plugin authors write the declaration; the guideline collectors of other plugins (the spec dispatchers, the review writer dispatch) read it at dispatch time through one core verb, `guidelines-resolve`, which merges the declarations of every enabled plugin with the entries the caller's own settings declare. Both sides rely on one resolution order, one entry grammar and one warning vocabulary, all defined here.

---

## 1. What a guideline declaration is

A declaration is the optional `provides_guidelines` field of a plugin manifest:

```
<plugin>/.claude-plugin/plugin.json
```

It maps a role name to an ordered list of entries. A role is the free-form label a collector derives for a job (`architect`, `developer`, `reviewer`, …); the field names only the roles the plugin has canon for. A plugin without the field, or without a key for the job's role, contributes nothing and produces no warning.

The same entry grammar applies to the `guidelines` lists a caller reads from its own settings (`spec.guidelines`, `products.<key>.guidelines`, `asset_types.<type>.guidelines` in `lazy.settings.json`), so a settings list may name a plugin's canon by key.

---

## 2. Required structure

### 2.1 Entries

An entry is a string of one of two forms:

- **Reference key** — `<plugin>:<name>`, with exactly one `:`, no `/`, and both halves non-empty. It names `<plugin root>/references/<name>.md` and resolves to that absolute path. The plugin root comes from `plugin_locator.plugin_root(<plugin>, start = <repo>)`, the same four-stage lookup that finds the declaring manifest, so the manifest and the files it names always come from one tree.
- **Repo-relative path** — anything else. A path an enabled plugin provides is checked against the repository root; a path the caller declares is checked against `--base` (the repository root when absent). It stays as written in the answer.

`reference_resolver.resolve` is not used for keys: it has only the env and registry stages, so in a development checkout outside the daemon it would answer from the cached install while the manifest came from the checkout.

### 2.2 Overlay order

A plugin lists each canon file before the project overlay that refines it, because an overlay is read after the canon and overrides it on conflict. An overlay path names a file the plugin's install scaffolds in the consumer repository.

---

## 3. Schema

### 3.1 Manifest field

```json
"provides_guidelines": {
  "<role>": [ "<plugin>:<name>", "<repo-relative path>" ]
}
```

The field is an object; each value is a list of strings. Any other shape makes the manifest unusable for this purpose (§ 3.3).

### 3.2 The `guidelines-resolve` verb

```
"${LAZYCORTEX_PYTHON:-python3}" <core-cli> guidelines-resolve --role <role> [--cwd DIR] [--base DIR]
"${LAZYCORTEX_PYTHON:-python3}" <core-cli> guidelines-resolve --declared-only [--cwd DIR] [--base DIR]
```

`<core-cli>` stands for the core plugin's `bin/lazycortex-core` file — the `installPath` that `~/.claude/plugins/installed_plugins.json` records for `lazycortex-core`, or `plugins/claude/lazycortex-core/` in a checkout that authors the plugin. Every verb runs through the interpreter: the file carries no exec bit and is not on `PATH`.

- `--cwd` — the directory the job's repository is found from; the repository root is `plugin_locator.query_repo_root(--cwd)`.
- `--base` — the directory the caller's declared paths are relative to, such as a nested settings root; absent means the repository root.
- `--declared-only` — resolve the caller's `declared` entries alone: no enabled plugin's `provides_guidelines` is read, so the answer carries no plugin canon and no `guideline plugin not found` / `guideline manifest unreadable` warning, and `--role` is not needed (ignored when given). A caller uses it for a list whose answer belongs to something other than a role, such as `asset_types.<type>.guidelines`, where a key and a path still resolve under § 2.1.
- stdin — one JSON object carrying the caller's entries in the caller's order:

```json
{
  "declared": [ "<entry>" ]
}
```

- stdout — one JSON line, exit 0:

```json
{
  "paths": [ "<absolute canon path or repo-relative path>" ],
  "warnings": [ "<warning>" ]
}
```

- A missing or empty `--role` without `--declared-only`, or stdin that is not an object whose `declared` is a list of strings, prints the error answer and exits 1:

```json
{
  "paths": null,
  "warnings": [],
  "error": "<why>"
}
```

The Python entry point is `guideline_resolver.resolve_guidelines(repo, role, declared, *, base = None, canon = True)`, returning `(paths, warnings)`; `canon = False` is the `--declared-only` mode, with `role` ignored.

### 3.3 Resolution rules

- **Enablement** — a plugin takes part when the repository's own `enabledPlugins` (`.claude/settings.json`, overridden by `.claude/settings.local.json`) switches it on (`lazy_setup.read_enabled_plugins`). The install registry says where a plugin lives, never whether the repository wants it.
- **Order** — the `provides_guidelines[<role>]` entries of the enabled plugins come first, plugins in name order, then the caller's `declared` entries; with `--declared-only` the `declared` entries alone.
- **No repeats** — an entry listed more than once is kept once, at its first position; an entry both a plugin and the caller declare sits at the plugin's position.
- **Existing files only** — `paths` holds only entries that resolve to an existing file.
- **Warnings, never an abort** — each problem is one warning and the rest still resolves:
  - `guideline not found: <entry>` — a path with no file, a key whose reference file is absent, or a key whose plugin no stage locates;
  - `guideline plugin not found: <plugin>` — an enabled plugin no stage locates;
  - `guideline manifest unreadable: <plugin>` — an enabled plugin whose manifest does not parse, or whose `provides_guidelines` (or its entry list for the role) has the wrong shape.

A caller passes every warning on to the place it already reports a missing guideline path (a dispatch result, a `# History` line).

---

## 4. Versioning

The field and the verb are versioned with `lazycortex-core`'s `plugin.json`. Adding a role or an entry to a plugin's declaration is backward compatible. Changing the entry grammar, the order, the wire shape or a warning's wording is incompatible: it ships as a new verb or a new field name, and the old one stays until every collector has moved.

---

## 5. Validation expectations

The resolver itself reports every declaration problem at dispatch time, as the warnings in § 3.3. No audit checks declarations statically yet. The verb's behaviour is pinned by `tests/core/guidelines/test_guideline_resolver.py` in the authoring repository.
