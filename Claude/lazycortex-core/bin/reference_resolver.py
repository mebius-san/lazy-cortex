"""Resolve agent / protocol references to filesystem paths."""
from __future__ import annotations
import json, os
from pathlib import Path


class ReferenceError(Exception):
    pass


def _dev_plugin_dirs() -> list[Path]:
    """Read `LAZYCORTEX_PLUGIN_DIRS` (set by the runtime daemon's runner from
    its `--plugin-dir` flags). Each entry is a plugin source directory whose
    `.claude-plugin/plugin.json` "name" is matched against the reference's
    plugin scope before the resolver falls back to the plugin cache. Subprocess
    routines inherit this env, so daemon-spawned `lazy-review tick` /
    `expert-pump-once` see the same dev plugins the daemon does."""
    raw = os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "")
    if not raw:
        return []
    return [Path(p) for p in raw.split(os.pathsep) if p]


def _resolve_in_dev_dir(plugin_dir: Path, plugin_name: str, dir_name: str, name: str) -> Path | None:
    """If `plugin_dir`'s manifest `name` matches `plugin_name`, return the
    resolved on-disk path under `<plugin_dir>/<dir_name>/<name>.md`. The
    file's existence is enforced by the caller — match-but-missing is a
    plugin authoring bug and must surface as a hard error rather than be
    silently shadowed by a cache fall-through."""
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if data.get("name") != plugin_name:
        return None
    return plugin_dir / dir_name / f"{name}.md"


def resolve(ref: str, *, category: str, repo: Path) -> Path:
    """Resolve a reference string to a filesystem path.

    Reference forms:
      <plugin>:<name>  — plugin cache: ~/.claude/plugins/cache/<registry>/<plugin>/<version>/<category>/<name>.md
                         picks the version directory that sorts last (latest by string order).
                         NOTE: version comparison is lexicographic, so "2.0.0" > "10.0.0". This
                         mirrors the same limitation in resolve_routine_command in runtime_daemon.py.
      user:<name>      — global ~/.claude/<category>/<name>.md
      <name>           — repo-local .claude/<category>/<name>.md

    category must be one of {'agents', 'protocols'}.
    Raises ReferenceError if the resolved path does not exist.
    """
    # Plugin-shipped protocols live under <plugin-root>/references/ — the
    # repo-wide convention used by every plugin's own protocol/contract docs
    # (lazy-obsidian.iconize-protocol.md, lazy-core.expert-protocols-contract.md,
    # lazy-review.doc-review-protocol.md).
    # Agents stay under <plugin-root>/agents/. Consumer-local resolution
    # (no plugin prefix) keeps the canonical Claude Code shape
    # <repo>/.claude/<category>/<name>.md.
    # All branches map category to the on-disk directory the same way:
    # protocols live in `references/`, agents live in `agents/`. The mapping
    # applies uniformly to plugin-prefixed, user-scope, and bare references.
    plugin_dir_for_category = {"protocols": "references", "agents": "agents"}
    dir_name = plugin_dir_for_category.get(category, category)
    if ":" in ref:
        scope, name = ref.split(":", 1)
        if scope == "user":
            p = Path.home() / ".claude" / dir_name / f"{name}.md"
        else:
            # Dev-plugin paths take precedence over the plugin cache.
            for plugin_dir in _dev_plugin_dirs():
                hit = _resolve_in_dev_dir(plugin_dir, scope, dir_name, name)
                if hit is not None:
                    if not hit.exists():
                        raise ReferenceError(f"{category} not found in dev plugin: {ref} → {hit}")
                    return hit
            cache = Path.home() / ".claude/plugins/cache"
            # Real layout: cache/<registry>/<plugin>/<version>/<dir>/<name>.md.
            # Walk all <registry>/<plugin> dirs under any registry prefix.
            plugin_dirs: list[Path] = []
            if cache.is_dir():
                for registry in cache.iterdir():
                    if not registry.is_dir():
                        continue
                    candidate = registry / scope
                    if candidate.is_dir():
                        plugin_dirs.append(candidate)
            if not plugin_dirs:
                raise ReferenceError(f"plugin not in cache: {scope}")
            # Collect all version subdirectories across matching registry/plugin dirs.
            all_versions = []
            for pd in plugin_dirs:
                all_versions.extend(v for v in pd.iterdir() if v.is_dir())
            if not all_versions:
                raise ReferenceError(f"no versions cached for plugin: {scope}")
            # Pick the latest version by lexicographic sort (consistent with runtime_daemon).
            latest = sorted(all_versions, key=lambda v: v.name, reverse=True)[0]
            p = latest / dir_name / f"{name}.md"
    else:
        p = Path(repo) / ".claude" / dir_name / f"{ref}.md"
    if not p.exists():
        raise ReferenceError(f"{category} not found: {ref} → {p}")
    return p
