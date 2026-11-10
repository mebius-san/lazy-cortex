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

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# resolve the shared memory_runtime helpers from this flat bin/ directory

_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
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

  # Domain(runtime.memory):
  # # Consolidating ephemeral sources once a fact is captured in memory
  # Once a fact has been written into a permanent memory note, the ephemeral material it was
  # distilled from — a run-log entry, or an older piece of memory state — may be deleted as
  # part of the same write. That deletion is confined to the memory subsystem's own two
  # trees, the run-log journal and the memory store itself; a consolidate target reaching
  # anywhere else in the repository is refused, so writing a note can never be used to delete
  # unrelated repository content.

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


# waiver: deliberate copy of constants.BOT_EMAIL_DOMAIN (sans "@") — skill-shipped script, no bin/ import path
_BOT_DOMAIN = "bot.invalid"
_MEMORY_PREFIX = "memory."


def _load_expert_git_author(repo: Path, expert: str) -> dict:
  """
  Read `lazy.settings.json[experts][<expert>].git_author` from the worktree.

  Used as the base identity from which the memory-bot identity is derived.
  Returns an empty dict when the file or entry is missing — the caller
  decides whether that is fatal.

  Args:
    repo: Absolute path to the repository worktree root.
    expert: Expert name as registered in `lazy.settings.json[experts]`.

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
    data = json.loads(settings_path.read_text(encoding = "utf-8"))
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

  Args:
    repo: Absolute path to the repository worktree root.
    expert: Expert name as registered in `lazy.settings.json[experts]`.

  Returns:
    A two-tuple of `(name, email)` with the `memory.` prefix applied, ready
    for use as git commit author credentials.
  """

  # Domain(runtime.bot-identity):
  # # Memory-bot identity is the expert's own identity under a `memory.` layer
  # A memory-subsystem commit is authored by an identity derived from the expert whose
  # memory changed, never by the expert's own base identity — every name and every email's
  # local part carries a `memory.` prefix so the commit is unmistakably a memory-subsystem
  # write rather than the expert's ordinary work. The base identity is resolved once, then
  # the prefix is applied idempotently: if the base identity already carries the prefix (for
  # example when the caller runs inside an already memory-attributed process) it is stripped
  # first, so the layer is applied exactly once rather than compounding. Downstream tooling
  # that classifies commits by author recognizes any email whose local part matches the
  # expert's name preceded by zero or more `memory.` prefixes as belonging to that expert's
  # memory-writing activity.

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

  # strip any pre-existing memory.* prefix to avoid memory.memory.foo
  # when the env vars were already memory-prefixed (operator-driven path).
  bare_name  = base_name[len(_MEMORY_PREFIX):]  if base_name.startswith(_MEMORY_PREFIX)  else base_name
  bare_email_local, _, bare_email_domain = base_email.partition("@")
  if bare_email_local.startswith(_MEMORY_PREFIX):
    bare_email_local = bare_email_local[len(_MEMORY_PREFIX):]
  domain = bare_email_domain or _BOT_DOMAIN
  return (f"{_MEMORY_PREFIX}{bare_name}", f"{_MEMORY_PREFIX}{bare_email_local}@{domain}")


def _query_tracked_paths(repo: Path, paths: list[str]) -> set[str]:
  """
  Return the subset of `paths` that git tracks.

  Args:
    repo: Absolute path to the repository worktree root.
    paths: Repo-relative paths to look up.

  Returns:
    The repo-relative paths among `paths` that git tracks.
  """
  result = subprocess.run(
    ["git", "-c", "core.quotePath=false", "ls-files", "--", *paths],
    cwd = repo, capture_output = True, text = True, check = False,
  )
  return set(result.stdout.splitlines())


def _is_diff_empty(repo: Path, paths: list[str]) -> bool:
  """
  Return True when the worktree matches HEAD on every one of `paths`.

  Tell a true no-op write, such as a byte-identical overwrite or an idempotent re-run, from a real change.
  Only the given paths are compared, so unrelated changes elsewhere in the repository never count.

  Args:
    repo: Absolute path to the repository worktree root.
    paths: Repo-relative paths this write touched.

  Returns:
    True when none of `paths` differs from HEAD; False when at least one does.
  """
  result = subprocess.run(
    ["git", "diff", "--quiet", "HEAD", "--", *paths],
    cwd = repo, capture_output = True, check = False,
  )
  return result.returncode == 0


def _atomic_commit_memory(
  repo: Path, expert: str, paths: list[Path], title: str,
) -> str | None:
  """
  Commit the memory-touching paths under the memory-bot identity.

  The commit carries exactly the write's own paths, so content other writers parked in the shared index stays
  unpublished, and a byte-identical write makes no commit.

  Notes:
    - A path git does not yet track is registered in the index as an intent-to-add entry, which holds no content.
    - A path missing on disk is committed as a deletion only when git tracks it.
    - When the commit fails, the intent-to-add entries the call registered are withdrawn, so the index is left as
      it was before the call while the changes stay in the worktree.

  Args:
    repo: Absolute path to the repository worktree root.
    expert: Expert identifier used to resolve the memory-bot commit identity.
    paths: Candidate paths to commit; entries missing on disk count as deletions when git tracks them.
    title: Note title used to build the commit subject.

  Returns:
    The new commit SHA (7 hex chars) on success, or `None` when there was nothing to commit.

  Raises:
    WriteError: With a `commit-failed` message when registering new files or committing fails.
  """
  # split the candidates into files on disk and files gone from it; a gone file only counts
  # when git tracks it (a consolidated drop), since a path git never knew has nothing to delete
  present_paths = [str(p.relative_to(repo)) for p in paths if p and p.exists()]
  gone_paths = [str(p.relative_to(repo)) for p in paths if p and not p.exists()]
  tracked = _query_tracked_paths(repo, [*present_paths, *gone_paths])
  removed_paths = [p for p in gone_paths if p in tracked]

  # guard: no file on disk and no tracked deletion leaves nothing to commit
  if not present_paths and not removed_paths:
    return None

  # Domain(runtime.git-safety):
  # # A memory write never uses the shared staging area
  # The repository's staging area is shared with the operator and with other writers, so a memory write
  # never places its content there. A file the write created is only announced to version control with an
  # intent-to-add registration, which carries no content. The commit names the write's own paths explicitly
  # and takes their content directly from the working tree, never from what happens to be staged. A path
  # removed from disk counts as a deletion only when version control already knows it. When the commit
  # fails, the write withdraws its own registrations, so the staging area is left exactly as it was before
  # the write, while the changes stay in the working tree. A write identical to the last committed content
  # produces no commit.

  # the write's own footprint — every git verb below is limited to it, because the index is
  # shared and whatever else sits there belongs to the operator or another routine
  own_paths = [*present_paths, *removed_paths]

  # a file this write created is registered with intent-to-add, which stages no content; the
  # commit's pathspec then carries every path straight from the worktree, so the operator's
  # index never holds this write's content, not even when the commit fails
  new_paths = [p for p in present_paths if p not in tracked]
  if new_paths:
    add = subprocess.run([ "git", "add", "-N", "--", *new_paths ], cwd = repo, capture_output = True, check = False)

    # guard: a failed registration aborts the commit before anything is published
    if add.returncode != 0:
      raise WriteError(
        f"commit-failed: git add -N returned {add.returncode}: {add.stderr.decode('utf-8', 'replace').strip()}"
      )

  # guard: a byte-identical write leaves nothing to commit
  if _is_diff_empty(repo, own_paths):
    return None

  # commit the write's own paths under the memory-bot identity, straight from the worktree
  name, email = _resolve_memory_bot_identity(repo, expert)
  commit_cmd = [
    "git",
    "-c", f"user.name={name}",
    "-c", f"user.email={email}",
    "-c", "commit.gpgsign=false",
    "commit", "-q", "-m", f"{_MEMORY_PREFIX}{expert}: {title}", "--", *own_paths,
  ]
  # git ranks inherited GIT_AUTHOR_* / GIT_COMMITTER_* above `-c user.*`, so the memory-bot identity is pinned in
  # the environment too — otherwise a daemon-spawned expert's own identity would author the commit unprefixed
  commit_env = {
    **os.environ,
    "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
    "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
  }
  commit = subprocess.run(commit_cmd, cwd = repo, env = commit_env, capture_output = True, check = False)

  # guard: `git commit` failure withdraws this write's intent-to-add entries, so the index is left as it
  # was before the write while the changes stay in the worktree; surface as WriteError
  if commit.returncode != 0:
    if new_paths:
      subprocess.run([ "git", "reset", "-q", "--", *new_paths ], cwd = repo, capture_output = True, check = False)
    raise WriteError(
      f"commit-failed: git commit returned {commit.returncode}: {commit.stderr.decode('utf-8', 'replace').strip()}"
    )

  # report the short SHA of the commit that just landed
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

  Guarantees:
    - Validation completes before any filesystem write; on failure, no note file is
      written and no consolidate target is removed.
    - Every tag file for a topic in the note's previous or current tags is regenerated.
    - Git state is never touched; committing the returned paths under the memory-bot
      identity is entirely the caller's responsibility.

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
    the commit subject. `touched_paths` is every path the caller must commit: the note
    itself, each regenerated tag file (local + global), and each consolidate target (a path
    that no longer exists on disk after this call is a deletion to commit).

  Raises:
    WriteError: If any consolidate path escapes the allowed roots, the frontmatter is missing
      or invalid, or a consolidate target fails to delete for a reason other than not being
      present.
  """
  repo = Path(repo)

  # Contract:
  # All validation — consolidate-path safety and frontmatter well-formedness — MUST
  # complete before any filesystem write; on any validation failure, no note file is
  # written and no consolidate target is removed.

  # validate consolidate paths up front; refuse the whole op if any
  # would escape .logs/ or .memory/.
  for c in consolidate:
    cp = Path(c) if Path(c).is_absolute() else (repo / c)

    # guard: refuse the whole op when any consolidate target escapes the safe roots
    if not _is_safe_consolidate_path(repo, cp):
      raise WriteError(f"consolidate-out-of-scope: {c}")

  # parse and validate the frontmatter block embedded in the body
  fm, _ = _parse_body_frontmatter(body)
  try:
    validate_frontmatter(fm)
  except FrontmatterError as e:
    raise WriteError(f"frontmatter-invalid: {e}") from e

  # resolve the per-expert memory directory and ensure it exists
  # waiver: filesystem path/filename idiom, not a domain constant
  memory_root = repo / ".memory"
  expert_dir = memory_root / expert
  expert_dir.mkdir(parents = True, exist_ok = True)

  # resolve the note slug — honor an explicit override, otherwise derive + deduplicate
  # waiver: memory-note frontmatter key (canonical home is the note format), not a reusable cross-module key
  base = slug_override or slugify(fm["title"])
  if slug_override is not None:
    slug = base
  else:
    slug = resolve_slug(expert_dir, base)
  note_path = expert_dir / f"{slug}.md"

  # Contract:
  # Every tag file for a topic in either the note's previous tags or its current tags
  # MUST be regenerated, so a topic dropped from the note never resolves through a stale
  # tag file.

  # capture old tags BEFORE overwriting so we can regenerate retagged files.
  old_tags: list[str] = []
  if note_path.exists():
    prev_fm = _read_note_frontmatter(note_path)
    if prev_fm:
      # waiver: memory-note frontmatter key (canonical home is the note format), not a reusable cross-module key
      prev = prev_fm.get("tags") or []
      if isinstance(prev, str):
        prev = [ prev ]
      old_tags = list(prev)

  # write the note body, ensuring a trailing newline
  note_path.write_text(body if body.endswith("\n") else body + "\n", encoding = "utf-8")

  # regenerate every tag touched by this write — union of old and new tags.
  touched_topics = set()
  # waiver: memory-note frontmatter key (canonical home is the note format), not a reusable cross-module key
  for tag in (fm["tags"] + old_tags):
    try:
      touched_topics.add(topic_from_tag(tag))
    except ValueError:
      continue
  regen_touched_tags(memory_root, expert, touched_topics)

  # drop consolidate targets — best-effort skip on missing.
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

  # Contract:
  # `write_note` NEVER touches git state; committing the returned paths under the
  # memory-bot identity is entirely the caller's responsibility.

  # touched paths the caller must commit: the note + every regenerated tag
  # file (local + global, for the union of old and new tags) + every
  # consolidate target (deletion or missing — the commit's pathspec
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
      optional `--slug`, repeatable `--consolidate`, and `--repo` (default current directory).

  Returns:
    `0` on a successful write (with or without a commit), `2` when the worker raises
    `WriteError`.
  """
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

  # commit what the write touched under the memory-bot identity, then report the note and the sha
  try:
    sha = _atomic_commit_memory(repo, args.expert, touched_paths, title)
  except WriteError as e:
    sys.stderr.write(f"{e}\n")
    return 2
  print(f"{note_path}\t{sha or 'no-commit'}")
  return 0


if __name__ == "__main__":
  raise SystemExit(_main(sys.argv[1:]))
