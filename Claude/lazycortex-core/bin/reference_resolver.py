"""Resolve agent / protocol references to filesystem paths."""
from __future__ import annotations
from pathlib import Path


class ReferenceError(Exception):
    pass


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
    if ":" in ref:
        scope, name = ref.split(":", 1)
        if scope == "user":
            p = Path.home() / ".claude" / category / f"{name}.md"
        else:
            cache = Path.home() / ".claude/plugins/cache"
            # Real layout: cache/<registry>/<plugin>/<version>/<category>/<name>.md
            # Glob finds all <registry>/<plugin> dirs under any registry prefix.
            plugin_dirs = list(cache.glob(f"*/{scope}"))
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
            p = latest / category / f"{name}.md"
    else:
        p = Path(repo) / ".claude" / category / f"{ref}.md"
    if not p.exists():
        raise ReferenceError(f"{category} not found: {ref} → {p}")
    return p
