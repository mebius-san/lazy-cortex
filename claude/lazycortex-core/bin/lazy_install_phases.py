"""Reusable phases extracted from lazy-core.install for testability.

Each function takes a repo path and is idempotent (safe to call repeatedly).
"""
from __future__ import annotations
import json
import re
from pathlib import Path


def bootstrap_logs_dir(repo: Path | str) -> str:
    """Create .logs/ at the repo root and ensure .gitignore lists it.

    Idempotent: missing dir → created; missing gitignore line → appended;
    existing line → no-op.

    Returns one of:
    - ``"bootstrapped"`` — created the directory and/or appended the gitignore line.
    - ``"already-present"`` — both the directory and the gitignore line already existed; no changes made.
    """
    repo = Path(repo)
    logs_dir = repo / ".logs"
    dir_existed = logs_dir.is_dir()
    logs_dir.mkdir(exist_ok=True)
    dir_created = not dir_existed

    gi_path = repo / ".gitignore"
    existing = gi_path.read_text(encoding="utf-8") if gi_path.exists() else ""
    has_entry = any(
        line.strip() in (".logs", ".logs/")
        for line in existing.splitlines()
    )
    gitignore_appended = False
    if not has_entry:
        suffix = "" if existing.endswith("\n") or not existing else "\n"
        gi_path.write_text(f"{existing}{suffix}.logs/\n", encoding="utf-8")
        gitignore_appended = True

    if dir_created or gitignore_appended:
        return "bootstrapped"
    return "already-present"


_STALE_LOG_HOOK_PATTERN = re.compile(
    r"\$\{CLAUDE_PLUGIN_ROOT\}/lazycortex-log/hooks/"
)


def migrate_log_hooks(settings_path: Path | str) -> str:
    """Strip any hook commands referencing the retired
    `${CLAUDE_PLUGIN_ROOT}/lazycortex-log/hooks/` path from the given
    settings.json. Leaves other hooks alone. Idempotent: a second run
    on already-clean settings is a no-op.

    Returns:
        "migrated" — one or more stale entries were stripped (and possibly
                     emptied matcher blocks dropped, or emptied event lists
                     dropped).
        "no-stale-entries" — file absent OR present but no stale entries
                             matched.
    """
    settings_path = Path(settings_path)
    if not settings_path.exists():
        return "no-stale-entries"

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = settings.get("hooks", {})
    changed = False

    for event in list(hooks.keys()):
        event_entries = hooks.get(event) or []
        new_event_entries = []
        for entry in event_entries:
            kept_hooks = [
                h for h in entry.get("hooks", [])
                if not (isinstance(h, dict)
                        and isinstance(h.get("command"), str)
                        and _STALE_LOG_HOOK_PATTERN.search(h["command"]))
            ]
            if len(kept_hooks) != len(entry.get("hooks", [])):
                changed = True
            if kept_hooks:
                new_event_entries.append({**entry, "hooks": kept_hooks})
            else:
                # matcher block now empty — drop it entirely
                changed = True
        if new_event_entries:
            hooks[event] = new_event_entries
        else:
            del hooks[event]
            changed = True

    if changed:
        settings["hooks"] = hooks
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        return "migrated"
    return "no-stale-entries"


def bootstrap_memory_dir(repo: Path) -> str:
    """Create .memory/ and append `!.memory/` to .gitignore so the
    directory is tracked in git even when a broader pattern would
    ignore it. Returns 'bootstrapped' when either action was taken,
    'already-present' when both already existed."""
    repo = Path(repo)
    mem = repo / ".memory"
    gi = repo / ".gitignore"
    mem_existed = mem.is_dir()
    if not mem_existed:
        mem.mkdir(parents=True, exist_ok=True)
    gi_lines = gi.read_text().splitlines() if gi.exists() else []
    gi_had = any(line.strip() == "!.memory/" for line in gi_lines)
    if not gi_had:
        gi_lines.append("!.memory/")
        gi.write_text("\n".join(gi_lines).rstrip() + "\n")
    if mem_existed and gi_had:
        return "already-present"
    return "bootstrapped"
