"""
Decisions-registry primitive — the sole writer of every `decisions.md` in the spec catalog.

Four operations, dispatched from the `decide` CLI subcommand: `add` (a fresh record),
`supersede` (a fresh record that also marks an older one `superseded-by`), `obsolete` (marks a
record `obsolete — <reason>`), and `promote` (transfers `[!decision]` blocks out of a living
doc's body — `design.md` / `bug.md` / `tech.md` / `architecture.md` — into its sibling registry,
replacing each block with a reference link). `decisions.md` is never scaffolded: the file is
created lazily, with its own header + frontmatter, on the first record written into it.

Numbering (`max + 1` within one file) is guarded by an exclusive file lock under the enclosing
repo's `.git/`, named from the registry file's own path — see `_decisions_lock`. `promote` refuses
on a non-living-doc role, and — for an asset-level doc — on the owning asset's own
`spec_cancelled` / `spec_halted` / `spec_released` flags, checked here rather than by any caller.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Iterator


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402

# The document type this module's registry files declare themselves as.
_DECISIONS_TYPE = "decisions"


# ----------------------------------------------------------------------------------------
class _K:
  """
  String constants — settings/frontmatter keys, dict-result field names, CLI tokens — used more
  than once across this module, per the plugin's per-file small-constant convention.

  Attributes:
    CLAUDE_DIR: The `.claude` directory segment.
    SETTINGS_FILE: Filename of the settings file.
    PRODUCTS: Settings key holding the product registry.
    SPEC_PATH: Settings key naming a product's spec directory.
    SPEC_ROLE: Frontmatter key naming a doc's role, read to gate `promote` to living docs.
    GIT_DIR: The `.git` entry marking a repo root / holding the exclusive lock file.
    TAG_PROTECTED: The `#protected/` H1-section owner-tag prefix (cross-plugin owned sections).
    TAG_EXPERT: The `#expert/` H1-section owner-tag prefix (review-cycle-scoped sections).
    NUMBER: A parsed record's `D-NNN` integer field.
    THESIS: A parsed record's or decision-block's thesis-line field.
    STATUS: A parsed record's `Status:` field, or an operation result's outcome field.
    DATE: A parsed record's `Date:` field.
    ORIGIN: A parsed record's `Origin:` field.
    BODY: A parsed record's full body text (everything below `Origin:`, verbatim).
    START: A decision-block's starting line index (half-open range).
    END: A decision-block's ending line index (half-open range).
    RAW_LINES: A decision-block's own raw source lines.
    ID: An operation result's record-id field.
    FILE: An operation result's registry-file-path field.
    OLD_ID: `supersede`'s result field naming the superseded record.
    NEW_ID: `supersede`'s result field naming the fresh record.
    REASON: A refusal result's reason field.
    TOUCHED_PATHS: `promote`'s result field listing every path it wrote.
    RECORDS: `promote`'s result field listing every fresh record it wrote.
    OP: The CLI subparser dest naming which operation was selected.
    OP_ADD: The `add` operation token.
    OP_SUPERSEDE: The `supersede` operation token.
    OP_OBSOLETE: The `obsolete` operation token.
    OP_PROMOTE: The `promote` operation token.
    ARG_DECISIONS_PATH: CLI positional argument name for the registry file path.
    ARG_THESIS: CLI positional argument name for a record's thesis.
    ARG_OLD_ID: CLI positional argument name for `supersede`'s target record id.
    ARG_RECORD_ID: CLI positional argument name for `obsolete`'s target record id.
    ARG_REASON: CLI positional argument name for `obsolete`'s reason text.
    ARG_DOC_PATH: CLI positional argument name for `promote`'s living-doc path.
    FLAG_WHY: CLI flag name for the `**Why.**` field.
    FLAG_REJECTED: CLI flag name for the `**Rejected.**` field.
    FLAG_ORIGIN: CLI flag name for the `Origin:` field.
    FLAG_TODAY: CLI flag name overriding the recorded date.
    PROG: CLI program name shown in `--help` output.
  """

  CLAUDE_DIR = ".claude"
  SETTINGS_FILE = "lazy.settings.json"
  PRODUCTS = "products"
  SPEC_PATH = "spec_path"
  SPEC_ROLE = "spec_role"
  GIT_DIR = ".git"
  TAG_PROTECTED = "#protected/"
  TAG_EXPERT = "#expert/"
  NUMBER = "number"
  THESIS = "thesis"
  STATUS = "status"
  DATE = "date"
  ORIGIN = "origin"
  BODY = "body"
  START = "start"
  END = "end"
  RAW_LINES = "raw_lines"
  ID = "id"
  FILE = "file"
  OLD_ID = "old_id"
  NEW_ID = "new_id"
  REASON = "reason"
  TOUCHED_PATHS = "touched_paths"
  RECORDS = "records"
  OP = "op"
  OP_ADD = "add"
  OP_SUPERSEDE = "supersede"
  OP_OBSOLETE = "obsolete"
  OP_PROMOTE = "promote"
  ARG_DECISIONS_PATH = "decisions_path"
  ARG_THESIS = "thesis"
  ARG_OLD_ID = "old_id"
  ARG_RECORD_ID = "record_id"
  ARG_REASON = "reason"
  ARG_DOC_PATH = "doc_path"
  FLAG_WHY = "--why"
  FLAG_REJECTED = "--rejected"
  FLAG_ORIGIN = "--origin"
  FLAG_TODAY = "--today"
  PROG = "lazycortex-specs decide"


# ----------------------------------------------------------------------------------------
class _Result:
  """
  Result-dict status tokens returned by every operation in this module.

  Attributes:
    ADDED: A fresh record was written.
    DUPLICATE: A dedup match already existed — nothing was written.
    SUPERSEDED: A fresh record was written and an older one marked `superseded-by`.
    OBSOLETED: An existing record was marked `obsolete`.
    PROMOTED: One or more `[!decision]` blocks were transferred out of a living doc.
    NOOP: `promote` found no `[!decision]` blocks — nothing was written.
    REFUSED: The operation was rejected; no mutation happened.
  """

  ADDED = "added"
  DUPLICATE = "duplicate"
  SUPERSEDED = "superseded"
  OBSOLETED = "obsoleted"
  PROMOTED = "promoted"
  NOOP = "noop"
  REFUSED = "refused"


DECISIONS_BASENAME = "decisions.md"

# `spec_role` values a `promote` call is willing to read blocks from — the living docs. A CLOSED,
# named set: any OTHER role defaults to candidates-only (lazy-spec.set-stage's own trigger prose states
# this as a rule). Plans are a decomposition of already-accepted decisions and die with their
# feature; reports carry only candidates, never decisions themselves (spec-decisions-design.md
# § on how a decision enters the registry file).
_LIVING_ROLES = frozenset({"design", "bug", "tech", "architecture"})

# The three asset-terminal flags `promote` refuses on, checked against the owning asset's own
# status folder-note — unconditionally, regardless of caller (spec-decisions-design.md
# § on assets outside the automation).
_HALT_FLAGS = ("spec_cancelled", "spec_halted", "spec_released")

# Reverse of `scaffold_asset.py`'s `_Category.BUILTIN_FOLDERS` — maps an on-disk category folder
# name back to its singular `category` axis value; an operator-defined category folder maps to
# itself (scaffold_asset.py's own convention for non-built-in categories).
_CATEGORY_FOLDER_TO_KEY = {"features": "feature", "changes": "change", "bugs": "bug"}


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class _Context:
  """
  Resolved product/asset placement for a `decisions.md` path or a living doc's own path.

  Attributes:
    content_root: The spec content-root (`spec_content_root`), used to build path-qualified
      wikilinks relative to it.
    product: The product's settings-dict key (e.g. `core`) — the literal header value.
    category: The singular category axis value (`feature` / `change` / `bug` / operator-defined),
      or None at product level (no category exists there).
    slug: The asset's folder slug, or None at product level.
    asset_dir: The asset's own folder, or None at product level.
  """

  content_root: Path
  product: str
  category: str | None
  slug: str | None
  asset_dir: Path | None


def _resolve_context(target_path: Path) -> _Context:
  """
  Resolve the product/asset placement of a `decisions.md` path or a living doc's own path.

  Reads `.claude/lazy.settings.json[products]` and matches the target's parent directory
  (relative to the spec content-root) against each product's `spec_path`, picking the longest
  (most specific) match. A parent equal to a product's `spec_path` is product-level; a parent one
  or more segments deeper is asset-level.

  Args:
    target_path: The `decisions.md` path (may not yet exist) or a living doc's own path; only
      its parent directory is used for resolution.

  Returns:
    The resolved `_Context`.

  Raises:
    ValueError: When no registered product's `spec_path` covers the target's parent directory.
  """
  target_dir = target_path.resolve().parent
  settings_root = spec_paths.find_settings_root(target_dir)
  content_root = spec_paths.spec_content_root(settings_root).resolve()
  settings_path = settings_root / _K.CLAUDE_DIR / _K.SETTINGS_FILE
  data = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
  products = data.get(_K.PRODUCTS) or {}

  # match the target dir against every registered product's spec_path; the longest (most
  # specific) match wins when spec_path values happen to nest
  rel_str = target_dir.relative_to(content_root).as_posix()
  best_key: str | None = None
  best_spec_path: str | None = None
  for key, record in products.items():
    # guard: malformed product record — skip
    if not isinstance(record, dict):
      continue
    sp = record.get(_K.SPEC_PATH)
    # guard: no spec_path on this record, or the target dir isn't under it — not a candidate
    if not sp or not (rel_str == sp or rel_str.startswith(sp + "/")):
      continue
    if best_spec_path is None or len(sp) > len(best_spec_path):
      best_key, best_spec_path = key, sp

  # guard: no product's spec_path covers the target — caller passed a path outside the catalog
  if best_key is None or best_spec_path is None:
    raise ValueError(f"no product registered whose spec_path covers '{rel_str}'")

  # derive the placement fields shared by both product- and asset-level shells
  remainder = rel_str[len(best_spec_path):].strip("/")
  # guard: target dir IS the product root — product-level, no category/slug
  if not remainder:
    return _Context(content_root = content_root, product = best_key,
                    category = None, slug = None, asset_dir = None)

  # target dir is one level under an asset category folder — resolve category + slug + asset_dir
  parts = remainder.split("/")
  category_folder = parts[0]
  slug = parts[1] if len(parts) > 1 else parts[0]
  category = _CATEGORY_FOLDER_TO_KEY.get(category_folder, category_folder)
  asset_dir = content_root / best_spec_path / category_folder / slug
  return _Context(content_root = content_root, product = best_key,
                  category = category, slug = slug, asset_dir = asset_dir)


# ----------------------------------------------------------------------------------------
# File-level lock — O_CREAT | O_EXCL, one per registry file, under the enclosing repo's `.git/`.

# Decision: exclusive `O_CREAT | O_EXCL` create, not a copy of the core staging lock's
# read-then-replace algorithm — read-then-replace leaves a window where two processes both
# consider themselves the holder; an exclusive create never does, so only one process can ever
# hold this lock at a time.

_LOCK_WAIT_SECONDS = 30.0        # mirrors staging_lock.DEFAULT_WAIT_SECONDS by meaning
_LOCK_MAX_HOLD_SECONDS = 600.0   # mirrors staging_lock.DEFAULT_MAX_HOLD_SECONDS by meaning
_LOCK_POLL_MIN_S = 0.05
_LOCK_POLL_MAX_S = 0.2


def _git_repo_root(start: Path) -> Path:
  """
  Walk up from `start` to the nearest ancestor holding a `.git` entry.

  Returns:
    The first ancestor (inclusive) carrying `.git`; `start` itself when none is found.
  """
  cur = start.resolve()
  while cur != cur.parent:
    # guard: found the repo root
    if (cur / _K.GIT_DIR).exists():
      return cur
    cur = cur.parent
  return start.resolve()


def _lock_file_path(decisions_path: Path) -> Path:
  """
  Derive the exclusive lock file path for a `decisions.md` registry file.

  The lock lives under the enclosing repo's `.git/` (never inside the spec content tree — a
  worktree file would make the tree dirty and could trip the daemon's clean-tree guard), named
  from a hash of the registry file's own repo-relative path so distinct registries never collide.

  Returns:
    The lock file path.
  """
  repo = _git_repo_root(decisions_path.parent)
  target = decisions_path.resolve()
  # a target outside the repo (no plausible caller today, but not a contract violation either)
  # falls back to its own absolute path rather than raising
  try:
    rel_str = str(target.relative_to(repo))
  except ValueError:
    rel_str = str(target)
  digest = hashlib.sha1(rel_str.encode()).hexdigest()[:16]
  return repo / _K.GIT_DIR / f"lazy-decide-{digest}.lock"


@contextmanager
def _decisions_lock(decisions_path: Path) -> Iterator[None]:
  """
  Hold the exclusive per-registry lock for the duration of a read-count-write sequence.

  Polls with jittered backoff while a live peer holds the lock; a lock file older than
  `_LOCK_MAX_HOLD_SECONDS` is considered abandoned and broken unconditionally (no pid/host probe
  — an `O_CREAT | O_EXCL` lock never records a holder identity, unlike the core staging lock).

  Yields:
    None. The lock is released on exit, including on an exception raised inside the `with` block.

  Raises:
    TimeoutError: When the lock cannot be acquired within `_LOCK_WAIT_SECONDS`.
  """
  lock_path = _lock_file_path(decisions_path)
  lock_path.parent.mkdir(parents = True, exist_ok = True)
  deadline = time.time() + _LOCK_WAIT_SECONDS
  # poll until the exclusive create succeeds, a stale peer is broken, or the deadline passes
  while True:
    try:
      fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
      os.close(fd)
      break
    except FileExistsError:
      pass
    # a lock observed as present a moment ago but gone by the time it's stat'd (raced with its
    # own holder's release) is treated the same as still-contended below, rather than retried
    # instantly — it still waits its turn through the deadline/sleep check instead of spinning
    try:
      age = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
      pass
    else:
      # guard: an existing lock older than the max-hold ceiling is abandoned — break it and retry
      if age > _LOCK_MAX_HOLD_SECONDS:
        try:
          lock_path.unlink()
        except FileNotFoundError:
          pass
        continue
    # guard: wait deadline reached without acquiring the lock
    if time.time() >= deadline:
      raise TimeoutError(f"decisions lock busy: {lock_path}")
    time.sleep(random.uniform(_LOCK_POLL_MIN_S, _LOCK_POLL_MAX_S))
  try:
    yield
  finally:
    # best-effort release — a lock already gone (broken by a peer's stale-rule) is not an error
    try:
      lock_path.unlink()
    except FileNotFoundError:
      pass


# ----------------------------------------------------------------------------------------
# Record parsing, formatting, insertion.

_HEADING_RE = re.compile(r"(?m)^## D-(\d{3,}) — (.*)$")


def _split(text: str) -> tuple[str, str]:
  """
  Split a `decisions.md` file's full text into its frontmatter block and body.

  Returns:
    `(fm_text, body)` — `fm_text` includes the opening/closing `---` fences.
  """
  _, fm_end = flip_gate._parse_frontmatter(text)
  return text[:fm_end], text[fm_end:]


def _normalize_text(value: str) -> str:
  """
  Collapse a field's whitespace for dedup comparison.

  Returns:
    `value` stripped and with internal runs of whitespace collapsed to a single space.
  """
  return re.sub(r"\s+", " ", value.strip())


def _dedup_key(thesis: str, body: str) -> str:
  """
  Build the normalized-content key used to detect a repeated decision.

  Args:
    thesis: The record's thesis line (already stripped of `> ` prefixes and the heading marker).
    body: The record's full body text (already stripped of `> ` prefixes and the `Status:` /
      `Date:` / `Origin:` metadata lines).

  Returns:
    A key equal for two records whose thesis + full body are the same modulo whitespace — the
    `**Supersedes.**` line is never part of the key (spec-decisions-design.md
    § on promoting a living doc's decisions, which consumes the Supersedes command rather than
    storing it), since it is stripped out before this is called.
  """
  return "\x00".join(_normalize_text(v) for v in (thesis, body))


def _protected_boundary_line(lines: list[str]) -> int:
  """
  Locate the line index where registry CONTENT ends and a foreign protected section begins.

  Shared by `_insert_record` (the insertion boundary) and `_parse_records` (so a trailing
  protected section is never swept into the last record's parsed body).

  Guarantees:
    - Never treats a line belonging to a foreign `#protected/<owner>/...` H1 section as part of
      the registry's own content.

  Args:
    lines: The registry body's lines (via `str.splitlines()`).

  Returns:
    The line index of the first H1 heading whose next non-blank line is a `#protected/` tag, or
    `len(lines)` when no such section exists.
  """

  # Contract:
  # a line belonging to a foreign `#protected/<owner>/...` H1 section — owned by another plugin
  # and preserved byte-for-byte — is never registry content; every caller of this boundary stops here

  # scan every H1 heading in order; the first one whose next non-blank line is a `#protected/`
  # tag marks the boundary
  i = 0
  while i < len(lines):
    if re.match(r"^#\s", lines[i]):
      j = i + 1
      while j < len(lines) and not lines[j].strip():
        j += 1
      if j < len(lines) and lines[j].startswith(_K.TAG_PROTECTED):
        return i
    i += 1
  return len(lines)


def _parse_records(body: str) -> list[dict]:
  """
  Parse every `## D-NNN — <thesis>` record out of a `decisions.md` body.

  Args:
    body: The registry file's body text (post-frontmatter).

  Returns:
    A list of dicts, document order, each carrying `number`, `thesis`, `status`, `date`,
    `origin`, `body` (the full body text below `Origin:`, verbatim, trailing blank lines
    trimmed).
  """
  lines = body.splitlines()
  content_end = _protected_boundary_line(lines)
  headings = [(i, m) for i in range(content_end) if (m := _HEADING_RE.match(lines[i])) is not None]
  records = []
  # each record's chunk runs from its own heading to the next record's heading, or the content
  # boundary (whichever ends the registry's own content first)
  for idx, (line_no, m) in enumerate(headings):
    next_line_no = headings[idx + 1][0] if idx + 1 < len(headings) else content_end
    meta_lines = lines[line_no + 1:next_line_no]
    status = date = origin = ""
    body_start = 0
    for k, ln in enumerate(meta_lines):
      status_m = re.match(r"^Status:\s*(.*)$", ln)
      date_m = re.match(r"^Date:\s*(.*)$", ln)
      origin_m = re.match(r"^Origin:\s*(.*)$", ln)
      if status_m:
        status = status_m.group(1).strip()
      elif date_m:
        date = date_m.group(1).strip()
      elif origin_m:
        origin = origin_m.group(1).strip()
        body_start = k + 1
    # the body starts after the blank line separating it from the Origin metadata line
    while body_start < len(meta_lines) and not meta_lines[body_start].strip():
      body_start += 1
    body_lines = meta_lines[body_start:]
    while body_lines and not body_lines[-1].strip():
      body_lines.pop()
    records.append({
        _K.NUMBER: int(m.group(1)),
        _K.THESIS: m.group(2).strip(),
        _K.STATUS: status,
        _K.DATE: date,
        _K.ORIGIN: origin,
        _K.BODY: "\n".join(body_lines),
    })
  return records


def _next_number(body: str) -> int:
  """
  Compute the next free `D-NNN` number within one registry body.

  Returns:
    `max(existing) + 1`, or `1` when the body carries no records yet.
  """
  nums = [int(m.group(1)) for m in _HEADING_RE.finditer(body)]
  return (max(nums) + 1) if nums else 1


def _format_record(number: int, thesis: str, body: str, *, origin: str, today: str) -> str:
  """
  Render one decision record's markdown text (no trailing newline).

  Args:
    number: The record's `D-NNN` integer.
    thesis: The record's thesis line.
    body: The record's full body text, verbatim. Never carries a `**Supersedes.**` line — that
      command line is consumed by `promote`, not stored (spec-decisions-design.md
      § on promoting a living doc's decisions, which consumes the Supersedes command rather than
      storing it).
    origin: The `Origin:` line value.
    today: The `Date:` line value.

  Returns:
    The `## D-NNN — <thesis>` block with its `Status` / `Date` / `Origin` lines followed by
    `body` byte-for-byte.
  """
  return (
      f"## D-{number:03d} — {thesis}\n"
      "Status: active\n"
      f"Date: {today}\n"
      f"Origin: {origin}\n"
      "\n"
      f"{body}"
  )


def _set_status(body: str, number: int, new_status: str) -> tuple[str, bool]:
  """
  Rewrite the `Status:` line of one existing record — the only line a record may ever change.

  Returns:
    `(new_body, changed)` — `changed` is False (body returned unmodified) when the record or its
    `Status:` line could not be located.
  """
  heading_m = re.search(rf"(?m)^## D-{number:03d} — .*$", body)
  # guard: no such record in this body
  if heading_m is None:
    return body, False
  status_m = re.search(r"(?m)^Status:.*$", body[heading_m.end():])
  # guard: record found but malformed — no Status line to rewrite
  if status_m is None:
    return body, False
  start = heading_m.end() + status_m.start()
  end = heading_m.end() + status_m.end()
  return body[:start] + f"Status: {new_status}" + body[end:], True


def _insert_record(body: str, record_text: str) -> str:
  """
  Insert a formatted record at the end of the CONTENT, before a `#protected/`-tagged H1 section.

  Mirrors `flip_gate._append_under_heading`'s treatment of a `#protected/...` tag line as NOT a
  heading boundary in spirit, but this primitive has no named container heading to insert under —
  `decisions.md` records are top-level `## D-NNN` blocks, so the insertion point is simply "before
  the first H1 whose first non-blank content line is a `#protected/` tag", or end-of-body when no
  such section exists.

  Args:
    body: The registry file's body text (everything after the frontmatter, including its own
      title header).
    record_text: The new record's rendered text (no leading/trailing blank lines).

  Returns:
    The updated body text, newline-terminated.
  """
  lines = body.splitlines()
  insert_at = _protected_boundary_line(lines)

  # trim trailing blank lines directly above the insertion point so the new record sits flush
  trim_end = insert_at
  while trim_end > 0 and not lines[trim_end - 1].strip():
    trim_end -= 1

  # assemble: existing content, one blank separator, the new record, then (when something
  # follows, e.g. a protected section) another blank separator and the untouched tail
  after = lines[insert_at:]
  assembled = lines[:trim_end]
  if assembled:
    assembled.append("")
  assembled.extend(record_text.splitlines())
  if after:
    assembled.append("")
    assembled.extend(after)
  return "\n".join(assembled) + "\n"


def _new_file_shell(decisions_path: Path) -> tuple[str, str]:
  """
  Build the frontmatter + header body for a `decisions.md` file that does not exist yet.

  Args:
    decisions_path: The registry file's target path (used only to resolve product/asset context).

  Returns:
    `(fm_text, body)` per spec-decisions-design.md §§ on the record layout and the frontmatter
    shape.
  """
  ctx = _resolve_context(decisions_path)
  fm_lines = ["---", "spec_role: decisions", "wiki_pinned_topics:",
              "  - wiki/doc-kind/decisions", f"  - wiki/product/{ctx.product}"]
  if ctx.category is not None:
    fm_lines.append(f"  - wiki/category/{ctx.category}")
  # the registry never carries a stage, so no matcher ever claims it — the type's own seed is
  # the only paint it will ever have, and it has to be written here rather than by the scaffold
  if (paint := spec_doc_types.icon_color(
      spec_paths.find_settings_root(decisions_path.resolve().parent), _DECISIONS_TYPE, ctx.product)):
    fm_lines.append(f"iconize_icon: {paint[0]}")
    if paint[1]:
      fm_lines.append(f'iconize_color: "{paint[1]}"')
  fm_lines.append("---")
  fm_text = "\n".join(fm_lines) + "\n"

  # asset-level carries the slug segment in the title; product-level carries the product key
  if ctx.slug is not None:
    header = f"# {ctx.slug} — decisions\n"
  else:
    header = f"# {ctx.product} — decisions\n"
  return fm_text, header


def _self_link(decisions_path: Path, record_id: str, thesis: str, content_root: Path) -> str:
  """
  Build a path-qualified, display-carrying wikilink to a record within a registry file.

  Returns:
    `[[<path/from/content/root/decisions>#D-NNN — thesis|D-NNN]]`.
  """
  rel = decisions_path.resolve().relative_to(content_root.resolve()).with_suffix("")
  return f"[[{rel.as_posix()}#{record_id} — {thesis}|{record_id}]]"


def _parse_id(record_id: str) -> int:
  """
  Parse a `D-NNN` token into its bare integer.

  Returns:
    The integer number.

  Raises:
    ValueError: When `record_id` does not match the `D-NNN` shape.
  """
  m = re.match(r"^D-(\d{3,})$", record_id.strip())
  # guard: malformed id token
  if m is None:
    raise ValueError(f"invalid decision id: {record_id!r}")
  return int(m.group(1))


# ----------------------------------------------------------------------------------------
# Public operations.

def add(decisions_path: Path, thesis: str, body: str, *,
        origin: str = "—", today: str | None = None) -> dict:
  """
  Write a fresh decision record, or return the existing one on a dedup match.

  Lazily creates `decisions_path` (with its own frontmatter + header) on the first record written
  into it.

  Guarantees:
    - Concurrent callers never allocate the same `D-NNN` number.

  Args:
    decisions_path: The registry file's path (asset-level or product-level; need not exist yet).
    thesis: The record's thesis line.
    body: The record's full body text, verbatim — everything below the `Origin:` line, byte-
      preserved from its source (a `[!decision]` block's own content, or a `**Why.**` /
      `**Rejected.**` pair composed by a manual `add`/`supersede` CLI call). Never rewritten,
      summarized, or reduced to a subset of its own fields.
    origin: The `Origin:` line value — a qualified+display wikilink, or `—` for a manual record
      with no source document.
    today: Optional ISO date pinned into the `Date:` line; defaults to the current UTC date.

  Returns:
    `{"status": "added", "id", "file"}` on a fresh write, or `{"status": "duplicate", "id",
    "file"}` when an existing record already carries the same normalized thesis + body.

  Raises:
    TimeoutError: The registry's exclusive lock could not be acquired in time.
    ValueError: `decisions_path` needs to be lazily created and its parent directory isn't
      covered by any registered product's `spec_path`.
  """
  today_str = flip_gate._today(today)

  # Contract:
  # concurrent callers never allocate the same `D-NNN` number — the whole
  # read-count-write sequence below runs under the registry's own exclusive lock

  # read the current file (or its lazy shell) inside the lock, so the count below is never stale
  with _decisions_lock(decisions_path):
    if decisions_path.is_file():
      fm_text, existing_body = _split(decisions_path.read_text())
      # a decisions.md with no parseable frontmatter (fm_end == 0) still needs its canonical
      # shell — prepend fresh frontmatter + header rather than writing a still-headerless file
      if not fm_text:
        fm_text, header = _new_file_shell(decisions_path)
        existing_body = header + existing_body
    else:
      fm_text, existing_body = _new_file_shell(decisions_path)

    # a fresh record never lands on top of one that already says the same thing
    existing = _parse_records(existing_body)
    key = _dedup_key(thesis, body)
    dup = next(
        (r for r in existing if _dedup_key(r[_K.THESIS], r[_K.BODY]) == key), None,
    )
    # guard: an existing record already carries this exact content — write nothing
    if dup is not None:
      return {_K.STATUS: _Result.DUPLICATE, _K.ID: f"D-{dup[_K.NUMBER]:03d}",
              _K.FILE: str(decisions_path)}

    # no dedup match — allocate the next number and write the record
    number = _next_number(existing_body)
    record_text = _format_record(number, thesis, body, origin = origin, today = today_str)
    new_body = _insert_record(existing_body, record_text)
    decisions_path.write_text(fm_text + new_body)
  return {_K.STATUS: _Result.ADDED, _K.ID: f"D-{number:03d}", _K.FILE: str(decisions_path)}


def _write_status(decisions_path: Path, number: int, new_status: str) -> bool:
  """
  Rewrite one existing record's `Status:` line under the registry file's exclusive lock.

  Returns:
    True when the record was found and its `Status:` line rewritten; False when the file or the
    record does not exist.
  """
  # guard: registry file doesn't exist — nothing to update
  if not decisions_path.is_file():
    return False
  with _decisions_lock(decisions_path):
    text = decisions_path.read_text()
    fm_text, body = _split(text)
    new_body, changed = _set_status(body, number, new_status)
    # guard: no such record — nothing written
    if not changed:
      return False
    decisions_path.write_text(fm_text + new_body)
  return True


def supersede(decisions_path: Path, old_id: str, thesis: str, body: str, *,
              origin: str = "—", today: str | None = None) -> dict:
  """
  Write a fresh record and mark an older one `superseded-by` it, in the same registry file.

  Args:
    decisions_path: The registry file's path.
    old_id: The `D-NNN` token of the record being superseded — must already exist in this file.
    thesis: The new record's thesis line.
    body: The new record's full body text, verbatim (see `add`'s own `body` parameter).
    origin: The new record's `Origin:` line value.
    today: Optional ISO date pinned into the new record's `Date:` line.

  Returns:
    `{"status": "superseded", "old_id", "new_id"}` on success, or `{"status": "refused",
    "reason"}` when `old_id` does not exist in this file.

  Raises:
    ValueError: `old_id` isn't a `D-NNN` token, or (via `add`) `decisions_path` needs lazy
      creation and its parent isn't covered by any registered product.
    TimeoutError: The registry's exclusive lock could not be acquired in time.
  """
  old_number = _parse_id(old_id)
  existing = _parse_records(_split(decisions_path.read_text())[1]) if decisions_path.is_file() else []
  # guard: the record being superseded must already exist
  if not any(r[_K.NUMBER] == old_number for r in existing):
    return {_K.STATUS: _Result.REFUSED, _K.REASON: f"no such record: D-{old_number:03d}"}

  # the fresh record itself is written through `add`, which owns dedup/lock/lazy-create; the
  # supersede stamp on the old record only applies on a genuine write — a dedup hit means the
  # "new" record already existed and its supersede link was already applied by whichever call
  # created it, so re-stamping Status here would be a no-op repeat, not a correctness need
  result = add(decisions_path, thesis, body, origin = origin, today = today)
  new_id = result[_K.ID]
  if result[_K.STATUS] == _Result.ADDED:
    content_root = _resolve_context(decisions_path).content_root
    link = _self_link(decisions_path, new_id, thesis, content_root)
    _write_status(decisions_path, old_number, f"superseded-by {link}")
  return {_K.STATUS: _Result.SUPERSEDED, _K.OLD_ID: f"D-{old_number:03d}", _K.NEW_ID: new_id}


def obsolete(decisions_path: Path, record_id: str, reason: str) -> dict:
  """
  Mark an existing record `obsolete — <reason>`.

  Args:
    decisions_path: The registry file's path.
    record_id: The `D-NNN` token of the record to mark.
    reason: The human-readable reason folded into the `Status:` line.

  Returns:
    `{"status": "obsoleted", "id"}` on success, or `{"status": "refused", "reason"}` when the
    record does not exist.

  Raises:
    ValueError: `record_id` isn't a `D-NNN` token.
    TimeoutError: The registry's exclusive lock could not be acquired in time.
  """
  number = _parse_id(record_id)
  ok = _write_status(decisions_path, number, f"obsolete — {reason}")
  # guard: no such record
  if not ok:
    return {_K.STATUS: _Result.REFUSED, _K.REASON: f"no such record: D-{number:03d}"}
  return {_K.STATUS: _Result.OBSOLETED, _K.ID: f"D-{number:03d}"}


# ----------------------------------------------------------------------------------------
# `promote` — transfer `[!decision]` blocks out of a living doc's body.

_DECISION_OPEN_RE = re.compile(r"^> \[!decision\] (.+?) #spec/decision\s*$")
_CALLOUT_HEAD_RE = re.compile(r"^> \[!")
_WIKILINK_RE = re.compile(r"^\[\[([^#|\]]+)#D-(\d{3,})[^|\]]*(?:\|[^\]]*)?\]\]$")


def _find_decision_blocks(body: str) -> list[dict]:
  """
  Locate every `[!decision]` blockquote in a document body, skipping fenced code and any H1
  section whose first non-blank content line is a `#protected/...` or `#expert/...` tag.

  Guarantees:
    - Two `[!decision]` blocks with no blank line between them are never merged into one — a
      line opening a new callout always ends the block in progress.

  Args:
    body: The document's body text (post-frontmatter).

  Returns:
    A list of dicts, document order, each carrying `thesis`, `start`/`end` (line-index range,
    half-open), and `raw_lines` (the block's own lines, including the leading `> `).
  """

  # Contract:
  # a block's own lines stop at the next line that opens a new callout (`> [!...]`) — two
  # decision blocks with no blank line between them are never merged into one

  # set up the scan state before the single forward pass below
  lines = body.splitlines()
  n = len(lines)
  blocks: list[dict] = []
  in_fence = False
  skip_section = False
  i = 0
  # single forward pass: toggle fence state, refresh the current section's skip flag at every
  # H1 boundary, and collect `[!decision]` blocks only while neither guard is active
  while i < n:
    line = lines[i]
    if line.strip().startswith("```"):
      in_fence = not in_fence
      i += 1
      continue
    if not in_fence and re.match(r"^#\s", line):
      j = i + 1
      while j < n and not lines[j].strip():
        j += 1
      tag = lines[j].strip() if j < n else ""
      skip_section = tag.startswith((_K.TAG_PROTECTED, _K.TAG_EXPERT))
      i += 1
      continue
    if not in_fence and not skip_section:
      m = _DECISION_OPEN_RE.match(line)
      if m:
        # a block runs through every following `>`-prefixed line, EXCEPT one that opens a new
        # callout (`> [!...]`) — two decision blocks with no blank line between them must not
        # merge into one
        j = i + 1
        while j < n and lines[j].startswith(">") and not _CALLOUT_HEAD_RE.match(lines[j]):
          j += 1
        blocks.append({_K.THESIS: m.group(1).strip(), _K.START: i, _K.END: j,
                       _K.RAW_LINES: lines[i:j]})
        i = j
        continue
    i += 1
  return blocks


_SUPERSEDES_LINE_RE = re.compile(r"^\*\*Supersedes\.\*\*\s*(.*)$")


def _split_supersedes_and_body(raw_lines: list[str]) -> tuple[str, list[str]]:
  """
  Split a `[!decision]` block's own content, `> `-prefix stripped, into the `**Supersedes.**`
  command (if any) and the remaining body lines.

  Guarantees:
    - Every content line other than a `**Supersedes.**` line is preserved byte-for-byte (minus
      its `> ` prefix), in source order — no field-only reconstruction, no dropped continuation
      or extra prose line.

  Args:
    raw_lines: The block's own lines including the leading `[!decision]` line, each prefixed
      `> `.

  Returns:
    `(supersedes, body_lines)` — `supersedes` is the command's value, or empty string when the
    block carries none; `body_lines` is every remaining content line, verbatim.
  """

  # Contract:
  # every content line that is not itself a `**Supersedes.**` command is carried through
  # unmodified — `promote` copies a block's body verbatim, never reconstructing it from a
  # parsed subset of its own fields (spec-decisions-design.md § on how a decision enters the
  # registry file)

  # strip the `[!decision]` opening line and every remaining line's `> ` blockquote prefix
  content = [ln[2:] if ln.startswith("> ") else ln.lstrip(">") for ln in raw_lines[1:]]
  supersedes = ""
  body_lines = []
  for ln in content:
    m = _SUPERSEDES_LINE_RE.match(ln)
    if m:
      # the command line itself is excluded from the body regardless of position or repeats
      if not supersedes:
        supersedes = m.group(1).strip()
      continue
    body_lines.append(ln)
  return supersedes, body_lines


def _doc_title_line(body: str) -> str:
  """
  Return a living doc's own `<Title> — <role>` title text (the H1 line's content, sans `# `).

  Returns:
    The title text, or empty string when the body carries no leading H1.
  """
  for line in body.splitlines():
    m = re.match(r"^#\s+(.+)$", line)
    if m:
      return m.group(1).strip()
    # guard: first non-blank, non-heading line — no title present
    if line.strip():
      break
  return ""


def _resolve_supersedes_link(text: str, content_root: Path) -> tuple[Path | None, int | None]:
  """
  Parse a `**Supersedes.**` field's wikilink into the target registry file + record number.

  Returns:
    `(target_path, number)`, or `(None, None)` when `text` doesn't match the expected wikilink
    shape.
  """
  m = _WIKILINK_RE.match(text.strip())
  # guard: not a recognizable `[[<path>#D-NNN ...]]` link
  if m is None:
    return None, None
  return (content_root / f"{m.group(1)}.md").resolve(), int(m.group(2))


def promote(doc_path: Path, *, today: str | None = None) -> dict:
  """
  Transfer every `[!decision]` block in a living doc's body into its sibling `decisions.md`.

  Refuses (no mutation) when `doc_path` doesn't exist, when the doc's `spec_role` is not one of
  `design` / `bug` / `tech` / `architecture`, or — for an asset-level doc — when the owning
  asset's status folder-note currently carries `spec_cancelled` / `spec_halted` / `spec_released`
  as true. Each transferred block is replaced in the doc with a reference wikilink to its new (or
  dedup-matched existing) record; a block whose normalized thesis + full body already matches an
  existing record contributes no new record — only its own reference-link replacement, making a
  repeat approve idempotent.

  Guarantees:
    - Every outcome dict — refused, noop, or promoted — carries both `records` and
      `touched_paths`, each `[]` when not applicable.

  Args:
    doc_path: The living doc's path.
    today: Optional ISO date pinned into any freshly written record's `Date:` line.

  Returns:
    `{"status": "promoted", "touched_paths", "records"}` on a transfer, `{"status": "noop",
    "touched_paths": [], "records": []}` when the doc carries no `[!decision]` blocks, or
    `{"status": "refused", "reason", "touched_paths": [], "records": []}` when the doc is missing
    or the role / asset-flag guard rejects the call.

  Raises:
    ValueError: The doc's own directory isn't covered by any registered product's `spec_path`.
    TimeoutError: A registry's exclusive lock could not be acquired in time.
  """

  # Contract:
  # every returned dict — refused, noop, or promoted — carries both `records` and
  # `touched_paths`, so a caller (e.g. lazy-spec.set-stage) can read `result["touched_paths"]`
  # unconditionally without branching on `status` first

  # guard: doc must exist
  if not doc_path.is_file():
    return {_K.STATUS: _Result.REFUSED, _K.REASON: f"no such doc: {doc_path}",
            _K.TOUCHED_PATHS: [], _K.RECORDS: []}

  # only a living doc (the closed `_LIVING_ROLES` set) is a legal source for a promote call
  text = doc_path.read_text()
  fm_values, fm_end = flip_gate._parse_frontmatter(text)
  role = fm_values.get(_K.SPEC_ROLE, "")
  # guard: only living docs are a source for promoted decisions — plans decompose already-accepted
  # decisions and reports carry only candidates (spec-decisions-design.md § on candidates sourced
  # from reports)
  if role not in _LIVING_ROLES:
    return {_K.STATUS: _Result.REFUSED,
            _K.REASON: f"spec_role '{role}' is not a living doc ({'/'.join(sorted(_LIVING_ROLES))})",
            _K.TOUCHED_PATHS: [], _K.RECORDS: []}

  # a product-level doc has no owning asset and so no terminal/halt flags to check at all; an
  # asset-level doc's owning asset gates every promote call regardless of who invoked it (auto on
  # approve, or a manual /lazy-spec.decide promote)
  ctx = _resolve_context(doc_path)
  if ctx.asset_dir is not None:
    status_note = ctx.asset_dir / f"{ctx.slug}.md"
    if status_note.is_file():
      note_fm, _ = flip_gate._parse_frontmatter(status_note.read_text())
      for flag in _HALT_FLAGS:
        # guard: the owning asset carries a terminal/halt flag — refuse the whole call
        if flip_gate._is_true(note_fm, flag):
          return {_K.STATUS: _Result.REFUSED, _K.REASON: f"asset flag {flag} is true",
                  _K.TOUCHED_PATHS: [], _K.RECORDS: []}

  # find every transferable block before touching anything on disk
  body = text[fm_end:]
  blocks = _find_decision_blocks(body)
  # guard: nothing to promote — no mutation, no touched paths
  if not blocks:
    return {_K.STATUS: _Result.NOOP, _K.TOUCHED_PATHS: [], _K.RECORDS: []}

  # the doc's own title line becomes every new record's Origin display text
  decisions_path = doc_path.parent / DECISIONS_BASENAME
  origin_link = (f"[[{doc_path.resolve().relative_to(ctx.content_root).with_suffix('')}"
                 f"|{_doc_title_line(body) or doc_path.stem}]]")
  touched: set[str] = set()
  records: list[dict] = []
  lines = body.splitlines()

  # process blocks in reverse document order so earlier line-range replacements never shift the
  # indices of blocks still to be processed
  for blk in sorted(blocks, key = lambda b: b[_K.START], reverse = True):
    supersedes, block_body_lines = _split_supersedes_and_body(blk[_K.RAW_LINES])
    thesis = blk[_K.THESIS]
    # trim only the leading/trailing blank padding a source block may carry — every content
    # line in between is preserved exactly, verbatim, minus its `> ` prefix
    while block_body_lines and not block_body_lines[0].strip():
      block_body_lines.pop(0)
    while block_body_lines and not block_body_lines[-1].strip():
      block_body_lines.pop()

    # the record itself is written through `add`, which owns dedup/lock/lazy-create
    result = add(decisions_path, thesis, "\n".join(block_body_lines),
                 origin = origin_link, today = today)
    record_id = result[_K.ID]
    touched.add(result[_K.FILE])

    # a new record contributes to the result AND applies its own Supersedes command exactly
    # once, on the write that created it — a repeat/dedup hit must not re-stamp Status again
    if result[_K.STATUS] == _Result.ADDED:
      records.append({_K.ID: record_id, _K.THESIS: thesis})
      if supersedes:
        target_path, old_number = _resolve_supersedes_link(supersedes, ctx.content_root)
        if target_path is not None and old_number is not None:
          new_link = _self_link(decisions_path, record_id, thesis, ctx.content_root)
          if _write_status(target_path, old_number, f"superseded-by {new_link}"):
            touched.add(str(target_path))

    # the block's own lines are replaced in-place with a single reference-link line
    reference_line = _self_link(decisions_path, record_id, thesis, ctx.content_root)
    lines = [*lines[:blk[_K.START]], reference_line, *lines[blk[_K.END]:]]

  # write the doc back once, after every block has been replaced
  new_body = "\n".join(lines)
  if body.endswith("\n") and not new_body.endswith("\n"):
    new_body += "\n"
  doc_path.write_text(text[:fm_end] + new_body)
  touched.add(str(doc_path))
  return {_K.STATUS: _Result.PROMOTED, _K.TOUCHED_PATHS: sorted(touched), _K.RECORDS: records}


# ----------------------------------------------------------------------------------------
# CLI

def main(argv: list[str]) -> int:
  """
  Run one `decide` operation from the command line, printing the result as JSON.

  Args:
    argv: Subcommand argv tail (the operation name plus its own arguments).

  Returns:
    Exit code: `0` on success (including a dedup `duplicate` outcome), `1` on a refusal.

  Raises:
    SystemExit: With code `2`, raised by `argparse` itself on missing/invalid arguments.
    TimeoutError: A registry's exclusive lock could not be acquired in time — not caught here,
      since it names an operational failure rather than a business refusal `ValueError` covers.
  """
  parser = argparse.ArgumentParser(prog = _K.PROG)
  sub = parser.add_subparsers(dest = _K.OP, required = True)

  # `add <decisions_path> <thesis> --why --rejected [--origin] [--today]`
  p_add = sub.add_parser(_K.OP_ADD)
  p_add.add_argument(_K.ARG_DECISIONS_PATH, type = Path)
  p_add.add_argument(_K.ARG_THESIS)
  p_add.add_argument(_K.FLAG_WHY, required = True)
  p_add.add_argument(_K.FLAG_REJECTED, required = True)
  p_add.add_argument(_K.FLAG_ORIGIN, default = "—")
  p_add.add_argument(_K.FLAG_TODAY, default = None)

  # `supersede <decisions_path> <old_id> <thesis> --why --rejected [--origin] [--today]`
  p_sup = sub.add_parser(_K.OP_SUPERSEDE)
  p_sup.add_argument(_K.ARG_DECISIONS_PATH, type = Path)
  p_sup.add_argument(_K.ARG_OLD_ID)
  p_sup.add_argument(_K.ARG_THESIS)
  p_sup.add_argument(_K.FLAG_WHY, required = True)
  p_sup.add_argument(_K.FLAG_REJECTED, required = True)
  p_sup.add_argument(_K.FLAG_ORIGIN, default = "—")
  p_sup.add_argument(_K.FLAG_TODAY, default = None)

  # `obsolete <decisions_path> <record_id> <reason>`
  p_obs = sub.add_parser(_K.OP_OBSOLETE)
  p_obs.add_argument(_K.ARG_DECISIONS_PATH, type = Path)
  p_obs.add_argument(_K.ARG_RECORD_ID)
  p_obs.add_argument(_K.ARG_REASON)

  # `promote <doc_path> [--today]`
  p_pro = sub.add_parser(_K.OP_PROMOTE)
  p_pro.add_argument(_K.ARG_DOC_PATH, type = Path)
  p_pro.add_argument(_K.FLAG_TODAY, default = None)

  # parse first — every branch below reads only its own operation's arguments
  args = parser.parse_args(argv)

  # dispatch to the selected operation's own primitive; a `ValueError` a caller can't have
  # anticipated (an unresolvable product/asset context) surfaces as an ordinary refusal, not a
  # traceback — the CLI's whole contract is "JSON on stdout, exit code names the outcome"
  try:
    if args.op == _K.OP_ADD:
      result = add(args.decisions_path.resolve(), args.thesis,
                   f"**Why.** {args.why}\n**Rejected.** {args.rejected}",
                   origin = args.origin, today = args.today)
    elif args.op == _K.OP_SUPERSEDE:
      result = supersede(args.decisions_path.resolve(), args.old_id, args.thesis,
                         f"**Why.** {args.why}\n**Rejected.** {args.rejected}",
                         origin = args.origin, today = args.today)
    elif args.op == _K.OP_OBSOLETE:
      result = obsolete(args.decisions_path.resolve(), args.record_id, args.reason)
    else:
      result = promote(args.doc_path.resolve(), today = args.today)
  except ValueError as error:
    result = {_K.STATUS: _Result.REFUSED, _K.REASON: str(error)}

  # print the result the same way every other lazycortex-specs verb does
  print(json.dumps(result))
  return 0 if result[_K.STATUS] != _Result.REFUSED else 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
