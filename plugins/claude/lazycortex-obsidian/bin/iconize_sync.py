#!/usr/bin/env python3

"""
Generic iconize-sync worker for the lazycortex-obsidian plugin.

Resolves Obsidian file icons from a declarative icon-map and writes the result into each
note's `iconize_icon` / `iconize_color` frontmatter keys. Exposes subcommands invoked by
Claude Code's PostToolUse hook, daemon routines, and the operator directly; never blocks
a commit when the icon-map is missing or incompatible — hooks stay inert in that case.

See plugins/claude/lazycortex-obsidian/references/lazy-obsidian.iconize-protocol.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from icon_keys import (  # pylint: disable=import-error
  CallbackKey, FrontmatterKey, IconKey, InterpToken, MapKey,
  ResultKey, VersionStatus, WhenKey, YamlScalar,
)
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from shebang_launch import ShebangError, argv_for  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from frontmatter_rewriter import rewrite_file, rewrite_frontmatter  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import NoReturn


PROTOCOL_VERSION = "2.3.2"
HOOK_VERSION = "4.0.0"

# Schema versioning for icon-map.json (bilateral handshake).
# - SCHEMA_VERSION: the version this worker writes on install/migrate.
# - SUPPORTED_SCHEMA: integers this worker can consume at runtime; mismatch → preflight
#   exits the hook cleanly (EXIT_OK) with a stderr diagnostic. Consumers bump by re-running
#   lazy-obsidian.iconize-install.
SCHEMA_VERSION = 2
SUPPORTED_SCHEMA = { 2 }

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_VERSION_DRIFT = 5
EXIT_COMMIT_FAILED = 6

# The `sync` path argument that means "read the Claude Code hook payload from stdin", and the
# suffix of the only files the hook repaints.
_STDIN_PATH = "-"
_NOTE_SUFFIX = ".md"
# The PostToolUse payload fields naming the written file: the tool's response first, its input second.
_HOOK_RESPONSE, _HOOK_RESPONSE_PATH = "tool_response", "filePath"
_HOOK_INPUT, _HOOK_INPUT_PATH = "tool_input", "file_path"
# The schema-1 keys the 1 → 2 migration drops: the legacy top-level version string and each matcher's `emit`.
_LEGACY_VERSION_KEY, _LEGACY_EMIT_KEY = "version", "emit"
# The icon-map's text encoding, and the suffix of the sibling a rewrite goes through before its rename.
_MAP_ENCODING, _TMP_SUFFIX = "utf-8", ".tmp"

# ----------------------------------------------------------------------------------------
# Repaint identity, caches, registry constants and vault discovery
# ----------------------------------------------------------------------------------------

# Subject every icon-repaint commit carries, so the routine's own commits are recognisable
# in history and by any watcher that filters on them.
ICON_COMMIT_SUBJECT = "chore(icons): repaint after commit"

# The two frontmatter lines this worker owns — the only divergence from HEAD an automated
# repaint commit is allowed to carry (`_has_non_icon_divergence`).
_ICON_LINE_RE = re.compile(r"^\s*iconize_(?:icon|color)\s*:")
# A frontmatter scalar the flat parser reads as an integer: ASCII digits with at most one leading minus.
_INT_SCALAR_RE = re.compile(r"-?[0-9]+")
# A unified-diff hunk header, capturing the first old-side and new-side line numbers.
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# Bot identity + trailer on every repaint commit. The `@bot.` email marks the commit as
# system-authored for sibling coordinators (specs matches the substring; review matches a
# registered `experts` entry seeded at install time), so a repaint never reads as an
# operator edit and never wakes a coordinator.
BOT_NAME = "lazy-obsidian.repaint"
BOT_EMAIL = "lazy-obsidian.repaint@bot.invalid"
ICON_COMMIT_TRAILER = "Lazy-Bot: lazy-obsidian.repaint"

# opt: vault memoized — valid while every note resolution re-pins it to the vault it resolved before a callback runs
# waiver: a module function's memo shared by every caller; moving it onto an instance would change every call site
_CALLBACK_VAULT_CACHE = None

# Plugin-shipped iconize registries — runtime layer discovery. Every installed plugin may
# ship `references/<ns>.iconize-registry.json` files; the worker reads them on every run
# and folds their matchers under the vault's personal icon-map. No install-time merge.
PLUGIN_DIRS_ENV = "LAZYCORTEX_PLUGIN_DIRS"
REGISTRY_SUFFIX = ".iconize-registry.json"
# waiver: external Claude Code registry path, not an internal key
_INSTALLED_PLUGINS_REL = ".claude/plugins/installed_plugins.json"
REGISTRY_SCHEMA_VERSION = 1

# Semantic priority bands for registry matchers (see the iconize registry contract):
# 500-599 error/blocker, 400-499 operator action, 300-399 transient process,
# 200-299 permanent status, 100-199 base/decor. A registry matcher outside the bands is
# skipped with a stderr diagnostic. Operator matchers without a `priority` float above
# every band, so legacy personal rules keep beating plugin rules until the operator
# assigns an explicit band.
PRIORITY_BAND_MIN = 100
PRIORITY_BAND_MAX = 599
OPERATOR_DEFAULT_PRIORITY = 1000

# Internal provenance key injected into plugin-layer matchers by compose_layers so the
# callback engine can resolve a matcher's callbacks from its shipping plugin's own tree.
# Never present in any JSON document on disk.
_MATCHER_CB_ROOT = "_callback_root"
# The note-side frontmatter key holding the icon a state rule borrows through
# `{{frontmatter.iconize_icon}}`. Read only as the fallback for a colour-only resolution.
_NOTE_ICON_KEY = "iconize_icon"
# The self-referential name token a state rule writes to say "whatever icon this note's type gives
# it". A rule carrying it names no icon of its own, however the note is currently painted.
_SELF_BORROW_TOKEN = f"{{{{frontmatter.{_NOTE_ICON_KEY}}}}}"
# waiver: module-level mutable — ambient callback-root of the matcher being evaluated; threading it
# through eval_when → _build_entry → _invoke_callback would widen four signatures for one read
_ACTIVE_CB_ROOT: Path | None = None

# A note's leading YAML frontmatter block, capturing the lines between the two `---` fences.
FM_BLOCK_RE = re.compile(r"(?ms)\A---\s*\n(.*?\n)^---\s*\n")
# An icon colour: a three- or six-digit hex code, lowercase only.
COLOR_RE = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$")
# An icon name made of ASCII letters, digits, underscores and hyphens.
ICON_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
# Rejection text for an empty, padded, or whitespace-bearing icon name, formatted with the `name`.
ICON_NAME_INVALID = "invalid iconName {name!r}"
# Rejection text for an icon name matching neither accepted shape, formatted with the `name`.
ICON_NAME_UNRECOGNIZED = "iconName not recognized: {name!r}"
# Rejection text for an icon name that is not a string, formatted with the `name`.
ICON_NAME_NOT_STRING = "invalid iconName {name!r} (want a string)"
# Rejection text for a color outside the accepted lowercase hex shapes, formatted with the `color`.
COLOR_INVALID = "invalid color {color!r} (want lowercase #rgb or #rrggbb)"
# Rejection text for a color that is not a string, formatted with the `color`.
COLOR_NOT_STRING = "invalid color {color!r} (want a string)"
# Rejection text for a vault override that names no directory, formatted with the resolved `vault`.
VAULT_NOT_DIRECTORY = "vault override is not a directory: {vault}"
# Rejection text for a vault discovery that finds no enclosing git repository.
VAULT_NOT_FOUND = "vault not found: not inside a git repository"
# Rejection text for an empty vault-relative path.
PATH_EMPTY = "path is empty"
# Rejection text for an absolute path, formatted with the `path`.
PATH_NOT_VAULT_RELATIVE = "path must be vault-relative: {path!r}"
# Rejection text for a home-relative path, formatted with the `path`.
PATH_HOME_RELATIVE = "path must be vault-relative, not home-relative: {path!r}"
# Rejection text for a path with backslash separators, formatted with the `path`.
PATH_NOT_POSIX = "path must use POSIX separators: {path!r}"
# Rejection text for a path that normalizes to nothing.
PATH_EMPTY_NORMALIZED = "path is empty after normalization"
# Rejection text for an icon-map path that does not exist, formatted with the `path`.
ICON_MAP_NOT_FOUND = "icon-map not found at {path}"
# Rejection text for an icon-map that does not parse, formatted with the decode `error`.
ICON_MAP_INVALID_JSON = "icon-map invalid JSON: {error}"
# Rejection text for an icon-map without a top-level `matchers` key.
ICON_MAP_MISSING_MATCHERS = "icon-map missing 'matchers'"
# Rejection text for an icon-map whose `matchers` is not a list.
ICON_MAP_MATCHERS_NOT_LIST = "icon-map 'matchers' must be a list"
# Rejection text for an icon-map with a matcher that is not an object.
ICON_MAP_MATCHER_NOT_OBJECT = "icon-map 'matchers' entries must be objects"
# Rejection text for an icon-map whose `registries` is not an object.
ICON_MAP_REGISTRIES_NOT_OBJECT = "icon-map 'registries' must be an object"
# Rejection text for an icon-map whose `stage_colors` is not an object.
ICON_MAP_STAGE_COLORS_NOT_OBJECT = "icon-map 'stage_colors' must be an object"
# Rejection text for a `basename_in` predicate over a non-container, formatted with the value's type `kind`.
BASENAME_IN_NOT_LIST = "'basename_in' must be a list, got {kind}"
# Rejection text for a `when` predicate the matcher dialect does not define, formatted with the `key`.
WHEN_PREDICATE_UNKNOWN = "unknown 'when' predicate: {key!r}"
# The `--version` report line, formatted with the `protocol` and `hook` versions.
VERSION_LINE = "protocol_version={protocol} hook_version={hook}"
# Phrase every inert-hook diagnostic carries.
HOOK_INERT = "hook inert"
# Diagnostic for an icon-map that fails to load, formatted with the load `error` and the `inert` phrase.
MAP_LOAD_INERT = "iconize_sync: {error}; {inert}.\n"
# Diagnostic for an unsupported icon-map schema, formatted with the `schema` read, the `supported` list, and
# the `inert` phrase.
SCHEMA_UNSUPPORTED_INERT = (
  "iconize_sync: icon-map schema_version={schema!r} not in {supported}; "
  "{inert}. Run lazy-obsidian.iconize-install to migrate.\n"
)
# Diagnostic for a worker older than the icon-map's floor, formatted with the worker `hook` version, the
# `floor` the map requires, and the `inert` phrase.
HOOK_TOO_OLD_INERT = (
  "iconize_sync: HOOK_VERSION {hook} < icon-map min_hook_version {floor}; "
  "{inert}. Upgrade lazycortex-obsidian plugin.\n"
)
# Phrase every dropped-registry diagnostic carries.
REGISTRY_SKIPPED = "registry skipped"
# Diagnostic for an unreadable registry, formatted with the `path`, the read `error`, and the `skipped` phrase.
REGISTRY_UNREADABLE = "iconize_sync: registry {path}: {error}; {skipped}.\n"
# Diagnostic for a registry that is not an object, formatted with the `path` and the `skipped` phrase.
REGISTRY_NOT_OBJECT = "iconize_sync: registry {path}: not an object; {skipped}.\n"
# Diagnostic for a registry of another schema generation, formatted with the `path`, the `found` and
# `expected` versions, and the `skipped` phrase.
REGISTRY_SCHEMA_MISMATCH = "iconize_sync: registry {path}: schema_version={found!r} != {expected}; {skipped}.\n"
# Diagnostic for a registry whose `matchers` is not a list, formatted with the `path` and the `skipped` phrase.
REGISTRY_MATCHERS_NOT_LIST = "iconize_sync: registry {path}: 'matchers' must be a list; {skipped}.\n"
# Diagnostic for a registry matcher outside the priority bands, formatted with the `plugin`, the `priority`,
# and the band's `low` and `high` ends.
PRIORITY_OUTSIDE_BANDS = (
  "iconize_sync: registry {plugin}: matcher priority {priority!r} outside bands "
  "{low}-{high}; matcher skipped.\n"
)
# Top-level vault directories whose notes are never painted.
_EXCLUDED_DIRS = (".obsidian", ".git", ".claude", ".githooks")
# A `MAJOR.MINOR.PATCH` version string, surrounding whitespace allowed.
SEMVER_RE = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)\s*$")
# A `{{frontmatter.<key>}}`, `{{basename}}` or `{{basename.stem}}` interpolation token.
INTERP_RE = re.compile(r"\{\{\s*(frontmatter\.[A-Za-z0-9_]+|basename(?:\.stem)?)\s*\}\}")
# opt: compiled once per glob — the regex depends on the pattern text alone, never on the path or the vault
# waiver: a module function's memo shared by every caller; moving it onto an instance would change every call site
_PATH_GLOB_RE_CACHE: dict[str, re.Pattern[str]] = {}


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


def find_vault_git_root(start: Path) -> Path | None:
  """
  Return the git toplevel of the repository containing `start`.

  Args:
    start: Filesystem path to resolve the enclosing repository for.

  Returns:
    The repository toplevel as an absolute path, or None when `start` is not inside a
    git repository (or git itself is unavailable).
  """

  # Decision: the vault root is the git toplevel, not an `.obsidian/`-marked ancestor — the
  # icon-map lives under `.claude/` and every note path is repo-relative, while `.obsidian/`
  # is untracked since the vault-manifest migration and absent from headless checkouts.

  # resolve the enclosing repository through git itself
  # waiver: git CLI vocabulary, not domain constants
  try:
    proc = subprocess.run(
      ["git", "-C", os.path.abspath(start), "rev-parse", "--show-toplevel"],
      check = False, capture_output = True, text = True, encoding = "utf-8"
    )
  except OSError:
    # guard: git binary unavailable — no repository can be resolved
    return None

  # guard: not a git repository — there is no vault to resolve
  if proc.returncode != 0 or not (top := proc.stdout.strip()):
    return None
  return Path(top)


def find_vault(override: str | None) -> Path:
  """
  Return the vault root, either from an explicit override or as the git toplevel of the cwd.

  Args:
    override: Caller-supplied vault path; when set it must name an existing directory.

  Returns:
    Absolute path to the resolved vault root.

  Raises:
    IconizeError: When `override` is provided but does not name an existing directory, or
      when the current working directory is not inside a git repository.
  """
  # an explicit override path takes precedence over discovery
  if override:
    vault = Path(os.path.abspath(Path(override).expanduser()))

    # guard: override must name an existing directory
    if not vault.is_dir():
      raise IconizeError(VAULT_NOT_DIRECTORY.format(vault = vault))
    return vault
  found = find_vault_git_root(Path.cwd())

  # guard: discovery failed
  if found is None:
    raise IconizeError(VAULT_NOT_FOUND)
  return found


# ----------------------------------------------------------------------------------------
# Frontmatter parser + entry validators
# ----------------------------------------------------------------------------------------


def parse_frontmatter(text: str) -> dict:
  """
  Parse the YAML frontmatter block at the start of a markdown document.

  Supports a flat key/value subset: quoted or bare strings, booleans `true` / `false`, and
  integers. Nested structures, lists, and multi-line values are not supported.

  Guarantees:
    - Only the exact unquoted spellings `true` and `false` are read as booleans, and only an unquoted value made
      of digits alone, with an optional leading minus, is read as an integer.
    - Every other value, quoted or unquoted, is read as a string, and a quoted value loses its surrounding quotes.

  Args:
    text: Full markdown document text, expected to start with a `---` fenced block.

  Returns:
    Mapping of frontmatter keys to their parsed values. Returns an empty dict when no
    frontmatter block is present.
  """

  # Contract:
  # Only the exact unquoted spellings `true` and `false` are read as booleans, and only an unquoted
  # value made of digits alone, with an optional leading minus, is read as an integer.

  # Contract:
  # Every other value, quoted or unquoted, is read as a string, and a quoted value loses its
  # surrounding quotes.

  # locate the frontmatter block at the very start of the document
  block = FM_BLOCK_RE.match(text)

  # guard: no frontmatter block at the start of the document
  if not block:
    return {}
  out: dict = {}
  for line in block.group(1).splitlines():
    # waiver: the loop variable is deliberately rebound — each line is normalised in place before use
    line = line.rstrip()  # noqa: PLW2901

    # guard: skip blank and comment lines
    if not line or line.startswith("#"):
      continue

    # guard: lines without a colon are not key/value entries
    if ":" not in line:
      continue
    raw_key, _, raw_value = line.partition(":")
    key = raw_key.strip()
    value = raw_value.strip()

    # guard: keys must be non-empty
    if not key:
      continue
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
      out[key] = value[1:-1]
    elif value == YamlScalar.TRUE:
      out[key] = True
    elif value == YamlScalar.FALSE:
      out[key] = False
    elif _INT_SCALAR_RE.fullmatch(value):
      out[key] = int(value)
    else:
      out[key] = value
  return out


def normalize_path(path: str) -> str:
  """
  Validate and normalize a vault-relative POSIX path.

  Strips a leading `./` segment and a trailing `/`. Rejects absolute paths, home-relative
  paths, and paths containing backslash separators.

  Args:
    path: Candidate vault-relative path.

  Returns:
    The normalized path string.

  Raises:
    IconizeError: When the path is empty, absolute, home-relative, or uses non-POSIX
      separators.
  """
  # guard: empty input is never valid
  if not path:
    raise IconizeError(PATH_EMPTY)

  # guard: absolute paths are rejected — vault-relative only
  if path.startswith("/"):
    raise IconizeError(PATH_NOT_VAULT_RELATIVE.format(path = path))

  # guard: home-relative paths are rejected
  if path.startswith("~"):
    raise IconizeError(PATH_HOME_RELATIVE.format(path = path))

  # guard: backslash separators are rejected (POSIX only)
  if "\\" in path:
    raise IconizeError(PATH_NOT_POSIX.format(path = path))

  # a leading `./` and a trailing `/` name the same path, so both are dropped
  normalized = path[2:] if path.startswith("./") else path
  normalized = normalized.rstrip("/")

  # guard: normalization must leave a non-empty path
  if not normalized:
    raise IconizeError(PATH_EMPTY_NORMALIZED)
  return normalized


def validate_color(color: str) -> None:
  """
  Validate a color literal against the accepted lowercase hex shapes.

  Args:
    color: Candidate color string.

  Raises:
    IconizeError: When the value is not a lowercase `#rgb` or `#rrggbb` literal.
  """
  # guard: only lowercase #rgb / #rrggbb literals are accepted
  if not COLOR_RE.match(color):
    raise IconizeError(COLOR_INVALID.format(color = color))


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

  # Domain(obsidian.icon-resolution):
  # # An icon can be named two different ways
  # An icon value is either a symbolic key naming an entry in the icon library — a plain identifier of
  # letters, digits, underscores, and hyphens of any length — or a literal emoji character used directly
  # as the icon itself, accepted as a short fallback shape rather than checked against the library. The
  # fallback is not verified to be an emoji: any value of at most eight characters is taken for one, so a
  # short word in another script passes too. Any longer value of another shape, and any value that is
  # empty, padded, or carries whitespace, names no icon at all.

  # guard: empty, padded, or whitespace-bearing values are rejected
  if not name or name.strip() != name or any(ch.isspace() for ch in name):
    raise IconizeError(ICON_NAME_INVALID.format(name = name))

  # ASCII identifier shape passes immediately
  if ICON_NAME_RE.match(name):
    return

  # short emoji grapheme passes as a soft fallback
  # waiver: inline numeric literal
  if len(name) <= 8:
    return
  raise IconizeError(ICON_NAME_UNRECOGNIZED.format(name = name))


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
  parser = _Parser(prog = "iconize_sync", description = "Obsidian iconize-sync worker.")
  # waiver: argparse CLI signature
  parser.add_argument("--version", action = "store_true", help = "print protocol_version and hook_version")
  # waiver: argparse CLI signature
  parser.add_argument("--validate-entry", action = "store_true",
                 help = "read {iconName, iconColor?} JSON from stdin; exit 0 if valid")
  # waiver: argparse CLI signature
  parser.add_argument("--vault", help = "vault root (default: git toplevel of cwd)")
  # waiver: argparse CLI signature
  parser.add_argument("--icon-map",
                      help = "path to icon-map (default: <repo>/.claude/iconize/obsidian-icon-map.json)")
  # waiver: argparse CLI signature
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature
  sub = parser.add_subparsers(dest = "cmd", parser_class = _Parser)
  # waiver: subcommand-name value (canonical home is the parser+dispatch map)
  for name in ("sync", "sync-paths", "reconcile", "reconcile-plugin", "reconcile-dirty",
               "reconcile-commit", "check-versions", "migrate-1-to-2"):
    sub_parser = sub.add_parser(name)
    # waiver: subcommand-name value (canonical home is the parser+dispatch map)
    if name == "sync":
      # waiver: argparse CLI signature
      sub_parser.add_argument("path", help = "file path relative to vault root; `-` reads a hook payload from stdin")
    # waiver: subcommand-name value (canonical home is the parser+dispatch map)
    if name == "sync-paths":
      # waiver: argparse CLI signature
      sub_parser.add_argument("paths", nargs = "+", help = "file paths relative to vault root")
    # waiver: subcommand-name value (canonical home is the parser+dispatch map)
    if name == "reconcile-commit":
      # waiver: argparse CLI signature
      sub_parser.add_argument("item", nargs = "?", help = "commit sha, or the JSON item a git-watch routine passes")
    # waiver: subcommand-name value (canonical home is the parser+dispatch map)
    if name == "reconcile":
      # waiver: argparse CLI signature
      sub_parser.add_argument("--prefix", help = "only reconcile entries whose path starts with this prefix")
    # waiver: subcommand-name value (canonical home is the parser+dispatch map)
    if name == "migrate-1-to-2":
      # waiver: argparse CLI signature
      sub_parser.add_argument("icon_map_path", help = "icon-map JSON rewritten in place from schema 1 to schema 2")
    # waiver: subcommand-name value (canonical home is the parser+dispatch map)
    if name == "reconcile-plugin":
      # waiver: argparse CLI signature
      sub_parser.add_argument("plugin", help = "plugin name; reconcile only plugins/claude/<plugin>/")
  return parser


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
  # an explicit override path wins
  if override:
    return Path(override).expanduser().resolve()

  # Walk up from vault to find a .claude/iconize/obsidian-icon-map.json (repo root may be above vault).
  # Resolve symlinks once at entry so the walk crosses filesystem boundaries correctly.
  cur = vault.resolve()
  while True:
    # waiver: filesystem path idiom (.claude/.tmp/.md)
    cand = cur / ".claude" / "iconize" / "obsidian-icon-map.json"

    # the icon-map found at the current level is the answer
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
  Load the icon-map for hook contexts, returning None instead of raising when it cannot be used.

  Icons are cosmetic; hooks must never block a commit because of a missing or broken
  icon-map. Callers that receive None must short-circuit with the OK exit code so the
  hook stays inert. A diagnostic is written to stderr so a curious user can inspect why
  the hook went inert after removing any stderr redirection.

  Args:
    vault: Resolved vault root.
    override: Optional explicit icon-map path.

  Returns:
    Composed icon-map dict with plugin-registry layers folded in, or None when the
    personal icon-map is missing, invalid, or unreadable.
  """

  # Domain(obsidian.icon-repaint):
  # # Icons are cosmetic and never block a commit
  # Painting icons is decoration, so a vault whose icon-map is missing, invalid, or malformed must never be
  # prevented from committing because of it. Every icon hook context in that situation goes inert: it
  # succeeds without doing anything and says why on the error stream, so a curious operator can find the
  # cause by removing the stderr redirection instead of finding a silently dead hook.

  # any load failure is reported and turned into None rather than propagated
  try:
    path = _resolve_icon_map_path(vault, override)
    return compose_layers(load_icon_map(path), load_plugin_registries(vault))
  except (IconizeError, OSError, UnicodeDecodeError) as error:
    sys.stderr.write(MAP_LOAD_INERT.format(error = error, inert = HOOK_INERT))
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
  note_path = vault / vault_rel

  # guard: missing target yields empty frontmatter
  if not note_path.is_file():
    return {}
  # waiver: stdlib encoding-mode idiom
  return parse_frontmatter(note_path.read_text(encoding = "utf-8", errors = "ignore"))


def is_template_path(rel: str) -> bool:
  """
  Report whether a vault-relative path belongs to a scaffolding-template tree.

  Template files carry the live frontmatter of the notes they scaffold (`spec_stage`,
  `spec_role`, …), so a frontmatter-matching rule fires on the template itself. Painting
  one dirties a shipped source file on every reconcile and seeds every scaffolded note
  with a stale icon.

  Args:
    rel: Vault-relative POSIX path.

  Returns:
    True for a plugin's own `plugins/claude/<plugin>/templates/**` tree and for the consumer's
    `.claude/templates/**` override tree.
  """

  # Domain(obsidian.icon-resolution):
  # # A scaffolding template is exempt from every icon rule
  # A template file carries the same frontmatter shape as the notes it later produces, so a rule keyed on
  # frontmatter would otherwise match the template as readily as it matches a real note. Painting a
  # template is a domain error regardless of what any rule resolves to: it dirties a shipped source file
  # on every pass, and every note scaffolded from it afterward inherits a stale icon baked in at creation.
  # Template trees are therefore excluded from icon resolution entirely, ahead of any rule being consulted.

  # split the path into its segments to test the template-tree conventions below
  parts = rel.split("/")
  # waiver: filesystem path idioms — `plugins/claude` / `.claude` / `templates` are fixed layout tokens
  # a plugin's own shipped templates, `plugins/claude/<plugin>/templates/...`
  if len(parts) > 4 and parts[0] == "plugins" and parts[1] == "claude" and parts[3] == "templates":
    return True

  # the consumer's own override tree lives directly under `.claude/`
  # waiver: filesystem path idioms — `.claude` / `templates` are fixed layout tokens
  return len(parts) > 2 and parts[0] == ".claude" and parts[1] == "templates"


def _is_in_paint_roots(icon_map: dict, rel: str) -> bool:
  """
  Report whether a vault-relative path lies inside the icon-map's declared paint roots.

  An icon-map that declares no `paint_roots` list puts the entire vault in scope.

  Args:
    icon_map: Composed icon-map dict.
    rel: Vault-relative POSIX path of the note.

  Returns:
    True when the icon-map declares no paint roots, or when the path sits under one of the
    declared directory prefixes; False otherwise.
  """

  # Domain(obsidian.icon-resolution):
  # # Icon painting can be scoped to a subset of the vault
  # A vault may declare a fixed list of directories icon painting is allowed to touch, so an unrelated
  # part of the vault is never considered for a rule match at all. A note outside every declared
  # directory is invisible to icon rules regardless of what its frontmatter would otherwise match: it is
  # never read for matching and never written, and its existing icon fields stay the business of whichever
  # other manager set them. When no such list is declared, whether the setting is absent or holds anything
  # other than a list, the whole vault stays in scope. Absence is never read as an empty set of
  # directories, which would exclude everything, so a vault authored before this option
  # existed keeps behaving exactly as it always did. A declared directory only claims a path that sits
  # under it as a real subdirectory, never a differently named sibling that merely shares its prefix.

  roots = icon_map.get(MapKey.PAINT_ROOTS)

  # a map that declares no root list keeps the whole vault in scope
  if not isinstance(roots, list):
    return True

  # a root claims a path only across a directory boundary, so `specs` never claims `specsheets/...`
  # waiver: filesystem path idiom (the POSIX separator)
  return any(isinstance(root, str) and rel.startswith(root.rstrip("/") + "/") for root in roots)


def _resolve_icon_pair(icon_map: dict, vault: Path, rel: str) -> tuple[str | None, str | None] | None:
  """
  Resolve the icon/color pair one note should carry, or report that no rule claims it.

  Scaffolding templates and notes outside the declared paint roots resolve to None like any
  unclaimed note. Callers must skip the rewrite entirely on a None return, so the note's
  existing `iconize_icon` / `iconize_color` stay untouched.

  Notes:
    - Changes process-wide state: every call replaces the vault that later callbacks in this process
      read their settings and operator overrides from with the given vault.

  Args:
    icon_map: Composed icon-map dict.
    vault: Resolved vault root.
    rel: Vault-relative POSIX path of the note.

  Returns:
    `(icon, color)` when a matcher resolved an entry, or None when the note lies outside the
    declared paint roots or no matcher claims it (including a matched matcher whose
    resolution produced nothing).
  """

  # the vault this command resolved is the one every callback reads settings from and finds its
  # operator overrides in — never the directory the worker happened to be started in
  # waiver: a genuine module-level rebind, not a false positive — the resolved vault pins the cache
  global _CALLBACK_VAULT_CACHE  # noqa: PLW0603  # pylint: disable=global-statement
  _CALLBACK_VAULT_CACHE = vault

  # guard: template trees are source, not vault content — no rule may claim them
  if is_template_path(rel):
    return None

  # guard: outside the declared paint roots — the note is ignored entirely
  if not _is_in_paint_roots(icon_map, rel):
    return None

  # every other path is decided by the composed matchers alone
  frontmatter = _read_frontmatter_for(vault, rel)
  entries = resolve_matchers(icon_map, rel, frontmatter)

  # Domain(obsidian.icon-repaint):
  # # A note with no matching rule is left exactly as another manager wrote it
  # More than one automation can be responsible for keeping different frontmatter fields of the same note
  # in sync, and icon resolution is not the sole owner of a note's icon fields. When no rule claims a note
  # at all, that is read as "this system has nothing to say about this note" rather than "this note should
  # carry no icon" — the note's existing icon fields, however another manager set them, are left completely
  # untouched instead of being cleared.

  # no rule claims this note — the caller must leave its icon keys untouched
  if not entries:
    return None
  _, entry = entries[0]

  # a colour-only entry means every rule that claimed the note only painted it and none named a
  # look: hand back whatever the note itself declares, so the key the TYPE owns stands as it is
  return entry.get(IconKey.NAME) or frontmatter.get(_NOTE_ICON_KEY), entry.get(IconKey.COLOR)


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
  if raw.startswith("~") or Path(raw).is_absolute():
    try:
      abs_path = Path(raw).expanduser().resolve()
      rel = abs_path.relative_to(vault.resolve())
    except (ValueError, OSError):
      # path is outside the vault — caller treats this as a silent no-op
      return None
    return normalize_path(rel.as_posix())
  return normalize_path(raw)


def _parse_hook_payload_path(payload: str) -> str:
  """
  Extract the written file path from a Claude Code PostToolUse hook payload.

  Args:
    payload: Raw PostToolUse JSON payload read from the hook's stdin.

  Returns:
    The tool response's `filePath` when present, otherwise the tool input's `file_path`,
    or an empty string when the payload is not JSON, not an object, or names no string
    path.
  """
  # guard: a payload that is not JSON names no file
  try:
    data = json.loads(payload)
  except ValueError:
    return ""

  # guard: a payload that is not a JSON object names no file
  if not isinstance(data, dict):
    return ""

  # the response carries the path the tool actually wrote; the input path is the request, used when no response names one
  path = (data[_HOOK_RESPONSE].get(_HOOK_RESPONSE_PATH) if isinstance(data.get(_HOOK_RESPONSE), dict) else None) \
      or (data[_HOOK_INPUT].get(_HOOK_INPUT_PATH) if isinstance(data.get(_HOOK_INPUT), dict) else None)
  return path if isinstance(path, str) else ""


def cmd_sync(args: argparse.Namespace) -> int:
  """
  Resolve and apply the icon for a single note.

  Leaves the note's `iconize_icon` / `iconize_color` frontmatter keys holding the icon and
  colour the icon-map assigns to it; a note no matcher claims keeps whatever icon keys it
  already carries. A `path`
  of `-` reads a Claude Code PostToolUse hook payload from stdin instead, and is a silent
  no-op unless the payload names a `.md` file. Behaves as a silent no-op when the icon-map
  is missing or incompatible, when the path falls outside the vault, or when the target
  file does not exist.

  Guarantees:
    - A note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color` keys; they are never
      stripped or rewritten.
    - A scaffolding template is never painted.
    - A note outside the declared paint roots is never read for matching and never rewritten.

  Args:
    args: Parsed CLI arguments carrying the target `path`, optional `--vault`,
      `--icon-map`, and `--dry-run` flags.

  Returns:
    Process exit code; always OK in the current implementation.
  """
  path = args.path
  # a `-` path is the PostToolUse payload on stdin, read here so the hook needs no JSON tool of its own
  if path == _STDIN_PATH:
    path = _parse_hook_payload_path(sys.stdin.read())

    # guard: the hook repaints notes only — any other written file is a no-op
    if not path.endswith(_NOTE_SUFFIX):
      return EXIT_OK

  # resolve the vault and its icon map
  vault = find_vault(args.vault)
  icon_map = _load_icon_map_or_inert(vault, args.icon_map)

  # guard: missing or incompatible icon-map → hook inert
  if icon_map is None or _preflight_incompatible(icon_map):
    return EXIT_OK
  rel = _vault_relative_or_none(vault, path)

  # guard: path outside the vault → no-op
  if rel is None:
    return EXIT_OK
  note_path = vault / rel

  # guard: nothing to rewrite — hook may fire on transient states
  if not note_path.is_file():
    return EXIT_OK

  # Contract:
  # A note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color` keys
  # exactly as they are; this command never strips or rewrites them, so another plugin may own
  # the icon keys of such a note.

  # Contract:
  # A scaffolding template is never painted: this command neither rewrites its icon keys nor
  # lets any rule claim it.

  # Contract:
  # A note outside the declared paint roots is never read for matching and never rewritten by
  # this command.

  # resolve the icon pair the rules assign to this note
  resolved = _resolve_icon_pair(icon_map, vault, rel)
  icon, color = resolved if resolved is not None else ( None, None )

  # a dry run reports the resolved pair and leaves the note untouched
  if args.dry_run:
    print(json.dumps({
      ResultKey.OP: "sync", ResultKey.DRY_RUN: True, ResultKey.PATH: rel,
      ResultKey.ICON: icon, ResultKey.COLOR: color,
    }, ensure_ascii = False))
    return EXIT_OK

  # no rule claims this note — keep whatever icon keys another manager wrote
  if resolved is None:
    print(json.dumps({
      ResultKey.OP: "sync", ResultKey.PATH: rel, ResultKey.CHANGED: False,
      ResultKey.ICON: None, ResultKey.COLOR: None,
    }, ensure_ascii = False))
    return EXIT_OK

  # a real run rewrites the note's icon keys and reports whether its text changed
  changed = rewrite_file(note_path, icon = icon, color = color)
  print(json.dumps({
    ResultKey.OP: "sync", ResultKey.PATH: rel, ResultKey.CHANGED: changed,
    ResultKey.ICON: icon, ResultKey.COLOR: color,
  }, ensure_ascii = False))
  return EXIT_OK


def _sync_rel_paths(vault: Path, icon_map: dict, rels: list[str], *, dry_run: bool, op: str) -> int:
  """
  Resolve and apply icons for the given vault-relative notes, then emit the result record.

  The walk behind `sync-paths`. Rewrites frontmatter in the working tree only; a path
  that does not exist (or vanished mid-walk) is skipped silently.

  Args:
    vault: Resolved vault root.
    icon_map: Loaded, compatible icon-map.
    rels: Vault-relative POSIX paths of the notes to repaint.
    dry_run: When `True`, report the plan and touch nothing.
    op: The op label stamped into the JSON result record.

  Returns:
    Process exit code; always OK in the current implementation.
  """
  # the accumulators the walk fills
  touched: list[str] = []
  planned: list[dict] = []

  # resolve the icon for every named note and rewrite its frontmatter
  for rel in rels:
    note_path = vault / rel

    # guard: skip targets that do not exist (or disappeared between listing and walk)
    if not note_path.is_file():
      continue

    # the first matching icon-map entry decides the note's icon and color
    resolved = _resolve_icon_pair(icon_map, vault, rel)

    # no rule claims this note — keep whatever icon keys another manager wrote
    if resolved is None:
      continue
    icon, color = resolved

    # a dry run accumulates the plan; a real run rewrites and records what changed
    if dry_run:
      if _is_repaint_needed(note_path, icon, color):
        planned.append({ ResultKey.PATH: rel, ResultKey.ICON: icon, ResultKey.COLOR: color })
      continue
    if rewrite_file(note_path, icon = icon, color = color):
      touched.append(rel)

  # a dry run reports the plan and leaves the worktree untouched
  if dry_run:
    print(json.dumps({ ResultKey.OP: op, ResultKey.DRY_RUN: True, ResultKey.PLANNED: planned },
                     ensure_ascii = False))
    return EXIT_OK

  # emit the machine-readable result record for the caller
  print(json.dumps({ ResultKey.OP: op, ResultKey.TOUCHED: touched }, ensure_ascii = False))
  return EXIT_OK


def cmd_sync_paths(args: argparse.Namespace) -> int:
  """
  Resolve and apply icons for the named vault-relative `.md` paths.

  The single-commit door for sibling plugins: a bot routine about to commit a note runs
  this op on the paths it will commit and folds the touched files into its own pathspec,
  so the repaint rides inside the same commit instead of a separate icons commit later.
  Rewrites frontmatter in the working tree only. Stays inert when the icon-map is missing
  or incompatible; a named path that does not exist or is not markdown is skipped, and a
  named path no matcher claims keeps whatever icon keys it already carries.

  Guarantees:
    - Never stages or commits anything itself; every rewrite lands in the working tree
      only, and the caller MUST fold the returned touched paths into its own commit
      pathspec for the repaint to land in the same commit.
    - A named note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color` keys; they are
      never stripped or rewritten.
    - A scaffolding template is never painted, even when the caller names it.
    - A named note outside the declared paint roots is never read for matching and never rewritten.

  Args:
    args: Parsed CLI arguments carrying the `paths` list and optional `--vault`,
      `--icon-map`, and `--dry-run` flags.

  Returns:
    Process exit code; always OK in the current implementation.
  """
  vault = find_vault(args.vault)
  icon_map = _load_icon_map_or_inert(vault, args.icon_map)

  # guard: missing or incompatible icon-map → op inert
  if icon_map is None or _preflight_incompatible(icon_map):
    return EXIT_OK

  # only markdown notes carry icon frontmatter; the shared walk skips missing files itself.
  # Every path is normalized first: a `./`-prefixed argument would otherwise slip past the
  # template guard and the matchers alike, both of which read canonical vault-relative paths.
  rels: list[str] = []
  for raw in args.paths:
    # guard: only markdown notes participate
    # waiver: filesystem path idiom (.md)
    if not raw.endswith(".md"):
      continue
    try:
      rels.append(normalize_path(raw))
    except IconizeError as error:
      sys.stderr.write(f"iconize_sync: {error}; path skipped.\n")

  # Contract:
  # This command never stages or commits anything itself; every rewrite lands in the
  # working tree only. The caller MUST fold the returned touched paths into its own
  # commit pathspec for the repaint to land — that single commit is the whole point of
  # this op.

  # Contract:
  # A named note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color`
  # keys exactly as they are; this command never strips or rewrites them, so another plugin
  # may own the icon keys of such a note.

  # Contract:
  # A scaffolding template is never painted: this command neither rewrites its icon keys nor
  # lets any rule claim it, even when the caller names it.

  # Contract:
  # A named note outside the declared paint roots is never read for matching and never
  # rewritten by this command.

  # delegate to the shared rewrite-and-report walk over the normalized targets
  # waiver: subcommand-name value (canonical home is the parser+dispatch map)
  return _sync_rel_paths(vault, icon_map, rels, dry_run = args.dry_run, op = "sync-paths")


def _is_repaint_needed(note_path: Path, icon: str | None, color: str | None) -> bool:
  """
  Report whether repainting a note to the given pair would alter its text.

  A dry run lists exactly the notes a real run would rewrite, so a note already carrying the
  resolved pair is not planned — `rewrite_file` would leave it untouched.

  Args:
    note_path: Absolute path of the note.
    icon: Resolved icon, or None to remove the key.
    color: Resolved colour, or None to remove the key.

  Returns:
    True when the rewritten frontmatter differs from what is on disk.
  """
  # waiver: stdlib encoding-mode idiom
  src = note_path.read_text(encoding = "utf-8")
  return rewrite_frontmatter(src, icon = icon, color = color) != src


def walk_md_files(vault: Path, prefix: str | None) -> list[str]:
  """
  Enumerate `.md` files under the vault, optionally constrained to a sub-prefix.

  Skips infrastructure directories (`.obsidian`, `.git`, `.claude`, `.githooks`) and
  scaffolding-template trees, and does not follow symlinks.

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
  out: list[str] = []
  for dirpath, dirnames, filenames in os.walk(root, followlinks = False):
    # Prune skipped dirs in-place so we never descend into them.
    dirnames[:] = [ dirname for dirname in dirnames if dirname not in _EXCLUDED_DIRS ]
    for filename in filenames:
      # guard: only collect markdown files
      # waiver: filesystem path idiom (.md)
      if not filename.endswith(".md"):
        continue
      rel = Path(dirpath, filename).relative_to(vault)
      rel_posix = "/".join(rel.parts)

      # guard: template trees are source, not vault content — never enumerated for painting
      if is_template_path(rel_posix):
        continue
      out.append(rel_posix)
  return out


def cmd_reconcile(args: argparse.Namespace) -> int:
  """
  Recompute icons across the full vault (or a prefix sub-tree) and rewrite frontmatter.

  Walks every markdown file under the vault, evaluates the icon-map matchers, and rewrites
  the `iconize_icon` / `iconize_color` keys where the resolution differs; a note no matcher
  claims keeps whatever icon keys it already carries. Stays inert when the icon-map is
  missing or incompatible.

  Guarantees:
    - A note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color` keys; they are never
      stripped or rewritten.
    - A scaffolding template is never painted.
    - A note outside the declared paint roots is never read for matching and never rewritten.

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

  # Contract:
  # A note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color` keys
  # exactly as they are; this command never strips or rewrites them, so another plugin may own
  # the icon keys of such a note.

  # Contract:
  # A scaffolding template is never painted: this command neither rewrites its icon keys nor
  # lets any rule claim it.

  # Contract:
  # A note outside the declared paint roots is never read for matching and never rewritten by
  # this command.

  # the accumulators the vault walk fills
  touched: list[str] = []
  planned: list[dict] = []

  # recompute the icon for every markdown file in scope and rewrite its frontmatter
  for rel in walk_md_files(vault, prefix or None):
    resolved = _resolve_icon_pair(icon_map, vault, rel)

    # no rule claims this note — keep whatever icon keys another manager wrote
    if resolved is None:
      continue
    icon, color = resolved
    note_path = vault / rel

    # a dry run accumulates the plan; a real run rewrites and records what changed
    if args.dry_run:
      if _is_repaint_needed(note_path, icon, color):
        planned.append({ ResultKey.PATH: rel, ResultKey.ICON: icon, ResultKey.COLOR: color })
      continue
    if rewrite_file(note_path, icon = icon, color = color):
      touched.append(rel)

  # a dry run reports the plan and leaves the worktree untouched
  if args.dry_run:
    print(json.dumps({ ResultKey.OP: "reconcile", ResultKey.DRY_RUN: True, ResultKey.PREFIX: prefix,
                       ResultKey.PLANNED: planned }, ensure_ascii = False))
    return EXIT_OK

  # emit the machine-readable result record for the caller
  print(json.dumps({ ResultKey.OP: "reconcile", ResultKey.PREFIX: prefix,
                     ResultKey.TOUCHED_COUNT: len(touched) }, ensure_ascii = False))
  return EXIT_OK


def cmd_reconcile_plugin(args: argparse.Namespace) -> int:
  """
  Reconcile icons under a single plugin's sub-tree and report every path rewritten.

  Used by the pre-commit pipeline after a `plugin.json` bump: the version delta flips
  callbacks like `plugin-is-patch-bumped`, so every file under the plugin's subtree whose
  color depends on that callback (folder note, README) must repaint in the same commit.
  The full `reconcile` walk would do the same but at vault scope; this one is bounded to
  the touched plugin.

  Rewrites reach the working tree only; the index is never written to. The caller folds
  the reported paths into its own commit pathspec, which is what carries the repaint into
  the commit — the git index belongs to the operator, and staging into it here would leave
  entries behind that outlive the commit this ran for. A note under the subtree that no
  matcher claims keeps whatever icon keys it already carries.

  Guarantees:
    - Never stages or commits anything; every rewrite lands in the working tree only, and
      the caller MUST fold the reported `touched` paths into its own commit pathspec to
      land them.
    - A note under the plugin subtree that no icon rule claims keeps its existing `iconize_icon` /
      `iconize_color` keys; they are never stripped or rewritten.
    - A scaffolding template is never painted.
    - A note outside the declared paint roots is never read for matching and never rewritten.

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
  prefix = f"plugins/claude/{args.plugin}"

  # Contract:
  # A note under the plugin subtree that no icon rule claims keeps its existing `iconize_icon` /
  # `iconize_color` keys exactly as they are; this command never strips or rewrites them, so
  # another plugin may own the icon keys of such a note.

  # Contract:
  # A scaffolding template is never painted: this command neither rewrites its icon keys nor
  # lets any rule claim it.

  # Contract:
  # A note outside the declared paint roots is never read for matching and never rewritten by
  # this command.

  # the accumulators the plugin-subtree walk fills
  touched: list[str] = []
  planned: list[dict] = []

  # repaint every note under the plugin subtree whose color depends on the bumped version
  for rel in walk_md_files(vault, prefix):
    resolved = _resolve_icon_pair(icon_map, vault, rel)

    # no rule claims this note — keep whatever icon keys another manager wrote
    if resolved is None:
      continue
    icon, color = resolved
    note_path = vault / rel

    # guard: skip targets that disappeared during the walk
    if not note_path.is_file():
      continue

    # a dry run accumulates the plan; a real run rewrites and records what changed
    if args.dry_run:
      if _is_repaint_needed(note_path, icon, color):
        planned.append({ ResultKey.PATH: rel, ResultKey.ICON: icon, ResultKey.COLOR: color })
      continue
    if rewrite_file(note_path, icon = icon, color = color):
      touched.append(rel)

  # a dry run reports the plan and leaves the worktree untouched
  if args.dry_run:
    print(json.dumps({ ResultKey.OP: "reconcile-plugin", ResultKey.PLUGIN: args.plugin, ResultKey.DRY_RUN: True,
                       ResultKey.PLANNED: planned }, ensure_ascii = False))
    return EXIT_OK

  # Contract:
  # This command never stages or commits anything; every rewrite lands in the working
  # tree only. The caller MUST fold the reported `touched` paths into its own commit
  # pathspec — the git index is left exactly as the caller had it.

  # emit the machine-readable result record for the pre-commit pipeline
  print(json.dumps({ ResultKey.OP: "reconcile-plugin", ResultKey.PLUGIN: args.plugin,
                     ResultKey.TOUCHED: touched }, ensure_ascii = False))
  return EXIT_OK


def _dirty_md_files(vault: Path) -> list[str]:
  """
  Return vault-relative POSIX paths of every dirty `.md` file in the vault.

  A file is dirty when `git status --porcelain` reports it as modified, added, deleted,
  untracked, or renamed/copied. For renames and copies both the old and new paths are
  returned so the caller can clean up the stale path-key in the old parent directory as
  well as emit the new one. Returns an empty list silently on any non-git vault or git
  failure, so a broken git state never blocks a `reconcile-dirty` run.

  Args:
    vault: Resolved vault root.

  Returns:
    Sorted list of vault-relative POSIX paths.
  """
  # `--no-optional-locks` skips the stat-cache refresh that `git status`
  # would otherwise write to `.git/index.lock`; without the flag it races
  # with concurrent manual git ops.
  status = subprocess.run(
    [ "git", "--no-optional-locks", "-C", str(vault),
      "status", "-z", "--porcelain=v1" ],
    capture_output = True, text = False, check = False)

  # guard: git failure → empty list (reconcile-dirty stays a safety net)
  if status.returncode != 0:
    return []
  paths: set[str] = set()

  # -z output: each record is `XY<space><path>` terminated by NUL. For R/C codes the
  # record is `XY<space><new>\x00<old>`, so the *following* record is the original
  # path (no preceding status bytes). We track whether the previous record was R/C.
  records = status.stdout.split(b"\x00")
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

  Repaints every note in each directory, nested ones included, that holds a dirty markdown
  file in the vault. Invoked directly by the operator; no hook drives it. A note no
  matcher claims keeps whatever icon keys it already carries. Stays inert when the icon-map
  is missing or incompatible and is a no-op when no dirty files exist.

  Guarantees:
    - A note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color` keys; they are never
      stripped or rewritten.
    - A scaffolding template is never painted.
    - A note outside the declared paint roots is never read for matching and never rewritten.

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

  # dirty notes are the only place icons can have gone stale since the last turn
  paths = _dirty_md_files(vault)

  # guard: no dirty markdown files → silent no-op
  if not paths:
    return EXIT_OK

  # Domain(obsidian.icon-repaint):
  # # A note's own look can depend on which of its siblings exist
  # Some rules decide a note's icon by comparing its name against the directory that holds it — for
  # instance recognizing a note as speaking for its own folder. Renaming or deleting one note in a
  # directory can therefore change what a sibling note is entitled to, even though the sibling's own
  # content and frontmatter never changed. Repainting only the note that changed would miss that ripple,
  # so a repaint driven by what changed treats the whole containing directory as the unit that might now
  # need a different look, not the single file git reports as dirty. The unit is the directory together
  # with everything nested below it, so a changed note at the top of the vault puts the entire vault up
  # for repainting.

  # Contract:
  # A note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color` keys
  # exactly as they are; this command never strips or rewrites them, so another plugin may own
  # the icon keys of such a note.

  # Contract:
  # A scaffolding template is never painted: this command neither rewrites its icon keys nor
  # lets any rule claim it.

  # Contract:
  # A note outside the declared paint roots is never read for matching and never rewritten by
  # this command.

  # a sibling note's rename or deletion shifts colors across its whole directory, so reconcile by parent dir
  prefixes = sorted({ "/".join(PurePosixPath(p).parts[:-1]) for p in paths })

  # the accumulators the per-prefix walks fill
  touched: list[str] = []
  planned: list[dict] = []

  # recompute the icon for every note in each affected directory and rewrite its frontmatter
  for prefix in prefixes:
    for rel in walk_md_files(vault, prefix or None):
      resolved = _resolve_icon_pair(icon_map, vault, rel)

      # no rule claims this note — keep whatever icon keys another manager wrote
      if resolved is None:
        continue
      icon, color = resolved
      note_path = vault / rel

      # a dry run accumulates the plan; a real run rewrites and records what changed
      if args.dry_run:
        if _is_repaint_needed(note_path, icon, color):
          planned.append({ ResultKey.PATH: rel, ResultKey.ICON: icon, ResultKey.COLOR: color })
        continue
      if rewrite_file(note_path, icon = icon, color = color):
        touched.append(rel)

  # a dry run reports the plan and leaves the worktree untouched
  if args.dry_run:
    print(json.dumps({ ResultKey.OP: "reconcile-dirty", ResultKey.DRY_RUN: True,
                       ResultKey.PREFIXES: prefixes, ResultKey.PLANNED: planned },
                     ensure_ascii = False))
    return EXIT_OK

  # emit the machine-readable result record for the caller
  print(json.dumps({ ResultKey.OP: "reconcile-dirty", ResultKey.PREFIXES: prefixes,
                     ResultKey.TOUCHED_COUNT: len(touched) }, ensure_ascii = False))
  return EXIT_OK


def parse_item_sha(item: str | None) -> str | None:
  """
  Read the commit sha out of the value the driving routine handed this run.

  Lets the same subcommand run identically whether a git-watch routine drives it or an
  operator types the sha directly from a shell.

  Args:
    item: The raw argument value passed to the subcommand — a JSON envelope from a
      git-watch routine, a bare sha typed by hand, or None when the caller passed nothing.

  Returns:
    The commit sha, or None when the value carries none.
  """
  # guard: nothing passed — the caller named no commit
  if not item:
    return None
  stripped = item.strip()

  # a bare sha is the hand-run shape, anything else is the JSON envelope
  if not stripped.startswith("{"):
    return stripped or None
  try:
    payload = json.loads(stripped)
  except json.JSONDecodeError:
    return None
  # waiver: the git-watch item vocabulary, owned by lazycortex-core's routine schema
  sha = payload.get("sha")
  return sha if isinstance(sha, str) and sha else None


def _commit_notes(vault: Path, rels: list[str]) -> str | None:
  """
  Commit the named notes under the icon-repaint subject as the repaint bot, leaving the rest of the tree alone.

  The commit carries the repaint bot identity and trailer, so sibling coordinators treat it as
  system-authored rather than as an operator edit.

  Notes:
    - No-op on an empty list; nothing is staged or committed.

  Args:
    vault: Resolved vault root.
    rels: Vault-relative POSIX paths to commit.

  Returns:
    None when the notes are committed or the list was empty; a one-line reason when git
    refused, so the caller can surface the repaint it failed to land.
  """

  # Domain(obsidian.icon-repaint):
  # # A repaint commit carries its own identity so it is never mistaken for an edit
  # Every commit an automated repaint produces is authored under a name and address reserved for this
  # automation, never the operator's own identity, and its message carries a fixed trailer line naming
  # the routine that made it. Sibling automations that watch commit history rely on this identity to
  # recognize a repaint as system-authored and skip waking themselves over it — without it, every repaint
  # would read as an ordinary operator edit and re-trigger whatever else is watching the vault.

  # guard: an empty pathspec would make git snapshot the whole index — the operator's parked work
  if not rels:
    return None

  # an explicit pathspec keeps whatever else the operator has in flight out of this commit;
  # `core.hooksPath=/dev/null` keeps the consumer's own git hooks from re-entering this worker
  added = subprocess.run(
    [ "git", "-C", str(vault), "-c", "core.hooksPath=/dev/null", "add", "--", *rels ],
    capture_output = True, text = True, check = False, encoding = "utf-8")

  # guard: nothing reached the index — committing now would produce an empty or partial commit
  if added.returncode != 0:
    return added.stderr.strip() or "git add failed"

  # the same pathspec on the commit keeps a concurrently-parked index out of the snapshot;
  # the bot identity + trailer make the commit recognisable as system-authored to the
  # review / specs coordinators, so a repaint never fires their operator-edit wake
  committed = subprocess.run(
    [ "git", "-C", str(vault), "-c", "core.hooksPath=/dev/null",
      "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
      "commit", "-m", f"{ICON_COMMIT_SUBJECT}\n\n{ICON_COMMIT_TRAILER}", "--", *rels ],
    capture_output = True, text = True, check = False, encoding = "utf-8")

  # guard: the repaint stayed uncommitted, which is exactly the dirty tree this run exists to avoid
  if committed.returncode != 0:
    return committed.stderr.strip() or "git commit failed"
  return None


def _commit_range_paths(vault: Path, sha: str) -> list[str]:
  """
  Return the vault-relative paths a commit touched, whatever their file type.

  Args:
    vault: Resolved vault root.
    sha: The commit whose changed paths are returned.

  Returns:
    Sorted vault-relative POSIX paths. Empty on any git failure — the routine is a repaint
    pass, never a blocker.
  """
  proc = subprocess.run(
    [ "git", "--no-optional-locks", "-C", str(vault),
      "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--root", sha ],
    capture_output = True, text = True, check = False, encoding = "utf-8")

  # guard: git failure — nothing to repaint from
  if proc.returncode != 0:
    return []
  return sorted({ line.strip() for line in proc.stdout.splitlines() if line.strip() })


def _has_diverged_from_head(vault: Path, rel: str) -> bool:
  """
  Report whether a note's working copy differs from the revision recorded in HEAD.

  Args:
    vault: Resolved vault root.
    rel: Vault-relative POSIX path of the note.

  Returns:
    True when the working copy carries content HEAD does not, including a note git does
    not track yet. False on any git failure, so a broken probe never triggers a commit.
  """
  proc = subprocess.run(
    [ "git", "--no-optional-locks", "-C", str(vault), "status", "--porcelain=v1", "--", rel ],
    capture_output = True, text = True, check = False, encoding = "utf-8")

  # guard: git failure — treat as unchanged so a broken probe never commits blind
  if proc.returncode != 0:
    return False
  return bool(proc.stdout.strip())


def _has_non_icon_divergence(vault: Path, rel: str) -> bool:
  """
  Report whether a note's divergence from HEAD reaches past its own icon frontmatter lines.

  Args:
    vault: Resolved vault root.
    rel: Vault-relative POSIX path of the note.

  Returns:
    True when the note is untracked, when git fails, or when any changed line of the note's
    whole diff against HEAD (staged plus unstaged) is not an `iconize_icon:` / `iconize_color:`
    frontmatter line; False when every changed line is an icon line.
  """
  status = subprocess.run(
    [ "git", "--no-optional-locks", "-C", str(vault), "status", "--porcelain=v1", "--", rel ],
    capture_output = True, text = True, check = False, encoding = "utf-8")

  # guard: git failure, or an untracked note — someone else's in-flight file, never swept
  if status.returncode != 0 or status.stdout.startswith("??"):
    return True

  # the whole worktree-vs-HEAD diff (staged plus unstaged) is what the repaint commit would carry
  diff = subprocess.run(
    [ "git", "--no-optional-locks", "-C", str(vault), "diff", "HEAD", "--", rel ],
    capture_output = True, text = True, check = False, encoding = "utf-8")

  # guard: git failure — assume foreign content so a broken probe never sweeps blind
  if diff.returncode != 0:
    return True

  # the HEAD revision's text locates the frontmatter a removed line may belong to
  head = subprocess.run(
    [ "git", "--no-optional-locks", "-C", str(vault), "show", f"HEAD:./{rel}" ],
    capture_output = True, text = True, check = False, encoding = "utf-8")

  # guard: git failure — assume foreign content so a broken probe never sweeps blind
  if head.returncode != 0:
    return True

  # the working copy's text locates the frontmatter an added line may belong to; a deleted note has none
  try:
    # waiver: stdlib encoding / error-mode idiom
    work = (vault / rel).read_text(encoding = "utf-8", errors = "ignore")
  except OSError:
    work = ""

  # each side's frontmatter interior as 1-based line numbers: the lines between the two fences
  old_fm, new_fm = (
    range(2, 2 + fm.group(1).count("\n")) if fm else range(0)
    for fm in ( FM_BLOCK_RE.match(head.stdout), FM_BLOCK_RE.match(work) ))

  # any changed line that is not an icon line inside its side's frontmatter is foreign work in flight
  old_no = new_no = 0
  in_hunk = False
  for line in diff.stdout.splitlines():
    # a hunk header resets both sides' line counters
    if hunk := _HUNK_RE.match(line):
      old_no, new_no, in_hunk = int(hunk[1]), int(hunk[2]), True
      continue

    # guard: file headers before the first hunk and empty lines carry no content
    if not in_hunk or not line:
      continue

    # a context line advances both sides and changes nothing
    tag = line[0]
    if tag == " ":
      old_no += 1
      new_no += 1
      continue

    # a removed line is placed on the HEAD side, an added one on the working-copy side
    if tag == "-":
      in_fm = old_no in old_fm
      old_no += 1
    elif tag == "+":
      in_fm = new_no in new_fm
      new_no += 1
    else:
      continue

    # a changed line outside the frontmatter, or a non-icon one, is foreign work: the answer is found
    if not (in_fm and _ICON_LINE_RE.match(line[1:])):
      return True
  return False


def cmd_reconcile_commit(args: argparse.Namespace) -> int:
  """
  Repaint every directory a commit touched, then commit the notes whose icons drifted.

  The unit of work is a whole directory rather than a single file, because a note's color
  depends on its siblings, and the commit that triggers a repaint need not touch a markdown
  file itself.

  Guarantees:
    - Commits only a note whose whole diff against HEAD is confined to its own `iconize_icon` /
      `iconize_color` frontmatter lines; a note whose divergence reaches any other changed line, or
      that git does not yet track, is left uncommitted.
    - Every repaint commit is authored as `lazy-obsidian.repaint` / `lazy-obsidian.repaint@bot.invalid` and its
      message carries the `Lazy-Bot: lazy-obsidian.repaint` trailer after the subject, so sibling coordinators
      classify it as system-authored rather than as an operator edit.
    - Returns EXIT_COMMIT_FAILED, distinct from EXIT_OK, when the commit does not land, so
      a driving routine can tell a failed repaint apart from a clean run.
    - A note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color` keys; they are never
      stripped or rewritten.
    - A scaffolding template is never painted.
    - A note outside the declared paint roots is never rewritten, and no icon rule is matched against it.

  Args:
    args: Parsed CLI arguments carrying the driving `item` (a commit sha, or the JSON item a
      git-watch routine passes) plus optional `--vault`, `--icon-map`, and `--dry-run` flags.

  Returns:
    Process exit code: `EXIT_OK` on a clean run, `EXIT_COMMIT_FAILED` when the repaint commit
    did not land.
  """
  vault = find_vault(args.vault)
  icon_map = _load_icon_map_or_inert(vault, args.icon_map)

  # guard: missing or incompatible icon-map → run inert
  if icon_map is None or _preflight_incompatible(icon_map):
    return EXIT_OK

  # the driving routine names the commit this repaint is scoped to
  sha = parse_item_sha(args.item)

  # guard: the driving item names no commit — nothing to scope the repaint to
  if not sha:
    return EXIT_OK

  # every path the commit carried decides which directories to repaint, markdown or not
  changed = _commit_range_paths(vault, sha)
  prefixes = sorted({ "/".join(PurePosixPath(p).parts[:-1]) for p in changed })

  # guard: the commit touched nothing this vault holds
  if not prefixes:
    return EXIT_OK

  # Contract:
  # A note that no icon rule claims keeps its existing `iconize_icon` / `iconize_color` keys
  # exactly as they are; this command never strips or rewrites them, so another plugin may own
  # the icon keys of such a note.

  # Contract:
  # A scaffolding template is never painted: this command neither rewrites its icon keys nor
  # lets any rule claim it.

  # Contract:
  # A note outside the declared paint roots is never rewritten by this command, and no icon
  # rule is matched against it.

  # the accumulators the per-prefix walks fill
  seen: list[str] = []
  rewritten: list[str] = []
  planned: list[dict] = []

  # recompute the icon for every note in each affected directory and rewrite its frontmatter
  for prefix in prefixes:
    for rel in walk_md_files(vault, prefix or None):
      resolved = _resolve_icon_pair(icon_map, vault, rel)
      note_path = vault / rel
      if args.dry_run:
        # only a claimed note reaches the plan — unclaimed ones will not be rewritten
        if resolved is not None and _is_repaint_needed(note_path, resolved[0], resolved[1]):
          planned.append({ ResultKey.PATH: rel, ResultKey.ICON: resolved[0], ResultKey.COLOR: resolved[1] })
        continue

      # an unclaimed note is not rewritten but stays in the commit sweep — divergence
      # from HEAD, not this run's rewrites, decides the commit set
      if resolved is not None:
        icon, color = resolved
        if rewrite_file(note_path, icon = icon, color = color):
          rewritten.append(rel)
      seen.append(rel)

  # a dry run reports the plan and leaves the worktree untouched
  if args.dry_run:
    print(json.dumps({ ResultKey.OP: "reconcile-commit", ResultKey.DRY_RUN: True,
                       ResultKey.PREFIXES: prefixes, ResultKey.PLANNED: planned },
                     ensure_ascii = False))
    return EXIT_OK

  # Contract:
  # A diverged note enters this commit only when its whole diff against HEAD (staged plus
  # unstaged) touches nothing but `iconize_icon:` / `iconize_color:` frontmatter lines. A note
  # whose divergence reaches any other changed line is left uncommitted and untouched — an
  # operator gesture or a sibling writer's payload must never ride a bot commit. An untracked
  # note is never swept. The one exception is the template trees the walk never enumerates: a
  # dirty template stays out of `seen`, so the daemon never auto-commits an operator's
  # in-progress edit of a shipped template.

  # Domain(obsidian.icon-repaint):
  # # A commit-triggered repaint commits only drift that is icon-only
  # When a repaint is scoped to a single commit, a note joins that commit only when two things are
  # both true: its working copy differs from the last recorded revision, and every one of those
  # differences is confined to the icon fields this system owns. A note an operator session already
  # corrected by hand for its icon is carried into the commit, since that correction is already right
  # on disk and leaving it out would dirty the tree for no reason the repaint caused. A note whose
  # drift reaches any other content — an operator's edit in progress, another automation's payload —
  # is left exactly as it stands; icon resolution never rides someone else's unfinished work into a
  # commit. A note git does not yet track at all is treated the same way, never swept. The one
  # deliberate exception on top of this rule is a scaffolding template: it never enters the set of
  # candidates in the first place, so an operator's in-progress edit to a shipped template is never
  # swept into an automated commit either.

  # notes whose working copy no longer matches HEAD are the ones this run has to land — but
  # only while the whole divergence is icon lines: any other changed line is someone's work in
  # flight (an operator gesture, a writer's payload) and must never ride a bot commit
  pending = [
      rel for rel in seen
      if _has_diverged_from_head(vault, rel) and not _has_non_icon_divergence(vault, rel)
  ]

  # Contract:
  # Every repaint commit MUST be authored as `lazy-obsidian.repaint` /
  # `lazy-obsidian.repaint@bot.invalid` and its message MUST carry the
  # `Lazy-Bot: lazy-obsidian.repaint` trailer after the subject. Sibling coordinators classify
  # the commit as system-authored from these marks, the specs coordinator by the `@bot.`
  # substring of the email and the review coordinator by the identity registered in the
  # consumer's expert entries. Dropping either mark turns every repaint into an operator-edit wake.

  # Contract:
  # A failed commit MUST surface as EXIT_COMMIT_FAILED, distinct from EXIT_OK, so a
  # driving git-watch routine can tell an uncommitted repaint apart from a clean run and
  # retry or escalate instead of treating the dirty tree as resolved.

  # land the icon-only drift in one bot-authored commit
  failure = _commit_notes(vault, pending)

  # emit the machine-readable result record for the caller
  record = { ResultKey.OP: "reconcile-commit", ResultKey.PREFIXES: prefixes,
             ResultKey.TOUCHED_COUNT: len(rewritten), ResultKey.COMMITTED: 0 if failure else len(pending) }

  # guard: an uncommitted repaint leaves the dirty tree this run exists to clear
  if failure:
    record[ResultKey.ERROR] = failure
    print(json.dumps(record, ensure_ascii = False))
    return EXIT_COMMIT_FAILED

  # the caller reads the record; a clean run says so with the standard OK code
  print(json.dumps(record, ensure_ascii = False))
  return EXIT_OK


# ----------------------------------------------------------------------------------------
# Schema version management — check-versions + preflight
# ----------------------------------------------------------------------------------------


def _parse_semver(text: str) -> tuple[int, int, int] | None:
  """
  Parse a bare `x.y.z` semver triple.

  Args:
    text: Candidate semver string with optional surrounding whitespace.

  Returns:
    Triple of major, minor, patch components, or None when the value is not a triple.
  """
  match = SEMVER_RE.match(text)

  # guard: not a well-formed semver triple
  if not match:
    return None
  # waiver: inline numeric literal
  return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _current_version() -> tuple[int, int, int]:
  """
  Return the worker's compiled-in `HOOK_VERSION` parsed into a semver triple.

  Returns:
    Triple of major, minor, patch components.
  """
  version = _parse_semver(HOOK_VERSION)
  # waiver: type-narrowing invariant guaranteed by construction here, not input validation
  assert version is not None
  return version


def _preflight_incompatible(icon_map: dict) -> bool:
  """
  Decide whether the loaded icon-map is incompatible with this worker.

  Writes a stderr diagnostic when incompatibility is detected so `2>/dev/null || true`
  hook wrappers stay quiet in CI / tty contexts but a curious user can `unset` the
  redirect and see why hooks went inert. A True return signals the caller to short-circuit
  with the OK exit code — hooks must never block a commit.

  A missing `schema_version` reads as schema 1 — the pre-handshake shape. Schema 1 is not
  supported, so such a vault is reported incompatible and its hooks go inert with the
  stderr diagnostic above, rather than being processed under a guessed schema.

  Args:
    icon_map: Parsed icon-map dict.

  Returns:
    True when the icon-map cannot be processed by this worker, False otherwise.
  """

  # Domain(obsidian.icon-repaint):
  # # An incompatible icon-map goes quiet instead of breaking anything
  # The icon-map and the worker that reads it declare their compatibility to each other: the map states
  # which schema generation it was written for and, optionally, the oldest worker version able to
  # understand it. A map declaring no schema at all is read as the oldest, no-longer-supported generation
  # rather than guessed forward. Whenever either side of that handshake fails — an unsupported schema, or
  # a worker too old for what the map requires — every repaint this run would have performed is skipped
  # outright rather than attempted under an assumption that might be wrong. The commands that report the
  # compatibility verdict and that migrate an old map to the current schema do not consult the handshake
  # first: they exist to work on exactly such a map. Icons are cosmetic, so nothing
  # that depends on a commit succeeding is ever allowed to depend on the handshake instead.

  # a missing schema_version reads as the oldest, unsupported generation
  schema = icon_map.get(MapKey.SCHEMA_VERSION, 1)

  # guard: unsupported schema version → hook inert
  if not isinstance(schema, int) or schema not in SUPPORTED_SCHEMA:
    sys.stderr.write(
      SCHEMA_UNSUPPORTED_INERT.format(schema = schema, supported = sorted(SUPPORTED_SCHEMA), inert = HOOK_INERT)
    )
    return True

  # a declared worker floor splits two ways: an unparseable floor is warned about and ignored,
  # since it states no requirement; a worker older than a valid floor goes inert
  min_hv = icon_map.get(MapKey.MIN_HOOK_VERSION)
  if isinstance(min_hv, str):
    required = _parse_semver(min_hv)
    if required is None:
      sys.stderr.write(
        f"iconize_sync: icon-map min_hook_version={min_hv!r} not valid semver; ignoring.\n")
    elif _current_version() < required:
      sys.stderr.write(HOOK_TOO_OLD_INERT.format(hook = HOOK_VERSION, floor = min_hv, inert = HOOK_INERT))
      return True

  # both sides of the handshake hold
  return False


def cmd_check_versions(args: argparse.Namespace) -> int:
  """
  Print the current icon-map schema compatibility report.

  Inspects the icon-map's declared `schema_version` and `min_hook_version` against the
  worker's compiled-in constants and emits a JSON report. Exits with the version-drift
  code when the icon-map is incompatible.

  Args:
    args: Parsed CLI arguments carrying optional `--vault` and `--icon-map`.

  Returns:
    Version-drift exit code on drift, otherwise the OK exit code.
  """
  # resolve the vault and the worker version the handshake is judged against
  vault = find_vault(args.vault)
  current = _current_version()

  # icon-map schema handshake (bilateral): report both the schema the vault declares
  # and whether this worker's HOOK_VERSION satisfies its min_hook_version, if any
  schema_block: dict = {
    VersionStatus.DECLARED: None, ResultKey.STATUS: VersionStatus.MISSING, MapKey.MIN_HOOK_VERSION: None }

  # an icon-map that cannot be loaded leaves the report at its "missing" status
  try:
    icon_map = load_icon_map(_resolve_icon_map_path(vault, getattr(args, "icon_map", None)))
  except IconizeError:
    icon_map = None

  # a loaded map fills in what it declares, then the verdict: a supported schema and,
  # when a valid worker floor is declared, a worker no older than it
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

  # an incompatible icon-map is what the caller's exit code must reflect
  drift = schema_block[ResultKey.STATUS] == VersionStatus.INCOMPATIBLE

  # emit the machine-readable compatibility report
  report = {
    ResultKey.OP: "check-versions",
    "HOOK_VERSION": HOOK_VERSION,
    "SCHEMA_VERSION": SCHEMA_VERSION,
    "SUPPORTED_SCHEMA": sorted(SUPPORTED_SCHEMA),
    "icon_map_schema": schema_block,
  }
  print(json.dumps(report, ensure_ascii = False))
  return EXIT_VERSION_DRIFT if drift else EXIT_OK


def cmd_migrate_1_to_2(args: argparse.Namespace) -> int:
  """
  Rewrite an icon-map file in place from schema 1 to schema 2.

  Runs as the `lazy-obsidian.iconize-install` skill's schema 1 → 2 transform step, applied to a
  pre-handshake icon-map that the worker's preflight would otherwise leave inert.

  Guarantees:
    - `schema_version` is set to 2, overwritten in place when already present or appended at the end
      when absent.
    - Every other key, except the dropped top-level `version` key and each matcher's `emit` key, keeps
      its value and its position.
    - The rewrite is atomic, so an interrupted run never leaves a half-written icon-map.

  Args:
    args: Parsed CLI arguments carrying the `icon_map_path` to rewrite.

  Returns:
    The OK exit code.

  Raises:
    IconizeError: If the icon-map document is not a JSON object, or if `matchers` is present but not
      a list.
    ValueError: If the file is not valid JSON or not valid UTF-8.
    OSError: If the file cannot be read or the rewrite fails.
  """
  path = Path(args.icon_map_path)
  data = json.loads(path.read_text(encoding = _MAP_ENCODING))

  # guard: only a JSON object is an icon-map
  if not isinstance(data, dict):
    raise IconizeError(f"{path} is not a JSON object")

  # guard: matchers, when present, must be a list the migration can walk
  if not isinstance(data.get(MapKey.MATCHERS) or [], list):
    raise IconizeError(f"{path}: `{MapKey.MATCHERS}` is not a list")

  # Contract:
  # `schema_version` is set to 2 — overwritten in place when the key is already present,
  # appended at the end when it is absent. Every other key, except the dropped top-level
  # `version` key and each matcher's `emit` key, keeps its value and its position in the
  # document.

  # schema 2 drops the legacy version string and every matcher's emit key; every other key keeps its place
  data.pop(_LEGACY_VERSION_KEY, None)
  data[MapKey.SCHEMA_VERSION] = 2
  for matcher in data.get(MapKey.MATCHERS) or []:
    if isinstance(matcher, dict):
      matcher.pop(_LEGACY_EMIT_KEY, None)

  # Contract:
  # The rewrite is atomic: an interrupted run never leaves a half-written icon-map.

  # write-then-rename, so an interrupted run never leaves a half-written icon-map
  tmp = path.with_name(path.name + _TMP_SUFFIX)
  tmp.write_text(json.dumps(data, indent = 2, ensure_ascii = False) + "\n", encoding = _MAP_ENCODING)
  os.replace(tmp, path)
  return EXIT_OK


DISPATCH = {
  "sync": cmd_sync,
  "sync-paths": cmd_sync_paths,
  "reconcile": cmd_reconcile,
  "reconcile-plugin": cmd_reconcile_plugin,
  "reconcile-dirty": cmd_reconcile_dirty,
  "reconcile-commit": cmd_reconcile_commit,
  "check-versions": cmd_check_versions,
  "migrate-1-to-2": cmd_migrate_1_to_2,
}


def main(argv: list[str] | None = None) -> int:
  """
  Worker entry point: parse CLI arguments and dispatch to the requested subcommand.

  Guarantees:
    - Always returns one of the module's EXIT_* constants; never lets an exception escape.
    - An `IconizeError` propagates as its own `.code`; any other exception is reported to
      stderr and treated as `EXIT_VALIDATION`.

  Args:
    argv: Optional argument list; when None, falls back to the process argv.

  Returns:
    Process exit code emitted by the dispatched subcommand, or a validation code when
    arguments are malformed.
  """

  # Contract:
  # Every path through this function returns one of the module's EXIT_* constants; it
  # never lets an exception escape. An `IconizeError` propagates as its own `.code`; any
  # other exception is reported to stderr and treated as `EXIT_VALIDATION`. A caller that
  # subprocesses this entry point can therefore always take the return value as
  # authoritative without wrapping the call in its own exception handler.

  # parse argv; argparse exits on usage errors and `--help`, so its exit becomes a return code
  # (a clean exit — code 0 or None — is EXIT_OK, any other code is EXIT_VALIDATION)
  try:
    args = build_parser().parse_args(argv)
  except SystemExit as error:
    return EXIT_OK if error.code in (0, None) else EXIT_VALIDATION

  # `--version` reports the wire versions and runs no subcommand
  if args.version:
    print(VERSION_LINE.format(protocol = PROTOCOL_VERSION, hook = HOOK_VERSION))
    return EXIT_OK

  # `--validate-entry` checks one icon entry read from stdin and runs no subcommand
  if args.validate_entry:
    try:
      entry = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
      print(f"invalid JSON: {error}", file = sys.stderr)
      return EXIT_VALIDATION

    # guard: valid JSON that is not an object carries no icon entry
    if not isinstance(entry, dict):
      print(f"error: entry must be a JSON object, got {entry!r}", file = sys.stderr)
      return EXIT_VALIDATION

    # validate the name and the optional color; both must be strings before the shape checks
    name = entry.get(IconKey.NAME, "")
    color = entry.get(IconKey.COLOR)
    try:
      # guard: a non-string name never reaches the shape check
      if not isinstance(name, str):
        raise IconizeError(ICON_NAME_NOT_STRING.format(name = name))
      validate_icon_name(name)

      # guard: a non-string color never reaches the shape check
      if color and not isinstance(color, str):
        raise IconizeError(COLOR_NOT_STRING.format(color = color))
      if color:
        validate_color(color)
    except IconizeError as error:
      print(f"error: {error}", file = sys.stderr)
      return EXIT_VALIDATION
    return EXIT_OK

  # guard: no subcommand supplied → print usage and exit with validation code
  if not args.cmd:
    # waiver: one-off human-facing message
    print(
      "usage: iconize_sync <sync|sync-paths|reconcile|reconcile-plugin|reconcile-dirty"
      "|reconcile-commit|check-versions|migrate-1-to-2> ...",
      file = sys.stderr)
    return EXIT_VALIDATION
  handler = DISPATCH.get(args.cmd)

  # guard: a subcommand with no registered handler
  if handler is None:
    return EXIT_VALIDATION

  # run the handler; its own error code wins, any other failure is a validation exit
  try:
    return handler(args)
  except IconizeError as error:
    sys.stderr.write(f"iconize_sync: {error}\n")
    return error.code
  except Exception as error:
    sys.stderr.write(f"iconize_sync: unexpected: {error}\n")
    return EXIT_VALIDATION


# ----------------------------------------------------------------------------------------
# Icon-map loader + registry lookup helpers
# ----------------------------------------------------------------------------------------


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
    OSError: When the file exists but cannot be read.
    UnicodeDecodeError: When the file content is not valid UTF-8.
  """
  map_path = Path(path)

  # guard: file must exist
  if not map_path.exists():
    raise IconizeError(ICON_MAP_NOT_FOUND.format(path = map_path), EXIT_VALIDATION)
  try:
    # waiver: stdlib encoding-mode idiom
    icon_map = json.loads(map_path.read_text(encoding = "utf-8"))
  except json.JSONDecodeError as error:
    raise IconizeError(ICON_MAP_INVALID_JSON.format(error = error), EXIT_VALIDATION) from error

  # guard: top-level must be an object with a 'matchers' key
  if not isinstance(icon_map, dict) or MapKey.MATCHERS not in icon_map:
    raise IconizeError(ICON_MAP_MISSING_MATCHERS, EXIT_VALIDATION)

  # guard: matchers must be a list
  if not isinstance(icon_map[MapKey.MATCHERS], list):
    raise IconizeError(ICON_MAP_MATCHERS_NOT_LIST, EXIT_VALIDATION)

  # guard: every matcher must be an object
  if not all(isinstance(matcher, dict) for matcher in icon_map[MapKey.MATCHERS]):
    raise IconizeError(ICON_MAP_MATCHER_NOT_OBJECT, EXIT_VALIDATION)

  # the optional lookup tables default to empty objects
  icon_map.setdefault(MapKey.REGISTRIES, {})
  icon_map.setdefault(MapKey.STAGE_COLORS, {})

  # guard: registries must be an object
  if not isinstance(icon_map[MapKey.REGISTRIES], dict):
    raise IconizeError(ICON_MAP_REGISTRIES_NOT_OBJECT, EXIT_VALIDATION)

  # guard: stage_colors must be an object
  if not isinstance(icon_map[MapKey.STAGE_COLORS], dict):
    raise IconizeError(ICON_MAP_STAGE_COLORS_NOT_OBJECT, EXIT_VALIDATION)
  return icon_map


def _load_registry_or_none(path: Path) -> dict | None:
  """
  Load and structurally validate one plugin-shipped iconize registry file.

  Registries are best-effort by contract: any defect — unreadable file, invalid JSON,
  wrong schema generation, malformed `matchers` — drops the whole file with a stderr
  diagnostic and never interrupts the run.

  Args:
    path: Filesystem path to the registry JSON file.

  Returns:
    Parsed registry dict, or None when the file cannot be used.
  """
  try:
    # waiver: stdlib encoding-mode idiom
    reg = json.loads(path.read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError) as error:
    sys.stderr.write(REGISTRY_UNREADABLE.format(path = path, error = error, skipped = REGISTRY_SKIPPED))
    return None

  # guard: top level must be an object
  if not isinstance(reg, dict):
    sys.stderr.write(REGISTRY_NOT_OBJECT.format(path = path, skipped = REGISTRY_SKIPPED))
    return None

  # guard: unknown schema generation → the worker cannot interpret the matchers
  if reg.get(MapKey.SCHEMA_VERSION) != REGISTRY_SCHEMA_VERSION:
    sys.stderr.write(
      REGISTRY_SCHEMA_MISMATCH.format(
        path = path, found = reg.get(MapKey.SCHEMA_VERSION), expected = REGISTRY_SCHEMA_VERSION,
        skipped = REGISTRY_SKIPPED,
      )
    )
    return None

  # guard: matchers must be a list
  if not isinstance(reg.get(MapKey.MATCHERS), list):
    sys.stderr.write(REGISTRY_MATCHERS_NOT_LIST.format(path = path, skipped = REGISTRY_SKIPPED))
    return None
  return reg


def version_sort_key(name: str) -> tuple[int, ...]:
  """
  Build a numeric sort key for a plugin version string.

  Guarantees:
    - Versions rank by the numeric value of each dot-separated component, so `10.0.0` ranks above `9.1.1`.
    - A component without digits ranks as `0`.

  Args:
    name: Version string as the install registry records it.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """

  # Contract:
  # Versions rank by the numeric value of each dot-separated component, never lexically,
  # so `10.0.0` ranks above `9.1.1`. A component without digits ranks as `0`.
  # Callers refuse to downgrade an installed plugin on the strength of this order.

  # collect one integer per dot-separated component
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(char for char in part if char.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


def _read_installed_plugin_roots() -> list[Path]:
  """
  Enumerate every installed plugin's source root from Claude Code's plugin registry.

  The registry (`~/.claude/plugins/installed_plugins.json`) records one entry per project and
  version that installed a plugin, each naming its `installPath`; per plugin the highest recorded
  version wins. The plugin cache itself is never searched: it keeps every version ever installed,
  so a walk across it returns copies the registry no longer names. The registry is always read from the
  current user's home directory.

  Returns:
    One existing root per plugin name, sorted by plugin name; empty without a readable registry.
  """
  registry = Path.home() / _INSTALLED_PLUGINS_REL
  try:
    data = json.loads(registry.read_text(encoding = "utf-8"))
  except (OSError, ValueError):
    return []
  # the registry nests its map under `plugins` in newer files and is the map itself in older ones
  # waiver: install-registry key, Claude Code's own schema
  plugins = data.get("plugins", data) if isinstance(data, dict) else {}
  best: dict[str, dict] = {}
  for key, entries in plugins.items():
    name = key.split("@", 1)[0]
    for rec in entries or []:
      # guard: a record without an install path names nothing to read
      # waiver: install-registry key, Claude Code's own schema
      if not isinstance(rec, dict) or not rec.get("installPath"):
        continue
      current = best.get(name)
      # waiver: install-registry key, Claude Code's own schema
      if current is None or version_sort_key(str(rec.get("version", ""))) > version_sort_key(
          # waiver: install-registry key, Claude Code's own schema
          str(current.get("version", ""))):
        best[name] = rec
  roots = [ Path(str(best[name]["installPath"])) for name in sorted(best) ]
  return [ root for root in roots if root.is_dir() ]


def plugin_root_name(root: Path) -> str:
  """
  Name the plugin a root belongs to.

  Args:
    root: Plugin root directory — a dev source tree named after the plugin, or one cached
      version whose own name is a version string.

  Returns:
    The manifest's `name` when the root carries one, else the directory name.
  """
  # waiver: plugin-manifest layout idiom, not a domain key
  manifest = root / ".claude-plugin" / "plugin.json"
  try:
    # waiver: plugin-manifest key, Claude Code's own schema
    name = json.loads(manifest.read_text(encoding = "utf-8")).get("name")
  except (OSError, ValueError, AttributeError):
    return root.name
  return name if isinstance(name, str) and name else root.name


def resolve_plugin_roots(vault: Path) -> list[Path]:
  """
  Enumerate the root of every plugin visible from a vault, freshly on each call.

  Plugin roots come from the `LAZYCORTEX_PLUGIN_DIRS` dev trees the runtime daemon exports; when
  that is empty the dev-vault sibling layout `<vault>/plugins/claude/*` stands in. Every plugin
  those roots do not cover then comes from Claude Code's install registry
  (`~/.claude/plugins/installed_plugins.json`, that plugin's highest recorded version).

  Args:
    vault: Resolved vault root, used only for the dev-vault sibling layout.

  Returns:
    The visible plugin roots: the dev trees first, then the installed plugins they do not cover.
  """
  # the daemon-exported dev trees lead; an operator shell and a consumer daemon export none
  roots = [ Path(entry) for entry in os.environ.get(PLUGIN_DIRS_ENV, "").split(os.pathsep) if entry ]

  # guard: outside the daemon the env is empty — fall back to the dev-vault sibling layout
  if not roots:
    # waiver: filesystem path idiom (plugins/claude/ plugin tree)
    dev = vault / "plugins/claude"
    if dev.is_dir():
      roots = [ dev / name for name in sorted(os.listdir(dev)) ]

  # the env carries dev trees only, so every plugin they do not cover comes from the install
  # registry — read now, never frozen at daemon start; a dev root shadows its installed copy by name
  covered = { plugin_root_name(root) for root in roots }
  return roots + [ root for root in _read_installed_plugin_roots() if plugin_root_name(root) not in covered ]


def load_plugin_registries(vault: Path) -> list[tuple[str, Path, dict]]:
  """
  Enumerate the iconize registries every visible plugin ships, freshly on each run.

  Reads the registries of every plugin root that `resolve_plugin_roots` reports for the vault. A plugin
  that is not visible simply contributes no rules — best-effort, like every other part of the hook
  surface.

  Args:
    vault: Resolved vault root, used to find the visible plugin roots.

  Returns:
    List of `(plugin_name, plugin_root, registry_dict)` triples, sorted by plugin name
    then registry filename.
  """

  # Domain(plugin.boundaries):
  # # An installed plugin's own icon rules are discovered fresh every run
  # Every installed plugin may ship its own icon rules alongside the vault's personal ones, and no rule
  # set is copied or merged in ahead of time — the full list of visible plugins is rediscovered on each
  # run, so a rule shipped by a newly installed or updated plugin takes effect immediately. A plugin the
  # current run cannot see for any reason simply contributes no rules of its own; nothing about resolving
  # a note's icon depends on any particular plugin being present.

  # collect every registry file each visible plugin root ships
  out: list[tuple[str, Path, dict]] = []
  for root in resolve_plugin_roots(vault):
    # waiver: filesystem path idiom (references/)
    refs = root / "references"

    # guard: a root without a references dir ships no registries
    if not refs.is_dir():
      continue
    for name in sorted(os.listdir(refs)):
      # guard: only registry-suffixed files participate
      if not name.endswith(REGISTRY_SUFFIX):
        continue
      reg = _load_registry_or_none(refs / name)
      if reg is not None:
        out.append(( plugin_root_name(root), root, reg ))

  # deterministic layer order: plugin name, then the per-root filename order above
  out.sort(key = lambda triple: triple[0])
  return out


def compose_layers(icon_map: dict, registries: list[tuple[str, Path, dict]]) -> dict:
  """
  Fold plugin-registry matchers under the personal icon-map into one ordered matcher list.

  Plugin lookup tables (`registries` objects) merge under the personal map's, the
  operator's keys winning on collision.

  Guarantees:
    - The composed order is deterministic: higher `priority` first; on an equal priority
      the operator's matcher precedes any plugin's, and two plugin matchers at equal
      priority order by plugin name then declaration order.
    - An operator matcher without a `priority` defaults above every band (1000).
    - A plugin matcher whose `priority` is missing, non-int, or outside the 100-599 band
      never acts; it is skipped with a stderr diagnostic — the band is the registry's
      contract, not a suggestion.

  Args:
    icon_map: Parsed personal icon-map dict.
    registries: Discovered `(plugin_name, plugin_root, registry_dict)` triples.

  Returns:
    New icon-map dict whose `matchers` list is the composed, ordered layer stack. The
    input dicts are not mutated; plugin-layer matchers carry an internal provenance key
    for callback resolution.
  """

  # Domain(obsidian.icon-resolution):
  # # Personal rules always outrank the rules a plugin ships
  # A vault's own rules and the rule sets shipped by installed plugins are combined into one ordered
  # list, evaluated highest priority first. Every plugin-shipped rule must declare a priority inside one
  # of five bands — from a blocking error at the top, through an action the operator must take, a
  # transient process state, a permanent status, down to plain decoration at the bottom — and a rule
  # outside every band is dropped rather than guessed into one. A personal rule that declares no priority
  # floats above every plugin band by default, so an operator's untouched rule keeps beating every shipped
  # rule until the operator deliberately assigns it a band of its own. When two rules still tie on
  # priority, a personal rule wins over any plugin's, and two plugin rules are ordered by the name of
  # the plugin that ships them, then by the order each declared its own rules.

  # the ordering record accumulates every rule from both layers before it is sorted
  ordered: list[tuple[int, int, str, int, dict]] = []
  seq = 0

  # operator matchers: a missing priority floats above every plugin band
  for matcher in icon_map.get(MapKey.MATCHERS, []):
    priority = matcher.get(MapKey.PRIORITY, OPERATOR_DEFAULT_PRIORITY)

    # guard: a malformed operator priority falls back to the operator default
    if not isinstance(priority, int):
      priority = OPERATOR_DEFAULT_PRIORITY
    ordered.append(( priority, 0, "", seq, matcher ))
    seq += 1

  # plugin matchers: band-checked and provenance-tagged for callback resolution
  for plugin, root, reg in registries:
    for matcher in reg.get(MapKey.MATCHERS, []):
      # guard: malformed matcher entries are dropped silently with the registry's blessing
      if not isinstance(matcher, dict):
        continue
      priority = matcher.get(MapKey.PRIORITY)

      # guard: a registry matcher outside its band does not act
      if not isinstance(priority, int) or not PRIORITY_BAND_MIN <= priority <= PRIORITY_BAND_MAX:
        sys.stderr.write(
          PRIORITY_OUTSIDE_BANDS.format(plugin = plugin, priority = priority, low = PRIORITY_BAND_MIN,
                                        high = PRIORITY_BAND_MAX)
        )
        continue
      tagged = dict(matcher)
      tagged[_MATCHER_CB_ROOT] = str(root)
      ordered.append(( priority, 1, plugin, seq, tagged ))
      seq += 1

  # Contract:
  # The composed order is deterministic run to run: higher `priority` sorts first; on an
  # equal priority the operator's matcher precedes any plugin's, and two plugin matchers at
  # equal priority order by plugin name then declaration order. An operator matcher without
  # a `priority` was defaulted above every band (`OPERATOR_DEFAULT_PRIORITY`); a plugin
  # matcher whose priority is missing, non-int, or outside `PRIORITY_BAND_MIN`..`PRIORITY_BAND_MAX`
  # never reached this sort. First-match resolution downstream depends on this ordering.

  # priority desc; ties: operator first, then plugin name, then declaration order
  # waiver: positional tuple indices of the ordering record built just above
  ordered.sort(key = lambda record: ( -record[0], record[1], record[2], record[3] ))

  # the composed map carries the ordered stack plus the merged lookup tables
  merged = dict(icon_map)
  # waiver: positional tuple index of the ordering record built above
  merged[MapKey.MATCHERS] = [ record[4] for record in ordered ]
  tables: dict = {}
  for _, _, reg in registries:
    if isinstance(reg.get(MapKey.REGISTRIES), dict):
      tables.update(reg[MapKey.REGISTRIES])
  tables.update(icon_map.get(MapKey.REGISTRIES) or {})
  merged[MapKey.REGISTRIES] = tables
  return merged


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

  Guarantees:
    - A resolve block's template string may reference the basename, the basename without its extension, and
      one frontmatter field of the note by a key of letters, digits and underscores, and nothing else.
    - A frontmatter token stands for that field's value, or for nothing when the note lacks the field.

  Args:
    template: Template string possibly containing `{{...}}` tokens.
    frontmatter: Parsed frontmatter mapping providing values for `{{frontmatter.*}}` refs.
    basename: Vault-relative basename used for `{{basename}}` and `{{basename.stem}}`.

  Returns:
    The string with all recognized tokens replaced.
  """

  # Domain(obsidian.icon-resolution):
  # # Placeholder tokens borrow their value from the note itself
  # An icon or color literal may embed a placeholder that is filled in from the note being painted: one
  # token stands for the note's own filename, another for that filename with its extension removed, and
  # a family of tokens each reach into one frontmatter field of the note. A frontmatter field that is
  # absent resolves to nothing rather than failing the rule. Tokens are substituted in a single pass — a
  # value that itself looks like a placeholder is never expanded a second time — and a token the
  # vocabulary does not recognize is left in the text untouched.

  # Contract:
  # A resolve block's template string may reference the basename, the basename without its extension,
  # and one frontmatter field of the note by a key of letters, digits and underscores, and nothing
  # else.

  # Contract:
  # A frontmatter token stands for that field's value, or for nothing when the note lacks the
  # field.

  # a template with no token markers is already its own resolved value
  if "{{" not in template:
    return template
  # resolve a single `{{...}}` capture to its replacement string
  def sub(match: re.Match) -> str:
    ref = match.group(1)
    if ref == InterpToken.BASENAME:
      return basename
    if ref == InterpToken.BASENAME_STEM:
      return basename.rsplit(".", 1)[0]

    # ref must start with "frontmatter." per INTERP_RE
    key = ref.split(".", 1)[1]
    value = frontmatter.get(key)
    return "" if value is None else str(value)
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



def _path_glob_to_regex(pattern: str) -> re.Pattern[str]:
  """
  Translate a path glob into a fully-anchored compiled regex.

  Mirrors `PurePosixPath.full_match` (Python 3.13+) semantics:

  - `**/` matches zero or more path segments (including empty).
  - `**` at the end matches anything, including `/`.
  - `*` matches within a single segment and does not cross `/`.
  - `?` matches a single character (not `/`).

  Args:
    pattern: Glob pattern using the supported syntax.

  Returns:
    Compiled, anchored regex equivalent to the glob.
  """

  # Decision: inline glob translator, not `PurePosixPath.full_match` — that needs Python 3.13, the floor is 3.12

  # a pattern compiled before is returned without recompiling it
  cached = _PATH_GLOB_RE_CACHE.get(pattern)
  if cached is not None:
    return cached

  # the pattern is read left to right, each glob token emitting its regex fragment
  parts: list[str] = []
  pos, length = 0, len(pattern)
  while pos < length:
    char = pattern[pos]
    if char == "*":
      # a doubled star spans segments; a single star stays inside one segment
      if pos + 1 < length and pattern[pos + 1] == "*":
        # `**/` consumes zero or more whole segments, so `a/**/b` also matches `a/b`
        if pos + 2 < length and pattern[pos + 2] == "/":
          parts.append(r"(?:[^/]+/)*")
          # waiver: inline numeric literal
          pos += 3
        # a `**` not followed by `/` matches anything, separators included
        else:
          parts.append(r".*")
          pos += 2
      else:
        parts.append(r"[^/]*")
        pos += 1
    # `?` is exactly one character that is not a separator
    elif char == "?":
      parts.append(r"[^/]")
      pos += 1
    # every other character matches itself literally
    else:
      parts.append(re.escape(char))
      pos += 1

  # the fragments are anchored at both ends and memoised for the next lookup of this pattern
  compiled = re.compile(r"\A" + "".join(parts) + r"\Z")
  _PATH_GLOB_RE_CACHE[pattern] = compiled
  return compiled


def eval_when(when: dict, path: str, frontmatter: dict) -> bool:
  """
  Evaluate a matcher `when` block against a vault file.

  The answer is an AND over the block's predicates — every predicate must hold for the matcher to be
  selected. The accepted predicate vocabulary is defined by `WhenKey`.

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

  # Domain(obsidian.icon-resolution):
  # # A note qualifies for a rule only when every one of its conditions holds
  # A rule's applicability is expressed as a set of independent conditions, and the rule claims a
  # candidate only once every condition it lists agrees. The recognized conditions are matching an exact
  # filename, matching a whitelist of accepted filenames, matching a path pattern, matching whether a
  # note's declared role echoes its own filename, requiring a frontmatter field to be present or absent,
  # requiring a frontmatter field to equal a literal value, requiring or forbidding folder-note status,
  # and deferring the decision to an external check. A single failing condition disqualifies the whole
  # rule no matter how many of its other conditions already agreed, so a rule with several conditions is
  # always narrower than any one of them taken alone.

  # every clause below must hold for the matcher to be selected
  bn = _basename(path)
  for key, expected in when.items():
    if key == WhenKey.BASENAME:
      # a basename mismatch fails the whole block
      if bn != expected:
        return False
    elif key == WhenKey.BASENAME_IN:
      # guard: 'basename_in' must carry an iterable container
      if not isinstance(expected, (list, tuple, set)):
        # waiver: reporting the type name of an arbitrary YAML-supplied value; type(x).__name__ is the right idiom here — no project class-system object to query
        raise IconizeError(BASENAME_IN_NOT_LIST.format(kind = type(expected).__name__))

      # the basename must be in the container
      if bn not in expected:
        return False
    elif key == WhenKey.PATH_GLOB:
      # the path must match the glob, where `**` crosses segments and `*` does not
      if not _path_glob_to_regex(expected).match(path):
        return False
    elif key == WhenKey.ROLE_MATCHES_BASENAME:
      stem = bn.rsplit(".", 1)[0]

      # frontmatter 'role' must equal the basename stem
      if frontmatter.get(FrontmatterKey.ROLE) != stem:
        return False
    elif key == WhenKey.IS_FOLDER_NOTE:
      parts = path.split("/")

      # the note's folder-note-ness (named after its parent dir) must equal the expected
      # boolean — `is_folder_note: false` rejects folder notes, `true` rejects everything else
      if (len(parts) >= 2 and parts[-2] == bn.rsplit(".", 1)[0]) != bool(expected):
        return False
    elif key == WhenKey.FRONTMATTER_HAS:
      # the named key must be present in frontmatter
      if expected not in frontmatter:
        return False
    elif key == WhenKey.FRONTMATTER_MISSING:
      # the named key must be absent from frontmatter
      if expected in frontmatter:
        return False
    elif key.startswith(WhenKey.FRONTMATTER_PREFIX):
      fkey = key.split(".", 1)[1]

      # frontmatter value must equal the expected literal
      if frontmatter.get(fkey) != expected:
        return False
    elif key == WhenKey.CALLBACK:
      # the external callback must report a match
      if not _callback_when(expected, path, frontmatter):
        return False
    else:
      raise IconizeError(WHEN_PREDICATE_UNKNOWN.format(key = key))
  return True


def _callback_dir(vault: Path | None = None) -> Path:
  """
  Return the directory where external callback scripts live for the vault.

  Caches the vault discovered on first call so subsequent lookups skip the walk-up.

  Args:
    vault: Resolved vault root; when None the cached or freshly-discovered vault is used.

  Returns:
    Absolute path to `<vault>/.claude/callbacks`.
  """
  # an absent vault falls back to the memoized one, discovered once
  # waiver: a genuine module-level rebind, not a false positive — this is the one writer of that cache
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

  The callback resolves from the vault's own callback directory first, so an operator override
  always wins; when the vault copy is missing, resolution falls back to the callback's shipping
  plugin's own tree, letting a registry-shipped matcher's callback work with zero vault setup.
  The resolved script is launched through the interpreter its own first line names and must
  emit valid JSON on stdout. Any failure mode — no shebang, timeout, non-zero exit, non-JSON
  output — is reported on stderr and surfaced to the caller as None.

  Args:
    callback_id: Filename of the callback script under the callback directory.
    payload: JSON-serializable payload sent to the callback on stdin.

  Returns:
    Parsed JSON response from the callback, or None on any failure.
  """

  # Domain(plugin.boundaries):
  # # An external check is answered by the vault first, its shipping plugin second
  # A rule may hand its condition or its resolution to an external check rather than deciding it inline.
  # That check is looked up first in the vault's own, operator-editable location, exactly the way a
  # personal rule already outranks a plugin's; only when the vault copy is missing does the lookup
  # fall back to the copy the check's own shipping plugin carries. This lets a
  # shipped rule's external check work out of the box with no vault setup at all, while still leaving the
  # operator free to override its behavior locally.

  # the vault's callback dir wins — the operator overrides a shipped callback the same
  # way an operator matcher beats a plugin matcher; the shipping plugin's own tree is
  # the fallback that makes registry callbacks work with zero vault setup
  cb_path = _callback_dir() / callback_id
  if not cb_path.is_file() and _ACTIVE_CB_ROOT is not None:
    # waiver: filesystem path idiom (callbacks/)
    cb_path = _ACTIVE_CB_ROOT / "callbacks" / callback_id

  # guard: callback must exist; how it runs is its own first line's business
  if not cb_path.is_file():
    return None
  try:
    argv = argv_for(cb_path)
  except ShebangError as error:
    sys.stderr.write(f"callback {callback_id!r} unusable: {error}\n")
    return None
  try:
    # waiver: inline numeric literal
    completed = subprocess.run(argv, input = json.dumps(payload), cwd = _CALLBACK_VAULT_CACHE,
                               capture_output = True, text = True, timeout = 10, check = False,
                               encoding = "utf-8")
  except subprocess.TimeoutExpired as error:
    out = "".join(
      # waiver: stdlib encoding-mode idiom
      stream.decode("utf-8", "replace") if isinstance(stream, bytes) else (stream or "")
      for stream in (error.stdout, error.stderr)
    )
    sys.stderr.write(f"callback {callback_id!r} timed out: {out}\n")
    return None
  except OSError as error:
    sys.stderr.write(f"callback {callback_id!r} failed: {error}\n")
    return None

  # guard: non-zero exit → no result
  if completed.returncode != 0:
    sys.stderr.write(f"callback {callback_id!r}: {completed.stderr}")
    return None
  try:
    return json.loads(completed.stdout)
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
  reply = _invoke_callback(callback_id,
                           { CallbackKey.OP: "when", CallbackKey.PATH: path, CallbackKey.FRONTMATTER: frontmatter })
  return bool(reply and reply.get(CallbackKey.MATCH) is True)


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

    # a key the registry does not hold resolves to no value
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
  `path_glob` or other path-aware predicates evaluate correctly, and it is handed to a
  `{callback}` resolution so the callback can answer from the note's location.

  Args:
    resolve_spec: Resolve block from a matcher entry.
    icon_map: Parsed icon-map dict providing the registry root.
    frontmatter: Parsed frontmatter mapping for the candidate file.
    basename: Vault-relative basename used in interpolation.
    path: Full vault-relative POSIX path of the candidate file.

  Returns:
    Resolved icon entry as `{"iconName": ..., "iconColor"?: ...}` when the resolve block
    names an icon. Returns a colour-only entry (`{"iconColor": ...}`, no name) when the
    block's `iconName` is the self-referential borrow token, which never names an icon of
    its own, or when any other template `iconName` resolves to nothing while a colour did
    resolve — this shape signals the caller to keep walking to the matcher that owns the
    icon. Returns None when nothing could be resolved.
  """
  if IconKey.NAME in resolve_spec or IconKey.COLOR in resolve_spec:
    name = _resolve_field(resolve_spec.get(IconKey.NAME), icon_map, frontmatter, basename)
    color = _resolve_field(resolve_spec.get(IconKey.COLOR), icon_map, frontmatter, basename)

    # a state rule paints the colour and borrows its name through the self-referential
    # token, which says "whatever this note's type gives it" rather than "whatever this note
    # currently carries". Such a rule names no icon at any time, so it hands back the colour alone
    # and the walk goes on to the rule that owns the icon, which re-resolves it from the type.
    if isinstance(resolve_spec.get(IconKey.NAME), str) and _SELF_BORROW_TOKEN in resolve_spec[IconKey.NAME]:
      return { IconKey.COLOR: color } if color else None

    # any other template resolving to nothing still yields its colour, while a lookup spec
    # resolving to nothing yields no entry at all — an unresolved registry key is a broken rule,
    # not a borrowed icon, and a broken rule leaves the note unclaimed
    if not name:
      spec = resolve_spec.get(IconKey.NAME)
      return { IconKey.COLOR: color } if color and isinstance(spec, str) and "{{" in spec else None

    # the rule named a look of its own, optionally carrying a colour to go with it
    entry = { IconKey.NAME: name }
    if color:
      entry[IconKey.COLOR] = color
    return entry

  # Domain(obsidian.icon-resolution):
  # # An icon can be a plain base look, refined by exceptions
  # An icon rule may describe its outcome directly, or as a base look further refined by a list of
  # exceptions. Each exception carries its own condition and its own priority; exceptions are tried from
  # the highest priority down, ties broken by the order they were declared, and the first exception whose
  # condition matches wins outright — its name and color replace the base's own, field by field, rather
  # than blending with it. When no exception matches, the base look stands unchanged. An exception that
  # supplies no name of its own does not decline: once its condition holds it still ends the search,
  # keeps the base's name and replaces only the colour. If the base has no name either, the rule
  # resolves to nothing.

  # a base look, optionally overridden by the first matching overlay
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
    return _callback_resolve(resolve_spec[MapKey.CALLBACK], frontmatter, icon_map, path)
  return None


def _callback_resolve(callback_id: str, frontmatter: dict, icon_map: dict, path: str = "") -> dict | None:
  """
  Resolve an icon entry via an external callback.

  The payload carries the candidate's vault-relative path alongside its frontmatter, so a
  callback whose answer depends on where the note sits — which product owns it, which content
  root it falls under — has the same locator a `when` callback is given.

  Args:
    callback_id: Filename of the callback under the callback directory.
    frontmatter: Parsed frontmatter mapping passed to the callback.
    icon_map: Parsed icon-map dict passed to the callback for registry lookups.
    path: Vault-relative POSIX path of the candidate file, passed to the callback.

  Returns:
    Resolved icon entry as `{"iconName": ..., "iconColor"?: ...}`, or None when the
    callback declines to resolve.
  """
  reply = _invoke_callback(callback_id,
                           { CallbackKey.OP: "resolve", CallbackKey.PATH: path,
                             CallbackKey.FRONTMATTER: frontmatter,
                             CallbackKey.ICON_MAP: icon_map })

  # a callback that declines, or returns no name, resolves nothing
  if not reply or not reply.get(IconKey.NAME):
    return None
  entry = { IconKey.NAME: reply[IconKey.NAME] }
  if reply.get(IconKey.COLOR):
    entry[IconKey.COLOR] = reply[IconKey.COLOR]
  return entry


def resolve_matchers(icon_map: dict, path: str, frontmatter: dict) -> list:
  """
  Apply the icon-map matchers to a single file and return the resulting emission list.

  Matchers are tried in descending priority order. The first matcher that both matches and names
  an icon decides the note; a matcher that matches but resolves only a colour carries that colour
  forward to whichever matcher later names the icon, outranking the colour that naming matcher
  carries on its own. When every matching matcher only supplied a colour, that colour applies
  alone. A matcher that matches and resolves nothing at all leaves the note unclaimed.

  Guarantees:
    - Under schema 2 the result is always `[]` or a single-element list `[(self_path, entry)]`;
      callers MUST NOT expect more than one entry.

  Args:
    icon_map: Parsed icon-map dict.
    path: Vault-relative POSIX path of the candidate file.
    frontmatter: Parsed frontmatter mapping for the candidate file.

  Returns:
    Emission list for the candidate file; empty when no matcher applies.
  """

  # Domain(obsidian.icon-resolution):
  # # The first rule that applies decides, and a rule that only paints keeps looking for the look
  # Rules are walked in their combined priority order and the first one whose conditions all hold decides
  # the note, with one exception: a rule that describes a passing state paints a colour over whatever the
  # note already looks like, and says nothing about the look itself. Such a rule keeps its colour and the
  # walk carries on beneath it, until a rule is found that does name a look — the note then wears that
  # look in the colour its state gave it. Nothing lower is consulted once a rule has named a look, and a
  # rule that matches but resolves to nothing at all still leaves the note unclaimed outright: that is a
  # broken rule rather than a rule with nothing to say about appearance. When every rule that claimed the
  # note only painted, the colour alone stands.

  # Contract:
  # The returned list carries at most one entry: under schema 2 the result is always `[]` (no
  # matcher claimed the file, or the claiming matcher resolved nothing) or a single-element
  # list holding the one `(path, entry)` pair the walk settled on. Callers MUST NOT expect
  # more than one entry.

  # the basename is shared across every matcher tried below
  basename = _basename(path)

  # a colour carried down from a state matcher that named no icon, awaiting the rule that names one
  borrowed_color = ""
  # waiver: a genuine module-level rebind — the callback engine reads the active matcher's plugin root from here
  global _ACTIVE_CB_ROOT  # noqa: PLW0603  # pylint: disable=global-statement
  for matcher in icon_map.get(MapKey.MATCHERS, []):
    # a plugin-layer matcher carries its shipping plugin's root for callback resolution
    cb_root = matcher.get(_MATCHER_CB_ROOT)
    _ACTIVE_CB_ROOT = Path(cb_root) if cb_root else None
    try:
      # only a matcher whose when-condition matches this path takes part
      if not eval_when(matcher.get(MapKey.WHEN, {}), path, frontmatter):
        continue
      entry = _build_entry(matcher.get(MapKey.RESOLVE, {}), icon_map, frontmatter, basename, path)

      # a matched rule that resolves to nothing leaves the note unclaimed, no further matchers attempted
      if not entry:
        return []

      # a state matcher that borrows its name resolved a colour and no name — it keeps the
      # colour, and the walk goes on to the rule that owns the icon, whatever the note carries now
      if IconKey.NAME not in entry:
        borrowed_color = borrowed_color or entry.get(IconKey.COLOR, "")
        continue

      # the state's colour outranks the one the naming rule carries — that is what a state rule is
      if borrowed_color:
        entry = { **entry, IconKey.COLOR: borrowed_color }
      return [ (normalize_path(path), entry) ]
    finally:
      _ACTIVE_CB_ROOT = None

  # every rule that claimed the note only painted it; the colour stands on its own
  if borrowed_color:
    return [ (normalize_path(path), { IconKey.COLOR: borrowed_color }) ]
  return []


if __name__ == "__main__":
  sys.exit(main())
