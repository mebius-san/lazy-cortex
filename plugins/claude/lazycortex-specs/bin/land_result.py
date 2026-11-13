"""
`land-result` — the specs-side collector for one finished expert job.

A launch-checkbox job never writes into the spec catalog itself: it returns its result
document as the FIRST entry of `response.json`'s `result` array and every attachment after
it, and this worker puts them in place. The document lands at the target path the caller
names; each attachment lands beside it under its own basename; the document's
`result/<file>` links are rewritten to those neighbour names; and the whole set is
committed under this worker's own bot identity with an explicit pathspec, because the
checkout's index is shared with the operator and with every other routine.

A landing ends in one of three results: `landed` when files were written and committed, `empty` when
the job had nothing to deliver, and `refused` — with a one-line reason — when a delivery was declared
but this worker will not make it. A job that ended in error against a report journal lands its files
like a successful one.

`gate_tick.py` calls this on a job's `DONE`, before the coordinator opens review with the
review system's `submit` verb — so the document the coordinator submits is already tracked.
The path checks are mirrored file-wise from `lazycortex-review`'s own `payload.py` rather
than imported: a cross-plugin Python import would break in a consumer install where the two
plugins live at unrelated cache paths (`dev.plugin-boundaries.md` § 2a).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
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
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import SiblingDoc, SpecKey  # noqa: E402


# Job-bundle layout, mirrored file-wise from `lazycortex-core`'s runtime rather than imported
# across the plugin boundary (`dev.plugin-boundaries.md` § 2a).
_RESPONSE_FILE = "response.json"
_REQUEST_FILE = "request.json"
_RESULT_DIR = "result"
_RESULT_PREFIX = "result/"

# The dispatch payload key naming the document a job writes, repo-relative. The coordinator puts
# it there at dispatch; it is the only thing that says where a job's document belongs.
_TARGET_DOC_KEY = "target_doc"

# Response-envelope tokens this worker reads, mirrored the same way.
_OUTCOME_KEY = "outcome"
_OUTCOME_EDITED = "edited"
_OUTCOME_ERROR = "error"
_OUTCOME_DEFERRED = "deferred"
_RESULT_KEY = "result"
_PATH_KEY = "path"

# Bot identity for this worker's own commits.
_LAND_AUTHOR_NAME = "lazy-spec.land-result"
LAND_AUTHOR_EMAIL = "lazy-spec.land-result@bot.invalid"

# A link target pointing into the job's own result dir — what a writer spells when it references
# an attachment it is returning alongside the document. Four shapes carry such a target: an inline
# link `[a](result/x)`, a titled inline link `[a](result/x "t")`, a reference definition
# `[a]: result/x`, and an HTML source attribute `src="result/x"`. A bare `(result/x)` in prose is
# no link and stays as written. Only the opening delimiter is captured and replayed, so whatever
# closes each shape is left exactly as the writer spelled it.
_RESULT_LINK_RE = re.compile(
    r"""(?P<open>\]\(|\]:[ \t]*|src[ \t]*=[ \t]*["'])result/(?P<name>[^)"'\s]+)""")

# An inline code span: a backtick run, the shortest text, and a closing run of the same length.
_CODE_SPAN_RE = re.compile(r"(`+).+?(?<!`)\1(?!`)")

# `_RESULT_LINK_RE`'s capture groups: the delimiter that opened the shape, replayed verbatim,
# and the returned file's name behind the `result/` prefix.
_GROUP_OPEN = "open"
_GROUP_NAME = "name"

# The markdown suffix `_is_spec_document` recognizes, matched case-insensitively.
_MD_SUFFIX = ".md"

# This worker's own result-dict keys.
_ACTION_KEY = "action"
_ACTION_LANDED = "landed"
_ACTION_EMPTY = "empty"
_ACTION_REFUSED = "refused"
_LANDED_KEY = "landed"
_REASON_KEY = "reason"

# The report journals: documents that record every run, a failed one included.
_JOURNAL_DOCS = frozenset({ SiblingDoc.CODE_REPORT, SiblingDoc.TEST_REPORT })


class LandResultError(Exception):
  """
  A response payload this worker refuses to land.

  Raised whenever a response, or one of the files it declares, cannot be landed as declared.
  The caller turns it into a `refused` landing: nothing is written for it and the gate tick
  halts the asset.
  """


def _entry_path(entry: object) -> str:
  """
  Read one `result` array member's path.

  Args:
    entry: One `result` member — `{"path": "result/<file>"}` or the bare path string.

  Returns:
    The entry's declared path, verbatim.

  Raises:
    LandResultError: If the entry resolves to anything but a string.
  """
  path = entry.get(_PATH_KEY) if isinstance(entry, dict) else entry

  # guard: an entry that resolves to anything but a path string names no file
  if not isinstance(path, str):
    raise LandResultError(f"result entry carries no path: {entry!r}")
  return path


def _basename(entry: object) -> str:
  """
  Resolve one `result` entry to the bare filename it takes beside the landed document.

  Args:
    entry: One `result` array member.

  Returns:
    The entry's basename.

  Raises:
    LandResultError: If the entry points outside `result/` or is not a plain filename.
  """

  # Domain(spec.lifecycle):
  # # A returned file names a neighbour, never a location
  # What an expert returns alongside its document is only ever a file NAME: where the file ends
  # up is the collector's decision, taken from where the document lands, never the expert's. An
  # entry carrying any location of its own — a directory, a parent hop, a path outside the job's
  # own output directory — claims a placement it has no standing to claim, so the whole landing
  # is refused rather than honoured, and the job stays undelivered for the operator to see.

  path = _entry_path(entry)

  # guard: a returned file lives under the job's own result/ dir and nowhere else
  if not path.startswith(_RESULT_PREFIX):
    raise LandResultError(f"result path outside result/: {path!r}")
  name = path[len(_RESULT_PREFIX):]

  # guard: the basename is a plain filename — no separator, no parent hop, never empty
  if not name or "/" in name or "\\" in name or name in {".", ".."}:
    raise LandResultError(f"result basename is not a plain filename: {path!r}")
  return name


def _is_spec_document(path: Path) -> bool:
  """
  Report whether `path` is an existing markdown note carrying a spec catalog's role marker.

  Args:
    path: Absolute path of the destination an attachment would take.

  Returns:
    `True` when the file exists, is markdown, and its frontmatter carries `spec_role`;
    `False` for every other path, including one that cannot be read.
  """
  # guard: only an existing markdown file can carry the frontmatter that marks a spec note
  if path.suffix.lower() != _MD_SUFFIX or not path.is_file():
    return False
  try:
    values, _ = flip_gate.parse_frontmatter(path.read_text(encoding = "utf-8"))
  # waiver: an unreadable neighbour is simply not a spec note — the landing is not this
  # helper's to refuse over an IO error it cannot attribute
  except (OSError, UnicodeDecodeError):
    return False
  return SpecKey.ROLE in values


def _require_entry_lands(source: Path, dest: Path | None, document: Path) -> None:
  """
  Refuse one `result` entry whose bundle file, or whose destination, makes it unsafe to write.

  Args:
    source: The entry's file inside the job bundle's `result/` directory.
    dest: The path the entry would take beside the document, or `None` for the job's own
      result document, whose destination is the target the caller named.
    document: The target path the job's result document takes.

  Raises:
    LandResultError: When the bundle file is a symlink or absent, or when the destination is a
      symlink, the result document itself, or a spec catalog's own note.
  """

  # Domain(spec.lifecycle):
  # # A landing overwrites its own kind, never someone else's document
  # A response's entries are files the collector writes into a folder full of documents it did
  # not write. Re-landing an attachment the same expert produced before is the ordinary regenerate
  # case and overwrites freely. Everything else is off limits: the job's own result document is
  # the round's output and is never an attachment's destination, and a canonical or status note of
  # the catalog belongs to the ladder this collector only delivers into. A symlink is refused on
  # both sides — inside the bundle before it is read, and at the destination before it is written
  # — because what it names is somewhere else whatever it resolves to, and the containment the
  # entry passed was only ever about the name.

  # guard: a symlink names a file outside the bundle whatever it resolves to
  if source.is_symlink():
    raise LandResultError(f"result entry is a symlink: {source.name!r}")

  # guard: the response declared a file the writer never wrote — a malformed response
  if not source.is_file():
    raise LandResultError(f"result entry declared but not delivered: {source.name!r}")

  # guard: the result document's own destination is the caller's target, already checked
  if dest is None:
    return

  # guard: the document an attachment rides with is never the file it overwrites
  if dest == document:
    raise LandResultError(f"attachment would overwrite the result document: {source.name!r}")

  # guard: writing through a symlinked destination puts the bytes wherever it points
  if dest.is_symlink():
    raise LandResultError(f"attachment destination is a symlink: {source.name!r}")

  # guard: a canonical or status note of the catalog is nobody's attachment destination
  if _is_spec_document(dest):
    raise LandResultError(f"attachment would overwrite a spec document: {source.name!r}")


def _read_response(job_dir: Path) -> dict | None:
  """
  Read one finished job's response envelope.

  Args:
    job_dir: The job-bundle directory.

  Returns:
    The parsed `response.json` object, or `None` when the file is absent, unreadable, or holds
    anything but a JSON object.
  """
  try:
    response = json.loads((job_dir / _RESPONSE_FILE).read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return None
  return response if isinstance(response, dict) else None


def _declared_entries(response: dict | None) -> list[object]:
  """
  Read the `result` entries a response declares.

  Args:
    response: The parsed response envelope, or `None` when there is none.

  Returns:
    The response's `result` array; empty when there is no response or it declares no array.
  """
  entries = response.get(_RESULT_KEY) if response is not None else None
  return entries if isinstance(entries, list) else []


def _select_entries(job_dir: Path, target_doc: Path) -> list[object]:
  """
  Select the `result` entries one finished job's outcome entitles it to land.

  Args:
    job_dir: The job-bundle directory.
    target_doc: The path the job's result document takes.

  Returns:
    The response's `result` array when the job finished with an edit, or with an error against
    a report journal; empty when the response declares no files, the work was deferred, or the
    job failed against any other document.

  Raises:
    LandResultError: If the response is unreadable, or declares files under an outcome that is
      neither an edit nor an error.
  """

  # Domain(spec.lifecycle):
  # # What a job's outcome entitles it to deliver
  # A job delivers files only by saying it finished its edit. A job that says it failed delivers
  # nothing, with one exception: a report journal records every run, the failed one included, so
  # the journal of a failed run is delivered like any other and the operator reads the failure
  # where the successes are. A job that deferred its work, or declared no files, delivers
  # nothing and that is an ordinary ending. A job that declares files under any other word has
  # produced work the system cannot place: that is a failure of the delivery, reported as one,
  # never an empty ending.

  response = _read_response(job_dir)

  # guard: a finished job with no readable response cannot say what it delivered
  if response is None:
    raise LandResultError(f"unreadable {_RESPONSE_FILE}")
  entries = _declared_entries(response)
  outcome = response.get(_OUTCOME_KEY)

  # guard: nothing declared, or the work was deliberately not done — an ordinary empty ending
  if not entries or outcome == _OUTCOME_DEFERRED:
    return []

  # a failed job lands only the journal that records the failure
  if outcome == _OUTCOME_ERROR:
    return entries if target_doc.name in _JOURNAL_DOCS else []

  # guard: files declared under a word that is not the success value cannot be placed
  if outcome != _OUTCOME_EDITED:
    raise LandResultError(
        f"outcome {outcome!r} is not {_OUTCOME_EDITED!r}, yet the response declares "
        f"{len(entries)} result file(s)")
  return entries


def _refuse_landing(job_dir: Path, reason: str) -> dict:
  """
  Report one landing this worker refuses, on stderr and as its result.

  Args:
    job_dir: The job-bundle directory, named in the log line.
    reason: One line saying why nothing was landed.

  Returns:
    `{"action": "refused", "landed": [], "reason": <reason>}`.
  """
  sys.stderr.write(f"land-result: {job_dir.name}: {reason}\n")
  return { _ACTION_KEY: _ACTION_REFUSED, _LANDED_KEY: [], _REASON_KEY: reason }


def _is_inside(path: Path, root: Path) -> bool:
  """
  Report whether `path` resolves to somewhere at or under `root`.

  Args:
    path: The candidate path, already resolved.
    root: The directory the candidate must not escape.

  Returns:
    `True` when `path` lies at or under `root`; `False` otherwise.
  """
  return path.is_relative_to(root.resolve())


def document_target(job_dir: Path, asset_dir: Path) -> Path | None:
  """
  Name the path one dispatched job's result document takes, as the dispatch declared it.

  Guarantees:
    - A returned target always lies inside `asset_dir`, whatever path the dispatch spelled, and a release is held to
      this exactly as any other asset; anything else yields `None`.

  Notes:
    - Writes one line to stderr saying why when the dispatch names no usable target.

  Args:
    job_dir: The job-bundle directory.
    asset_dir: The asset folder the job's document must land in.

  Returns:
    The repo-root-resolved `target_doc` the dispatch payload declared, or `None` when the
    payload is unreadable, declares no `target_doc`, or names a path outside `asset_dir`.
  """

  # Contract:
  # A job's `target_doc` is accepted only when it resolves inside the job's own asset folder, for a release
  # exactly as for any other asset; anything else yields no target. Callers MUST NEVER receive a target
  # outside the asset folder.

  target, reason = _resolve_target(job_dir, asset_dir)

  # the caller only learns there is no usable target, so the reason goes to the log
  if target is None:
    sys.stderr.write(f"land-result: {job_dir.name}: {reason}\n")
  return target


def _resolve_target(job_dir: Path, asset_dir: Path) -> tuple[Path | None, str]:
  """
  Resolve the path one dispatched job's result document takes, with the reason when there is none.

  Args:
    job_dir: The job-bundle directory.
    asset_dir: The asset folder the job's document must land in.

  Returns:
    The repo-root-resolved `target_doc` and an empty reason, or `None` and one line saying why
    the dispatch names no usable target.
  """

  # Domain(spec.lifecycle):
  # # Where a document belongs travels with the job, not with what came back
  # A job is dispatched to write one named document, and that name is settled when the job is
  # created, by the side that knows the ladder. What comes back is only content: an expert
  # returning a file under some other name has misunderstood its job, not relocated it, and no
  # mapping from the step's label to a filename could stand in for the dispatch's own statement
  # anyway — a cascade job writes into a different asset's folder entirely. A job that never said
  # where its document goes has nowhere to put it and stays undelivered.

  # guard: a dispatch payload that cannot be read names no target at all
  try:
    request = json.loads((job_dir / _REQUEST_FILE).read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError) as exc:
    return None, f"unreadable {_REQUEST_FILE}: {exc}"
  raw = request.get(_TARGET_DOC_KEY) if isinstance(request, dict) else None

  # guard: a job that declared no target has nowhere to put its document
  if not isinstance(raw, str) or not raw:
    return None, f"dispatch declares no {_TARGET_DOC_KEY!r}"

  # the declared path is repo-relative; resolving it collapses any parent hop before the
  # containment check below, which is what actually decides whether it may be written
  target = (flip_gate.repo_root(asset_dir) / raw).resolve()

  # guard: a job's document belongs in its own asset folder and nowhere else
  if not _is_inside(target, asset_dir):
    return None, f"{_TARGET_DOC_KEY} {raw!r} is outside {asset_dir.name}"
  return target, ""


def _fix_links(body: str, names: list[str], job_dir: Path) -> str:
  """
  Rewrite the document's `result/<file>` targets to the neighbour names the attachments take.

  Covers every shape a writer spells such a target in: an inline link, a titled inline link, a
  reference definition, and an HTML `src` attribute.

  Notes:
    - Never raises and never drops a link: a mismatch between the links and the delivered
      files is reported on stderr and the landing continues.

  Args:
    body: The landed document's text as the expert returned it.
    names: The attachment basenames this response delivered.
    job_dir: The job-bundle directory, named in each log line.

  Returns:
    The document text with every `result/<file>` target rewritten to `<file>`.
  """
  delivered = set(names)
  linked: set[str] = set()

  # replace one `result/<file>` link target with the bare neighbour name
  def _neighbour(match: re.Match) -> str:
    name = match.group(_GROUP_NAME)
    linked.add(name)

    # guard: the document points at a neighbour this response never delivered
    if name not in delivered:
      sys.stderr.write(f"land-result: {job_dir.name}: link to missing neighbour {name!r}\n")
    return f"{match.group(_GROUP_OPEN)}{name}"

  # rewrite the links of every line outside a fenced block, skipping inline code spans — a link
  # quoted as code is an example, not a target
  lines = body.split("\n")
  fenced = spec_frontmatter.fenced_lines(lines)
  for idx, line in enumerate(lines):
    # guard: a fenced line is code, never a link
    if fenced[idx]:
      continue
    prose = [ _RESULT_LINK_RE.sub(_neighbour, part) for part in _CODE_SPAN_RE.split(line)[::2] ]
    spans = [ span.group(0) for span in _CODE_SPAN_RE.finditer(line) ]
    lines[idx] = "".join(piece for pair in zip(prose, [ *spans, "" ], strict = True) for piece in pair)
  out = "\n".join(lines)

  # a file nobody references is still landed — the operator is told, the job is not failed
  for name in sorted(delivered - linked):
    sys.stderr.write(f"land-result: {job_dir.name}: attachment {name!r} is not linked from the document\n")
  return out


def _commit(repo: Path, paths: list[str]) -> None:
  """
  Commit exactly `paths` under this worker's bot identity, repaint folded in.

  Nothing is committed when the paths hold no change.

  Args:
    repo: The repository root.
    paths: Repo-relative paths to commit; the operator's staged entries stay out of the commit.

  Raises:
    subprocess.CalledProcessError: If the commit fails.
  """
  # commit exactly what this landing wrote under the dedicated bot identity, its icon repaint folded in; a
  # byte-identical re-landing changed nothing and commits nothing
  flip_gate.commit_paths(
      repo, paths, author_name = _LAND_AUTHOR_NAME, author_email = LAND_AUTHOR_EMAIL,
      subject = f"{_LAND_AUTHOR_NAME}: land {len(paths)} file(s) for {Path(paths[0]).parent.name}",
  )


def _snapshot(destinations: list[Path]) -> dict[Path, bytes | None]:
  """
  Record what each destination holds before the landing writes a byte.

  Args:
    destinations: Every path the landing is about to write.

  Returns:
    Each destination mapped to its current bytes, or to `None` when nothing is there yet.
  """
  return {dest: dest.read_bytes() if dest.is_file() else None for dest in destinations}


def _indexed(repo: Path, paths: list[str]) -> set[str]:
  """
  Select the paths the shared git index already carries.

  Args:
    repo: The repository root.
    paths: Repo-relative paths to look up.

  Returns:
    The subset of `paths` with an index entry, staged or committed.
  """
  # guard: rejects a repository root that does not exist, which has no index to carry any path
  if not repo.is_dir():
    return set()

  # one listing answers for every path at once, in the same repo-relative spelling the caller used
  listing = subprocess.run(
      ["git", "ls-files", "-z", "--", *paths],
      cwd = str(repo), check = False, capture_output = True, text = True, encoding = "utf-8",
  )
  return {path for path in listing.stdout.split("\0") if path}


def _unstage(repo: Path, paths: list[str]) -> None:
  """
  Take exactly `paths` back out of the shared index, leaving everything else staged.

  Undoes the intent-to-add registrations a failed landing made for brand-new files. A path the index
  already carried before the landing, including one the operator staged, is never reset.

  Notes:
    - Never raises: a reset that cannot run leaves the index as it is rather than masking the
      failure the roll-back is already unwinding.

  Args:
    repo: The repository root.
    paths: Repo-relative brand-new paths the failed landing registered as intent-to-add.
  """
  # guard: an empty pathspec would reset the whole index, including what the operator parked
  if not paths:
    return

  # the landing registered these itself, so only these come back out
  subprocess.run(
      ["git", "reset", "-q", "--", *paths],
      cwd = str(repo), check = False, capture_output = True,
  )


def _restore(snapshot: dict[Path, bytes | None]) -> None:
  """
  Put every destination back to what `_snapshot` found there.

  Args:
    snapshot: The mapping `_snapshot` returned before the landing's first write.
  """
  for dest, before in snapshot.items():
    # guard: a destination the landing itself created is removed, not left behind empty
    if before is None:
      dest.unlink(missing_ok = True)
      continue
    dest.write_bytes(before)


def land_result(job_dir: Path, target_doc: Path) -> dict:
  """
  Put one finished job's `result/` into the asset folder and commit it.

  Guarantees:
    - Writes nothing and commits nothing when the job has nothing to deliver — the response
      declares no files, the work was deferred, or the job ended in error against a document
      that is not a report journal — and reports `empty`.
    - Writes nothing and commits nothing when the landing is refused, and reports `refused` with
      a one-line reason, which the gate tick turns into a halted asset. A landing
      is refused when `response.json` is unreadable, when files are declared under an outcome
      that is neither `edited` nor `error`, when an entry is not a plain filename under
      `result/`, when the bundle file is a symlink or absent, when the document's basename is
      not the target's, or when an attachment's destination is a symlink, the result document,
      or a spec catalog's own note.
    - A job that ended in `error` against `code-report.md` or `test-report.md` lands its files
      like one that ended with an edit.
    - The commit carries exactly the landed paths plus their icon repaint — content another
      writer parked in the shared index stays unpublished; a landing that changed no byte
      reports `landed` and makes no commit at all.
    - A write or a commit that fails puts every destination back to the bytes it held before
      the landing — one the landing created is removed — takes back only the intent-to-add
      registrations the landing made, so the operator's staged entries survive, and re-raises
      the failure.

  Args:
    job_dir: The finished job's bundle directory.
    target_doc: The path the job's result document takes in the asset folder.

  Returns:
    `{"action": "landed", "landed": [<repo-relative paths>]}` when files landed,
    `{"action": "empty", "landed": []}` when there was nothing to land, or
    `{"action": "refused", "landed": [], "reason": <one line>}` when the landing was refused.

  Raises:
    subprocess.CalledProcessError: If a git command of the landing's own commit exits
      non-zero, after every destination has been restored.
    OSError: If a destination cannot be written or the commit cannot be spawned, after every
      destination has been restored.
  """

  # Contract:
  # The commit this call makes carries exactly the paths it wrote plus their icon repaint;
  # content staged by anyone else stays in the index, unpublished. Either every destination
  # carries the landing and the commit records it, or every destination holds what it held
  # before the call, the index holds nothing this call put there, and the failure reaches the
  # caller.

  # Contract:
  # A job that delivers nothing is reported `empty`; a job whose declared delivery this call will
  # not make is reported `refused`, with a one-line reason. A refusal is never reported as
  # `empty`, because the caller halts the asset on `refused` and retires the job on `empty`.

  try:
    entries = _select_entries(job_dir, target_doc)

    # guard: nothing delivered — the asset folder is left exactly as found
    if not entries:
      return {_ACTION_KEY: _ACTION_EMPTY, _LANDED_KEY: []}
    names = [_basename(entry) for entry in entries]

    # guard: the document lands where the caller said, never under a name the expert chose
    if names[0] != target_doc.name:
      raise LandResultError(f"result document {names[0]!r} is not the target {target_doc.name!r}")

    # every entry is a promise about a file and a destination: check the whole list before
    # anything is written, so one bad entry lands nothing at all rather than a part
    for index, name in enumerate(names):
      _require_entry_lands(job_dir / _RESULT_DIR / name,
                           None if index == 0 else target_doc.parent / name, target_doc)
  except LandResultError as exc:
    return _refuse_landing(job_dir, str(exc))

  # what every destination holds right now, so a failed commit can undo the whole landing
  repo = flip_gate.repo_root(target_doc.parent)
  destinations = [target_doc, *(target_doc.parent / name for name in names[1:])]
  before = _snapshot(destinations)
  indexed = _indexed(repo, [str(dest.resolve().relative_to(repo.resolve())) for dest in destinations])
  landed: list[str] = []

  # write and commit as one step: whatever the folder held comes back if the commit does not land
  try:
    # the document first, with its links pointed at the neighbours it will sit beside
    body = (job_dir / _RESULT_DIR / names[0]).read_text(encoding = "utf-8")
    target_doc.parent.mkdir(parents = True, exist_ok = True)
    spec_paths.write_text_atomic(target_doc, _fix_links(body, names[1:], job_dir))
    landed.append(str(target_doc.resolve().relative_to(repo.resolve())))

    # then every attachment, beside it, under the basename the response declared
    for name in names[1:]:
      dest = target_doc.parent / name
      shutil.copyfile(job_dir / _RESULT_DIR / name, dest)
      landed.append(str(dest.resolve().relative_to(repo.resolve())))

    # one commit over exactly what this landing wrote, under this worker's own bot identity
    _commit(repo, landed)
  # the roll-back is the only thing this handler adds — the caller still decides what an
  # undeliverable job means, so the failure is re-raised exactly as it arrived
  except (subprocess.CalledProcessError, OSError):
    _unstage(repo, [path for path in landed if path not in indexed])
    _restore(before)
    raise

  # the landing is committed, so the paths it wrote are the ones it reports
  return {_ACTION_KEY: _ACTION_LANDED, _LANDED_KEY: landed}


def land_job(job_dir: Path, asset_dir: Path) -> dict:
  """
  Land one finished job's `result/` where its own dispatch said the document belongs.

  Guarantees:
    - A dispatch with no usable target never yields a silent empty ending for a job that declared
      files: the answer is `refused` when the response declares files and `empty` only when it
      declares none.

  Args:
    job_dir: The finished job's bundle directory.
    asset_dir: The asset folder the job's document must land in.

  Returns:
    The result of `land_result` for the dispatch's target. When the dispatch names no usable
    target: `{"action": "refused", "landed": [], "reason": <one line>}` if the response declares
    files, `{"action": "empty", "landed": []}` if it declares none.

  Raises:
    subprocess.CalledProcessError: Propagated from `land_result`.
    OSError: Propagated from `land_result`.
  """

  # Contract:
  # When the dispatch names no usable target, the answer is `refused` if the response declares
  # files and `empty` only if it declares none; declared files with nowhere to go are never
  # reported as an empty ending.

  target, reason = _resolve_target(job_dir, asset_dir)

  # with a usable target the landing itself decides the rest
  if target is not None:
    return land_result(job_dir, target)

  # guard: files with nowhere to go are a refused landing, not an empty one
  if _declared_entries(_read_response(job_dir)):
    return _refuse_landing(job_dir, reason)
  return { _ACTION_KEY: _ACTION_EMPTY, _LANDED_KEY: [] }


def main(argv: list[str]) -> int:
  """
  Land one finished job's result set from the command line, printing the result as JSON.

  Without `--target` the document goes where the job's own dispatch payload said, which must be
  inside `asset_dir`. With it, the
  caller names the target itself — the coordinator's cascade landing, whose document belongs to
  another asset — and the only bound left is the spec catalog's own content root.

  Notes:
    - Without `--target`, prints the answer of `land_job` and exits 0: `refused` when the dispatch names
      no usable target but the response declares files, `empty` when it declares none.
    - Otherwise prints the result of the landing: `landed`, `empty` or `refused`.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the job directory does not exist or an overridden target
    falls outside the catalog.
  """
  # the CLI surface: a job bundle, the asset folder that anchors it, and the optional override
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs land-result")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("job_dir", type = Path)
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_dir", type = Path)
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--target", type = Path, default = None,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "land the document here instead of where the dispatch said")
  args = parser.parse_args(argv)

  # guard: the job bundle must exist before anything is read out of it
  job_dir: Path = args.job_dir.resolve()
  if not job_dir.is_dir():
    sys.stderr.write(f"no job bundle: {job_dir}\n")
    return 2

  # the asset folder anchors both the repo-root lookup and the un-overridden containment check
  asset_dir: Path = args.asset_dir.resolve()

  # an overridden target answers to the catalog instead of to one asset folder
  if args.target is not None:
    target: Path = args.target.resolve()
    catalog = spec_paths.spec_content_root(flip_gate.repo_root(asset_dir))

    # guard: no override may place a document outside the spec catalog
    if not _is_inside(target, catalog):
      sys.stderr.write(f"target outside the spec catalog {catalog}: {target}\n")
      return 2
  else:
    # the dispatch's own target, with the same refused-or-empty answer the tick gets when there is none
    print(json.dumps(land_job(job_dir, asset_dir)))
    return 0

  # run the overridden landing and report it the same way every other lazycortex-specs worker does
  print(json.dumps(land_result(job_dir, target)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
