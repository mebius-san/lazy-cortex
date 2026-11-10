"""
Logic behind the `lazycortex-specs migrate-requests` verb — removes the retired `experts=` field from the
`spawn-product` decision lines of every open spec request.

A `spawn-product` decision once named the role experts of the product it registers; that field was retired, and an
open request still carrying it fails its apply transition. This verb removes exactly that field from each such line,
leaving every other byte of the request as it was, and reports which requests it changed. A closed request is never
touched. It never commits.
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
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from apply_request import _K, parse_frontmatter  # noqa: E402


# The `request_status` values that close a request: an accepted or rejected request is final and never rewritten.
# ref: apply_request.py — `ApplyRequest.run`, terminal-state skip
_CLOSED_STATUSES = frozenset({ _K.STATUS_ACCEPTED, _K.STATUS_REJECTED })

# The body's `# Routing` section: its heading line, then everything up to the next H1 or the end of the body.
# ref: apply_request.py — `_parse_routing`
_ROUTING_RE = re.compile(rf"(?ms)^{re.escape(_K.ROUTING_H1)}\s*$(.*?)(?=^# \S|\Z)")

# The decision block inside that section: the text between the first block opener and the next comment closer.
# ref: apply_request.py — `_extract_decision_block`
_DECISION_RE = re.compile(
    rf"(?s){re.escape(_K.ROUTING_DECISION_OPEN)}\s*(.*?)\s*{re.escape(_K.ROUTING_DECISION_CLOSE)}")

# The retired field with the blank run ahead of it; the field always follows the verb, so a blank always precedes it.
_EXPERTS_FIELD_RE = re.compile(r"[ \t]+experts=\S*")

_LF = "\n"
_MD_SUFFIX = ".md"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The exit code of a run that failed to read or write the catalog, never an answer `--check` gives.
_EXIT_FAILED = 2

# The result's own wire-shape keys, read by the migration step and the tests.
_CHANGED_KEY = "changed"
_SKIPPED_KEY = "skipped"


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Remove the retired `experts=` field from the `spawn-product` decision lines of every open spec request.

  Guarantees:
    - Only the `experts=` field and the blanks ahead of it leave a `spawn-product` line of a request's routing
      decision; every other byte of the request stays, and a request with nothing to change is not written.
    - A closed request is never written.
    - A dry run writes nothing.
    - A second run over the result changes nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    `{"changed", "skipped"}` — the requests rewritten and the requests already current or closed, each a list of
    paths relative to the settings root, in file-name order.

  Raises:
    OSError: When a request cannot be read or written.
    ValueError: When the settings file or a request cannot be decoded.
  """

  # Contract:
  # Only the `experts=` field of a `spawn-product` decision line, with the blanks ahead of it, leaves an open request;
  # every other byte MUST stay. A closed request MUST never be written. A dry run MUST write no file, and running the
  # verb again over its own output MUST change nothing.

  settings_root = spec_paths.find_settings_root(repo)
  requests_dir = spec_paths.spec_content_root(settings_root) / _K.REQUESTS_DIR
  result: dict = { _CHANGED_KEY: [], _SKIPPED_KEY: [] }

  # guard: a catalog without a requests folder holds no request
  if not requests_dir.is_dir():
    return result

  # every request file of the folder, its folder-note aside, in a stable order
  for name in sorted(os.listdir(requests_dir)):

    # guard: only markdown files other than the folder-note are requests
    if not name.endswith(_MD_SUFFIX) or name == _K.REQUESTS_NOTE:
      continue

    # the request's text and its status, read once for every check below
    request = requests_dir / name
    text = spec_paths.read_text(request)
    fm_values, fm_end = parse_frontmatter(text)

    # a closed request keeps every byte; an open one loses the retired field from its body's decision lines
    new_text = text if fm_values.get(_K.REQUEST_STATUS) in _CLOSED_STATUSES else _drop_experts(text, fm_end)

    # a request with nothing to change is reported skipped and goes unwritten
    rel = request.relative_to(settings_root).as_posix()
    if new_text == text:
      result[_SKIPPED_KEY].append(rel)
      continue

    # a changed request is reported, and written unless the run is dry
    result[_CHANGED_KEY].append(rel)
    if not dry_run:
      spec_paths.write_text_atomic(request, new_text)

  # both lists in file-name order
  return result


def _drop_experts(text: str, body_start: int) -> str:
  """
  Remove the `experts=` field from every `spawn-product` line of a request's routing decision.

  Args:
    text: The full request text.
    body_start: The offset where the body begins, right after the frontmatter; 0 when there is none.

  Returns:
    The request text without those fields; unchanged when the routing decision carries none. The frontmatter is never
    searched.
  """

  # guard: a request whose body has no routing section carries no decision
  if (routing := _ROUTING_RE.search(text, body_start)) is None:
    return text

  # guard: a routing section without a decision block carries no decision line
  if (decision := _DECISION_RE.search(text, routing.start(1), routing.end(1))) is None:
    return text

  # only the block's own lines are rewritten, everything around them is carried over
  lines = [ _drop_line_experts(line) for line in decision.group(1).split(_LF) ]
  return text[:decision.start(1)] + _LF.join(lines) + text[decision.end(1):]


def _drop_line_experts(line: str) -> str:
  """
  Remove the `experts=` field from one decision line when it is a `spawn-product` line.

  Args:
    line: One line of the decision block, without its line ending.

  Returns:
    The line with the field gone from the part ahead of its description separator; unchanged when the line is not a
    `spawn-product` decision, one whose first word is the verb and which carries the description separator.
  """
  head, sep, tail = line.partition(_K.DECISION_DESC_SEP)
  tokens = head.split()

  # guard: only a line opening with the `spawn-product` verb and carrying the description separator is a decision
  # ref: apply_request.py — `_parse_spawn_product_targets`
  if not tokens or tokens[0].lower() != _K.DECISION_VERB_SPAWN_PRODUCT or not sep:
    return line

  # the description after the separator is free text and keeps every byte
  return _EXPERTS_FIELD_RE.sub("", head) + sep + tail


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when at least one request would change, 1 when none would.
    - Any failure of the migration exits 2 under every flag and prints no result, never an answer `--check` gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names the
      repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: with `--check`, 0 when a request would change and 1 when none would; 0 otherwise; 2 when the
    migration failed.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed; also told apart from both `--check` answers.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when at least one request would change, 1 when none would;
  # any failure of the migration MUST exit 2, so a migration step's `applies_when` predicate never reads a failure as
  # an answer.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-requests")
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
    sys.stderr.write(f"migrate-requests: {error!r}\n")
    return _EXIT_FAILED

  # the result is printed only once the migration finished
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 0 if result[_CHANGED_KEY] else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
