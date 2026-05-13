"""lazy.settings.json read/write helper with per-section _version migration ladder."""
from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Any

CURRENT_VERSIONS = {
    "agent_models": 1,
    "daemon": 1,
    "routines": 1,
    "experts": 1,
    "git": 1,
    "review": 1,
}

def _migrations(section_key: str) -> dict[int, callable]:
    mod_name = section_key.replace(".", "_").replace("-", "_")
    try:
        from importlib import import_module
        ladder = import_module(f"lazy_settings_migrations.{mod_name}")
        return ladder.MIGRATIONS  # {from_version: fn}
    except ModuleNotFoundError:
        return {}

def migrate_root_version_to_section_version(raw: dict) -> dict:
    if "version" in raw:
        legacy = raw.pop("version")
        for k, v in raw.items():
            if isinstance(v, dict) and "_version" not in v:
                v["_version"] = legacy
    return raw

def load_section(path: Path | str, section_key: str) -> dict:
    path = Path(path)
    if not path.exists():
        return {"_version": CURRENT_VERSIONS.get(section_key, 1)}
    raw = json.loads(path.read_text() or "{}")
    had_root_version = "version" in raw
    raw = migrate_root_version_to_section_version(raw)
    dirty = had_root_version
    section = raw.get(section_key, {})
    if not section:
        section = {"_version": CURRENT_VERSIONS.get(section_key, 1)}
    cur = section.get("_version", 1)
    target = CURRENT_VERSIONS.get(section_key, cur)
    ladder = _migrations(section_key)
    while cur < target:
        section = ladder[cur](section)
        cur += 1
        section["_version"] = cur
        dirty = True
    raw[section_key] = section
    if dirty:
        _atomic_write(path, raw)
    return section

def migrate_all(path: Path | str) -> dict[str, tuple[int, int]]:
    """Run the migration ladder for every section in CURRENT_VERSIONS.

    Returns {section_key: (before, after)} for sections that were upgraded.
    Sections already at the target version are omitted from the result.
    """
    path = Path(path)
    pre: dict[str, int] = {}
    if path.exists():
        raw = json.loads(path.read_text() or "{}")
        raw = migrate_root_version_to_section_version(raw)
        for k, target in CURRENT_VERSIONS.items():
            sect = raw.get(k) or {}
            pre[k] = sect.get("_version", target)
    else:
        pre = dict(CURRENT_VERSIONS)
    result: dict[str, tuple[int, int]] = {}
    for k, target in CURRENT_VERSIONS.items():
        after = load_section(path, k).get("_version", target)
        if pre[k] != after:
            result[k] = (pre[k], after)
    return result


def save_section(path: Path | str, section_key: str, section: dict) -> None:
    path = Path(path)
    raw = json.loads(path.read_text() or "{}") if path.exists() else {}
    raw = migrate_root_version_to_section_version(raw)
    section.setdefault("_version", CURRENT_VERSIONS.get(section_key, 1))
    raw[section_key] = section
    _atomic_write(path, raw)

def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".lazy_settings_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or sys.argv[1] != "migrate":
        print("usage: lazy_settings.py migrate [path]", file=sys.stderr)
        sys.exit(2)
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".claude/lazy.settings.json")
    upgraded = migrate_all(target)
    total = len(CURRENT_VERSIONS)
    up_to_date = total - len(upgraded)
    if not upgraded:
        print(f"migrated: 0 sections ({up_to_date} up-to-date)")
    else:
        print(f"migrated: {len(upgraded)} sections ({up_to_date} up-to-date)")
        for k, (a, b) in upgraded.items():
            print(f"  {k}: v{a} -> v{b}")
