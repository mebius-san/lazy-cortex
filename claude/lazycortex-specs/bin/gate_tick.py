"""
Per-file gate-tick worker for the md-scan daemon.

Invoked once per matched asset status folder-note. `spec.coordinator` (per
`lazy-spec.coordination-playbook.md`, dispatched by the sibling `coordinator_dispatch.py` routine, not
by this one) now owns every inter- and intra-asset sequencing decision — which gate to flip,
which sibling doc to promote, which checkbox-equivalent job to dispatch next, whether a change
cascades into its targets. This worker keeps only the three concerns no LLM needs to be woken for:

- Active-job polling (`spec_job_markers.py`'s `active_job`): an asset tracking the marker has its
  job bundle's terminal marker (`DONE` / `DEAD` / `CANCELLED`, per the `lazycortex-core` job-runtime
  layout, read file-wise — never imported across the plugin boundary) checked on every tick.
  `DONE` lands the job's `result/` into the asset folder through the `land-result` collector —
  the only channel a job's document and attachments take into the catalog — then clears the
  marker, logs a `# History` line, and retires the bundle (`gate_dispatch.consume_stale_job`,
  freeing its dedup key so the checkbox can be re-dispatched); `CANCELLED` does the same without
  the landing; `DEAD` additionally sets `spec_halted: true` and appends a persistent `[!failure]`
  callout to `# Gates` (un-halting is a manual operator act, out of scope here), leaving its
  bundle unretired for diagnostics. Every clear also raises `pending_wake: job-done` in the sidecar — that flag,
  not a diff of the clearing commit, is what makes the transition visible to
  `coordinator_dispatch.py`'s own `job-done` trigger. This worker opens no review itself; the
  coordinator opens it with `lazy-review.submit` on the `job-done` wake this same poll raises.
- Coordinator-job polling (`spec_job_markers.py`'s `coordinator_job`): the same terminal-marker
  check, applied to the coordinator's own one-job-per-asset slot instead. `DONE` / `CANCELLED` retire the
  bundle (`gate_dispatch.consume_stale_job`, freeing its dedup key) and clear the marker, touching
  the note not at all — that branch's whole effect is runtime state, so it costs no commit; `DEAD`
  clears the marker, writes a `# History` WARNING line, and never halts the asset — the
  coordinator's own wake job is not a ladder expert job, so `spec_halted` stays untouched. This
  sweep is `coordinator_dispatch.py`'s own backstop: that git-watch routine only re-checks a
  coordinator job's marker when a NEW commit wakes it, so a job that dies with no further commit
  landing would otherwise leave the marker stranded forever — this worker's periodic md-scan
  cadence catches it regardless (4a debt, plan 4b Task 5).
- Structural note-check: `note_ops.note_check`'s violations (an unrecognized or mistyped
  frontmatter key, a missing or misordered required section) are folded into this tick's own
  result — read-only, repaired by the coordinator through its pen and `note-set-key`, never by
  this worker.

A no-op tick (no active job with a terminal marker yet, note structurally clean) reports
`{"action": "noop"}`. `coordinator_dispatch.py` is this worker's own sibling routine, not a step
of this tick — it wakes `spec.coordinator` on its own schedule.
"""
from __future__ import annotations

import argparse
import json
import re
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
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import iconize_inline  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    HaltReason,
    HistoryEvent,
    JobMarker,
    TickAction,
)


# Regex template for locating a frontmatter key's line, shared by `set_fm_json` / `del_fm_key`.
_FM_KEY_RE_TEMPLATE = r"(?m)^{key}\s*:.*$"
# Trailing-newline suffix `del_fm_key` appends to `_FM_KEY_RE_TEMPLATE` so the deleted key's
# own line break goes with it, rather than leaving a blank line behind.
_TRAILING_NEWLINE_RE = r"\n?"

# The sibling CLI entry point's bare filename, resolved via `_BIN` (this module's own directory)
# rather than `$LAZYCORTEX_PLUGIN_DIRS` — `_run_note_check` calls back into this same plugin, not
# across the plugin boundary.
_SPEC_CLI_NAME = "lazycortex-specs"
_NOTE_CHECK_SUBVERB = "note-check"

# `note_ops.note_check`'s result-dict key this worker folds into its own tick result.
_VIOLATIONS_KEY = "violations"

# `land_result.land_result`'s result-dict key listing the paths it wrote.
_LANDED_KEY = "landed"


# Mirrored job-bundle terminal-marker filenames from `lazycortex-core`'s job runtime, read
# file-wise only, per `dev.plugin-boundaries.md` § 2a — a cross-plugin Python import of
# `lazycortex-core`'s own constants module would break in a consumer install where the two
# plugins live at unrelated cache paths. Each is a bare filename `touch()`-ed empty by the
# core expert pump inside a job's `.experts/.jobs/<expert>/<job_id>/` directory.
_JOB_MARKER_DONE = "DONE"
JOB_MARKER_DEAD = "DEAD"
_JOB_MARKER_CANCELLED = "CANCELLED"

# Mirrored job-bundle lifecycle markers from the same runtime: `READY` is touched last by a
# dispatch (the bundle is complete and queued), `PID` is written by the pump the moment it
# claims the job and copies its `source/` / `context/` from the tree as it stands then.
_JOB_MARKER_READY = "READY"
_JOB_MARKER_PID = "PID"

# Mirrored claim-time artifact from the same runtime: the commit the work tree stood at when the
# pump claimed the job, i.e. the tree its `source/` / `context/` were copied from.
_JOB_ARTIFACT_CLAIM_HEAD = "claim_head"

# Mirrored job-bundle directory layout: `<repo>/.experts/.jobs/<expert>/<job_id>/`.
_JOBS_BASE = ".experts/.jobs"

# Bot identity for this worker's own commits (job-marker application + History line).
_PROMOTE_AUTHOR_NAME = "lazy-spec.gate-tick"
_PROMOTE_AUTHOR_EMAIL = "lazy-spec.gate-tick@bot.invalid"

# Regex templates for a YAML block-list frontmatter value (`key:\n  - a\n  - b\n`), shared by
# `read_fm_list` / `write_fm_list`. `flip_gate.parse_frontmatter`'s flat scalar parse skips
# bullet lines entirely, so a list-typed key needs its own reader/writer.
_FM_LIST_BLOCK_RE_TEMPLATE = r"(?m)^{key}\s*:\s*\n(?:\s+-\s*.*\n)*"
_FM_LIST_INLINE_RE_TEMPLATE = r"(?m)^{key}\s*:\s*\[\s*\]\s*$\n?"
# Populated inline form (`key: ["a", "b"]` / `key: [a, b]`) — the wizard-documented shape for
# `spec_targets`, read-only (never written by `write_fm_list`, which only ever emits the block
# or empty-inline forms above). `read_fm_list` matches this only after the two above fail, so an
# empty `[]` still takes the dedicated empty-inline path.
_FM_LIST_INLINE_POPULATED_RE_TEMPLATE = r"(?m)^{key}\s*:\s*\[(.*)\]\s*$"


def commit_note_change(asset_dir: Path, asset_note: Path, subject: str) -> None:
  """
  Atomically commit the rewritten status folder-note under the `lazy-spec.gate-tick` bot identity.

  Shared by every gate-tick mutation that touches only the single folder-note file. Without this
  commit the worker's `asset_note.write_text(...)` leaves the folder-note dirty, tripping the
  daemon's dirty-tree-skip guard on the next iteration and silently halting every routine on the
  asset. Defensive skip when the asset is not inside a git repository (the unit-test fixture path
  that exercises the worker against a bare tmp dir).

  Args:
    asset_dir: The asset folder; used to resolve the enclosing repo root for the `git` cwd.
    asset_note: The status folder-note path that was just rewritten.
    subject: The commit subject line.
  """
  # waiver: sibling-module git read -- the one git-field helper every specs worker shares
  top = flip_gate.git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")

  # guard: asset is not inside a git repository — skip commit (test-fixture path); the file
  # write above remains and is the entire mutation the bare-fixture caller observes
  if not top:
    return

  # the enclosing repo root anchors both the repaint and the git commands below
  repo = Path(top)

  # fold the note's icon repaint into this same commit so no separate icons commit follows
  extra_paths = iconize_inline.repaint_paths(
      repo, [str(asset_note.resolve().relative_to(repo.resolve()))],
  )

  # stage the rewritten folder-note so the tree is clean for the next daemon iteration
  subprocess.run(
      ["git", "add", "--", str(asset_note), *extra_paths],
      cwd = str(repo), check = True, capture_output = True,
  )

  # commit under the dedicated bot identity so the operator's authorship stays untouched
  subprocess.run(
      [
          "git",
          "-c", f"user.name={_PROMOTE_AUTHOR_NAME}",
          "-c", f"user.email={_PROMOTE_AUTHOR_EMAIL}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", subject, "--", str(asset_note), *extra_paths,
      ],
      cwd = str(repo), check = True, capture_output = True,
  )


def target_asset_dir(asset_dir: Path, raw_target: str) -> Path | None:
  """
  Resolve a cascade-target or dependency token to its asset folder.

  The token is a path relative to the owning product's root — the product `resolve_product`
  attributes `asset_dir` to by the longest matching `spec_path`, so a nested product resolves to
  the inner one — with any number of segments: `bugs/crash`, a nested asset's full path, or a
  bare slug at the product root. `coordinator_dispatch.py`'s own `spec_targets` /
  `spec_depends_on` context fold-in (`_build_bundle`) and its reverse-edge scan resolve every
  token through this same primitive.

  Args:
    asset_dir: The asset folder the token is declared on.
    raw_target: The product-relative path token (e.g. `bugs/my-bug`).

  Returns:
    The target asset folder, resolved, or None when the token is malformed or names no
    folder-note that actually exists on disk.
  """
  return resolve_product.resolve_asset_token(asset_dir, raw_target)


def find_active_job_marker(repo_root: Path, expert: str, job_id: str) -> str | None:
  """
  Check which terminal marker, if any, is present in an active job's bundle directory.

  Args:
    repo_root: The repository root holding `.experts/.jobs/`.
    expert: The dispatched expert name from the job marker.
    job_id: The dispatched job id from the job marker.

  Returns:
    The bare marker filename found (`"DONE"` / `"DEAD"` / `"CANCELLED"`), or None when the
    job's bundle directory carries none of them yet (still running).
  """
  job_dir = repo_root / _JOBS_BASE / expert / job_id
  for marker in (_JOB_MARKER_DONE, JOB_MARKER_DEAD, _JOB_MARKER_CANCELLED):
    if (job_dir / marker).is_file():
      return marker
  return None


def is_job_queued(repo_root: Path, expert: str, job_id: str) -> bool:
  """
  Check whether an active job is still waiting in the queue — dispatched, never claimed.

  Args:
    repo_root: The repository root holding `.experts/.jobs/`.
    expert: The dispatched expert name from the job marker.
    job_id: The dispatched job id from the job marker.

  Returns:
    True when the bundle carries `READY` and no `PID`; False for a claimed job, and for a
    bundle that is missing altogether, whose state cannot be told and so reads as running.
  """
  job_dir = repo_root / _JOBS_BASE / expert / job_id
  return (job_dir / _JOB_MARKER_READY).is_file() and not (job_dir / _JOB_MARKER_PID).exists()


def read_job_claim_head(repo_root: Path, expert: str, job_id: str) -> str | None:
  """
  Read the commit a claimed job's inputs were copied from.

  Args:
    repo_root: The repository root holding `.experts/.jobs/`.
    expert: The dispatched expert name from the job marker.
    job_id: The dispatched job id from the job marker.

  Returns:
    The recorded commit hash, or None when the bundle carries no claim-head marker — a job
    not yet claimed, a bundle that is gone, or a pump older than the marker.
  """
  try:
    value = (repo_root / _JOBS_BASE / expert / job_id / _JOB_ARTIFACT_CLAIM_HEAD).read_text().strip()
  except OSError:
    return None
  return value or None


def _land_job_result(repo_root: Path, asset_dir: Path, expert: str, job_id: str) -> list[str]:
  """
  Put one finished job's `result/` into the asset folder via the `land-result` collector.

  Best-effort: any failure — a bundle no longer on disk, a collector that will not import, an
  unreadable response, a refused entry, a git command that exits non-zero — degrades to an empty
  return, never raises. The job is then simply undelivered, which is the state the coordinator
  already reports.

  Guarantees:
    - Never raises; every failure path returns an empty list and leaves the asset folder as
      it was found — the collector rolls its own partial writes back before it re-raises.

  Args:
    repo_root: The repository root holding the job queue.
    asset_dir: The asset folder the job's document belongs in.
    expert: The dispatched expert's name, the job queue's first path segment.
    job_id: The finished job's id.

  Returns:
    The repo-relative paths the landing wrote and committed; empty when nothing landed.
  """

  # Contract:
  # This call never raises: any failure degrades to an empty return, leaving the job
  # undelivered for the coordinator to report rather than stopping the tick.

  job_dir = repo_root / _JOBS_BASE / expert / job_id

  # guard: the bundle is gone — there is nothing to land
  if not job_dir.is_dir():
    return []
  try:
    # waiver: deferred sibling import -- flat bin/ dir resolved via sys.path at runtime, not
    # statically importable; inside the try so a failed resolution degrades like any other
    import land_result  # pylint: disable=import-error
    target = land_result.document_target(job_dir, asset_dir)

    # guard: the job delivered no document — nothing to place
    if target is None:
      return []
    return land_result.land_result(job_dir, target)[_LANDED_KEY]
  # waiver: fire-and-forget collector — ANY landing failure, the collector's own refusal
  # included, must leave the job undelivered rather than stop the tick that also has a
  # History line and a wake to write
  except Exception as exc:
    sys.stderr.write(f"gate-tick: land-result {expert}/{job_id}: {exc}\n")
    return []


def set_fm_json(fm_text: str, key: str, value: dict) -> str:
  """
  Set or insert `key: <compact-json>` in a frontmatter block.

  Mirrors `flip_gate.set_bool`'s shape for a JSON-valued (rather than boolean-valued) key —
  the hand-rolled frontmatter parser treats a value as an opaque string, so a one-line JSON
  object round-trips through it without any schema change. Reused by `coordinator_dispatch.py`
  for its own worker-internal dict-valued markers.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The frontmatter key to set.
    value: The dict to serialize as the key's compact-JSON value.

  Returns:
    The updated frontmatter text.
  """
  literal = json.dumps(value)
  pat = _compile_key_pattern(key)
  if pat.search(fm_text):
    return pat.sub(lambda _m: f"{key}: {literal}", fm_text, count = 1)
  close_idx = fm_text.rfind("---\n")

  # guard: malformed frontmatter without a closing fence
  if close_idx < 0:
    return fm_text
  return fm_text[:close_idx] + f"{key}: {literal}\n" + fm_text[close_idx:]


def del_fm_key(fm_text: str, key: str) -> str:
  """
  Remove a frontmatter key's line, if present.

  Mirrors `set_fm_json`'s regex approach for the opposite operation — deleting rather than
  writing a key. A no-op (returns `fm_text` unchanged) when the key is absent.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The frontmatter key to remove.

  Returns:
    The updated frontmatter text.
  """
  pat = re.compile(_FM_KEY_RE_TEMPLATE.format(key = re.escape(key)) + _TRAILING_NEWLINE_RE)
  return pat.sub("", fm_text, count = 1)


def read_fm_list(fm_text: str, key: str) -> list[str]:
  """
  Read a YAML list-typed frontmatter value. Recognizes both the block form (`key:\\n  - a\\n
  - b\\n`) and the wizard-documented populated inline form (`key: ["a", "b"]`).

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences), or any
      larger text this block leads (the trailing body is never scanned).
    key: The list-typed frontmatter key (e.g. `spec_targets`).

  Returns:
    The list's string members, in file order; empty when the key is an inline `[]`, absent, or
    written with no members.
  """
  pat = re.compile(_FM_LIST_BLOCK_RE_TEMPLATE.format(key = re.escape(key)))
  match = pat.search(fm_text)
  if match is not None:
    return [
        stripped[1:].strip()
        for stripped in (line.strip() for line in match.group(0).splitlines()[1:])
        if stripped.startswith("-")
    ]

  # no block form — try the wizard-documented populated inline form (`key: ["a", "b"]`); an
  # inline-`[]` or a genuinely absent key both fall through this to the empty return below
  pat_inline = re.compile(_FM_LIST_INLINE_POPULATED_RE_TEMPLATE.format(key = re.escape(key)))
  inline_match = pat_inline.search(fm_text)

  # guard: no inline-populated form either — absent key, or written as empty inline `[]`
  if inline_match is None:
    return []
  interior = inline_match.group(1).strip()

  # guard: `key: []` matched here too (empty interior) — same empty result as the dedicated form
  if not interior:
    return []

  # a trailing comma (`[a, b, ]`) splits to a final empty member — drop it rather than collect
  # a blank token no caller declared
  return [
      stripped for member in interior.split(",")
      if (stripped := member.strip().strip("'\""))
  ]


def write_fm_list(fm_text: str, key: str, values: list[str]) -> str:
  """
  Set or insert a `key:` YAML block-list value in a frontmatter block.

  Mirrors `apply_request.py`'s `set_fm_list` (same replacement rule — an existing inline `[]`
  or multi-line `- ` block is replaced in place, a missing key is appended before the closing
  fence); duplicated here rather than imported per this `bin/` tree's own per-file small-helper
  convention. Reused by `note_ops.note_set_key` (its `_Kind.LIST` writer).

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The list-typed frontmatter key.
    values: Replacement member list, rendered as unquoted `- <value>` lines.

  Returns:
    The updated frontmatter text.
  """
  block_lines = "\n".join(f"  - {value}" for value in values)
  replacement = f"{key}:\n{block_lines}\n" if values else f"{key}: []\n"
  pat_inline = re.compile(_FM_LIST_INLINE_RE_TEMPLATE.format(key = re.escape(key)))
  pat_block = re.compile(_FM_LIST_BLOCK_RE_TEMPLATE.format(key = re.escape(key)))
  if pat_inline.search(fm_text):
    return pat_inline.sub(replacement, fm_text, count = 1)
  if pat_block.search(fm_text):
    return pat_block.sub(replacement, fm_text, count = 1)
  close_idx = fm_text.rfind("---\n")

  # guard: malformed frontmatter without a closing fence — leave untouched
  if close_idx < 0:
    return fm_text
  return fm_text[:close_idx] + replacement + fm_text[close_idx:]


def _compile_key_pattern(key: str) -> re.Pattern[str]:
  """
  Compile `_FM_KEY_RE_TEMPLATE` for one frontmatter key.

  Args:
    key: The frontmatter key to match a same-line value for.

  Returns:
    The compiled single-line `^key\\s*:.*$` pattern.
  """
  return re.compile(_FM_KEY_RE_TEMPLATE.format(key = re.escape(key)))


def _run_note_check(asset_note: Path) -> list[dict]:
  """
  Run `note-check` on `asset_note` via the sibling CLI, for folding into this tick's own result.

  Subprocessed rather than imported — `note_ops.py` already imports this module (for
  `set_fm_json` / `write_fm_list`), so an in-process import here would be circular. Best-effort:
  a missing or broken CLI degrades to reporting no violations rather than failing the tick, since
  the structural check is advisory (the coordinator repairs what it finds, this worker never does).

  Guarantees:
    - Never raises; a missing, broken, or unparseable CLI response degrades to an empty
      violations list rather than failing the tick.

  Args:
    asset_note: The status folder-note path to check.

  Returns:
    The `note-check` violations list; empty when the note is structurally clean, or the CLI
    itself could not be resolved, run, or parsed.
  """

  # Contract:
  # This call never raises and never fails the tick: a missing, broken, or unparseable CLI
  # response degrades to an empty violations list rather than propagating a failure.

  cli = _BIN / _SPEC_CLI_NAME

  # guard: sibling CLI missing from this checkout — degrade to a skip, never fail the tick
  if not cli.is_file():
    return []
  try:
    proc = subprocess.run(
        [sys.executable, str(cli), _NOTE_CHECK_SUBVERB, str(asset_note)],
        capture_output = True, text = True, check = False,
    )
  # waiver: best-effort follow-up — a broken subprocess must degrade to "nothing to report",
  # never abort the tick that already handled the active-job polling pass above
  except OSError:
    return []
  try:
    result = json.loads(proc.stdout)
  except json.JSONDecodeError:
    return []
  return result.get(_VIOLATIONS_KEY, [])


def apply_job_marker(
    asset_note: Path, text: str, fm_end: int, *,
    body: str, asset_dir: Path, repo_root: Path, marker: str, job_info: dict, today_str: str,
) -> dict:
  """
  Apply an active expert job's terminal bundle marker to the asset.

  Every marker retires the tracked job and raises a `job-done` wake for the coordinator to act
  on. `DONE` lands the job's `result/` into the asset folder — undelivered when the job left
  nothing to land — and appends a `# History` line recording the outcome; `CANCELLED` appends the
  same kind of line with nothing to land. `DEAD` instead halts the asset, appending a persistent
  `[!failure]` callout to `# Gates` that stays until an operator resolves it by hand, and leaves
  the job bundle in place for diagnostics. Deciding what happens next on the asset — dispatching a
  replacement job, reacting to the halt — is `spec.coordinator`'s call; this pass only records the
  terminal outcome.

  Guarantees:
    - On a `DONE` or `CANCELLED` marker, the job bundle is retired, freeing its dedup key for
      re-dispatch while its files stay on disk.
    - On a `DEAD` marker, the job bundle is left unretired, kept on disk for diagnostics.

  Args:
    asset_note: The status folder-note path.
    text: The folder-note's full text as last read from disk.
    fm_end: Index just past the frontmatter's closing `---` fence in `text`.
    body: The folder-note's body text (post-frontmatter).
    asset_dir: The asset folder the marker is being applied to.
    repo_root: The repository root holding the job-marker sidecar.
    marker: The terminal marker found in the job's bundle directory (`"DONE"` / `"DEAD"` /
      `"CANCELLED"`).
    job_info: The tracked active-job marker (`checkbox` / `expert` / `job_id`).
    today_str: ISO date string pinned into the callout and history line.

  Returns:
    A result dict naming the applied `TickAction` plus the job's `checkbox` and `job_id`.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot
      be resolved.
  """

  # Contract:
  # On a `DONE` or `CANCELLED` marker, the job bundle is retired via
  # `gate_dispatch.consume_stale_job`, freeing its dedup key so the same checkbox can be
  # re-dispatched, while the bundle's files stay on disk for the coordinator's job-done wake
  # to read. On a `DEAD` marker, the bundle is deliberately left unretired, kept for
  # diagnostics alongside the asset halt.

  checkbox_label = job_info[JobMarker.CHECKBOX]
  job_id = job_info[JobMarker.JOB_ID]

  # one language resolution serves every branch's narrative line (the resolver walks to the
  # settings root and reads config)
  note_lang = note_explainers.lang_for_note(asset_note)
  fm_text = text[:fm_end]

  # the job is over on every branch: retire the marker and raise the wake the coordinator's
  # `job-done` trigger reads, before the note write below that the wake will accompany
  spec_job_markers.update(
      repo_root, asset_note,
      { JobMarker.ACTIVE_JOB: None, JobMarker.PENDING_WAKE: JobMarker.JOB_DONE },
  )

  # only the body/action/subject differ per marker kind
  if marker == _JOB_MARKER_DONE:
    # the job's document and attachments arrive only through `result/`: put them in the asset
    # folder and commit them here, so the document the coordinator submits into review on the
    # `job-done` wake this same call raises is already tracked
    _land_job_result(repo_root, asset_dir, job_info[JobMarker.EXPERT], job_id)

    # the landing writes into the asset folder this call is about to edit, so the note text read
    # before it is now stale — re-read it, or the write below would revert what just landed
    text = asset_note.read_text()
    _, fm_end = flip_gate.parse_frontmatter(text)
    fm_text, body = text[:fm_end], text[fm_end:]

    # the localized narrative tail of the History line, in the note's authoring language
    done_tail = note_explainers.history_line_for_lang(note_lang, HistoryEvent.JOB_DONE,
                                                      job_id = job_id, label = checkbox_label)
    body = history_journal.append(body, done_tail, today_str, repo = repo_root)
    action = TickAction.JOB_DONE
    subject = f"{_PROMOTE_AUTHOR_NAME}: job {job_id} ({checkbox_label}) done on {asset_dir.name}"

    # retire the bundle so its dedup key frees for a retry — same move the coordinator-job
    # branch already makes; the bundle's files stay on disk for the coordinator's wake to read
    gate_dispatch.consume_stale_job(repo_root, job_info[JobMarker.EXPERT], job_id)
  elif marker == _JOB_MARKER_CANCELLED:
    # the localized narrative tail of the History line, in the note's authoring language
    cancelled_tail = note_explainers.history_line_for_lang(note_lang, HistoryEvent.JOB_CANCELLED,
                                                           job_id = job_id, label = checkbox_label)
    body = history_journal.append(body, cancelled_tail, today_str, repo = repo_root)
    action = TickAction.JOB_CANCELLED
    subject = f"{_PROMOTE_AUTHOR_NAME}: job {job_id} ({checkbox_label}) cancelled on {asset_dir.name}"

    # a cancelled bundle is equally spent — retire it so the checkbox can be re-dispatched
    gate_dispatch.consume_stale_job(repo_root, job_info[JobMarker.EXPERT], job_id)
  else:
    # marker == JOB_MARKER_DEAD — halt the asset via the shared text-core primitive, in this
    # branch's own single write+commit (the marker clear above touched no note text)
    reason = HaltReason.JOB_DIED.format(job_id = job_id, label = checkbox_label)
    fm_text, body, _ = flip_gate.halt_asset_text(
        fm_text, body, reason, today = today_str, lang = note_lang,
    )
    action = TickAction.ASSET_HALTED
    subject = f"{_PROMOTE_AUTHOR_NAME}: halt {asset_dir.name} — {reason}"

  # one write, one commit, shared by every branch above
  asset_note.write_text(note_explainers.heal_note_text(asset_note, fm_text + body))
  commit_note_change(asset_dir, asset_note, subject)

  # the applied marker's action plus the job identity it acted on, for every branch above
  return {
      TickAction.ACTION: action,
      JobMarker.CHECKBOX: checkbox_label,
      JobMarker.JOB_ID: job_id,
  }


# Decision: shared line-builder over per-caller formatting — two independent writers can
# each be the one to observe the same DEAD marker first, and whichever wins must append
# identical text (4b Task 5 fix round 1 — a duplicated formatter let one writer consume DEAD
# identically to DONE/CANCELLED, silently dropping this line whenever it won the race).

def coordinator_job_dead_line(trigger: str, job_id: str, *, lang: str) -> str:
  """
  Build the `# History` WARNING text for a dead coordinator-job bundle.

  Single owner of this line's exact wording, so concurrent writers append identical text
  regardless of which one reaches the dead marker first. The day group and bullet are the
  shared history verb's, not this builder's.

  Args:
    trigger: The `CoordinatorJobKey.TRIGGER` value recorded on the dead job.
    job_id: The dead job's id.
    lang: The note's authoring language for the line's narrative tail.

  Returns:
    The `WARNING: ...` line text, without bullet or date.
  """
  # the localized narrative tail of the History line, in the note's authoring language
  return note_explainers.history_line_for_lang(lang, HistoryEvent.JOB_DEAD,
                                               job_id = job_id, trigger = trigger)


def _apply_coordinator_job_marker(
    asset_note: Path, text: str, fm_end: int, *,
    body: str, asset_dir: Path, repo_root: Path, marker: str, job_info: dict, today_str: str,
) -> dict:
  """
  Sweep a finished `coordinator_job` marker off the asset.

  Retires the coordinator's own tracked job — never a ladder expert job, so a `DEAD` bundle here
  never halts the asset. `DEAD` instead appends a `# History` WARNING line, the only branch that
  writes and commits the note; `DONE` / `CANCELLED` free the bundle's dedup key for the
  coordinator's next dispatch, with no note write of their own. Any wake flag raised while the
  swept job ran is left untouched — it survives for the next genuine wake to redeem.

  Guarantees:
    - A `DEAD` marker never sets `spec_halted` on the asset; the coordinator's own job death is
      recorded as a `# History` WARNING line only.
    - A `DONE` or `CANCELLED` marker retires the job bundle via `gate_dispatch.consume_stale_job`,
      freeing its dedup key for the coordinator's next dispatch.

  Args:
    asset_note: The status folder-note path.
    text: The folder-note's full text as last read from disk.
    fm_end: Index just past the frontmatter's closing `---` fence in `text`.
    body: The folder-note's body text (post-frontmatter).
    asset_dir: The asset folder the commit's repo root is resolved from.
    repo_root: The repository root holding the job-marker sidecar and `.experts/.jobs/`.
    marker: The terminal marker found in the job's bundle directory (`"DONE"` / `"DEAD"` /
      `"CANCELLED"`).
    job_info: The tracked coordinator-job marker (`trigger` / `expert` / `job_id`).
    today_str: ISO date string pinned into the History line.

  Returns:
    A result dict naming the applied `TickAction` plus the job's `trigger` and `job_id`.

  Raises:
    RuntimeError: Propagated from `history_journal.append` when the core verb refuses or cannot
      be resolved.
  """

  # Contract:
  # A `DEAD` coordinator-job marker never sets `spec_halted` on the asset — the coordinator's
  # own wake job is not a ladder expert job, so its death is recorded as a `# History` WARNING
  # line only. A `DONE` or `CANCELLED` marker retires the job bundle via
  # `gate_dispatch.consume_stale_job`, freeing its dedup key for the coordinator's next
  # dispatch.

  trigger = job_info[JobMarker.TRIGGER]
  job_id = job_info[JobMarker.JOB_ID]
  spec_job_markers.update(repo_root, asset_note, { JobMarker.COORDINATOR_JOB: None })

  # every marker clears the coordinator-job marker (already applied above); only DEAD owes the
  # note a WARNING line, and only DONE / CANCELLED owe the bundle its dedup retirement
  if marker == JOB_MARKER_DEAD:
    # one language resolution serves the WARNING line and the explainer heal (the resolver
    # walks to the settings root and reads config)
    note_lang = note_explainers.lang_for_note(asset_note)
    body = history_journal.append(
        body, coordinator_job_dead_line(trigger, job_id, lang = note_lang), today_str,
        repo = repo_root,
    )
    asset_note.write_text(text[:fm_end] + note_explainers.ensure_explainers(body, note_lang))
    commit_note_change(
        asset_dir, asset_note,
        f"{_PROMOTE_AUTHOR_NAME}: coordinator job {job_id} ({trigger}) died on {asset_dir.name}",
    )
    action = TickAction.COORDINATOR_JOB_DEAD
  else:
    # marker in (_JOB_MARKER_DONE, _JOB_MARKER_CANCELLED) — retire the bundle so its dedup key
    # frees for the coordinator's next dispatch; nothing here reaches the note
    gate_dispatch.consume_stale_job(repo_root, job_info[JobMarker.EXPERT], job_id)
    action = TickAction.COORDINATOR_JOB_CONSUMED

  # the applied marker's action plus the job identity it acted on, for every branch above
  return {
      TickAction.ACTION: action,
      JobMarker.TRIGGER: trigger,
      JobMarker.JOB_ID: job_id,
  }


def gate_tick(asset_note: Path, today: str | None = None) -> dict:
  """
  Poll one asset's active expert job and coordinator job, then structurally check the
  folder-note.

  An asset tracking an active expert job has that job's terminal marker checked first; the
  coordinator's own tracked job is checked the same way next, backstopping
  `coordinator_dispatch.py` against a dead coordinator job whose marker no further commit would
  ever wake it to clear (plan 4b Task 5). Every other sequencing decision this worker used to
  make (stage promotion, gate advancement, downward reconciliation, the launch-checkbox ladder,
  change-cascade dispatch) now belongs to `spec.coordinator`, per `lazy-spec.coordination-playbook.md`.

  Args:
    asset_note: The status folder-note path; its parent is the asset dir.
    today: Optional ISO date forwarded into the applied job-marker's callout and history line.

  Returns:
    A result dict whose `action` is one of `job-done`, `job-cancelled`, `asset-halted`,
    `coordinator-job-consumed`, `coordinator-job-dead`, or `noop`; every non-`noop` action
    carries the identity it acted on (`checkbox` + `job_id` for the active-job branches,
    `trigger` + `job_id` for the coordinator-job branches); a `noop` carries an additional
    `violations` list when `note-check` found any.
  """
  asset_dir = asset_note.parent
  repo_root = flip_gate.repo_root(asset_dir)
  # waiver: sibling-module date resolution -- the one today-pinning helper every specs worker shares
  today_str = flip_gate.effective_today(today)
  text = asset_note.read_text()
  _, fm_end = flip_gate.parse_frontmatter(text)
  body = text[fm_end:]
  markers = spec_job_markers.read(repo_root, asset_note)

  # Domain(spec.lifecycle):
  # # Expert job terminal outcomes
  # A dispatched expert job finishes in one of three states. A completed or a cancelled job both
  # free the ladder's work slot for the same step to be dispatched again if it is still needed —
  # the attempt is done with, successfully or not, and nothing about it needs to be kept in the
  # way. A job that dies instead stops the whole asset from moving forward until an operator looks
  # at it: the failed attempt is left exactly as it was, on purpose, so there is something to
  # examine before deciding what happens next. That stop applies only to a step on the asset's own
  # promotion ladder — the automation's own background job watching over the asset is not part of
  # that ladder, so its own death is only ever recorded as a warning and never halts the asset it
  # was watching.

  # active-job polling: an asset tracking an `active_job` marker has its job bundle's
  # terminal marker checked before anything else this tick
  job_info = markers[JobMarker.ACTIVE_JOB]
  if isinstance(job_info, dict):
    marker = find_active_job_marker(repo_root, job_info[JobMarker.EXPERT], job_info[JobMarker.JOB_ID])
    if marker is not None:
      return apply_job_marker(
          asset_note, text, fm_end,
          body = body, asset_dir = asset_dir, repo_root = repo_root,
          marker = marker, job_info = job_info, today_str = today_str,
      )

  # coordinator-job polling: same terminal-marker check, applied to the
  # coordinator's own one-job-per-asset slot
  coord_job_info = markers[JobMarker.COORDINATOR_JOB]
  if isinstance(coord_job_info, dict):
    coord_marker = find_active_job_marker(
        repo_root, coord_job_info[JobMarker.EXPERT], coord_job_info[JobMarker.JOB_ID],
    )
    if coord_marker is not None:
      return _apply_coordinator_job_marker(
          asset_note, text, fm_end,
          body = body, asset_dir = asset_dir, repo_root = repo_root,
          marker = coord_marker, job_info = coord_job_info, today_str = today_str,
      )

  # structural check, folded into the tick result — repairing a violation is the coordinator's
  # own job (through its pen and `note-set-key`), never this worker's.
  violations = _run_note_check(asset_note)
  result: dict = { TickAction.ACTION: TickAction.NOOP }
  if violations:
    result[_VIOLATIONS_KEY] = violations
  return result


def main(argv: list[str]) -> int:
  """
  Poll one asset's active job and note-check it from the command line, printing the result as
  JSON.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the asset note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs gate-tick")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_note", type = Path)
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--today", default = None,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "ISO date pinned into emitted callouts")
  args = parser.parse_args(argv)
  asset_note: Path = args.asset_note.resolve()

  # guard: asset status folder-note must exist
  if not asset_note.is_file():
    sys.stderr.write(f"no status folder-note: {asset_note}\n")
    return 2

  # run the tick and report the result the same way every other lazycortex-specs worker does
  print(json.dumps(gate_tick(asset_note, today = args.today)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
