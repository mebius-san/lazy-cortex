"""Postman for finished expert jobs: wake the coordinator, land payloads on demand.

`collect-tick` (the routine sweep) walks `<repo>/.experts/.jobs/<expert>/<job_id>/` for
DONE-and-not-CONSUMED job bundles and, per target document, clears the runtime `active_job`
marker, raises the `job-done` pending wake, and dispatches the coordinator directly — the
sweep itself no longer lands payloads and no longer commits.
The landing happens inside the coordinator's own wake, via `collect-job --no-commit`:
payloads are applied to the working tree via `reapply.reapply` (mirrors `dispatcher.py`'s
`_collect_one_barrier_section`, copied rather than imported — per the lazycortex-review
coordinator migration's own-verbs-only boundary, `dispatcher.py` is being retired), each
applied job is marked `CONSUMED`, and the coordinator's single `commit-doc` carries payload
and settle together. The standalone `collect-job` (without `--no-commit`) keeps the old
one-mechanical-bot-commit shape for hand runs. This module carries no scheduling judgment:
a `DEAD` job, a job still pending, or a job already `CONSUMED` is left exactly as found for
whoever dispatched it to decide what happens next.

Request-payload fields this module reads (written by the job's dispatcher; `mode` is the
same structural field `payload.build_request` already writes — `"main"` for a full-document
payload, `"validation"` / `"terminal"` for a section-writer payload):

    {
      "_target_file": "<absolute path of the reviewed document>",
      "mode":       "main" | "validation" | "terminal",
      "expert":     "<dispatch name of the section-owning writer>",  # required when mode != "main"
      "section_id": "<section id>",                                  # required when mode != "main"
      "section":    "<H1 section title>",                            # optional; defaults from `section_id`
      "position":   "top" | "bottom"                                 # optional; defaults to bottom
    }

Response-payload fields this module reads (the agent's `response.json`):

    {
      "outcome": "edited" | "empty" | "error",
      "result": ["result/<relpath>"]   # required when outcome == "edited"
    }

Only `outcome == "edited"` jobs are applied; every other outcome, and every malformed
request/response, is left uncollected for a future pass to interpret.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# pylint: disable=import-error,wrong-import-position,deprecated-module

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import git_ops as _git_ops  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import job_markers as _job_markers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import parser as _parser  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import coordinator_dispatch as _coordinator_dispatch  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import reapply as _reapply  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import (  # noqa: E402
    BotIdentity, CoreCommand, EnvVar, JobFile, JobKey, JobMarker, JobStatus, Outcome, Paths, Phase, Plugin, Tag,
)


# ------------------------------------------------------------- job discovery


def _job_target(repo: Path, jdir: Path, data: dict) -> Path | None:
  """
  Resolve the document a job bundle targets.

  Args:
    repo: Absolute path to the repository root.
    jdir: The job-bundle directory.
    data: The bundle's parsed `request.json`.

  Returns:
    The target document's path — from the payload's `_target_file` when the dispatch
    carried it, else recovered through the job-markers sidecar (`mark-job` records the
    document→job link before every dispatch) — or `None` when neither names one.
  """
  target = data.get(JobKey.TARGET_FILE)
  if isinstance(target, str) and target.strip():
    return Path(target)

  # fallback: the mark-job marker written before dispatch still links doc to job
  key = _job_markers.doc_for_job(repo, jdir.name)
  # guard: no payload field and no marker entry — the job is unaddressable
  if key is None:
    return None
  return repo / key


def _job_dirs_for_file(repo: Path, file_path: Path) -> list[Path]:
  """
  Return every job-bundle directory under `.experts/.jobs/` that targets `file_path`.

  Args:
    repo: Absolute path to the repository root.
    file_path: Absolute path to the review document.

  Returns:
    List of job-bundle directories, in filesystem iteration order.
  """
  jobs_root = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR
  # guard: no job queue at all — nothing can target this file
  if not jobs_root.is_dir():
    return []
  target = str(file_path)
  out: list[Path] = []
  for expert_dir in jobs_root.iterdir():
    # guard: only expert subdirectories hold job bundles
    if not expert_dir.is_dir():
      continue
    for jdir in expert_dir.iterdir():
      # guard: only job subdirectories carry a request.json
      if not jdir.is_dir():
        continue
      req = jdir / JobFile.REQUEST
      # guard: job dir without a request.json carries no target to match
      if not req.is_file():
        continue
      try:
        data = json.loads(req.read_text())
      except (OSError, json.JSONDecodeError):
        continue
      resolved = _job_target(repo, jdir, data)
      # a payload target is compared verbatim (dispatchers write the same absolute string),
      # while a sidecar-recovered `repo / key` needs symlink-safe resolution to match it
      if resolved is not None and (str(resolved) == target or resolved.resolve() == file_path.resolve()):
        out.append(jdir)
  return out


def _job_status(jdir: Path) -> str:
  """
  Classify a job bundle by its terminal marker files.

  Args:
    jdir: Job-bundle directory to classify.

  Returns:
    One of `Outcome.CONSUMED`, `JobStatus.DEAD`, `JobStatus.CANCELLED`, `JobStatus.DONE`, or
    `JobStatus.PENDING`, in precedence order when more than one marker is present: a consumed
    job always classifies as `CONSUMED` before `JobStatus.DEAD`, which takes precedence over
    `JobStatus.CANCELLED`, which in turn takes precedence over `JobStatus.DONE` (a cancelled
    job's payload must never be collected); a job carrying none of the markers classifies as
    `JobStatus.PENDING`.
  """
  if (jdir / Outcome.CONSUMED).exists():
    return Outcome.CONSUMED
  if (jdir / JobFile.DEAD).exists():
    return JobStatus.DEAD
  if (jdir / JobFile.CANCELLED).exists():
    return JobStatus.CANCELLED
  if (jdir / JobFile.DONE).exists():
    return JobStatus.DONE
  return JobStatus.PENDING


# --------------------------------------------------------------- payload apply


def _build_agent_body(jdir: Path, request: dict, response: dict) -> tuple[str, str, tuple[str, str] | None]:
  """
  Build the `reapply.reapply` inputs for one job's response payload.

  Args:
    jdir: Job-bundle directory the response's `result` path resolves against.
    request: Parsed `request.json` contents.
    response: Parsed `response.json` contents.

  Returns:
    A `(agent_body, phase, owned_owner)` tuple ready to pass into `reapply.reapply`. `mode ==
    "main"` yields a main-writer's full document body with `owned_owner` `None`; any other
    mode (`"validation"` / `"terminal"`) yields the body wrapped in the owned section's
    heading and ownership tag, with `owned_owner` identifying that section.
  """
  result_entry = response[JobKey.RESULT][0]
  result_relpath = result_entry.get(JobKey.PATH) if isinstance(result_entry, dict) else result_entry
  # guard: a result entry that resolves to anything but a path string is a malformed response
  if not isinstance(result_relpath, str):
    raise KeyError("result entry carries no path")
  result_text = (jdir / result_relpath).read_text()
  _result_meta, result_body = _fm.parse(result_text)

  # guard: a main-writer payload is the full document body, no owned section
  if request.get(JobKey.MODE) == Phase.MAIN:
    return result_body, Phase.MAIN, None

  # wrap the response body in the owned section's heading and ownership tag, per _reassemble_section
  section_id = request[JobKey.SECTION_ID]
  flat_expert = _parser.flatten_expert_name(request[JobKey.EXPERT])
  owner = (flat_expert, section_id)
  title = request.get(JobKey.SECTION) or section_id.replace("_", " ").capitalize()
  owner_tag = f"{Tag.EXPERT_PREFIX}{flat_expert}/{section_id}"
  stripped = result_body.strip("\n")
  agent_body = f"# {title}\n{owner_tag}\n\n{stripped}\n" if stripped else f"# {title}\n{owner_tag}\n"
  return agent_body, Phase.SECTION, owner


def _apply_one_job(text: str, jdir: Path, request: dict, response: dict) -> str | None:
  """
  Apply one DONE job's response to `text`.

  Args:
    text: Current document text (frontmatter + body).
    jdir: Job-bundle directory the response's `result` path resolves against.
    request: Parsed `request.json` contents.
    response: Parsed `response.json` contents.

  Returns:
    The updated document text, or `None` when the response's outcome is not `edited`,
    carries no `result`, or the payload is otherwise malformed — left uncollected for a
    future pass to interpret.
  """
  # guard: only a completed edit carries content to land; empty/error responses are left uncollected
  if response.get(JobKey.OUTCOME) != Outcome.EDITED:
    return None
  result = response.get(JobKey.RESULT)
  # guard: outcome=edited without a result payload is a malformed response — leave it uncollected
  if not isinstance(result, list) or not result:
    return None
  # a malformed request (e.g. `section_id` without a matching `expert`) leaves the job uncollected
  try:
    agent_body, phase, owner = _build_agent_body(jdir, request, response)
  except (KeyError, OSError):
    return None
  section_layout = (
      {owner: request[JobKey.POSITION]} if owner is not None and JobKey.POSITION in request else None
  )
  # graft the response onto the operator's current document via the existing reapply pipeline
  reapply_result = _reapply.reapply(
      operator_text=text,
      agent_body=agent_body,
      phase=phase,
      agent_frontmatter_overlay={},
      owned_owner=owner,
      section_layout=section_layout,
  )
  return reapply_result.text


# ------------------------------------------------------------- consume (§1c)


def _resolve_core_cli() -> Path | None:
  """
  Find the `lazycortex-core` CLI binary.

  Returns:
    Absolute path to the resolved binary, preferring `$LAZYCORTEX_PLUGIN_DIRS` over the
    plugin cache, or `None` when neither lookup finds one.
  """
  # waiver: matches dispatcher.py's own literal — not a keys.py-promoted constant there either
  dirs = os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "").split(os.pathsep)
  for d in dirs:
    # guard: empty path segment (from a trailing/double pathsep) — skip it
    if not d:
      continue
    cli = Path(d) / Paths.BIN_DIR / Plugin.CORE
    if cli.is_file():
      return cli
  cache = Path.home() / Paths.PLUGIN_CACHE
  # guard: no plugin cache on this machine — nothing further to try
  if not cache.is_dir():
    return None
  plugin_dirs = [
      registry / Plugin.CORE
      for registry in cache.iterdir()
      if registry.is_dir() and (registry / Plugin.CORE).is_dir()
  ]
  all_versions = [v for pd in plugin_dirs for v in pd.iterdir() if v.is_dir()]
  # guard: no installed version found — nothing further to try
  if not all_versions:
    return None
  latest = sorted(all_versions, key=lambda v: v.name, reverse=True)[0]
  cli = latest / Paths.BIN_DIR / Plugin.CORE
  return cli if cli.is_file() else None


def _consume_job(repo: Path, jdir: Path) -> None:
  """
  Mark one job bundle consumed.

  Notes:
    - Falls back to touching a local marker file when the core CLI cannot be resolved or
      the call fails, so the job ends up consumed either way.

  Args:
    repo: Absolute path to the repository root.
    jdir: Job-bundle directory to consume; its parent/own directory names are the expert
      and job id the `consume-job` CLI call needs.
  """
  cli = _resolve_core_cli()
  if cli is not None:
    env = os.environ.copy()
    env[EnvVar.LAZY_REPO_ROOT] = str(repo)
    try:
      proc = subprocess.run(
          [str(cli), CoreCommand.CONSUME_JOB],
          input=json.dumps({JobKey.EXPERT: jdir.parent.name, JobKey.JOB_ID: jdir.name}),
          capture_output=True, text=True, env=env, check=False,
      )
      # guard: the core CLI consumed the job — the local fallback marker is not needed
      if proc.returncode == 0:
        return
    # waiver: consume is fire-and-forget (error-ledger reporting is best-effort) — a failed
    # core-CLI call falls through to the local marker rather than aborting the collect pass
    except OSError:
      pass
  # fallback: same-repo direct marker touch, mirroring dispatcher.py's own `_core_consume_job`
  # fallback path when the CLI cannot be resolved
  (jdir / Outcome.CONSUMED).touch()


# ------------------------------------------------------------------- collect


def collect_for_file(repo: Path, file_path: Path, *, commit: bool = True) -> dict:
  """
  Land every DONE-and-not-CONSUMED job targeting `file_path`.

  Args:
    repo: Absolute path to the repository root.
    file_path: Absolute path to the review document.
    commit: When `True` (the standalone `collect-job` shape), the batch lands as one
      mechanical bot commit and the `job-done` pending wake is raised. When `False` (the
      coordinator collecting inside its own wake, `collect-job --no-commit`), the payloads
      are applied to the working tree only — no commit and no pending wake, because the
      wake being served is the one that asked for this landing; the coordinator's own
      `commit-doc` carries the result.

  Returns:
    `{"collected": N}` — the number of jobs whose payload was applied. The document and
    the job queue are left untouched when `N` is `0`.
  """
  candidates = [jdir for jdir in _job_dirs_for_file(repo, file_path) if _job_status(jdir) == JobStatus.DONE]
  original = file_path.read_text()
  text = original
  applied: list[Path] = []
  for jdir in candidates:
    try:
      request = json.loads((jdir / JobFile.REQUEST).read_text())
      response = json.loads((jdir / JobFile.RESPONSE).read_text())
    except (OSError, json.JSONDecodeError):
      continue
    new_text = _apply_one_job(text, jdir, request, response)
    # guard: nothing to apply for this job — leave it uncollected
    if new_text is None:
      continue
    text = new_text
    applied.append(jdir)

  # guard: nothing landed — the document and the queue stay exactly as found
  if not applied:
    return {"collected": 0}

  # drain the queue either way; the wake plumbing differs per caller below
  for jdir in applied:
    _consume_job(repo, jdir)

  # the coordinator collecting inside its own wake: worktree write only, its `commit-doc`
  # carries the result and no new wake is raised for a landing already being served
  if not commit:
    _job_markers.update(repo, file_path, { JobMarker.ACTIVE_JOB: None })
    if text != original:
      file_path.write_text(text)
    return {"collected": len(applied)}

  # standalone shape: hand the turn back — the `active_job` marker comes off and the
  # `job-done` wake goes up in the same sidecar write, before the commit that carries it — a
  # commit that lands without the flag would be an operator-edit wake instead of a job-done one
  _job_markers.update(
      repo, file_path,
      { JobMarker.ACTIVE_JOB: None, JobMarker.PENDING_WAKE: JobMarker.JOB_DONE },
  )

  # limit: a payload that reproduces the document byte-for-byte leaves nothing to commit, so no
  # git item carries the wake and the document waits for the next commit to deliver it; give the
  # postman its own wake channel if experts start landing no-op edits routinely
  if text != original:
    file_path.write_text(text)
    _git_ops.commit_mechanical(
        repo, file_path,
        author={JobKey.NAME: BotIdentity.NAME, JobKey.EMAIL: BotIdentity.EMAIL},
        message=f"review: collect {len(applied)} job(s)",
    )
  return {"collected": len(applied)}


# ---------------------------------------------------------------------- tick


def collect_tick(repo: Path) -> dict:
  """
  Raise a `job-done` wake and dispatch the coordinator for every document with finished work.

  The postman sweep no longer lands payloads or commits anything. For each target file
  carrying at least one DONE-and-not-CONSUMED job it clears the `active_job` marker, raises
  the `job-done` pending wake, and dispatches the coordinator directly (no git item is
  needed — nothing was committed). The coordinator lands the payload itself with
  `collect-job --no-commit` inside its wake and commits once, payload and settle together.

  A target whose coordinator is still busy is left with its wake raised and its jobs still
  DONE — the next sweep retries the dispatch, so a died coordinator job cannot strand the
  landing. A job bundle that fails to parse, or a target whose dispatch raises, is logged
  to stderr and retried on a future sweep — it does not stop the rest of the batch.

  Guarantees:
    - A DONE job bundle that cannot be resolved to a target file belongs to another
      plugin's pipeline and is skipped silently: never counted, never written to stderr,
      and never surfaced as an `error` in the sweep summary.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    `{"files": N, "dispatched": M}` — N is the number of distinct target files that carried
    at least one finished job, M is how many coordinator jobs this sweep queued. Carries an
    additional `"error"` field summarizing the failures when one or more targets could not
    be processed (the error-ledger contract — a failed sweep must not report success via exit 0).
  """
  jobs_root = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR
  # guard: no job queue at all — nothing to sweep
  if not jobs_root.is_dir():
    return {"files": 0, "dispatched": 0}

  # walk every DONE-and-not-CONSUMED job once, collecting its target file and job ids. Only a
  # deliverable payload counts: an `edited` outcome is the one thing `collect-job` will land
  # and consume. A coordinator's own DONE job (`handled`), an `empty`/`error` writer, and a
  # response-less bundle would never be consumed — counting them would re-dispatch the
  # coordinator every tick forever (found live: 16 self-fed coordinator wakes).
  targets: dict[Path, list[str]] = {}
  broken: list[str] = []
  for expert_dir in sorted(jobs_root.iterdir()):
    # guard: only expert subdirectories hold job bundles
    if not expert_dir.is_dir():
      continue
    for jdir in sorted(expert_dir.iterdir()):
      # guard: only DONE-and-not-CONSUMED job dirs are due for this sweep
      if not jdir.is_dir() or _job_status(jdir) != JobStatus.DONE:
        continue
      try:
        data = json.loads((jdir / JobFile.REQUEST).read_text())
      except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"collect-tick: {jdir}: {exc}\n")
        broken.append(str(jdir))
        continue
      resolved = _job_target(repo, jdir, data)

      # Contract:
      # A DONE job bundle whose `request.json` carries no `_target_file` and whose job id
      # has no row in the review job-markers sidecar belongs to another plugin's pipeline
      # and is skipped silently: never counted, never written to stderr, never surfaced as
      # an `error` in the sweep summary, and it never blocks collection of the rest of the
      # batch. Every review-system dispatch writes `_target_file` or a sidecar row, so an
      # unresolvable bundle is, by construction, foreign.

      # guard: no `_target_file` and no marker link — the job belongs to another plugin's
      # pipeline (every review dispatch writes one or the other), so it is skipped silently
      if resolved is None:
        continue
      # guard: only an `edited` payload is deliverable — everything else stays for the
      # coordinator to judge off the stuck `active_job` marker, exactly as before the merge
      try:
        outcome = json.loads((jdir / JobFile.RESPONSE).read_text()).get(JobKey.OUTCOME)
      except (OSError, json.JSONDecodeError):
        continue
      # guard: non-edited outcomes are never consumed by collect-job, so never counted here
      if outcome != Outcome.EDITED:
        continue
      targets.setdefault(resolved, []).append(jdir.name)

  # raise the wake and dispatch the coordinator per target; one bad target logs and continues
  dispatched = 0
  failed: list[str] = []
  for doc, job_ids in sorted(targets.items()):
    try:
      _job_markers.update(
          repo, doc,
          { JobMarker.ACTIVE_JOB: None, JobMarker.PENDING_WAKE: JobMarker.JOB_DONE },
      )
      # waiver: type: ignore — coordinator_dispatch is a deferred/late-bound sibling import; mypy cannot resolve it
      result = _coordinator_dispatch.dispatch_job_done(  # type: ignore[attr-defined]
          repo, doc, "+".join(sorted(job_ids)),
      )
    # waiver: this sweep's per-target error boundary — one bad target must not stop the rest
    except Exception as exc:
      sys.stderr.write(f"collect-tick: {doc}: {exc}\n")
      failed.append(str(doc))
      continue
    # waiver: 'action' matches coordinator_dispatch's own wire-shape key, not a keys.py-promoted constant
    if result.get("action") == "dispatched":
      dispatched += 1

  # the "error" field is additive — a clean sweep's summary stays exactly the two keys above
  # waiver: 'files'/'dispatched' are this sweep's own wire-shape keys, not keys.py-promoted constants
  summary: dict[str, int | str] = {"files": len(targets), "dispatched": dispatched}
  errors = broken + failed
  # a sweep with failures must not report success via exit 0 (the error-ledger contract)
  if errors:
    summary[JobKey.ERROR] = f"{len(errors)} job(s) failed to collect: {', '.join(errors)}"
  return summary


def main_tick(argv: list[str]) -> int:
  """
  Run `collect_tick` and print its summary.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: `0` when the sweep completed with nothing left uncollected, `1` when at least
    one target failed to collect.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazycortex-review collect-tick")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default=".")
  args = parser.parse_args(argv)

  # resolve --repo then run the sweep; the CLI's whole contract is this one summary line
  repo = Path(args.repo).resolve()
  summary = collect_tick(repo)
  # waiver: 'files'/'dispatched' are collect_tick's own wire-shape keys, not keys.py-promoted constants
  print(json.dumps({"files": summary["files"], "dispatched": summary["dispatched"]}))
  return 1 if JobKey.ERROR in summary else 0


def main(argv: list[str]) -> int:
  """
  Land every DONE job targeting one review document and print the collected count.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: `0` on success, `2` when the target file does not exist.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazycortex-review collect-job")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default=".")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-commit", action="store_true")
  args = parser.parse_args(argv)

  # `file` resolves against `--repo` unless it's already absolute, mirroring the other verbs
  repo = Path(args.repo).resolve()
  file_path = (repo / args.file).resolve()
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2

  # the CLI's whole contract is this one summary line
  print(json.dumps(collect_for_file(repo, file_path, commit=not args.no_commit)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
