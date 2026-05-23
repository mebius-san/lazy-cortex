"""
lazy-memory.write worker — atomic note + tag-index regen + consolidate drops.

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
  """
  Error raised by the lazy-memory.write worker.

  The exception message starts with a stable category prefix (e.g. `frontmatter-invalid:`,
  `consolidate-out-of-scope:`, `consolidate-io-error:`) that the calling skill matches on to
  decide how to report the failure to the operator.
  """


def _parse_body_frontmatter(body: str) -> tuple[dict, str]:
  """
  Split a markdown note into its YAML frontmatter mapping and the remaining body text.

  Accepts the YAML subset used by memory notes: scalar `key: value` entries, inline list
  literals `key: [a, b]`, and block-style lists with `  - item` continuation lines.

  Args:
    body: Full note text beginning with an opening `---` frontmatter delimiter.

  Returns:
    A tuple of the parsed frontmatter dict and the body text that follows the closing
    delimiter.

  Raises:
    WriteError: If the opening or closing `---` delimiter is missing.
  """
  # guard: body must open with the YAML frontmatter delimiter
  if not body.startswith("---"):
    raise WriteError("frontmatter-invalid: body missing opening `---`")
  try:
    end = body.index("\n---", 3)
  except ValueError:
    raise WriteError("frontmatter-invalid: body missing closing `---`")
  # extract the frontmatter text and the body that follows the closing delimiter
  fm_text = body[3:end].strip()
  rest = body[end + 4:].lstrip("\n")
  # line-by-line YAML-subset parser: scalar `key: value`, inline `[a, b]`, and block lists
  fm: dict = {}
  pending_list_key: str | None = None
  for line in fm_text.splitlines():
    raw = line.rstrip()
    # blank line ends any pending block-list context
    if not raw:
      pending_list_key = None
      continue
    # block-list item belonging to the currently open key
    if raw.startswith("  - ") and pending_list_key:
      fm[pending_list_key].append(raw[4:].strip().strip('"\''))
      continue
    pending_list_key = None
    # guard: skip lines without a key:value separator
    if ":" not in raw:
      continue
    key, _, value = raw.partition(":")
    key = key.strip()
    value = value.strip()
    # inline list literal: `key: [a, b, c]`
    if value.startswith("[") and value.endswith("]"):
      inner = value[1:-1].strip()
      fm[key] = [ v.strip().strip('"\'') for v in inner.split(",") ] if inner else []
    # bare key — open block-list context for subsequent `  - ` items
    elif not value:
      fm[key] = []
      pending_list_key = key
    # scalar value — strip surrounding quotes
    else:
      fm[key] = value.strip('"\'')
  return fm, rest


def _is_safe_consolidate_path(repo: Path, target: Path) -> bool:
  """
  Report whether a consolidate target is permitted by the worker's safety policy.

  A path is safe only when it resolves to a location inside the repository's `.logs/` or
  `.memory/` tree. Unresolvable paths (broken symlinks, permission errors) are treated as
  unsafe.

  Args:
    repo: Absolute path to the repository root.
    target: Candidate consolidate target to validate.

  Returns:
    `True` if the target falls under one of the allowed roots, `False` otherwise.
  """
  try:
    target_resolved = target.resolve()
  except (OSError, RuntimeError):
    return False
  # consolidate targets are constrained to the two repo-internal trees
  safe_roots = [ (repo / ".logs").resolve(), (repo / ".memory").resolve() ]
  for root in safe_roots:
    try:
      target_resolved.relative_to(root)
      return True
    except ValueError:
      continue
  return False


def write_note(repo: Path, expert: str, body: str,
               slug_override: str | None, consolidate: list[str]) -> Path:
  """
  Persist a memory note for one expert and refresh the tag indexes it touches.

  The note body's frontmatter is parsed and validated before any filesystem change; on any
  validation failure no files are written and no consolidate targets are removed. After a
  successful write, every tag file affected by the union of the note's previous and current
  tags is regenerated, and each consolidate target is best-effort deleted (a missing target
  is logged to stderr and does not abort the call). Git state is not touched — the caller is
  responsible for committing.

  Args:
    repo: Absolute path to the repository root.
    expert: Expert identifier whose memory directory receives the note.
    body: Full note text including its opening YAML frontmatter block.
    slug_override: Explicit slug to use for the note filename; when `None` the slug is derived
      from the frontmatter title and deduplicated against existing notes.
    consolidate: Repo-relative or absolute paths to remove after the note is written. Each
      path must resolve under `.logs/` or `.memory/`.

  Returns:
    Absolute path to the note that was written.

  Raises:
    WriteError: If any consolidate path escapes the allowed roots, the frontmatter is missing
      or invalid, or a consolidate target fails to delete for a reason other than not being
      present.
  """
  repo = Path(repo)

  # Validate consolidate paths up front; refuse the whole op if any
  # would escape .logs/ or .memory/.
  for c in consolidate:
    cp = Path(c) if Path(c).is_absolute() else (repo / c)
    # guard: refuse the whole op when any consolidate target escapes the safe roots
    if not _is_safe_consolidate_path(repo, cp):
      raise WriteError(f"consolidate-out-of-scope: {c}")

  # Parse and validate the frontmatter block embedded in the body
  try:
    fm, _ = _parse_body_frontmatter(body)
  except WriteError:
    raise
  try:
    validate_frontmatter(fm)
  except FrontmatterError as e:
    raise WriteError(f"frontmatter-invalid: {e}")

  # Resolve the per-expert memory directory and ensure it exists
  memory_root = repo / ".memory"
  expert_dir = memory_root / expert
  expert_dir.mkdir(parents = True, exist_ok = True)

  # Resolve the note slug — honor an explicit override, otherwise derive + deduplicate
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
        prev = [ prev ]
      old_tags = list(prev)

  # Write the note body, ensuring a trailing newline
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
  """
  Command-line entry point for the lazy-memory.write worker.

  Reads the note body from standard input and writes it for the given expert. The resolved
  note path is printed to standard output on success; on failure the error category is
  printed to standard error.

  Args:
    argv: Argument vector without the program name. Supports the positional `expert`,
      optional `--slug`, repeatable `--consolidate`, and `--repo` (default current directory).

  Returns:
    `0` on a successful write, `2` when the worker raises `WriteError`.
  """
  import argparse
  # parse the CLI surface — expert positional + optional slug + repeatable consolidate
  parser = argparse.ArgumentParser()
  parser.add_argument("expert")
  parser.add_argument("--slug", default = None)
  parser.add_argument("--consolidate", action = "append", default = [])
  parser.add_argument("--repo", default = ".")
  args = parser.parse_args(argv)
  # body content arrives on stdin
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
