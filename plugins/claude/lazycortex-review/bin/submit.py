"""
`/lazy-review.submit <file> [--expert <name>]` — open a document
for review skipping the opening main-writer round.

Same bootstrap as `start` (`review_active: true`, `review_round: 1`,
`review_approved: false`, Waiting banner, `review_result` cleared),
plus a skip-seed: `review_main_done` is pre-filled with every main
writer of the document, `review_round` advances by that count, and
`review_phase` lands on `awaiting-operator` — the coordinator's own
bootstrap-on-`review-entry` (`lazy-review.coordination-playbook.md` §
"Opening the loop") sees an already-settled main round and the
document goes straight to the operator's Ready banner. A document that carries a non-empty
`[!todo] #review/command` callout is not leapfrogged: it lands on `review_phase: main` with an
empty `review_main_done` and an unadvanced round, so the writer round runs on the command first. A document of a
report class is never leapfrogged either: it enters the same writer state, so its implementer reads the report and
records a verdict before the operator is shown the two decision boxes.

`--expert` (optional) writes `review_expert` — a per-document
override of the class `experts.main`. When given, the seeded writer
set is `[expert]`; otherwise it is the class's `experts.main` list,
resolved from the repo's settings (`.claude/lazy.settings.json` with its
local overlay merged on, as core reads them).

The commit carries a `Doc-Review-Phase: initial` trailer. It is made under the review bot identity, so the
coordinator watch does not treat it as an operator edit that resets the settled state submit just applied, unless
the running job sets its own author identity (`GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` in the environment, as a
daemon expert job does); that identity then authors it. Commit signing stays off either way.

Returns 0 on success, 2 when the file is not a markdown file, 3 when an
`--expert` is given that is not in the global experts table, 4 when the
file matches no configured review class (and no `--expert` given to
seed from).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import atomic_io as _atomic_io  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import core_settings as _core_settings  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import doc_class as _doc_class  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import job_markers as _job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_ops as _note_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
import parser as _parser  # noqa: E402  # pylint: disable=import-error,wrong-import-position,deprecated-module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from errors import SettingsReadError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from keys import BotIdentity, Bucket, JobKey, Phase, ReviewKey, Trailer  # noqa: E402
# waiver: deferred sibling imports follow the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import start as _start  # noqa: E402  # pylint: disable=import-error,wrong-import-position

# The bare YAML boolean literal a set frontmatter flag carries, as `frontmatter.py` writes it.
_YAML_TRUE = "true"

# Git's per-path magic prefix that makes one path argument a literal name. A git call that can run a hook marks its
# paths with it; the global `--literal-pathspecs` option would reach the hook's environment.
_LITERAL_MAGIC = ":(literal)"


def _load_settings(settings_root: Path) -> dict:
  """
  Read the `review` and `experts` sections for a settings root as core sees them, local overlay merged.

  Notes:
    - Core routes each section: the daemon-read `experts` section comes from the checkout toplevel, and `review`
      from the nearest settings root `settings_root`.

  Args:
    settings_root: The nearest settings root of the document.

  Returns:
    Settings-shaped dict holding the merged `review` and `experts` sections, or `{}` when the
    settings are unreadable.

  Raises:
    RuntimeError: When no core CLI is resolvable.
  """
  # an unreadable settings layer registers nothing, exactly as an absent one does
  try:
    return _core_settings.read_merged_sections(settings_root, JobKey.REVIEW, JobKey.EXPERTS)
  except SettingsReadError:
    return {}


def _parse_main_done(value: str | None) -> list[str]:
  """
  Parse the `review_main_done` frontmatter value into a list of flat writer names.

  Accepts a bracketed inline list (`[a, b]` / `[]`) or a bare comma-separated
  form (`a, b`) for hand-edited fixtures. `None`, absent, or empty brackets
  produce an empty list.

  Args:
    value: Raw `review_main_done` frontmatter value, or `None` when the key is absent.

  Returns:
    List of flat writer name strings committed in the current round.
  """
  # guard: an absent key means no writer has committed yet; there is nothing to strip or split
  if value is None:
    return []

  # the bracketed inline form and the bare comma-separated form differ only by the enclosing brackets
  raw = value.strip()
  if raw.startswith("[") and raw.endswith("]"):
    raw = raw[1:-1]

  # empty items, from `[]` or a trailing comma, are not writer names
  return [item.strip() for item in raw.split(",") if item.strip()]


def _serialize_main_done(names: list[str]) -> str:
  """
  Render a `review_main_done` list to its bracketed inline form (`[a, b]` / `[]`).

  Args:
    names: Flat writer names to serialize.

  Returns:
    Serialized string ready to write verbatim into frontmatter.
  """
  return "[" + ", ".join(names) + "]"


def open_submit(
    file_path: Path,
    *,
    expert: str | None = None,
    main_writers: list[str],
    report: bool = False,
) -> bool:
  """
  Open a document for review as entry into a new cycle, skipping the opening writer round when it can.

  Normally leaves the document with every main writer already marked done, the round counter advanced past
  them, and the banner showing the operator's Ready state. This is the exact state the coordinator's own
  bootstrap-on-`review-entry` produces when every main writer of the round has already spoken
  (`lazy-review.coordination-playbook.md` § "Opening the loop").

  This matches the lazy-review.submit contract: the operator hands a document whose body diffs are already
  pre-authored (a machine writer wrote them outside the review loop), and submit lands the document on the
  operator's Ready banner without dispatching the opening writer round. A document that carries an open
  operator command, and a document of a report class, instead enters the writer state, with the writer round
  still owed.

  Guarantees:
    - Always leaves `review_approved` false: a submit is entry into a new cycle, so the document is never
      opened already approved, whatever a stopped cycle left behind.
    - A document carrying a non-empty `[!todo] #review/command` callout is never leapfrogged: it lands on
      `review_phase: main` with an empty done-list and an unadvanced round, and its banner shows the
      writer round as owed.
    - A document of a report class (`report` set) is never leapfrogged either: it lands in the same writer state,
      and its banner waits for the implementer's answer with no decision box.
    - Submitting a report clears the verdict recorded for it in the marker sidecar, a stopped cycle's included.
    - Submitting a document that already carries `review_active: true` is a no-op: nothing is written and
      the call returns `False`.

  Args:
    file_path: The markdown document to bootstrap.
    expert: Optional per-document main-writer override; writes `review_expert` when provided.
    main_writers: Flat-name list to mark done — `[expert]` when an override is given, else
      the class `experts.main` names. The caller resolves this set.
    report: Whether the document belongs to a report class; it then enters the writer state, so its implementer
      records a verdict first, and its banner waits for that answer.

  Returns:
    `True` if the document changed; `False` for a document already opted in or on an idempotent re-run.
  """

  # Domain(review.lifecycle):
  # # Submitting skips the opening writer round
  # A document whose body was already authored outside the review loop does not need the
  # round machine's opening writer round run over it. Submitting marks every writer of that
  # round done in one shot — either the single writer given as an override, or the
  # document's whole configured writer set for that round — and advances the round counter
  # past all of them at once, reaching the round machine's post-main-settled state directly
  # instead of only after each of those writers had actually run. The document surfaces on
  # the operator's own waiting state rather than dispatching that round's writers.
  # Submitting is entry into a new review cycle, so the document never enters it approved,
  # whatever a stopped cycle left behind. One exception to the skip is a document that
  # carries a pending operator command: the command is the opening round's input, so nothing
  # is skipped. The document enters in the writer state of the opening phase, with an empty
  # list of finished writers and the round counter not advanced, and the operator is never
  # shown "ready to approve" while that writer round is still owed.
  # A report is the other exception: its implementer owes a verdict on it before the operator
  # can decide, so a submitted report enters the same writer state, the implementer reads it
  # and records a verdict at once, and the banner waits for that answer.
  # A document that is already in its review loop is left exactly as it is: submitting it changes nothing at all.

  text = _atomic_io.read_text(file_path)

  # Contract:
  # Submitting a document that already carries `review_active: true` is a no-op:
  # nothing is written and the call returns `False`.

  # guard: a document already opted in is in its review loop, so submit leaves it untouched
  if str(_fm.parse(text)[0].get(ReviewKey.ACTIVE, "")).strip().lower() == _YAML_TRUE:
    return False

  # Reuse start's bootstrap (review_active / round / approved / banner /
  # review_result and autorun-key clear / optional review_expert).
  _start.open_review(file_path, expert=expert)  # bootstrap, writes in place, no commit

  # Contract:
  # Submitting a report clears the verdict recorded for it in the marker sidecar, so its implementer's turn records
  # a fresh one before the operator is shown a decision box.

  # a report's implementer answers afresh on every submit, so no verdict recorded before survives it
  if report:
    _job_markers.clear_verdict(_query_repo_root_for(file_path), file_path)

  # the edits run on LF text; the document's own ending comes back once, on write
  bootstrapped, ending = _atomic_io.to_lf(_atomic_io.read_text(file_path))
  meta, _body = _fm.parse(bootstrapped)

  # Contract:
  # A submit ALWAYS leaves `review_approved` false: it is entry into a new cycle, so the
  # document is never opened already approved, whatever a stopped cycle left behind.

  # entering a new cycle is never entering it approved, whatever a stopped cycle left behind
  # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
  # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
  new_text = _note_ops.set_key(bootstrapped, ReviewKey.APPROVED, False)  # type: ignore[attr-defined]

  # Idempotency: detect already-settled state. A document stopped in `review_phase: awaiting-operator`
  # with every requested main writer already present in `review_main_done` has its writers' round done;
  # re-seeding it would re-bump `review_round`.
  current_done_flat = { _parser.flatten_expert_name(n) for n in _parse_main_done(meta.get(ReviewKey.MAIN_DONE)) }
  already_settled = (
      meta.get(ReviewKey.PHASE) == Bucket.AWAITING_OPERATOR
      and all(_parser.flatten_expert_name(n) in current_done_flat for n in main_writers)
  )

  # Contract:
  # A document carrying a non-empty `[!todo] #review/command` callout is NEVER leapfrogged:
  # it lands on `review_phase: main` with an empty done-list and an unadvanced round, so the
  # writer round runs on the command first and the banner shows that round as owed.

  # Contract:
  # A document of a report class is NEVER leapfrogged: it lands in the same writer state, so its
  # implementer records a verdict before the operator is shown a decision box.

  # a pending operator command is the opening round's input, and a report's implementer owes its verdict first,
  # so the writer round runs instead of the leapfrog
  # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
  # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
  if report or _note_ops.has_open_command(bootstrapped):  # type: ignore[attr-defined]
    # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
    # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
    new_text = _note_ops.set_key(new_text, ReviewKey.PHASE, Phase.MAIN)  # type: ignore[attr-defined]
    # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
    # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
    new_text = _note_ops.set_key(  # type: ignore[attr-defined]
        new_text, ReviewKey.MAIN_DONE, _serialize_main_done([]))
  elif not already_settled:
    # submit always seeds the FULL main-writer set in one shot, so the done-set
    # covers every main writer by construction — the phase always lands on
    # awaiting-operator (unlike the coordinator's own per-writer cleanup, which
    # can leave the phase at `main` when writers remain).
    flat_writers = [_parser.flatten_expert_name(n) for n in main_writers]
    # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
    # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
    new_text = _note_ops.set_key(  # type: ignore[attr-defined]
        new_text, ReviewKey.MAIN_DONE, _serialize_main_done(flat_writers))
    new_round = int(meta.get(ReviewKey.ROUND, 1)) + max(1, len(main_writers))
    # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
    # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
    new_text = _note_ops.set_key(new_text, ReviewKey.ROUND, new_round)  # type: ignore[attr-defined]
    # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
    # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
    new_text = _note_ops.set_key(new_text, ReviewKey.PHASE, Bucket.AWAITING_OPERATOR)  # type: ignore[attr-defined]

  # the banner follows the state just seated, and the file is rewritten only when the entry moved it
  # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
  # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
  new_text = _note_ops.repaint_banner(  # type: ignore[attr-defined]
      new_text, lang = _note_ops.resolve_language(file_path), report = report)  # type: ignore[attr-defined]
  if new_text != bootstrapped:
    _atomic_io.write_text_atomic(file_path, _atomic_io.restore_ending(new_text, ending))
  return _atomic_io.read_text(file_path) != text


def _resolve_main_writers(file_path: Path, expert: str | None) -> list[str] | None:
  """
  Resolve the writer set to pre-seed into `review_main_done`.

  Args:
    file_path: The document being submitted, used to locate its review class.
    expert: Per-document main-writer override; when provided the result is `[expert]`.

  Returns:
    List of expert names to seed, or `None` when no review class matches and no expert was given.
  """
  if expert:
    return [expert]
  settings_root = _core_settings.query_settings_root_for(file_path)
  class_cfg = _doc_class.class_for_file(_load_settings(settings_root), settings_root, file_path)
  if not class_cfg:
    return None
  return [m[JobKey.NAME] for m in (class_cfg.get(JobKey.EXPERTS, {}).get(Phase.MAIN) or [])]


def _is_expert_known(file_path: Path, expert: str) -> bool:
  """
  Check whether an expert name is registered in the global experts table.

  Args:
    file_path: Any file inside the repo, used to locate `lazy.settings.json`.
    expert: Expert name to look up.

  Returns:
    `True` if the name exists in the global experts table; `False` otherwise.
  """
  return expert in (_load_settings(_core_settings.query_settings_root_for(file_path)).get(JobKey.EXPERTS) or {})


def _query_repo_root_for(file_path: Path) -> Path:
  """
  Locate the repository root for the given file.

  Args:
    file_path: Any file; the checkout holding its folder is resolved.

  Returns:
    The root of the checkout the file sits in, a linked worktree's own root inside one; `file_path.parent` when
    it is not inside a git repository.
  """
  # the checkout git names for the file's folder, else the folder itself
  return _review_locator.query_checkout_toplevel(file_path.parent)


def _atomic_commit(file_path: Path) -> None:
  """
  Stage and commit the file with the initial-phase trailer.

  The commit is made under the review bot identity, unless the running job sets its own author identity
  (`GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` in the environment, as a daemon expert job does), in which case that
  identity authors it. Commit signing stays off either way.

  Args:
    file_path: The submitted document; only this file is committed, and its file name is taken literally, never as
      a pattern.
  """
  # the document is staged under its literal name, never as a pattern; the name is marked per path, so the hooks
  # these calls run see no global pathspec option in their environment
  subprocess.run(
      ["git", "add", "--", f"{_LITERAL_MAGIC}{file_path.name}"],
      cwd = file_path.parent, check = True, capture_output = True,
  )

  # the pathspec keeps a concurrently staged foreign file out of the submit commit; the review bot identity makes
  # it a system commit, so the coordinator watch does not read it as an operator edit that resets the settled
  # state submit just applied; the bot's flags also keep the operator's commit signing off a key it does not own
  subprocess.run(
      [
          "git", *_git_ops.author_flags({ JobKey.NAME: BotIdentity.NAME, JobKey.EMAIL: BotIdentity.EMAIL }),
          "commit", "-q",
          "-m", f"review: submit {file_path.name}",
          "-m", f"{Trailer.PHASE}: {Phase.INITIAL}",
          "--", f"{_LITERAL_MAGIC}{file_path.name}",
      ],
      cwd = file_path.parent, check = True, capture_output = True,
  )


def main(argv: list[str]) -> int:
  """
  Open a document for review skipping the opening writer round.

  Guarantees:
    - The submit commit is authored by the review bot identity, unless the running job sets its own author identity
      through `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL`, in which case that identity authors it; commit signing is
      always off.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 success, 2 not-markdown, 3 unknown expert, 4 no review class.
  """

  # Contract:
  # The submit commit is authored by the review bot identity, unless the running job sets its own author identity
  # through `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL`, in which case that identity authors it. Commit signing is
  # always off.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.submit")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file", type=Path)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--expert", default=None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-commit", action="store_true",
                      # waiver: argparse CLI signature, not a domain key
                      help="apply mutations but do not commit")
  args = parser.parse_args(argv)
  file_path: Path = args.file.resolve()

  # guard: the named path is missing or is not a markdown document
  # waiver: filesystem path idiom
  if not file_path.exists() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2

  # guard: an explicit `--expert` that the experts table does not know
  if args.expert and not _is_expert_known(file_path, args.expert):
    sys.stderr.write(f"unknown expert (not in experts table): {args.expert}\n")
    # waiver: inline numeric literal, not a domain constant
    return 3

  # guard: no review class to seed the main-writer set from
  if (writers := _resolve_main_writers(file_path, args.expert)) is None:
    sys.stderr.write(f"no review class matches: {file_path}\n")
    # waiver: inline numeric literal, not a domain constant
    return 4

  # open the review, then commit it unless the caller asked for an uncommitted run
  # a report class's document opens its implementer's turn instead of the operator's
  settings_root = _core_settings.query_settings_root_for(file_path)
  report = _doc_class.is_report_class(_load_settings(settings_root), settings_root, file_path)
  changed = open_submit(file_path, expert=args.expert, main_writers=writers, report=report)
  if changed and not args.no_commit:
    _atomic_commit(file_path)
  print(f"submitted: {file_path} (changed={changed})")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
