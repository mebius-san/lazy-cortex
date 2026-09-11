"""Shared HTML-comment explainer lines for generated spec-note sections.

Every bot-written section of a spec note carries one `<!-- ... -->` one-liner
under its heading, in the vault's authoring language, so the operator never has
to guess what a section means — visible in the editor, invisible in reading
view. This module owns the mechanics (idempotent insert/replace) plus the text
table for asset/container folder-note sections; `upstream_tick.py` keeps its
own upstream-note table and reuses the mechanics. It also owns the
language-resolved templates for the narrative `# History` lines the bin
primitives land on notes.

Asterisk-italic lines (`*...*`) — the explainers' pre-comment form — are still
recognized at the explainer slot and migrate to the comment form on the next
heal. Underscore placeholders like `_Not yet assessed by the coordinator._` are
content and stay untouched, and so is any `<!-- spec:... -->` marker comment
(`summary_render.py`'s precis/stats fences). On notes whose sections carry a
`#protected/...` owner tag the explainer sits right after the tag line, keeping
the tag the first content line as the protected-sections convention requires.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_language  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import HistoryEvent, Section  # noqa: E402


LANG_EN = "en"
LANG_RU = "ru"

# a section's owner tag line sits directly under the heading and stays the first content line
_PROTECTED_PREFIX = "#protected/"

# an explainer is exactly one line in the comment form or the legacy asterisk-italic form;
# underscore-italic placeholders are content, and so is any `<!-- spec:... -->` marker comment.
# Public: section readers (e.g. the commands-wake detector) use it to skip the explainer line.
EXPLAINER_LINE_RE = re.compile(r"^(?:\*[^*].*\*|<!--(?!\s*spec:).*-->)\s*$")

# one-liners rendered as `<!-- ... -->` under the generated sections of asset/container
# folder-notes — the note documents itself so the operator never has to guess what a section means
# waiver: the RU lines carry `# noqa: RUF001` — Cyrillic in Russian UI strings is the content,
# not a lookalike-character typo; the checker cannot distinguish deliberate Russian text
ASSET_EXPLAINERS: dict[tuple[str, str], str] = {
    (Section.SUMMARY, LANG_EN): "A short description. Updated automatically — do not edit by hand.",
    (Section.SUMMARY, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Краткое описание. Обновляется автоматически — руками не править.",  # noqa: RUF001
    (Section.GATES, LANG_EN): "Work stages. Tick an item — the next stage starts on its own.",
    (Section.GATES, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Этапы работы. Отметьте пункт — следующий этап начнётся сам.",  # noqa: RUF001
    (Section.STATUS_BRIEF, LANG_EN): "What is happening now and what comes next. Written automatically.",
    (Section.STATUS_BRIEF, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Что сейчас происходит и что будет дальше. Пишется автоматически.",  # noqa: RUF001
    (Section.COORD_RULES, LANG_EN):
        "Your standing instructions for the automation. Write here freely — it takes them into account.",
    (Section.COORD_RULES, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Ваши постоянные указания для автоматики. Пишите сюда свободно — она их учитывает.",  # noqa: RUF001
    (Section.COORD_COMMANDS, LANG_EN):
        "A one-off instruction: write it here — it will be carried out, and the outcome moves to # History.",
    (Section.COORD_COMMANDS, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Разовое поручение: напишите здесь — оно будет выполнено, а итог переедет в # History.",  # noqa: RUF001
    (Section.HISTORY, LANG_EN): "What has already happened. Filled in automatically.",
    (Section.HISTORY, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Что уже произошло. Заполняется автоматически.",  # noqa: RUF001
}

# narrative line templates the bin primitives land on notes — `# History` tails plus the halt
# callout's tail — keyed by event and language; the `- <date> — <author> · ` / `> [!failure] `
# wrappers stay at the call sites (dates, bot identities, and callout marks are
# language-neutral). The `*-scan` keys are the dedup fragments `gate_tick`'s sweeps grep a
# body for, bound to their written counterparts by `history_fragments`'s Contract.
# waiver: the RU lines carry `# noqa: RUF001` — Cyrillic in Russian UI strings is the content,
# not a lookalike-character typo; the checker cannot distinguish deliberate Russian text
HISTORY_LINES: dict[tuple[str, str], str] = {
    (HistoryEvent.SCAFFOLDED, LANG_EN): "scaffolded {asset_type} '{slug}' under {product}",
    (HistoryEvent.SCAFFOLDED, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "создан каркас {asset_type} '{slug}' под {product}",  # noqa: RUF001
    (HistoryEvent.HALTED, LANG_EN): "{reason} — asset halted",
    (HistoryEvent.HALTED, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "{reason} — ассет остановлен",  # noqa: RUF001
    (HistoryEvent.HALTED_CALLOUT, LANG_EN): "asset halted: {reason}",
    (HistoryEvent.HALTED_CALLOUT, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "ассет остановлен: {reason}",  # noqa: RUF001
    (HistoryEvent.JOB_DONE, LANG_EN): "job {job_id} ({label}) done",
    (HistoryEvent.JOB_DONE, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "job {job_id} ({label}) завершён",  # noqa: RUF001
    (HistoryEvent.JOB_DONE_SCAN, LANG_EN): "({label}) done",
    (HistoryEvent.JOB_DONE_SCAN, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "({label}) завершён",  # noqa: RUF001
    (HistoryEvent.JOB_CANCELLED, LANG_EN): "job {job_id} ({label}) cancelled",
    (HistoryEvent.JOB_CANCELLED, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "job {job_id} ({label}) отменён",  # noqa: RUF001
    (HistoryEvent.JOB_DEAD, LANG_EN):
        "WARNING: coordinator job {job_id} ({trigger}) died — cleared the coordinator-job marker, "
        "asset NOT halted; a pending operator edit, if any, survives for the next genuine wake",
    (HistoryEvent.JOB_DEAD, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "WARNING: координаторский job {job_id} ({trigger}) умер — маркер coordinator-job снят, "  # noqa: RUF001
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "ассет НЕ остановлен; незавершённая правка оператора, если была, доживёт до следующего "  # noqa: RUF001
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "настоящего пробуждения",  # noqa: RUF001
    (HistoryEvent.REVIEW_OPENED, LANG_EN): "opened review on {doc} (stuck-draft backstop)",
    (HistoryEvent.REVIEW_OPENED, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "открыто ревью на {doc} (страховка stuck-draft)",  # noqa: RUF001
    (HistoryEvent.REVIEW_OPENED_SCAN, LANG_EN): "opened review on {doc}",
    (HistoryEvent.REVIEW_OPENED_SCAN, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "открыто ревью на {doc}",  # noqa: RUF001
    (HistoryEvent.REQUEST_PROCESSED, LANG_EN): "request [[{wikilink}]] accepted → processed",
    (HistoryEvent.REQUEST_PROCESSED, LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "запрос [[{wikilink}]] принят → обработан",  # noqa: RUF001
}


def explainer_text(heading: str, lang: str, table: dict[tuple[str, str], str]) -> str | None:
  """
  Look up a section heading's explainer text, falling back to English per line.

  Args:
    heading: The H1 heading line (e.g. `# Gates`).
    lang: The vault's authoring language.
    table: The `(heading, lang) -> text` table to read.

  Returns:
    The explainer text, or None when the heading has no entry in any language.
  """
  return table.get((heading, lang)) or table.get((heading, LANG_EN))


def with_explainer(section: str, lang: str, table: dict[tuple[str, str], str]) -> str:
  """
  Insert a rendered section's comment explainer line right under its heading.

  Idempotent: an explainer already present under the heading (any language or
  form, from a prior render) is replaced rather than stacked.

  Guarantees:
    - An explainer already present under the heading — in any language or form, from a prior
      render — is replaced rather than stacked, so calling this function again on its own
      output never leaves more than one explainer line under the heading.

  Args:
    section: A rendered section — heading line plus body.
    lang: The vault's authoring language; falls back to English per line.
    table: The `(heading, lang) -> text` table to read.

  Returns:
    The section with exactly one explainer line under the heading, or unchanged
    when no explainer is defined for its heading.
  """

  # Contract:
  # An explainer already present under the heading — in any language or form, from a prior
  # render — is replaced rather than stacked; calling this function again on its own output
  # never leaves more than one explainer line under the heading.

  heading, _, rest = section.partition("\n")
  note = explainer_text(heading, lang, table)
  # guard: a heading without a defined explainer renders exactly as before
  if not note:
    return section
  # replace a previous render's explainer — comment or legacy italic — instead of stacking one
  first, _, remainder = rest.partition("\n")
  if EXPLAINER_LINE_RE.match(first):
    rest = remainder
  return f"{heading}\n<!-- {note} -->\n{rest}"


def ensure_explainers(
    body: str, lang: str, table: dict[tuple[str, str], str] | None = None,
) -> str:
  """
  Insert or refresh the explainer line under every known section of a note body.

  Idempotent whole-body healer: for each heading present in `body` and known to
  `table`, exactly one `<!-- ... -->` line ends up under the heading — after the
  section's `#protected/...` owner tag when one is present, so the tag stays the
  first content line. A line at that spot matching the explainer shape — any
  non-`spec:` HTML comment, or the legacy asterisk-italic form — is replaced;
  any other line (underscore-italic placeholders, `<!-- spec:... -->` marker
  comments, plain prose) is left in place and the explainer is inserted above
  it.

  Guarantees:
    - For every heading in `body` known to `table`, exactly one explainer line ends up
      directly under it — after the section's `#protected/...` owner tag when one is present —
      so calling this function again on its own output never accumulates more than one
      explainer line per heading.

  Args:
    body: The note body text (post-frontmatter).
    lang: The vault's authoring language; falls back to English per line.
    table: The `(heading, lang) -> text` table; defaults to `ASSET_EXPLAINERS`.

  Returns:
    The body with explainer lines in place; unchanged when no known heading is
    present.
  """

  # Domain(spec.notes):
  # # Self-documenting generated sections
  # Every section an automation writes into an asset's note carries one short line directly under
  # its heading, explaining in plain language what the section is for and, where relevant, that it
  # is filled in automatically. This lets someone reading the note understand a generated section
  # without having to already know the system that produces it, while staying out of the way of
  # the rendered document — the line is written in a form that shows in the source but not in the
  # rendered page, so it never clutters what is actually read day to day. A note carrying an older,
  # plainly-visible form of the same explanation from earlier tooling has that older line replaced
  # the next time the section is regenerated, so a note never accumulates more than one explanation
  # per section. When a section is itself claimed by another automation as territory it alone may
  # rewrite, the explanation still applies to it but is placed after that claim, never before it.

  # Contract:
  # For every heading in `body` known to `table`, exactly one explainer line ends up directly
  # under it — placed after a `#protected/...` owner tag when the section carries one — so
  # calling this function again on its own output never accumulates more than one explainer
  # line per heading.

  texts = ASSET_EXPLAINERS if table is None else table
  lines = body.splitlines()
  idx = 0
  in_fence = False
  while idx < len(lines):
    # a fenced code block may quote a section heading verbatim — never write inside one
    if lines[idx].lstrip().startswith("```"):
      in_fence = not in_fence
      idx += 1
      continue
    note = None if in_fence else explainer_text(lines[idx].strip(), lang, texts)
    # guard: not a known section heading — keep scanning
    if note is None:
      idx += 1
      continue
    # the explainer sits after the owner tag when the section carries one
    insert_at = idx + 1
    if insert_at < len(lines) and lines[insert_at].startswith(_PROTECTED_PREFIX):
      insert_at += 1
    # replace a line wearing the explainer shape — any non-`spec:` HTML comment, or a legacy
    # italic render; anything else (an underscore placeholder, a `spec:` marker comment,
    # operator prose) is content and the explainer is inserted above it instead
    if insert_at < len(lines) and EXPLAINER_LINE_RE.match(lines[insert_at]):
      lines[insert_at] = f"<!-- {note} -->"
    else:
      lines.insert(insert_at, f"<!-- {note} -->")
    # resume past the line just written so the scan never re-reads its own output
    idx = insert_at + 1
  return "\n".join(lines) + ("\n" if body.endswith("\n") else "")


def lang_for_note(note_path: Path) -> str:
  """
  Resolve the authoring language for a note through the spec language chain.

  Walks up from the note to the nearest settings root (`.claude/lazy.settings.json`),
  then runs the standard fallback chain (doc frontmatter, owning product,
  settings default, English floor).

  Args:
    note_path: The note file the language is resolved for.

  Returns:
    The resolved language tag; `en` when no settings root is found above the note.
  """
  # limit: re-resolved per note write (settings walk + config reads); memoise per settings
  # root if vault-wide reconcile passes ever grow slow enough to matter
  vault = spec_paths.find_settings_root(note_path.resolve().parent)
  return resolve_language.resolve_spec_language(vault, str(note_path.resolve().relative_to(vault)))


def history_line_for_lang(lang: str, key: str, **fields: str) -> str:
  """
  Render one narrative `# History` line tail for an explicit language.

  Args:
    lang: The authoring language tag; unknown tags fall back to English.
    key: The event key in `HISTORY_LINES`.
    fields: Named values substituted into the template's placeholders.

  Returns:
    The rendered line tail (the part after the `· ` separator).
  """
  # unknown languages land on the English floor, exactly like the explainer tables
  template = HISTORY_LINES.get((key, lang)) or HISTORY_LINES[(key, LANG_EN)]
  return template.format(**fields)


def history_line(note_path: Path, key: str, **fields: str) -> str:
  """
  Render one narrative `# History` line tail in the note's authoring language.

  Args:
    note_path: The note file the line will be appended to.
    key: The event key in `HISTORY_LINES`.
    fields: Named values substituted into the template's placeholders.

  Returns:
    The rendered line tail (the part after the `· ` separator).
  """
  return history_line_for_lang(lang_for_note(note_path), key, **fields)


def history_fragments(key: str, **fields: str) -> list[str]:
  """
  Render one event key's dedup fragment in every language the table ships.

  A sweep greps a note body with every returned variant so an event recorded under a
  previous authoring language still counts as recorded.

  Guarantees:
    - Every `*-scan` key's template stays a substring of its written counterpart's rendering in
      every language the table ships, so scanning with the returned fragments recognizes an
      event recorded under any authoring language.

  Args:
    key: The event key in `HISTORY_LINES` (typically a `*-scan` key).
    fields: Named values substituted into the template's placeholders.

  Returns:
    The rendered fragments, one per language carrying the key, in table order.
  """

  # Domain(spec.notes):
  # # Multi-language history narration
  # Every automatic step an asset goes through is written into its permanent history as one line
  # of plain narration, in whichever language that particular note is authored in. Because
  # different notes in the same catalog can be authored in different languages, and a note's own
  # authoring language can change over its life, a later check asking "was this event already
  # recorded" must recognize the record regardless of which language it happened to be written in,
  # not only whichever language is currently in force for the note.

  # Contract:
  # Every `*-scan` key's template MUST stay a substring of its written counterpart's rendering
  # in every language the table ships, so a body scanned with the returned fragments recognizes
  # an event recorded under any authoring language; violating this silently makes recorded
  # events unrecognizable to the dedup sweeps.

  # render the key's template in each language carrying it, in table order
  return [template.format(**fields)
          for (event_key, _), template in HISTORY_LINES.items() if event_key == key]


def heal_note_text(note_path: Path, text: str) -> str:
  """
  Refresh the explainer lines of a full folder-note text before it is written.

  Convenience wrapper for write sites that hold `frontmatter + body` as one
  string: the frontmatter block is split off untouched and the body is run
  through `ensure_explainers` in the note's resolved language.

  Guarantees:
    - The frontmatter block is returned byte-for-byte unchanged; only the body below it is
      run through the explainer healer.

  Args:
    note_path: The note file the text is about to be written to.
    text: The full note text (frontmatter plus body).

  Returns:
    The text with explainer lines in place under every known section heading.
  """

  # Contract:
  # The frontmatter block — from the opening `---` fence through its closing `---` line — is
  # returned byte-for-byte unchanged; only the body below it is modified.

  # split the frontmatter off so heading scans never look inside it
  fm_end = 0
  if text.startswith("---\n"):
    close = text.find("\n---\n", 4)
    if close >= 0:
      # waiver: magic literal 5 -- length of the '\n---\n' closing fence just located
      fm_end = close + 5
  return text[:fm_end] + ensure_explainers(text[fm_end:], lang_for_note(note_path))
