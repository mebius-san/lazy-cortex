"""
Logic behind the `lazycortex-specs migrate-report-order` verb — turns the run entries of a release's report journals
around so the newest run stands first.

An earlier release wrote the `#### build <k>` entries of a release's `code-report.md` and `test-report.md` oldest
first. The journals now list them newest first. This verb reverses the entries of every release's journals once,
keeping a newest entry that an old-order report received on top where it stands, and leaves a report it cannot read as
one run of entries as it is, reporting why. Every byte outside the entries stays. It never commits.
"""
from __future__ import annotations

import argparse
import itertools
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
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    ReleaseKey,
    SiblingDoc,
)


# The report journals of a release folder, and the frontmatter key its folder note names its asset type with.
_JOURNAL_DOCS = ( SiblingDoc.CODE_REPORT, SiblingDoc.TEST_REPORT )
_ASSET_TYPE_KEY = "spec_asset_type"
_MD_SUFFIX = ".md"

# The heading that opens one run entry, and the heading lines that close one: any heading of level 1 to 4.
_ENTRY_RE = re.compile(r"^#### build (?P<build>\d+)[ \t]*$")
_ENTRY_END_RE = re.compile(r"^#{1,4}(\s|$)")
_BUILD_GROUP = "build"

# Why a report was left as it is.
_REASON_CURRENT = "already newest first"
_REASON_NO_ENTRIES = "no build entries"
_REASON_SAME_BUILD = "entry order cannot be told: every entry names the same build"
_REASON_MIXED = "entry order is neither oldest first nor newest first"
_REASON_SPLIT = "build entries are not contiguous"

_LF = "\n"
_CR = "\r"
_CRLF = "\r\n"
_ENCODING = "utf-8"

# The result's own wire-shape keys, and the keys of one skipped entry, read by the migration step and the tests.
_CHANGED_KEY = "changed"
_SKIPPED_KEY = "skipped"
_PATH_KEY = "path"
_REASON_KEY = "reason"

# The exit code of a failed run, told apart from both `--check` answers.
_EXIT_FAILED = 2


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Reverse the build entries of every release's report journals from oldest first to newest first.

  Guarantees:
    - A report whose entries run oldest first comes out with the same entries newest first; so does a report whose
      first entry names a higher build than every other entry while the entries after it run oldest first, with that
      first entry kept in place. In both cases every byte before the first entry and after the last one, the blank
      lines between entries, the line endings and a missing final newline are kept.
    - A report already newest first, with one entry, with no entry, with every entry naming the same build, with any
      other mix of orders or with another heading between two entries is left byte-identical, reported skipped
      with a reason.
    - A dry run writes no file, and a second run over the result changes nothing.

  Notes:
    - Reads every release report journal under the spec content root and rewrites each reversed one in place on disk.
    - Never commits; the rewritten files stay in the working tree for the caller to commit.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    `{"changed", "skipped"}` — the reports rewritten, as paths relative to the settings root, and the reports left
    as they are, each a `{"path", "reason"}` record; both in walk order.

  Raises:
    FileNotFoundError: When no settings file lies at or above `repo`.
    OSError: When a report cannot be read or written.
    VaultRootError: When the settings or the content root they name is refused.
  """

  # Contract:
  # A report whose build entries run oldest first MUST come out with the same entries newest first. So MUST a report
  # whose first entry names a higher build than every other entry while the entries after it run oldest first, with
  # that first entry kept in place. Either way every byte before the first entry and after the last one MUST be kept,
  # the blank lines between entries kept in their places and the line endings and a missing final newline kept. A
  # report already newest first, with one entry, with no entry, with every entry naming the same build, with any other
  # mix of orders or with another heading between two entries MUST be left byte-identical and reported skipped with a
  # reason. A dry run MUST write no file, and running the verb again over its own output MUST change nothing.

  # Domain(spec.repair):
  # # A release's report journals list their runs newest first
  # Each run of a build or of a test writes one entry into the release's report, and the entry of the newest run
  # stands first, right under the document's title, with the earlier entries below it unchanged. Reports written
  # before this order held their entries oldest first; turning such a report around once puts it into the current
  # order, and a report already in it is left alone. A report whose order cannot be told is never guessed at.

  # the settings root the result's paths are relative to, and the empty result
  settings_root = spec_paths.require_settings_root(repo)
  result: dict = { _CHANGED_KEY: [], _SKIPPED_KEY: [] }

  # every release folder under the content root, its journals in a stable order
  for dirpath, dirnames, filenames in os.walk(spec_paths.spec_content_root(settings_root)):
    dirnames.sort()
    folder = Path(dirpath)

    # guard: only a release folder holds the report journals
    if not set(_JOURNAL_DOCS) & set(filenames) or not _is_release_folder(folder):
      continue

    # each journal of the release folder, the code report first
    for name in _JOURNAL_DOCS:

      # guard: a journal the release does not have is nothing to migrate
      if name not in filenames:
        continue

      # the journal's raw text, its line endings untranslated
      doc = folder / name
      with open(doc, encoding = _ENCODING, newline = "") as handle:
        text = handle.read()

      # the journal turned around, or the reason it stays, and its path as the result names it
      new_text, reason = _reorder(text)
      rel = doc.relative_to(settings_root).as_posix()

      # a journal the migration leaves as it is goes unwritten, reported with the reason
      if reason is not None:
        result[_SKIPPED_KEY].append({ _PATH_KEY: rel, _REASON_KEY: reason })
        continue

      # a reversed journal is reported, and written unless the run is dry
      result[_CHANGED_KEY].append(rel)
      if not dry_run:
        spec_paths.write_text_atomic(doc, new_text, newline = _LF)

  # both lists in walk order
  return result


def _is_release_folder(folder: Path) -> bool:
  """
  Tell whether a folder is a release folder.

  Args:
    folder: The folder to test.

  Returns:
    True when the folder's own note names the release asset type; False otherwise.
  """
  # a release folder is one whose folder note names the release asset type
  note = folder / f"{folder.name}{_MD_SUFFIX}"
  return note.is_file() and spec_frontmatter.parse(spec_paths.read_text(note))[0].get(
      _ASSET_TYPE_KEY) == ReleaseKey.ASSET_TYPE


def _reorder(text: str) -> tuple[str, str | None]:
  """
  Put the build entries of one report newest first, or leave the report as it is.

  Args:
    text: The full report text, line endings untranslated.

  Returns:
    The report text with its entries newest first, and None as the reason; or the text unchanged and the reason the
    report is left as it is.
  """
  # the body's lines with their own endings, each marked when it sits inside a code fence
  end = spec_frontmatter.block(text)[1]
  lines = spec_frontmatter.split_lines(text[end:], keepends = True)
  bare = [ line.rstrip(_LF).rstrip(_CR) for line in lines ]
  fenced = spec_frontmatter.fenced_lines(bare)

  # every entry heading outside a fence, with the build it names
  headings = [ ( idx, match ) for idx, row in enumerate(bare)
               if not fenced[idx] and ( match := _ENTRY_RE.match(row) ) ]
  starts = [ idx for idx, _match in headings ]

  # guard: a report without an entry has nothing to reorder
  if not starts:
    return text, _REASON_NO_ENTRIES

  # each entry runs to the next heading of level 1 to 4 outside a fence
  spans = [ ( start, _find_entry_end(bare, fenced, start) ) for start in starts ]

  # guard: entries split by another heading cannot be turned around as one run
  if any(spans[idx][1] != spans[idx + 1][0] for idx in range(len(spans) - 1)):
    return text, _REASON_SPLIT

  # the order the build numbers tell, top to bottom
  builds = [ int(match[_BUILD_GROUP]) for _idx, match in headings ]
  pairs = list(itertools.pairwise(builds))
  rises = any(low < high for low, high in pairs)
  falls = any(low > high for low, high in pairs)

  # guard: entries all naming one build give no order to read
  if len(builds) > 1 and not rises and not falls:
    return text, _REASON_SAME_BUILD

  # a report newest first already, or holding one entry, stays as it is
  if not rises:
    return text, _REASON_CURRENT

  # Domain(spec.repair):
  # # A report caught halfway between the two orders
  # A report written in the old order receives its next run's entry on top, so its newest entry stands first while
  # the older entries below it still run oldest first. That shape has one readable order: the top entry is already
  # in place, and only the entries under it are turned around. Any other mix of rising and falling builds is never
  # guessed at and stays as it is.

  # whether the top entry is newer than all the rest while the entries under it run oldest first
  keeps_head = builds[0] > max(builds[1:]) and all(low <= high for low, high in itertools.pairwise(builds[1:]))

  # guard: an order of neither kind is never guessed at
  if falls and not keeps_head:
    return text, _REASON_MIXED

  # the region of the entries, the line ending its first line carries, and whether its last line lacks one
  first, last = spans[0][0], spans[-1][1]
  region = lines[first:last]
  ending = _CRLF if region[0].endswith(_CRLF) else _LF
  open_end = not region[-1].endswith(_LF)

  # guard: a last line without its line ending gets the region's own one while the entries move, so no two entries
  # share a line
  if open_end:
    region[-1] += ending

  # each entry splits into its text and the blank lines that end it; the texts swap, the gaps keep their slots
  texts: list[list[str]] = []
  gaps: list[list[str]] = []
  for start, stop in spans:
    rows = region[start - first:stop - first]
    keep = max(( idx for idx, row in enumerate(rows) if row.strip() ), default = 0) + 1
    texts.append(rows[:keep])
    gaps.append(rows[keep:])
  order = [ texts[0], *reversed(texts[1:]) ] if falls else list(reversed(texts))
  turned = "".join("".join(body) + "".join(gap) for body, gap in zip(order, gaps, strict = True))

  # the missing final newline stays missing
  if open_end:
    turned = turned[:-len(ending)]

  # the frontmatter, the head and the tail are carried over untouched
  return text[:end] + "".join(lines[:first]) + turned + "".join(lines[last:]), None


def _find_entry_end(bare: list[str], fenced: list[bool], start: int) -> int:
  """
  Find the line where a build entry ends.

  Args:
    bare: The body's lines without their line endings.
    fenced: Whether each of those lines sits inside a code fence.
    start: The index of the entry's heading line.

  Returns:
    The index of the first line after the entry.
  """
  # the next heading of level 1 to 4 outside a fence ends the entry, else the end of the text
  return next(( idx for idx in range(start + 1, len(bare)) if not fenced[idx] and _ENTRY_END_RE.match(bare[idx]) ),
              len(bare))


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when at least one report would change, 1 when none would.
    - Any failure exits 2 under every flag and prints no result, never an answer `--check` gives.

  Notes:
    - Prints the `migrate` result to stdout as one JSON object; a failure is written to stderr instead.
    - The run works in the nearest directory, within its checkout, that holds `.claude/lazy.settings.json`, searched
      upward from `--cwd`, else the `LAZY_REPO_ROOT` environment variable, else the process working directory; the
      checkout's root when none holds it.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names a
      directory inside the repository (falling back to the `LAZY_REPO_ROOT` environment variable, then the process
      working directory); the run works in the nearest directory at or above it, within its checkout, that holds
      `.claude/lazy.settings.json`, else the checkout's root.

  Returns:
    Exit code: with `--check`, 0 when a report would change and 1 when none would; 0 otherwise; 2 on any failure.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed; also told apart from both `--check` answers.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when at least one report would change, 1 when none would;
  # any failure MUST exit 2, so a migration step's `applies_when` predicate never reads a failure as an answer.

  # the verb's three flags
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-report-order")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # a check runs dry; any failure exits 2, so no flag ever reads a failure as an answer
  try:
    result = migrate(spec_locator.query_settings_root(args.cwd), dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    sys.stderr.write(f"migrate-report-order: {error!r}\n")
    return _EXIT_FAILED
  # a refused content root is a `BaseException` the broad catch above lets through; it fails the run the same way
  except spec_paths.VaultRootError as error:
    sys.stderr.write(f"migrate-report-order: {error!r}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 0 if result[_CHANGED_KEY] else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
