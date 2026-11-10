"""
Declarative gate-flip primitive for spec assets.

An asset is a folder under `<spec_path>` at any depth — `<spec_path>/<slug>/`,
or `<spec_path>/<folder>/<slug>/` when the type or the caller named a folder —
holding a status folder-note `<slug>/<slug>.md` whose frontmatter carries flat boolean
gates (`spec_design_done`, `spec_plan_done`, `spec_develop_done`,
`spec_tests_passing`, `spec_built`, `spec_released`) plus a `spec_cancelled` flag. The four middle gates
(plan, develop, tests, built) belong to a release note alone; on every other asset `spec_released` is the
only readiness a downstream consumer reads.

A level note — a product's `<spec_path>/<leaf>.md` or the catalog root's
`<vault_root>/<root>.md` — carries the level ladder instead
(`spec_vision_done`, `spec_use_cases_done`, `spec_design_done`,
`spec_ui_design_done`, `spec_tech_done`). The note's own `spec_role` says which ladder it runs, and
a gate off that ladder is refused; `spec_design_done` is the one key both
ladders share, so the role is what tells the two apart. A note declaring no
role at all is read as an asset status note.

`flip_gate` moves one gate from false to true (or, with `off`, back to
false). The flip is unconditional on call — `spec.coordinator` (per
`lazy-spec.coordination-playbook.md`) is the sole judge of when a gate is ready
to move, so this primitive no longer gates the mutation on a precondition
table of its own. A cancelled asset refuses every flip except `spec_cancelled`
turned off — that check is not a sequencing decision, it is the asset's own
cancelled state. The bare primitive moves no document when it clears the flag.

Design choice — the `auto` flag only marks the run log's reason as the
coordinator's own; the primitive always performs the mutation when called.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterable


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import error_report  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import iconize_inline  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    BOOL_FALSE,
    BOOL_TRUE,
    DESIGN_ONLY_GATES,
    FLIP_GATE_NAME,
    FLIPPABLE_GATES,
    LEVEL_ROLES,
    LOG_CLAUDE,
    LOG_NO_GIT,
    LOG_ROOT,
    ROLE_GATES,
    PluginErrorCause,
    AssetTypeKey,
    FlipResult,
    Gate,
    HistoryEvent,
    ReleaseKey,
    Section,
    SpecHaltKey,
    SpecKey,
    SpecMomentKey,
    SpecValue,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from summary_render import parent_container_note, apply_container_stats, is_shelf_note  # noqa: E402

# the moment written beside a gate: a pinned date lands as that day's midnight, the clock's own
# reading is `Z`-suffixed rather than `+00:00`
_MOMENT_MIDNIGHT = "T00:00:00Z"
_UTC_OFFSET = "+00:00"
_UTC_SUFFIX = "Z"

# the markdown suffix the icon repaint reads, and the text encoding git output is decoded with
_MD_SUFFIX = ".md"
_ENCODING = "utf-8"

# Error-ledger incident key a failed icon repaint opens; every failed repaint of the repo folds into it
_REPAINT_INCIDENT = "spec-icon-repaint"

# the bot identity a flip commit lands under, and the default one for a halt commit
_FLIP_AUTHOR_NAME = FLIP_GATE_NAME
_FLIP_AUTHOR_EMAIL = f"{FLIP_GATE_NAME}@bot.invalid"

# The note written into a flip's `[!gate]` callout when no operator reason accompanies it, and
# the prefix the reason carries when the coordinator derived the flip rather than being told.
_AUTO_NOTE = "auto"

_HALT_CALLOUT_MARK = "[!failure]"

# Result-dict status values emitted by `halt_asset`, mirroring `FlipResult`'s shape for the
# flip primitive (a fresh halt vs. an idempotent repeat carry no precondition-refusal case, so
# there is no third value to model here).
_HALT_STATUS_HALTED = "halted"
_HALT_STATUS_NOOP = "noop"


def effective_today(today: str | None) -> str:
  """
  Return the effective date string for callout and history lines.

  Args:
    today: An ISO date pinned by the caller, or None to read the clock.

  Returns:
    The supplied `today` when given, else the current UTC date in ISO form.
  """
  # guard: caller-supplied date wins so tests pin deterministic output
  if today is not None:
    return today
  return datetime.now(UTC).date().isoformat()



def _moment(today: str | None) -> str:
  """
  Return the ISO 8601 UTC moment recorded beside a gate that just turned true.

  Args:
    today: An ISO date pinned by the caller, or None to read the clock.

  Returns:
    `<today>T00:00:00Z` when a date was pinned (deterministic for tests), else the current UTC
    time to the second, `Z`-suffixed.
  """
  # guard: a pinned date yields a pinned moment so tests stay deterministic
  if today is not None:
    return f"{today}{_MOMENT_MIDNIGHT}"
  return datetime.now(UTC).replace(microsecond = 0).isoformat().replace(_UTC_OFFSET, _UTC_SUFFIX)


def parse_frontmatter(text: str) -> tuple[dict, int]:
  """
  Parse the leading YAML frontmatter block of a file's text.

  Args:
    text: The full file text, its frontmatter first when it has one.

  Returns:
    A two-tuple `(values, fm_end_idx)` where `values` is a flat dict of
    top-level scalar keys and `fm_end_idx` is the index just past the closing
    `---` line; `({}, 0)` when there is no parseable frontmatter.
  """
  return spec_frontmatter.parse(text)


def is_true(values: dict, key: str) -> bool:
  """
  Return whether a frontmatter boolean key reads as true.

  Args:
    values: The parsed frontmatter mapping.
    key: The frontmatter key to read.

  Returns:
    True when the key's value is the literal `true`; False otherwise.
  """
  return values.get(key, "").strip().lower() == BOOL_TRUE



def set_bool(fm_text: str, key: str, value: bool) -> str:
  """
  Set or insert `key: <true|false>` in a frontmatter block.

  Replaces the existing line in place when the key is present; inserts before
  the closing `---` when absent.

  Args:
    fm_text: The frontmatter block text, fences included.
    key: The frontmatter key to write.
    value: The boolean to write as its literal.

  Returns:
    The updated frontmatter text.
  """
  return spec_frontmatter.set_scalar(fm_text, key, BOOL_TRUE if value else BOOL_FALSE)


def _drop_scalar(fm_text: str, key: str) -> str:
  """
  Remove the `key: ...` line from a frontmatter block, if present.

  Args:
    fm_text: The frontmatter block text, fences included.
    key: The frontmatter key to remove.

  Returns:
    The frontmatter text without that line; unchanged when the key is absent.
  """
  return re.sub(rf"(?m)^{re.escape(key)}\s*:.*\n", "", fm_text, count = 1)


def append_under_heading(body: str, heading: str, line: str) -> str:
  """
  Append `line` to the section opened by `heading` in `body`.

  Inserts after the heading and any existing section lines, before the next
  ATX heading (`^#{1,6}\\s`); appends a fresh section at end-of-body when
  the heading is absent. Lines beginning with `#` but no space (e.g.
  `#protected/spec/…` tags) are NOT treated as section boundaries, and a
  heading inside a fenced code block is neither the target nor a boundary.
  A fence left unclosed at the end of the body is closed before the line.

  Args:
    body: The note body (post-frontmatter) to insert into.
    heading: The section heading the line belongs under.
    line: The line to append inside that section.

  Returns:
    The body text with the new line placed inside the named section.
  """
  lines = spec_frontmatter.split_lines(body)

  # a heading quoted inside a fenced code block is code, never the section
  fenced = spec_frontmatter.fenced_lines(lines)
  head_idx = next(( idx for idx, row in enumerate(lines) if not fenced[idx] and row.strip() == heading ), None)

  # a fence left open at the end of the body is closed before anything is appended after it,
  # so the new line never lands inside it
  closer = spec_frontmatter.open_fence(lines)

  # guard: heading missing — append a fresh section
  if head_idx is None:
    suffix = "" if body.endswith("\n") else "\n"
    closing = f"{closer}\n" if closer else ""
    return body + f"{suffix}{closing}\n{heading}\n\n{line}\n"
  insert_at = len(lines)
  for pos in range(head_idx + 1, len(lines)):
    # the next real ATX heading closes the section; a `#protected/...` tag
    # line has no space after `#` and is NOT a boundary, and neither is a
    # `#` line quoted inside a fenced code block
    if not fenced[pos] and re.match(r"^#{1,6}\s", lines[pos]):
      insert_at = pos
      break

  # trim trailing blanks inside the section so the new line sits flush
  end = insert_at
  while end > head_idx + 1 and not lines[end - 1].strip():
    end -= 1
  fence_close = [ closer ] if closer and insert_at == len(lines) else []
  new_lines = [*lines[:end], *fence_close, line, *lines[end:]]
  return "\n".join(new_lines) + ("\n" if body.endswith("\n") else "")



def note_role(fm_values: dict) -> str:
  """
  Report which folder-note role the frontmatter declares.

  A note that declares no `spec_role` at all is read as an asset status note, so a pre-role
  folder-note keeps behaving exactly as it did before roles existed.

  Args:
    fm_values: The folder-note's parsed frontmatter values.

  Returns:
    The declared `spec_role` value, or the asset status role when the key is absent or empty.
  """
  return fm_values.get(SpecKey.ROLE, "").strip() or SpecValue.ROLE_STATUS


def _role_refusal(role: str, gate: str) -> str | None:
  """
  Report why a folder-note's role forbids this gate, or nothing when it allows it.

  Args:
    role: The folder-note's own role, as `note_role` resolves it.
    gate: The gate key the caller asked to flip.

  Returns:
    A message naming why the note's role refuses the gate, or None when the flip may proceed.
  """
  # guard: a role outside the three gate-bearing ones carries no ladder to flip at all
  if (allowed := ROLE_GATES.get(role)) is None:
    return f"note role '{role}' carries no gates"

  # guard: the gate belongs to the other ladder — the roles keep the two ladders apart
  if gate not in allowed:
    return f"gate {gate} is not on the '{role}' ladder"
  return None


def _design_only_refusal(fm_values: dict, gate: str, *, off: bool) -> str | None:
  """
  Report why any non-release note forbids opening this gate, or nothing when it allows it.

  Only a release note may open the plan, build, tests and built gates; a note that declares no asset type counts as a
  non-release note. Turning a gate off, and any gate outside those four, is never refused.

  Args:
    fm_values: The folder-note's parsed frontmatter values.
    gate: The gate key the caller asked to flip.
    off: Whether the caller turns the gate off rather than on.

  Returns:
    A message naming the refused middle gate, or None when the flip may proceed.
  """

  # Domain(spec.lifecycle):
  # # Only a release builds
  # Every asset type but the release has stopped carrying its own implementation: its ladder
  # ends when its start document is approved, and the release that later ships it closes its
  # release checkpoint. The four middle checkpoints — plan, development, tests, built — therefore
  # belong to a release note alone, and asking to open one on any other asset note — a note that
  # declares no type at all included — is refused. Turning such a checkpoint off is never refused, because a
  # note that still carries one from before the rule only needs it cleared.

  # only opening one of the four middle gates is release-only; every other flip stays allowed
  if off or gate not in DESIGN_ONLY_GATES:
    return None

  # a release note runs the full ladder by design; every other note, untyped included, is design-only
  if fm_values.get(AssetTypeKey.TYPE, "").strip() == ReleaseKey.ASSET_TYPE:
    return None
  return f"gate {gate} is not on a design-only ladder"


def _write_log(asset_dir: Path, gate: str, value: bool, reason: str) -> None:
  """
  Write a run-log file for this flip under the lazy-spec.flip-gate log dir.

  Args:
    asset_dir: The asset folder the flip was applied to.
    gate: The gate key that was flipped.
    value: The boolean the gate was set to.
    reason: Optional human-or-source note recorded with the flip.
  """
  sha = git_field(asset_dir, ["rev-parse", "HEAD"], LOG_NO_GIT)
  branch = git_field(asset_dir, ["rev-parse", "--abbrev-ref", "HEAD"], LOG_NO_GIT)
  now = datetime.now(UTC)
  stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
  date_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
  log_dir = repo_root(asset_dir) / LOG_ROOT / LOG_CLAUDE / FLIP_GATE_NAME
  log_dir.mkdir(parents = True, exist_ok = True)
  body = (
      "---\n"
      f"git_sha: {sha}\n"
      f"git_branch: {branch}\n"
      f"date: {date_str}\n"
      f"input: flip-gate {asset_dir.name} {gate} (value={value}, reason={reason or 'none'})\n"
      "---\n\n"
      "# lazy-spec.flip-gate\n\n"
      "## Actions\n\n"
      f"- flipped `{gate}` → {str(value).lower()} on `{asset_dir.name}`\n\n"
      "## Result\n\n"
      f"- success — `{gate}` set to {str(value).lower()}\n"
  )
  spec_paths.write_text_atomic((log_dir / f"{stamp}.md"), body)


def git_field(cwd: Path, args: list[str], fallback: str) -> str:
  """
  Run a read-only `git` query, returning a fallback on any failure.

  Args:
    cwd: The directory the query runs in.
    args: The git arguments, without the leading `git`.
    fallback: The value returned when git is unavailable or errors.

  Returns:
    The trimmed git output, or `fallback` when git is unavailable or errors.
  """
  try:
    out = subprocess.run(
        ["git", *args], cwd = cwd, check = True, capture_output = True, text = True, encoding = "utf-8",
    )
  except (subprocess.CalledProcessError, FileNotFoundError):
    return fallback
  return out.stdout.strip() or fallback


def repo_root(cwd: Path) -> Path:
  """
  Resolve the git repo root for log placement, falling back to `cwd`.

  Args:
    cwd: The directory the lookup starts from.

  Returns:
    The repository top-level `Path`, or `cwd` when not inside a git repo.
  """
  top = git_field(cwd, ["rev-parse", "--show-toplevel"], "")

  # guard: not a git repo — log beside the asset
  if not top:
    return cwd
  return Path(top)


def committable_paths(repo: Path, paths: Iterable[Path | str]) -> list[str]:
  """
  Select the paths a pathspec commit can carry, registering brand-new files for it.

  Guarantees:
    - Each returned path keeps the caller's spelling and the caller's order.
    - No content is added to the shared git index: a new file is registered as intent-to-add only.

  Notes:
    - A path that is untracked and gone from disk is dropped from the result.
    - Every other untracked path is registered with `git add -N` so a pathspec can name it.

  Args:
    repo: The repository root the paths are resolved against.
    paths: The candidate paths, repo-relative or absolute.

  Returns:
    The subset of `paths` that can join a pathspec commit, as strings.

  Raises:
    subprocess.CalledProcessError: If registering a new file with `git add -N` fails.
  """

  # Contract:
  # Each returned path keeps the caller's spelling, and the result keeps the caller's order.

  # Contract:
  # No file content is ever added to the shared git index;
  # a brand-new file is registered as intent-to-add only.

  # the registrations themselves are the caller's to keep; only the committable set is returned
  return _register_paths(repo, paths)[0]


def _register_paths(repo: Path, paths: Iterable[Path | str]) -> tuple[list[str], list[str]]:
  """
  Select the paths a pathspec commit can carry and report which of them this call registered.

  Notes:
    - A path that is untracked and gone from disk is dropped.
    - Every other untracked path is registered with `git add -N`, which stages no content.

  Args:
    repo: The repository root the paths are resolved against.
    paths: The candidate paths, repo-relative or absolute.

  Returns:
    The kept paths as strings, in the caller's spelling and order, and the subset of them this call registered
    as intent-to-add.

  Raises:
    subprocess.CalledProcessError: If registering a new file with `git add -N` fails.
  """
  # the paths that may join a pathspec commit, each kept in the caller's own spelling, and the
  # brand-new ones among them this call registered
  kept = []
  registered = []
  for path in paths:
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", str(path)],
        cwd = str(repo), capture_output = True, check = False,
    ).returncode == 0

    # guard: a path gone from the worktree and unknown to git has nothing to commit
    if not (repo / path).exists() and not tracked:
      continue

    # a brand-new file is registered as intent-to-add, which stages none of its content, so the
    # pathspec commit can name it at all
    if not tracked:
      subprocess.run(["git", "add", "-N", "--", str(path)], cwd = str(repo), check = True, capture_output = True)
      registered.append(str(path))
    kept.append(str(path))
  return kept, registered


def commit_exact(repo: Path, paths: Iterable[Path | str], *, author_name: str | None, author_email: str | None,
                 subject: str) -> None:
  """
  Commit exactly the committable subset of `paths` under the given author identity.

  Guarantees:
    - The operator's staged entries stay staged and out of the commit.
    - A rejected commit resets exactly the intent-to-add entries this call registered, leaving the shared git
      index as it was found.
    - No commit is made when no path is committable, so an empty pathspec never commits the whole index.

  Notes:
    - Commit signing is off for this commit.
    - Brand-new files among `paths` are registered as intent-to-add, which stages no content.
    - An identity half given as None keeps the ambient git identity for that half.

  Args:
    repo: The repository root.
    paths: The candidate paths; those that are untracked and gone from disk drop out.
    author_name: The `user.name` the commit lands under, or None for the ambient one.
    author_email: The `user.email` the commit lands under, or None for the ambient one.
    subject: The commit subject.

  Raises:
    subprocess.CalledProcessError: If the commit fails.
  """

  # Contract:
  # The operator's staged entries MUST stay staged and out of the commit;
  # the commit carries the named paths and nothing else.

  # Contract:
  # A rejected commit resets exactly the intent-to-add entries this call registered
  # and leaves the shared git index as it was found; the failure is re-raised unchanged.

  # Contract:
  # When no path is committable, NO commit is made;
  # an empty pathspec NEVER falls through to committing the whole index.

  # the pathspec the commit carries, new files registered and vanished strangers dropped
  pathspec, registered = _register_paths(repo, paths)

  # guard: an empty pathspec would commit the whole shared index, the operator's staging included
  if not pathspec:
    return

  # a pathspec commit takes these paths' worktree content and nothing else from the index; the
  # operator's staged entries stay staged, and git itself rolls the index back on a rejection
  try:
    subprocess.run(
        [
            "git",
            *_identity_config(author_name, author_email),
            "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", subject, "--", *pathspec,
        ],
        cwd = str(repo), check = True, capture_output = True,
    )

  # a rejected commit takes back the intent-to-add entries this call made, so the index is left
  # exactly as found; the failure itself is re-raised as it arrived
  except subprocess.CalledProcessError:
    if registered:
      subprocess.run(
          ["git", "reset", "-q", "--", *registered], cwd = str(repo), check = False, capture_output = True,
      )
    raise


def _identity_config(author_name: str | None, author_email: str | None) -> list[str]:
  """
  Build the per-command git config flags that pin a commit's identity.

  Args:
    author_name: The `user.name` to pin, or None to keep the ambient one.
    author_email: The `user.email` to pin, or None to keep the ambient one.

  Returns:
    The `-c user.*` flag pairs for the values given; empty when both are None.
  """
  # each pinned value becomes one `-c` pair; an absent one leaves git's own identity in force
  flags: list[str] = []
  if author_name is not None:
    flags.extend([ "-c", f"user.name={author_name}" ])
  if author_email is not None:
    flags.extend([ "-c", f"user.email={author_email}" ])
  return flags


def _query_untracked_under(repo: Path, rel_paths: list[str]) -> list[str]:
  """
  List the untracked, non-ignored files inside the directories among `rel_paths`.

  Args:
    repo: The repository root.
    rel_paths: Repo-relative paths, some of which may be directories.

  Returns:
    The untracked files under those directories, repo-relative; empty when none is a directory.
  """
  dirs = [ path for path in rel_paths if (repo / path).is_dir() ]

  # guard: a pathspec of files alone names every file it carries already
  if not dirs:
    return []

  # a tracked directory's brand-new files are invisible to a pathspec commit until registered
  listed = subprocess.run(
      [ "git", "ls-files", "--others", "--exclude-standard", "-z", "--", *dirs ],
      cwd = str(repo), check = True, capture_output = True, text = True, encoding = _ENCODING,
  )
  return [ entry for entry in listed.stdout.split("\0") if entry ]


def commit_paths_detail(repo: Path, paths: Iterable[Path | str], *,
                        subject: str,
                        author_name: str | None,
                        author_email: str | None,
                        repaint: bool = True,
                        deferred_write: tuple[Path, str] | None = None) -> tuple[bool, list[str], list[str]]:
  """
  Commit exactly `paths`, the icon repaint optionally folded in, and report what the commit carried.

  A directory among the paths carries every file under it, brand-new ones included.

  Guarantees:
    - No commit is made when `repo` is not a git repository or a path lies outside `repo`.
    - No commit is made when the paths hold no change against the last commit.
    - The operator's staged entries never ride along; the commit carries the named paths and nothing else.
    - An empty pathspec never commits the whole index.
    - A repaint failure never raises and is reported to the error ledger; a later repaint that runs without failing
      closes that incident.
    - The path of a `deferred_write` always joins the commit set, so the write is carried by the commit and never
      left behind as a dirty path.

  Notes:
    - New files under the paths are registered as intent-to-add only, which stages no content.
    - A `deferred_write` lands after the repaint, so a process death during the repaint leaves the previously
      committed file untouched.

  Args:
    repo: The repository root.
    paths: The paths to commit, absolute or repo-relative; a directory carries every file under it.
    subject: The commit subject.
    author_name: The `user.name` the commit lands under, or None for the ambient identity.
    author_email: The `user.email` the commit lands under, or None for the ambient identity.
    repaint: Whether the icon repaint of the markdown paths joins the commit.
    deferred_write: An optional `(path, text)` written after the repaint; its path always joins the commit set.

  Returns:
    Whether a commit was made, the repo-relative paths it carried, and the repainted paths among them.

  Raises:
    subprocess.CalledProcessError: If the commit fails.
  """

  # Contract:
  # The operator's staged entries MUST stay staged and out of the commit;
  # the commit carries the named paths and nothing else.

  # Contract:
  # An empty pathspec NEVER falls through to committing the whole index.

  # Contract:
  # When `repo` is not a git repository, or a named path lies outside `repo`, NO commit is made.

  # Contract:
  # When the paths hold no change against the last commit, NO commit is made.

  # Contract:
  # A failing icon repaint NEVER raises out of this call and is NEVER silent: the failure is reported
  # to the error ledger, and the commit proceeds without the repainted paths.
  # A later repaint that runs without failing closes that incident.

  # Contract:
  # The path of a `deferred_write` ALWAYS joins the commit set,
  # so the write is carried by the commit and never left behind as a dirty path.

  # the held-back write's own path joins the commit set, so the write it makes is always carried
  named = [ *paths, *( [ deferred_write[0] ] if deferred_write is not None else [] ) ]
  candidates = [ Path(path) if Path(path).is_absolute() else repo / path for path in named ]

  # guard: no git repository, or a path outside it, means nothing to commit into
  if not git_field(repo, [ "rev-parse", "--show-toplevel" ], "") or any(
      not path.resolve().is_relative_to(repo.resolve()) for path in candidates):
    return False, [], []

  # the repaint of the markdown paths rides the same commit so no second, foreign-identity commit follows
  rel_paths = list(dict.fromkeys(path.resolve().relative_to(repo.resolve()).as_posix() for path in candidates))
  notes = [ path for path in rel_paths if path.endswith(_MD_SUFFIX) ]
  try:
    repainted = iconize_inline.repaint_paths_checked(repo, notes) if repaint and notes else []
  # waiver: best-effort boundary — a cosmetic repaint never gates the commit it rides with, so a failed one is
  # reported to the error ledger and drops the repainted paths only
  except (OSError, RuntimeError, ValueError) as error:
    # waiver: a stdlib exception carries no class_name accessor; its class name is the varying detail of the report
    error_report.report_marked_warning(repo, cause = PluginErrorCause.ICON_REPAINT_FAILED,
                                       incident = _REPAINT_INCIDENT, detail = f"{type(error).__name__}: {error}")
    repainted = []
  else:
    # a repaint that ran proves an earlier failed one cleared
    if repaint and notes:
      error_report.resolve_marked(repo, _REPAINT_INCIDENT)
  all_paths = list(dict.fromkeys([ *rel_paths, *repainted ]))

  # the held-back write lands here, past the slow repaint step and one step away from the commit
  if deferred_write is not None:
    spec_paths.write_text_atomic(deferred_write[0], deferred_write[1])

  # guard: an empty pathspec would reach the whole tree
  if not all_paths:
    return False, [], []

  # what the paths carry against the last commit
  status = subprocess.run([ "git", "status", "--porcelain", "--", *all_paths ], cwd = str(repo), check = True,
                          capture_output = True, text = True, encoding = _ENCODING)

  # guard: a run that changed no byte commits nothing
  if not status.stdout.strip():
    return False, [], []

  # the commit, under the given identity and these paths alone, the shared index left to the operator
  commit_exact(repo, [ *all_paths, *_query_untracked_under(repo, all_paths) ], author_name = author_name,
               author_email = author_email, subject = subject)
  return True, all_paths, repainted


def commit_paths(repo: Path, paths: Iterable[Path | str], *,
                 subject: str,
                 author_name: str | None,
                 author_email: str | None,
                 repaint: bool = True,
                 deferred_write: tuple[Path, str] | None = None) -> bool:
  """
  Commit exactly `paths` under the given identity, the icon repaint optionally folded in.

  The bool form of `commit_paths_detail`, with the same guarantees.

  Args:
    repo: The repository root.
    paths: The paths to commit, absolute or repo-relative; a directory carries every file under it.
    subject: The commit subject.
    author_name: The `user.name` the commit lands under, or None for the ambient identity.
    author_email: The `user.email` the commit lands under, or None for the ambient identity.
    repaint: Whether the icon repaint of the markdown paths joins the commit.
    deferred_write: An optional `(path, text)` written after the repaint; its path always joins the commit set.

  Returns:
    True when a commit was made.

  Raises:
    subprocess.CalledProcessError: If the commit fails.
  """
  return commit_paths_detail(
      repo, paths, subject = subject, author_name = author_name, author_email = author_email,
      repaint = repaint, deferred_write = deferred_write,
  )[0]


def containers_above(asset_dir: Path) -> list[Path]:
  """
  List the container notes whose stats region an asset's flip moved, innermost first.

  A group folder is transparent to the container tally, so a product's own counts read straight
  through every such folder between it and the asset — each note along that chain reports a
  count this flip just changed. The chain ends at the first note running a ladder of its own,
  and never reaches the catalog root, whose region counts products rather than assets.

  Args:
    asset_dir: The asset folder the flip landed on.

  Returns:
    The enclosing folder's own note, then one note per shelf folder above it, ending with the
    first level note reached; empty when no folder-note encloses the asset.
  """

  # Domain(spec.lifecycle):
  # # A flip refreshes every summary that counted the asset
  # An asset's move along its ladder changes the reading of every summary that counts it, and a
  # folder that merely holds assets without running a ladder of its own is counted through
  # rather than counted, so the same asset appears in the totals of each place above it up to
  # the one that answers for its own contents. Refreshing only the folder immediately holding
  # the asset would leave those wider totals stating a distribution that no longer exists. The
  # walk upward stops at the first place that runs a ladder of its own, because everything
  # above that point counts whole products rather than individual assets, and a single asset's
  # step forward moves nothing in that reading.

  containers: list[Path] = []
  current = asset_dir
  while (container := parent_container_note(current)) is not None:
    containers.append(container)

    # guard: a level note answers for its own region — nothing above it counted this asset
    if not is_shelf_note(container):
      break
    current = container.parent
  return containers


def _commit_flip(
    asset_dir: Path, note: Path, gate: str, value: bool, *,
    role: str = SpecValue.ROLE_STATUS, extra_paths: list[Path] | None = None,
) -> None:
  """
  Atomically commit the folder-note flip under the `lazy-spec.flip-gate` bot identity.

  Commits the folder-note by pathspec (plus the stats line of every container note that counted
  this asset — the enclosing group note, every shelf above it, and the product note that reads
  through them — when the flip changed a count and the note is an asset's own, plus any
  caller-supplied `extra_paths`), leaving the operator's staged entries untouched, with a
  deterministic subject naming the gate and its new value. Skipped silently when the
  asset does not live inside a git repository (the unit-test fixture path, where the worker is
  exercised against a bare tmp dir). The daemon always runs the routine inside the operator's
  repo, so production reaches the commit branch every time. Any subprocess error inside the
  commit branch propagates — the flip is a state mutation the caller promised was atomic, and
  silently swallowing a commit failure would leave the daemon's dirty-tree guard tripping every
  subsequent iteration with no visible cause.

  Args:
    asset_dir: The asset folder; used to resolve the enclosing repo root for the `git` cwd.
    note: The folder-note path that was just rewritten.
    gate: The gate key that was flipped.
    value: The boolean value the gate was set to.
    role: The folder-note's own role. A level role skips the container climb entirely: a
      level note's own stats are recomputed by its children's flips, never by its own, and the
      folder above a level note is another level's root, whose region no flip below rewrites —
      an asset's flip does refresh the product root it sits in, but a product's own flip moves
      nothing in the count of products above it.
    extra_paths: Additional paths to fold into this same commit, named explicitly by the caller
      (e.g. sibling files a rollback already deleted from the worktree). A path that was never
      tracked and is gone from disk drops out. None commits the note (and the container note,
      when refreshed) alone.
  """
  # an empty toplevel means there is no repo to commit into
  top = git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")

  # guard: asset is not inside a git repository — skip commit (test-fixture path); the file
  # write above remains and is the entire mutation the bare-fixture caller observes
  if not top:
    return

  # the flipped folder-note is the base of the commit set
  repo = Path(top)
  add_paths = [str(note)]

  # every container note that counted this asset goes stale on a flip, so refresh each and carry
  # it along — the group note for a grouped asset, then every shelf above it, up to and including
  # the product note that reads through them; a level note's own flip refreshes nothing, since
  # its stats are its children's flips to recompute and the level above it counts products by
  # role, which no gate flip on this note moves
  for container in (() if role in LEVEL_ROLES else containers_above(asset_dir)):
    if apply_container_stats(container):
      add_paths.append(str(container))

  # fold the notes' icon repaint into this same commit so no separate icons commit follows
  add_paths.extend(iconize_inline.repaint_paths(
      repo, [str(Path(path).resolve().relative_to(repo.resolve())) for path in add_paths],
  ))

  # commit under the dedicated bot identity so the operator's authorship stays untouched; the
  # caller's own paths (e.g. a rollback's already-deleted plan siblings) join the same commit,
  # and one that was never tracked and is gone from disk drops out
  subject = f"{FLIP_GATE_NAME}: {gate} → {str(value).lower()} on {asset_dir.name}"
  commit_exact(
      repo, [ *add_paths, *(extra_paths or []) ],
      author_name = _FLIP_AUTHOR_NAME, author_email = _FLIP_AUTHOR_EMAIL, subject = subject,
  )


def flip_gate(
    asset_dir: Path,
    gate: str,
    *,
    off: bool = False,
    auto: bool = False,
    reason: str = "",
    today: str | None = None,
    extra_paths: list[Path] | None = None,
) -> dict:
  """
  Flip one boolean gate on an asset's status folder-note or on a level note.

  The flip is unconditional on call, `off` or forward alike, except for refusals of a gate the
  note may not carry or may not move in its current state. Each refuses before anything is
  written, leaving the folder-note byte-identical. On success the folder-note
  frontmatter is rewritten and a run-log file is written — a level note takes the same
  treatment an asset note does. Nothing is
  written to `# History` or `# Gates`: the gate's state is its frontmatter boolean, the flip's
  reason lives in the run log, and a gate flip is the mechanics of the ladder, not an event the
  operator reads the journal for. Halting an asset (`main`'s `--halt`) is a separate primitive,
  `halt_asset` — it never calls this function.

  Guarantees:
    - A refusal leaves the folder-note file byte-identical; nothing is written until every
      refusal check has passed.
    - A cancelled asset accepts exactly one flip, `spec_cancelled` turned off; every other flip, on or off, is
      refused.

  Args:
    asset_dir: The asset or level folder holding `<asset_dir.name>.md` and siblings.
    gate: The `spec_*` gate key to flip, from the ladder the note's role carries.
    off: When True, set the gate to false.
    auto: When True, mark the run log's reason with an `auto:` prefix.
    reason: Optional human-or-source note recorded in the run log.
    today: Optional ISO date pinned into the frontmatter moment recorded beside a gate that
      just turned true.
    extra_paths: Additional paths to fold into this flip's commit, named explicitly by the
      caller (see `_commit_flip`).

  Returns:
    `{"status": "flipped", "gate": gate, "value": <bool>}` on success, or
    `{"status": "refused", "gate": gate, "reason": <message>}` when refused.
  """

  # Contract:
  # A refusal — an unknown gate name, a gate outside the note's own role ladder, or a flip
  # refused on a cancelled asset — leaves the folder-note file byte-identical; nothing is
  # written until every refusal check has passed.

  # Contract:
  # A cancelled asset accepts exactly one flip, `spec_cancelled` turned off;
  # every other flip, on or off, is refused.

  # Domain(spec.lifecycle):
  # # Two gate ladders, one shared checkpoint
  # An asset that ships its own deliverable moves through six yes/no checkpoints — design, plan, development, tests
  # passing, built, and release — plus a cancelled flag that, while raised, freezes the ladder: no checkpoint moves,
  # whichever were already met, until the cancellation itself is cleared again. A product, or the whole catalog, runs
  # a different five-checkpoint ladder instead — vision, use cases, design, UI design, and technical readiness —
  # because it accumulates approved decisions rather than shipping one deliverable. Which ladder a note runs is the
  # note's own declared stance, not a guess from its position in the tree; a checkpoint belonging to the other ladder
  # is refused outright. Design readiness is the one checkpoint both ladders share, which is why it means the same
  # thing wherever it appears. Moving a checkpoint, forward or back, is never conditioned on a readiness check of its
  # own — that judgement is made once, elsewhere, by whatever decided the move belongs on the ladder now; this
  # mechanic only records the outcome.

  # guard: a name outside the two ladders is a caller typo, refused before the note is read —
  # writing it would leave an invented boolean in the frontmatter that nothing ever reads
  if gate not in FLIPPABLE_GATES:
    return {FlipResult.STATUS: FlipResult.REFUSED, "gate": gate, "reason": f"unknown gate: {gate}"}

  # the folder-note's frontmatter carries every gate this function can flip
  note = asset_dir / f"{asset_dir.name}.md"
  text = spec_paths.read_text(note)
  fm_values, fm_end = parse_frontmatter(text)

  # the note's own role decides which of the two ladders it runs
  role = note_role(fm_values)

  # guard: a gate off the note's own ladder is refused before anything is written
  if (role_refusal := _role_refusal(role, gate)) is not None:
    return {FlipResult.STATUS: FlipResult.REFUSED, "gate": gate, "reason": role_refusal}

  # guard: a middle gate on a typed design-only asset is refused — only a release note runs the full ladder
  if (design_only_refusal := _design_only_refusal(fm_values, gate, off = off)) is not None:
    return {FlipResult.STATUS: FlipResult.REFUSED, "gate": gate, "reason": design_only_refusal}

  # guard: a cancelled asset refuses every flip, on or off, but the un-cancel itself — the asset's
  # own state, not a sequencing precondition
  if is_true(fm_values, Gate.SPEC_CANCELLED) and not (off and gate == Gate.SPEC_CANCELLED):
    return {FlipResult.STATUS: FlipResult.REFUSED, "gate": gate, "reason": "asset is cancelled"}

  # the flip lands in the frontmatter together with its moment: a gate turning true records
  # when beside itself, a gate turning false drops that moment. Nothing goes to `# History` —
  # a gate flip is the mechanics of the ladder, not an event the operator reads the journal for
  value = not off
  fm_text = set_bool(text[:fm_end], gate, value)
  moment_key = f"{gate}{SpecMomentKey.AT_SUFFIX}"
  fm_text = (
      spec_frontmatter.set_scalar(fm_text, moment_key, _moment(today)) if value
      else _drop_scalar(fm_text, moment_key)
  )

  # the run-log line for this flip: an automatic flip names itself, and carries the caller's
  # reason behind that name when there is one; a manual flip carries the reason alone
  note_text = f"{_AUTO_NOTE}: {reason}" if auto and reason else (_AUTO_NOTE if auto else reason or _AUTO_NOTE)

  # the healed note: the flipped frontmatter over the untouched body with its explainers ensured
  body = text[fm_end:]
  new_text = fm_text + note_explainers.ensure_explainers(body, note_explainers.lang_for_note(note))

  # write and commit only when the note actually changed — a gate already at this value leaves
  # it byte-identical, there is no history line to add, and a commit of nothing would fail
  if new_text != text:
    spec_paths.write_text_atomic(note, new_text)

    # atomic commit of the folder-note edit under the flip-gate bot identity; without this the
    # daemon's next iteration trips its dirty-tree guard and silently skips every routine until
    # the operator commits by hand
    _commit_flip(asset_dir, note, gate, value, role = role, extra_paths = extra_paths)

  # the run log records the flip and its reason, then the caller gets the outcome
  _write_log(asset_dir, gate, value, note_text)
  return {FlipResult.STATUS: FlipResult.FLIPPED, "gate": gate, "value": value}


def _halt_callout(reason: str, lang: str) -> str:
  """
  Build the persistent failure callout appended to `# Gates` on a halt.

  Args:
    reason: Human-readable clause naming what went wrong.
    lang: The note's authoring language for the callout's narrative tail.

  Returns:
    The `> [!failure] <halted: reason>` line (no trailing newline), tail localized.
  """
  callout_tail = note_explainers.history_line_for_lang(lang, HistoryEvent.HALTED_CALLOUT, reason = reason)
  return f"> {_HALT_CALLOUT_MARK} {callout_tail}"


def _commit_halt(
    asset_dir: Path, note: Path, reason: str, *,
    author_name: str, author_email: str, extra_paths: list[Path] | None = None,
) -> None:
  """
  Atomically commit the asset-halt mutation under the given bot identity.

  Mirrors `_commit_flip`'s shape: commit the status folder-note (plus any caller-supplied
  `extra_paths`) by pathspec under the given bot identity, leaving the operator's staged
  entries untouched, skip silently when the
  asset is not inside a git repository (the unit-test fixture path). Unlike `_commit_flip`, this
  never refreshes the parent container's stats line — `summary_render.classify` buckets an
  asset by `spec_cancelled` / `spec_released` / the `GATE_ORDER` booleans only, never
  `spec_halted`, so a halt cannot move the count it renders.

  Args:
    asset_dir: The asset folder; used to resolve the enclosing repo root for the `git` cwd.
    note: The folder-note path that was just rewritten.
    reason: The halt reason, folded into the commit subject.
    author_name: The `user.name` the commit lands under.
    author_email: The `user.email` the commit lands under.
    extra_paths: Additional paths to fold into this same commit, named explicitly by the
      caller. A path that was never tracked and is gone from disk drops out. None commits the
      note alone.
  """
  # an empty toplevel means there is no repo to commit into
  top = git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")

  # guard: asset is not inside a git repository — skip commit (test-fixture path); the file
  # write above remains and is the entire mutation the bare-fixture caller observes
  if not top:
    return

  # commit the halted folder-note under the caller's bot identity so the operator's authorship
  # stays untouched; the caller's own paths join the same commit, and one that was never
  # tracked and is gone from disk drops out
  commit_exact(
      Path(top), [ note, *(extra_paths or []) ],
      author_name = author_name, author_email = author_email,
      subject = f"{author_name}: halt {asset_dir.name} — {reason}",
  )


def halt_asset_text(
    fm_text: str, body: str, reason: str, *, lang: str,
    today: str | None = None,
) -> tuple[str, str, bool]:
  """
  Text transform for halting an asset: no file I/O of its own, no commit.

  Sets `spec_halted: true` in `fm_text`, appends a persistent `> [!failure] asset halted:
  <reason>` callout to `# Gates`, and appends one `# History` line recording the halt.
  Idempotent: an asset already halted with this exact failure callout present returns its
  inputs unchanged. Split out from `halt_asset` so a caller that already owns a single
  write/commit for a larger mutation (e.g. `gate_tick`'s DEAD branch, which also appends its
  own `# History` line in the same folder-note write) can fold the halt into it instead of
  triggering a second, separate commit.

  Guarantees:
    - When the asset is already halted with this exact failure reason recorded, the call is a
      no-op: `fm_text` and `body` are returned unchanged and `changed` is False.

  Args:
    fm_text: The folder-note's frontmatter block text (opening through closing `---` fence).
    body: The folder-note's body text (post-frontmatter).
    reason: Human-readable clause naming what went wrong (see `HaltReason` in `spec_keys.py`).
    lang: The note's authoring language for the callout and the History line.
    today: Optional ISO date pinned as the History line's day group.

  Returns:
    `(fm_text, body, changed)` — the updated frontmatter and body text, and whether anything
    changed (False on the idempotent no-op, in which case `fm_text` / `body` are the inputs
    unchanged).

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot
      be resolved.
  """

  # Contract:
  # When the asset is already halted with this exact failure reason recorded (under any
  # historical authoring language), the call is a no-op: `fm_text` and `body` are returned
  # unchanged and `changed` is False.

  fm_values, _ = parse_frontmatter(fm_text)
  callout = _halt_callout(reason, lang)

  # a callout written under any prior authoring language still counts as recorded
  callout_variants = [
      f"> {_HALT_CALLOUT_MARK} {tail}"
      for tail in note_explainers.history_fragments(HistoryEvent.HALTED_CALLOUT, reason = reason)
  ]

  # guard: already halted with this exact failure recorded — nothing new to say
  if is_true(fm_values, SpecHaltKey.HALTED) and any(variant in body for variant in callout_variants):
    return fm_text, body, False

  # the halt flag lands in the frontmatter, its audit trail in the body's callout and history
  fm_text = set_bool(fm_text, SpecHaltKey.HALTED, True)
  body = append_under_heading(body, Section.GATES, callout)

  # the localized narrative line, in the note's authoring language, placed by the shared verb
  halted_tail = note_explainers.history_line_for_lang(lang, HistoryEvent.HALTED, reason = reason)
  body = history_journal.append(body, halted_tail, effective_today(today))
  return fm_text, body, True


def halt_asset(
    asset_dir: Path, reason: str, *,
    author_name: str = _FLIP_AUTHOR_NAME, author_email: str = _FLIP_AUTHOR_EMAIL,
    today: str | None = None,
    extra_paths: list[Path] | None = None,
) -> dict:
  """
  Halt an asset pending operator resolution.

  Un-halting is a manual operator act, out of scope here — the callout is never auto-removed on
  a later tick. Mirrors `flip_gate`'s own shape — the mutation is written and committed here,
  under the given bot identity (default: the `lazy-spec.flip-gate` CLI's own), rather than left for
  the caller to commit. A caller that owns a different bot identity (e.g. `gate_tick`'s DEAD
  branch) passes it through `author_name` / `author_email` so the produced History line and
  commit both read as that caller's own. The mutation itself is `halt_asset_text`; this wrapper
  owns the read/write/commit around it.

  Guarantees:
    - Once set, the halt persists until an operator resolves it by hand; nothing in this
      codebase clears `spec_halted` or its failure callout automatically.

  Args:
    asset_dir: The asset folder holding `<asset_dir.name>.md`.
    reason: Human-readable clause naming what went wrong (see `HaltReason` in `spec_keys.py`).
    author_name: The bot identity's `user.name`, folded into the History line and the commit.
    author_email: The bot identity's `user.email`, used for the commit only.
    today: Optional ISO date pinned into the History line.
    extra_paths: Additional paths to fold into this halt's commit, named explicitly by the
      caller (see `_commit_halt`).

  Returns:
    `{"status": "halted", "reason": reason}` on a fresh halt, or `{"status": "noop", "reason":
    reason}` when the asset was already halted with this exact failure recorded.
  """

  # Contract:
  # Once an asset is halted, nothing in this codebase clears the halt automatically — the
  # `spec_halted` flag and its failure callout persist until an operator resolves them by hand.

  # Domain(spec.lifecycle):
  # # Halting a stuck asset
  # When the automation carrying an asset forward cannot make progress — a change could not be
  # folded in cleanly, a cleanup step left the asset half-finished — the asset is marked halted
  # instead of retried silently. A halted asset stops being picked up as more work to sequence until
  # an operator has looked at it; nothing automated clears the mark on its own. Recording the same
  # failure a second time changes nothing — the mark and its explanation are written once and left
  # alone, so retrying the same broken condition does not pile up duplicate records of it.

  # the status folder-note's frontmatter carries the halt flag this function sets
  note = asset_dir / f"{asset_dir.name}.md"
  text = spec_paths.read_text(note)
  _, fm_end = parse_frontmatter(text)
  fm_text, body, changed = halt_asset_text(
      text[:fm_end], text[fm_end:], reason, today = today,
      lang = note_explainers.lang_for_note(note),
  )

  # guard: idempotent no-op — nothing to write or commit
  if not changed:
    return {FlipResult.STATUS: _HALT_STATUS_NOOP, "reason": reason}

  # a fresh halt writes the note, then commits under the caller's bot identity, mirroring
  # `flip_gate`'s own commit-inline shape
  spec_paths.write_text_atomic(
      note, fm_text + note_explainers.ensure_explainers(body, note_explainers.lang_for_note(note)))
  _commit_halt(
      asset_dir, note, reason,
      author_name = author_name, author_email = author_email, extra_paths = extra_paths,
  )
  return {FlipResult.STATUS: _HALT_STATUS_HALTED, "reason": reason}


def main(argv: list[str]) -> int:
  """
  Flip a gate on an asset from the command line, printing the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on a flip or a halt, 1 on a refusal, 2 when the asset note is missing or
    neither `gate` nor `--halt` was given.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs flip-gate")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_dir", type = Path)
  # waiver: argparse CLI signature -- positional argument, optional so `--halt` can stand alone
  parser.add_argument("gate", nargs = "?", default = None)
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--off", action = "store_true",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "set the gate to false")
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--auto", action = "store_true",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "mark the run-log reason with an auto: prefix")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--reason", default = "",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "reason recorded in the run log")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--halt", default = None,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "halt the asset with the given reason, instead of flipping a gate")
  args = parser.parse_args(argv)
  asset_dir: Path = args.asset_dir.resolve()
  note = asset_dir / f"{asset_dir.name}.md"

  # guard: asset status folder-note must exist
  if not note.is_file():
    sys.stderr.write(f"no status folder-note: {note}\n")
    return 2

  # --halt takes an asset straight to the halt primitive, bypassing gate-flip entirely
  if args.halt is not None:
    result = halt_asset(asset_dir, args.halt)
    print(json.dumps(result))
    return 0

  # guard: neither a gate nor --halt was given — nothing to do
  if args.gate is None:
    # waiver: one-off human-facing message -- CLI usage error, not a reusable token
    sys.stderr.write("either a gate or --halt is required\n")
    return 2
  result = flip_gate(
      asset_dir, args.gate, off = args.off, auto = args.auto, reason = args.reason,
  )
  print(json.dumps(result))
  return 0 if result[FlipResult.STATUS] == FlipResult.FLIPPED else 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
