"""
Integrity audit for lazycortex-wiki scopes.

`Doctor` runs a fixed suite of checks against one or all configured scopes,
returning structured findings (severity, message, node path, fixable flag).
When `apply=True` is requested, fixable checks apply their auto-repair
(index rebuild, broken See-also line removal, stale gloss refresh) and
re-emit each finding with an `applied` note.

Cross-plugin Python import is forbidden (per the inter-plugin boundary contract),
so all primitives used here are imported from within this plugin's own `bin/`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import re
from pathlib import Path

import index as _index
import nodes as _nodes
import repos as _repos
import scope as _scope

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ────────────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────────────

# Wiki tag prefix shared with nodes/index modules.
_WIKI_TAG_PREFIX = "wiki/"

# Config keys for scope entries.
_CFG_TAG_AXES     = "tag_axes"
_CFG_TOPICS_INDEX = "topics_index"
_CFG_PATHS        = "paths"
_CFG_EXCLUDE      = "exclude_paths"

# Default topics-index path when missing from config.
_DEFAULT_TOPICS_INDEX = "wiki/topics.md"

# File encoding used throughout.
_ENCODING = "utf-8"

# Regex to extract a markdown link target from a list-item line.
# Matches `- [text](target) — gloss` or `- [text](target)`.
_MD_LINK_RE = re.compile(r"^\s*-\s+\[([^\]]*)\]\(([^)]+)\)")

# Near-duplicate branch heuristic: Levenshtein threshold and prefix length.
_DUP_EDIT_DIST_THRESHOLD = 3
_DUP_PREFIX_MIN_LEN      = 4

# Severity constants.
SEV_FAIL = "FAIL"
SEV_WARN = "WARN"
SEV_INFO = "INFO"

# Markdown extension sentinel.
_MD_EXT = ".md"

# Block-comment wiki marker literals (mirrors nodes.py private constants).
_WIKI_OPEN_BLOCK_LINE  = "/* <wiki>"
_WIKI_CLOSE_BLOCK_LINE = "</wiki> */"
_WIKI_OPEN_TAG_STR     = "<wiki>"
_WIKI_CLOSE_TAG_STR    = "</wiki>"

# Finding dict key constants (used when attaching apply-state to a finding).
_FK_FIXABLE   = "fixable"
_FK_CHECK     = "check"
_FK_APPLIED   = "applied"
_FK_NODE      = "node"
_FK_TARGET    = "_target"
_FK_NEW_GLOSS = "_new_gloss"
_FK_NODE_OBJ  = "_node_obj"

# Message string constants for broken-wiki-block findings.
_MSG_UNREADABLE       = "could not read file to check <wiki> block"
_MSG_OPEN_NO_CLOSE    = "<wiki> open marker found but </wiki> close marker missing"
_MSG_CLOSE_NO_OPEN    = "</wiki> close marker found but <wiki> open marker missing"

# Message string constant for missing-summary.
_MSG_NO_SUMMARY       = "node has no summary (dispatch curator to classify)"


# ────────────────────────────────────────────────────────────────────────────
# Finding dataclass (plain dict for simplicity / zero-dependency)
# ────────────────────────────────────────────────────────────────────────────

def _finding(
  check: str,
  severity: str,
  message: str,
  node: str = "-",
  *,
  fixable: bool = False,
  applied: bool = False,
) -> dict:
  """
  Return a structured finding dict.

  Args:
    check: Check identifier string (e.g. `orphan-topic`).
    severity: `FAIL`, `WARN`, or `INFO`.
    message: Human-readable description of the defect.
    node: Repo-relative path of the affected node, or `"-"` for scope-level findings.
    fixable: True when `--apply` can auto-repair this finding.
    applied: True when the fix was already applied in this run.

  Returns:
    Dict with keys `check`, `severity`, `node`, `message`, `fixable`, `applied`.
  """
  return {
    "check":    check,
    "severity": severity,
    "node":     node,
    "message":  message,
    "fixable":  fixable,
    "applied":  applied,
  }


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
  """
  Return the Levenshtein edit distance between `a` and `b`.

  Args:
    a: First string.
    b: Second string.

  Returns:
    Non-negative integer edit distance.
  """
  if a == b:
    return 0
  m, n = len(a), len(b)
  # waiver: small matrix — dp-table is clear and O(m*n) is fine for short tag segments
  dp = list(range(n + 1))
  for i in range(1, m + 1):
    prev = dp[0]
    dp[0] = i
    for j in range(1, n + 1):
      temp = dp[j]
      if a[i - 1] == b[j - 1]:
        dp[j] = prev
      else:
        dp[j] = 1 + min(prev, dp[j], dp[j - 1])
      prev = temp
  return dp[n]


def _parse_topics_md(content: str) -> set[str]:
  """
  Parse a `topics.md` file and return the set of `wiki/*` tags it declares.

  Each `### <axis>/<value_path>` heading declares one tag; the heading text
  is prefixed with `wiki/` to recover the canonical tag string.

  Args:
    content: Raw text of the `topics.md` file.

  Returns:
    Set of `wiki/<axis>/<value>` tag strings declared in the index.
  """
  tags: set[str] = set()

  for raw_line in content.splitlines():
    line = raw_line.strip()

    # `### <axis>/<value>` heading — declares one tag
    if line.startswith("### "):
      heading = line[4:].strip()
      if heading:
        tags.add(f"{_WIKI_TAG_PREFIX}{heading}")

  return tags


def _read_topics_md_tags(index_path: Path) -> set[str] | None:
  """
  Return the set of `wiki/*` tag strings declared in `topics.md`, or `None`.

  Args:
    index_path: Absolute path to the `topics.md` file.

  Returns:
    Set of tag strings from `### <axis>/<value>` headings, prefixed with
    `wiki/`, or `None` when the file does not exist.
  """
  # guard: index file absent
  if not index_path.is_file():
    return None
  content = index_path.read_text(encoding = _ENCODING)
  return _parse_topics_md(content)


def _see_also_lines_from_node(
  node: _nodes.MarkdownNode | _nodes.CodeNode,
) -> list[str]:
  """
  Return the raw See-also items from a node.

  For markdown nodes: lines from the managed See-also section body.
  For code nodes: items from the `see_also` property.

  Args:
    node: Loaded node object.

  Returns:
    List of raw line strings (no leading `- ` for markdown, bare items for code).
  """
  if isinstance(node, _nodes.MarkdownNode):
    inner = node.see_also_inner
    if not inner:
      return []
    lines = []
    for ln in inner.splitlines():
      stripped = ln.strip()
      if stripped.startswith("- "):
        lines.append(stripped[2:].strip())
    return lines
  # CodeNode
  return list(node.see_also)


def _extract_link_target(item: str) -> tuple[str, str]:
  """
  Extract the link target path and gloss from a See-also item string.

  Handles two formats:

  - Markdown format: `[text](target) — gloss` → `(target, gloss)`
  - Bare format (code nodes): `target — gloss` or `target` → `(target, gloss)`

  Args:
    item: Raw See-also item string (without leading `- `).

  Returns:
    Tuple `(link_target, gloss)` where `gloss` may be empty.
  """
  stripped = item.strip()

  # Markdown link format: `[text](target) ...`
  m = _MD_LINK_RE.match("- " + stripped)
  if m:
    target = m.group(2)
    rest = stripped[m.end() - 2:].strip()
    gloss = rest[1:].strip() if rest.startswith("—") else ""
    return target, gloss

  # Bare format: `target — gloss`
  if " — " in stripped:
    target, _, gloss = stripped.partition(" — ")
    return target.strip(), gloss.strip()

  return stripped, ""


def _drop_see_also_line(node: _nodes.MarkdownNode, broken_target: str) -> None:
  """
  Remove a broken See-also line from a markdown node by rewriting the section.

  Reads the current inner content, drops any line whose link target matches
  `broken_target`, and applies the remaining lines back.  Idempotent when
  the line is already absent.

  Args:
    node: The markdown node to modify (writes in-place).
    broken_target: The link target string to drop.
  """
  inner = node.see_also_inner or ""
  kept_lines = []
  for ln in inner.splitlines():
    stripped = ln.strip()
    if not stripped.startswith("- "):
      kept_lines.append(ln)
      continue
    item_text = stripped[2:].strip()
    target, _ = _extract_link_target(item_text)
    # guard: this line has the broken target — drop it
    if target == broken_target:
      continue
    kept_lines.append(ln)
  new_inner = "\n".join(kept_lines)
  # Keep the full `- [text](target) — gloss` list-item strings: apply_link grafts
  # see_also_lines verbatim (ready-to-graft, per the curator protocol).
  kept_items = [ ln.strip() for ln in new_inner.splitlines() if ln.strip().startswith("- ") ]
  node.apply_link(see_also_lines = kept_items)


def _drop_code_see_also_line(node: _nodes.CodeNode, broken_target: str) -> None:
  """
  Remove a broken See-also item from a code node's `<wiki>` block.

  Args:
    node: The code node to modify (writes in-place).
    broken_target: The link target string to drop.
  """
  items = node.see_also
  kept = []
  for item in items:
    target, _ = _extract_link_target(item)
    # guard: this item has the broken target — drop it
    if target == broken_target:
      continue
    kept.append(item)
  node.apply_link(see_also_lines = kept)


def _refresh_gloss_markdown(
  node: _nodes.MarkdownNode,
  stale_target: str,
  new_gloss: str,
) -> None:
  """
  Refresh a stale gloss in a markdown node's See-also section.

  Replaces the entire item line for `stale_target` with the updated gloss.

  Args:
    node: The markdown node to modify (writes in-place).
    stale_target: Link target whose gloss should be refreshed.
    new_gloss: Updated gloss text (the target node's current summary).
  """
  inner = node.see_also_inner or ""
  new_lines = []
  for ln in inner.splitlines():
    stripped = ln.strip()
    if stripped.startswith("- "):
      item_text = stripped[2:].strip()
      target, _ = _extract_link_target(item_text)
      if target == stale_target:
        # Find the link text (the markdown [text] part) to rebuild the line.
        m = _MD_LINK_RE.match("- " + item_text)
        if m:
          link_text = m.group(1)
          new_lines.append(f"- [{link_text}]({target}) — {new_gloss}")
        else:
          new_lines.append(f"- {target} — {new_gloss}")
        continue
    new_lines.append(stripped)
  # Keep the full `- …` list-item strings: apply_link grafts them verbatim.
  items = [ ln for ln in new_lines if ln.startswith("- ") ]
  node.apply_link(see_also_lines = items)


def _refresh_gloss_code(
  node: _nodes.CodeNode,
  stale_target: str,
  new_gloss: str,
) -> None:
  """
  Refresh a stale gloss in a code node's `<wiki>` block.

  Args:
    node: The code node to modify (writes in-place).
    stale_target: Link target whose gloss should be refreshed.
    new_gloss: Updated gloss text (the target node's current summary).
  """
  items = node.see_also
  new_items = []
  for item in items:
    target, _ = _extract_link_target(item)
    if target == stale_target:
      new_items.append(f"{target} — {new_gloss}")
    else:
      new_items.append(item)
  node.apply_link(see_also_lines = new_items)


# ────────────────────────────────────────────────────────────────────────────
class Doctor:
  """
  Integrity audit runner for a single wiki scope.

  Each check method takes the loaded scope nodes and returns a list of
  findings.  `run_all` collects them and, when `apply=True`, also executes
  the auto-fix for fixable findings.
  """

  # Check identifiers (canonical names).
  CHECK_ORPHAN_TOPIC    = "orphan-topic"
  CHECK_BROKEN_SEE_ALSO = "broken-see-also"
  CHECK_BROKEN_REPO_KEY = "broken-repo-key"
  CHECK_INDEX_DESYNC    = "index-desync"
  CHECK_MISSING_SUMMARY = "missing-summary"
  CHECK_STALE_GLOSS     = "stale-gloss"
  CHECK_UNKNOWN_AXIS    = "unknown-axis"
  CHECK_DUP_BRANCH      = "dup-branch"
  CHECK_BROKEN_WIKI_BLOK = "broken-wiki-block"
  CHECK_SCOPE_OVERLAP   = "scope-overlap"

  def __init__(
    self,
    *,
    repo: Path,
    scope_id: str,
    cfg: dict,
    apply: bool = False,
  ) -> None:
    """
    Initialise the doctor for one scope.

    Args:
      repo: Absolute path to the repository root.
      scope_id: Scope identifier string as declared in `lazy.settings.json`.
      cfg: Scope-config dict for `scope_id`.
      apply: When `True`, fixable findings are repaired in-place.
    """
    self._repo     = Path(repo).resolve()
    self._scope_id = scope_id
    self._cfg      = cfg
    self._apply    = apply
    self._resolver = _scope.ScopeResolver(repo = self._repo)
    self._reg      = _repos.RepoRegistry(local_repo = self._repo)

  # ── public ────────────────────────────────────────────────────────────────

  def run_all(self) -> list[dict]:
    """
    Run all checks and return the combined list of findings.

    When `apply=True`, fixable findings trigger their auto-repair before
    the finding is recorded.  Index-rebuild fixes run once at the end
    (after all per-node fixes) to keep the rebuild idempotent.

    Returns:
      List of finding dicts, each with keys `check`, `severity`, `node`,
      `message`, `fixable`, `applied`.
    """
    tag_axes     = list(self._cfg.get(_CFG_TAG_AXES) or [])
    index_path   = self._resolve_index_path()

    # The generated topics-index file may match the scope globs; it is
    # deterministic output, not a curated node, so exclude it from every check.
    node_paths = [
      p for p in self._resolver.iter_nodes(self._cfg)
      if p.resolve() != index_path
    ]

    # Load every node once; skip unrecognised types.
    nodes: list[tuple[Path, _nodes.MarkdownNode | _nodes.CodeNode]] = []
    for p in node_paths:
      nd = _nodes.node_for(p)
      # guard: unrecognised file type — skip
      if nd is None:
        continue
      nodes.append((p, nd))

    all_findings: list[dict] = []
    needs_index_rebuild = False

    # Per-node checks.
    for node_path, node in nodes:
      rel = node_path.relative_to(self._repo).as_posix()

      all_findings += self._check_orphan_topic(node, rel, index_path)
      all_findings += self._check_missing_summary(node, rel)
      all_findings += self._check_unknown_axis(node, rel, tag_axes)

      sa_findings = self._check_see_also(node, rel)
      all_findings += sa_findings

    # Scope-level checks.
    all_findings += self._check_index_desync(nodes, index_path)
    all_findings += self._check_dup_branch(nodes)
    all_findings += self._check_broken_wiki_block(node_paths)
    all_findings += self._check_scope_overlap(node_paths)

    # Apply fixable findings.
    if self._apply:
      for f in all_findings:
        # guard: finding is not fixable — skip
        if not f[_FK_FIXABLE]:
          continue
        if f[_FK_CHECK] in (self.CHECK_ORPHAN_TOPIC, self.CHECK_INDEX_DESYNC):
          needs_index_rebuild = True
          f[_FK_APPLIED] = True
        elif f[_FK_CHECK] == self.CHECK_BROKEN_SEE_ALSO:
          self._apply_drop_see_also(f)
          f[_FK_APPLIED] = True
        elif f[_FK_CHECK] == self.CHECK_STALE_GLOSS:
          self._apply_refresh_gloss(f)
          f[_FK_APPLIED] = True

      # Run index rebuild once at the end when any orphan/desync fix was requested.
      if needs_index_rebuild:
        builder = _index.TopicIndex(
          repo     = self._repo,
          cfg      = self._cfg,
          scope_id = self._scope_id,
        )
        builder.build()

    return all_findings

  # ── check: orphan-topic ───────────────────────────────────────────────────

  def _check_orphan_topic(
    self,
    node: _nodes.MarkdownNode | _nodes.CodeNode,
    rel: str,
    index_path: Path,
  ) -> list[dict]:
    """
    Report any `wiki/*` tag on the node that is absent from `topics.md`.

    Args:
      node: Loaded node object.
      rel: Repo-relative POSIX path string for the node.
      index_path: Absolute path to the `topics.md` file for this scope.

    Returns:
      List of findings (zero or more per tag).
    """
    findings: list[dict] = []
    index_tags = _read_topics_md_tags(index_path)
    # guard: index does not exist yet — nothing to cross-check against
    if index_tags is None:
      return findings

    wiki_tags = self._node_wiki_tags(node)
    for tag in wiki_tags:
      # guard: tag present in index — no finding
      if tag in index_tags:
        continue
      findings.append(_finding(
        check    = self.CHECK_ORPHAN_TOPIC,
        severity = SEV_WARN,
        message  = f"tag '{tag}' not in topics.md (index out of sync)",
        node     = rel,
        fixable  = True,
      ))
    return findings

  # ── check: broken-see-also + broken-repo-key + stale-gloss ───────────────

  def _check_see_also(
    self,
    node: _nodes.MarkdownNode | _nodes.CodeNode,
    rel: str,
  ) -> list[dict]:
    """
    Run three related See-also checks: broken links, broken repo keys, stale glosses.

    Args:
      node: Loaded node object.
      rel: Repo-relative POSIX path string for the node.

    Returns:
      List of findings.
    """
    findings: list[dict] = []
    items = _see_also_lines_from_node(node)
    node_dir = (self._repo / rel).parent

    for item in items:
      target, gloss = _extract_link_target(item)
      # guard: empty target — skip
      if not target:
        continue

      # Check for broken repo key.
      if target.startswith("@"):
        slash = target.find("/", 1)
        key = target[1:slash] if slash != -1 else target[1:]
        repo_root = self._reg.resolve_repo(key)
        if repo_root is None:
          findings.append(_finding(
            check    = self.CHECK_BROKEN_REPO_KEY,
            severity = SEV_FAIL,
            message  = f"repo key '@{key}' not in repos registry",
            node     = rel,
            fixable  = False,
          ))
          continue
        # Cross-repo link: check existence and gloss.
        abs_target = self._reg.resolve_link(target)
        if abs_target is None or not abs_target.is_file():
          f = _finding(
            check    = self.CHECK_BROKEN_SEE_ALSO,
            severity = SEV_FAIL,
            message  = f"see-also target '{target}' does not exist",
            node     = rel,
            fixable  = True,
          )
          # Embed target for the apply step (drop-line repair).
          f[_FK_TARGET] = target
          findings.append(f)
          continue
        # Stale gloss check for cross-repo target.
        findings += self._check_stale_gloss_for_target(
          node      = node,
          rel       = rel,
          target    = target,
          gloss     = gloss,
          abs_path  = abs_target,
        )
      else:
        # Local relative link.
        abs_target = (node_dir / target).resolve()
        if not abs_target.is_file():
          f = _finding(
            check    = self.CHECK_BROKEN_SEE_ALSO,
            severity = SEV_FAIL,
            message  = f"see-also target '{target}' does not exist",
            node     = rel,
            fixable  = True,
          )
          f[_FK_TARGET] = target
          findings.append(f)
          continue
        # Stale gloss check for local target.
        findings += self._check_stale_gloss_for_target(
          node      = node,
          rel       = rel,
          target    = target,
          gloss     = gloss,
          abs_path  = abs_target,
        )

    return findings

  def _check_stale_gloss_for_target(
    self,
    *,
    node: _nodes.MarkdownNode | _nodes.CodeNode,
    rel: str,
    target: str,
    gloss: str,
    abs_path: Path,
  ) -> list[dict]:
    """
    Check whether the gloss in a See-also entry matches the target's current summary.

    Args:
      node: The source node carrying the See-also entry.
      rel: Repo-relative path of the source node.
      target: Link target string (relative or `@key/path`).
      gloss: Current gloss text from the See-also entry.
      abs_path: Resolved absolute path of the link target file.

    Returns:
      Zero or one finding.
    """
    target_node = _nodes.node_for(abs_path)
    # guard: target node type unrecognised — skip stale-gloss check
    if target_node is None:
      return []

    if isinstance(target_node, _nodes.MarkdownNode):
      current_summary = target_node.wiki_summary or ""
    else:
      current_summary = target_node.summary or ""

    # guard: no summary on target — nothing to compare
    if not current_summary:
      return []
    # guard: gloss matches current summary — no finding
    if gloss == current_summary:
      return []
    # guard: gloss is empty — not a stale gloss, just missing (curator's job to fill)
    if not gloss:
      return []

    f = _finding(
      check    = self.CHECK_STALE_GLOSS,
      severity = SEV_WARN,
      message  = (
        f"see-also gloss for '{target}' is stale "
        f"(gloss: '{gloss}'; current summary: '{current_summary}')"
      ),
      node     = rel,
      fixable  = True,
    )
    f[_FK_TARGET]    = target
    f[_FK_NEW_GLOSS] = current_summary
    f[_FK_NODE_OBJ]  = node
    return [f]

  # ── check: index-desync ───────────────────────────────────────────────────

  def _check_index_desync(
    self,
    nodes: list[tuple[Path, _nodes.MarkdownNode | _nodes.CodeNode]],
    index_path: Path,
  ) -> list[dict]:
    """
    Report `wiki/*` tags in `topics.md` that no node actually carries.

    Args:
      nodes: List of `(path, node)` pairs for all scope nodes.
      index_path: Absolute path to `topics.md`.

    Returns:
      List of findings.
    """
    findings: list[dict] = []
    index_tags = _read_topics_md_tags(index_path)
    # guard: no index yet — nothing to check
    if not index_tags:
      return findings

    live_tags: set[str] = set()
    for _, node in nodes:
      live_tags.update(self._node_wiki_tags(node))

    for tag in sorted(index_tags - live_tags):
      findings.append(_finding(
        check    = self.CHECK_INDEX_DESYNC,
        severity = SEV_WARN,
        message  = f"topics.md declares '{tag}' but no node carries it",
        node     = "-",
        fixable  = True,
      ))
    return findings

  # ── check: missing-summary ────────────────────────────────────────────────

  def _check_missing_summary(
    self,
    node: _nodes.MarkdownNode | _nodes.CodeNode,
    rel: str,
  ) -> list[dict]:
    """
    Report scope nodes that have no `wiki_summary` / `summary` value.

    Args:
      node: Loaded node object.
      rel: Repo-relative POSIX path string.

    Returns:
      Zero or one finding.
    """
    if isinstance(node, _nodes.MarkdownNode):
      summary = node.wiki_summary
    else:
      summary = node.summary
    # guard: summary present — no finding
    if summary:
      return []
    return [_finding(
      check    = self.CHECK_MISSING_SUMMARY,
      severity = SEV_INFO,
      message  = _MSG_NO_SUMMARY,
      node     = rel,
      fixable  = False,
    )]

  # ── check: unknown-axis ───────────────────────────────────────────────────

  def _check_unknown_axis(
    self,
    node: _nodes.MarkdownNode | _nodes.CodeNode,
    rel: str,
    tag_axes: list[str],
  ) -> list[dict]:
    """
    Report `wiki/*` tags whose axis is not declared in `tag_axes`.

    Args:
      node: Loaded node object.
      rel: Repo-relative POSIX path string.
      tag_axes: The scope's configured axis names.

    Returns:
      List of findings.
    """
    findings: list[dict] = []
    # guard: no axes configured — every tag would be flagged; skip
    if not tag_axes:
      return findings

    axes_set = set(tag_axes)
    for tag in self._node_wiki_tags(node):
      # tag is `wiki/<axis>/<value...>`
      rest = tag[len(_WIKI_TAG_PREFIX):]
      axis = rest.split("/")[0] if "/" in rest else rest
      # guard: axis is known
      if axis in axes_set:
        continue
      findings.append(_finding(
        check    = self.CHECK_UNKNOWN_AXIS,
        severity = SEV_WARN,
        message  = f"tag '{tag}' uses unknown axis '{axis}' (not in tag_axes {tag_axes})",
        node     = rel,
        fixable  = False,
      ))
    return findings

  # ── check: dup-branch ─────────────────────────────────────────────────────

  def _check_dup_branch(
    self,
    nodes: list[tuple[Path, _nodes.MarkdownNode | _nodes.CodeNode]],
  ) -> list[dict]:
    """
    Report near-duplicate tag values within a single axis across all scope nodes.

    Heuristic: two values are near-duplicates when they are case-insensitively
    equal, one is a prefix of the other (min length `_DUP_PREFIX_MIN_LEN`), or
    their Levenshtein distance is ≤ `_DUP_EDIT_DIST_THRESHOLD`.  This check
    is report-only (never auto-fixed).  Values are grouped by the axis segment
    of each `wiki/<axis>/<value>` tag the nodes actually carry, not by the
    configured `tag_axes` — an unknown axis is flagged separately by
    `_check_unknown_axis`.

    Args:
      nodes: List of `(path, node)` pairs for all scope nodes.

    Returns:
      List of `WARN` findings, one per detected near-duplicate pair.
    """
    findings: list[dict] = []
    # Collect all distinct values per axis across the scope.
    axis_values: dict[str, set[str]] = {}
    for _, node in nodes:
      for tag in self._node_wiki_tags(node):
        rest = tag[len(_WIKI_TAG_PREFIX):]
        parts = rest.split("/", 1)
        # guard: tag has no value under the axis
        if len(parts) < 2:
          continue
        axis, value = parts[0], parts[1]
        axis_values.setdefault(axis, set()).add(value)

    # Check each pair of distinct values within the same axis.
    reported: set[tuple[str, str]] = set()
    for axis, values in sorted(axis_values.items()):
      val_list = sorted(values)
      for i, a in enumerate(val_list):
        for b in val_list[i + 1:]:
          a_low, b_low = a.lower(), b.lower()
          is_dup = False
          if a_low == b_low:
            is_dup = True
          elif (
            len(a_low) >= _DUP_PREFIX_MIN_LEN
            and len(b_low) >= _DUP_PREFIX_MIN_LEN
            and (b_low.startswith(a_low) or a_low.startswith(b_low))
          ):
            is_dup = True
          elif _levenshtein(a_low, b_low) <= _DUP_EDIT_DIST_THRESHOLD:
            is_dup = True

          if is_dup:
            pair = (min(a, b), max(a, b))
            # guard: already reported this pair
            if pair in reported:
              continue
            reported.add(pair)
            findings.append(_finding(
              check    = self.CHECK_DUP_BRANCH,
              severity = SEV_WARN,
              message  = (
                f"near-duplicate values in axis '{axis}': "
                f"'{a}' vs '{b}' — consider consolidating"
              ),
              node     = "-",
              fixable  = False,
            ))
    return findings

  # ── check: broken-wiki-block ──────────────────────────────────────────────

  def _check_broken_wiki_block(self, node_paths: list[Path]) -> list[dict]:
    """
    Report code nodes with unterminated `<wiki>` blocks or unrecognised comment prefixes.

    Skips markdown files (they have no `<wiki>` block) and skips files with
    unrecognised extensions (those aren't code nodes at all).

    Args:
      node_paths: All file paths returned by `iter_nodes` for this scope.

    Returns:
      List of findings.
    """
    findings: list[dict] = []
    for p in node_paths:
      # guard: markdown files don't have <wiki> blocks
      if p.suffix.lower() == _MD_EXT:
        continue
      ext = p.suffix.lower()
      style = _nodes._comment_style(ext)
      # guard: unrecognised extension — not a code node
      if style is None:
        continue
      rel = p.relative_to(self._repo).as_posix()
      try:
        text = p.read_text(encoding = _ENCODING)
      except OSError:
        findings.append(_finding(
          check    = self.CHECK_BROKEN_WIKI_BLOK,
          severity = SEV_WARN,
          message  = _MSG_UNREADABLE,
          node     = rel,
          fixable  = False,
        ))
        continue

      lines = text.splitlines(keepends = True)

      # Check for unterminated block: open tag present without matching close tag.
      open_found = self._has_wiki_open(lines, style)
      close_found = self._has_wiki_close(lines, style)

      if open_found and not close_found:
        findings.append(_finding(
          check    = self.CHECK_BROKEN_WIKI_BLOK,
          severity = SEV_FAIL,
          message  = _MSG_OPEN_NO_CLOSE,
          node     = rel,
          fixable  = False,
        ))
      elif close_found and not open_found:
        findings.append(_finding(
          check    = self.CHECK_BROKEN_WIKI_BLOK,
          severity = SEV_FAIL,
          message  = _MSG_CLOSE_NO_OPEN,
          node     = rel,
          fixable  = False,
        ))

    return findings

  def _has_wiki_open(self, lines: list[str], prefix: str) -> bool:
    """
    Return True when the `<wiki>` open marker is present in `lines`.

    Args:
      lines: List of source lines.
      prefix: Comment prefix for the file (`"/*"` for block-comment languages).

    Returns:
      True when the open marker line is found.
    """
    if prefix == _nodes._BLOCK_COMMENT_SENTINEL:
      return any(ln.strip() == _WIKI_OPEN_BLOCK_LINE for ln in lines)
    return any(
      _nodes._strip_comment_prefix(ln.rstrip("\n").rstrip("\r"), prefix) == _WIKI_OPEN_TAG_STR
      for ln in lines
    )

  def _has_wiki_close(self, lines: list[str], prefix: str) -> bool:
    """
    Return True when the `</wiki>` close marker is present in `lines`.

    Args:
      lines: List of source lines.
      prefix: Comment prefix for the file (`"/*"` for block-comment languages).

    Returns:
      True when the close marker line is found.
    """
    if prefix == _nodes._BLOCK_COMMENT_SENTINEL:
      return any(ln.strip() == _WIKI_CLOSE_BLOCK_LINE for ln in lines)
    return any(
      _nodes._strip_comment_prefix(ln.rstrip("\n").rstrip("\r"), prefix) == _WIKI_CLOSE_TAG_STR
      for ln in lines
    )

  # ── check: scope-overlap ──────────────────────────────────────────────────

  def _check_scope_overlap(self, node_paths: list[Path]) -> list[dict]:
    """
    Report nodes that match multiple scopes' `paths` globs in the same repo.

    Uses `ScopeResolver.load_scopes` and tests each node against all scopes,
    flagging when more than one scope claims a path.  Report-only (never
    auto-fixed).

    Args:
      node_paths: All file paths returned by `iter_nodes` for the current scope.

    Returns:
      List of `WARN` findings.
    """
    findings: list[dict] = []
    all_scopes = self._resolver.load_scopes()
    # guard: only one scope defined — overlap is impossible
    if len(all_scopes) < 2:
      return findings

    matcher = _scope.GlobMatcher()
    for p in node_paths:
      rel = p.relative_to(self._repo).as_posix()
      matching_scopes = []
      for sid, scfg in all_scopes.items():
        paths_globs = scfg.get(_CFG_PATHS) or []
        exclude_globs = scfg.get(_CFG_EXCLUDE) or []
        included = any(matcher.match(rel, pat) for pat in paths_globs)
        excluded = any(matcher.match(rel, ep) for ep in exclude_globs)
        if included and not excluded:
          matching_scopes.append(sid)

      if len(matching_scopes) > 1:
        findings.append(_finding(
          check    = self.CHECK_SCOPE_OVERLAP,
          severity = SEV_WARN,
          message  = (
            f"node matched by multiple scopes: {matching_scopes} "
            "(narrow scope globs to resolve)"
          ),
          node     = rel,
          fixable  = False,
        ))
    return findings

  # ── apply helpers ─────────────────────────────────────────────────────────

  def _apply_drop_see_also(self, finding: dict) -> None:
    """
    Remove the broken link from the node's See-also section.

    Args:
      finding: The finding dict; must carry `"node"` (rel path) and `"_target"`.
    """
    rel     = finding.get(_FK_NODE, "")
    target  = finding.get(_FK_TARGET, "")
    # guard: missing node path or target
    if not rel or rel == "-" or not target:
      return
    abs_path = self._repo / rel
    # guard: file absent
    if not abs_path.is_file():
      return
    node = _nodes.node_for(abs_path)
    # guard: unrecognised type
    if node is None:
      return
    if isinstance(node, _nodes.MarkdownNode):
      _drop_see_also_line(node, target)
    else:
      _drop_code_see_also_line(node, target)

  def _apply_refresh_gloss(self, finding: dict) -> None:
    """
    Refresh the stale gloss in the node's See-also section.

    Args:
      finding: The finding dict; must carry `"_node_obj"`, `"_target"`, and `"_new_gloss"`.
    """
    node      = finding.get(_FK_NODE_OBJ)
    target    = finding.get(_FK_TARGET, "")
    new_gloss = finding.get(_FK_NEW_GLOSS, "")
    # guard: missing data
    if node is None or not target or not new_gloss:
      return
    if isinstance(node, _nodes.MarkdownNode):
      _refresh_gloss_markdown(node, target, new_gloss)
    else:
      _refresh_gloss_code(node, target, new_gloss)

  # ── helpers ───────────────────────────────────────────────────────────────

  def _resolve_index_path(self) -> Path:
    """
    Return the absolute path to `topics.md` for this scope.

    Returns:
      Absolute `Path` derived from `cfg["topics_index"]` relative to
      the repository root, falling back to `_DEFAULT_TOPICS_INDEX`.
    """
    raw: str = self._cfg.get(_CFG_TOPICS_INDEX, _DEFAULT_TOPICS_INDEX)
    return (self._repo / raw).resolve()

  def _node_wiki_tags(
    self,
    node: _nodes.MarkdownNode | _nodes.CodeNode,
  ) -> list[str]:
    """
    Return the `wiki/*`-prefixed topic tags for either node type.

    For `MarkdownNode` this is `node.wiki_tags`; for `CodeNode` the plain
    `topics` list is prefixed with `wiki/` to produce canonical tag strings.

    Args:
      node: A loaded node object.

    Returns:
      List of `wiki/<axis>/<value>` tag strings.
    """
    if isinstance(node, _nodes.MarkdownNode):
      return node.wiki_tags
    # CodeNode topics are stored without the `wiki/` prefix.
    return [ f"{_WIKI_TAG_PREFIX}{t}" for t in node.topics ]
