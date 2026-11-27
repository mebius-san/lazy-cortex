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
from pathlib import Path, PurePosixPath

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
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
# The `spec` section key naming the content root folder, and the folder used when it names none.
_VAULT_ROOT_KEY = "vault_root"
_DEFAULT_VAULT_ROOT = "specs"
# The path segment that climbs to the parent directory.
_PARENT_SEGMENT = ".."


# waiver: `spec_cfg` is the raw `spec` value of operator-edited JSON and may be any JSON value; the body narrows it
def spec_content_root(settings_root: Path, spec_cfg: object) -> Path:
  """
  Name the spec content root of a repository.

  Guarantees:
    - A `vault_root` that is absolute, climbs out of the repository through a `..` segment, or names the repository
      root itself always raises `SettingsReadError` and is never replaced by the default content root.
    - Only an absent, blank or non-string `vault_root` yields the default content root.

  Args:
    settings_root: The repository root that holds `.claude/lazy.settings.json`.
    spec_cfg: The merged `spec` settings section; anything that is not a mapping reads as an empty section.

  Returns:
    The content root: the section's `vault_root` under the repository root, or `specs` when it is absent, blank or
    not a string.

  Raises:
    SettingsReadError: When `vault_root` is an absolute path, climbs out through a `..` segment, or names the
      repository root itself.
  """

  # Contract:
  # A `vault_root` that is absolute, climbs out of the repository through a `..` segment, or names the repository
  # root itself MUST raise `SettingsReadError`; it is NEVER replaced by the default content root. Only an absent,
  # blank or non-string value yields the default content root.

  # Domain(spec.config):
  # # The spec catalog root is refused, never defaulted, when it leaves its sub-directory
  # The spec catalog occupies a named sub-directory of the repository, never the repository root itself and never
  # a place outside it. A configured location that points at the repository root, at an absolute location, or
  # climbs out of the repository is refused; it is never silently replaced by the default location, because
  # every automatic step would then act on a tree the operator did not set up as the catalog. Only a location
  # that is absent, blank or not text names no choice at all, and the default location is used.

  # the configured `vault_root`, none when the section is not a mapping
  vault_root = spec_cfg.get(_VAULT_ROOT_KEY) if isinstance(spec_cfg, dict) else None

  # guard: no usable value names the default folder
  if not isinstance(vault_root, str) or not vault_root:
    return settings_root / _DEFAULT_VAULT_ROOT

  # the configured value read as a relative POSIX path
  rel = PurePosixPath(vault_root)

  # guard: a root at an absolute place, above the repository, or at the repository root itself is refused, never
  # replaced by the default folder
  if rel.is_absolute() or _PARENT_SEGMENT in rel.parts or not rel.parts:
    raise SettingsReadError(
        f"spec.{_VAULT_ROOT_KEY} {vault_root!r} must name a sub-directory of {settings_root}"
    )
  return settings_root / rel.as_posix()


def query_settings_root_for(file_path: Path) -> Path:
  """
  Return the directory whose `.claude/lazy.settings.json` configures a document.

  Args:
    file_path: The document; the search starts at its folder.

  Returns:
    The nearest directory from the document's folder upward holding `.claude/lazy.settings.json`, never above the
    checkout the document sits in; the checkout's root when none holds it, the folder itself outside git.
  """
  # the nearest settings root within the document's checkout, else the checkout's root
  return _review_locator.query_settings_root(file_path.parent)


def read_merged_sections(repo: Path, *sections: str) -> dict[str, dict]:
  """
  Read settings sections of `repo` as core sees them: tracked file with the local overlay merged on.

  Guarantees:
    - Every requested section is a key of the result, each value the merged view core's own readers see,
      so a value set only in `.claude/lazy.settings.local.json` is never dropped.
    - A failed read raises and never yields an empty section.

  Args:
    repo: Directory holding the `.claude/lazy.settings.json` that is read.
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
  cli = _git_ops.require_core_cli(repo)

  # one verb call per section; each prints that section's merged view as a JSON object
  merged: dict[str, dict] = {}
  for section in sections:
    proc = subprocess.run(
        [ sys.executable, str(cli), CoreCommand.SETTINGS_GET, section, _SCOPE_FLAG, _MERGED_SCOPE, _CWD_FLAG,
          str(repo) ],
        capture_output = True, text = True, check = False, encoding = "utf-8",
        # waiver: stdlib decode-error mode, not a domain constant
        errors = "replace",
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
