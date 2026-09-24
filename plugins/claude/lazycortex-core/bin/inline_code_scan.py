#!/usr/bin/env python3
"""
Find executable code embedded in markdown instructions.

    inline_code_scan.py <repo-root> [--dev]

Prints a JSON list of `{"path", "line", "kind", "text"}` findings. A skill, agent, command,
rule or reference may tell the agent to run a program that lives on disk; it may not carry
the program itself. Code in markdown escapes every checker and every test — a wrong import
or a typo in it surfaces only when an operator runs the step. Three kinds are reported:

- `interpreter` — an interpreter handed its program inline: `python3 -c "…"`,
  `python3 - <<'EOF'`, `node -e '…'`, `sh -c "…"`, and the same behind `$LAZYCORTEX_PYTHON`.
- `shell-script` — shell control flow (`then`, `fi`, `do`, `done`, `esac`) in a runnable
  shell context: a shell-typed or untyped fence, a line carrying a `Bash(` call, or a backtick
  code span on a prose line. One finding per fenced block.
- `code-fence` — a `python` / `javascript` fence inside a skill or command body, which the
  agent can only act on by running it.

Allowed, and never reported: one invocation of a file on disk, including a plugin CLI verb
behind the interpreter (`"${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb> …`); a single
command or pipeline; a code fence in an agent, rule or reference that illustrates an API or a
style rather than asking to be run.

Scope is the same as `cli_call_scan.py`, narrowed to markdown: `.claude/**` and `CLAUDE.md`,
and with `--dev` every plugin source tree under `plugins/claude/*/` and the root READMEs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable —
# the sibling scanner owns the scope walk and the code-context reading, which both scans must share
from cli_call_scan import _candidates, _in_code  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# an interpreter name as the command word, or the `$LAZYCORTEX_PYTHON` spelling of python
_INTERP = r'(?:(?<![\w/.-])(?:python3?|node|perl|ruby|osascript|bash|zsh|sh)|LAZYCORTEX_PYTHON:-python3\}"?)'
# the interpreter reads its program from the command line (`-c` / `-e` followed by the quoted
# program or a substitution) or from stdin (`-` as the script argument, or a heredoc)
_INLINE = re.compile(_INTERP + r"""(?:\s+-[A-Za-z]+)*?\s+(?:-[ce]\s*["'$]|-(?=\s|$)|<<)""")
# a heredoc fed to an interpreter reading its program from stdin (`python3 - "<arg>" <<'EOF'`); a heredoc
# behind a script file is that script's input, not a program
_HEREDOC = re.compile(_INTERP + r"\s+-\s[^|;&`]*<<")
# a shell keyword that only a multi-statement script carries, in command position: at the line
# start or after a separator; a trailing `=`, `(` or `.` is a Python name, not the keyword
_SHELL_KEYWORD = re.compile(r"(?:^|[;&|])\s*(?:then|fi|do|done|esac)\b(?!\s*[=(.])")
# a line that opens or continues a shell construct; the only reading of an untyped fence, whose
# body is as often prose as script
_SHELL_LINE = re.compile(
  r"^\s*(?:for|while|until|if|case|esac|fi|done|then|do|else|elif)\b(?!\s*[=(.:])(?!.*:\s*$)")
# a code span on a prose line
_CODE_SPAN = re.compile(r"`[^`]*`")
# waiver: fence languages whose body the shell runs
_SHELL_FENCES = frozenset(("bash", "sh", "shell", "zsh", "console"))
# waiver: documentation written for a person, who may well be told to run `sh -c "<command>"`
_HELP_DIR = "/help/"
# waiver: fence languages that are programs, not examples, inside a runnable artifact
_PROGRAM_FENCES = frozenset(("python", "py", "python3", "javascript", "js", "node", "typescript", "ts"))
# waiver: path segments of the artifacts an agent executes step by step
_RUNNABLE_DIRS = ("/skills/", "/commands/")
# waiver: markdown fence marker and the Claude Code tool-call spelling
_FENCE, _BASH_CALL = "```", "Bash("
# waiver: markdown suffix; the sibling scanner also reads YAML and shell, which are code on disk
_MARKDOWN = ".md"
# waiver: finding kinds, part of the JSON report the doctor skill and the test read
_KIND_INTERP, _KIND_SHELL, _KIND_FENCE = "interpreter", "shell-script", "code-fence"


def _is_inline_at(line: str, *, fenced: bool) -> bool:
  """
  Report whether a line hands an interpreter its program inline.

  Args:
    line: One markdown line, without its trailing newline.
    fenced: Whether the line lies inside a fenced block.

  Returns:
    True when a code-context match starts an inline program.
  """
  # both spellings of an inline program are tried; the first hit that sits in code settles it
  for pattern in (_INLINE, _HEREDOC):
    for hit in pattern.finditer(line):
      # guard: a hit in code context is an inline program — the line is settled
      if _in_code(line, hit.start(), fenced):
        return True

  # every hit sat in prose
  return False


def _is_shell_script_at(line: str, fence_lang: str | None) -> bool:
  """
  Report whether a line carries shell control flow in a runnable shell context.

  Args:
    line: One markdown line, without its trailing newline.
    fence_lang: Language of the enclosing fence, or `None` outside one.

  Returns:
    True when a shell-only keyword sits in command position in a shell fence, when an untyped
    fence line opens a shell construct, or when the keyword sits inside a code span or an open
    `Bash(` call outside a fence or inside an untyped fence.
  """
  # a shell-typed fence is a script, so any keyword in command position counts
  if fence_lang in _SHELL_FENCES:
    return bool(_SHELL_KEYWORD.search(line))

  # guard: a fence of another language is not shell
  if fence_lang:
    return False

  # guard: an untyped fence line that opens a shell construct is a script line
  if fence_lang == "" and _SHELL_LINE.search(line):
    return True

  # outside a fence or in an untyped fence, the keyword must sit inside a code span or an open `Bash(` call
  return any(_is_in_call(line, hit.end()) for hit in _SHELL_KEYWORD.finditer(line))


def _is_in_call(line: str, pos: int) -> bool:
  """
  Report whether a position on a line lies inside an unclosed `Bash(` call or a code span.

  Args:
    line: One markdown line, without its trailing newline.
    pos: Offset to test.

  Returns:
    True inside the parentheses of a `Bash(` call that has not closed before `pos`, or inside a
    backtick span.
  """
  # guard: a code span is code wherever it sits
  if any(span.start() < pos < span.end() for span in _CODE_SPAN.finditer(line)):
    return True

  # guard: no call opened before the position means prose
  if (opened := line.rfind(_BASH_CALL, 0, pos)) < 0:
    return False

  # the call is still open at the position when no more parentheses closed than opened since it
  inside = line[opened + len(_BASH_CALL):pos]
  return inside.count("(") >= inside.count(")")


def _scan_text(path: Path, text: str) -> list[dict[str, str | int]]:
  """
  Report every place in one file that embeds executable code.

  Args:
    path: File the text came from, echoed into each finding.
    text: The file's content.

  Returns:
    Findings in line order; empty when the file is clean.
  """
  # the walk's state: the report, whether the file is one an agent runs, and the fence it is inside
  out: list[dict[str, str | int]] = []
  runnable = any(part in f"/{path.as_posix()}" for part in _RUNNABLE_DIRS)
  fence_lang: str | None = None
  fence_reported = False

  # one appender for every finding, so the report keeps a single row shape
  def add(number: int, kind: str, line: str) -> None:
    # waiver: JSON report keys
    out.append({ "path": str(path), "line": number, "kind": kind, "text": line.strip() })

  # walk the file once, tracking the fence the line sits in and whether it was reported already
  for number, line in enumerate(text.splitlines(), 1):
    stripped = line.strip()

    # a fence line opens or closes a block; a program fence in a runnable artifact is a finding
    if stripped.startswith(_FENCE):
      # an opening fence names the block's language, and a program fence is reported at once
      if fence_lang is None:
        fence_lang = stripped[len(_FENCE):].strip().lower()
        fence_reported = runnable and fence_lang in _PROGRAM_FENCES
        if fence_reported:
          add(number, _KIND_FENCE, line)
      # a closing fence leaves the block, and the next block starts unreported
      else:
        fence_lang, fence_reported = None, False
      continue

    # an inline program is reported on the line that starts it
    if _is_inline_at(line, fenced = fence_lang is not None):
      add(number, _KIND_INTERP, line)
      fence_reported = fence_lang is not None
      continue

    # shell control flow is reported once per fenced block, and per line outside a fence
    if not fence_reported and _is_shell_script_at(line, fence_lang):
      add(number, _KIND_SHELL, line)
      fence_reported = fence_lang is not None

  # the file's findings in line order
  return out


def scan(root: Path, *, dev: bool = False) -> list[dict[str, str | int]]:
  """
  Scan a repo's markdown instructions for embedded executable code.

  Guarantees:
    - Only markdown files are read; YAML and shell files are code on disk.
    - Paths in the report are relative to `root`, in path order.
    - The report is empty exactly when no scanned markdown carries a program of its own.

  Args:
    root: Repository root the scanned paths are relative to.
    dev: Whether to include the plugin sources under `plugins/claude/*/`.

  Returns:
    The findings described in the module docstring.
  """

  # Contract:
  # Only markdown files are read; YAML and shell files are code on disk. Paths in the report are
  # relative to the root, in path order. The report is empty exactly when no scanned markdown
  # carries a program of its own; the repo test and the doctor check both rely on that reading.

  # walk every candidate, keeping only the markdown an agent reads as instructions
  out: list[dict[str, str | int]] = []
  for path in _candidates(root, dev):
    # guard: shell and YAML sources are code that lives on disk, which is the allowed form, and a
    # help page instructs a person, not the agent
    if path.suffix != _MARKDOWN or _HELP_DIR in f"/{path.relative_to(root).as_posix()}":
      continue

    # the file's findings join the report under its repo-relative path
    # waiver: stdlib encoding idiom
    out += _scan_text(path.relative_to(root), path.read_text(encoding = "utf-8", errors = "replace"))

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
  parser = argparse.ArgumentParser(prog = "inline_code_scan.py")
  # waiver: argparse surface strings, not reusable domain keys
  parser.add_argument("repo", help = "repo root to scan")
  # waiver: argparse surface strings, not reusable domain keys
  parser.add_argument("--dev", action = "store_true", help = "also scan plugin sources under plugins/claude/*/")
  args = parser.parse_args(argv)

  # guard: a repo path that is not a directory is a usage error, not an empty report
  if not (repo := Path(args.repo).resolve()).is_dir():
    print(f"error: not a directory: {repo}", file = sys.stderr)
    return 2

  # emit the report the doctor skill and the repo test read
  print(json.dumps(scan(repo, dev = args.dev), indent = 2, ensure_ascii = False))
  return 0


if __name__ == "__main__":
  sys.exit(main())
