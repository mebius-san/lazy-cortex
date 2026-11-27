"""
Logic behind the `lazycortex-specs release-scaffold (<product-key> --bump <part> | --refresh <release-note>
[--no-architecture])` verb.

The verb creates a product's next release from its delta — the release folder under `releases/`, its status note
with the delta's wikilinks in `spec_includes` and its version, and the refreshed stats of the `releases` group
note — and moves the closed releases into the archive. On a rebuild, it pulls the new approvals the owner's
architecture covers into an open release's `spec_includes` without dropping anyone already carried; a product with
no architecture document, or a refresh with `--no-architecture`, holds no approval back.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
import coordinator_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
import release_delta  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
import release_version  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
import summary_render  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime
# via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import AssetState, Gate, ReleaseKey, SpecStateKey  # noqa: E402


_ENCODING = "utf-8"

# The bot identity this verb commits under
SCAFFOLD_NAME = "lazy-spec.release-scaffold"
_GROUP_NOTE = "group_note"
_MD_SUFFIX = ".md"
_SPEC_PATH_KEY = "spec_path"

# Refusal and usage messages
_MSG_EMPTY_DELTA = "the delta is empty: no approved, unreleased asset to carry"
_MSG_PUBLISHED = "release is published; its members are frozen"
_MSG_SLOT_TAKEN = "an archive slot is already taken, or two releases would move into the same one"
_MSG_USAGE = "usage: release-scaffold <product-key> --bump <part> | --refresh <release-note> [--no-architecture]\n"

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
_BEHIND = "behind"


def read_next_slug(releases_dir: Path) -> str:
  """
  Number the next release folder.

  Args:
    releases_dir: The product's `releases/` folder, which may not exist yet.

  Returns:
    The highest existing number plus one, zero-padded to the five-digit release slug width; `00001` when there
    is none. The count spans the releases folder and its archive, whatever the width of the existing numbers.
  """

  # Domain(spec.lifecycle):
  # # How a release is numbered
  # A release is named by its place in the product's sequence, written with leading zeros to five digits. The next
  # number continues from the highest one already taken, among the numbered folders of the releases folder and
  # of its archive alike, whatever width an older number was written with: a shorter number counts by its value,
  # not by its spelling. A numbered folder with no note of its own is no release and is left in place, yet it
  # still holds its number, so a new release never takes a number a folder already holds and never collides with
  # a stray one. Counting from the highest rather than from how many exist keeps a number from ever being
  # reused, even when releases have gone missing from the sequence.

  # the numbers already taken, in the releases folder and in its archive, whatever their width
  numbers = [ *_read_release_numbers(releases_dir), *_read_release_numbers(releases_dir / ReleaseKey.ARCHIVE) ]
  return str(max(numbers, default = 0) + 1).zfill(ReleaseKey.SLUG_WIDTH)


def _read_release_numbers(folder: Path) -> list[int]:
  """
  List the sequence numbers of the release folders directly in a folder.

  Args:
    folder: A releases folder or its archive, which may not exist.

  Returns:
    The number of every numbered subfolder; empty when the folder does not exist.
  """
  # guard: no folder, no releases in it
  if not folder.is_dir():
    return []

  # every numbered subfolder counts, whether or not it carries a note
  return [ int(name) for name in os.listdir(folder)
           if name.isascii() and name.isdigit() and (folder / name).is_dir() ]


def _read_archive_moves(releases_dir: Path) -> list[tuple[Path, Path]]:
  """
  Read where every release folder in the releases folder would move in the archive, re-padded to the slug width.

  A numbered folder without its own note is no release: it is left where it is.

  Args:
    releases_dir: The product's `releases/` folder, which may not exist yet.

  Returns:
    One `(folder, target)` pair per numbered folder carrying its own note, in folder-name order; nothing is moved.
    Empty when the releases folder does not exist.
  """
  # guard: no releases folder yet, nothing to move
  if not releases_dir.is_dir():
    return []

  # the pairs, one per numbered release folder
  moves: list[tuple[Path, Path]] = []
  for name in sorted(os.listdir(releases_dir)):
    folder = releases_dir / name

    # guard: only a numbered folder carrying its own note is a release that moves
    if not (name.isascii() and name.isdigit()) or not (folder / f"{name}{_MD_SUFFIX}").is_file():
      continue

    # the release's slot in the archive, its number re-padded to the slug width
    moves.append(( folder, releases_dir / ReleaseKey.ARCHIVE / str(int(name)).zfill(ReleaseKey.SLUG_WIDTH) ))
  return moves


def _apply_archive_moves(moves: list[tuple[Path, Path]]) -> list[Path]:
  """
  Carry out the given release-folder moves into the archive, each release's own note renamed with its folder.

  Notes:
    - Every target must be free, and no two moves may share a target; the caller checks this before the call.

  Args:
    moves: The `(folder, target)` pairs to carry out.

  Returns:
    Every file path the move touched: each file's old path, now gone, and its new path.

  Raises:
    OSError: If the filesystem fails while a folder is moved, the archive folder is created, or a release note is
      renamed.
  """

  # Domain(spec.lifecycle):
  # # Closed releases move to the archive only when the next release is created
  # Publishing or cancelling a release does not move it: it stays in the releases folder. A closed release goes
  # into the archive only when the next release is created, and that creation moves every other release still
  # beside the new one into the archive at once. All of them are closed, since no release can be created while
  # one is open. An old release written with a shorter number is renumbered to five digits as it moves,
  # and its own note is renamed to match; everything else in the folder moves unchanged. So the releases folder
  # holds the open release and, between creations, the last closed one: the current work stays in view and the
  # history stays out of the way. The archive is only a shelf of history, never a release itself.

  # the paths the move touched, collected so the caller can commit them
  touched: list[Path] = []
  for folder, target in moves:
    # the files are listed before the move: their old paths vanish with it, and the commit needs them as deletions
    old_files = [ Path(root) / filename for root, _dirs, filenames in os.walk(folder) for filename in filenames ]

    # the folder moves under the archive with its number re-padded to the slug width
    target.parent.mkdir(parents = True, exist_ok = True)
    os.rename(folder, target)

    # a re-padded number renames the release's own note with it
    if target.name != folder.name:
      os.rename(target / f"{folder.name}{_MD_SUFFIX}", target / f"{target.name}{_MD_SUFFIX}")

    # the old paths carry the deletions, the new ones the files as they now stand
    new_files = [ Path(root) / filename for root, _dirs, filenames in os.walk(target) for filename in filenames ]
    touched.extend([ *old_files, *new_files ])
  return touched


def _render_include_link(repo: Path, note: Path) -> str:
  """
  Render the wikilink a release's `spec_includes` carries for one asset note.

  Args:
    repo: Repository root.
    note: The asset's status note.

  Returns:
    The content-root-relative link without its `.md` suffix, in wikilink brackets.
  """
  rel = note.resolve().relative_to(spec_paths.spec_content_root(repo).resolve()).as_posix()
  return f"{release_delta.WIKILINK_OPEN}{rel[: -len(_MD_SUFFIX)]}{release_delta.WIKILINK_CLOSE}"


def _update_in_release_state(notes: list[Path],
                             *,
                             products: dict | None = None,
                             catalog_guidelines: dict[str, list[str]] | None = None) -> list[Path]:
  """
  Paint each included asset's note `in-release`, so the folder colour changes before the asset's own next wake, and
  recount every container above a repainted asset.

  Args:
    notes: The included assets' status notes.
    products: An already-loaded products registry the container notes' language is resolved in; None reads it from
      the settings file.
    catalog_guidelines: The catalog-wide `spec.guidelines` already read; None reads them from the settings file.

  Returns:
    The container notes whose stats region changed, each once, in the order first met.

  Raises:
    ValueError: If a container note carries the stats markers and the settings file is read for the products
      registry or the catalog-wide guidelines and cannot be read, is not valid JSON, not UTF-8 text or not a JSON
      object.
    RuntimeError: If a container note carries the stats markers, its own language and its product's yield nothing,
      and the core plugin's CLI cannot be resolved, its language verb exits non-zero, or the verb exits zero but
      answers nothing.
  """

  # Domain(spec.lifecycle):
  # # A release taking assets in refreshes every summary that counted them
  # When a release takes assets in, each of them moves into the in-release state, and every summary that counted
  # such an asset is recounted in the same change. These are the same places that read an asset's move along its
  # ladder, up to the one that answers for its own contents, so no total above the asset keeps stating a
  # distribution in which the asset still waits outside the release.

  # each included asset reads in-release from now on
  for note in notes:
    text = note.read_text(encoding = _ENCODING)
    spec_paths.write_text_atomic(note, spec_frontmatter.set_scalar(text, SpecStateKey.STATE, AssetState.IN_RELEASE))

  # every container counting a repainted asset reads its new state in the same commit
  changed: list[Path] = []
  above = ( container for note in notes for container in flip_gate.containers_above(note.parent) )
  for container in dict.fromkeys(above):
    if summary_render.apply_container_stats(container, products = products, catalog_guidelines = catalog_guidelines):
      changed.append(container)
  return changed


def _wake_members(repo: Path, notes: list[Path]) -> None:
  """
  Wake the coordinator of each release member once, after the commit that repainted it has landed.

  Args:
    repo: Repository root.
    notes: The members' status notes.
  """
  # best-effort: the release is already committed, so a failed wake only reaches stderr
  try:
    coordinator_dispatch.wake_release_members(repo, notes, today = None)
  # waiver: the scaffold is already committed — no failure waking a member may change its outcome
  except Exception as error:
    sys.stderr.write(f"release-scaffold: member wake failed after the commit: {error}\n")


def _create_refusal(reason: str) -> dict:
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

  Scaffolding the next release also archives the closed ones: every other release folder directly in `releases/`
  moves into `releases/archive/`, renumbered to five digits with its note renamed to match.

  Guarantees:
    - Every file the verb writes lands in its single commit: the new release note, the members repainted as
      in-release, every container note above a repainted member whose stats region changed, every closed release
      moved into the archive (its old paths as deletions), the archive's group note when the verb wrote it or its
      stats region changed, and the `releases` group note when the scaffold created it or its stats region changed.
    - A successful run leaves none of the verb's own writes uncommitted.
    - Refuses with nothing written when the previous version cannot be read or bumped (an unreadable or missing
      manifest, a version that is not bare SemVer, an unknown bump part), when an archive slot a closed release
      would move into is already taken, when two closed releases would claim the same slot, or when the archive's
      group note has to be written and no group-note template resolves: no release folder is created, no member
      is repainted, no closed release is moved and nothing is committed. The refusal is returned, never raised.

  Notes:
    - The archive's group note, `releases/archive/archive.md`, an operator-zone group note, is written whenever
      `releases/archive/` exists without it: by the first move, or by a run in which nothing moves.
    - The stats region of the `releases` group note is refreshed to count the new release.

  Args:
    repo: The settings root whose settings configure the product; the root of its checkout carries the commit and
      the wake reports.
    key: A product key; the release owner is resolved from it.
    bump: The version part to raise over the previous version: `major`, `minor` or `patch`.

  Returns:
    `{"status": "set", "folder", "folder_note", "version", "included"}` with repo-relative paths and the included
    tokens, or `{"status": "refused", "reason"}` when a release is already open, the delta is empty, no product in
    the chain owns releases, the previous version cannot be read or bumped, an archive slot is already taken on
    disk or would be claimed by two closed releases at once (the reason names the slots and nothing has been
    written), no group-note template resolves for the archive's note, or the scaffold of the release folder is
    refused.

  Raises:
    ValueError: If the merged settings cannot be read; a `spec_paths.SettingsError` naming the settings file, also
      when no core CLI resolves.
    RuntimeError: If a note's own language and its product's yield nothing and the core plugin's CLI cannot be
      resolved, its language verb exits non-zero, or the verb exits zero but answers nothing.
    subprocess.CalledProcessError: If staging or committing the release fails.
    OSError: If a note cannot be read or written, or a closed release folder cannot be moved into the archive for a
      filesystem reason other than a taken or doubly claimed slot.
  """

  # Contract:
  # Every file the verb writes MUST land in its single commit: the new release note, the members repainted
  # as in-release, every container note above a repainted member whose stats region changed, every closed
  # release moved into the archive (its old paths as deletions), the archive's group note when the verb wrote
  # it or its stats region changed, and the `releases` group note when the scaffold created it or its stats
  # region changed. A successful run therefore leaves none of the verb's own writes uncommitted.

  # Contract:
  # When the previous version cannot be read or bumped, when an archive slot a closed release would move into is
  # already taken, or two closed releases would claim the same slot, or the archive's group note has to be
  # written and no group-note template resolves, the verb MUST refuse before it writes anything: no release
  # folder is created, no member is repainted, no closed release is moved and nothing is committed. The refusal
  # is returned as a result, never raised, so callers MUST handle it.

  # resolve who owns the product's releases, in the registry and catalog-wide guidelines the runtime dispatches from,
  # read once for the release
  registry, catalog = resolve_product.read_runtime_catalog(repo)
  owner = resolve_product.find_release_owner_key(repo, key, products = registry)

  # guard: an umbrella without code owns no releases
  if owner is None:
    return _create_refusal(f"no release owner above product {key!r}")

  # guard: one open release at a time
  if (open_note := release_delta.find_open_release(repo, owner, products = registry)) is not None:
    return _create_refusal(f"a release is already open: {open_note.relative_to(repo).as_posix()}")

  # the delta: the approved assets the new release would carry
  included, _excluded = release_delta.find_all_delta_entries(repo, owner, products = registry)

  # guard: nothing to ship, nothing to create
  if not included:
    return _create_refusal(_MSG_EMPTY_DELTA)

  # the owner's record names where its releases live and the number the new one takes
  record = registry[owner]
  releases_dir = spec_paths.spec_content_root(repo) / record[_SPEC_PATH_KEY] / ReleaseKey.FOLDER
  slug = read_next_slug(releases_dir)

  # the version the release carries, raised over the previous published one; read before anything is written, so a
  # manifest that cannot be read or carries no bare version refuses without leaving a half-created release behind
  try:
    version = release_version.bump(release_version.read_previous_version(repo, record, releases_dir), bump)
  except (ValueError, OSError) as error:
    return _create_refusal(f"the release's version cannot be computed: {error}")

  # the releases already there are the ones the new release sends to the archive
  moves = _read_archive_moves(releases_dir)

  # the archive slots the moves would fill, one per moving release
  targets = [ target for _folder, target in moves ]

  # guard: an archive slot already taken, or claimed by two releases at once, refuses before anything is written
  if (taken := sorted({ target.relative_to(repo).as_posix() for target in targets
                        if target.exists() or targets.count(target) > 1 })):
    return _create_refusal(f"{_MSG_SLOT_TAKEN}: {', '.join(taken)}")

  # the archive's own group note, written below when the archive exists without it
  archive_note = releases_dir / ReleaseKey.ARCHIVE / f"{ReleaseKey.ARCHIVE}{_MD_SUFFIX}"
  try:
    # guard: a group-note template that does not resolve refuses before anything is written, under the same
    # condition the writing step below acts on
    if (moves or archive_note.parent.is_dir()) and not archive_note.exists():
      scaffold_asset.resolve_template(repo, ReleaseKey.ASSET_TYPE, owner, scaffold_asset.Keys.GROUP_NOTE_TMPL,
                                      products = registry)

    # the new release's folder and note, from the release type's own template chain
    created = scaffold_asset.scaffold(repo, owner, ReleaseKey.ASSET_TYPE, slug, products = registry,
                                      catalog_guidelines = catalog)
  except scaffold_asset.ScaffoldRefusal as refusal:
    return _create_refusal(refusal.message)

  # the new release's own status note
  note = repo / created[_FOLDER_NOTE]

  # the delta's members are listed on the release note
  text = note.read_text(encoding = _ENCODING)
  links = [ _render_include_link(repo, entry.note) for entry in included ]
  spec_paths.write_text_atomic(note, spec_frontmatter.write_list(text, ReleaseKey.INCLUDES, links))

  # the release is versioned from the moment it exists, so its version tag already names it in the vault
  release_version.set_release_version(note, version)

  # the members read in-release from now on, and the containers above them count them so
  recounted = _update_in_release_state([ entry.note for entry in included ], products = registry,
                                       catalog_guidelines = catalog)

  # the closed releases beside the new one move into the archive here; the paths written so far are the release
  # note, the repainted members, the containers recounted above them and every path the move touched
  written = [ note, *( entry.note for entry in included ), *recounted, *_apply_archive_moves(moves) ]

  # Domain(spec.notes):
  # # The archive counts its releases and the releases folder counts them all
  # The archive has a group note of its own, which counts the archived releases and is recounted whenever more
  # arrive. The releases folder's note counts every release of the product, the archived ones included.
  # Archiving therefore never lowers the count the releases folder shows.

  # an archive without its group note gets one written; an existing note has its count refreshed
  if archive_note.parent.is_dir():
    seeded = not archive_note.exists()
    owner_record = resolve_product.effective_record(repo, owner, products = registry, catalog_guidelines = catalog)
    scaffold_asset.ensure_group_note(repo, archive_note.parent, asset_type = ReleaseKey.ASSET_TYPE,
                                     owner_key = owner, owner_record = owner_record, products = registry,
                                     catalog_guidelines = catalog)
    if summary_render.apply_container_stats(archive_note, products = registry,
                                            catalog_guidelines = catalog) or seeded:
      written.append(archive_note)

  # the releases group note counts the release just created; it joins the written paths when the
  # scaffold created it or when its stats region moved
  group_note = releases_dir / f"{ReleaseKey.FOLDER}{_MD_SUFFIX}"
  if group_note.is_file():
    stats_moved = summary_render.apply_container_stats(group_note, products = registry, catalog_guidelines = catalog)
    if (stats_moved or created.get(_GROUP_NOTE)) and group_note not in written:
      written.append(group_note)

  # one commit under this verb's identity, in the checkout the settings root sits in, carries every written path
  release_version.commit_paths(spec_locator.query_repo_root(repo), written, author = SCAFFOLD_NAME,
                               subject = f"{SCAFFOLD_NAME}: {slug} ({version}) under {owner}")

  # every member painted in-release is told once the release has landed, so its brief follows its new state
  _wake_members(spec_locator.query_repo_root(repo), [ entry.note for entry in included ])
  return {
      _STATUS: _STATUS_SET, _FOLDER: created[_FOLDER], _FOLDER_NOTE: created[_FOLDER_NOTE], _VERSION: version,
      _INCLUDED: [ entry.token for entry in included ],
  }


def refresh_includes(repo: Path, release_note: Path, *, waived: bool = False) -> dict:
  """
  Pull the delta's new members into an open release's `spec_includes`.

  A new delta asset the owner's architecture does not cover yet stays out. Each newly listed member is woken once
  the commit that lists it has landed.

  Guarantees:
    - Every file the verb writes lands in its single commit: the release note, the members repainted as in-release
      and every container note above a repainted member whose stats region changed. A run that adds no member
      writes and commits nothing.
    - A new delta asset the architecture holds behind is named in `behind` and never listed; a product with no
      architecture document, or a call that waives the architecture, holds none behind.

  Args:
    repo: The settings root whose settings configure the release's product; the root of its checkout carries the
      commit and the wake reports.
    release_note: The release's status note.
    waived: When True, the architecture holds no new asset out of the release.

  Returns:
    `{"added": [tokens], "kept": [tokens], "behind": [tokens]}` — the members newly listed, the delta members
    already listed, and the new delta assets held out while the owner's architecture document exists, is not waived
    and is not approved after them; a member listed earlier and no longer in the delta stays listed.
    `{"status": "refused", "reason"}` when the release is published or no product in the note's chain owns releases.

  Raises:
    OSError: If the release note or an included asset's note cannot be read or written.
    ValueError: If `release_note` does not lie under `repo`, or if the merged settings cannot be read; the latter is
      a `spec_paths.SettingsError` naming the settings file, also when no core CLI resolves.
    subprocess.CalledProcessError: If the commit of the new members fails.
  """

  # Contract:
  # Every file the verb writes MUST land in its single commit: the release note, the members repainted as
  # in-release and every container note above a repainted member whose stats region changed. A run that adds no
  # member writes nothing and commits nothing.

  # Contract:
  # A new delta asset is listed in the release only while the owner's architecture holds it behind no longer;
  # an asset the architecture holds behind is named in `behind` and never listed. A product with no architecture
  # document, or a call that waives the architecture, holds no asset behind.

  # Domain(spec.lifecycle):
  # # A release takes in only what its architecture covers
  # A release open for new members takes in an approved design only once the product's architecture covers it, as
  # a release starts only from an architecture behind none of its designs. A design the architecture is behind waits
  # outside the release until the architecture is approved after it; it is named as waiting, never added.
  # A product with no architecture document, or whose rules waive the document, holds no design back: a new
  # approved design joins the open release at once.

  text = release_note.read_text(encoding = _ENCODING)
  fm_values, _end = spec_frontmatter.parse(text)

  # guard: a published release's members are frozen
  if flip_gate.is_true(fm_values, Gate.RELEASED):
    return _create_refusal(_MSG_PUBLISHED)

  # the product the release note sits under, in the registry and catalog-wide guidelines the runtime dispatches
  # from, read once for the release
  registry, catalog = resolve_product.read_runtime_catalog(repo)
  key, _record = resolve_product.effective_record_by_path(repo, release_note.relative_to(repo).as_posix(),
                                                          products = registry, catalog_guidelines = catalog)

  # guard: a release note under a product that owns no releases has no delta to refresh from
  if key is None or (owner := resolve_product.find_release_owner_key(repo, key, products = registry)) is None:
    return _create_refusal(f"no release owner above the release note {release_note.name!r}")

  # the delta as it stands now, against the members already listed; a new asset the owner's architecture does not
  # cover yet is held out
  included, _excluded = release_delta.find_all_delta_entries(repo, key, products = registry)
  existing = spec_frontmatter.read_list(text, ReleaseKey.INCLUDES)
  fresh = [ entry for entry in included if _render_include_link(repo, entry.note) not in existing ]
  _doc, _approved_at, behind = release_delta.find_architecture_lag(repo, owner, fresh, waived = waived,
                                                                   products = registry)
  added = [ entry for entry in fresh if entry.token not in behind ]
  kept = [ entry.token for entry in included if _render_include_link(repo, entry.note) in existing ]

  # the new members join the list and are repainted in-release, all in one commit
  if added:
    links = existing + [ _render_include_link(repo, entry.note) for entry in added ]
    spec_paths.write_text_atomic(release_note, spec_frontmatter.write_list(text, ReleaseKey.INCLUDES, links))
    recounted = _update_in_release_state([ entry.note for entry in added ], products = registry,
                                         catalog_guidelines = catalog)
    release_version.commit_paths(
        spec_locator.query_repo_root(repo), [ release_note, *( entry.note for entry in added ), *recounted ],
        author = SCAFFOLD_NAME,
        subject = f"{SCAFFOLD_NAME}: {len(added)} new member(s) in {release_note.parent.name}")

    # only the newly listed members changed state, so only they are told
    _wake_members(spec_locator.query_repo_root(repo), [ entry.note for entry in added ])

  # the members newly listed and the delta members already there
  return { _ADDED: [ entry.token for entry in added ], _KEPT: kept, _BEHIND: behind }


def main(argv: list[str]) -> int:
  """
  Create a product's next release, or refresh an open release's members.

  The product's settings come from the nearest `.claude/lazy.settings.json` above the directory named by the
  `LAZY_REPO_ROOT` environment variable, falling back to the process working directory, within the checkout that
  directory sits in; without one, from the checkout's root. A `--refresh` note is relative to that settings root,
  and the commit lands in the checkout.

  Notes:
    - Prints the JSON result of `scaffold_release` or `refresh_includes` on stdout.
    - A failed commit or file-system step is reported as one line on stderr, `release-scaffold: <ErrorType>:
      <message>`; whatever the verb already wrote stays in place.

  Args:
    argv: Command-line arguments, excluding the program name; `--no-architecture` is meaningful with `--refresh`
      and holds no new asset out of the release.

  Returns:
    Exit code: 0 on success, 1 on a refusal or on a commit or file-system failure, 2 when the arguments name no
    product or no existing note.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs release-scaffold")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("product", nargs = "?", default = "")
  # waiver: argparse CLI signature -- option name
  parser.add_argument("--bump", choices = release_version.PARTS, default = "")
  # waiver: argparse CLI signature -- option name
  parser.add_argument("--refresh", default = "")
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--no-architecture", action = "store_true")
  args = parser.parse_args(argv)
  settings_root = spec_locator.query_settings_root()

  # a commit that does not land is the verb's failure, named on stderr; what the verb wrote stays as it is, and
  # the dirty tree it leaves is the alarm
  try:
    # the refresh form names a note; the create form names a product and a bump
    if args.refresh:
      note = (settings_root / args.refresh).resolve()

      # guard: the refresh form names a note that must exist
      if not note.is_file():
        sys.stderr.write(f"no such note: {note}\n")
        return 2

      # the refresh pulls the delta's new members into the open release
      result = refresh_includes(settings_root, note, waived = args.no_architecture)
    elif args.product and args.bump:
      result = scaffold_release(settings_root, args.product, bump = args.bump)
    else:
      sys.stderr.write(_MSG_USAGE)
      return 2
  except (subprocess.CalledProcessError, OSError) as error:
    sys.stderr.write(f"release-scaffold: {type(error).__name__}: {error}\n")
    return 1

  # the result goes out as one JSON line; a refusal exits 1
  print(json.dumps(result))
  return 1 if result.get(_STATUS) == _STATUS_REFUSED else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
