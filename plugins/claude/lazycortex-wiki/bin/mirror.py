"""
Mirror-scope engine for lazycortex-wiki.

Keeps a local markdown mirror of a foreign git repository inside the consumer
vault.  The clone update is delegated to `lazycortex-core`'s `remote-mirror`
primitive (`mode: "plan"`, dispatched per the inter-plugin boundary
contract's § 1c CLI-subprocess pattern); the sync copies every `.md` file
under the scope's `mirror.source_paths` globs (minus `mirror.exclude`) to
`<mirror_path>/<source-rel>`, replacing the body byte-for-byte from the
source while preserving the consumer-owned wiki layer: the wiki frontmatter
keys, the operator pin keys, and the protected `# See also` section.  Files
that disappeared from the source are removed from the mirror; the standard
prune routine drops dangling See-also links.

Cross-plugin Python import is forbidden (per the inter-plugin boundary contract),
so all primitives used here are imported from within this plugin's own `bin/`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import axes as _axes  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import nodes as _nodes  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scope as _scope  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from markers import Markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from textfile import TextFile  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Scope-config keys of the nested `mirror` block.
CFG_MIRROR       = "mirror"
CFG_URL          = "url"
CFG_BRANCH       = "branch"
CFG_SOURCE_PATHS = "source_paths"
CFG_EXCLUDE      = "exclude"
CFG_MIRROR_PATH  = "mirror_path"

# Report dict keys shared with the CLI and the tests.
K_SCOPE     = "scope"
K_SYNCED    = "synced"
K_UPDATED   = "updated"
K_REMOVED   = "removed"
K_UNCHANGED = "unchanged"
K_ERRORS    = "errors"

# Keys of one `errors` entry: the repo-relative mirror path of the file left out, and why.
K_ERROR_PATH   = "path"
K_ERROR_REASON = "reason"

# Runtime directory (repo-relative) holding one clone per mirror scope.
RUNTIME_MIRRORS_REL = ".runtime/lazy-wiki/mirrors"

# Only markdown is mirrored — never any other source content.
_MD_SUFFIX = ".md"

# File encoding used for every read/write in this module.
_ENCODING = "utf-8"

# Codec error handler that turns a byte that is not valid text into a replacement mark instead of failing.
_DECODE_LOSSY = "replace"

# Consumer-owned scalar frontmatter keys that survive a sync.
_PRESERVED_SCALAR_KEYS = ( "wiki_summary", "wiki_src_hash" )

# Consumer-owned sequence frontmatter keys that survive a sync — the curator's
# connectors block plus the four operator pin keys.
_PRESERVED_SEQ_KEYS = (
  "wiki_connectors",
  "wiki_pinned_topics",
  "wiki_unrelated_topics",
  "wiki_pinned_links",
  "wiki_unrelated_links",
)

# Prefix of the wiki-owned subset of `tags:` that survives a sync.
_WIKI_TAG_PREFIX = "wiki/"

# Frontmatter key carrying the tag list.
_KEY_TAGS = "tags"

# `remote-mirror` request `mode` this module ever sends — it always classifies, never writes;
# `fetch()` uses the primitive purely to update the clone and discards the classification —
# wiki's own `plan()`/`sync()` classify and apply through `find_all_source_files()` and `merge()`.
_MODE_PLAN = "plan"

# `remote-mirror` response key this module reads — duplicated from lazycortex-core's
# remote_mirror.py closed vocabulary because cross-plugin imports are forbidden (module docstring).
_KEY_ERROR = "error"

# Directory whose presence marks a git working copy.
_GIT_DIR = ".git"

# Separator of a `git ls-files -z` listing, which prints every path as written, never quoted.
_NUL = "\0"


def _run_remote_mirror(repo: Path, payload: dict) -> dict:
  """
  Invoke `lazycortex-core remote-mirror` with `payload` on stdin and parse its JSON response.

  Args:
    repo: Repository root the mirror scope belongs to.
    payload: Request body per the `remote-mirror` contract (`url`, `branch`, `cache_dir`,
      `include`, `exclude`, `dest`, `mode`).

  Returns:
    Parsed JSON response — `{"fetched_sha", "plan", "applied"}` on success, or `{"error"}`
    when the request could not be completed (an invalid field, a fetch failure, or an
    underlying git/filesystem error).

  Raises:
    RuntimeError: When the `lazycortex-core` CLI cannot be resolved.
    OSError: When the resolved binary cannot be executed.
    json.JSONDecodeError: When the CLI's stdout is not valid JSON (an unexpected crash).
    UnicodeDecodeError: When the CLI's stdout is not valid UTF-8 text.
  """
  # the CLI always prints a JSON body — {"error": ...} on failure, the response shape otherwise
  return json.loads(subprocess.run(
    [ sys.executable, str(_axes.resolve_core_cli(repo)), "remote-mirror" ],
    input = json.dumps(payload).encode(_ENCODING), capture_output = True, check = False,
  ).stdout)


# ----------------------------------------------------------------------------------------
class MirrorSourceError(Exception):
  """
  Failure to list the files of a mirror scope's source clone.

  Raised when the clone is absent or git cannot list its tracked files; the message names the scope and the
  reason. It is never raised for a source that simply holds no matching document, nor for a source document whose
  name is not valid UTF-8, which the plan reports among its errors instead.
  """


# ----------------------------------------------------------------------------------------
class MirrorSync:
  """
  Fetch-and-merge engine for one scope's `mirror` block.

  Owns the runtime clone of the source repository and the deterministic merge
  that lands source markdown in the vault without losing the consumer-owned
  wiki layer.  `fetch` updates the clone, `plan` classifies every file
  without writing, and `sync` applies the plan.  Git commits are the
  caller's business.

  Guarantees:
    - Running `sync` twice against an unchanged source produces zero writes
      on the second run (every file classifies as unchanged).
    - A fetch failure never touches the mirror tree.
    - A source that cannot be listed is reported as `MirrorSourceError`, never read as a source that holds no
      documents.
  """

  def __init__(self, *, repo: Path | str, scope_id: str, cfg: dict) -> None:
    """
    Initialise the engine for one scope of one repository.

    Args:
      repo: Absolute path to the consumer repository root.
      scope_id: Scope identifier as declared in `lazy.settings.json[wiki.scopes]`.
      cfg: The scope-config dict whose optional `mirror` block drives the sync.
    """
    self._repo = Path(repo).resolve()
    self._scope_id = scope_id
    self._mirror_cfg: dict = cfg.get(CFG_MIRROR) or {}
    self._matcher = _scope.GlobMatcher()

    # the source documents the last listing left out for a name that is not UTF-8, as the file system spells them
    self._skipped_sources: list[str] = []

  @property
  def is_configured(self) -> bool:
    """
    True when the scope carries a usable `mirror` block (`url` + `mirror_path`).
    """
    return bool(self._mirror_cfg.get(CFG_URL)) and bool(self._mirror_cfg.get(CFG_MIRROR_PATH))

  @property
  def clone_dir(self) -> Path:
    """
    Absolute path of this scope's runtime clone directory.
    """
    return self._repo / RUNTIME_MIRRORS_REL / self._scope_id

  @property
  def mirror_path(self) -> str:
    """
    Repo-relative mirror directory from the `mirror` block, or empty string.
    """
    return str(self._mirror_cfg.get(CFG_MIRROR_PATH) or "")

  def fetch(self) -> str | None:
    """
    Clone the source on first use, or reset the existing clone onto its current head.

    Guarantees:
      - Only ever requests the primitive's classify-only mode (`mode: "plan"`); never triggers its
        `mode: "sync"`, so the mirror tree's consumer-owned wiki layer is never overwritten by this call.
      - Never raises: an unresolvable `lazycortex-core` CLI or a malformed response comes back
        through the same error-string contract as an ordinary fetch failure.

    Notes:
      - A failure never touches the mirror tree; the underlying clone may be
        left mid-update when its fetch step succeeded and its reset step
        then failed. The caller surfaces the returned message and exits
        non-zero.

    Returns:
      `None` on success, or a one-line error message on failure.
    """
    # guard: no mirror block — nothing to fetch
    if not self.is_configured:
      return f"scope '{self._scope_id}' has no mirror block configured"

    # Decision: reuse remote-mirror only for the clone-or-fast-forward step, not its classification.
    # find_all_source_files()/plan() classify independently against whatever clone is on disk, so they keep
    # working when called without a prior fetch() in the same process (doctor.py relies on this to
    # audit an already-fetched clone).

    # Contract:
    # fetch() MUST always dispatch `lazycortex-core remote-mirror` with mode: "plan", NEVER
    # mode: "sync" — even though it passes the real mirror directory as dest. The primitive's
    # mode: "sync" copies source bytes verbatim over dest and deletes files the source no
    # longer names, with no merge logic at all; that would destroy every mirror file's
    # consumer-owned wiki layer (frontmatter keys, operator pins, the protected See-also
    # section) that merge() is responsible for preserving. fetch() only ever classifies;
    # sync() is the sole writer, and it always writes through merge(), never through the
    # primitive's own sync.

    # build the remote-mirror request body from this scope's mirror block
    payload = {
      "url":       str(self._mirror_cfg.get(CFG_URL) or ""),
      "branch":    str(self._mirror_cfg.get(CFG_BRANCH) or "") or None,
      "cache_dir": str(self.clone_dir),
      "dest":      str(self._repo / self.mirror_path),
      "include":   list(self._mirror_cfg.get(CFG_SOURCE_PATHS) or []),
      "exclude":   list(self._mirror_cfg.get(CFG_EXCLUDE) or []),
      "mode":      _MODE_PLAN,
    }

    # Contract:
    # fetch() MUST NOT let a caught exception propagate. An unresolvable `lazycortex-core`
    # CLI or a malformed response converts to the same one-line error string this method
    # returns for an ordinary fetch failure, so callers can rely on fetch() never raising
    # for these classes.

    # dispatch the request — every failure path leaves the mirror tree untouched (plan mode never writes)
    try:
      result = _run_remote_mirror(self._repo, payload)
    # guard: the CLI couldn't be resolved, run, or crashed without emitting JSON — same string contract
    except (RuntimeError, OSError, ValueError) as error:
      return f"mirror fetch failed for scope '{self._scope_id}': {error}"

    # guard: the request failed — fetch, an invalid field, or an underlying git/filesystem error
    if _KEY_ERROR in result:
      return f"mirror fetch failed for scope '{self._scope_id}': {result[_KEY_ERROR]}"

    # no error field — the clone is fetched and ready for plan()/sync()
    return None

  def plan(self) -> dict:
    """
    Classify every mirror file against the current clone, without writing.

    Guarantees:
      - Classification leaves the mirror tree, the clone, and the rest of the
        repository untouched.
      - A file that cannot be read or decoded, on the source side or on the mirror side, is left out of every
        bucket and recorded under `errors`; it is never listed as `removed`.
      - A source document whose name is not valid UTF-8 is treated the same way: it is left out of every bucket, its
        mirror twin is never listed as `removed` because the source still offers the document, and it is recorded
        under `errors` with a path spelled so that it can be written, the odd bytes shown as escapes, and a reason.
      - A source that cannot be listed raises `MirrorSourceError`, so a failed listing is never read as every
        document having been removed upstream.

    Returns:
      Dict shaped `{"scope": <id>, "synced": [<rel>...], "updated": [<rel>...],
      "removed": [<rel>...], "unchanged": [<rel>...], "errors": [{"path", "reason"}...]}` — each of the four
      path lists holds repo-relative POSIX paths under the scope's `mirror_path`, sorted. `errors` lists the files
      that could not be read or decoded on either side or whose source name is not valid UTF-8, sorted by path, each
      with its `path` and `reason`.

    Raises:
      MirrorSourceError: When the source clone is absent or its files cannot be listed.
    """

    # Contract:
    # plan() MUST NOT write anything — neither the mirror tree, nor the clone, nor any
    # other part of the repository. Callers rely on classifying an already-fetched clone
    # without mutating the vault; sync() is the sole writer.

    # Contract:
    # A file that cannot be read or decoded, on either the source side or the mirror side, is
    # left out of the synced, updated, removed and unchanged buckets and recorded under the
    # `errors` key as an entry with its `path` and its `reason`, sorted by path. Such a file is
    # NEVER listed as removed. A source document whose name is not valid UTF-8 is treated the same way:
    # it is left out of the four buckets, its mirror twin is NEVER listed as removed because the source
    # still offers the document, and it is recorded under `errors` with a path spelled so that it can be
    # written, the odd bytes shown as escapes, and a reason.

    # Contract:
    # When the source cannot be listed, plan() MUST raise `MirrorSourceError`; callers never
    # receive a plan that reads a failed listing as every document having been removed upstream.

    # the four classification buckets, plus the mirror paths the source still provides
    synced: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    errors: list[dict[str, str]] = []
    expected: set[str] = set()

    # Domain(wiki.surfaces):
    # # How a mirror follows its source
    # A mirror is a projection of the source at one moment, not a place where documents are authored.
    # Every refresh compares the two sides and sorts each document into one of four outcomes: newly
    # appeared, changed, unchanged, or gone. A document the source no longer offers leaves the mirror
    # as well, and links that pointed at it are cleaned up by the ordinary link upkeep. A document that
    # cannot be read or decoded, on the source side or the mirror side, belongs to none of the four: it
    # is set aside, neither refreshed nor removed, and reported, while the rest of the mirror is
    # refreshed as usual. Absence counts as evidence only when the source could be listed at all: a
    # source that cannot be listed says nothing about which documents it still offers, so such a
    # refresh does not happen and nothing is removed on its account. A refresh against an unchanged
    # source writes nothing at all, so the mirror can be refreshed as often as wanted without churning
    # the vault.

    # classify every current source file against its mirror twin
    for source_rel in self.find_all_source_files():
      mirror_rel = f"{self.mirror_path}/{source_rel}"
      expected.add(mirror_rel)
      mirror_abs = self._repo / mirror_rel

      # one file that cannot be read or decoded, on either side, is left out of every bucket and recorded;
      # it stays among the expected paths above, so it is never taken for a document the source dropped
      try:
        source_text = (self.clone_dir / source_rel).read_text(encoding = _ENCODING)
        existing = mirror_abs.read_text(encoding = _ENCODING) if mirror_abs.is_file() else None
      except (OSError, UnicodeError) as error:
        errors.append({ K_ERROR_PATH: mirror_rel, K_ERROR_REASON: f"{type(error).__name__}: {error}" })
        continue

      # no mirror twin yet — the file is new to the mirror and lands in the synced bucket
      if existing is None:
        synced.append(mirror_rel)
      elif self.merge(source_text, existing) == existing:
        unchanged.append(mirror_rel)
      else:
        updated.append(mirror_rel)

    # a source document left out for its name is still offered by the source: its mirror twin stays among the
    # expected paths, so it is never removed, and the document is recorded as one that could not be mirrored,
    # under a spelling that can be written
    for source_rel in self._skipped_sources:
      mirror_rel = f"{self.mirror_path}/{source_rel}"
      expected.add(mirror_rel)
      # waiver: `backslashreplace` is the stdlib codec error-handler name that spells an unencodable byte out
      errors.append({
        K_ERROR_PATH:   mirror_rel.encode(_ENCODING, errors = "backslashreplace").decode(_ENCODING),
        K_ERROR_REASON: "the source name is not valid UTF-8",
      })

    # anything in the mirror tree the source no longer provides is removed
    removed = sorted(set(self._mirror_files()) - expected)

    # the four lists and the files left out are the whole plan — sync applies the lists verbatim
    return {
      K_SCOPE:     self._scope_id,
      K_SYNCED:    sorted(synced),
      K_UPDATED:   sorted(updated),
      K_REMOVED:   removed,
      K_UNCHANGED: sorted(unchanged),
      K_ERRORS:    sorted(errors, key = lambda entry: entry[K_ERROR_PATH]),
    }

  def sync(self) -> dict:
    """
    Apply the current plan to the mirror tree.

    New files land as verbatim source copies, changed files are merged so the
    consumer wiki layer survives, and files gone from the source are deleted.

    Guarantees:
      - A sync against a source unchanged since the previous one writes nothing
        at all, so repeated syncs never churn the vault.
      - A source that cannot be listed raises `MirrorSourceError` before anything is written or deleted.
      - A file listed under `errors` is neither written nor deleted, and the other files still sync.

    Returns:
      The applied plan dict (same shape as `plan`, including its `errors` list of files left untouched).

    Raises:
      MirrorSourceError: When the source clone is absent or its files cannot be listed.
    """

    # Contract:
    # A sync against a source that has not changed since the previous sync MUST write
    # nothing: every file classifies as unchanged, so a mirror can be refreshed as often
    # as wanted without producing a single modified file.

    # Contract:
    # When the source cannot be listed, sync() MUST raise `MirrorSourceError` before it writes or
    # deletes anything in the mirror tree.

    # Contract:
    # A file the plan lists under `errors` is NEVER written and NEVER deleted by sync(); the other
    # files still sync.

    # the plan is recomputed here so the applied lists match the tree as it stands now
    report = self.plan()

    # new files carry the source bytes verbatim — the curator layers wiki state later
    for mirror_rel in report[K_SYNCED]:
      mirror_abs = self._repo / mirror_rel
      mirror_abs.parent.mkdir(parents = True, exist_ok = True)
      source_rel = mirror_rel[len(self.mirror_path) + 1:]
      TextFile(path = mirror_abs).write((self.clone_dir / source_rel).read_bytes().decode(_ENCODING))

    # changed files are merged so the consumer layer survives the body swap
    for mirror_rel in report[K_UPDATED]:
      mirror_abs = self._repo / mirror_rel
      source_rel = mirror_rel[len(self.mirror_path) + 1:]
      mirror_file = TextFile(path = mirror_abs)
      merged = self.merge(
        (self.clone_dir / source_rel).read_text(encoding = _ENCODING),
        mirror_file.read(),
      )
      mirror_file.write(merged)

    # files the source dropped disappear from the mirror; prune handles dangling links
    for mirror_rel in report[K_REMOVED]:
      (self._repo / mirror_rel).unlink(missing_ok = True)

    # the applied plan doubles as the caller's report
    return report

  def merge(self, source_text: str, existing_text: str) -> str:
    """
    Merge one source file with its existing mirror twin.

    The body comes byte-for-byte from the source (including any source
    frontmatter); the consumer-owned wiki layer of the existing mirror file
    is layered on top: the wiki scalar keys, the `wiki/*` subset of `tags`
    (the source's own non-`wiki/` tags survive), the connectors and operator
    pin sequences, and the protected `# See also` section.

    Guarantees:
      - The consumer-owned wiki layer of the existing mirror file survives the
        merge in full, including the protected `# See also` section.
      - Merging the same source against an already-merged result returns it
        byte-identical, so repeated syncs are stable.

    Args:
      source_text: Full text of the file in the source clone.
      existing_text: Full text of the current mirror file.

    Returns:
      The merged document text.
    """

    # Contract:
    # merge() MUST NEVER drop the consumer-owned wiki layer of the existing mirror file:
    # the wiki scalar keys, the `wiki/*` tags, the connector and operator pin sequences,
    # and the protected `# See also` section all survive the body swap. Everything else
    # belongs to the source and is replaced outright.

    # Contract:
    # Merging a source against a document that already merged that same source MUST
    # return it byte-identical, so a sync over an unchanged source classifies every file
    # as unchanged and writes nothing.

    # the source body is the base every consumer-owned region lands on top of
    # waiver: intentional reuse of the nodes module's frontmatter primitives (same plugin bin/)
    # pylint: disable=protected-access
    merged = source_text

    # Domain(wiki.surfaces):
    # # Who owns which part of a mirrored document
    # A mirrored document has two owners. The source owns the body and everything the source itself
    # declares about the document; every refresh replaces that part outright, so edits made to it
    # inside the vault do not survive. The vault owns the wiki layer laid on top: the one-line
    # summary, the recorded source fingerprint, the tags in the wiki's own namespace, the connector
    # list, the operator's pinned and unrelated topics and links, and the See-also section. That
    # layer is carried across every refresh, so curation done in the vault is never lost to an
    # update, while tags the source declares in namespaces of its own stay with the source.

    # consumer-owned scalar keys ride over from the existing mirror file
    for key in _PRESERVED_SCALAR_KEYS:
      value = _nodes._get_scalar_field(existing_text, key)
      if value is not None:
        merged = _nodes._set_scalar_field(merged, key, value)

    # the wiki/* tag subset is consumer state; the source keeps its own other tags
    wiki_tags = [
      tag for tag in _nodes._get_array_field(existing_text, _KEY_TAGS)
      if tag.startswith(_WIKI_TAG_PREFIX)
    ]
    if wiki_tags:
      non_wiki = [
        tag for tag in _nodes._get_array_field(merged, _KEY_TAGS)
        if not tag.startswith(_WIKI_TAG_PREFIX)
      ]
      merged = _nodes.set_tags_field(merged, non_wiki + wiki_tags)

    # connectors and operator pins are block sequences preserved wholesale
    for key in _PRESERVED_SEQ_KEYS:
      values = _nodes._get_array_field(existing_text, key)
      if values:
        merged = _nodes._set_block_seq_field(merged, key, values)

    # the protected See-also section re-lands at the canonical end-of-body spot
    inner = Markers().read_inner(existing_text)
    if inner is not None:
      merged = Markers().ensure_see_also(merged, inner)
    # pylint: enable=protected-access
    return merged

  def find_all_source_files(self) -> list[str]:
    """
    Enumerate the clone's markdown files under `source_paths` minus `exclude`.

    Only git-tracked files are considered, so the clone's own untracked noise
    never reaches the mirror.

    Guarantees:
      - Only markdown the source repository itself tracks is ever enumerated.
      - A clone that is absent, or that git cannot list, raises `MirrorSourceError`; an empty result means only
        that the source holds no matching document.
      - A source path name that is not valid UTF-8 never fails the listing: a document that would be mirrored but
        whose name cannot be written as UTF-8 text is reported on stderr and left out, and every other document
        is listed as usual. The names left out are remembered for the plan, which records them under `errors`, so
        the skip reaches the caller's exit code and the error ledger.

    Returns:
      Sorted list of clone-relative POSIX path strings; empty only when the source holds no matching document.

    Raises:
      MirrorSourceError: When the clone is absent, or git cannot be started or exits non-zero when listing its
        tracked files.
    """

    # Contract:
    # Only markdown that the source repository itself tracks in git is ever enumerated.
    # Untracked or ignored content in the clone NEVER reaches the mirror, whatever the
    # scope's include patterns say.

    # Contract:
    # A clone that is absent, or that git cannot list (git cannot be started or exits non-zero), MUST
    # raise `MirrorSourceError`. An empty list means only that the source holds no matching document,
    # so callers never read a failed listing as every document having been removed upstream.

    # Contract:
    # A source path name that is not valid UTF-8 NEVER fails the listing. A document that would be
    # mirrored but whose name cannot be written as UTF-8 text is reported on stderr and left out, and
    # every other document is listed, and so mirrored, as usual. The names left out are remembered for
    # the plan, which records them under `errors`, so the skip reaches the caller's exit code and the
    # error ledger.

    # guard: no clone on disk — the source cannot be listed, which is not the same as a source with no files
    if not (self.clone_dir / _GIT_DIR).is_dir():
      raise MirrorSourceError(f"scope '{self._scope_id}': no source clone at '{self.clone_dir}'")

    # the clone's tracked files, as git lists them, taken as bytes so the exit status alone tells whether the
    # listing succeeded
    try:
      proc = subprocess.run(
        [ "git", "ls-files", "-z" ], cwd = str(self.clone_dir), capture_output = True, check = False,
      )
    # a listing git cannot produce is a source that cannot be listed
    except OSError as error:
      raise MirrorSourceError(f"scope '{self._scope_id}': git could not list the source clone: {error}") from error

    # guard: listing failed — an unlisted source says nothing about which documents it still holds
    if proc.returncode != 0:
      raise MirrorSourceError(
        f"scope '{self._scope_id}': git could not list the source clone: "
        f"{proc.stderr.decode(_ENCODING, errors = _DECODE_LOSSY).strip() or proc.returncode}"
      )


    # Domain(wiki.scope):
    # # What a mirror takes from a foreign repository
    # A mirror scope republishes another repository's documents inside the vault so they can be read
    # and linked like local material. Only markdown is mirrored, and only documents the source
    # repository itself tracks — untracked noise in a working copy is never republished. The scope
    # narrows the set further: a document is mirrored when it sits under at least one of the scope's
    # include patterns and under none of its exclude patterns, and a scope that names no include
    # pattern takes everything the other two rules already allow.

    # only .md under an include glob and under no exclude glob is mirrored
    include = list(self._mirror_cfg.get(CFG_SOURCE_PATHS) or [])
    exclude = list(self._mirror_cfg.get(CFG_EXCLUDE) or [])
    result: list[str] = []
    self._skipped_sources = []
    for rel in os.fsdecode(proc.stdout).split(_NUL):
      # only markdown is mirrored
      if not rel.endswith(_MD_SUFFIX):
        continue

      # a document outside every source_paths glob is not mirrored
      if include and not any(self._matcher.match(rel, pat) for pat in include):
        continue

      # a document named by an exclude glob is not mirrored
      if any(self._matcher.match(rel, pat) for pat in exclude):
        continue

      # a document whose name is not UTF-8 cannot be written into the vault; it is reported and left out, and
      # the other documents are mirrored as usual
      try:
        rel.encode(_ENCODING)
      except UnicodeEncodeError:
        print(
          f"scope '{self._scope_id}': skipped a source document whose name is not UTF-8: {rel!r}",
          file = sys.stderr,
        )
        self._skipped_sources.append(rel)
        continue
      result.append(rel)
    return sorted(result)

  def to_source_remainder(self, text: str) -> str:
    """
    Reduce a document to the source-owned remainder for drift comparison.

    Strips everything the sync or the operator legitimately layers onto a
    mirror file — the wiki-managed regions and the operator pin keys — and
    normalises whitespace, so equal results mean the mirror body still
    matches the source.

    Guarantees:
      - Applying this to the mirror side and to the source side of the same
        document, when no source-owned edit was made in the vault, returns
        byte-identical text.

    Args:
      text: Full document text (mirror or source side).

    Returns:
      Normalised source-owned text.
    """

    # Contract:
    # Applying to_source_remainder() to the mirror side and to the source side of the same
    # document MUST return byte-identical text when no source-owned edit was made in the
    # vault. Callers rely on this equality as the sole signal that a mirror body has not
    # drifted from its source.

    # Domain(wiki.integrity):
    # # When a mirrored document counts as drifted
    # A mirrored document is judged against its source by remainder: everything the vault is allowed
    # to add — the wiki layer and the operator's pins — is stripped from both sides, and differences
    # in whitespace are ignored. What remains must match the source, because only the source may
    # author it. A remainder that differs means source-owned text was edited inside the vault; that
    # counts as drift and is reported, since the next refresh would silently discard the edit.

    # drop the consumer-owned layer so only source-owned text remains for comparison
    # waiver: intentional reuse of the nodes module's frontmatter primitives (same plugin bin/)
    # pylint: disable=protected-access
    out = text
    for key in _PRESERVED_SEQ_KEYS:
      out = _nodes._drop_key(out, key)
    result = _nodes._markdown_source_for_hash(out)
    # pylint: enable=protected-access
    return result

  def _mirror_files(self) -> list[str]:
    """
    Enumerate the markdown files currently under the mirror directory.

    Returns:
      Repo-relative POSIX path strings, unsorted; empty when the mirror
      directory does not exist.
    """
    mirror_abs = self._repo / self.mirror_path

    # guard: mirror directory not created yet
    if not mirror_abs.is_dir():
      return []

    # one walk collects every markdown file the mirror currently holds
    result: list[str] = []
    for base, _dirs, files in os.walk(str(mirror_abs)):
      for fname in files:
        # only markdown belongs to the mirror
        if fname.endswith(_MD_SUFFIX):
          result.append((Path(base) / fname).relative_to(self._repo).as_posix())
    return result
