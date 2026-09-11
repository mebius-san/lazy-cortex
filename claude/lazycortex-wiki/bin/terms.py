"""
Deterministic application of one settled terms decision to one document.

The terms audit reports a divergence between the word a document uses and the term the scope's
dictionary carries, and reports both sides so the operator picks the winner; nothing here judges
that. `apply_term` performs the substitution the operator already decided on: it rewrites free
prose occurrences of one term with another in a single document, leaves every region that is not
prose exactly as it stands, and refuses outright on a document the wiki may not edit.

Cross-plugin Python import is forbidden (per the inter-plugin boundary contract), so all
primitives used here are imported from within this plugin's own `bin/`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import re
from pathlib import Path

import markers as _markers
import mirror as _mirror
import scope as _scope

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Result `status` values.
STATUS_APPLIED = "applied"
STATUS_NOOP = "noop"
STATUS_REFUSED = "refused"

# Result dict keys.
_K_STATUS = "status"
_K_FILE = "file"
_K_REPLACEMENTS = "replacements"
_K_REASON = "reason"

_ENCODING = "utf-8"

# Regions of one prose line that are not prose: an inline code span, a markdown link's target,
# and a wikilink's target. Everything outside these on a non-fenced line is rewritable.
_PROTECTED_SPAN_RE = re.compile(r"`[^`]*`|\]\([^)]*\)|\[\[[^\]]*\]\]")

# A line opening or closing a fenced block, in either fence character.
_FENCE_RE = re.compile(r"^\s{0,3}(?:```|~~~)")

# A line opening an H1 section — the boundary the protected See-also block ends at.
_H1_RE = re.compile(r"^# ")

# Frontmatter key that marks a document as belonging to an open review round, and the values
# that read as set. An edit from outside the review job counts against that round.
_REVIEW_ACTIVE_KEY = "review_active"
_REVIEW_ACTIVE_RE = re.compile(
  rf"^{_REVIEW_ACTIVE_KEY}\s*:\s*[\"']?(?:true|yes)[\"']?\s*$", re.IGNORECASE | re.MULTILINE,
)

# Refusal reasons, one per state the pass declines to act in.
_REASON_MISSING = "document does not exist"
_REASON_EMPTY_TERM = "both the replaced term and its replacement must be non-empty"
_REASON_REVIEW = (
  f"document carries `{_REVIEW_ACTIVE_KEY}: true` — it belongs to the open review round, and an "
  "edit from outside that round counts against it"
)
_REASON_MIRROR = (
  "document lies under a scope's mirror tree, which is regenerated from its source on every sync "
  "— the edit would be erased and the drift detection broken"
)
_REASON_GROWING = (
  "the replacement contains the replaced term, so the substitution could never be idempotent"
)


def _refusal(path_label: str, reason: str) -> dict:
  """
  Build the result of a pass that declined to touch the document.

  Args:
    path_label: The document's repo-relative path, or its raw path when it lies outside the repo.
    reason: The one-line reason the pass refused.

  Returns:
    A refusal result carrying no replacement count.
  """
  return { _K_STATUS: STATUS_REFUSED, _K_FILE: path_label, _K_REASON: reason }


def _rel_label(repo: Path, path: Path) -> str:
  """
  Render one document's path the way every result reports it.

  Args:
    repo: Repository root.
    path: The document's path, absolute or repo-relative.

  Returns:
    The repo-relative POSIX path, or the path as given when it lies outside the repository.
  """
  candidate = path if path.is_absolute() else repo / path
  try:
    return candidate.resolve().relative_to(repo.resolve()).as_posix()
  except ValueError:
    return path.as_posix()


def _mirror_paths(repo: Path) -> list[str]:
  """
  Collect the mirror directory of every configured scope that declares one.

  Args:
    repo: Repository root.

  Returns:
    Repo-relative POSIX directory paths, one per scope carrying a usable `mirror` block.
  """
  resolver = _scope.ScopeResolver(repo = repo)
  out: list[str] = []
  for scope_id, cfg in resolver.load_scopes().items():
    sync = _mirror.MirrorSync(repo = repo, scope_id = scope_id, cfg = cfg)
    # guard: the scope mirrors nothing — it has no regenerated tree to protect
    if not sync.configured:
      continue
    out.append(sync.mirror_path)
  return out


def _under_mirror(rel_posix: str, mirror_paths: list[str]) -> bool:
  """
  Test whether one repo-relative path lies inside a mirror tree.

  Args:
    rel_posix: The document's repo-relative POSIX path.
    mirror_paths: Repo-relative mirror directories, from `_mirror_paths`.

  Returns:
    `True` when the path sits under one of the directories; a sibling merely sharing a name
    prefix (`wiki/mirrored-notes` against `wiki/mirror`) is never a match.
  """
  return any(rel_posix.startswith(f"{base}/") for base in mirror_paths if base)


def _split_frontmatter(text: str) -> tuple[str, str]:
  """
  Split a document into its frontmatter block and the body that follows it.

  Args:
    text: Full document text.

  Returns:
    `(head, body)` — `head` is the frontmatter block including its closing fence and newline, or
    `""` when the document carries none; `body` is everything after it.
  """
  # guard: no opening fence — the whole document is body
  if not text.startswith("---\n"):
    return "", text
  end = text.find("\n---\n", len("---\n") - 1)
  # guard: no closing fence — malformed frontmatter is treated as body, never rewritten blindly
  if end < 0:
    return "", text
  cut = end + len("\n---\n")
  return text[:cut], text[cut:]


def _replace_in_line(line: str, pattern: re.Pattern, replacement: str) -> tuple[str, int]:
  """
  Rewrite one prose line outside its protected spans.

  Args:
    line: A single body line, without its line ending.
    pattern: The compiled whole-word matcher for the replaced term.
    replacement: The term replacing it.

  Returns:
    `(rewritten_line, count)` — the line with every free occurrence replaced, and how many were.
  """
  out: list[str] = []
  last = 0
  count = 0
  # rewrite each gap between protected spans, and carry every span through verbatim
  for span in _PROTECTED_SPAN_RE.finditer(line):
    chunk, hits = pattern.subn(replacement, line[last:span.start()])
    out.append(chunk)
    out.append(span.group(0))
    count += hits
    last = span.end()

  # the tail past the last protected span is prose like any other gap
  chunk, hits = pattern.subn(replacement, line[last:])
  out.append(chunk)
  return "".join(out), count + hits


def _rewrite_body(body: str, pattern: re.Pattern, replacement: str) -> tuple[str, int]:
  """
  Rewrite every free prose occurrence in a document body.

  Fenced blocks and the protected See-also section are carried through untouched, as is every
  protected span inside an otherwise rewritable line.

  Args:
    body: The document's body text, frontmatter already removed.
    pattern: The compiled whole-word matcher for the replaced term.
    replacement: The term replacing it.

  Returns:
    `(rewritten_body, count)` — the body with every free occurrence replaced, and how many were.
  """
  lines = body.split("\n")
  out: list[str] = []
  count = 0
  in_fence = False
  in_see_also = False
  for line in lines:
    # a fence line toggles the block state and is itself never prose
    if _FENCE_RE.match(line):
      in_fence = not in_fence
      out.append(line)
      continue
    # an H1 opens the protected See-also block or closes it again
    if not in_fence and _H1_RE.match(line):
      in_see_also = line.strip() == _markers.Markers.SEE_ALSO_HEADING
      out.append(line)
      continue
    # guard: inside a fenced block or the section another plugin's contract protects
    if in_fence or in_see_also:
      out.append(line)
      continue
    rewritten, hits = _replace_in_line(line, pattern, replacement)
    out.append(rewritten)
    count += hits
  return "\n".join(out), count


def apply_term(repo: Path | str, path: Path | str, old_term: str, new_term: str) -> dict:
  """
  Apply one settled terms decision to one document: replace `old_term` with `new_term` in prose.

  Decides nothing — which side of a reported divergence wins is the operator's call, supplied
  here as the direction. Whole-word, case-sensitive, and idempotent: a second pass over an
  already-applied decision finds no free occurrence and rewrites nothing.

  Guarantees:
    - The frontmatter block, every fenced code block, every inline code span, every link target,
      and the protected See-also section are carried through byte-for-byte.
    - A document under an open review round or inside a scope's mirror tree is refused, and the
      file is not written at all.

  Args:
    repo: Repository root, used to resolve the scope configuration and to report the path.
    path: The document to rewrite, absolute or repo-relative.
    old_term: The term being replaced, as it appears in the document.
    new_term: The term replacing it.

  Returns:
    `{status, file, replacements}` on `applied` / `noop`, or `{status, file, reason}` on
    `refused`.
  """

  # Contract:
  # The frontmatter block, every fenced code block, every inline code span, every link target,
  # and the protected See-also section are carried through byte-for-byte.

  # Contract:
  # A document carrying `review_active: true`, or lying inside a scope's mirror tree, is refused
  # and never written.

  repo = Path(repo).resolve()
  path = Path(path)
  label = _rel_label(repo, path)
  target = path if path.is_absolute() else repo / path

  # guard: a blank term on either side names nothing to match or nothing to write
  if not old_term.strip() or not new_term.strip():
    return _refusal(label, _REASON_EMPTY_TERM)
  # guard: the document is gone — the operator's decision names a file that is not there
  if not target.is_file():
    return _refusal(label, _REASON_MISSING)

  # the whole-word matcher every later step shares, plus the two refusals it makes decidable
  pattern = re.compile(rf"(?<!\w){re.escape(old_term)}(?!\w)")
  # guard: replacing a term with a phrase containing it would re-match on the next pass
  if pattern.search(new_term):
    return _refusal(label, _REASON_GROWING)
  # guard: a mirrored document is regenerated from its source — the edit would not survive
  if _under_mirror(label, _mirror_paths(repo)):
    return _refusal(label, _REASON_MIRROR)

  # the frontmatter is split off before anything reads it — it is both the review flag's home
  # and a region no replacement may reach
  text = target.read_text(encoding = _ENCODING)
  head, body = _split_frontmatter(text)
  # guard: the review loop owns the document until its round closes
  if _REVIEW_ACTIVE_RE.search(head):
    return _refusal(label, _REASON_REVIEW)

  # the substitution itself, written back only when it actually found something
  rewritten, count = _rewrite_body(body, pattern, new_term)
  # guard: nothing to replace outside the protected regions — leave the file untouched
  if count == 0:
    return { _K_STATUS: STATUS_NOOP, _K_FILE: label, _K_REPLACEMENTS: 0 }
  target.write_text(head + rewritten, encoding = _ENCODING)
  return { _K_STATUS: STATUS_APPLIED, _K_FILE: label, _K_REPLACEMENTS: count }
