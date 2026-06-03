"""`# History` section maintenance.

The historian owns the History section exclusively (spec § historian
subsystem). One historian job is dispatched per writer-commit (main /
section) AT WRITER-COMMIT TIME, runs asynchronously through the pump,
and is picked up whenever it completes — no state-machine gate, no
git-log introspection. Operator-commits and mechanical bot-commits do
not trigger historian dispatch.

Entry shape (spec § historian subsystem):

```
### YYYY-MM-DD HH:MM
<one declarative sentence — what is now in the document, substance only>
```

No actor and no role label on the heading. The historian's persona
forbids actor / process narration in the sentence itself.

Each entry's timestamp is the writer-commit time it narrates (captured
at dispatch). Entries are inserted **chronologically** under the H1 +
ownership-tag header — newest on top, oldest at the bottom — by
comparing timestamps against existing entries. Out-of-order pump
completions (when several historian jobs are in flight and finish in
a different order than they were dispatched) still produce a
chronologically-ordered file.

The History section survives finalize unchanged.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# pylint: disable=import-error,deprecated-module

import re
from pathlib import Path

import frontmatter as _fm
import parser as _parser

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


HISTORIAN_TAG = "#expert/lazy-review-historian"
HISTORY_TITLE = "# History"


_H1_RE = re.compile(r"^# (.+?)\s*$", re.MULTILINE)


# ----------------------------------------------------------- helpers


def _split_frontmatter(text: str) -> tuple[str, str]:
  _meta, body = _fm.parse(text)
  fm_text = text[: len(text) - len(body)]
  return fm_text, body


def _find_history_span(body: str) -> tuple[int, int] | None:
  matches = list(_H1_RE.finditer(body))
  for i, m in enumerate(matches):
    start = m.start()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
    line_end = body.find("\n", m.end())
    content_start = line_end + 1 if line_end != -1 else end
    # Tag-first: the historian section is identified by its ownership
    # tag, not its title — a content H1 titled `History` is not it.
    if _parser.is_historian_section(body[content_start:end]):
      return (start, end)
  return None


# -------------------------------------------------- ensure_history_section


def append_empty_marker(text: str) -> str:
  """
  Append a single empty line at the end of the `# History` section.

  Used by the noop-historian path so the commit physically touches the
  file. The section is created if missing. Subsequent calls keep
  adding one empty line per call — that's fine; the loop closes after
  one such commit, so the section grows by at most one line per stuck
  operator turn.

  Args:
    text: Full document text including frontmatter.

  Returns:
    Updated document text with one extra blank line appended to the history section.
  """
  text = ensure_history_section(text)
  fm_text, body = _split_frontmatter(text)
  span = _find_history_span(body)
  # waiver: type-narrowing invariant guaranteed by construction here, not input validation
  assert span is not None
  start, end = span
  section = body[start:end]
  new_section = section + "\n"
  new_body = body[:start] + new_section + body[end:]
  return fm_text + new_body


def ensure_history_section(text: str) -> str:
  """
  Add an empty `# History` section at the end of body if absent.

  The new section carries the historian's ownership tag on its first
  content line. Already-present sections are left untouched.

  Args:
    text: Full document text including frontmatter.

  Returns:
    Updated document text, guaranteed to contain a `# History` section.
  """
  fm_text, body = _split_frontmatter(text)
  if _find_history_span(body) is not None:
    return text
  suffix = body
  if suffix and not suffix.endswith("\n"):
    suffix += "\n"
  if suffix and not suffix.endswith("\n\n"):
    suffix += "\n"
  new_body = suffix + f"{HISTORY_TITLE}\n{HISTORIAN_TAG}\n"
  return fm_text + new_body


# -------------------------------------------------------- insert_entry


_ENTRY_TS_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")


def insert_entry(
    text: str,
    *,
    timestamp_utc: str,
    sentence: str,
) -> str:
  """
  Insert one entry under `# History` in chronological order —
  newest entries on top, oldest at the bottom — using `timestamp_utc`
  as the sort key against existing `### YYYY-MM-DD HH:MM` headings.
  Creates the section if missing.

  The heading carries only the UTC timestamp; no actor / role label.
  The persona forbids actor / process narration in the sentence
  itself (spec § historian subsystem — Forbidden vocabulary).

  Out-of-order pump completions are handled correctly: the new entry
  always lands above existing entries with strictly older timestamps
  and below existing entries with newer-or-equal timestamps. Equal
  timestamps keep the existing entry above the new one (stable).

  Args:
    text: Full document text including frontmatter.
    timestamp_utc: UTC timestamp string in `YYYY-MM-DD HH:MM` format used as the sort key.
    sentence: One declarative sentence describing what is now in the document.

  Returns:
    Updated document text with the new entry inserted at the correct chronological position.
  """
  text = ensure_history_section(text)
  fm_text, body = _split_frontmatter(text)
  span = _find_history_span(body)
  # waiver: type-narrowing invariant guaranteed by construction here, not input validation
  assert span is not None  # ensure_history_section just created it
  start, end = span
  section = body[start:end]
  lines = section.splitlines(keepends=True)
  # Capture H1 + ownership-tag header lines exactly as written.
  head_lines: list[str] = []
  i = 0
  if i < len(lines) and lines[i].startswith("# "):
    head_lines.append(lines[i])
    i += 1
  if i < len(lines) and lines[i].strip() == HISTORIAN_TAG:
    head_lines.append(lines[i])
    i += 1
# Skip leading blank line(s) between header and existing entries —
# we'll re-emit separators ourselves to keep layout stable.
  while i < len(lines) and lines[i].strip() == "":
    i += 1
# Parse remaining lines into entries: each entry is one
# `### YYYY-MM-DD HH:MM` heading + its body lines (until next
# heading or EOF). Pre-heading orphans (shouldn't appear after
# `repair` runs, but tolerated) are dropped silently.
  entries: list[tuple[str, list[str]]] = []
  cur_ts: str | None = None
  cur_block: list[str] = []
  for line in lines[i:]:
    m = _ENTRY_TS_RE.match(line)
    if m is not None:
      if cur_ts is not None:
        entries.append((cur_ts, cur_block))
      cur_ts = m.group(1)
      cur_block = [line]
    elif cur_ts is not None:
      cur_block.append(line)
  # else: orphan content before any heading — drop
  if cur_ts is not None:
    entries.append((cur_ts, cur_block))
  new_block = [f"### {timestamp_utc}\n", f"{sentence}\n"]
  # Find slot: first existing entry strictly older than ours → insert
  # before it. Equal or newer → walk past. Default: append at end
  # (we are older than all existing).
  insert_idx = len(entries)
  for k, (ts, _block) in enumerate(entries):
    if ts < timestamp_utc:
      insert_idx = k
      break
  entries.insert(insert_idx, (timestamp_utc, new_block))
  # Re-render: header + blank + entries separated by single blank.
  parts: list[str] = ["".join(head_lines), "\n"]
  for k, (_ts, block) in enumerate(entries):
    block_text = "".join(block).rstrip("\n") + "\n"
    parts.append(block_text)
    if k < len(entries) - 1:
      parts.append("\n")
  new_section = "".join(parts)
  new_body = body[:start] + new_section + body[end:]
  return fm_text + new_body


# Legacy alias — callers that haven't migrated to `insert_entry` yet.
# `append_entry` is now a pure synonym (the function's prepend
# semantics are replaced by chronological ordering, which subsumes the
# old "newest first" behaviour for the common monotonic-time case).
append_entry = insert_entry


# ------------------------------------------------------- splice_history_body


def splice_history_body(text: str, repaired_body: str) -> str:
  """
  Replace the body of the `# History` section with `repaired_body`.

  Spec § historian subsystem Repair mode: when the operator damaged
  `# History` by deleting `### ts` headings, the historian returns a
  best-effort reconstruction of the entries in
  `repaired_history_section`. The dispatcher splices that body in
  (replacing whatever entries currently live under `# History`) BEFORE
  prepending the new entry the same response carries.

  Preserves the H1 heading and the historian's ownership tag; replaces
  everything after them. Creates the section if absent. `repaired_body`
  is the entries-only payload (no heading, no tag).

  Args:
    text: Full document text including frontmatter.
    repaired_body: Entries-only payload to splice in, without the section heading or ownership tag.

  Returns:
    Updated document text with the history section body replaced by `repaired_body`.
  """
  text = ensure_history_section(text)
  fm_text, body = _split_frontmatter(text)
  span = _find_history_span(body)
  # waiver: type-narrowing invariant guaranteed by construction here, not input validation
  assert span is not None
  start, end = span
  section = body[start:end]
  lines = section.splitlines(keepends=True)
  head: list[str] = []
  i = 0
  if i < len(lines) and lines[i].startswith("# "):
    head.append(lines[i])
    i += 1
  if i < len(lines) and lines[i].strip() == HISTORIAN_TAG:
    head.append(lines[i])
    i += 1
  repaired = repaired_body.strip("\n")
  new_section = "".join(head)
  if repaired:
    if new_section and not new_section.endswith("\n"):
      new_section += "\n"
    new_section += "\n" + repaired + "\n"
  suffix = body[end:]
  new_body = body[:start] + new_section + suffix
  return fm_text + new_body


# ----------------------------------------------------------- repair


_ENTRY_HEADING_RE = re.compile(
    r"^### \d{4}-\d{2}-\d{2} \d{2}:\d{2}\s*$",
    re.MULTILINE,
)


def repair(text: str) -> str:
  """
  Best-effort repair of operator damage to `# History`.

  Detects orphan content paragraphs (text not directly preceded by a
  canonical `### YYYY-MM-DD HH:MM` heading) and prepends a
  placeholder `### 1970-01-01 00:00` heading so the chain stays
  parseable. Idempotent.

  Args:
    text: Full document text including frontmatter.

  Returns:
    Updated document text with orphan paragraphs given placeholder headings,
    or the original text unchanged if no `# History` section is present.
  """
  fm_text, body = _split_frontmatter(text)
  span = _find_history_span(body)
  if span is None:
    return text
  start, end = span
  section = body[start:end]
  # Split section into preamble (heading + ownership tag + blank) and entries.
  lines = section.splitlines(keepends=True)
  out_lines: list[str] = []
  i = 0
  # Keep the H1 line.
  if i < len(lines) and lines[i].startswith("# "):
    out_lines.append(lines[i])
    i += 1
# Keep the historian's ownership tag line if present.
  if i < len(lines) and lines[i].strip() == HISTORIAN_TAG:
    out_lines.append(lines[i])
    i += 1
# Keep leading blank lines.
  while i < len(lines) and lines[i].strip() == "":
    out_lines.append(lines[i])
    i += 1
# Walk entries; orphan paragraph = content before any heading we've seen.
  current_block: list[str] = []
  has_seen_heading = False
  for line in lines[i:]:
    if _ENTRY_HEADING_RE.match(line):
      current_block.append(line)
      has_seen_heading = True
    elif line.strip() == "":
      current_block.append(line)
    else:
      if not has_seen_heading:
        # waiver: regex / format fragment, not a domain key
        current_block.append("### 1970-01-01 00:00\n")
        has_seen_heading = True
      current_block.append(line)
  out_lines.extend(current_block)
  new_section = "".join(out_lines)
  new_body = body[:start] + new_section + body[end:]
  return fm_text + new_body


# -------------------------------------------- is_human_commit_handled


_HISTORY_TRAILER_RE = re.compile(
    r"^Doc-Review-Phase:\s+history:(append|noop)\b",
    re.MULTILINE,
)


# waiver: `path` kept for caller signature symmetry; this check works off git history, not the file
def is_human_commit_handled(repo: Path, path: Path, human_sha: str) -> bool:  # pylint: disable=unused-argument
  """
  Return whether some commit after `human_sha` already carries a historian trailer.

  A `Doc-Review-Phase: history:*` trailer means the historian has already
  either appended an entry for that human commit or recorded a noop. Used
  to short-circuit re-dispatch.

  The noop commit is intentionally empty (`--allow-empty`) so it does not
  appear in per-file history; this check therefore scans the repo-wide log
  between HEAD and the named human sha and is not restricted to commits
  touching `path`.

  Args:
    repo: Path to the git repository root.
    path: Path to the reviewed file (kept for caller signature symmetry; not used in the check).
    human_sha: SHA of the human commit to check coverage for.

  Returns:
    True if a historian trailer for `human_sha` already exists in a later commit, False otherwise.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess
  proc = subprocess.run(
      ["git", "-C", str(repo), "log", f"{human_sha}..HEAD",
       "--format=%B%x1e"],
      check=False, capture_output=True, text=True,
  )
  if proc.returncode != 0:
    return False
  return any(_HISTORY_TRAILER_RE.search(chunk) for chunk in proc.stdout.split("\x1e"))
