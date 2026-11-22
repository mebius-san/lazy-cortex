#!/usr/bin/env python3

"""
Expert class and role listing for the lazycortex-experts plugin.

Backs the `list-classes` verb, which `lazy-experts.install` calls to learn which expert classes and roles a plugin
root ships.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The plugin root this module ships in, the default root the verb lists.
_OWN_ROOT = Path(__file__).resolve().parent.parent

# The directories of a plugin root holding the aspects and the agents.
_REFERENCES_DIR = "references"
_AGENTS_DIR = "agents"

# The filename shape of an aspect and of an agent, and the affixes stripped to get a key.
_ASPECT_PATTERN = "lazy-experts.*-aspect.md"
_AGENT_PATTERN = "lazy-experts.*.md"
_PREFIX = "lazy-experts."
_ASPECT_SUFFIX = "-aspect.md"
_AGENT_SUFFIX = ".md"

# The aspects composed onto experts of every class, never a class of their own.
CROSS_CUTTING = frozenset({ "discipline", "research", "tech-writing", "terms", "structure" })

# The answer's wire-shape keys and outcomes.
_OUTCOME_KEY = "outcome"
_CLASSES_KEY = "classes"
_ROLES_KEY = "roles"
_MISSING_KEY = "missing"
_OUTCOME_OK = "ok"
_OUTCOME_INCOMPLETE = "plugin-cache-incomplete"

# The exit code of a plugin root with no class or no role.
_EXIT_INCOMPLETE = 1


def _find_all_keys(directory: Path, pattern: str, suffix: str) -> list[str]:
  """
  List the keys of the files in one directory that match a filename pattern.

  Args:
    directory: Directory to list; absent yields no key.
    pattern: Filename pattern a file must match.
    suffix: Suffix stripped from a matching filename, after the plugin prefix.

  Returns:
    The keys, sorted.
  """
  # guard: an absent directory ships nothing
  if not directory.is_dir():
    return []

  # flat listing: only regular files directly in the directory count
  return sorted(
      name[len(_PREFIX):-len(suffix)]
      for name in os.listdir(directory)
      if fnmatch.fnmatch(name, pattern) and (directory / name).is_file()
  )


def read_classes(root: Path) -> dict[str, str | list[str]]:
  """
  List the expert classes and roles one plugin root ships.

  Guarantees:
    - A cross-cutting aspect is never listed as a class.
    - A root with no class or no role is answered `plugin-cache-incomplete`, naming the first empty directory,
      the references before the agents.

  Args:
    root: The plugin root.

  Returns:
    The `ok` answer with sorted `classes` and `roles`, or the `plugin-cache-incomplete` answer naming the first
    directory that yielded nothing.
  """

  # Contract:
  # A cross-cutting aspect is never listed as a class.

  # Contract:
  # A root with no class or no role is answered `plugin-cache-incomplete`, never `ok`, and the answer names
  # the first empty directory, the references before the agents.

  references = root / _REFERENCES_DIR
  agents = root / _AGENTS_DIR

  # Domain(experts.composition):
  # # Expert classes and cross-cutting aspects
  # An expert class is a domain aspect, such as a plugin-authoring or a fiction genre; every expert is composed from
  # one class. The cross-cutting aspects (discipline, research, tech-writing, terms, structure) compose onto experts
  # of every class and are never a class themselves. A plugin root that ships no class, or no role to seed experts
  # from, is an incomplete install and cannot be used to compose experts.

  # classes are the aspects that are not cross-cutting
  classes = [
      key for key in _find_all_keys(references, _ASPECT_PATTERN, _ASPECT_SUFFIX) if key not in CROSS_CUTTING
  ]

  # guard: no class means the references of the plugin root are missing or incomplete
  if not classes:
    return { _OUTCOME_KEY: _OUTCOME_INCOMPLETE, _MISSING_KEY: str(references) }

  # roles are the agent files the plugin root ships
  roles = _find_all_keys(agents, _AGENT_PATTERN, _AGENT_SUFFIX)

  # guard: no role means the agents of the plugin root are missing
  if not roles:
    return { _OUTCOME_KEY: _OUTCOME_INCOMPLETE, _MISSING_KEY: str(agents) }
  return { _OUTCOME_KEY: _OUTCOME_OK, _CLASSES_KEY: classes, _ROLES_KEY: roles }


def main(argv: list[str]) -> int:
  """
  Run the `list-classes` verb and print its answer as JSON.

  Args:
    argv: Arguments after the subcommand: an optional `--root <dir>`.

  Returns:
    0 for the `ok` answer, 1 for `plugin-cache-incomplete`.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-experts list-classes")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--root", type = Path, default = _OWN_ROOT)
  args = parser.parse_args(argv)

  # the answer goes to stdout whatever it is; the exit code tells the two apart
  answer = read_classes(args.root.resolve())
  print(json.dumps(answer))
  return 0 if answer[_OUTCOME_KEY] == _OUTCOME_OK else _EXIT_INCOMPLETE


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
