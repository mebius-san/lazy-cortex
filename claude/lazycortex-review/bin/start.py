"""`/lazy-review.start <file>` — open a document for review.

Single atomic commit that:

- Sets frontmatter `review_active: true`, `review_round: 1`,
  `review_approved: false`, `review_phase: main`,
  `review_main_done: []` (only the keys that are missing or wrong;
  the surgical line-edit keeps everything else byte-for-byte). The
  phase keys make the bootstrap complete: the coordinator's entry
  wake finds nothing to write and only dispatches the opening turn.
- Clears `review_result` if a prior finalize left it on the file —
  re-opening for review must reset the terminal apply-gate
  discriminator.
- Inserts the initial Waiting banner above the first H1.
- Appends an empty `# History` section (tagged
  `#protected/review/history`, with an italic one-line explainer in
  the vault's language under the tag) at the end of the body when the
  document does not carry one yet — the coordinator appends its
  entries into this section and never creates it itself.

The commit is made under the OPERATOR's git identity (no Doc-Review
trailer) so the dispatcher's next tick sees a "human commit" and
runs its first historian noop / writer dispatch.

Returns 0 on success, 2 when the file doesn't exist or isn't a
markdown file.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# deferred imports below module code; position intentional (ruff E402 noqa guards it)
# `import parser` below is the local sibling parser.py, not the removed stdlib `parser` module
# pylint: disable=import-error,wrong-import-position,deprecated-module

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
import banner as _banner  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import body as _body  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_ops as _note_ops  # type: ignore # noqa: E402
# waiver: `claude/lazycortex-specs/bin/note_ops.py` shares this basename; in a whole-project mypy run the bare
# `import note_ops` above resolves to that unrelated module instead (this dir's `__init__.py` makes review's
# own copy package-qualified as `bin.note_ops`), so mypy checks the attribute against the wrong file's shape
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import parser as _parser  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import Phase, ReviewKey, Tag  # noqa: E402


_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_REVIEW_SECTION = "review"
_LANGUAGE_KEY = "language"
_LANG_EN = "en"

# italic one-liner seeded under the `# History` heading (after its owner tag) so the operator
# never has to guess what the section is; per vault language, English is the floor
_HISTORY_EXPLAINERS = {
    _LANG_EN: "A log of what changed in this document during review. Kept automatically — do not edit by hand.",
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    "ru": "Журнал изменений документа за время ревью. Ведётся автоматически — руками не править.",  # noqa: RUF001
}


def _resolve_language(file_path: Path) -> str:
  """
  Resolve the explainer language for a document from the vault settings.

  Walks up from the document to the nearest `.claude/lazy.settings.json` and
  returns the first non-empty value among `review.language`, the top-level
  `language` key, and the floor `en`.

  Args:
    file_path: The document the language is resolved for.

  Returns:
    The resolved language tag; `en` when no settings file is found or readable.
  """
  # walk up to the nearest settings root; a doc outside any vault keeps the floor
  settings = None
  for cand in file_path.resolve().parents:
    candidate = cand / _SETTINGS_REL
    if candidate.is_file():
      try:
        settings = json.loads(candidate.read_text())
      except (OSError, json.JSONDecodeError):
        settings = None
      break
  # guard: no settings file, or an unreadable one — English is the shipped floor
  if not isinstance(settings, dict):
    return _LANG_EN

  # first the plugin's own key, then the repo-wide default
  review = settings.get(_REVIEW_SECTION)
  plugin_lang = review.get(_LANGUAGE_KEY) if isinstance(review, dict) else None
  root_lang = settings.get(_LANGUAGE_KEY)
  for value in (plugin_lang, root_lang):
    if isinstance(value, str) and value:
      return value
  return _LANG_EN


def _history_explainer(file_path: Path) -> str:
  """
  Render the `# History` section's explainer line for a document.

  Args:
    file_path: The document the section is being seeded on.

  Returns:
    The asterisk-italic explainer line in the vault's resolved language,
    falling back to English.
  """
  text = _HISTORY_EXPLAINERS.get(_resolve_language(file_path)) or _HISTORY_EXPLAINERS[_LANG_EN]
  return f"*{text}*"


# an explainer is exactly one asterisk-italic line; underscore-italic lines are content
_EXPLAINER_LINE_RE = re.compile(r"^\*[^*].*\*\s*$")


def _reconcile_history_explainer(body: str, explainer: str) -> str:
  """
  Insert or refresh the explainer line under an existing `# History` tag.

  Idempotent: an asterisk-italic line already sitting right under the
  `#protected/review/history` tag is replaced (stale language), any other line
  gets the explainer inserted above it, and a body without the tag is returned
  unchanged.

  Args:
    body: The document body (post-frontmatter).
    explainer: The rendered `*...*` line to end up under the tag.

  Returns:
    The body with exactly one explainer line under the History tag.
  """
  lines = body.splitlines()
  # guard: no tag line — nothing to reconcile against
  if Tag.HISTORY not in lines:
    return body
  at = lines.index(Tag.HISTORY) + 1
  if at < len(lines) and _EXPLAINER_LINE_RE.match(lines[at]):
    lines[at] = explainer
  else:
    lines.insert(at, explainer)
  return "\n".join(lines) + ("\n" if body.endswith("\n") else "")


def open_review(file_path: Path, *, expert: str | None = None) -> bool:
  """
  Apply the bootstrap mutations to `file_path`.

  Returns:
    `True` if anything changed; `False` if the file was already opted-in and fully bootstrapped
    (idempotent re-run).
  """
  text = file_path.read_text()
  new_text = text
  new_text = _fm.set_field(new_text, ReviewKey.ACTIVE, True)
  meta, _ = _fm.parse(new_text)
  if ReviewKey.ROUND not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.ROUND, 1)
  if ReviewKey.APPROVED not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.APPROVED, False)
# Seed the phase machinery too, so the coordinator's entry wake finds a fully
# bootstrapped document and has nothing to commit — it only dispatches the
# opening turn (sidecar writes are free).
  if ReviewKey.PHASE not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.PHASE, Phase.MAIN)
  if ReviewKey.MAIN_DONE not in meta:
    new_text = _fm.set_field(new_text, ReviewKey.MAIN_DONE, [])
# Clear the terminal apply-gate discriminator if a prior finalize
# left it on the file. Re-opening for review means the apply-gate
# has nothing to act on yet — its trigger is the *next* finalize.
  if ReviewKey.RESULT in meta:
    new_text = _fm.unset_field(new_text, ReviewKey.RESULT)
  if expert:
    new_text = _fm.set_field(new_text, ReviewKey.EXPERT, expert)
# Re-opening a finalized doc: strip the prior cycle's `#status/<state>` landing
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
    effective_phase = meta.get(ReviewKey.PHASE, Phase.MAIN)
    # waiver: type: ignore — note_ops is a deferred/late-bound sibling import; mypy cannot resolve it
    context_label = _note_ops.waiting_context_for_phase(effective_phase)  # type: ignore[attr-defined]
    body = _banner.replace_banner(
        body, _banner.State.IN_PROCESS,
        waiting_context = context_label,
    )

# Bootstrap the review-owned `# History` section at the end of the body. It is
# tagged `#protected/review/history` (persistent under the protected-section
# contract) and stays the terminal section for the document's whole life.
  if _parser.find_history(body) is None:
    if not body.endswith("\n"):
      body += "\n"
    if not body.endswith("\n\n"):
      body += "\n"
    body += f"# History\n{Tag.HISTORY}\n{_history_explainer(file_path)}\n"
  else:
    # a pre-existing section gets its explainer reconciled — inserted when a document from
    # before this line existed re-enters review, replaced when the vault language changed
    body = _reconcile_history_explainer(body, _history_explainer(file_path))
  new_text = fm_text + body
  if new_text == text:
    return False
  file_path.write_text(new_text)
  return True


def _atomic_commit(file_path: Path) -> None:
  """Stage the file and commit under the caller's git identity with
    a human-shaped subject (no Doc-Review trailer)."""
  cwd = file_path.parent
  subprocess.run(
      ["git", "add", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )
  subprocess.run(
      ["git", "commit", "-q", "-m", f"review: opt-in {file_path.name}"],
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
  # waiver: filesystem path idiom
  if not file_path.exists() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2
  changed = open_review(file_path, expert=args.expert)
  if changed and not args.no_commit:
    _atomic_commit(file_path)
  print(f"opted in: {file_path} (changed={changed})")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
