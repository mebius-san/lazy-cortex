"""`/lazy-review.start <file>` — open a document for review.

Single atomic commit that:

- Sets frontmatter `review_active: true`. A fresh document also gets the
  seeds `review_round: 1`, `review_approved: false`, `review_phase: main`,
  `review_main_done: []`; keys already present (for example after a
  `/lazy-review.stop`) are kept as they stand, so a start after a stop
  resumes the stopped cycle. The surgical line-edit keeps everything
  else byte-for-byte. The phase keys make the bootstrap complete: the
  coordinator's entry wake finds nothing to write and only dispatches
  the opening turn.
- Clears `review_result` if a prior finalize left it on the file —
  re-opening for review must reset the terminal apply-gate
  discriminator.
- Inserts the initial Waiting banner above the first H1.
- Appends an empty `# History` section (tagged
  `#protected/review/history`, with an HTML-comment one-line explainer in
  the vault's language under the tag) at the end of the body when the
  document does not carry one yet — the coordinator appends its
  entries into this section and never creates it itself.

The commit is made under the OPERATOR's git identity and carries no
trailer; the coordinator watch picks up the `review_active` transition,
and the review-entry trigger fires for any commit author.

Returns 0 on success, 2 when the file doesn't exist or isn't a
markdown file.
"""
from __future__ import annotations

import argparse
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
import atomic_io as _atomic_io  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import banner as _banner  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import body as _body  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_ops as _note_ops  # type: ignore # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: `plugins/claude/lazycortex-specs/bin/note_ops.py` shares this basename; in a whole-project mypy run the bare
# `import note_ops` above resolves to that unrelated module instead (this dir's `__init__.py` makes review's
# own copy package-qualified as `bin.note_ops`), so mypy checks the attribute against the wrong file's shape
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import finalize as _finalize  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
import parser as _parser  # noqa: E402  # pylint: disable=import-error,wrong-import-position,deprecated-module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from keys import LangId, Phase, ReviewKey, Tag  # noqa: E402


# The per-cycle autorun choices a review entry removes from the frontmatter.
_AUTORUN_KEYS = ( ReviewKey.SKIP_VALIDATION, ReviewKey.AUTORUN, ReviewKey.AUTORUN_CYCLES )


# comment one-liner seeded under the `# History` heading (after its owner tag) so the section
# is self-described in source without rendering; per vault language, English is the floor
_HISTORY_EXPLAINERS = {
    LangId.EN: "A log of what changed in this document during review. Kept automatically — do not edit by hand.",
    LangId.RU: "Журнал изменений документа за время ревью. Ведётся автоматически — руками не править.",
}


def _history_explainer(file_path: Path) -> str:
  """
  Render the `# History` section's explainer line for a document.

  Args:
    file_path: The document the section is being seeded on.

  Returns:
    The HTML-comment explainer line in the vault's resolved language,
    falling back to English.
  """
  # the resolver lives beside the banner writer, so start, submit, and the paint-banner verb read one chain
  # waiver: type: ignore — in a whole-project run mypy binds this bare `note_ops` to the specs
  # plugin's same-named module, which has no such attribute; at runtime it is review's own
  text = _HISTORY_EXPLAINERS.get(
      _note_ops.resolve_language(file_path)  # type: ignore[attr-defined]
  ) or _HISTORY_EXPLAINERS[LangId.EN]
  return f"<!-- {text} -->"


# an explainer is one HTML-comment line, or a legacy asterisk-italic line left by earlier
# seeders — both are replaced with the fresh comment form; any other line is content
_COMMENT_EXPLAINER_RE = re.compile(r"^<!-- .* -->\s*$")
_ITALIC_LINE_RE = re.compile(r"^\*([^*].*)\*\s*$")


def _first_sentence(text: str) -> str:
  """
  Return the first sentence of `text`, without its closing period.

  Args:
    text: Prose to cut.

  Returns:
    The text up to its first sentence break, stripped of surrounding whitespace and the period.
  """
  return text.split(". ", 1)[0].strip().rstrip(".")


# the opening sentence of every explainer ever seeded, which identifies a legacy italic explainer
_EXPLAINER_OPENINGS = frozenset(_first_sentence(text) for text in _HISTORY_EXPLAINERS.values())


def _is_explainer_line(line: str) -> bool:
  """
  Report whether `line` is a History explainer, in the comment form or the legacy italic form.

  Args:
    line: One line of the History section, its line ending removed.

  Returns:
    `True` for an HTML-comment line, or an asterisk-italic line opening with the first sentence
    of a seeded explainer; `False` for any other line, an operator's own italic note included.
  """
  if (italic := _ITALIC_LINE_RE.match(line)) is not None:
    return _first_sentence(italic.group(1)) in _EXPLAINER_OPENINGS
  return bool(_COMMENT_EXPLAINER_RE.match(line))


def _reconcile_history_explainer(body: str, explainer: str) -> str:
  """
  Insert or refresh the explainer line under the review-owned `# History` tag.

  Idempotent: an explainer line (comment form, or the legacy italic form) already sitting right under the
  `#protected/review/history` tag is replaced (stale language), any other line
  gets the explainer inserted above it, and a body without the section is returned
  unchanged.

  Args:
    body: The document body (post-frontmatter).
    explainer: The rendered `<!-- ... -->` line to end up under the tag.

  Returns:
    The body with exactly one explainer line under the History tag. Only the review-owned History
    section changes: a History example inside a code fence and every other byte of `body` stay
    as they are, and the line endings (LF or CRLF) are kept.
  """

  headings = _parser.find_all_h1_headings(body)
  for idx, (start, _match_end, _title) in enumerate(headings):
    end = headings[idx + 1][0] if idx + 1 < len(headings) else len(body)
    lines = body[start:end].splitlines(keepends = True)

    # only the review-owned History section carries the explainer
    if not _parser.is_historian_section("".join(lines[1:])):
      continue

    # the tag is the first non-blank line under the heading; the explainer goes right below it
    tag_at = next(i for i in range(1, len(lines)) if lines[i].strip())
    tag_line = lines[tag_at]
    newline = tag_line[len(tag_line.rstrip("\r\n")):] or _parser.line_ending(body)
    if not tag_line.endswith("\n"):
      lines[tag_at] = tag_line + newline
    at = tag_at + 1
    if at < len(lines) and _is_explainer_line(lines[at].rstrip("\r\n")):
      lines[at] = explainer + lines[at][len(lines[at].rstrip("\r\n")):]
    else:
      lines.insert(at, explainer + (newline if at < len(lines) or body.endswith("\n") else ""))
    return body[:start] + "".join(lines) + body[end:]
  return body


def open_review(file_path: Path, *, expert: str | None = None) -> bool:
  """
  Apply the bootstrap mutations to `file_path`.

  Guarantees:
    - An already-set review round, approval, phase, or main-writer done-list value survives
      the call unchanged; only a missing key is seeded.
    - Opening a document that still carries a prior finalize's terminal outcome clears
      `review_result` from the frontmatter and strips the terminal status callout from the body.
    - Refreshing the History explainer line touches only the review-owned `# History` section; a
      History example inside a code fence and every other byte of the body stay as they are.
    - The body's line endings, LF or CRLF, are kept.
    - Opening clears `review_skip_validation`, `review_autorun`, and `review_autorun_cycles`
      from the frontmatter, so each review cycle starts without the previous cycle's choices.

  Args:
    file_path: The markdown document to open for review; rewritten in place.
    expert: Optional per-document main-writer override; writes `review_expert` when provided.

  Returns:
    `True` if anything changed; `False` if the file was already opted-in and fully bootstrapped
    (idempotent re-run).
  """

  # Domain(review.lifecycle):
  # # Opening a document seeds the round machine once and resumes a stopped cycle
  # A document entering review for the first time is seeded with round one, the opening writer
  # phase, an empty done-list for that phase's writers, and not yet approved — the exact state
  # the coordinator's own bootstrap would produce, so its first wake has nothing left to write
  # and only dispatches the opening turn. Seeding fills only what is missing: a document that
  # already carries a round, approval, phase or done-list, such as one parked by a stop, keeps
  # them, so entering review again resumes the stopped cycle from where it was paused instead
  # of returning the document to the starting state. Re-opening a document that still carries
  # a prior finalize's terminal outcome clears that outcome everywhere it was recorded — the
  # frontmatter discriminator a downstream consumer gates on, and the landing marker shown
  # above the document's first heading — because entering review again means the outcome
  # no longer describes the document.

  # the edits run on LF text; the document's own ending comes back once, on write
  text = _atomic_io.read_text(file_path)
  new_text, ending = _atomic_io.to_lf(text)
  new_text = _fm.set_field(new_text, ReviewKey.ACTIVE, True)
  meta, _ = _fm.parse(new_text)

  # Contract:
  # An already-set `review_round`, `review_approved`, `review_phase`, or
  # `review_main_done` value survives this call unchanged; only a missing
  # key is seeded.

  # seed only the round-machine keys still missing from frontmatter
  if ReviewKey.ROUND not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.ROUND, 1)
  if ReviewKey.APPROVED not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.APPROVED, False)

  # seed the phase machinery too, so the coordinator's entry wake finds a fully
  # bootstrapped document and has nothing to commit — it only dispatches the
  # opening turn (sidecar writes are free).
  if ReviewKey.PHASE not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.PHASE, Phase.MAIN)
  if ReviewKey.MAIN_DONE not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.MAIN_DONE, [])

  # pin the cycle's edit-marker style from the repo settings — every later consumer
  # (dispatch, strip-markup, finalize) reads the pin, so a settings change mid-cycle
  # never reaches this review. An existing pin survives the idempotent re-run.
  if ReviewKey.MARKER_STYLE not in meta:
    new_text = _fm.set_field(
        new_text, ReviewKey.MARKER_STYLE, _finalize.read_settings_edit_marker_style(file_path)
    )

  # clear the terminal apply-gate discriminator if a prior finalize
  # left it on the file. Re-opening for review means the apply-gate
  # has nothing to act on yet — its trigger is the *next* finalize.
  if ReviewKey.RESULT in meta:
    new_text = _fm.unset_field(new_text, ReviewKey.RESULT)

  # drop the previous cycle's autorun and skip-validation choices: each review cycle
  # starts with the operator choosing them afresh.
  for key in _AUTORUN_KEYS:
    if key in meta:
      new_text = _fm.unset_field(new_text, key)

  # seed the per-document main-writer override when the caller names one.
  if expert:
    new_text = _fm.set_field(new_text, ReviewKey.EXPERT, expert)

  # Contract:
  # Opening a document that still carries a prior finalize's terminal outcome
  # clears `review_result` from the frontmatter and strips the terminal status
  # callout from the body.

  # re-opening a finalized doc: strip the prior cycle's `#status/<state>` landing
  # callout from body. Symmetric with the `review_result` frontmatter clear above —
  # both are terminal markers from the previous finalize and no longer apply while
  # the doc is back in active review (Bug 121).
  _, body = _fm.parse(new_text)
  fm_text = new_text[: len(new_text) - len(body)]
  body = _body.strip_status_callout(body)
  if _banner.extract(body) is None:
    # the phase in effect after the seeding block above — Phase.MAIN when it was just
    # seeded, or a stale non-main phase surviving a re-open — never the hardcoded writer
    # label, so a re-open with e.g. review_phase: validators paints the same context the
    # coordinator's own entry wake would derive, instead of repainting it right after.
    # waiver: type: ignore — a whole-project mypy run binds `note_ops` to
    # `lazycortex-specs/bin/note_ops.py`, so this review module's attributes are unknown to it
    context_label = _note_ops.waiting_context_for_phase(  # type: ignore[attr-defined]
        meta.get(ReviewKey.PHASE, Phase.MAIN),
    )
    body = _banner.replace_banner(
        body, _banner.State.IN_PROCESS,
        waiting_context = context_label,
        # waiver: type: ignore — in a whole-project run mypy binds this bare `note_ops` to the specs
        # plugin's same-named module, which has no such attribute; at runtime it is review's own
        lang = _note_ops.resolve_language(file_path),  # type: ignore[attr-defined]
    )

  # Contract:
  # Refreshing the History explainer line touches only the review-owned `# History` section;
  # a History example inside a code fence and every other byte of the body stay as they are.

  # Contract:
  # The body's line endings, LF or CRLF, are kept.

  # bootstrap the review-owned `# History` section at the end of the body. It is
  # tagged `#protected/review/history` (persistent under the protected-section
  # contract) and stays the terminal section for the document's whole life.
  if _parser.find_history(body) is None:
    body = _parser.close_open_fence(body, ending)
    if not body.endswith("\n"):
      body += "\n"
    if not body.endswith("\n\n"):
      body += "\n"
    body += "\n".join(("# History", Tag.HISTORY, _history_explainer(file_path), ""))
  else:
    # a pre-existing section gets its explainer reconciled — inserted when a document from
    # before this line existed re-enters review, replaced when the vault language changed
    body = _reconcile_history_explainer(body, _history_explainer(file_path))

  # write back with the original line endings, only when the bootstrap changed something
  new_text = _atomic_io.restore_ending(fm_text + body, ending)
  if new_text == text:
    return False
  _atomic_io.write_text_atomic(file_path, new_text)
  return True


def _atomic_commit(file_path: Path) -> None:
  """
  Commit the file under the caller's git identity with a human-shaped subject and no Doc-Review trailer.

  Args:
    file_path: Document to stage and commit; the commit carries only this file.
  """
  cwd = file_path.parent
  subprocess.run(
      ["git", "add", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )

  # the pathspec keeps a concurrently staged foreign file out of the opt-in commit
  subprocess.run(
      ["git", "commit", "-q", "-m", f"review: opt-in {file_path.name}", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )


def main(argv: list[str]) -> int:
  """
  Open a document for review from the command line.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the file does not exist or is not a markdown file.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.start")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file", type=Path)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--expert", default=None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-commit", action="store_true",
                      # waiver: argparse CLI signature, not a domain key
                      help="apply bootstrap mutations but do not commit")
  args = parser.parse_args(argv)
  file_path: Path = args.file.resolve()

  # guard: the named path is missing or is not a markdown document
  # waiver: filesystem path idiom
  if not file_path.exists() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2

  # open the review, then commit the opt-in unless the caller asked for an uncommitted run
  changed = open_review(file_path, expert=args.expert)
  if changed and not args.no_commit:
    _atomic_commit(file_path)
  print(f"opted in: {file_path} (changed={changed})")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
