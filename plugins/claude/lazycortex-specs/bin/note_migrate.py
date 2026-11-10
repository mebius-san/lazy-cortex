"""
Logic behind the `lazycortex-specs migrate-notes` verb — brings the spec catalog's status and level notes onto the
current frontmatter shape.

Several keys and rows a note may still carry were retired: the middle rungs of the asset ladder on every asset type
but a release and a research asset, the asset dependency list and its `blocked` state, the child-wake bookkeeping of
a level note, and the `Revise design` launch row. This verb removes or rewrites exactly those, leaving every other
line of the note as it was, and reports which notes it changed. It never commits.
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
    LEVEL_ROLES, RESEARCH_ASSET_TYPE, AssetState, AssetTypeKey, Gate, GateCheckbox, ReleaseKey, Section, SpecKey,
    SpecMomentKey, SpecStateKey, SpecValue,
)


# The middle rungs of the asset ladder and their moment keys, which only a release and a research asset still carry.
_MIDDLE_KEYS = tuple(
    key for gate in ( Gate.PLAN_DONE, Gate.DEVELOP_DONE, Gate.TESTS_PASSING )
    for key in ( gate, f"{gate}{SpecMomentKey.AT_SUFFIX}" )
)

# The asset types whose notes keep the middle rungs.
_MIDDLE_GATE_TYPES = frozenset({ ReleaseKey.ASSET_TYPE, RESEARCH_ASSET_TYPE })

# The retired keys this verb removes from every note; nothing else in the plugin names them any more.
_RETIRED_KEYS = ( "spec_depends_on", "spec_coordinator_child_wake_state" )

# A `spec_state` line holding the retired `blocked` value of an asset waiting on a dependency: the key and its
# spacing, the optional quote, then the value, followed only by blanks, an optional comment and a CRLF's carriage
# return.
_BLOCKED_STATE_RE = re.compile(
    rf"(?m)^({SpecStateKey.STATE}[ \t]*:[ \t]*)([\"']?)blocked\2(?=(?:[ \t]+#[^\r\n]*)?[ \t]*\r?$)")

# The replacement for that line: the key, its spacing and its quotes kept, the value turned to `draft`.
_DRAFT_STATE = rf"\g<1>\g<2>{AssetState.DRAFT}\g<2>"

# The label of the retired launch row.
_REVISE_DESIGN = "Revise design"

# The note roles this verb migrates: an asset's status note and both level notes.
_MIGRATED_ROLES = LEVEL_ROLES | { SpecValue.ROLE_STATUS }

# The body markup a gate row is read from: its callout opener, the quote every row line starts with, the opener of
# any next callout, and an H1 heading.
_GATE_OPEN = f"> {GateCheckbox.GATE_CALLOUT_MARK} "
_QUOTE = ">"
_CALLOUT_OPEN = "> [!"
_H1_PREFIX = "# "

_LF = "\n"
_MD_SUFFIX = ".md"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The exit code of a run that failed, never an answer `--check` gives.
_EXIT_FAILED = 2

# The result's own wire-shape keys, read by the migration step and the tests.
_CHANGED_KEY = "changed"
_SKIPPED_KEY = "skipped"


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Bring every status and level note of the spec catalog onto the current frontmatter shape.

  Guarantees:
    - Only the retired keys, the `blocked` state value and the `Revise design` rows of `# Gates` change; every other
      line keeps its bytes and its order, and a note with nothing to change is not written.
    - A dry run writes nothing.
    - A second run over the result changes nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    `{"changed", "skipped"}` — the notes rewritten and the notes already current, each a list of paths relative to
    the settings root, in walk order.
  """

  # Contract:
  # Only the retired keys, the `blocked` state value and the `Revise design` rows change; every other line of a note
  # MUST keep its bytes and order. A dry run MUST write no file, and running the verb again over its own output MUST
  # change nothing.

  settings_root = spec_paths.find_settings_root(repo)
  result: dict = { _CHANGED_KEY: [], _SKIPPED_KEY: [] }

  # every markdown file under the content root, in a stable order
  for dirpath, dirnames, filenames in os.walk(spec_paths.spec_content_root(settings_root)):
    dirnames.sort()
    for name in sorted(filenames):

      # guard: only markdown files carry frontmatter
      if not name.endswith(_MD_SUFFIX):
        continue

      # the note's text and its frontmatter values, read once for every check below
      note = Path(dirpath) / name
      text = spec_paths.read_text(note)
      fm_values, _end = spec_frontmatter.parse(text)

      # guard: only an asset's status note and a level note carry the retired shape
      if fm_values.get(SpecKey.ROLE, "").strip() not in _MIGRATED_ROLES:
        continue

      # a note the migration leaves as it is goes unwritten
      new_text = _migrate_text(text, fm_values)
      rel = note.relative_to(settings_root).as_posix()
      if new_text == text:
        result[_SKIPPED_KEY].append(rel)
        continue
      result[_CHANGED_KEY].append(rel)
      if not dry_run:
        spec_paths.write_text_atomic(note, new_text)

  # both lists in walk order
  return result


def _migrate_text(text: str, fm_values: dict) -> str:
  """
  Rewrite one note's text onto the current shape.

  Args:
    text: The full note text.
    fm_values: The note's parsed frontmatter values.

  Returns:
    The note text without the retired keys and rows and with a `blocked` state turned to `draft`; the text unchanged
    when it carries none of them.
  """
  # the middle rungs leave every note but a release's and a research asset's
  if fm_values.get(AssetTypeKey.TYPE, "").strip() not in _MIDDLE_GATE_TYPES:
    for key in _MIDDLE_KEYS:
      text = spec_frontmatter.drop_key(text, key)

  # the dependency list and the child-wake bookkeeping leave every note
  for key in _RETIRED_KEYS:
    text = spec_frontmatter.drop_key(text, key)

  # a note still blocked on a dependency is a draft again; the retired launch row leaves the gates section
  return _drop_revise_rows(_unblock_state(text))


def _unblock_state(text: str) -> str:
  """
  Turn every `blocked` state value in a note's frontmatter into `draft`.

  Args:
    text: The full note text.

  Returns:
    The note text with only the value token of each blocked state line replaced, its quotes, spacing and trailing
    comment kept; unchanged when no state line holds `blocked`.
  """
  _fm_text, end = spec_frontmatter.block(text)

  # guard: a note without frontmatter carries no state
  if not end:
    return text

  # the substitution runs between the opening fence and the end of the closing one, never in the body
  opening = text.index(_LF) + 1
  return text[:opening] + _BLOCKED_STATE_RE.sub(_DRAFT_STATE, text[opening:end]) + text[end:]


def _drop_revise_rows(text: str) -> str:
  """
  Remove every `Revise design` row from a note's `# Gates` section.

  Args:
    text: The full note text.

  Returns:
    The note text without those rows and without the blank line that separated each one when nothing but a blank
    line or the end of the note follows it; unchanged when the section carries no such row.
  """
  _fm_text, end = spec_frontmatter.block(text)
  lines = text[end:].split(_LF)

  # a line inside a code fence is never structure: it opens no section and hangs no row
  prose = [ not fenced for fenced in spec_frontmatter.fenced_lines(lines) ]

  # guard: a note without the gates section hangs no row
  if (head := next(( idx for idx, line in enumerate(lines) if prose[idx] and line.strip() == Section.GATES ),
                   None)) is None:
    return text

  # the rows open inside the section, which runs to the next H1 or the end of the note
  stop = next(( idx for idx in range(head + 1, len(lines)) if prose[idx] and lines[idx].startswith(_H1_PREFIX) ),
              len(lines))
  rows = [
      idx for idx in range(head + 1, stop)
      if prose[idx] and lines[idx].startswith(_GATE_OPEN) and lines[idx][len(_GATE_OPEN):].strip() == _REVISE_DESIGN
  ]

  # each row runs over its quoted lines up to the next callout; dropped from the back, its separator folded away
  for start in reversed(rows):
    close = start + 1
    while close < len(lines) and lines[close].startswith(_QUOTE) and not lines[close].startswith(_CALLOUT_OPEN):
      close += 1
    del lines[start:close]
    if start > 0 and not lines[start - 1].strip() and (start >= len(lines) or not lines[start].strip()):
      del lines[start - 1]

  # the frontmatter is carried over untouched ahead of the rewritten body
  return text[:end] + _LF.join(lines)


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when at least one note would change, 1 when none would.
    - Any failure of the migration exits 2 under every flag and prints no result, never an answer `--check` gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names the
      repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: with `--check`, 0 when a note would change and 1 when none would; 0 otherwise; 2 when the migration
    failed.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed; also told apart from both `--check` answers.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when at least one note would change, 1 when none would; any
  # failure of the migration MUST exit 2, so a migration step's `applies_when` predicate never reads a failure as an
  # answer.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-notes")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the repo root comes from `--cwd`, else the daemon's env var, else the process cwd
  repo = Path(args.cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()

  # the migration runs, dry under a check; whatever stops it is named on stderr and exits 2
  try:
    result = migrate(repo, dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    # an unreadable catalog, malformed settings, or any other fault is not an answer and must never look like one
    sys.stderr.write(f"migrate-notes: {error!r}\n")
    return _EXIT_FAILED

  # the result is printed only once the migration finished
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 0 if result[_CHANGED_KEY] else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
