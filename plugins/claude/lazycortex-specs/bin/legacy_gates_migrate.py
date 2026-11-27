"""
Logic behind the `lazycortex-specs migrate-legacy-gates` verb — takes the launch rows and gate keys earlier plugin
versions left on spec notes and the current plugin no longer declares off them.

Earlier versions hung implementation, testing and planning rows on asset notes and kept the middle rungs of the
release ladder on research notes. Nothing reads them any more, yet a ticked leftover stays ticked and wakes its asset
again and again. This verb drops exactly those rows from the `# Gates` section of status and level notes and those
keys from research notes, leaving every other line as it was, and reports which notes it changed. It never commits.
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

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_rows  # noqa: E402  # pylint: disable=import-error,wrong-import-position
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
    LEVEL_ROLES, RELEASE_ONLY_GATES, RESEARCH_ASSET_TYPE, AssetTypeKey, GateCheckbox, ReleaseKey, Section, SpecKey,
    SpecMomentKey, SpecValue,
)


# The note roles this verb migrates: an asset's status note and both level notes.
_MIGRATED_ROLES = LEVEL_ROLES | { SpecValue.ROLE_STATUS }

# The retired launch labels no note of any role carries any more.
_RETIRED_EVERYWHERE = frozenset({ "Start testing", "Start coding", "Start data entry", "Start documentation",
                                  "Revise design" })

# The retired per-tool implementation launch, with or without the tool named in parentheses.
_START_IMPLEMENTATION_RE = re.compile(r"Start implementation(?: \(.*\))?")

# The labels only a release note or a level note still carries; on any other asset note they are retired.
_RETIRED_ON_ASSETS = frozenset({ GateCheckbox.WRITE_ARCHITECTURE, GateCheckbox.PUBLISH })

# A retired per-tool plan launch on an asset note: any `Write <tool>-plan` but the asset's own `Write test-plan`.
_TOOL_PLAN_RE = re.compile(rf"(?!{re.escape(GateCheckbox.WRITE_TEST_PLAN)}$){GateCheckbox.WRITE_VERB} \S+-plan")

# The release-ladder gates and their moment keys a research note no longer carries.
_RESEARCH_RETIRED_KEYS = tuple(
    key for gate in sorted(RELEASE_ONLY_GATES) for key in ( gate, f"{gate}{SpecMomentKey.AT_SUFFIX}" )
)

_H1_PREFIX = "# "
_LF = "\n"
_MD_SUFFIX = ".md"

# The exit code of a run that failed, never an answer `--check` gives.
_EXIT_FAILED = 2

# The result's own wire-shape keys, read by the migration step and the tests.
_CHANGED_KEY = "changed"
_SKIPPED_KEY = "skipped"


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Drop the retired launch rows and research gate keys from every status and level note of the spec catalog.

  Guarantees:
    - Only retired rows of `# Gates`, the gate callouts and group sub-headings they leave empty, and the
      release-ladder keys of a research note change; every other line keeps its bytes and its order, and a note
      with nothing to change is not written.
    - A retired row goes whether it is ticked or not, and is never replaced by another row.
    - A dry run writes nothing.
    - A second run over the result changes nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    `{"changed", "skipped"}` — the notes rewritten and the notes already current, each a list of paths relative to
    the settings root, in walk order.

  Raises:
    FileNotFoundError: When no settings file lies at or above `repo`.
    ValueError: When the settings file cannot be read, is not UTF-8 text, not valid JSON or not a JSON object, or a
      note under the content root is not UTF-8 text.
    OSError: When a note cannot be read or written.
    VaultRootError: When `spec.vault_root` names no sub-directory of the settings root.
  """

  # Contract:
  # Only retired rows, the callouts and sub-headings they leave empty, and a research note's release-ladder keys
  # change; every other line of a note MUST keep its bytes and order. A retired row MUST be dropped, ticked or not,
  # and never renamed into a current one. A dry run MUST write no file, and running the verb again over its own
  # output MUST change nothing.

  # settings that cannot be read as a JSON object stop the migration here: the content root they would name is
  # unknown, and the default one must never be migrated in its place
  settings_root = spec_paths.require_settings_root(repo)
  spec_paths.require_valid_settings(settings_root)
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
      role = fm_values.get(SpecKey.ROLE, "")

      # guard: only an asset's status note and a level note carry launch rows; an unreadable role is neither
      if not isinstance(role, str) or role.strip() not in _MIGRATED_ROLES:
        continue

      # a note the migration leaves as it is goes unwritten; an asset type of any other shape names no type
      asset_type = fm_values.get(AssetTypeKey.TYPE, "")
      new_text = _migrate_text(text, role.strip(), asset_type.strip() if isinstance(asset_type, str) else "")
      rel = note.relative_to(settings_root).as_posix()
      if new_text == text:
        result[_SKIPPED_KEY].append(rel)
        continue
      result[_CHANGED_KEY].append(rel)
      if not dry_run:
        spec_paths.write_text_atomic(note, new_text)

  # both lists in walk order
  return result


def _migrate_text(text: str, role: str, kind: str) -> str:
  """
  Rewrite one note's text without its retired rows and keys.

  Args:
    text: The full note text.
    role: The note's `spec_role`.
    kind: The note's `spec_asset_type`, empty when the note declares none.

  Returns:
    The note text without the retired rows and keys; the text unchanged when it carries none of them.
  """

  # Domain(spec.notes):
  # # A research note carries no release rungs
  # A research asset is never built or released by a release: its ladder is the accepted design and the accepted
  # report, nothing in between. The plan, development, tests and built checkpoints belong to a release alone, so a
  # research note that still carries one of them, or the moment it closed, loses it; a release keeps all of them.

  # a research note keeps only the design and released gates of the ladder
  if role == SpecValue.ROLE_STATUS and kind == RESEARCH_ASSET_TYPE:
    for key in _RESEARCH_RETIRED_KEYS:
      text = spec_frontmatter.drop_key(text, key)

  # every walked note loses its retired rows; an asset note other than a release loses the release's own ones too
  return _drop_retired_rows(text, asset_note = role == SpecValue.ROLE_STATUS and kind != ReleaseKey.ASSET_TYPE)


def _is_retired(label: str, *, asset_note: bool) -> bool:
  """
  Tell whether a launch row's label is one the current plugin no longer hangs on the note.

  Args:
    label: The row's label.
    asset_note: Whether the note is an asset's status note other than a release's.

  Returns:
    True when the label is retired on every note, or retired on an asset note and the note is one.
  """

  # Domain(spec.notes):
  # # Retired launch rows
  # Earlier versions hung rows that started an asset's implementation, its testing, its coding, its data entry or
  # its documentation, a per-tool plan, a design revision on a level, and — on an ordinary asset — the architecture
  # writing and the publication. Today the implementation of every asset is a build of its product's release, so
  # none of those rows exists on an asset any more: only a release plans, builds, tests and publishes, and only a
  # product writes its architecture. An asset keeps its own test cases row, and a research asset its own start row.
  # A retired row is dropped from the note, ticked or not; it is never turned into a current row, because an old
  # tick would then launch work nobody asked for now.

  # a label retired on every note, then the ones retired only on an ordinary asset
  if label in _RETIRED_EVERYWHERE or _START_IMPLEMENTATION_RE.fullmatch(label):
    return True
  return asset_note and (label in _RETIRED_ON_ASSETS or _TOOL_PLAN_RE.fullmatch(label) is not None)


def _drop_retired_rows(text: str, *, asset_note: bool) -> str:
  """
  Remove every retired row from a note's `# Gates` section.

  Args:
    text: The full note text.
    asset_note: Whether the note is an asset's status note other than a release's.

  Returns:
    The note text without those rows, without a gate callout or group sub-heading they leave empty, and without the
    blank line that separated an emptied callout; unchanged when the section carries no such row.
  """
  _fm_text, end = spec_frontmatter.block(text)
  lines = text[end:].split(_LF)

  # a line inside a code fence is never structure: it opens no section and hangs no row
  prose = [ not fenced for fenced in spec_frontmatter.fenced_lines(lines) ]

  # guard: a note without the gates section hangs no row
  if (head := next(( idx for idx, line in enumerate(lines) if prose[idx] and line.strip() == Section.GATES ),
                   None)) is None:
    return text

  # the section runs to the next H1 outside a fence, or to the end of the note
  stop = next(( idx for idx in range(head + 1, len(lines)) if prose[idx] and lines[idx].startswith(_H1_PREFIX) ),
              len(lines))
  section, tail = lines[head:stop], lines[stop:]

  # the retired rows outside a fence, by the line each one is read from
  doomed = {
      row.line for row in review_rows.parse_gate_rows(section)
      if prose[head + row.line] and _is_retired(row.label, asset_note = asset_note)
  }

  # guard: a section without a retired row stays byte for byte
  if not doomed:
    return text

  # the rows go with every callout they empty, then every group sub-heading left without a callout
  review_rows.drop_rows(section, doomed, tail)
  _drop_empty_headings(section)

  # the frontmatter and the lines around the section are carried over untouched
  return text[:end] + _LF.join([ *lines[:head], *section, *tail ])


def _drop_empty_headings(section: list[str]) -> None:
  """
  Remove the group sub-headings of a `# Gates` section that no longer head any line, in place.

  Args:
    section: Lines of the `# Gates` section, heading first, edited in place.
  """
  headings = note_explainers.gate_heading_texts()
  prose = [ not fenced for fenced in spec_frontmatter.fenced_lines(section) ]

  # from the back, so the indices still to visit stay valid while later lines go
  for idx in reversed(range(1, len(section))):

    # guard: only a group sub-heading outside a fence can be left empty
    if not prose[idx] or section[idx] not in headings:
      continue

    # a sub-heading followed by nothing but blank lines up to the next one, or the end, heads nothing and goes
    written = next(( pos for pos in range(idx + 1, len(section)) if section[pos].strip() ), len(section))
    if written == len(section) or section[written] in headings:
      del section[idx:written]


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when at least one note would change, 1 when none would.
    - Any failure of the migration exits 2 under every flag and prints no result, never an answer `--check` gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names a
      directory inside the repository (falling back to the `LAZY_REPO_ROOT` environment variable, then the process
      working directory); the run works in the nearest directory at or above it, within its checkout, that holds
      `.claude/lazy.settings.json`, else the checkout's root.

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
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-legacy-gates")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the migration runs, dry under a check; whatever stops it is named on stderr and exits 2
  try:
    result = migrate(spec_locator.query_settings_root(args.cwd), dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    # an unreadable catalog, malformed settings, or any other fault is not an answer and must never look like one
    sys.stderr.write(f"migrate-legacy-gates: {error!r}\n")
    return _EXIT_FAILED
  # a refused content root is a `BaseException` the broad catch above lets through; it fails the run the same way
  except spec_paths.VaultRootError as error:
    sys.stderr.write(f"migrate-legacy-gates: {error!r}\n")
    return _EXIT_FAILED

  # the result is printed only once the migration finished
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 0 if result[_CHANGED_KEY] else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
