"""
Main CLI for lazy-review (dispatched by the `lazycortex-review` shim).

Subcommands:

- `status`   — delegate to :mod:`status`.
- `parse-note` — delegate to :mod:`note_ops` (read-only structural report).
- `set-key`  — delegate to :mod:`note_ops` (write one reserved frontmatter key).
- `mark-job` — delegate to :mod:`job_markers` (write one runtime job marker; the only door
               into the sidecar the coordinator and the watch worker share).
- `paint-banner` — delegate to :mod:`note_ops` (repaint the top banner from frontmatter state).
- `collect-job` — delegate to :mod:`collect_ops` (land DONE job payloads into the working
                 tree for the coordinator's own `commit-doc`; no commit, no wake).
- `collect-tick` — delegate to :mod:`collect_ops` (sweep the job queue, raise `job-done`
                 wakes and dispatch the coordinator — no landing, no commit).
- `sanitize` — delegate to :mod:`sanitize` (repair the three file-provable stuck review-loop
                 states: lost writer wakes, orphaned reviews, markers on vanished documents).
- `commit-doc` — delegate to :mod:`commit_doc` (the coordinator's single wake commit:
                 working-tree state + icon repaint, coordinator identity, mechanical trailer).
- `coordinator-dispatch` — delegate to :mod:`coordinator_dispatch` (detect a coordinator
                 wake trigger on every changed document of one git-watch tick and dispatch a
                 job per firing document; a failing path is reported back as a trailing
                 `failed_paths` line). The `lazy-review.coordinator-watch` git-watch routine's
                 own entrypoint.
- `start`    — delegate to :mod:`start`.
- `submit`   — delegate to :mod:`submit` (skip opening writer round).
- `stop`     — delegate to :mod:`stop` (cancel the jobs in flight, then park the review; `--json` prints a
                 report naming the jobs cancelled and the jobs already over).
- `raise-wake` — raise a document's `job-done` wake in the runtime sidecar and dispatch the
                 coordinator for it (no commit) — run to restore a review whose job a caller cancelled.
- `finalize` — delegate to :mod:`finalize`.
- `strip-markup` — print the document body, without frontmatter, with its edit-annotation
                 markup resolved (the markup-final view validation / terminal dispatches use as source).
- `strip-frontmatter` — print the document body without frontmatter, edit-annotation markup
                 left as it is (the view a main-writer dispatch uses as source).
- `fold-markup` — fold the document's edit-annotation markup in place, frontmatter untouched,
                 printing `{"changed": bool}` — run on an operator approve gesture.
- `strip-status` — remove every `#status/<state>` callout from the document body outside code fences in
                 place, frontmatter untouched, no commit, printing `{"changed": bool}` — run by a caller
                 abandoning the document.
- `strip-command` — remove the document's open `#review/command` callout outside code fences and foreign protected
                 sections in place, every other byte untouched, no commit, printing `{"changed": bool}` — run by
                 the coordinator when a command is finished; a document with no command is not an error.
- `clear-multi-ticks` — clear every tick of each `[!question] #review/question` callout ticked more than once and of
                 each `[!decision-candidate]` callout with both boxes ticked, and write a notice line in the
                 document's language under each one's options in place, no commit, printing `{"cleared": <n>}`
                 counting both kinds — run by the coordinator on the wake that brought the ticks; a document with
                 none is not an error.
- `strip-discussion` — remove a report's discussion block from the document body in place, every other byte
                 untouched, no commit, printing `{"stripped": bool}` — run when a report's review closes on a
                 path that takes the block off; a document with no block is not an error.
- `repair-structure` — delegate to :mod:`structure_repair` (repair an unclosed fence or frontmatter
                 delimiter and strip lone edit-annotation opening marks (the mark characters only, outside
                 sections another plugin owns) in place when no guess is needed, no commit; `--check` only reports).
- `operator-text` — delegate to :mod:`operator_text` (print the passages of the document's prose an
                 operator commit wrote, a submit carried in from the operator's draft, or a review commit
                 landed while an operator command stood open).
- `decision-clean` — delegate to :mod:`decision_gate` (print `{"clean": bool}`: whether a decision box ticked on
                 the ready banner counts, true only when the operator's commits since the review system's last
                 commit changed nothing but the banner's box ticks).
- `configure-apply` — delegate to :mod:`configure_apply` (write one review class collected by
                 `/lazy-review.configure` and re-run the install bootstrap; JSON in via `--payload`,
                 `--payload-file`, or stdin).
- `decisions-context` — delegate to :mod:`decisions_context` (print the `{filename: text}`
                 map of whichever decisions-registry file(s) resolve for one document; the
                 coordinator folds this into a main or barrier writer dispatch's `context`).
- `guidelines-context` — delegate to :mod:`guidelines_context` (print the `{paths, warnings}`
                 map of the plugin canon and product guidelines one expert carries on one
                 document; a main or barrier writer dispatch names the repo-relative paths in
                 its `context` and the absolute canon paths in the payload's `guidelines`).
- `dispatch-writer` — delegate to :mod:`writer_dispatch` (build the whole expert-job bundle for one
                 document and one expert, write the writer job marker, and queue the job through
                 core; prints `{job_id, status, warnings}`, or `{error}` on a refusal).
- `core-cli` — print the absolute path of the `lazycortex-core` CLI this plugin resolves
                 for the repository the working directory belongs to: `$LAZYCORTEX_PLUGIN_DIRS`,
                 the dev-vault sibling, the checkout's own plugin tree, then the install the
                 registry records for this repository or the user; the coordinator agent holds
                 it as `<core-cli>` for the wake.
"""
from __future__ import annotations

import argparse
import json
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
import atomic_io as _atomic_io  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from keys import JobKey, JobMarker, LockitKey  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from review_lockit import Lockit  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Subcommand names, help lines and argument spellings of the verbs registered with named constants below
_REPAIR_VERB = "repair-structure"
_REPAIR_HELP = "repair the doc's mechanical structure in place"
_CONFIGURE_VERB = "configure-apply"
_CONFIGURE_HELP = "write one review class from stdin and re-run install"
_OPERATOR_TEXT_VERB = "operator-text"
_OPERATOR_TEXT_HELP = "list the doc's passages the operator wrote or ordered by command"
_STRIP_COMMAND_VERB = "strip-command"
_DECISION_CLEAN_VERB = "decision-clean"
_DECISION_CLEAN_HELP = "report whether the operator changed only the banner's boxes since the system's last commit"
_STRIP_COMMAND_HELP = "remove the doc's open #review/command callout"
_CLEAR_MULTI_TICKS_VERB = "clear-multi-ticks"
_CLEAR_MULTI_TICKS_HELP = "clear the ticks of every question ticked more than once and say why under it"
_STRIP_DISCUSSION_VERB = "strip-discussion"
_STRIP_DISCUSSION_HELP = "remove a report's discussion block from the doc body"
_ARG_FILE = "file"
_ARG_CHECK = "--check"
_ARG_REPO = "--repo"
# The parsed-namespace attribute `--repo` lands in
_REPO_ATTR = "repo"
# The parsed-namespace attribute keeping `--repo` as given, before it is widened to the checkout root
_REPO_START_ATTR = "repo_start"
_ARG_PAYLOAD = "--payload"
_ARG_PAYLOAD_FILE = "--payload-file"
_STORE_TRUE = "store_true"

# Subcommand name, help line and argument spellings of the `dispatch-writer` verb
_DISPATCH_VERB = "dispatch-writer"
_DISPATCH_HELP = "build and queue one expert job for a review document"
_ARG_EXPERT = "expert"
_ARG_SECTION_ID = "--section-id"
_ARG_SECTION = "--section"
_ARG_POSITION = "--position"
_ARG_CONTEXT = "--context"
_ARG_REPAIR = "--repair"
_APPEND = "append"
_POSITIONS = ( "top", "bottom" )

# The exit code of the `paint-banner` verb when the job markers cannot be read, so the job state is unknown.
_EXIT_JOB_STATE_UNKNOWN = 1
# The exit code of the `paint-banner` verb when the document's review class cannot be resolved.
_EXIT_CLASS_UNKNOWN = 1


def cmd_status(args: argparse.Namespace) -> int:
  """
  Delegate the `status` subcommand to the status module.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code from the status module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import status  # type: ignore  # pylint: disable=import-error
  return status.main([ args.file ])


def cmd_parse_note(args: argparse.Namespace) -> int:
  """
  Delegate the `parse-note` subcommand to the note_ops module.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code from the note_ops module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import note_ops  # type: ignore  # pylint: disable=import-error
  # waiver: `plugins/claude/lazycortex-specs/bin/note_ops.py` shares this basename; in a whole-project mypy
  # run the bare `import note_ops` above resolves to that unrelated module instead (this dir's
  # `__init__.py` makes review's own copy package-qualified as `bin.note_ops`), so mypy checks the
  # attribute against the wrong file's shape rather than skipping it as unresolved
  return note_ops.main([ args.file, "--repo", args.repo ])  # type: ignore[attr-defined]


def cmd_set_key(args: argparse.Namespace) -> int:
  """
  Delegate the `set-key` subcommand to the note_ops module.

  Guarantees:
    - An unknown `key` is rejected without writing anything; the file is left completely
      untouched.

  Args:
    args: Parsed namespace with `file`, `key`, `value`, and `repo` attributes.

  Returns:
    Exit code: 0 on success; 2 when the file does not exist or `set_key` refuses the key or value (an unknown or
    retired key, a bad autorun state, a bad cycle count), with the file left untouched.

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """

  # Contract:
  # The file is left completely untouched when `key` is not in the reserved schema; a
  # rejected key never produces a partial write.

  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import note_ops  # type: ignore  # pylint: disable=import-error

  # parse the value as a JSON scalar: true→True, false→False, null→None, integer, otherwise string
  # waiver: 'true'/'false' are JSON literal keywords, not magic strings; the parsing is domain logic
  parsed_value: object
  if args.value == "true":  # waiver: JSON literal
    parsed_value = True
  elif args.value == "false":  # waiver: JSON literal
    parsed_value = False
  elif args.value == "null":
    parsed_value = None
  else:
    # attempt to parse as integer; fall back to plain string
    try:
      parsed_value = int(args.value)
    except ValueError:
      parsed_value = args.value

  # resolve the file path against --repo
  file_path = (Path(args.repo).resolve() / args.file).resolve()

  # guard: target file does not exist — nothing to set the key on
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # read the document and attempt to set the key
  lf_text, ending = _atomic_io.to_lf(_atomic_io.read_text(file_path))
  try:
    # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
    # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
    updated_text = note_ops.set_key(lf_text, args.key, parsed_value)  # type: ignore[attr-defined]
  except ValueError as error:
    sys.stderr.write(f"{error}\n")
    return 2

  # write the updated document
  _atomic_io.write_text_atomic(file_path, _atomic_io.restore_ending(updated_text, ending))
  return 0


def cmd_mark_job(args: argparse.Namespace) -> int:
  """
  Delegate the `mark-job` subcommand to the job_markers module.

  Args:
    args: Parsed namespace with `file`, `kind`, `job_id`, `clear`, and `repo` attributes.

  Returns:
    Exit code from the job_markers module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import job_markers  # type: ignore  # pylint: disable=import-error

  # the file and marker kind always go through; a job id only when one was given
  forward: list[str] = [ args.file, args.kind ]
  if args.job_id:
    forward.append(args.job_id)

  # a clear request is replayed as its flag
  if args.clear:
    # waiver: argparse CLI signature, not a domain key
    forward.append("--clear")
  return job_markers.main([ *forward, "--repo", args.repo ])


def cmd_paint_banner(args: argparse.Namespace) -> int:
  """
  Delegate the `paint-banner` subcommand to the note_ops module.

  The banner painted is the report banner when the document's review class is configured with `report: true`, and
  the plain banner otherwise; a report banner carries the plan-verdict line when the document has a stored verdict.
  The verdict is the one recorded for the document's own repository root, whatever checkout the command works in;
  the other job state comes from that checkout. The review class comes from the document's nearest
  `.claude/lazy.settings.json` within its checkout, the checkout's root when none is nearer.

  Guarantees:
    - When the document's review class cannot be resolved, because the review settings cannot be read or no core CLI
      is resolvable, no banner is painted and the document is left untouched.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code: 0 on success, 1 when the job markers cannot be read or the document's review class cannot be resolved
    (the banner is left as it is and one stderr line says the job state or the class is unknown), 2 if the file does
    not exist (nothing written).

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing
      fence — mirrors `cmd_set_key`, which propagates the same failure uncaught.
    RuntimeError: If the document sits in a vault and the `lazycortex-core` language lookup fails or returns no
      language.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import job_markers  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import note_ops  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import core_settings  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import doc_class  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import finalize  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  from errors import SettingsReadError  # type: ignore  # pylint: disable=import-error

  # resolve the file path against --repo, mirroring cmd_set_key
  repo = Path(args.repo).resolve()
  file_path = (repo / args.file).resolve()

  # guard: target file does not exist — nothing to repaint
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # the document is read once, its line ending kept for the write back
  lf_text, ending = _atomic_io.to_lf(_atomic_io.read_text(file_path))

  # guard: markers that cannot be read do not say "no job in flight"; the banner is left as it is
  # the writer's verdict is keyed by the document's repository root, where every other verdict reader and writer
  # keys it, whatever `--repo` names
  try:
    markers = job_markers.read_checked(repo, file_path)
    verdict = job_markers.read_checked(finalize.query_repo_root_for(file_path), file_path)[JobMarker.VERDICT]
  except OSError as error:
    sys.stderr.write(
        f"paint-banner: job state unknown, banner left as it is: {job_markers.sidecar_path(repo)}: "
        f"{type(error).__name__}: {error}\n"
    )
    return _EXIT_JOB_STATE_UNKNOWN

  # guard: settings or a core that cannot be read say nothing about the class, and painting either banner on a guess
  # could put the approve banner on a report; the banner is left as it is
  try:
    settings_root = core_settings.query_settings_root_for(file_path)
    settings = core_settings.read_merged_sections(settings_root, JobKey.REVIEW)
    report = bool(doc_class.is_report_class(settings, settings_root, file_path))
  except (SettingsReadError, RuntimeError) as error:
    sys.stderr.write(
        f"paint-banner: the document's review class is unknown, banner left as it is: "
        f"{type(error).__name__}: {error}\n"
    )
    return _EXIT_CLASS_UNKNOWN

  # the banner is repainted from the frontmatter state and the sidecar's job state and plan verdict, then written
  # back with no commit
  # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
  # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
  updated_text = note_ops.repaint_banner(  # type: ignore[attr-defined]
      lf_text, job_in_flight = bool(markers[JobMarker.ACTIVE_JOB]),
      lang = note_ops.resolve_language(file_path),  # type: ignore[attr-defined]
      report = report, verdict = verdict)
  _atomic_io.write_text_atomic(file_path, _atomic_io.restore_ending(updated_text, ending))
  return 0


def cmd_collect_job(args: argparse.Namespace) -> int:
  """
  Delegate the `collect-job` subcommand to the collect_ops module.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code from the collect_ops module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import collect_ops  # type: ignore  # pylint: disable=import-error
  return collect_ops.main([ args.file, "--repo", args.repo ])


def cmd_collect_tick(args: argparse.Namespace) -> int:
  """
  Delegate the `collect-tick` subcommand to the collect_ops module.

  Args:
    args: Parsed namespace with a `repo` attribute.

  Returns:
    Exit code from the collect_ops module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import collect_ops  # type: ignore  # pylint: disable=import-error
  return collect_ops.main_tick([ "--repo", args.repo ])


def cmd_sanitize(args: argparse.Namespace) -> int:
  """
  Delegate the `sanitize` subcommand to the sanitize module.

  Args:
    args: Parsed namespace with a `repo` attribute.

  Returns:
    Exit code from the sanitize module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import sanitize  # type: ignore  # pylint: disable=import-error
  return sanitize.main([ "--repo", args.repo ])


def cmd_coordinator_dispatch(args: argparse.Namespace) -> int:
  """
  Delegate the `coordinator-dispatch` subcommand to the coordinator_dispatch module.

  Args:
    args: Parsed namespace with `item_json` and `repo` attributes.

  Returns:
    Exit code from the coordinator_dispatch module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import coordinator_dispatch  # type: ignore  # pylint: disable=import-error
  return coordinator_dispatch.main([ args.item_json, "--repo", args.repo ])


def cmd_commit_doc(args: argparse.Namespace) -> int:
  """
  Delegate the `commit-doc` subcommand to the commit_doc module.

  Args:
    args: Parsed namespace with `file`, `subject`, `repo`, `also`, and `history` attributes.

  Returns:
    Exit code from the commit_doc module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import commit_doc  # type: ignore  # pylint: disable=import-error

  # each landed attachment is replayed as its own flag — the verb reads `--also` repeatably
  extra = [ token for path in (args.also or ()) for token in ("--also", path) ]

  # each History line is replayed as its own flag, in the order given
  lines = [ token for line in (args.history or ()) for token in ("--history", line) ]
  return commit_doc.main([ args.file, "--subject", args.subject, "--repo", args.repo, *extra, *lines ])


def cmd_start(args: argparse.Namespace) -> int:
  """
  Delegate the `start` subcommand to the start module.

  Args:
    args: Parsed namespace with `file` and optional `expert` / `no_commit` attributes.

  Returns:
    Exit code from the start module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import start  # type: ignore  # pylint: disable=import-error

  # the file always goes through; an expert only when one was named
  forward: list[str] = [ args.file ]
  if args.expert:
    forward.extend([ "--expert", args.expert ])

  # a caller that owns the commit itself takes the bootstrap alone — see the flag's own help
  if args.no_commit:
    # waiver: argparse CLI signature forwarded verbatim to the start module
    forward.append("--no-commit")
  return start.main(forward)


def cmd_submit(args: argparse.Namespace) -> int:
  """
  Delegate the `submit` subcommand to the submit module.

  Args:
    args: Parsed namespace with `file` and optional `expert` attributes.

  Returns:
    Exit code from the submit module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import submit  # type: ignore  # pylint: disable=import-error

  # the file always goes through; an expert only when one was named
  forward: list[str] = [ args.file ]
  if args.expert:
    forward.extend([ "--expert", args.expert ])
  return submit.main(forward)


def cmd_stop(args: argparse.Namespace) -> int:
  """
  Delegate the `stop` subcommand to the stop module.

  The review is stopped either way; with `--no-commit` the commit is left to the caller.

  Args:
    args: Parsed namespace with `file`, `no_commit`, `strip_banner` and `json` attributes; each set flag is
      forwarded, `json` asking the stop module for its JSON report.

  Returns:
    Exit code from the stop module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import stop  # type: ignore  # pylint: disable=import-error

  # the file always goes through; a caller owning the commit itself asks for none
  forward = [ args.file ]
  if args.no_commit:
    # waiver: argparse CLI signature forwarded verbatim to the stop module
    forward.append("--no-commit")

  # a caller abandoning the document asks for its banner to come down with the review
  if args.strip_banner:
    # waiver: argparse CLI signature forwarded verbatim to the stop module
    forward.append("--strip-banner")

  # a caller acting on what the stop cancelled asks for the JSON report
  if args.json:
    # waiver: argparse CLI signature forwarded verbatim to the stop module
    forward.append("--json")
  return stop.main(forward)


def cmd_raise_wake(args: argparse.Namespace) -> int:
  """
  Raise a document's `job-done` wake and dispatch the review coordinator for it.

  Guarantees:
    - The wake is raised before the coordinator is dispatched, so a failed dispatch exits 1 with the wake left
      raised.
    - A file that does not exist exits 2 with nothing written.

  Args:
    args: Parsed namespace with `file`, `repo` and `hint` attributes.

  Returns:
    Exit code: 0 when the wake was dispatched or a live coordinator already owns the document, 1 when the dispatch
    failed, an OS or subprocess error included, with the wake left raised, 2 when the file does not exist (nothing
    written).
  """

  # Contract:
  # The document's `job-done` wake is raised BEFORE the coordinator is dispatched, so a dispatch failure exits 1
  # with the wake left raised for a later tick.

  # Contract:
  # A file that does not exist exits 2 and nothing is written.

  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import coordinator_dispatch  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import job_markers  # type: ignore  # pylint: disable=import-error

  # a relative file path names a document inside the repository the wake acts in
  repo = Path(args.repo).resolve()
  file_path = (repo / args.file).resolve()

  # guard: target file does not exist — no review to wake
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # the flag goes up first, so a failed dispatch still leaves the wake for a later tick
  job_markers.update(repo, file_path, { JobMarker.PENDING_WAKE: JobMarker.JOB_DONE })
  try:
    # waiver: the whole-project mypy run resolves the bare name to lazycortex-specs' same-named module, which has no
    # `dispatch_job_done`; at runtime the sys.path.insert above loads this bin's own sibling
    coordinator_dispatch.dispatch_job_done(repo, file_path, args.hint)  # type: ignore[attr-defined]
  except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
    sys.stderr.write(f"raise-wake: {error}\n")
    return 1
  return 0


def cmd_finalize(args: argparse.Namespace) -> int:
  """
  Delegate the `finalize` subcommand to the finalize module.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code from the finalize module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import finalize  # type: ignore  # pylint: disable=import-error
  return finalize.main([ args.file ])


def cmd_send_back(args: argparse.Namespace) -> int:
  """
  Delegate the `send-back` subcommand to the send_back module.

  Args:
    args: Parsed namespace with `file`, `repo`, and `decision` attributes; a set `decision` is forwarded as the
      `--decision` flag.

  Returns:
    Exit code from the send_back module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import send_back  # type: ignore  # pylint: disable=import-error
  return send_back.main([ args.file, _ARG_REPO, args.repo, *([ "--decision" ] if args.decision else []) ])


def cmd_strip_markup(args: argparse.Namespace) -> int:
  """
  Print the document body with its edit-annotation markup resolved to final text.

  The frontmatter is left out of the output. The markup is resolved according to the document's own marker
  style, falling back to the repo's configured style.

  Guarantees:
    - Never aborts on an unrecognized configured edit-marker style; the document's body is
      printed with its markup left unresolved instead.
    - The output never contains the document's frontmatter; it is the body alone, with its edit markup resolved.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code: 0 on success (unknown configured style degrades to printing the
    body unchanged), 2 when the file is missing or not markdown.

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import writer_dispatch  # type: ignore  # pylint: disable=import-error
  file_path = Path(args.file).resolve()

  # guard: only an existing markdown file has a review body to resolve
  # waiver: filesystem path idiom
  if not file_path.is_file() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2

  # Domain(review.dispatch):
  # # Resolved text for judging, raw markup for revising
  # A writer that revises a document's body works from its edit-annotation markup left
  # unresolved, so a later round can still retract or build on an earlier round's marked
  # change. A writer that only judges the document's current state — whether it is ready to
  # advance, or whether it already satisfies a terminal check — is instead handed the markup
  # folded away into the plain text the operator would actually read, because judging the
  # wrong view risks approving or rejecting text that no longer exists once the markup
  # resolves.

  # Domain(review.dispatch):
  # # A writer sees the body, never the frontmatter
  # The frontmatter is machine state: review keys, wiki summaries and spec keys written by
  # their own owners, none of which a writer may change. A writer handed it judges or rewrites
  # values it cannot touch — a validator flags a stale summary no writer round can ever close,
  # and the review circles. Every writer is therefore handed the body alone; only the
  # structural repair, which fixes the frontmatter fence itself, works from the whole file.

  # Contract:
  # An unrecognized configured edit-marker style never aborts the dispatch; the document's
  # body is returned with its markup left unresolved instead of raising.

  # Contract:
  # The output NEVER contains the document's frontmatter; it is the body alone, with its edit markup resolved.
  # Writers take this output as their source, and a writer that sees frontmatter raises concerns no writer
  # round can close.

  # the resolved body goes to stdout — the same view a validation or terminal dispatch takes as its source;
  # an unknown style does not kill the verb, the view degrades to the raw body half
  sys.stdout.write(writer_dispatch.read_resolved_body_view(file_path))
  return 0


def cmd_strip_frontmatter(args: argparse.Namespace) -> int:
  """
  Print the document body without its frontmatter.

  The edit-annotation markup is printed exactly as it stands in the document.

  Guarantees:
    - The body's edit-annotation markup is printed exactly as written; no marker style is resolved.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code: 0 on success, 2 when the file is missing or not markdown.

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """

  # Contract:
  # The body's edit-annotation markup is printed exactly as written; no marker style is ever resolved.
  # The main writer needs the raw markup as working material.

  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import writer_dispatch  # type: ignore  # pylint: disable=import-error
  file_path = Path(args.file).resolve()

  # guard: only an existing markdown file has a review body to print
  # waiver: filesystem path idiom
  if not file_path.is_file() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2

  # the body goes to stdout with its edit markup intact — the main writer's working material
  sys.stdout.write(writer_dispatch.read_body_view(file_path))
  return 0


def cmd_dispatch_writer(args: argparse.Namespace) -> int:
  """
  Delegate the `dispatch-writer` subcommand to the writer_dispatch module.

  Args:
    args: Parsed namespace with `file`, `expert`, `repo`, `section_id`, `section`, `position`, `context` and
      `repair` attributes.

  Returns:
    Exit code from the writer_dispatch module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import writer_dispatch  # type: ignore  # pylint: disable=import-error

  # each given flag is replayed as itself; an absent one keeps the module's own default
  forward: list[str] = [ args.file, args.expert, _ARG_REPO, args.repo ]
  for flag, value in ( ( _ARG_SECTION_ID, args.section_id ), ( _ARG_SECTION, args.section ),
                       ( _ARG_POSITION, args.position ) ):
    if value is not None:
      forward.extend([ flag, value ])

  # each extra context file is replayed as its own flag, in the order given
  for path in args.context or ():
    forward.extend([ _ARG_CONTEXT, path ])

  # a doctor repair dispatch is replayed as its flag
  if args.repair:
    forward.append(_ARG_REPAIR)
  return writer_dispatch.main(forward)


def cmd_fold_markup(args: argparse.Namespace) -> int:
  """
  Fold the document's edit-annotation markup into final text in place.

  Backs the `fold-markup` verb, run on an operator approve gesture so the next ready-to-approve round shows only the
  edits made since. The document's pinned edit-marker style applies, falling back to the settings value.

  Guarantees:
    - Frontmatter bytes are left untouched.
    - The file is rewritten only when the fold changed something, so a repeat call leaves it as it is.
    - A rewrite is atomic.

  Notes:
    - Prints one JSON line, `{"changed": bool}`, to stdout on success.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code: 0 on success, 1 when the file is missing, 2 when the edit-marker style is unknown (file untouched).
  """

  # Contract:
  # The document's frontmatter MUST be left byte-for-byte untouched; only the body is ever folded.

  # Contract:
  # The file MUST be rewritten only when the fold changed the body; when nothing changed the file is not touched,
  # so a repeat call is a no-op.

  # Contract:
  # A rewrite MUST be atomic: a reader never observes a partially written document.

  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import body as _body  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import finalize  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import frontmatter as _fm  # type: ignore  # pylint: disable=import-error

  # resolve the file against --repo; an absolute file argument wins over the repo root
  file_path = (Path(args.repo).resolve() / args.file).resolve()

  # guard: only an existing file has a body to fold
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 1

  # split the document once — the frontmatter half is written back byte-for-byte
  lf_text, ending = _atomic_io.to_lf(_atomic_io.read_text(file_path))
  _meta, body = _fm.parse(lf_text)
  fm_text = lf_text[: len(lf_text) - len(body)]

  # fold the body per the document's pinned style; an unknown style leaves the file untouched
  try:
    folded = _body.fold_edit_markers(body, style = finalize.read_document_edit_marker_style(file_path))
  except ValueError as error:
    sys.stderr.write(f"{error}\n")
    return 2

  # write only when the fold changed something, so a repeat call is a no-op on disk
  changed = folded != body
  if changed:
    _atomic_io.write_text_atomic(file_path, _atomic_io.restore_ending(fm_text + folded, ending))
  print(json.dumps({ "changed": changed }))
  return 0


def cmd_strip_status(args: argparse.Namespace) -> int:
  """
  Remove every `#status/<state>` callout from the document body in place, with no commit.

  Backs the `strip-status` verb, run by a caller that abandons the document so its terminal-state callout no longer
  claims a state the document has left.

  Guarantees:
    - Frontmatter bytes are left untouched, and a callout inside a code fence survives.
    - The file is rewritten, atomically, only when a callout was removed; no commit is made.

  Notes:
    - Prints one JSON line, `{"changed": bool}`, to stdout on success.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code: 0 on success, 1 when the file is missing (nothing written).
  """

  # Contract:
  # The document's frontmatter MUST be left byte-for-byte untouched and a fenced status callout survives.

  # Contract:
  # The file MUST be rewritten only when a callout was removed, atomically, and no commit is ever made.

  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import body as _body  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import frontmatter as _fm  # type: ignore  # pylint: disable=import-error

  # resolve the file against --repo; an absolute file argument wins over the repo root
  file_path = (Path(args.repo).resolve() / args.file).resolve()

  # guard: only an existing file has a body to strip
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 1

  # split the document once — the frontmatter half is written back byte-for-byte
  lf_text, ending = _atomic_io.to_lf(_atomic_io.read_text(file_path))
  _meta, body = _fm.parse(lf_text)
  fm_text = lf_text[: len(lf_text) - len(body)]

  # write only when a callout came off, so a repeat call is a no-op on disk
  stripped = _body.strip_every_status_callout(body)
  changed = stripped != body
  if changed:
    _atomic_io.write_text_atomic(file_path, _atomic_io.restore_ending(fm_text + stripped, ending))
  print(json.dumps({ "changed": changed }))
  return 0


def cmd_clear_multi_ticks(args: argparse.Namespace) -> int:
  """
  Clear the ticks of every question ticked more than once and every decision-candidate ticked both ways, in place,
  with no commit.

  Guarantees:
    - A document with no such question or candidate exits 0, prints `{"cleared": 0}`, and is not rewritten.
    - A missing file exits 1, and nothing is written then.

  Notes:
    - The notice line under each cleared question or candidate is written in the document's language.
    - Prints one JSON line, `{"cleared": <n>}`, the number of questions and candidates cleared together, to stdout on
      success.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code: 0 on success, none to clear included, 1 when the file is missing (nothing written).
  """

  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import note_ops  # type: ignore  # pylint: disable=import-error

  # resolve the file against --repo; an absolute file argument wins over the repo root
  file_path = (Path(args.repo).resolve() / args.file).resolve()

  # guard: only an existing file has questions to clear
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 1

  # the questions are counted and cleared on the LF view of the document, its line ending kept for the write back
  lf_text, ending = _atomic_io.to_lf(_atomic_io.read_text(file_path))
  # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
  # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
  report = note_ops.build_report(lf_text)  # type: ignore[attr-defined]
  # waiver: 'multi_ticked_questions'/'both_ticked_candidates' are parse-note's own wire-shape keys (note_ops docstring)
  cleared = len(report["multi_ticked_questions"]) + len(report["both_ticked_candidates"])

  # write only when a question or a candidate was cleared, so a repeat call is a no-op on disk
  if cleared:
    # waiver: type: ignore — the same whole-project mypy binding of `note_ops` as above
    lang = note_ops.resolve_language(file_path)  # type: ignore[attr-defined]
    # waiver: type: ignore — the same whole-project mypy binding of `note_ops` as above
    updated = note_ops.clear_multi_ticked_questions(  # type: ignore[attr-defined]
        lf_text, Lockit.text(LockitKey.QUESTION_MULTI_TICKED, lang))
    # waiver: type: ignore — the same whole-project mypy binding of `note_ops` as above
    updated = note_ops.clear_both_ticked_candidates(  # type: ignore[attr-defined]
        updated, Lockit.text(LockitKey.CANDIDATE_BOTH_TICKED, lang))
    _atomic_io.write_text_atomic(file_path, _atomic_io.restore_ending(updated, ending))
  print(json.dumps({ "cleared": cleared }))
  return 0


def cmd_strip_command(args: argparse.Namespace) -> int:
  """
  Remove the document's open operator command callout in place, with no commit.

  Guarantees:
    - A document with no open command exits 0, prints `{"changed": false}`, and is not rewritten.
    - A missing file exits 1, and nothing is written then.

  Notes:
    - The file is rewritten atomically, and only when a callout was removed.
    - Prints one JSON line, `{"changed": bool}`, to stdout on success.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code: 0 on success, an absent command included, 1 when the file is missing (nothing written).
  """

  # Contract:
  # A document with no open command exits 0 with `{"changed": false}` and is not rewritten; a missing file exits 1
  # with nothing written. The coordinator runs this at the end of every finished command, and an absent callout
  # must never break its wake.

  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import note_ops  # type: ignore  # pylint: disable=import-error

  # resolve the file against --repo; an absolute file argument wins over the repo root
  file_path = (Path(args.repo).resolve() / args.file).resolve()

  # guard: only an existing file has a command to remove
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 1

  # the command comes off the LF view of the document, its line ending kept for the write back
  lf_text, ending = _atomic_io.to_lf(_atomic_io.read_text(file_path))
  # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
  # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
  stripped = note_ops.strip_open_command(lf_text)  # type: ignore[attr-defined]

  # write only when a callout came off, so a repeat call is a no-op on disk
  changed = stripped != lf_text
  if changed:
    _atomic_io.write_text_atomic(file_path, _atomic_io.restore_ending(stripped, ending))
  print(json.dumps({ "changed": changed }))
  return 0


def cmd_strip_discussion(args: argparse.Namespace) -> int:
  """
  Remove a report's discussion block from the document body in place, with no commit.

  Guarantees:
    - Frontmatter bytes and every byte outside the block are left untouched, and the line ending is kept.
    - A document with no discussion block exits 0, prints `{"stripped": false}`, and is not rewritten.
    - A missing file exits 1, and nothing is written then.

  Notes:
    - No commit is made.
    - Prints one JSON line, `{"stripped": bool}`, to stdout on success.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code: 0 on success, an absent block included, 1 when the file is missing (nothing written).

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """

  # Contract:
  # A document with no discussion block exits 0 with `{"stripped": false}` and is not rewritten; a missing file
  # exits 1 with nothing written. The file is rewritten only when a block came off, and no commit is ever made.

  # Contract:
  # Frontmatter bytes and every byte outside the discussion block are left untouched, and the document's
  # line ending is kept.

  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import body as _body  # type: ignore  # pylint: disable=import-error
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import frontmatter as _fm  # type: ignore  # pylint: disable=import-error

  # resolve the file against --repo; an absolute file argument wins over the repo root
  file_path = (Path(args.repo).resolve() / args.file).resolve()

  # guard: only an existing file has a body to strip
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 1

  # split the document once — the frontmatter half is written back byte-for-byte
  lf_text, ending = _atomic_io.to_lf(_atomic_io.read_text(file_path))
  _meta, body = _fm.parse(lf_text)
  fm_text = lf_text[: len(lf_text) - len(body)]

  # write only when a block came off, so a repeat call is a no-op on disk
  new_body = _body.strip_discussion(body)
  stripped = new_body != body
  if stripped:
    _atomic_io.write_text_atomic(file_path, _atomic_io.restore_ending(fm_text + new_body, ending))
  print(json.dumps({ "stripped": stripped }))
  return 0


def cmd_repair_structure(args: argparse.Namespace) -> int:
  """
  Delegate the `repair-structure` subcommand to the `structure_repair` module.

  Args:
    args: Parsed namespace with `file`, `repo`, and `check` attributes.

  Returns:
    Exit code from the `structure_repair` module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; pylint cannot see that path
  import structure_repair  # pylint: disable=import-error

  # `--check` is replayed only when given, so the module's own default stays the write
  return structure_repair.main([ args.file, _ARG_REPO, args.repo, *([ _ARG_CHECK ] if args.check else []) ])


def cmd_operator_text(args: argparse.Namespace) -> int:
  """
  Delegate the `operator-text` subcommand to the `operator_text` module.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code from the `operator_text` module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; pylint cannot see that path
  import operator_text  # pylint: disable=import-error
  return operator_text.main([ args.file, _ARG_REPO, args.repo ])


def cmd_decision_clean(args: argparse.Namespace) -> int:
  """
  Delegate the `decision-clean` subcommand to the `decision_gate` module.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code from the `decision_gate` module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; pylint cannot see that path
  import decision_gate  # pylint: disable=import-error
  return decision_gate.main([ args.file, _ARG_REPO, args.repo ])


def cmd_configure_apply(args: argparse.Namespace) -> int:
  """
  Delegate the `configure-apply` subcommand to the `configure_apply` module.

  Args:
    args: Parsed namespace with the `repo`, `payload`, and `payload_file` attributes, and `repo_start`, the `--repo`
      value as given, when `main` parsed it.

  Returns:
    Exit code from the `configure_apply` module.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; pylint cannot see that path
  import configure_apply  # pylint: disable=import-error

  # each given document source is replayed as its flag; with neither, the document stays on stdin for the module
  payload = [ _ARG_PAYLOAD, args.payload ] if args.payload is not None else []
  payload_file = [ _ARG_PAYLOAD_FILE, args.payload_file ] if args.payload_file is not None else []

  # the settings written are the nearest ones to `--repo` as given, so the module gets it unwidened; none given, the
  # module falls back to `$LAZY_REPO_ROOT`, then the cwd, itself
  start = getattr(args, _REPO_START_ATTR, args.repo)
  repo_args = [ _ARG_REPO, start ] if start is not None else []
  return configure_apply.main([ *repo_args, *payload, *payload_file ])


def cmd_decisions_context(args: argparse.Namespace) -> int:
  """
  Print the decisions-registry context map for one review document.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code: always 0. Prints the JSON `{filename: text}` decisions-registry context map to
    stdout on every call, and each warning on stderr as `warning: <text>`; the target document need not
    exist on disk.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import decisions_context  # type: ignore  # pylint: disable=import-error

  # resolve the target file — the same absolute-path convention cmd_strip_markup uses
  file_path = Path(args.file).resolve()

  # the registries go out as the one JSON line on stdout, piped straight into the coordinator's dispatch build
  # waiver: type: ignore — decisions_context is a deferred/late-bound sibling import; mypy cannot resolve it
  contexts, warnings = decisions_context.collect(file_path)  # type: ignore[attr-defined]
  print(json.dumps(contexts))

  # a refused content root is reported beside the map, one stderr line per warning, never dropped
  for warning in warnings:
    sys.stderr.write(f"warning: {warning}\n")
  return 0


def cmd_guidelines_context(args: argparse.Namespace) -> int:
  """
  Print the plugin canon and product guideline paths one expert carries on one review document.

  Args:
    args: Parsed namespace with `file` and `expert` attributes.

  Returns:
    Exit code: always 0. Prints the JSON `{paths, warnings}` map to stdout on every call; the
    target document need not exist on disk.
  """
  # waiver: deferred local import — each verb loads its flat `bin/` sibling module only when that verb runs
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import guidelines_context  # type: ignore  # pylint: disable=import-error

  # the verb's whole contract is this one JSON line, piped straight into the coordinator's dispatch build
  # waiver: type: ignore — guidelines_context is a deferred/late-bound sibling import; mypy cannot resolve it
  print(json.dumps(guidelines_context.collect(Path(args.file).resolve(), args.expert)))  # type: ignore[attr-defined]
  return 0


def cmd_core_cli(_args: argparse.Namespace) -> int:
  """
  Print the absolute path of the `lazycortex-core` CLI resolved for the repository the command works in.

  Args:
    _args: Parsed namespace; the verb takes no arguments.

  Returns:
    Exit code: 0 with the path on stdout, 1 with an `error:` line on stderr when no lookup
    stage finds core.
  """
  # one resolver for the whole plugin, started at the checkout root the command works in
  try:
    cli = _git_ops.require_core_cli(_review_locator.query_repo_root())
  # no lookup stage found a binary — the agent stops and reports rather than guessing a path; the
  # resolver's own message names every stage searched
  except RuntimeError as error:
    sys.stderr.write(f"error: {error}\n")
    return 1
  print(cli)
  return 0


def build_parser() -> argparse.ArgumentParser:
  """
  Build and return the top-level argument parser for the lazy-review CLI.

  Returns:
    Configured argument parser with all subcommands registered.
  """
  # the root parser and the subcommand slot every verb below registers itself into
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazy-review")
  # waiver: argparse CLI signature, not a domain key
  sub = parser.add_subparsers(dest = "cmd", required = True)

  # `status` — read-only introspection for the operator
  # waiver: argparse CLI signature, not a domain key
  p_status = sub.add_parser("status", help = "introspect one file")
  # waiver: argparse CLI signature, not a domain key
  p_status.add_argument("file")
  p_status.set_defaults(func = cmd_status)

  # `parse-note` — read-only structural report for the coordinator / watch worker
  # waiver: argparse CLI signature, not a domain key
  p_parse = sub.add_parser("parse-note", help = "structural report for one file")
  # waiver: argparse CLI signature, not a domain key
  p_parse.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_parse.add_argument("--repo", default = None)
  p_parse.set_defaults(func = cmd_parse_note)

  # `set-key` — write a frontmatter key to a review document
  # waiver: argparse CLI signature, not a domain key
  p_set = sub.add_parser("set-key", help = "set frontmatter key in a review document")
  # waiver: argparse CLI signature, not a domain key
  p_set.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_set.add_argument("key")
  # waiver: argparse CLI signature, not a domain key
  p_set.add_argument("value")
  # waiver: argparse CLI signature, not a domain key
  p_set.add_argument("--repo", default = None)
  p_set.set_defaults(func = cmd_set_key)

  # `mark-job` — write one runtime job marker into the gitignored sidecar
  # waiver: argparse CLI signature, not a domain key
  p_mark = sub.add_parser("mark-job", help = "set or clear one runtime job marker on a review document")
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("kind", choices = [ JobMarker.KIND_COORDINATOR, JobMarker.KIND_WRITER ])
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("job_id", nargs = "?", default = None)
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("--clear", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("--repo", default = None)
  p_mark.set_defaults(func = cmd_mark_job)

  # `paint-banner` — repaint the top banner from the document's current frontmatter state
  # waiver: argparse CLI signature, not a domain key
  p_paint = sub.add_parser("paint-banner", help = "repaint the review banner from frontmatter state")
  # waiver: argparse CLI signature, not a domain key
  p_paint.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_paint.add_argument("--repo", default = None)
  p_paint.set_defaults(func = cmd_paint_banner)

  # `collect-job` — land DONE job payloads for one file into the working tree, no commit
  # waiver: argparse CLI signature, not a domain key
  p_collect = sub.add_parser("collect-job", help = "land DONE job payloads for one review document")
  # waiver: argparse CLI signature, not a domain key
  p_collect.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_collect.add_argument("--repo", default = None)
  p_collect.set_defaults(func = cmd_collect_job)

  # `collect-tick` — sweep the whole job queue, landing every DONE-and-not-CONSUMED job
  # waiver: argparse CLI signature, not a domain key
  p_collect_tick = sub.add_parser("collect-tick", help = "sweep the job queue for finished review jobs")
  # waiver: argparse CLI signature, not a domain key
  p_collect_tick.add_argument("--repo", default = None)
  p_collect_tick.set_defaults(func = cmd_collect_tick)

  # `sanitize` — repair the three file-provable stuck review-loop states
  # waiver: argparse CLI signature, not a domain key
  p_sanitize = sub.add_parser("sanitize", help = "repair stuck review-loop state")
  # waiver: argparse CLI signature, not a domain key
  p_sanitize.add_argument("--repo", default = None)
  p_sanitize.set_defaults(func = cmd_sanitize)

  # `commit-doc` — the coordinator's single wake commit, repaint folded in
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc = sub.add_parser("commit-doc", help = "commit one review document's wake state")
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc.add_argument("--subject", required = True)
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc.add_argument("--repo", default = None)

  # repeatable: one `--also <path>` per attachment a `collect-job` landed beside the document
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc.add_argument("--also", action = "append", default = None)

  # repeatable: one `--history <line>` per journal line the verb lands under today's day group
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc.add_argument("--history", action = "append", default = None)
  p_commit_doc.set_defaults(func = cmd_commit_doc)

  # `coordinator-dispatch` — the git-watch routine's entrypoint for one tick's changed documents
  # waiver: argparse CLI signature, not a domain key
  p_coord = sub.add_parser("coordinator-dispatch", help = "detect a coordinator wake trigger and dispatch")
  # waiver: argparse CLI signature, not a domain key
  p_coord.add_argument("item_json")
  # waiver: argparse CLI signature, not a domain key
  p_coord.add_argument("--repo", default = None)
  p_coord.set_defaults(func = cmd_coordinator_dispatch)

  # `start` — opt a document in, opening writer round included
  # waiver: argparse CLI signature, not a domain key
  p_start = sub.add_parser("start", help = "opt a file into review")
  # waiver: argparse CLI signature, not a domain key
  p_start.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_start.add_argument("--expert", default = None)
  # waiver: argparse CLI signature, not a domain key
  p_start.add_argument("--no-commit", action = "store_true",
                       # waiver: one-off human-facing message -- argparse help text
                       help = "apply the bootstrap but leave the commit to the caller")
  p_start.set_defaults(func = cmd_start, no_commit = False)

  # `submit` — opt a document in with the opening writer round skipped
  p_submit = sub.add_parser(
      # waiver: argparse CLI signature, not a domain key
      "submit", help = "opt a file into review skipping the opening writer round")
  # waiver: argparse CLI signature, not a domain key
  p_submit.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_submit.add_argument("--expert", default = None)
  p_submit.set_defaults(func = cmd_submit)

  # `stop` — opt a document out mid-cycle
  # waiver: argparse CLI signature, not a domain key
  p_stop = sub.add_parser("stop", help = "opt a file out of review")
  # waiver: argparse CLI signature, not a domain key
  p_stop.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_stop.add_argument("--no-commit", action = "store_true",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "stop the review but leave the commit to the caller")
  # waiver: argparse CLI signature, not a domain key
  p_stop.add_argument("--strip-banner", action = "store_true",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "also remove the review banner and its approval gestures")
  # waiver: argparse CLI signature, not a domain key
  p_stop.add_argument("--json", action = "store_true",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "print the outcome, the cancelled jobs included, as one JSON object")
  p_stop.set_defaults(func = cmd_stop, no_commit = False, strip_banner = False, json = False)

  # `raise-wake` — raise a document's job-done wake and dispatch the coordinator for it, no commit
  # waiver: argparse CLI signature, not a domain key
  p_wake = sub.add_parser("raise-wake", help = "raise a job-done wake and dispatch the review coordinator")
  # waiver: argparse CLI signature, not a domain key
  p_wake.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_wake.add_argument("--repo", default = None)
  # waiver: argparse CLI signature, not a domain key
  p_wake.add_argument("--hint", default = "wake",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "stable token folded into the dispatch's dedup key")
  p_wake.set_defaults(func = cmd_raise_wake)

  # `finalize` — strip the review's markup from an approved document
  # waiver: argparse CLI signature, not a domain key
  p_final = sub.add_parser("finalize", help = "finalize a fully-approved doc")
  # waiver: argparse CLI signature, not a domain key
  p_final.add_argument("file")
  p_final.set_defaults(func = cmd_finalize)

  # `send-back` — end the cycle without approval, handing the ticked problems back to the producer
  # waiver: argparse CLI signature, not a domain key
  p_send_back = sub.add_parser("send-back", help = "end the review cycle, handing ticked problems back")
  # waiver: argparse CLI signature, not a domain key
  p_send_back.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_send_back.add_argument("--repo", default = None)
  # waiver: argparse CLI signature, not a domain key
  p_send_back.add_argument("--decision", action = "store_true")
  p_send_back.set_defaults(func = cmd_send_back)

  # `strip-markup` — markup-resolved view for validation / terminal dispatch sources
  # waiver: argparse CLI signature, not a domain key
  p_strip = sub.add_parser(
      # waiver: argparse CLI signature, not a domain key
      "strip-markup", help = "print the doc body, without frontmatter, with edit markup resolved",
  )
  # waiver: argparse CLI signature, not a domain key
  p_strip.add_argument("file")
  p_strip.set_defaults(func = cmd_strip_markup)

  # `strip-frontmatter` — body-only view with raw markup, the main writer's dispatch source
  # waiver: argparse CLI signature, not a domain key
  p_strip_fm = sub.add_parser("strip-frontmatter", help = "print the doc body without its frontmatter")
  # waiver: argparse CLI signature, not a domain key
  p_strip_fm.add_argument("file")
  p_strip_fm.set_defaults(func = cmd_strip_frontmatter)

  # `fold-markup` — fold the edit markers in place on an operator approve gesture
  # waiver: argparse CLI signature, not a domain key
  p_fold = sub.add_parser("fold-markup", help = "fold the doc's edit markup in place")
  # waiver: argparse CLI signature, not a domain key
  p_fold.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_fold.add_argument("--repo", default = None)
  p_fold.set_defaults(func = cmd_fold_markup)

  # `strip-status` — remove every terminal-state status callout in place, no commit
  # waiver: argparse CLI signature, not a domain key
  p_strip_status = sub.add_parser("strip-status", help = "remove every #status/<state> callout from the doc body")
  # waiver: argparse CLI signature, not a domain key
  p_strip_status.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_strip_status.add_argument("--repo", default = None)
  p_strip_status.set_defaults(func = cmd_strip_status)

  # `strip-command` — remove the finished operator command callout in place, no commit
  p_strip_command = sub.add_parser(_STRIP_COMMAND_VERB, help = _STRIP_COMMAND_HELP)
  p_strip_command.add_argument(_ARG_FILE)
  p_strip_command.add_argument(_ARG_REPO, default = None)
  p_strip_command.set_defaults(func = cmd_strip_command)

  # `clear-multi-ticks` — clear the ticks of every question ticked more than once in place, no commit
  p_clear_ticks = sub.add_parser(_CLEAR_MULTI_TICKS_VERB, help = _CLEAR_MULTI_TICKS_HELP)
  p_clear_ticks.add_argument(_ARG_FILE)
  p_clear_ticks.add_argument(_ARG_REPO, default = None)
  p_clear_ticks.set_defaults(func = cmd_clear_multi_ticks)

  # `strip-discussion` — remove a report's discussion block in place, no commit
  p_strip_discussion = sub.add_parser(_STRIP_DISCUSSION_VERB, help = _STRIP_DISCUSSION_HELP)
  p_strip_discussion.add_argument(_ARG_FILE)
  p_strip_discussion.add_argument(_ARG_REPO, default = None)
  p_strip_discussion.set_defaults(func = cmd_strip_discussion)

  # `repair-structure` — the guess-free mechanical repair, written in place with no commit
  p_repair = sub.add_parser(_REPAIR_VERB, help = _REPAIR_HELP)
  p_repair.add_argument(_ARG_FILE)
  p_repair.add_argument(_ARG_CHECK, action = _STORE_TRUE)
  p_repair.add_argument(_ARG_REPO, default = None)
  p_repair.set_defaults(func = cmd_repair_structure)

  # `operator-text` — the passages of a document's prose the operator wrote or ordered by command
  p_operator = sub.add_parser(_OPERATOR_TEXT_VERB, help = _OPERATOR_TEXT_HELP)
  p_operator.add_argument(_ARG_FILE)
  p_operator.add_argument(_ARG_REPO, default = None)
  p_operator.set_defaults(func = cmd_operator_text)

  # `decision-clean` — whether a ticked decision box counts: nothing but the boxes changed since the system's turn
  p_decision = sub.add_parser(_DECISION_CLEAN_VERB, help = _DECISION_CLEAN_HELP)
  p_decision.add_argument(_ARG_FILE)
  p_decision.add_argument(_ARG_REPO, default = None)
  p_decision.set_defaults(func = cmd_decision_clean)

  # `configure-apply` — the wizard's collected class written through the core settings verbs
  p_configure = sub.add_parser(_CONFIGURE_VERB, help = _CONFIGURE_HELP)
  p_configure.add_argument(_ARG_REPO, default = None)
  p_configure.add_argument(_ARG_PAYLOAD, default = None)
  p_configure.add_argument(_ARG_PAYLOAD_FILE, default = None)
  p_configure.set_defaults(func = cmd_configure_apply)

  # `decisions-context` — decisions-registry context map for a main / barrier writer dispatch
  # waiver: argparse CLI signature, not a domain key
  p_decisions = sub.add_parser("decisions-context", help = "print the decisions-registry context map for one file")
  # waiver: argparse CLI signature, not a domain key
  p_decisions.add_argument("file")
  p_decisions.set_defaults(func = cmd_decisions_context)

  # `guidelines-context` — the role's plugin canon and the product guideline paths for a main / barrier writer dispatch
  # waiver: argparse CLI signature, not a domain key
  p_guidelines = sub.add_parser(
      "guidelines-context", help = "print the guideline paths one expert carries on one file",
  )
  # waiver: argparse CLI signature, not a domain key
  p_guidelines.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_guidelines.add_argument("expert")
  p_guidelines.set_defaults(func = cmd_guidelines_context)

  # `dispatch-writer` — the whole expert-job bundle built from the document, its class and a few flags
  p_dispatch = sub.add_parser(_DISPATCH_VERB, help = _DISPATCH_HELP)
  p_dispatch.add_argument(_ARG_FILE)
  p_dispatch.add_argument(_ARG_EXPERT)
  p_dispatch.add_argument(_ARG_SECTION_ID, default = None)
  p_dispatch.add_argument(_ARG_SECTION, default = None)
  p_dispatch.add_argument(_ARG_POSITION, default = None, choices = _POSITIONS)

  # repeatable: one `--context <path>` per extra file the job should find in its context
  p_dispatch.add_argument(_ARG_CONTEXT, action = _APPEND, default = None)
  p_dispatch.add_argument(_ARG_REPAIR, action = _STORE_TRUE)
  p_dispatch.add_argument(_ARG_REPO, default = None)
  p_dispatch.set_defaults(func = cmd_dispatch_writer)

  # `core-cli` — the resolved `lazycortex-core` CLI path for the coordinator agent's `<core-cli>`
  # waiver: argparse CLI signature, not a domain key
  p_core_cli = sub.add_parser("core-cli", help = "print the absolute path of the resolved lazycortex-core CLI")
  p_core_cli.set_defaults(func = cmd_core_cli)

  # every subcommand carries its handler in `func`, so the caller dispatches on the parse
  # result alone and never has to match subcommand names a second time
  return parser


def main(argv: list[str]) -> int:
  """
  Parse arguments and dispatch to the appropriate subcommand handler.

  Notes:
    - Every verb that takes `--repo` works in the root of the checkout of the directory `--repo` names (default:
      `$LAZY_REPO_ROOT`, then the working directory), a linked worktree's own root inside one.
    - `configure-apply` writes the settings nearest to `--repo` as given, so it receives that value unwidened.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code from the dispatched subcommand.
  """
  args = build_parser().parse_args(argv)

  # every verb that takes `--repo` works in the root of the checkout it names, else of `$LAZY_REPO_ROOT`, else of
  # the cwd; a relative document path is then read from that root
  if hasattr(args, _REPO_ATTR):
    setattr(args, _REPO_START_ATTR, args.repo)
    args.repo = str(_review_locator.query_repo_root(args.repo))

  # the verb's handler runs against the resolved root and its exit code is the command's
  return args.func(args)


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
