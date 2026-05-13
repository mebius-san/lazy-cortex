"""lazy-memory.write worker — atomic note + tag-index regen + consolidate drops.

Reads frontmatter from the body, validates, writes the note, regenerates
every touched tag file (local + global), and drops --consolidate paths.
Caller (skill) commits — this worker does NOT touch git.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Resolve the shared memory_runtime helpers from the plugin's bin/.
_BIN = Path(__file__).resolve().parents[3] / "bin"
sys.path.insert(0, str(_BIN))

from memory_runtime import (
    FrontmatterError, slugify, resolve_slug, validate_frontmatter,
    topic_from_tag, _read_note_frontmatter, regen_touched_tags,
)


class WriteError(Exception):
    """Surfaced to skill caller with a category prefix."""


def _parse_body_frontmatter(body: str) -> tuple[dict, str]:
    """Split frontmatter from body content. Returns (fm_dict, rest_text)."""
    if not body.startswith("---"):
        raise WriteError("frontmatter-invalid: body missing opening `---`")
    try:
        end = body.index("\n---", 3)
    except ValueError:
        raise WriteError("frontmatter-invalid: body missing closing `---`")
    fm_text = body[3:end].strip()
    rest = body[end + 4:].lstrip("\n")
    fm: dict = {}
    pending_list_key: str | None = None
    for line in fm_text.splitlines():
        raw = line.rstrip()
        if not raw:
            pending_list_key = None
            continue
        if raw.startswith("  - ") and pending_list_key:
            fm[pending_list_key].append(raw[4:].strip().strip('"\''))
            continue
        pending_list_key = None
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            fm[key] = [v.strip().strip('"\'') for v in inner.split(",")] if inner else []
        elif not value:
            fm[key] = []
            pending_list_key = key
        else:
            fm[key] = value.strip('"\'')
    return fm, rest


def _is_safe_consolidate_path(repo: Path, target: Path) -> bool:
    """A consolidate target must be under repo/.logs/ or repo/.memory/."""
    try:
        target_resolved = target.resolve()
    except (OSError, RuntimeError):
        return False
    safe_roots = [(repo / ".logs").resolve(), (repo / ".memory").resolve()]
    for root in safe_roots:
        try:
            target_resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def write_note(repo: Path, expert: str, body: str,
               slug_override: str | None, consolidate: list[str]) -> Path:
    """Atomic write. Returns the resolved note path."""
    repo = Path(repo)

    # Validate consolidate paths up front; refuse the whole op if any
    # would escape .logs/ or .memory/.
    for c in consolidate:
        cp = Path(c) if Path(c).is_absolute() else (repo / c)
        if not _is_safe_consolidate_path(repo, cp):
            raise WriteError(f"consolidate-out-of-scope: {c}")

    try:
        fm, _ = _parse_body_frontmatter(body)
    except WriteError:
        raise
    try:
        validate_frontmatter(fm)
    except FrontmatterError as e:
        raise WriteError(f"frontmatter-invalid: {e}")

    memory_root = repo / ".memory"
    expert_dir = memory_root / expert
    expert_dir.mkdir(parents=True, exist_ok=True)

    base = slug_override or slugify(fm["title"])
    if slug_override is not None:
        slug = base
    else:
        slug = resolve_slug(expert_dir, base)
    note_path = expert_dir / f"{slug}.md"

    # Capture old tags BEFORE overwriting so we can regenerate retagged files.
    old_tags: list[str] = []
    if note_path.exists():
        prev_fm = _read_note_frontmatter(note_path)
        if prev_fm:
            prev = prev_fm.get("tags") or []
            if isinstance(prev, str):
                prev = [prev]
            old_tags = list(prev)

    note_path.write_text(body if body.endswith("\n") else body + "\n")

    # Regenerate every tag touched by this write — union of old and new tags.
    touched_topics = set()
    for tag in (fm["tags"] + old_tags):
        try:
            touched_topics.add(topic_from_tag(tag))
        except ValueError:
            continue
    regen_touched_tags(memory_root, expert, touched_topics)

    # Drop consolidate targets — best-effort skip on missing.
    for c in consolidate:
        cp = Path(c) if Path(c).is_absolute() else (repo / c)
        try:
            cp.unlink()
        except FileNotFoundError:
            sys.stderr.write(f"consolidate-target-missing: {c}\n")
        except OSError as e:
            raise WriteError(f"consolidate-io-error: {c}: {e}")

    return note_path


def _main(argv: list[str]) -> int:
    """CLI shim: lazy-memory.write <expert> [--slug <slug>] [--consolidate <p>...]
    Body via stdin."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("expert")
    parser.add_argument("--slug", default=None)
    parser.add_argument("--consolidate", action="append", default=[])
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    body = sys.stdin.read()
    try:
        path = write_note(Path(args.repo), args.expert, body, args.slug, args.consolidate)
    except WriteError as e:
        sys.stderr.write(f"{e}\n")
        return 2
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
