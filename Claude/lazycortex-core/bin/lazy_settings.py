"""lazy.settings.json read/write helper with per-section _version migration ladder."""
from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Any

CURRENT_VERSIONS = {
    "agent_models": 1,
    "lazy-core.runtime": 1,
    "lazy-core.git": 1,
    "lazycortex-review": 1,
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

def migrate_loop_section_to_runtime(raw: dict) -> dict:
    """One-shot rename of legacy `lazy-core.loop` section key to `lazy-core.runtime`.
    Idempotent — second call is a no-op."""
    if "lazy-core.loop" in raw and "lazy-core.runtime" not in raw:
        raw["lazy-core.runtime"] = raw.pop("lazy-core.loop")
    return raw

def load_section(path: Path | str, section_key: str) -> dict:
    path = Path(path)
    if not path.exists():
        return {"_version": CURRENT_VERSIONS.get(section_key, 1)}
    raw = json.loads(path.read_text() or "{}")
    had_root_version = "version" in raw
    raw = migrate_root_version_to_section_version(raw)
    had_loop_key = "lazy-core.loop" in raw
    raw = migrate_loop_section_to_runtime(raw)
    dirty = had_root_version or had_loop_key
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

def save_section(path: Path | str, section_key: str, section: dict) -> None:
    path = Path(path)
    raw = json.loads(path.read_text() or "{}") if path.exists() else {}
    raw = migrate_root_version_to_section_version(raw)
    raw = migrate_loop_section_to_runtime(raw)
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
