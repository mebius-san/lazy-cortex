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

import json
import os
import re
import time
from pathlib import Path

import domains as _domains
import index as _index
import mirror as _mirror
import nodes as _nodes
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

# Settings path and keys read by the domain checks.
_SETTINGS_PATH        = ".claude/lazy.settings.json"
_ROUTINES_KEY         = "routines"
_DAEMON_KEY           = "daemon"
_DAEMON_ENABLED_KEY   = "enabled"

# The domain routine names the install skill registers.
_DOMAIN_ROUTINES      = ( "lazy-wiki.domain-scan", "lazy-wiki.domain-full" )

# Message string constant for domain-doc-unknown findings.
_MSG_DOC_UNKNOWN      = "file in the output tree matches no dictionary group"

# Message tail shared with the `/wiki.configure domains` overlap warning.
_MSG_OUTPUT_IN_SCOPE  = (
  "the generated tree is excluded from every scope regardless, so these globs claim "
  "nothing — narrow them so the scope says what it actually covers"
)

# Prefix that marks a leftover cross-repo See-also link (the form no longer resolves).
_AT_PREFIX            = "@"

# Message string constant for mirror-local-edit findings.
_MSG_MIRROR_LOCAL_EDIT = (
  "mirror body differs from the source — edits outside the wiki layer "
  "are overwritten by the next mirror-sync"
)

# Git bookkeeping paths consulted for the clone's last-fetch time.
_GIT_DIR_NAME         = ".git"
_FETCH_HEAD_NAME      = "FETCH_HEAD"

# A mirror clone older than this many days since its last fetch is reported stale.
_MIRROR_STALE_DAYS    = 7

# Seconds in one day, for clone-age arithmetic.
_SECONDS_PER_DAY      = 86400


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

  # the index declares its tags only through headings — the link lines carry none
  for raw_line in content.splitlines():
    line = raw_line.strip()

    # `### <axis>/<value>` heading — declares one tag
    if line.startswith("### "):
      heading = line[4:].strip()
      if heading:
        tags.add(f"{_WIKI_TAG_PREFIX}{heading}")

  # callers diff this against the live node tags to spot desync
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

  # neither shape matched — the whole item is the target and there is no gloss
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

  Runs a fixed suite of checks against the scope's nodes and returns structured
  findings, each carrying a severity, message, affected node, and whether it can
  be auto-repaired.

  Guarantees:
    - Auto-repair writes only to the audited scope's own nodes and to that scope's topics index;
      no file outside the scope is ever modified.

  Attributes:
    CHECK_ORPHAN_TOPIC: Check identifier for a node tag missing from the topics index.
    CHECK_BROKEN_SEE_ALSO: Check identifier for a See-also link whose target does not exist.
    CHECK_PATH_BASE: Check identifier for a See-also link written against a non-canonical base.
    CHECK_DANGLING_AT: Check identifier for a See-also link carrying a leftover `@` prefix.
    CHECK_INDEX_DESYNC: Check identifier for a topics-index tag no node currently carries.
    CHECK_MISSING_SUMMARY: Check identifier for a node with no summary.
    CHECK_STALE_GLOSS: Check identifier for a See-also gloss that no longer matches its
      target's current summary.
    CHECK_UNKNOWN_AXIS: Check identifier for a tag whose axis is not declared for the scope.
    CHECK_DUP_BRANCH: Check identifier for near-duplicate tag values within the same axis.
    CHECK_BROKEN_WIKI_BLOK: Check identifier for a code node with an unterminated `<wiki>` block.
    CHECK_SCOPE_OVERLAP: Check identifier for a node claimed by more than one configured scope.
    CHECK_MIRROR_ORPHAN_CLONE: Check identifier for a runtime clone whose scope has no `mirror` block.
    CHECK_MIRROR_DIR_MISSING: Check identifier for a configured mirror whose directory does not exist.
    CHECK_MIRROR_UNCOVERED: Check identifier for a `mirror_path` the scope's `paths` globs miss.
    CHECK_MIRROR_STALE: Check identifier for a mirror clone that has not been fetched recently.
    CHECK_MIRROR_LOCAL_EDIT: Check identifier for a mirror node whose body drifted from the source.
  """

  # Contract:
  # Auto-repair NEVER writes outside the audited scope: the only files it modifies are that
  # scope's own nodes and that scope's topics index.

  # Check identifiers (canonical names).
  CHECK_ORPHAN_TOPIC    = "orphan-topic"
  CHECK_BROKEN_SEE_ALSO = "broken-see-also"
  CHECK_PATH_BASE       = "see-also-path-base"
  CHECK_DANGLING_AT     = "dangling-at-prefix"
  CHECK_INDEX_DESYNC    = "index-desync"
  CHECK_MISSING_SUMMARY = "missing-summary"
  CHECK_STALE_GLOSS     = "stale-gloss"
  CHECK_UNKNOWN_AXIS    = "unknown-axis"
  CHECK_DUP_BRANCH      = "dup-branch"
  CHECK_BROKEN_WIKI_BLOK = "broken-wiki-block"
  CHECK_SCOPE_OVERLAP   = "scope-overlap"
  CHECK_MIRROR_ORPHAN_CLONE = "mirror-clone-orphaned"
  CHECK_MIRROR_DIR_MISSING  = "mirror-dir-missing"
  CHECK_MIRROR_UNCOVERED    = "mirror-paths-uncovered"
  CHECK_MIRROR_STALE        = "mirror-stale-fetch"
  CHECK_MIRROR_LOCAL_EDIT   = "mirror-local-edit"

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

  # ── public ────────────────────────────────────────────────────────────────

  def run_all(self) -> list[dict]:
    """
    Run all checks and return the combined list of findings.

    When `apply=True`, fixable findings trigger their auto-repair before
    the finding is recorded.  Index-rebuild fixes run once at the end
    (after all per-node fixes) to keep the rebuild idempotent.

    Guarantees:
      - No file is written when the doctor was constructed with `apply` false.
      - A finding whose `fixable` flag is false is never repaired automatically.
      - A repair that locates a See-also line by its target text runs before that line's path base
        is rewritten, and the topics index is rebuilt once, after every per-node repair.

    Returns:
      List of finding dicts, each with keys `check`, `severity`, `node`,
      `message`, `fixable`, `applied`.
    """

    # Contract:
    # When the doctor was constructed with `apply` false, the run NEVER writes to any file;
    # every check only reports.

    # Contract:
    # A finding whose `fixable` flag is false is NEVER repaired automatically, under any setting.

    # the scope's axes and index address gate the classification checks below; the vocabulary is
    # the repository's, narrowed by whatever this scope declares
    tag_axes     = self._resolver.tag_axes(self._cfg)
    index_path   = self._resolve_index_path()

    # the generated topics-index file is excluded by the resolver itself, so this is
    # the curated-node set already
    node_paths = self._resolver.iter_nodes(self._cfg)

    # Load every node once; skip unrecognised types.
    nodes: list[tuple[Path, _nodes.MarkdownNode | _nodes.CodeNode]] = []
    for p in node_paths:
      nd = _nodes.node_for(p)
      # guard: unrecognised file type — skip
      if nd is None:
        continue
      nodes.append((p, nd))

    # one flat findings list across every check; the index rebuild is deferred to the end
    all_findings: list[dict] = []
    needs_index_rebuild = False

    # Per-node checks.
    for node_path, node in nodes:
      rel = node_path.relative_to(self._repo).as_posix()

      # classification checks — what the node declares about itself
      all_findings += self._check_orphan_topic(node, rel, index_path)
      all_findings += self._check_missing_summary(node, rel)
      all_findings += self._check_unknown_axis(node, rel, tag_axes)

      # linking checks — what the node points at
      sa_findings = self._check_see_also(node, rel)
      all_findings += sa_findings

    # Scope-level checks.
    all_findings += self._check_index_desync(nodes, index_path)
    all_findings += self._check_dup_branch(nodes)
    all_findings += self._check_broken_wiki_block(node_paths)
    all_findings += self._check_scope_overlap(node_paths)
    all_findings += self._check_mirror()

    # Domain(wiki.integrity):
    # # What the doctor treats as a defect and what it repairs itself
    # An integrity finding carries a severity, an address and a repairability flag. Severity splits defects into
    # those that break connectivity, those that weaken it, and those merely worth the operator's notice. The address
    # is either one particular node or the whole scope, when the fault lies with the shared configuration rather than
    # with a node.
    # Only what has a single correct restoration is repaired automatically: a broken link, a stale gloss, a
    # non-canonical path base, and a divergence between the topic index and the live tags. Everything where the
    # choice belongs to a human — an unclosed managed region, a disputed axis, a node owned twice, local edits
    # inside a mirror — is only reported.
    # The order of the repairs follows their mutual interference: fixes that locate a line by the text of its target
    # run before the path base is rewritten, otherwise the line is no longer findable afterwards. The topic index is
    # rebuilt last and once, because it depends on the final state of every node.

    # Contract:
    # A repair that locates a See-also line by the text of its target MUST run before that line's
    # path base is rewritten, and the topics index MUST be rebuilt once, after every per-node repair.

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

      # Base rewrites run last: every other per-line repair matches on the target string
      # as currently written, so rewriting the base first would make those matches miss.
      for f in all_findings:
        # guard: not a base-rewrite finding
        if f[_FK_CHECK] != self.CHECK_PATH_BASE:
          continue
        self._apply_rebase_see_also(f)
        f[_FK_APPLIED] = True

      # Run index rebuild once at the end when any orphan/desync fix was requested.
      if needs_index_rebuild:
        builder = _index.TopicIndex(
          repo     = self._repo,
          cfg      = self._cfg,
          scope_id = self._scope_id,
        )
        builder.build()

    # findings carry their own applied/fixable flags — the caller renders from this alone
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

    # Domain(wiki.taxonomy):
    # # The topic index and the live tags must agree
    # The topic index is a derived projection: it lists exactly the tags the scope's nodes carry right now, no more
    # and no less. Divergence is possible in both directions and means the same thing — the index was built before
    # the last edit to the classification.
    # A tag on a node that the index does not know appears when the node was classified after the build. A tag in the
    # index that no node carries is left over from an earlier build: the node was retagged or deleted. Both cases are
    # cured by rebuilding the index, not by editing nodes.
    # Until the index has been built at least once there is nothing to compare against, and that does not count as a
    # divergence.

    # a tag the index never learned about means the node was classified after the last build
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

  # ── check: broken-see-also + dangling-at-prefix + stale-gloss ─────────────

  def _check_see_also(
    self,
    node: _nodes.MarkdownNode | _nodes.CodeNode,
    rel: str,
  ) -> list[dict]:
    """
    Run three related See-also checks: broken links, dangling `@` prefixes, stale glosses.

    Args:
      node: Loaded node object.
      rel: Repo-relative POSIX path string for the node.

    Returns:
      List of findings.
    """
    findings: list[dict] = []
    items = _see_also_lines_from_node(node)
    node_dir = (self._repo / rel).parent

    # Domain(wiki.graph):
    # # Three ways to break a See-also link
    # A link between nodes lives as a glossed reference in the See-also section, and it breaks in three different
    # ways, each with a cure of its own.
    # A reference into another repository is a leftover of the earlier addressing form, which no longer resolves
    # anywhere. The link may still be meaningful, but it cannot be restored mechanically: the target must either be
    # rewritten as the local path of a mirrored node, or removed by hand.
    # A reference written from a foreign base — the scope root or the vault root instead of the node's own directory
    # — is essentially intact: the edge exists, only its written address is spoilt. Such a link is cured by rewriting
    # the base, not by deleting the line.
    # A reference that resolves from no base at all means the target is gone: the edge is dead and the line is
    # deleted.

    # a leftover @-prefixed link and a local link fail in different ways, so each is checked apart
    for item in items:
      target, gloss = _extract_link_target(item)
      # guard: empty target — skip
      if not target:
        continue

      # guard: leftover cross-repo form — the `@` prefix resolves nowhere anymore; the
      # link must be rewritten to a mirrored node's local path or dropped by the operator
      if target.startswith(_AT_PREFIX):
        findings.append(_finding(
          check    = self.CHECK_DANGLING_AT,
          severity = SEV_WARN,
          message  = (
            f"see-also target '{target}' carries a dangling '{_AT_PREFIX}' prefix — "
            "rewrite it to a mirrored node's local path or drop the line"
          ),
          node     = rel,
          fixable  = False,
        ))
        continue

      # a local link is judged by resolving it against the node's own directory
      abs_target = (node_dir / target).resolve()
      if not abs_target.is_file():
        # The target may be written against a coarser base (scope root, repo root) by
        # an older curator run. Such a link is repairable by rewriting its base, not by
        # dropping the line — the edge itself is sound.
        rebased = _nodes.resolve_see_also_target(target, self._repo / rel)
        if rebased is not None:
          finding = _finding(
            check    = self.CHECK_PATH_BASE,
            severity = SEV_WARN,
            message  = (
              f"see-also target '{target}' is written against a non-canonical base "
              f"(resolves to '{rebased.relative_to(self._repo).as_posix()}')"
            ),
            node     = rel,
            fixable  = True,
          )
          finding[_FK_TARGET]   = target
          finding[_FK_NODE_OBJ] = node
          findings.append(finding)
          abs_target = rebased
        else:
          # no base recovers it — the edge itself is gone, so the line must be dropped
          finding = _finding(
            check    = self.CHECK_BROKEN_SEE_ALSO,
            severity = SEV_FAIL,
            message  = f"see-also target '{target}' does not exist",
            node     = rel,
            fixable  = True,
          )
          finding[_FK_TARGET] = target
          findings.append(finding)
          continue

      # the gloss is compared against whatever the target resolved to, base-repaired or not
      findings += self._check_stale_gloss_for_target(
        node      = node,
        rel       = rel,
        target    = target,
        gloss     = gloss,
        abs_path  = abs_target,
      )

    # all three See-also checks report through one list so the caller applies them together
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
      target: Link target string (node-relative).
      gloss: Current gloss text from the See-also entry.
      abs_path: Resolved absolute path of the link target file.

    Returns:
      Zero or one finding.
    """
    target_node = _nodes.node_for(abs_path)
    # guard: target node type unrecognised — skip stale-gloss check
    if target_node is None:
      return []

    # Domain(wiki.graph):
    # # A gloss is a copy of the target's summary
    # The gloss beside a link exists for one purpose: to let a reader decide whether to open a node without opening
    # it. It therefore repeats verbatim the current summary of the side the link leads to; any divergence is a lag
    # behind an edit of that summary, and it is cured by carrying the fresh text into the gloss.
    # Two cases do not count as divergence: the target has no summary at all, so there is nothing to compare against;
    # and the gloss is empty — the link is not described yet, which is classification work rather than repair.

    # the gloss is compared against the target's own summary, wherever that type keeps it
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

    # the gloss survived a summary edit — carry the replacement text for the apply step
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

    # pool what the nodes actually declare right now
    live_tags: set[str] = set()
    for _, node in nodes:
      live_tags.update(self._node_wiki_tags(node))

    # anything the index still lists but no node carries is a leftover from an earlier build
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
      tag_axes: The scope's effective axis names — the repository vocabulary, narrowed.

    Returns:
      List of findings.
    """
    findings: list[dict] = []
    # guard: no axes configured — every tag would be flagged; skip
    if not tag_axes:
      return findings

    # Domain(wiki.taxonomy):
    # # The vault declares a tag's axis
    # A tag is built as an axis and a value inside it: the axis asks the question, the value answers it. The set of
    # axes is declared by the vault in advance and is closed; values inside an axis grow freely. An area of the
    # vault may narrow the set to the axes it actually uses, but never widen it.
    # A tag with an undeclared axis is either a typo or a new axis nobody declared. The two cases cannot be told
    # apart mechanically, so such a tag is only flagged: the choice between renaming the tag and extending the
    # vocabulary belongs to the operator.
    # An area with no axes available to it is not checked at all — otherwise every tag would fall under suspicion.

    # flag every tag whose axis the scope never declared
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

    # Domain(wiki.taxonomy):
    # # Near-duplicate branches inside one axis
    # Values inside an axis are entered by hand and split apart over time: one concept picks up two similar names,
    # and related nodes drift into different branches. Only values of the same axis are compared — the same name in
    # different axes is meaningful and is not duplication.
    # A split is signalled by three things: equality ignoring case, one value nesting in the other as a prefix while
    # both are at least `4` characters long, and an edit distance of no more than `3`. This is a heuristic, not a
    # proof, so it reports a candidate pair and never merges branches itself. The pair is unordered and is reported
    # once.

    # Check each pair of distinct values within the same axis.
    reported: set[tuple[str, str]] = set()
    for axis, values in sorted(axis_values.items()):
      val_list = sorted(values)
      for i, a in enumerate(val_list):
        for b in val_list[i + 1:]:
          # three signals stand in for "the operator meant the same branch": case-fold
          # equality, one value being a prefix of the other, and a small edit distance
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

          # order-independent pair key so the same duplicate is reported only once
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
      # guard: unreadable file — report it instead of aborting the whole sweep
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

      # the tags are matched per line, so the block is inspected line-wise
      lines = text.splitlines(keepends = True)

      # Check for unterminated block: open tag present without matching close tag.
      open_found = self._has_wiki_open(lines, style)
      close_found = self._has_wiki_close(lines, style)

      # either tag alone means the block cannot be parsed or rewritten safely
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

    # Domain(wiki.graph):
    # # A managed region inside code
    # A wiki node can also be a code file: everything belonging to the wiki then lives in a comment bounded by a pair
    # of markers, an opening one and a closing one. The boundaries of the region are the only thing separating wiki
    # text from the author's own.
    # A single marker with no counterpart leaves the boundary undefined: where the region ends is unknown, so it can
    # be neither read nor rewritten safely, and the damage is only reported.
    # Comment syntax depends on the language of the file; a file in a language whose comment form is unknown is not a
    # code node and is not checked at all.

    # report-only: a malformed block is never rewritten, only surfaced
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

    # Domain(wiki.scope):
    # # A node belongs to exactly one scope
    # A scope claims a file when the file matched at least one including pattern and no excluding one. Competing
    # claims are resolved not by priority but by separation: an overlap counts as a configuration error, not as a
    # situation that has a winner.
    # Double ownership means two topic indexes classify and link the same node independently, overwriting each
    # other's work. The only cure is narrowing the patterns, so an overlap is reported to the operator and never
    # resolved automatically.
    # A single configured scope has nothing to overlap with.

    # replay every scope's own glob logic against each node to see who else claims it
    matcher = _scope.GlobMatcher()
    for p in node_paths:
      rel = p.relative_to(self._repo).as_posix()
      matching_scopes = []
      for sid, scfg in all_scopes.items():
        # a scope claims the node only when an include glob hits and no exclude does
        paths_globs = scfg.get(_CFG_PATHS) or []
        exclude_globs = scfg.get(_CFG_EXCLUDE) or []
        included = any(matcher.match(rel, pat) for pat in paths_globs)
        excluded = any(matcher.match(rel, ep) for ep in exclude_globs)
        if included and not excluded:
          matching_scopes.append(sid)

      # two claimants means two indexes would curate the same node against each other
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

  # ── check: mirror ─────────────────────────────────────────────────────────

  def _check_mirror(self) -> list[dict]:
    """
    Audit the scope's mirror wiring and content drift (all report-only).

    Five checks: a leftover runtime clone for a scope with no `mirror` block;
    a configured mirror whose directory does not exist yet; a `mirror_path`
    the scope's `paths` globs do not cover (mirrored files are silently not
    nodes); a clone whose last fetch is older than the staleness window; and
    mirror files whose source-owned body drifted from the clone (local edits
    the next sync overwrites).  The drift and staleness checks need the clone
    on disk and are skipped without one.

    Returns:
      List of `WARN` findings.
    """
    findings: list[dict] = []
    sync = _mirror.MirrorSync(repo = self._repo, scope_id = self._scope_id, cfg = self._cfg)

    # guard: no mirror block — the only defect possible is a leftover runtime clone
    if not sync.configured:
      if sync.clone_dir.is_dir():
        findings.append(_finding(
          check    = self.CHECK_MIRROR_ORPHAN_CLONE,
          severity = SEV_WARN,
          message  = (
            f"runtime clone exists at '{_mirror.RUNTIME_MIRRORS_REL}/{self._scope_id}' "
            "but the scope has no mirror block (leftover — safe to delete)"
          ),
        ))
      return findings

    # Domain(wiki.scope):
    # # A mirror of a foreign repository inside the vault
    # Foreign documents a scope needs are pulled into the vault as copies: the body belongs to the source, while the
    # wiki superstructure over it belongs to the receiving side. Hence four ways for a mirror to diverge from
    # expectations.
    # A copy on disk with no declared mirror is a leftover of an earlier configuration: nobody updates it, and
    # deleting it is safe. A declared mirror with no directory means synchronisation has never run.
    # A mirror directory not covered by the scope's patterns is the quietest defect: the files sit in place but never
    # become nodes, and the wiki simply does not see them.
    # How long ago the source was last consulted matters more than the age of the copy itself: freshness is measured
    # from the last fetch, and a threshold of `7` days separates a live mirror from a lagging one.
    # A divergence between the body of the copy and the source is an edit made around the wiki superstructure; the
    # next synchronisation will overwrite it, so the warning comes in advance.

    # a configured mirror whose directory never materialised has not been synced yet
    mirror_path = sync.mirror_path
    if not (self._repo / mirror_path).is_dir():
      findings.append(_finding(
        check    = self.CHECK_MIRROR_DIR_MISSING,
        severity = SEV_WARN,
        message  = (
          f"mirror configured but '{mirror_path}' does not exist "
          f"(run `lazycortex-wiki mirror-sync {self._scope_id}`)"
        ),
      ))

    # every mirrored file must fall under a paths glob, or it is silently not a node
    probe = f"{mirror_path}/__probe__.md"
    paths_globs: list[str] = self._cfg.get(_CFG_PATHS) or []
    matcher = _scope.GlobMatcher()
    if not any(matcher.match(probe, pat) for pat in paths_globs):
      findings.append(_finding(
        check    = self.CHECK_MIRROR_UNCOVERED,
        severity = SEV_WARN,
        message  = (
          f"scope paths do not cover mirror_path '{mirror_path}' — mirrored files are "
          f"silently not nodes (add '{mirror_path}/**' to the scope's paths)"
        ),
      ))

    # guard: staleness and drift compare against the clone — skip without one
    if not sync.clone_dir.is_dir():
      return findings

    # a clone the routine stopped fetching means the mirror silently lags the source
    age_days = (time.time() - self._clone_fetch_time(sync.clone_dir)) / _SECONDS_PER_DAY
    if age_days > _MIRROR_STALE_DAYS:
      findings.append(_finding(
        check    = self.CHECK_MIRROR_STALE,
        severity = SEV_WARN,
        message  = (
          f"source clone last fetched {age_days:.0f} days ago "
          f"(> {_MIRROR_STALE_DAYS}) — the mirror may lag the source"
        ),
      ))

    # body drift outside the wiki layer is work the next sync silently erases
    for source_rel in sync.source_files():
      mirror_rel = f"{mirror_path}/{source_rel}"
      mirror_abs = self._repo / mirror_rel
      # guard: not mirrored yet — nothing to drift
      if not mirror_abs.is_file():
        continue
      mirror_side = sync.consumer_stripped(mirror_abs.read_text(encoding = _ENCODING))
      source_side = sync.consumer_stripped(
        (sync.clone_dir / source_rel).read_text(encoding = _ENCODING)
      )
      if mirror_side != source_side:
        findings.append(_finding(
          check    = self.CHECK_MIRROR_LOCAL_EDIT,
          severity = SEV_WARN,
          message  = _MSG_MIRROR_LOCAL_EDIT,
          node     = mirror_rel,
        ))
    return findings

  def _clone_fetch_time(self, clone_dir: Path) -> float:
    """
    Return the epoch timestamp of the clone's last fetch.

    Args:
      clone_dir: Absolute path of the runtime clone directory.

    Returns:
      Modification time of `.git/FETCH_HEAD` when present, of `.git`
      otherwise, falling back to the clone directory itself.
    """
    # the freshest signal wins: FETCH_HEAD is touched by every fetch
    for candidate in (
        clone_dir / _GIT_DIR_NAME / _FETCH_HEAD_NAME,
        clone_dir / _GIT_DIR_NAME,
        clone_dir,
    ):
      try:
        return candidate.stat().st_mtime
      except OSError:
        continue
    # nothing stat-able — treat as never fetched
    return 0.0

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

  def _apply_rebase_see_also(self, finding: dict) -> None:
    """
    Rewrite the node's See-also targets to the canonical node-relative base.

    Re-reads the node from disk (a gloss refresh in the same run may have rewritten it)
    and re-applies its current items — `apply_link` normalises every target on write, so
    one call repairs every non-canonical line on the node and is a no-op once canonical.

    Args:
      finding: The finding dict; must carry `"node"` (rel path).
    """
    rel = finding.get(_FK_NODE, "")
    # guard: missing node path
    if not rel or rel == "-":
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
      inner = node.see_also_inner or ""
      items = [ ln.strip() for ln in inner.splitlines() if ln.strip().startswith("- ") ]
    else:
      items = list(node.see_also)
    node.apply_link(see_also_lines = items)

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


# ────────────────────────────────────────────────────────────────────────────
class DomainDoctor:
  """
  Integrity audit runner for the repo's domain-spec configuration.

  Repo-level (not per-scope): checks the `wiki.domains` section against the
  dictionary, the code's `Domain(…)` blocks, the generated docs, the wiki
  scopes, and the registered routines. Every finding is report-only — the
  repairs (edit the dictionary, run the knowledge sweep, rerun the sync, rerun
  the install) are operator moves.

  Attributes:
    CHECK_DICTIONARY_MISSING: Check identifier for a configured dictionary file that is absent.
    CHECK_DOC_UNKNOWN: Check identifier for an output file matching no dictionary group.
    CHECK_GLOSS_MISSING: Check identifier for a dictionary group carrying no gloss line.
    CHECK_GROUP_UNKNOWN: Check identifier for a code group absent from the dictionary.
    CHECK_HASH_STALE: Check identifier for a group doc whose `domain_hash` diverged from the code.
    CHECK_OUTPUT_IN_SCOPE: Check identifier for a wiki scope whose globs reach the domain output tree.
    CHECK_ROUTINE_MISMATCH: Check identifier for `wiki.domains` and the domain routines disagreeing.
  """

  # Check identifiers (canonical names).
  CHECK_DICTIONARY_MISSING = "domain-dictionary-missing"
  CHECK_DOC_UNKNOWN        = "domain-doc-unknown"
  CHECK_GLOSS_MISSING      = "domain-gloss-missing"
  CHECK_GROUP_UNKNOWN      = "domain-group-unknown"
  CHECK_HASH_STALE         = "domain-hash-stale"
  CHECK_OUTPUT_IN_SCOPE    = "domain-output-in-scope"
  CHECK_ROUTINE_MISMATCH   = "domain-routine-mismatch"

  def __init__(self, *, repo: Path) -> None:
    """
    Initialise the doctor for one repository.

    Args:
      repo: Absolute path to the repository root.
    """
    # config may be absent — run_all degrades to the routine-mismatch check alone
    self._repo = Path(repo).resolve()
    self._cfg = _domains.DomainConfig.load(self._repo)

  # ── public ────────────────────────────────────────────────────────────────

  def run_all(self) -> list[dict]:
    """
    Return the combined findings from every domain check.

    Guarantees:
      - The audit is report-only: no file, dictionary, generated doc, or settings entry is written.

    Returns:
      List of finding dicts (`check`, `severity`, `node`, `message`,
      `fixable`, `applied`); empty when domains are unconfigured and no
      domain routine is registered.
    """

    # Contract:
    # The domain audit is report-only: the run NEVER writes to any file, and NEVER changes
    # the dictionary, the generated docs, or the settings.

    # which domain routines are registered decides what an unconfigured repo can still report
    routines = self._registered_domain_routines()

    # guard: domains not configured — the only defect possible is a leftover routine
    if self._cfg is None:
      return [
        _finding(
          check    = self.CHECK_ROUTINE_MISMATCH,
          severity = SEV_WARN,
          message  = f"routine '{name}' registered but wiki.domains is not configured",
        )
        for name in routines
      ]

    # dictionary presence gates every content check
    findings: list[dict] = []
    dictionary_file = _domains.DomainDictionary(path = self._repo / self._cfg.dictionary)

    # guard: configured dictionary missing — content checks are meaningless without it
    if not dictionary_file.is_present():
      findings.append(_finding(
        check    = self.CHECK_DICTIONARY_MISSING,
        severity = SEV_FAIL,
        message  = f"wiki.domains configured but dictionary '{self._cfg.dictionary}' does not exist",
      ))
      findings += self._check_routines(routines)
      return findings

    # Domain(wiki.domains):
    # # The group dictionary is the single source of truth
    # Domain knowledge lives as markup right inside the code and is collected into documents group by group. The list
    # of groups is set by the dictionary, and the dictionary outranks the code: a group met in the code but not
    # declared in the dictionary silently drops out of the build — its knowledge reaches nowhere.
    # Hence four kinds of divergence. A group present in the code but absent from the dictionary — knowledge is lost.
    # A group declared without its gloss line — it stays unnamed in the index, and the overview of its document has
    # to be synthesised from the blocks alone. A file in the output tree answering to no declared group — it is
    # either left over from a rename or was put there by a foreign hand. A group's document lagging behind the code —
    # the content of the group's blocks is folded into a fingerprint, and a mismatch with the fingerprint recorded in
    # the document means the code was edited after the last build.
    # None of these divergences repairs itself: editing the dictionary, rebuilding, and re-registering the background
    # work are the operator's decisions.

    # content checks share one dictionary parse and one code scan
    dictionary = dictionary_file.groups()
    scanned = _domains.DomainScanner(repo = self._repo, code_globs = self._cfg.code).scan()
    layout = _domains.DomainLayout(output = self._cfg.output)
    findings += self._check_group_unknown(dictionary, scanned)
    findings += self._check_gloss_missing(dictionary)
    findings += self._check_doc_unknown(dictionary, layout)
    findings += self._check_hash_stale(dictionary, scanned, layout)
    findings += self._check_output_in_scope()
    findings += self._check_routines(routines)
    return findings

  # ── check: domain-group-unknown ───────────────────────────────────────────

  def _check_group_unknown(
    self,
    dictionary: dict[str, str],
    scanned: dict[str, list[dict]],
  ) -> list[dict]:
    """
    Report code groups the dictionary does not list.

    Args:
      dictionary: Group→gloss mapping from the dictionary file.
      scanned: Group→blocks mapping from the code scan.

    Returns:
      One `WARN` finding per unknown group, naming its carrier files.
    """
    findings: list[dict] = []
    for group in sorted(scanned):
      # guard: listed or reserved — not a finding
      if group in dictionary or group == _domains.RESERVED_GROUP:
        continue
      files = sorted({ blk[_domains.BLOCK_PATH] for blk in scanned[group] })
      findings.append(_finding(
        check    = self.CHECK_GROUP_UNKNOWN,
        severity = SEV_WARN,
        message  = (
          f"group '{group}' used in code but absent from the dictionary "
          f"(files: {', '.join(files)}) — the routine skips it silently"
        ),
      ))
    return findings

  # ── check: domain-gloss-missing ───────────────────────────────────────────

  def _check_gloss_missing(self, dictionary: dict[str, str]) -> list[dict]:
    """
    Report dictionary groups declared without a gloss line.

    Args:
      dictionary: Group→gloss mapping from the dictionary file.

    Returns:
      One `WARN` finding per group whose gloss is empty.
    """
    cfg = self._cfg
    # guard: unreachable without config — content checks run only when configured
    if cfg is None:
      return []

    # a gloss-less group reaches the index bare and the writer with nothing but its blocks
    findings: list[dict] = []
    for group in sorted(dictionary):
      # guard: the group carries a gloss — nothing to report
      if dictionary[group]:
        continue
      findings.append(_finding(
        check    = self.CHECK_GLOSS_MISSING,
        severity = SEV_WARN,
        message  = (
          f"group '{group}' has no gloss line in the dictionary — its index line stays bare "
          "and the writer synthesises the doc's overview from the blocks alone"
        ),
        node     = cfg.dictionary,
      ))
    return findings

  # ── check: domain-output-in-scope ─────────────────────────────────────────

  def _check_output_in_scope(self) -> list[dict]:
    """
    Report wiki scopes whose globs reach generated docs in the output tree.

    Returns:
      One `WARN` finding per scope whose globs reach at least one generated doc, naming
      the first such doc. The tree is excluded structurally, so the finding reports a
      misleading glob rather than a contested file.
    """
    cfg = self._cfg
    # guard: unreachable without config — content checks run only when configured
    if cfg is None:
      return []
    output_abs = self._repo / cfg.output
    # guard: no output tree yet — no file exists for two writers to fight over
    if not output_abs.is_dir():
      return []

    # Domain(wiki.domains):
    # # The domain document tree does not belong to the wiki
    # Group documents are generated from the code in full and rewritten on every build. Were the wiki's coverage to
    # span the same tree, the same files would end up with two writers: the build overwrites a document from the
    # code, while node curation edits that same document as an ordinary node, and the edits of one side vanish on
    # the next pass of the other.
    # The conflict is therefore ruled out structurally rather than by agreement: while the tree is configured at
    # all, it is excluded from every area of the vault, and no setting can hand it over. Coverage that reaches into
    # it is not a danger, only a lie about what the area covers — which is why it is reported.

    # replay every scope's own glob logic over the generated docs; one hit is one misleading glob
    findings: list[dict] = []
    matcher = _scope.GlobMatcher()
    docs = self._output_docs(output_abs)
    for sid, scfg in _scope.ScopeResolver(repo = self._repo).load_scopes().items():
      claimed = next(( rel for rel in docs if self._is_claimed_by_scope(scfg, rel, matcher) ), None)
      # guard: this scope claims nothing under the output tree
      if claimed is None:
        continue
      findings.append(_finding(
        check    = self.CHECK_OUTPUT_IN_SCOPE,
        severity = SEV_WARN,
        message  = f"scope '{sid}' globs reach '{cfg.output}' — {_MSG_OUTPUT_IN_SCOPE}",
        node     = claimed,
      ))
    return findings

  def _output_docs(self, output_abs: Path) -> list[str]:
    """
    List the markdown files the output tree currently holds.

    Args:
      output_abs: Absolute path of the output directory.

    Returns:
      Sorted repo-relative POSIX paths of every `.md` file under the tree.
    """
    docs: list[str] = []
    for base, _dirs, files in os.walk(str(output_abs)):
      docs += [
        (Path(base) / fname).relative_to(self._repo).as_posix()
        for fname in files if fname.endswith(_MD_EXT)
      ]
    return sorted(docs)

  @staticmethod
  def _is_claimed_by_scope(scfg: dict, rel: str, matcher: _scope.GlobMatcher) -> bool:
    """
    Report whether one scope's globs claim a repo-relative path.

    Args:
      scfg: Scope-config dict as declared in `lazy.settings.json`.
      rel: Repo-relative POSIX path being tested.
      matcher: Glob matcher shared across the scan.

    Returns:
      True when an include glob hits and no exclude glob does.
    """
    included = any(matcher.match(rel, pat) for pat in scfg.get(_CFG_PATHS) or [])
    excluded = any(matcher.match(rel, pat) for pat in scfg.get(_CFG_EXCLUDE) or [])
    return included and not excluded

  # ── check: domain-doc-unknown ─────────────────────────────────────────────

  def _check_doc_unknown(
    self,
    dictionary: dict[str, str],
    layout: _domains.DomainLayout,
  ) -> list[dict]:
    """
    Report files under the output tree that match no dictionary group.

    Args:
      dictionary: Group→gloss mapping from the dictionary file.
      layout: Path mapper for the output directory.

    Returns:
      One `WARN` finding per foreign file (the index itself is exempt).
    """
    cfg = self._cfg
    # guard: unreachable without config — content checks run only when configured
    if cfg is None:
      return []
    output_abs = self._repo / cfg.output
    # guard: no output tree yet — nothing to check
    if not output_abs.is_dir():
      return []

    # every file under output must be the index or a doc of a listed group
    findings: list[dict] = []
    for base, _dirs, files in os.walk(str(output_abs)):
      for fname in files:
        rel = (Path(base) / fname).relative_to(self._repo).as_posix()
        # guard: the index file is engine-owned and always legal
        if rel == f"{cfg.output}/{_domains.INDEX_NAME}":
          continue
        group = layout.group_for(rel)
        # guard: a doc of a listed group is legal
        if group is not None and group in dictionary:
          continue
        findings.append(_finding(
          check    = self.CHECK_DOC_UNKNOWN,
          severity = SEV_WARN,
          message  = _MSG_DOC_UNKNOWN,
          node     = rel,
        ))
    return findings

  # ── check: domain-hash-stale ──────────────────────────────────────────────

  def _check_hash_stale(
    self,
    dictionary: dict[str, str],
    scanned: dict[str, list[dict]],
    layout: _domains.DomainLayout,
  ) -> list[dict]:
    """
    Report groups whose generated doc lags the code's block content.

    Args:
      dictionary: Group→gloss mapping from the dictionary file.
      scanned: Group→blocks mapping from the code scan.
      layout: Path mapper for the output directory.

    Returns:
      One `WARN` finding per stale or missing group doc.
    """
    findings: list[dict] = []
    for group in sorted(dictionary):
      blocks = scanned.get(group) or []
      # guard: no blocks in code — nothing to be stale against
      if not blocks:
        continue
      doc_rel = layout.doc_rel(group)
      # waiver: planner's protected hash reader reused — one frontmatter notation across the engine
      stored = _domains.DomainPlanner._stored_hash(self._repo / doc_rel)
      digest = _domains.DomainPlanner.group_hash(blocks)
      # guard: doc current — no finding
      if stored == digest:
        continue
      state = "missing" if stored is None else "stale"
      findings.append(_finding(
        check    = self.CHECK_HASH_STALE,
        severity = SEV_WARN,
        message  = f"group '{group}' doc is {state} (run /wiki.domain-sync or wait for the routine)",
        node     = doc_rel,
      ))
    return findings

  # ── check: domain-routine-mismatch ────────────────────────────────────────

  def _check_routines(self, routines: list[str]) -> list[dict]:
    """
    Report missing domain routines when the daemon is enabled.

    Args:
      routines: Names of the domain routines currently registered.

    Returns:
      One `WARN` finding per missing routine; empty when the daemon is off
      (a daemon-less repo legitimately runs `/wiki.domain-sync` by hand).
    """
    # guard: no daemon — routines are not expected
    if not self._is_daemon_enabled():
      return []
    return [
      _finding(
        check    = self.CHECK_ROUTINE_MISMATCH,
        severity = SEV_WARN,
        message  = f"wiki.domains configured but routine '{name}' is not registered (re-run /wiki.install)",
      )
      for name in _DOMAIN_ROUTINES
      if name not in routines
    ]

  # ── helpers ───────────────────────────────────────────────────────────────

  def _registered_domain_routines(self) -> list[str]:
    """
    List which of the domain routines the settings register.

    Returns:
      The registered domain-routine names, in canonical order.
    """
    settings = self._read_settings()
    routines = settings.get(_ROUTINES_KEY) or {}
    return [ name for name in _DOMAIN_ROUTINES if name in routines ]

  def _is_daemon_enabled(self) -> bool:
    """
    Report whether the background daemon is enabled for this repo.

    Returns:
      True when `daemon.enabled` is true in the settings; False otherwise.
    """
    daemon = self._read_settings().get(_DAEMON_KEY) or {}
    return bool(daemon.get(_DAEMON_ENABLED_KEY))

  def _read_settings(self) -> dict:
    """
    Read the repo's settings file as a dict.

    Returns:
      Parsed settings, or an empty dict when the file is absent or invalid.
    """
    settings_file = self._repo / _SETTINGS_PATH
    # guard: settings file does not exist
    if not settings_file.is_file():
      return {}
    try:
      with settings_file.open(encoding = _ENCODING) as fh:
        return json.load(fh)
    except (OSError, json.JSONDecodeError):
      # guard: unreadable or malformed settings — treat as empty
      return {}
