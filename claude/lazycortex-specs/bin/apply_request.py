"""
Deterministic apply-transition worker — the Python primitive backing the
`spec.request-apply` md-scan routine.

Replaces the LLM-driven `spec.request-apply` agent. Reads the resolved
routing prose from a post-finalize request file, enacts the named
attach / spawn targets, distributes the request body into populated
docs (Tier 3 fallback — whole body to the entity's WTR doc), opens a
review cycle on every populated doc, then stamps terminal markers
(`request_class`, `request_status`, `request/<status>` mirror tag,
status callout) and strips the `# Routing` section. Atomic commit
under the `spec.request-apply` bot identity.

Routing prose grammar (parsed leniently — the router agent emits free
text, so the patterns below match the conventional shapes):

- **Class verdict** — `Class: <verdict>` or `**Class:** \\<verdict>\\`
  (case-insensitive, optional surrounding backticks / asterisks).
  Verdict is one of `feature` / `change` / `bug` / `task` / `spec` /
  `plan` / `feedback` / `unknown`.
- **Spawn target** — a `Target:` / `Spawn:` line that mentions a
  built-in kind word (`feature` / `change` / `bug`) and a slug in
  backticks (the prose form the router emits, e.g.
  "Spawn one cross-cutting change entity — `slug`").
- **Attach target** — a `[[path]]` wikilink whose last path segment
  equals the previous one (folder-note shape, per
  `spec.layout-protocol`).
- **No target resolved** → request is rejected with the rejection
  callout + recovery hint.

Inputs read:

- `<repo>/.claude/lazy.settings.json[products]` — to map a product key
  to its `spec_path` (used during spawn-target enaction to resolve the
  folder-note path the scaffolder writes).
- The post-finalize request file passed as the positional argument.

Outputs written:

- Spawn targets: full asset scaffolds via the `scaffold-asset`
  subprocess.
- Each populated doc: body distribution + `spec_source_requests`
  frontmatter + `## Requests` projection inside `# Sources`.
- Each populated doc's folder-note: `## Source requests` bullet.
- Each populated doc: review cycle opened via the `lazycortex-review`
  CLI's `start` subcommand.
- Request file: `request_class` / `request_status` frontmatter,
  `request/<status>` mirror tag, status callout above first H1,
  `# Routing` stripped.
- One atomic commit under the bot identity covering every path.

Exit codes: `0` on success (including idempotent no-op on a
terminal-status file); `1` on a logical error written to stdout as a
JSON `error` object.
"""
from __future__ import annotations

from typing import NoReturn

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class _K:
  """
  String / int constants used by the apply worker.
  """

  # Frontmatter keys
  SPEC_ROLE = "spec_role"
  REQUEST_STATUS = "request_status"
  REQUEST_CLASS = "request_class"
  REVIEW_RESULT = "review_result"
  REVIEW_ACTIVE = "review_active"
  REVIEW_ROUND = "review_round"
  REVIEW_APPROVED = "review_approved"
  TAGS = "tags"
  SPEC_SOURCE_REQUESTS = "spec_source_requests"
  # Frontmatter values
  STATUS_DRAFT = "draft"
  STATUS_ACCEPTED = "accepted"
  STATUS_REJECTED = "rejected"
  CLASS_UNKNOWN = "unknown"
  ROLE_REQUEST = "request"
  REVIEW_APPROVED_VAL = "approved"
  REVIEW_APPROVED_WITH_CONCERNS = "approved-with-concerns"
  # Tag prefixes / members
  TAG_PREFIX = "request/"
  # Filenames + doc roles
  DESIGN_MD = "design.md"
  BUG_MD = "bug.md"
  PLAN_MD = "plan.md"
  FEATURE_KIND = "feature"
  CHANGE_KIND = "change"
  BUG_KIND = "bug"
  # Path segments
  CLAUDE_DIR = ".claude"
  SETTINGS_FILE = "lazy.settings.json"
  PRODUCTS = "products"
  SPEC_PATH = "spec_path"
  GIT_DIR = ".git"
  # Routing-section markers
  ROUTING_H1 = "# Routing"
  HISTORY_H1 = "# History"
  ROUTING_DECISION_OPEN = "<!-- routing-decision"
  ROUTING_DECISION_CLOSE = "-->"
  DECISION_VERB_SPAWN = "spawn"
  DECISION_VERB_ATTACH = "attach"
  SOURCES_H1 = "# Sources"
  SOURCES_TAG = "#protected/spec/sources"
  REQUESTS_H2 = "## Requests"
  REQUESTS_MARKER_START = "<!-- auto:spec-requests:start -->"
  REQUESTS_MARKER_END = "<!-- auto:spec-requests:end -->"
  SOURCE_REQUESTS_H2 = "## Source requests"
  HISTORY_H2 = "## History"
  # Status callout strings
  CALLOUT_SUCCESS = "[!success] Request accepted #status/accepted"
  CALLOUT_WARNING = "[!warning] Request rejected #status/rejected"
  STATUS_TAG_PATTERN = r"#status/\S+"
  REJECT_HINT = "To re-open: clear request_status, clear review_result, restore review_active: true."
  REJECT_REASON_DEFAULT = "Routing prose named no resolvable target."
  # Subprocess + git
  GIT = "git"
  # CLI identity
  PROG = "lazycortex-specs apply-request"
  CLI_LAZYCORTEX_SPECS = "lazycortex-specs"
  CLI_LAZYCORTEX_REVIEW = "lazycortex-review"
  ENV_PLUGIN_DIRS = "LAZYCORTEX_PLUGIN_DIRS"
  BIN_DIR = "bin"
  MD_SUFFIX = ".md"
  BOT_NAME_DEFAULT = "spec.request-apply"
  BOT_EMAIL_DEFAULT = "spec.request-apply@bot.lazy-cortex"
  ARG_FILE = "file"
  ARG_AUTHOR_NAME = "--author-name"
  ARG_AUTHOR_EMAIL = "--author-email"
  REVIEW_START_IDEMPOTENT_MARK = "already"
  ERR_NO_PRODUCTS = (
      "no products registered in lazy.settings.json; cannot resolve spawn target"
  )
  # Outcome / error categories
  CAT_LOGICAL = "logical"
  OUTCOME_SUCCESS = "success"
  OUTCOME_ERROR = "error"
  OUTCOME_TERMINAL_SKIP = "terminal-state-skip"
  OUTCOME_NO_ROUTING_SKIP = "no-routing-skip"
  # Layout-protocol convention
  CANONICAL_PATH_MIN_PARTS = 3
  PRODUCTS_SEGMENT = "products"
  # Allowed class enum
  CLASS_ENUM = ( "feature", "change", "bug", "task", "spec", "plan", "feedback", "unknown" )
  KIND_FOLDER = { "feature": "features", "change": "changes", "bug": "bugs" }
  KIND_LAYOUT = { "feature": [ "design.md", "plan.md" ],
                  "change":  [ "design.md", "plan.md" ],
                  "bug":     [ "bug.md", "plan.md" ] }


def _fail(category: str, message: str) -> NoReturn:
  """
  Print a JSON error object to stdout and exit non-zero.

  Args:
    category: Error category — one of `logical` (input invalid) or `technical`
      (internal failure).
    message: Single-line human-readable cause.
  """
  print(json.dumps({ "outcome": _K.OUTCOME_ERROR,
                     "error": { "category": category, "message": message } }))
  sys.exit(1)


def _repo_root(start: Path) -> Path:
  """
  Resolve the repo root from a working directory, falling back to start when not in a repo.

  Args:
    start: Working directory to start the search from.

  Returns:
    The first ancestor (or `start` itself) that contains a `.git` entry; absolute path.
  """
  cur = start.resolve()
  while cur != cur.parent:
    if (cur / _K.GIT_DIR).exists():
      return cur
    cur = cur.parent
  return start.resolve()


def _resolve_sibling_cli(name: str) -> Path:
  """
  Locate a sibling plugin's CLI binary through `$LAZYCORTEX_PLUGIN_DIRS`.

  Args:
    name: CLI filename (e.g. `lazycortex-specs`, `lazycortex-review`).

  Returns:
    Absolute path to the CLI binary in the first registered plugin dir that carries it.

  Raises:
    SystemExit: When the env var is unset or no plugin dir holds the named CLI.
  """
  raw = os.environ.get(_K.ENV_PLUGIN_DIRS, "")
  # guard: env var empty — caller is not running under the lazy-core runtime daemon
  if not raw:
    _fail(_K.CAT_LOGICAL, f"${_K.ENV_PLUGIN_DIRS} unset; cannot resolve sibling CLI '{name}'")
  for d in raw.split(os.pathsep):
    cli = Path(d) / _K.BIN_DIR / name
    if cli.is_file():
      return cli
  _fail(_K.CAT_LOGICAL, f"no '{name}' in ${_K.ENV_PLUGIN_DIRS}")


def _parse_frontmatter(text: str) -> tuple[dict, int]:
  """
  Parse a markdown file's YAML frontmatter into a flat dict + end offset.

  Args:
    text: Full file text.

  Returns:
    Two-tuple `(values, fm_end)` where `values` carries scalar and list-typed entries
    and `fm_end` is the byte offset of the first character after the closing fence.
    Returns `({}, 0)` when no frontmatter is present.
  """
  if not text.startswith("---\n"):
    return {}, 0
  # waiver: inline numeric literal -- length of the leading '---\n' fence consumed below
  rest = text[4:]
  # guard: empty frontmatter block (`---\n---\n`) — recognise as valid, no values
  if rest.startswith("---\n"):
    # waiver: inline numeric literal -- length of the two stacked '---\n' fences
    return {}, 8
  end_idx = rest.find("\n---\n")
  # guard: opening fence without closing fence — not a valid block
  if end_idx < 0:
    return {}, 0
  block = rest[:end_idx]
  # waiver: inline numeric literal -- length of the leading '---\n' fence
  fm_end = 4 + end_idx + len("\n---\n")
  values: dict = {}
  current_list_key: str | None = None
  for line in block.splitlines():
    stripped = line.strip()
    # guard: skip blank lines and comment markers
    if not stripped or stripped.startswith("#"):
      continue
    # guard: list continuation line (indented `- value`)
    if stripped.startswith("- ") and line.startswith(("  ", "\t")):
      if current_list_key:
        item = stripped[2:].strip().strip('"').strip("'")
        values[current_list_key].append(item)
      continue
    # guard: not a key:value line
    if ":" not in line:
      continue
    k, _, v = line.partition(":")
    k = k.strip()
    v_str = v.strip()
    # guard: empty key
    if not k:
      continue
    if v_str == "":
      current_list_key = k
      values[k] = []
    else:
      values[k] = v_str
      current_list_key = None
  return values, fm_end


def _parse_routing_decision(block: str) -> tuple[list[tuple[str, str]], list[str]]:
  """
  Parse the structured `<!-- routing-decision ... -->` block body.

  Format is one decision per line, whitespace-separated:

  - `spawn <kind> <slug>`        → emit `(kind, slug)` into the spawn list.
  - `attach <folder-note-path>`  → emit the path into the attach list.

  Any other line shape (blank, prose, malformed) is silently skipped — the
  parser is forgiving on unknown content so the router can mix structured
  decisions with operator-readable notes inside the same block without
  breaking apply.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    Two lists: spawn-pair list (`(kind, slug)`) and attach-path list. Dedup is
    applied within each list (preserves insertion order).
  """
  spawn: list[tuple[str, str]] = []
  attach: list[str] = []
  seen_spawn: set[tuple[str, str]] = set()
  seen_attach: set[str] = set()
  for raw_line in block.splitlines():
    stripped = raw_line.strip()
    # guard: skip blanks and any non-decision prose lines
    if not stripped:
      continue
    tokens = stripped.split()
    verb = tokens[0].lower()
    # waiver: structural token count for `spawn <kind> <slug>` line format
    if verb == _K.DECISION_VERB_SPAWN and len(tokens) >= 3:
      kind = tokens[1].lower()
      slug = tokens[2]
      # guard: drop kinds outside the built-in folder set
      if kind not in _K.KIND_FOLDER:
        continue
      pair = ( kind, slug )
      if pair not in seen_spawn:
        seen_spawn.add(pair)
        spawn.append(pair)
      continue
    if verb == _K.DECISION_VERB_ATTACH and len(tokens) >= 2:
      target = tokens[1]
      if target not in seen_attach:
        seen_attach.add(target)
        attach.append(target)
      continue
  return spawn, attach


def _parse_routing(body: str) -> tuple[str | None, list[tuple[str, str]], list[str], str]:
  """
  Extract the class verdict + spawn / attach targets from a `# Routing` section.

  Args:
    body: Request body (post-frontmatter).

  Returns:
    Four-tuple `(class_verdict, spawn_list, attach_list, routing_text)`.
    `class_verdict` is the lowercased verdict word or `None` when absent.
    `spawn_list` carries `(kind, slug)` pairs. `attach_list` carries folder-note
    wikilink paths (last segment equals the previous one). `routing_text` is the
    raw inner text of the section (empty when no section is present).
  """
  m = re.search(
      rf"(?ms)^{re.escape(_K.ROUTING_H1)}\s*$(.*?)(?=^# \S|\Z)",
      body,
  )
  if not m:
    return None, [], [], ""
  routing_text = m.group(1)
  cls: str | None = None
  cm = re.search(
      r"(?im)\bclass\b\s*[:|]\s*\**\s*`?([a-z][a-z-]*)`?",
      routing_text,
  )
  if cm:
    candidate = cm.group(1).lower()
    if candidate in _K.CLASS_ENUM:
      cls = candidate
  # PRIMARY: structured `<!-- routing-decision ... -->` block. When present, its
  # contents are authoritative and prose-parsing is skipped entirely. Format:
  # one decision per line:
  #     spawn <kind> <slug>
  #     attach <repo-relative-folder-note-path>
  decision_match = re.search(
      rf"(?s){re.escape(_K.ROUTING_DECISION_OPEN)}\s*(.*?)\s*{re.escape(_K.ROUTING_DECISION_CLOSE)}",
      routing_text,
  )
  if decision_match:
    spawn_structured, attach_structured = _parse_routing_decision(decision_match.group(1))
    return cls, spawn_structured, attach_structured, routing_text
  spawn: list[tuple[str, str]] = []
  seen_spawn: set[tuple[str, str]] = set()
  # Spawn line shape examples:
  #   "Spawn one cross-cutting change entity — `slug`"
  #   "Spawn change: slug"
  #   "spawn: bug — `slug`"
  for sm in re.finditer(
      r"(?im)\bspawn\b[^\n]*?\b(feature|change|bug)\b[^\n]*?`([a-z][a-z0-9-]*)`",
      routing_text,
  ):
    pair = ( sm.group(1).lower(), sm.group(2) )
    if pair not in seen_spawn:
      seen_spawn.add(pair)
      spawn.append(pair)
  # Plain `<kind>: <slug>` form (router may emit a structured fallback).
  for sm in re.finditer(
      r"(?im)^\s*(?:[-*]\s*)?(?:spawn[^\n:]*[:|]\s*)?(feature|change|bug)\s*[:|]\s*`?([a-z][a-z0-9-]*)`?\s*$",
      routing_text,
  ):
    pair = ( sm.group(1).lower(), sm.group(2) )
    # guard: dedupe against the prose-form pass above
    if pair not in seen_spawn:
      seen_spawn.add(pair)
      spawn.append(pair)
  # Path-form spawn target — router may emit the full repo-relative spawn path in
  # backticks (e.g. "spawn `request/products/test/changes/<slug>`"). The kind is
  # the singular of the second-to-last path segment ("changes" → "change"); the
  # slug is the last path segment.
  for sm in re.finditer(
      r"(?im)\bspawn\b[^\n]*?`([^`\s]+/(?:features|changes|bugs)/[a-z][a-z0-9-]*)`",
      routing_text,
  ):
    path_target = sm.group(1)
    parts = path_target.rstrip("/").split("/")
    slug = parts[-1]
    folder = parts[-2]
    kind = { "features": "feature", "changes": "change", "bugs": "bug" }[folder]
    pair = ( kind, slug )
    # guard: dedupe against the prose-form passes above
    if pair not in seen_spawn:
      seen_spawn.add(pair)
      spawn.append(pair)
  attach: list[str] = []
  seen_attach: set[str] = set()
  for wm in re.finditer(r"\[\[([^\]|]+?)(?:\|[^\]]*?)?\]\]", routing_text):
    target = wm.group(1).strip()
    parts = target.split("/")
    # guard: folder-note shape is "<...>/<slug>/<slug>" — last two segments must match
    if len(parts) >= 2 and parts[-1] == parts[-2] and target not in seen_attach:
      seen_attach.add(target)
      attach.append(target)
  return cls, spawn, attach, routing_text


def _strip_routing(body: str) -> str:
  """
  Remove the entire `# Routing` H1 section from a body.

  Args:
    body: Request body (post-frontmatter).

  Returns:
    The body with the routing section excised; consecutive blank lines collapsed
    to at most one blank line.
  """
  pat = rf"(?ms)^{re.escape(_K.ROUTING_H1)}\s*$.*?(?=^# \S|\Z)"
  out = re.sub(pat, "", body, count = 1)
  return re.sub(r"\n{3,}", "\n\n", out)


def _strip_prior_status_callout(body: str) -> str:
  """
  Drop any leading `> [!...] ... #status/<x>` callout block above the first H1.

  Args:
    body: Body text starting at or before the first H1.

  Returns:
    Body with the leading status callout (and one trailing blank line) removed
    when present; unchanged otherwise.
  """
  m_h1 = re.search(r"(?m)^# ", body)
  # guard: no H1 — leave body as-is
  if not m_h1:
    return body
  head = body[:m_h1.start()]
  tail = body[m_h1.start():]
  out_lines: list[str] = []
  in_status_callout = False
  for line in head.splitlines(keepends = True):
    if line.startswith("> "):
      if re.search(_K.STATUS_TAG_PATTERN, line):
        in_status_callout = True
        continue
      # guard: continuation line of a callout we are already eating
      if in_status_callout:
        continue
      out_lines.append(line)
      continue
    if in_status_callout and line.strip() == "":
      in_status_callout = False
      continue
    in_status_callout = False
    out_lines.append(line)
  return "".join(out_lines) + tail


def _format_status_callout(*, accepted: bool, wikilinks: list[str], reason: str | None) -> str:
  """
  Render the apply transition's status callout block.

  Args:
    accepted: True for the success callout, False for the rejection callout.
    wikilinks: Resolved-target wikilink paths to list in the success callout body.
    reason: Optional rejection reason line; only used when `accepted is False`.

  Returns:
    Multi-line callout block without trailing newline.
  """
  if accepted:
    lines = [ f"> {_K.CALLOUT_SUCCESS}" ]
    for wl in wikilinks:
      lines.append(f"> [[{wl}]]")
    return "\n".join(lines)
  lines = [ f"> {_K.CALLOUT_WARNING}" ]
  if reason:
    lines.append(f"> {reason}")
  lines.append(f"> {_K.REJECT_HINT}")
  return "\n".join(lines)


def _insert_status_callout(body: str, callout: str) -> str:
  """
  Insert the rendered status callout one blank line above the first H1.

  Args:
    body: Body with any prior status callout already stripped.
    callout: Rendered callout block (no trailing newline).

  Returns:
    Body with the callout placed above the first H1 (or at the start when no H1).
  """
  m_h1 = re.search(r"(?m)^# ", body)
  # guard: no H1 — prepend at start
  if not m_h1:
    return callout + "\n\n" + body
  return body[:m_h1.start()] + callout + "\n\n" + body[m_h1.start():]


def _set_fm_scalar(fm_text: str, key: str, value: str) -> str:
  """
  Add or replace a scalar `key: value` line inside a `---`-delimited frontmatter block.

  Args:
    fm_text: Full frontmatter text including the opening / closing fences.
    key: Scalar key name.
    value: Replacement value (string-rendered).

  Returns:
    Frontmatter text with the key set; existing lines are replaced in place,
    missing keys are appended before the closing fence.
  """
  pat = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$")
  if pat.search(fm_text):
    return pat.sub(f"{key}: {value}", fm_text, count = 1)
  # guard: closing fence absent — leave untouched (parser would not recognise this as a block)
  _, fm_end_probe = _parse_frontmatter(fm_text)
  if fm_end_probe == 0:
    return fm_text
  close_idx = fm_text.rfind("---\n")
  # guard: should be unreachable when fm_end_probe > 0, but defensive against partial fences
  if close_idx <= 0:
    return fm_text
  return fm_text[:close_idx] + f"{key}: {value}\n" + fm_text[close_idx:]


def _sweep_request_tag(fm_text: str, new_tag_member: str) -> str:
  """
  Replace every `request/*` member in the `tags:` block with the new one; keep other tags.

  Args:
    fm_text: Full frontmatter text.
    new_tag_member: Replacement tag (e.g. `request/accepted`).

  Returns:
    Frontmatter text with the `request/*` mirror-tag swept and rewritten;
    non-`request/*` members untouched.
  """
  tags_re = re.compile(r"(?m)^tags\s*:\s*\n((?:\s+- .*\n)*)")
  m = tags_re.search(fm_text)
  if not m:
    close_idx = fm_text.rfind("---\n")
    # guard: cannot splice without a closing fence
    if close_idx < 0:
      return fm_text
    return fm_text[:close_idx] + f"tags:\n  - {new_tag_member}\n" + fm_text[close_idx:]
  existing = m.group(1)
  kept: list[str] = []
  added = False
  for line in existing.splitlines(keepends = True):
    stripped = line.strip()
    # guard: skip empty lines inside the block
    if not stripped.startswith("- "):
      kept.append(line)
      continue
    member = stripped[2:].strip()
    if member.startswith(_K.TAG_PREFIX):
      if not added:
        kept.append(f"  - {new_tag_member}\n")
        added = True
      continue
    kept.append(line)
  if not added:
    kept.append(f"  - {new_tag_member}\n")
  new_block = "".join(kept)
  return fm_text[:m.start(1)] + new_block + fm_text[m.end(1):]


def _stamp_request_terminal(fm_text: str, *, request_class: str, request_status: str) -> str:
  """
  Apply the apply transition's frontmatter mutations to a request file.

  Args:
    fm_text: Full frontmatter text.
    request_class: Class verdict (the eight-value enum from `_K.CLASS_ENUM`).
    request_status: Lifecycle terminal — `accepted` or `rejected`.

  Returns:
    Frontmatter text with `request_class`, `request_status`, and the mirror tag stamped.
  """
  fm_text = _set_fm_scalar(fm_text, _K.REQUEST_CLASS, request_class)
  fm_text = _set_fm_scalar(fm_text, _K.REQUEST_STATUS, request_status)
  fm_text = _sweep_request_tag(fm_text, f"{_K.TAG_PREFIX}{request_status}")
  return fm_text


def _request_h1_title(body: str) -> str:
  """
  Extract the first H1 title (without the leading `# `) from a body.

  Args:
    body: Body text.

  Returns:
    The title text, or `"request"` when no H1 is present.
  """
  m = re.search(r"(?m)^# (.+)$", body)
  return m.group(1).strip() if m else "request"


def _request_content_block(body: str) -> str:
  """
  Extract the H1 + section content of a request body, skipping `# Routing` and `# History`.

  Args:
    body: Request body (post-frontmatter, post-status-callout).

  Returns:
    Concatenated content of the first H1 section and any non-routing/non-history H1
    sections following it, separated by blank lines.
  """
  segments: list[str] = []
  for sec in re.finditer(r"(?ms)^# (\S.*?)$(.*?)(?=^# \S|\Z)", body):
    title = sec.group(1).strip()
    # guard: skip the routing section — it is the apply worker's input, not body content
    if title.lower() == _K.ROUTING_H1[2:].lower():
      continue
    # guard: skip the history section — it is per-document review state, not request prose
    if title.lower() == _K.HISTORY_H1[2:].lower():
      continue
    chunk = f"# {title}\n{sec.group(2).rstrip()}\n"
    segments.append(chunk)
  return "\n".join(segments).strip()


def _today_iso() -> str:
  """
  Return today's UTC date in `YYYY-MM-DD` form.

  Returns:
    ISO-formatted date string.
  """
  return _dt.datetime.now(_dt.UTC).date().isoformat()


class _Attach:
  """
  Inline attach primitive — replaces the LLM-driven `spec.request-attach`
  skill for the apply transition. Handles Tier-3 fallback distribution
  (whole request body appended before the doc's `# Sources` section),
  `spec_source_requests` frontmatter dedupe + `## Requests` body
  projection, and the folder-note's `## Source requests` line.
  """

  @staticmethod
  def doc_filenames_for_kind(kind: str) -> list[str]:
    """
    Return the authored-doc filenames for a built-in entity kind.

    Args:
      kind: One of `feature` / `change` / `bug`.

    Returns:
      The doc filenames declared in the kind's layout (defaults to `design.md` +
      `plan.md` when the kind is operator-defined).
    """
    return _K.KIND_LAYOUT.get(kind, [ _K.DESIGN_MD, _K.PLAN_MD ])

  @staticmethod
  def wtr_doc_for_kind(kind: str) -> str:
    """
    Return the entity's WTR (whole-to-receive) doc filename.

    Args:
      kind: One of `feature` / `change` / `bug`.

    Returns:
      `bug.md` for the bug kind, `design.md` otherwise.
    """
    return _K.BUG_MD if kind == _K.BUG_KIND else _K.DESIGN_MD

  @staticmethod
  def kind_from_folder_note(folder_note: Path) -> str:
    """
    Infer the entity kind from a folder-note's path.

    Args:
      folder_note: Path to the entity's `<slug>/<slug>.md` folder-note.

    Returns:
      One of `feature` / `change` / `bug` (defaults to `change` when the parent
      folder is unrecognised).
    """
    category_segment = folder_note.parent.parent.name
    for k, folder in _K.KIND_FOLDER.items():
      if folder == category_segment:
        return k
    return _K.CHANGE_KIND

  @staticmethod
  def append_body_content(doc_path: Path, content_block: str) -> bool:
    """
    Append the request's content block to a doc, before `# Sources` when present.

    Args:
      doc_path: Path to the target authored doc.
      content_block: H1 + sections to splice (already stripped of routing / history).

    Returns:
      `True` when the doc text changed, `False` otherwise.
    """
    text = doc_path.read_text()
    # guard: skip empty content blocks
    if not content_block.strip():
      return False
    sources_idx = text.find(f"\n{_K.SOURCES_H1}\n")
    if sources_idx < 0:
      # Append at end of body
      new_text = text.rstrip() + "\n\n" + content_block + "\n"
    else:
      head = text[:sources_idx].rstrip()
      tail = text[sources_idx:]
      new_text = head + "\n\n" + content_block + "\n" + tail
    if new_text == text:
      return False
    doc_path.write_text(new_text)
    return True

  @staticmethod
  def ensure_source_request(doc_path: Path, request_wikilink: str,
                            request_display: str) -> bool:
    """
    Add the request to `spec_source_requests` frontmatter and re-project the body bullet list.

    Args:
      doc_path: Path to the target authored doc.
      request_wikilink: The request file's vault-relative wikilink path.
      request_display: Display gloss for the wikilink bullet.

    Returns:
      `True` when the doc text changed, `False` when the request was already listed.
    """
    text = doc_path.read_text()
    fm_text = text[:_parse_frontmatter(text)[1]]
    body = text[_parse_frontmatter(text)[1]:]
    values, _ = _parse_frontmatter(text)
    existing = values.get(_K.SPEC_SOURCE_REQUESTS) or []
    target_member = f"[[{request_wikilink}]]"
    # guard: idempotent — request already listed
    for raw in existing:
      raw_clean = raw.strip().strip('"').strip("'")
      pure = raw_clean.split("|")[0].strip("[]")
      if pure == request_wikilink:
        return False
    fm_text = _Attach._append_source_requests_fm(fm_text, target_member)
    body = _Attach._project_requests_body(body, request_wikilink, request_display)
    doc_path.write_text(fm_text + body)
    return True

  @staticmethod
  def _append_source_requests_fm(fm_text: str, member: str) -> str:
    """
    Append `member` to the `spec_source_requests:` frontmatter list (create when absent).

    Args:
      fm_text: Full frontmatter text.
      member: Wikilink-bracketed reference to append (e.g. `[[path/to/req]]`).

    Returns:
      Frontmatter text with the member appended to the list, or with the list
      created when the key was previously absent.
    """
    pat_inline = re.compile(rf"(?m)^{re.escape(_K.SPEC_SOURCE_REQUESTS)}\s*:\s*\[\s*\]\s*$")
    pat_block = re.compile(
        rf"(?m)^{re.escape(_K.SPEC_SOURCE_REQUESTS)}\s*:\s*\n((?:\s+- .*\n)*)",
    )
    if pat_inline.search(fm_text):
      replacement = (
          f"{_K.SPEC_SOURCE_REQUESTS}:\n  - \"{member}\""
      )
      return pat_inline.sub(replacement, fm_text, count = 1)
    m = pat_block.search(fm_text)
    if m:
      existing = m.group(1)
      new_block = existing + f"  - \"{member}\"\n"
      return fm_text[:m.start(1)] + new_block + fm_text[m.end(1):]
    close_idx = fm_text.rfind("---\n")
    # guard: cannot splice without a closing fence
    if close_idx < 0:
      return fm_text
    inject = f"{_K.SPEC_SOURCE_REQUESTS}:\n  - \"{member}\"\n"
    return fm_text[:close_idx] + inject + fm_text[close_idx:]

  @staticmethod
  def _project_requests_body(body: str, request_wikilink: str,
                             request_display: str) -> str:
    """
    Append the request bullet inside the `## Requests` projection markers.

    Args:
      body: Doc body (post-frontmatter).
      request_wikilink: Wikilink target.
      request_display: Display gloss.

    Returns:
      Body with the new bullet appended between the projection markers; the
      `# Sources` container and `## Requests` sub-section are created on demand
      when absent.
    """
    today = _today_iso()
    new_bullet = f"- [[{request_wikilink}|{request_display}]] — {today}"
    start_marker = _K.REQUESTS_MARKER_START
    end_marker = _K.REQUESTS_MARKER_END
    if start_marker in body and end_marker in body:
      pat = re.compile(
          rf"({re.escape(start_marker)}\n)(.*?)(\n?{re.escape(end_marker)})",
          re.DOTALL,
      )
      m = pat.search(body)
      if m:
        block = m.group(2)
        if new_bullet in block:
          return body
        new_block = block.rstrip("\n")
        new_block = (new_block + "\n" if new_block else "") + new_bullet
        return body[:m.start(2)] + new_block + body[m.end(2):]
    container = "\n".join([
        "",
        _K.SOURCES_H1,
        _K.SOURCES_TAG,
        "",
        _K.REQUESTS_H2,
        start_marker,
        new_bullet,
        end_marker,
        "",
    ])
    return body.rstrip() + "\n" + container


class _FolderNote:
  """
  Folder-note edits — appends the request wikilink to `## Source requests`.
  """

  @staticmethod
  def append_source_request(folder_note: Path, request_wikilink: str,
                            request_display: str) -> bool:
    """
    Append `- [[<wikilink>|<display>]] — <today>` to the folder-note's `## Source requests` section.

    Args:
      folder_note: Path to `<slug>/<slug>.md`.
      request_wikilink: Request file's wikilink target.
      request_display: Display gloss for the bullet.

    Returns:
      `True` when the folder-note text changed, `False` when the bullet was already
      present (idempotent re-run).
    """
    text = folder_note.read_text()
    today = _today_iso()
    bullet = f"- [[{request_wikilink}|{request_display}]] — {today}"
    if f"[[{request_wikilink}]]" in text or f"[[{request_wikilink}|" in text:
      return False
    section_re = re.compile(
        rf"(?ms)^{re.escape(_K.SOURCE_REQUESTS_H2)}\s*$(.*?)(?=^## \S|^# \S|\Z)",
    )
    m = section_re.search(text)
    if m:
      block = m.group(1)
      cleaned = block.rstrip("\n")
      new_block = cleaned + ("\n\n" if cleaned else "\n") + bullet + "\n"
      new_text = text[:m.start(1)] + new_block + text[m.end(1):]
    else:
      # Insert section before ## History when present, otherwise append.
      hist_idx = text.find(f"\n{_K.HISTORY_H2}\n")
      block_text = f"{_K.SOURCE_REQUESTS_H2}\n\n{bullet}\n\n"
      if hist_idx >= 0:
        new_text = text[:hist_idx + 1] + block_text + text[hist_idx + 1:]
      else:
        new_text = text.rstrip() + "\n\n" + block_text
    folder_note.write_text(new_text)
    return True


class _Apply:
  """
  Top-level apply orchestrator. Owns the routing parse → enact → stamp → commit pipeline.
  """

  def __init__(self, *, file_path: Path, author_name: str, author_email: str) -> None:
    """
    Construct an apply orchestrator scoped to one request file.

    Args:
      file_path: Absolute path to the request markdown file.
      author_name: Git author name for the atomic commit (bot identity).
      author_email: Git author email for the atomic commit.
    """
    self.file_path = file_path.resolve()
    self.repo = _repo_root(self.file_path.parent)
    self.author_name = author_name
    self.author_email = author_email
    self.specs_cli = _resolve_sibling_cli(_K.CLI_LAZYCORTEX_SPECS)
    self.review_cli = _resolve_sibling_cli(_K.CLI_LAZYCORTEX_REVIEW)
    self.populated_docs: list[Path] = []
    self.spawn_folder_notes: list[Path] = []
    self.attach_folder_notes: list[Path] = []

  @property
  def request_wikilink(self) -> str:
    """
    The request file's wikilink target — the repo-relative path with the `.md` suffix dropped.
    """
    rel = self.file_path.resolve().relative_to(self.repo)
    return str(rel.with_suffix(""))

  def _load_product_record(self, product: str) -> dict:
    """
    Look up a product record from `.claude/lazy.settings.json`.

    Args:
      product: Product compound-key.

    Returns:
      The product record (`spec_path` and friends).
    """
    settings_path = self.repo / _K.CLAUDE_DIR / _K.SETTINGS_FILE
    if not settings_path.exists():
      _fail(_K.CAT_LOGICAL, f".claude/lazy.settings.json absent at {settings_path}")
    try:
      data = json.loads(settings_path.read_text())
    except json.JSONDecodeError as e:
      _fail(_K.CAT_LOGICAL, f".claude/lazy.settings.json malformed: {e}")
    products_section = data.get(_K.PRODUCTS) or {}
    record = products_section.get(product) if isinstance(products_section, dict) else None
    if not isinstance(record, dict):
      _fail(_K.CAT_LOGICAL,
            f"product '{product}' not registered in lazy.settings.json[{_K.PRODUCTS}]")
    if _K.SPEC_PATH not in record:
      _fail(_K.CAT_LOGICAL, f"product '{product}' has no {_K.SPEC_PATH}")
    return record

  def _default_product(self) -> str:
    """
    Pick the default product key.

    Returns:
      The first product key from settings; aborts when no product is registered.
    """
    settings_path = self.repo / _K.CLAUDE_DIR / _K.SETTINGS_FILE
    data = json.loads(settings_path.read_text())
    products_section = data.get(_K.PRODUCTS) or {}
    keys = sorted(
        k for k, v in products_section.items()
        if isinstance(k, str) and not k.startswith("_") and isinstance(v, dict)
    )
    # guard: at least one product must exist before apply can act on a spawn
    if not keys:
      _fail(_K.CAT_LOGICAL, _K.ERR_NO_PRODUCTS)
    return keys[0]

  def _spawn(self, kind: str, slug: str) -> Path:
    """
    Run the scaffold-asset subprocess to create the new entity folder.

    Args:
      kind: One of `feature` / `change` / `bug`.
      slug: Asset slug.

    Returns:
      Absolute path to the new folder-note (`<spec_path>/<folder>/<slug>/<slug>.md`).
    """
    product = self._default_product()
    record = self._load_product_record(product)
    spec_path = record[_K.SPEC_PATH]
    folder = _K.KIND_FOLDER[kind]
    target_folder = self.repo / spec_path / folder / slug
    folder_note = target_folder / f"{slug}.md"
    if folder_note.exists():
      # Idempotent — earlier apply attempt already scaffolded; no-op.
      return folder_note
    res = subprocess.run(
        [ str(self.specs_cli), "scaffold-asset", product, kind, slug ],
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False,
    )
    if res.returncode != 0:
      _fail(_K.CAT_LOGICAL,
            f"scaffold-asset failed for {kind} '{slug}': "
            f"exit={res.returncode} stderr={res.stderr.strip()[:240]}")
    return folder_note

  def _resolve_attach_folder_note(self, attach_target: str) -> Path:
    """
    Map a routing wikilink target onto an absolute folder-note path.

    Args:
      attach_target: The wikilink content (e.g. `request/products/test/features/csv-export/csv-export`).

    Returns:
      Absolute path to the resolved folder-note.
    """
    rel = Path(attach_target + ".md")
    candidate = self.repo / rel
    if not candidate.is_file():
      _fail(_K.CAT_LOGICAL,
            f"attach target '{attach_target}' does not resolve to a folder-note ({candidate})")
    return candidate

  def _attach_to_folder_note(self, folder_note: Path, request_body: str,
                             request_display: str) -> list[Path]:
    """
    Distribute the request body into the entity's WTR doc + maintain Sources / folder-note.

    Args:
      folder_note: Absolute path to `<slug>/<slug>.md`.
      request_body: Request body (post-frontmatter, post-status-callout, post-routing).
      request_display: Display gloss used in the `## Requests` and folder-note bullets.

    Returns:
      List of authored docs that were populated (used to open review on each).
    """
    kind = _Attach.kind_from_folder_note(folder_note)
    wtr = _Attach.wtr_doc_for_kind(kind)
    wtr_path = folder_note.parent / wtr
    content_block = _request_content_block(request_body)
    populated: list[Path] = []
    if wtr_path.is_file():
      changed_body = _Attach.append_body_content(wtr_path, content_block)
      changed_sources = _Attach.ensure_source_request(
          wtr_path, self.request_wikilink, request_display,
      )
      if changed_body or changed_sources:
        populated.append(wtr_path)
    _FolderNote.append_source_request(folder_note, self.request_wikilink, request_display)
    return populated

  def _open_review(self, doc_path: Path) -> None:
    """
    Open a review cycle on a populated doc via the `lazycortex-review start` subcommand.

    Args:
      doc_path: Absolute path to the populated authored doc.
    """
    res = subprocess.run(
        [ str(self.review_cli), "start", str(doc_path) ],
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False,
    )
    # guard: review-start is idempotent — non-zero exit on already-open is benign;
    # surface only when stderr names an unexpected failure
    if res.returncode != 0 and _K.REVIEW_START_IDEMPOTENT_MARK not in (res.stderr or "").lower():
      _fail(_K.CAT_LOGICAL,
            f"lazycortex-review start failed on {doc_path}: "
            f"exit={res.returncode} stderr={res.stderr.strip()[:240]}")

  def _stamp_request_file(self, *, request_class: str, request_status: str,
                          resolved_wikilinks: list[str], reject_reason: str | None) -> None:
    """
    Apply the request file's terminal mutations: frontmatter + status callout + Routing strip.

    Args:
      request_class: Eight-value enum verdict.
      request_status: `accepted` or `rejected`.
      resolved_wikilinks: Wikilink paths to enumerate in the success callout body.
      reject_reason: Optional one-line rejection reason.
    """
    text = self.file_path.read_text()
    _, fm_end = _parse_frontmatter(text)
    fm_text = text[:fm_end]
    body = text[fm_end:]
    fm_text = _stamp_request_terminal(
        fm_text, request_class = request_class, request_status = request_status,
    )
    body = _strip_routing(body)
    body = _strip_prior_status_callout(body)
    accepted = request_status == _K.STATUS_ACCEPTED
    callout = _format_status_callout(
        accepted = accepted, wikilinks = resolved_wikilinks, reason = reject_reason,
    )
    body = _insert_status_callout(body, callout)
    self.file_path.write_text(fm_text + body)

  def _commit(self, *, subject: str) -> None:
    """
    Stage every modified path and commit under the bot identity in one atomic step.

    Args:
      subject: One-line commit subject describing the staged diff.
    """
    add_res = subprocess.run(
        [ _K.GIT, "add", "-A" ],
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False,
    )
    if add_res.returncode != 0:
      _fail(_K.CAT_LOGICAL,
            f"git add failed: exit={add_res.returncode} stderr={add_res.stderr.strip()[:240]}")
    # guard: nothing to commit — every step was a no-op (idempotent re-run on
    # terminal state); skip the commit step to keep the tree clean
    status_res = subprocess.run(
        [ _K.GIT, "diff", "--cached", "--quiet" ],
        cwd = str(self.repo),
        check = False,
    )
    # guard: empty staged diff — nothing to commit on this apply pass
    if status_res.returncode == 0:
      return
    commit_res = subprocess.run(
        [
            _K.GIT,
            "-c", f"user.name={self.author_name}",
            "-c", f"user.email={self.author_email}",
            "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", subject,
        ],
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False,
    )
    if commit_res.returncode != 0:
      _fail(_K.CAT_LOGICAL,
            f"git commit failed: exit={commit_res.returncode} "
            f"stderr={commit_res.stderr.strip()[:240]}")

  def run(self) -> int:
    """
    Drive one apply transition on the request file.

    Returns:
      Exit code: `0` on success or idempotent terminal-state skip; `1` on logical error.
    """
    text = self.file_path.read_text()
    values, fm_end = _parse_frontmatter(text)
    status = values.get(_K.REQUEST_STATUS)
    # guard: terminal-state idempotence (md-scan filter normally excludes these,
    # but a same-tick race could still hand us one)
    if status in ( _K.STATUS_ACCEPTED, _K.STATUS_REJECTED ):
      print(json.dumps({ "outcome": _K.OUTCOME_SUCCESS, "skip": _K.OUTCOME_TERMINAL_SKIP }))
      return 0
    body = text[fm_end:]
    cls, spawn_targets, attach_targets, _ = _parse_routing(body)
    request_class = cls or values.get(_K.REQUEST_CLASS) or _K.CLASS_UNKNOWN
    # Display gloss must come from the request's OWN H1, not from `# Routing` (which is the
    # first H1 in the raw body before strip). Read from `_request_content_block` which already
    # filters out `# Routing` and `# History` sections.
    request_display = _request_h1_title(_request_content_block(body))
    resolved_wikilinks: list[str] = []
    if not spawn_targets and not attach_targets:
      self._stamp_request_file(
          request_class = request_class,
          request_status = _K.STATUS_REJECTED,
          resolved_wikilinks = [],
          reject_reason = _K.REJECT_REASON_DEFAULT,
      )
      self._commit(
          subject = f"apply: stamp rejected on {self.file_path.relative_to(self.repo)}",
      )
      print(json.dumps({ "outcome": _K.OUTCOME_SUCCESS, "result": _K.STATUS_REJECTED,
                         "request_class": request_class }))
      return 0
    for kind, slug in spawn_targets:
      folder_note = self._spawn(kind, slug)
      rel = folder_note.relative_to(self.repo).with_suffix("")
      resolved_wikilinks.append(str(rel))
      populated = self._attach_to_folder_note(folder_note, body, request_display)
      self.populated_docs.extend(populated)
      self.spawn_folder_notes.append(folder_note)
    for target in attach_targets:
      folder_note = self._resolve_attach_folder_note(target)
      resolved_wikilinks.append(target)
      populated = self._attach_to_folder_note(folder_note, body, request_display)
      self.populated_docs.extend(populated)
      self.attach_folder_notes.append(folder_note)
    for doc in self.populated_docs:
      self._open_review(doc)
    self._stamp_request_file(
        request_class = request_class,
        request_status = _K.STATUS_ACCEPTED,
        resolved_wikilinks = resolved_wikilinks,
        reject_reason = None,
    )
    rel_path = self.file_path.relative_to(self.repo)
    self._commit(
        subject = f"apply: stamp accepted + strip Routing on {rel_path}",
    )
    print(json.dumps({
        "outcome": _K.OUTCOME_SUCCESS,
        "result": _K.STATUS_ACCEPTED,
        "request_class": request_class,
        "spawn_count": len(self.spawn_folder_notes),
        "attach_count": len(self.attach_folder_notes),
        "populated_count": len(self.populated_docs),
    }))
    return 0


def main(argv: list[str]) -> int:
  """
  Run the `apply-request` subcommand against one request file.

  Args:
    argv: Subcommand argv tail (positional `<file>` + optional `--author-*` flags).

  Returns:
    Process exit code: `0` on success / idempotent skip, `1` on logical error,
    `2` on argparse failure / missing file.
  """
  parser = argparse.ArgumentParser(prog = _K.PROG)
  parser.add_argument(_K.ARG_FILE, type = Path)
  parser.add_argument(_K.ARG_AUTHOR_NAME, default = _K.BOT_NAME_DEFAULT)
  parser.add_argument(_K.ARG_AUTHOR_EMAIL, default = _K.BOT_EMAIL_DEFAULT)
  args = parser.parse_args(argv)
  file_path: Path = args.file
  # guard: argparse hands relative paths straight through; resolve to absolute
  if not file_path.is_absolute():
    file_path = file_path.resolve()
  # guard: filesystem path idiom — markdown file extension check
  if not file_path.exists() or file_path.suffix.lower() != _K.MD_SUFFIX:
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2
  apply = _Apply(
      file_path = file_path,
      author_name = args.author_name,
      author_email = args.author_email,
  )
  return apply.run()


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
