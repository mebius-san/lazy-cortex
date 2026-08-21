"""
Daemon-free relink planning for lazycortex-wiki.

`RelinkPlanner` computes which scope nodes a `/wiki.relink` run must
reclassify, re-link, or drop, by comparing the current working tree
against the `wiki_synced_sha` anchor stored in the scope's topics.md
frontmatter.  It selects one of three modes:

- `initial` — no anchor (or no index file): the whole scope.
- `incremental` — anchor is a reachable ancestor of HEAD: the `git diff`
  delta restricted to the scope's `paths` globs.
- `anchor-lost` — anchor is unreachable or not an ancestor: a content
  comparison of every node's current `source_hash` against its stored
  `wiki_src_hash` (the git-independent backstop).

All git access goes through `subprocess` against the repo root — no
GitPython, per the project tech conventions.  Node hashing reuses the
`source_hash` / `stored_src_hash` properties from `nodes.py`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import subprocess
from pathlib import Path

import nodes as _nodes
import scope as _scope

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ────────────────────────────────────────────────────────────────────────────
class RelinkPlanner:
  """
  Plan a daemon-free relink pass over one wiki scope.

  Determines which scope nodes must be reclassified, re-linked, or dropped, by
  comparing the current working tree against the scope's last synced anchor.

  Guarantees:
    - Planning is read-only: a planning run never writes to the repository, to the
      scope's nodes, or to the scope's topic index.

  Attributes:
    MODE_INITIAL: Plan mode used when no anchor exists yet, covering the whole scope.
    MODE_INCREMENTAL: Plan mode used when the anchor is a reachable ancestor of HEAD.
    MODE_ANCHOR_LOST: Plan mode used when the anchor is unreachable and content
      hashes decide the plan instead.
  """

  # Contract:
  # Planning is read-only: a planning run NEVER writes to the repository, to the
  # scope's nodes, or to the scope's topic index.

  # Plan modes.
  MODE_INITIAL     = "initial"
  MODE_INCREMENTAL = "incremental"
  MODE_ANCHOR_LOST = "anchor-lost"

  # Plan-dict keys.
  _K_MODE       = "mode"
  _K_SYNCED_SHA = "synced_sha"
  _K_CLASSIFY   = "classify"
  _K_LINK       = "link"
  _K_DROP       = "drop"

  # Anchor frontmatter key on topics.md.
  _KEY_WIKI_SYNCED_SHA = "wiki_synced_sha"

  # Config key carrying the topics-index path.
  _CFG_TOPICS_INDEX = "topics_index"

  # File encoding.
  _ENCODING = "utf-8"

  # git porcelain status codes from `git diff --name-status`.
  _STATUS_DELETE = "D"
  _STATUS_ADD    = "A"
  # Rename / copy status entries start with this letter and carry old+new paths.
  _STATUS_RENAME_PREFIX = "R"
  # A rename row has at least status + old-path + new-path columns.
  _RENAME_COLS = 3

  def __init__(self, *, repo: Path, scope_id: str, cfg: dict) -> None:
    """
    Initialise the planner for one scope.

    Args:
      repo: Absolute path to the repository root.
      scope_id: Scope identifier as configured in lazy.settings.json.
      cfg: Scope-config dict (the value side of a `wiki.scopes` entry).
    """
    self._repo = Path(repo).resolve()
    self._scope_id = scope_id
    self._cfg = cfg
    self._resolver = _scope.ScopeResolver(repo = self._repo)

  # ── public ────────────────────────────────────────────────────────────────

  def plan(self) -> dict:
    """
    Compute the relink plan for the scope.

    Guarantees:
      - Every node path in the returned plan is absolute and every plan list is sorted,
        so the same working tree always yields the same plan.
      - In `incremental` and `anchor-lost` mode a node whose curated text has not moved
        on is never planned, so a pass over a scope with no operator edits since the
        last one yields nothing to classify and nothing to link.

    Returns:
      Dict shaped `{"mode": ..., "synced_sha": <sha-or-None>,
      "classify": [<abs paths>], "link": [<abs paths>], "drop": [<abs paths>]}`.
      The `classify` and `link` lists hold absolute node-path strings; `drop`
      holds absolute paths of nodes deleted since the anchor.  Lists are sorted.
    """

    # Contract:
    # Every node path in the returned plan is absolute and every plan list is
    # sorted, so the same working tree ALWAYS yields the same plan.

    # Contract:
    # In `incremental` and `anchor-lost` mode a node whose curated text has not
    # moved on is NEVER planned, so a pass over a scope with no operator edits
    # since the last one yields nothing to classify and nothing to link.

    # Domain(wiki.graph):
    # # Where a relink pass picks up from
    # A scope remembers the point in the repository's history at which its nodes were last brought up to
    # date, and every later pass owes only the work that accumulated past that mark. Three situations tell
    # the pass what it owes. With no mark recorded, nothing has ever been curated and the whole scope is
    # owed. With a mark that still stands in the history, only the material that moved since it is owed.
    # With a mark the history no longer holds — a rewritten or discarded past — the history says nothing
    # at all, and each node is judged instead by its own text against the text it was curated from. The
    # mark is kept beside the scope's topic index, so the scope carries its own bearing rather than
    # depending on any record kept elsewhere.

    # read the mark the scope was last brought up to date at
    synced_sha = self._read_synced_sha()

    # guard: no anchor or no index file → full initial pass
    if synced_sha is None:
      return self._plan_initial(synced_sha)

    # guard: anchor unreachable / not an ancestor → content-hash backstop
    if not self._anchor_reachable(synced_sha):
      return self._plan_anchor_lost(synced_sha)

    # anchor is usable — plan from the git delta since it
    return self._plan_incremental(synced_sha)

  # ── mode builders ───────────────────────────────────────────────────────────

  def _plan_initial(self, synced_sha: str | None) -> dict:
    """
    Build the `initial` plan — every node classified and linked, nothing dropped.

    Args:
      synced_sha: Anchor value (always `None` in this mode); echoed back.

    Returns:
      The plan dict.
    """
    nodes = [ str(p) for p in self._resolver.iter_nodes(self._cfg) ]
    return {
      self._K_MODE:       self.MODE_INITIAL,
      self._K_SYNCED_SHA: synced_sha,
      self._K_CLASSIFY:   sorted(nodes),
      self._K_LINK:       sorted(nodes),
      self._K_DROP:       [],
    }

  def _plan_anchor_lost(self, synced_sha: str) -> dict:
    """
    Build the `anchor-lost` plan via content comparison of each node's hash.

    Each scope node whose current `source_hash` differs from its stored
    `wiki_src_hash` (or that has no stored hash) is reclassified and re-linked;
    nothing is dropped (git cannot tell us what was deleted without the anchor).

    Guarantees:
      - An `anchor-lost` plan never drops a node; its empty drop list is not proof that
        no node left the scope.

    Args:
      synced_sha: The unreachable anchor value; echoed back for diagnosis.

    Returns:
      The plan dict.
    """

    # Contract:
    # An `anchor-lost` plan NEVER drops a node; callers MUST NOT read its empty
    # drop list as proof that no node left the scope.

    # Domain(wiki.graph):
    # # What a lost history hides
    # A node that has left the wiki leaves nothing behind to examine: its absence shows only in the record
    # of what the repository did, never in the material that survives. A pass that has lost its bearing in
    # that record can therefore still recognise every node whose text has moved on from the text it was
    # curated from, and cannot recognise a single departure. Such a pass re-curates and never removes,
    # leaving the links that name a departed node to be repaired once the history is legible again. A node
    # that was never curated at all counts as moved on, since there is no curated text to hold it against.

    # collect the nodes whose authored text no longer matches what was curated
    changed: list[str] = []
    for node_path in self._resolver.iter_nodes(self._cfg):
      node = _nodes.node_for(node_path)
      # guard: unrecognised file type — skip
      if node is None:
        continue
      stored = node.stored_src_hash
      # never curated (no stored hash) or content drifted — recurate
      if stored is None or stored != node.source_hash:
        changed.append(str(node_path))
    changed.sort()
    return {
      self._K_MODE:       self.MODE_ANCHOR_LOST,
      self._K_SYNCED_SHA: synced_sha,
      self._K_CLASSIFY:   changed,
      self._K_LINK:       changed,
      self._K_DROP:       [],
    }

  def _plan_incremental(self, synced_sha: str) -> dict:
    """
    Build the `incremental` plan from the `git diff <sha>..HEAD` delta.

    Added/modified paths that resolve into this scope and exist on disk are
    classified and re-linked; deleted paths that resolved into the scope are
    dropped.  Neighbour expansion is the skill's concern — `link` is exactly
    the added/modified set here.

    Args:
      synced_sha: The reachable anchor commit.

    Returns:
      The plan dict.
    """
    classify: list[str] = []
    drop: list[str] = []

    # split the git delta into nodes to re-curate and nodes that left the scope
    for status, rel in self._diff_name_status(synced_sha):
      abs_path = (self._repo / rel).resolve()
      if status == self._STATUS_DELETE:
        # A deleted file: include only if it resolved into this scope by path.
        if self._resolves_into_scope(rel):
          drop.append(str(abs_path))
        continue
      # Added / modified: must resolve into this scope AND still exist on disk.
      if self._resolves_into_scope(rel) and abs_path.is_file():
        node = _nodes.node_for(abs_path)
        # guard: unrecognised file type — skip
        if node is None:
          continue
        stored = node.stored_src_hash
        # guard: operator content unchanged since last curation — only managed
        # regions moved (e.g. this relink's own commit). Skip so a re-run with no
        # real edits converges to an empty plan (idempotent); same content-hash
        # backstop the anchor-lost mode uses.
        if stored is not None and stored == node.source_hash:
          continue
        classify.append(str(abs_path))

    # git orders the delta by its own rules — sort so the plan is reproducible
    classify.sort()
    drop.sort()
    return {
      self._K_MODE:       self.MODE_INCREMENTAL,
      self._K_SYNCED_SHA: synced_sha,
      self._K_CLASSIFY:   classify,
      self._K_LINK:       list(classify),
      self._K_DROP:       drop,
    }

  # ── git + scope helpers ───────────────────────────────────────────────────

  def _read_synced_sha(self) -> str | None:
    """
    Read `wiki_synced_sha` from the scope's topics.md frontmatter.

    Returns:
      The anchor value, or `None` when the index file or key is absent.
    """
    raw = self._cfg.get(self._CFG_TOPICS_INDEX, "")
    # guard: no topics index configured — treat as no anchor
    if not raw:
      return None
    index_path = (self._repo / raw).resolve()
    # guard: index file does not exist yet — no anchor
    if not index_path.is_file():
      return None
    text = index_path.read_text(encoding = self._ENCODING)
    return _nodes.get_scalar_field(text, self._KEY_WIKI_SYNCED_SHA)

  def _anchor_reachable(self, sha: str) -> bool:
    """
    Return True when `sha` exists as a commit AND is an ancestor of HEAD.

    Uses `git cat-file -e <sha>^{commit}` (existence) and
    `git merge-base --is-ancestor <sha> HEAD` (reachability).  Either check
    failing — or git being absent — marks the anchor lost.

    Args:
      sha: The candidate anchor commit SHA.

    Returns:
      True when the anchor is a usable base for `git diff`, False otherwise.
    """
    exists = self._git_ok([ "cat-file", "-e", f"{sha}^{{commit}}" ])
    # guard: commit object is gone (gc / shallow / rewritten history)
    if not exists:
      return False
    return self._git_ok([ "merge-base", "--is-ancestor", sha, "HEAD" ])

  def _diff_name_status(self, sha: str) -> list[tuple[str, str]]:
    """
    Return `(status, rel_path)` pairs from `git diff --name-status <sha>..HEAD`.

    The full repo delta is returned unfiltered; scope membership is decided
    afterwards by `_resolves_into_scope`, which applies the project's own
    glob semantics rather than git's pathspec matcher (git treats a `**`
    pathspec literally unless `:(glob)` magic is used, so passing the scope
    globs to git would silently drop changes).  Rename entries (`R…`) are
    split into their old (deleted) and new (added) paths so both sides are seen.

    Args:
      sha: The anchor commit to diff against HEAD.

    Returns:
      List of `(status_letter, repo-relative-posix-path)` tuples.
    """
    cmd = [ "git", "-C", str(self._repo), "diff", "--name-status", f"{sha}..HEAD" ]
    proc = subprocess.run(cmd, capture_output = True, text = True, check = False)
    # guard: git failed — yield no delta rather than crashing the plan
    if proc.returncode != 0:
      return []

    # unpack the porcelain into (status, path) pairs the planner can consume
    out: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
      # guard: skip blank lines
      if not line.strip():
        continue
      parts = line.split("\t")
      status = parts[0]
      # Rename / copy: `R100\told\tnew` — old path deleted, new path added.
      if status.startswith(self._STATUS_RENAME_PREFIX) and len(parts) >= self._RENAME_COLS:
        out.append((self._STATUS_DELETE, parts[1]))
        out.append((self._STATUS_ADD, parts[2]))
        continue
      # guard: malformed line without a path column
      if len(parts) < 2:
        continue
      out.append((status[0], parts[1]))
    return out

  def _resolves_into_scope(self, rel_path: str) -> bool:
    """
    Return True when `rel_path` resolves into THIS scope.

    Uses `ScopeResolver.resolve_scope_by_path` against the repo-relative path
    and checks the resulting scope id equals this planner's scope id.  A path
    that matches a different scope (or none) is excluded.

    Args:
      rel_path: Repo-relative POSIX path string.

    Returns:
      True when the path belongs to this scope, False otherwise.
    """

    # Domain(wiki.scope):
    # # One document belongs to one scope
    # Scopes do not share documents: a document resolves into at most one of them, so the work a scope owes
    # covers exactly the documents resolving into it and nothing that resolves elsewhere or nowhere at all.
    # This bounds a pass from both ends — an edit to material outside the scope is no work for it, and a
    # document that vanished counts as a departure from the wiki only when the place it vanished from was
    # the scope's own.

    # a path belongs here only when it resolves into this very scope
    result = self._resolver.resolve_scope_by_path(rel_path)
    # guard: path matches no scope at all
    if result is None:
      return False
    matched_id, _ = result
    return matched_id == self._scope_id

  def _git_ok(self, args: list[str]) -> bool:
    """
    Run a quiet `git` command in the repo and report whether it exited zero.

    Args:
      args: Git arguments (without the leading `git` / `-C <repo>`).

    Returns:
      True on a zero exit, False on any non-zero exit or when git is absent.
    """
    cmd = [ "git", "-C", str(self._repo), *args ]
    try:
      proc = subprocess.run(cmd, capture_output = True, text = True, check = False)
    except OSError:
      # guard: git binary not found / not executable
      return False
    return proc.returncode == 0
