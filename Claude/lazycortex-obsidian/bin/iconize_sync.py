#!/usr/bin/env python3
"""Generic iconize-sync worker. See Claude/lazycortex-obsidian/references/iconize-protocol.md."""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path, PurePosixPath

PROTOCOL_VERSION = "1.0.0"
HOOK_VERSION = "1.0.0"

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_DATAFILE_MISSING = 2
EXIT_CONCURRENT = 3
EXIT_TARGET_MISSING = 4
EXIT_VERSION_DRIFT = 5

# ---------------------------------------------------------------------------
# Vault discovery + data.json I/O
# ---------------------------------------------------------------------------

PLUGIN_SUBPATH = Path(".obsidian/plugins/obsidian-icon-folder/data.json")
RESERVED_KEYS = {"settings", "rules", "recentlyUsedIcons"}
RETRIES = 3
RETRY_SLEEP_SEC = 0.05

CALLBACK_DIR_OVERRIDE = None  # Tests override this; prod: None → <vault>/.claude/callbacks
_CALLBACK_VAULT_CACHE = None


class IconizeError(Exception):
    def __init__(self, message: str, code: int = EXIT_VALIDATION):
        super().__init__(message)
        self.code = code


def find_vault_walk_up(start: Path) -> Path | None:
    """Walk up from `start`, returning the first ancestor directory that has `.obsidian/`."""
    cur = Path(os.path.abspath(start))
    while True:
        if (cur / ".obsidian").is_dir():
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent


def find_vault(override: str | None) -> Path:
    """Return the vault root. If `override` is given it must contain `.obsidian/`."""
    if override:
        v = Path(os.path.abspath(Path(override).expanduser()))
        if not (v / ".obsidian").is_dir():
            raise IconizeError(
                f"vault override has no .obsidian/: {v}", EXIT_DATAFILE_MISSING
            )
        return v
    v = find_vault_walk_up(Path.cwd())
    if v is None:
        raise IconizeError(
            "vault not found: no .obsidian/ in cwd or parents", EXIT_DATAFILE_MISSING
        )
    return v


def find_data_path(vault: Path) -> Path:
    """Return the path to `data.json`; raise IconizeError(EXIT_DATAFILE_MISSING) if absent."""
    dp = vault / PLUGIN_SUBPATH
    if not dp.exists():
        raise IconizeError(
            f"Iconize data.json not found at {dp}", EXIT_DATAFILE_MISSING
        )
    return dp


def load_data(path: Path) -> tuple[dict, int]:
    """Read and parse `data.json`. Returns `(obj, mtime_ns)`."""
    raw = path.read_text(encoding="utf-8")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise IconizeError(f"data.json invalid JSON: {e}", EXIT_VALIDATION) from e
    if not isinstance(obj, dict):
        raise IconizeError("data.json top-level must be object", EXIT_VALIDATION)
    return obj, path.stat().st_mtime_ns


def dump_data(path: Path, obj: dict, expected_mtime: int) -> None:
    """Write `obj` to `path` as JSON atomically, raising IconizeError(EXIT_CONCURRENT) if mtime drifted."""
    if path.stat().st_mtime_ns != expected_mtime:
        raise IconizeError(
            "data.json changed between read and write", EXIT_CONCURRENT
        )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def with_retry(path: Path, mutate_fn, retries: int = RETRIES, sleep: float = RETRY_SLEEP_SEC):
    """Load → mutate → dump, retrying on EXIT_CONCURRENT up to `retries` times."""
    last = None
    for attempt in range(retries):
        data, mtime = load_data(path)
        new_data = mutate_fn(data)
        try:
            dump_data(path, new_data, mtime)
            return new_data
        except IconizeError as e:
            if e.code != EXIT_CONCURRENT:
                raise
            last = e
            time.sleep(sleep * (attempt + 1))
    assert last is not None
    raise last


# ---------------------------------------------------------------------------
# Frontmatter parser + entry validators
# ---------------------------------------------------------------------------

FM_BLOCK_RE = re.compile(r"(?ms)\A---\s*\n(.*?\n)^---\s*\n")
COLOR_RE = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$")  # lowercase only
ICON_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def parse_frontmatter(text: str) -> dict:
    """Minimal YAML-subset frontmatter parser — flat key:value only.
    Supports: string (quoted or bare), bool (true/false), int (digit-only). No nested structures."""
    m = FM_BLOCK_RE.match(text)
    if not m: return {}
    out: dict = {}
    for line in m.group(1).splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"): continue
        if ":" not in line: continue
        k, _, v = line.partition(":")
        k = k.strip(); v = v.strip()
        if not k: continue
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            out[k] = v[1:-1]
        elif v == "true": out[k] = True
        elif v == "false": out[k] = False
        elif v.lstrip("-").isdigit(): out[k] = int(v)
        else: out[k] = v
    return out


def normalize_path(p: str) -> str:
    if not p: raise IconizeError("path is empty")
    if p.startswith("/"): raise IconizeError(f"path must be vault-relative: {p!r}")
    if p.startswith("~"): raise IconizeError(f"path must be vault-relative, not home-relative: {p!r}")
    if "\\" in p: raise IconizeError(f"path must use POSIX separators: {p!r}")
    if p.startswith("./"): p = p[2:]
    p = p.rstrip("/")
    if not p: raise IconizeError("path is empty after normalization")
    return p


def validate_color(c: str) -> None:
    if not COLOR_RE.match(c):
        raise IconizeError(f"invalid color {c!r} (want lowercase #rgb or #rrggbb)")


def validate_icon_name(name: str) -> None:
    if not name or name.strip() != name or any(ch.isspace() for ch in name):
        raise IconizeError(f"invalid iconName {name!r}")
    if ICON_NAME_RE.match(name): return
    if len(name) <= 8: return  # short emoji grapheme
    raise IconizeError(f"iconName not recognized: {name!r}")


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that exits with EXIT_VALIDATION (1) on usage errors."""

    def error(self, message):  # pragma: no cover - exercised via subprocess
        self.print_usage(sys.stderr)
        self.exit(EXIT_VALIDATION, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="iconize_sync", description="Obsidian iconize-sync worker.")
    p.add_argument("--version", action="store_true", help="print protocol_version and hook_version")
    p.add_argument("--validate-entry", action="store_true",
                   help="read {iconName, iconColor?} JSON from stdin; exit 0 if valid")
    p.add_argument("--vault", help="vault root (default: walk up from cwd)")
    p.add_argument("--icon-map", help="path to icon-map.json (default: <repo>/.claude/obsidian-iconize/icon-map.json)")
    p.add_argument("--dry-run", action="store_true")
    sub = p.add_subparsers(dest="cmd", parser_class=_Parser)
    for name in ("sync", "sync-staged", "reconcile", "install-hooks", "check-versions"):
        sp = sub.add_parser(name)
        if name == "sync":
            sp.add_argument("path", help="file path relative to vault root")
        if name == "reconcile":
            sp.add_argument("--prefix", help="only reconcile entries whose path starts with this prefix")
    return p


def _resolve_icon_map_path(vault: Path, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    # Walk up from vault to find a .claude/obsidian-iconize/icon-map.json (repo root may be above vault).
    # Resolve symlinks once at entry so the walk crosses filesystem boundaries correctly.
    cur = vault.resolve()
    while True:
        cand = cur / ".claude" / "obsidian-iconize" / "icon-map.json"
        if cand.exists():
            return cand
        if cur == cur.parent:
            break
        cur = cur.parent
    raise IconizeError(
        "icon-map.json not found; run lazy-obsidian.iconize-install first", EXIT_VALIDATION)


def _read_frontmatter_for(vault: Path, vault_rel: str) -> dict:
    p = vault / vault_rel
    if not p.is_file():
        return {}
    return parse_frontmatter(p.read_text(encoding="utf-8", errors="ignore"))


def cmd_sync(args) -> int:
    vault = find_vault(args.vault)
    data_path = find_data_path(vault)
    icon_map = load_icon_map(_resolve_icon_map_path(vault, args.icon_map))
    rel = normalize_path(args.path)
    fm = _read_frontmatter_for(vault, rel)
    entries = resolve_matchers(icon_map, rel, fm)
    if args.dry_run:
        print(json.dumps({"op": "sync", "dry_run": True, "path": rel, "entries": entries}, ensure_ascii=False))
        return EXIT_OK
    if not entries:
        print(json.dumps({"op": "sync", "path": rel, "entries": []}, ensure_ascii=False))
        return EXIT_OK
    def mutate(d):
        for p, entry in entries:
            d[p] = entry
        return d
    with_retry(data_path, mutate)
    print(json.dumps({"op": "sync", "path": rel, "entries": entries}, ensure_ascii=False))
    return EXIT_OK


def _staged_md_files(vault: Path) -> list[str]:
    # --diff-filter=ACMR covers Added/Copied/Modified/Renamed. Deletions are not
    # handled here; stale entries for deleted files get cleaned up by `reconcile`.
    r = subprocess.run(
        ["git", "-C", str(vault), "diff", "--cached", "--name-only",
         "--diff-filter=ACMR", "--", "*.md"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise IconizeError(f"git failed: {r.stderr.strip()}", EXIT_VALIDATION)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def cmd_sync_staged(args) -> int:
    vault = find_vault(args.vault)
    data_path = find_data_path(vault)
    icon_map = load_icon_map(_resolve_icon_map_path(vault, args.icon_map))
    all_entries: list = []
    for rel in _staged_md_files(vault):
        fm = _read_frontmatter_for(vault, rel)
        all_entries.extend(resolve_matchers(icon_map, rel, fm))
    if args.dry_run:
        print(json.dumps({"op": "sync-staged", "dry_run": True, "entries": all_entries},
                         ensure_ascii=False))
        return EXIT_OK
    if not all_entries:
        return EXIT_OK
    def mutate(d):
        for p, entry in all_entries:
            d[p] = entry
        return d
    with_retry(data_path, mutate)
    # Re-stage data.json so the commit includes our write.
    rs = subprocess.run(["git", "-C", str(vault), "add",
                         ".obsidian/plugins/obsidian-icon-folder/data.json"],
                        capture_output=True, text=True)
    if rs.returncode != 0:
        sys.stderr.write(f"warning: re-stage of data.json failed: {rs.stderr.strip()}\n")
    return EXIT_OK


def _walk_md_files(vault: Path, prefix: str | None) -> list[str]:
    root = vault / prefix if prefix else vault
    if not root.exists(): return []
    out: list[str] = []
    for p in root.rglob("*.md"):
        # Skip .obsidian/, .git/, .claude/, .githooks/ at any depth
        rel_parts = p.relative_to(vault).parts
        if any(part in (".obsidian", ".git", ".claude", ".githooks") for part in rel_parts):
            continue
        out.append("/".join(rel_parts))
    return out


def cmd_reconcile(args) -> int:
    vault = find_vault(args.vault)
    data_path = find_data_path(vault)
    icon_map = load_icon_map(_resolve_icon_map_path(vault, args.icon_map))
    prefix = normalize_path(args.prefix) if args.prefix else ""
    # Build desired entries
    desired: dict[str, dict] = {}
    for rel in _walk_md_files(vault, prefix or None):
        fm = _read_frontmatter_for(vault, rel)
        for p, entry in resolve_matchers(icon_map, rel, fm):
            desired[p] = entry

    def in_prefix(k: str) -> bool:
        if not prefix: return True
        return k == prefix or k.startswith(prefix + "/")

    def mutate(d):
        # Drop stale in-prefix path-keys that aren't desired
        for k in list(d.keys()):
            if k in RESERVED_KEYS: continue
            if in_prefix(k) and k not in desired:
                del d[k]
        # Add/update desired
        for k, entry in desired.items(): d[k] = entry
        return d

    if args.dry_run:
        cur, _ = load_data(data_path)
        plan = {
            "op": "reconcile", "dry_run": True, "prefix": prefix,
            "add_or_update": sorted(k for k in desired if cur.get(k) != desired[k]),
            "drop": sorted(k for k in cur
                           if k not in RESERVED_KEYS and in_prefix(k) and k not in desired),
        }
        print(json.dumps(plan, ensure_ascii=False)); return EXIT_OK
    with_retry(data_path, mutate)
    print(json.dumps({"op": "reconcile", "prefix": prefix, "declared": len(desired)},
                     ensure_ascii=False))
    return EXIT_OK


# ---------------------------------------------------------------------------
# Hook version management — install-hooks + check-versions
# ---------------------------------------------------------------------------

HOOK_VERSION_RE = re.compile(r"HOOK_VERSION:\s*(\d+)\.(\d+)\.(\d+)")


def _plugin_root() -> Path:
    """Plugin root resolved from this file's on-disk location."""
    return Path(__file__).resolve().parents[1]


def _plugin_bin_path() -> Path:
    return _plugin_root() / "bin"


def _template_path(name: str) -> Path:
    return _plugin_root() / "templates" / "obsidian-iconize" / name


def _render_shim() -> str:
    tpl = _template_path("pre-commit-shim.sh").read_text(encoding="utf-8")
    return tpl.replace("{{PLUGIN_BIN_PATH}}", str(_plugin_bin_path()))


def _render_post_tool_use_snippet() -> dict:
    tpl = _template_path("post-tool-use.snippet.json").read_text(encoding="utf-8")
    # JSON-escape the path so `"` or `\` in a plugin path cannot break json.loads.
    escaped = json.dumps(str(_plugin_bin_path()))[1:-1]
    rendered = tpl.replace("{{PLUGIN_BIN_PATH}}", escaped)
    return json.loads(rendered)


def _parse_hook_version(text: str) -> tuple[int, int, int] | None:
    m = HOOK_VERSION_RE.search(text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _current_version() -> tuple[int, int, int]:
    v = _parse_hook_version(f"HOOK_VERSION: {HOOK_VERSION}")
    assert v is not None
    return v


def _shim_installed_version(vault: Path) -> tuple[int, int, int] | None:
    shim = vault / ".githooks" / "pre-commit"
    if not shim.is_file():
        return None
    return _parse_hook_version(shim.read_text(encoding="utf-8", errors="ignore"))


def _post_tool_use_installed_version(vault: Path) -> tuple[int, int, int] | None:
    settings_path = vault / ".claude" / "settings.json"
    if not settings_path.is_file():
        return None
    try:
        s = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(s, dict):
        return None
    hooks = s.get("hooks")
    if not isinstance(hooks, dict):
        return None
    post = hooks.get("PostToolUse")
    if not isinstance(post, list):
        return None
    for group in post:
        if not isinstance(group, dict):
            continue
        for h in group.get("hooks", []) or []:
            if not isinstance(h, dict):
                continue
            cmd = h.get("command", "")
            if isinstance(cmd, str) and "iconize_sync.py" in cmd:
                v = _parse_hook_version(cmd)
                if v is not None:
                    return v
    return None


def _is_iconize_sync_post_tool_use_group(group: dict) -> bool:
    """True if a PostToolUse group is an iconize_sync entry (for replacement)."""
    if not isinstance(group, dict):
        return False
    for h in group.get("hooks", []) or []:
        if isinstance(h, dict) and "iconize_sync.py" in (h.get("command") or ""):
            return True
    return False


def _install_shim(vault: Path) -> Path:
    hooks_dir = vault / ".githooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    shim = hooks_dir / "pre-commit"
    shim.write_text(_render_shim(), encoding="utf-8")
    shim.chmod(0o755)
    return shim


def _install_post_tool_use(vault: Path) -> Path:
    claude_dir = vault / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.json"
    settings: dict = {}
    if settings_path.exists():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except json.JSONDecodeError:
            settings = {}  # defensive: malformed → reset
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    post_list = hooks.get("PostToolUse")
    if not isinstance(post_list, list):
        post_list = []
    # Strip any prior iconize_sync entries so re-install is idempotent
    post_list = [g for g in post_list if not _is_iconize_sync_post_tool_use_group(g)]
    snippet = _render_post_tool_use_snippet()
    iconize_sync_groups = snippet["hooks"]["PostToolUse"]
    post_list.extend(iconize_sync_groups)
    hooks["PostToolUse"] = post_list
    settings["hooks"] = hooks
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return settings_path


def cmd_install_hooks(args) -> int:
    vault = find_vault(args.vault)
    shim = _install_shim(vault)
    settings_path = _install_post_tool_use(vault)
    print(json.dumps({
        "op": "install-hooks",
        "HOOK_VERSION": HOOK_VERSION,
        "shim": str(shim),
        "settings": str(settings_path),
    }, ensure_ascii=False))
    return EXIT_OK


def cmd_check_versions(args) -> int:
    vault = find_vault(args.vault)
    current = _current_version()
    pre = _shim_installed_version(vault)
    post = _post_tool_use_installed_version(vault)

    def _status(installed):
        if installed is None:
            return "missing"
        if installed[0] != current[0]:
            return "major-drift"
        if installed != current:
            return "minor-drift"
        return "ok"

    pre_status = _status(pre)
    post_status = _status(post)
    drift = any(s in ("missing", "major-drift") for s in (pre_status, post_status))
    report = {
        "op": "check-versions",
        "HOOK_VERSION": HOOK_VERSION,
        "pre_commit": {
            "installed": ".".join(map(str, pre)) if pre else None,
            "status": pre_status,
        },
        "post_tool_use": {
            "installed": ".".join(map(str, post)) if post else None,
            "status": post_status,
        },
    }
    print(json.dumps(report, ensure_ascii=False))
    return EXIT_VERSION_DRIFT if drift else EXIT_OK


DISPATCH = {
    "sync": cmd_sync,
    "sync-staged": cmd_sync_staged,
    "reconcile": cmd_reconcile,
    "install-hooks": cmd_install_hooks,
    "check-versions": cmd_check_versions,
}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"protocol_version={PROTOCOL_VERSION} hook_version={HOOK_VERSION}")
        return EXIT_OK
    if args.validate_entry:
        try: entry = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(f"invalid JSON: {e}", file=sys.stderr); return EXIT_VALIDATION
        try:
            validate_icon_name(entry.get("iconName", ""))
            if entry.get("iconColor"): validate_color(entry["iconColor"])
        except IconizeError as e:
            print(f"error: {e}", file=sys.stderr); return EXIT_VALIDATION
        return EXIT_OK
    if not args.cmd:
        print("usage: iconize_sync <sync|sync-staged|reconcile|install-hooks|check-versions> ...", file=sys.stderr)
        return EXIT_VALIDATION
    handler = DISPATCH.get(args.cmd)
    if handler is None:
        # Other subcommands land in later tasks.
        return EXIT_VALIDATION
    try:
        return handler(args)
    except IconizeError as e:
        sys.stderr.write(f"iconize_sync: {e}\n")
        return e.code
    except Exception as e:
        sys.stderr.write(f"iconize_sync: unexpected: {e}\n")
        return EXIT_VALIDATION


# ---------------------------------------------------------------------------
# Icon-map loader + registry lookup helpers
# ---------------------------------------------------------------------------

INTERP_RE = re.compile(r"\{\{\s*(frontmatter\.[A-Za-z0-9_]+|basename(?:\.stem)?)\s*\}\}")

def load_icon_map(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise IconizeError(f"icon-map not found at {p}", EXIT_VALIDATION)
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise IconizeError(f"icon-map invalid JSON: {e}", EXIT_VALIDATION) from e
    if not isinstance(m, dict) or "matchers" not in m:
        raise IconizeError("icon-map missing 'matchers'", EXIT_VALIDATION)
    if not isinstance(m["matchers"], list):
        raise IconizeError("icon-map 'matchers' must be a list", EXIT_VALIDATION)
    m.setdefault("registries", {}); m.setdefault("stage_colors", {})
    if not isinstance(m["registries"], dict):
        raise IconizeError("icon-map 'registries' must be an object", EXIT_VALIDATION)
    if not isinstance(m["stage_colors"], dict):
        raise IconizeError("icon-map 'stage_colors' must be an object", EXIT_VALIDATION)
    return m

def lookup_dotted(root: dict, dotted: str):
    cur = root
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur: return None
        cur = cur[part]
    return cur

def interpolate(template: str, frontmatter: dict, basename: str) -> str:
    """Substitute `{{frontmatter.<key>}}` / `{{basename}}` / `{{basename.stem}}`.

    Single-pass: no recursion, no nested `{{}}`. Unrecognized tokens (typos,
    unsupported syntax) pass through literally; the caller's registry lookup
    will miss and the matcher fails silently per protocol spec.
    Missing frontmatter keys resolve to empty string. Bool/int values stringify
    via `str()` (`True` → `"True"`, `1` → `"1"`).
    """
    if "{{" not in template:
        return template
    def sub(match):
        ref = match.group(1)
        if ref == "basename": return basename
        if ref == "basename.stem": return basename.rsplit(".", 1)[0]
        # ref must start with "frontmatter." per INTERP_RE
        key = ref.split(".", 1)[1]
        v = frontmatter.get(key)
        return "" if v is None else str(v)
    return INTERP_RE.sub(sub, template)


# ---------------------------------------------------------------------------
# Matcher engine — `when` predicate evaluation
# ---------------------------------------------------------------------------

def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1] if "/" in path else path

def eval_when(when: dict, path: str, frontmatter: dict) -> bool:
    """Evaluate a matcher `when` block against a file. AND semantics across keys."""
    bn = _basename(path)
    for key, expected in when.items():
        if key == "basename":
            if bn != expected: return False
        elif key == "basename_in":
            if not isinstance(expected, (list, tuple, set)):
                raise IconizeError(f"'basename_in' must be a list, got {type(expected).__name__}")
            if bn not in expected: return False
        elif key == "path_glob":
            # PurePosixPath.full_match (3.13+) honors `**` cross-segment and
            # `*` as single-segment, unlike fnmatch which ignores `/`.
            if not PurePosixPath(path).full_match(expected): return False
        elif key == "role_matches_basename":
            stem = bn.rsplit(".", 1)[0]
            if frontmatter.get("role") != stem: return False
        elif key.startswith("frontmatter."):
            fkey = key.split(".", 1)[1]
            if frontmatter.get(fkey) != expected: return False
        elif key == "callback":
            # Real implementation lands in Task 7 (callbacks).
            if not _callback_when(expected, path, frontmatter): return False
        else:
            raise IconizeError(f"unknown 'when' predicate: {key!r}")
    return True

def _callback_dir(vault: Path | None = None) -> Path:
    if CALLBACK_DIR_OVERRIDE is not None:
        return Path(CALLBACK_DIR_OVERRIDE)
    global _CALLBACK_VAULT_CACHE
    if vault is None:
        if _CALLBACK_VAULT_CACHE is None:
            _CALLBACK_VAULT_CACHE = find_vault(None)
        vault = _CALLBACK_VAULT_CACHE
    return vault / ".claude" / "callbacks"


def _invoke_callback(callback_id: str, payload: dict) -> dict | None:
    cb_path = _callback_dir() / callback_id
    if not cb_path.is_file() or not os.access(cb_path, os.X_OK):
        return None
    try:
        r = subprocess.run([str(cb_path)], input=json.dumps(payload),
                           capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        sys.stderr.write(f"callback {callback_id!r} timed out: {out}\n"); return None
    except OSError as e:
        sys.stderr.write(f"callback {callback_id!r} failed: {e}\n"); return None
    if r.returncode != 0:
        sys.stderr.write(f"callback {callback_id!r}: {r.stderr}"); return None
    try: return json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(f"callback {callback_id!r} returned non-JSON\n"); return None


def _callback_when(callback_id: str, path: str, frontmatter: dict) -> bool:
    r = _invoke_callback(callback_id, {"op": "when", "path": path, "frontmatter": frontmatter})
    return bool(r and r.get("match") is True)


# ---------------------------------------------------------------------------
# Matcher engine — `resolve` + base/overlays + emit
# ---------------------------------------------------------------------------

def _resolve_field(spec, icon_map, frontmatter, basename):
    """Resolve a single field spec (literal string OR {from, key, field?})."""
    if isinstance(spec, str):
        return spec if "{{" not in spec else interpolate(spec, frontmatter, basename)
    if isinstance(spec, dict) and "from" in spec:
        reg = lookup_dotted(icon_map, spec["from"])
        if reg is None: return None
        key = interpolate(spec["key"], frontmatter, basename)
        if not key: return None
        val = reg.get(key)
        if val is None: return None
        field = spec.get("field")
        if field is None:
            return val if isinstance(val, str) else None  # flat map
        if isinstance(val, dict): return val.get(field)
        return None
    return None

def _build_entry(resolve_spec, icon_map, frontmatter, basename, path):
    """Execute a 'resolve' block and return {'iconName': ..., 'iconColor'?: ...} or None.

    `path` is the full vault-relative path; required so overlay `when`
    blocks with `path_glob` or path-aware predicates evaluate correctly.
    Ties among overlays at equal `priority` are resolved by declaration
    order (sorted is stable)."""
    if "iconName" in resolve_spec or "iconColor" in resolve_spec:
        name = _resolve_field(resolve_spec.get("iconName"), icon_map, frontmatter, basename)
        if not name: return None
        entry = {"iconName": name}
        color = _resolve_field(resolve_spec.get("iconColor"), icon_map, frontmatter, basename)
        if color: entry["iconColor"] = color
        return entry
    if "base" in resolve_spec:
        base = _build_entry(resolve_spec["base"], icon_map, frontmatter, basename, path)
        overlays = sorted(resolve_spec.get("overlays", []),
                          key=lambda o: -int(o.get("priority", 0)))
        for ov in overlays:
            if eval_when(ov.get("when", {}), path, frontmatter):
                entry = dict(base) if base else {}
                if "iconName" in ov: entry["iconName"] = ov["iconName"]
                if "iconColor" in ov: entry["iconColor"] = ov["iconColor"]
                return entry if "iconName" in entry else None
        return base
    if "callback" in resolve_spec:
        return _callback_resolve(resolve_spec["callback"], frontmatter, icon_map)
    return None

def _callback_resolve(callback_id: str, frontmatter: dict, icon_map: dict) -> dict | None:
    r = _invoke_callback(callback_id,
                         {"op": "resolve", "frontmatter": frontmatter, "icon_map": icon_map})
    if not r or not r.get("iconName"): return None
    entry = {"iconName": r["iconName"]}
    if r.get("iconColor"): entry["iconColor"] = r["iconColor"]
    return entry

def resolve_matchers(icon_map: dict, path: str, frontmatter: dict) -> list:
    """Return list of (emit_path, entry_dict)."""
    basename = _basename(path)
    for matcher in icon_map.get("matchers", []):
        when = matcher.get("when", {})
        if not eval_when(when, path, frontmatter): continue
        entry = _build_entry(matcher.get("resolve", {}), icon_map, frontmatter, basename, path)
        # First-match-wins: once `when` matches, this matcher owns the file.
        # Resolution miss → return []; do not fall through to later matchers.
        if not entry: return []
        out = []
        for target in matcher.get("emit", ["self"]):
            if target == "self": out.append((normalize_path(path), entry))
            elif target == "parent_dir":
                parent = "/".join(path.split("/")[:-1])
                if parent: out.append((normalize_path(parent), dict(entry)))
        return out
    return []


if __name__ == "__main__":
    sys.exit(main())
