"""
Logic behind the `lazycortex-specs coherence-apply <job-dir>`, `coherence-dismiss <note> <doc>` and
`coherence-resolve <note> <doc>` verbs.

The apply verb hangs the conflicts a coherence check found as callouts in the `# Gates` section of the folder-notes
of the documents involved, replacing the checked document's earlier ones and ignoring reported conflicts the check
could not have found. The dismiss verb takes down the callouts of a document whose `Not a conflict` box is ticked,
together with the mirror callouts stating the same essence, and records each pair as no conflict on both notes, so
the pair is not raised again until a document is re-approved; the pair's other callouts stay. The resolve verb takes down the callouts of a document
whose `Resolve here` box is ticked, removes the document from the mirror callouts stating the same essence, and
hands back what they said, recording nothing. Each verb commits all its notes together or leaves them untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
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
import gate_tick  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import review_rows  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import ConflictCallout, ConflictKey, Gate, Section, SpecMomentKey  # noqa: E402


_ENCODING = "utf-8"
_LF = "\n"
_QUOTE = ">"
_MD_SUFFIX = ".md"
_H1_PREFIX = "# "
_GIT_DIR = ".git"
# The env var the daemon exports for every subprocess it spawns
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The bot identity the three verbs commit under
BOT_NAME = "lazy-spec.coherence"
BOT_EMAIL = f"{BOT_NAME}@bot.invalid"

# The job directory's two files the apply verb reads
_REQUEST_FILE = "request.json"
_RESULT_FILE = Path("result/conflicts.json")

# Request and result fields
_CHECKED = "checked"
_NEIGHBOURS = "neighbours"
_INNER = "inner"
_WITH = "with"
_ESSENCE = "essence"

# Summary keys
_DOC = "doc"
_NOTES = "notes"
_CONFLICTS = "conflicts"
_STATUS = "status"
_REASON = "reason"
_STATUS_REFUSED = "refused"

# A wikilink in a callout title: the target before any `#anchor` or `|display`
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
# The trailing comment naming a callout's inner document
_MARKER_RE = re.compile(rf"^{_QUOTE}\s*<!--\s*{re.escape(ConflictCallout.MARKER_PREFIX)}(.+?)\s*-->\s*$")
# A checkbox line of a callout, ticked or not
_BOX_RE = re.compile(rf"^{_QUOTE}\s*-\s*\[[ xX]\]")
# The ticked `Not a conflict` box of a callout
_DISMISS_TICKED_RE = re.compile(rf"^{_QUOTE}\s*-\s*\[[xX]\]\s*{re.escape(ConflictCallout.DISMISS)}\s*$")
# The ticked `Resolve here` box of a callout
_RESOLVE_TICKED_RE = re.compile(rf"^{_QUOTE}\s*-\s*\[[xX]\]\s*{re.escape(ConflictCallout.RESOLVE)}\s*$")
# The refusal reason when the document's callouts carry no ticked `Not a conflict` box
NOTHING_TICKED = "nothing-ticked"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class Conflict:
  """
  One conflict a coherence check found: an inner document, the documents it disagrees with, and the gist.

  Attributes:
    inner: The repo-relative document the callout hangs for.
    with_docs: The repo-relative documents the inner one disagrees with, in title order.
    essence: The one-line statement of the disagreement.
  """

  # The repo-relative document the callout hangs for
  inner: str

  # The repo-relative documents the inner one disagrees with, in title order
  with_docs: tuple[str, ...]

  # The one-line statement of the disagreement
  essence: str


# ----------------------------------------------------------------------------------------
@dataclass
class _NoteState:
  """
  One folder-note held in memory while a verb rewrites its conflict callouts.

  Attributes:
    path: The folder-note file.
    text: The note's text as read.
    blocks: The note's conflict callouts in note order: each block's lines and the conflict parsed from them, `None`
      when the block names no inner document.
    dismissed: The note's `spec_conflict_dismissed` entries.
  """

  # The folder-note file
  path: Path

  # The note's text as read
  text: str

  # The note's conflict callouts in note order, each with its parsed conflict or None
  blocks: list[tuple[list[str], Conflict | None]] = field(default_factory = list)

  # The note's `spec_conflict_dismissed` entries
  dismissed: list[dict] = field(default_factory = list)


# ----------------------------------------------------------------------------------------
def folder_note(doc: Path) -> Path:
  """
  Name the folder-note of the folder a document lives in.

  Args:
    doc: The document.

  Returns:
    `<folder>/<folder name>.md` beside the document.
  """
  return doc.parent / f"{doc.parent.name}{_MD_SUFFIX}"


def _label(doc: str) -> str:
  """
  Build the display text of a link to a document.

  Args:
    doc: The repo-relative document.

  Returns:
    `<folder name>/<document stem>`.
  """
  path = Path(doc)
  return f"{path.parent.name}/{path.stem}"


def render_callout(conflict: Conflict, repo: Path) -> list[str]:
  """
  Render the callout one conflict hangs in its inner document's folder-note.

  Args:
    conflict: The conflict to render.
    repo: The repository root.

  Returns:
    The callout lines, title first: the links to the `with` documents, the essence, the `Resolve here` and
    `Not a conflict` boxes, and the comment naming the inner document.
  """
  settings_root = spec_paths.find_settings_root(repo)
  links = ", ".join(
      f"[[{spec_paths.build_wikilink_target(repo / doc, settings_root)}|{_label(doc)}]]"
      for doc in conflict.with_docs
  )
  return [
      f"{review_rows.CONFLICT_OPEN}{links}",
      f"{_QUOTE} {conflict.essence}",
      f"{_QUOTE} - [ ] {ConflictCallout.RESOLVE}",
      f"{_QUOTE} - [ ] {ConflictCallout.DISMISS}",
      f"{_QUOTE} <!-- {ConflictCallout.MARKER_PREFIX}{conflict.inner} -->",
  ]


def _parse_block(lines: list[str], repo: Path, settings_root: Path) -> Conflict | None:
  """
  Read the conflict a callout block records.

  Args:
    lines: The block's lines, title first.
    repo: The repository root.
    settings_root: The directory holding `.claude/lazy.settings.json`.

  Returns:
    The conflict, or `None` when the block carries no comment naming its inner document.
  """
  inner = next(( match.group(1) for line in lines if (match := _MARKER_RE.match(line)) ), None)

  # guard: without its marker the block cannot say whose callout it is
  if inner is None:
    return None

  # the title's links, each resolved the way Obsidian resolves it
  root = repo.resolve()
  with_docs = []
  for target in _WIKILINK_RE.findall(lines[0]):
    doc = spec_paths.resolve_wikilink(target.strip(), settings_root).resolve()
    with_docs.append(doc.relative_to(root).as_posix() if doc.is_relative_to(root) else target.strip())

  # the essence is the first body line that is neither a box nor the marker
  body = [ line for line in lines[1:] if not _BOX_RE.match(line) and not _MARKER_RE.match(line) ]
  essence = next(( text for line in body if (text := line[len(_QUOTE):].strip()) ), "")
  return Conflict(inner = inner, with_docs = tuple(with_docs), essence = essence)


def _gates_bounds(lines: list[str]) -> tuple[int, int] | None:
  """
  Find the `# Gates` section of a note body.

  Args:
    lines: The note body's lines.

  Returns:
    The section's `(start, end)` half-open line range, heading included, or `None` when the body has no section.
  """
  head = next(( idx for idx, line in enumerate(lines) if line.strip() == Section.GATES ), None)

  # guard: a body without the section has nowhere to hold a callout
  if head is None:
    return None
  end = next(( idx for idx in range(head + 1, len(lines)) if lines[idx].startswith(_H1_PREFIX) ), len(lines))
  return head, end


def _read_dismissed(fm_values: dict) -> list[dict]:
  """
  Read a note's dismissal entries.

  Args:
    fm_values: The note's parsed frontmatter.

  Returns:
    The entries of `spec_conflict_dismissed`, empty when the key is absent or does not hold a JSON list.
  """
  try:
    entries = json.loads(fm_values.get(ConflictKey.DISMISSED, "") or "[]")
  except json.JSONDecodeError:
    return []
  return [ entry for entry in entries if isinstance(entry, dict) ] if isinstance(entries, list) else []


def _load_note(repo: Path, note: Path) -> _NoteState:
  """
  Read a folder-note's conflict callouts and dismissals.

  Args:
    repo: The repository root.
    note: The folder-note.

  Returns:
    The note in memory.

  Raises:
    ValueError: If the note does not exist or has no `# Gates` section.
  """
  # guard: a document whose folder has no note has nowhere to hold a callout
  if not note.is_file():
    raise ValueError(f"no folder-note {note.relative_to(repo).as_posix() if note.is_relative_to(repo) else note}")
  text = note.read_text(encoding = _ENCODING)
  fm_values, fm_end = spec_frontmatter.parse(text)
  lines = text[fm_end:].split(_LF)

  # guard: the callouts live in the `# Gates` section only
  if (bounds := _gates_bounds(lines)) is None:
    raise ValueError(f"the note has no {Section.GATES} section: {note.relative_to(repo).as_posix()}")

  # every conflict callout of the section, with what it records
  settings_root = spec_paths.find_settings_root(repo)
  section = lines[bounds[0]:bounds[1]]
  blocks = [
      ( section[start:end], _parse_block(section[start:end], repo, settings_root) )
      for start, end in review_rows.find_all_conflict_spans(section)
  ]
  return _NoteState(path = note, text = text, blocks = blocks, dismissed = _read_dismissed(fm_values))


def read_conflicts(repo: Path, note: Path) -> list[Conflict]:
  """
  Read the conflict callouts a folder-note carries.

  Args:
    repo: The repository root.
    note: The folder-note.

  Returns:
    The conflicts in note order; a callout that names no inner document is left out.

  Raises:
    ValueError: If the note does not exist or has no `# Gates` section.
  """
  return [ conflict for _lines, conflict in _load_note(repo, note).blocks if conflict is not None ]


def _approved_at(repo: Path, doc: str) -> str:
  """
  Read a document's approval stamp.

  Args:
    repo: The repository root.
    doc: The repo-relative document.

  Returns:
    The document's `spec_approved_at`, empty when it has none or no longer exists.
  """
  path = repo / doc

  # guard: a deleted document carries no stamp
  if not path.is_file():
    return ""
  fm_values, _end = spec_frontmatter.parse(path.read_text(encoding = _ENCODING))
  return str(fm_values.get(SpecMomentKey.APPROVED_AT, "")).strip()


def _is_dismissed(repo: Path, state: _NoteState, inner: str, other: str) -> bool:
  """
  Tell whether a note records a pair as dismissed at both documents' current approvals.

  Args:
    repo: The repository root.
    state: The note whose dismissals are read.
    inner: One document of the pair.
    other: The other document of the pair.

  Returns:
    True when an entry names the two documents, either way round, with stamps equal to their current ones.
  """

  # Domain(spec.coherence):
  # # A dismissed pair stays quiet until either document is re-approved
  # When the operator marks a pair of documents as "Not a conflict", the pair is not raised again by later checks. The
  # dismissal holds only for the approvals both documents had at the moment of dismissal: a re-approval of either one
  # revives the question, because the text that was judged compatible is no longer the text that stands. The pair is
  # the same whichever of the two documents is the inner one.

  stamps = { inner: _approved_at(repo, inner), other: _approved_at(repo, other) }
  for entry in state.dismissed:
    one, two = str(entry.get(ConflictKey.INNER)), str(entry.get(ConflictKey.WITH))

    # guard: an entry about another pair says nothing about this one
    if { one, two } != { inner, other }:
      continue

    # the pair stays dismissed only while neither document was approved again since
    if entry.get(ConflictKey.INNER_APPROVED_AT) == stamps[one] and \
        entry.get(ConflictKey.WITH_APPROVED_AT) == stamps[two]:
      return True
  return False


def _drop_doc(repo: Path, state: _NoteState, doc: str, *, inner: str | None = None,
              essences: set[str] | None = None) -> None:
  """
  Take a document out of every callout of a note that names it in its `with` list.

  A callout whose `with` list is left empty is removed; a trimmed one gets a new title line and keeps every other
  line as it was.

  Args:
    repo: The repository root.
    state: The note to edit in memory.
    doc: The repo-relative document to take out.
    inner: When given, only the callouts hung for this inner document are touched.
    essences: When given, only the callouts stating one of these essences are touched.
  """
  kept: list[tuple[list[str], Conflict | None]] = []
  for lines, conflict in state.blocks:
    # guard: a callout that does not name the document, or belongs to another inner one or essence, stays as it is
    if conflict is None or doc not in conflict.with_docs or inner not in ( None, conflict.inner ) or \
        ( essences is not None and conflict.essence not in essences ):
      kept.append(( lines, conflict ))
      continue

    # the trimmed callout survives only while it still names a document, its boxes untouched
    rest = tuple(other for other in conflict.with_docs if other != doc)
    if rest:
      trimmed = Conflict(inner = conflict.inner, with_docs = rest, essence = conflict.essence)
      kept.append(( [ render_callout(trimmed, repo)[0], *lines[1:] ], trimmed ))
  state.blocks = kept


def _is_live(repo: Path, doc: str) -> bool:
  """
  Tell whether a document still takes part in the catalog.

  Args:
    repo: The repository root.
    doc: The repo-relative document.

  Returns:
    True when the document exists and the folder-note beside it does not mark its asset cancelled.
  """
  path = repo / doc

  # guard: a deleted document takes part in nothing
  if not path.is_file():
    return False
  note = folder_note(path)
  return not note.is_file() or \
      not flip_gate.is_true(spec_frontmatter.parse(note.read_text(encoding = _ENCODING))[0], Gate.SPEC_CANCELLED)


def _sweep(repo: Path, state: _NoteState) -> None:
  """
  Take out of a note every callout and listed document that no longer takes part in the catalog.

  Args:
    repo: The repository root.
    state: The note to edit in memory.
  """

  # Domain(spec.coherence):
  # # A conflict with a document that is gone or cancelled is no conflict
  # A document that was deleted, or whose asset was cancelled, no longer disagrees with anything. Every time conflict
  # callouts are rewritten, the callouts hung for such a document disappear, and such a document is taken out of the
  # other callouts that list it; a callout left listing no document at all disappears with it.

  live: dict[str, bool] = {}
  docs = { doc for _lines, conflict in state.blocks if conflict is not None
           for doc in ( conflict.inner, *conflict.with_docs ) }
  for doc in docs:
    live[doc] = _is_live(repo, doc)

  # the callouts of a dead document go whole, a dead document goes from every other list
  state.blocks = [ ( lines, conflict ) for lines, conflict in state.blocks
                   if conflict is None or live[conflict.inner] ]
  for doc in sorted(doc for doc, alive in live.items() if not alive):
    _drop_doc(repo, state, doc)


def _try_load(repo: Path, note: Path) -> _NoteState | None:
  """
  Read a folder-note's conflict callouts when the note can hold them.

  Args:
    repo: The repository root.
    note: The folder-note.

  Returns:
    The note in memory, or `None` when the note does not exist.

  Raises:
    ValueError: If the note exists but has no `# Gates` section.
  """
  # guard: a note that is gone is skipped rather than refused
  if not note.is_file():
    return None
  return _load_note(repo, note)


def _add(repo: Path, state: _NoteState, conflict: Conflict) -> None:
  """
  Hang a conflict's callout in a note unless an identical one already hangs there.

  Args:
    repo: The repository root.
    state: The note to edit in memory.
    conflict: The conflict to hang.
  """
  # guard: the same conflict is never hung twice
  if any(existing == conflict for _lines, existing in state.blocks):
    return
  state.blocks.append(( render_callout(conflict, repo), conflict ))


def _record(state: _NoteState, entry: dict) -> None:
  """
  Add a dismissal entry to a note unless an identical one is already there.

  Args:
    state: The note to edit in memory.
    entry: The dismissal entry.
  """
  # guard: the same pair at the same stamps is recorded once
  if entry in state.dismissed:
    return
  state.dismissed.append(entry)


def _render_note(repo: Path, state: _NoteState) -> str:
  """
  Render a note with its current callouts laid out in `# Gates` and its frontmatter flags brought in line.

  Args:
    repo: The repository root.
    state: The note in memory.

  Returns:
    The note's new text.
  """
  _fm_values, fm_end = spec_frontmatter.parse(state.text)
  lines = state.text[fm_end:].split(_LF)
  bounds = _gates_bounds(lines)

  # guard: a note is loaded only with its section, so a missing one means the file changed under the verb
  if bounds is None:
    raise ValueError(f"the note lost its {Section.GATES} section: {state.path}")
  head, end = bounds
  section = lines[head:end]

  # the section without its old callouts, the current ones appended after its last written line
  for start, stop in reversed(review_rows.find_all_conflict_spans(section)):
    del section[start:stop]
  last = max(( idx for idx, line in enumerate(section) if line.strip() ), default = 0) + 1
  section[last:last] = [ row for block, _conflict in state.blocks for row in [ "", *block ] ]

  # the layout sorts the callouts under their own heading after the row groups
  laid = review_rows.layout_section(
      section, review_rows.read_review_stages(repo, state.path), note_explainers.lang_for_note(state.path),
  )
  body = _LF.join([ *lines[:head], *laid, *lines[end:] ])

  # Domain(spec.coherence):
  # # A conflicted folder-note is one that holds a conflict callout
  # A folder-note is flagged as conflicted exactly while it holds at least one conflict callout, and the flag is taken
  # down as soon as the last callout goes. A conflict only informs: it blocks nothing, neither the approval of the
  # documents involved nor any step of the ladder.

  # the flag says whether the note holds a callout, the dismissals ride as one JSON line
  fm_text = state.text[:fm_end]
  if state.blocks:
    fm_text = flip_gate.set_bool(fm_text, ConflictKey.CONFLICTED, True)
  else:
    fm_text = gate_tick.del_fm_key(fm_text, ConflictKey.CONFLICTED)
  if state.dismissed:
    fm_text = gate_tick.set_fm_json(fm_text, ConflictKey.DISMISSED, state.dismissed)
  return fm_text + body


def _write_all(repo: Path, states: dict[Path, _NoteState], originals: dict[Path, tuple]) -> list[Path]:
  """
  Write every note whose callouts or dismissals changed.

  Args:
    repo: The repository root.
    states: The notes in memory, keyed by path.
    originals: Each note's callout lines and dismissals as read, keyed by path.

  Returns:
    The notes whose text changed on disk, in path order.
  """
  touched: list[Path] = []
  for path in sorted(states):
    state = states[path]

    # guard: a note whose callouts and dismissals are as read needs no rewrite, flag aside
    snapshot = ( [ lines for lines, _conflict in state.blocks ], state.dismissed )
    flagged = flip_gate.is_true(spec_frontmatter.parse(state.text)[0], ConflictKey.CONFLICTED)
    if snapshot == originals[path] and flagged == bool(state.blocks):
      continue
    text = _render_note(repo, state)
    if text != state.text:
      spec_paths.write_text_atomic(path, text)
      touched.append(path)
  return touched


def _snapshot(states: dict[Path, _NoteState]) -> dict[Path, tuple]:
  """
  Record each note's callout lines and dismissals as read, so a later write can tell what changed.

  Args:
    states: The notes in memory, keyed by path.

  Returns:
    Each note's callout lines and a copy of its dismissals, keyed by path.
  """
  return {
      path: ( [ list(lines) for lines, _conflict in state.blocks ], [ dict(entry) for entry in state.dismissed ] )
      for path, state in states.items()
  }


def _commit(repo: Path, touched: list[Path], subject: str) -> None:
  """
  Commit the touched notes in one commit under the coherence bot.

  Nothing is committed when `touched` is empty or the notes hold no change.

  Args:
    repo: The repository root.
    touched: The notes the verb rewrote.
    subject: The commit subject.

  Raises:
    subprocess.CalledProcessError: If the commit fails.
    OSError: If git cannot be run.
  """
  # guard: a run that changed nothing commits nothing, and an empty pathspec would reach the whole tree
  if not touched:
    return
  flip_gate.commit_paths(repo, touched, subject = subject, author_name = BOT_NAME, author_email = BOT_EMAIL)


def _write_and_commit(repo: Path, states: dict[Path, _NoteState], originals: dict[Path, tuple],
                      subject: str) -> list[Path]:
  """
  Sweep dead documents out of the notes, then write and commit every note that changed, all or nothing.

  Guarantees:
    - On any write or commit failure, every note this run wrote is unstaged and restored to its bytes from before
      the write.

  Args:
    repo: The repository root.
    states: The notes in memory, keyed by path.
    originals: Each note's callout lines and dismissals as read, keyed by path.
    subject: The commit subject.

  Returns:
    The notes whose text changed on disk, in path order.

  Raises:
    ValueError: If any write or the commit failed; every note this run wrote is then back to its bytes from before
      the write and none of them is left staged.
  """
  for state in states.values():
    _sweep(repo, state)

  # the bytes as they stand before the first write, so any failure on the way can put every note back
  before = { path: path.read_bytes() for path in states }
  try:
    touched = _write_all(repo, states, originals)
    _commit(repo, touched, subject)
  except (subprocess.CalledProcessError, OSError) as error:
    # only the notes this run wrote come back out of the index, best-effort, then each gets its old bytes back
    written = [ path for path, data in before.items() if not path.is_file() or path.read_bytes() != data ]
    if written:
      subprocess.run([ "git", "reset", "-q", "--", *( str(path) for path in written ) ], cwd = str(repo),
                     check = False, capture_output = True)
    for path in written:
      path.write_bytes(before[path])
    raise ValueError(f"write failed: {error}") from error
  return touched


def _rel(repo: Path, path: Path) -> str:
  """
  Name a path relative to the repository root.

  Args:
    repo: The repository root.
    path: A path inside the repository.

  Returns:
    The repo-relative POSIX path.
  """
  return path.resolve().relative_to(repo.resolve()).as_posix()


def parse_doc_arg(repo: Path, raw: str) -> str:
  """
  Bring a document named on the command line or in a result to its repo-relative form.

  Args:
    repo: The repository root.
    raw: The path as given, absolute or repo-relative.

  Returns:
    The repo-relative POSIX path.

  Raises:
    ValueError: If the path lies outside the repository or names no file.
  """
  path = Path(raw) if Path(raw).is_absolute() else repo / raw

  # guard: only an existing file inside the repository is a document
  if not path.resolve().is_relative_to(repo.resolve()) or not path.is_file():
    raise ValueError(f"no such document: {raw}")
  return _rel(repo, path)


def _norm(repo: Path, raw: object) -> str | None:
  """
  Bring a document named in a job to its repo-relative form, whether it exists or not.

  Args:
    repo: The repository root.
    raw: The value as the job gives it.

  Returns:
    The repo-relative POSIX path, or `None` when the value is no non-empty string or lies outside the repository.
  """
  # guard: only a non-empty string can name a document
  if not isinstance(raw, str) or not raw.strip():
    return None
  path = (Path(raw) if Path(raw).is_absolute() else repo / raw).resolve()
  root = repo.resolve()
  return path.relative_to(root).as_posix() if path.is_relative_to(root) else None


def _parse_entry(repo: Path, entry: object) -> Conflict | None:
  """
  Read one conflict entry of a coherence result.

  Args:
    repo: The repository root.
    entry: The entry as the result gives it.

  Returns:
    The conflict, every document repo-relative, or `None` when the entry is malformed.
  """
  # guard: an entry is an object
  if not isinstance(entry, dict):
    return None
  inner = _norm(repo, entry.get(_INNER))
  raw_with = entry.get(_WITH)
  with_docs = [ _norm(repo, doc) for doc in raw_with ] if isinstance(raw_with, list) else []
  essence = entry.get(_ESSENCE)

  # guard: an inner document, a non-empty list of others and the gist, each well formed
  if inner is None or not with_docs or any(doc is None for doc in with_docs) or \
      not isinstance(essence, str) or not essence.strip():
    return None
  return Conflict(inner = inner, with_docs = tuple(dict.fromkeys(doc for doc in with_docs if doc is not None)),
                  essence = " ".join(essence.split()))


def _read_job(repo: Path, job_dir: Path) -> tuple[str, list[str] | None, list[Conflict]]:
  """
  Read a coherence job's request and result.

  Args:
    repo: The repository root.
    job_dir: The job directory.

  Returns:
    The checked document, the neighbours the request lists (`None` when it lists none), and the well-formed
    conflicts the result reports, all documents repo-relative; a malformed entry is left out.

  Raises:
    ValueError: If the request or the result cannot be read, the result is not a list, or the request names no
      existing checked document inside the repository.
  """
  try:
    request = json.loads((job_dir / _REQUEST_FILE).read_text(encoding = _ENCODING))
    result = json.loads((job_dir / _RESULT_FILE).read_text(encoding = _ENCODING))
  except (OSError, json.JSONDecodeError) as error:
    raise ValueError(f"unreadable job: {error}") from error

  # guard: the request names an existing document the check ran for
  checked = _norm(repo, request.get(_CHECKED)) if isinstance(request, dict) else None
  if checked is None or not (repo / checked).is_file():
    raise ValueError(f"the request names no {_CHECKED} document")

  # guard: the result is a list of conflict entries
  if not isinstance(result, list):
    raise ValueError("the result is not a list")
  raw_neighbours = request.get(_NEIGHBOURS)
  neighbours = [ doc for doc in ( _norm(repo, raw) for raw in raw_neighbours ) if doc is not None ] \
      if isinstance(raw_neighbours, list) else None
  conflicts = [ conflict for conflict in ( _parse_entry(repo, entry) for entry in result ) if conflict is not None ]
  return checked, neighbours, conflicts


def _is_admissible(repo: Path, conflict: Conflict, checked: str, neighbours: list[str] | None) -> bool:
  """
  Tell whether a reported conflict is one the check could have found.

  Args:
    repo: The repository root.
    conflict: The reported conflict.
    checked: The checked document.
    neighbours: The documents the check compared it with, or `None` when the request did not list them.

  Returns:
    True when the conflict involves the checked document, names only documents the check was given, does not set
    a document against itself, and names only documents that still take part in the catalog.
  """

  # Domain(spec.coherence):
  # # A check reports only conflicts it was able to see
  # A coherence check compares one document with the neighbours it was given, so every conflict it reports must
  # involve that document and name only the documents it was given; a document never conflicts with itself. A
  # reported conflict that breaks any of this, or that names a document deleted or cancelled since, is ignored and
  # the rest of the report still stands.

  docs = ( conflict.inner, *conflict.with_docs )
  allowed = None if neighbours is None else { checked, *neighbours }
  return checked in docs and conflict.inner not in conflict.with_docs and \
      ( allowed is None or all(doc in allowed for doc in docs) ) and all(_is_live(repo, doc) for doc in docs)


def _find_all_marked_notes(repo: Path) -> list[Path]:
  """
  List the folder-notes under the spec content-root that carry a conflict callout marker.

  Args:
    repo: The repository root.

  Returns:
    The folder-notes, in walk order.
  """
  root = spec_paths.spec_content_root(spec_paths.find_settings_root(repo))
  notes = []
  for dirpath, dirs, files in os.walk(root):
    dirs[:] = [ name for name in dirs if name != _GIT_DIR ]
    note = Path(dirpath) / f"{Path(dirpath).name}{_MD_SUFFIX}"
    if note.name in files and ConflictCallout.MARKER_PREFIX in note.read_text(encoding = _ENCODING):
      notes.append(note)
  return notes


def apply_result(repo: Path, job_dir: Path) -> dict:
  """
  Hang the conflicts a coherence check found as callouts on the folder-notes, replacing the checked document's.

  Notes:
    - A malformed entry, and a conflict the check could not have found, is ignored while the rest of the result
      stands.
    - A folder-note that no longer exists is skipped, and a conflict whose inner document has no folder-note is not
      raised.

  Args:
    repo: The repository root.
    job_dir: The coherence-checker job directory holding `request.json` and `result/conflicts.json`.

  Returns:
    `{"checked", "notes", "conflicts"}`: the checked document, the repo-relative notes rewritten in sorted order, and
    the number of conflicts hung.

  Raises:
    ValueError: If the job's request or result cannot be read, the result is not a list, the request names no
      existing checked document, a folder-note it reaches has no `# Gates` section, or the commit failed; nothing
      is left written then.
  """
  checked, neighbours, reported = _read_job(repo, job_dir)
  conflicts = [ conflict for conflict in reported if _is_admissible(repo, conflict, checked, neighbours) ]

  # every note the run reads or writes is loaded before anything is written; a note that no longer exists is
  # skipped, and a conflict whose inner document has none is not raised
  states: dict[Path, _NoteState] = {}
  needed = { folder_note(repo / checked) }
  for conflict in conflicts:
    needed.update(folder_note(repo / doc) for doc in ( conflict.inner, *conflict.with_docs ))
  for note in sorted(needed):
    if ( state := _try_load(repo, note) ) is not None:
      states[note] = state
  for note in _find_all_marked_notes(repo):
    if note not in states:
      try:
        states[note] = _load_note(repo, note)
      except ValueError:
        continue
  conflicts = [ conflict for conflict in conflicts if folder_note(repo / conflict.inner) in states ]
  originals = _snapshot(states)

  # Domain(spec.coherence):
  # # A new check replaces everything the document said before
  # When a document is checked again, the earlier verdict about it is void. Every callout hung for it as the inner
  # document goes, and the document is taken out of every other callout that lists it. A callout left listing no
  # document at all disappears with it. Only then are the conflicts of the new check raised, so a conflict that no
  # longer holds does not outlive the check that found it.

  # the checked document's old callouts go, and so does it from every other callout's list
  for state in states.values():
    state.blocks = [ ( lines, conflict ) for lines, conflict in state.blocks
                     if conflict is None or conflict.inner != checked ]
    _drop_doc(repo, state, checked)

  # Domain(spec.coherence):
  # # One conflict callout per inner document and essence
  # A disagreement between approved documents is raised once for each inner document and each essence it concerns. The
  # callout hangs in the folder-note of the folder the inner document lives in and lists every document the inner one
  # disagrees with. Each listed document carries a mirror callout in the folder-note of its own folder, where it is
  # the inner document and the original inner document is the one listed, so that either side finds the conflict
  # from its own note. An identical callout is never hung twice in the same note.

  # every reported conflict, less its dismissed pairs, hangs in the inner note and mirrors in the others'
  hung = 0
  for conflict in conflicts:
    inner_state = states[folder_note(repo / conflict.inner)]
    with_docs = tuple(doc for doc in conflict.with_docs if not _is_dismissed(repo, inner_state, conflict.inner, doc))

    # guard: a conflict whose every pair was dismissed is not raised again
    if not with_docs:
      continue
    hung += 1
    _add(repo, inner_state, Conflict(inner = conflict.inner, with_docs = with_docs, essence = conflict.essence))
    for doc in with_docs:
      mirror = states.get(folder_note(repo / doc))
      if mirror is not None:
        _add(repo, mirror, Conflict(inner = doc, with_docs = ( conflict.inner, ), essence = conflict.essence))

  # every changed note on disk, then one commit for all of them
  touched = _write_and_commit(repo, states, originals, f"{BOT_NAME}: conflicts of {checked}")
  return { _CHECKED: checked, _NOTES: sorted(_rel(repo, note) for note in touched), _CONFLICTS: hung }


@dataclass
class _TakeDown:
  """
  The ticked callouts of one document in a note, with every note their removal reaches, held in memory.

  Attributes:
    states: The note and the mirror notes, keyed by path.
    originals: Each note's callout lines and dismissals as read, keyed by path.
    own: The note holding the ticked callouts.
    picked: The ticked callouts' blocks, in note order.
    selected: The ticked callouts' conflicts, in note order.
    others: The documents the ticked callouts list, in first-listed order.
  """

  # The note and the mirror notes, keyed by path
  states: dict[Path, _NoteState]

  # Each note's callout lines and dismissals as read, keyed by path
  originals: dict[Path, tuple]

  # The note holding the ticked callouts
  own: _NoteState

  # The ticked callouts' blocks, in note order
  picked: list[tuple[list[str], Conflict | None]]

  # The ticked callouts' conflicts, in note order
  selected: list[Conflict]

  # The documents the ticked callouts list, in first-listed order
  others: list[str]


def _take_down(repo: Path, note: Path, doc: str, ticked: re.Pattern[str]) -> _TakeDown:
  """
  Take a document's ticked callouts out of a note, in memory, with the notes of the documents they list loaded.

  Args:
    repo: The repository root.
    note: The folder-note holding the callouts.
    doc: The repo-relative inner document of the callouts.
    ticked: The pattern of the ticked box that picks a callout.

  Returns:
    The notes with the ticked callouts taken down, the mirrors not yet touched and nothing written.

  Raises:
    ValueError: If the note does not exist, has no `# Gates` section, or holds no callout for the document, a
      mirror note has no `# Gates` section, or none of the document's callouts has the box ticked (reason
      `nothing-ticked`).
  """
  states = { note: _load_note(repo, note) }
  own = states[note]
  candidates = [ block for block in own.blocks if block[1] is not None and block[1].inner == doc ]

  # guard: only a callout the note actually holds can be taken down
  if not candidates:
    raise ValueError(f"no conflict callout for {doc} in {_rel(repo, note)}")

  # only the callouts whose box the operator ticked are taken down
  picked = [ block for block in candidates if any(ticked.match(line) for line in block[0]) ]

  # guard: without a ticked box the operator asked for nothing, and nothing is taken down
  if not picked:
    raise ValueError(NOTHING_TICKED)
  selected = [ conflict for _lines, conflict in picked if conflict is not None ]

  # the other side of every pair, each note that can hold callouts loaded before anything is written
  others = list(dict.fromkeys(other for conflict in selected for other in conflict.with_docs))
  for other in others:
    path = folder_note(repo / other)
    if path not in states and ( state := _try_load(repo, path) ) is not None:
      states[path] = state
  originals = _snapshot(states)

  # the ticked callouts go from this note
  own.blocks = [ block for block in own.blocks if not any(block is chosen for chosen in picked) ]
  return _TakeDown(states = states, originals = originals, own = own, picked = picked, selected = selected,
                   others = others)


def _mirror(repo: Path, down: _TakeDown, other: str) -> _NoteState | None:
  """
  Find the loaded note of a document a taken-down callout listed.

  Args:
    repo: The repository root.
    down: The take-down in progress.
    other: The listed document.

  Returns:
    The document's note, or `None` when it has none that can hold callouts.
  """
  return down.states.get(folder_note(repo / other))


def _drop_mirrors(repo: Path, down: _TakeDown, doc: str) -> None:
  """
  Take a document out of the mirror callouts that state the essence of one of its taken-down callouts.

  Args:
    repo: The repository root.
    down: The take-down in progress.
    doc: The repo-relative inner document of the taken-down callouts.
  """
  for conflict in down.selected:
    for other in conflict.with_docs:
      # a listed document whose note is gone has no mirror to trim
      if ( mirror := _mirror(repo, down, other) ) is not None:
        _drop_doc(repo, mirror, doc, inner = other, essences = { conflict.essence })


def dismiss(repo: Path, note: Path, doc: str) -> dict:
  """
  Take down a document's ticked conflict callouts in a note and their mirrors, recording each pair as no conflict.

  Only the ticked callouts and the mirror callouts stating the same essence go; the other callouts between the same
  documents stay in both notes. The pair is nevertheless recorded as no conflict on both notes, so it is not raised
  again until either document is approved again. A mirror note that does not exist is skipped.

  Args:
    repo: The repository root.
    note: The folder-note holding the callouts.
    doc: The repo-relative inner document of the callouts.

  Returns:
    `{"notes"}`: the repo-relative notes rewritten, in sorted order.

  Raises:
    ValueError: If the note does not exist, has no `# Gates` section, or holds no callout for the document, a
      mirror note has no `# Gates` section, none of the document's callouts has its `Not a conflict` box ticked
      (reason `nothing-ticked`), or the commit failed; nothing is written then.
  """
  down = _take_down(repo, note, doc, _DISMISS_TICKED_RE)

  # each mirror loses the document only from the callouts stating the essence that was dismissed
  _drop_mirrors(repo, down, doc)

  # Domain(spec.coherence):
  # # A dismissal is recorded on both documents' notes
  # Dismissing a conflict takes down the callout that was ticked and, in the notes of the documents it listed, only the
  # mirror callouts stating the same essence; other callouts between the same documents stay. Each pair is recorded
  # as no conflict, on the notes of both documents, each from its own side, with the approvals of both documents as
  # they stood at dismissal. The record concerns the pair, whatever the essence, so the pair stays dismissed whichever
  # of the two is checked, until either one is approved again.

  # each side records the pair from its own end, with both stamps as they stand now
  stamp = _approved_at(repo, doc)
  for other in down.others:
    other_stamp = _approved_at(repo, other)
    _record(down.own, { ConflictKey.INNER: doc, ConflictKey.WITH: other, ConflictKey.INNER_APPROVED_AT: stamp,
                        ConflictKey.WITH_APPROVED_AT: other_stamp })
    if ( mirror := _mirror(repo, down, other) ) is not None:
      _record(mirror, { ConflictKey.INNER: other, ConflictKey.WITH: doc, ConflictKey.INNER_APPROVED_AT: other_stamp,
                        ConflictKey.WITH_APPROVED_AT: stamp })

  # every changed note on disk, then one commit for all of them
  touched = _write_and_commit(repo, down.states, down.originals, f"{BOT_NAME}: dismiss conflicts of {doc}")
  return { _NOTES: sorted(_rel(repo, path) for path in touched) }


def resolve(repo: Path, note: Path, doc: str) -> dict:
  """
  Take down a document's conflict callouts ticked for resolution in a note and their mirrors.

  Callouts of the document whose `Resolve here` box is not ticked stay in the note, and no pair is recorded as no
  conflict. A mirror loses the document only from the callouts stating the picked essence, and a mirror note that
  does not exist is skipped.

  Args:
    repo: The repository root.
    note: The folder-note holding the callout.
    doc: The repo-relative inner document of the callout.

  Returns:
    `{"doc", "conflicts"}`: the document and, per callout taken down in note order, its `essence` and the
    repo-relative documents it listed under `with`.

  Raises:
    ValueError: If the note does not exist, has no `# Gates` section, or holds no callout for the document, a
      mirror note has no `# Gates` section, none of the document's callouts has its `Resolve here` box ticked
      (reason `nothing-ticked`), or the commit failed; nothing is written then.
  """

  # Domain(spec.coherence):
  # # A conflict sent for resolution leaves both notes at once
  # Asking for a conflict to be resolved in a document takes down only the callouts picked for resolution, together
  # with the document's place in the mirror callouts of the documents they listed that state the same essence as a
  # picked callout; callouts left unpicked stay, and so do mirror callouts of another essence between the same pair,
  # because the disagreement they state is not the one being resolved.
  # Unlike a dismissal, nothing is recorded about the pair, so the disagreement is not declared void. The document's
  # writer receives the gist of each conflict and the documents it disagrees with, and no other document is touched;
  # when the revised document is approved, the next check raises whatever still disagrees.

  down = _take_down(repo, note, doc, _RESOLVE_TICKED_RE)

  # each mirror loses the document only from the callouts stating the essence that was picked
  _drop_mirrors(repo, down, doc)

  # every changed note on disk, then one commit for all of them
  _write_and_commit(repo, down.states, down.originals, f"{BOT_NAME}: resolve conflicts of {doc}")
  return { _DOC: doc, _CONFLICTS: [ { _ESSENCE: conflict.essence, _WITH: list(conflict.with_docs) }
                                    for conflict in down.selected ] }


def _refuse(reason: str) -> int:
  """
  Print a refusal summary.

  Args:
    reason: Why the verb refused.

  Returns:
    Exit code 1.
  """
  print(json.dumps({ _STATUS: _STATUS_REFUSED, _REASON: reason }))
  return 1


def repo_root() -> Path:
  """
  Resolve the repository root from `LAZY_REPO_ROOT`, falling back to the process working directory.

  Returns:
    The repository root.
  """
  return scaffold_asset.repo_root(Path(os.environ.get(_ENV_REPO_ROOT) or Path.cwd()))


def main_apply(argv: list[str]) -> int:
  """
  Hang a coherence check's conflicts on the folder-notes and commit them.

  Notes:
    - Prints `{"checked", "notes", "conflicts"}` on stdout, or `{"status": "refused", "reason"}` when the job is
      unreadable, its result is not a list, its request names no existing checked document, a note it reaches has
      no `# Gates` section or the commit failed, in which case nothing is written.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 when the result was applied, 1 when it was refused.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs coherence-apply")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("job_dir")
  args = parser.parse_args(argv)
  repo = repo_root()
  job_dir = Path(args.job_dir) if Path(args.job_dir).is_absolute() else repo / args.job_dir

  # the whole run, refused as one when the job or a note it reaches is unusable
  try:
    summary = apply_result(repo, job_dir)
  except ValueError as error:
    return _refuse(str(error))
  print(json.dumps(summary))
  return 0


def main_dismiss(argv: list[str]) -> int:
  """
  Take down a document's ticked conflict callouts in a note and their mirrors, recording the pairs as no conflict.

  Notes:
    - Only the ticked callouts and the mirror callouts stating the same essence go; the other callouts of the pair
      stay in both notes, while the pair is recorded as no conflict on both.
    - Prints `{"notes"}` on stdout, or `{"status": "refused", "reason"}` when the note or the callout is missing,
      none of the document's callouts is ticked (reason `nothing-ticked`), a note it reaches has no `# Gates`
      section or the commit failed, in which case nothing is written.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 when the callouts were dismissed, 1 when the request was refused.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs coherence-dismiss")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("note")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("doc")
  args = parser.parse_args(argv)
  repo = repo_root()
  note = Path(args.note) if Path(args.note).is_absolute() else repo / args.note

  # the whole dismissal, refused as one when the note, the callout or a mirror note is unusable
  try:
    summary = dismiss(repo, note, parse_doc_arg(repo, args.doc))
  except ValueError as error:
    return _refuse(str(error))
  print(json.dumps(summary))
  return 0


def main_resolve(argv: list[str]) -> int:
  """
  Take down a document's conflict callouts ticked for resolution in a note and their mirrors.

  Notes:
    - Callouts of the document whose `Resolve here` box is not ticked stay in the note.
    - Prints `{"doc", "conflicts"}` on stdout, or `{"status": "refused", "reason"}` when the note or the callout is
      missing, none of the document's callouts is ticked (reason `nothing-ticked`), a note it reaches has no
      `# Gates` section or the commit failed, in which case nothing is written.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 when the callouts were taken down, 1 when the request was refused.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs coherence-resolve")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("note")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("doc")
  args = parser.parse_args(argv)
  repo = repo_root()
  note = Path(args.note) if Path(args.note).is_absolute() else repo / args.note

  # the whole resolution, refused as one when the note, the callout or a mirror note is unusable
  try:
    summary = resolve(repo, note, parse_doc_arg(repo, args.doc))
  except ValueError as error:
    return _refuse(str(error))
  print(json.dumps(summary))
  return 0
