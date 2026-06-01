#!/usr/bin/env python3

"""
Generic iconize-sync worker for the lazycortex-obsidian plugin.

Resolves Obsidian file icons from a declarative icon-map and writes the result into each
note's `iconize_icon` / `iconize_color` frontmatter keys. Exposes subcommands invoked by
git pre-commit hooks and by Claude Code's PostToolUse / Stop hooks; never blocks a commit
when the icon-map is missing or incompatible — hooks stay inert in that case.

See claude/lazycortex-obsidian/references/lazy-obsidian.iconize-protocol.md.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from icon_keys import (
  CallbackKey, FrontmatterKey, IconKey, InterpToken, MapKey,
  ResultKey, VersionStatus, WhenKey, YamlScalar,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import NoReturn


PROTOCOL_VERSION = "2.0.0"
HOOK_VERSION = "2.0.0"

# Schema versioning for icon-map.json (bilateral handshake).
# - SCHEMA_VERSION: the version this worker writes on install/migrate.
# - SUPPORTED_SCHEMA: integers this worker can consume at runtime; mismatch → preflight
#   exits the hook cleanly (EXIT_OK) with a stderr diagnostic. Consumers bump by re-running
#   lazy-obsidian.iconize-install.
SCHEMA_VERSION = 2
SUPPORTED_SCHEMA = { 2 }

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_TARGET_MISSING = 4
EXIT_VERSION_DRIFT = 5

# ----------------------------------------------------------------------------------------
# Vault discovery
# ----------------------------------------------------------------------------------------

CALLBACK_DIR_OVERRIDE = None  # Tests override this; prod: None → <vault>/.claude/callbacks
_CALLBACK_VAULT_CACHE = None


class IconizeError(Exception):
  """
  Worker-level error carrying a process exit code.

  Attributes:
    code: Exit code the worker should return when this error propagates to the entry point.
  """

  def __init__(self, message: str, code: int = EXIT_VALIDATION):
    """
    Initialize the error with a human-readable message and an exit code.

    Args:
      message: Description of the failure surfaced to stderr.
      code: Exit code returned by the worker; defaults to the validation exit code.
    """
    super().__init__(message)
    self.code = code


def find_vault_walk_up(start: Path) -> Path | None:
  """
  Return the closest ancestor directory of `start` that contains an Obsidian vault marker.

  Args:
    start: Filesystem path to begin the upward walk from.

  Returns:
    The first ancestor directory that has a `.obsidian/` subdirectory, or None when no
    ancestor qualifies up to the filesystem root.
  """
  cur = Path(os.path.abspath(start))
  while True:
    # guard: vault marker found at the current level
    # waiver: filesystem path idiom (.obsidian)
    if (cur / ".obsidian").is_dir():
      return cur
    parent = cur.parent
    # guard: reached filesystem root without finding a vault
    if parent == cur:
      return None
    cur = parent


def find_vault(override: str | None) -> Path:
  """
  Return the vault root, either from an explicit override or by walking up from the cwd.

  Args:
    override: Caller-supplied vault path; when set it must contain a `.obsidian/` directory.

  Returns:
    Absolute path to the resolved vault root.

  Raises:
    IconizeError: When `override` is provided but does not point at a valid vault, or when
      no vault is found by walking up from the current working directory.
  """
  # guard: explicit override path takes precedence over discovery
  if override:
    v = Path(os.path.abspath(Path(override).expanduser()))
    # guard: override must itself be a vault
    # waiver: filesystem path idiom (.obsidian)
    if not (v / ".obsidian").is_dir():
      raise IconizeError(f"vault override has no .obsidian/: {v}")
    return v
  found = find_vault_walk_up(Path.cwd())
  # guard: discovery failed
  if found is None:
    raise IconizeError("vault not found: no .obsidian/ in cwd or parents")
  return found


# ----------------------------------------------------------------------------------------
# Frontmatter parser + entry validators
# ----------------------------------------------------------------------------------------

FM_BLOCK_RE = re.compile(r"(?ms)\A---\s*\n(.*?\n)^---\s*\n")
COLOR_RE = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$")  # lowercase only
ICON_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def parse_frontmatter(text: str) -> dict:
  """
  Parse the YAML frontmatter block at the start of a markdown document.

  Supports a flat key/value subset: quoted or bare strings, booleans `true` / `false`, and
  integers. Nested structures, lists, and multi-line values are not supported.

  Args:
    text: Full markdown document text, expected to start with a `---` fenced block.

  Returns:
    Mapping of frontmatter keys to their parsed values. Returns an empty dict when no
    frontmatter block is present.
  """
  m = FM_BLOCK_RE.match(text)
  # guard: no frontmatter block at the start of the document
  if not m:
    return {}
  out: dict = {}
  for line in m.group(1).splitlines():
    # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
    line = line.rstrip()  # noqa: PLW2901
    # guard: skip blank and comment lines
    if not line or line.startswith("#"):
      continue
    # guard: lines without a colon are not key/value entries
    if ":" not in line:
      continue
    k, _, v = line.partition(":")
    k = k.strip()
    v = v.strip()
    # guard: keys must be non-empty
    if not k:
      continue
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
      out[k] = v[1:-1]
    elif v == YamlScalar.TRUE:
      out[k] = True
    elif v == YamlScalar.FALSE:
      out[k] = False
    elif v.lstrip("-").isdigit():
      out[k] = int(v)
    else:
      out[k] = v
  return out


def normalize_path(p: str) -> str:
  """
  Validate and normalize a vault-relative POSIX path.

  Strips a leading `./` segment and a trailing `/`. Rejects absolute paths, home-relative
  paths, and paths containing backslash separators.

  Args:
    p: Candidate vault-relative path.

  Returns:
    The normalized path string.

  Raises:
    IconizeError: When the path is empty, absolute, home-relative, or uses non-POSIX
      separators.
  """
  # guard: empty input is never valid
  if not p:
    raise IconizeError("path is empty")
  # guard: absolute paths are rejected — vault-relative only
  if p.startswith("/"):
    raise IconizeError(f"path must be vault-relative: {p!r}")
  # guard: home-relative paths are rejected
  if p.startswith("~"):
    raise IconizeError(f"path must be vault-relative, not home-relative: {p!r}")
  # guard: backslash separators are rejected (POSIX only)
  if "\\" in p:
    raise IconizeError(f"path must use POSIX separators: {p!r}")
  if p.startswith("./"):
    p = p[2:]
  p = p.rstrip("/")
  # guard: normalization must leave a non-empty path
  if not p:
    raise IconizeError("path is empty after normalization")
  return p


def validate_color(c: str) -> None:
  """
  Validate a color literal against the accepted lowercase hex shapes.

  Args:
    c: Candidate color string.

  Raises:
    IconizeError: When the value is not a lowercase `#rgb` or `#rrggbb` literal.
  """
  # guard: only lowercase #rgb / #rrggbb literals are accepted
  if not COLOR_RE.match(c):
    raise IconizeError(f"invalid color {c!r} (want lowercase #rgb or #rrggbb)")


def validate_icon_name(name: str) -> None:
  """
  Validate an icon-name literal against the accepted shapes.

  Accepts ASCII identifiers (letters, digits, underscore, hyphen) of any length, and short
  emoji-grapheme literals up to eight characters.

  Args:
    name: Candidate icon name.

  Raises:
    IconizeError: When the value is empty, contains whitespace, or does not match either
      accepted shape.
  """
  # guard: empty, padded, or whitespace-bearing values are rejected
  if not name or name.strip() != name or any(ch.isspace() for ch in name):
    raise IconizeError(f"invalid iconName {name!r}")
  # guard: ASCII identifier shape passes immediately
  if ICON_NAME_RE.match(name):
    return
  # guard: short emoji grapheme passes as a soft fallback
  # waiver: inline numeric literal
  if len(name) <= 8:
    return
  raise IconizeError(f"iconName not recognized: {name!r}")


class _Parser(argparse.ArgumentParser):
  """
  Argument parser variant that exits with the worker's validation code on usage errors.
  """

  def error(self, message: str) -> NoReturn:  # pragma: no cover - exercised via subprocess
    """
    Print the usage banner and exit with the worker's validation exit code.

    Args:
      message: Error message describing the parsing failure.

    Raises:
      SystemExit: Always raised with the validation exit code after printing the usage banner.
    """
    self.print_usage(sys.stderr)
    self.exit(EXIT_VALIDATION, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
  """
  Build the top-level argument parser for the worker entry point.

  Returns:
    Parser wired with global flags (`--version`, `--validate-entry`, `--vault`,
    `--icon-map`, `--dry-run`) and one subparser per supported subcommand.
  """
  # waiver: argparse CLI signature
  p = _Parser(prog = "iconize_sync", description = "Obsidian iconize-sync worker.")
  # waiver: argparse CLI signature
  p.add_argument("--version", action = "store_true", help = "print protocol_version and hook_version")
  # waiver: argparse CLI signature
  p.add_argument("--validate-entry", action = "store_true",
                 help = "read {iconName, iconColor?} JSON from stdin; exit 0 if valid")
  # waiver: argparse CLI signature
  p.add_argument("--vault", help = "vault root (default: walk up from cwd)")
  # waiver: argparse CLI signature
  p.add_argument("--icon-map", help = "path to icon-map (default: <repo>/.claude/iconize/obsidian-icon-map.json)")
  # waiver: argparse CLI signature
  p.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature
  sub = p.add_subparsers(dest = "cmd", parser_class = _Parser)
  # waiver: subcommand-name value (canonical home is the parser+dispatch map)
  for name in ("sync", "sync-staged", "reconcile", "reconcile-plugin", "reconcile-dirty",
               "install-hooks", "check-versions"):
    sp = sub.add_parser(name)
    # waiver: subcommand-name value (canonical home is the parser+dispatch map)
    if name == "sync":
      # waiver: argparse CLI signature
      sp.add_argument("path", help = "file path relative to vault root")
    # waiver: subcommand-name value (canonical home is the parser+dispatch map)
    if name == "reconcile":
      # waiver: argparse CLI signature
      sp.add_argument("--prefix", help = "only reconcile entries whose path starts with this prefix")
    # waiver: subcommand-name value (canonical home is the parser+dispatch map)
    if name == "reconcile-plugin":
      # waiver: argparse CLI signature
      sp.add_argument("plugin", help = "plugin name; reconcile only claude/<plugin>/")
  return p


def _resolve_icon_map_path(vault: Path, override: str | None) -> Path:
  """
  Resolve the path to the icon-map JSON for the given vault.

  When `override` is supplied it wins. Otherwise walks up from the vault to find the
  nearest `.claude/iconize/obsidian-icon-map.json`, because the repo root may sit above
  the vault directory.

  Args:
    vault: Resolved vault root.
    override: Optional explicit icon-map path.

  Returns:
    Absolute path to the icon-map file.

  Raises:
    IconizeError: When no icon-map is found at or above the vault.
  """
  # guard: explicit override path wins
  if override:
    return Path(override).expanduser().resolve()
  # Walk up from vault to find a .claude/iconize/obsidian-icon-map.json (repo root may be above vault).
  # Resolve symlinks once at entry so the walk crosses filesystem boundaries correctly.
  cur = vault.resolve()
  while True:
    # waiver: filesystem path idiom (.claude/.tmp/.md)
    cand = cur / ".claude" / "iconize" / "obsidian-icon-map.json"
    # guard: icon-map found at the current level
    if cand.exists():
      return cand
    # guard: reached filesystem root without finding the icon-map
    if cur == cur.parent:
      break
    cur = cur.parent
  raise IconizeError(
    "obsidian-icon-map.json not found; run lazy-obsidian.iconize-install first", EXIT_VALIDATION)


def _load_icon_map_or_inert(vault: Path, override: str | None) -> dict | None:
  """
  Load the icon-map for hook contexts, returning None when it cannot be used.

  Icons are cosmetic; hooks must never block a commit because of a missing or broken
  icon-map. Callers that receive None must short-circuit with the OK exit code so the
  hook stays inert. A diagnostic is written to stderr so a curious user can inspect why
  the hook went inert after removing any stderr redirection.

  Args:
    vault: Resolved vault root.
    override: Optional explicit icon-map path.

  Returns:
    Parsed icon-map dict, or None when the icon-map is missing, invalid, or unreadable.
  """
  try:
    path = _resolve_icon_map_path(vault, override)
    return load_icon_map(path)
  except IconizeError as e:
    sys.stderr.write(f"iconize_sync: {e}; hook inert.\n")
    return None


def _read_frontmatter_for(vault: Path, vault_rel: str) -> dict:
  """
  Read and parse the frontmatter for a vault-relative path.

  Args:
    vault: Resolved vault root.
    vault_rel: Vault-relative POSIX path.

  Returns:
    Parsed frontmatter mapping; empty dict when the target is missing or has no frontmatter.
  """
  p = vault / vault_rel
  # guard: missing target yields empty frontmatter
  if not p.is_file():
    return {}
  # waiver: stdlib encoding-mode idiom
  return parse_frontmatter(p.read_text(encoding = "utf-8", errors = "ignore"))


def _vault_relative_or_none(vault: Path, raw: str) -> str | None:
  """
  Coerce a caller-supplied path to a vault-relative POSIX path.

  Accepts absolute and `~`-prefixed paths — as Claude Code's PostToolUse hook supplies
  `tool_input.file_path` — and relativizes them against the vault. Returns None when the
  path is outside the vault, a common case for PostToolUse which fires on every edit
  regardless of whether the file belongs to the iconize-driven vault. Already-relative
  inputs are validated via the standard normalization rules.

  Args:
    vault: Resolved vault root.
    raw: Caller-supplied path, absolute, home-relative, or vault-relative.

  Returns:
    Normalized vault-relative POSIX path, or None when the path lies outside the vault.
  """
  if raw.startswith(("/", "~")):
    try:
      abs_path = Path(raw).expanduser().resolve()
      rel = abs_path.relative_to(vault.resolve())
    except (ValueError, OSError):
      # path is outside the vault — caller treats this as a silent no-op
      return None
    return normalize_path(str(PurePosixPath(rel)))
  return normalize_path(raw)


def cmd_sync(args: argparse.Namespace) -> int:
  """
  Resolve and apply the icon for a single note.

  Reads the note's frontmatter, evaluates the icon-map matchers, and rewrites the
  `iconize_icon` / `iconize_color` frontmatter keys when they differ from the resolved
  values. Behaves as a silent no-op when the icon-map is missing or incompatible, when
  the path falls outside the vault, or when the target file does not exist.

  Args:
    args: Parsed CLI arguments carrying the target `path`, optional `--vault`,
      `--icon-map`, and `--dry-run` flags.

  Returns:
    Process exit code; always OK in the current implementation.
  """
  vault = find_vault(args.vault)
  icon_map = _load_icon_map_or_inert(vault, args.icon_map)
  # guard: missing or incompatible icon-map → hook inert
  if icon_map is None or _preflight_incompatible(icon_map):
    return EXIT_OK
  rel = _vault_relative_or_none(vault, args.path)
  # guard: path outside the vault → no-op
  if rel is None:
    return EXIT_OK
  note_path = vault / rel
  # guard: nothing to rewrite — hook may fire on transient states
  if not note_path.is_file():
    return EXIT_OK
  fm = _read_frontmatter_for(vault, rel)
  entries = resolve_matchers(icon_map, rel, fm)
  # Schema 2: entries is [] or [(self_path, entry)]. Extract icon/color or None/None.
  icon, color = (None, None)
  if entries:
    _, entry = entries[0]
    icon = entry.get(IconKey.NAME)
    color = entry.get(IconKey.COLOR)
  if args.dry_run:
    print(json.dumps({
      ResultKey.OP: "sync", ResultKey.DRY_RUN: True, ResultKey.PATH: rel,
      ResultKey.ICON: icon, ResultKey.COLOR: color,
    }, ensure_ascii = False))
    return EXIT_OK
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from frontmatter_rewriter import rewrite_file
  changed = rewrite_file(note_path, icon = icon, color = color)
  print(json.dumps({
    ResultKey.OP: "sync", ResultKey.PATH: rel, ResultKey.CHANGED: changed,
    ResultKey.ICON: icon, ResultKey.COLOR: color,
  }, ensure_ascii = False))
  return EXIT_OK


def _staged_md_files(vault: Path) -> list[str]:
  """
  Return the list of `.md` paths currently staged in the vault's git index.

  Covers files in the Added, Copied, Modified, or Renamed states. Deletions are not
  handled here — stale entries for deleted files are cleaned up by `reconcile`.

  Args:
    vault: Resolved vault root.

  Returns:
    List of vault-relative POSIX paths.

  Raises:
    IconizeError: When the underlying git invocation fails.
  """
  # --diff-filter=ACMR covers Added/Copied/Modified/Renamed. Deletions are not
  # handled here; stale entries for deleted files get cleaned up by `reconcile`.
  # `--no-optional-locks` skips the stat-cache refresh that `git diff --cached`
  # would otherwise write to `.git/index.lock`. This hook fires from
  # .githooks/pre-commit on every manual commit AND from Claude Code's
  # PostToolUse/Stop on every edit; without the flag it races with concurrent
  # manual git ops.
  r = subprocess.run(
    [ "git", "--no-optional-locks", "-C", str(vault),
      "diff", "--cached", "--name-only",
      "--diff-filter=ACMR", "--", "*.md" ],
    capture_output = True, text = True, check = False)
  # guard: surface git failures as validation errors
  if r.returncode != 0:
    raise IconizeError(f"git failed: {r.stderr.strip()}", EXIT_VALIDATION)
  return [ ln for ln in r.stdout.splitlines() if ln.strip() ]


def cmd_sync_staged(args: argparse.Namespace) -> int:
  """
  Resolve and apply icons for every `.md` file currently staged in the vault index.

  Re-stages files whose frontmatter is rewritten so they ride along in the operator's
  pending commit. Stays inert when the icon-map is missing or incompatible.

  Args:
    args: Parsed CLI arguments carrying optional `--vault`, `--icon-map`, and `--dry-run`
      flags.

  Returns:
    Process exit code; always OK in the current implementation.
  """
  vault = find_vault(args.vault)
  icon_map = _load_icon_map_or_inert(vault, args.icon_map)
  # guard: missing or incompatible icon-map → hook inert
  if icon_map is None or _preflight_incompatible(icon_map):
    return EXIT_OK

  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from frontmatter_rewriter import rewrite_file
  touched: list[str] = []
  planned: list[dict] = []

  for rel in _staged_md_files(vault):
    fm = _read_frontmatter_for(vault, rel)
    entries = resolve_matchers(icon_map, rel, fm)
    icon, color = (None, None)
    if entries:
      _, entry = entries[0]
      icon = entry.get(IconKey.NAME)
      color = entry.get(IconKey.COLOR)
    note_path = vault / rel
    # guard: skip targets that disappeared between staging and walk
    if not note_path.is_file():
      continue
    if args.dry_run:
      planned.append({ ResultKey.PATH: rel, ResultKey.ICON: icon, ResultKey.COLOR: color })
      continue
    if rewrite_file(note_path, icon = icon, color = color):
      touched.append(rel)

  if args.dry_run:
    print(json.dumps({ ResultKey.OP: "sync-staged", ResultKey.DRY_RUN: True, ResultKey.PLANNED: planned },
                     ensure_ascii = False))
    return EXIT_OK

  if touched:
    # Re-stage the .md files whose frontmatter we just rewrote.
    rs = subprocess.run(
      [ "git", "-C", str(vault), "add", "--", *touched ],
      capture_output = True, text = True, check = False,
    )
    if rs.returncode != 0:
      sys.stderr.write(
        f"warning: re-stage of modified notes failed: {rs.stderr.strip()}\n")

  print(json.dumps({ ResultKey.OP: "sync-staged", ResultKey.TOUCHED: touched }, ensure_ascii = False))
  return EXIT_OK


def _walk_md_files(vault: Path, prefix: str | None) -> list[str]:
  """
  Enumerate `.md` files under the vault, optionally constrained to a sub-prefix.

  Skips infrastructure directories (`.obsidian`, `.git`, `.claude`, `.githooks`) and
  does not follow symlinks.

  Args:
    vault: Resolved vault root.
    prefix: Vault-relative sub-directory to descend into; when None the full vault is walked.

  Returns:
    List of vault-relative POSIX paths.
  """
  root = vault / prefix if prefix else vault
  # guard: missing sub-tree yields empty list
  if not root.exists():
    return []
  skip_dirs = { ".obsidian", ".git", ".claude", ".githooks" }
  out: list[str] = []
  for dirpath, dirnames, filenames in os.walk(root, followlinks = False):
    # Prune skipped dirs in-place so we never descend into them.
    dirnames[:] = [ d for d in dirnames if d not in skip_dirs ]
    for fn in filenames:
      # guard: only collect markdown files
      # waiver: filesystem path idiom (.md)
      if not fn.endswith(".md"):
        continue
      rel = Path(dirpath, fn).relative_to(vault)
      out.append("/".join(rel.parts))
  return out


def cmd_reconcile(args: argparse.Namespace) -> int:
  """
  Recompute icons across the full vault (or a prefix sub-tree) and rewrite frontmatter.

  Walks every markdown file under the vault, evaluates the icon-map matchers, and rewrites
  the `iconize_icon` / `iconize_color` keys where the resolution differs. Stays inert when
  the icon-map is missing or incompatible.

  Args:
    args: Parsed CLI arguments carrying optional `--prefix`, `--vault`, `--icon-map`,
      and `--dry-run` flags.

  Returns:
    Process exit code; always OK in the current implementation.
  """
  vault = find_vault(args.vault)
  icon_map = _load_icon_map_or_inert(vault, args.icon_map)
  # guard: missing or incompatible icon-map → hook inert
  if icon_map is None or _preflight_incompatible(icon_map):
    return EXIT_OK
  prefix = normalize_path(args.prefix) if args.prefix else ""

  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from frontmatter_rewriter import rewrite_file
  touched: list[str] = []
  planned: list[dict] = []

  for rel in _walk_md_files(vault, prefix or None):
    fm = _read_frontmatter_for(vault, rel)
    entries = resolve_matchers(icon_map, rel, fm)
    icon, color = (None, None)
    if entries:
      _, entry = entries[0]
      icon = entry.get(IconKey.NAME)
      color = entry.get(IconKey.COLOR)
    note_path = vault / rel
    if args.dry_run:
      planned.append({ ResultKey.PATH: rel, ResultKey.ICON: icon, ResultKey.COLOR: color })
      continue
    if rewrite_file(note_path, icon = icon, color = color):
      touched.append(rel)

  if args.dry_run:
    print(json.dumps({ ResultKey.OP: "reconcile", ResultKey.DRY_RUN: True, ResultKey.PREFIX: prefix,
                       ResultKey.PLANNED: planned }, ensure_ascii = False))
    return EXIT_OK

  print(json.dumps({ ResultKey.OP: "reconcile", ResultKey.PREFIX: prefix,
                     ResultKey.TOUCHED_COUNT: len(touched) }, ensure_ascii = False))
  return EXIT_OK


def cmd_reconcile_plugin(args: argparse.Namespace) -> int:
  """
  Reconcile icons under a single plugin's sub-tree and re-stage touched files.

  Used by the pre-commit pipeline after a `plugin.json` bump: the version delta flips
  callbacks like `plugin-is-patch-bumped`, so every file under the plugin's subtree whose
  color depends on that callback (folder note, README) must repaint in the same commit.
  The full `reconcile` walk would do the same but at vault scope; this one is bounded to
  the touched plugin.

  Args:
    args: Parsed CLI arguments carrying the target `plugin` name and optional `--vault`,
      `--icon-map`, and `--dry-run` flags.

  Returns:
    Process exit code; always OK in the current implementation.
  """
  vault = find_vault(args.vault)
  icon_map = _load_icon_map_or_inert(vault, args.icon_map)
  # guard: missing or incompatible icon-map → hook inert
  if icon_map is None or _preflight_incompatible(icon_map):
    return EXIT_OK
  plugin = args.plugin
  prefix = f"claude/{plugin}"

  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from frontmatter_rewriter import rewrite_file
  touched: list[str] = []
  planned: list[dict] = []

  for rel in _walk_md_files(vault, prefix):
    fm = _read_frontmatter_for(vault, rel)
    entries = resolve_matchers(icon_map, rel, fm)
    icon, color = (None, None)
    if entries:
      _, entry = entries[0]
      icon = entry.get(IconKey.NAME)
      color = entry.get(IconKey.COLOR)
    note_path = vault / rel
    # guard: skip targets that disappeared during the walk
    if not note_path.is_file():
      continue
    if args.dry_run:
      planned.append({ ResultKey.PATH: rel, ResultKey.ICON: icon, ResultKey.COLOR: color })
      continue
    if rewrite_file(note_path, icon = icon, color = color):
      touched.append(rel)

  if args.dry_run:
    print(json.dumps({ ResultKey.OP: "reconcile-plugin", ResultKey.PLUGIN: plugin, ResultKey.DRY_RUN: True,
                       ResultKey.PLANNED: planned }, ensure_ascii = False))
    return EXIT_OK

  if touched:
    rs = subprocess.run(
      [ "git", "-C", str(vault), "add", "--", *touched ],
      capture_output = True, text = True, check = False,
    )
    if rs.returncode != 0:
      sys.stderr.write(
        f"warning: re-stage of modified notes failed: {rs.stderr.strip()}\n")

  print(json.dumps({ ResultKey.OP: "reconcile-plugin", ResultKey.PLUGIN: plugin, ResultKey.TOUCHED: touched },
                   ensure_ascii = False))
  return EXIT_OK


_EXCLUDED_DIRS = (".obsidian", ".git", ".claude", ".githooks")


def _dirty_md_files(vault: Path) -> list[str]:
  """
  Return vault-relative POSIX paths of every dirty `.md` file in the vault.

  A file is dirty when `git status --porcelain` reports it as modified, added, deleted,
  untracked, or renamed/copied. For renames and copies both the old and new paths are
  returned so the caller can clean up the stale path-key in the old parent directory as
  well as emit the new one. Returns an empty list silently on any non-git vault or git
  failure — the Stop hook is a safety net, not a blocker.

  Args:
    vault: Resolved vault root.

  Returns:
    Sorted list of vault-relative POSIX paths.
  """
  # `--no-optional-locks` skips the stat-cache refresh that `git status`
  # would otherwise write to `.git/index.lock`. Called from the Stop hook
  # on every Claude Code turn; without the flag it races with concurrent
  # manual git ops.
  r = subprocess.run(
    [ "git", "--no-optional-locks", "-C", str(vault),
      "status", "-z", "--porcelain=v1" ],
    capture_output = True, text = False, check = False)
  # guard: git failure → empty list (Stop hook stays a safety net)
  if r.returncode != 0:
    return []
  paths: set[str] = set()
  # -z output: each record is `XY<space><path>` terminated by NUL. For R/C codes the
  # record is `XY<space><new>\x00<old>`, so the *following* record is the original
  # path (no preceding status bytes). We track whether the previous record was R/C.
  records = r.stdout.split(b"\x00")
  expect_origin = False
  for rec in records:
    if not rec:
      expect_origin = False
      continue
    if expect_origin:
      # Record is the pre-rename/copy original path, no XY prefix.
      path_bytes = rec
      expect_origin = False
    else:
      # guard: malformed records shorter than "XY " + 1 path byte are skipped
      # waiver: inline numeric literal
      if len(rec) < 4:
        continue
      xy = rec[:2]
      path_bytes = rec[3:]
      if xy[:1] in (b"R", b"C") or xy[1:2] in (b"R", b"C"):
        expect_origin = True
    try:
      # waiver: stdlib encoding-mode idiom
      path = path_bytes.decode("utf-8")
    except UnicodeDecodeError:
      # skip records whose path is not valid UTF-8
      continue
    # guard: only markdown files participate
    # waiver: filesystem path idiom (.md)
    if not path.endswith(".md"):
      continue
    parts = PurePosixPath(path).parts
    # guard: drop paths inside excluded top-level directories
    if parts and parts[0] in _EXCLUDED_DIRS:
      continue
    paths.add(path)
  return sorted(paths)


def cmd_reconcile_dirty(args: argparse.Namespace) -> int:
  """
  Reconcile icons across every directory containing a dirty `.md` file.

  Computes the parent directories of all dirty markdown files in the vault and walks each
  prefix to recompute icons. Used by the Stop hook on every Claude Code turn. Stays inert
  when the icon-map is missing or incompatible and is a no-op when no dirty files exist.

  Args:
    args: Parsed CLI arguments carrying optional `--vault`, `--icon-map`, and `--dry-run`
      flags.

  Returns:
    Process exit code; always OK in the current implementation.
  """
  vault = find_vault(args.vault)
  icon_map = _load_icon_map_or_inert(vault, args.icon_map)
  # guard: missing or incompatible icon-map → hook inert
  if icon_map is None or _preflight_incompatible(icon_map):
    return EXIT_OK

  paths = _dirty_md_files(vault)
  # guard: no dirty markdown files → silent no-op
  if not paths:
    return EXIT_OK

  prefixes = sorted({ "/".join(PurePosixPath(p).parts[:-1]) for p in paths })

  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from frontmatter_rewriter import rewrite_file
  touched: list[str] = []
  planned: list[dict] = []

  for prefix in prefixes:
    for rel in _walk_md_files(vault, prefix or None):
      fm = _read_frontmatter_for(vault, rel)
      entries = resolve_matchers(icon_map, rel, fm)
      icon, color = (None, None)
      if entries:
        _, entry = entries[0]
        icon = entry.get(IconKey.NAME)
        color = entry.get(IconKey.COLOR)
      note_path = vault / rel
      if args.dry_run:
        planned.append({ ResultKey.PATH: rel, ResultKey.ICON: icon, ResultKey.COLOR: color })
        continue
      if rewrite_file(note_path, icon = icon, color = color):
        touched.append(rel)

  if args.dry_run:
    print(json.dumps({ ResultKey.OP: "reconcile-dirty", ResultKey.DRY_RUN: True,
                       ResultKey.PREFIXES: prefixes, ResultKey.PLANNED: planned },
                     ensure_ascii = False))
    return EXIT_OK

  print(json.dumps({ ResultKey.OP: "reconcile-dirty", ResultKey.PREFIXES: prefixes,
                     ResultKey.TOUCHED_COUNT: len(touched) }, ensure_ascii = False))
  return EXIT_OK


# ----------------------------------------------------------------------------------------
# Hook + schema version management — install-hooks + check-versions + preflight
# ----------------------------------------------------------------------------------------

HOOK_VERSION_RE = re.compile(r"HOOK_VERSION:\s*(\d+)\.(\d+)\.(\d+)")
SEMVER_RE = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)\s*$")


def _plugin_root() -> Path:
  """
  Return the on-disk root of the lazycortex-obsidian plugin.

  Returns:
    Absolute path to the plugin root, resolved from this module's location.
  """
  return Path(__file__).resolve().parents[1]


def _template_path(name: str) -> Path:
  """
  Return the on-disk path of an iconize template file shipped with the plugin.

  Args:
    name: Template filename (without directory prefix).

  Returns:
    Absolute path under `templates/iconize/` inside the plugin root.
  """
  # waiver: filesystem path idiom (.obsidian/.tmp/.md)
  return _plugin_root() / "templates" / "iconize" / name


def _parse_hook_version(text: str) -> tuple[int, int, int] | None:
  """
  Extract the `HOOK_VERSION: x.y.z` triple embedded in a shipped hook shim.

  Args:
    text: Text content of a shim or template file.

  Returns:
    Triple of major, minor, patch components, or None when no marker is present.
  """
  m = HOOK_VERSION_RE.search(text)
  # guard: no version marker found
  if not m:
    return None
  # waiver: inline numeric literal
  return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _parse_semver(text: str) -> tuple[int, int, int] | None:
  """
  Parse a bare `x.y.z` semver triple.

  Args:
    text: Candidate semver string with optional surrounding whitespace.

  Returns:
    Triple of major, minor, patch components, or None when the value is not a triple.
  """
  m = SEMVER_RE.match(text)
  # guard: not a well-formed semver triple
  if not m:
    return None
  # waiver: inline numeric literal
  return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _current_version() -> tuple[int, int, int]:
  """
  Return the worker's compiled-in `HOOK_VERSION` parsed into a semver triple.

  Returns:
    Triple of major, minor, patch components.
  """
  v = _parse_semver(HOOK_VERSION)
  # waiver: type-narrowing invariant guaranteed by construction here, not input validation
  assert v is not None
  return v


def _shim_installed_version(vault: Path) -> tuple[int, int, int] | None:
  """
  Read the `HOOK_VERSION` marker from the pre-commit shim installed in the vault.

  Args:
    vault: Resolved vault root.

  Returns:
    Triple of major, minor, patch components from the installed shim, or None when no
    shim is installed or its marker cannot be parsed.
  """
  # waiver: filesystem path idiom (.githooks/pre-commit)
  shim = vault / ".githooks" / "pre-commit"
  # guard: no shim installed yet
  if not shim.is_file():
    return None
  # waiver: stdlib encoding-mode idiom
  return _parse_hook_version(shim.read_text(encoding = "utf-8", errors = "ignore"))


def _preflight_incompatible(icon_map: dict) -> bool:
  """
  Decide whether the loaded icon-map is incompatible with this worker.

  Writes a stderr diagnostic when incompatibility is detected so `2>/dev/null || true`
  hook wrappers stay quiet in CI / tty contexts but a curious user can `unset` the
  redirect and see why hooks went inert. A True return signals the caller to short-circuit
  with the OK exit code — hooks must never block a commit.

  A missing `schema_version` is treated as schema 1 for backward compatibility, so
  pre-handshake vaults keep working silently.

  Args:
    icon_map: Parsed icon-map dict.

  Returns:
    True when the icon-map cannot be processed by this worker, False otherwise.
  """
  schema = icon_map.get(MapKey.SCHEMA_VERSION, 1)
  # guard: unsupported schema version → hook inert
  if not isinstance(schema, int) or schema not in SUPPORTED_SCHEMA:
    sys.stderr.write(
      f"iconize_sync: icon-map schema_version={schema!r} not in {sorted(SUPPORTED_SCHEMA)}; "
      f"hook inert. Run lazy-obsidian.iconize-install to migrate.\n")
    return True
  min_hv = icon_map.get(MapKey.MIN_HOOK_VERSION)
  if isinstance(min_hv, str):
    required = _parse_semver(min_hv)
    if required is None:
      sys.stderr.write(
        f"iconize_sync: icon-map min_hook_version={min_hv!r} not valid semver; ignoring.\n")
    elif _current_version() < required:
      sys.stderr.write(
        f"iconize_sync: HOOK_VERSION {HOOK_VERSION} < icon-map min_hook_version {min_hv}; "
        f"hook inert. Upgrade lazycortex-obsidian plugin.\n")
      return True
  return False


def _install_shim(vault: Path) -> Path:
  """
  Install the pre-commit shim into the vault's `.githooks/` directory.

  Copies the shim template verbatim — no substitution, no absolute-path leakage, no
  version-pinned path. The shim resolves the plugin at exec time.

  Args:
    vault: Resolved vault root.

  Returns:
    Absolute path to the installed shim.
  """
  # waiver: filesystem path idiom (.githooks)
  hooks_dir = vault / ".githooks"
  hooks_dir.mkdir(parents = True, exist_ok = True)
  # waiver: filesystem path idiom (pre-commit)
  shim = hooks_dir / "pre-commit"
  # Shim is path-agnostic: it resolves the plugin at exec time. Copy the template
  # verbatim — no substitution, no /Users/... leakage, no version-pinned path.
  # waiver: filesystem path idiom (pre-commit-shim.sh) + stdlib encoding-mode idiom
  shim.write_text(_template_path("pre-commit-shim.sh").read_text(encoding = "utf-8"),
                  # waiver: stdlib encoding-mode idiom
                  encoding = "utf-8")
  # waiver: inline numeric literal
  shim.chmod(0o755)
  return shim


def cmd_install_hooks(args: argparse.Namespace) -> int:
  """
  Install the pre-commit shim into the vault and print the install record.

  Args:
    args: Parsed CLI arguments carrying optional `--vault`.

  Returns:
    Process exit code; always OK in the current implementation.
  """
  vault = find_vault(args.vault)
  shim = _install_shim(vault)
  print(json.dumps({
    ResultKey.OP: "install-hooks",
    "HOOK_VERSION": HOOK_VERSION,
    "shim": str(shim),
  }, ensure_ascii = False))
  return EXIT_OK


def cmd_check_versions(args: argparse.Namespace) -> int:
  """
  Print the current hook and icon-map schema compatibility report.

  Compares the worker's compiled-in `HOOK_VERSION` against the installed pre-commit shim,
  inspects the icon-map's declared `schema_version` and `min_hook_version`, and emits a
  JSON report. Exits with the version-drift code when the shim is missing, the shim is
  on a different major, or the icon-map is incompatible.

  Args:
    args: Parsed CLI arguments carrying optional `--vault` and `--icon-map`.

  Returns:
    Version-drift exit code on drift, otherwise the OK exit code.
  """
  vault = find_vault(args.vault)
  current = _current_version()
  pre = _shim_installed_version(vault)

  def _status(installed: tuple | None) -> str:
    """
    Classify an installed version triple against the worker's current version.

    Args:
      installed: Installed version triple, or None when no shim is installed.

    Returns:
      One of `"missing"`, `"major-drift"`, `"minor-drift"`, or `"ok"`.
    """
    # guard: nothing installed
    if installed is None:
      return VersionStatus.MISSING
    # guard: incompatible major
    if installed[0] != current[0]:
      return VersionStatus.MAJOR_DRIFT
    if installed != current:
      return VersionStatus.MINOR_DRIFT
    return VersionStatus.OK

  pre_status = _status(pre)

  # Icon-map schema handshake (bilateral): report both the schema the vault declares
  # and whether this worker's HOOK_VERSION satisfies its min_hook_version, if any.
  schema_block: dict = {
    VersionStatus.DECLARED: None, ResultKey.STATUS: VersionStatus.MISSING, MapKey.MIN_HOOK_VERSION: None }
  try:
    icon_map = load_icon_map(_resolve_icon_map_path(vault, getattr(args, "icon_map", None)))
  except IconizeError:
    icon_map = None
  if icon_map is not None:
    schema = icon_map.get(MapKey.SCHEMA_VERSION, 1)
    min_hv = icon_map.get(MapKey.MIN_HOOK_VERSION)
    schema_block[VersionStatus.DECLARED] = schema
    schema_block[MapKey.MIN_HOOK_VERSION] = min_hv if isinstance(min_hv, str) else None
    compatible = isinstance(schema, int) and schema in SUPPORTED_SCHEMA
    if compatible and isinstance(min_hv, str):
      required = _parse_semver(min_hv)
      if required is not None and current < required:
        compatible = False
    schema_block[ResultKey.STATUS] = VersionStatus.OK if compatible else VersionStatus.INCOMPATIBLE

  drift = (pre_status in (VersionStatus.MISSING, VersionStatus.MAJOR_DRIFT)
           or schema_block[ResultKey.STATUS] == VersionStatus.INCOMPATIBLE)
  report = {
    ResultKey.OP: "check-versions",
    "HOOK_VERSION": HOOK_VERSION,
    "SCHEMA_VERSION": SCHEMA_VERSION,
    "SUPPORTED_SCHEMA": sorted(SUPPORTED_SCHEMA),
    "pre_commit": {
      "installed": ".".join(map(str, pre)) if pre else None,
      ResultKey.STATUS: pre_status,
    },
    "icon_map_schema": schema_block,
  }
  print(json.dumps(report, ensure_ascii = False))
  return EXIT_VERSION_DRIFT if drift else EXIT_OK


DISPATCH = {
  "sync": cmd_sync,
  "sync-staged": cmd_sync_staged,
  "reconcile": cmd_reconcile,
  "reconcile-plugin": cmd_reconcile_plugin,
  "reconcile-dirty": cmd_reconcile_dirty,
  "install-hooks": cmd_install_hooks,
  "check-versions": cmd_check_versions,
}


def main(argv: list[str] | None = None) -> int:
  """
  Worker entry point: parse CLI arguments and dispatch to the requested subcommand.

  Args:
    argv: Optional argument list; when None, falls back to the process argv.

  Returns:
    Process exit code emitted by the dispatched subcommand, or a validation code when
    arguments are malformed.
  """
  args = build_parser().parse_args(argv)
  if args.version:
    print(f"protocol_version={PROTOCOL_VERSION} hook_version={HOOK_VERSION}")
    return EXIT_OK
  if args.validate_entry:
    try:
      entry = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
      print(f"invalid JSON: {e}", file = sys.stderr)
      return EXIT_VALIDATION
    try:
      validate_icon_name(entry.get(IconKey.NAME, ""))
      if entry.get(IconKey.COLOR):
        validate_color(entry[IconKey.COLOR])
    except IconizeError as e:
      print(f"error: {e}", file = sys.stderr)
      return EXIT_VALIDATION
    return EXIT_OK
  # guard: no subcommand supplied → print usage and exit with validation code
  if not args.cmd:
    # waiver: one-off human-facing message
    print(
      "usage: iconize_sync <sync|sync-staged|reconcile|reconcile-plugin|reconcile-dirty"
      "|install-hooks|check-versions> ...",
      file = sys.stderr)
    return EXIT_VALIDATION
  handler = DISPATCH.get(args.cmd)
  # guard: unknown subcommand (later tasks may land additional handlers)
  if handler is None:
    return EXIT_VALIDATION
  try:
    return handler(args)
  except IconizeError as e:
    sys.stderr.write(f"iconize_sync: {e}\n")
    return e.code
  except Exception as e:
    sys.stderr.write(f"iconize_sync: unexpected: {e}\n")
    return EXIT_VALIDATION


# ----------------------------------------------------------------------------------------
# Icon-map loader + registry lookup helpers
# ----------------------------------------------------------------------------------------

INTERP_RE = re.compile(r"\{\{\s*(frontmatter\.[A-Za-z0-9_]+|basename(?:\.stem)?)\s*\}\}")


def load_icon_map(path: str | Path) -> dict:
  """
  Load and structurally validate the icon-map JSON document.

  Ensures the document parses, contains a `matchers` list, and that `registries` and
  `stage_colors` either exist as objects or are defaulted to empty objects.

  Args:
    path: Filesystem path to the icon-map JSON file.

  Returns:
    Parsed icon-map dict with defaults applied.

  Raises:
    IconizeError: When the file is missing, contains invalid JSON, or fails structural
      validation.
  """
  p = Path(path)
  # guard: file must exist
  if not p.exists():
    raise IconizeError(f"icon-map not found at {p}", EXIT_VALIDATION)
  try:
    # waiver: stdlib encoding-mode idiom
    m = json.loads(p.read_text(encoding = "utf-8"))
  except json.JSONDecodeError as e:
    raise IconizeError(f"icon-map invalid JSON: {e}", EXIT_VALIDATION) from e
  # guard: top-level must be an object with a 'matchers' key
  if not isinstance(m, dict) or MapKey.MATCHERS not in m:
    raise IconizeError("icon-map missing 'matchers'", EXIT_VALIDATION)
  # guard: matchers must be a list
  if not isinstance(m[MapKey.MATCHERS], list):
    raise IconizeError("icon-map 'matchers' must be a list", EXIT_VALIDATION)
  m.setdefault(MapKey.REGISTRIES, {})
  m.setdefault(MapKey.STAGE_COLORS, {})
  # guard: registries must be an object
  if not isinstance(m[MapKey.REGISTRIES], dict):
    raise IconizeError("icon-map 'registries' must be an object", EXIT_VALIDATION)
  # guard: stage_colors must be an object
  if not isinstance(m[MapKey.STAGE_COLORS], dict):
    raise IconizeError("icon-map 'stage_colors' must be an object", EXIT_VALIDATION)
  return m


def lookup_dotted(root: dict, dotted: str) -> object:
  """
  Resolve a dotted lookup path inside a nested dictionary.

  Args:
    root: Top-level mapping to traverse.
    dotted: Dotted lookup expression (e.g. `registries.icon-pool`).

  Returns:
    The resolved value, or None when any segment is missing or the traversal encounters
    a non-dict before the path is exhausted.
  """
  cur = root
  for part in dotted.split("."):
    # guard: cannot descend further when the current node is not a dict or is missing the key
    if not isinstance(cur, dict) or part not in cur:
      return None
    cur = cur[part]
  return cur


def interpolate(template: str, frontmatter: dict, basename: str) -> str:
  """
  Substitute `{{frontmatter.<key>}}`, `{{basename}}`, and `{{basename.stem}}` tokens.

  Performs a single pass with no recursion and no nested `{{}}` handling. Unrecognized
  tokens pass through literally; the caller's registry lookup misses and the matcher
  fails silently per protocol spec. Missing frontmatter keys resolve to the empty string,
  and boolean / integer values stringify via `str()` (so `True` → `"True"`, `1` → `"1"`).

  Args:
    template: Template string possibly containing `{{...}}` tokens.
    frontmatter: Parsed frontmatter mapping providing values for `{{frontmatter.*}}` refs.
    basename: Vault-relative basename used for `{{basename}}` and `{{basename.stem}}`.

  Returns:
    The string with all recognized tokens replaced.
  """
  # guard: no token markers → return template verbatim
  if "{{" not in template:
    return template
  def sub(match: re.Match) -> str:
    """
    Resolve a single `{{...}}` capture to its replacement string.

    Args:
      match: Regex match object capturing the inner token reference.

    Returns:
      The replacement string for the captured token.
    """
    ref = match.group(1)
    if ref == InterpToken.BASENAME:
      return basename
    if ref == InterpToken.BASENAME_STEM:
      return basename.rsplit(".", 1)[0]
    # ref must start with "frontmatter." per INTERP_RE
    key = ref.split(".", 1)[1]
    v = frontmatter.get(key)
    return "" if v is None else str(v)
  return INTERP_RE.sub(sub, template)


# ----------------------------------------------------------------------------------------
# Matcher engine — `when` predicate evaluation
# ----------------------------------------------------------------------------------------

def _basename(path: str) -> str:
  """
  Return the final POSIX path segment.

  Args:
    path: POSIX path string.

  Returns:
    The substring after the last `/`, or the original path when no `/` is present.
  """
  return path.rsplit("/", 1)[-1] if "/" in path else path


_PATH_GLOB_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _path_glob_to_regex(pattern: str) -> re.Pattern[str]:
  """
  Translate a path glob into a fully-anchored compiled regex.

  Mirrors `PurePosixPath.full_match` (Python 3.13+) semantics:

  - `**/` matches zero or more path segments (including empty).
  - `**` at the end matches anything, including `/`.
  - `*` matches within a single segment and does not cross `/`.
  - `?` matches a single character (not `/`).

  Implemented inline so the worker runs on Python < 3.13 too — Obsidian-Git on macOS
  invokes `python3` via a non-login shell, which often resolves to `/usr/bin/python3`
  (system 3.9), where `full_match` does not exist. Compiled patterns are memoized in a
  process-local cache.

  Args:
    pattern: Glob pattern using the supported syntax.

  Returns:
    Compiled, anchored regex equivalent to the glob.
  """
  cached = _PATH_GLOB_RE_CACHE.get(pattern)
  # guard: return memoized compilation when available
  if cached is not None:
    return cached
  parts: list[str] = []
  i, n = 0, len(pattern)
  while i < n:
    c = pattern[i]
    if c == "*":
      if i + 1 < n and pattern[i + 1] == "*":
        if i + 2 < n and pattern[i + 2] == "/":
          parts.append(r"(?:[^/]+/)*")
          # waiver: inline numeric literal
          i += 3
        else:
          parts.append(r".*")
          i += 2
      else:
        parts.append(r"[^/]*")
        i += 1
    elif c == "?":
      parts.append(r"[^/]")
      i += 1
    else:
      parts.append(re.escape(c))
      i += 1
  compiled = re.compile(r"\A" + "".join(parts) + r"\Z")
  _PATH_GLOB_RE_CACHE[pattern] = compiled
  return compiled


def eval_when(when: dict, path: str, frontmatter: dict) -> bool:
  """
  Evaluate a matcher `when` block against a vault file.

  AND semantics apply across keys — every clause must hold for the matcher to be selected.
  Supported clauses are `basename`, `basename_in`, `path_glob`, `role_matches_basename`,
  `frontmatter.<key>`, and `callback`.

  Args:
    when: Mapping of predicate names to their expected values.
    path: Vault-relative POSIX path of the candidate file.
    frontmatter: Parsed frontmatter mapping for the candidate file.

  Returns:
    True when every clause is satisfied, False otherwise.

  Raises:
    IconizeError: When `basename_in` is not a list/tuple/set or when an unknown predicate
      key is encountered.
  """
  bn = _basename(path)
  for key, expected in when.items():
    if key == WhenKey.BASENAME:
      # guard: basename mismatch fails the whole block
      if bn != expected:
        return False
    elif key == WhenKey.BASENAME_IN:
      # guard: 'basename_in' must carry an iterable container
      if not isinstance(expected, (list, tuple, set)):
        # waiver: reporting the type name of an arbitrary YAML-supplied value; type(x).__name__ is the right idiom here — no project class-system object to query
        raise IconizeError(f"'basename_in' must be a list, got {type(expected).__name__}")
      # guard: basename must be in the container
      if bn not in expected:
        return False
    elif key == WhenKey.PATH_GLOB:
      # Mirrors PurePosixPath.full_match (3.13+): `**` crosses segments,
      # `*` does not. Polyfilled inline so older Python (e.g. macOS
      # /usr/bin/python3 = 3.9) used by Obsidian-Git hooks still works.
      # guard: path must match the glob
      if not _path_glob_to_regex(expected).match(path):
        return False
    elif key == WhenKey.ROLE_MATCHES_BASENAME:
      stem = bn.rsplit(".", 1)[0]
      # guard: frontmatter 'role' must equal the basename stem
      if frontmatter.get(FrontmatterKey.ROLE) != stem:
        return False
    elif key.startswith(WhenKey.FRONTMATTER_PREFIX):
      fkey = key.split(".", 1)[1]
      # guard: frontmatter value must equal the expected literal
      if frontmatter.get(fkey) != expected:
        return False
    elif key == WhenKey.CALLBACK:
      # Real implementation lands in Task 7 (callbacks).
      # guard: external callback must report a match
      if not _callback_when(expected, path, frontmatter):
        return False
    else:
      raise IconizeError(f"unknown 'when' predicate: {key!r}")
  return True


def _callback_dir(vault: Path | None = None) -> Path:
  """
  Return the directory where external callback scripts live for the vault.

  Honors the module-level `CALLBACK_DIR_OVERRIDE` for test contexts. Otherwise caches the
  vault discovered on first call so subsequent lookups skip the walk-up.

  Args:
    vault: Resolved vault root; when None the cached or freshly-discovered vault is used.

  Returns:
    Absolute path to `<vault>/.claude/callbacks` (or the override path).
  """
  # guard: test override wins
  if CALLBACK_DIR_OVERRIDE is not None:
    return Path(CALLBACK_DIR_OVERRIDE)
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  global _CALLBACK_VAULT_CACHE  # noqa: PLW0603  # pylint: disable=global-statement
  if vault is None:
    if _CALLBACK_VAULT_CACHE is None:
      _CALLBACK_VAULT_CACHE = find_vault(None)
    vault = _CALLBACK_VAULT_CACHE
  # waiver: filesystem path idiom (.claude/callbacks)
  return vault / ".claude" / "callbacks"


def _invoke_callback(callback_id: str, payload: dict) -> dict | None:
  """
  Invoke an external callback script and return its parsed JSON response.

  The callback executable must live under the vault's callback directory, be executable,
  and emit valid JSON on stdout. Any failure mode — missing executable, timeout, non-zero
  exit, non-JSON output — is reported on stderr and surfaced to the caller as None.

  Args:
    callback_id: Filename of the callback script under the callback directory.
    payload: JSON-serializable payload sent to the callback on stdin.

  Returns:
    Parsed JSON response from the callback, or None on any failure.
  """
  cb_path = _callback_dir() / callback_id
  # guard: callback must exist and be executable
  if not cb_path.is_file() or not os.access(cb_path, os.X_OK):
    return None
  try:
    # waiver: inline numeric literal
    r = subprocess.run([ str(cb_path) ], input = json.dumps(payload),
                       capture_output = True, text = True, timeout = 10, check = False)
  except subprocess.TimeoutExpired as e:
    out = "".join(
      # waiver: stdlib encoding-mode idiom
      c.decode("utf-8", "replace") if isinstance(c, bytes) else (c or "")
      for c in (e.stdout, e.stderr)
    )
    sys.stderr.write(f"callback {callback_id!r} timed out: {out}\n")
    return None
  except OSError as e:
    sys.stderr.write(f"callback {callback_id!r} failed: {e}\n")
    return None
  # guard: non-zero exit → no result
  if r.returncode != 0:
    sys.stderr.write(f"callback {callback_id!r}: {r.stderr}")
    return None
  try:
    return json.loads(r.stdout)
  except json.JSONDecodeError:
    sys.stderr.write(f"callback {callback_id!r} returned non-JSON\n")
    return None


def _callback_when(callback_id: str, path: str, frontmatter: dict) -> bool:
  """
  Ask an external callback whether a `when` clause matches the given file.

  Args:
    callback_id: Filename of the callback under the callback directory.
    path: Vault-relative POSIX path of the candidate file.
    frontmatter: Parsed frontmatter mapping for the candidate file.

  Returns:
    True when the callback explicitly reports `{"match": true}`, False otherwise.
  """
  r = _invoke_callback(callback_id,
                       { CallbackKey.OP: "when", CallbackKey.PATH: path, CallbackKey.FRONTMATTER: frontmatter })
  return bool(r and r.get(CallbackKey.MATCH) is True)


# ----------------------------------------------------------------------------------------
# Matcher engine — `resolve` + base/overlays + emit
# ----------------------------------------------------------------------------------------

def _resolve_field(spec: object, icon_map: dict, frontmatter: dict, basename: str) -> str | None:
  """
  Resolve a single field specification to its concrete string value.

  A spec is either a literal string (with optional `{{...}}` placeholders) or a
  registry-lookup object of the shape `{from, key, field?}`. Returns None when the
  registry lookup misses or returns a non-string value where one is required.

  Args:
    spec: Field specification, literal or lookup object.
    icon_map: Parsed icon-map dict providing the registry root.
    frontmatter: Parsed frontmatter mapping for the candidate file.
    basename: Vault-relative basename used in interpolation.

  Returns:
    The resolved string value, or None when resolution fails.
  """
  if isinstance(spec, str):
    return spec if "{{" not in spec else interpolate(spec, frontmatter, basename)
  if isinstance(spec, dict) and MapKey.FROM in spec:
    reg = lookup_dotted(icon_map, spec[MapKey.FROM])
    # guard: missing or non-dict registry → no value
    if not isinstance(reg, dict):
      return None
    key = interpolate(spec[MapKey.KEY], frontmatter, basename)
    # guard: empty key → no value
    if not key:
      return None
    val = reg.get(key)
    # guard: registry miss → no value
    if val is None:
      return None
    field = spec.get(MapKey.FIELD)
    if field is None:
      return val if isinstance(val, str) else None  # flat map
    if isinstance(val, dict):
      return val.get(field)
    return None
  return None


def _build_entry(resolve_spec: dict, icon_map: dict, frontmatter: dict, basename: str, path: str) -> dict | None:
  """
  Execute a `resolve` block and return the resulting icon entry.

  Supports three shapes: a direct `{iconName, iconColor?}` block, a `{base, overlays}`
  composition (overlays are sorted by descending priority, ties broken by declaration
  order via a stable sort), and a `{callback}` external resolution. The `path` argument
  is the full vault-relative path; it is required so overlay `when` blocks with
  `path_glob` or other path-aware predicates evaluate correctly.

  Args:
    resolve_spec: Resolve block from a matcher entry.
    icon_map: Parsed icon-map dict providing the registry root.
    frontmatter: Parsed frontmatter mapping for the candidate file.
    basename: Vault-relative basename used in interpolation.
    path: Full vault-relative POSIX path of the candidate file.

  Returns:
    Resolved icon entry as `{"iconName": ..., "iconColor"?: ...}`, or None when no name
    could be resolved.
  """
  if IconKey.NAME in resolve_spec or IconKey.COLOR in resolve_spec:
    name = _resolve_field(resolve_spec.get(IconKey.NAME), icon_map, frontmatter, basename)
    # guard: no name → no entry
    if not name:
      return None
    entry = { IconKey.NAME: name }
    color = _resolve_field(resolve_spec.get(IconKey.COLOR), icon_map, frontmatter, basename)
    if color:
      entry[IconKey.COLOR] = color
    return entry
  if MapKey.BASE in resolve_spec:
    base = _build_entry(resolve_spec[MapKey.BASE], icon_map, frontmatter, basename, path)
    overlays = sorted(resolve_spec.get(MapKey.OVERLAYS, []),
                      key = lambda o: -int(o.get(MapKey.PRIORITY, 0)))
    for ov in overlays:
      if eval_when(ov.get(MapKey.WHEN, {}), path, frontmatter):
        entry = dict(base) if base else {}
        if IconKey.NAME in ov:
          entry[IconKey.NAME] = ov[IconKey.NAME]
        if IconKey.COLOR in ov:
          entry[IconKey.COLOR] = ov[IconKey.COLOR]
        return entry if IconKey.NAME in entry else None
    return base
  if MapKey.CALLBACK in resolve_spec:
    return _callback_resolve(resolve_spec[MapKey.CALLBACK], frontmatter, icon_map)
  return None


def _callback_resolve(callback_id: str, frontmatter: dict, icon_map: dict) -> dict | None:
  """
  Resolve an icon entry via an external callback.

  Args:
    callback_id: Filename of the callback under the callback directory.
    frontmatter: Parsed frontmatter mapping passed to the callback.
    icon_map: Parsed icon-map dict passed to the callback for registry lookups.

  Returns:
    Resolved icon entry as `{"iconName": ..., "iconColor"?: ...}`, or None when the
    callback declines to resolve.
  """
  r = _invoke_callback(callback_id,
                       { CallbackKey.OP: "resolve", CallbackKey.FRONTMATTER: frontmatter,
                         CallbackKey.ICON_MAP: icon_map })
  # guard: callback declined or returned no name
  if not r or not r.get(IconKey.NAME):
    return None
  entry = { IconKey.NAME: r[IconKey.NAME] }
  if r.get(IconKey.COLOR):
    entry[IconKey.COLOR] = r[IconKey.COLOR]
  return entry


def resolve_matchers(icon_map: dict, path: str, frontmatter: dict) -> list:
  """
  Apply the icon-map matchers to a single file and return the resulting emission list.

  Walks the matchers in order; the first matcher whose `when` predicate holds drives the
  resolution. Under schema 2 the result is either `[]` (no match or empty resolution) or
  a single-element list `[(self_path, entry)]`.

  Args:
    icon_map: Parsed icon-map dict.
    path: Vault-relative POSIX path of the candidate file.
    frontmatter: Parsed frontmatter mapping for the candidate file.

  Returns:
    Emission list for the candidate file; empty when no matcher applies.
  """
  basename = _basename(path)
  for matcher in icon_map.get(MapKey.MATCHERS, []):
    when = matcher.get(MapKey.WHEN, {})
    # guard: skip entries whose when-condition does not match this path
    if not eval_when(when, path, frontmatter):
      continue
    entry = _build_entry(matcher.get(MapKey.RESOLVE, {}), icon_map, frontmatter, basename, path)
    # guard: matcher matched but resolution failed → return [] (no further matchers attempted)
    if not entry:
      return []
    return [ (normalize_path(path), entry) ]
  return []


if __name__ == "__main__":
  sys.exit(main())
