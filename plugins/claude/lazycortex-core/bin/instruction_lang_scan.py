#!/usr/bin/env python3
"""
Find instruction text written in a language other than English.

    instruction_lang_scan.py <repo-root> [--dev]

Prints a JSON list of `{"path", "line", "text"}` findings. A skill, command or agent is written in
English; text in another language appears only as data, inside a code span or quotes
(`lazy-core.skill-writing` § 14). A finding is a line that carries a letter outside the Latin
script, a Greek letter of a formula aside, anywhere a reader takes as instruction: outside a
fenced block, outside a backtick span, and outside a double-quoted, guillemet-quoted,
curly-quoted or single-quoted stretch. In the frontmatter the YAML quoting of a value is not
counted as a quote, so a quoted `description:` is read like prose.

The check sees scripts, not languages: a language written in Latin letters (German, Spanish)
passes it.

Scope is the markdown under the `skills/`, `commands/` and `agents/` folders of `.claude/`, and
with `--dev` of every plugin source tree under `plugins/claude/*/` as well; a skill's own
`references/` sit under its folder and are read too.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable —
# the sibling scanner owns the scope walk both scans share
from cli_call_scan import _candidates  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# a backtick span, then the quote pairs that mark text as data: double, guillemet, curly, and a single-quoted
# stretch that opens and closes outside a word, so an apostrophe never opens one
_DATA_SPANS = re.compile(r"`[^`]*`|\"[^\"]*\"|«[^»]*»|“[^”]*”|(?<!\w)'[^'\n]*'(?!\w)")
# a frontmatter line whose whole value is YAML-quoted; the quoting belongs to YAML, not to the text
_YAML_QUOTED = re.compile(r"^\s*[\w-]+:\s*([\"'])(?P<value>.*)\1\s*$")
# waiver: the named group the frontmatter pattern above declares
_VALUE_GROUP = "value"
# waiver: path segments of the artifacts the rule governs
_ARTIFACT_DIRS = ("/skills/", "/commands/", "/agents/")
# waiver: markdown suffix and fence marker, and the frontmatter delimiter
_MARKDOWN, _FENCE, _FRONTMATTER = ".md", "```", "---"
# waiver: the Unicode name prefixes of the scripts instruction text may use: Latin for prose, Greek for the
# symbols of a formula
_ALLOWED_SCRIPTS = ("LATIN", "GREEK")


def _is_foreign(text: str) -> bool:
  """
  Report whether text carries a letter outside the Latin script, Greek formula symbols aside.

  Args:
    text: Text with every data span already removed.

  Returns:
    True when at least one alphabetic character is neither a Latin nor a Greek letter.
  """
  return any(char.isalpha() and not unicodedata.name(char, "").startswith(_ALLOWED_SCRIPTS) for char in text)


def _scan_text(path: Path, text: str) -> list[dict[str, str | int]]:
  """
  Report every instruction line of one file that carries a letter outside the Latin and Greek scripts.

  Args:
    path: File the text came from, echoed into each finding.
    text: The file's content.

  Returns:
    Findings in line order; empty when the file is clean.
  """
  # the walk's state: the report, whether the line sits in the frontmatter, and whether it sits in a fence
  out: list[dict[str, str | int]] = []
  lines = text.splitlines()
  in_frontmatter = bool(lines) and lines[0].strip() == _FRONTMATTER
  fenced = False

  # walk the file once, skipping fences and reading frontmatter values without their YAML quoting
  for number, line in enumerate(lines, 1):
    stripped, body = line.strip(), line

    # the frontmatter ends at its second delimiter; its values are read without their YAML quoting
    if in_frontmatter:
      # the opening delimiter carries no text, and the closing one ends the frontmatter
      if stripped == _FRONTMATTER:
        in_frontmatter = number == 1
        continue
      if quoted := _YAML_QUOTED.match(line):
        body = quoted.group(_VALUE_GROUP)

    # a fence line opens or closes a block, and a fenced line is code
    elif stripped.startswith(_FENCE):
      fenced = not fenced
      continue
    elif fenced:
      continue

    # a line whose text, data spans removed, carries a letter outside the Latin and Greek scripts is a finding
    if _is_foreign(_DATA_SPANS.sub("", body)):
      # waiver: JSON report keys
      out.append({ "path": str(path), "line": number, "text": stripped })

  # the file's findings in line order
  return out


def scan(root: Path, *, dev: bool = False) -> list[dict[str, str | int]]:
  """
  Scan a repo's skills, commands and agents for instruction text outside English.

  Guarantees:
    - A Greek letter passes like a Latin one, as a formula symbol; a letter outside the Latin and Greek scripts on an
      instruction line is reported.
    - The report is empty exactly when every instruction line carries no letter outside the Latin and Greek scripts.
    - A letter inside a fenced block, a backtick span, or a double-quoted, guillemet-quoted, curly-quoted or
      single-quoted stretch of the body is data and is never reported.
    - In the frontmatter the YAML quoting of a value is not data: a quoted `description:` is read like prose and its
      letters are reported.
    - Each finding names its file by a path relative to `root`, and findings come in path order.

  Args:
    root: Repository root the scanned paths are relative to.
    dev: Whether to include the plugin sources under `plugins/claude/*/`.

  Returns:
    The findings described in the module docstring.
  """

  # Contract:
  # A Greek letter passes like a Latin one, as a formula symbol. The report is empty exactly when every
  # governed instruction line carries no letter outside the Latin and Greek scripts; the audit and the repo
  # test rely on that reading.

  # Contract:
  # A letter inside a fenced block, a backtick span, or a double-quoted, guillemet-quoted, curly-quoted or
  # single-quoted stretch of the body is data and is never reported. In the frontmatter the YAML quoting of
  # a value is not data: a quoted `description:` is read like prose and its letters are reported.

  # Contract:
  # Each finding names its file by a path relative to `root`, and findings come in path order, so the
  # audit's report reads the same wherever the repository sits.

  # walk every candidate, keeping only the markdown of the governed artifacts
  out: list[dict[str, str | int]] = []
  for path in _candidates(root, dev):
    rel = path.relative_to(root)

    # guard: a file outside the governed artifact folders, or not markdown, is not an instruction this rule reads
    if path.suffix != _MARKDOWN or not any(part in f"/{rel.as_posix()}" for part in _ARTIFACT_DIRS):
      continue

    # the file's findings join the report under its repo-relative path
    # waiver: stdlib encoding idiom
    out += _scan_text(rel, path.read_text(encoding = "utf-8", errors = "replace"))

  # the findings in path order
  return out


def main(argv: list[str] | None = None) -> int:
  """
  Parse the arguments and print the findings for the named repo.

  Args:
    argv: Arguments without the program name; defaults to `sys.argv[1:]`.

  Returns:
    Process exit code: 0 on success, 2 on a usage error.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the scanner's command line: the repo root and the dev-tree switch
  # waiver: argparse surface strings, not reusable domain keys
  parser = argparse.ArgumentParser(prog = "instruction_lang_scan.py")
  # waiver: argparse surface strings, not reusable domain keys
  parser.add_argument("repo", help = "repo root to scan")
  # waiver: argparse surface strings, not reusable domain keys
  parser.add_argument("--dev", action = "store_true", help = "also scan plugin sources under plugins/claude/*/")
  args = parser.parse_args(argv)

  # guard: a repo path that is not a directory is a usage error, not an empty report
  if not (repo := Path(args.repo).resolve()).is_dir():
    print(f"error: not a directory: {repo}", file = sys.stderr)
    return 2

  # emit the report the audit skill and the repo test read
  print(json.dumps(scan(repo, dev = args.dev), indent = 2, ensure_ascii = False))
  return 0


if __name__ == "__main__":
  sys.exit(main())
