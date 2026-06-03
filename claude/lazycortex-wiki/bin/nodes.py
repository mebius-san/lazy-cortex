"""
Markdown and code node read/write for lazycortex-wiki managed regions.

`MarkdownNode` reads and writes the three wiki-owned regions of a markdown
file (wiki_summary, wiki/* tags, See-also section) while preserving all
operator content byte-for-byte.  Frontmatter is manipulated with surgical
line-edits — no YAML round-trip — so block-style values, comments, and
quoting survive unchanged.

`CodeNode` reads and writes the single `<wiki>` comment block at the top
of a code file while leaving code untouched.  Comment prefix is determined
by file extension via `_COMMENT_STYLE_MAP`.  `node_for(path)` is the
factory function that selects the right node class for a given path.

Cross-plugin Python import is forbidden (per the inter-plugin boundary contract),
so this module re-implements the minimal frontmatter primitives needed
rather than importing from `lazycortex-core` or `lazycortex-review`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import hashlib
import re

from markers import Markers

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# ────────────────────────────────────────────────────────────────────────────
# Module-level helpers — private, not part of public API
# ────────────────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^---[ \t]*$", re.MULTILINE)

# Matches a top-level YAML key line (no leading space, `key:` shape).
_KEY_LINE_RE = re.compile(r"^([A-Za-z_][\w.-]*)\s*:(?:\s|$)")

# Frontmatter key names shared between module-level helpers and MarkdownNode.
_KEY_WIKI_SUMMARY      = "wiki_summary"
_KEY_CONNECTORS        = "wiki_connectors"
_KEY_TAGS              = "tags"
_KEY_PINNED_TOPICS     = "wiki_pinned_topics"
_KEY_UNRELATED_TOPICS  = "wiki_unrelated_topics"
_KEY_PINNED_LINKS      = "wiki_pinned_links"
_KEY_UNRELATED_LINKS   = "wiki_unrelated_links"
_KEY_SRC_HASH          = "wiki_src_hash"

# File encoding used for every read/write in this module.
_ENCODING = "utf-8"

# Length (hex chars) of the stored source hash — first N of a sha256 hexdigest.
_SRC_HASH_LEN = 16

# Minimum length of any single-layer quoted scalar — the outer opening and
# closing quote characters. A string shorter than this cannot carry a real
# quoted-scalar shape.
_MIN_QUOTED_LEN = 2

# Extracts the path from a markdown link: `[text](path)` → `path`. Used to
# read the existing See-also target set from both markdown nodes (block
# inner text) and code nodes (individual `<wiki>` see-also entries).
_SEE_ALSO_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _find_fences(text: str) -> tuple[int, int, int] | None:
  """
  Return `(open_end, close_start, close_end)` byte offsets of the frontmatter
  fences, or `None` when the document has no frontmatter.

  Args:
    text: Full document text.

  Returns:
    Triple of byte offsets, or `None` when no frontmatter is detected.
  """
  # guard: document does not start with an opening fence
  if not (text.startswith(("---\n", "---\r\n")) or text == "---"):
    return None

  after_open = len("---\r\n") if text.startswith("---\r\n") else len("---\n")
  rest = text[after_open:]
  match = _FENCE_RE.search(rest)
  # guard: no closing fence — treat as no frontmatter rather than hard error
  if match is None:
    return None

  close_start = after_open + match.start()
  close_end = after_open + match.end()
  # guard: consume the newline that follows the closing fence
  if close_end < len(text) and text[close_end] == "\n":
    close_end += 1
  return after_open, close_start, close_end


def _line_starts_top_level_key(line: str) -> bool:
  """
  Return True when `line` begins a new top-level YAML key.

  Args:
    line: A single line from the frontmatter block (no trailing newline).

  Returns:
    True when the line opens a new top-level key entry.
  """
  # guard: empty line or comment or indented continuation
  if not line or line[0] in (" ", "\t", "#"):
    return False
  return bool(_KEY_LINE_RE.match(line))


def _key_block_span(block: str, key: str) -> tuple[int, int] | None:
  """
  Return `(start, end)` byte offsets inside `block` for the full logical
  entry of `key` — its header line plus any indented continuation lines.

  Args:
    block: The raw text between the frontmatter fences (exclusive).
    key: Top-level YAML key to locate.

  Returns:
    Byte-offset pair covering the entire key entry, or `None` when absent.
  """
  pattern = re.compile(rf"(?m)^{re.escape(key)}\s*:(?:\s|$)")
  match = pattern.search(block)
  # guard: key not present in this block
  if match is None:
    return None

  start = match.start()
  cursor = block.find("\n", match.end())
  # guard: key is on the last line with no trailing newline
  if cursor == -1:
    return start, len(block)

  cursor += 1
  while cursor < len(block):
    next_nl = block.find("\n", cursor)
    line_end = next_nl if next_nl != -1 else len(block)
    line = block[cursor:line_end]
    # guard: next top-level key — stop here
    if _line_starts_top_level_key(line):
      break
    cursor = (line_end + 1) if next_nl != -1 else line_end

  return start, cursor


def _parse_tags_block(block: str) -> list[str]:
  """
  Parse all tag values from a `tags:` key entry in the frontmatter block.

  Handles three YAML shapes:
  - Block sequence: `tags:\\n  - foo\\n  - bar`
  - Inline flow sequence: `tags: [foo, bar]`
  - Bare scalar (unusual but tolerated): `tags: foo`

  Args:
    block: The raw text of the `tags:` key entry (header + continuation lines).

  Returns:
    List of tag strings in their original order, with quoting stripped.
  """
  header_end = block.find("\n")
  header_line = block if header_end == -1 else block[:header_end]
  after_colon = header_line.partition(":")[2].strip()

  # Inline flow sequence — e.g. `tags: [foo, bar, "baz qux"]`
  if after_colon.startswith("[") and after_colon.endswith("]"):
    inner = after_colon[1:-1]
    return [ _unquote_tag(t.strip()) for t in inner.split(",") if t.strip() ]

  # Block sequence — continuation lines starting with `  - `
  tags: list[str] = []
  for line in block.splitlines()[1:]:
    stripped = line.strip()
    # guard: not a list item
    if not stripped.startswith("- "):
      continue
    tags.append(_unquote_tag(stripped[2:].strip()))
  return tags


def _unquote_tag(s: str) -> str:
  """
  Remove one layer of surrounding single or double quotes from a YAML scalar.

  Args:
    s: Raw tag string that may be surrounded by matching quote characters.

  Returns:
    Unquoted string, or the input unchanged when no matching quotes surround it.
  """
  if len(s) >= _MIN_QUOTED_LEN and s[0] == s[-1] and s[0] in ('"', "'"):
    return s[1:-1]
  return s


def _yaml_needs_quote(value: str) -> bool:
  """
  Decide whether a string value needs single-quoting for YAML 1.2 round-trip.

  Plain (unquoted) YAML scalars cannot contain a mapping separator (`: `),
  a comment introducer (` #`), or any of the flow / indicator leading
  characters without being parsed as something other than the literal
  string. Bool / null literals, leading-or-trailing whitespace, and
  embedded newlines also need quoting to survive round-trip.

  Args:
    value: Candidate scalar value to be written as `key: <value>`.

  Returns:
    True when the value cannot be written as a plain (unquoted) YAML scalar
    without changing meaning; False when it is safe as plain text.
  """
  # guard: empty string is ambiguous with `null` when written plain
  if not value:
    return True
  # mapping ambiguity: `: ` mid-value or trailing `:` reads as a mapping key
  if ": " in value or value.endswith(":"):
    return True
  # comment ambiguity: ` #` starts a comment to end of line
  if " #" in value:
    return True
  # leading character forces a non-scalar / indicator interpretation
  if value[0] in "[]{}&*!|>'\"%@`#,?":
    return True
  # `- ` at start is a block-sequence item; bare `-` is also ambiguous
  if value.startswith("- ") or value == "-":
    return True
  # YAML 1.1 bool / null literals — quote to keep them strings
  if value.lower() in ( "true", "false", "yes", "no", "null", "~", "on", "off" ):
    return True
  # leading / trailing whitespace is lost without quoting
  if value != value.strip():
    return True
  # newlines break the single-line value contract
  if "\n" in value:
    return True
  return False


def _yaml_scalar(value: str) -> str:
  """
  Render a string as a YAML scalar suitable for `key: <value>` block style.

  Returns the value unchanged when it is unambiguous as a plain scalar.
  Otherwise single-quotes it (escaping inner `'` as `''`) so the produced
  fragment round-trips through any YAML 1.2 parser.

  Args:
    value: String value to render.

  Returns:
    YAML-safe scalar fragment — either the raw value or a `'...'`-wrapped form.
  """
  # guard: value is safe as plain scalar — keep it unquoted to avoid churn
  if not _yaml_needs_quote(value):
    return value
  return "'" + value.replace("'", "''") + "'"


def _yaml_unquote(value: str) -> str:
  """
  Strip a single layer of YAML scalar quoting and return the inner string.

  Recognises both single-quoted (with `''` → `'` unescape) and double-quoted
  YAML scalars. Plain (unquoted) scalars pass through unchanged. Mirrors
  `_yaml_scalar` so write-then-read round-trips.

  Args:
    value: Raw post-`:` scalar fragment as read from the frontmatter line.

  Returns:
    The inner string with the outer quote layer (if any) removed.
  """
  # guard: single-quoted form — unescape the doubled-quote pair
  if len(value) >= _MIN_QUOTED_LEN and value[0] == "'" and value[-1] == "'":
    return value[1:-1].replace("''", "'")
  # guard: double-quoted form — strip the outer quotes
  if len(value) >= _MIN_QUOTED_LEN and value[0] == '"' and value[-1] == '"':
    return value[1:-1]
  return value


def _set_scalar_field(text: str, key: str, value: str) -> str:
  """
  Set a scalar frontmatter `key` to `value`, preserving all other text.

  Creates the frontmatter block when absent.  When the key already exists
  (possibly with block-style continuation lines), the entire key entry is
  replaced with a single-line scalar.  The value is rendered through
  `_yaml_scalar` so values containing `:` / `#` / leading indicators or
  reserved bool/null literals are quoted for YAML round-trip safety.

  Args:
    text: Full document text.
    key: Top-level YAML key to set.
    value: String value; must not contain newlines.

  Returns:
    Document text with the key set to `value`.
  """
  rendered = f"{key}: {_yaml_scalar(value)}"
  span = _find_fences(text)

  # guard: no frontmatter at all — synthesise one
  if span is None:
    return f"---\n{rendered}\n---\n{text}"

  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)

  if existing is None:
    # Append before the closing fence
    if block and not block.endswith("\n"):
      new_block = block + "\n" + rendered + "\n"
    else:
      new_block = block + rendered + "\n"
    return text[:open_end] + new_block + text[close_start:]

  # Replace the whole existing entry with the single-line scalar form
  start, end = existing
  # Preserve trailing newline so the closing fence stays on its own line
  suffix = "\n" if end > 0 and block[end - 1:end] == "\n" else ""
  new_block = block[:start] + rendered + suffix + block[end:]
  return text[:open_end] + new_block + text[close_start:]


def _set_tags_field(text: str, new_tags: list[str]) -> str:
  """
  Replace the entire `tags:` key entry with a block-sequence of `new_tags`.

  If `new_tags` is empty and the key is present, the key is removed.
  If `new_tags` is empty and the key is absent, the text is returned unchanged.
  If the key is absent and `new_tags` is non-empty, a new block-style entry
  is appended before the closing fence.

  Args:
    text: Full document text.
    new_tags: Complete ordered list of tag strings to write.

  Returns:
    Document text with the `tags:` key updated.
  """
  span = _find_fences(text)
  # guard: no frontmatter — synthesise if there are tags to add, skip otherwise
  if span is None:
    if not new_tags:
      return text
    block_yaml = _render_tags_block(new_tags)
    return f"---\n{block_yaml}---\n{text}"

  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, _KEY_TAGS)

  if not new_tags:
    # guard: no tags and no existing key — nothing to change
    if existing is None:
      return text
    # Remove the existing entry entirely
    start, end = existing
    new_block = block[:start] + block[end:]
    return text[:open_end] + new_block + text[close_start:]

  rendered = _render_tags_block(new_tags)
  # Rendered block already ends with `\n` so no extra suffix needed
  if existing is None:
    if block and not block.endswith("\n"):
      new_block = block + "\n" + rendered
    else:
      new_block = block + rendered
    return text[:open_end] + new_block + text[close_start:]

  start, end = existing
  # Preserve any whitespace suffix so subsequent keys stay on their own lines
  tail = block[end:]
  new_block = block[:start] + rendered + tail
  return text[:open_end] + new_block + text[close_start:]


def _render_tags_block(tags: list[str]) -> str:
  """
  Render `tags` as a YAML block sequence string.

  Args:
    tags: Ordered list of tag strings.

  Returns:
    Multi-line string `tags:\\n  - tag1\\n  - tag2\\n`.
  """
  return _render_block_seq(_KEY_TAGS, tags)


def _render_block_seq(key: str, values: list[str]) -> str:
  """
  Render `values` as a YAML block sequence under `key`.

  Args:
    key: Top-level YAML key for the sequence.
    values: Ordered list of value strings.

  Returns:
    Multi-line string `<key>:\\n  - v1\\n  - v2\\n`.
  """
  lines = [f"{key}:"]
  for value in values:
    lines.append(f"  - {value}")
  return "\n".join(lines) + "\n"


def _set_block_seq_field(text: str, key: str, new_values: list[str]) -> str:
  """
  Replace the entire `key` entry with a block-sequence of `new_values`.

  Mirrors the surgical semantics of `_set_tags_field` for any top-level
  sequence key: an empty `new_values` removes the key when present (no-op
  when absent); a non-empty list appends a fresh block-style entry when the
  key is absent, or replaces the whole existing entry in place.

  Args:
    text: Full document text.
    key: Top-level YAML key holding the sequence.
    new_values: Complete ordered list of value strings to write.

  Returns:
    Document text with the `key` entry updated.
  """
  span = _find_fences(text)
  # guard: no frontmatter — synthesise if there are values to add, skip otherwise
  if span is None:
    if not new_values:
      return text
    block_yaml = _render_block_seq(key, new_values)
    return f"---\n{block_yaml}---\n{text}"

  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)

  if not new_values:
    # guard: no values and no existing key — nothing to change
    if existing is None:
      return text
    start, end = existing
    new_block = block[:start] + block[end:]
    return text[:open_end] + new_block + text[close_start:]

  rendered = _render_block_seq(key, new_values)
  # Rendered block already ends with `\n` so no extra suffix needed
  if existing is None:
    if block and not block.endswith("\n"):
      new_block = block + "\n" + rendered
    else:
      new_block = block + rendered
    return text[:open_end] + new_block + text[close_start:]

  start, end = existing
  tail = block[end:]
  new_block = block[:start] + rendered + tail
  return text[:open_end] + new_block + text[close_start:]


def _get_scalar_field(text: str, key: str) -> str | None:
  """
  Return the string value of a scalar frontmatter `key`, or `None`.

  Args:
    text: Full document text.
    key: Top-level YAML key to look up.

  Returns:
    Stripped string value when the key exists with a scalar value on its
    header line, or `None` when absent or blank.
  """
  span = _find_fences(text)
  # guard: no frontmatter
  if span is None:
    return None

  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)
  # guard: key not found
  if existing is None:
    return None

  start, end = existing
  entry = block[start:end]
  header_line = entry.split("\n")[0]
  after_colon = header_line.partition(":")[2].strip()
  # guard: empty post-colon means the key has no scalar value on its header line
  if not after_colon:
    return None
  return _yaml_unquote(after_colon)


def _get_array_field(text: str, key: str) -> list[str]:
  """
  Return the string list value of a `key` that holds a YAML sequence.

  Handles both block-sequence (`- item`) and inline-flow (`[a, b]`) shapes.

  Args:
    text: Full document text.
    key: Top-level YAML key holding the sequence.

  Returns:
    List of tag/item strings, or an empty list when absent or blank.
  """
  span = _find_fences(text)
  # guard: no frontmatter
  if span is None:
    return []

  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)
  # guard: key not found
  if existing is None:
    return []

  start, end = existing
  entry = block[start:end]
  return _parse_tags_block(entry)


def _normalise_for_hash(text: str) -> str:
  """
  Normalise text for stable hashing.

  Each line has its trailing whitespace and `\\r` removed, then leading and
  trailing blank lines are dropped.  This absorbs whitespace-only edits and
  the blank-line residue left when a managed region is excised, so neither
  perturbs the hash.

  Args:
    text: Raw text to normalise.

  Returns:
    Newline-joined text, each line right-stripped, no leading/trailing blanks.
  """
  lines = [ line.rstrip() for line in text.splitlines() ]
  # Drop leading blank lines.
  while lines and not lines[0]:
    lines.pop(0)
  # Drop trailing blank lines.
  while lines and not lines[-1]:
    lines.pop()
  return "\n".join(lines)


def _markdown_source_for_hash(text: str) -> str:
  """
  Reduce a markdown document to its operator-authored source for hashing.

  Every wiki-managed region is removed so the curator's own writes never
  perturb the result: the `wiki_summary` / `wiki_src_hash` / `wiki_connectors`
  frontmatter keys are dropped, the `wiki/*`-prefixed tags are dropped
  (non-`wiki/` tags survive in their original order), and the
  `# See also` managed section is removed between its markers
  (heading included).  The remainder is whitespace-normalised line by line.

  Args:
    text: Full markdown document text.

  Returns:
    Normalised operator-source string suitable for a stable hash.
  """
  stripped = _strip_managed_md(text)
  return _normalise_for_hash(stripped)


def _strip_managed_md(text: str) -> str:
  """
  Remove the wiki-managed frontmatter keys, `wiki/*` tags, connectors, and See-also section.

  Args:
    text: Full markdown document text.

  Returns:
    Document text with managed regions removed; operator content intact.
  """
  # Drop the managed scalar keys outright.
  out = _drop_key(text, _KEY_WIKI_SUMMARY)
  out = _drop_key(out, _KEY_SRC_HASH)
  # Drop the managed connectors block (curator-written, excluded from the hash).
  out = _drop_key(out, _KEY_CONNECTORS)
  # Keep only the non-wiki/* subset of tags (drop the key when none remain).
  non_wiki = [ t for t in _get_array_field(out, _KEY_TAGS) if not t.startswith(MarkdownNode._WIKI_TAG_PREFIX) ]
  out = _set_tags_field(out, non_wiki)
  # Collapse a now-empty frontmatter block so curation of a frontmatter-free
  # node hashes identically before and after.
  out = _drop_empty_frontmatter(out)
  # Remove the See-also managed section from the body.
  return _drop_see_also_section(out)


def _drop_empty_frontmatter(text: str) -> str:
  """
  Remove the frontmatter fences when no keys remain between them.

  Args:
    text: Full document text.

  Returns:
    Document text with an empty frontmatter block removed; unchanged when the
    block is absent or still carries keys.
  """
  span = _find_fences(text)
  # guard: no frontmatter at all
  if span is None:
    return text
  open_end, close_start, close_end = span
  # guard: block still carries operator keys — keep it
  if text[open_end:close_start].strip():
    return text
  # The opening fence always begins at offset 0 (see _find_fences); dropping
  # the whole fenced span leaves just the body.
  return text[close_end:]


def _drop_key(text: str, key: str) -> str:
  """
  Remove a top-level frontmatter `key` entry entirely, preserving other text.

  Args:
    text: Full document text.
    key: Top-level YAML key to remove.

  Returns:
    Document text with the key entry removed; unchanged when absent.
  """
  span = _find_fences(text)
  # guard: no frontmatter — nothing to drop
  if span is None:
    return text
  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)
  # guard: key not present
  if existing is None:
    return text
  start, end = existing
  new_block = block[:start] + block[end:]
  return text[:open_end] + new_block + text[close_start:]


def _drop_see_also_section(text: str) -> str:
  """
  Remove the `# See also` heading (and its `#protected/wiki/see-also` owner tag) plus the marker-bounded block.

  Args:
    text: Full document text.

  Returns:
    Document text with the See-also heading and managed block removed;
    unchanged when the markers are absent.
  """
  start_marker = f"<!-- auto:{Markers.SEE_ALSO_MARKER_ID}:start -->"
  end_marker = f"<!-- auto:{Markers.SEE_ALSO_MARKER_ID}:end -->"
  # guard: markers absent — nothing to strip
  if start_marker not in text or end_marker not in text:
    return text
  start_idx = text.index(start_marker)
  end_idx = text.index(end_marker, start_idx) + len(end_marker)
  # Pull the cut back over a preceding See-also heading (and its owner-tag line) if present.
  heading = Markers.SEE_ALSO_HEADING
  head_idx = text.rfind(heading, 0, start_idx)
  between = text[head_idx:start_idx].strip() if head_idx != -1 else ""
  if head_idx != -1 and between in (
      heading,
      f"{heading}\n{Markers.SEE_ALSO_PROTECTED_TAG}",
  ):
    start_idx = head_idx
  return text[:start_idx] + text[end_idx:]


# ────────────────────────────────────────────────────────────────────────────
class MarkdownNode:
  """
  Read/write the wiki-managed regions of a single markdown file.

  Wiki owns four regions:

  1. `wiki_summary` — a scalar frontmatter key.
  2. `wiki/*` subset of `tags:` — the prefix-scoped topic tags.
  3. `wiki_connectors` — a block-sequence frontmatter key of short
     linkable-facet phrases.
  4. `# See also` body section between HTML-comment markers.

  All other frontmatter keys, non-`wiki/` tags, body prose, and any
  un-managed sections are preserved byte-for-byte.  `apply` is the
  canonical write entry point; the read properties let callers inspect
  the current state without modifying the file.
  """

  # Frontmatter key names wiki owns or reads.
  _KEY_WIKI_SUMMARY        = "wiki_summary"
  _KEY_CONNECTORS          = "wiki_connectors"
  _KEY_TAGS                = "tags"
  _KEY_PINNED_TOPICS       = "wiki_pinned_topics"
  _KEY_UNRELATED_TOPICS    = "wiki_unrelated_topics"
  _KEY_PINNED_LINKS        = "wiki_pinned_links"
  _KEY_UNRELATED_LINKS     = "wiki_unrelated_links"

  # File encoding for read/write.
  _ENCODING = "utf-8"

  # Prefix that identifies wiki-owned topic tags.
  _WIKI_TAG_PREFIX = "wiki/"

  def __init__(self, *, path: Path) -> None:
    """
    Load the markdown file at `path` into memory.

    Args:
      path: Absolute path to the markdown file to manage.
    """
    self._path = path
    self._text = path.read_text(encoding = self._ENCODING)
    self._markers = Markers()

  # ── read properties ────────────────────────────────────────────────────────

  @property
  def path(self) -> Path:
    """
    Absolute path to the managed file.
    """
    return self._path

  @property
  def wiki_summary(self) -> str | None:
    """
    Current `wiki_summary` frontmatter value, or `None` when absent.
    """
    return _get_scalar_field(self._text, _KEY_WIKI_SUMMARY)

  @property
  def tags(self) -> list[str]:
    """
    All tags from the `tags:` frontmatter field in their original order.
    """
    return _get_array_field(self._text, _KEY_TAGS)

  @property
  def wiki_tags(self) -> list[str]:
    """
    Only the `wiki/*`-prefixed subset of the `tags:` field.
    """
    return [ t for t in self.tags if t.startswith(self._WIKI_TAG_PREFIX) ]

  @property
  def connectors(self) -> list[str]:
    """
    Current `wiki_connectors` values in their original order, or an empty list.
    """
    return _get_array_field(self._text, _KEY_CONNECTORS)

  @property
  def pinned_topics(self) -> list[str]:
    """
    `wiki_pinned_topics` values (read-only; never written by wiki).
    """
    return _get_array_field(self._text, _KEY_PINNED_TOPICS)

  @property
  def unrelated_topics(self) -> list[str]:
    """
    `wiki_unrelated_topics` values (read-only; never written by wiki).
    """
    return _get_array_field(self._text, _KEY_UNRELATED_TOPICS)

  @property
  def pinned_links(self) -> list[str]:
    """
    `wiki_pinned_links` values (read-only; never written by wiki).
    """
    return _get_array_field(self._text, _KEY_PINNED_LINKS)

  @property
  def unrelated_links(self) -> list[str]:
    """
    `wiki_unrelated_links` values (read-only; never written by wiki).
    """
    return _get_array_field(self._text, _KEY_UNRELATED_LINKS)

  @property
  def see_also_inner(self) -> str | None:
    """
    Current inner content of the `# See also` section, or `None`.

    Returns the text between the HTML comment markers, stripped of surrounding
    newlines.  Returns `None` when the marker pair is absent.
    """
    return self._markers.read_inner(self._body(), Markers.SEE_ALSO_MARKER_ID)

  @property
  def see_also_targets(self) -> set[str]:
    """
    Set of forward See-also link target paths as written by the curator.

    Parses `[text](path)` link entries from the `# See also` marker block
    and exposes every unique `path` value verbatim. Same-repo targets appear as
    repo-relative POSIX paths; cross-repo targets keep their `@<repo-key>/path`
    qualifier. Empty when the See-also section is absent or empty. Used by
    `dispatch-link` to skip back-link dispatches for attractor nodes that
    already forward-link to the target.
    """
    inner = self.see_also_inner
    # guard: no See-also section — no outgoing edges
    if not inner:
      return set()
    return { m.group(1).strip() for m in _SEE_ALSO_LINK_RE.finditer(inner) }

  @property
  def source_hash(self) -> str:
    """
    Stable hash of the operator-authored source, excluding managed regions.

    The hash is computed over the document with every wiki-managed region
    removed (`wiki_summary` / `wiki_src_hash` keys, `wiki/*` tags, and the
    `# See also` section), so re-curation never changes it.
    """
    source = _markdown_source_for_hash(self._text)
    digest = hashlib.sha256(source.encode(self._ENCODING)).hexdigest()
    return digest[:_SRC_HASH_LEN]

  @property
  def stored_src_hash(self) -> str | None:
    """
    Current `wiki_src_hash` frontmatter value, or `None` when absent.
    """
    return _get_scalar_field(self._text, _KEY_SRC_HASH)

  # ── write ──────────────────────────────────────────────────────────────────

  def apply(
    self,
    *,
    wiki_summary: str,
    topics: list[str],
    see_also_lines: list[str],
    connectors: list[str] | None = None,
  ) -> None:
    """
    Write all three wiki-managed regions in one atomic pass.

    The operation is idempotent: applying identical `wiki_summary`, `topics`,
    `connectors`, and `see_also_lines` twice produces byte-identical file
    content on the second call.

    Steps:

    1. Set `wiki_summary` to the given string.
    2. Merge `topics` into `tags:` — replace only the `wiki/`-prefixed subset,
       preserving every non-`wiki/` tag in its original relative order.
    3. Replace the `wiki_connectors` block with the given phrases.
    4. Graft the `# See also` section via `Markers.ensure_see_also`.

    Args:
      wiki_summary: One-line summary string (no newlines).
      topics: Full list of `wiki/<axis>/<value>` tag strings to apply.
        These replace the current `wiki/*` subset; non-`wiki/` tags survive.
      see_also_lines: Ready-to-graft markdown list-item strings for the
        See-also section, one per list item.  An empty list produces an
        empty (but present) managed block.
      connectors: Short linkable-facet phrases for `wiki_connectors`; `None`
        leaves the existing block untouched, an empty list removes it.
    """
    self.apply_classify(wiki_summary = wiki_summary, topics = topics, connectors = connectors)
    self.apply_link(see_also_lines = see_also_lines)

  def apply_classify(
    self,
    *,
    wiki_summary: str,
    topics: list[str],
    connectors: list[str] | None = None,
  ) -> None:
    """
    Write the classify-phase managed regions: `wiki_summary`, `wiki/*` tags, `wiki_connectors`.

    Leaves the `# See also` section (and any other body content)
    untouched.  The operation is idempotent — applying identical
    `wiki_summary`, `topics`, and `connectors` twice produces byte-identical
    file content on the second call.

    Specifically:

    1. Set `wiki_summary` to the given string.
    2. Merge `topics` into `tags:` — replace only the `wiki/`-prefixed
       subset, preserving every non-`wiki/` tag in its original order.
    3. Replace the `wiki_connectors` block (when `connectors` is given).

    `wiki_connectors` is a managed region excluded from `source_hash`, so a
    connectors-only change never perturbs the recorded `wiki_src_hash`.

    Args:
      wiki_summary: One-line summary string (no newlines).
      topics: Full list of `wiki/<axis>/<value>` tag strings to apply.
        These replace the current `wiki/*` subset; non-`wiki/` tags survive.
      connectors: Short linkable-facet phrases for `wiki_connectors`; `None`
        leaves the existing block untouched, an empty list removes it.
    """
    text = self._text

    # Compute the source hash from the CURRENT content with managed regions
    # excluded — invariant across the writes below, so order does not matter.
    src_hash = hashlib.sha256(
      _markdown_source_for_hash(text).encode(_ENCODING)
    ).hexdigest()[:_SRC_HASH_LEN]

    # Step 1 — wiki_summary
    text = _set_scalar_field(text, _KEY_WIKI_SUMMARY, wiki_summary)

    # Step 2 — tags: merge wiki/* subset, preserve non-wiki/* tags in order
    current_tags = _get_array_field(text, _KEY_TAGS)
    non_wiki = [ t for t in current_tags if not t.startswith(self._WIKI_TAG_PREFIX) ]
    merged = non_wiki + topics
    text = _set_tags_field(text, merged)

    # Step 3 — wiki_connectors (managed block, excluded from source_hash)
    # guard: only rewrite the block when the caller supplied connectors
    if connectors is not None:
      text = _set_block_seq_field(text, _KEY_CONNECTORS, connectors)

    # Step 4 — wiki_src_hash (backstop for incremental relink on anchor loss)
    text = _set_scalar_field(text, _KEY_SRC_HASH, src_hash)

    self._text = text
    self._path.write_text(text, encoding = _ENCODING)

  def apply_link(
    self,
    *,
    see_also_lines: list[str],
  ) -> None:
    """
    Write the link-phase managed region: the `# See also` section.

    Leaves `wiki_summary`, `wiki/*` tags, and all other content untouched.
    The operation is idempotent — applying identical `see_also_lines` twice
    produces byte-identical file content on the second call.

    Specifically: grafts the `# See also` section via
    `Markers.ensure_see_also`.

    Args:
      see_also_lines: Ready-to-graft markdown list-item strings for the
        See-also section, one per list item.  An empty list produces an
        empty (but present) managed block.
    """
    text = self._text

    # Step 1 — See-also section
    span = _find_fences(text)
    if span is None:
      body = text
      pre = ""
    else:
      _, _, close_end = span
      pre = text[:close_end]
      body = text[close_end:]

    inner = "\n".join(see_also_lines)
    body = self._markers.ensure_see_also(body, inner)
    text = pre + body

    self._text = text
    self._path.write_text(text, encoding = _ENCODING)

  # ── helpers ───────────────────────────────────────────────────────────────

  def _body(self) -> str:
    """
    Return the document body — the text after the frontmatter fences.

    Args: (none)

    Returns:
      Body string starting immediately after the closing `---` fence (and its
      trailing newline).  When no frontmatter is present, the full document
      text is returned.
    """
    span = _find_fences(self._text)
    # guard: no frontmatter — entire text is the body
    if span is None:
      return self._text
    _, _, close_end = span
    return self._text[close_end:]


# ────────────────────────────────────────────────────────────────────────────
# CodeNode — comment-prefix styles and block parsing
# ────────────────────────────────────────────────────────────────────────────

# Map from file extension (lower-cased, with leading dot) to either:
#   - A string line-comment prefix (e.g. "#", "//", "--", ";"), or
#   - The sentinel "/*" indicating a block-comment-only language.
# Unknown extensions are not listed; `node_for` returns None for them.
_COMMENT_STYLE_MAP: dict[str, str] = {
  ".py":   "#",
  ".sh":   "#",
  ".rb":   "#",
  ".r":    "#",
  ".pl":   "#",
  ".yaml": "#",
  ".yml":  "#",
  ".js":   "//",
  ".ts":   "//",
  ".tsx":  "//",
  ".jsx":  "//",
  ".go":   "//",
  ".c":    "//",
  ".h":    "//",
  ".cpp":  "//",
  ".cc":   "//",
  ".cxx":  "//",
  ".cs":   "//",
  ".java": "//",
  ".rs":   "//",
  ".kt":   "//",
  ".swift":"//",
  ".dart": "//",
  ".sql":  "--",
  ".lua":  "--",
  ".hs":   "--",
  ".elm":  "--",
  ".el":   ";",
  ".lisp": ";",
  ".clj":  ";",
  ".cljs": ";",
  ".ini":  ";",
  ".css":  "/*",
}

# Sentinel value for block-comment-only languages.
_BLOCK_COMMENT_SENTINEL = "/*"

# Markers that delimit the wiki block inside comments.
_WIKI_OPEN_TAG  = "<wiki>"
_WIKI_CLOSE_TAG = "</wiki>"

# Namespace prefix the curator prepends to every topic tag.  Markdown nodes store
# it verbatim in `tags:`; a code `<wiki>` block stores BARE `<axis>/<value>`
# topics (build-index re-adds the prefix for code nodes).
_WIKI_TAG_PREFIX = "wiki/"

# Regex to detect a shebang line.
_SHEBANG_RE = re.compile(r"^#!")

# Field keys used in the parsed wiki-block dict (internal snake_case).
_FK_SUMMARY          = "summary"
_FK_TOPICS           = "topics"
_FK_CONNECTORS       = "connectors"
_FK_SRC_HASH         = "src_hash"
_FK_SEE_ALSO         = "see_also"
_FK_PINNED_TOPICS    = "pinned_topics"
_FK_UNRELATED_TOPICS = "unrelated_topics"
_FK_PINNED_LINKS     = "pinned_links"
_FK_UNRELATED_LINKS  = "unrelated_links"

# Field header strings as they appear in the comment block (wire format).
_FH_SUMMARY          = "summary:"
_FH_TOPICS           = "topics:"
_FH_CONNECTORS       = "connectors:"
_FH_SRC_HASH         = "src-hash:"
_FH_SEE_ALSO         = "see-also:"
_FH_PINNED_TOPICS    = "pinned-topics:"
_FH_UNRELATED_TOPICS = "unrelated-topics:"
_FH_PINNED_LINKS     = "pinned-links:"
_FH_UNRELATED_LINKS  = "unrelated-links:"

# Markdown file extension sentinel for `node_for`.
_MD_SUFFIX = ".md"


def _comment_style(ext: str) -> str | None:
  """
  Return the comment style for a file extension, or `None` when unrecognised.

  Args:
    ext: Lower-cased file extension including the leading dot (e.g. `.py`).

  Returns:
    Comment prefix string, `"/*"` for block-comment-only languages, or `None`.
  """
  return _COMMENT_STYLE_MAP.get(ext)


def _strip_comment_prefix(line: str, prefix: str) -> str | None:
  """
  Strip a line-comment prefix from a line of text.

  Handles both `# text` (space after prefix) and `#text` (no space), and
  the same for `//` and `--`.  Returns the stripped content, or `None` when
  the line does not carry the given prefix.

  Args:
    line: A single source line (no trailing newline).
    prefix: The comment prefix string (e.g. `#`, `//`).

  Returns:
    Content after the prefix (with one leading space stripped when present),
    or `None` when the prefix is absent.
  """
  stripped = line.strip()
  # guard: line does not start with the expected prefix
  if not stripped.startswith(prefix):
    return None
  after = stripped[len(prefix):]
  # strip at most one leading space (matches `# text` vs `#text`)
  if after.startswith(" "):
    after = after[1:]
  return after


def _build_wiki_line(content: str, prefix: str) -> str:
  """
  Render a single wiki-block line by prepending the comment prefix.

  Args:
    content: The inner content string (no trailing newline).
    prefix: Comment prefix string (e.g. `#`, `//`, `--`, `;`).

  Returns:
    Line string without trailing newline: `<prefix> <content>` or `<prefix>` for empty.
  """
  if content:
    return f"{prefix} {content}"
  return prefix


def _locate_header_end(lines: list[str], prefix: str) -> int:
  """
  Return the index of the first line that is NOT a shebang or a leading-comment header.

  Leading comment header means: all consecutive comment lines at the top of
  the file (after an optional shebang) that do NOT contain `<wiki>`.  The
  index returned is the insertion point for a new `<wiki>` block.

  For block-comment-only languages, the prefix is `"/*"` and there is no
  inline header to detect — the insertion point is always after the shebang
  (if any).

  Args:
    lines: List of source lines (with trailing newlines).
    prefix: Comment prefix string for line-comment languages, or `"/*"`.

  Returns:
    Zero-based index of the first line after the header region.
  """
  i = 0
  # skip shebang
  if lines and _SHEBANG_RE.match(lines[0]):
    i = 1
  # guard: block-comment language has no line prefix to detect
  if prefix == _BLOCK_COMMENT_SENTINEL:
    return i
  # skip contiguous line-comment header (license / encoding) that precedes code
  while i < len(lines):
    line = lines[i].rstrip("\n").rstrip("\r")
    stripped = line.strip()
    # guard: stop at blank line or non-comment line
    if not stripped or not stripped.startswith(prefix):
      break
    # guard: stop if this is already a wiki open tag (shouldn't happen on fresh files)
    inner = _strip_comment_prefix(line.rstrip("\n").rstrip("\r"), prefix)
    if inner is not None and inner.strip() == _WIKI_OPEN_TAG:
      break
    i += 1
  return i


def _find_wiki_block(lines: list[str], prefix: str) -> tuple[int, int] | None:
  """
  Find the `<wiki>` / `</wiki>` block in a list of source lines.

  For line-comment languages, each delimiter line looks like `# <wiki>`.
  For block-comment languages, the block is wrapped: `/* <wiki>` / `</wiki> */`.

  Args:
    lines: List of source lines (with trailing newlines).
    prefix: Comment prefix string, or `"/*"` for block-comment languages.

  Returns:
    `(start, end)` zero-based indices where `start` is the index of the
    opening delimiter line and `end` is the index of the closing delimiter
    line (inclusive).  `None` when no block is present.
  """
  if prefix == _BLOCK_COMMENT_SENTINEL:
    return _find_wiki_block_block_comment(lines)
  return _find_wiki_block_line_comment(lines, prefix)


def _find_wiki_block_line_comment(
  lines: list[str],
  prefix: str,
) -> tuple[int, int] | None:
  """
  Find the `<wiki>` / `</wiki>` block delimited by line-comment prefixes.

  Args:
    lines: List of source lines with trailing newlines.
    prefix: Line-comment prefix (e.g. `#`, `//`, `--`, `;`).

  Returns:
    `(start, end)` zero-based inclusive indices, or `None`.
  """
  open_idx: int | None = None
  for i, raw in enumerate(lines):
    line = raw.rstrip("\n").rstrip("\r")
    inner = _strip_comment_prefix(line, prefix)
    # guard: not a comment line
    if inner is None:
      continue
    tag = inner.strip()
    if tag == _WIKI_OPEN_TAG and open_idx is None:
      open_idx = i
    elif tag == _WIKI_CLOSE_TAG and open_idx is not None:
      return open_idx, i
  return None


def _find_wiki_block_block_comment(lines: list[str]) -> tuple[int, int] | None:
  """
  Find the `<wiki>` / `</wiki>` block delimited by `/* … */` block comments.

  The opening line is `/* <wiki>` and the closing line is `</wiki> */`.

  Args:
    lines: List of source lines with trailing newlines.

  Returns:
    `(start, end)` zero-based inclusive indices, or `None`.
  """
  open_idx: int | None = None
  for i, raw in enumerate(lines):
    line = raw.strip()
    if line == f"/* {_WIKI_OPEN_TAG}" and open_idx is None:
      open_idx = i
    elif line == f"{_WIKI_CLOSE_TAG} */" and open_idx is not None:
      return open_idx, i
  return None


def _parse_wiki_block(
  lines: list[str],
  start: int,
  end: int,
  prefix: str,
) -> dict[str, str | list[str]]:
  """
  Parse the content lines of a `<wiki>` block into a field dict.

  Fields parsed: `summary`, `topics` (list), `connectors` (list),
  `see_also` (list), `pinned_topics` (str), `unrelated_topics` (str),
  `pinned_links` (str), `unrelated_links` (str).  Lines between `see-also:`
  and the next field header are collected as `see_also` items (bare-path
  lines prefixed with `  - `).

  Args:
    lines: List of source lines with trailing newlines.
    start: Index of the opening delimiter line (inclusive).
    end: Index of the closing delimiter line (inclusive).
    prefix: Comment prefix string or `"/*"`.

  Returns:
    Dict of parsed field values.  Missing fields are absent from the dict.
  """
  fields: dict[str, str | list[str]] = {}
  see_also_list: list[str] = []
  in_see_also = False
  block_comment = prefix == _BLOCK_COMMENT_SENTINEL

  interior = [ raw.rstrip("\n").rstrip("\r") for raw in lines[start + 1:end] ]
  # Block-comment interior lines carry no comment prefix but may share a common
  # leading indent (an indented `/* … */` block).  Dedent by that common base so
  # field headers land at column 0 while see-also items keep their relative `  - `
  # indent — a flat per-line strip would erase the indent the continuation check needs.
  base_indent = 0
  if block_comment:
    indents = [ len(e) - len(e.lstrip()) for e in interior if e.strip() ]
    base_indent = min(indents) if indents else 0

  for line in interior:
    if block_comment:
      content = line[base_indent:].rstrip()
    else:
      content_or_none = _strip_comment_prefix(line, prefix)
      # guard: not a comment line inside the block — skip
      if content_or_none is None:
        continue
      content = content_or_none

    # guard: empty content line — skip
    if not content:
      continue

    # see-also continuation item (indented `  - path — gloss` or `  - path`)
    if in_see_also and content.startswith("  - "):
      item = content[4:].strip()
      if item:
        see_also_list.append(item)
      continue

    # field header lines
    if content.startswith(_FH_SUMMARY):
      in_see_also = False
      val = content[len(_FH_SUMMARY):].strip()
      if val:
        fields[_FK_SUMMARY] = val
    elif content.startswith(_FH_TOPICS):
      in_see_also = False
      val = content[len(_FH_TOPICS):].strip()
      if val:
        topics_raw = [ t.strip() for t in val.split(",") if t.strip() ]
        fields[_FK_TOPICS] = topics_raw
    elif content.startswith(_FH_CONNECTORS):
      in_see_also = False
      val = content[len(_FH_CONNECTORS):].strip()
      if val:
        connectors_raw = [ c.strip() for c in val.split(",") if c.strip() ]
        fields[_FK_CONNECTORS] = connectors_raw
    elif content.startswith(_FH_SRC_HASH):
      in_see_also = False
      val = content[len(_FH_SRC_HASH):].strip()
      if val:
        fields[_FK_SRC_HASH] = val
    elif content.startswith(_FH_SEE_ALSO):
      in_see_also = True
      # save any partial see_also collected so far
      fields[_FK_SEE_ALSO] = see_also_list
    elif content.startswith(_FH_PINNED_TOPICS):
      in_see_also = False
      fields[_FK_PINNED_TOPICS] = content[len(_FH_PINNED_TOPICS):].strip()
    elif content.startswith(_FH_UNRELATED_TOPICS):
      in_see_also = False
      fields[_FK_UNRELATED_TOPICS] = content[len(_FH_UNRELATED_TOPICS):].strip()
    elif content.startswith(_FH_PINNED_LINKS):
      in_see_also = False
      fields[_FK_PINNED_LINKS] = content[len(_FH_PINNED_LINKS):].strip()
    elif content.startswith(_FH_UNRELATED_LINKS):
      in_see_also = False
      fields[_FK_UNRELATED_LINKS] = content[len(_FH_UNRELATED_LINKS):].strip()
    else:
      # unknown field — skip
      in_see_also = False

  # finalise see_also
  if in_see_also or _FK_SEE_ALSO in fields:
    fields[_FK_SEE_ALSO] = see_also_list

  return fields


def _render_wiki_block_lines(
  fields: dict[str, str | list[str]],
  prefix: str,
) -> list[str]:
  """
  Render a `<wiki>` block as a list of lines (without trailing newlines).

  Field order mirrors the spec example: summary → topics → connectors →
  see-also → pinned-topics → unrelated-topics → pinned-links →
  unrelated-links.  Fields absent from `fields` are omitted.

  For line-comment languages each line is prefixed with `prefix + " "`.
  For block-comment languages, the opening is `/* <wiki>`, the closing is
  `</wiki> */`, and interior lines have no prefix.

  Args:
    fields: Dict of field name → value (string or list) to emit.
    prefix: Comment prefix or `"/*"`.

  Returns:
    List of line strings without trailing newlines.
  """
  block_comment = prefix == _BLOCK_COMMENT_SENTINEL
  out: list[str] = []

  if block_comment:
    out.append(f"/* {_WIKI_OPEN_TAG}")
  else:
    out.append(_build_wiki_line(_WIKI_OPEN_TAG, prefix))

  def _line(content: str) -> str:
    if block_comment:
      return content
    return _build_wiki_line(content, prefix)

  summary = fields.get(_FK_SUMMARY)
  if summary:
    out.append(_line(f"{_FH_SUMMARY} {summary}"))

  topics = fields.get(_FK_TOPICS)
  if topics and isinstance(topics, list):
    out.append(_line(f"{_FH_TOPICS} {', '.join(topics)}"))

  connectors = fields.get(_FK_CONNECTORS)
  if connectors and isinstance(connectors, list):
    out.append(_line(f"{_FH_CONNECTORS} {', '.join(connectors)}"))

  src_hash = fields.get(_FK_SRC_HASH)
  if src_hash:
    out.append(_line(f"{_FH_SRC_HASH} {src_hash}"))

  see_also = fields.get(_FK_SEE_ALSO)
  if see_also is not None:
    out.append(_line(_FH_SEE_ALSO))
    for item in (see_also if isinstance(see_also, list) else []):
      out.append(_line(f"  - {item}"))

  for field_key, field_hdr in [
    (_FK_PINNED_TOPICS,    _FH_PINNED_TOPICS),
    (_FK_UNRELATED_TOPICS, _FH_UNRELATED_TOPICS),
    (_FK_PINNED_LINKS,     _FH_PINNED_LINKS),
    (_FK_UNRELATED_LINKS,  _FH_UNRELATED_LINKS),
  ]:
    val = fields.get(field_key)
    if val:
      out.append(_line(f"{field_hdr} {val}"))

  if block_comment:
    out.append(f"{_WIKI_CLOSE_TAG} */")
  else:
    out.append(_build_wiki_line(_WIKI_CLOSE_TAG, prefix))

  return out


def _code_source_for_hash(lines: list[str], prefix: str) -> str:
  """
  Reduce a code file to its operator-authored source for hashing.

  The entire `<wiki>` block (delimiters included) is removed, plus a single
  blank separator line that follows it, so the curator's own writes never
  perturb the result.  The remaining lines are whitespace-normalised.

  Args:
    lines: Source lines with trailing newlines.
    prefix: Comment prefix for the file's language, or `"/*"`.

  Returns:
    Normalised operator-source string suitable for a stable hash.
  """
  span = _find_wiki_block(lines, prefix)
  if span is None:
    kept = lines
  else:
    start, end = span
    after = end + 1
    # guard: drop one trailing blank separator the writer adds after the block
    if after < len(lines) and lines[after].strip() == "":
      after += 1
    kept = lines[:start] + lines[after:]
  return _normalise_for_hash("".join(kept))


# ────────────────────────────────────────────────────────────────────────────
class CodeNode:
  """
  Read/write the `<wiki>` comment block in a code file while leaving code untouched.

  Wiki owns a single delimited block at the top of the file, placed after
  any shebang line and leading license/header comment, before the first line
  of actual code.  The block carries: `summary`, `topics`, `connectors`,
  `see-also` and the four operator-pin fields (`pinned-topics`,
  `unrelated-topics`, `pinned-links`, `unrelated-links`).

  Comment delimiters are determined by file extension via `_COMMENT_STYLE_MAP`.
  Block-comment-only languages (`"/*"` sentinel) wrap the entire block in
  `/* <wiki> … </wiki> */`; all others prefix each line with the language's
  line-comment prefix.

  `apply_classify` and `apply_link` are partial-write operations parallel to
  `MarkdownNode` — each rewrites only its managed fields, leaving code and
  other block fields untouched.  `apply` writes all fields in one pass.
  All three operations are idempotent.
  """

  _ENCODING = "utf-8"

  def __init__(self, *, path: Path, prefix: str) -> None:
    """
    Load the code file at `path` using the given comment `prefix`.

    Args:
      path: Absolute path to the source file.
      prefix: Comment prefix for this file's language (e.g. `#`, `//`, `"/*"`).
    """
    self._path = path
    self._prefix = prefix
    self._text = path.read_text(encoding = self._ENCODING)
    self._lines: list[str] = self._text.splitlines(keepends = True)

  # ── read properties ────────────────────────────────────────────────────────

  @property
  def path(self) -> Path:
    """
    Absolute path to the managed file.
    """
    return self._path

  @property
  def has_wiki_block(self) -> bool:
    """
    True when the file already contains a `<wiki>` / `</wiki>` block.
    """
    return _find_wiki_block(self._lines, self._prefix) is not None

  @property
  def summary(self) -> str | None:
    """
    Current `summary:` value from the `<wiki>` block, or `None` when absent.
    """
    block = self._read_block()
    # guard: no block present
    if block is None:
      return None
    val = block.get(_FK_SUMMARY)
    return str(val) if val else None

  @property
  def topics(self) -> list[str]:
    """
    Current `topics:` value from the `<wiki>` block as a list of strings.
    """
    block = self._read_block()
    # guard: no block present
    if block is None:
      return []
    val = block.get(_FK_TOPICS)
    if isinstance(val, list):
      return val
    return []

  @property
  def connectors(self) -> list[str]:
    """
    Current `connectors:` value from the `<wiki>` block as a list of strings.
    """
    block = self._read_block()
    # guard: no block present
    if block is None:
      return []
    val = block.get(_FK_CONNECTORS)
    if isinstance(val, list):
      return val
    return []

  @property
  def see_also(self) -> list[str]:
    """
    Current `see-also:` items from the `<wiki>` block as a list of strings.
    """
    block = self._read_block()
    # guard: no block present
    if block is None:
      return []
    val = block.get(_FK_SEE_ALSO)
    if isinstance(val, list):
      return val
    return []

  @property
  def see_also_targets(self) -> set[str]:
    """
    Set of forward See-also link target paths as written by the curator.

    Parses `[text](path)` link entries from every item in the `<wiki>` block's
    `see-also` list and exposes every unique `path` value verbatim. Same-repo
    targets appear as repo-relative POSIX paths; cross-repo targets keep their
    `@<repo-key>/path` qualifier. Empty when the `<wiki>` block has no see-also
    items. Used by `dispatch-link` to skip back-link dispatches for attractor
    nodes that already forward-link to the target.
    """
    out: set[str] = set()
    for item in self.see_also:
      for match in _SEE_ALSO_LINK_RE.finditer(item):
        out.add(match.group(1).strip())
    return out

  @property
  def source_hash(self) -> str:
    """
    Stable hash of the operator-authored source, excluding the `<wiki>` block.

    The hash is computed over the file with the entire `<wiki>` comment
    block removed, so re-curation never changes it.
    """
    source = _code_source_for_hash(self._lines, self._prefix)
    digest = hashlib.sha256(source.encode(self._ENCODING)).hexdigest()
    return digest[:_SRC_HASH_LEN]

  @property
  def stored_src_hash(self) -> str | None:
    """
    Current `src-hash:` value from the `<wiki>` block, or `None` when absent.
    """
    block = self._read_block()
    # guard: no block present
    if block is None:
      return None
    val = block.get(_FK_SRC_HASH)
    return str(val) if val else None

  @property
  def pinned_topics(self) -> str:
    """
    Current `pinned-topics:` value, or empty string when absent.
    """
    return self._pin_field(_FK_PINNED_TOPICS)

  @property
  def unrelated_topics(self) -> str:
    """
    Current `unrelated-topics:` value, or empty string when absent.
    """
    return self._pin_field(_FK_UNRELATED_TOPICS)

  @property
  def pinned_links(self) -> str:
    """
    Current `pinned-links:` value, or empty string when absent.
    """
    return self._pin_field(_FK_PINNED_LINKS)

  @property
  def unrelated_links(self) -> str:
    """
    Current `unrelated-links:` value, or empty string when absent.
    """
    return self._pin_field(_FK_UNRELATED_LINKS)

  # ── write ──────────────────────────────────────────────────────────────────

  def apply(
    self,
    *,
    wiki_summary: str,
    topics: list[str],
    see_also_lines: list[str],
    connectors: list[str] | None = None,
  ) -> None:
    """
    Write all wiki-managed fields in one atomic pass.

    The operation is idempotent: applying identical inputs twice produces
    byte-identical file content on the second call.

    Args:
      wiki_summary: One-line summary string (no newlines).
      topics: Full list of topic strings to set in the `topics:` field.
      see_also_lines: Lines to set as `see-also:` items (bare `path — gloss` strings).
      connectors: Short linkable-facet phrases for the `connectors:` field;
        `None` leaves the existing value untouched.
    """
    self.apply_classify(wiki_summary = wiki_summary, topics = topics, connectors = connectors)
    self.apply_link(see_also_lines = see_also_lines)

  def apply_classify(
    self,
    *,
    wiki_summary: str,
    topics: list[str],
    connectors: list[str] | None = None,
  ) -> None:
    """
    Write the classify-phase fields: `summary`, `topics`, `connectors`.

    Leaves `see-also`, all pin fields, and code outside the block untouched.
    The operation is idempotent.  The `connectors:` field lives inside the
    `<wiki>` block, which is excluded from `source_hash` in full, so writing
    it never perturbs the recorded `src-hash`.

    Args:
      wiki_summary: One-line summary string (no newlines).
      topics: Full list of topic strings to set.
      connectors: Short linkable-facet phrases for the `connectors:` field;
        `None` leaves the existing value untouched.
    """
    # Compute the source hash from the CURRENT content with the wiki block
    # excluded, so the hash reflects only operator-authored code.
    src_hash = hashlib.sha256(
      _code_source_for_hash(self._lines, self._prefix).encode(self._ENCODING)
    ).hexdigest()[:_SRC_HASH_LEN]

    current = self._read_block() or {}
    current[_FK_SUMMARY] = wiki_summary
    # Code topics are stored BARE (`<axis>/<value>`) — strip the `wiki/` prefix
    # the curator emits.  build-index re-adds `wiki/` for code nodes, so storing
    # the prefixed form here would double it (`wiki/wiki/<axis>/…`).
    current[_FK_TOPICS] = [
      t[len(_WIKI_TAG_PREFIX):] if t.startswith(_WIKI_TAG_PREFIX) else t
      for t in topics
    ]
    # guard: only rewrite connectors when the caller supplied them
    if connectors is not None:
      current[_FK_CONNECTORS] = connectors
    current[_FK_SRC_HASH] = src_hash
    self._write_block(current)

  def apply_link(
    self,
    *,
    see_also_lines: list[str],
  ) -> None:
    """
    Write the link-phase field: `see-also`.

    Leaves `summary`, `topics`, all pin fields, and code outside the block
    untouched.  The operation is idempotent.

    Args:
      see_also_lines: Lines to set as `see-also:` items.
    """
    current = self._read_block() or {}
    # Code see-also is stored bare — strip the leading markdown list bullet the
    # curator emits (`- [name](path) — gloss`) so the block renderer's own `  - `
    # is the only bullet (mirrors the bare-topics strip in apply_classify).
    current[_FK_SEE_ALSO] = [
      line[2:] if line.startswith("- ") else line
      for line in see_also_lines
    ]
    self._write_block(current)

  # ── helpers ───────────────────────────────────────────────────────────────

  def _pin_field(self, key: str) -> str:
    """
    Return a pin field value from the current `<wiki>` block, or empty string.

    Args:
      key: Internal field name (e.g. `pinned_topics`).

    Returns:
      String value or empty string when absent.
    """
    block = self._read_block()
    # guard: no block
    if block is None:
      return ""
    val = block.get(key)
    return str(val) if val else ""

  def _read_block(self) -> dict[str, str | list[str]] | None:
    """
    Parse the current `<wiki>` block from `_lines`, or return `None`.

    Returns:
      Parsed field dict, or `None` when no block is present.
    """
    span = _find_wiki_block(self._lines, self._prefix)
    # guard: no block present
    if span is None:
      return None
    start, end = span
    return _parse_wiki_block(self._lines, start, end, self._prefix)

  def _write_block(self, fields: dict[str, str | list[str]]) -> None:
    """
    Write a `<wiki>` block with `fields` into the file, replacing any existing block.

    If no block exists, inserts at the canonical location (after shebang and
    header comments, before code).  Existing code outside the block is
    preserved byte-for-byte.

    Args:
      fields: Dict of field name → value to emit.
    """
    block_lines = _render_wiki_block_lines(fields, self._prefix)
    # Add trailing newlines to each rendered line
    block_with_nl = [ ln + "\n" for ln in block_lines ]
    # Ensure a blank separator line after the block (before code)
    block_with_nl.append("\n")

    span = _find_wiki_block(self._lines, self._prefix)
    if span is not None:
      start, end = span
      # Replace lines[start:end+1] with the new block lines
      # Preserve the separator blank line that may already follow the block
      after_block = end + 1
      # guard: skip a blank line that was already the separator to avoid doubling
      if after_block < len(self._lines) and self._lines[after_block].strip() == "":
        after_block += 1
      new_lines = self._lines[:start] + block_with_nl + self._lines[after_block:]
    else:
      insert_at = _locate_header_end(self._lines, self._prefix)
      new_lines = self._lines[:insert_at] + block_with_nl + self._lines[insert_at:]

    self._lines = new_lines
    self._text = "".join(new_lines)
    self._path.write_text(self._text, encoding = self._ENCODING)


# ────────────────────────────────────────────────────────────────────────────
# Public factory
# ────────────────────────────────────────────────────────────────────────────

def set_scalar_field(text: str, key: str, value: str) -> str:
  """
  Set a scalar frontmatter `key` to `value`, preserving all other text.

  Public wrapper over the module's surgical frontmatter editor, used by the
  CLI to write the `wiki_synced_sha` anchor into a topics.md document without
  reaching into a private name across the module boundary.  Synthesises a
  frontmatter block when the document has none.

  Args:
    text: Full document text (may be empty for a brand-new file).
    key: Top-level YAML key to set.
    value: String value; must not contain newlines.

  Returns:
    Document text with the key set to `value`.
  """
  return _set_scalar_field(text, key, value)


def get_scalar_field(text: str, key: str) -> str | None:
  """
  Return the string value of a scalar frontmatter `key`, or `None` when absent.

  Public wrapper over the module's surgical frontmatter reader, used by
  sibling bin-modules to read arbitrary top-level frontmatter keys (e.g. the
  `wiki_synced_sha` anchor on topics.md) without crossing into a private name.

  Args:
    text: Full document text.
    key: Top-level YAML key to look up.

  Returns:
    Stripped scalar value, or `None` when absent or blank.
  """
  return _get_scalar_field(text, key)


def node_for(path: Path) -> MarkdownNode | CodeNode | None:
  """
  Return the appropriate node object for `path`, or `None` for unrecognised types.

  Returns a `MarkdownNode` for `.md` files, a `CodeNode` for any extension
  listed in `_COMMENT_STYLE_MAP`, and `None` for everything else.

  Args:
    path: Absolute (or relative) path to the source file.

  Returns:
    A `MarkdownNode`, `CodeNode`, or `None`.
  """
  ext = path.suffix.lower()
  if ext == _MD_SUFFIX:
    return MarkdownNode(path = path)
  style = _comment_style(ext)
  # guard: unrecognised extension — not a supported code node
  if style is None:
    return None
  return CodeNode(path = path, prefix = style)
