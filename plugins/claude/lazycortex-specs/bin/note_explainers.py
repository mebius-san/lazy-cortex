"""
Shared HTML-comment explainer lines for generated spec-note sections.

Every bot-written section of a spec note carries one `<!-- ... -->` one-liner
under its heading, in the vault's authoring language, so the operator never has
to guess what a section means — visible in the editor, invisible in reading
view. This module owns the mechanics (idempotent insert/replace) plus the key
table for asset/container folder-note sections; `upstream_tick.py` keeps its
own upstream-note key table and reuses the mechanics. It also owns the
language-resolved templates for the narrative `# History` lines the bin
primitives land on notes, and the language-resolved footer line of a gate
callout in a folder note's `# Gates` section, for every verb that has a fixed one.
Every text itself lives in the plugin's lockit, read through `spec_lockit`; the
`lockit-text` and `lockit-keys` CLI verbs hand those texts to callers outside Python.

Asterisk-italic lines (`*...*`) — the explainers' pre-comment form — are still
recognized at the explainer slot and migrate to the comment form on the next
heal. Underscore placeholders like `_Not yet assessed by the coordinator._` are
content and stay untouched, and so is any `<!-- spec:... -->` marker comment
(`summary_render.py`'s precis/stats fences). On notes whose sections carry a
`#protected/...` owner tag the explainer sits right after the tag line, keeping
the tag the first content line as the protected-sections convention requires.
"""
from __future__ import annotations

import argparse
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
import resolve_language  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import GateCheckbox, LangId, Section  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_lockit import Lockit  # noqa: E402


# A section's owner tag line sits directly under the heading and stays the first content line
_PROTECTED_PREFIX = "#protected/"

# An explainer is exactly one line in the comment form or the legacy asterisk-italic form;
# underscore-italic placeholders are content, and so is any `<!-- spec:... -->` marker comment.
# Public: section readers (e.g. the commands-wake detector) use it to skip the explainer line.
EXPLAINER_LINE_RE = re.compile(r"^(?:\*[^*].*\*|<!--(?!\s*spec:).*-->)\s*$")

# Sections the operator writes into: an italic line or a comment right under the heading may be
# theirs, so only an explainer this plugin ships — word for word — is replaced there
OPERATOR_SECTIONS = frozenset({ Section.COORD_RULES, Section.COORD_COMMANDS })

# The lockit key of the one-liner rendered as `<!-- ... -->` under each generated section of an asset/container
# folder-note, by section heading — the note documents itself so the operator never has to guess what a section means
ASSET_EXPLAINER_KEYS: dict[str, str] = {
    Section.SUMMARY: "asset-explainer.summary",
    Section.GATES: "asset-explainer.gates",
    Section.STATUS_BRIEF: "asset-explainer.status-brief",
    Section.COORD_RULES: "asset-explainer.coordinator-rules",
    Section.COORD_COMMANDS: "asset-explainer.coordinator-commands",
    Section.HISTORY: "asset-explainer.history",
}

# Lockit key prefix of the narrative line templates the bin primitives land on notes — `# History` tails plus the
# halt callout's tail; the full key is the prefix plus a `HistoryEvent` value. The `- <date> — <author> · ` /
# `> [!failure] ` wrappers stay at the call sites (dates, bot identities, and callout marks are language-neutral).
# A key whose rendering is a substring of another key's — `HALTED_CALLOUT` under `HALTED` — is a fragment key:
# `history_fragments` renders it in every language so a caller can recognize the event in a body regardless of how
# the note was authored.
HISTORY_KEY_PREFIX = "history."

# The lockit key of the footer line of the gate callout holding the rows of one verb, by verb; a verb without an
# entry carries the hints its rows brought along
GATE_HELPER_KEYS: dict[str, str] = {
    GateCheckbox.WRITE_VERB: "gate-helper.write",
    GateCheckbox.REVIEW_VERB: "gate-helper.review",
    GateCheckbox.REVISE_VERB: "gate-helper.revise",
    GateCheckbox.START_VERB: "gate-helper.start",
    GateCheckbox.BUILD_VERB: "gate-helper.build",
    GateCheckbox.REBUILD_VERB: "gate-helper.rebuild",
    GateCheckbox.PUBLISH_VERB: "gate-helper.publish",
}

# Lockit key prefix of the `##` sub-headings the `review-rows` verb writes inside `# Gates`, one per row group; the
# full key is the prefix plus a `GateRowGroup` value
GATE_HEADING_KEY_PREFIX = "gate-heading."

# Exit code of a lockit verb that refuses its arguments — a key the lockit does not carry, a note outside the vault.
_EXIT_REFUSED = 2


def is_explainer_line(line: str, heading: str, table: dict[str, str] | None = None) -> bool:
  """
  Judge whether a line under a section heading is that section's explainer rather than content.

  Guarantees:
    - Under an operator-written heading (`# Coordinator rules`, `# Coordinator commands`), only a
      line matching one of this plugin's own explainer texts verbatim, in any language the plugin
      carries and in either the comment or the legacy italic form, counts as the explainer.
    - Under any other heading, any line matching the explainer shape counts as the explainer.

  Args:
    line: The candidate line, found directly under the heading.
    heading: The H1 heading line the candidate line sits under.
    table: The section heading to lockit key mapping whose texts are checked against under an
      operator-written heading; defaults to `ASSET_EXPLAINER_KEYS`.

  Returns:
    Whether `line` is the section's explainer rather than operator-written or generated content.
  """
  # outside an operator-written section any line of the explainer shape is one
  if heading not in OPERATOR_SECTIONS:
    return bool(EXPLAINER_LINE_RE.match(line))

  # an operator-written section only gives up a line this plugin wrote, in any language and either form
  keys = ( ASSET_EXPLAINER_KEYS if table is None else table ).values()
  texts = { Lockit.text(key, lang) for key in keys for lang in LangId }
  return line.strip() in { form for text in texts for form in ( f"<!-- {text} -->", f"*{text}*" ) }


def explainer_text(heading: str, lang: str, table: dict[str, str]) -> str | None:
  """
  Look up a section heading's explainer text, falling back to English.

  Args:
    heading: The H1 heading line (e.g. `# Gates`).
    lang: The vault's authoring language.
    table: The section heading to lockit key mapping to read.

  Returns:
    The explainer text, or None when the heading has no entry in the table.

  Raises:
    KeyError: If the table names a lockit key the English strings do not carry.
  """
  # guard: a heading the table does not name has no explainer
  if (key := table.get(heading)) is None:
    return None
  return Lockit.text(key, lang)


def with_explainer(section: str, lang: str, table: dict[str, str]) -> str:
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
    table: The section heading to lockit key mapping to read.

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
    body: str, lang: str, table: dict[str, str] | None = None,
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
    table: The section heading to lockit key mapping; defaults to `ASSET_EXPLAINER_KEYS`.

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

  keys = ASSET_EXPLAINER_KEYS if table is None else table
  lines = spec_frontmatter.split_lines(body)
  idx = 0

  # a fenced code block may quote a section heading verbatim — never write inside one; the mask
  # is taken once, and each insertion below shifts it along with the lines
  fenced = spec_frontmatter.fenced_lines(lines)
  while idx < len(lines):
    heading = lines[idx].strip()
    note = None if fenced[idx] else explainer_text(heading, lang, keys)

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
    if insert_at < len(lines) and is_explainer_line(lines[insert_at], heading, keys):
      lines[insert_at] = f"<!-- {note} -->"
    else:
      lines.insert(insert_at, f"<!-- {note} -->")
      fenced.insert(insert_at, False)

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
    lang: The authoring language tag; a language with no text for the event falls back to English.
    key: The event key, a `HistoryEvent` value.
    fields: Named values substituted into the template's placeholders.

  Returns:
    The rendered line tail (the part after the `· ` separator).

  Raises:
    KeyError: If the lockit carries no text for the event key, or `fields` lacks a placeholder the text names.
  """
  # unknown languages land on the English floor, exactly like the explainer lines
  return Lockit.text(HISTORY_KEY_PREFIX + key, lang).format(**fields)


def history_line(note_path: Path, key: str, **fields: str) -> str:
  """
  Render one narrative `# History` line tail in the note's authoring language.

  Args:
    note_path: The note file the line will be appended to.
    key: The event key, a `HistoryEvent` value.
    fields: Named values substituted into the template's placeholders.

  Returns:
    The rendered line tail (the part after the `· ` separator).

  Raises:
    KeyError: If the lockit carries no text for the event key, or `fields` lacks a placeholder the text names.
  """
  return history_line_for_lang(lang_for_note(note_path), key, **fields)


def history_fragments(key: str, **fields: str) -> list[str]:
  """
  Render one event key's dedup fragment in every language the plugin carries texts in.

  A caller greps a note body with every returned variant so an event recorded under a
  previous authoring language still counts as recorded.

  Guarantees:
    - One fragment is returned per language `LangId` names, in `LangId` order, so scanning with
      the returned fragments recognizes an event recorded under any authoring language the plugin
      writes in.
    - Every event key must carry its own text in every language `LangId` names: a key missing one
      language yields the English fragment a second time, and events recorded in that language go
      unrecognized, silently, by the callers that scan for them.

  Args:
    key: The event key, a `HistoryEvent` value (typically a fragment key).
    fields: Named values substituted into the template's placeholders.

  Returns:
    The rendered fragments, one per language the plugin carries texts in, in `LangId` order.

  Raises:
    KeyError: If the lockit carries no text for the event key, or `fields` lacks a placeholder the text names.
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
  # The function returns one fragment per language `LangId` names, in `LangId` order, so a body
  # scanned with the returned fragments recognizes an event recorded under any authoring language
  # the plugin writes in.
  # Every event key MUST carry its own text in every language `LangId` names: the lockit falls
  # back to English for a key a language's file lacks, so a key missing one language yields the
  # English fragment a second time, and events recorded in that language go unrecognized, silently,
  # by the callers that scan for them.

  # render the key's template in each language the plugin carries texts in
  return [ Lockit.text(HISTORY_KEY_PREFIX + key, lang).format(**fields) for lang in LangId ]


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
  fm_end = spec_frontmatter.block(text)[1]
  return text[:fm_end] + ensure_explainers(text[fm_end:], lang_for_note(note_path))


def gate_helper_text(verb: str, lang: str) -> str | None:
  """
  Give the fixed footer line of the gate callout holding the rows of one verb.

  Args:
    verb: The verb the callout's rows share, as the labels write it.
    lang: The note's authoring language; a language with no text falls back to English.

  Returns:
    The footer line, or None for a verb that has no fixed one.
  """
  # guard: a verb outside the fixed set carries the hints its rows brought along
  if (key := GATE_HELPER_KEYS.get(verb)) is None:
    return None
  return Lockit.text(key, lang)


def gate_heading_text(group: str, lang: str) -> str:
  """
  Give the `##` sub-heading of one row group of a `# Gates` section.

  Args:
    group: One of the `GateRowGroup` values.
    lang: The note's authoring language; a language with no text falls back to English.

  Returns:
    The heading line.

  Raises:
    KeyError: If `group` is not a row group the lockit carries a heading for.
  """
  return Lockit.text(GATE_HEADING_KEY_PREFIX + group, lang)


def gate_heading_texts() -> set[str]:
  """
  Give the `##` sub-heading of every row group of a `# Gates` section in every language.

  Returns:
    The heading lines of every group, in every language the plugin carries texts in.
  """
  # the groups are whatever the lockit carries a heading for, so a new group needs no second list here
  return {
      Lockit.text(key, lang)
      for key in Lockit.load_keys() if key.startswith(GATE_HEADING_KEY_PREFIX) for lang in LangId
  }


def main_lockit_text(argv: list[str]) -> int:
  """
  Print one fixed text of the plugin from the command line.

  Notes:
    - The language is `--lang` when given, else the one resolved for the `--note` note, else the repository's.
    - A refused request prints nothing to stdout and a refusal line naming the key or the note to stderr.
    - A request is refused for a key the lockit does not carry, or for an absolute `--note` path outside the vault.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code 0 when the text was printed, 2 when the request is refused.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs lockit-text")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("key")
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag
      "--lang", default = None,
      # waiver: one-off human-facing message -- argparse help text
      help = "language code of the text (default: the note's language, else the repo's)",
  )
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag
      "--note", default = None,
      # waiver: one-off human-facing message -- argparse help text
      help = "note the text is meant for; its resolved language is used when --lang is absent",
  )
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag + vault-root default
      "--cwd", type = Path, default = None,
      # waiver: one-off human-facing message -- argparse help text
      help = "vault root holding .claude/lazy.settings.json (default: cwd)",
  )
  args = parser.parse_args(argv)

  # an explicit language wins; then the note's own resolved language; then the repo's
  vault: Path = (args.cwd or Path.cwd()).resolve()
  lang: str | None = args.lang

  # guard: no explicit language given — fall back to the one resolved for the note the text is meant for
  if lang is None and args.note is not None:
    note = Path(args.note)

    # guard: an absolute note path outside the vault has no language to resolve — refused on stderr
    if note.is_absolute() and not note.resolve().is_relative_to(vault):
      sys.stderr.write(f"note is outside the vault: {args.note}\n")
      return _EXIT_REFUSED
    lang = resolve_language.resolve_spec_language(
        vault, str(note.resolve().relative_to(vault) if note.is_absolute() else note))

  # guard: neither a language nor a note given — fall back to the repository's language
  if lang is None:
    lang = resolve_language.resolve_repo_language(vault)

  # a key the lockit does not carry is refused on stderr, with nothing printed
  try:
    print(Lockit.text(args.key, lang))
  except KeyError:
    sys.stderr.write(f"unknown lockit key: {args.key}\n")
    return _EXIT_REFUSED
  return 0


def main_lockit_keys(argv: list[str]) -> int:
  """
  Print every key of the plugin's fixed texts from the command line.

  Notes:
    - Prints one key per line, sorted.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code 0.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  argparse.ArgumentParser(prog = "lazycortex-specs lockit-keys").parse_args(argv)
  print("\n".join(Lockit.load_keys()))
  return 0
