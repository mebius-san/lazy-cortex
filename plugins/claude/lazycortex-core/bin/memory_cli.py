"""
Memory-reflection dispatch verb for the `lazycortex-core` CLI.

This module backs `memory-reflect <expert>`, the call the `lazy-memory.reflect` skill makes
to queue one `kind = reflect` job for a persona-marked expert. The job's request names the
expert's recent run logs under `.logs/claude/<expert>/` and every memory note under
`.memory/<expert>/`; the bundle itself is queued through the runtime like any other job.

An expert without the persona aspect prints `not-persona` and exits 1 before anything is
queued. The repository root follows the dispatcher convention — `LAZY_REPO_ROOT`, then the
process working directory, overridable per call with `--cwd`.
"""
from __future__ import annotations

import argparse
import json
import time

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import JobConfigKey  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from expert_runtime import dispatch_job, lookup_expert  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from provider_env import ProviderConfigError  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# waiver: the aspect reference that marks an expert as persona-bearing, fixed by the lazy-memory contract
PERSONA_ASPECT = "lazycortex-core:lazy-memory.persona-aspect"
# waiver: run-log and memory-note roots, fixed by the lazy-log / lazy-memory layout, not domain keys
_LOG_ROOT = ".logs/claude"
# waiver: run-log and memory-note roots, fixed by the lazy-log / lazy-memory layout, not domain keys
_MEMORY_ROOT = ".memory"
# waiver: the reflect request wording the persona aspect answers to, not a reusable domain key
_REFLECT_REQUEST = (
  "Consolidate recent runs into memory per lazy-memory.persona-aspect §Obligations. "
  "On finding patterns worth retaining, call /lazy-memory.write. On finding nothing "
  "new, return outcome=empty."
)
_DEFAULT_DAYS = 30
_SECONDS_PER_DAY = 86400
# waiver: the outcome word the reflect skill branches on, not a reusable domain key
NOT_PERSONA = "not-persona"
# waiver: markdown suffix of run logs and memory notes, a file-format literal
_MARKDOWN_SUFFIX = ".md"


def _find_all_markdown_files(root: Path, *, newer_than: float | None = None) -> list[Path]:
  """
  List the markdown files directly under a directory, in name order.

  Args:
    root: Directory to list; a missing one yields nothing.
    newer_than: When set, only files modified at or after this epoch time are kept.

  Returns:
    The matching file paths.
  """
  # guard: an expert that never ran or never wrote a note has no directory yet
  if not root.is_dir():
    return []

  # keep the markdown files in name order, dropping the ones older than the cutoff when one is set
  return [
    path for path in sorted(root.iterdir())
    if path.is_file() and path.suffix == _MARKDOWN_SUFFIX
    and (newer_than is None or path.stat().st_mtime >= newer_than)
  ]


def build_reflect_payload(repo: Path, expert: str, *, days: int) -> dict[str, object]:
  """
  Compose the request body of a reflect job for one expert.

  Guarantees:
    - The source list names the run logs modified inside the day window first, then every memory
      note regardless of age, each with the fixed description the persona aspect reads.

  Args:
    repo: Absolute repository root.
    expert: Expert name as registered in `lazy.settings.json[experts]`.
    days: Age window in days for run logs; memory notes are included regardless of age.

  Returns:
    The `request.json` body: kind, role, the reflect instruction, and a `source` list of
    `{path, description}` entries naming recent run logs and current memory notes.
  """

  # Contract:
  # The source list names the run logs modified inside the day window first, then every memory
  # note regardless of age, each with the fixed description the persona aspect reads to tell the
  # two kinds apart.

  # recent run logs first, then every memory note — the order the reflect instruction reads them in
  sources = [
    # waiver: request-body keys and descriptions read by the reflect aspect, not reusable domain keys
    *({ "path": str(path), "description": "recent run log" }
      for path in _find_all_markdown_files(
        repo / _LOG_ROOT / expert, newer_than = time.time() - days * _SECONDS_PER_DAY,
      )),
    # waiver: request-body keys and descriptions read by the reflect aspect, not reusable domain keys
    *({ "path": str(path), "description": "current memory note" }
      for path in _find_all_markdown_files(repo / _MEMORY_ROOT / expert)),
  ]
  # waiver: request-body keys read by the reflect aspect, not reusable domain keys
  return { "kind": "reflect", "role": "reflect", "request": _REFLECT_REQUEST, "source": sources }


def is_persona(repo: Path, expert: str) -> bool:
  """
  Report whether an expert carries the persona aspect.

  Args:
    repo: Absolute repository root.
    expert: Expert name as registered in `lazy.settings.json[experts]`.

  Returns:
    True when the expert is registered and its `aspects` list names the persona aspect.
  """
  return PERSONA_ASPECT in ((lookup_expert(repo, expert) or {}).get(JobConfigKey.ASPECTS) or [])


def cmd_memory_reflect(argv: list[str]) -> int:
  """
  Run the `memory-reflect` subcommand: queue one reflect job and print the dispatch result.

  Args:
    argv: Argument vector after the subcommand name (expert plus optional `--days`, `--cwd`).

  Returns:
    Process exit code: 0 on success (prints the dispatch result JSON), 1 when the expert is
    not persona-marked (prints `not-persona`) or its configuration refuses the dispatch
    (prints an error JSON).

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the expert name, the run-log window, and the repo-root override
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core memory-reflect")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("expert")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--days", type = int, default = _DEFAULT_DAYS, help = "run-log window in days")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)
  repo = resolve_repo_root(args.cwd)

  # guard: only a persona-marked expert has memory to consolidate — the skill branches on this word
  if not is_persona(repo, args.expert):
    print(NOT_PERSONA)
    return 1

  # queue the job through the runtime's own primitive and print its result; a refused dispatch is
  # reported as an error JSON instead
  try:
    print(json.dumps(dispatch_job(repo, args.expert, build_reflect_payload(repo, args.expert, days = args.days))))
  except (ProviderConfigError, ValueError) as error:
    print(json.dumps({ "error": str(error) }))
    return 1

  # the dispatch result on stdout is the success signal the skill reads
  return 0
