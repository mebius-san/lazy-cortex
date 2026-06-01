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
  single dispatch-level operation, `dispatch_curator`.  An internal helper
  method handles the raw subprocess call and is exercised directly by unit
  tests via the public interface.
  """

  # Expert name as it appears in `lazy.settings.json[experts]`.
  EXPERT_NAME = "wiki-curator"

  # Subcommand forwarded to lazycortex-core.
  _CMD_DISPATCH = "dispatch-job"

  # Environment variable name core reads to locate the repo.
  _ENV_REPO_ROOT = "LAZY_REPO_ROOT"

  # Plugin-dirs env var set by the daemon for subprocess routines.
  _ENV_PLUGIN_DIRS = "LAZYCORTEX_PLUGIN_DIRS"

  # Path components used in binary resolution.
  _CORE_PLUGIN_NAME = "lazycortex-core"
  _BIN_SEGMENT      = "bin"
  _CACHE_SEGMENTS   = (".claude", "plugins", "cache")

  # Valid kind values that the curator protocol recognises. Callers place one
  # of these as the payload's `kind` field; the payload is written verbatim to
  # `request.json` by core, so the curator reads `request.json["kind"]`.
  KIND_CLASSIFY = "classify"
  KIND_LINK     = "link"

  # Payload field carrying the node's raw text.
  _PAYLOAD_KIND       = "kind"
  _PAYLOAD_NODE_FIELD = "node_content"

  # source/ filename the curator reads the node from (matches the protocol).
  _SOURCE_NODE_FILE = "node"

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
    Queue a wiki-curator job for one node via `dispatch-job`.

    Builds the full job bundle and forwards it to `lazycortex-core
    dispatch-job`.  Core owns the job-dir layout, config.json
    composition, READY ordering, and git_author/aspects/model
    resolution — none of those leak into this caller (§1c §3).

    The caller's `payload` is forwarded verbatim; core writes it to
    `request.json` unchanged.  The curation `kind` (`classify` /
    `link`) MUST be carried inside `payload["kind"]` by the caller so
    it reaches the curator's `request.json` — this method never injects
    or mutates the payload.

    Args:
      repo: Absolute path to the repository root.
      node_path: Absolute or repo-relative path to the node being
        curated; the resolved-absolute form is combined with the
        curation `kind` to build the `dedup_key`, so repeated
        dispatches for the same (kind, node) collapse to one pending
        job while classify and link dispatches for the same node are
        kept distinct.
      payload: Caller-assembled curation payload dict (curation `kind`,
        node content, scope context, pins).

    Returns:
      Parsed JSON response from `dispatch-job`, typically
      `{"job_id": "<id>", "queue_path": "<abs-path>"}`.
    """
    # Resolve the path to its absolute form so relative/absolute callers
    # collapse to the same dedup_key. Prepend `kind` so classify and link
    # for the same node do not dedup against each other (a DONE-but-not-
    # CONSUMED classify-job would otherwise swallow the chained link
    # dispatch from its own tail).
    if node_path.is_absolute():
      abs_node = node_path
    else:
      abs_node = (Path(repo) / node_path).resolve()
    kind = str(payload.get(self._PAYLOAD_KIND, ""))
    dedup_key = f"{kind}:{abs_node}"
    bundle: dict = {
      "expert":    self.EXPERT_NAME,
      "payload":   payload,
      "source":    { self._SOURCE_NODE_FILE: payload.get(self._PAYLOAD_NODE_FIELD, "") },
      "result":    [ "curation.json" ],
      "dedup_key": dedup_key,
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

    Two-stage lookup matching the shape `runtime_daemon.resolve_routine_command`
    uses on the daemon side:

    1. Walk `$LAZYCORTEX_PLUGIN_DIRS` (set by the daemon when it spawns
       subprocess routines) for `<dir>/bin/lazycortex-core`.
    2. Fall back to the highest-versioned entry in the plugin cache
       at `~/.claude/plugins/cache/<registry>/lazycortex-core/<version>/bin/lazycortex-core`.
       Used when the env is unset (operator running outside the daemon,
       or a consumer install that does not run the daemon at all).

    Returns:
      Resolved `Path` to a usable `lazycortex-core` binary.

    Raises:
      RuntimeError: When both lookup stages fail.
    """
    env_dirs = os.environ.get(CoreDispatch._ENV_PLUGIN_DIRS, "").split(os.pathsep)
    for d in env_dirs:
      # guard: skip empty segments produced by a leading/trailing colon
      if not d:
        continue
      cli = Path(d) / CoreDispatch._BIN_SEGMENT / CoreDispatch._CORE_PLUGIN_NAME
      if cli.is_file():
        return cli
    # Stage 2 — plugin cache layout:
    # ~/.claude/plugins/cache/<registry>/lazycortex-core/<version>/bin/lazycortex-core
    cache = Path.home().joinpath(*CoreDispatch._CACHE_SEGMENTS)
    if cache.is_dir():
      plugin_dirs = [
        registry / CoreDispatch._CORE_PLUGIN_NAME
        for registry in cache.iterdir()
        if registry.is_dir() and (registry / CoreDispatch._CORE_PLUGIN_NAME).is_dir()
      ]
      all_versions = [
        v for pd in plugin_dirs for v in pd.iterdir() if v.is_dir()
      ]
      if all_versions:
        latest = sorted(all_versions, key = lambda v: v.name, reverse = True)[0]
        cli = latest / CoreDispatch._BIN_SEGMENT / CoreDispatch._CORE_PLUGIN_NAME
        if cli.is_file():
          return cli
    raise RuntimeError(
      "lazycortex-core CLI not resolvable: $LAZYCORTEX_PLUGIN_DIRS "
      "yields no match and the plugin cache has no lazycortex-core "
      "version with a bin/lazycortex-core entry. Either pass "
      "--plugin-dir to the daemon, or install lazycortex-core into "
      "the Claude Code plugin cache."
    )
