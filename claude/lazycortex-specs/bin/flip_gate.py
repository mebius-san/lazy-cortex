"""Declarative gate-flip primitive for spec assets.

An asset is a folder `<spec_path>/<category>/<slug>/` holding a status
folder-note `<slug>/<slug>.md` whose frontmatter carries flat boolean
gates (`spec_design_done`, `spec_plan_done`, `spec_develop_done`,
`spec_tests_passing`, `spec_released`) plus a `spec_cancelled` flag.

`flip_gate` moves one gate from false to true (or, with `off`, back to
false). The flip is unconditional on call — `spec.coordinator` (per
`lazy-spec.coordination-playbook.md`) is the sole judge of when a gate is ready
to move, so this primitive no longer gates the mutation on a precondition
table of its own. A cancelled asset still refuses every flip, on or off —
that check is not a sequencing decision, it is the asset's own terminal
state.

Design choice — the `auto` flag controls ONLY the callout annotation; the
primitive always performs the mutation when called.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import iconize_inline  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402
    BOOL_TRUE,
    FLIP_GATE_NAME,
    LOG_CLAUDE,
    LOG_NO_GIT,
    LOG_ROOT,
    FlipResult,
    Gate,
    HistoryEvent,
    PlanReview,
    Section,
    SpecHaltKey,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from summary_render import parent_container_note, apply_container_stats  # noqa: E402


def _today(today: str | None) -> str:
  """
  Return the effective date string for callout and history lines.

  Returns:
    The supplied `today` when given, else the current UTC date in ISO form.
  """
  # guard: caller-supplied date wins so tests pin deterministic output
  if today is not None:
    return today
  return datetime.now(UTC).date().isoformat()


def _parse_frontmatter(text: str) -> tuple[dict, int]:
  """
  Parse the leading YAML frontmatter block of a file's text.

  Returns:
    A two-tuple `(values, fm_end_idx)` where `values` is a flat dict of
    top-level scalar keys and `fm_end_idx` is the index just past the closing
    `---` line; `({}, 0)` when there is no parseable frontmatter.
  """
  if not text.startswith("---\n"):
    return {}, 0
  rest = text[4:]
  end_idx = rest.find("\n---\n")
  if end_idx < 0:
    return {}, 0
  block = rest[:end_idx]
  # waiver: inline numeric literal -- length of the leading '---\n' fence consumed above
  fm_end = 4 + end_idx + len("\n---\n")
  values: dict = {}
  for line in block.splitlines():
    stripped = line.lstrip()
    # guard: skip blank lines and comment / bullet markers
    if not stripped or stripped.startswith(("#", "-")):
      continue
    # guard: skip lines without a key:value separator
    if ":" not in line:
      continue
    k, _, v = line.partition(":")
    k = k.strip()
    # guard: skip entries with an empty key
    if not k:
      continue
    values[k] = v.strip()
  return values, fm_end


def _is_true(values: dict, key: str) -> bool:
  """
  Return whether a frontmatter boolean key reads as true.

  Returns:
    True when the key's value is the literal `true`; False otherwise.
  """
  return values.get(key, "").strip().lower() == BOOL_TRUE


def _set_bool(fm_text: str, key: str, value: bool) -> str:
  """
  Set or insert `key: <true|false>` in a frontmatter block.

  Replaces the existing line in place when the key is present; inserts before
  the closing `---` when absent.

  Returns:
    The updated frontmatter text.
  """
  literal = "true" if value else "false"
  pat = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$")
  if pat.search(fm_text):
    return pat.sub(f"{key}: {literal}", fm_text, count = 1)
  close_idx = fm_text.rfind("---\n")
  # guard: malformed frontmatter without a closing fence
  if close_idx < 0:
    return fm_text
  return fm_text[:close_idx] + f"{key}: {literal}\n" + fm_text[close_idx:]


def _append_under_heading(body: str, heading: str, line: str) -> str:
  """
  Append `line` to the section opened by `heading` in `body`.

  Inserts after the heading and any existing section lines, before the next
  ATX heading (`^#{1,6}\\s`); appends a fresh section at end-of-body when
  the heading is absent. Lines beginning with `#` but no space (e.g.
  `#protected/spec/…` tags) are NOT treated as section boundaries.

  Returns:
    The body text with the new line placed inside the named section.
  """
  lines = body.splitlines()
  head_idx = None
  for i, ln in enumerate(lines):
    if ln.strip() == heading:
      head_idx = i
      break
  # guard: heading missing — append a fresh section
  if head_idx is None:
    suffix = "" if body.endswith("\n") else "\n"
    return body + f"{suffix}\n{heading}\n\n{line}\n"
  insert_at = len(lines)
  for j in range(head_idx + 1, len(lines)):
    # guard: stop before the next real ATX heading; a `#protected/...` tag
    # line has no space after `#` and is NOT a boundary
    if re.match(r"^#{1,6}\s", lines[j]):
      insert_at = j
      break
  # Trim trailing blanks inside the section so the new line sits flush.
  end = insert_at
  while end > head_idx + 1 and not lines[end - 1].strip():
    end -= 1
  new_lines = [*lines[:end], line, *lines[end:]]
  return "\n".join(new_lines) + ("\n" if body.endswith("\n") else "")


def _write_log(asset_dir: Path, gate: str, value: bool, reason: str) -> None:
  """
  Write a run-log file for this flip under the lazy-spec.flip-gate log dir.

  Args:
    asset_dir: The asset folder the flip was applied to.
    gate: The gate key that was flipped.
    value: The boolean the gate was set to.
    reason: Optional human-or-source note recorded with the flip.
  """
  cwd = asset_dir
  sha = _git_field(cwd, ["rev-parse", "HEAD"], LOG_NO_GIT)
  branch = _git_field(cwd, ["rev-parse", "--abbrev-ref", "HEAD"], LOG_NO_GIT)
  ts = datetime.now(UTC)
  stamp = ts.strftime("%Y-%m-%d_%H-%M-%S")
  date_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC")
  log_dir = _repo_root(cwd) / LOG_ROOT / LOG_CLAUDE / FLIP_GATE_NAME
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
  (log_dir / f"{stamp}.md").write_text(body)


def _git_field(cwd: Path, args: list[str], fallback: str) -> str:
  """
  Run a read-only `git` query, returning a fallback on any failure.

  Returns:
    The trimmed git output, or `fallback` when git is unavailable or errors.
  """
  try:
    out = subprocess.run(
        ["git", *args], cwd = cwd, check = True, capture_output = True, text = True,
    )
  except (subprocess.CalledProcessError, FileNotFoundError):
    return fallback
  return out.stdout.strip() or fallback


def _repo_root(cwd: Path) -> Path:
  """
  Resolve the git repo root for log placement, falling back to `cwd`.

  Returns:
    The repository top-level `Path`, or `cwd` when not inside a git repo.
  """
  top = _git_field(cwd, ["rev-parse", "--show-toplevel"], "")
  # guard: not a git repo — log beside the asset
  if not top:
    return cwd
  return Path(top)


def _resolve_review_cli() -> Path | None:
  """
  Resolve the `lazycortex-review` CLI binary, or report that it is unavailable.

  Returns:
    Absolute path to the resolved binary, or None when no plugin directory on the env path
    carries a `bin/lazycortex-review` entry.
  """
  return spec_paths.resolve_plugin_cli(PlanReview.REVIEW_CLI)


_FLIP_AUTHOR_NAME = FLIP_GATE_NAME
_FLIP_AUTHOR_EMAIL = f"{FLIP_GATE_NAME}@bot.invalid"


def _stage_reachable_paths(repo: Path, paths: list[Path] | None) -> list[str]:
  """
  Stage each caller-named path, best-effort, returning only the ones that actually staged.

  A path that was never tracked by git (and no longer exists, having just been deleted from the
  worktree) has nothing for `git add` to stage; that call exits non-zero and the path is
  dropped from the result rather than failing the caller's whole commit.

  Args:
    repo: The repo root to run `git` in.
    paths: Caller-named extra paths to stage, or None.

  Returns:
    The subset of `paths`, as strings, that staged successfully.
  """
  staged = []
  for path in (paths or []):
    result = subprocess.run(
        ["git", "add", "--", str(path)], cwd = str(repo), capture_output = True, check = False,
    )
    if result.returncode == 0:
      staged.append(str(path))
  return staged


def _commit_flip(
    asset_dir: Path, note: Path, gate: str, value: bool, *, extra_paths: list[Path] | None = None,
) -> None:
  """
  Atomically commit the folder-note flip under the `lazy-spec.flip-gate` bot identity.

  Stages the status folder-note (plus the parent container note's stats line, when the flip
  changed its asset count, plus any caller-supplied `extra_paths`) and commits that exact set
  with a deterministic subject naming the gate and its new value. Skipped silently when the
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
    extra_paths: Additional paths to fold into this same commit, named explicitly by the caller
      (e.g. sibling files a rollback already deleted from the worktree). None commits the note
      (and the container note, when refreshed) alone.
  """
  # an empty toplevel means there is no repo to commit into
  top = _git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")
  # guard: asset is not inside a git repository — skip commit (test-fixture path); the file
  # write above remains and is the entire mutation the bare-fixture caller observes
  if not top:
    return

  # the flipped folder-note is the base of the commit set
  repo = Path(top)
  add_paths = [str(note)]

  # the parent container's stats line goes stale on a flip, so refresh it and carry it along
  parent = parent_container_note(asset_dir)
  if parent is not None and apply_container_stats(parent):
    add_paths.append(str(parent))

  # fold the notes' icon repaint into this same commit so no separate icons commit follows
  add_paths.extend(iconize_inline.repaint_paths(
      repo, [str(Path(p).resolve().relative_to(repo.resolve())) for p in add_paths],
  ))

  # the note and container note always exist on disk, so staging them is not best-effort
  subprocess.run(
      ["git", "add", "--", *add_paths],
      cwd = str(repo), check = True, capture_output = True,
  )

  # the caller's own paths (e.g. a rollback's already-deleted plan siblings) join the same
  # commit, best-effort — a caller-named path that was never tracked has nothing to stage
  add_paths.extend(_stage_reachable_paths(repo, extra_paths))

  # commit under the dedicated bot identity so the operator's authorship stays untouched; an
  # explicit pathspec means a stray parked index entry never rides along by accident
  subject = f"{FLIP_GATE_NAME}: {gate} → {str(value).lower()} on {asset_dir.name}"
  subprocess.run(
      [
          "git",
          "-c", f"user.name={_FLIP_AUTHOR_NAME}",
          "-c", f"user.email={_FLIP_AUTHOR_EMAIL}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", subject, "--", *add_paths,
      ],
      cwd = str(repo), check = True, capture_output = True,
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
  Flip one boolean gate on an asset's status folder-note.

  The flip is unconditional on call, `off` or forward alike, except that any flip is refused
  while the asset is cancelled. On success the folder-note frontmatter is rewritten, a `[!gate]`
  callout is appended to `# Gates`, a line is appended to `# History`, and a run-log file is
  written. Halting an asset (`main`'s `--halt`) is a separate primitive, `halt_asset` — it never
  calls this function.

  Args:
    asset_dir: The asset folder holding `<asset_dir.name>.md` and siblings.
    gate: The `spec_*` gate key to flip.
    off: When True, set the gate to false.
    auto: When True, annotate the callout with an `auto:` prefix.
    reason: Optional human-or-source note recorded in the callout.
    today: Optional ISO date pinned into the callout and history line.
    extra_paths: Additional paths to fold into this flip's commit, named explicitly by the
      caller (see `_commit_flip`).

  Returns:
    `{"status": "flipped", "gate": gate, "value": <bool>}` on success, or
    `{"status": "refused", "gate": gate, "reason": <message>}` when refused.
  """
  # the status folder-note's frontmatter carries every gate this function can flip
  note = asset_dir / f"{asset_dir.name}.md"
  text = note.read_text()
  fm_values, fm_end = _parse_frontmatter(text)

  # guard: a cancelled asset refuses every flip, on or off — the asset's own terminal state,
  # not a sequencing precondition
  if _is_true(fm_values, Gate.SPEC_CANCELLED):
    return {FlipResult.STATUS: FlipResult.REFUSED, "gate": gate, "reason": "asset is cancelled"}

  # the flip lands in the frontmatter, its audit trail in the body's callout and history sections
  value = not off
  fm_text = _set_bool(text[:fm_end], gate, value)
  body = text[fm_end:]
  date_str = _today(today)
  note_text = (reason or "auto") if not auto else f"auto: {reason}" if reason else "auto"
  callout = f"> [!gate] {gate} — flipped {date_str} ({note_text})"
  body = _append_under_heading(body, Section.GATES, callout)
  hist = f"- {date_str} — {FLIP_GATE_NAME} · {gate} → {str(value).lower()}"
  body = _append_under_heading(body, Section.HISTORY, hist)
  note.write_text(fm_text + note_explainers.ensure_explainers(body, note_explainers.lang_for_note(note)))

  # Atomic commit of the folder-note edit under the flip-gate bot identity. Without this the
  # daemon's next iteration trips its dirty-tree guard and silently skips every routine until
  # the operator commits by hand.
  _commit_flip(asset_dir, note, gate, value, extra_paths = extra_paths)

  # the run log records the flip, then the caller gets the outcome
  _write_log(asset_dir, gate, value, reason)
  return {FlipResult.STATUS: FlipResult.FLIPPED, "gate": gate, "value": value}


_HALT_CALLOUT_MARK = "[!failure]"

# Result-dict status values emitted by `halt_asset`, mirroring `FlipResult`'s shape for the
# flip primitive (a fresh halt vs. an idempotent repeat carry no precondition-refusal case, so
# there is no third value to model here).
_HALT_STATUS_HALTED = "halted"
_HALT_STATUS_NOOP = "noop"


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

  Mirrors `_commit_flip`'s shape: stage the status folder-note (plus any caller-supplied
  `extra_paths`), commit that exact set under the given bot identity, skip silently when the
  asset is not inside a git repository (the unit-test fixture path). Unlike `_commit_flip`, this
  never refreshes the parent container's stats line — `summary_render._classify` buckets an
  asset by `spec_cancelled` / `spec_released` / the `GATE_ORDER` booleans only, never
  `spec_halted`, so a halt cannot move the count it renders.

  Args:
    asset_dir: The asset folder; used to resolve the enclosing repo root for the `git` cwd.
    note: The folder-note path that was just rewritten.
    reason: The halt reason, folded into the commit subject.
    author_name: The `user.name` the commit lands under.
    author_email: The `user.email` the commit lands under.
    extra_paths: Additional paths to fold into this same commit, named explicitly by the
      caller. None commits the note alone.
  """
  # an empty toplevel means there is no repo to commit into
  top = _git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")
  # guard: asset is not inside a git repository — skip commit (test-fixture path); the file
  # write above remains and is the entire mutation the bare-fixture caller observes
  if not top:
    return

  # the halted folder-note always exists on disk, so staging it is not best-effort
  repo = Path(top)
  add_paths = [str(note)]
  subprocess.run(
      ["git", "add", "--", *add_paths],
      cwd = str(repo), check = True, capture_output = True,
  )

  # the caller's own paths join the same commit, best-effort — a caller-named path that was
  # never tracked has nothing to stage
  add_paths.extend(_stage_reachable_paths(repo, extra_paths))

  # commit under the caller's bot identity so the operator's authorship stays untouched; an
  # explicit pathspec means a stray parked index entry never rides along by accident
  subject = f"{author_name}: halt {asset_dir.name} — {reason}"
  subprocess.run(
      [
          "git",
          "-c", f"user.name={author_name}",
          "-c", f"user.email={author_email}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", subject, "--", *add_paths,
      ],
      cwd = str(repo), check = True, capture_output = True,
  )


def halt_asset_text(
    fm_text: str, body: str, reason: str, *, author_name: str, lang: str,
    today: str | None = None,
) -> tuple[str, str, bool]:
  """
  Pure text transform for halting an asset: no file I/O, no commit.

  Sets `spec_halted: true` in `fm_text`, appends a persistent `> [!failure] asset halted:
  <reason>` callout to `# Gates`, and appends one `# History` line recording the halt.
  Idempotent: an asset already halted with this exact failure callout present returns its
  inputs unchanged. Split out from `halt_asset` so a caller that already owns a single
  write/commit for a larger mutation (e.g. `gate_tick`'s DEAD branch, which also appends its
  own `# History` line in the same folder-note write) can fold the halt into it instead of
  triggering a second, separate commit.

  Args:
    fm_text: The folder-note's frontmatter block text (opening through closing `---` fence).
    body: The folder-note's body text (post-frontmatter).
    reason: Human-readable clause naming what went wrong (see `HaltReason` in `spec_keys.py`).
    author_name: The bot identity's `user.name`, folded into the History line.
    lang: The note's authoring language for the callout and the History line.
    today: Optional ISO date pinned into the History line.

  Returns:
    `(fm_text, body, changed)` — the updated frontmatter and body text, and whether anything
    changed (False on the idempotent no-op, in which case `fm_text` / `body` are the inputs
    unchanged).
  """
  fm_values, _ = _parse_frontmatter(fm_text)
  callout = _halt_callout(reason, lang)

  # guard: already halted with this exact failure recorded — nothing new to say; a callout
  # written under any prior authoring language still counts as recorded
  callout_variants = [
      f"> {_HALT_CALLOUT_MARK} {tail}"
      for tail in note_explainers.history_fragments(HistoryEvent.HALTED_CALLOUT, reason = reason)
  ]
  if _is_true(fm_values, SpecHaltKey.HALTED) and any(variant in body for variant in callout_variants):
    return fm_text, body, False

  # the halt flag lands in the frontmatter, its audit trail in the body's callout and history
  fm_text = _set_bool(fm_text, SpecHaltKey.HALTED, True)
  body = _append_under_heading(body, Section.GATES, callout)
  date_str = _today(today)
  # the localized narrative tail of the History line, in the note's authoring language
  halted_tail = note_explainers.history_line_for_lang(lang, HistoryEvent.HALTED, reason = reason)
  hist = f"- {date_str} — {author_name} · {halted_tail}"
  body = _append_under_heading(body, Section.HISTORY, hist)
  return fm_text, body, True


def halt_asset(
    asset_dir: Path, reason: str, *,
    author_name: str = _FLIP_AUTHOR_NAME, author_email: str = _FLIP_AUTHOR_EMAIL,
    today: str | None = None,
    extra_paths: list[Path] | None = None,
) -> dict:
  """
  Halt an asset, marking it blocked pending operator resolution.

  Un-halting is a manual operator act, out of scope here — the callout is never auto-removed on
  a later tick. Mirrors `flip_gate`'s own shape — the mutation is written and committed here,
  under the given bot identity (default: the `lazy-spec.flip-gate` CLI's own), rather than left for
  the caller to commit. A caller that owns a different bot identity (e.g. `gate_tick`'s DEAD
  branch) passes it through `author_name` / `author_email` so the produced History line and
  commit both read as that caller's own. The mutation itself is `halt_asset_text`; this wrapper
  owns the read/write/commit around it.

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
  # the status folder-note's frontmatter carries the halt flag this function sets
  note = asset_dir / f"{asset_dir.name}.md"
  text = note.read_text()
  _, fm_end = _parse_frontmatter(text)
  fm_text, body, changed = halt_asset_text(
      text[:fm_end], text[fm_end:], reason, author_name = author_name, today = today,
      lang = note_explainers.lang_for_note(note),
  )
  # guard: idempotent no-op — nothing to write or commit
  if not changed:
    return {FlipResult.STATUS: _HALT_STATUS_NOOP, "reason": reason}

  # a fresh halt writes the note, then commits under the caller's bot identity, mirroring
  # `flip_gate`'s own commit-inline shape
  note.write_text(fm_text + note_explainers.ensure_explainers(body, note_explainers.lang_for_note(note)))
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
                      help = "annotate the callout with an auto: prefix")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--reason", default = "",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "note recorded in the gate callout")
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
  # guard: --halt takes an asset straight to the halt primitive, bypassing gate-flip entirely
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
