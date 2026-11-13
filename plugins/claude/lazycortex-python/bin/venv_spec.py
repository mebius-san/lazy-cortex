from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class VenvSpec:
  """
  The environment a project's `pyproject.toml` asks for, as the checker venv must carry it.

  Responsibilities:
    - Name the project's dependency groups and the package-installer arguments that bring a venv to
      the project's requirements plus the checker tools.
    - Fingerprint the requirement inputs and record or compare that fingerprint inside a venv.

  Guarantees:
    - A project without `pyproject.toml` reads as one declaring no requirements.

  Attributes:
    project_dir: Root directory of the project.
    pyproject: Path of the project's `pyproject.toml`.
    data: Parsed `pyproject.toml` content.
  """

  TOOLS: tuple[str, ...] = ("mypy", "pylint", "pytest", "pytest-clarity", "pytest-sugar", "ruff")
  STAMP_NAME = ".lazy-python-cfg"

  def __init__(self, *, project_dir: Path) -> None:
    """
    Read the project's `pyproject.toml`.

    Args:
      project_dir: Root directory of the project.

    Raises:
      tomllib.TOMLDecodeError: The project's `pyproject.toml` is not valid TOML.
    """
    self.project_dir: Path = project_dir
    self.pyproject: Path = project_dir / "pyproject.toml"
    self.data: dict = tomllib.loads(self.pyproject.read_text(encoding = "utf-8")) if self.pyproject.is_file() else {}

  @property
  def project(self) -> dict | None:
    """
    The `[project]` table, or `None` when the file declares none.
    """
    table = self.data.get("project")
    return table if isinstance(table, dict) else None

  def group_names(self) -> list[str]:
    """
    Name every dependency group the project declares.

    Returns:
      The group names in declaration order; empty when the project declares no group.
    """
    groups = self.data.get("dependency-groups")

    # guard: no `[dependency-groups]` table means no group to install
    if not isinstance(groups, dict):
      return []
    return list(groups)

  def install_args(self) -> list[str]:
    """
    Build the package-installer arguments that bring a venv to the project's requirements.

    Returns:
      Requirement arguments for the project's dependencies, every extra and every dependency group,
      followed by the checker tools.
    """
    args: list[str] = []

    # the project's own dependencies and all its extras, only when a `[project]` table declares them
    if self.project is not None:
      args += [ "-r", str(self.pyproject), "--all-extras" ]

    # every dependency group by name, since the installer has no switch selecting them all
    for name in self.group_names():
      args += [ "--group", f"{self.pyproject}:{name}" ]

    # the checker tools ride on top of whatever the project asks for
    return args + list(self.TOOLS)

  def digest(self) -> str:
    """
    Fingerprint the inputs that decide what the venv must carry.

    Returns:
      A hex digest that changes exactly when one of those inputs changes.
    """

    # Domain(install.reconciliation):
    # # Venv freshness inputs
    # A configured environment stays current until one of the inputs that decide its content
    # changes: the project's supported Python range, its dependencies, its optional extras, its
    # dependency groups, a pinned Python version file beside the project, and the list of checker
    # tools added on top. Any other edit to the project file — a tool's own settings, metadata,
    # build configuration — leaves the environment current, so it is never rebuilt for a change
    # that cannot alter what it holds.

    project = self.project or {}
    version_file = self.project_dir / ".python-version"
    inputs = {
      "requires-python": project.get("requires-python"),
      "dependencies": project.get("dependencies", []),
      "optional-dependencies": project.get("optional-dependencies", {}),
      "dependency-groups": self.data.get("dependency-groups", {}),
      "python-version": version_file.read_text(encoding = "utf-8").strip() if version_file.is_file() else None,
      "tools": list(self.TOOLS),
    }

    # a canonical serialisation, so equal inputs always hash alike
    canonical = json.dumps(inputs, sort_keys = True, separators = (",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

  def is_fresh(self, venv: Path) -> bool:
    """
    Tell whether a venv was configured against the project's current requirement inputs.

    Args:
      venv: Root directory of the venv.

    Returns:
      `True` when the venv's recorded fingerprint matches the current one; `False` when it differs
      or the venv carries none.
    """
    stamp = venv / self.STAMP_NAME

    # guard: a venv never configured by this tool carries no fingerprint and counts as stale
    if not stamp.is_file():
      return False
    return stamp.read_text(encoding = "utf-8").strip() == self.digest()

  def write_stamp(self, venv: Path) -> None:
    """
    Record the current requirement fingerprint inside a venv.

    Notes:
      - Replaces any fingerprint the venv already carries.

    Args:
      venv: Root directory of the venv.
    """
    (venv / self.STAMP_NAME).write_text(self.digest() + "\n", encoding = "utf-8")


def main() -> int:
  """
  Run the venv-spec command line against a project.

  Notes:
    - `install-args` prints one installer argument per line, `fresh` prints `fresh` or `stale`, and `stamp`
      prints nothing.
    - `fresh` and `stamp` require the venv directory argument.

  Returns:
    0 on success, 1 when the project's `pyproject.toml` cannot be read.
  """

  # the command line: one command, the project root, and the venv for the venv-bound commands
  parser = argparse.ArgumentParser(description = "Read a project's venv requirements from pyproject.toml.")
  parser.add_argument("command", choices = ("install-args", "fresh", "stamp"))
  parser.add_argument("project_dir", type = Path)
  parser.add_argument("venv", type = Path, nargs = "?")
  options = parser.parse_args()

  # guard: the venv-bound commands cannot run without a venv to read or write
  if options.command != "install-args" and options.venv is None:
    parser.error(f"{options.command} needs a venv directory")

  # guard: an unreadable pyproject.toml must stop the run, never read as one without requirements
  try:
    spec = VenvSpec(project_dir = options.project_dir)
  except tomllib.TOMLDecodeError as exc:
    print(f"[lazy-python] {options.project_dir / 'pyproject.toml'} is not valid TOML: {exc}", file = sys.stderr)
    return 1

  # dispatch the command
  if options.command == "install-args":
    print("\n".join(spec.install_args()))
  elif options.command == "fresh":
    print("fresh" if spec.is_fresh(options.venv) else "stale")
  else:
    spec.write_stamp(options.venv)
  return 0


if __name__ == "__main__":
  sys.exit(main())
