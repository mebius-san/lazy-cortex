#!/usr/bin/env python3
"""
Find plugin-CLI invocations that bypass the interpreter.

    cli_call_scan.py <repo-root> [--dev]

Prints a JSON list of `{"path", "line", "text"}` findings, one per line that runs a
`lazycortex-<plugin>` CLI (or a shell variable holding one) as a bare command. Such a line
works only where the file carries an exec bit and its `bin/` sits on `PATH`; neither holds
after a mode-blind git client touched the checkout, and neither holds under a headless spawn.
The accepted spelling is `"${LAZYCORTEX_PYTHON:-python3}" <path-to-cli> <verb> …`.

Scope: `.claude/**` and `CLAUDE.md` of the repo; with `--dev` also every plugin source tree
under `claude/*/` and the root READMEs. Markdown, YAML and shell files are read; Python and
JSON are not (they call siblings via `sys.executable` and name routines as argv lists).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: the CLI entry names the marketplace ships, not reusable domain keys
_CLI_NAMES = "core|specs|wiki|review|obsidian"
# a bare or path-prefixed CLI name followed by a verb; a `lazycortex-x:agent` reference has no
# space after the name and never matches
_BARE = re.compile(rf'(?<![\w/.-])(?:[^\s"\'`()]*/)?lazycortex-(?:{_CLI_NAMES})\s+(?P<verb>[a-z][a-z-]*)')
# a shell variable that holds a resolved CLI path, run as the command itself
_VAR = re.compile(r'"?\$\{?[A-Z_]*(?:BIN|CLI)\}?"?\s+(?P<verb>[a-z][a-z-]*)')
# text before the match that proves an interpreter carries the call
_INTERPRETED = re.compile(r"LAZYCORTEX_PYTHON|python3 |sys\.executable")
# a code span on a prose line; a match outside one is a sentence naming the plugin, not a call
_CODE_SPAN = re.compile(r"`[^`]*`")
# waiver: the marketplace's single-word verbs — every other verb carries a hyphen, and a plain
# word after a plugin name ("lazycortex-core runtime metrics") is prose unless it is one of these
_SINGLE_WORD_VERBS = frozenset(
    ("runtime", "resume", "scaffold", "retag", "doctor", "decide", "pins", "status", "sanitize",
     "start", "stop", "finalize", "sync", "reconcile"))
# waiver: file kinds whose text is read as instructions; code and data are out of scope
_SUFFIXES = (".md", ".yml", ".yaml", ".sh")
# waiver: repo layout, not a reusable domain key
_LOCAL_ROOT, _DEV_ROOT = ".claude", "claude"
# waiver: files scanned at the repo root, not reusable domain keys
_ROOT_FILES = ("CLAUDE.md", "README.md", "README.public.md")
# waiver: generated release notes never carry a runnable instruction
_SKIP_PREFIX = "CHANGELOG"
# waiver: markdown fence marker
_FENCE = "```"


def _is_verb(word: str) -> bool:
  """
  Report whether a word after a CLI name reads as one of its verbs.

  Args:
    word: The token following the CLI name.

  Returns:
    True for a hyphenated verb or a known single-word one.
  """
  return "-" in word or word in _SINGLE_WORD_VERBS


def _in_code(line: str, at: int, fenced: bool) -> bool:
  """
  Report whether a position on a line sits in code rather than prose.

  Args:
    line: The line.
    at: Offset of the match.
    fenced: Whether the line lies inside a fenced block.

  Returns:
    True inside a fence, a backtick span, or a `Bash(` call.
  """
  # guard: a fenced line and a `Bash(` call are code wherever the match sits
  if fenced or "Bash(" in line[:at]:
    return True
  return any(span.start() < at < span.end() for span in _CODE_SPAN.finditer(line))


def _call_at(line: str, fenced: bool) -> bool:
  """
  Report whether a line runs a CLI without an interpreter.

  Args:
    line: The line.
    fenced: Whether the line lies inside a fenced block.

  Returns:
    True when a code-context match with a real verb has no interpreter before it.
  """
  for pattern in (_BARE, _VAR):
    for hit in pattern.finditer(line):
      if _INTERPRETED.search(line[:hit.start()]):
        continue
      if _is_verb(hit.group("verb")) and _in_code(line, hit.start(), fenced):
        return True
  return False


def _scan_text(path: Path, text: str) -> list[dict]:
  """
  Report every line of one file that runs a CLI without an interpreter.

  Args:
    path: File the text came from, echoed into each finding.
    text: The file's content.

  Returns:
    Findings in line order; empty when the file is clean.
  """
  out: list[dict] = []
  fenced = False
  for number, line in enumerate(text.splitlines(), 1):
    # track fenced blocks so a bare call inside one is read as code
    if line.lstrip().startswith(_FENCE):
      fenced = not fenced
      continue
    if _call_at(line, fenced):
      # waiver: JSON report keys read by the doctor skill and the test
      out.append({ "path": str(path), "line": number, "text": line.strip() })
  return out


def _candidates(root: Path, dev: bool) -> list[Path]:
  """
  List the files the scan reads, in path order.

  Args:
    root: Repo root.
    dev: Whether the repo authors plugins and `claude/*/` joins the scope.

  Returns:
    Instruction-bearing files under the scanned trees.
  """
  trees = [ root / _LOCAL_ROOT ] + ([ root / _DEV_ROOT ] if dev else [])
  files = [ root / name for name in _ROOT_FILES if (root / name).is_file() ]
  for tree in trees:
    files += [
        p for p in tree.rglob("*")
        if p.suffix in _SUFFIXES and p.is_file() and not p.name.startswith(_SKIP_PREFIX)
    ]
  return sorted(set(files))


def scan(root: Path, dev: bool = False) -> list[dict]:
  """
  Scan a repo for CLI calls that bypass the interpreter.

  Guarantees:
    - A line whose match is preceded by `LAZYCORTEX_PYTHON`, `python3 ` or `sys.executable`
      is never reported.
    - Paths in the report are relative to `root`, in path order.

  Args:
    root: Repo root.
    dev: Whether to include the plugin sources under `claude/*/`.

  Returns:
    The findings described in the module docstring.
  """
  # Contract: the report is empty exactly when every scanned line either names no CLI or hands
  # it to an interpreter; the repo test and the doctor check both rely on that reading.
  out: list[dict] = []
  for path in _candidates(root, dev):
    # waiver: stdlib encoding idiom
    out += _scan_text(path.relative_to(root), path.read_text(encoding = "utf-8", errors = "replace"))
  return out


def main(argv: list[str] | None = None) -> int:
  """
  Parse the arguments and print the findings for the named repo.

  Args:
    argv: Arguments without the program name; defaults to `sys.argv[1:]`.

  Returns:
    Process exit code: 0 on success, 2 on a usage error.
  """
  # waiver: argparse surface strings, not reusable domain keys
  parser = argparse.ArgumentParser(prog = "cli_call_scan.py")
  # waiver: argparse surface strings, not reusable domain keys
  parser.add_argument("repo", help = "repo root to scan")
  # waiver: argparse surface strings, not reusable domain keys
  parser.add_argument("--dev", action = "store_true", help = "also scan plugin sources under claude/*/")
  args = parser.parse_args(argv)

  # guard: a repo path that is not a directory is a usage error, not an empty report
  repo = Path(args.repo).resolve()
  if not repo.is_dir():
    print(f"error: not a directory: {repo}", file = sys.stderr)
    return 2

  # emit the report the doctor skill and the repo test read
  print(json.dumps(scan(repo, args.dev), indent = 2, ensure_ascii = False))
  return 0


if __name__ == "__main__":
  sys.exit(main())
