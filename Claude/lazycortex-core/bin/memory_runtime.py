"""Shared helpers for the .memory/ subsystem.

Used by lazy-memory.{write,index,reflect} skills and the memory-reflect-all
CLI verb. Pure functions where possible — caller (skill) owns commits + IO
sequencing.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Iterable


VALID_TYPES = {"persona", "rule", "example", "warning", "fact"}
TAG_PREFIX = "memory/"


class FrontmatterError(ValueError):
    """Raised when a memory-note frontmatter dict fails validation."""


def slugify(title: str) -> str:
    """Deterministic title → slug. Lowercase, ASCII alphanumerics + dashes,
    collapse whitespace and punctuation runs to single dash, strip leading
    and trailing dashes. Does NOT handle collisions — caller pairs with
    resolve_slug(...)."""
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "untitled"


def resolve_slug(expert_dir: Path, base: str) -> str:
    """Pick a non-colliding slug under expert_dir. Returns base when no
    collision; otherwise appends -2, -3, ... until free."""
    if not (expert_dir / f"{base}.md").exists():
        return base
    n = 2
    while (expert_dir / f"{base}-{n}.md").exists():
        n += 1
    return f"{base}-{n}"


def validate_frontmatter(fm: dict) -> None:
    """Raise FrontmatterError if the memory-note frontmatter dict is
    incomplete or malformed. Required: title, tags (non-empty list, each
    prefixed `memory/`), type (enum), summary."""
    for field in ("title", "tags", "type", "summary"):
        if field not in fm:
            raise FrontmatterError(f"missing required field: {field}")
    tags = fm["tags"]
    if not isinstance(tags, list) or not tags:
        raise FrontmatterError("tags must be a non-empty list")
    for t in tags:
        if not isinstance(t, str) or not t.startswith(TAG_PREFIX):
            raise FrontmatterError(f"tag must be prefixed `{TAG_PREFIX}`: {t!r}")
    if fm["type"] not in VALID_TYPES:
        raise FrontmatterError(f"type must be one of {sorted(VALID_TYPES)}: {fm['type']!r}")


def topic_from_tag(tag: str) -> str:
    """Strip the `memory/` prefix. Hierarchical sub-paths preserved."""
    if not tag.startswith(TAG_PREFIX):
        raise ValueError(f"tag missing `{TAG_PREFIX}` prefix: {tag!r}")
    return tag[len(TAG_PREFIX):]


def _read_note_frontmatter(path: Path) -> dict | None:
    """Best-effort YAML frontmatter parser. Returns None when frontmatter
    is absent or malformed. Avoids a hard PyYAML dep by parsing the simple
    `key: value`, `tags: [a, b]` (inline), and `tags:\\n  - a\\n  - b`
    (block-list) shapes used by memory notes."""
    try:
        text = path.read_text()
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    try:
        end = text.index("\n---", 3)
    except ValueError:
        return None
    body = text[3:end].strip()
    fm: dict = {}
    pending_list_key: str | None = None
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line:
            pending_list_key = None
            continue
        if line.lstrip().startswith("#"):
            continue
        # Continuation of a block-list value: `  - item`.
        if pending_list_key is not None and line.lstrip().startswith("- "):
            fm[pending_list_key].append(line.lstrip()[2:].strip().strip('"\''))
            continue
        # Anything else terminates an open block-list.
        pending_list_key = None
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                fm[key] = []
            else:
                fm[key] = [v.strip().strip('"\'') for v in inner.split(",")]
        elif not value:
            fm[key] = []
            pending_list_key = key
        else:
            fm[key] = value.strip('"\'')
    return fm


def _iter_notes(expert_dir: Path) -> Iterable[Path]:
    """Yield every memory-note path under expert_dir (flat layout, *.md
    excluding `.tags/`)."""
    if not expert_dir.is_dir():
        return
    for entry in sorted(expert_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_file() and entry.suffix == ".md":
            yield entry


def regen_local_tag_file(expert_dir: Path, topic: str) -> None:
    """Rewrite expert_dir/.tags/<topic>.md to list every note carrying
    `memory/<topic>` as a tag. Deletes the tag file when no notes carry
    the tag."""
    tags_dir = expert_dir / ".tags"
    tag_file = tags_dir / f"{topic}.md"
    matching: list[tuple[str, str, str]] = []  # (slug, type, summary)
    for note in _iter_notes(expert_dir):
        fm = _read_note_frontmatter(note)
        if not fm:
            continue
        tags = fm.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        if f"{TAG_PREFIX}{topic}" in tags:
            matching.append((note.name, fm.get("type", "?"), fm.get("summary", "")))
    if not matching:
        if tag_file.exists():
            tag_file.unlink()
        return
    tags_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"- `../{name}` — {t} — {summary}" for (name, t, summary) in matching]
    tag_file.write_text("\n".join(lines) + "\n")


def regen_global_tag_file(memory_root: Path, topic: str) -> None:
    """Rewrite memory_root/.tags/<topic>.md to list every per-expert
    tag file that exists for `topic`. Deletes when no expert holds the
    topic."""
    global_tag_file = memory_root / ".tags" / f"{topic}.md"
    holders: list[str] = []
    if memory_root.is_dir():
        for expert in sorted(memory_root.iterdir()):
            if not expert.is_dir() or expert.name.startswith("."):
                continue
            local = expert / ".tags" / f"{topic}.md"
            if local.exists():
                holders.append(f"- `../{expert.name}/.tags/{topic}.md`")
    if not holders:
        if global_tag_file.exists():
            global_tag_file.unlink()
        return
    global_tag_file.parent.mkdir(parents=True, exist_ok=True)
    global_tag_file.write_text("\n".join(holders) + "\n")


def regen_touched_tags(memory_root: Path, expert: str, topics: Iterable[str]) -> None:
    """Convenience: regenerate both local and global tag files for every
    topic in `topics`. Idempotent — safe to call repeatedly."""
    expert_dir = memory_root / expert
    seen: set[str] = set()
    for topic in topics:
        if topic in seen:
            continue
        seen.add(topic)
        regen_local_tag_file(expert_dir, topic)
        regen_global_tag_file(memory_root, topic)
