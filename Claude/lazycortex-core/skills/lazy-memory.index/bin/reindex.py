"""lazy-memory.index — rebuild .memory/.tags/ + every .memory/<expert>/.tags/
from the notes' frontmatter. Recovery / operator tool. No commit."""
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
    """Walk every expert in .memory/, recompute the set of topics
    each carries, regenerate local + global tag files, and remove
    any tag file that no longer has a backing note. Returns a
    summary dict."""
    repo = Path(repo)
    memory_root = repo / ".memory"
    summary = {"experts": 0, "notes": 0, "tags": 0}
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
            if not fm:
                continue
            tags = fm.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
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
    import argparse, json
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    print(json.dumps(reindex(Path(args.repo))))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
