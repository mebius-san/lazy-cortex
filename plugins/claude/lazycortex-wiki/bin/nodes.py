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

import hashlib
import json
import os
import re

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from markers import Markers  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from textfile import TextFile  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# ────────────────────────────────────────────────────────────────────────────
# Module-level helpers — private, not part of public API
# ────────────────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^---[ \t]*\r?$", re.MULTILINE)

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

# Namespace prefix the curator prepends to every topic tag.  Markdown nodes store
# it verbatim in `tags:`; a code `<wiki>` block stores BARE `<axis>/<value>`
# topics (build-index re-adds the prefix for code nodes).
_WIKI_TAG_PREFIX = "wiki/"

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

# Directory whose presence marks a repository root.
_GIT_DIR = ".git"

# Plain scalars YAML would read as a number, a timestamp, or a special float rather than a string.
_YAML_RETYPED_RE = re.compile(
  r"^(?:[-+]?(?:\d[\d_]*(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
  r"|0x[0-9a-fA-F_]+|0o?[0-7_]+|0b[01_]+"
  r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)"
  r"|\d{4}-\d\d?-\d\d?(?:[Tt ].*)?"
  r"|[-+]?\d+(?::[0-5]?\d)+(?:\.\d*)?)$"
)

# One escape sequence inside a double-quoted YAML scalar.
_DQ_ESCAPE_RE = re.compile(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)")

# Single-character double-quoted escapes and the characters they stand for.
_DQ_ESCAPES = {
  "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f",
  "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0",
  "L": "\u2028", "P": "\u2029",
}

# Radix of the code point a `\x` / `\u` / `\U` escape spells.
_HEX_BASE = 16

# Header value of a block scalar: a `|` or `>` style, then chomping and indentation indicators in
# either order, then an optional comment.
_BLOCK_SCALAR_RE = re.compile(r"^([|>])([-+]?)\d?([-+]?)\s*(?:#.*)?$")

# Block-scalar style and chomping indicators.
_LITERAL_STYLE = "|"
_CHOMP_STRIP = "-"
_CHOMP_KEEP = "+"

# Quote characters of the two quoted YAML scalar styles.
_SINGLE_QUOTE = "'"
_DOUBLE_QUOTE = '"'

# Character that opens a YAML comment when it starts a value or follows whitespace outside quotes.
_COMMENT_CHAR = "#"

# Characters YAML reads as a line break, and the double-quoted escapes that keep each on one line.
_LINE_BREAK_ESCAPES = { "\n": "\\n", "\r": "\\r", "\x85": "\\N", "\u2028": "\\L", "\u2029": "\\P" }


def _repo_root_for(node_path: Path) -> Path | None:
  """
  Return the nearest ancestor directory of `node_path` that holds a `.git` entry.

  Args:
    node_path: Absolute path to a node file.

  Returns:
    The repository root, or `None` when no ancestor carries `.git`.
  """
  for parent in node_path.resolve().parents:
    # guard: this ancestor is a repository root
    if (parent / _GIT_DIR).exists():
      return parent
  return None


def resolve_see_also_target(target: str, node_path: Path) -> Path | None:
  """
  Resolve a same-repo See-also target against every base the wiki has ever written.

  The canonical base is the directory of the node carrying the link. Targets written
  against a coarser base (the scope root, the repo root) still resolve: after the node
  directory, each ancestor directory up to and including the repo root is tried in turn,
  nearest first.

  Guarantees:
    - A returned path names an existing file inside the repository that holds the node.
    - A target matching no file under any base resolves to `None`, never to a path that does not exist.

  Args:
    target: Raw link target string from a See-also entry.
    node_path: Absolute path of the node file carrying the link.

  Returns:
    Absolute path of the existing target file, or `None` when the target
    resolves to no file under any base.
  """

  # Contract:
  # A returned path always names an existing file inside the repository that holds the node;
  # resolution never widens past that repository.

  # Contract:
  # A target that matches no file under any base resolves to `None`. An unresolved target is
  # NEVER guessed at, and no path that does not exist is ever returned.

  # Domain(wiki.graph):
  # # Where a link between nodes is written from
  # A link is addressed relative to the node that carries it, so one and the same edge between two nodes is
  # spelled differently in every node that holds it. That node-relative spelling is the canonical one, and it
  # is the only one curation ever writes.
  # Older addressing forms wrote the target against a coarser starting point — the root of the scope or of the
  # repository — and those links still name a real neighbour. A target is therefore looked for from the node's
  # own place first and then from ever wider surroundings, the nearest one that finds a real file winning. The
  # search never widens past the repository, and a node lying outside one has nowhere to widen to at all. A
  # target found from no starting point is left written exactly as it stands, because rewriting it would
  # invent a neighbour that does not exist.
  # Comparing links stated by different nodes needs one shared spelling, so an edge is identified by the place
  # of its target within the repository — the same string no matter which node states the link.

  # every base is bounded by the repository, so a node outside one has nothing to resolve against
  repo = _repo_root_for(node_path)

  # guard: node lives outside any repository — no base to try
  if repo is None:
    return None

  # the canonical base is the node's own directory — try it before widening
  node_dir = node_path.resolve().parent
  candidate = (node_dir / target).resolve()

  # guard: already written against the canonical base, and lands inside the repository
  if candidate.is_file() and repo in candidate.parents:
    return candidate

  # an older curator run may have written the target against a coarser base
  for base in node_dir.parents:
    # guard: walked above the repo root — stop widening
    if base != repo and repo not in base.parents:
      break
    candidate = (base / target).resolve()
    if candidate.is_file():
      return candidate
  return None


def normalize_see_also_target(target: str, node_path: Path) -> str:
  """
  Rewrite a See-also target to the canonical node-directory-relative spelling.

  A target that already uses the canonical base is returned unchanged, so the rewrite
  is idempotent. Targets that resolve to no file are returned verbatim — a rewrite
  would invent a path.

  Guarantees:
    - Normalisation is idempotent: a target already in canonical spelling is returned unchanged.
    - A target that resolves to no file is returned verbatim, byte for byte.

  Args:
    target: Raw link target string from a See-also entry.
    node_path: Absolute path of the node file carrying the link.

  Returns:
    The canonical target string.
  """

  # Contract:
  # Normalisation is idempotent: a target already written in the canonical spelling is
  # returned unchanged, so repeated passes never churn a node.

  # Contract:
  # A target that resolves to no file is returned verbatim, byte for byte; the operator's
  # string is NEVER rewritten into a path that does not exist.

  # resolve first — the canonical spelling can only be derived from a real file
  abs_target = resolve_see_also_target(target, node_path)

  # guard: unresolvable — leave the operator's string alone
  if abs_target is None:
    return target
  return os.path.relpath(abs_target, node_path.resolve().parent)


def normalize_see_also_line(line: str, node_path: Path) -> str:
  """
  Rewrite every markdown link target in one See-also item to the canonical base.

  Only markdown-link targets (`[text](path)`) are rewritten; a bare-path item carries
  no link syntax and is returned unchanged.

  Guarantees:
    - An item carrying no markdown-link syntax is returned unchanged.

  Args:
    line: One See-also item string, with or without its leading list bullet.
    node_path: Absolute path of the node file carrying the item.

  Returns:
    The item with canonical link targets.
  """

  # Contract:
  # An item carrying no markdown-link syntax (a bare path) is returned completely unchanged;
  # only `[text](path)` link targets inside the item are ever rewritten.

  def _rewrite(match: re.Match) -> str:
    raw = match.group(0)
    target = match.group(1).strip()
    canonical = normalize_see_also_target(target, node_path)
    return raw.replace(f"({match.group(1)})", f"({canonical})", 1)

  # a bare-path item carries no link syntax, so the substitution leaves it untouched
  return _SEE_ALSO_LINK_RE.sub(_rewrite, line)


def repo_relative_see_also_target(target: str, node_path: Path) -> str:
  """
  Express a See-also target as a repo-relative POSIX path for comparison purposes.

  This is the identity form used to compare edges across nodes (each node writes its
  targets against its own directory, so the stored strings are not comparable).
  Unresolvable targets are returned verbatim.

  Guarantees:
    - One target file yields one and the same string whichever node states the link to it.

  Args:
    target: Raw link target string from a See-also entry.
    node_path: Absolute path of the node file carrying the link.

  Returns:
    Repo-relative POSIX path string, or the original target when it cannot be resolved.
  """

  # Contract:
  # The returned string is the identity of an edge: one and the same target file yields one
  # and the same string whichever node states the link to it.

  # resolve first — an identity form can only be derived from a real file
  abs_target = resolve_see_also_target(target, node_path)

  # guard: unresolvable — nothing to express
  if abs_target is None:
    return target
  repo = _repo_root_for(node_path)

  # guard: no repository root to anchor against
  if repo is None:
    return target
  try:
    return abs_target.relative_to(repo).as_posix()
  except ValueError:
    return target


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

  # search for the closing fence past the opening one, honouring either line ending
  after_open = len("---\r\n") if text.startswith("---\r\n") else len("---\n")
  rest = text[after_open:]
  match = _FENCE_RE.search(rest)

  # guard: no closing fence — treat as no frontmatter rather than hard error
  if match is None:
    return None

  # re-anchor the match offsets onto the full document
  close_start = after_open + match.start()
  close_end = after_open + match.end()

  # take the newline after the closing fence into the span so the body starts clean
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

  # the entry runs from its header line to the newline that ends it
  start = match.start()
  cursor = block.find("\n", match.end())

  # guard: key is on the last line with no trailing newline
  if cursor == -1:
    return start, len(block)

  # indented lines and list items continue the entry; anything else at column 0 ends it
  cursor += 1
  kept = cursor
  while cursor < len(block):
    next_nl = block.find("\n", cursor)
    line_end = next_nl if next_nl != -1 else len(block)
    line = block[cursor:line_end]
    cursor = (line_end + 1) if next_nl != -1 else line_end

    # guard: a blank line belongs to the entry only when a continuation line follows it
    if not line.strip():
      continue

    # guard: a column-0 line that is no list item — a key, a comment — is not this entry's
    if not (line[0] in (" ", "\t") or line == "-" or line.startswith("- ")):
      break
    kept = cursor

  # the span is what a caller replaces to rewrite the whole entry at once
  return start, kept


def _parse_tags_block(block: str) -> list[str]:
  """
  Parse all tag values from a `tags:` key entry in the frontmatter block.

  Accepts a block-sequence entry, an inline flow sequence, or a bare scalar value, so any of the
  three input shapes yields the same tag list.

  Args:
    block: The raw text of the `tags:` key entry (header + continuation lines).

  Returns:
    List of tag strings in their original order, with quoting stripped.
  """
  lines = [ _strip_yaml_comment(line) for line in block.splitlines() ]
  after_colon = lines[0].partition(":")[2].strip() if lines else ""

  # Flow sequence, possibly spread over several lines — e.g. `tags: [foo,\n  "baz, qux"]`
  if after_colon.startswith("["):
    flow = " ".join([ after_colon, *( line.strip() for line in lines[1:] ) ])
    close = flow.rfind("]")
    inner = flow[1:close] if close > 0 else flow[1:]
    return [ _yaml_unquote(item) for item in _split_flow_items(inner) if item ]

  # guard: a scalar on the header line is a single tag
  if after_colon:
    return [ _yaml_unquote(after_colon) ]

  # Block sequence — continuation lines starting with `- `
  tags: list[str] = []
  for line in lines[1:]:
    stripped = line.strip()

    # guard: not a list item
    if not stripped.startswith("- "):
      continue
    tags.append(_yaml_unquote(stripped[2:].strip()))
  return tags


def _split_flow_items(inner: str) -> list[str]:
  """
  Split the inside of a YAML flow sequence on the commas that separate its items.

  Args:
    inner: Text between the flow sequence's brackets.

  Returns:
    The stripped item texts, quoting kept, with commas inside quoted items left in place.
  """
  items: list[str] = []
  current: list[str] = []
  quote = ""
  i = 0

  # one pass, tracking which quoted scalar (if any) the cursor is inside
  while i < len(inner):
    char = inner[i]
    if quote == _DOUBLE_QUOTE and char == "\\":
      current.append(inner[i:i + 2])
      i += 2
      continue
    if quote and char == quote:
      # a doubled single quote is an escaped quote, not the closing one
      if quote == _SINGLE_QUOTE and inner[i + 1:i + 2] == _SINGLE_QUOTE:
        current.append(char * 2)
        i += 2
        continue
      quote = ""
    elif not quote and char in ( _SINGLE_QUOTE, _DOUBLE_QUOTE ) and not "".join(current).strip():
      quote = char
    elif not quote and char == ",":
      items.append("".join(current).strip())
      current = []
      i += 1
      continue
    current.append(char)
    i += 1

  # the last item has no trailing comma to flush it
  items.append("".join(current).strip())
  return items


def _strip_yaml_comment(value: str) -> str:
  """
  Remove a trailing YAML comment from one line of a value.

  Args:
    value: One frontmatter line fragment, possibly holding quoted scalars.

  Returns:
    The fragment up to the first `#` that starts it or follows whitespace outside any quoted scalar,
    right-stripped; the fragment unchanged when it carries no comment.
  """
  quote = ""
  pos = 0

  # one pass, tracking which quoted scalar (if any) the cursor is inside
  while pos < len(value):
    char = value[pos]
    if quote == _DOUBLE_QUOTE and char == "\\":
      pos += 2
      continue
    if quote and char == quote:
      # a doubled single quote is an escaped quote, not the closing one
      if quote == _SINGLE_QUOTE and value[pos + 1:pos + 2] == _SINGLE_QUOTE:
        pos += 2
        continue
      quote = ""
    elif not quote and char in ( _SINGLE_QUOTE, _DOUBLE_QUOTE ):
      quote = char
    elif not quote and char == _COMMENT_CHAR and (pos == 0 or value[pos - 1] in " \t"):
      return value[:pos].rstrip()
    pos += 1

  # no comment on this line
  return value


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

  # any YAML line break — LF, CR, NEL, line or paragraph separator — breaks the single-line value contract
  if any(char in value for char in _LINE_BREAK_ESCAPES):
    return True

  # a plain number, timestamp, or special float would be read back as something other than a string
  return bool(_YAML_RETYPED_RE.match(value))


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

  # guard: a line break only survives on one line as a double-quoted escape
  if any(char in value for char in _LINE_BREAK_ESCAPES):
    rendered = json.dumps(value, ensure_ascii = False)
    for char, escape in _LINE_BREAK_ESCAPES.items():
      rendered = rendered.replace(char, escape)
    return rendered
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

  # guard: double-quoted form — strip the outer quotes and resolve the escapes
  if len(value) >= _MIN_QUOTED_LEN and value[0] == '"' and value[-1] == '"':
    return _DQ_ESCAPE_RE.sub(_dq_unescape, value[1:-1])
  return value


def _dq_unescape(match: re.Match) -> str:
  """
  Return the character one double-quoted YAML escape sequence stands for.

  Args:
    match: Match of one escape sequence, its code (without the backslash) in group 1.

  Returns:
    The escaped character, or the sequence unchanged when YAML defines no such escape.
  """
  code = match.group(1)

  # guard: a hex escape carries its code point after the escape letter
  if len(code) > 1:
    return chr(int(code[1:], _HEX_BASE))
  return _DQ_ESCAPES.get(code, match.group(0))


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

  # every edit happens inside the fences; the body text is spliced back untouched
  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)

  # an absent key is appended, a present one is replaced whole
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

  # every edit happens inside the fences; the body text is spliced back untouched
  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, _KEY_TAGS)

  # an empty list means the key goes away entirely, not an empty sequence
  if not new_tags:
    # guard: no tags and no existing key — nothing to change
    if existing is None:
      return text

    # Remove the existing entry entirely
    start, end = existing
    new_block = block[:start] + block[end:]
    return text[:open_end] + new_block + text[close_start:]

  # the same rendered sequence serves both the append and the replace path
  rendered = _render_tags_block(new_tags)

  # Rendered block already ends with `\n` so no extra suffix needed
  if existing is None:
    if block and not block.endswith("\n"):
      new_block = block + "\n" + rendered
    else:
      new_block = block + rendered
    return text[:open_end] + new_block + text[close_start:]

  # swap the old entry for the new one, leaving neighbouring keys exactly as they were
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
    lines.append(f"  - {_yaml_scalar(value)}")
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

  # every edit happens inside the fences; the body text is spliced back untouched
  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)

  # an empty list means the key goes away entirely, not an empty sequence
  if not new_values:
    # guard: no values and no existing key — nothing to change
    if existing is None:
      return text
    start, end = existing
    new_block = block[:start] + block[end:]
    return text[:open_end] + new_block + text[close_start:]

  # the same rendered sequence serves both the append and the replace path
  rendered = _render_block_seq(key, new_values)

  # Rendered block already ends with `\n` so no extra suffix needed
  if existing is None:
    if block and not block.endswith("\n"):
      new_block = block + "\n" + rendered
    else:
      new_block = block + rendered
    return text[:open_end] + new_block + text[close_start:]

  # swap the old entry for the new one, leaving neighbouring keys exactly as they were
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

  # only the frontmatter block can hold the key
  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)

  # guard: key not found
  if existing is None:
    return None

  # a scalar lives on the header line, after the colon — continuation lines are not one
  start, end = existing
  entry = block[start:end]
  header_line = entry.split("\n")[0]
  after_colon = _strip_yaml_comment(header_line.partition(":")[2].strip())

  # guard: empty post-colon means the key has no scalar value on its header line
  if not after_colon:
    return None

  # a block scalar keeps its value on the indented lines below the indicator
  block_style = _BLOCK_SCALAR_RE.match(after_colon)
  if block_style is not None:
    style, chomp_a, chomp_b = block_style.groups()
    # the entry span stops at its last content line; the blank lines after it are chomping material
    trailing = re.match(r"(?:[ \t]*\n)*", block[end:])
    scalar_text = entry + (trailing.group(0) if trailing else "")
    lines = scalar_text.split("\n")[1:]
    # a terminating line break is not a blank line of its own
    if scalar_text.endswith("\n"):
      lines.pop()
    return _read_block_scalar(lines, style, chomp_a or chomp_b)
  return _yaml_unquote(after_colon)


def _read_block_scalar(lines: list[str], style: str, chomp: str) -> str:
  """
  Return the value a literal or folded YAML block scalar spells.

  Args:
    lines: The block scalar's content lines, below its header line, including any trailing blank
      lines after the last content line.
    style: `|` for a literal scalar, `>` for a folded one.
    chomp: `-` (strip) drops every trailing line break, empty (clip) keeps exactly one final line
      break, `+` (keep) keeps the final line break plus one per trailing blank line after the last
      content line.

  Returns:
    The scalar's string value.
  """
  # trailing blank lines are chomping material, not content: count them for keep chomping
  trailing_breaks = 0
  while lines and not lines[-1].strip():
    lines = lines[:-1]
    trailing_breaks += 1
  indents = [ len(line) - len(line.lstrip()) for line in lines if line.strip() ]
  indent = min(indents) if indents else 0
  body = [ line[indent:] if line.strip() else "" for line in lines ]

  # a literal scalar keeps its line breaks; a folded one joins lines, a blank line marking a break
  if style == _LITERAL_STYLE:
    text = "\n".join(body)
  else:
    text = ""
    for line in body:
      if not line:
        text += "\n"
      elif text and not text.endswith("\n"):
        text += " " + line
      else:
        text += line

  # strip drops every trailing line break, clip keeps exactly one, keep also keeps one per blank line
  if chomp == _CHOMP_STRIP:
    return text
  # an empty scalar has no final line break of its own
  final_break = "\n" if text else ""
  if chomp == _CHOMP_KEEP:
    return text + final_break + "\n" * trailing_breaks
  return text + final_break


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

  # only the frontmatter block can hold the key
  open_end, close_start, _ = span
  block = text[open_end:close_start]
  existing = _key_block_span(block, key)

  # guard: key not found
  if existing is None:
    return []

  # the shared parser handles both the block-sequence and inline-flow shapes
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

  # Domain(wiki.graph):
  # # When a node counts as changed
  # Curation must never make a node look edited, or every pass would hand the next one work to redo. What
  # counts as a node's own content is therefore only what the operator wrote: the curated facets are cut away
  # first, and the remainder is read with trailing spaces and blank edges ignored, so that reformatting noise
  # and the gap left behind by a removed facet both pass unnoticed.
  # A short fingerprint of that remainder is kept with the node. It records which curated state belongs to
  # which authored text, so a pass that has lost its bearing in the repository history can still tell the
  # nodes whose text has moved on from those whose text still stands as it was curated.

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
  non_wiki = [ t for t in _get_array_field(out, _KEY_TAGS) if not t.startswith(_WIKI_TAG_PREFIX) ]
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
  end_marker = f"<!-- auto:{Markers.SEE_ALSO_MARKER_ID}:end -->"
  region = Markers().find_region(text, Markers.SEE_ALSO_MARKER_ID)

  # guard: markers absent — nothing to strip
  if region is None:
    return text
  start_idx, end_idx = region
  end_idx += len(end_marker)

  # Pull the cut back over a preceding See-also heading (and its owner-tag line) if present.
  heading = Markers.SEE_ALSO_HEADING
  head_idx = text.rfind(heading, 0, start_idx)
  between = text[head_idx:start_idx].replace("\r\n", "\n").strip() if head_idx != -1 else ""
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

  Guarantees:
    - Every part of the document outside the four wiki-owned regions survives a write byte-for-byte.
    - The four operator-pin frontmatter keys are read and never written.
    - Each write phase touches only the regions it owns: classifying leaves the `# See also` section
      alone, and linking leaves frontmatter alone.
    - Every write operation is idempotent: identical inputs leave byte-identical content on the second call.
    - A write preserves the file's original line ending; a file read with CRLF stays CRLF.
  """

  # Contract:
  # Every part of the document outside the four wiki-owned regions survives a write byte-for-byte:
  # other frontmatter keys with their block style, comments and quoting, non-`wiki/` tags, body
  # prose, headings, and any section another tool owns.

  # Contract:
  # The four operator-pin keys — `wiki_pinned_topics`, `wiki_unrelated_topics`, `wiki_pinned_links`
  # and `wiki_unrelated_links` — are read-only: they are read and NEVER written.

  # Contract:
  # Each write phase touches only the regions it owns. Classifying leaves the `# See also` section
  # untouched, and linking leaves every frontmatter key untouched.

  # Contract:
  # Every write operation is idempotent: applying identical inputs twice leaves byte-identical file
  # content on the second call.

  # Contract:
  # A write preserves the file's original line ending: a file read with CRLF line endings is written
  # back with CRLF, never silently converted to LF.

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

  def __init__(self, *, path: Path) -> None:
    """
    Load the markdown file at `path` into memory.

    Args:
      path: Absolute path to the markdown file to manage.
    """
    self._path = path
    self._file = TextFile(path = path)
    self._text = self._file.read()
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
    return [ t for t in self.tags if t.startswith(_WIKI_TAG_PREFIX) ]

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
    Set of forward See-also link target paths, expressed repo-relative.

    Parses `[text](path)` link entries from the `# See also` marker block. Stored
    targets are relative to this node's own directory, so each one is re-expressed as
    a repo-relative POSIX path — the identity form in which edges from different nodes
    are comparable. Unresolvable targets are kept verbatim. Empty
    when the See-also section is absent or empty. Used by `dispatch-link` to skip
    back-link dispatches for attractor nodes that already forward-link to the target.

    Guarantees:
      - Every returned target is in the shared repo-relative identity form, so the same target
        file compares equal whichever node states the link to it.
    """

    # Contract:
    # Every target in the returned set is expressed in the shared repo-relative identity form,
    # so the same target file compares equal whichever node states the link to it.

    inner = self.see_also_inner

    # guard: no See-also section — no outgoing edges
    if not inner:
      return set()
    return {
      repo_relative_see_also_target(m.group(1).strip(), self._path)
      for m in _SEE_ALSO_LINK_RE.finditer(inner)
    }

  @property
  def source_hash(self) -> str:
    """
    Stable hash of the operator-authored source, excluding managed regions.

    The hash is computed over the document with every wiki-managed region
    removed (`wiki_summary` / `wiki_src_hash` keys, `wiki/*` tags, and the
    `# See also` section), so re-curation never changes it.

    Guarantees:
      - The value changes only when operator-authored content changes; a wiki write never moves it.
    """

    # Contract:
    # The value covers operator-authored content only. A write to any wiki-managed region NEVER
    # changes it, so a re-curated node still reads as unchanged.

    # a short digest is enough to tell one authored revision from another
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
    see_also_lines: list[str],
    wiki_summary: str | None = None,
    topics: list[str] | None = None,
    connectors: list[str] | None = None,
  ) -> None:
    """
    Write all three wiki-managed regions in one atomic pass.

    Guarantees:
      - Applying identical `wiki_summary`, `topics`, `connectors`, and `see_also_lines`
        twice produces byte-identical file content on the second call.
      - Non-`wiki/`-prefixed tags survive untouched; only the `wiki/*` subset is replaced.
      - A `None` `wiki_summary` or `topics` argument leaves the currently stored value unchanged.

    Args:
      see_also_lines: Ready-to-graft markdown list-item strings for the
        See-also section, one per list item.  An empty list produces an
        empty (but present) managed block.
      wiki_summary: One-line summary string (no newlines); `None` leaves the currently stored
        value unchanged.
      topics: Full list of `wiki/<axis>/<value>` tag strings to apply.
        These replace the current `wiki/*` subset; non-`wiki/` tags survive. `None` leaves the
        currently stored subset unchanged.
      connectors: Short linkable-facet phrases for `wiki_connectors`; `None`
        leaves the existing block untouched, an empty list removes it.
    """
    self.apply_classify(wiki_summary = wiki_summary, topics = topics, connectors = connectors)
    self.apply_link(see_also_lines = see_also_lines)

  def apply_classify(
    self,
    *,
    wiki_summary: str | None = None,
    topics: list[str] | None = None,
    connectors: list[str] | None = None,
    stamp_src_hash: bool = True,
  ) -> None:
    """
    Write the classify-phase managed regions: `wiki_summary`, `wiki/*` tags, `wiki_connectors`.

    Leaves the `# See also` section (and any other body content) untouched.

    Guarantees:
      - Applying identical `wiki_summary`, `topics`, and `connectors` twice produces
        byte-identical file content on the second call.
      - Non-`wiki/`-prefixed tags survive untouched in their original relative order; only the
        `wiki/*` subset is replaced.
      - A connectors-only change never perturbs the recorded `wiki_src_hash`, since
        `wiki_connectors` is excluded from `source_hash`.
      - A `None` `wiki_summary` or `topics` argument leaves the currently stored value unchanged.
      - `stamp_src_hash=False` leaves the stored `wiki_src_hash` value untouched.

    Args:
      wiki_summary: One-line summary string (no newlines); `None` leaves the currently stored
        value unchanged.
      topics: Full list of `wiki/<axis>/<value>` tag strings to apply.
        These replace the current `wiki/*` subset; non-`wiki/` tags survive. `None` leaves the
        currently stored subset unchanged.
      connectors: Short linkable-facet phrases for `wiki_connectors`; `None`
        leaves the existing block untouched, an empty list removes it.
      stamp_src_hash: `False` leaves the stored `wiki_src_hash` value untouched instead of
        recomputing it.
    """

    # Contract:
    # Tags without the `wiki/` prefix survive the write in their original relative order.
    # Only the `wiki/*` subset is ever replaced.

    # Contract:
    # A connectors-only change never perturbs the recorded source hash, because the connectors
    # block is excluded from the operator-authored content the hash covers.

    # Contract:
    # A `None` `wiki_summary` or `topics` argument leaves the corresponding stored value exactly as
    # it was before the call; only a non-`None` value ever replaces it.

    # Contract:
    # `stamp_src_hash=False` leaves the stored `wiki_src_hash` value untouched, whatever the freshly
    # computed hash would be.

    # Domain(wiki.graph):
    # # Curated facets of a node
    # Curation touches four facets of a node and nothing else: the one-line gloss that describes it, the
    # topics that classify it, the connector phrases by which it can be reached from elsewhere, and its
    # outbound links. Everything else the node carries — its prose, its headings, and any label or metadata
    # another tool owns — stays exactly as the operator left it, so a curation pass is never a rewrite.
    # Alongside those facets the operator may state standing preferences: topics and links pinned to the node,
    # and topics and links declared unwanted there. Those statements are read by curation and never written
    # by it. Curation is free to overwrite its own facets on every pass, and never free to overwrite intent
    # the operator stated.

    text = self._text

    # Compute the source hash from the CURRENT content with managed regions
    # excluded — invariant across the writes below, so order does not matter.
    src_hash = hashlib.sha256(
      _markdown_source_for_hash(text).encode(_ENCODING)
    ).hexdigest()[:_SRC_HASH_LEN]

    # Step 1 — wiki_summary; a None leaves the current one as it is
    if wiki_summary is not None:
      text = _set_scalar_field(text, _KEY_WIKI_SUMMARY, wiki_summary)

    # Step 2 — tags: merge wiki/* subset, preserve non-wiki/* tags in order; a None leaves them
    if topics is not None:
      current_tags = _get_array_field(text, _KEY_TAGS)
      non_wiki = [ t for t in current_tags if not t.startswith(_WIKI_TAG_PREFIX) ]
      text = _set_tags_field(text, non_wiki + topics)

    # Step 3 — wiki_connectors (managed block, excluded from source_hash)
    # a None means "leave the block as it is"; an empty list means "clear it"
    if connectors is not None:
      text = _set_block_seq_field(text, _KEY_CONNECTORS, connectors)

    # Step 4 — wiki_src_hash (backstop for incremental relink on anchor loss), only for a curation
    if stamp_src_hash:
      text = _set_scalar_field(text, _KEY_SRC_HASH, src_hash)

    # all four steps land in a single write, so the file is never seen half-applied
    self._text = text
    self._file.write(text)

  def apply_link(
    self,
    *,
    see_also_lines: list[str],
  ) -> None:
    """
    Write the link-phase managed region: the `# See also` section.

    Leaves `wiki_summary`, `wiki/*` tags, and all other content untouched.

    Guarantees:
      - Applying identical `see_also_lines` twice produces byte-identical file content
        on the second call.
      - Every link target is normalised to the canonical node-directory-relative base,
        so a target copied from `topics.md` or spelled repo-relative lands correctly.

    Args:
      see_also_lines: Ready-to-graft markdown list-item strings for the
        See-also section, one per list item.  An empty list produces an
        empty (but present) managed block.
    """

    # Contract:
    # Every link target written into the section is in canonical node-directory-relative
    # spelling, whatever base the caller spelled it against.

    # the whole document is rewritten from the in-memory copy in one pass
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

    # rebase every target onto this node's directory, then graft the managed section
    inner = "\n".join(
      normalize_see_also_line(line, self._path) for line in see_also_lines
    )
    body = self._markers.ensure_see_also(body, inner)
    text = pre + body

    # frontmatter and body go back to disk as one document
    self._text = text
    self._file.write(text)

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

# Regex to detect a shebang line.
_SHEBANG_RE = re.compile(r"^#!")

# A run of line breaks (JavaScript and Python's line splitting also break on NEL, U+2028, and U+2029)
# with the whitespace around it, collapsed to one space in a `<wiki>` value.
_LINE_BREAKS_RE = re.compile(r"\s*[\r\n\x85\u2028\u2029]+\s*")

# The terminator of a block comment, and the spelling a value uses for it so the comment never ends early.
_BLOCK_COMMENT_END = "*/"
_BLOCK_COMMENT_END_SAFE = "* /"

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

    # a wiki tag in the header run means the header already ended here
    inner = _strip_comment_prefix(line.rstrip("\n").rstrip("\r"), prefix)

    # guard: stop if this is already a wiki open tag (shouldn't happen on fresh files)
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

  Only the header comment region at the top of the file is searched: an optional shebang, then
  comment and blank lines up to the first line of code.

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

    # a non-comment line other than the shebang or a blank one is code — the header region ends there
    if inner is None:
      # guard: the shebang and blank lines still belong to the header region
      if (i == 0 and _SHEBANG_RE.match(line)) or not line.strip():
        continue
      break
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

  # the delimiter lines themselves are not field content
  interior = [ raw.rstrip("\n").rstrip("\r") for raw in lines[start + 1:end] ]

  # Block-comment interior lines carry no comment prefix but may share a common
  # leading indent (an indented `/* … */` block).  Dedent by that common base so
  # field headers land at column 0 while see-also items keep their relative `  - `
  # indent — a flat per-line strip would erase the indent the continuation check needs.
  base_indent = 0
  if block_comment:
    indents = [ len(e) - len(e.lstrip()) for e in interior if e.strip() ]
    base_indent = min(indents) if indents else 0

  # one pass over the interior: each line is either a field header or a see-also item
  for line in interior:
    # the two comment styles reach their payload differently
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

    # field header lines — any of them ends an open see-also run
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

  # absent fields stay absent — the caller distinguishes "unset" from "empty"
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

  Guarantees:
    - A line break in any rendered value collapses to one space, so it never ends the comment early.
    - In the block-comment style, the comment's own closing sequence inside a value is rewritten so
      the block's own closing line is the only place the rendered comment terminates.

  Args:
    fields: Dict of field name → value (string or list) to emit.
    prefix: Comment prefix or `"/*"`.

  Returns:
    List of line strings without trailing newlines.
  """

  # Contract:
  # A line break in a rendered value — LF, CR, NEL, the line separator, or the paragraph separator —
  # MUST collapse to one space, together with any surrounding whitespace, so it can never end the
  # comment early. In the block-comment style, the comment's own closing sequence inside a value is
  # NEVER emitted as-is; it is rewritten so the block's own closing line is the only place the
  # rendered comment terminates.

  block_comment = prefix == _BLOCK_COMMENT_SENTINEL
  out: list[str] = []

  # a block-comment language opens the wrapper on the tag line itself
  if block_comment:
    out.append(f"/* {_WIKI_OPEN_TAG}")
  else:
    out.append(_build_wiki_line(_WIKI_OPEN_TAG, prefix))

  # inside a block comment the interior needs no prefix; a line-comment file does. A line break in a
  # value would end a line comment and a `*/` a block comment, so each is neutralised and every
  # rendered line stays inside the comment.
  def _line(content: str) -> str:
    content = _LINE_BREAKS_RE.sub(" ", content)
    if block_comment:
      return content.replace(_BLOCK_COMMENT_END, _BLOCK_COMMENT_END_SAFE)
    return _build_wiki_line(content, prefix)

  # emit the curated fields in a fixed order so a re-render is byte-stable
  summary = fields.get(_FK_SUMMARY)
  if summary:
    out.append(_line(f"{_FH_SUMMARY} {summary}"))

  # topics and connectors render as comma-joined single lines
  topics = fields.get(_FK_TOPICS)
  if topics and isinstance(topics, list):
    out.append(_line(f"{_FH_TOPICS} {', '.join(topics)}"))

  # connectors ride alongside topics as free-form linking hints
  connectors = fields.get(_FK_CONNECTORS)
  if connectors and isinstance(connectors, list):
    out.append(_line(f"{_FH_CONNECTORS} {', '.join(connectors)}"))

  # the hash anchors incremental relink when the git anchor is lost
  src_hash = fields.get(_FK_SRC_HASH)
  if src_hash:
    out.append(_line(f"{_FH_SRC_HASH} {src_hash}"))

  # an empty-but-present see-also still emits its header, marking the node as linked
  see_also = fields.get(_FK_SEE_ALSO)
  if see_also is not None:
    out.append(_line(_FH_SEE_ALSO))
    for item in (see_also if isinstance(see_also, list) else []):
      out.append(_line(f"  - {item}"))

  # the operator pin fields all render the same way — one header, one value
  for field_key, field_hdr in [
    (_FK_PINNED_TOPICS,    _FH_PINNED_TOPICS),
    (_FK_UNRELATED_TOPICS, _FH_UNRELATED_TOPICS),
    (_FK_PINNED_LINKS,     _FH_PINNED_LINKS),
    (_FK_UNRELATED_LINKS,  _FH_UNRELATED_LINKS),
  ]:
    val = fields.get(field_key)
    if val:
      out.append(_line(f"{field_hdr} {val}"))

  # close the wrapper the same way it was opened
  if block_comment:
    out.append(f"{_WIKI_CLOSE_TAG} */")
  else:
    out.append(_build_wiki_line(_WIKI_CLOSE_TAG, prefix))

  # newline-free lines — the writer owns line endings
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

  # Domain(wiki.graph):
  # # When a code node counts as changed
  # The same rule that decides a markdown node's fingerprint applies to a code file: only what the
  # operator wrote counts as its content, so curation must never make the file look edited. For a
  # code file the curated content is the single delimited block wiki owns, together with the one
  # blank line the writer leaves after it — dropping that separator too keeps a freshly written
  # block from making the code right after it look changed.

  span = _find_wiki_block(lines, prefix)
  if span is None:
    kept = lines
  else:
    start, end = span
    after = end + 1

    # the writer adds a blank separator after the block — exclude it from the hash too
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

  Guarantees:
    - Every line outside the `<wiki>` block survives a write byte-for-byte.
    - A shebang line and the leading header comment stay above the block, so an executable file
      stays executable.
    - The four operator-pin fields are read and never written.
    - Each write phase leaves the block fields it does not own untouched.
    - Every write operation is idempotent: identical inputs leave byte-identical content on the second call.
    - A write preserves the file's original line ending; a file read with CRLF stays CRLF.
  """

  # Contract:
  # Every line outside the `<wiki>` block survives a write byte-for-byte — code, imports,
  # header comments, and the shebang alike.

  # Contract:
  # The block is NEVER written above a shebang line or the leading header comment; an executable
  # file stays executable across any number of write passes.

  # Contract:
  # The four operator-pin fields — `pinned-topics`, `unrelated-topics`, `pinned-links` and
  # `unrelated-links` — are read-only: they are read and NEVER written.

  # Contract:
  # Each write phase leaves the block fields it does not own untouched, so a classify pass and a
  # link pass never overwrite each other's result.

  # Contract:
  # Every write operation is idempotent: applying identical inputs twice leaves byte-identical file
  # content on the second call.

  # Contract:
  # A write preserves the file's original line ending: a file read with CRLF line endings is written
  # back with CRLF, never silently converted to LF.

  # File encoding for read/write.
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
    self._file = TextFile(path = path)
    self._text = self._file.read()
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
    Set of forward See-also link target paths, expressed repo-relative.

    Parses `[text](path)` link entries from every item in the `<wiki>` block's
    `see-also` list. Stored targets are relative to this node's own directory, so
    each one is re-expressed as a repo-relative POSIX path — the identity form in
    which edges from different nodes are comparable. Unresolvable targets are
    kept verbatim. Empty when the `<wiki>` block has no see-also
    items. Used by `dispatch-link` to skip back-link dispatches for attractor
    nodes that already forward-link to the target.

    Guarantees:
      - Every returned target is in the shared repo-relative identity form, so the same target
        file compares equal whichever node states the link to it.
    """

    # Contract:
    # Every target in the returned set is expressed in the shared repo-relative identity form,
    # so the same target file compares equal whichever node states the link to it.

    out: set[str] = set()
    for item in self.see_also:
      for match in _SEE_ALSO_LINK_RE.finditer(item):
        out.add(repo_relative_see_also_target(match.group(1).strip(), self._path))
    return out

  @property
  def source_hash(self) -> str:
    """
    Stable hash of the operator-authored source, excluding the `<wiki>` block.

    The hash is computed over the file with the entire `<wiki>` comment
    block removed, so re-curation never changes it.

    Guarantees:
      - The value changes only when operator-authored source changes; a wiki write never moves it.
    """

    # Contract:
    # The value covers operator-authored source only. A write to the `<wiki>` block NEVER changes
    # it, so a re-curated file still reads as unchanged.

    # a short digest is enough to tell one authored revision from another
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
    see_also_lines: list[str],
    wiki_summary: str | None = None,
    topics: list[str] | None = None,
    connectors: list[str] | None = None,
  ) -> None:
    """
    Write all wiki-managed fields in one atomic pass.

    Guarantees:
      - Applying identical `wiki_summary`, `topics`, `connectors`, and `see_also_lines` twice
        produces byte-identical file content on the second call.
      - A `None` `wiki_summary` or `topics` argument leaves the currently stored value unchanged.

    Args:
      see_also_lines: Lines to set as `see-also:` items (bare `path — gloss` strings).
      wiki_summary: One-line summary string (no newlines); `None` leaves the currently stored
        value unchanged.
      topics: Full list of topic strings to set in the `topics:` field; `None` leaves the
        currently stored value unchanged.
      connectors: Short linkable-facet phrases for the `connectors:` field;
        `None` leaves the existing value untouched.
    """
    self.apply_classify(wiki_summary = wiki_summary, topics = topics, connectors = connectors)
    self.apply_link(see_also_lines = see_also_lines)

  def apply_classify(
    self,
    *,
    wiki_summary: str | None = None,
    topics: list[str] | None = None,
    connectors: list[str] | None = None,
    stamp_src_hash: bool = True,
  ) -> None:
    """
    Write the classify-phase fields: `summary`, `topics`, `connectors`.

    Guarantees:
      - Applying identical `wiki_summary`, `topics`, and `connectors` twice produces
        byte-identical file content on the second call.
      - Leaves `see-also`, all pin fields, and code outside the block untouched.
      - Topics are persisted bare, as `<axis>/<value>`; the `wiki/` prefix is never stored.
      - A connectors-only change never perturbs the recorded `src-hash`, since the `connectors:`
        field is excluded from `source_hash`.
      - A `None` `wiki_summary` or `topics` argument leaves the currently stored field unchanged.
      - `stamp_src_hash=False` leaves the stored `src-hash` value untouched.

    Args:
      wiki_summary: One-line summary string (no newlines); `None` leaves the currently stored
        value unchanged.
      topics: Full list of topic strings to set; `None` leaves the currently stored value
        unchanged.
      connectors: Short linkable-facet phrases for the `connectors:` field;
        `None` leaves the existing value untouched.
      stamp_src_hash: `False` leaves the stored `src-hash` value untouched instead of
        recomputing it.
    """

    # Contract:
    # Topics are persisted bare — `<axis>/<value>`, with no `wiki/` prefix — whichever of the two
    # spellings the caller passes in.

    # Contract:
    # A `None` `wiki_summary` or `topics` argument leaves the corresponding stored field exactly as
    # it was before the call; only a non-`None` value ever replaces it.

    # Contract:
    # `stamp_src_hash=False` leaves the stored `src-hash` value untouched, whatever the freshly
    # computed hash would be.

    # Domain(wiki.taxonomy):
    # # How a code node states its topics
    # A topic is written differently depending on the kind of file that states it. In a prose node the topic
    # sits among the file's other labels, so it carries the marker that tells wiki-owned labels apart from
    # foreign ones. In a code node everything the wiki owns already lives inside one clearly bounded block,
    # where no foreign label can be mistaken for a topic, so the topic is stated bare — axis and value only.
    # Both forms name the same topic, and the catalog restores the marker as it reads a code node, so how a
    # node is classified never depends on the kind of file carrying it.

    # Compute the source hash from the CURRENT content with the wiki block
    # excluded, so the hash reflects only operator-authored code.
    src_hash = hashlib.sha256(
      _code_source_for_hash(self._lines, self._prefix).encode(self._ENCODING)
    ).hexdigest()[:_SRC_HASH_LEN]

    # merge onto the existing block so fields this phase does not own survive; a None leaves a field
    current = self._read_block() or {}
    if wiki_summary is not None:
      current[_FK_SUMMARY] = wiki_summary

    # Code topics are stored BARE (`<axis>/<value>`) — strip the `wiki/` prefix
    # the curator emits.  build-index re-adds `wiki/` for code nodes, so storing
    # the prefixed form here would double it (`wiki/wiki/<axis>/…`).
    if topics is not None:
      current[_FK_TOPICS] = [
        t[len(_WIKI_TAG_PREFIX):] if t.startswith(_WIKI_TAG_PREFIX) else t
        for t in topics
      ]

    # a None means "leave connectors as they are"; an empty list clears them
    if connectors is not None:
      current[_FK_CONNECTORS] = connectors

    # only a curation re-anchors the source hash; a tag rewrite keeps the stored one
    if stamp_src_hash:
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
    untouched.  The operation is idempotent.  Link targets are normalised to the
    canonical node-directory-relative base, as in `MarkdownNode.apply_link`.

    Guarantees:
      - Every stored link target is in canonical node-directory-relative spelling.

    Args:
      see_also_lines: Lines to set as `see-also:` items.
    """

    # Contract:
    # Every link target written into the block is in canonical node-directory-relative spelling,
    # whatever base the caller spelled it against.

    # merge onto the existing block so fields this phase does not own survive
    current = self._read_block() or {}

    # Code see-also is stored bare — strip the leading markdown list bullet the
    # curator emits (`- [name](path) — gloss`) so the block renderer's own `  - `
    # is the only bullet (mirrors the bare-topics strip in apply_classify).
    current[_FK_SEE_ALSO] = [
      normalize_see_also_line(line[2:] if line.startswith("- ") else line, self._path)
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

    # an existing block is replaced in place; a fresh one is inserted after the header
    span = _find_wiki_block(self._lines, self._prefix)
    if span is not None:
      start, end = span

      # Replace lines[start:end+1] with the new block lines
      # Preserve the separator blank line that may already follow the block
      after_block = end + 1

      # consume the existing separator so the rewrite does not double it
      if after_block < len(self._lines) and self._lines[after_block].strip() == "":
        after_block += 1
      new_lines = self._lines[:start] + block_with_nl + self._lines[after_block:]
    else:
      insert_at = _locate_header_end(self._lines, self._prefix)
      new_lines = self._lines[:insert_at] + block_with_nl + self._lines[insert_at:]

    # keep the in-memory view and the file in step after the write
    self._lines = new_lines
    self._text = "".join(new_lines)
    self._file.write(self._text)


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

  Guarantees:
    - Only the named key's entry changes; every other byte of the document survives untouched,
      including sibling keys, their block style, comments, and quoting.

  Args:
    text: Full document text (may be empty for a brand-new file).
    key: Top-level YAML key to set.
    value: String value; must not contain newlines.

  Returns:
    Document text with the key set to `value`.
  """

  # Contract:
  # Only the named key's entry changes. Every other byte of the document survives untouched —
  # sibling keys, their block style, comments, quoting, and the whole body below the fences.

  # the surgical editor is the single implementation of the key-entry rewrite
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
