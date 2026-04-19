#!/usr/bin/env python3
"""
iconize.py — manipulate the Obsidian Iconize plugin `data.json` safely.

Locates `<vault>/.obsidian/plugins/obsidian-icon-folder/data.json` by walking
up from the current working directory (or an explicit `--vault` root).

Preserves plugin-owned fields (`settings`, `rules`, `recentlyUsedIcons`) and
any other non-path top-level keys. Path-entry values are always written in
long form `{"iconName": "...", "iconColor": "..."}`. Reads tolerate the short
form `"path": "iconName"`.

Exit codes:
    0  success
    1  validation error (bad args, bad color, etc.)
    2  data.json not found / vault not detected
    3  concurrent-write conflict unresolved after retries
    4  target path missing (only when --strict-paths is on)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

PLUGIN_SUBPATH = Path(".obsidian/plugins/obsidian-icon-folder/data.json")
RESERVED_KEYS = {"settings", "rules", "recentlyUsedIcons"}
COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
ICON_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
FM_BLOCK_RE = re.compile(r"(?ms)\A---\s*\n(.*?\n)^---\s*\n")
FM_ICON_KEY_RE = re.compile(r"(?m)^icon\s*:")

RETRIES = 3
RETRY_SLEEP_SEC = 0.05

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_DATAFILE_MISSING = 2
EXIT_CONCURRENT = 3
EXIT_TARGET_MISSING = 4


class IconizeError(Exception):
    def __init__(self, message: str, code: int = EXIT_VALIDATION):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Locate vault + data.json
# ---------------------------------------------------------------------------

def find_vault_and_data(vault_override: str | None) -> tuple[Path, Path]:
    if vault_override:
        vault = Path(vault_override).expanduser().resolve()
        if not (vault / ".obsidian").is_dir():
            raise IconizeError(
                f"vault override has no .obsidian/: {vault}",
                EXIT_DATAFILE_MISSING,
            )
    else:
        vault = _walk_up_for_vault(Path.cwd().resolve())
        if vault is None:
            raise IconizeError(
                "vault not found: no .obsidian/ in cwd or parents",
                EXIT_DATAFILE_MISSING,
            )
    data_path = vault / PLUGIN_SUBPATH
    if not data_path.exists():
        raise IconizeError(
            f"iconize data.json not found at {data_path} "
            "(is the obsidian-icon-folder plugin installed?)",
            EXIT_DATAFILE_MISSING,
        )
    return vault, data_path


def _walk_up_for_vault(start: Path) -> Path | None:
    current = start
    while True:
        if (current / ".obsidian").is_dir():
            return current
        if current == current.parent:
            return None
        current = current.parent


# ---------------------------------------------------------------------------
# Read / write with concurrent-mutation guard
# ---------------------------------------------------------------------------

def load_data(data_path: Path) -> tuple[dict, int]:
    raw = data_path.read_text(encoding="utf-8")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise IconizeError(f"data.json is not valid JSON: {e}", EXIT_VALIDATION)
    if not isinstance(obj, dict):
        raise IconizeError("data.json top-level must be an object", EXIT_VALIDATION)
    return obj, data_path.stat().st_mtime_ns


def dump_data(data_path: Path, obj: dict, expected_mtime: int) -> None:
    if data_path.stat().st_mtime_ns != expected_mtime:
        raise IconizeError(
            "data.json changed between read and write", EXIT_CONCURRENT
        )
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    data_path.write_text(text, encoding="utf-8")


def with_retry(data_path: Path, mutate_fn) -> dict:
    """`mutate_fn(data: dict) -> dict` (returns the new full top-level object)."""
    last_error: IconizeError | None = None
    for attempt in range(RETRIES):
        data, mtime = load_data(data_path)
        new_data = mutate_fn(data)
        try:
            dump_data(data_path, new_data, mtime)
            return new_data
        except IconizeError as exc:
            if exc.code != EXIT_CONCURRENT:
                raise
            last_error = exc
            time.sleep(RETRY_SLEEP_SEC * (attempt + 1))
    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_color(color: str) -> None:
    if not COLOR_RE.match(color):
        raise IconizeError(f"invalid color: {color!r} (want #rgb or #rrggbb)")


def validate_icon_name(name: str) -> None:
    if not name or name.strip() != name:
        raise IconizeError(f"iconName is empty or has leading/trailing whitespace: {name!r}")
    if any(ch.isspace() for ch in name):
        raise IconizeError(f"iconName contains whitespace: {name!r}")
    if ICON_NAME_RE.match(name):
        return
    # allow short non-ASCII (emoji grapheme etc.)
    if len(name) <= 8:
        return
    raise IconizeError(f"iconName not recognized: {name!r}")


def normalize_path(path: str) -> str:
    if not path:
        raise IconizeError("path is empty")
    if path.startswith("/"):
        raise IconizeError(f"path must be vault-relative (no leading /): {path!r}")
    if path.startswith("./"):
        path = path[2:]
    if path.endswith("/"):
        path = path.rstrip("/")
    return path


def build_entry(icon_name: str, icon_color: str | None) -> dict:
    validate_icon_name(icon_name)
    entry: dict = {"iconName": icon_name}
    if icon_color:
        validate_color(icon_color)
        entry["iconColor"] = icon_color
    return entry


# ---------------------------------------------------------------------------
# Frontmatter-conflict warning for .md files
# ---------------------------------------------------------------------------

def warn_if_frontmatter_conflict(vault: Path, path: str, data: dict) -> str | None:
    settings = data.get("settings")
    if not isinstance(settings, dict):
        return None
    if not settings.get("iconInFrontmatterEnabled"):
        return None
    if not path.endswith(".md"):
        return None
    target = vault / path
    if not target.is_file():
        return None
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = FM_BLOCK_RE.match(text)
    if not match:
        return None
    field_name = settings.get("iconInFrontmatterFieldName", "icon")
    key_re = re.compile(rf"(?m)^{re.escape(field_name)}\s*:")
    if key_re.search(match.group(1)):
        return (
            f"WARN: {path} has `{field_name}:` frontmatter — the plugin will "
            "overwrite this data.json entry on next sweep; consider writing to "
            "frontmatter instead"
        )
    return None


# ---------------------------------------------------------------------------
# Target existence check
# ---------------------------------------------------------------------------

def warn_if_target_missing(vault: Path, path: str) -> str | None:
    target = vault / path
    if not target.exists():
        return f"WARN: target does not exist on disk: {path} (plugin will prune on next sweep)"
    return None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def apply_set(data: dict, path: str, entry: dict) -> dict:
    path = normalize_path(path)
    data[path] = entry
    return data


def apply_clear(data: dict, path: str) -> dict:
    path = normalize_path(path)
    if path in RESERVED_KEYS:
        raise IconizeError(f"refusing to clear reserved top-level key: {path!r}")
    data.pop(path, None)
    return data


def iter_path_entries(data: dict):
    """Yield (path, entry-dict) for every non-reserved top-level key, normalizing short-form."""
    for key, value in data.items():
        if key in RESERVED_KEYS:
            continue
        if isinstance(value, str):
            yield key, {"iconName": value}
        elif isinstance(value, dict):
            yield key, value
        else:
            # unknown shape; leave alone
            continue


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_set(args) -> int:
    vault, data_path = find_vault_and_data(args.vault)

    if args.file:
        policy = _load_policy(args.file)
        warnings: list[str] = []

        def mutate(data: dict) -> dict:
            for item in policy:
                path = normalize_path(item["path"])
                entry = build_entry(item["iconName"], item.get("iconColor"))
                if args.strict_paths:
                    if not (vault / path).exists():
                        raise IconizeError(
                            f"target missing (strict): {path}", EXIT_TARGET_MISSING
                        )
                else:
                    w = warn_if_target_missing(vault, path)
                    if w:
                        warnings.append(w)
                fw = warn_if_frontmatter_conflict(vault, path, data)
                if fw:
                    warnings.append(fw)
                data[path] = entry
            return data

        if args.dry_run:
            _preview_bulk(vault, data_path, policy, strict=args.strict_paths)
            return EXIT_OK
        with_retry(data_path, mutate)
        for w in warnings:
            print(w, file=sys.stderr)
        _report({"op": "set-bulk", "count": len(policy), "file": args.file})
        return EXIT_OK

    if not args.path or not args.iconName:
        raise IconizeError("usage: set <path> <iconName> [--color HEX]  OR  set --file POLICY")

    path = normalize_path(args.path)
    entry = build_entry(args.iconName, args.color)
    if args.strict_paths and not (vault / path).exists():
        raise IconizeError(f"target missing (strict): {path}", EXIT_TARGET_MISSING)
    warnings = []
    if not (vault / path).exists():
        w = warn_if_target_missing(vault, path)
        if w:
            warnings.append(w)

    def mutate(data: dict) -> dict:
        fw = warn_if_frontmatter_conflict(vault, path, data)
        if fw:
            warnings.append(fw)
        return apply_set(data, path, entry)

    if args.dry_run:
        _preview_single(vault, data_path, path, entry)
        return EXIT_OK
    with_retry(data_path, mutate)
    for w in warnings:
        print(w, file=sys.stderr)
    _report({"op": "set", "path": path, "entry": entry})
    return EXIT_OK


def cmd_set_folder(args) -> int:
    vault, data_path = find_vault_and_data(args.vault)
    path = normalize_path(args.path)
    entry = build_entry(args.iconName, args.color)

    note_path: str | None = None
    if args.also_folder_note is not None:
        filename = args.also_folder_note or "_folder.md"
        note_path = f"{path}/{filename}"

    warnings = []
    if not (vault / path).exists():
        w = warn_if_target_missing(vault, path)
        if w:
            warnings.append(w)
    if note_path and not (vault / note_path).exists():
        w = warn_if_target_missing(vault, note_path)
        if w:
            warnings.append(w)

    def mutate(data: dict) -> dict:
        data[path] = entry
        if note_path:
            data[note_path] = dict(entry)  # copy
        return data

    if args.dry_run:
        preview = {path: entry}
        if note_path:
            preview[note_path] = entry
        _preview_map(vault, data_path, preview)
        return EXIT_OK
    with_retry(data_path, mutate)
    for w in warnings:
        print(w, file=sys.stderr)
    result = {"op": "set-folder", "path": path, "entry": entry}
    if note_path:
        result["folder_note"] = note_path
    _report(result)
    return EXIT_OK


def cmd_clear(args) -> int:
    _vault, data_path = find_vault_and_data(args.vault)
    path = normalize_path(args.path)

    def mutate(data: dict) -> dict:
        return apply_clear(data, path)

    if args.dry_run:
        data, _ = load_data(data_path)
        existed = path in data and path not in RESERVED_KEYS
        _report({"op": "clear", "path": path, "dry_run": True, "existed": existed})
        return EXIT_OK
    with_retry(data_path, mutate)
    _report({"op": "clear", "path": path})
    return EXIT_OK


def cmd_get(args) -> int:
    _vault, data_path = find_vault_and_data(args.vault)
    path = normalize_path(args.path)
    data, _ = load_data(data_path)
    value = data.get(path)
    if value is None or path in RESERVED_KEYS:
        # empty stdout + exit 0 signifies "no entry"
        return EXIT_OK
    if isinstance(value, str):
        value = {"iconName": value}
    print(json.dumps(value, ensure_ascii=False))
    return EXIT_OK


def cmd_list(args) -> int:
    _vault, data_path = find_vault_and_data(args.vault)
    data, _ = load_data(data_path)
    prefix = normalize_path(args.prefix) if args.prefix else ""
    out: dict[str, dict] = {}
    for key, entry in iter_path_entries(data):
        if prefix and not (key == prefix or key.startswith(prefix + "/")):
            continue
        out[key] = entry
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_reconcile(args) -> int:
    vault, data_path = find_vault_and_data(args.vault)
    policy = _load_policy(args.declared)
    prefix = normalize_path(args.prefix) if args.prefix else ""
    declared: dict[str, dict] = {}
    for item in policy:
        declared[normalize_path(item["path"])] = build_entry(
            item["iconName"], item.get("iconColor")
        )

    def mutate(data: dict) -> dict:
        # drop unknown within prefix
        for key in list(data.keys()):
            if key in RESERVED_KEYS:
                continue
            in_subtree = (not prefix) or key == prefix or key.startswith(prefix + "/")
            if in_subtree and key not in declared:
                del data[key]
        # add/update declared within prefix
        for key, entry in declared.items():
            in_subtree = (not prefix) or key == prefix or key.startswith(prefix + "/")
            if in_subtree:
                data[key] = entry
        return data

    warnings = []
    for key in declared:
        if not (vault / key).exists():
            warnings.append(
                f"WARN: declared target missing on disk: {key} (plugin will prune)"
            )

    if args.dry_run:
        data, _ = load_data(data_path)
        plan = {
            "add_or_update": sorted(
                k for k in declared if data.get(k) != declared[k]
            ),
            "drop": sorted(
                key for key, _ in iter_path_entries(data)
                if ((not prefix) or key == prefix or key.startswith(prefix + "/"))
                and key not in declared
            ),
        }
        _report({"op": "reconcile", "dry_run": True, "prefix": prefix, **plan})
        return EXIT_OK
    with_retry(data_path, mutate)
    for w in warnings:
        print(w, file=sys.stderr)
    _report(
        {
            "op": "reconcile",
            "prefix": prefix,
            "declared": len(declared),
        }
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_policy(path: str) -> list[dict]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise IconizeError(f"policy file not readable: {path}: {e}")
    try:
        arr = json.loads(raw)
    except json.JSONDecodeError as e:
        raise IconizeError(f"policy file is not valid JSON: {path}: {e}")
    if not isinstance(arr, list):
        raise IconizeError(f"policy file must be a JSON array: {path}")
    for i, item in enumerate(arr):
        if not isinstance(item, dict) or "path" not in item or "iconName" not in item:
            raise IconizeError(
                f"policy item {i} must have keys 'path' and 'iconName': {item!r}"
            )
    return arr


def _preview_single(vault: Path, data_path: Path, path: str, entry: dict) -> None:
    data, _ = load_data(data_path)
    before = data.get(path)
    _report({"op": "set", "dry_run": True, "path": path, "before": before, "after": entry})


def _preview_bulk(vault: Path, data_path: Path, policy: list[dict], strict: bool) -> None:
    data, _ = load_data(data_path)
    changes = []
    for item in policy:
        path = normalize_path(item["path"])
        entry = build_entry(item["iconName"], item.get("iconColor"))
        changes.append(
            {"path": path, "before": data.get(path), "after": entry}
        )
    _report({"op": "set-bulk", "dry_run": True, "strict_paths": strict, "changes": changes})


def _preview_map(vault: Path, data_path: Path, preview: dict[str, dict]) -> None:
    data, _ = load_data(data_path)
    changes = []
    for path, entry in preview.items():
        changes.append(
            {"path": path, "before": data.get(path), "after": entry}
        )
    _report({"op": "set-folder", "dry_run": True, "changes": changes})


def _report(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Safely edit the Obsidian Iconize plugin data.json."
    )
    p.add_argument("--vault", help="vault root (default: walk up from cwd)")
    p.add_argument("--dry-run", action="store_true", help="print plan, no writes")
    p.add_argument(
        "--strict-paths",
        action="store_true",
        help="error out if any target path is missing on disk (default: warn only)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("set", help="set an icon on a path (or bulk via --file)")
    s.add_argument("path", nargs="?")
    s.add_argument("iconName", nargs="?")
    s.add_argument("--color", help="hex color like #fed7aa or #fab")
    s.add_argument("--file", help="bulk-apply a JSON array of {path, iconName, iconColor?}")
    s.set_defaults(func=cmd_set)

    sf = sub.add_parser(
        "set-folder", help="set an icon on a folder; optional --also-folder-note"
    )
    sf.add_argument("path")
    sf.add_argument("iconName")
    sf.add_argument("--color")
    sf.add_argument(
        "--also-folder-note",
        nargs="?",
        const="_folder.md",
        default=None,
        metavar="FILENAME",
        help="also set the same icon on <path>/<FILENAME> (default _folder.md)",
    )
    sf.set_defaults(func=cmd_set_folder)

    c = sub.add_parser("clear", help="remove an icon entry")
    c.add_argument("path")
    c.set_defaults(func=cmd_clear)

    g = sub.add_parser("get", help="print the icon entry for a path (empty if none)")
    g.add_argument("path")
    g.set_defaults(func=cmd_get)

    l = sub.add_parser("list", help="print all icon entries, optionally filtered by prefix")
    l.add_argument("--prefix")
    l.set_defaults(func=cmd_list)

    r = sub.add_parser("reconcile", help="add-missing + drop-unknown within a subtree")
    r.add_argument("--declared", required=True, help="policy file (JSON array)")
    r.add_argument("--prefix", help="limit reconciliation to a subtree")
    r.set_defaults(func=cmd_reconcile)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except IconizeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
