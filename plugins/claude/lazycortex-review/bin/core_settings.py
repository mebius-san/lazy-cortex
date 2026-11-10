"""
Review's one reader of the consumer's settings: the merged view, through the core CLI.

Core and the expert pump read every section as the tracked `.claude/lazy.settings.json` with the
gitignored `.claude/lazy.settings.local.json` overlay deep-merged onto it. Review must see the same
view — an expert whose `git_author` lives only in the overlay commits under that identity, and a
reader of the tracked file alone would take its commits for an operator's. Every settings read in
this plugin therefore goes through `lazycortex-core settings-get <section> --scope merged`, never
through a parse of the file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from errors import SettingsReadError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import CoreCommand  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The core `settings-get` flag that selects which settings layer is read.
_SCOPE_FLAG = "--scope"
# The `settings-get` scope that reads the tracked settings with the local overlay merged on.
_MERGED_SCOPE = "merged"
# The core `settings-get` flag that names the repository whose settings are read.
_CWD_FLAG = "--cwd"


def read_merged_sections(repo: Path, *sections: str) -> dict[str, dict]:
  """
  Read settings sections of `repo` as core sees them: tracked file with the local overlay merged on.

  Guarantees:
    - Every requested section is a key of the result, each value the merged view core's own readers see,
      so a value set only in `.claude/lazy.settings.local.json` is never dropped.
    - A failed read raises and never yields an empty section.

  Args:
    repo: Repository root whose settings are read.
    *sections: Names of the top-level settings sections to read.

  Returns:
    Mapping of each section name to its merged section dict.

  Raises:
    RuntimeError: When no core CLI is resolvable.
    SettingsReadError: When core cannot read a section — a settings layer that is not valid JSON.
  """

  # Contract:
  # The result MUST carry every requested section, each the merged view core's own readers see —
  # an overlay-only value is never dropped — and a failed read MUST raise, never yield an empty section.

  # no core CLI reachable raises — review cannot know the identities or classes core works with
  cli = _git_ops.require_core_cli()

  # one verb call per section; each prints that section's merged view as a JSON object
  merged: dict[str, dict] = {}
  for section in sections:
    proc = subprocess.run(
        [ sys.executable, str(cli), CoreCommand.SETTINGS_GET, section, _SCOPE_FLAG, _MERGED_SCOPE, _CWD_FLAG,
          str(repo) ],
        capture_output = True, text = True, check = False, encoding = "utf-8",
    )

    # guard: the verb failed — a broken settings layer must not pass for an empty one
    if proc.returncode != 0:
      raise SettingsReadError(
          f"{CoreCommand.SETTINGS_GET} {section} failed in {repo}: {proc.stderr.strip() or proc.stdout.strip()}"
      )

    # guard: the verb printed no JSON — an unreadable answer must not pass for an empty section
    try:
      value = json.loads(proc.stdout)
    except json.JSONDecodeError as error:
      raise SettingsReadError(f"{CoreCommand.SETTINGS_GET} {section} printed no JSON in {repo}") from error

    # guard: a whole-section read always prints an object; anything else is a broken wire
    if not isinstance(value, dict):
      raise SettingsReadError(f"{CoreCommand.SETTINGS_GET} {section} printed a non-object in {repo}")

    # the section's merged view joins the result under its own name
    merged[section] = value
  return merged
