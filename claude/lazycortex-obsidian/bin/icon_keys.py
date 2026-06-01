"""
Centralized key names for the Iconize sync system.

The iconize-sync worker reads and writes a fixed pair of Iconize frontmatter
keys across many resolution and reconcile paths, emits result envelopes whose
keys are parsed by callers, and exchanges payloads with external callbacks over
a fixed protocol. Defining every such key once here means a mistyped key
surfaces as an `AttributeError` at import time rather than as a silently
unpainted icon, an unparseable result envelope, or a callback that never fires.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class IconKey:
  """
  Iconize frontmatter key names resolved and written by the sync worker.

  Attributes:
    NAME: The icon identifier key Iconize paints from.
    COLOR: The optional icon color key Iconize paints from.
  """

  NAME = "iconName"
  COLOR = "iconColor"


# ----------------------------------------------------------------------------------------
class ResultKey:
  """
  Key names in the JSON result envelopes the sync worker prints on stdout.

  Attributes:
    OP: The operation discriminator naming which subcommand produced the envelope.
    PATH: The vault-relative path the envelope reports on.
    ICON: The resolved icon name carried in a per-file result.
    COLOR: The resolved icon color carried in a per-file result.
    CHANGED: Whether a single-file rewrite altered the note on disk.
    DRY_RUN: Marker flagging an envelope produced without writing to disk.
    PLANNED: The list of would-be per-file results gathered during a dry run.
    TOUCHED: The list of paths whose frontmatter the run rewrote.
    TOUCHED_COUNT: The count of paths rewritten when individual paths are not enumerated.
    PREFIX: The single sub-tree prefix a reconcile run was scoped to.
    PREFIXES: The set of sub-tree prefixes a dirty-reconcile run covered.
    PLUGIN: The plugin name a plugin-scoped reconcile run targeted.
    STATUS: The compatibility classification carried in the version report.
  """

  OP = "op"
  PATH = "path"
  ICON = "icon"
  COLOR = "color"
  CHANGED = "changed"
  DRY_RUN = "dry_run"
  PLANNED = "planned"
  TOUCHED = "touched"
  TOUCHED_COUNT = "touched_count"
  PREFIX = "prefix"
  PREFIXES = "prefixes"
  PLUGIN = "plugin"
  STATUS = "status"


# ----------------------------------------------------------------------------------------
class CallbackKey:
  """
  Key names in the payloads and responses exchanged with external callbacks.

  Attributes:
    OP: The operation discriminator naming the callback request kind.
    PATH: The vault-relative path the callback request concerns.
    FRONTMATTER: The parsed frontmatter mapping sent in a callback request.
    ICON_MAP: The parsed icon-map mapping sent in a resolve callback request.
    MATCH: The boolean verdict a `when` callback returns.
  """

  OP = "op"
  PATH = "path"
  FRONTMATTER = "frontmatter"
  ICON_MAP = "icon_map"
  MATCH = "match"


# ----------------------------------------------------------------------------------------
class MapKey:
  """
  Top-level and nested field names in the external icon-map JSON document.

  Attributes:
    SCHEMA_VERSION: The schema-generation integer the document declares.
    MIN_HOOK_VERSION: The minimum worker hook version the document requires.
    MATCHERS: The ordered list of matcher entries the document carries.
    REGISTRIES: The named lookup tables referenced by resolve specs.
    STAGE_COLORS: The stage-to-color registry referenced by resolve specs.
    WHEN: The predicate block selecting which files a matcher or overlay applies to.
    RESOLVE: The resolution block producing an icon entry for a matched file.
    BASE: The base resolve block composed under overlays.
    OVERLAYS: The list of conditional overlay resolve blocks layered on the base.
    PRIORITY: The integer ordering weight on a single overlay.
    CALLBACK: The external-callback identifier driving a resolution or predicate.
    FROM: The dotted registry path a field-lookup spec reads from.
    KEY: The interpolated registry key a field-lookup spec resolves.
    FIELD: The optional sub-field a field-lookup spec extracts from a registry record.
  """

  SCHEMA_VERSION = "schema_version"
  MIN_HOOK_VERSION = "min_hook_version"
  MATCHERS = "matchers"
  REGISTRIES = "registries"
  STAGE_COLORS = "stage_colors"
  WHEN = "when"
  RESOLVE = "resolve"
  BASE = "base"
  OVERLAYS = "overlays"
  PRIORITY = "priority"
  CALLBACK = "callback"
  FROM = "from"
  KEY = "key"
  FIELD = "field"


# ----------------------------------------------------------------------------------------
class WhenKey:
  """
  Predicate names accepted inside an icon-map matcher `when` block.

  Attributes:
    BASENAME: Exact final-path-segment equality predicate.
    BASENAME_IN: Membership-in-container predicate over the final path segment.
    PATH_GLOB: Glob-match predicate over the full vault-relative path.
    ROLE_MATCHES_BASENAME: Predicate tying the `role` frontmatter value to the basename stem.
    FRONTMATTER_PREFIX: The prefix marking a `frontmatter.<key>` equality predicate.
    CALLBACK: External-callback predicate name.
  """

  BASENAME = "basename"
  BASENAME_IN = "basename_in"
  PATH_GLOB = "path_glob"
  ROLE_MATCHES_BASENAME = "role_matches_basename"
  FRONTMATTER_PREFIX = "frontmatter."
  CALLBACK = "callback"


# ----------------------------------------------------------------------------------------
class FrontmatterKey:
  """
  Frontmatter field names the matcher engine reads from candidate notes.

  Attributes:
    ROLE: The note-role field compared against the basename stem.
  """

  ROLE = "role"


# ----------------------------------------------------------------------------------------
class InterpToken:
  """
  Interpolation token references substituted inside icon-map template strings.

  Attributes:
    BASENAME: The full-basename token reference.
    BASENAME_STEM: The basename-without-extension token reference.
  """

  BASENAME = "basename"
  BASENAME_STEM = "basename.stem"


# ----------------------------------------------------------------------------------------
class YamlScalar:
  """
  YAML scalar literals the flat frontmatter parser recognizes.

  Attributes:
    TRUE: The boolean-true scalar token.
    FALSE: The boolean-false scalar token.
  """

  TRUE = "true"
  FALSE = "false"


# ----------------------------------------------------------------------------------------
class VersionStatus:
  """
  Compatibility-classification tokens emitted by the version report.

  Attributes:
    MISSING: No shim installed, or no icon-map present.
    MAJOR_DRIFT: Installed shim is on an incompatible major version.
    MINOR_DRIFT: Installed shim differs from the worker on a compatible major.
    OK: Installed shim and icon-map are fully compatible.
    INCOMPATIBLE: Icon-map schema or min-hook-version is unsatisfiable.
    DECLARED: The report key carrying the icon-map's declared schema generation.
  """

  MISSING = "missing"
  MAJOR_DRIFT = "major-drift"
  MINOR_DRIFT = "minor-drift"
  OK = "ok"
  INCOMPATIBLE = "incompatible"
  DECLARED = "declared"
