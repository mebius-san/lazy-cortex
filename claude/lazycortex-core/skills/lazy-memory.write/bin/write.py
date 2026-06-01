"""
lazy-memory.write worker — atomic note + tag-index regen + consolidate drops + commit.

Reads frontmatter from the body, validates, writes the note, regenerates
every touched tag file (local + global), drops --consolidate paths, and
finalizes the change with one atomic git commit under the memory-bot
identity derived from the expert (`memory.<expert>` / `memory.<expert>@<bot-domain>`).
The expert that called this worker does NOT commit the memory paths
itself — the subsystem owns its own git visibility.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# deferred imports below module code; position intentional (ruff E402 noqa guards it)
# pylint: disable=import-error,wrong-import-position

import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Resolve the shared memory_runtime helpers from the plugin's bin/.

_BIN = Path(__file__).resolve().parents[3] / "bin"
sys.path.insert(0, str(_BIN))

# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from memory_runtime import (  # noqa: E402
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
    # waiver: inline numeric literal, not a domain constant
    end = body.index("\n---", 3)
  except ValueError as exc:
    raise WriteError("frontmatter-invalid: body missing closing `---`") from exc
  # extract the frontmatter text and the body that follows the closing delimiter
  fm_text = body[3:end].strip()
  # waiver: inline numeric literal, not a domain constant
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
  # waiver: filesystem path/filename idiom, not a domain constant
  safe_roots = [ (repo / ".logs").resolve(), (repo / ".memory").resolve() ]
  for root in safe_roots:
    try:
      target_resolved.relative_to(root)
      return True
    except ValueError:
      continue
  return False


_BOT_DOMAIN = "bot.lazy-cortex"
_MEMORY_PREFIX = "memory."


def _load_expert_git_author(repo: Path, expert: str) -> dict:
  """
  Read `lazy.settings.json[experts][<expert>].git_author` from the worktree.

  Used as the base identity from which the memory-bot identity is derived.
  Returns an empty dict when the file or entry is missing — the caller
  decides whether that is fatal.

  Returns:
    The `git_author` dict for the named expert, or an empty dict when the settings
    file is absent, unreadable, or does not declare the expert.
  """
  # waiver: filesystem path/filename idiom, not a domain constant
  settings_path = repo / ".claude" / "lazy.settings.json"
  # guard: settings file missing — return empty dict, caller decides
  if not settings_path.exists():
    return {}
  try:
    data = json.loads(settings_path.read_text())
  except (OSError, json.JSONDecodeError):
    return {}
  # waiver: external settings field name, not an internal key
  experts = data.get("experts") or {}
  entry = experts.get(expert) or {}
  # waiver: external settings field name, not an internal key
  return entry.get("git_author") or {}


def _resolve_memory_bot_identity(repo: Path, expert: str) -> tuple[str, str]:
  """
  Compute the `(name, email)` pair the worker uses to author memory commits.

  Resolution order:
  1. `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` env vars (set by the
     expert pump when the worker is called inside a daemon-spawned expert).
  2. `lazy.settings.json[experts][<expert>].git_author` derived identity
     (covers operator-driven invocations like `/lazy-memory.reflect`).
  3. Hard fallback: bare expert name + `<expert>@<bot-domain>`.

  In all cases the `memory.` prefix is applied to both name and email
  local-part so commits land under `memory.<expert>` and downstream
  classifiers can identify them via the email-suffix rule (every email
  whose local-part is `[<prefix>.]*<known-expert>` belongs to that
  expert family).

  Returns:
    A two-tuple of `(name, email)` with the `memory.` prefix applied, ready
    for use as git commit author credentials.
  """
  env_name  = os.environ.get("GIT_AUTHOR_NAME",  "").strip()
  env_email = os.environ.get("GIT_AUTHOR_EMAIL", "").strip()
  if env_name and env_email:
    base_name, base_email = env_name, env_email
  else:
    fm = _load_expert_git_author(repo, expert)
    # waiver: memory-note frontmatter key (canonical home is the note format), not a reusable cross-module key
    base_name  = fm.get("name")  or expert
    # waiver: memory-note frontmatter key (canonical home is the note format), not a reusable cross-module key
    base_email = fm.get("email") or f"{expert}@{_BOT_DOMAIN}"
  # Strip any pre-existing memory.* prefix to avoid memory.memory.foo
  # when the env vars were already memory-prefixed (operator-driven path).
  bare_name  = base_name[len(_MEMORY_PREFIX):]  if base_name.startswith(_MEMORY_PREFIX)  else base_name
  bare_email_local, _, bare_email_domain = base_email.partition("@")
  if bare_email_local.startswith(_MEMORY_PREFIX):
    bare_email_local = bare_email_local[len(_MEMORY_PREFIX):]
  domain = bare_email_domain or _BOT_DOMAIN
  return (f"{_MEMORY_PREFIX}{bare_name}", f"{_MEMORY_PREFIX}{bare_email_local}@{domain}")


def _staged_diff_empty(repo: Path) -> bool:
  """
  Return True when `git diff --cached --quiet` reports nothing staged.

  Used to skip the commit when the write was a true no-op (overwrite of
  a byte-identical note, idempotent re-run, etc.).

  Returns:
    True when the index has no staged changes; False when at least one path is staged.
  """
  result = subprocess.run(
    ["git", "diff", "--cached", "--quiet"],
    cwd = repo, capture_output = True, check = False,
  )
  return result.returncode == 0


def _atomic_commit_memory(
  repo: Path, expert: str, paths: list[Path], title: str,
) -> str | None:
  """
  Stage the memory-touching paths and commit under the memory-bot identity.

  Raises `WriteError` with category `commit-failed` when `git add` or
  `git commit` exits non-zero — the staged index is left as-is so the
  operator can inspect it.

  Returns:
    The new commit SHA (7 hex chars) on success, or `None` when nothing was
    staged (no-op skip).

  Raises:
    WriteError: If staging or committing the paths fails.
  """
  # Filter to existing paths only; skip None / missing entries gracefully
  add_paths = [str(p.relative_to(repo)) for p in paths if p and p.exists()]
  # Also stage deletions: include paths that no longer exist on disk but
  # were in the index (consolidated drops); `git add -A -- <path>` covers
  # both add and delete for the given path-spec.
  removed_paths = [str(p.relative_to(repo)) for p in paths if p and not p.exists()]
  if not add_paths and not removed_paths:
    return None
  add_cmd = ["git", "add", "--", *add_paths, *removed_paths]
  add = subprocess.run(add_cmd, cwd = repo, capture_output = True, check = False)
  # guard: `git add` failure aborts the commit; leave any partial staging for operator inspection
  if add.returncode != 0:
    raise WriteError(
      f"commit-failed: git add returned {add.returncode}: {add.stderr.decode('utf-8', 'replace').strip()}"
    )
  if _staged_diff_empty(repo):
    return None
  name, email = _resolve_memory_bot_identity(repo, expert)
  commit_cmd = [
    "git",
    "-c", f"user.name={name}",
    "-c", f"user.email={email}",
    "-c", "commit.gpgsign=false",
    "commit", "-q", "-m", f"{_MEMORY_PREFIX}{expert}: {title}",
  ]
  commit = subprocess.run(commit_cmd, cwd = repo, capture_output = True, check = False)
  # guard: `git commit` failure leaves the index staged; surface as WriteError
  if commit.returncode != 0:
    raise WriteError(
      f"commit-failed: git commit returned {commit.returncode}: {commit.stderr.decode('utf-8', 'replace').strip()}"
    )
  sha = subprocess.run(
    ["git", "log", "-1", "--format=%h"], cwd = repo, capture_output = True, check = False,
  )
  # waiver: stdlib idiom, not a domain constant
  return sha.stdout.decode("ascii").strip() if sha.returncode == 0 else None


def write_note(repo: Path, expert: str, body: str,
               slug_override: str | None, consolidate: list[str]) -> tuple[Path, str, list[Path]]:
  """
  Persist a memory note for one expert and refresh the tag indexes it touches.

  The note body's frontmatter is parsed and validated before any filesystem change; on any
  validation failure no files are written and no consolidate targets are removed. After a
  successful write, every tag file affected by the union of the note's previous and current
  tags is regenerated, and each consolidate target is best-effort deleted (a missing target
  is logged to stderr and does not abort the call). Git state is not touched here — the
  caller is responsible for committing the returned path set under the memory-bot identity.

  Args:
    repo: Absolute path to the repository root.
    expert: Expert identifier whose memory directory receives the note.
    body: Full note text including its opening YAML frontmatter block.
    slug_override: Explicit slug to use for the note filename; when `None` the slug is derived
      from the frontmatter title and deduplicated against existing notes.
    consolidate: Repo-relative or absolute paths to remove after the note is written. Each
      path must resolve under `.logs/` or `.memory/`.

  Returns:
    A tuple of (note_path, title, touched_paths). `title` is the frontmatter title used in
    the commit subject. `touched_paths` is every path that needs to be staged: the note
    itself, each regenerated tag file (local + global), and each consolidate target (a path
    that no longer exists on disk after this call signals a deletion to stage).

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
  fm, _ = _parse_body_frontmatter(body)
  try:
    validate_frontmatter(fm)
  except FrontmatterError as e:
    raise WriteError(f"frontmatter-invalid: {e}") from e

  # Resolve the per-expert memory directory and ensure it exists
  # waiver: filesystem path/filename idiom, not a domain constant
  memory_root = repo / ".memory"
  expert_dir = memory_root / expert
  expert_dir.mkdir(parents = True, exist_ok = True)

  # Resolve the note slug — honor an explicit override, otherwise derive + deduplicate
  # waiver: memory-note frontmatter key (canonical home is the note format), not a reusable cross-module key
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
      # waiver: memory-note frontmatter key (canonical home is the note format), not a reusable cross-module key
      prev = prev_fm.get("tags") or []
      if isinstance(prev, str):
        prev = [ prev ]
      old_tags = list(prev)

  # Write the note body, ensuring a trailing newline
  note_path.write_text(body if body.endswith("\n") else body + "\n")

  # Regenerate every tag touched by this write — union of old and new tags.
  touched_topics = set()
  # waiver: memory-note frontmatter key (canonical home is the note format), not a reusable cross-module key
  for tag in (fm["tags"] + old_tags):
    try:
      touched_topics.add(topic_from_tag(tag))
    except ValueError:
      continue
  regen_touched_tags(memory_root, expert, touched_topics)

  # Drop consolidate targets — best-effort skip on missing.
  consolidate_paths: list[Path] = []
  for c in consolidate:
    cp = Path(c) if Path(c).is_absolute() else (repo / c)
    consolidate_paths.append(cp)
    try:
      cp.unlink()
    except FileNotFoundError:
      sys.stderr.write(f"consolidate-target-missing: {c}\n")
    except OSError as e:
      raise WriteError(f"consolidate-io-error: {c}: {e}") from e

  # Touched paths the caller must stage: the note + every regenerated tag
  # file (local + global, for the union of old and new tags) + every
  # consolidate target (deletion or missing — `git add -A -- <path>`
  # handles both).
  touched_paths: list[Path] = [note_path]
  for topic in touched_topics:
    # waiver: filesystem path/filename idiom, not a domain constant
    touched_paths.append(memory_root / expert / ".tags" / f"{topic}.md")
    # waiver: filesystem path/filename idiom, not a domain constant
    touched_paths.append(memory_root / ".tags" / f"{topic}.md")
  touched_paths.extend(consolidate_paths)
  # waiver: memory-note frontmatter key (canonical home is the note format), not a reusable cross-module key
  return (note_path, fm["title"], touched_paths)


def _main(argv: list[str]) -> int:
  """
  Command-line entry point for the lazy-memory.write worker.

  Reads the note body from standard input, writes it for the given expert, then commits the
  resulting paths atomically under the memory-bot identity derived from the expert
  (`memory.<expert>` / `memory.<expert>@<bot-domain>`). The resolved note path is printed
  to stdout on success (followed by a tab and the commit SHA when a commit landed, or the
  literal token `no-commit` when the write was a byte-identical no-op); failures print the
  error category to stderr.

  Args:
    argv: Argument vector without the program name. Supports the positional `expert`,
      optional `--slug`, repeatable `--consolidate`, `--repo` (default current directory),
      and `--no-commit` (skip the commit step; used by tests).

  Returns:
    `0` on a successful write (with or without a commit), `2` when the worker raises
    `WriteError`.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import argparse
  # parse the CLI surface — expert positional + optional slug + repeatable consolidate
  parser = argparse.ArgumentParser()
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("expert")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--slug", default = None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--consolidate", action = "append", default = [])
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = ".")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-commit", action = "store_true",
    # waiver: one-off human-facing message
    help = "Skip the atomic commit step (worker leaves changes unstaged for the caller).",
  )
  args = parser.parse_args(argv)
  # body content arrives on stdin
  body = sys.stdin.read()
  repo = Path(args.repo)
  try:
    note_path, title, touched_paths = write_note(
      repo, args.expert, body, args.slug, args.consolidate,
    )
  except WriteError as e:
    sys.stderr.write(f"{e}\n")
    return 2
  if args.no_commit:
    print(str(note_path))
    return 0
  try:
    sha = _atomic_commit_memory(repo, args.expert, touched_paths, title)
  except WriteError as e:
    sys.stderr.write(f"{e}\n")
    return 2
  print(f"{note_path}\t{sha or 'no-commit'}")
  return 0


if __name__ == "__main__":
  raise SystemExit(_main(sys.argv[1:]))
