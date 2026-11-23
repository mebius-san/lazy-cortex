from __future__ import annotations

import argparse
import hashlib
import json
import os
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

  TOOLS: tuple[str, ...] = ("mypy", "pylint", "pytest", "pytest-clarity", "pytest-sugar", "pytest-xdist", "ruff")
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

  def target_venv(self) -> Path:
    """
    Name the venv the checker runners use for this project.

    Returns:
      `[tool.lazy-python].venv` with `~` expanded and a relative value resolved against the project root, or
      `<project>/.venv` when no venv is configured.
    """

    # Domain(install.reconciliation):
    # # Project venv location
    # A project's checker environment sits where the project's own configuration names it, a home-relative
    # or project-relative location resolved the way a shell reads it; a project that names none keeps it in
    # a conventional directory at its own root.

    # guard: nothing configured — the conventional venv at the project root
    if ( venv := self._configured_venv() ) is None:
      return self.project_dir / ".venv"

    # a relative value joins the project root
    return venv if venv.is_absolute() else self.project_dir / venv

  def _configured_venv(self) -> Path | None:
    """
    Read `[tool.lazy-python].venv` with `~` expanded.

    Returns:
      The configured venv path, relative when configured so, or `None` when the project configures none.
    """
    tool = self.data.get("tool")
    section = tool.get("lazy-python") if isinstance(tool, dict) else None
    configured = section.get("venv") if isinstance(section, dict) else None

    # guard: an absent, empty or non-string value configures nothing
    if not isinstance(configured, str) or not configured:
      return None
    return Path(configured).expanduser()

  def is_unreachable_from_worktrees(self) -> bool:
    """
    Tell whether the configured venv is a relative path that climbs out of the project root.

    Returns:
      `True` for such a venv, `False` otherwise.
    """

    # Domain(install.reconciliation):
    # # Venv out of reach of isolated job worktrees
    # A job's isolated working copy resolves a relative venv location against its own root, not the
    # operator's checkout. A relative location that climbs out of the checkout therefore names a different
    # place in every such copy, and since only paths inside the repository can be shared into a copy, no
    # sharing repairs it; only an absolute location reaches the same venv from everywhere.

    venv = self._configured_venv()
    return venv is not None and not venv.is_absolute() and self.worktree_link() is None

  def worktree_link(self) -> str | None:
    """
    Name the project venv by its project-relative path when it lies inside the project root.

    Returns:
      The venv's path relative to the project root in forward-slash form, or `None` when the venv lies outside it,
      which includes a relative venv that climbs out of the root.
    """
    # both sides are compared lexically, so a venv reached through a link inside the tree still counts as inside
    venv = Path(os.path.normpath(self.target_venv()))
    root = Path(os.path.normpath(self.project_dir))

    # a venv outside the root, or the root itself, is no path a checkout can carry
    if venv == root or not venv.is_relative_to(root):
      return None
    return venv.relative_to(root).as_posix()

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


def _print_worktree_reach(spec: VenvSpec) -> None:
  """
  Print the one line that names the venv path an isolated job worktree must carry, or why none can be carried.

  Notes:
    - Prints `worktree-link: <rel>` when the venv lies inside the project root, `<rel>` being its path relative to
      that root.
    - Prints `worktree-link-none: ...` for an absolute venv outside the repository, which every worktree reaches by
      the same path.
    - Prints `worktree-link-unreachable: ...` for a relative venv outside the repository, with the advice to name
      the venv by an absolute path.

  Args:
    spec: The project's venv requirements.
  """

  # Domain(install.reconciliation):
  # # Venv carried into isolated job worktrees
  # A job that runs in its own working copy finds there only what the repository tracks. A project venv
  # kept inside the checkout is therefore shared with every such copy by name; a venv at an absolute place
  # outside the checkout needs nothing, since each copy's own project file points at that same place. A
  # relative location that climbs out of the checkout lands elsewhere in every copy and cannot be shared,
  # so it is reported with the fix of naming the venv by an absolute path.

  # the venv's repo-relative path, or None when it lies outside the checkout
  link = spec.worktree_link()

  # a relative venv climbing out of the checkout names another place in every worktree, and no link can carry it
  if spec.is_unreachable_from_worktrees():
    print(f"worktree-link-unreachable: venv {spec.target_venv()} is a relative path outside the repository, which "
          "job worktrees resolve against their own root — make [tool.lazy-python].venv an absolute path")

  # an absolute venv outside the checkout is reached from every worktree by the path pyproject.toml names
  elif link is None:
    print(f"worktree-link-none: venv {spec.target_venv()} lies outside the repository")

  # the path the install skill hands to the core verb
  else:
    print(f"worktree-link: {link}")


def main() -> int:
  """
  Run the venv-spec command line against a project.

  Guarantees:
    - `worktree-link` prints exactly one line on stdout, whose prefix the install skill parses to decide whether to
      call the core `worktree-links-add` verb.
    - The prefix is `worktree-link: <rel>` for a venv inside the project root (`<rel>` its normalised repo-relative
      path), `worktree-link-none: ...` for an absolute venv outside it, or `worktree-link-unreachable: ...` for a
      relative venv outside it, each with exit code 0.
    - When `pyproject.toml` does not parse, `worktree-link` prints `worktree-link-failed: ...` on stdout, never on
      stderr, and exits with 1.

  Notes:
    - `install-args` prints one installer argument per line, `fresh` prints `fresh` or `stale`, `stamp` prints
      nothing, and `worktree-link` prints one line naming the venv path a job worktree must carry, or why none can
      be.
    - `fresh` and `stamp` require the venv directory argument; `worktree-link` takes none.
    - When `pyproject.toml` does not parse, `worktree-link` prints `worktree-link-failed: ...` on stdout, while the
      other commands print their message on stderr; both exit 1.

  Returns:
    0 on success, 1 when the project's `pyproject.toml` cannot be read.
  """

  # Contract:
  # The `worktree-link` command prints exactly one line on stdout, and the install skill parses its prefix to decide
  # whether to call the core `worktree-links-add` verb. The prefix is `worktree-link: <rel>` (venv inside the project
  # root, `<rel>` its normalised repo-relative path), `worktree-link-none: ...` (absolute venv outside the project
  # root) or `worktree-link-unreachable: ...` (relative venv outside the project root), each with exit code 0.
  # When `pyproject.toml` does not parse, the line is `worktree-link-failed: ...`, printed on stdout and never on
  # stderr, with exit code 1. These prefixes MUST NOT be renamed and the failure line MUST NEVER move to stderr.

  # the command line: one command, the project root, and the venv for the venv-bound commands
  parser = argparse.ArgumentParser(description = "Read a project's venv requirements from pyproject.toml.")
  parser.add_argument("command", choices = ("install-args", "fresh", "stamp", "worktree-link"))
  parser.add_argument("project_dir", type = Path)
  parser.add_argument("venv", type = Path, nargs = "?")
  options = parser.parse_args()

  # guard: the venv-bound commands cannot run without a venv to read or write
  if options.command in ( "fresh", "stamp" ) and options.venv is None:
    parser.error(f"{options.command} needs a venv directory")

  # guard: an unreadable pyproject.toml must stop the run, never read as one without requirements
  try:
    spec = VenvSpec(project_dir = options.project_dir.resolve())
  except tomllib.TOMLDecodeError as error:
    # the worktree-link answer is read from stdout, so its failure line goes there
    if options.command == "worktree-link":
      print(f"worktree-link-failed: pyproject.toml is not valid TOML: {error}")
    else:
      print(f"[lazy-python] {options.project_dir / 'pyproject.toml'} is not valid TOML: {error}", file = sys.stderr)
    return 1

  # dispatch the command
  if options.command == "install-args":
    print("\n".join(spec.install_args()))
  elif options.command == "fresh":
    print("fresh" if spec.is_fresh(options.venv) else "stale")
  elif options.command == "worktree-link":
    _print_worktree_reach(spec)
  else:
    spec.write_stamp(options.venv)
  return 0


if __name__ == "__main__":
  sys.exit(main())
