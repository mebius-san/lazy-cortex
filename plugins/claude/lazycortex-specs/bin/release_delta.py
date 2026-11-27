"""
Logic behind the `lazycortex-specs release-delta <product-key>` and `release-type-guidelines <release-note>` verbs.

The `release-delta` verb names the assets a product's next release carries — every approved, unreleased,
uncancelled asset of the product that owns releases and of the nested products that ship with it, for a change once
its cascade into the target designs is done — finds the product's open release, if any, and reports the two facts a
release start waits on: whether the owner's `architecture.md` is approved later than every design the release
carries, and which notes carry an open coherence conflict. A product with no architecture document, or a run with
`--no-architecture`, holds no design back.

The `release-type-guidelines` verb answers, for one release note, which guideline files the type of each included
asset declares, each a repo-relative path or an absolute path into a plugin tree, so a caller reads the guidelines
that apply to the release's assets without resolving types itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


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
import gate_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
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
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    RESEARCH_ASSET_TYPE, AssetTypeKey, ConflictKey, Gate, LevelDoc, ReleaseKey, SpecCascadeKey, SpecKey,
    SpecMomentKey, SpecValue, Stage, StageKey,
)


_ENCODING = "utf-8"
_MD_SUFFIX = ".md"
_SPEC_PATH_KEY = "spec_path"
# The one shipped type whose delta entry waits for its cascade into the targets' designs
_CHANGE_ASSET_TYPE = "change"

# Exclusion reasons
REASON_CASCADE = "cascade-pending"
REASON_NO_START_DOC = "no-start-doc"

# Summary keys
_OWNER = "owner"
_OPEN_RELEASE = "open_release"
_INCLUDED = "included"
_EXCLUDED = "excluded"
_TOKEN = "token"
_REASON = "reason"
_ARCHITECTURE = "architecture"
_DOC = "doc"
_APPROVED_AT = "approved_at"
_BEHIND = "behind"
_CONFLICTED = "conflicted"

# Type-guidelines answer keys and its warning prefixes
_RELEASE = "release"
_ASSETS = "assets"
_ASSET = "asset"
_TYPE = "type"
_BASE_TYPE = "base_type"
_GUIDELINES = "guidelines"
_WARNINGS = "warnings"
_ERROR = "error"
_WARN_MEMBER_NOT_FOUND = "included asset not found: "

# The wikilink delimiters a `spec_includes` member carries around its target, and what may follow the target inside
WIKILINK_OPEN = "[["
WIKILINK_CLOSE = "]]"
_WIKILINK_DISPLAY = "|"
_WIKILINK_ANCHOR = "#"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class DeltaEntry:
  """
  One asset the delta rule judged.

  Attributes:
    note: The asset's status note.
    token: The asset folder's path relative to the release owner's root.
    asset_type: The asset's `spec_asset_type`.
    reason: Why the asset is held back, empty for an included one.
    approved_at: The approval moment of the asset's start document, empty when it carries none or the asset is
      held back.
  """

  note: Path
  token: str
  asset_type: str
  reason: str = ""
  approved_at: str = ""


def _member_roots(repo: Path, owner_key: str, registry: dict) -> list[Path]:
  """
  List the product roots whose assets ship in the owner's releases.

  Args:
    repo: Repository root.
    owner_key: The release owner's product key.
    registry: The products registry the release is looked up in.

  Returns:
    The owner's root first, then the roots of every nested product the owner also owns.
  """
  content_root = spec_paths.spec_content_root(repo)
  roots = [ content_root / registry[owner_key][_SPEC_PATH_KEY] ]
  pending = [ owner_key ]
  while pending:
    for child in resolve_product.child_keys(repo, pending.pop(), products = registry):
      if resolve_product.find_release_owner_key(repo, child, products = registry) == owner_key:
        roots.append(content_root / registry[child][_SPEC_PATH_KEY])
        pending.append(child)
  return roots


def _find_all_status_notes(root: Path, foreign_roots: list[Path]) -> list[Path]:
  """
  Collect the status notes under a product root, skipping its releases and the trees of other owners.

  Args:
    root: The product root to walk.
    foreign_roots: Roots of products owned elsewhere, never descended into.

  Returns:
    The status note paths, in path order.
  """
  notes: list[Path] = []
  skipped = { str(path.resolve()) for path in foreign_roots }
  for dirpath, dirnames, filenames in os.walk(root):
    here = Path(dirpath)
    dirnames[:] = sorted(
        name for name in dirnames
        if not (here == root and name == ReleaseKey.FOLDER) and str((here / name).resolve()) not in skipped
    )
    note = here / f"{here.name}{_MD_SUFFIX}"
    if here != root and note.name in filenames:
      notes.append(note)
  return notes


def _is_true(fm_values: dict, key: str) -> bool:
  """
  Read a boolean frontmatter key.

  Args:
    fm_values: Parsed frontmatter values.
    key: The key to read.

  Returns:
    True when the key reads as the literal `true`.
  """
  return flip_gate.is_true(fm_values, key)


def _read_asset_verdict(repo: Path, owner_root: Path, note: Path, *,
                        registry: dict) -> tuple[DeltaEntry | None, DeltaEntry | None]:
  """
  Judge one status note by the per-asset rules.

  Args:
    repo: Repository root.
    owner_root: The release owner's product root, the tokens' base.
    note: The status note.
    registry: The products registry the release is looked up in.

  Returns:
    An included entry when the asset enters the delta, or an excluded entry when the change's
    cascade is pending or the asset's type names no start document; both None when the asset is out of the delta's
    scope without being reported.
  """
  fm_values, _fm_end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))

  # Domain(spec.lifecycle):
  # # What the next release carries
  # The delta of a product is every asset of the release owner and of every product nested under
  # it, whether design-only or carrying its own source that only narrows the owner's code, whose
  # start document is approved and which is neither released nor cancelled.
  # A release never enters, as it is the unit of shipping itself; only an asset of the release type
  # itself is meant, while an asset whose type is merely declared as an alias of it is an ordinary
  # asset and can enter. A research asset never enters, whether of the research type itself or of
  # an alias of it, because it has no implementation. An asset whose type names no start document
  # can never be approved: it does not enter, but is reported among the held-back assets as having
  # no start document, rather than passed over silently. An asset whose declared start document is
  # missing on disk is passed over without a report. A change enters only once its cascade into
  # its targets has converged, because the implementer builds from the targets' folded designs,
  # never from the change's own text.

  # the note's declared asset type, empty when it declares none
  asset_type = fm_values.get(AssetTypeKey.TYPE, "").strip()

  # guard: rejects a file that is not a typed status note, so no asset stands behind it
  if fm_values.get(SpecKey.ROLE, "").strip() != SpecValue.ROLE_STATUS or not asset_type:
    return None, None

  # the type's base, read through the owning product's own type declarations; no catalog-wide guidelines are read,
  # since the verdict depends on none
  _product, record = resolve_product.effective_record_by_path(repo, note.relative_to(repo).as_posix(),
                                                              products = registry, catalog_guidelines = {})
  base = asset_types.alias_base(asset_type, record or {}) or asset_type

  # a release, by its own type name only, and a research asset, aliases included, are never members of a delta
  if asset_type == ReleaseKey.ASSET_TYPE or base == RESEARCH_ASSET_TYPE:
    return None, None

  # a released or cancelled asset has already left the ladder
  if _is_true(fm_values, Gate.RELEASED) or _is_true(fm_values, Gate.SPEC_CANCELLED):
    return None, None

  # the type's start document, which carries the approval
  start_file, _doc_type = asset_types.start_doc(asset_type, record or {})

  # an asset whose type names no start document can never be approved, so it is reported rather than dropped
  if not start_file:
    return None, DeltaEntry(note, note.parent.relative_to(owner_root).as_posix(), asset_type, REASON_NO_START_DOC)

  # guard: rejects an asset whose start document is not on disk
  if not (start := note.parent / start_file).is_file():
    return None, None

  # an asset whose start document is not approved is not ready to ship
  start_fm, _end = spec_frontmatter.parse(start.read_text(encoding = _ENCODING))
  if start_fm.get(StageKey.STAGE, "").strip() != Stage.APPROVED:
    return None, None

  # the entry, named by its folder relative to the owner's root
  entry = DeltaEntry(
      note = note, token = note.parent.relative_to(owner_root).as_posix(), asset_type = asset_type,
      approved_at = str(start_fm.get(SpecMomentKey.APPROVED_AT, "")).strip(),
  )

  # a change ships only once its delta is folded into the targets' designs; until then it is held back
  if base == _CHANGE_ASSET_TYPE and not _is_true(fm_values, SpecCascadeKey.DONE):
    return None, DeltaEntry(entry.note, entry.token, entry.asset_type, REASON_CASCADE)
  return entry, None


def find_all_delta_entries(repo: Path, key: str, *,
                           products: dict | None = None) -> tuple[list[DeltaEntry], list[DeltaEntry]]:
  """
  Name the assets the next release of a product carries, and the ones held back.

  Args:
    repo: Repository root.
    key: A product key; the release owner is resolved from it.
    products: An already-read products registry; None reads the merged one the expert runtime dispatches from, the
      local overlay merged on.

  Returns:
    The included entries and the excluded entries, each sorted by token. An excluded entry carries its reason.

  Raises:
    ValueError: If no product in the key's chain owns releases, or if `products` is None and the merged settings
      cannot be read; the latter is a `spec_paths.SettingsError` naming the settings file, also when no core CLI
      resolves.
  """
  # the registry the whole release is looked up in, as the runtime dispatches from it unless the caller read it
  registry = products if products is not None else resolve_product.read_runtime_products(repo)
  owner_key = resolve_product.find_release_owner_key(repo, key, products = registry)

  # guard: rejects a product key with no release owner in its chain — an umbrella without code has no delta
  if owner_key is None:
    raise ValueError(f"no release owner above product {key!r}")

  # the owner's member products, and the roots of every other product, which the walk never enters
  roots = _member_roots(repo, owner_key, registry)
  content_root = spec_paths.spec_content_root(repo)
  all_roots = [ content_root / record[_SPEC_PATH_KEY] for record in registry.values()
                if isinstance(record, dict) and record.get(_SPEC_PATH_KEY) ]
  foreign = [ path for path in all_roots if path not in roots ]

  # every asset that passes the per-asset checks, and the changes held back by their cascade — one walk from
  # the owner's root, which already descends into every nested product the owner also owns
  included: list[DeltaEntry] = []
  excluded: list[DeltaEntry] = []
  for note in _find_all_status_notes(roots[0], foreign):
    entered, held = _read_asset_verdict(repo, roots[0], note, registry = registry)
    if entered is not None:
      included.append(entered)
    if held is not None:
      excluded.append(held)

  # both lists come back in token order, so the summary reads the same on every run
  by_token = attrgetter(_TOKEN)
  return sorted(included, key = by_token), sorted(excluded, key = by_token)


def find_architecture_lag(repo: Path,
                          owner_key: str,
                          included: list[DeltaEntry], *,
                          waived: bool = False,
                          products: dict | None = None) -> tuple[Path, str | None, list[str]]:
  """
  Name the delta's assets the owner's architecture document does not cover yet.

  Guarantees:
    - The lagging tokens come back in the order of `included`.
    - A product with no `architecture.md` file, or a call that waives the architecture, reports no asset behind.
    - While a present architecture document is not approved, or is approved with no recorded moment, every included
      asset lags.

  Args:
    repo: Repository root.
    owner_key: The release owner's product key.
    included: The delta's included entries, in the order they are reported.
    waived: When True, the architecture holds no asset back, whatever the document says.
    products: An already-read products registry; None reads the merged one the expert runtime dispatches from, the
      local overlay merged on.

  Returns:
    The path of `architecture.md` in the owner's root, its approval moment — `None` when the document is absent,
    not approved, or approved with no recorded moment — and the tokens of the included assets it is behind, in
    the order of `included`; empty when the file is absent or the architecture is waived.

  Raises:
    ValueError: If `products` is None and the merged settings cannot be read; a `spec_paths.SettingsError` naming
      the settings file, also when no core CLI resolves.
  """

  # Contract:
  # The lagging tokens are returned in the order of `included`, so the release start reports them
  # the same way on every run.

  # Contract:
  # When the owner product has no architecture document file at all, or the caller waives the architecture,
  # no asset is reported as lagging.

  # Contract:
  # While a present architecture document is not approved, or is approved with no recorded moment,
  # every included asset is reported as lagging; a release MUST NEVER start from such a document.

  # Domain(spec.lifecycle):
  # # The architecture covers a design only once it is approved after it
  # A product's architecture is one document for all its releases, and it answers for every approved design of
  # the product. It covers a design when its own approval came later than the design's: an architecture approved
  # earlier was written without that design in view, whatever its text happens to say. An architecture that is
  # not approved covers nothing, and a design whose approval moment is unknown cannot be shown to be covered, so
  # both count against it. Two approvals at the same moment are covered. A release starts only from an
  # architecture that is behind none of the designs it would carry.
  # The rule binds only a product that keeps an architecture. A product with no architecture document at all holds
  # no design back, and neither does a product whose own rules waive the document, even while a stale document
  # still exists. A document that is present but not approved is no such exception: it still covers nothing.

  # the owner's architecture document, named whether or not it exists
  registry = products if products is not None else resolve_product.read_runtime_products(repo)
  doc = spec_paths.spec_content_root(repo) / registry[owner_key][_SPEC_PATH_KEY] / LevelDoc.ARCHITECTURE

  # the document's approval moment, read only from an approved document
  approved_at: str | None = None
  if doc.is_file():
    fm_values, _end = spec_frontmatter.parse(doc.read_text(encoding = _ENCODING))
    if fm_values.get(StageKey.STAGE, "").strip() == Stage.APPROVED:
      approved_at = str(fm_values.get(SpecMomentKey.APPROVED_AT, "")).strip() or None

  # guard: a product with no architecture document, or whose rules waive it, holds no design back
  if waived or not doc.is_file():
    return doc, approved_at, []

  # guard: an architecture with no approval moment covers no design at all
  if approved_at is None:
    return doc, None, [ entry.token for entry in included ]

  # the moments are fixed-width UTC stamps, so their text order is their time order
  return doc, approved_at, [
      entry.token for entry in included if not entry.approved_at or entry.approved_at > approved_at
  ]


def find_all_conflicted_notes(repo: Path, owner_key: str, included: list[DeltaEntry], *,
                              products: dict | None = None) -> list[Path]:
  """
  List the notes of a product's next release that carry an open coherence conflict.

  Guarantees:
    - The search covers the level notes of the owner's root and of every nested product that ships with it, and the
      status notes of the included assets; no other note is reported.

  Args:
    repo: Repository root.
    owner_key: The release owner's product key.
    included: The delta's included entries.
    products: An already-read products registry; None reads the merged one the expert runtime dispatches from, the
      local overlay merged on.

  Returns:
    The level notes of the owner's root and of every nested product that ships with it, and the status notes of
    the included assets, that carry `spec_conflicted: true`, sorted by path.

  Raises:
    ValueError: If `products` is None and the merged settings cannot be read; a `spec_paths.SettingsError` naming
      the settings file, also when no core CLI resolves.
  """

  # Contract:
  # Every product level that ships in the owner's releases, nested member products included, and every
  # included asset is searched for an open conflict. A release start is held while the result is non-empty,
  # so a level left out of the search would let a conflicted release start.

  # the level note of every product root that ships in the owner's releases, then the delta's own assets
  registry = products if products is not None else resolve_product.read_runtime_products(repo)
  candidates = [ root / f"{root.name}{_MD_SUFFIX}" for root in _member_roots(repo, owner_key, registry) ]
  candidates.extend(entry.note for entry in included)

  # a note counts only while its conflict flag reads true
  conflicted: list[Path] = []
  for note in candidates:
    # guard: rejects a product root that has no level note on disk
    if not note.is_file():
      continue
    fm_values, _end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))
    if _is_true(fm_values, ConflictKey.CONFLICTED):
      conflicted.append(note)
  return sorted(conflicted)


def find_open_release(repo: Path, key: str, *, products: dict | None = None) -> Path | None:
  """
  Find the release of a product's owner that is still open.

  Args:
    repo: Repository root.
    key: A product key; the release owner is resolved from it.
    products: An already-read products registry; None reads the merged one the expert runtime dispatches from, the
      local overlay merged on.

  Returns:
    The status note of the first numbered release folder, by name, that is not yet published (`spec_released` is
    not true, a built release included) and not cancelled; None when there is none, or when no product in the
    key's chain owns releases. Only numbered folders directly in `releases/` count, so the archive is never
    searched or returned.

  Raises:
    ValueError: If `products` is None and the merged settings cannot be read; a `spec_paths.SettingsError` naming
      the settings file, also when no core CLI resolves.
  """
  # the registry the release is looked up in, as the runtime dispatches from it unless the caller read it
  registry = products if products is not None else resolve_product.read_runtime_products(repo)
  owner_key = resolve_product.find_release_owner_key(repo, key, products = registry)

  # guard: rejects a product key with no release owner in its chain — no owner, no releases
  if owner_key is None:
    return None

  # Domain(spec.lifecycle):
  # # Only numbered release folders can be the open release
  # A product has at most one open release, found among the numbered release folders of its releases folder. The
  # archive that sits beside them holds only closed history and is never taken for a release, however it is
  # named or what it contains.

  # the owner's releases folder
  releases = spec_paths.spec_content_root(repo) / registry[owner_key][_SPEC_PATH_KEY] / ReleaseKey.FOLDER

  # guard: rejects an owner whose releases folder does not exist yet
  if not releases.is_dir():
    return None

  # the first open release by folder name; the invariant keeps it the only one
  for entry in sorted(os.listdir(releases)):
    note = releases / entry / f"{entry}{_MD_SUFFIX}"

    # guard: rejects any folder not named by an ASCII decimal number, the archive included, and any numbered
    # folder without its own note: none of them is a release
    if not (entry.isascii() and entry.isdigit()) or not note.is_file():
      continue

    # a release neither published nor cancelled is the open one
    fm_values, _end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))
    if not _is_true(fm_values, Gate.RELEASED) and not _is_true(fm_values, Gate.SPEC_CANCELLED):
      return note
  return None


def resolve_included_notes(vault: Path, release_text: str) -> list[Path]:
  """
  Resolve the status notes a release's `spec_includes` links to.

  Args:
    vault: The vault root holding `.claude/lazy.settings.json`.
    release_text: The release note's text.

  Returns:
    One note path per wikilink, in the order listed; display text and anchors are ignored. A path need not exist
    on disk.
  """
  return [ spec_paths.resolve_wikilink(target, vault) for target in _find_all_include_targets(release_text) ]


def _find_all_include_targets(release_text: str) -> list[str]:
  """
  List the bare wikilink targets of a release's `spec_includes`.

  Args:
    release_text: The release note's text.

  Returns:
    One target per member, in the order listed, without brackets, display text or anchor.
  """
  targets: list[str] = []

  # each member loses its brackets first, then whatever follows the target inside them
  for link in spec_frontmatter.read_list(release_text, ReleaseKey.INCLUDES):
    bare = link.strip().removeprefix(WIKILINK_OPEN).removesuffix(WIKILINK_CLOSE)
    targets.append(bare.split(_WIKILINK_DISPLAY, 1)[0].split(_WIKILINK_ANCHOR, 1)[0].strip())
  return targets


def read_type_guidelines(repo: Path, release_note: Path) -> dict:
  """
  List the guideline files each type of a release's included assets declares.

  Each member is answered from the type declarations of the product that owns it, so a nested product's own
  declarations apply to its assets. The declarations are read as the expert runtime dispatches from them, the local
  overlay merged on. A declared entry is a repo-relative path or a `<plugin>:<name>` reference key.

  Guarantees:
    - A declared guideline entry that does not resolve to a file, and an included member that resolves to no note,
      are never dropped silently: each is named in `warnings`, once.
    - A reference key comes back as an absolute path into the plugin tree, a path stays repo-relative as written,
      and the enabled plugins' canon never joins a type's list.
    - Every member that is not cancelled is listed, even with an empty `guidelines` list, in the order the release
      lists its members.
    - `base_type` is the alias base the type's alias names, or the type itself when it declares none; a broken alias
      raises `ValueError` and is never guessed around.

  Args:
    repo: The repository root holding `.claude/lazy.settings.json`.
    release_note: The release's status note, as a path inside the repository.

  Returns:
    `{"release", "assets", "warnings"}` — one `{"asset", "type", "base_type", "guidelines"}` entry per included
    asset that is not cancelled, in the order the release lists them. `base_type` follows the type's alias, and is
    the type itself when it is no alias. `guidelines` holds each resolved file, repo-relative or an absolute path
    into a plugin tree; a declared entry that does not resolve to a file is left out. The warnings name each member
    that resolves to no note and each declared entry that does not resolve.

  Raises:
    ValueError: If a member's type names a broken alias base, or if the merged settings cannot be read; the latter
      is a `spec_paths.SettingsError` naming the settings file.
  """

  # Contract:
  # Every member that is not cancelled is listed, even with an empty `guidelines` list, in the order the release
  # lists its members; the release implementer stops the build on an empty list for a member whose `base_type`
  # is `content`, so a member left out or reordered would hide that stop.

  # Contract:
  # A declared guideline entry that does not resolve to a file, and an included member that resolves to no note, are
  # never dropped silently: each is named in `warnings`, once.

  # Contract:
  # A reference key comes back as an absolute path into the plugin tree, a path stays repo-relative as written, and
  # the enabled plugins' canon never joins a type's list.

  # Contract:
  # `base_type` is the alias base the type's alias names, or the type itself when it declares none. A broken
  # alias raises `ValueError`; a base type is never guessed.

  # Domain(spec.dispatch):
  # # Guidelines of a release build
  # A release build covers the whole product, so the guidelines that an asset kind declares must reach it for
  # every asset the release carries. For a content kind these include the schema its records are written against.
  # For each carried asset the build is told its kind, the kind it is coordinated like when it borrows another
  # kind's playbook, and the files its own kind declares. An abandoned asset is built into nothing and gets none.
  # A declared file that does not exist, and a carried asset whose note cannot be found, are reported as gaps and
  # never skipped silently. A kind whose borrowing is broken is an error, never a guess. A data-defined asset whose
  # kind gives no schema stops the build, because its format must not be inferred from the data that exists.

  # the per-member answers and the gaps reported beside them, filled member by member below
  assets: list[dict] = []
  warnings: list[str] = []
  # opt: one call's members share `resolved`, which lives only for this call, so an answer never outlives the files
  # and plugin trees it was read from; members whose types declare the same entries cost one core call
  resolved: dict[tuple[str, ...], tuple[list[str], list[str]]] = {}

  # the registry and the catalog-wide guidelines as the runtime sees them, the local overlay merged on, read once
  settings = resolve_product.read_runtime_settings(repo)
  registry = resolve_product.filter_products(settings)
  catalog = resolve_product.build_catalog_guidelines(settings)

  # each live member is answered for the product that owns its own note, so a nested member reads its own record
  for target in _find_all_include_targets(release_note.read_text(encoding = _ENCODING)):
    note = spec_paths.resolve_wikilink(target, repo)

    # guard: a member that resolves to no note has no type to answer for, so it is only reported
    if not note.is_file():
      warnings.append(f"{_WARN_MEMBER_NOT_FOUND}{target}")
      continue

    # a cancelled member is built into nothing, so it is left out of the answer
    if _is_true(spec_frontmatter.parse(note.read_text(encoding = _ENCODING))[0], Gate.SPEC_CANCELLED):
      continue

    # the member's type, read against the record of the product that owns its note
    note_rel = note.relative_to(repo).as_posix()
    record = resolve_product.effective_record_by_path(repo, note_rel, products = registry,
                                                      catalog_guidelines = catalog)[1] or {}
    asset_type = asset_types.type_of(note)

    # the type's own entries resolved by core without any plugin's canon, which belongs to a role and never to a
    # type; an entry with no file is left out and reported, never silently dropped
    entries = tuple(asset_types.guidelines(asset_type, record))
    if entries and entries not in resolved:
      resolved[entries] = gate_dispatch.resolve_guideline_entries(repo, list(entries))
    paths, missing = resolved.get(entries, ( [], [] ))
    warnings += missing
    assets.append({ _ASSET: note_rel, _TYPE: asset_type,
                    _BASE_TYPE: asset_types.alias_base(asset_type, record) or asset_type, _GUIDELINES: list(paths) })
  return { _RELEASE: release_note.relative_to(repo).as_posix(), _ASSETS: assets,
           _WARNINGS: list(dict.fromkeys(warnings)) }


def main(argv: list[str]) -> int:
  """
  Print the delta of a product's next release.

  The run works in the nearest directory, within its checkout, that holds `.claude/lazy.settings.json`, searched
  upward from the directory the `LAZY_REPO_ROOT` environment variable names, else the process working directory;
  the checkout's root when none holds it.

  Guarantees:
    - The JSON summary always carries `architecture`, with `doc`, `approved_at` and `behind`, and `conflicted`; a
      release start is held while `behind` or `conflicted` is non-empty.
    - `behind` lists the tokens of the included assets in the order of `included`; `conflicted` lists
      repo-relative note paths, sorted.
    - The `--no-architecture` flag empties `behind`.
    - A failed run exits 1 with the reason on standard error and prints no JSON summary; the summary is read only
      on exit 0, and a failed run, an unreadable settings file included, is never data about a release owner.

  Notes:
    - Prints a JSON summary on stdout with the keys `owner`, `open_release` (repo-relative note path or null),
      `included` (tokens), `excluded` (objects with `token` and `reason`), `architecture` (an object with `doc`,
      the repo-relative path of the owner's `architecture.md`; `approved_at`, its approval moment or null; and
      `behind`, the tokens of the included assets it does not cover yet) and `conflicted` (repo-relative paths of
      the notes that carry an open coherence conflict).
    - With `--no-architecture`, `behind` is always empty, so a product's own rules can waive the architecture.

  Args:
    argv: Command-line arguments, excluding the program name; `--no-architecture` reports no asset as behind the
      architecture.

  Returns:
    Exit code: 0 on success; 1 when the settings cannot be read or no product in the key's chain owns releases.
  """

  # Contract:
  # The printed JSON summary always carries the key `architecture`, an object with `doc`, `approved_at` and
  # `behind`, and the key `conflicted`; the product coordinator parses them to decide whether a release may
  # start, and a start is held while `behind` or `conflicted` is non-empty. `behind` lists the tokens of the
  # included assets in the order of `included`; `conflicted` lists repo-relative note paths, sorted. The flag
  # `--no-architecture` empties `behind`.

  # Contract:
  # A run that fails, whether the settings cannot be read or no product in the key's chain owns releases, exits 1,
  # writes the reason to standard error and prints no JSON summary on standard output; a caller parses the
  # summary only on exit 0 and never takes a failed run, an unreadable settings file included, as data about a
  # release owner.

  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs release-delta")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("product")
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--no-architecture", action = "store_true")
  args = parser.parse_args(argv)
  repo = spec_locator.query_settings_root()

  # the registry every lookup of this release reads, as the runtime dispatches from it; unreadable settings are an
  # error, never a product without an owner
  try:
    registry = resolve_product.read_runtime_products(repo)
  except ValueError as error:
    sys.stderr.write(f"{error}\n")
    return 1

  # the owner decides the delta
  owner_key = resolve_product.find_release_owner_key(repo, args.product, products = registry)

  # guard: rejects a product key with no release owner in its chain
  if owner_key is None:
    sys.stderr.write(f"no release owner above product {args.product!r}\n")
    return 1

  # the delta and the release currently open
  included, excluded = find_all_delta_entries(repo, owner_key, products = registry)
  note = find_open_release(repo, owner_key, products = registry)

  # the two facts a release start waits on: the architecture's lag and the open conflicts
  doc, approved_at, behind = find_architecture_lag(repo, owner_key, included, waived = args.no_architecture,
                                                   products = registry)
  conflicted = find_all_conflicted_notes(repo, owner_key, included, products = registry)
  print(json.dumps({
      _OWNER: owner_key,
      _OPEN_RELEASE: note.relative_to(repo).as_posix() if note is not None else None,
      _INCLUDED: [ entry.token for entry in included ],
      _EXCLUDED: [ { _TOKEN: entry.token, _REASON: entry.reason } for entry in excluded ],
      _ARCHITECTURE: {
          _DOC: doc.relative_to(repo).as_posix(), _APPROVED_AT: approved_at, _BEHIND: behind,
      },
      _CONFLICTED: [ path.relative_to(repo).as_posix() for path in conflicted ],
  }))
  return 0


def main_type_guidelines(argv: list[str]) -> int:
  """
  Print the guideline files each type of a release's included assets declares.

  The run works in the nearest directory, within its checkout, that holds `.claude/lazy.settings.json`, searched
  upward from the directory the `LAZY_REPO_ROOT` environment variable names, else the process working directory;
  the checkout's root when none holds it.

  Guarantees:
    - Stdout carries the answer as one JSON line without its warnings; each warning is one line on stderr.
    - A release note that is no file, a broken alias base, or settings that cannot be read yields exit code 1 and
      the JSON line `{"release", "assets": null, "error"}`; `assets` is never a partial list.

  Args:
    argv: Command-line arguments, excluding the program name: the release note, repo-relative or absolute.

  Returns:
    Exit code: 0 when the release is answered; 1 when the release note is no file, a member's type names a broken
    alias base, or the settings cannot be read, after printing `{"release", "assets": null, "error"}`.
  """

  # Contract:
  # Stdout carries the answer as one JSON line that never contains the warnings; each warning is one line on
  # stderr. The release coordinator parses stdout and reads stderr as the warnings.

  # Contract:
  # When the release note is no file, a member's type names a broken alias base, or the merged settings cannot be
  # read, the exit code is 1 and stdout carries a JSON line whose `assets` is null and whose `error` is set;
  # `assets` is never a partial list.

  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs release-type-guidelines")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("release_note")
  args = parser.parse_args(argv)
  repo = spec_locator.query_settings_root()
  note = repo / args.release_note

  # guard: a release note that is no file has no members to answer for
  if not note.is_file():
    print(json.dumps({ _RELEASE: args.release_note, _ASSETS: None, _ERROR: f"release note not found: {note}" }))
    return 1

  # guard: a member whose type names a broken alias base, or settings that cannot be read, leave no answer to give;
  # either is an error, never a guess or an empty list
  try:
    answer = read_type_guidelines(repo, note)
  except ValueError as error:
    print(json.dumps({ _RELEASE: args.release_note, _ASSETS: None, _ERROR: str(error) }))
    return 1

  # the warnings go beside the answer, never inside it
  for warning in answer.pop(_WARNINGS):
    print(warning, file = sys.stderr)
  print(json.dumps(answer))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
