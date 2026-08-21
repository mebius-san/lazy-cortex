"""
Cross-plugin dispatch for lazycortex-wiki.

Implements the §1c CLI-subprocess contract from
The inter-plugin boundary contract — lazycortex-wiki reaches
lazycortex-core exclusively via its published CLI binary, never by
importing core Python modules.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# lazycortex-wiki reaches lazycortex-core ONLY via its published CLI —
# no Python-import coupling, no filesystem-walk binary discovery beyond
# the $LAZYCORTEX_PLUGIN_DIRS contract.  See
# the inter-plugin boundary contract for the full pattern.

# ----------------------------------------------------------------------------------------
class CoreDispatch:
  """
  Thin §1c bridge between lazycortex-wiki and lazycortex-core's CLI.

  Resolves the `lazycortex-core` binary at construction time and exposes a
  single dispatch-level operation to queue curator jobs.

  Guarantees:
    - `lazycortex-core` is reached only through its published CLI binary, located only among the
      directories named by `$LAZYCORTEX_PLUGIN_DIRS`; no core Python module is imported and no
      plugin-cache layout is walked.

  Attributes:
    EXPERT_NAME: Expert name as it appears in `lazy.settings.json[experts]`.
    EXPERT_DOMAIN_WRITER: Domain-spec writer expert name in `lazy.settings.json[experts]`.
    KIND_CLASSIFY: Payload `kind` value requesting node classification.
    KIND_LINK: Payload `kind` value requesting node linking.
    KIND_DOMAIN_SPEC: Payload `kind` value requesting a domain-spec (re)generation.
  """

  # Contract:
  # `lazycortex-core` is reached ONLY through its published CLI binary, and that binary is located
  # ONLY among the directories named by `$LAZYCORTEX_PLUGIN_DIRS`. Importing a core Python module or
  # walking the plugin cache is NEVER a substitute.

  # Expert name as it appears in `lazy.settings.json[experts]`.
  EXPERT_NAME = "wiki.curator"

  # Domain-spec writer expert name as it appears in `lazy.settings.json[experts]`.
  EXPERT_DOMAIN_WRITER = "wiki.domain-writer"

  # Payload `kind` value requesting a domain-spec (re)generation.
  KIND_DOMAIN_SPEC = "domain-spec"

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

    The caller's `payload` is forwarded verbatim; core writes it to
    `request.json` unchanged.  The curation `kind` (`classify` /
    `link`) MUST be carried inside `payload["kind"]` by the caller so
    it reaches the curator's `request.json` — this method never injects
    or mutates the payload.

    Guarantees:
      - The caller's `payload` reaches `request.json` unchanged; no field is added, renamed, or
        removed here.
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
    # The caller's `payload` reaches `request.json` unchanged — this method NEVER adds, renames, or
    # removes a payload field, so a curation `kind` the caller omits is absent for the curator too.

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
      "payload":   payload,
      "source":    [ node_rel ],
      "result":    [ "curation.json" ],
      "dedup_key": dedup_key,
    }
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

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
      [ str(self._cli), subcommand ],
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
    `runtime_daemon.resolve_routine_command` uses on the daemon side.

    Returns:
      Resolved `Path` to a usable `lazycortex-core` binary.

    Raises:
      RuntimeError: When the environment names no directory carrying the binary.
    """

    # Domain(plugin.boundaries):
    # # Finding a neighbour inside a job the runtime started
    # This work only ever runs as a job the runtime starts, and the runtime hands every process it spawns the
    # list of directories where the enabled plugins live. Under that guarantee the neighbour's address is taken
    # from that list alone and nothing else is consulted: the entries are tried in the order given, and the
    # first one that actually carries the published command wins. An empty list means the job was started
    # outside the runtime — a fault in how the run was set up, not a reason to look somewhere else. The wider
    # ladder of sources a resolver needs when it must also serve a hand-run install is described where that
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

    # the environment is the only sanctioned discovery channel — see dev.plugin-boundaries § 1c;
    # name what was searched so a misconfigured runner is diagnosable from the message alone
    searched = [d for d in env_dirs if d] or ["<unset>"]
    raise RuntimeError(
      f"lazycortex-core CLI not resolvable: no "
      f"{CoreDispatch._BIN_SEGMENT}/{CoreDispatch._CORE_PLUGIN_NAME} under any directory named by "
      f"${CoreDispatch._ENV_PLUGIN_DIRS} (searched: {', '.join(searched)}). "
      f"This worker runs as a daemon subprocess, which exports that variable; "
      f"running it from a plain shell requires exporting "
      f"${CoreDispatch._ENV_PLUGIN_DIRS} to the enabled plugin directories first."
    )
