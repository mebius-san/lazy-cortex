"""
Note canonization verbs for `spec.coordinator`.

`spec.coordinator` canonizes an asset status folder-note with two tools: its own pen for body
prose (`# Status brief`, `[!question]` callouts, `# Coordinator commands` locking — see
`lazy-spec.coordinator.md`'s "Your pen" section) and the CLI verbs of this module for everything else.

`note-set-key` validates and writes one frontmatter key drawn from the CLOSED schema the
coordinator is allowed to own — its own lifecycle, cascade and release bookkeeping keys, nothing
else. Every other frontmatter key on a status folder-note (`spec_role`, `tags`,
`spec_source_requests`) belongs to a different worker's own primitive and is refused here. The
two job markers are not frontmatter at all — they live in `spec_job_markers.py`'s runtime
sidecar and are written through `mark-job`, so this verb refuses their names like any other key
outside its schema.

`note-check` is a read-only structural scan: unrecognized or mistyped frontmatter keys, and a
missing or misordered required section from the canonical roster (`# Gates`, `# Status brief`
with its `#protected/spec/status-brief` marker, `# Coordinator rules`, `# Coordinator commands`,
`# History`, plus `# Attachments` on a `product` / `catalog` level note). It reports violations
as JSON and fixes nothing — repairing a broken note is the
coordinator's own job, done through its pen and through `note-set-key`. Its result also carries
the note's `job_markers` sidecar entry, so a reader that used to find the two markers in
frontmatter still gets them from one call.

`question-clear-ticks` unticks a coordinator question whose ticked options contradict each other and leaves
a notice under it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Mapping


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import asset_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import gate_tick  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import summary_render  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    BOOL_FALSE,
    BOOL_TRUE,
    FLIPPABLE_GATES,
    GATE_ORDER,
    LEVEL_GATES,
    LEVEL_ROLES,
    PROTECTED_ATTACHMENTS,
    PROTECTED_COORD_COMMANDS,
    PROTECTED_COORD_RULES,
    PROTECTED_STATUS_BRIEF,
    AnsweredQuestionKey,
    AssetTypeKey,
    ConflictKey,
    Gate,
    ReleaseKey,
    Section,
    SpecCascadeKey,
    SpecCoordinatorDocStateKey,
    SpecCoordinatorReadyStateKey,
    SpecHaltKey,
    SpecKey,
    SpecMomentKey,
    SpecStateKey,
    SpecTargetsKey,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from spec_lockit import Lockit  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# ----------------------------------------------------------------------------------------
class _Kind:
  """
  Frontmatter value-shape tokens used to type-check and serialize a schema key's value.

  Attributes:
    BOOL: The `true`/`false` literal shape written by `flip_gate.set_bool`.
    STR: The bare single-line scalar shape written by this module's own `set_fm_scalar`.
    LIST: The YAML block-list shape, or the empty inline-list shape (`key: []`), that
      `gate_tick.write_fm_list` writes.
    DICT: The compact single-line JSON object shape `gate_tick.set_fm_json` writes.
    INT: A bare non-negative integer scalar, written by this module's own `set_fm_scalar`.
    MOMENT: An ISO 8601 UTC moment to the second, `YYYY-MM-DDTHH:MM:SSZ`, written by this module's own
      `set_fm_scalar`.
  """

  # The `true`/`false` literal shape written by `flip_gate.set_bool`.
  BOOL = "bool"
  # The bare single-line scalar shape written by this module's own `set_fm_scalar`.
  STR = "str"
  # The YAML block-list shape, or the empty inline-list shape (`key: []`), that `gate_tick.write_fm_list` writes.
  LIST = "list"
  # The compact single-line JSON object shape `gate_tick.set_fm_json` writes.
  DICT = "dict"
  # A bare non-negative integer scalar, written by this module's own `set_fm_scalar`.
  INT = "int"
  # An ISO 8601 UTC moment to the second, `YYYY-MM-DDTHH:MM:SSZ`, written by this module's own `set_fm_scalar`.
  MOMENT = "moment"


# ----------------------------------------------------------------------------------------
class _ResultKey:
  """
  Result-dict field names shared by this module's own returned dicts.

  Attributes:
    STATUS: The `note_set_key` outcome-field key.
    OK: The `note_check` overall-pass field key.
    JOB_MARKERS: The `note_check` field carrying the note's runtime job-marker sidecar entry.
    NOTE: The `note_check` field naming the note that was checked.
    VIOLATIONS: The `note_check` field listing every finding.
    KIND: The field naming which violation a finding is.
    KEY: The field naming the frontmatter key a finding is about.
    REASON: The field carrying a refusal's human-readable cause.
    VALUE: The field carrying the offending raw value.
    EXPECTED: The field naming the shape a `BAD_TYPE` finding expected.
    SECTION: The field naming the body section a finding is about.
    SECTIONS: The field listing the canonical section order a finding compares against.
    MARKER: The field carrying the owner tag a section was missing.
  """

  # The `note_set_key` outcome-field key.
  STATUS = "status"
  # The `note_check` overall-pass field key.
  OK = "ok"
  # The `note_check` field carrying the note's runtime job-marker sidecar entry.
  JOB_MARKERS = "job_markers"
  # The `note_check` field naming the note that was checked.
  NOTE = "note"
  # The `note_check` field listing every finding.
  VIOLATIONS = "violations"
  # The field naming which violation a finding is.
  KIND = "kind"
  # The field naming the frontmatter key a finding is about.
  KEY = "key"
  # The field carrying a refusal's human-readable cause.
  REASON = "reason"
  # The field carrying the offending raw value.
  VALUE = "value"
  # The field naming the shape a `BAD_TYPE` finding expected.
  EXPECTED = "expected"
  # The field naming the body section a finding is about.
  SECTION = "section"
  # The field listing the canonical section order a finding compares against.
  SECTIONS = "sections"
  # The field carrying the owner tag a section was missing.
  MARKER = "marker"


# ----------------------------------------------------------------------------------------
class _Violation:
  """
  `_ResultKey.KIND` values `note_check` reports, the vocabulary its callers branch on.

  Attributes:
    UNKNOWN_KEY: A frontmatter key the note schema does not recognize.
    BAD_TYPE: A recognized key whose raw value does not parse into its declared shape.
    MISSING_SECTION: A required body section the note does not carry.
    MISSING_MARKER: A present section whose next line is not its protected-owner tag.
    SECTION_ORDER: The required sections are present but not in canonical order.
  """

  # A frontmatter key the note schema does not recognize.
  UNKNOWN_KEY = "unknown-key"
  # A recognized key whose raw value does not parse into its declared shape.
  BAD_TYPE = "bad-type"
  # A required body section the note does not carry.
  MISSING_SECTION = "missing-section"
  # A present section whose next line is not its protected-owner tag.
  MISSING_MARKER = "missing-marker"
  # The required sections are present but not in canonical order.
  SECTION_ORDER = "section-order"


# ----------------------------------------------------------------------------------------
class _SetKeyStatus:
  """
  `_ResultKey.STATUS` values `note_set_key` returns.

  Attributes:
    SET: A fresh frontmatter write landed.
    NOOP: The value already matched what was on disk — no write, no commit.
    REFUSED: The key or value was rejected — no write.
  """

  # A fresh frontmatter write landed.
  SET = "set"
  # The value already matched what was on disk — no write, no commit.
  NOOP = "noop"
  # The key or value was rejected — no write.
  REFUSED = "refused"


# ----------------------------------------------------------------------------------------
class _DropKeyStatus:
  """
  `_ResultKey.STATUS` values `note_drop_key` returns.

  Attributes:
    DROPPED: The key was present and unrecognized, and the note was rewritten without it.
    ABSENT: The note carries no such key — no write, no commit.
    REFUSED: The key is recognized by the note schema, or belongs to another worker — no write.
  """

  # The key was present and unrecognized, and the note was rewritten without it.
  DROPPED = "dropped"
  # The note carries no such key — no write, no commit.
  ABSENT = "absent"
  # The key is recognized by the note schema, or belongs to another worker — no write.
  REFUSED = "refused"


# The namespace prefix of every frontmatter key this plugin authors. A stray key outside it was
# written by some other worker (`iconize_*`, `tags`, `wiki_*`), and removing one would silently
# undo that worker's own state; only a `spec_*` key the note schema does not recognize is this
# plugin's own litter to take back.
_SPEC_KEY_PREFIX = "spec_"


# The closed schema `note-set-key` may write — exactly the coordinator's own frontmatter-owned keys
# per `lazy-spec.coordinator.md`'s verb table: its lifecycle, cascade and release bookkeeping keys.
# Every other frontmatter key on a status folder-note is written by a different worker's own
# primitive and stays out of this verb's reach; the two job markers are written through `mark-job`
# into the runtime sidecar instead.
_WRITABLE_SCHEMA = {
    Gate.DESIGN_DONE: _Kind.BOOL,
    Gate.PLAN_DONE: _Kind.BOOL,
    Gate.DEVELOP_DONE: _Kind.BOOL,
    Gate.TESTS_PASSING: _Kind.BOOL,
    Gate.BUILT: _Kind.BOOL,
    Gate.RELEASED: _Kind.BOOL,
    Gate.SPEC_CANCELLED: _Kind.BOOL,
    SpecHaltKey.HALTED: _Kind.BOOL,
    SpecTargetsKey.TARGETS: _Kind.LIST,
    SpecCascadeKey.DONE: _Kind.BOOL,
    SpecCascadeKey.TARGETS_DONE: _Kind.LIST,
    SpecStateKey.STATE: _Kind.STR,
    # the release note's own two keys: its bare SemVer version and the wikilinks of the assets it carries
    ReleaseKey.VERSION: _Kind.STR,
    ReleaseKey.INCLUDES: _Kind.LIST,
    # the release's build bookkeeping the coordinator writes in a build dispatch: the build's number, its moment,
    # and the flag a `Rebuild` tick raises until the next build is dispatched
    ReleaseKey.BUILD: _Kind.INT,
    ReleaseKey.BUILD_AT: _Kind.MOMENT,
    ReleaseKey.REBUILD_OWED: _Kind.BOOL,
    # the implementation build's own number and moment, which a test-only rebuild leaves standing, the moment of the
    # last `Test` dispatch, and the pin an operator-set version carries
    ReleaseKey.IMPL_BUILD: _Kind.INT,
    ReleaseKey.IMPL_BUILD_AT: _Kind.MOMENT,
    ReleaseKey.TEST_DISPATCHED_AT: _Kind.MOMENT,
    # the job ids of the last `Build` and the last `Test` dispatch, so a failed job is told from a later one
    ReleaseKey.BUILD_JOB: _Kind.STR,
    ReleaseKey.TEST_JOB: _Kind.STR,
    ReleaseKey.VERSION_PINNED: _Kind.BOOL,
    # the asset's kind the coordinator records, held to the types declared in the note's product scope
    AssetTypeKey.TYPE: _Kind.STR,
    # the level ladder's own five gates, spread from the closed set so the schema cannot drift
    # from it; `spec_design_done` is already above and the two ladders share that one key name
    **dict.fromkeys(LEVEL_GATES, _Kind.BOOL),
}

# Member-shape regex for the product-relative path token list — `spec_targets` is the only
# `_Kind.LIST` key whose members name another asset folder
# (`resolve_product.resolve_asset_token`'s own contract); every other LIST-kind key keeps its own
# member shape and is unchecked here.
_ASSET_PATH_TOKEN_RE = re.compile(r"^[^/]+(/[^/]+)*$")

# The one spelling of a frontmatter moment: an ISO 8601 UTC moment to the second, `Z`-suffixed, so moments compare
# by their text
_UTC_MOMENT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_UTC_MOMENT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# The keys whose value decides which bucket a container's stats count the asset in: every write of one of them
# recounts the containers above the asset
_CLASSIFYING_KEYS = frozenset({
    SpecStateKey.STATE, SpecHaltKey.HALTED, Gate.SPEC_CANCELLED, Gate.RELEASED, *GATE_ORDER,
})
_TOKEN_LIST_KEYS = frozenset({ SpecTargetsKey.TARGETS })


# The `tags` / `spec_source_requests` frontmatter key names, declared here rather than imported
# under this bin/ tree's per-file small-constant convention.
_TAGS_KEY = "tags"
_SPEC_SOURCE_REQUESTS_KEY = "spec_source_requests"

# Managed-paint and wiki-pin keys every scaffolded status note legitimately carries: the
# iconize pair is seeded by `scaffold_asset.Keys.ICONIZE_*` and rewritten by the iconize worker,
# `wiki_pinned_topics` ships in the asset-note template (`spec_pins.Keys.WIKI_PINNED_TOPICS`).
ICONIZE_ICON_KEY = "iconize_icon"
ICONIZE_COLOR_KEY = "iconize_color"
_WIKI_PINNED_TOPICS_KEY = "wiki_pinned_topics"

# `note-check`'s recognized-key superset: every `_WRITABLE_SCHEMA` entry plus the other legitimate
# frontmatter keys a status folder-note carries that this verb never writes itself — the
# scaffold-time `spec_role` / `tags`, the `spec_source_requests` slot `apply_request.py` owns, and
# `coordinator_dispatch.py`'s own three worker-internal markers — the answered-question fingerprint,
# the sibling-doc review-result marker, and the approval snapshot (all deliberately outside
# `_WRITABLE_SCHEMA` — the coordinator persona never writes any of them itself). The busy-guard's
# own declined/job-done wake lives in the runtime sidecar (`spec_job_markers.py`), never
# frontmatter, so it carries no entry here. Recognizing them here means their ordinary presence
# never reads as a "garbage key" finding.
_NOTE_SCHEMA = {
    **_WRITABLE_SCHEMA,
    # the moment beside every gate (`spec_design_done_at`, …): written by `flip-gate` when the
    # gate turns true, dropped when it turns false
    **{ f"{gate}{SpecMomentKey.AT_SUFFIX}": _Kind.STR for gate in FLIPPABLE_GATES },
    SpecKey.ROLE: _Kind.STR,
    _TAGS_KEY: _Kind.LIST,
    _SPEC_SOURCE_REQUESTS_KEY: _Kind.LIST,
    AnsweredQuestionKey.FINGERPRINT: _Kind.STR,
    SpecCoordinatorDocStateKey.STATE: _Kind.DICT,
    SpecCoordinatorReadyStateKey.STATE: _Kind.DICT,
    ICONIZE_ICON_KEY: _Kind.STR,
    ICONIZE_COLOR_KEY: _Kind.STR,
    _WIKI_PINNED_TOPICS_KEY: _Kind.LIST,
    # the coherence verbs' own pair: the conflicted flag and the one-line JSON list of dismissed pairs
    ConflictKey.CONFLICTED: _Kind.BOOL,
    ConflictKey.DISMISSED: _Kind.LIST,
}

# Canonical required-section roster and order, per `lazy-spec.coordinator.md`'s asset-note templates
# (Task 4). `# Summary` is template-present but plugin-owned (`summary_render.py`), not part of
# the coordinator's own canonization concern, so it is not required here; an optional
# `# Sources` section (`lazy-spec.sources-protocol.md`) is neither required nor flagged.
_REQUIRED_SECTIONS = (
    Section.GATES,
    Section.STATUS_BRIEF,
    Section.COORD_RULES,
    Section.COORD_COMMANDS,
    Section.HISTORY,
)

# The same roster on a level note (`spec_role` in `LEVEL_ROLES`), where `# Attachments` follows
# `# Gates` exactly as on the asset note, as the registry of the level documents' own attachments,
# and `# History` closes the body. It is required there rather than optional because every level
# note is brought to this shape by `catalog-note backfill`, so an absent section means the
# backfill was never run — exactly what the check should say.
_LEVEL_REQUIRED_SECTIONS = (
    Section.GATES,
    Section.ATTACHMENTS,
    Section.STATUS_BRIEF,
    Section.COORD_RULES,
    Section.COORD_COMMANDS,
    Section.HISTORY,
)

# Sections that must carry their `#protected/<owner>/<region>` tag as the very next line
# — a scaffolded placeholder is never a legitimate substitute.
PROTECTED_MARKERS = {
    Section.STATUS_BRIEF: PROTECTED_STATUS_BRIEF,
    Section.COORD_RULES: PROTECTED_COORD_RULES,
    Section.COORD_COMMANDS: PROTECTED_COORD_COMMANDS,
    Section.ATTACHMENTS: PROTECTED_ATTACHMENTS,
}

# Sections the plugin owns but does not require — absent without complaint, marker-checked
# when present. `# Attachments` only exists once an asset actually has one, and pre-existing
# notes predate it, so requiring it would fail every existing asset. An entry here that the
# checked note's own role requires is skipped: the required pass already covered it.
_OPTIONAL_PROTECTED_MARKERS = {
    Section.ATTACHMENTS: PROTECTED_ATTACHMENTS,
}

# Bot identity for this verb's own commit (the frontmatter write), mirroring
# `flip_gate`'s `_FLIP_AUTHOR_NAME` / `_FLIP_AUTHOR_EMAIL` shape. The `@bot.` substring is what
# `coordinator_dispatch.resolve_wake_trigger`'s self-suppression check relies on to never
# re-wake the coordinator on this verb's own writes.
_AUTHOR_NAME = "lazy-spec.note-set-key"
_AUTHOR_EMAIL = f"{_AUTHOR_NAME}@bot.invalid"

# The lockit key of the line written under a question whose contradicting ticks were cleared.
MULTI_TICKED_KEY = "question.multi-ticked"

# The closing lines both coordinator personas sign their own `[!question]` callouts with, each the callout's last
# quoted line; the one set every reader of a coordinator question recognises it by.
QUESTION_SIGNATURES = frozenset({ "> — spec.coordinator", "> — spec.catalog-coordinator" })
# A `[!question]` callout's head line.
_QUESTION_HEAD_RE = re.compile(r"^>\s*\[!question\]")
# Any callout's head line.
_ANY_CALLOUT_HEAD_RE = re.compile(r"^>\s*\[!")
# An option line of a callout; captures its tick and its text.
_OPTION_LINE_RE = re.compile(r"^(?P<open>>\s*-\s*\[)(?P<tick>[^\]\n]*)(?P<close>\]\s*)(?P<text>.*)$")
# The tick character of a ticked option, compared case-insensitively.
_TICK = "x"
# A routing option attaching the request to an asset or a level document; captures the repo-relative path.
_ROUTING_ATTACH_RE = re.compile(r"^attach\s+(\S+)")
# A routing option spawning a change onto assets; captures the comma-separated targets.
_ROUTING_CHANGE_RE = re.compile(r"^spawn\s+change\s+\S+.*?\btargets=(\S+)")
# The `product=` field of a change-spawn routing option; captures the product key.
_ROUTING_PRODUCT_RE = re.compile(r"\bproduct=(\S+)")
# The suffix of a markdown file an attach path names.
_NOTE_SUFFIX = ".md"
# The characters an option's text may be wrapped in, stripped before it is read as a routing line.
_OPTION_WRAP = "` "
# The product-record key holding a product's repo-relative spec path.
_SPEC_PATH = "spec_path"
# The prefix of an asset key whose product cannot be resolved, so it never equals a repo-relative path.
_UNRESOLVED_PREFIX = "unresolved:"


def _attach_target(path: str) -> str:
  """
  Name what an attach routing option settles.

  Args:
    path: The repo-relative path the attach line names.

  Returns:
    The asset folder when the path is an asset's folder-note, named like its folder; the path itself otherwise, a
    level document or a folder named directly.
  """
  folder, _sep, name = path.rpartition("/")

  # a folder-note is named like the folder it opens, and that folder is the asset
  if name.endswith(_NOTE_SUFFIX) and name.removesuffix(_NOTE_SUFFIX) == folder.rpartition("/")[2]:
    return folder
  return path


def _default_product(roots: Mapping[str, str]) -> str | None:
  """
  Name the product a change-spawn that names none lands in.

  Args:
    roots: Product key to the product's repo-relative spec path.

  Returns:
    The alphabetically first product whose spec path no other product's encloses; the alphabetically first product
    when every one is enclosed; `None` for an empty mapping.
  """
  top = [
      key for key, path in roots.items()
      if not any(other != key and path.startswith(f"{root}/") for other, root in roots.items())
  ]
  return min(top or roots, default = None)


def _routing_assets(option: str, roots: Mapping[str, str]) -> list[str] | None:
  """
  Name the assets a routing option settles, each as one comparable key.

  A change target is resolved against the spec path of its product, the `product=` one or else the default product.

  Args:
    option: The text of one option line, past its checkbox.
    roots: Product key to the product's repo-relative spec path.

  Returns:
    The repo-relative paths the option settles; a change target whose product has no known spec path is keyed by
    its product and token, so it equals only the same target of the same product. `None` when the option is not an
    attach or a change-spawn routing line.
  """
  text = option.strip(_OPTION_WRAP)

  # an attach names its target by a repo-relative path
  if attach := _ROUTING_ATTACH_RE.match(text):
    return [ _attach_target(attach.group(1).strip(_OPTION_WRAP)) ]

  # a change-spawn names its assets by paths relative to its product, the named one or the default
  if change := _ROUTING_CHANGE_RE.match(text):
    named = _ROUTING_PRODUCT_RE.search(text)
    product = named.group(1).strip(_OPTION_WRAP) if named else _default_product(roots)
    root = roots.get(product) if product is not None else None
    tokens = [ token.strip("/") for token in change.group(1).strip(_OPTION_WRAP).split(",") if token ]
    return [ f"{root}/{token}" if root else f"{_UNRESOLVED_PREFIX}{product}:{token}" for token in tokens ]
  return None


def product_roots(repo: Path) -> dict[str, str]:
  """
  Read each registered product's spec path, the roots routing options are resolved against.

  Args:
    repo: The repository root holding `.claude/lazy.settings.json`.

  Returns:
    Product key to its repo-relative spec path; empty when the settings cannot be read or register no product.
  """
  # an unreadable registry resolves no product, so change targets are compared by their own product and token
  try:
    registry = resolve_product.load_products(repo)
  except ValueError:
    return {}
  return {
      key: str(record[_SPEC_PATH]).strip("/") for key, record in registry.items()
      if isinstance(record, dict) and record.get(_SPEC_PATH)
  }


def ticks_contradict(options: list[str], roots: Mapping[str, str] | None = None) -> bool:
  """
  Judge whether the ticked options of one coordinator question contradict each other.

  Guarantees:
    - One ticked option, or none, never contradicts.
    - Routing options ticked once for each of several assets or level documents do not contradict; two ticked
      routing options that settle one asset do. A change target is resolved against its own product, the named one
      or the default, so the same relative path in two products is two assets.
    - Any other pair of ticked options contradicts.

  Args:
    options: The texts of the question's ticked options, past their checkboxes.
    roots: Product key to the product's repo-relative spec path; `None` resolves no product.

  Returns:
    True when the ticks cannot all be applied, False otherwise.
  """

  # Contract:
  # One ticked option, or none, never contradicts. Routing options ticked for different assets, each asset resolved
  # against its own product, never contradict; two different options settling the same resolved asset always do.
  # Any other pair of ticked options always contradicts.

  # Domain(spec.lifecycle):
  # # Contradicting ticks on a coordinator question apply nothing
  # The options of a coordinator question exclude one another, so a question the operator ticked more than once
  # carries no answer and none of its ticked options is applied. The one question whose options do not all exclude
  # one another is the routing question, which offers an attach and a change for each existing asset the request
  # touches: ticks on different assets are one answer per asset, while two ticks on the same asset contradict each
  # other and settle nothing.

  # one tick or none is an answer, or no answer yet
  if len(options) < 2:
    return False
  assets = [ _routing_assets(option, roots or {}) for option in options ]

  # a ticked option that is not a routing line makes every second tick a contradiction
  if any(named is None for named in assets):
    return True

  # routing ticks contradict only when two different options settle one asset
  seen: dict[str, int] = {}
  for index, named in enumerate(assets):
    for asset in set(named or ()):
      if seen.setdefault(asset, index) != index:
        return True
  return False


def clear_contradicting_questions(text: str, notice: str, roots: Mapping[str, str] | None = None) -> tuple[str, int]:
  """
  Clear the ticks of every coordinator question whose ticked options contradict each other, and say why.

  Guarantees:
    - Only `[!question]` callouts signed by a coordinator persona are touched; every one whose ticks contradict
      comes back with all its options unticked and one `notice` line under its last option, never a second one.
    - Every other byte of the note stays identical.

  Args:
    text: The note's full text.
    notice: The line written under the options, in the note's language.
    roots: Product key to the product's repo-relative spec path, the routing question's targets are resolved
      against; `None` resolves no product.

  Returns:
    The note's text with the ticks cleared, and the number of questions cleared.
  """

  # Contract:
  # Only questions signed by a coordinator whose ticked options contradict are touched. Each comes back with every
  # option unticked and exactly one notice line under its last option, never a second one on a repeat call. Every
  # other byte of the note stays identical.

  lines = text.split("\n")
  cleared = 0
  index = 0
  while index < len(lines):
    # a line that opens no question starts no block worth reading
    if not _QUESTION_HEAD_RE.match(lines[index].strip()):
      index += 1
      continue

    # the block runs over the quoted lines after the head, up to the next callout or the first unquoted line
    end = index + 1
    while end < len(lines) and lines[end].startswith(">") and not _ANY_CALLOUT_HEAD_RE.match(lines[end].strip()):
      end += 1
    body = [ line.strip() for line in lines[index + 1:end] if line.strip() != ">" ]
    options = [
        ( row, match ) for row in range(index + 1, end) if (match := _OPTION_LINE_RE.match(lines[row].strip()))
    ]
    # waiver: the named groups of `_OPTION_LINE_RE`, spelled once in the pattern beside it
    ticked = [ match["text"] for _row, match in options if match["tick"].strip().lower() == _TICK ]

    # an unsigned question, or one whose ticks do not contradict, is left as it is
    if not body or body[-1] not in QUESTION_SIGNATURES or not ticks_contradict(ticked, roots):
      index = end
      continue

    # every option is unticked, and the notice goes under the last one unless it already stands there
    for row, match in options:
      # waiver: the named groups of `_OPTION_LINE_RE`, spelled once in the pattern beside it
      lines[row] = f"{match['open']} {match['close']}{match['text']}"
    if f"> {notice}" not in body:
      lines.insert(options[-1][0] + 1, f"> {notice}")
      end += 1
    cleared += 1
    index = end
  return "\n".join(lines), cleared


def main_clear_ticks(argv: list[str]) -> int:
  """
  Run `question-clear-ticks` from the command line.

  Unticks the options of every coordinator question in the note whose ticks contradict each other and writes a
  notice, in the note's language, under each. Nothing is committed. Routing targets are resolved against the
  products registered in the note's vault.

  Notes:
    - Prints a JSON object with the number of questions cleared to standard output.
    - The note is rewritten only when at least one question was cleared.

  Args:
    argv: Command-line arguments, excluding the program name and subcommand.

  Returns:
    Exit code: 0 on success, including when no question needed clearing; 2 when the note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs question-clear-ticks")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("note", type = Path)
  note: Path = parser.parse_args(argv).note.resolve()

  # guard: the note must exist
  if not note.is_file():
    sys.stderr.write(f"no note: {note}\n")
    return 2

  # the note is rewritten only when a question was cleared, so a repeat call is a no-op on disk
  original = note.read_text(encoding = "utf-8")
  vault = spec_paths.find_settings_root(note.parent)
  text, cleared = clear_contradicting_questions(
      original, Lockit.text(MULTI_TICKED_KEY, note_explainers.lang_for_note(note)),
      product_roots(vault) if vault is not None else None)
  if cleared:
    note.write_text(text, encoding = "utf-8")
  print(json.dumps({ "cleared": cleared }))
  return 0


def set_fm_scalar(fm_text: str, key: str, value: str) -> str:
  """
  Add or replace a scalar `key: value` line inside a frontmatter block.

  The value is written bare when YAML reads it back verbatim, and double-quoted (escapes
  included) otherwise, so the key always stays one line.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The scalar frontmatter key to set.
    value: The replacement string value.

  Returns:
    The updated frontmatter text.
  """
  return spec_frontmatter.set_scalar(fm_text, key, value)


def is_asset_path_token(member: str) -> bool:
  """
  Judge whether a cross-asset token names a folder reachable from the product root.

  Args:
    member: One `spec_targets` member.

  Returns:
    True when the token is a non-empty path of non-empty segments, none of them a `.` or `..`
    step; False otherwise.
  """
  # guard: an empty token, or one carrying an empty segment, anchors at no folder
  if not _ASSET_PATH_TOKEN_RE.match(member):
    return False
  return not any(segment in (".", "..") for segment in member.split("/"))


def is_utc_moment(raw: str) -> bool:
  """
  Tell whether a value is an ISO 8601 UTC moment to the second, written `YYYY-MM-DDTHH:MM:SSZ`.

  Args:
    raw: The value to check.

  Returns:
    True when the value has exactly that shape and names a real calendar moment.
  """

  # guard: any other spelling — a bare date, an offset, a space separator, fractions — is not the one shape
  if _UTC_MOMENT_RE.fullmatch(raw) is None:
    return False

  # the shape alone admits a 13th month or a 31st of February; the calendar decides
  try:
    datetime.strptime(raw, _UTC_MOMENT_FORMAT)
  except ValueError:
    return False
  return True


def _parse_value(kind: str, raw: str, key: str) -> tuple[object, str | None]:
  """
  Parse and validate a CLI-supplied value string against a schema key's expected shape.

  Args:
    kind: The `_Kind` token naming the expected shape.
    raw: The raw CLI argument — `true`/`false` for `_Kind.BOOL`, a bare string for `_Kind.STR`, a run of digits
      for `_Kind.INT`, a UTC moment `YYYY-MM-DDTHH:MM:SSZ` for `_Kind.MOMENT`, a JSON array of strings for
      `_Kind.LIST`.
    key: The frontmatter key being written — threaded through to the member-shape check the two
      product-relative path token list carries.

  Returns:
    A `(value, error)` pair — `value` is the parsed Python object (bool / str / list[str]; an integer or a moment
    kept as its text) on success with `error` None; on failure `value` is None and `error` names what was wrong.
  """
  if kind == _Kind.BOOL:
    # guard: only the two literal tokens `flip_gate.set_bool` writes are accepted
    if raw not in (BOOL_TRUE, BOOL_FALSE):
      return None, f"expected 'true' or 'false', got {raw!r}"
    return raw == BOOL_TRUE, None
  if kind == _Kind.STR:
    # guard: an empty scalar is never a legitimate value for a str-typed key
    if not raw:
      return None, "expected a non-empty string"
    return raw, None
  if kind == _Kind.INT:
    # guard: only a bare run of digits is a build number; a sign, a fraction or a word is not
    if not (raw.isascii() and raw.isdigit()):
      return None, f"expected a non-negative integer, got {raw!r}"
    return raw, None
  if kind == _Kind.MOMENT:
    # guard: only a real UTC moment to the second, `Z`-suffixed, compares against the other moments by its text
    if not is_utc_moment(raw):
      return None, f"expected an ISO 8601 UTC moment YYYY-MM-DDTHH:MM:SSZ, got {raw!r}"
    return raw, None

  # every other kind returned above, so only `_Kind.LIST` remains
  try:
    parsed = json.loads(raw)
  except json.JSONDecodeError:
    return None, f"expected a JSON list of strings, got {raw!r}"

  # guard: not a list, or a list with a non-string member — no `_Kind.LIST` key takes either
  if not isinstance(parsed, list) or not all(isinstance(member, str) for member in parsed):
    return None, f"expected a JSON list of strings, got {raw!r}"

  # Domain(spec.notes):
  # # Cross-asset references are product-relative paths
  # An asset points at another asset — as a cascade target — through the
  # target's path from the owning product's root, however deep that is: a bare slug for an asset
  # sitting at the product root, two segments for one under a group folder, more for one nested
  # inside another asset. Anchoring at the product root is what lets the token resolve to exactly
  # one asset across a catalog where the same slug can legitimately recur under different
  # folders, so a token that anchors nowhere is refused here rather than accepted and silently
  # failing to resolve later.

  # guard: `spec_targets` carries product-relative paths — a member that
  # resolves to no folder under the product root (empty, an empty segment, a `.` / `..` step)
  # is refused here rather than writing clean and only surfacing as a silent context-fold-in
  # miss later (M8)
  if key in _TOKEN_LIST_KEYS and not all(is_asset_path_token(member) for member in parsed):
    return None, (f"expected every member to be a path relative to the product root,"
                  f" got {raw!r}")
  return parsed, None


def _apply_value(fm_text: str, key: str, kind: str, value: object) -> str:
  """
  Write a parsed value into the frontmatter block through the shape-appropriate helper.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The frontmatter key to write.
    kind: The `_Kind` token naming `value`'s shape.
    value: The parsed value, as returned by `_parse_value`.

  Returns:
    The updated frontmatter text.

  Raises:
    TypeError: When `value`'s runtime type does not match `kind`.
  """
  if kind == _Kind.BOOL and isinstance(value, bool):
    return flip_gate.set_bool(fm_text, key, value)
  if kind in ( _Kind.STR, _Kind.INT, _Kind.MOMENT ) and isinstance(value, str):
    return set_fm_scalar(fm_text, key, value)
  if kind == _Kind.LIST and isinstance(value, list):
    return gate_tick.write_fm_list(fm_text, key, [str(item) for item in value])
  raise TypeError(f"value {value!r} does not match kind {kind!r}")


def _format_value(kind: str, value: object) -> str:
  """
  Render a parsed value back to the string form folded into the commit subject.

  Args:
    kind: The `_Kind` token naming `value`'s shape.
    value: The parsed value, as returned by `_parse_value`.

  Returns:
    `"true"`/`"false"` for `_Kind.BOOL`, the compact JSON text for `_Kind.LIST`, or the bare
    string itself for `_Kind.STR`, `_Kind.INT` and `_Kind.MOMENT`.
  """
  if kind == _Kind.BOOL:
    return str(value).lower()
  if kind == _Kind.LIST:
    return json.dumps(value)
  return str(value)


def _commit(asset_dir: Path, note: Path, key: str, value_str: str, *, containers: list[Path] | None = None) -> None:
  """
  Commit the rewritten status folder-note, with the container notes its write moved, under the
  `lazy-spec.note-set-key` bot identity.

  Skipped silently when the asset lives in a vault outside a git checkout — the file write
  remains, and is the entire mutation that case observes.

  Args:
    asset_dir: The asset folder, locating the enclosing repository.
    note: The folder-note path that was just rewritten.
    key: The frontmatter key that was set, folded into the commit subject.
    value_str: The value's rendering, folded into the commit subject.
    containers: The container notes whose stats region the write moved, carried by the same commit.

  Raises:
    subprocess.CalledProcessError: If the commit fails, registering a new file with `git add -N` fails, or git
      fails during the status query.
    OSError: If git cannot name the top level while a `.git` entry is in sight, so a lookup failure is never read
      as "no repository", or if git cannot be run for the status query or the commit.
  """
  repo = flip_gate.find_repo_top(asset_dir)

  # guard: the vault lives outside a git checkout — nothing to commit into; the file write
  # above stays and is the whole mutation. A git failure inside a checkout raised above
  if repo is None:
    return

  # Domain(obsidian.icon-repaint):
  # # Paint rides the same commit as the state it reflects
  # An icon's colour is a read of the note's own state, so a change that could alter that read
  # must never land in a commit of its own: repainting separately would leave a window where the
  # folder shows a colour the note's actual state no longer matches, visible to anyone browsing
  # the vault before the second commit catches up. The repaint is folded into the very commit
  # that changed the state instead, so whenever the repaint is available the two land together.
  # The repaint is best-effort: when the repainting plugin is absent, misconfigured, or fails,
  # the state change is committed alone with its old colours, and they are refreshed only by the
  # next change to the note.

  # commit the note by pathspec under the dedicated bot identity, its icon repaint folded in, so the tree is
  # clean for the next daemon iteration and the operator's authorship and staging stay untouched
  flip_gate.commit_paths(
      repo, [ note, *(containers or []) ], subject = f"{_AUTHOR_NAME}: {key} → {value_str} on {asset_dir.name}",
      author_name = _AUTHOR_NAME, author_email = _AUTHOR_EMAIL,
  )


def _find_undeclared_type_reason(asset_dir: Path, asset_type: str) -> str | None:
  """
  Say why an asset type cannot be recorded on a note in a folder.

  Args:
    asset_dir: The asset folder holding the note.
    asset_type: The asset type about to be written.

  Returns:
    The reason when neither the plugin nor the product covering the folder, its ancestors included, declares the
    type; None when the type is declared there.
  """
  # the covering product's effective record names the types visible in its scope, the shipped ones included
  vault = spec_paths.find_settings_root(asset_dir.resolve())
  _key, record = resolve_product.effective_record_by_path(vault, asset_dir.resolve().relative_to(vault).as_posix())

  # a type the scope declares is recordable
  if asset_types.resolve(asset_type, record or {}) is not None:
    return None
  return f"undeclared asset type: {asset_type}"


def note_set_key(asset_dir: Path, key: str, raw_value: str) -> dict:
  """
  Validate and write one frontmatter key on an asset's status folder-note.

  Refuses (no file mutation) when `key` is outside the coordinator's closed writable schema, or
  when `raw_value` does not parse into the key's expected shape, or when `key` is `spec_asset_type` and the type is
  not declared in the note's product scope. A value that already matches
  what is on disk is a no-op — no write, no commit. On a genuine change, the frontmatter is
  rewritten and the note is committed under the `lazy-spec.note-set-key` bot identity — the key
  and its new value ride in the commit subject; no `# History` line is appended. A key that decides which
  bucket the asset counts in also brings the stats of every container above the asset up to date, in that
  same commit.

  Guarantees:
    - A key outside the coordinator's closed writable schema is always refused with no file
      mutation.
    - An asset type that no declaration in the note's product scope names, shipped or declared by the product or
      one of its ancestors, is always refused with no file mutation.
    - A value that already matches what is on disk is a no-op: no write and no commit occur.
    - A write of a key that decides the asset's bucket carries every container note above the asset whose stats
      region changed in the same commit as the asset's note, so no container is left counting the asset's old
      state.
    - A key write whose commit does not land leaves the working tree as it found it: the note and every container
      note whose counts were refreshed get back the bytes they held before the write, and the exception
      propagates unchanged, so a retry redoes the change instead of answering `noop` over an uncommitted note.

  Args:
    asset_dir: The asset folder holding `<asset_dir.name>.md`.
    key: The `spec_*` frontmatter key to set.
    raw_value: The value as a CLI argument string — `true`/`false` for a bool-typed key, a bare
      string for a str-typed key, a run of digits for an int-typed key, a UTC moment `YYYY-MM-DDTHH:MM:SSZ` for a
      moment-typed key, a JSON array of strings for a list-typed key.

  Returns:
    `{"status": "set", "key", "value"}` on a fresh write, `{"status": "noop", "key"}` when the
    value already matched, or `{"status": "refused", "key", "reason"}` when the key is unknown, the value fails to
    parse, or the asset type is not declared in the note's product scope.

  Raises:
    subprocess.CalledProcessError: When the commit or a git query it makes fails; the note and every container note
      whose counts were refreshed are first put back to the bytes they held, and the error propagates.
    OSError: When git cannot be run; the note and the refreshed container notes are first put back the same way.
  """

  # Domain(spec.notes):
  # # Closed vocabulary for coordinator-owned frontmatter
  # An asset's status note carries state contributed by several independent workers sharing one
  # file, and the coordinator's own share of it is a fixed, closed set of keys — the lifecycle
  # gates of both the asset ladder and the level ladder, the cancellation and halt flags, the cascade lists,
  # the derived state token, the asset's kind, and a release's version, contents and build bookkeeping. A key
  # outside that set is never the coordinator's to set, however plausible its name looks, because writing it would
  # silently overwrite state another worker owns and relies on staying exactly as it left it. The asset's kind is
  # held to the kinds declared for the asset's product: a kind that no declaration in that product's scope names is
  # refused, so the note never claims a kind the product does not know.

  # Contract:
  # A key outside the coordinator's closed writable schema is always refused with no file
  # mutation — this verb NEVER writes a key it does not itself own.

  # Contract:
  # An asset type that no declaration in the note's product scope names, whether shipped with the plugin or declared
  # by the product or one of its ancestors, is always refused with no file mutation; only a declared type is ever
  # recorded as the note's asset type.

  # Contract:
  # A value that already matches what is on disk is treated as a no-op: no frontmatter write
  # and no commit occur.

  # Contract:
  # A write of a key that decides which bucket the asset counts in carries every container note above the asset
  # whose stats region changed in the same commit as the asset's note; no commit of such a write leaves a container
  # counting the asset's old state.

  # Contract:
  # A key write whose commit does not land leaves the working tree as it found it: the note and every container
  # note whose counts were refreshed get back the bytes they held before the write, and the exception is
  # re-raised unchanged, so a retry redoes the change instead of answering `noop` over an uncommitted note.

  # guard: key outside the coordinator's closed writable schema — clean refusal, no write
  if (kind := _WRITABLE_SCHEMA.get(key)) is None:
    return {_ResultKey.STATUS: _SetKeyStatus.REFUSED, _ResultKey.KEY: key,
            _ResultKey.REASON: f"unknown key: {key}"}

  # validate and parse the CLI value against the key's declared shape
  value, error = _parse_value(kind, raw_value, key)

  # guard: value does not parse into the key's expected shape — clean refusal, no write
  if error is not None:
    return {_ResultKey.STATUS: _SetKeyStatus.REFUSED, _ResultKey.KEY: key, _ResultKey.REASON: error}

  # guard: an asset type no declaration in the note's product scope names — clean refusal, no write
  if key == AssetTypeKey.TYPE and (error := _find_undeclared_type_reason(asset_dir, raw_value)) is not None:
    return {_ResultKey.STATUS: _SetKeyStatus.REFUSED, _ResultKey.KEY: key, _ResultKey.REASON: error}

  # read the note's current frontmatter so the value write lands precisely
  note = asset_dir / f"{asset_dir.name}.md"
  text = spec_paths.read_text(note)
  _, fm_end = flip_gate.parse_frontmatter(text)
  fm_text = text[:fm_end]

  # apply the parsed value through the shape-appropriate writer
  new_fm_text = _apply_value(fm_text, key, kind, value)

  # the value already matches what is on disk — nothing to write or commit
  if new_fm_text == fm_text:
    return {_ResultKey.STATUS: _SetKeyStatus.NOOP, _ResultKey.KEY: key}

  # the value as the commit message names it
  value_str = _format_value(kind, value)

  # the bytes of every file this call rewrites, held before the rewrite: a commit that does not land gives each
  # of them back, so a failed write leaves the tree clean and a retry redoes it
  above = flip_gate.containers_above(asset_dir) if key in _CLASSIFYING_KEYS else []
  held: dict[Path, bytes | None] = {
      path: path.read_bytes() if path.is_file() else None for path in ( note, *above )
  }
  try:
    # the note is written with its section explainers refreshed; a key write is the ladder's mechanics and leaves no
    # `# History` line — the journal is for events the operator reads, and the commit below already records the write
    spec_paths.write_text_atomic(
        note,
        new_fm_text + note_explainers.ensure_explainers(text[fm_end:], note_explainers.lang_for_note(note)))

    # a key that decides the asset's bucket moves the counts of every container above it; those that changed
    # ride the note's commit, so no container ever reads a count the note no longer matches
    containers = [ container for container in above if summary_render.apply_container_stats(container) ]
    _commit(asset_dir, note, key, value_str, containers = containers)
  # waiver: the rollback boundary catches every exception on purpose, an interrupt included — a written file
  # must never outlive a commit that did not land, and the exception is re-raised unchanged
  except BaseException:
    _restore_held(held)
    raise
  return {_ResultKey.STATUS: _SetKeyStatus.SET, _ResultKey.KEY: key, _ResultKey.VALUE: value_str}


def _restore_held(held: dict[Path, bytes | None]) -> None:
  """
  Put every held file back to the state it had before a write.

  Args:
    held: The bytes each file held before the write, or None for a file that did not exist and is removed again.
  """
  # a file that did not exist is removed again; any other gets the bytes it held
  for path, data in held.items():
    if data is None:
      path.unlink(missing_ok = True)
    else:
      path.write_bytes(data)


def _drop_fm_key(fm_text: str, key: str) -> str:
  """
  Remove one key and everything it owns from a frontmatter block.

  A block-form value continues on the lines below its key, so the removal takes the key's own
  line plus every following line that is indented or a bullet — up to the next key line or the
  closing fence.

  Args:
    fm_text: The note's frontmatter block, fences included.
    key: The frontmatter key to remove.

  Returns:
    The block without that key; the block unchanged when it carries none.
  """
  lines = fm_text.split("\n")
  kept: list[str] = []
  dropping = False
  for line in lines:
    # a key's own line opens the removal and is itself dropped
    if line.startswith(f"{key}:"):
      dropping = True
      continue

    # still inside the dropped key's block-form value — its continuation lines go too
    # — the closing fence also starts with `-` and is never one of them
    if dropping and line.startswith((" ", "\t", "-")) and line.strip() and line.rstrip() != "---":
      continue
    dropping = False
    kept.append(line)
  return "\n".join(kept)


def note_drop_key(asset_dir: Path, key: str) -> dict:
  """
  Remove one unrecognized `spec_*` frontmatter key from a folder-note.

  This is the counterpart of `note_set_key` for litter rather than state: a key the note schema
  does not recognize is what `note_check` reports as an "unknown-key" violation, and this verb is
  the only door that takes one back off. Refuses (no file mutation) when the key IS recognized —
  a recognized key holds state and changing it is `note_set_key`'s business — and when the key
  lies outside this plugin's own `spec_` namespace, since another worker owns it. On a genuine
  removal the frontmatter is rewritten and the note is committed under the
  `lazy-spec.note-set-key` bot identity — the removed key rides in the commit subject; no
  `# History` line is appended.

  Guarantees:
    - A key recognized by the note schema, or one outside this plugin's own `spec_` namespace,
      is always refused with no file mutation.
    - A key drop whose commit does not land leaves the working tree as it found it: the note gets back the bytes
      it held before the drop and the exception propagates unchanged, so a retry redoes the removal instead of
      answering `absent` over an uncommitted note.

  Args:
    asset_dir: The folder holding `<asset_dir.name>.md` — an asset's folder or a level's.
    key: The frontmatter key to remove.

  Returns:
    `{"status": "dropped", "key"}` on a removal, `{"status": "absent", "key"}` when the note
    carries no such key, or `{"status": "refused", "key", "reason"}` when the key is recognized
    or belongs to another worker.

  Raises:
    subprocess.CalledProcessError: When the commit or a git query it makes fails; the note is first put back to the
      bytes it held before the drop, and the error propagates.
    OSError: When git cannot be run; the note is first put back the same way.
  """

  # Domain(spec.notes):
  # # Litter is namespace-owned before it is recognized
  # A note's frontmatter is shared by several independent workers, and only a key that both
  # belongs to this worker's own namespace and is unrecognized by its schema counts as litter
  # this worker may sweep. Ownership is judged before recognition: a key can be unrecognized here
  # yet still belong to another worker, and removing it on that basis alone would delete state
  # that worker still needs, rather than debris of this worker's own making. The same order settles
  # the overlap: a key that is both outside this worker's namespace and recognized by the schema is
  # refused for whose key it is, never for being recognized, because the schema also recognizes
  # several keys that other workers own and the refusal must name the real reason.

  # Contract:
  # A key recognized by the note schema, or one outside this plugin's own `spec_` namespace, is
  # always refused with no file mutation — this verb only ever removes unrecognized litter it
  # itself owns.

  # Contract:
  # A key drop whose commit does not land leaves the working tree as it found it: the note gets back the bytes
  # it held before the drop and the exception is re-raised unchanged, so a retry redoes the removal instead of
  # answering `absent` over an uncommitted note.

  # guard: a key outside this plugin's namespace belongs to another worker — never ours to remove
  if not key.startswith(_SPEC_KEY_PREFIX):
    return {_ResultKey.STATUS: _DropKeyStatus.REFUSED, _ResultKey.KEY: key,
            _ResultKey.REASON: f"foreign key: {key}"}

  # guard: a recognized key carries state, and state is set through `note_set_key`, never dropped
  if key in _NOTE_SCHEMA:
    return {_ResultKey.STATUS: _DropKeyStatus.REFUSED, _ResultKey.KEY: key,
            _ResultKey.REASON: f"recognized key: {key}"}

  # read the note's current frontmatter so the removal lands precisely
  note = asset_dir / f"{asset_dir.name}.md"
  text = spec_paths.read_text(note)
  fm_values, fm_end = flip_gate.parse_frontmatter(text)

  # guard: the note carries no such key — nothing to remove or commit
  if key not in fm_values:
    return {_ResultKey.STATUS: _DropKeyStatus.ABSENT, _ResultKey.KEY: key}

  # strip the key and refresh the section explainers before writing; no `# History` line, as
  # for a key write — the commit records the drop
  held: dict[Path, bytes | None] = { note: note.read_bytes() }
  try:
    spec_paths.write_text_atomic(
        note,
        _drop_fm_key(text[:fm_end], key)
        + note_explainers.ensure_explainers(text[fm_end:], note_explainers.lang_for_note(note)))
    _commit(asset_dir, note, key, _DropKeyStatus.DROPPED)
  # waiver: the rollback boundary catches every exception on purpose, an interrupt included — the written note
  # must never outlive a commit that did not land, and the exception is re-raised unchanged
  except BaseException:
    _restore_held(held)
    raise
  return {_ResultKey.STATUS: _DropKeyStatus.DROPPED, _ResultKey.KEY: key}


def _is_value_ok(raw: str, kind: str) -> bool:
  """
  Check whether a frontmatter key's raw same-line value matches its schema-declared shape.

  A block-form list parses to an empty same-line value, which is accepted for `_Kind.LIST`
  without re-walking the body for its bullet lines.

  Args:
    raw: The key's same-line value, already stripped.
    kind: The `_Kind` token this key is declared as in `_NOTE_SCHEMA`.

  Returns:
    True when the value's shape matches `kind`; False otherwise.
  """
  if kind == _Kind.BOOL:
    return raw.lower() in (BOOL_TRUE, BOOL_FALSE)
  if kind == _Kind.STR:
    return bool(raw)
  if kind == _Kind.INT:
    return raw.isascii() and raw.isdigit()
  if kind == _Kind.MOMENT:
    return is_utc_moment(raw.strip("\"'"))
  if kind == _Kind.LIST:
    # an empty same-line value is the block-list form — accepted without a body re-walk
    if not raw:
      return True
    return raw.startswith("[") and raw.endswith("]")

  # only _Kind.DICT remains
  try:
    return isinstance(json.loads(raw), dict)
  except json.JSONDecodeError:
    return False


def _find_section_line_index(body: str, heading: str) -> int | None:
  """
  Find the line index of an exact-match H1 heading in the folder-note body.

  Args:
    body: The folder-note body text (post-frontmatter) to search.
    heading: The exact heading line to locate (e.g. `# Coordinator commands`).

  Returns:
    The zero-based line index of the heading, or None when absent.
  """
  for idx, line in enumerate(body.splitlines()):
    if line.strip() == heading:
      return idx
  return None


def note_check(asset_note: Path) -> dict:
  """
  Structurally check a folder-note — asset status or level: frontmatter schema + required sections.

  Reports every schema, required-section, section-marker, and section-order violation found,
  and applies no fix. A job marker written into frontmatter surfaces as an unrecognized key.
  The required roster follows the note's own `spec_role`, so a level note owes sections an
  asset's status note does not.

  Guarantees:
    - The required-section roster follows the note's own `spec_role`, so no asset-only key and
      no asset-only section is ever demanded of a level note, and vice versa.
    - Read-only: the note is never written, and no violation is repaired.

  Args:
    asset_note: The status folder-note path to check.

  Returns:
    `{"note": <path>, "ok": <bool>, "violations": [...], "job_markers": {...}}` — `ok` is True
    exactly when `violations` is empty; `job_markers` is the note's sidecar entry, every field of
    the closed marker schema present, unrecorded ones as `None`.
  """

  # Contract:
  # The required-section roster follows the note's own `spec_role`: no asset-only key and no
  # asset-only section is ever demanded of a level note, and no level-only one of an asset note.

  # Contract:
  # Read-only — the note is never written and no violation is repaired.

  # split the note into the two halves the checks below read, and open the findings list
  text = spec_paths.read_text(asset_note)
  frontmatter, fm_end = flip_gate.parse_frontmatter(text)
  body = text[fm_end:]
  violations: list[dict] = []

  # check every present frontmatter key against the recognized schema
  for key, raw in frontmatter.items():
    kind = _NOTE_SCHEMA.get(key)
    if kind is None:
      violations.append({ _ResultKey.KIND: _Violation.UNKNOWN_KEY, _ResultKey.KEY: key })
      continue
    if not _is_value_ok(raw, kind):
      violations.append({ _ResultKey.KIND: _Violation.BAD_TYPE, _ResultKey.KEY: key,
                          _ResultKey.EXPECTED: kind, _ResultKey.VALUE: raw })

  # Domain(spec.notes):
  # # A level note's section roster adds an attachments registry
  # A folder-note's required sections follow a fixed roster in a fixed order, and a note at the
  # product or catalog level owes one section beyond an asset's own: an attachments registry that
  # sits directly after the gates, ahead of the status brief, while the history still closes the
  # body, because a level accumulates artifacts no single document tracks on its own.
  # An asset's own status note has no such registry to require — its own optional attachments
  # section is checked only when present, never demanded.

  # the note's own role picks the roster: a level note owes one section more than an asset's
  required = _LEVEL_REQUIRED_SECTIONS if frontmatter.get(SpecKey.ROLE) in LEVEL_ROLES else _REQUIRED_SECTIONS

  # locate each required section's line, recording its position for the order check below
  positions: dict[str, int] = {}
  for heading in required:
    idx = _find_section_line_index(body, heading)
    if idx is None:
      violations.append({ _ResultKey.KIND: _Violation.MISSING_SECTION, _ResultKey.SECTION: heading })
    else:
      positions[heading] = idx

  # verify each protected section's next line carries its own owner tag
  lines = body.splitlines()
  for section, marker in PROTECTED_MARKERS.items():
    # guard: section itself was never found — nothing to check its marker against
    if section not in positions:
      continue
    marker_idx = positions[section] + 1
    if marker_idx >= len(lines) or lines[marker_idx] != marker:
      violations.append({ _ResultKey.KIND: _Violation.MISSING_MARKER, _ResultKey.SECTION: section,
                          _ResultKey.MARKER: marker })

  # an optional section is never a missing-section finding, but a present one still has to
  # carry its owner tag — an untagged block means some other writer has claimed the heading
  for section, marker in _OPTIONAL_PROTECTED_MARKERS.items():
    # guard: this role requires the section — the required pass above already checked its marker
    if section in required:
      continue
    idx = _find_section_line_index(body, section)

    # guard: the optional section is absent — nothing to validate
    if idx is None:
      continue
    if idx + 1 >= len(lines) or lines[idx + 1] != marker:
      violations.append({ _ResultKey.KIND: _Violation.MISSING_MARKER, _ResultKey.SECTION: section,
                          _ResultKey.MARKER: marker })

  # order is checked only over the sections that were actually found — a missing one is already
  # reported above and must not also trip a spurious order violation
  present_order = [positions[heading] for heading in required if heading in positions]
  if present_order != sorted(present_order):
    violations.append({ _ResultKey.KIND: _Violation.SECTION_ORDER, _ResultKey.SECTIONS: list(required) })

  # the coordinator branches on `ok` alone to decide whether a repair pass is owed at all, and
  # reads the sidecar block for the two markers it used to find in the frontmatter above
  return {
      _ResultKey.NOTE: str(asset_note),
      _ResultKey.OK: not violations,
      _ResultKey.VIOLATIONS: violations,
      _ResultKey.JOB_MARKERS: spec_job_markers.read(flip_gate.repo_root(asset_note.parent), asset_note),
  }


def main_set_key(argv: list[str]) -> int:
  """
  Run `note-set-key` from the command line, printing the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name and subcommand.

  Returns:
    Exit code: 0 on a fresh write or a no-op, 1 on a refusal, 2 when the asset note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs note-set-key")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_dir", type = Path)
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("key")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("value")
  args = parser.parse_args(argv)
  asset_dir: Path = args.asset_dir.resolve()
  note = asset_dir / f"{asset_dir.name}.md"

  # guard: asset status folder-note must exist
  if not note.is_file():
    sys.stderr.write(f"no status folder-note: {note}\n")
    return 2

  # run the write and print its result as JSON on stdout; only a refused write exits non-zero
  result = note_set_key(asset_dir, args.key, args.value)
  print(json.dumps(result))
  return 0 if result[_ResultKey.STATUS] != _SetKeyStatus.REFUSED else 1


def main_drop_key(argv: list[str]) -> int:
  """
  Run `note-drop-key` from the command line, printing the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name and subcommand.

  Returns:
    Exit code: 0 on a removal or an absent key, 1 on a refusal, 2 when the note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs note-drop-key")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_dir", type = Path)
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("key")
  args = parser.parse_args(argv)
  asset_dir: Path = args.asset_dir.resolve()
  note = asset_dir / f"{asset_dir.name}.md"

  # guard: the folder-note must exist
  if not note.is_file():
    sys.stderr.write(f"no status folder-note: {note}\n")
    return 2

  # run the removal and print its result as JSON on stdout; only a refused removal exits non-zero
  result = note_drop_key(asset_dir, args.key)
  print(json.dumps(result))
  return 0 if result[_ResultKey.STATUS] != _DropKeyStatus.REFUSED else 1


def main_check(argv: list[str]) -> int:
  """
  Run `note-check` from the command line, printing the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name and subcommand.

  Returns:
    Exit code: 0 when the note carries no violations, 1 when it does, 2 when the note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs note-check")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_note", type = Path)
  asset_note: Path = parser.parse_args(argv).asset_note.resolve()

  # guard: asset status folder-note must exist
  if not asset_note.is_file():
    sys.stderr.write(f"no status folder-note: {asset_note}\n")
    return 2

  # run the check and print its violations as JSON on stdout; a non-conforming note exits non-zero
  result = note_check(asset_note)
  print(json.dumps(result))
  return 0 if result[_ResultKey.OK] else 1


def main_history(argv: list[str]) -> int:
  """
  Run `note-history` from the command line: append one line under today's day group.

  The coordinator persona's door into `# History`. The line lands through the shared core verb,
  so the section keeps its one shape whoever writes; nothing is committed — the coordinator's
  own wake commit carries it, like every other edit of its pen.

  Args:
    argv: Command-line arguments, excluding the program name and subcommand.

  Returns:
    Exit code: 0 on success, 1 when the verb refuses the line, 2 when the note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs note-history")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_note", type = Path)
  # waiver: argparse CLI signature -- option flag
  parser.add_argument("--line", required = True,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "the line to record, without a leading bullet")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--today", default = None,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "ISO date pinned as the day group")
  args = parser.parse_args(argv)
  asset_note: Path = args.asset_note.resolve()

  # guard: the folder-note must exist
  if not asset_note.is_file():
    sys.stderr.write(f"no status folder-note: {asset_note}\n")
    return 2

  # land the line and print the core verb's result as JSON on stdout
  try:
    result = history_journal.append_to_file(asset_note, args.line, args.today, repo = spec_locator.query_repo_root())
  # the core verb refused the line or could not be resolved — surface the reason, exit 1
  except RuntimeError as error:
    sys.stderr.write(f"{error}\n")
    return 1
  print(json.dumps(result))
  return 0
