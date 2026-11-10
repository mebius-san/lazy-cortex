"""
Logic behind the `lazycortex-specs migrate-readiness` verb — moves status notes off the retired `spec_draft` key.

Readiness for a downstream consumer used to live in a negative `spec_draft` flag beside `spec_released`. It now lives
in `spec_released` alone, and a release note's old `spec_released` meaning — built and tested, not yet published —
moved to `spec_built`. This verb rewrites every status note of the spec catalog still carrying `spec_draft` to that
format, reports what it rewrote, and lists every note it could not classify, leaving those untouched. It never
commits.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    BOOL_FALSE, BOOL_TRUE, AssetTypeKey, Gate, ReleaseKey, SpecKey, SpecMomentKey, SpecValue,
)


# The retired readiness key this verb migrates away from; nothing else in the plugin names it any more.
_DRAFT_KEY = "spec_draft"

# The moment keys beside the released and built gates.
_RELEASED_AT = f"{Gate.RELEASED}{SpecMomentKey.AT_SUFFIX}"
_BUILT_AT = f"{Gate.BUILT}{SpecMomentKey.AT_SUFFIX}"

_MD_SUFFIX = ".md"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# waiver: the result's own wire-shape keys, read by the install skill and the tests
_DRY_RUN_KEY = "dry_run"
_ASSETS_KEY = "assets"
_RELEASES_KEY = "releases"
_UNCHANGED_KEY = "unchanged"
_UNCLASSIFIED_KEY = "unclassified"
_NOTE_KEY = "note"
_REASON_KEY = "reason"

# The two boolean literals a migrated flag may hold.
_BOOLS = frozenset({ BOOL_TRUE, BOOL_FALSE })


class _UnclassifiedError(Exception):
  """
  Failure signal for a status note that cannot be migrated without guessing.
  """


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Rewrite every status note still carrying `spec_draft` to the `spec_released` / `spec_built` format.

  Guarantees:
    - A note the verb cannot classify is left byte-identical and listed with its reason.
    - A dry run writes nothing.
    - A second run over the result rewrites nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would be rewritten and write nothing.

  Returns:
    `{"dry_run", "assets", "releases", "unchanged", "unclassified"}` — the counts of asset and release notes
    rewritten, of status notes already free of `spec_draft`, and one `{"note", "reason"}` entry per note left
    untouched because it could not be classified, its path relative to the settings root.
  """

  # Contract:
  # A note this verb cannot classify MUST keep its bytes, and a dry run MUST write no file. Running the verb again
  # over its own output MUST rewrite nothing.

  settings_root = spec_paths.find_settings_root(repo)
  result: dict = {
      _DRY_RUN_KEY: dry_run, _ASSETS_KEY: 0, _RELEASES_KEY: 0, _UNCHANGED_KEY: 0, _UNCLASSIFIED_KEY: [],
  }

  # every markdown file under the content root, in a stable order
  for dirpath, dirnames, filenames in os.walk(spec_paths.spec_content_root(settings_root)):
    dirnames.sort()
    for name in sorted(filenames):

      # guard: only markdown files carry frontmatter
      if not name.endswith(_MD_SUFFIX):
        continue
      note = Path(dirpath) / name
      text = spec_paths.read_text(note)
      fm_values, _end = spec_frontmatter.parse(text)

      # guard: only an asset status note carries readiness
      if fm_values.get(SpecKey.ROLE, "").strip() != SpecValue.ROLE_STATUS:
        continue

      # guard: a note without the retired key is already in the new format
      if _DRAFT_KEY not in fm_values:
        result[_UNCHANGED_KEY] += 1
        continue

      # the note is rewritten by its type; one that cannot be classified is reported and left alone
      is_release = fm_values.get(AssetTypeKey.TYPE, "").strip() == ReleaseKey.ASSET_TYPE
      try:
        new_text = _migrate_release(text, fm_values) if is_release else _migrate_asset(text, fm_values)
      except _UnclassifiedError as error:
        result[_UNCLASSIFIED_KEY].append(
            { _NOTE_KEY: note.relative_to(settings_root).as_posix(), _REASON_KEY: str(error) })
        continue
      result[_RELEASES_KEY if is_release else _ASSETS_KEY] += 1
      if not dry_run:
        spec_paths.write_text_atomic(note, new_text)
  return result


def _read_bool(fm_values: dict, key: str) -> bool | None:
  """
  Read one boolean frontmatter value strictly.

  Args:
    fm_values: The note's parsed frontmatter values.
    key: The key to read.

  Returns:
    True or False for the literals `true` / `false`, None when the key is absent.

  Raises:
    _UnclassifiedError: The key holds anything but a boolean literal.
  """
  # guard: an absent key reads as None, distinct from an explicit false
  if key not in fm_values:
    return None

  # only the two literals are trusted; anything else is not guessed at
  raw = fm_values[key].strip().lower()
  if raw not in _BOOLS:
    raise _UnclassifiedError(f"{key} is not a boolean: {fm_values[key]!r}")
  return raw == BOOL_TRUE


def _drop_key(text: str, key: str) -> str:
  """
  Remove one scalar key's line from a note's frontmatter.

  Args:
    text: The full note text.
    key: The key to remove.

  Returns:
    The note text without that key's line; unchanged when the frontmatter does not carry it.
  """
  # the line is removed inside the frontmatter only, never from the body
  fm_text, end = spec_frontmatter.block(text)
  head = text[:end]
  start = head.find(fm_text)
  dropped = re.sub(rf"(?m)^{re.escape(key)}[ \t]*:.*\n?", "", fm_text, count = 1)
  return head[:start] + dropped + head[start + len(fm_text):] + text[end:]


def _migrate_asset(text: str, fm_values: dict) -> str:
  """
  Migrate the status note of an asset of any type but `release`, untyped included.

  Args:
    text: The full note text.
    fm_values: The note's parsed frontmatter values.

  Returns:
    The rewritten note text: `spec_draft` dropped and every other line, `spec_released` included, unchanged.

  Raises:
    _UnclassifiedError: `spec_draft` is not a boolean.
  """

  # Decision: an asset keeps its `spec_released` as is, never derived from the old draft flag — out of draft and
  # unreleased is the re-approved-after-release state, which must stay not ready; every path that cleared the draft
  # flag without a release already closed `spec_released` with it.

  # a draft flag that is not a boolean cannot be trusted; reading it refuses the note
  _read_bool(fm_values, _DRAFT_KEY)

  # only the retired key leaves the note
  return _drop_key(text, _DRAFT_KEY)


def _migrate_release(text: str, fm_values: dict) -> str:
  """
  Migrate a release's status note.

  Args:
    text: The full note text.
    fm_values: The note's parsed frontmatter values.

  Returns:
    The rewritten note text: `spec_built` holds the old `spec_released` (its moment moved beside it),
    `spec_released` says whether the release was published, and `spec_draft` is dropped.

  Raises:
    _UnclassifiedError: A flag is not a boolean, the note already carries `spec_built`, or it was published without a
      build.
  """
  draft = _read_bool(fm_values, _DRAFT_KEY)
  built = bool(_read_bool(fm_values, Gate.RELEASED))

  # guard: a note carrying both keys is half migrated by hand; neither value can be trusted
  if Gate.BUILT in fm_values:
    raise _UnclassifiedError(f"carries both {Gate.BUILT} and {_DRAFT_KEY}")

  # guard: a published release that was never built contradicts the ladder
  if draft is False and not built:
    raise _UnclassifiedError(f"published ({_DRAFT_KEY}: false) while {Gate.RELEASED} is not true")

  # the old released gate and its moment become the built gate; released now means published
  moment = fm_values.get(_RELEASED_AT, "")
  if built and moment:
    text = _drop_key(text, _RELEASED_AT)
    text = spec_frontmatter.set_scalar(text, _BUILT_AT, moment)
  text = _set_before(text, Gate.BUILT, BOOL_TRUE if built else BOOL_FALSE, Gate.RELEASED)
  text = spec_frontmatter.set_scalar(text, Gate.RELEASED, BOOL_FALSE if draft else BOOL_TRUE)
  return _drop_key(text, _DRAFT_KEY)


def _set_before(text: str, key: str, value: str, anchor: str) -> str:
  """
  Insert a scalar key on the line just above another key, so the ladder keeps its order.

  Args:
    text: The full note text.
    key: The key to insert.
    value: Its literal value.
    anchor: The key the new line goes above.

  Returns:
    The note text with the new line above the anchor's, or appended to the frontmatter when the anchor is absent.
  """
  # the new line lands above the anchor when the frontmatter carries one
  pattern = re.compile(rf"(?m)^{re.escape(anchor)}[ \t]*:")
  fm_text, end = spec_frontmatter.block(text)
  match = pattern.search(fm_text)
  if match is None:
    return spec_frontmatter.set_scalar(text, key, value)

  # the frontmatter body is spliced back between the untouched fence and body
  start = text[:end].find(fm_text)
  updated = fm_text[:match.start()] + f"{key}: {value}\n" + fm_text[match.start():]
  return text[:start] + updated + text[start + len(fm_text):]


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--cwd` names
      the repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: 1 when a note could not be classified, 0 otherwise.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-readiness")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the result goes to stdout whole; an unclassified note turns the exit code red
  repo_raw = args.cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()
  result = migrate(Path(repo_raw).resolve(), dry_run = args.dry_run)
  print(json.dumps(result))
  return 1 if result[_UNCLASSIFIED_KEY] else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
