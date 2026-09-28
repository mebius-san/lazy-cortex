"""Shared markdown-text primitives for the specs `bin/` tree: frontmatter and code fences.

One place locates a note's leading frontmatter block, parses its flat scalars, splices a line in
before its closing fence, renders a scalar the way YAML reads it back verbatim, and reads or
rewrites a list-typed key. Every writer in this tree edits frontmatter as text, so these helpers
are what keep those edits from breaking the block. The code-fence mask tells body scanners which
lines sit inside a fenced block, where nothing is structure.
"""
from __future__ import annotations

import json
import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterator


# Named groups of `_BLOCK_RE`: the key lines inside the block, the closing fence line.
_GROUP_BODY = "body"
_GROUP_CLOSE = "close"

# The leading block: an optional byte-order mark, an opening `---` line, the lazily-shortest run of whole lines, and a closing
# `---` line ended by a newline or the end of the text. The body group is lazily optional, so an
# empty block `---\n---\n` closes at once instead of stretching to a later `---` in the body.
_BLOCK_RE = re.compile(
    rf"\A\ufeff?---[ \t]*\r?\n(?P<{_GROUP_BODY}>(?:.*?\n)??)(?P<{_GROUP_CLOSE}>---[ \t]*(?:\r?\n|\Z))",
    re.DOTALL)

# A list key's own line, at column 0: the key, optional blanks, the colon; the value follows.
_KEY_LINE_RE_TEMPLATE = r"{key}[ \t]*:"

# A block-list item line — any indentation, a `-` followed by whitespace or the line end, so a
# `---` fence is never an item.
_ITEM_RE = re.compile(r"^[ \t]*-(?:[ \t]|$)")

# One member of a flow list: a double-quoted, a single-quoted, or a bare comma-free run.
_FLOW_ITEM_RE = re.compile(r'[ \t]*(?:"(?:[^"\\]|\\.)*"|\'(?:[^\']|\'\')*\'|[^,]+)')

# The flow-list brackets, a comment's opening character, and the plain scalars YAML reads as null.
_FLOW_OPEN = "["
_FLOW_CLOSE = "]"
_COMMENT = "#"
_NULLS = frozenset({ "", "~", "null" })
_INDENT = ( " ", "\t" )

# The characters a comment's `#` may follow inside a multi-line value.
_BLANKS = ( " ", "\t", "\n" )

# Characters that give a plain scalar's first position a YAML meaning of its own.
_INDICATORS = "-?:,[]{}#&*!|>'\"%@`"

# The two quote characters a single-line YAML scalar can be wrapped in.
_DOUBLE_QUOTE = '"'
_SINGLE_QUOTE = "'"

# A code-fence line: up to three spaces of indent, a run of three or more backticks or tildes,
# then the info string (or nothing, on a closing fence).
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_BACKTICK = "`"

# The two comment forms a fence line cannot open inside: an HTML comment and an Obsidian `%%` one,
# each keyed by its opener and mapped to its closer.
_COMMENT_CLOSERS = { "<!--": "-->", "%%": "%%" }

# A comment-opening line: up to three spaces of indent, then `<!--` or `%%` (CommonMark HTML block
# type 2, Obsidian block comment); a mid-line opener is ordinary text.
_COMMENT_OPEN_RE = re.compile(r" {0,3}(<!--|%%)")

# A closer may overlap its opener by this many characters, so `<!-->` and `<!--->` close at once.
_CLOSER_OVERLAP = 2

# A column-0 line that ends a flow list's span: the next key.
_COL0_KEY_RE = re.compile(r"[^\s#-][^:]*:(\s|$)")

# The frontmatter block's closing fence, when the scan runs over a text without a matched block.
_CLOSE_FENCE_RE = re.compile(r"---[ \t]*\r?\n?\Z")

# The line break every line splitter here honours; `\r\n` is the same break with a carriage return.
_LF = "\n"
_CR = "\r"


def block(text: str) -> tuple[str, int]:
  """
  Locate the leading frontmatter block.

  Guarantees:
    - Recognizes the block whether its line endings are LF or CRLF, and behind a leading
      byte-order mark, which stays outside the returned key lines.
    - Recognizes an empty block and a block whose closing fence ends the text without a
      trailing newline.

  Args:
    text: The full note text to search for a leading frontmatter block.

  Returns:
    A tuple of the block's inner key-lines text and the offset just past the closing fence, or
    an empty string and offset zero when the text carries no frontmatter block.
  """
  match = _BLOCK_RE.match(text)
  return ( match.group(_GROUP_BODY), match.end() ) if match else ( "", 0 )


def parse(text: str) -> tuple[dict, int]:
  """
  Parse the leading frontmatter block's flat scalars.

  Args:
    text: The full note text to parse.

  Returns:
    A tuple of a dict mapping each scalar key to its unquoted value, less any trailing comment
    outside quotes, and the offset just past the block's closing fence. List items, comments,
    and blank lines contribute no entries.
  """
  lines, end = block(text)

  # one entry per `key: value` line; list items, comments, and blank lines carry no scalar
  values: dict = {}
  for line in split_lines(lines):
    stripped = line.strip()

    # guard: skip blank lines, comments, list items, and lines without a separator
    if not stripped or stripped.startswith(("#", "-")) or ":" not in line:
      continue
    key, _, val = line.partition(":")

    # guard: skip entries with an empty key
    if not key.strip():
      continue
    values[key.strip()] = unquote_scalar(strip_comment(val.strip()))
  return values, end


def insert_before_close(fm_text: str, lines: str) -> str:
  """
  Splice lines into the frontmatter block, right before its closing fence.

  Args:
    fm_text: The full note text carrying a leading frontmatter block.
    lines: The text to insert, placed immediately before the closing fence.

  Returns:
    The text with `lines` spliced in, or `fm_text` unchanged when no complete frontmatter
    block is found.
  """
  match = _BLOCK_RE.match(fm_text)

  # guard: no complete block to splice into
  if match is None:
    return fm_text
  close = match.start(_GROUP_CLOSE)
  return fm_text[:close] + lines + fm_text[close:]


def yaml_scalar(value: str) -> str:
  """
  Render a string as a single-line YAML scalar that reads back as exactly that string.

  Args:
    value: The string to render.

  Returns:
    The value written bare when YAML would read it back verbatim, otherwise a double-quoted,
    escaped, single-line form.
  """
  needs_quotes = (
      not value
      or value != value.strip()
      or value[0] in _INDICATORS
      or ": " in value
      or " #" in value
      or value.endswith(":")
      or any(char < " " for char in value)
  )
  return json.dumps(value, ensure_ascii = False) if needs_quotes else value


def unquote_scalar(raw: str) -> str:
  """
  Read a single-line YAML scalar's string value, removing its quotes.

  Args:
    raw: The raw scalar text as it appears after the colon in a `key: value` line.

  Returns:
    The scalar's string value with its surrounding quotes removed, resolving single-quote
    doubling or double-quote escapes. A scalar that is not quoted, or a double-quoted scalar
    that fails to decode, is returned exactly as written.
  """
  # guard: a bare scalar is its own value
  if len(raw) < 2 or raw[0] != raw[-1] or raw[0] not in ( _DOUBLE_QUOTE, _SINGLE_QUOTE ):
    return raw

  # a single-quoted scalar only doubles its own quote character
  if raw[0] == _SINGLE_QUOTE:
    return raw[1:-1].replace("''", _SINGLE_QUOTE)

  # a double-quoted scalar decodes through its escapes; one that does not decode stays as written
  try:
    decoded = json.loads(raw)
  except json.JSONDecodeError:
    return raw
  return decoded if isinstance(decoded, str) else raw


def set_scalar(fm_text: str, key: str, value: str) -> str:
  """
  Add or replace a scalar `key: value` line inside the frontmatter block.

  Args:
    fm_text: The full note text carrying a leading frontmatter block.
    key: The scalar's key name.
    value: The value to render for the key.

  Returns:
    The text with the key's line replaced in place when the key already exists, or inserted
    before the block's closing fence otherwise.
  """
  line = f"{key}: {yaml_scalar(value)}"
  pat = re.compile(rf"(?m)^{re.escape(key)}[ \t]*:.*$")
  if pat.search(fm_text):
    return pat.sub(lambda _m: line, fm_text, count = 1)
  return insert_before_close(fm_text, line + "\n")


def _value_span(fm_text: str, key: str) -> tuple[int, int, list[str]] | None:
  """
  Locate a key's whole value span: its own line plus every line its value runs on.

  Searches the leading frontmatter block when the text carries one, otherwise the whole text.
  A flow list runs to the line closing its bracket; any other value runs over the indented and
  item lines below it, including comment and blank lines that have more of the value after them.

  Args:
    fm_text: The text to search.
    key: The key's name.

  Returns:
    The span's start and end offsets in `fm_text` and its lines (endings kept), or None when the
    key is absent.
  """
  match = _BLOCK_RE.match(fm_text)
  base, scope = ( match.start(_GROUP_BODY), match.group(_GROUP_BODY) ) if match else ( 0, fm_text )
  lines = split_lines(scope, keepends = True)
  key_re = re.compile(_KEY_LINE_RE_TEMPLATE.format(key = re.escape(key)))
  first = next(( idx for idx, line in enumerate(lines) if key_re.match(line) ), None)

  # guard: the key is absent
  if first is None:
    return None
  value = _value_text(lines[first], key)
  end = first + 1

  # a flow list runs to the line that closes its bracket — its continuation lines and `]` may sit at
  # column 0, but the next column-0 key or the closing fence ends it; an unclosed list is its header
  # line alone
  if value.startswith(_FLOW_OPEN):
    stop = next(( idx for idx in range(first + 1, len(lines))
                  if _COL0_KEY_RE.match(lines[idx]) or _CLOSE_FENCE_RE.match(lines[idx]) ), len(lines))
    closed = next(( idx for idx in range(first, stop)
                    if _flow_end(_flow_text(lines[first:idx + 1], key)) >= 0 ), None)
    end = first + 1 if closed is None else closed + 1

  # any other value runs over its item and indented lines; a comment or blank line — at any
  # indentation — joins the span only when more of the value follows it
  else:
    idx = end
    while idx < len(lines):
      row = lines[idx].rstrip("\r\n")
      stripped = row.strip()
      if not stripped or stripped.startswith(_COMMENT):
        idx += 1
        continue
      if not (_ITEM_RE.match(row) or row.startswith(_INDENT)):
        break
      idx += 1
      end = idx
  start = base + sum(len(line) for line in lines[:first])
  return start, start + sum(len(line) for line in lines[first:end]), lines[first:end]


def _value_text(key_line: str, key: str) -> str:
  """
  Read the value written on a key's own line, a trailing-comment-only value read as empty.

  Args:
    key_line: The key's line.
    key: The key's name.

  Returns:
    The stripped text after the colon, less a trailing comment outside quotes; empty when only a
    comment follows it.
  """
  return strip_comment(_value_raw(key_line, key))


def _value_raw(key_line: str, key: str) -> str:
  """
  Read the text written after the colon on a key's own line, comments included.

  Args:
    key_line: The key's line.
    key: The key's name.

  Returns:
    The stripped text after the colon.
  """
  return re.sub(_KEY_LINE_RE_TEMPLATE.format(key = re.escape(key)), "", key_line, count = 1).strip()


def _unquoted(text: str) -> Iterator[tuple[int, str]]:
  """
  Walk a YAML scalar or flow text, yielding only the characters outside quoted scalars.

  A quote opens a quoted scalar only where one may start — at the text's start or after `[` or
  `,` — so an apostrophe inside a plain word never does. A comment — a `#` at a line's start or
  after a blank, outside quotes — yields its `#` and hides the rest of its line.

  Args:
    text: The value text to walk, possibly several lines joined by line feeds.

  Yields:
    Each character outside a quoted scalar and outside a comment's body, with its offset in `text`.
  """
  quote = ""
  prev = ""
  idx = 0
  while idx < len(text):
    char = text[idx]

    # inside a quoted scalar: a double-quoted one escapes with a backslash, a single-quoted one by
    # doubling its quote
    if quote:
      if quote == _DOUBLE_QUOTE and char == "\\":
        idx += 2
        continue
      if char == quote and quote == _SINGLE_QUOTE and text[idx + 1:idx + 2] == _SINGLE_QUOTE:
        idx += 2
        continue
      if char == quote:
        quote = ""
    elif char in ( _DOUBLE_QUOTE, _SINGLE_QUOTE ) and prev in ( "", _FLOW_OPEN, "," ):
      quote = char
    elif char == _COMMENT and (idx == 0 or text[idx - 1] in _BLANKS):
      # a comment runs to the end of its line: nothing in it closes a bracket or opens a quote
      yield idx, char
      line_end = text.find(_LF, idx)
      idx = len(text) if line_end < 0 else line_end
      continue
    else:
      yield idx, char
    if not char.isspace():
      prev = char
    idx += 1


def strip_comment(value: str) -> str:
  """
  Drop a trailing YAML comment — a `#` at the start or after a blank, outside quotes.

  Args:
    value: A stripped scalar, flow, or list-item text.

  Returns:
    The text before the comment, stripped; the text unchanged when it carries none, so `C#`,
    `a#b`, and a URL fragment stay whole.
  """
  for idx, char in _unquoted(value):
    if char == _COMMENT and (idx == 0 or value[idx - 1] in _INDENT):
      return value[:idx].rstrip()
  return value


def _flow_end(text: str) -> int:
  """
  Find the bracket that closes the flow list a text opens with, outside quotes and nesting.

  Args:
    text: The flow value, starting at its opening `[`.

  Returns:
    The closing bracket's offset in `text`, or -1 when the list never closes.
  """
  depth = 0
  for idx, char in _unquoted(text):
    if char == _FLOW_OPEN:
      depth += 1
    elif char == _FLOW_CLOSE:
      depth -= 1
      if depth == 0:
        return idx
  return -1


def _flow_text(lines: list[str], key: str) -> str:
  """
  Join a flow value's lines into one text, every YAML comment left out.

  A comment is a `#` at a line's start or after a blank, outside quotes, at any indentation, and
  runs to the end of its line — a whole-line comment inside the list contributes nothing.

  Args:
    lines: The key's line followed by the continuation lines to join.
    key: The key's name.

  Returns:
    The value from its opening `[` on, its lines joined by a blank, with no comment text.
  """
  raw = _LF.join([ _value_raw(lines[0], key), *( line.strip() for line in lines[1:] ) ])

  # each comment is cut from its `#` to the end of its line; quote state carries across lines
  cuts = [ idx for idx, char in _unquoted(raw) if char == _COMMENT and (idx == 0 or raw[idx - 1] in _BLANKS) ]
  kept: list[str] = []
  start = 0
  for cut in cuts:
    kept.append(raw[start:cut])
    line_end = raw.find(_LF, cut)
    start = len(raw) if line_end < 0 else line_end
  kept.append(raw[start:])
  return "".join(kept).replace(_LF, " ")


def read_list(fm_text: str, key: str) -> list[str]:
  """
  Read a list-typed key's members, in any YAML spelling.

  Guarantees:
    - A scalar value reads as a one-item list; a flow list may span several lines; comment and
      blank lines inside a block list do not end it.

  Args:
    fm_text: The full note text carrying a leading frontmatter block.
    key: The list key's name.

  Returns:
    The key's members, unquoted, from the block form (one item per line), the flow form
    (`key: [a, b]`), or a lone scalar. An empty list when the key is absent or null.
  """
  span = _value_span(fm_text, key)

  # guard: the key is absent
  if span is None:
    return []
  lines = span[2]
  value = _value_text(lines[0], key)

  # the flow form: the members between the brackets, over however many lines they run
  if value.startswith(_FLOW_OPEN):
    joined = _flow_text(lines, key)
    close = _flow_end(joined)
    inner = joined[1:close] if close >= 0 else joined[1:]
    members = [ item.strip() for item in _FLOW_ITEM_RE.findall(inner) ]
    return [ unquote_scalar(item) for item in members if item ]

  # a scalar is a one-item list; a null is none
  if value not in _NULLS:
    return [ unquote_scalar(value) ]

  # the block form: one member per item line, a trailing comment dropped
  items = [ strip_comment(line.strip()[1:].strip()) for line in lines[1:] if _ITEM_RE.match(line) ]
  return [ unquote_scalar(item) for item in items if item ]


def write_list(fm_text: str, key: str, values: list[str]) -> str:
  """
  Set a list-typed key, replacing its existing value in place or adding the key.

  Guarantees:
    - Writes an empty list as `key: []`.
    - Replaces the key's whole value span — a scalar, a multi-line flow list, or a block list with
      comment or blank lines inside — so no key line or member is ever left duplicated.
    - Leaves the comment and blank lines inside an existing block list in place when writing members.

  Args:
    fm_text: The full note text carrying a leading frontmatter block.
    key: The list key's name.
    values: The members to write for the key.

  Returns:
    The text with the key's value rewritten at its original location, or the key inserted before
    the block's closing fence when absent.
  """
  items = [ f"  - {yaml_scalar(value)}\n" for value in values ]
  replacement = f"{key}:\n{''.join(items)}" if values else f"{key}: []\n"
  span = _value_span(fm_text, key)

  # guard: absent key — add it before the closing fence
  if span is None:
    return insert_before_close(fm_text, replacement)
  start, end, lines = span

  # a block list with members to write keeps its comment and blank lines: each item line takes
  # the next member, spare item lines go, and extra members follow the last line of the value
  if values and _value_text(lines[0], key) in _NULLS:
    pending = list(items)
    kept = [ lines[0] ]
    for line in lines[1:]:
      if not _ITEM_RE.match(line):
        kept.append(line)
      elif pending:
        kept.append(pending.pop(0))
    if kept[-1][-1:] != "\n":
      kept[-1] += "\n"
    replacement = "".join([ *kept, *pending ])
  return fm_text[:start] + replacement + fm_text[end:]


def _fence_scan(lines: list[str]) -> tuple[list[bool], str]:
  """
  Walk a markdown body's lines, marking fenced ones and tracking the fence still open.

  A fence opens on a run of three or more backticks or tildes indented by at most three spaces
  — never a backtick run whose info string holds a backtick, which is inline code, and never
  inside an HTML `<!-- -->` or Obsidian `%% %%` comment block — and closes only on a bare run of
  the same character at least as long. A comment opener inside a fenced block is code.

  Args:
    lines: The markdown body's lines to scan.

  Returns:
    One boolean per line (`True` inside a fenced block or on a fence line), and the opening run
    of a fence left unclosed at the end, or an empty string when every fence closes.
  """
  mask: list[bool] = []
  opener = ""
  closer = ""
  for line in lines:
    fence = _FENCE_RE.match(line)

    # outside a block, a line inside a comment or opening one is prose: it only moves the
    # comment state, never opens a fence
    if not opener and (closer or not fence):
      closer = _comment_state(line, closer)
      mask.append(False)
      continue

    # outside a block, a fence line opens one; a backtick run with a backtick in its info string
    # is inline code, not a fence
    if not opener:
      if fence and fence.group(1)[0] == _BACKTICK and _BACKTICK in fence.group(2):
        fence = None
      opener = fence.group(1) if fence else ""
      mask.append(bool(fence))
      continue
    mask.append(True)

    # only a bare fence of the same character, at least as long, closes the open block
    if fence and fence.group(1)[0] == opener[0] and len(fence.group(1)) >= len(opener) \
        and not fence.group(2).strip():
      opener = ""
  return mask, opener


def _comment_state(line: str, closer: str) -> str:
  """
  Carry the comment-block state across one prose line.

  A comment block opens only on a line starting, after up to three spaces, with `<!--` or `%%`,
  and ends on the first line holding its closer — on the opening line itself when the closer
  follows the opener's first two characters. A mid-line opener, or one indented four or more
  spaces, is ordinary text.

  Args:
    line: A line outside any fenced block.
    closer: The closer of the comment open at the line's start, or an empty string.

  Returns:
    The closer of the comment still open at the line's end, or an empty string.
  """
  # guard: inside a comment, the first line holding its closer ends it
  if closer:
    return "" if closer in line else closer
  start = _COMMENT_OPEN_RE.match(line)

  # guard: the line opens no comment
  if start is None:
    return ""
  closer = _COMMENT_CLOSERS[start.group(1)]
  return "" if line.find(closer, start.start(1) + _CLOSER_OVERLAP) >= 0 else closer


def split_lines(text: str, *, keepends: bool = False) -> list[str]:
  """
  Split text into lines at `\\n` alone, the way `str.splitlines()` does for LF and CRLF text.

  Guarantees:
    - Breaks only at `\\n` (a `\\r\\n` pair being the same break); every other character — a lone
      `\\r`, a form feed, U+0085, U+2028, U+2029 — stays inside its line, so joining the lines
      with `\\n` rebuilds the LF text unchanged.

  Args:
    text: The text to split.
    keepends: When True, each line keeps its own `\\n` or `\\r\\n` ending.

  Returns:
    The lines, with no trailing empty entry for a text ending in a line break; an empty list for
    an empty text.
  """
  rows = text.split(_LF)
  tail = rows.pop()
  if keepends:
    lines = [ row + _LF for row in rows ]
  else:
    lines = [ row.removesuffix(_CR) for row in rows ]
  return [ *lines, tail ] if tail else lines


def fenced_lines(lines: list[str]) -> list[bool]:
  """
  Mark which lines of a markdown body belong to a fenced code block, fence lines included.

  Guarantees:
    - Recognizes fences opened with backticks or tildes, and closes an open fence only on a
      bare fence of the same character, at least as long as the one that opened it.
    - A backtick run whose info string holds a backtick is inline code, never a fence opener.

  Args:
    lines: The markdown body's lines to scan.

  Returns:
    One boolean per input line, `True` when the line sits inside a fenced block or is itself a
    fence line, in the same order as `lines`.
  """
  return _fence_scan(lines)[0]


def open_fence(lines: list[str]) -> str:
  """
  Report the fence a markdown body leaves unclosed at its end.

  Args:
    lines: The markdown body's lines to scan.

  Returns:
    The unclosed fence's opening run of backticks or tildes, or an empty string when every fence
    in the body closes.
  """
  return _fence_scan(lines)[1]
