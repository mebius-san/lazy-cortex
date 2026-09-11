---
description: Schema reference for `lazy.settings.json` consumers — section ownership, per-section `_version` invariant, helper module, and the migration ladder.
---
# lazy-core.settings

Architecture reference for `lazy.settings.json` consumers. Audience: plugin authors who need to read or write settings from their own code.

---

## 1. The helper module

```python
from lazy_settings import load_section, save_section
```

The helper lives in `claude/lazycortex-core/bin/lazy_settings.py`. Consumers must add that directory to `sys.path` before importing.

**In skill prose** (inline `python3 -c` invocations):

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import load_section, save_section
# ...
"
```

**In hook scripts** (file-based Python):

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))
from lazy_settings import load_section, save_section
```

`CLAUDE_PLUGIN_ROOT` resolves to the lazycortex-core plugin cache dir at runtime. Hook scripts typically know their own location via `__file__` and walk up to `bin/`.

---

## 2. Per-section `_version` invariant

A **versioned** section is a flat top-level key whose dict carries an `_version: int` field. `load_section(path, "<key>")` reads each section directly off the top-level JSON. Example:

```json
{
  "daemon": {
    "_version": 4,
    "git": { ... },
    "polling_interval_sec": 5,
    "stream_idle_timeout_sec": 900,
    "stream_max_retries": 3
  },
  "routines": {
    "_version": 7,
    "lazy-expert.pump": { ... }
  },
  "external_dirs": {
    "_version": 1,
    "paths": [ ... ]
  }
}
```

Sections are **owned by individual plugins** and migrate independently. There is no global settings version — the root `version` field is legacy (written by pre-A1 code). On first `load_section` call, any root `version` present is migrated to per-section `_version` on all existing sections, then the root key is removed. This migration is automatic and transparent.

**Which sections are versioned.** Only the keys listed in `CURRENT_VERSIONS` (`bin/lazy_settings.py`) — `migrate_all` iterates that constant and nothing else, so a key absent from it is never stamped with an `_version` on disk and can never acquire a migration ladder. `load_section` itself is indifferent: it reads and merges any top-level key it is handed, versioned or not. Two live sections are read that way without appearing in the constant:

| Key | Read by | Shape |
|---|---|---|
| `providers` | `provider_env.resolve_provider` | `{<name>: {base_url, token_env, models}}` — see `lazy-core.expert-runtime-schema` § Providers |
| `hooks` | `hook_gate` | `{disabled: [<hook short name>, ...]}` — see `lazy-core.expert-runtime-schema` § Lazycortex hooks |

A third root key is not a section at all: `language` is a bare string (`"language": "ru"`), read straight off the parsed JSON document by consumer plugins (`lazycortex-specs`' language chain, `lazycortex-review`'s history explainers) and never through `load_section`. The `_version` invariant does not reach it.

---

## 3. Migration ladder filesystem layout

Migrations live at:

```
bin/lazy_settings_migrations/<section_module>.py
```

Section key → module name translation: dots and hyphens become underscores.

| Section key | Module name |
|---|---|
| `daemon` | `daemon` |
| `agent_models` | `agent_models` |
| `my-plugin.state` | `my_plugin_state` |

Each module exports a single dict:

```python
# bin/lazy_settings_migrations/daemon.py
MIGRATIONS = {}  # {from_version: callable}
```

When a migration exists, the callable receives the current section dict and returns the updated dict. The helper increments `_version` after each step and writes back atomically. If no migrations are needed yet, `MIGRATIONS = {}` is the correct empty declaration.

The helper discovers migration modules via `importlib.import_module`. A `ModuleNotFoundError` is treated as an empty ladder (no migrations defined), so new plugins do not need a migrations file until they have their first schema change.

---

## 4. Idempotency on read

`load_section` is safe to call repeatedly. It only writes back to disk if a migration actually fired:

- A root `version` field was migrated to per-section `_version`, **or**
- The section's `_version` was below `CURRENT_VERSIONS[section_key]` and a migration step ran.

Otherwise the call is a pure read — no write, no lock, no side effect.

---

## 5. Atomic write semantics

All writes (both `load_section` migration write-back and `save_section`) go through `_atomic_write`:

1. `tempfile.mkstemp(dir=<same directory as target>)` — ensures the temp file is on the same filesystem.
2. Write the full JSON document to the temp file.
3. `os.replace(tmp, target)` — atomic rename on POSIX; concurrent readers see either the old file or the new file, never partial content.
4. On any exception, the temp file is unlinked before re-raising.

The same-directory temp file is critical: `os.replace` is only atomic when source and destination are on the same filesystem. Placing the temp file elsewhere (e.g. `/tmp`) would break this guarantee on systems where home is a separate mount.
