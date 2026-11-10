"""
Logic behind the `lazycortex-specs release-delta <product-key>` verb.

The verb names the assets a product's next release carries — every approved, unreleased, uncancelled asset of
the product that owns releases and of the nested products that ship with it, for a change once its cascade into
the target designs is done — and finds the product's open release, if any.
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

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import asset_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    RESEARCH_ASSET_TYPE, AssetTypeKey, Gate, ReleaseKey, SpecCascadeKey, SpecKey,
    SpecValue, Stage, StageKey,
)


_ENCODING = "utf-8"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"
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
  """

  note: Path
  token: str
  asset_type: str
  reason: str = ""


def _member_roots(repo: Path, owner_key: str) -> list[Path]:
  """
  List the product roots whose assets ship in the owner's releases.

  Args:
    repo: Repository root.
    owner_key: The release owner's product key.

  Returns:
    The owner's root first, then the roots of every nested product the owner also owns.
  """
  content_root = spec_paths.spec_content_root(repo)
  registry = resolve_product.load_products(repo)
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


def _read_asset_verdict(repo: Path, owner_root: Path, note: Path) -> tuple[DeltaEntry | None, DeltaEntry | None]:
  """
  Judge one status note by the per-asset rules.

  Args:
    repo: Repository root.
    owner_root: The release owner's product root, the tokens' base.
    note: The status note.

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

  # guard: rejects a file that is not a typed status note, so no asset stands behind it
  asset_type = fm_values.get(AssetTypeKey.TYPE, "").strip()
  if fm_values.get(SpecKey.ROLE, "").strip() != SpecValue.ROLE_STATUS or not asset_type:
    return None, None

  # the type's base, read through the owning product's own type declarations
  _product, record = resolve_product.effective_record_by_path(repo, note.relative_to(repo).as_posix())
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
  start = note.parent / start_file
  if not start.is_file():
    return None, None

  # an asset whose start document is not approved is not ready to ship
  start_fm, _end = spec_frontmatter.parse(start.read_text(encoding = _ENCODING))
  if start_fm.get(StageKey.STAGE, "").strip() != Stage.APPROVED:
    return None, None

  # the entry, named by its folder relative to the owner's root
  entry = DeltaEntry(note = note, token = note.parent.relative_to(owner_root).as_posix(), asset_type = asset_type)

  # a change ships only once its delta is folded into the targets' designs; until then it is held back
  if base == _CHANGE_ASSET_TYPE and not _is_true(fm_values, SpecCascadeKey.DONE):
    return None, DeltaEntry(entry.note, entry.token, entry.asset_type, REASON_CASCADE)
  return entry, None


def find_all_delta_entries(repo: Path, key: str) -> tuple[list[DeltaEntry], list[DeltaEntry]]:
  """
  Name the assets the next release of a product carries, and the ones held back.

  Args:
    repo: Repository root.
    key: A product key; the release owner is resolved from it.

  Returns:
    The included entries and the excluded entries, each sorted by token. An excluded entry carries its reason.

  Raises:
    ValueError: If no product in the key's chain owns releases.
  """
  owner_key = resolve_product.find_release_owner_key(repo, key)

  # guard: rejects a product key with no release owner in its chain — an umbrella without code has no delta
  if owner_key is None:
    raise ValueError(f"no release owner above product {key!r}")
  roots = _member_roots(repo, owner_key)
  content_root = spec_paths.spec_content_root(repo)
  all_roots = [ content_root / record[_SPEC_PATH_KEY] for record in resolve_product.load_products(repo).values()
                if isinstance(record, dict) and record.get(_SPEC_PATH_KEY) ]
  foreign = [ path for path in all_roots if path not in roots ]

  # every asset that passes the per-asset checks, and the changes held back by their cascade — one walk from
  # the owner's root, which already descends into every nested product the owner also owns
  included: list[DeltaEntry] = []
  excluded: list[DeltaEntry] = []
  for note in _find_all_status_notes(roots[0], foreign):
    entered, held = _read_asset_verdict(repo, roots[0], note)
    if entered is not None:
      included.append(entered)
    if held is not None:
      excluded.append(held)

  # both lists come back in token order, so the summary reads the same on every run
  by_token = attrgetter(_TOKEN)
  return sorted(included, key = by_token), sorted(excluded, key = by_token)


def find_open_release(repo: Path, key: str) -> Path | None:
  """
  Find the release of a product's owner that is still open.

  Args:
    repo: Repository root.
    key: A product key; the release owner is resolved from it.

  Returns:
    The status note of the first release folder, by name, that is not yet published (`spec_released` is not true,
    a built release included) and not cancelled; None when there is none, or when no product in the key's chain
    owns releases.
  """
  owner_key = resolve_product.find_release_owner_key(repo, key)

  # guard: rejects a product key with no release owner in its chain — no owner, no releases
  if owner_key is None:
    return None

  # the owner's releases folder
  releases = spec_paths.spec_content_root(repo) / resolve_product.load_products(repo)[owner_key][_SPEC_PATH_KEY] \
      / ReleaseKey.FOLDER

  # guard: rejects an owner whose releases folder does not exist yet
  if not releases.is_dir():
    return None

  # the first open release by folder name; the invariant keeps it the only one
  for entry in sorted(os.listdir(releases)):
    note = releases / entry / f"{entry}{_MD_SUFFIX}"

    # guard: rejects a folder without its own note, which is no release
    if not note.is_file():
      continue
    fm_values, _end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))
    if not _is_true(fm_values, Gate.RELEASED) and not _is_true(fm_values, Gate.SPEC_CANCELLED):
      return note
  return None


def main(argv: list[str]) -> int:
  """
  Print the delta of a product's next release.

  The repository root comes from the `LAZY_REPO_ROOT` environment variable, falling back to the process working
  directory.

  Notes:
    - Prints a JSON summary on stdout with the keys `owner`, `open_release` (repo-relative note path or null),
      `included` (tokens) and `excluded` (objects with `token` and `reason`).

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 1 when no product in the key's chain owns releases.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs release-delta")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("product")
  args = parser.parse_args(argv)
  repo = scaffold_asset.repo_root(Path(os.environ.get(_ENV_REPO_ROOT) or Path.cwd()))

  # the owner decides the delta
  owner_key = resolve_product.find_release_owner_key(repo, args.product)

  # guard: rejects a product key with no release owner in its chain
  if owner_key is None:
    sys.stderr.write(f"no release owner above product {args.product!r}\n")
    return 1
  included, excluded = find_all_delta_entries(repo, owner_key)
  note = find_open_release(repo, owner_key)
  print(json.dumps({
      _OWNER: owner_key,
      _OPEN_RELEASE: note.relative_to(repo).as_posix() if note is not None else None,
      _INCLUDED: [ entry.token for entry in included ],
      _EXCLUDED: [ { _TOKEN: entry.token, _REASON: entry.reason } for entry in excluded ],
  }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
