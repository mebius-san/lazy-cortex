"""
lazy-memory.index — rebuild .memory/.tags/ + every .memory/<expert>/.tags/
from the notes' frontmatter. Recovery / operator tool. No commit.
"""
from __future__ import annotations
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parents[3] / "bin"
sys.path.insert(0, str(_BIN))

from memory_runtime import (
  _read_note_frontmatter, _iter_notes, topic_from_tag,
  regen_local_tag_file, regen_global_tag_file,
)


def reindex(repo: Path) -> dict:
  """
  Rebuild the tag index for the repository's `.memory/` tree from current note frontmatter.

  Stale tag files that no longer have a backing note are removed; tag files for live notes
  are written in their canonical form.

  Args:
    repo: Absolute path to the repository whose `.memory/` tree should be reindexed.

  Returns:
    A summary dict with `experts`, `notes`, and `tags` counts covered by the rebuild.
  """
  repo = Path(repo)
  memory_root = repo / ".memory"
  summary = { "experts": 0, "notes": 0, "tags": 0 }
  # guard: no .memory tree — nothing to reindex
  if not memory_root.is_dir():
    return summary

  # Pass 1: discover every topic anywhere in the tree (across notes
  # and existing tag files so we delete stale entries too).
  all_topics: set[str] = set()
  experts: list[Path] = []
  for entry in sorted(memory_root.iterdir()):
    if entry.is_dir() and not entry.name.startswith("."):
      experts.append(entry)
      summary["experts"] += 1
    if entry.is_dir() and entry.name == ".tags":
      for f in entry.iterdir():
        if f.is_file() and f.suffix == ".md":
          all_topics.add(f.stem)

  for expert_dir in experts:
    for note in _iter_notes(expert_dir):
      summary["notes"] += 1
      fm = _read_note_frontmatter(note)
      # guard: note has no parseable frontmatter — skip
      if not fm:
        continue
      tags = fm.get("tags") or []
      if isinstance(tags, str):
        tags = [ tags ]
      for tag in tags:
        try:
          all_topics.add(topic_from_tag(tag))
        except ValueError:
          continue
    # Also fold in existing local .tags/ files so stale ones are seen.
    local_tags_dir = expert_dir / ".tags"
    if local_tags_dir.is_dir():
      for f in local_tags_dir.iterdir():
        if f.is_file() and f.suffix == ".md":
          all_topics.add(f.stem)

  # Pass 2: regenerate every (expert, topic) pair and every global topic.
  for topic in sorted(all_topics):
    for expert_dir in experts:
      regen_local_tag_file(expert_dir, topic)
    regen_global_tag_file(memory_root, topic)

  summary["tags"] = len(all_topics)
  return summary


def _main(argv: list[str]) -> int:
  """
  Command-line entry point for the reindex skill.

  Emits the rebuild summary as a single JSON line on stdout.

  Args:
    argv: Argument list without the program name. Supports `--repo <path>` (default `.`).

  Returns:
    The process exit code (`0` on success).
  """
  import argparse, json
  parser = argparse.ArgumentParser()
  parser.add_argument("--repo", default = ".")
  args = parser.parse_args(argv)
  print(json.dumps(reindex(Path(args.repo))))
  return 0


if __name__ == "__main__":
  raise SystemExit(_main(sys.argv[1:]))
