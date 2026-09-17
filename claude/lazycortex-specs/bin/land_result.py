"""
`land-result` — the specs-side collector for one finished expert job.

A launch-checkbox job never writes into the spec catalog itself: it returns its result
document as the FIRST entry of `response.json`'s `result` array and every attachment after
it, and this worker puts them in place. The document lands at the target path the caller
names; each attachment lands beside it under its own basename; the document's
`result/<file>` links are rewritten to those neighbour names; and the whole set is
committed under this worker's own bot identity with an explicit pathspec, because the
checkout's index is shared with the operator and with every other routine.

`gate_tick.py` calls this on a job's `DONE`, before the coordinator opens review with the
review system's `submit` verb — so the document the coordinator submits is already tracked.
The path checks are mirrored file-wise from `lazycortex-review`'s own `payload.py` rather
than imported: a cross-plugin Python import would break in a consumer install where the two
plugins live at unrelated cache paths (`dev.plugin-boundaries.md` § 2a).
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

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
import flip_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import iconize_inline  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import SpecKey  # noqa: E402


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
_RESULT_KEY = "result"
_PATH_KEY = "path"

# Bot identity for this worker's own commits.
_LAND_AUTHOR_NAME = "lazy-spec.land-result"
_LAND_AUTHOR_EMAIL = "lazy-spec.land-result@bot.invalid"

# A link target pointing into the job's own result dir — what a writer spells when it references
# an attachment it is returning alongside the document. Four shapes carry such a target: an inline
# link `(result/x)`, a titled inline link `(result/x "t")`, a reference definition `[a]: result/x`,
# and an HTML source attribute `src="result/x"`. Only the opening delimiter is captured and
# replayed, so whatever closes each shape is left exactly as the writer spelled it.
_RESULT_LINK_RE = re.compile(
    r"""(?P<open>\(|\]:[ \t]*|src[ \t]*=[ \t]*["'])result/(?P<name>[^)"'\s]+)""")

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
_LANDED_KEY = "landed"


class LandResultError(Exception):
  """
  A response payload this worker refuses to land.

  Raised for an entry that names no path string, points outside the job's own `result/`, or
  resolves to anything but a plain filename. The caller turns it into an `empty` landing, so
  the coordinator marks the job undelivered instead of writing a file nobody declared.
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
    values, _ = flip_gate.parse_frontmatter(path.read_text())
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


def _read_entries(job_dir: Path) -> list[object]:
  """
  Read one finished job's deliverable `result` entries.

  Args:
    job_dir: The job-bundle directory.

  Returns:
    The response's `result` array; empty when the bundle has no readable response, did not
    finish with an edit, or delivered nothing.
  """
  try:
    response = json.loads((job_dir / _RESPONSE_FILE).read_text())
  except (OSError, json.JSONDecodeError):
    return []
  # guard: only a completed edit carries files to land
  if response.get(_OUTCOME_KEY) != _OUTCOME_EDITED:
    return []
  entries = response.get(_RESULT_KEY)
  return entries if isinstance(entries, list) else []


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

  Args:
    job_dir: The job-bundle directory.
    asset_dir: The asset folder the job's document must land in.

  Returns:
    The repo-root-resolved `target_doc` the dispatch payload declared, or `None` when the
    payload is unreadable, declares no `target_doc`, or names a path outside `asset_dir`.
  """

  # Domain(spec.lifecycle):
  # # Where a document belongs travels with the job, not with what came back
  # A job is dispatched to write one named document, and that name is settled when the job is
  # created, by the side that knows the ladder. What comes back is only content: an expert
  # returning a file under some other name has misunderstood its job, not relocated it, and no
  # mapping from the step's label to a filename could stand in for the dispatch's own statement
  # anyway — a cascade job writes into a different asset's folder entirely. A job that never said
  # where its document goes has nowhere to put it and stays undelivered.

  try:
    request = json.loads((job_dir / _REQUEST_FILE).read_text())
  except (OSError, json.JSONDecodeError) as exc:
    sys.stderr.write(f"land-result: {job_dir.name}: unreadable {_REQUEST_FILE}: {exc}\n")
    return None
  raw = request.get(_TARGET_DOC_KEY) if isinstance(request, dict) else None
  # guard: a job that declared no target has nowhere to put its document
  if not isinstance(raw, str) or not raw:
    sys.stderr.write(f"land-result: {job_dir.name}: dispatch declares no {_TARGET_DOC_KEY!r}\n")
    return None

  # the declared path is repo-relative; resolving it collapses any parent hop before the
  # containment check below, which is what actually decides whether it may be written
  target = (flip_gate.repo_root(asset_dir) / raw).resolve()
  # guard: a launch job's document belongs in its own asset folder and nowhere else
  if not _is_inside(target, asset_dir):
    sys.stderr.write(
        f"land-result: {job_dir.name}: {_TARGET_DOC_KEY} {raw!r} is outside {asset_dir.name}\n")
    return None
  return target


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

  # rewrite every link in one pass, then report what the two sides did not agree on
  out = _RESULT_LINK_RE.sub(_neighbour, body)
  # a file nobody references is still landed — the operator is told, the job is not failed
  for name in sorted(delivered - linked):
    sys.stderr.write(f"land-result: {job_dir.name}: attachment {name!r} is not linked from the document\n")
  return out


def _commit(repo: Path, paths: list[str]) -> None:
  """
  Commit exactly `paths` under this worker's bot identity, repaint folded in.

  Args:
    repo: The repository root.
    paths: Repo-relative paths to stage and commit.
  """
  # the icon repaint rides the same commit so no second, foreign-identity commit follows
  extra_paths = iconize_inline.repaint_paths(repo, paths)
  all_paths = list(dict.fromkeys([*paths, *extra_paths]))

  # guard: a byte-identical re-landing changed nothing — an empty status over exactly these
  # paths covers all three states at once (untracked, unstaged, staged), which `git diff` alone
  # does not: it is blind to a file the first landing has only just created
  status = subprocess.run(
      ["git", "status", "--porcelain", "--", *all_paths],
      cwd = str(repo), check = True, capture_output = True, text = True,
  )
  if not status.stdout.strip():
    return

  # stage exactly what this landing wrote — the index is shared, so nothing else may ride along
  subprocess.run(
      ["git", "add", "--", *all_paths],
      cwd = str(repo), check = True, capture_output = True,
  )

  # commit under the dedicated bot identity so the operator's authorship stays untouched
  subprocess.run(
      [
          "git",
          "-c", f"user.name={_LAND_AUTHOR_NAME}",
          "-c", f"user.email={_LAND_AUTHOR_EMAIL}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m",
          f"{_LAND_AUTHOR_NAME}: land {len(paths)} file(s) for {Path(paths[0]).parent.name}",
          "--", *all_paths,
      ],
      cwd = str(repo), check = True, capture_output = True,
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


def _unstage(repo: Path, paths: list[str]) -> None:
  """
  Take exactly `paths` back out of the shared index, leaving everything else staged.

  Notes:
    - Never raises: a reset that cannot run leaves the index as it is rather than masking the
      failure the roll-back is already unwinding.

  Args:
    repo: The repository root.
    paths: Repo-relative paths the failed landing may have staged.
  """
  # guard: an empty pathspec would reset the whole index, including what the operator parked
  if not paths:
    return

  # the landing staged these itself, so only these come back out
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
    - Writes nothing and commits nothing when the job delivered no files or any entry is
      refused; the job is left undelivered for the coordinator to report. An entry is refused
      when it is not a plain filename under `result/`, when the bundle file is a symlink or
      absent, when the document's basename is not the target's, or when an attachment's
      destination is a symlink, the result document, or a spec catalog's own note.
    - The commit carries exactly the landed paths plus their icon repaint — content another
      writer parked in the shared index stays unpublished; a landing that changed no byte
      reports `landed` and makes no commit at all.
    - A write or a commit that fails puts every destination back to the bytes it held before
      the landing — one the landing created is removed — takes the landing's own paths back
      out of the shared index, and re-raises the failure.

  Args:
    job_dir: The finished job's bundle directory.
    target_doc: The path the job's result document takes in the asset folder.

  Returns:
    `{"action": "landed", "landed": [<repo-relative paths>]}` when files landed, or
    `{"action": "empty", "landed": []}` when there was nothing to land.

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

  entries = _read_entries(job_dir)
  # guard: nothing delivered — the asset folder is left exactly as found
  if not entries:
    return {_ACTION_KEY: _ACTION_EMPTY, _LANDED_KEY: []}
  try:
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
    sys.stderr.write(f"land-result: {job_dir.name}: {exc}\n")
    return {_ACTION_KEY: _ACTION_EMPTY, _LANDED_KEY: []}

  # what every destination holds right now, so a failed commit can undo the whole landing
  repo = flip_gate.repo_root(target_doc.parent)
  before = _snapshot([target_doc, *(target_doc.parent / name for name in names[1:])])
  landed: list[str] = []

  # write and commit as one step: whatever the folder held comes back if the commit does not land
  try:
    # the document first, with its links pointed at the neighbours it will sit beside
    body = (job_dir / _RESULT_DIR / names[0]).read_text()
    target_doc.parent.mkdir(parents = True, exist_ok = True)
    target_doc.write_text(_fix_links(body, names[1:], job_dir))
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
    _unstage(repo, landed)
    _restore(before)
    raise

  # the landing is committed, so the paths it wrote are the ones it reports
  return {_ACTION_KEY: _ACTION_LANDED, _LANDED_KEY: landed}


def main(argv: list[str]) -> int:
  """
  Land one finished job's result set from the command line, printing the result as JSON.

  Without `--target` the document goes where the job's own dispatch payload said, which must be
  inside `asset_dir`. With it, the caller names the target itself — the coordinator's cascade
  landing, whose document belongs to another asset — and the only bound left is the spec
  catalog's own content root.

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
    target: Path | None = args.target.resolve()
    catalog = spec_paths.spec_content_root(flip_gate.repo_root(asset_dir))
    # guard: no override may place a document outside the spec catalog
    if target is not None and not _is_inside(target, catalog):
      sys.stderr.write(f"target outside the spec catalog {catalog}: {target}\n")
      return 2
  else:
    target = document_target(job_dir, asset_dir)

  # guard: nothing to land onto — the job stays undelivered, reported as an empty landing
  if target is None:
    print(json.dumps({_ACTION_KEY: _ACTION_EMPTY, _LANDED_KEY: []}))
    return 0

  # run the landing and report it the same way every other lazycortex-specs worker does
  print(json.dumps(land_result(job_dir, target)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
