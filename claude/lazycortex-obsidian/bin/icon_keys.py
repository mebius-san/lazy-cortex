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

  Guarantees:
    - Repaint reads and writes only the NAME and COLOR keys; every other frontmatter field on the
      note is left untouched.

  Attributes:
    NAME: The icon identifier key Iconize paints from.
    COLOR: The optional icon color key Iconize paints from.
  """

  # Domain(obsidian.icon-repaint):
  # # Managed icon frontmatter keys
  # Icon repaint touches exactly two frontmatter keys on a note: the icon identifier and an optional color.
  # No other frontmatter field is ever read or written by the repaint mechanism, which is what lets a
  # surgical rewrite of a note replace only these two keys and leave every other byte of the note's
  # frontmatter and body untouched.

  # Contract:
  # Repaint reads and writes only NAME and COLOR on a note's frontmatter; every other frontmatter
  # field is never read or written by the repaint mechanism.

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
    COMMITTED: The count of notes a run committed after repainting them.
    ERROR: The one-line reason a run could not land its repaint.
  """

  # Domain(obsidian.icon-repaint):
  # # Repaint and reconcile result envelope
  # Every worker subcommand reports back through a JSON envelope discriminated by which operation
  # produced it. A run started as a dry run reports the icons it would assign without writing anything
  # to disk, while a real run reports either the individual paths it actually rewrote or, when
  # individual paths are not tracked, only their count. A reconcile run can be scoped narrowly to one
  # sub-tree prefix, broadly to a set of dirty prefixes, or to every note belonging to one plugin;
  # after repainting, the worker commits the touched notes and reports how many landed in the commit,
  # or a one-line reason when the commit could not land.

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
  COMMITTED = "committed"
  ERROR = "error"


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

  # Domain(obsidian.icon-resolution):
  # # External callback resolution protocol
  # When a matcher's predicate or resolve block delegates to an external callback, the worker sends
  # the callback the note's vault-relative path and its parsed frontmatter, plus — for a resolve
  # callback — the parsed icon-map's named registries, then reads back either a boolean match verdict
  # or a resolved icon entry. The callback is the only place where resolution logic can depend on
  # computation outside the icon-map document itself.

  OP = "op"
  PATH = "path"
  FRONTMATTER = "frontmatter"
  ICON_MAP = "icon_map"
  MATCH = "match"


# ----------------------------------------------------------------------------------------
class MapKey:
  """
  Top-level and nested field names in the external icon-map JSON document.

  Guarantees:
    - Overlays apply in descending PRIORITY order; the highest-priority overlay whose own WHEN
      predicate matches wins over every lower-priority overlay.

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

  # Domain(obsidian.icon-resolution):
  # # Icon-map matcher and resolve composition
  # The icon-map document is an ordered list of matchers, each pairing a selection predicate with a
  # resolve block that produces the matched note's icon and color. A resolve block always starts from
  # a base resolution and may layer overlays on top of it; overlays are applied in descending priority
  # order, so the highest-priority overlay whose own predicate matches wins over lower-priority ones.
  # Named registries, including a dedicated stage-to-color table, let a resolve block look values up
  # by a shared key instead of repeating literal names across matchers.

  # Contract:
  # Overlays are applied in descending PRIORITY order; the highest-priority overlay whose own WHEN
  # predicate matches wins over every lower-priority overlay.

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

  Guarantees:
    - The predicate keys defined on this class are the complete vocabulary accepted inside a `when`
      block; any other key is rejected.
    - Several predicate keys present on the same matcher or overlay combine with AND semantics — a
      note matches only when every present predicate holds.

  Attributes:
    BASENAME: Exact final-path-segment equality predicate.
    BASENAME_IN: Membership-in-container predicate over the final path segment.
    PATH_GLOB: Glob-match predicate over the full vault-relative path.
    ROLE_MATCHES_BASENAME: Predicate tying the `role` frontmatter value to the basename stem.
    FRONTMATTER_PREFIX: The prefix marking a `frontmatter.<key>` equality predicate.
    FRONTMATTER_HAS: Key-presence predicate over the frontmatter mapping.
    FRONTMATTER_MISSING: Key-absence predicate over the frontmatter mapping.
    IS_FOLDER_NOTE: Predicate selecting notes named after their own parent folder.
    CALLBACK: External-callback predicate name.
  """

  # Domain(obsidian.icon-resolution):
  # # Matcher predicate vocabulary
  # A matcher's selection predicate is drawn from a closed vocabulary of checks, combined with AND
  # semantics when several are present on the same matcher or overlay: an exact basename match,
  # basename membership in a set, a glob over the full vault-relative path, a check that the note's
  # declared role equals its own basename stem, equality against one named frontmatter field, presence
  # or absence of a frontmatter key, whether the note is named after its own parent folder, or a
  # delegated external callback. A note matches a matcher only when every predicate present on it holds.

  # Contract:
  # The predicate keys defined on this class are the complete vocabulary accepted inside a matcher's
  # `when` block; any key outside this set MUST be rejected.

  # Contract:
  # Several predicate keys present on the same matcher or overlay combine with AND semantics: a note
  # matches only when every present predicate holds.

  BASENAME = "basename"
  BASENAME_IN = "basename_in"
  PATH_GLOB = "path_glob"
  ROLE_MATCHES_BASENAME = "role_matches_basename"
  FRONTMATTER_PREFIX = "frontmatter."
  FRONTMATTER_HAS = "frontmatter_has"
  FRONTMATTER_MISSING = "frontmatter_missing"
  IS_FOLDER_NOTE = "is_folder_note"
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

  Guarantees:
    - BASENAME and BASENAME_STEM are the only interpolation tokens a template string may reference.

  Attributes:
    BASENAME: The full-basename token reference.
    BASENAME_STEM: The basename-without-extension token reference.
  """

  # Domain(obsidian.icon-resolution):
  # # Icon template interpolation
  # A resolve block's icon or color name may reference the note's own basename, or the basename with
  # its file extension stripped, as an interpolation token inside the template string. The worker
  # substitutes these tokens with the actual note filename fragments before the resolved value is
  # written back to the note's frontmatter.

  # Contract:
  # BASENAME and BASENAME_STEM are the only interpolation tokens a resolve block's template string
  # may reference.

  BASENAME = "basename"
  BASENAME_STEM = "basename.stem"


# ----------------------------------------------------------------------------------------
class YamlScalar:
  """
  YAML scalar literals the flat frontmatter parser recognizes.

  Guarantees:
    - TRUE and FALSE are the only spellings the flat frontmatter parser recognizes as booleans; every
      other value, including any different casing or a numeric literal, is read back as a plain
      string.

  Attributes:
    TRUE: The boolean-true scalar token.
    FALSE: The boolean-false scalar token.
  """

  # Domain(obsidian.icon-resolution):
  # # Frontmatter scalar recognition for matching
  # When a predicate compares a note's frontmatter value against a literal, the frontmatter is read by
  # a flat parser that recognizes only the literal true and false tokens as booleans; every other
  # scalar value, including numbers and quoted or unquoted strings, is treated as a plain string. A
  # predicate that expects a boolean must match this literal spelling exactly.

  # Contract:
  # TRUE and FALSE are the only spellings the flat frontmatter parser recognizes as booleans; every
  # other value, including any different casing or a numeric literal, is read back as a plain string.

  TRUE = "true"
  FALSE = "false"


# ----------------------------------------------------------------------------------------
class VersionStatus:
  """
  Compatibility-classification tokens emitted by the version report.

  Guarantees:
    - The version report's STATUS field always carries exactly one of MISSING, OK, or INCOMPATIBLE;
      DECLARED never appears as a STATUS value, it names the report's separate declared-schema field.

  Attributes:
    MISSING: No icon-map present.
    OK: Icon-map is fully compatible.
    INCOMPATIBLE: Icon-map schema or min-hook-version is unsatisfiable.
    DECLARED: The report key carrying the icon-map's declared schema generation.
  """

  # Domain(obsidian.icon-resolution):
  # # Icon-map compatibility gate
  # An icon-map document declares the schema generation it was authored against and the minimum
  # worker version required to interpret it correctly. Before resolving any icon, the worker compares
  # its own version against these two declarations and classifies the map as missing when no icon-map
  # is present, incompatible when the schema generation or the minimum required worker version cannot
  # be satisfied by the running worker, or fully compatible otherwise. A missing or incompatible map
  # means no icon is resolved for any note until the mismatch is fixed.

  # Contract:
  # The version report's STATUS field always carries exactly one of MISSING, OK, or INCOMPATIBLE;
  # DECLARED never appears as a STATUS value, it names the report's separate declared-schema field.

  MISSING = "missing"
  OK = "ok"
  INCOMPATIBLE = "incompatible"
  DECLARED = "declared"
