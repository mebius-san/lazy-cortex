"""
Cross-plugin dispatch for lazycortex-wiki.

Implements the §1c CLI-subprocess contract from
The inter-plugin boundary contract — lazycortex-wiki reaches
lazycortex-core exclusively via its published CLI binary, never by
importing core Python modules.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import os
import subprocess
import sys
from pathlib import Path

import tags as _tags

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# lazycortex-wiki reaches lazycortex-core ONLY via its published CLI —
# no Python-import coupling, no filesystem-walk binary discovery beyond
# the $LAZYCORTEX_PLUGIN_DIRS contract.  See
# the inter-plugin boundary contract for the full pattern.

# ----------------------------------------------------------------------------------------
def _version_sort_key(name: str) -> tuple[int, ...]:
  """
  Build a numeric sort key for a plugin-cache version directory name.

  Args:
    name: Version directory name as it appears in the plugin cache.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(c for c in part if c.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


def _cached_sibling_root(name: str) -> Path | None:
  """
  Locate a sibling plugin's newest cached install next to this plugin's own cached install.

  A cached install lives at `<cache>/<registry>/<plugin>/<version>/`, so when this file runs from
  one, the cache root is four levels above `bin/` and every sibling's versions sit under it. A dev
  source tree has no version level above `bin/`, so the walk finds nothing there — the dev layout
  is served by the daemon's env export and each caller's own dev fallback.

  Args:
    name: Sibling plugin name, which is also its cache directory and CLI name.

  Returns:
    The sibling's highest cached version directory, or None outside a cached install or when no
    version of the sibling is cached.
  """
  own = Path(__file__).resolve()
  # guard: not a cached install — a dev checkout has no version directory above bin/
  if not own.parents[1].name.replace(".", "").isdigit():
    return None
  # the cache root sits four levels above bin/: cache/<registry>/<plugin>/<version>/bin
  try:
    cache = own.parents[4]
  except IndexError:
    return None
  versions = [
    version
    for registry in cache.iterdir() if (registry / name).is_dir()
    for version in (registry / name).iterdir()
    if version.is_dir() and version.name.replace(".", "").isdigit()
  ]
  return max(versions, key = lambda v: _version_sort_key(v.name)) if versions else None


class CoreDispatch:
  """
  Thin §1c bridge between lazycortex-wiki and lazycortex-core's CLI.

  Resolves the `lazycortex-core` binary at construction time and exposes a
  single dispatch-level operation to queue curator jobs.

  Guarantees:
    - `lazycortex-core` is reached only through its published CLI binary, never by importing a
      core Python module; the binary is located via `$LAZYCORTEX_PLUGIN_DIRS`, falling back to
      the newest cached `lazycortex-core` install next to this plugin's own cache entry when the
      environment names none.

  Attributes:
    EXPERT_NAME: Expert name as it appears in `lazy.settings.json[experts]`.
    EXPERT_DOMAIN_WRITER: Domain-spec writer expert name in `lazy.settings.json[experts]`.
    EXPERT_TAG_CURATOR: Tag-curator expert name in `lazy.settings.json[experts]`.
    KIND_CLASSIFY: Payload `kind` value requesting node classification.
    KIND_LINK: Payload `kind` value requesting node linking.
    KIND_DOMAIN_SPEC: Payload `kind` value requesting a domain-spec (re)generation.
    KIND_NORMALIZE_TAGS: Payload `kind` value requesting a surface's tag-value canon.
  """

  # Contract:
  # `lazycortex-core` is reached ONLY through its published CLI binary, NEVER by importing a core
  # Python module. The binary is located by walking `$LAZYCORTEX_PLUGIN_DIRS` first, falling back
  # to the newest cached `lazycortex-core` install next to this plugin's own cache entry when the
  # environment names none.

  # Expert name as it appears in `lazy.settings.json[experts]`.
  EXPERT_NAME = "wiki.curator"

  # Domain-spec writer expert name as it appears in `lazy.settings.json[experts]`.
  EXPERT_DOMAIN_WRITER = "wiki.domain-writer"

  # Tag-curator expert name as it appears in `lazy.settings.json[experts]`.
  EXPERT_TAG_CURATOR = "wiki.tag-curator"

  # Payload `kind` value requesting a domain-spec (re)generation.
  KIND_DOMAIN_SPEC = "domain-spec"

  # Payload `kind` value requesting one surface's tag-value canon.
  KIND_NORMALIZE_TAGS = "normalize-tags"

  # Job-dir filenames the tag-curator protocol names for its context and its result.
  _CONTEXT_COLLECTED_TAGS = "collected_tags.json"
  _RESULT_ALIAS_MAP       = "alias_map.json"

  # Subcommand forwarded to lazycortex-core.
  _CMD_DISPATCH = "dispatch-job"

  # Environment variable name core reads to locate the repo.
  _ENV_REPO_ROOT = "LAZY_REPO_ROOT"

  # Plugin-dirs env var set by the daemon for subprocess routines.
  _ENV_PLUGIN_DIRS = "LAZYCORTEX_PLUGIN_DIRS"

  # Path components used in binary resolution.
  _CORE_PLUGIN_NAME = "lazycortex-core"
  _BIN_SEGMENT      = "bin"

  # Valid kind values that the curator protocol recognises. Callers place one
  # of these as the payload's `kind` field; the payload is written verbatim to
  # `request.json` by core, so the curator reads `request.json["kind"]`.
  KIND_CLASSIFY = "classify"
  KIND_LINK     = "link"

  # Payload field naming the curation kind, which also scopes the dedup key.
  _PAYLOAD_KIND = "kind"

  # Payload field carrying the classify anchor, and the keys of its entries.
  _PAYLOAD_EXISTING_TAGS = "existing_tags"
  _ANCHOR_VALUE          = "value"
  _ANCHOR_COUNT          = "count"
  _ANCHOR_EXAMPLES       = "examples"

  def __init__(self) -> None:
    """
    Resolve the `lazycortex-core` CLI binary on construction.

    Raises:
      RuntimeError: When neither `$LAZYCORTEX_PLUGIN_DIRS` nor the
        plugin cache contains a usable `lazycortex-core` binary.
    """
    self._cli = self._resolve_core_cli()

  # ------------------------------------------------------------------
  def dispatch_curator(
    self,
    *,
    repo: Path,
    node_path: Path,
    payload: dict,
  ) -> dict:
    """
    Queue a `wiki.curator` job for one node via `dispatch-job`.

    Builds the full job bundle and forwards it to `lazycortex-core
    dispatch-job`.  Core owns the job-dir layout, config.json
    composition, READY ordering, and git_author/aspects/model
    resolution — none of those leak into this caller (§1c §3).

    The caller's `payload` is forwarded to `request.json`; the curation
    `kind` (`classify` / `link`) MUST be carried inside `payload["kind"]`
    by the caller so it reaches the curator's `request.json` — this
    method never injects it.  A `classify` payload's `existing_tags`
    anchor is the one field this method extends: the advisory tag
    dictionary's per-axis values are unioned into it, so a value that
    was canonised but is worn by no node today still anchors the
    curator.

    Guarantees:
      - The caller's `payload` reaches `request.json` unchanged except for a `classify` payload's
        `existing_tags` anchor, which gains the dictionary's values; no field is added, renamed, or
        removed beyond that.
      - The `dedup_key` combines the curation `kind` with the absolute node path, so repeated
        dispatches for the same kind and node collapse into one pending job while classify and
        link for the same node remain independent jobs.
      - A node lying outside the repository is refused before anything is queued.

    Args:
      repo: Absolute path to the repository root.
      node_path: Absolute or repo-relative path to the node being
        curated; the resolved-absolute form is combined with the
        curation `kind` to build the `dedup_key`, so repeated
        dispatches for the same (kind, node) collapse to one pending
        job while classify and link dispatches for the same node are
        kept distinct.
      payload: Caller-assembled curation payload dict (curation `kind`,
        node path, scope context, pins).

    Returns:
      Parsed JSON response from `dispatch-job`, typically
      `{"job_id": "<id>", "queue_path": "<abs-path>"}`.
    """

    # Contract:
    # The caller's `payload` reaches `request.json` unchanged apart from the `classify` anchor —
    # this method NEVER adds, renames, or removes any other payload field, so a curation `kind` the
    # caller omits is absent for the curator too.

    # Contract:
    # The `dedup_key` MUST combine the curation `kind` with the absolute node path, so repeated
    # dispatches for the same kind and node collapse into one pending job while classify and link
    # for the same node remain independent jobs.

    # Contract:
    # A node lying outside the repository is refused before anything is queued — no job bundle ever
    # reaches core carrying a source manifest the pump cannot resolve.

    # Domain(runtime.jobs):
    # # Collapsing repeated requests in the queue
    # A request for expert work carries a deduplication key: while an identical request is still waiting
    # in the queue, a repeat one is not created — the new ask joins the one already standing. The key is
    # built from the kind of work and the target it applies to, so different kinds of work on one target
    # stay independent requests. Were the kind of work left out of the key, an already-finished but not
    # yet collected request would swallow the request of another kind that it spawned itself. The target
    # is reduced to one canonical written form, otherwise the same target named two ways yields two keys
    # and two requests instead of one.

    # Resolve the path to its absolute form so relative/absolute callers
    # collapse to the same dedup_key. Prepend `kind` so classify and link
    # for the same node do not dedup against each other (a DONE-but-not-
    # CONSUMED classify-job would otherwise swallow the chained link
    # dispatch from its own tail).
    abs_node = node_path.resolve() if node_path.is_absolute() else (Path(repo) / node_path).resolve()
    kind = str(payload.get(self._PAYLOAD_KIND, ""))
    dedup_key = f"{kind}:{abs_node}"

    # the bundle names the node; the pump copies it when it claims the job, so the curator sees
    # the file as it stands then rather than as it stood when the dispatch was queued
    try:
      node_rel = abs_node.relative_to(Path(repo)).as_posix()
    except ValueError as err:
      # a node outside the repo has no manifest form: a bare basename would reach the pump and
      # fail the job at claim, so the dispatch is refused here where the caller can still see why
      raise RuntimeError(f"node {abs_node} lies outside the repository at {repo}") from err

    # the bundle core reads off stdin — layout, config.json and READY ordering stay core's
    bundle: dict = {
      "expert":    self.EXPERT_NAME,
      "payload":   self._merge_dictionary_anchor(repo, payload),
      "source":    [ node_rel ],
      "result":    [ "curation.json" ],
      "dedup_key": dedup_key,
    }
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

  # ------------------------------------------------------------------
  def dispatch_tag_curator(
    self,
    *,
    repo: Path,
    surface: str,
    payload: dict,
    collected_tags: dict,
  ) -> dict:
    """
    Queue a `wiki.tag-curator` job for one tag surface via `dispatch-job`.

    Forwards the caller's `payload` verbatim (core writes it to
    `request.json` unchanged) and stages the surface's tag census as the
    job's `context/collected_tags.json`, which no file on disk holds.

    Guarantees:
      - The caller's `payload` reaches `request.json` unchanged; no field is added, renamed, or
        removed here.
      - The `dedup_key` combines the normalize-tags kind with the surface id, so repeated
        dispatches for one surface collapse into one pending job while other surfaces stay
        independent.

    Args:
      repo: Absolute path to the repository root.
      surface: Tag-surface id the job canonises — a configured wiki scope id,
        or the reserved id of the generated domain-doc tree.
      payload: Caller-assembled request dict (`kind`, surface, dictionary path).
      collected_tags: The surface's tag census, staged as the job's
        `context/collected_tags.json`.

    Returns:
      Parsed JSON response from `dispatch-job`, typically
      `{"job_id": "<id>", "queue_path": "<abs-path>"}`.
    """

    # Contract:
    # The caller's `payload` reaches `request.json` unchanged — this method NEVER adds, renames, or
    # removes a payload field.

    # Contract:
    # The `dedup_key` MUST combine the normalize-tags kind with the surface id, so repeated
    # dispatches for one surface collapse into one pending job while other surfaces stay independent.

    # the census exists only in memory, so it rides as inline context rather than a path manifest
    bundle: dict = {
      "expert":         self.EXPERT_TAG_CURATOR,
      "payload":        payload,
      "context_inline": { self._CONTEXT_COLLECTED_TAGS: json.dumps(collected_tags) },
      "result":         [ self._RESULT_ALIAS_MAP ],
      "dedup_key":      f"{self.KIND_NORMALIZE_TAGS}:{surface}",
    }
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

  # ------------------------------------------------------------------
  @classmethod
  def _merge_dictionary_anchor(cls, repo: Path, payload: dict) -> dict:
    """
    Union the advisory dictionary's values into a classify payload's anchor.

    Args:
      repo: Absolute path to the repository root.
      payload: The caller's curation payload.

    Returns:
      The payload with every dictionary value present in `existing_tags`
      (dictionary-only values carrying a zero count and no examples), or the
      caller's own payload object when the kind is not `classify` or the
      dictionary holds nothing.
    """

    # Domain(wiki.taxonomy):
    # # Anchoring a classification to the settled vocabulary, not only the live one
    # A classification anchors to the values already spoken for, so it reuses one instead of coining a
    # synonym beside it. Read from the nodes alone, that set is only what is worn right now: a value
    # settled by an earlier canon but currently worn by nobody is invisible, and the very drift the canon
    # resolved starts again. The settled vocabulary is therefore folded in beside the live census, each
    # value appearing once whichever side it came from, and a value the census never saw is marked as worn
    # by no one — evidence enough to reuse it, and honest about how little is behind it.

    # guard: only classify carries an anchor — every other kind is forwarded verbatim
    if payload.get(cls._PAYLOAD_KIND) != cls.KIND_CLASSIFY:
      return payload
    listed = _tags.dictionary_values(repo)
    # guard: no dictionary on disk — the collected census stands as the whole anchor
    if not listed:
      return payload

    # fold each recorded value into its axis, keeping the census entry when both sides carry it
    anchor = payload.get(cls._PAYLOAD_EXISTING_TAGS)
    anchor = anchor if isinstance(anchor, dict) else {}
    axes = dict(anchor.get(_tags.COLLECT_AXES) or {})
    for axis, values in listed.items():
      entries = list(axes.get(axis) or [])
      known = { e.get(cls._ANCHOR_VALUE) for e in entries if isinstance(e, dict) }
      entries += [
        { cls._ANCHOR_VALUE: value, cls._ANCHOR_COUNT: 0, cls._ANCHOR_EXAMPLES: [] }
        for value in values if value not in known
      ]
      axes[axis] = entries
    return { **payload, cls._PAYLOAD_EXISTING_TAGS: { **anchor, _tags.COLLECT_AXES: axes } }

  # ------------------------------------------------------------------
  def dispatch_domain_writer(
    self,
    *,
    repo: Path,
    group: str,
    payload: dict,
  ) -> dict:
    """
    Queue a `wiki.domain-writer` job for one domain group via `dispatch-job`.

    Forwards the caller's `payload` verbatim (core writes it to
    `request.json` unchanged); the `dedup_key` combines the domain-spec kind
    with the group key, so repeated dispatches for the same group collapse
    to one pending job while other groups stay distinct.

    Guarantees:
      - The caller's `payload` reaches `request.json` unchanged; no field is added, renamed, or
        removed here.
      - The `dedup_key` combines the domain-spec kind with the group key, so repeated dispatches
        for one group collapse into one pending job while other groups stay independent.

    Args:
      repo: Absolute path to the repository root.
      group: Dot-separated domain group key the job regenerates.
      payload: Caller-assembled request dict (`kind`, group, gloss, blocks,
        language, doc_path, hash).

    Returns:
      Parsed JSON response from `dispatch-job`, typically
      `{"job_id": "<id>", "queue_path": "<abs-path>"}`.
    """

    # Contract:
    # The caller's `payload` reaches `request.json` unchanged — this method NEVER adds, renames, or
    # removes a payload field.

    # Contract:
    # The `dedup_key` MUST combine the domain-spec kind with the group key, so repeated dispatches
    # for one group collapse into one pending job while other groups stay independent.

    # the bundle core reads off stdin — layout, config.json and READY ordering stay core's
    bundle: dict = {
      "expert":    self.EXPERT_DOMAIN_WRITER,
      "payload":   payload,
      "dedup_key": f"{self.KIND_DOMAIN_SPEC}:{group}",
    }
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

  # ------------------------------------------------------------------
  def _call_core(self, subcommand: str, body: dict, repo: Path) -> dict:
    """
    Invoke `lazycortex-core <subcommand>` with a JSON body on stdin.

    Sets `LAZY_REPO_ROOT` in the subprocess environment so core can
    find the repo's settings without additional arguments.

    Args:
      subcommand: One of the `_CMD_*` class constants.
      body: Payload dict serialised to JSON on stdin.
      repo: Absolute path to the repository root.

    Returns:
      Parsed JSON from the subprocess stdout.

    Raises:
      RuntimeError: When the subprocess exits non-zero.
    """

    # Domain(plugin.boundaries):
    # # Exchange across a plugin boundary: JSON in, JSON out
    # Reaching for another plugin's functionality means running its executable as a separate process: the
    # request body goes to it as JSON on standard input, the answer is taken back as JSON from standard
    # output. Importing the other side's code is forbidden: the link is held at the level of data, not of
    # modules. The repository path is handed over through the environment so the receiving side reads its
    # own settings itself and the caller never retells fields it does not own. A non-zero exit code is a
    # refusal in full: there is no answer, and the error raised to the caller carries whatever the process
    # managed to print.

    env = os.environ.copy()
    env[self._ENV_REPO_ROOT] = str(repo)
    proc = subprocess.run(
      [ sys.executable, str(self._cli), subcommand ],
      input = json.dumps(body),
      capture_output = True,
      text = True,
      env = env,
      check = False,
    )
    # guard: non-zero exit from core — surface stdout+stderr for diagnosis
    if proc.returncode != 0:
      raise RuntimeError(
        f"lazycortex-core {subcommand} exit={proc.returncode} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
      )
    return json.loads(proc.stdout)

  # ------------------------------------------------------------------
  @staticmethod
  def _resolve_core_cli() -> Path:
    """
    Locate the `lazycortex-core` CLI binary.

    Walks `$LAZYCORTEX_PLUGIN_DIRS` — set by the daemon for every subprocess
    routine it spawns — for `<dir>/bin/lazycortex-core`, matching the shape
    `runtime_daemon.resolve_routine_command` uses on the daemon side, then falls
    back to the plugin cache this plugin itself runs from.

    Returns:
      Resolved `Path` to a usable `lazycortex-core` binary.

    Raises:
      RuntimeError: When neither the environment nor the plugin cache carries the binary.
    """

    # Domain(plugin.boundaries):
    # # Finding a neighbour inside a job the runtime started
    # This work only ever runs as a job the runtime starts, and the runtime hands every process it spawns the
    # list of directories where the enabled plugins live. Under that guarantee the neighbour's address is taken
    # from that list alone and nothing else is consulted: the entries are tried in the order given, and the
    # first one that actually carries the published command wins. An empty list means the job was started
    # outside the runtime; the one other place looked at is the installed-plugin cache this plugin itself
    # runs from, where the neighbour's newest installed version carries the command. The wider ladder of
    # sources a resolver needs when it must also serve a development checkout is described where that
    # resolver lives, and is not repeated here.

    # take the first directory that actually carries the binary — order is the caller's priority
    env_dirs = os.environ.get(CoreDispatch._ENV_PLUGIN_DIRS, "").split(os.pathsep)
    for d in env_dirs:
      # guard: skip empty segments produced by a leading/trailing colon
      if not d:
        continue
      cli = Path(d) / CoreDispatch._BIN_SEGMENT / CoreDispatch._CORE_PLUGIN_NAME
      if cli.is_file():
        return cli

    # plugin-cache fallback — a consumer install's own session has no daemon export to walk
    cached_root = _cached_sibling_root(CoreDispatch._CORE_PLUGIN_NAME)
    cached = None if cached_root is None else (
      cached_root / CoreDispatch._BIN_SEGMENT / CoreDispatch._CORE_PLUGIN_NAME
    )
    if cached is not None and cached.is_file():
      return cached

    # the environment and the plugin cache are the only sanctioned discovery channels — see
    # dev.plugin-boundaries § 1c; name what was searched so a misconfigured runner is diagnosable
    # from the message alone
    searched = [d for d in env_dirs if d] or ["<unset>"]
    raise RuntimeError(
      f"lazycortex-core CLI not resolvable: no "
      f"{CoreDispatch._BIN_SEGMENT}/{CoreDispatch._CORE_PLUGIN_NAME} under any directory named by "
      f"${CoreDispatch._ENV_PLUGIN_DIRS} (searched: {', '.join(searched)}) and no cached sibling. "
      f"This worker runs as a daemon subprocess, which exports that variable; "
      f"running it from a plain shell outside a cached install requires exporting "
      f"${CoreDispatch._ENV_PLUGIN_DIRS} to the enabled plugin directories first."
    )
