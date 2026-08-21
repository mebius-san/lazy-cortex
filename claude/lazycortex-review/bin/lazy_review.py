"""Main CLI for lazy-review (dispatched by the `lazycortex-review` shim).

Subcommands:

- `status`   — delegate to :mod:`status`.
- `parse-note` — delegate to :mod:`note_ops` (read-only structural report).
- `set-key`  — delegate to :mod:`note_ops` (write one reserved frontmatter key).
- `mark-job` — delegate to :mod:`job_markers` (write one runtime job marker; the only door
               into the sidecar the coordinator and the watch worker share).
- `paint-banner` — delegate to :mod:`note_ops` (repaint the top banner from frontmatter state).
- `collect-job` — delegate to :mod:`collect_ops` (land DONE job payloads; `--no-commit`
                 applies them to the working tree for the coordinator's own `commit-doc`).
- `collect-tick` — delegate to :mod:`collect_ops` (sweep the job queue, raise `job-done`
                 wakes and dispatch the coordinator — no landing, no commit).
- `sanitize` — delegate to :mod:`sanitize` (repair the three file-provable stuck review-loop
                 states: lost writer wakes, orphaned reviews, markers on vanished documents).
- `commit-doc` — delegate to :mod:`commit_doc` (the coordinator's single wake commit:
                 working-tree state + icon repaint, coordinator identity, mechanical trailer).
- `coordinator-dispatch` — delegate to :mod:`coordinator_dispatch` (detect a coordinator
                 wake trigger on one changed document and dispatch a job). The
                 `lazy-review.coordinator-watch` git-watch routine's own entrypoint.
- `start`    — delegate to :mod:`start`.
- `submit`   — delegate to :mod:`submit` (skip opening writer round).
- `stop`     — delegate to :mod:`stop`.
- `finalize` — delegate to :mod:`finalize`.
- `strip-markup` — print the document with its edit-annotation markup resolved (the
                 markup-final view validation / terminal dispatches use as source).
- `decisions-context` — delegate to :mod:`decisions_context` (print the `{filename: text}`
                 map of whichever decisions-registry file(s) resolve for one document; the
                 coordinator folds this into a main or barrier writer dispatch's `context`).
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))


def cmd_status(args: argparse.Namespace) -> int:
  """
  Delegate the `status` subcommand to the status module.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code from the status module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import status  # type: ignore
  return status.main([args.file])


def cmd_parse_note(args: argparse.Namespace) -> int:
  """
  Delegate the `parse-note` subcommand to the note_ops module.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code from the note_ops module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import note_ops  # type: ignore
  # waiver: `claude/lazycortex-specs/bin/note_ops.py` shares this basename; in a whole-project mypy
  # run the bare `import note_ops` above resolves to that unrelated module instead (this dir's
  # `__init__.py` makes review's own copy package-qualified as `bin.note_ops`), so mypy checks the
  # attribute against the wrong file's shape rather than skipping it as unresolved
  return note_ops.main([args.file, "--repo", args.repo])  # type: ignore[attr-defined]


def cmd_set_key(args: argparse.Namespace) -> int:
  """
  Delegate the `set-key` subcommand to the note_ops module.

  Args:
    args: Parsed namespace with `file`, `key`, `value`, and `repo` attributes.

  Returns:
    Exit code: 0 on success, 2 if the key is unknown (file untouched).

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing fence.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import note_ops  # type: ignore
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
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # read the document and attempt to set the key
  text = file_path.read_text()
  try:
    # waiver: type: ignore — note_ops is a deferred/late-bound sibling import; mypy cannot resolve it
    updated_text = note_ops.set_key(text, args.key, parsed_value)  # type: ignore[attr-defined]
  except ValueError as e:
    sys.stderr.write(f"{e}\n")
    return 2

  # write the updated document
  file_path.write_text(updated_text)
  return 0


def cmd_mark_job(args: argparse.Namespace) -> int:
  """
  Delegate the `mark-job` subcommand to the job_markers module.

  Args:
    args: Parsed namespace with `file`, `kind`, `job_id`, `clear`, and `repo` attributes.

  Returns:
    Exit code from the job_markers module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import job_markers  # type: ignore
  forward: list[str] = [args.file, args.kind]
  if args.job_id:
    forward.append(args.job_id)
  if args.clear:
    # waiver: argparse CLI signature, not a domain key
    forward.append("--clear")
  return job_markers.main([*forward, "--repo", args.repo])


def cmd_paint_banner(args: argparse.Namespace) -> int:
  """
  Delegate the `paint-banner` subcommand to the note_ops module.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code: 0 on success, 2 if the file does not exist (nothing written).

  Raises:
    ParseError: If the document has an opening frontmatter fence with no matching closing
      fence — mirrors `cmd_set_key`, which propagates the same failure uncaught.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import job_markers  # type: ignore
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import note_ops  # type: ignore
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  from keys import JobMarker  # type: ignore

  # resolve the file path against --repo, mirroring cmd_set_key
  repo = Path(args.repo).resolve()
  file_path = (repo / args.file).resolve()
  # guard: target file does not exist — nothing to repaint
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # repaint and write back — no commit, per the verb's contract. Whether a job is out on the
  # document is runtime state now, so the banner's in-process state comes from the sidecar
  text = file_path.read_text()
  in_flight = bool(job_markers.read(repo, file_path)[JobMarker.ACTIVE_JOB])
  # waiver: type: ignore — note_ops is a deferred/late-bound sibling import; mypy cannot resolve it
  updated_text = note_ops.repaint_banner(text, job_in_flight = in_flight)  # type: ignore[attr-defined]
  file_path.write_text(updated_text)
  return 0


def cmd_collect_job(args: argparse.Namespace) -> int:
  """
  Delegate the `collect-job` subcommand to the collect_ops module.

  Args:
    args: Parsed namespace with `file` and `repo` attributes.

  Returns:
    Exit code from the collect_ops module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import collect_ops  # type: ignore
  extra = ["--no-commit"] if args.no_commit else []
  return collect_ops.main([args.file, "--repo", args.repo, *extra])


def cmd_collect_tick(args: argparse.Namespace) -> int:
  """
  Delegate the `collect-tick` subcommand to the collect_ops module.

  Args:
    args: Parsed namespace with a `repo` attribute.

  Returns:
    Exit code from the collect_ops module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import collect_ops  # type: ignore
  return collect_ops.main_tick(["--repo", args.repo])


def cmd_sanitize(args: argparse.Namespace) -> int:
  """
  Delegate the `sanitize` subcommand to the sanitize module.

  Args:
    args: Parsed namespace with a `repo` attribute.

  Returns:
    Exit code from the sanitize module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import sanitize  # type: ignore
  return sanitize.main(["--repo", args.repo])


def cmd_coordinator_dispatch(args: argparse.Namespace) -> int:
  """
  Delegate the `coordinator-dispatch` subcommand to the coordinator_dispatch module.

  Args:
    args: Parsed namespace with `item_json` and `repo` attributes.

  Returns:
    Exit code from the coordinator_dispatch module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import coordinator_dispatch  # type: ignore
  return coordinator_dispatch.main([args.item_json, "--repo", args.repo])


def cmd_commit_doc(args: argparse.Namespace) -> int:
  """
  Delegate the `commit-doc` subcommand to the commit_doc module.

  Args:
    args: Parsed namespace with `file`, `subject`, and `repo` attributes.

  Returns:
    Exit code from the commit_doc module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import commit_doc  # type: ignore
  return commit_doc.main([args.file, "--subject", args.subject, "--repo", args.repo])


def cmd_start(args: argparse.Namespace) -> int:
  """
  Delegate the `start` subcommand to the start module.

  Args:
    args: Parsed namespace with `file` and optional `expert` / `no_commit` attributes.

  Returns:
    Exit code from the start module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import start  # type: ignore
  forward: list[str] = [args.file]
  if args.expert:
    forward.extend(["--expert", args.expert])
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
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import submit  # type: ignore
  forward: list[str] = [args.file]
  if args.expert:
    forward.extend(["--expert", args.expert])
  return submit.main(forward)


def cmd_stop(args: argparse.Namespace) -> int:
  """
  Delegate the `stop` subcommand to the stop module.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code from the stop module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import stop  # type: ignore
  return stop.main([args.file])


def cmd_finalize(args: argparse.Namespace) -> int:
  """
  Delegate the `finalize` subcommand to the finalize module.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code from the finalize module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import finalize  # type: ignore
  return finalize.main([args.file])


def cmd_strip_markup(args: argparse.Namespace) -> int:
  """
  Print the document with its edit-annotation markup resolved to final text.

  The body is run through `edit_markup.strip_markers` with the repo's configured
  `review.edit_marker_style`; the frontmatter is printed untouched. Used by the
  coordinator to build the markup-resolved source for validation / terminal
  writer dispatches — those experts judge the document's final state, not the
  raw diff material main writers work on.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code: 0 on success (unknown configured style degrades to printing the
    document unchanged), 2 when the file is missing or not markdown.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import edit_markup  # type: ignore
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import finalize  # type: ignore
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import frontmatter as _fm  # type: ignore
  file_path = Path(args.file).resolve()

  # guard: only an existing markdown file has a review body to resolve
  # waiver: filesystem path idiom
  if not file_path.is_file() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2

  # split the document once — the frontmatter half passes through untouched
  # waiver: explicit utf-8 for pylint W1514; the repo-wide file encoding, not a domain constant
  text = file_path.read_text(encoding = "utf-8")
  _meta, body = _fm.parse(text)
  fm_text = text[: len(text) - len(body)]

  # resolve the body's edit markup per the configured style; an unknown style must not
  # kill the dispatch — `body` stays the raw document half and the verb degrades gracefully
  style = finalize.settings_edit_marker_style(file_path)
  try:
    body = edit_markup.strip_markers(body, style=style)
  except ValueError:
    pass

  # the resolved document goes to stdout whole — the caller pipes it straight into a source file
  sys.stdout.write(fm_text + body)
  return 0


def cmd_decisions_context(args: argparse.Namespace) -> int:
  """
  Print the decisions-registry context map for one review document.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code: always 0. Prints the JSON `{filename: text}` decisions-registry context map to
    stdout on every call; the target document need not exist on disk.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  import decisions_context  # type: ignore

  # resolve the target file — the same absolute-path convention cmd_strip_markup uses
  file_path = Path(args.file).resolve()

  # the verb's whole contract is this one JSON line, piped straight into the coordinator's dispatch build
  # waiver: type: ignore — decisions_context is a deferred/late-bound sibling import; mypy cannot resolve it
  print(json.dumps(decisions_context.collect(file_path)))  # type: ignore[attr-defined]
  return 0


def build_parser() -> argparse.ArgumentParser:
  """
  Build and return the top-level argument parser for the lazy-review CLI.

  Returns:
    Configured argument parser with all subcommands registered.
  """
  # the `mark-job` kind tokens below are the sidecar's own, so they come from `keys` rather
  # than being re-spelled in the CLI surface
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: sibling module resolved at runtime via the sys.path.insert above; mypy cannot see that path
  from keys import JobMarker  # type: ignore

  # the root parser and the subcommand slot every verb below registers itself into
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review")
  # waiver: argparse CLI signature, not a domain key
  sub = parser.add_subparsers(dest="cmd", required=True)

  # `status` — read-only introspection for the operator
  # waiver: argparse CLI signature, not a domain key
  p_status = sub.add_parser("status", help="introspect one file")
  # waiver: argparse CLI signature, not a domain key
  p_status.add_argument("file")
  p_status.set_defaults(func=cmd_status)

  # `parse-note` — read-only structural report for the coordinator / watch worker
  # waiver: argparse CLI signature, not a domain key
  p_parse = sub.add_parser("parse-note", help="structural report for one file")
  # waiver: argparse CLI signature, not a domain key
  p_parse.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_parse.add_argument("--repo", default=".")
  p_parse.set_defaults(func=cmd_parse_note)

  # `set-key` — write a frontmatter key to a review document
  # waiver: argparse CLI signature, not a domain key
  p_set = sub.add_parser("set-key", help="set frontmatter key in a review document")
  # waiver: argparse CLI signature, not a domain key
  p_set.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_set.add_argument("key")
  # waiver: argparse CLI signature, not a domain key
  p_set.add_argument("value")
  # waiver: argparse CLI signature, not a domain key
  p_set.add_argument("--repo", default=".")
  p_set.set_defaults(func=cmd_set_key)

  # `mark-job` — write one runtime job marker into the gitignored sidecar
  # waiver: argparse CLI signature, not a domain key
  p_mark = sub.add_parser("mark-job", help="set or clear one runtime job marker on a review document")
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("kind", choices=[JobMarker.KIND_COORDINATOR, JobMarker.KIND_WRITER])
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("job_id", nargs="?", default=None)
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("--clear", action="store_true")
  # waiver: argparse CLI signature, not a domain key
  p_mark.add_argument("--repo", default=".")
  p_mark.set_defaults(func=cmd_mark_job)

  # `paint-banner` — repaint the top banner from the document's current frontmatter state
  # waiver: argparse CLI signature, not a domain key
  p_paint = sub.add_parser("paint-banner", help="repaint the review banner from frontmatter state")
  # waiver: argparse CLI signature, not a domain key
  p_paint.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_paint.add_argument("--repo", default=".")
  p_paint.set_defaults(func=cmd_paint_banner)

  # `collect-job` — land DONE job payloads for one file as one bot commit
  # waiver: argparse CLI signature, not a domain key
  p_collect = sub.add_parser("collect-job", help="land DONE job payloads for one review document")
  # waiver: argparse CLI signature, not a domain key
  p_collect.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_collect.add_argument("--repo", default=".")
  # waiver: argparse CLI signature, not a domain key
  p_collect.add_argument("--no-commit", action="store_true")
  p_collect.set_defaults(func=cmd_collect_job)

  # `collect-tick` — sweep the whole job queue, landing every DONE-and-not-CONSUMED job
  # waiver: argparse CLI signature, not a domain key
  p_collect_tick = sub.add_parser("collect-tick", help="sweep the job queue for finished review jobs")
  # waiver: argparse CLI signature, not a domain key
  p_collect_tick.add_argument("--repo", default=".")
  p_collect_tick.set_defaults(func=cmd_collect_tick)

  # `sanitize` — repair the three file-provable stuck review-loop states
  # waiver: argparse CLI signature, not a domain key
  p_sanitize = sub.add_parser("sanitize", help = "repair stuck review-loop state")
  # waiver: argparse CLI signature, not a domain key
  p_sanitize.add_argument("--repo", default = ".")
  p_sanitize.set_defaults(func = cmd_sanitize)

  # `commit-doc` — the coordinator's single wake commit, repaint folded in
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc = sub.add_parser("commit-doc", help="commit one review document's wake state")
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc.add_argument("--subject", required=True)
  # waiver: argparse CLI signature, not a domain key
  p_commit_doc.add_argument("--repo", default=".")
  p_commit_doc.set_defaults(func=cmd_commit_doc)

  # `coordinator-dispatch` — the git-watch routine's entrypoint for one changed document
  # waiver: argparse CLI signature, not a domain key
  p_coord = sub.add_parser("coordinator-dispatch", help="detect a coordinator wake trigger and dispatch")
  # waiver: argparse CLI signature, not a domain key
  p_coord.add_argument("item_json")
  # waiver: argparse CLI signature, not a domain key
  p_coord.add_argument("--repo", default=".")
  p_coord.set_defaults(func=cmd_coordinator_dispatch)

  # `start` — opt a document in, opening writer round included
  # waiver: argparse CLI signature, not a domain key
  p_start = sub.add_parser("start", help="opt a file into review")
  # waiver: argparse CLI signature, not a domain key
  p_start.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_start.add_argument("--expert", default=None)
  # waiver: argparse CLI signature, not a domain key
  p_start.add_argument("--no-commit", action="store_true",
                       # waiver: one-off human-facing message -- argparse help text
                       help="apply the bootstrap but leave the commit to the caller")
  p_start.set_defaults(func=cmd_start, no_commit=False)

  # `submit` — opt a document in with the opening writer round skipped
  p_submit = sub.add_parser(
      # waiver: argparse CLI signature, not a domain key
      "submit", help="opt a file into review skipping the opening writer round")
  # waiver: argparse CLI signature, not a domain key
  p_submit.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_submit.add_argument("--expert", default=None)
  p_submit.set_defaults(func=cmd_submit)

  # `stop` — opt a document out mid-cycle
  # waiver: argparse CLI signature, not a domain key
  p_stop = sub.add_parser("stop", help="opt a file out of review")
  # waiver: argparse CLI signature, not a domain key
  p_stop.add_argument("file")
  p_stop.set_defaults(func=cmd_stop)

  # `finalize` — strip the review's markup from an approved document
  # waiver: argparse CLI signature, not a domain key
  p_final = sub.add_parser("finalize", help="finalize a fully-approved doc")
  # waiver: argparse CLI signature, not a domain key
  p_final.add_argument("file")
  p_final.set_defaults(func=cmd_finalize)

  # `strip-markup` — markup-resolved view for validation / terminal dispatch sources
  # waiver: argparse CLI signature, not a domain key
  p_strip = sub.add_parser("strip-markup", help="print the doc with edit markup resolved")
  # waiver: argparse CLI signature, not a domain key
  p_strip.add_argument("file")
  p_strip.set_defaults(func=cmd_strip_markup)

  # `decisions-context` — decisions-registry context map for a main / barrier writer dispatch
  # waiver: argparse CLI signature, not a domain key
  p_decisions = sub.add_parser("decisions-context", help="print the decisions-registry context map for one file")
  # waiver: argparse CLI signature, not a domain key
  p_decisions.add_argument("file")
  p_decisions.set_defaults(func=cmd_decisions_context)

  # every subcommand carries its handler in `func`, so the caller dispatches on the parse
  # result alone and never has to match subcommand names a second time
  return parser


def main(argv: list[str]) -> int:
  """
  Parse arguments and dispatch to the appropriate subcommand handler.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code from the dispatched subcommand.
  """
  parser = build_parser()
  args = parser.parse_args(argv)
  return args.func(args)


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
