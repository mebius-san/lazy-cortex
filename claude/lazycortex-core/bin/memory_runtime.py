"""
Shared helpers for the .memory/ subsystem.

Used by lazy-memory.{write,index,reflect} skills and the memory-reflect-all
CLI verb. Pure functions where possible — caller (skill) owns commits + IO
sequencing.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import re

from constants import MemoryFrontmatterKey, RepoDir

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterable
  from pathlib import Path


VALID_TYPES = { "persona", "rule", "example", "warning", "fact" }
TAG_PREFIX = "memory/"


class FrontmatterError(ValueError):
  """
  Raised when a memory-note frontmatter dict fails validation.
  """


def slugify(title: str) -> str:
  """
  Convert a memory-note title into a deterministic URL-friendly slug.

  Args:
    title: Free-form note title supplied by the caller.

  Returns:
    Lowercase ASCII slug made of alphanumerics and single dashes, with leading and trailing dashes stripped.
    Returns the literal `"untitled"` when the input collapses to an empty string. The result is not guaranteed
    to be unique under the target directory — pair with `resolve_slug` to handle collisions.
  """
  s = title.strip().lower()
  s = re.sub(r"[^a-z0-9]+", "-", s)
  s = s.strip("-")
  return s or "untitled"


def resolve_slug(expert_dir: Path, base: str) -> str:
  """
  Pick a slug under the expert directory that does not collide with an existing note.

  Args:
    expert_dir: Directory under `.memory/<expert>/` where the note will be written.
    base: Candidate slug, typically produced by `slugify`.

  Returns:
    `base` when no `<base>.md` exists in `expert_dir`; otherwise the lowest-numbered `<base>-N` suffix
    (starting at `-2`) for which `<base>-N.md` does not yet exist.
  """
  # guard: no collision — base slug is available as-is
  if not (expert_dir / f"{base}.md").exists():
    return base
  n = 2
  while (expert_dir / f"{base}-{n}.md").exists():
    n += 1
  return f"{base}-{n}"


def validate_frontmatter(fm: dict) -> None:
  """
  Validate the frontmatter dict of a memory note.

  Args:
    fm: Frontmatter dict parsed from a memory-note YAML block. Required keys are `title`, `tags`,
      `type`, and `summary`.

  Raises:
    FrontmatterError: If a required field is missing, if `tags` is not a non-empty list of strings
      each prefixed with `memory/`, or if `type` is not one of the values in `VALID_TYPES`.
  """
  for field in ("title", "tags", "type", "summary"):
    # guard: required field missing from frontmatter
    if field not in fm:
      raise FrontmatterError(f"missing required field: {field}")
  tags = fm[MemoryFrontmatterKey.TAGS]
  # guard: tags must be a non-empty list
  if not isinstance(tags, list) or not tags:
    raise FrontmatterError("tags must be a non-empty list")
  for t in tags:
    # guard: each tag must be a string carrying the memory/ prefix
    if not isinstance(t, str) or not t.startswith(TAG_PREFIX):
      raise FrontmatterError(f"tag must be prefixed `{TAG_PREFIX}`: {t!r}")
  # guard: type must be drawn from the closed set
  if fm[MemoryFrontmatterKey.TYPE] not in VALID_TYPES:
    raise FrontmatterError(f"type must be one of {sorted(VALID_TYPES)}: {fm[MemoryFrontmatterKey.TYPE]!r}")


def topic_from_tag(tag: str) -> str:
  """
  Return the topic portion of a memory tag.

  Args:
    tag: Tag string expected to start with the `memory/` prefix. Hierarchical sub-paths after the
      prefix are preserved verbatim.

  Returns:
    The tag with the leading `memory/` prefix removed.

  Raises:
    ValueError: If `tag` does not start with the `memory/` prefix.
  """
  # guard: tag must carry the memory/ prefix
  if not tag.startswith(TAG_PREFIX):
    raise ValueError(f"tag missing `{TAG_PREFIX}` prefix: {tag!r}")
  return tag[len(TAG_PREFIX):]


def _read_note_frontmatter(path: Path) -> dict | None:
  """
  Read and parse the YAML frontmatter block of a memory note.

  Supports the three shapes used by memory notes: simple `key: value`, inline list `tags: [a, b]`,
  and block list `tags:\\n  - a\\n  - b`. Avoids a hard PyYAML dependency.

  Args:
    path: Filesystem path to a memory note.

  Returns:
    The parsed frontmatter dict, or `None` when the file cannot be read, does not begin with the
    `---` frontmatter marker, or lacks a closing `---` line.
  """
  try:
    text = path.read_text()
  except OSError:
    return None
  # guard: frontmatter must open with --- on the first line
  if not text.startswith("---"):
    return None
  try:
    # waiver: inline numeric literal (length of the `---` fence), not a domain constant
    end = text.index("\n---", 3)
  except ValueError:
    return None
  body = text[3:end].strip()
  fm: dict = {}
  pending_list_key: str | None = None
  for raw in body.splitlines():
    line = raw.rstrip()
    # blank line terminates an open block-list
    if not line:
      pending_list_key = None
      continue
    # comment line — skip
    # guard: skip comment lines
    if line.lstrip().startswith("#"):
      continue
    # continuation of a block-list value: `  - item`
    if pending_list_key is not None and line.lstrip().startswith("- "):
      fm[pending_list_key].append(line.lstrip()[2:].strip().strip('"\''))
      continue
    # anything else terminates an open block-list
    pending_list_key = None
    # guard: skip lines without a key/value separator
    if ":" not in line:
      continue
    key, _, value = line.partition(":")
    key = key.strip()
    value = value.strip()
    # inline list form: tags: [a, b]
    if value.startswith("[") and value.endswith("]"):
      inner = value[1:-1].strip()
      if not inner:
        fm[key] = []
      else:
        fm[key] = [ v.strip().strip('"\'') for v in inner.split(",") ]
    # bare key with no value opens a block-list
    elif not value:
      fm[key] = []
      pending_list_key = key
    else:
      fm[key] = value.strip('"\'')
  return fm


def _iter_notes(expert_dir: Path) -> Iterable[Path]:
  """
  Yield every memory-note file under a single expert directory.

  Iterates the flat `.memory/<expert>/` layout, skipping dotfiles and the `.tags/` subdirectory.
  Entries are visited in lexicographic order.

  Args:
    expert_dir: Directory under `.memory/` for one expert.

  Yields:
    Each `*.md` note file under `expert_dir`, in sorted order. Yields nothing when the directory
    does not exist.
  """
  # guard: directory missing — nothing to yield
  if not expert_dir.is_dir():
    return
  for entry in sorted(expert_dir.iterdir()):
    # guard: skip hidden entries
    if entry.name.startswith("."):
      continue
    # waiver: filesystem extension idiom, not a domain constant
    if entry.is_file() and entry.suffix == ".md":
      yield entry


def regen_local_tag_file(expert_dir: Path, topic: str) -> None:
  """
  Rewrite the per-expert tag file for a single topic.

  Scans every note under `expert_dir`, collects those carrying `memory/<topic>` as a tag, and writes
  one bullet per matching note into `<expert_dir>/.tags/<topic>.md`. Deletes the tag file when no
  note carries the tag.

  Args:
    expert_dir: Directory under `.memory/` for one expert.
    topic: Topic suffix (the portion after the `memory/` prefix) to regenerate.

  Raises:
    OSError: If the tag file or its parent directory cannot be written or removed.
  """
  tags_dir = expert_dir / RepoDir.TAGS
  tag_file = tags_dir / f"{topic}.md"
  # (slug, type, summary) tuples for every matching note
  matching: list[tuple[str, str, str]] = []
  for note in _iter_notes(expert_dir):
    fm = _read_note_frontmatter(note)
    # guard: skip notes without parseable frontmatter
    if not fm:
      continue
    tags = fm.get(MemoryFrontmatterKey.TAGS) or []
    if isinstance(tags, str):
      tags = [ tags ]
    if f"{TAG_PREFIX}{topic}" in tags:
      matching.append((note.name, fm.get(MemoryFrontmatterKey.TYPE, "?"), fm.get(MemoryFrontmatterKey.SUMMARY, "")))
  # no notes carry the topic — remove the stale tag file if any
  if not matching:
    if tag_file.exists():
      tag_file.unlink()
    return
  tags_dir.mkdir(parents = True, exist_ok = True)
  lines = [ f"- `../{name}` — {t} — {summary}" for (name, t, summary) in matching ]
  tag_file.write_text("\n".join(lines) + "\n")


def regen_global_tag_file(memory_root: Path, topic: str) -> None:
  """
  Rewrite the cross-expert tag file for a single topic.

  Scans every expert directory under `memory_root`, collects those whose own `.tags/<topic>.md`
  exists, and writes one bullet per holding expert into `<memory_root>/.tags/<topic>.md`. Deletes
  the global tag file when no expert holds the topic.

  Args:
    memory_root: Root `.memory/` directory containing per-expert subdirectories.
    topic: Topic suffix (the portion after the `memory/` prefix) to regenerate.

  Raises:
    OSError: If the global tag file or its parent directory cannot be written or removed.
  """
  global_tag_file = memory_root / RepoDir.TAGS / f"{topic}.md"
  holders: list[str] = []
  if memory_root.is_dir():
    for expert in sorted(memory_root.iterdir()):
      # guard: skip non-directory and hidden entries
      if not expert.is_dir() or expert.name.startswith("."):
        continue
      local = expert / RepoDir.TAGS / f"{topic}.md"
      if local.exists():
        holders.append(f"- `../{expert.name}/.tags/{topic}.md`")
  # no expert holds the topic — remove the stale global tag file if any
  if not holders:
    if global_tag_file.exists():
      global_tag_file.unlink()
    return
  global_tag_file.parent.mkdir(parents = True, exist_ok = True)
  global_tag_file.write_text("\n".join(holders) + "\n")


def regen_touched_tags(memory_root: Path, expert: str, topics: Iterable[str]) -> None:
  """
  Regenerate both the local and global tag files for each topic in a batch.

  Idempotent — safe to call repeatedly with the same inputs. Topics seen more than once in the
  iterable are processed only on the first occurrence.

  Args:
    memory_root: Root `.memory/` directory containing per-expert subdirectories.
    expert: Name of the expert subdirectory whose local tag files should be refreshed.
    topics: Iterable of topic suffixes (the portion after the `memory/` prefix) to regenerate.

  Raises:
    OSError: If any of the underlying tag files cannot be written or removed.
  """
  expert_dir = memory_root / expert
  seen: set[str] = set()
  for topic in topics:
    # guard: skip topics already emitted
    if topic in seen:
      continue
    seen.add(topic)
    regen_local_tag_file(expert_dir, topic)
    regen_global_tag_file(memory_root, topic)
