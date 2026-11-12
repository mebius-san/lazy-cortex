"""
Logic behind the `lazycortex-specs migrate-upstream-history` verb — moves the `# History` section of upstream unit
notes off the old flat list and onto the shared journal layout.

An earlier release wrote a unit note's history as a flat list, newest line first, each line carrying its own date.
Every note's history is now grouped under one heading per day, oldest day first. This verb regroups the old lines
through the same journal writer every other history line goes through, keeps the explainer under the heading, and
leaves a note it cannot read line by line as it is, reporting why. Every byte outside the section stays. It never
commits.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    SpecKey, UpstreamRole,
)


# The settings-root folder upstream mirrors live under, and the depth of a unit folder below it: a source key, a
# mount, then at least one unit segment.
_UPSTREAM_DIR = "upstream"
_UNIT_MIN_DEPTH = 3

# The section's heading, the prefix of the H1 that ends it, and the placeholder of an empty section.
_HISTORY_H1 = "# History"
_H1_PREFIX = "# "
_NONE_MARKER = "_(none)_"

# An old-format line: the bullet, the date, an em dash, then the bot and the text the line keeps.
_OLD_LINE_RE = re.compile(r"^- (?P<date>\d{4}-\d{2}-\d{2}) — (?P<entry>\S+ · .+)$")
_DATE_GROUP = "date"
_ENTRY_GROUP = "entry"

# A day heading of the journal layout and the bullet of each line under it.
_DAY_RE = re.compile(r"^#### (?P<date>\d{4}-\d{2}-\d{2})$")
_BULLET = "- "

# Why a note was left as it is.
_REASON_CURRENT = "already current"
_REASON_NO_SECTION = "no history section"
_REASON_UNRECOGNIZED = "unrecognized history line"
_REASON_ROLE_UNREADABLE = "spec_role is not a string"

_LF = "\n"
_MD_SUFFIX = ".md"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The result's own wire-shape keys, and the keys of one skipped entry, read by the migration step and the tests.
_CHANGED_KEY = "changed"
_SKIPPED_KEY = "skipped"
_PATH_KEY = "path"
_REASON_KEY = "reason"

# The exit code of a failed run, told apart from both `--check` answers.
_EXIT_FAILED = 2


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Regroup the old flat `# History` list of every upstream unit note under day headings.

  Guarantees:
    - Old lines land under one heading per day, oldest day first and oldest line first within a day, without their
      date; a day group already present is merged in after the same day's old lines.
    - The explainer under the heading stays; an empty section and a note already grouped are left byte-identical.
    - Only the `# History` section changes, line endings included; every other byte keeps its place.
    - A line of neither shape, an old line under a day heading or on a day the calendar lacks, and a role that is
      not a string leave the note byte-identical, reported skipped with a reason, and the run goes on.
    - A dry run writes nothing, and a second run over the result changes nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    `{"changed", "skipped"}` — the unit notes rewritten, as paths relative to the settings root, and the unit notes
    left as they are, each a `{"path", "reason"}` record; both in walk order.

  Raises:
    OSError: When a note cannot be read or written, or no settings file lies at or above `repo`.
    RuntimeError: When the journal writer refuses a line or cannot be resolved.
  """

  # Contract:
  # Old lines MUST land under one `#### <date>` heading per day, oldest day first and oldest line first within a day,
  # without their date, and a day group already present MUST be merged in after the same day's old lines. The
  # explainer under the heading MUST stay, and an empty section or a note already grouped MUST be left byte-identical.

  # Contract:
  # Only the `# History` section of an upstream unit note changes; every other byte MUST keep its place. A line of
  # neither shape, an old line under a day heading or on a day the calendar lacks, and a role that is not a string
  # are never guessed at: the note MUST be left as it is and reported skipped with a reason, and the run MUST go on.
  # A dry run MUST write no file, and running the verb again over its own output MUST change nothing.

  settings_root = spec_paths.require_settings_root(repo)
  upstream_root = settings_root / _UPSTREAM_DIR
  result: dict = { _CHANGED_KEY: [], _SKIPPED_KEY: [] }

  # every folder deep enough to be a unit, in a stable order
  for dirpath, dirnames, filenames in os.walk(upstream_root):
    dirnames.sort()
    unit_dir = Path(dirpath)
    name = f"{unit_dir.name}{_MD_SUFFIX}"

    # guard: only a folder note at a unit's depth can be a unit note
    if len(unit_dir.relative_to(upstream_root).parts) < _UNIT_MIN_DEPTH or name not in filenames:
      continue

    # the candidate note's text, read once for the role check and the rewrite
    note = unit_dir / name
    text = spec_paths.read_text(note)

    # the note's role, and its path as the result names it
    role = spec_frontmatter.parse(text)[0].get(SpecKey.ROLE, "")
    rel = note.relative_to(settings_root).as_posix()

    # guard: a role that is not a string cannot be read, so the note is skipped and the run goes on
    if not isinstance(role, str):
      result[_SKIPPED_KEY].append({ _PATH_KEY: rel, _REASON_KEY: _REASON_ROLE_UNREADABLE })
      continue

    # guard: only a note carrying the unit role is one
    if role.strip() != UpstreamRole.UNIT:
      continue

    # the regrouped text, and the reason when the note is left as it is
    new_text, reason = _migrate_text(text, repo = settings_root)

    # a note the migration leaves as it is goes unwritten, reported with the reason
    if new_text == text:
      result[_SKIPPED_KEY].append({ _PATH_KEY: rel, _REASON_KEY: reason })
      continue

    # a changed note is reported, and written unless the run is dry
    result[_CHANGED_KEY].append(rel)
    if not dry_run:
      spec_paths.write_text_atomic(note, new_text)

  # both lists in walk order
  return result


def _migrate_text(text: str, *, repo: Path) -> tuple[str, str]:
  """
  Regroup one unit note's `# History` section.

  Args:
    text: The full note text, with LF line endings.
    repo: The settings root, for the journal writer's resolver.

  Returns:
    The note text with the section regrouped, and the reason the note is left as it is; the text unchanged when it
    has no section, the section holds no old line, or it holds a line of neither shape.

  Raises:
    RuntimeError: When the journal writer refuses a line or cannot be resolved.
  """
  # the body's lines, each marked when it sits inside a code fence
  _fm_text, end = spec_frontmatter.block(text)
  lines = text[end:].split(_LF)
  fenced = spec_frontmatter.fenced_lines(lines)

  # guard: a note without the section has nothing to regroup
  if (head := next(( idx for idx, line in enumerate(lines) if not fenced[idx] and line.rstrip() == _HISTORY_H1 ),
                   None)) is None:
    return text, _REASON_NO_SECTION

  # the section runs to the next H1; its trailing blank lines keep separating it from what follows
  stop = next(
      ( idx for idx in range(head + 1, len(lines)) if not fenced[idx] and lines[idx].startswith(_H1_PREFIX) ),
      len(lines))
  last = max(( idx for idx in range(head + 1, stop) if lines[idx].strip() ), default = head)
  preamble, entries, reason = _parse_section(lines[head + 1:last + 1], fenced[head + 1:last + 1])

  # guard: a section with no old line, or one holding a line of neither shape, stays as it is
  if reason is not None:
    return text, reason

  # the heading and its explainer, then every line through the shared journal writer, oldest first
  section = _LF.join([ lines[head], *preamble ]) + _LF
  for day, entry in entries:
    section = history_journal.append(section, entry, day, repo = repo)

  # the frontmatter and every line outside the section are carried over untouched
  return ( text[:end] + _LF.join([ *lines[:head], *section.rstrip(_LF).split(_LF), *lines[last + 1:] ]),
           _REASON_CURRENT )


def _parse_section(lines: list[str], fenced: list[bool]) -> tuple[list[str], list[tuple[str, str]], str | None]:
  """
  Parse the lines of one `# History` section below its heading.

  Args:
    lines: The section's lines below the heading, through its last non-blank line.
    fenced: Whether each of those lines sits inside a code fence.

  Returns:
    The explainer lines under the heading; the `(date, line)` entries in the order they are to be written, oldest
    day first and the old lines of a day ahead of its grouped ones; and the reason the section is left as it is, or
    None when it is to be regrouped.
  """
  preamble: list[str] = []
  old: list[tuple[str, str]] = []
  grouped: list[tuple[str, str]] = []
  day: str | None = None

  # every line is the explainer, the placeholder, an old line, a day heading or a line under one
  for line, is_fenced in zip(lines, fenced, strict = True):
    stripped = line.strip()

    # guard: blank lines separate, and the writer lays the separation out anew
    if not stripped:
      continue

    # guard: a line inside a code fence is no history line, and is never guessed at
    if is_fenced:
      return preamble, [], f"{_REASON_UNRECOGNIZED}: {stripped}"

    # an old-shaped line, matched once for the checks below
    old_match = _OLD_LINE_RE.match(stripped)

    # guard: an old-shaped line under a day heading, or on a day the calendar lacks, is never guessed at
    if old_match and ( day is not None or not _is_calendar_day(old_match[_DATE_GROUP]) ):
      return preamble, [], f"{_REASON_UNRECOGNIZED}: {stripped}"

    # ahead of any group, an old line keeps its text without the date
    if old_match:
      old.append(( old_match[_DATE_GROUP], old_match[_ENTRY_GROUP] ))
      continue

    # a day heading opens a group, and every other bullet under it is a grouped line
    if ( match := _DAY_RE.match(stripped) ):
      day = match[_DATE_GROUP]
      continue
    if day is not None and stripped.startswith(_BULLET):
      grouped.append(( day, stripped ))
      continue

    # ahead of any line, the explainer stays
    if day is None and not old and note_explainers.EXPLAINER_LINE_RE.match(line):
      preamble.append(line)
      continue

    # guard: ahead of any group, the placeholder gives way to the lines
    if day is None and stripped == _NONE_MARKER:
      continue

    # anything else is never guessed at
    return preamble, [], f"{_REASON_UNRECOGNIZED}: {stripped}"

  # guard: a section without an old line is already current
  if not old:
    return preamble, [], _REASON_CURRENT

  # the old list ran newest first; a stable sort by day keeps each day's old lines ahead of its grouped ones
  return preamble, sorted([ *reversed(old), *grouped ], key = lambda item: item[0]), None


def _is_calendar_day(text: str) -> bool:
  """
  Tell whether a `YYYY-MM-DD` string names a day that exists.

  Args:
    text: The date as written in the line.

  Returns:
    True for a real calendar day; False for a well-shaped one that does not exist, such as month 13.
  """
  # a date the calendar rejects is no day to group under
  try:
    date.fromisoformat(text)
  except ValueError:
    return False
  return True


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when at least one note would change, 1 when none would.
    - Any failure exits 2 under every flag and prints no result, never an answer `--check` gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names the
      repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: with `--check`, 0 when a note would change and 1 when none would; 0 otherwise; 2 on any failure.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed; also told apart from both `--check` answers.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when at least one note would change, 1 when none would; any
  # failure MUST exit 2, so a migration step's `applies_when` predicate never reads a failure as an answer.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-upstream-history")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the repo root comes from `--cwd`, else the daemon's env var, else the process cwd
  repo = Path(args.cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()

  # a check runs dry; any failure exits 2, so no flag ever reads a failure as an answer
  try:
    result = migrate(repo, dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    sys.stderr.write(f"migrate-upstream-history: {error!r}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 0 if result[_CHANGED_KEY] else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
