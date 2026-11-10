"""
Logic behind the `lazycortex-specs release-scaffold (<product-key> --bump <part> | --refresh <release-note>)` verb.

The verb creates a product's next release from its delta — the release folder under `releases/`, its status note
with the delta's wikilinks in `spec_includes` and its version — and, on a rebuild, pulls the new approvals into an
open release's `spec_includes` without dropping anyone already carried.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import release_delta  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import release_version  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import AssetState, Gate, ReleaseKey, SpecStateKey  # noqa: E402


_ENCODING = "utf-8"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The bot identity this verb commits under
SCAFFOLD_NAME = "lazy-spec.release-scaffold"
_GROUP_NOTE = "group_note"
_MD_SUFFIX = ".md"
_SPEC_PATH_KEY = "spec_path"
_WIKILINK_OPEN = "[["
_WIKILINK_CLOSE = "]]"

# Refusal and usage messages
_MSG_EMPTY_DELTA = "the delta is empty: no approved, unreleased asset to carry"
_MSG_PUBLISHED = "release is published; its members are frozen"
_MSG_USAGE = "usage: release-scaffold <product-key> --bump <part> | --refresh <release-note>\n"

# Result keys
_STATUS = "status"
_REASON = "reason"
_STATUS_SET = "set"
_STATUS_REFUSED = "refused"
_FOLDER = "folder"
_FOLDER_NOTE = "folder_note"
_VERSION = "version"
_INCLUDED = "included"
_ADDED = "added"
_KEPT = "kept"


def compute_next_slug(releases_dir: Path) -> str:
  """
  Number the next release folder.

  Args:
    releases_dir: The product's `releases/` folder, which may not exist yet.

  Returns:
    The highest existing number plus one, zero-padded to the release slug width; `001` for an empty folder.
  """
  # guard: no folder, no releases yet
  if not releases_dir.is_dir():
    return str(1).zfill(ReleaseKey.SLUG_WIDTH)
  numbers = [ int(name) for name in os.listdir(releases_dir) if name.isdigit() and (releases_dir / name).is_dir() ]
  return str(max(numbers, default = 0) + 1).zfill(ReleaseKey.SLUG_WIDTH)


def _include_link(repo: Path, note: Path) -> str:
  """
  Render the wikilink a release's `spec_includes` carries for one asset note.

  Args:
    repo: Repository root.
    note: The asset's status note.

  Returns:
    The content-root-relative link without its `.md` suffix, in wikilink brackets.
  """
  rel = note.resolve().relative_to(spec_paths.spec_content_root(repo).resolve()).as_posix()
  return f"{_WIKILINK_OPEN}{rel[: -len(_MD_SUFFIX)]}{_WIKILINK_CLOSE}"


def _mark_in_release(notes: list[Path]) -> None:
  """
  Paint each included asset's note `in-release`, so the folder colour changes before the asset's own next wake.

  Args:
    notes: The included assets' status notes.
  """
  for note in notes:
    text = note.read_text(encoding = _ENCODING)
    spec_paths.write_text_atomic(note, spec_frontmatter.set_scalar(text, SpecStateKey.STATE, AssetState.IN_RELEASE))


def _refusal(reason: str) -> dict:
  """
  Build a refusal result.

  Args:
    reason: Why the verb did nothing.

  Returns:
    `{"status": "refused", "reason": <reason>}`.
  """
  return { _STATUS: _STATUS_REFUSED, _REASON: reason }


def scaffold_release(repo: Path, key: str, *, bump: str) -> dict:
  """
  Create the next release of a product from its delta.

  Args:
    repo: Repository root.
    key: A product key; the release owner is resolved from it.
    bump: The version part to raise over the previous version: `major`, `minor` or `patch`.

  Returns:
    `{"status": "set", "folder", "folder_note", "version", "included"}` with repo-relative paths and the included
    tokens, or `{"status": "refused", "reason"}` when a release is already open, the delta is empty, no product in
    the chain owns releases, or the scaffold of the release folder is refused.

  Raises:
    ValueError: If `bump` is not one of the three parts, the settings file is not valid JSON, or the previous
      version, read from the manifest or the published releases, is not a bare SemVer version or the manifest has an
      unknown format or no version field.
    subprocess.CalledProcessError: If staging or committing the release fails.
    OSError: If a note or the manifest cannot be read or written.
  """
  owner = resolve_product.find_release_owner_key(repo, key)

  # guard: an umbrella without code owns no releases
  if owner is None:
    return _refusal(f"no release owner above product {key!r}")

  # guard: one open release at a time
  if (open_note := release_delta.find_open_release(repo, owner)) is not None:
    return _refusal(f"a release is already open: {open_note.relative_to(repo).as_posix()}")

  # guard: nothing to ship, nothing to create
  included, _excluded = release_delta.find_all_delta_entries(repo, owner)
  if not included:
    return _refusal(_MSG_EMPTY_DELTA)

  # the release folder and note, from the release type's own template chain
  record = resolve_product.load_products(repo)[owner]
  releases_dir = spec_paths.spec_content_root(repo) / record[_SPEC_PATH_KEY] / ReleaseKey.FOLDER
  slug = compute_next_slug(releases_dir)
  try:
    created = scaffold_asset.scaffold(repo, owner, ReleaseKey.ASSET_TYPE, slug)
  except scaffold_asset.ScaffoldRefusal as refusal:
    return _refusal(refusal.message)
  note = repo / created[_FOLDER_NOTE]

  # the delta's members and the version the release carries; the members read in-release from now on
  text = note.read_text(encoding = _ENCODING)
  links = [ _include_link(repo, entry.note) for entry in included ]
  spec_paths.write_text_atomic(note, spec_frontmatter.write_list(text, ReleaseKey.INCLUDES, links))
  version = release_version.bump(release_version.read_previous_version(repo, record, releases_dir), bump)
  release_version.set_release_version(note, version)
  _mark_in_release([ entry.note for entry in included ])

  # one commit under this verb's identity carries the release folder, its group note and the repainted members
  written = [ note, *( entry.note for entry in included ) ]
  if created.get(_GROUP_NOTE):
    written.append(repo / created[_GROUP_NOTE])
  release_version.commit_paths(repo, written, author = SCAFFOLD_NAME,
                               subject = f"{SCAFFOLD_NAME}: {slug} ({version}) under {owner}")
  return {
      _STATUS: _STATUS_SET, _FOLDER: created[_FOLDER], _FOLDER_NOTE: created[_FOLDER_NOTE], _VERSION: version,
      _INCLUDED: [ entry.token for entry in included ],
  }


def refresh_includes(repo: Path, release_note: Path) -> dict:
  """
  Pull the delta's new members into an open release's `spec_includes`.

  Args:
    repo: Repository root.
    release_note: The release's status note.

  Returns:
    `{"added": [tokens], "kept": [tokens]}` — the members newly listed and the delta members already listed; a
    member listed earlier and no longer in the delta stays listed. `{"status": "refused", "reason"}` when the
    release is published or no product in the note's chain owns releases.
  """
  text = release_note.read_text(encoding = _ENCODING)
  fm_values, _end = spec_frontmatter.parse(text)

  # guard: a published release's members are frozen
  if flip_gate.is_true(fm_values, Gate.RELEASED):
    return _refusal(_MSG_PUBLISHED)

  # guard: a release note under a product that owns no releases has no delta to refresh from
  key, _record = resolve_product.effective_record_by_path(repo, release_note.relative_to(repo).as_posix())
  if key is None or resolve_product.find_release_owner_key(repo, key) is None:
    return _refusal(f"no release owner above the release note {release_note.name!r}")

  # the delta as it stands now, against the members already listed
  included, _excluded = release_delta.find_all_delta_entries(repo, key)
  existing = spec_frontmatter.read_list(text, ReleaseKey.INCLUDES)
  added = [ entry for entry in included if _include_link(repo, entry.note) not in existing ]
  kept = [ entry.token for entry in included if _include_link(repo, entry.note) in existing ]
  if added:
    links = existing + [ _include_link(repo, entry.note) for entry in added ]
    spec_paths.write_text_atomic(release_note, spec_frontmatter.write_list(text, ReleaseKey.INCLUDES, links))
    _mark_in_release([ entry.note for entry in added ])
    release_version.commit_paths(
        repo, [ release_note, *( entry.note for entry in added ) ], author = SCAFFOLD_NAME,
        subject = f"{SCAFFOLD_NAME}: {len(added)} new member(s) in {release_note.parent.name}")
  return { _ADDED: [ entry.token for entry in added ], _KEPT: kept }


def main(argv: list[str]) -> int:
  """
  Create a product's next release, or refresh an open release's members.

  The repository root comes from the `LAZY_REPO_ROOT` environment variable, falling back to the process working
  directory.

  Notes:
    - Prints the JSON result of `scaffold_release` or `refresh_includes` on stdout.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 1 on a refusal, 2 when the arguments name no product or no existing note.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs release-scaffold")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("product", nargs = "?", default = "")
  # waiver: argparse CLI signature -- option name
  parser.add_argument("--bump", choices = release_version.PARTS, default = "")
  # waiver: argparse CLI signature -- option name
  parser.add_argument("--refresh", default = "")
  args = parser.parse_args(argv)
  repo = scaffold_asset.repo_root(Path(os.environ.get(_ENV_REPO_ROOT) or Path.cwd()))

  # the refresh form names a note; the create form names a product and a bump
  if args.refresh:
    note = (repo / args.refresh).resolve()
    # guard: the refresh form names a note that must exist
    if not note.is_file():
      sys.stderr.write(f"no such note: {note}\n")
      return 2
    result = refresh_includes(repo, note)
  elif args.product and args.bump:
    result = scaffold_release(repo, args.product, bump = args.bump)
  else:
    sys.stderr.write(_MSG_USAGE)
    return 2
  print(json.dumps(result))
  return 1 if result.get(_STATUS) == _STATUS_REFUSED else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
