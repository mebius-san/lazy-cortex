"""Strip / reassemble document parts for agent dispatch.

This module is half of the ownership-isolation contract — together
with :mod:`reapply`. The agent never sees more of the document than
its role permits, and the dispatcher mechanically restores anything
the agent should not have edited.

Strip side (dispatch → agent):

- :func:`strip_for_main_writer` — keep frontmatter + content-only
  body. Drop banner, every owned section, `# History`, approve
  checkbox.
- :func:`strip_for_section_writer` — same, but preserve the writer's
  own owned section if it exists.

Reassemble side (agent → dispatcher):

- :func:`reassemble` — graft the agent's reply onto the operator's
  current state per role rules:
  * `phase="main"` — body comes from agent; owned meta-sections,
    history, banner come from operator.
  * `phase="section"` — body comes from operator (UNCHANGED — any
    agent body edit ignored); ONLY the writer's owned section is
    taken from the agent.

Reserved frontmatter keys (`review_active` / `review_round` /
`review_approved`) are silently dropped from any agent overlay.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# pylint: disable=import-error,deprecated-module

import re

import frontmatter as _fm
import parser as _parser
from keys import Phase, Position, Tag

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Mapping, Sequence


# ----------------------------------------------------------- internals


# Strip block: banner + any trailing blank lines. All 4 banner-state
# tags from spec § Top banner: in-process / action-needed / ready /
# concerns-decision.
_BANNER_BLOCK_RE = re.compile(
    r"(?ms)"
    r"^>\s*\[!\w+\][^\n]*"
    r"#review/(?:in-process|action-needed|ready|concerns-decision|finalizing)"
    r"[^\n]*\n"
    r"(?:>[^\n]*\n)*"
    r"(?:\n)*"
)

_H1_RE = re.compile(r"^# (.+?)\s*$", re.MULTILINE)

# Obsidian-style single-line hashtag: `#` followed by an alphanumeric
# tag path (letters, digits, `_`, `-`, `/`). Excludes markdown ATX
# heading markers (`## Heading`, `### Sub`) — those have a space
# after the `#`s and therefore do not match. The first char after `#`
# must be a letter (Obsidian's tag rule).
_TAG_LINE_RE = re.compile(r"^#[A-Za-z][\w/\-]*$")


def _strip_banner(body: str) -> str:
  """
  Remove the top banner callout block from `body`.

  Returns:
    `body` with the leading banner block removed, or `body` unchanged when no banner is present.
  """
  return _BANNER_BLOCK_RE.sub("", body, count=1)


def _enumerate_h1_spans(body: str) -> list[tuple[int, int, str, str]]:
  """
  Return a list of span tuples for each H1 section in `body`.

  Returns:
    List of `(start, end, title, heading_line)` tuples where `end` is the start of the next H1
    or `len(body)`.
  """
  matches = list(_H1_RE.finditer(body))
  spans: list[tuple[int, int, str, str]] = []
  for i, m in enumerate(matches):
    start = m.start()
    line_end = body.find("\n", m.end())
    heading_line = body[start:line_end if line_end != -1 else len(body)]
    end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
    spans.append((start, end, m.group(1).strip(), heading_line))
  return spans


def _owner_of_section(section_body: str) -> tuple[str, str] | None:
  """
  Parse the ownership tag from the first non-empty line of `section_body`.

  Only the 2-part `#expert/<flat_name>/<section_id>` form qualifies as identifiable ownership —
  used when a specific section writer's section must be addressed by owner identity (e.g. for
  the section-writer reapply path and `section_layout` position lookup).

  To test whether a section is foreign-owned and must be preserved through a main-writer round,
  use the broader tag predicate that recognises any tag-on-first-content-line marker, not just
  the 2-part `#expert/...` form. Spec inv 8 — main writer protects every tagged H1 section
  regardless of who put the tag.

  Returns:
    `(flat_name, section_id)` when the first non-empty line is a well-formed 2-part ownership
    tag, or `None` when no tag line is found or the tag is malformed.
  """
  for line in section_body.split("\n"):
    stripped = line.strip()
    # guard: leading blank lines aren't the tag line; skip to the first non-empty content line.
    if not stripped:
      continue
    # guard: first content line lacking the #expert/ prefix means no ownership tag — bail.
    if not stripped.startswith(Tag.EXPERT_PREFIX):
      return None
    rest = stripped[len(Tag.EXPERT_PREFIX):].strip()
    parts = rest.split("/")
    # guard: a well-formed ownership tag is exactly 2 slash-parts; anything else is malformed.
    if len(parts) != 2:
      return None
    flat_name, section_id = parts[0].strip(), parts[1].strip()
    # guard: both parts must be non-empty for a valid owner; an empty half is malformed.
    if not flat_name or not section_id:
      return None
    return (flat_name, section_id)
  return None


def _section_is_tagged(section_body: str) -> bool:
  """
  Report whether the section's first non-empty content line is an Obsidian-style single-line
  hashtag (`#expert/...`, `#review/...`, `#protected/...`, `#consumer/<...>`, etc.).

  Tagged H1 sections belong to someone other than the main writer (a validation writer, a
  terminal writer, a protected cross-plugin section, a downstream consumer's overlay) and the
  main writer's reapply must not drop or rewrite them. Spec inv 8.

  Notes:
    - Only single-line Obsidian tags qualify. ATX heading markers (`## Premise`, `### Sub`)
      are excluded because they always have whitespace between the hashes and the text
      (Bug 69 — the prior form matched any `#`-leading line and caused section duplication
      in the reassembly pipeline).

  Returns:
    `True` when the first non-empty content line is a single-line Obsidian hashtag,
    `False` otherwise.
  """
  for line in section_body.split("\n"):
    stripped = line.strip()
    # guard: leading blank lines aren't the tag line; skip to the first non-empty content line.
    if not stripped:
      continue
    return bool(_TAG_LINE_RE.match(stripped))
  return False


def _drop_sections(
    body: str,
    *,
    drop_owned: bool,
    drop_history: bool,
    keep_owner: tuple[str, str] | None = None,
) -> str:
  """
  Walk `body` H1 sections and remove those that match the policy.

  When `drop_owned` is `True`, any section whose first non-empty content line is a tag
  (spec inv 8) is removed, except when its 2-part owner equals `keep_owner`. This covers
  any foreign-owned overlay — they are not "main writer's body". When `drop_history` is
  `True`, the `# History` section
  (titled exactly `History`, with or without an ownership tag) is also removed.

  Returns:
    `body` with the matching H1 sections removed; preamble content before the first H1
    is always preserved.
  """
  spans = _enumerate_h1_spans(body)
  if not spans:
    return body
  keep_ranges: list[tuple[int, int]] = []
  # Preamble (anything before first H1) always kept.
  if spans[0][0] > 0:
    keep_ranges.append((0, spans[0][0]))
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    section_body_only = section_text[len(_heading_line_for(start, end, body)):]
    owner = _owner_of_section(section_body_only)
    tagged = _section_is_tagged(section_body_only)
    # guard: under drop_history policy, the # History section is removed (not kept) — skip appending it.
    if drop_history and _parser.is_historian_section(section_body_only):
      continue
    # guard: under drop_owned policy, foreign-owned tagged sections are removed; the kept owner is exempt.
    if drop_owned and tagged and owner != keep_owner:
      continue
    keep_ranges.append((start, end))
  return "".join(body[s:e] for s, e in keep_ranges)


def _heading_line_for(start: int, end: int, body: str) -> str:
  """
  Return the heading line (including its newline terminator) for the H1 section at `[start, end)`.

  Returns:
    The heading line text including the trailing newline, or the entire range when no newline
    exists within the span.
  """
  line_end = body.find("\n", start)
  if line_end == -1 or line_end >= end:
    return body[start:end]
  return body[start:line_end + 1]


# Approve-checkbox lines inside the ready banner. Already covered by
# banner-block stripping above, but kept as a safety net when a stale
# checkbox sits outside a banner. Covers both the clean-approve form
# and the "approve with concerns" escape (Bug 44).
_APPROVE_LINE_RE = re.compile(
    r"^>\s*-\s*\[[ x]\]\s*approve(?:\s+the\s+whole\s+document|\s+with\s+concerns)[^\n]*$",
    re.MULTILINE | re.IGNORECASE,
)


# -------------------------------------------------------------- strip api


def strip_for_main_writer(text: str) -> str:
  """
  Strip `text` to the content-only view for main-writer dispatch per spec § Stage 2.

  Returns:
    The full text with frontmatter preserved and the body reduced to operator-authored
    content — banner, owned sections, approve checkbox, and history removed.
  """
  _meta, body = _fm.parse(text)
  frontmatter_text = text[: len(text) - len(body)]
  body = _strip_banner(body)
  body = _APPROVE_LINE_RE.sub("", body)
  body = _drop_sections(body, drop_owned=True, drop_history=True)
  return frontmatter_text + body


def strip_for_section_writer(text: str, *, owner: tuple[str, str]) -> str:
  """
  Strip `text` to the section-writer view, preserving `owner`'s own section.

  Applies the same strip as main-writer dispatch, but keeps the section already owned by
  `owner` when it exists in the document. `owner` is the `(flat_name, section_id)` pair.

  Returns:
    The full text with frontmatter preserved and the body stripped of all owned sections
    except `owner`'s, plus banner, approve checkbox, and history removed.
  """
  _meta, body = _fm.parse(text)
  frontmatter_text = text[: len(text) - len(body)]
  body = _strip_banner(body)
  body = _APPROVE_LINE_RE.sub("", body)
  body = _drop_sections(
      body, drop_owned=True, drop_history=True, keep_owner=owner,
  )
  return frontmatter_text + body


# ------------------------------------------------------- reassemble api


def _extract_section_by_owner(body: str, owner: tuple[str, str]) -> str | None:
  """
  Extract the full text of the H1 section owned by `owner`.

  Returns:
    The section text from the heading line through the next H1 or EOF, or `None` when no
    section with that owner exists.
  """
  spans = _enumerate_h1_spans(body)
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    heading_len = len(_heading_line_for(start, end, body))
    owner_pair = _owner_of_section(section_text[heading_len:])
    if owner_pair == owner:
      return section_text
  return None


def _extract_section_by_flat_name(body: str, flat_name: str) -> str | None:
  """
  Extract the full text of the H1 section whose owner flat-name matches `flat_name`.

  Does not require the caller to know the section-id — useful for gate predicates that only
  carry the flat expert name.

  Returns:
    The section text from heading through next H1 or EOF, or `None` when no matching section
    exists.
  """
  spans = _enumerate_h1_spans(body)
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    heading_len = len(_heading_line_for(start, end, body))
    owner_pair = _owner_of_section(section_text[heading_len:])
    if owner_pair is not None and owner_pair[0] == flat_name:
      return section_text
  return None


def section_content_for_owner(body: str, owner: tuple[str, str]) -> str | None:
  """
  Return the markdown body of `owner`'s owned H1 section with the heading line and the
  ownership-tag line stripped.

  Used by callers that need to inspect the section content apart from scaffolding — e.g.
  the state-machine probe for `any_post_approve_section_non_empty` and the main-writer
  payload builder (Phase 3b, `concerns.content`).

  Returns:
    The section content with heading and ownership-tag lines removed, or `None` when no
    such section exists.
  """
  section_text = _extract_section_by_owner(body, owner)
  if section_text is None:
    return None
  heading_line = _heading_line_for(0, len(section_text), section_text)
  rest = section_text[len(heading_line):]
  # Strip the leading ownership tag line. Tag may sit on the first
  # non-empty line; preserve blank lines around it for the caller's
  # whitespace check (see `section_has_substance`).
  lines = rest.split("\n")
  out_lines: list[str] = []
  tag_consumed = False
  for line in lines:
    if not tag_consumed and line.strip().startswith(Tag.EXPERT_PREFIX):
      tag_consumed = True
      continue
    out_lines.append(line)
  return "\n".join(out_lines)


def section_has_substance(body: str, owner: tuple[str, str]) -> bool:
  """
  Report whether `owner`'s owned section in `body` contains any non-whitespace content beyond
  the H1 heading and the ownership-tag line.

  Used by the state-machine probe to decide whether a post-approve section is non-empty.

  Returns:
    `True` when the section exists and has non-whitespace content; `False` otherwise.
  """
  content = section_content_for_owner(body, owner)
  if content is None:
    return False
  return any(line.strip() for line in content.split("\n"))


_APPROVE_MARKER_RE = __import__("re").compile(
    r"^>\s*\[!check\]\s+No concerns\s*$",
    __import__("re").MULTILINE,
)


def section_has_concerns(body: str, owner: tuple[str, str]) -> bool:
  """
  Report whether `owner`'s owned section contains content beyond scaffolding.

  Scaffolding consists of the H1 heading, the ownership-tag line, and the approve-marker
  callout `> [!check] No concerns` (spec invariant 6). The approve marker is auto-inserted
  when a section-writer returns `outcome=empty` or an empty result file (spec invariant 12)
  — it signals "no concerns" and must not count as substance for state-machine gating,
  otherwise `any_post_approve_section_non_empty` and the validation-round bump predicate
  trigger spuriously on conceptually empty responses.

  Returns:
    `True` when the section exists and contains non-whitespace content beyond scaffolding;
    `False` otherwise.
  """
  content = section_content_for_owner(body, owner)
  if content is None:
    return False
  stripped = _APPROVE_MARKER_RE.sub("", content)
  return any(line.strip() for line in stripped.split("\n"))


def remove_owned_section(body: str, owner: tuple[str, str]) -> str:
  """
  Remove `owner`'s owned H1 section from `body` entirely.

  Removes the heading, ownership tag, substance, and trailing blank line, leaving all
  surrounding sections intact. Used by the dispatcher to consume a post-approve validation
  section once a main writer has lifted its findings into actionable `[!question]
  #review/question` callouts in the body — without this step, `section_has_substance` would
  keep returning `True` and `any_post_approve_section_non_empty` would trigger a fresh
  revert-to-main on every re-approve, looping forever. A pending writer's next dispatch
  re-creates the section from scratch; the pre-existing shell was previously visible as
  cosmetic noise (Bug 42).

  Returns:
    `body` with the owned section removed, or `body` unchanged when `owner` does not own
    any section.
  """
  spans = _enumerate_h1_spans(body)
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    heading_line = _heading_line_for(start, end, body)
    owner_pair = _owner_of_section(section_text[len(heading_line):])
    # guard: only the target owner's section is dropped; skip every other section.
    if owner_pair != owner:
      continue
  # Drop the section span entirely. The H1 spans returned by
  # `_enumerate_h1_spans` include the trailing blank gap before
  # the next H1, so cutting [start, end) leaves no orphan blank
  # line behind. Surrounding sections shift up by exactly the
  # section's byte length.
    return body[:start] + body[end:]
  return body


def replace_owned_section_body(
    body: str, owner: tuple[str, str], new_body: str,
) -> str:
  """
  Replace the body of `owner`'s owned H1 section with `new_body`.

  Preserves the heading line and the ownership-tag line; replaces everything below them
  with `new_body`. Used by the dispatcher's mechanical clear-validation-section step
  (Bug 73): after a validator's concerns have been forwarded and lifted by the main writer
  into `[!question]` callouts in the body, the source validation section is spent and its
  body is replaced with the deterministic approve-marker (spec inv 12), preserving heading
  and ownership tag so the next validator dispatch finds an empty section to write into
  rather than a stale concerns blob.

  `new_body` is the literal replacement content; the caller is responsible for any trailing
  newline handling. A single blank line is inserted between the ownership tag and `new_body`
  to match the canonical section shape.

  Returns:
    `body` with the owned section's content replaced, or `body` unchanged when `owner` does
    not own any section.
  """
  spans = _enumerate_h1_spans(body)
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    heading_line = _heading_line_for(start, end, body)
    owner_pair = _owner_of_section(section_text[len(heading_line):])
    # guard: only the target owner's section has its tag line stripped; skip every other section.
    if owner_pair != owner:
      continue
  # Find the ownership-tag line: should be the first non-empty
  # line after the heading.
    lines = section_text.splitlines(keepends=True)
    head_lines: list[str] = []
    i = 0
    if i < len(lines):
      head_lines.append(lines[i])  # heading
      i += 1
  # Walk blanks until we find the tag line.
    while i < len(lines) and lines[i].strip() == "":
      head_lines.append(lines[i])
      i += 1
    if i < len(lines):
      head_lines.append(lines[i])  # ownership tag
      i += 1
  # Preserve any trailing blank lines from the section's tail
  # (the trailing blank gap before the next H1 that the span
  # includes — see `_enumerate_h1_spans`).
    tail_blanks: list[str] = []
    j = len(lines) - 1
    while j >= i and lines[j].strip() == "":
      tail_blanks.insert(0, lines[j])
      j -= 1
    stripped = new_body.strip("\n")
    new_section = "".join(head_lines)
    if stripped:
      if new_section and not new_section.endswith("\n"):
        new_section += "\n"
      new_section += "\n" + stripped + "\n"
    new_section += "".join(tail_blanks)
    return body[:start] + new_section + body[end:]
  return body


def rewrite_section_h1(body: str, owner: tuple[str, str], canonical_title: str) -> str:
  """
  Replace the H1 heading of the section owned by `owner` with `# <canonical_title>`.

  The section body under the heading line is preserved verbatim.

  Returns:
    `body` with the owned section's H1 heading replaced, or `body` unchanged when no
    section with that owner exists.
  """
  spans = _enumerate_h1_spans(body)
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    heading_line = _heading_line_for(start, end, body)
    owner_pair = _owner_of_section(section_text[len(heading_line):])
    # guard: only the target owner's section gets its heading rewritten; skip every other section.
    if owner_pair != owner:
      continue
    new_heading = f"# {canonical_title}\n"
    rest = section_text[len(heading_line):]
    return body[:start] + new_heading + rest + body[end:]
  return body


_STATUS_CALLOUT_BLOCK_RE = re.compile(
    r"(?ms)^>\s*\[![\w-]+\][^\n]*#status/[\w-]+[^\n]*\n(?:>[^\n]*\n)*(?:\n)*"
)


def strip_status_callout(body: str) -> str:
  """
  Remove the top-of-body `#status/<state>` callout block when present.

  Used when re-opening a previously-finalized document for a fresh review cycle: the
  prior cycle's terminal landing-marker is no longer applicable while the doc is back in
  active review. Mirrors the frontmatter side of the re-open (clearing `review_result`)
  on the body side. Idempotent: a body without a `#status/<x>` callout is returned
  unchanged.

  Returns:
    `body` with the leading `#status/<state>` callout block removed and any leading
    blank lines normalised.
  """
  return _STATUS_CALLOUT_BLOCK_RE.sub("", body, count = 1).lstrip("\n")


def upsert_status_callout(
    body: str,
    *,
    state: str,
    marker: str,
    title: str,
    body_lines: Sequence[str] = (),
) -> str:
  """
  Place or replace the terminal-state status callout at the top of `body`.

  The callout is placed above the first H1 with exactly one blank line of separation. It
  carries a `#status/<state>` tag in its own namespace, not under `#review/<x>`: the
  finalize-time system-callout strip removes `#review/` callouts only, so the status
  record survives as the terminal artifact the operator sees on opening a finalized
  document. The namespace is also intentionally generic because consumer apply transitions
  (e.g. setting `accepted` / `rejected` / `spawned`) write into the same callout slot —
  those values are not review-internal scaffolding.

  Idempotent: any existing `#status/<x>` callout block at the top of `body` is removed
  before the new one is inserted.

  Returns:
    `body` with the status callout inserted or replaced at the top.
  """
  body_no_old = _STATUS_CALLOUT_BLOCK_RE.sub("", body, count=1).lstrip("\n")
  head = f"> [!{marker}] {title} #status/{state}"
  extras = [f"> {line}" for line in body_lines]
  callout = "\n".join([head, *extras]) + "\n"
  return callout + "\n" + body_no_old


def strip_owned_h1_sections(
    body: str,
    *,
    preserve_section_ids: set[str] | None = None,
) -> str:
  """
  Remove every owned H1 section from `body`, keeping unowned sections and `# History`.

  `# History` is always kept even if it carries an ownership tag. Sections without an
  ownership tag are kept. `preserve_section_ids` is an optional set of section-ids (the
  second component of the ownership tag); sections whose section-id appears in the set
  survive the strip. Spec § Stage 7: terminal section-ids are always preserved; validation
  section-ids only when `review_approved_with_concerns: true`. The caller assembles the
  set. Used at finalize so post-approve validation sections and pre-approve section-writer
  artefacts are removed, leaving only operator-authored prose and `# History`.

  Returns:
    `body` with owned H1 sections removed according to the policy.
  """
  preserve_section_ids = preserve_section_ids or set()
  spans = _enumerate_h1_spans(body)
  if not spans:
    return body
  keep_ranges: list[tuple[int, int]] = []
  if spans[0][0] > 0:
    keep_ranges.append((0, spans[0][0]))
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    heading_len = len(_heading_line_for(start, end, body))
    if _parser.is_historian_section(section_text[heading_len:]):
      keep_ranges.append((start, end))
      continue
    owner = _owner_of_section(section_text[heading_len:])
    # owner is (flat_name, section_id); preserve check is on section_id
    # per spec § Stage 7 (preserve-set keyed by section-id, since
    # section-id is unique across both umbrellas — see § review-class
    # configuration).
    # guard: drop owned sections whose section-id is absent from the preserve-set; only kept owners survive the trim.
    if owner is not None and owner[1] not in preserve_section_ids:
      continue
    keep_ranges.append((start, end))
  return "".join(body[s:e] for s, e in keep_ranges)


def strip_ownership_tag(body: str, *, section_ids: set[str]) -> str:
  """
  Remove the ownership-tag line from every owned H1 section whose section-id is in
  `section_ids`, keeping the H1 heading and all section content.

  Used at finalize-with-concerns so preserved validator sections survive as plain prose
  rather than as review-owned sections carrying a dangling expert tag (Bug 88). The heading
  and body below the head-pair are preserved verbatim; a single blank line separates the
  heading from the kept content. Sections whose section-id is not in the set are untouched.

  Returns:
    `body` with the ownership-tag lines removed from matching sections, or `body` unchanged
    when `section_ids` is empty or nothing matches.
  """
  if not section_ids:
    return body
  spans = _enumerate_h1_spans(body)
  if not spans:
    return body
  out: list[str] = []
  cursor = 0
  for start, end, _title, _heading in spans:
    out.append(body[cursor:start])
    cursor = end
    section_text = body[start:end]
    heading_line = _heading_line_for(start, end, body)
    owner_pair = _owner_of_section(section_text[len(heading_line):])
    if owner_pair is None or owner_pair[1] not in section_ids:
      out.append(section_text)
      continue
    lines = section_text.splitlines(keepends=True)
    # head-pair = [H1 line, optional blanks, ownership-tag line]; drop
    # the tag line, keep the heading + everything below it.
    i = 0
    if i < len(lines):
      i += 1  # H1 heading line
    head = "".join(lines[:i])
    while i < len(lines) and lines[i].strip() == "":
      i += 1  # blanks between heading and tag (rare)
    if i < len(lines):
      i += 1  # the ownership-tag line — dropped
    rest = "".join(lines[i:])
    if rest and not rest.startswith("\n"):
      head += "\n"
    out.append(head + rest)
  out.append(body[cursor:])
  return "".join(out)


def _extract_history_section(body: str) -> str | None:
  """
  Extract the full text of the `# History` section from `body`.

  Returns:
    The historian section text from its heading through the next H1 or EOF, or `None` when
    no historian section exists in `body`.
  """
  spans = _enumerate_h1_spans(body)
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    heading_len = len(_heading_line_for(start, end, body))
    if _parser.is_historian_section(section_text[heading_len:]):
      return section_text
  return None


_REVIEW_CALLOUT_BLOCK_RE = re.compile(
    r"(?ms)^>\s*\[![\w-]+\][^\n]*#review/[\w-]+[^\n]*\n(?:>[^\n]*\n)*"
)


_BANNER_CALLOUT_BLOCK_RE = re.compile(
    r"(?ms)^>\s*\[![\w-]+\][^\n]*"
    r"#review/(?:in-process|action-needed|ready|concerns-decision)"
    r"[^\n]*\n(?:>[^\n]*\n)*"
)


def strip_banner_callouts(body: str) -> str:
  """
  Remove banner-state callouts from `body`.

  Removes only `#review/in-process`, `#review/action-needed`, `#review/ready`, and
  `#review/concerns-decision` callouts. Used by the historian-dispatch gate so the
  historian receives body content stripped of banner-state scaffolding and narrates
  substance only. Writer-authored `[!question]` and `[!attention]` callouts are substance
  and are preserved.

  Returns:
    `body` with banner-state callout blocks removed.
  """
  return _BANNER_CALLOUT_BLOCK_RE.sub("", body)


def strip_review_callouts(body: str) -> str:
  """
  Remove every `#review/<x>`-tagged callout block from `body`.

  Used by the historian-comparison gate: a body diff that consists only of system-callout
  additions or removals must not be treated as a content change.

  Returns:
    `body` with all `#review/<x>`-tagged callout blocks removed.
  """
  return _REVIEW_CALLOUT_BLOCK_RE.sub("", body)


# Inert H1 placeholder that stands in for a lifted `#protected/...` section while the
# body-wide finalize strips run. An untagged H1 owns its own span, so strip_owned_h1_sections
# keeps it (owner is None); no strip matches its text, so it round-trips byte-for-byte.
_PROTECTED_PLACEHOLDER = "# LAZY-REVIEW-PROTECTED-PLACEHOLDER-{idx}"


def _section_is_protected(section_body: str) -> bool:
  """
  Report whether the section's first non-empty content line is a `#protected/` owner tag.

  Args:
    section_body: Section text below its H1 heading line.

  Returns:
    True when the first non-empty line starts with the `#protected/` prefix, False otherwise.
  """
  for line in section_body.split("\n"):
    stripped = line.strip()
    # guard: skip leading blank lines before the first content line
    if not stripped:
      continue
    return stripped.startswith(Tag.PROTECTED_PREFIX)
  return False


def split_out_protected_sections(body: str) -> tuple[str, list[str]]:
  """
  Replace every `#protected/<owner>/...` H1 section with an inert placeholder H1.

  A protected section is foreign-owned by another plugin (e.g. the wiki's `# See also`
  block) and must survive finalize byte-for-byte, including any HTML markers inside it that
  the body-wide `strip_markers` pass would otherwise eat. Lifting each such section out to a
  placeholder before those passes, then restoring it afterwards (see
  :func:`restore_protected_sections`), keeps the section intact while the passes still clean
  the rest of the body.

  Args:
    body: Document body (without frontmatter) to scan for protected sections.

  Returns:
    A tuple of the body with each protected section replaced by a placeholder H1 line, and
    the ordered list of original section texts (list index = placeholder index).
  """
  spans = _enumerate_h1_spans(body)
  # guard: no H1 sections — nothing protected to lift
  if not spans:
    return body, []
  out: list[str] = []
  saved: list[str] = []
  cursor = 0
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    heading_len = len(_heading_line_for(start, end, body))
    # guard: not a protected section — leave it for the normal passes
    if not _section_is_protected(section_text[heading_len:]):
      continue
    out.append(body[cursor:start])
    out.append(_PROTECTED_PLACEHOLDER.format(idx=len(saved)) + "\n")
    saved.append(section_text)
    cursor = end
  out.append(body[cursor:])
  return "".join(out), saved


def restore_protected_sections(body: str, saved: list[str]) -> str:
  """
  Swap each placeholder H1 back to its original `#protected/...` section text.

  Inverse of :func:`split_out_protected_sections`: the placeholder lines are inert through
  every finalize pass, so each is still present and is replaced verbatim by the section it
  stood in for.

  Args:
    body: Body carrying the placeholder H1 lines produced by `split_out_protected_sections`.
    saved: The ordered original section texts (list index = placeholder index).

  Returns:
    The body with every placeholder restored to its original protected section.
  """
  for idx, section_text in enumerate(saved):
    body = body.replace(_PROTECTED_PLACEHOLDER.format(idx=idx) + "\n", section_text, 1)
  return body


def _apply_frontmatter_overlay(
    frontmatter_text: str,
    overlay: Mapping[str, object],
) -> str:
  """
  Apply `overlay` keys to `frontmatter_text`.

  The caller allowlist-filters the overlay per expert
  (`review.classes[].experts.*.frontmatter_keys`) before passing it here, so every key
  in `overlay` is applied unconditionally.

  Returns:
    The updated frontmatter text with all overlay keys written in.
  """
  full = frontmatter_text  # already contains fences
  for key, value in overlay.items():
    full = _fm.set_field(full, key, value)
  return full


def _strip_owned_meta_and_history(body: str) -> str:
  """
  Remove the banner, all owned sections, and history from `body`.

  Returns:
    `body` stripped of banner, approve-checkbox lines, owned H1 sections, and `# History`.
  """
  body = _strip_banner(body)
  body = _APPROVE_LINE_RE.sub("", body)
  return _drop_sections(body, drop_owned=True, drop_history=True)


def reassemble(
    *,
    operator_text: str,
    agent_body: str,
    phase: str,
    agent_frontmatter_overlay: Mapping[str, object],
    owned_owner: tuple[str, str] | None = None,
    section_layout: dict[tuple[str, str], str] | None = None,
) -> str:
  """
  Splice the agent's reply onto the operator state per phase rules.

  `phase` is one of `'main'`, `'section'`, or `'final'` — the pipeline category of the
  writer. It is NOT the section-group label (`'routing'` etc.); that is a separate concept
  owned by state-machine routing tables. `owned_owner` is the `(flat_name, section_id)`
  pair required when `phase='section'`. `section_layout` is an optional map of
  `(flat_name, section_id)` to `"top"` or `"bottom"`: top-positioned sections are placed
  before the operator's free body; bottom-positioned (and unmapped) sections are placed
  after it, before `# History`.

  Returns:
    The reassembled document text with the agent's contribution grafted onto the operator
    state per the phase rules.
  """
  _op_meta, op_body = _fm.parse(operator_text)
  op_fm_text = operator_text[: len(operator_text) - len(op_body)]

  # Always apply the (filtered) frontmatter overlay on top of operator's.
  new_fm_text = _apply_frontmatter_overlay(op_fm_text, agent_frontmatter_overlay)

  if phase == Phase.MAIN:
    return _reassemble_main(op_body, agent_body, new_fm_text, section_layout=section_layout)
  if phase == Phase.SECTION:
    # guard: section-phase reassembly is meaningless without an owner to target; reject the malformed call.
    if owned_owner is None:
      raise ValueError("reassemble(phase='section') requires owned_owner")
    return _reassemble_section(
        op_body, agent_body, new_fm_text, owned_owner, section_layout=section_layout,
    )
  raise ValueError(f"unknown reassemble phase: {phase!r}")


# ---------------------------------------------------- per-role reassemble


def _restore_owned_and_history(
    operator_body: str,
    new_content_body: str,
    *,
    skip_owner: tuple[str, str] | None = None,
    section_layout: dict[tuple[str, str], str] | None = None,
) -> str:
  """
  Append all operator-side owned sections and the history section onto `new_content_body`.

  `# History` is always the terminal section. When `section_layout` is provided, owned
  sections are split into two groups by position: `"top"` sections are prepended to
  `new_content_body` (between the status callout or banner and the operator's free body);
  `"bottom"` sections are appended after it, before `# History`. When `section_layout` is
  `None` or a given owner is absent from the map, the section defaults to `"bottom"`.

  Returns:
    The assembled body with top-positioned sections, `new_content_body`, bottom-positioned
    sections, and `# History` joined in order.
  """
  top_parts: list[str] = []
  bottom_parts: list[str] = []
  spans = _enumerate_h1_spans(operator_body)
  history_section: str | None = None
  for start, end, _title, _heading in spans:
    section_text = operator_body[start:end]
    heading_len = len(_heading_line_for(start, end, operator_body))
    section_body_only = section_text[heading_len:]
    owner = _owner_of_section(section_body_only)
    tagged = _section_is_tagged(section_body_only)
    if _parser.is_historian_section(section_body_only):
      history_section = section_text
      continue
  # Spec inv 8: preserve EVERY tagged H1 section (any tag), not
  # only 2-part #expert/<flat>/<section-id>. Downstream consumer
  # overlays may carry other prefixes. All foreign to the main writer.
    # guard: only foreign-owned tagged sections get re-placed; skip untagged main-writer body and the caller's own section.
    if not tagged or owner == skip_owner:
      continue
    position = (section_layout or {}).get(owner, Position.BOTTOM) if owner else Position.BOTTOM
    if position == Position.TOP:
      top_parts.append(section_text)
    else:
      bottom_parts.append(section_text)
  parts: list[str] = []
  for chunk in top_parts:
    if not parts:
      parts.append(chunk)
    else:
      parts.append(_ensure_leading_blank(parts[-1], chunk))
  if parts:
    parts.append(_ensure_leading_blank(parts[-1], new_content_body))
  else:
    parts.append(new_content_body)
  for chunk in bottom_parts:
    parts.append(_ensure_leading_blank(parts[-1], chunk))
  if history_section is not None:
    parts.append(_ensure_leading_blank(parts[-1], history_section))
  return "".join(parts)


def _ensure_leading_blank(prev_chunk: str, next_chunk: str) -> str:
  """
  Return `next_chunk` with a blank-line separator prepended when `prev_chunk` does not
  already end with one.

  Returns:
    `next_chunk` unchanged when `prev_chunk` ends with a blank line or is empty; otherwise
    `next_chunk` prefixed with the necessary newlines to produce one blank line of separation.
  """
  if prev_chunk.endswith("\n\n") or prev_chunk == "":
    return next_chunk
  if prev_chunk.endswith("\n"):
    return "\n" + next_chunk
  return "\n\n" + next_chunk


def _carry_banner_from_operator(operator_body: str, new_body: str) -> str:
  """
  Restore the operator's top banner above `new_body`'s first H1.

  The state machine repaints the banner separately on its own tick; this function
  preserves whatever banner was already in place so the body is never left banner-less
  mid-tick. Normalizes trailing blank lines to exactly one blank line between the banner
  and the following content, preventing layout drift across rounds (Bug 30 part a).

  Returns:
    `new_body` with the operator's banner prepended and normalized, or `new_body` unchanged
    when the operator body carries no banner.
  """
  head = ""
  # Find the banner block at the very top of operator_body.
  m = _BANNER_BLOCK_RE.match(operator_body)
  if m is not None:
    head = m.group(0)
  if not head:
    return new_body
# Normalize: strip all trailing newlines, then re-attach exactly one
# trailing newline + one blank-line separator.
  head = head.rstrip("\n") + "\n\n"
  # Strip any banner already in new_body to avoid duplication.
  new_body_no_banner = _strip_banner(new_body).lstrip("\n")
  return head + new_body_no_banner


def _document_title_heading(body: str) -> str | None:
  """Return the heading line of the document's title.

    The title is the first H1 that is neither the historian's `# History`
    section nor an expert-owned section — that is, the document headline
    the operator authored. Returns None when the body carries no such H1.

    Args:
      body: Document body (post-frontmatter) to inspect.

    Returns:
      The title heading line without its trailing newline, or None.
    """
  spans = _enumerate_h1_spans(body)
  for start, end, _title, _heading in spans:
    section_text = body[start:end]
    heading_line = _heading_line_for(start, end, body)
    section_body_only = section_text[len(heading_line):]
    # guard: the historian's # History section is not the title
    if _parser.is_historian_section(section_body_only):
      continue
  # guard: expert-owned sections are not the title
    if _owner_of_section(section_body_only) is not None:
      continue
    return heading_line.rstrip("\n")
  return None


def _carry_title_from_operator(operator_body: str, new_content: str) -> str:
  """Restore the document title onto `new_content` when the main writer
    dropped it.

    The title H1 is the document's identity, not writer-editable content; a
    writer that omits it must not silently delete it from the document
    (Bug 105 — a dropped title left the banner-placement logic anchoring on
    `# History` and parking the banner at the bottom). No-op when the
    writer kept a title H1, or when the operator body itself has none.

    Args:
      operator_body: The operator-anchored base the writer edited from.
      new_content: The writer's content body, owned sections and history
        already stripped.

    Returns:
      `new_content` with the operator's title re-anchored at the top when
      the writer dropped it, otherwise `new_content` unchanged.
    """
  op_title = _document_title_heading(operator_body)
  # guard: operator body carries no title H1 — nothing to restore
  if op_title is None:
    return new_content
# guard: writer kept a title H1 — leave its content untouched
  if _document_title_heading(new_content) is not None:
    return new_content
  return op_title + "\n\n" + new_content.lstrip("\n")


def _reassemble_main(
    operator_body: str,
    agent_body: str,
    new_fm_text: str,
    *,
    section_layout: dict[tuple[str, str], str] | None = None,
) -> str:
  """
  Reassemble a main-writer round: agent content is authoritative, operator scaffolding is
  restored.

  Returns:
    The reassembled document text with the new frontmatter, agent content body, restored
    operator owned sections and history, and the operator's banner.
  """
  # 1. Agent's content body is authoritative for user content.
  new_content = _strip_owned_meta_and_history(agent_body)
  # 1b. Restore the document title if the writer dropped it (Bug 105).
  new_content = _carry_title_from_operator(operator_body, new_content)
  # 2. Restore operator's owned sections + history.
  rebuilt = _restore_owned_and_history(operator_body, new_content, section_layout=section_layout)
  # 3. Restore the operator's banner anchor (state machine repaints
  #    separately).
  rebuilt = _carry_banner_from_operator(operator_body, rebuilt)
  return new_fm_text + rebuilt


def _reassemble_section(
    operator_body: str,
    agent_body: str,
    new_fm_text: str,
    owned_owner: tuple[str, str],
    *,
    section_layout: dict[tuple[str, str], str] | None = None,
) -> str:
  """
  Reassemble a section-writer round: operator body is authoritative, only the agent's owned
  section is taken from the agent reply.

  Returns:
    The reassembled document text with the new frontmatter, operator body with the agent's
    owned section spliced in at the configured position, and the operator's banner restored.
  """
  # Body comes from operator — agent's body edits are IGNORED.
    # Pull only the agent's owned section.
  agent_owned = _extract_section_by_owner(agent_body, owned_owner)
  # Operator body minus owned sections AND History — we re-add both
  # below in canonical order (owned first, History last). Bug 30.
  op_body_no_owned = _drop_sections(
      operator_body,
      drop_owned=True,
      drop_history=True,
      keep_owner=None,
  )
  # Splice the agent's owned section in BEFORE History so the History
  # terminal invariant holds. Position is taken from `section_layout`
  # — `"top"` prepends the section above the operator's free body,
  # `"bottom"` (or unmapped) appends it below. Without this lookup
  # the agent's NEW section always lands at the end of the content
  # body, ignoring its `position` configuration (Bug 67); the layout
  # mechanism in `_restore_owned_and_history` only sees operator-side
  # owned sections, not the agent's fresh one we're splicing in here.
  if agent_owned is not None:
    position = (section_layout or {}).get(owned_owner, Position.BOTTOM)
    if position == Position.TOP:
      if op_body_no_owned:
        op_body_no_owned = agent_owned + _ensure_leading_blank(
            agent_owned, op_body_no_owned,
        )
      else:
        op_body_no_owned = agent_owned
    else:
      op_body_no_owned = op_body_no_owned + _ensure_leading_blank(
          op_body_no_owned, agent_owned,
      )
  rebuilt = _restore_owned_and_history(
      operator_body, op_body_no_owned, skip_owner=owned_owner, section_layout=section_layout,
  )
  return new_fm_text + _carry_banner_from_operator(operator_body, rebuilt)


