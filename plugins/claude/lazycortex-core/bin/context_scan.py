"""
Measure what a session loads into context and how heavy the memory and skill artifacts are.

Backs the `context-scan` verb: one section per call, reported as a single JSON document.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from frontmatter_parser import parse_frontmatter  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error
# waiver: the memory store's own note reader, private by name but shared by every memory primitive (reindex, write)
# pylint: disable-next=import-error
from memory_runtime import _read_note_frontmatter as read_note_frontmatter

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


# One kilobyte, the unit every threshold below is stated in.
_KB = 1024
# Always-loaded total: above the first is WARN, above the second FAIL.
_WEIGHT_WARN = 20 * _KB
_WEIGHT_FAIL = 40 * _KB
# A memory index above this size should be consolidated.
_INDEX_LIMIT = 5 * _KB
# A skill body over either limit is a delegation candidate by size.
_SKILL_LINES = 120
_SKILL_BYTES = 5 * _KB
# Two note titles within this edit distance are near-duplicates.
_TITLE_DISTANCE = 3
# Body phrases that show a skill already dispatches scans in parallel.
_PARALLEL_MARKERS = (
  'subagent_type: "Explore"', 'subagent_type: "general-purpose"', "in parallel", "dispatching-parallel-agents",
  "references/lazy-core.parallel-scan.md", "rules/lazy-core.parallel-scan.md", "multiple Agent tool calls",
)
# A frontmatter key that scopes a rule to on-demand loading.
_PATHS_KEY = "paths"
# The memory index file and the note-tag vocabulary.
_INDEX = "MEMORY.md"
_TAG_PREFIX = "memory/"
_TAGS_DIR = ".tags"
_MD = ".md"
# A markdown link target inside the memory index.
_LINK = re.compile(r"\]\(([^)\s]+)\)")
# Characters of a project path that the session key replaces with a dash.
_KEY_CHARS = re.compile(r"[^A-Za-z0-9]")
# Section names of the verb.
_SECTIONS = ( "weight", "memory-index", "expert-memory", "skill-size" )
# Severity words of the weight section.
_PASS, _WARN, _FAIL = "PASS", "WARN", "FAIL"



# ----------------------------------------------------------------------------------------
class _Layout:
  """
  Names of the files, directories and note fields that make up a session's context layout.
  """

  # The settings directory under a project root or the operator's home.
  CLAUDE_DIR = ".claude"
  # The instruction file a session always loads.
  CLAUDE_MD = "CLAUDE.md"
  # Subdirectories of the settings directory, by artifact kind.
  RULES = "rules"
  AGENTS = "agents"
  SKILLS = "skills"
  COMMANDS = "commands"
  # A skill's entry file.
  SKILL_MD = "SKILL.md"
  # The per-project session directory and its memory folder.
  PROJECTS = "projects"
  MEMORY = "memory"
  # The expert memory root under a project.
  EXPERT_MEMORY = ".memory"
  # The plugin-authoring tree of a repo that ships plugins.
  PLUGINS = ( "plugins", "claude" )
  # Frontmatter fields of a memory note.
  TITLE = "title"
  TAGS = "tags"



# ----------------------------------------------------------------------------------------
class _Field:
  """
  Keys of a measured file entry in the scan output.
  """

  # A measured file's path, size and artifact kind.
  PATH = "path"
  BYTES = "bytes"
  KIND = "kind"


def _split_frontmatter(text: str) -> tuple[str, str]:
  """
  Split a markdown text into its frontmatter block and its body.

  Args:
    text: Full text of a markdown file.

  Returns:
    The frontmatter block including its fence lines and the remaining body; the block is empty when the text
    does not open one.
  """
  # line endings are kept so the frontmatter and the body rejoin byte for byte into the original text
  lines = text.splitlines(keepends = True)

  # guard: a file that does not open a frontmatter block is all body
  if not lines or lines[0].strip() != "---":
    return "", text

  # the block runs to the next fence line; an unclosed block is all frontmatter
  for idx in range(1, len(lines)):
    if lines[idx].strip() == "---":
      return "".join(lines[:idx + 1]), "".join(lines[idx + 1:])
  return text, ""


def _find_all_md_files(directory: Path) -> list[Path]:
  """
  List the markdown files directly inside a directory.

  Args:
    directory: Directory to list; it may be absent.

  Returns:
    The markdown file paths in name order; empty when the directory does not exist.
  """
  # guard: an absent directory holds nothing
  if not directory.is_dir():
    return []
  return [ directory / name for name in sorted(os.listdir(directory))
           if name.endswith(_MD) and (directory / name).is_file() ]


def _find_all_skill_files(skills_dir: Path) -> list[Path]:
  """
  List the entry files of the skills inside a skills directory.

  Args:
    skills_dir: Skills directory to list; it may be absent.

  Returns:
    The skill entry file paths in skill-name order; empty when the directory does not exist.
  """
  # guard: an absent skills directory holds no skill
  if not skills_dir.is_dir():
    return []
  return [ skills_dir / name / _Layout.SKILL_MD for name in sorted(os.listdir(skills_dir))
           if (skills_dir / name / _Layout.SKILL_MD).is_file() ]


def _memory_dir(cwd: Path, home: Path) -> Path:
  """
  Return the session memory directory of a project.

  Args:
    cwd: Project root the session runs in.
    home: Operator's home directory.

  Returns:
    The memory folder for the project; it may not exist.
  """
  # the session keys a project by its resolved path with every non-alphanumeric character dashed
  return home / _Layout.CLAUDE_DIR / _Layout.PROJECTS / _KEY_CHARS.sub("-", str(cwd.resolve())) / _Layout.MEMORY


def _is_scoped_rule(path: Path) -> bool:
  """
  Tell whether a rule file loads only on demand.

  Args:
    path: Rule file to inspect.

  Returns:
    `True` when the rule's frontmatter scopes it to matching paths, `False` when it loads every turn.
  """
  # a rule with a `paths:` key loads only when a matching file is touched
  head, _body = _split_frontmatter(path.read_text(encoding = "utf-8"))
  return _PATHS_KEY in parse_frontmatter(head)


def _scan_weight(cwd: Path, home: Path) -> dict:
  """
  Measure the context a session loads at start and the artifacts it loads only when used.

  Args:
    cwd: Project root the session runs in.
    home: Operator's home directory.

  Returns:
    A mapping with the always-loaded files by descending size, the on-demand files with their kind, the
    always-loaded byte total, and the severity level the total grades to.
  """

  # Domain(unfiled):
  # # Always-loaded context and its budget
  # A session pays for some instructions on every turn and for the rest only when they are used. The operator and
  # project instruction files, the memory index and every rule that is not scoped to particular files are paid for
  # every turn. A rule scoped to matching files, an agent, a skill, a command and a memory note cost nothing until
  # they are touched. Only the always-loaded part is a budget: its total size is graded PASS up to 20 KB, WARN
  # above 20 KB and up to 40 KB, and FAIL above 40 KB. Scoping a rule to the files it concerns is the way to move
  # weight out of the budget.

  # the load classes and the roots they are read from
  always: list[dict] = []
  on_demand: list[dict] = []
  memory = _memory_dir(cwd, home)
  cwd_dir = cwd / _Layout.CLAUDE_DIR
  home_dir = home / _Layout.CLAUDE_DIR

  # the instruction files every session loads, each only when it exists
  for path in ( home_dir / _Layout.CLAUDE_MD, cwd_dir / _Layout.CLAUDE_MD, cwd / _Layout.CLAUDE_MD,
                memory / _INDEX ):
    if path.is_file():
      always.append({ _Field.PATH: str(path), _Field.BYTES: path.stat().st_size })

  # an unscoped rule loads every turn; a scoped one only on demand
  for rule in _find_all_md_files(home_dir / _Layout.RULES) + _find_all_md_files(cwd_dir / _Layout.RULES):
    entry = { _Field.PATH: str(rule), _Field.BYTES: rule.stat().st_size }
    if _is_scoped_rule(rule):
      on_demand.append({ **entry, _Field.KIND: "rule" })
    else:
      always.append(entry)

  # agents, skills, commands and memory notes cost nothing until they are used
  sources = (
    ( "agent", _find_all_md_files(cwd_dir / _Layout.AGENTS) ),
    ( "skill", _find_all_skill_files(cwd_dir / _Layout.SKILLS) + _find_all_skill_files(home_dir / _Layout.SKILLS) ),
    ( "command", _find_all_md_files(cwd_dir / _Layout.COMMANDS) + _find_all_md_files(home_dir / _Layout.COMMANDS) ),
    ( "memory", [ path for path in _find_all_md_files(memory) if path.name != _INDEX ] ),
  )
  for kind, paths in sources:
    on_demand.extend(
      { _Field.PATH: str(path), _Field.BYTES: path.stat().st_size, _Field.KIND: kind } for path in paths
    )

  # the always-loaded sum is the per-turn budget the level grades
  always.sort(key = lambda item: item[_Field.BYTES], reverse = True)
  total = sum(item[_Field.BYTES] for item in always)
  level = _PASS if total <= _WEIGHT_WARN else (_WARN if total <= _WEIGHT_FAIL else _FAIL)
  return { "always_loaded": always, "on_demand": on_demand, "always_total": total, "level": level }


def _scan_memory_index(cwd: Path, home: Path) -> dict:
  """
  Check the memory index against the notes beside it.

  Args:
    cwd: Project root the session runs in.
    home: Operator's home directory.

  Returns:
    A mapping with the index size, whether it is oversized, the notes it never links, and the link targets that
    do not exist.
  """
  memory = _memory_dir(cwd, home)
  index = memory / _INDEX
  text = index.read_text(encoding = "utf-8") if index.is_file() else ""

  # every link target the index names, and the notes it names none of
  targets = _LINK.findall(text)
  notes = [ path.name for path in _find_all_md_files(memory) if path.name != _INDEX ]
  return {
    "index_bytes": index.stat().st_size if index.is_file() else 0,
    "oversized": index.is_file() and index.stat().st_size > _INDEX_LIMIT,
    "orphans": [ name for name in notes if name not in targets ],
    "broken": [ target for target in targets if not (memory / target).exists() ],
  }


def _compute_edit_distance(left: str, right: str) -> int:
  """
  Compute the edit distance between two strings.

  Args:
    left: First string.
    right: Second string.

  Returns:
    The minimum number of single-character insertions, deletions and substitutions turning one string into the
    other.
  """
  # the classic two-row edit distance: insert, delete and substitute each cost one
  previous = list(range(len(right) + 1))
  for row, lch in enumerate(left, start = 1):
    current = [ row ]
    for col, rch in enumerate(right, start = 1):
      current.append(min(previous[col] + 1, current[col - 1] + 1, previous[col - 1] + (lch != rch)))
    previous = current
  return previous[-1]


def _read_note(path: Path) -> tuple[str, list[str]]:
  """
  Read the title and tags of a memory note.

  Args:
    path: Note file to read.

  Returns:
    The note title, falling back to the file stem, and its tags as a list.
  """
  # a note is read by the memory store's own reader; its title falls back to the file stem
  meta = read_note_frontmatter(path) or {}
  tags = meta.get(_Layout.TAGS) or []
  return str(meta.get(_Layout.TITLE) or path.stem), [ tags ] if isinstance(tags, str) else list(tags)


def _scan_expert_memory(cwd: Path, _home: Path) -> dict:
  """
  Check each expert's memory notes for missing tag listings and near-duplicate titles.

  Args:
    cwd: Project root holding the expert memory.
    _home: Unused; present so every scanner shares one signature.

  Returns:
    A mapping with the notes no tag file lists and the pairs of notes that share a tag and have nearly the same
    title.
  """
  root = cwd / _Layout.EXPERT_MEMORY
  orphans: list[dict] = []
  dupes: list[dict] = []
  experts = sorted(name for name in os.listdir(root) if (root / name).is_dir() and not name.startswith(".")) \
    if root.is_dir() else []

  # each expert's notes are checked against that expert's own tag files
  for expert in experts:
    notes = [
      (path, *_read_note(path)) for path in _find_all_md_files(root / expert) if not path.name.startswith(".")
    ]
    for path, _title, tags in notes:
      listed = [
        tag for tag in tags if tag.startswith(_TAG_PREFIX)
        and (tag_file := root / expert / _TAGS_DIR / f"{tag[len(_TAG_PREFIX):]}{_MD}").is_file()
        and f"`../{path.name}`" in tag_file.read_text(encoding = "utf-8")
      ]
      if not listed:
        orphans.append({ "expert": expert, "path": str(path.relative_to(cwd)), "tags": tags })

    # Domain(unfiled):
    # # Near-duplicate memory notes
    # Two notes of one expert may record the same thing twice, and a duplicate pair is worth merging. Two notes are
    # suspected duplicates when they share at least one tag and their titles differ by at most three single-character
    # edits. A shared tag alone only says the notes are about one topic, and similar titles alone are often a
    # coincidence of wording, so both signals must hold. The comparison stays inside one expert's memory.

    # two notes sharing a tag with nearly the same title may say the same thing
    for idx, (path_a, title_a, tags_a) in enumerate(notes):
      for path_b, title_b, tags_b in notes[idx + 1:]:
        shared = [ tag for tag in tags_a if tag in tags_b ]
        if shared and (distance := _compute_edit_distance(title_a, title_b)) <= _TITLE_DISTANCE:
          dupes.append({ "a": str(path_a.relative_to(cwd)), "b": str(path_b.relative_to(cwd)),
                         "shared_tags": shared, "distance": distance })
  return { "orphan_notes": orphans, "near_duplicates": dupes }


def _scan_skill_size(cwd: Path, home: Path) -> list[dict]:
  """
  Measure the body size of every skill the session can reach.

  Args:
    cwd: Project root the session runs in.
    home: Operator's home directory.

  Returns:
    One entry per skill with its path, body line and byte counts, whether it is over the size limits, and
    whether it already dispatches work in parallel.
  """
  skills = _find_all_skill_files(cwd / _Layout.CLAUDE_DIR / _Layout.SKILLS)
  skills += _find_all_skill_files(home / _Layout.CLAUDE_DIR / _Layout.SKILLS)

  # a repo that authors plugins carries their skills too
  plugins = cwd.joinpath(*_Layout.PLUGINS)
  if plugins.is_dir():
    for name in sorted(os.listdir(plugins)):
      skills += _find_all_skill_files(plugins / name / _Layout.SKILLS)

  # Domain(unfiled):
  # # Skill size limit
  # A skill is read in full whenever it is invoked, so a long body is a standing cost and a sign that the skill does
  # too much itself. A skill body of more than 120 lines or more than 5 KB is a candidate for delegating work to
  # subagents. Either limit alone is enough. Only the body counts, because the frontmatter is the skill's
  # registration and not its working text. A skill that already dispatches its scans in parallel is marked as such,
  # since delegation is then already in place.

  # size and existing parallel dispatch are measured on the body, never the frontmatter
  out = []
  for path in skills:
    body = _split_frontmatter(path.read_text(encoding = "utf-8"))[1]
    lines = len(body.splitlines())
    size = len(body.encode("utf-8"))
    out.append({
      _Field.PATH: str(path), "lines": lines, _Field.BYTES: size,
      "over_size": lines > _SKILL_LINES or size > _SKILL_BYTES,
      "has_parallel_dispatch": any(marker in body for marker in _PARALLEL_MARKERS),
    })
  return out


_SCANNERS: dict[str, Callable[[Path, Path], dict | list]] = dict(zip(
  _SECTIONS, ( _scan_weight, _scan_memory_index, _scan_expert_memory, _scan_skill_size ), strict = True,
))


def scan(section: str, *, cwd: Path, home: Path) -> dict | list:
  """
  Run one named context scan section.

  Args:
    section: Section name to run.
    cwd: Project root the session runs in.
    home: Operator's home directory.

  Returns:
    The measurements of the requested section.

  Raises:
    KeyError: If `section` is not a known context scan section.
  """
  return _SCANNERS[section](cwd, home)


def cmd_context_scan(argv: list[str]) -> int:
  """
  Run the `context-scan` verb and print the requested section as JSON.

  Args:
    argv: Command-line arguments after the verb name.

  Returns:
    Process exit code; always `0`.
  """
  # one section per call; the repo root follows the dispatcher convention
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-core context-scan")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--section", required = True, choices = _SECTIONS)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the section's measurements are the verb's whole output
  print(json.dumps(scan(args.section, cwd = resolve_repo_root(args.cwd), home = Path.home())))
  return 0
