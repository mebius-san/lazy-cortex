"""
Cross-plugin dispatch for lazycortex-wiki.

Reaches lazycortex-core only through core's published CLI, run as a subprocess,
and never by importing core Python modules.
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
import tags as _tags  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# lazycortex-wiki reaches lazycortex-core ONLY via its published CLI —
# no Python-import coupling, and no plugin-cache walk: the binary comes
# from the wiki's one core resolver.  See the inter-plugin boundary
# contract for the full pattern.

# ----------------------------------------------------------------------------------------
class CoreDispatch:
  """
  Thin §1c bridge between lazycortex-wiki and lazycortex-core's CLI.

  Resolves the `lazycortex-core` binary at construction time and exposes the
  job-level operations this plugin needs: queueing expert jobs, and listing,
  reading, and retiring the finished ones it collects itself.

  Guarantees:
    - `lazycortex-core` is reached only through its published CLI binary, never by importing a
      core Python module.

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
  # Python module.

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

  # Subcommands forwarded to lazycortex-core.
  _CMD_DISPATCH  = "dispatch-job"
  _CMD_LIST_JOBS = "list-jobs"
  _CMD_COLLECT   = "collect-job"
  _CMD_CONSUME   = "consume-job"
  _CMD_RETIRE    = "retire-jobs"

  # `list-jobs` flags, the `{expert, job_id}` body keys `collect-job` / `consume-job` read, and the
  # `{expert, dedup_key}` body `retire-jobs` reads.
  _ARG_EXPERT    = "--expert"
  _ARG_CWD       = "--cwd"
  _JOB_EXPERT    = "expert"
  _JOB_ID        = "job_id"
  _JOB_DEDUP_KEY = "dedup_key"

  # Environment variable name core reads to locate the repo.
  _ENV_REPO_ROOT = "LAZY_REPO_ROOT"

  # `error-record` verb, its flags and wire values, as the core error ledger reads them.
  _CMD_ERROR_RECORD   = "error-record"
  _ARG_KIND           = "--kind"
  _ARG_CAUSE          = "--cause"
  _ARG_INCIDENT       = "--incident"
  _ARG_SEVERITY       = "--severity"
  _ARG_DETAIL         = "--detail"
  _ARG_RESOLVE        = "--resolve"
  _KIND_PLUGIN_ERROR  = "plugin_error"
  _SEVERITY_WARN      = "warn"

  # Repo-relative directory of the markers this plugin keeps for the ledger incidents it opened and has not closed,
  # so a success learns whether it has anything to close without spawning core.
  # opt: a marker exists only while the core ledger holds its incident open, which stays true because this plugin
  # is the only writer of the retire incidents it marks; an incident closed by anyone else leaves a stale marker
  # that sends one extra, harmless resolve on the next successful retire and is then removed.
  _OPEN_INCIDENTS_REL = ".runtime/lazy-wiki/open-incidents"

  # Stable cause a failed retire of finished jobs reports, and the incident-key prefix it folds under,
  # followed by the expert whose jobs were not retired.
  _CAUSE_RETIRE_FAILED     = "retire-finished-failed"
  _INCIDENT_RETIRE_PREFIX  = "wiki-retire:"

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
      RuntimeError: When no lookup stage finds a usable `lazycortex-core` binary.
    """
    self._cli = _axes.resolve_core_cli()

  # ------------------------------------------------------------------
  def dispatch_curator(self, *,
                       repo: Path,
                       node_path: Path,
                       payload: dict) -> dict:
    """
    Queue a `wiki.curator` job for one node via `dispatch-job`.

    The curator receives the caller's `payload` as given. The curation `kind` (`classify` / `link`) MUST be
    carried inside `payload["kind"]` by the caller — this method never supplies it. A `classify` payload's
    `existing_tags` anchor is the one field this method extends: the advisory tag dictionary's per-axis
    values are added to it, so a value that was canonised but is worn by no node today still anchors the
    curator.

    Guarantees:
      - The caller's `payload` reaches `request.json` unchanged except for a `classify` payload's
        `existing_tags` anchor, which gains the dictionary's values; no field is added, renamed, or
        removed beyond that.
      - The `dedup_key` combines the curation `kind` with the absolute node path, so repeated
        dispatches for the same kind and node collapse into one pending job while classify and
        link for the same node remain independent jobs.
      - A node lying outside the repository is refused before anything is queued.
      - A finished earlier job under the same `dedup_key` never blocks the dispatch, so a node edited again
        after its job finished gets a new job; a queued or running job still collapses the repeat.

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

    # Contract:
    # A finished earlier job under the same `dedup_key` MUST NOT block the dispatch;
    # a queued or running job still collapses the repeat into itself.

    # Domain(runtime.jobs):
    # # Collapsing repeated requests in the queue
    # A request for expert work carries a deduplication key: while an identical request is still waiting
    # in the queue, a repeat one is not created — the new ask joins the one already standing. The key is
    # built from the kind of work and the target it applies to, so different kinds of work on one target
    # stay independent requests. Were the kind of work left out of the key, an already-finished but not
    # yet collected request would swallow the request of another kind that it spawned itself. The target
    # is reduced to one canonical written form, otherwise the same target named two ways yields two keys
    # and two requests instead of one.

    # resolve the path to its absolute form so relative/absolute callers
    # collapse to the same dedup_key.
    abs_node = node_path.resolve() if node_path.is_absolute() else (Path(repo) / node_path).resolve()

    # the bundle names the node; the pump copies it when it claims the job, so the curator sees
    # the file as it stands then rather than as it stood when the dispatch was queued
    try:
      node_rel = abs_node.relative_to(Path(repo)).as_posix()
    except ValueError as err:
      # a node outside the repo has no manifest form: a bare basename would reach the pump and
      # fail the job at claim, so the dispatch is refused here where the caller can still see why
      raise RuntimeError(f"node {abs_node} lies outside the repository at {repo}") from err

    # the bundle core reads off stdin — layout, config.json and READY ordering stay core's; the
    # dedup_key is prefixed with the payload `kind` so classify and link for the same node do not
    # dedup against each other (a DONE-but-not-CONSUMED classify-job would otherwise swallow the
    # chained link dispatch from its own tail)
    bundle: dict = {
      "expert":    self.EXPERT_NAME,
      "payload":   self._merge_dictionary_anchor(repo, payload),
      "source":    [ node_rel ],
      "result":    [ "curation.json" ],
      "dedup_key": f"{payload.get(self._PAYLOAD_KIND, '')}:{abs_node}",
    }
    self._retire_finished(repo, bundle)
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

  # ------------------------------------------------------------------
  def dispatch_tag_curator(self, *,
                           repo: Path,
                           surface: str,
                           payload: dict,
                           collected_tags: dict) -> dict:
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
      - A finished earlier job for the surface never blocks the dispatch; a queued or running job still
        collapses the repeat.

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

    # Contract:
    # A finished earlier job for the surface MUST NOT block the dispatch;
    # a queued or running job still collapses the repeat into itself.

    # the census exists only in memory, so it rides as inline context rather than a path manifest
    bundle: dict = {
      "expert":         self.EXPERT_TAG_CURATOR,
      "payload":        payload,
      "context_inline": { self._CONTEXT_COLLECTED_TAGS: json.dumps(collected_tags) },
      "result":         [ self._RESULT_ALIAS_MAP ],
      "dedup_key":      f"{self.KIND_NORMALIZE_TAGS}:{surface}",
    }
    self._retire_finished(repo, bundle)
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

  # ------------------------------------------------------------------
  def _retire_finished(self, repo: Path, bundle: dict) -> None:
    """
    Retire the finished jobs that would hold the bundle's dedup key, via `retire-jobs`.

    Best-effort: a failed call is reported to the core error ledger and the dispatch still goes ahead, answering
    `already-queued` exactly as it would without the retire, so the caller still sees why nothing new was queued.

    Notes:
      - A failed `retire-jobs` call is reported to the core error ledger as a warning incident keyed per expert; the
        plugin remembers that incident as open for the repository only when core recorded the report, and a report
        that could not be delivered or that core refused leaves nothing remembered.
      - The next successful retire for the same expert in the same repository closes that incident through core's
        `error-record --resolve`.
      - A success with no incident remembered as open spawns nothing.
      - A close that core did not accept stays remembered as open and is retried on the next success.

    Args:
      repo: Absolute path to the repository root.
      bundle: The dispatch bundle about to be queued; its `expert` and `dedup_key` address the jobs to retire.
    """

    # Domain(runtime.jobs):
    # # Releasing a finished request nobody collects
    # A request whose answer is applied by the expert itself, with no one reading the answer back, is
    # never acknowledged by its caller, so a finished request would hold its deduplication key until the
    # queue is cleaned up days later and every repeat ask would be swallowed. Such a caller therefore
    # releases the finished requests under the key just before it asks again; a request still waiting or
    # running is left alone and the repeat joins it. The release is a courtesy, not a condition: when it
    # fails, the ask still goes out and simply meets the old request, as it did before.

    # the expert's retire incident and the local marker that records it as open
    incident = f"{self._INCIDENT_RETIRE_PREFIX}{bundle[self._JOB_EXPERT]}"
    marker = self._incident_marker(repo, incident)

    # a failed retire must not stop the dispatch — it goes to the error ledger and is marked open here, and the
    # dispatch's own answer reports what happened to the request
    try:
      self._call_core(
        self._CMD_RETIRE,
        { self._JOB_EXPERT: bundle[self._JOB_EXPERT], self._JOB_DEDUP_KEY: bundle[self._JOB_DEDUP_KEY] },
        repo,
      )
    except (RuntimeError, json.JSONDecodeError) as error:
      # only a report core recorded opened an incident, so only that one is remembered as open
      # waiver: a stdlib exception carries no class_name accessor; its class name is the varying detail of the report
      if self._report_warning(repo, cause = self._CAUSE_RETIRE_FAILED, incident = incident,
                              detail = f"{type(error).__name__}: {error}"):
        self._mark_open(marker)
      return

    # guard: no incident of this expert is marked open, so the success needs nothing from core
    if not marker.is_file():
      return

    # the success is the proof the condition cleared; the marker goes only once core took the close
    if self._resolve_incident(repo, incident):
      self._clear_mark(marker)

  # ------------------------------------------------------------------
  @classmethod
  def _incident_marker(cls, repo: Path, incident: str) -> Path:
    """
    Locate the record that tells whether an incident is remembered as open for a repository.

    Args:
      repo: Absolute path to the repository root.
      incident: Stable incident key in the core error ledger.

    Returns:
      The path of the open-incident record; it exists only while the incident is remembered as open.
    """
    # the incident key with its separator made filename-safe on every host
    return Path(repo) / cls._OPEN_INCIDENTS_REL / incident.replace(":", ".")

  # ------------------------------------------------------------------
  @staticmethod
  def _mark_open(marker: Path) -> None:
    """
    Remember an incident as open.

    Notes:
      - A record that cannot be written is dropped and never raised into the caller.

    Args:
      marker: Open-incident record path of the incident to remember.
    """
    # a marker that cannot be written leaves the incident to the operator, never breaks the dispatch
    try:
      marker.parent.mkdir(parents = True, exist_ok = True)
      marker.touch()
    # waiver: best-effort boundary — an unwritable runtime directory must not fail the dispatch it reports on
    except OSError:
      pass

  # ------------------------------------------------------------------
  @staticmethod
  def _clear_mark(marker: Path) -> None:
    """
    Forget an incident that core has accepted as closed.

    Notes:
      - A record that cannot be removed is left in place and never raised into the caller; the close is retried
        on the next successful retire.

    Args:
      marker: Open-incident record path of the incident to forget.
    """
    # a marker that cannot be removed only costs one more resolve on the next success
    try:
      marker.unlink(missing_ok = True)
    # waiver: best-effort boundary — a stale marker is harmless, the next success resolves again
    except OSError:
      pass

  # ------------------------------------------------------------------
  def _resolve_incident(self, repo: Path, incident: str) -> bool:
    """
    Ask core to close an incident in its error ledger via `error-record --resolve`.

    Notes:
      - A close that cannot be delivered is reported as not done and never raised into the caller.

    Args:
      repo: Absolute path to the repository root whose ledger holds the incident.
      incident: Stable incident key to close.

    Returns:
      `True` when core accepted the close, `False` otherwise.
    """
    # core's ledger lives under the working directory of the verb, so it runs from the repo root;
    # an undeliverable close is reported as not done, never raised into the dispatch
    try:
      # waiver: stdlib subprocess idiom, the arguments are the error-record wire contract
      done = subprocess.run(
        [ sys.executable, str(self._cli), self._CMD_ERROR_RECORD, self._ARG_INCIDENT, incident, self._ARG_RESOLVE ],
        cwd = repo, capture_output = True, text = True, check = False, encoding = "utf-8",
      )
    # waiver: best-effort boundary — a close that cannot be delivered leaves the marker for the next success
    except (OSError, ValueError):
      return False

    # only a clean exit means core recorded the close
    return done.returncode == 0

  # ------------------------------------------------------------------
  def _report_warning(self, repo: Path, *, cause: str, incident: str, detail: str) -> bool:
    """
    Open, or add to, a `plugin_error` incident at warning severity in the core error ledger.

    Notes:
      - A report that cannot be delivered is dropped and never raised into the caller.

    Args:
      repo: Absolute path to the repository root whose ledger records the event.
      cause: Stable cause token of the failure.
      incident: Stable incident key repeated reports of the same condition fold into.
      detail: One line describing this occurrence.

    Returns:
      `True` when `error-record` exited 0, `False` when the report could not be delivered or core refused it.
    """
    # core's ledger lives under the working directory of the verb, so it runs from the repo root;
    # a report that cannot be delivered is dropped, never raised into the work it reports on
    try:
      # waiver: stdlib subprocess idiom, the arguments are the error-record wire contract
      done = subprocess.run(
        [ sys.executable, str(self._cli), self._CMD_ERROR_RECORD, self._ARG_KIND, self._KIND_PLUGIN_ERROR,
          self._ARG_CAUSE, cause, self._ARG_INCIDENT, incident, self._ARG_SEVERITY, self._SEVERITY_WARN,
          self._ARG_DETAIL, detail ],
        cwd = repo, capture_output = True, text = True, check = False, encoding = "utf-8",
      )
    # waiver: best-effort boundary — an undeliverable report is dropped, never raised into the caller
    except (OSError, ValueError):
      return False

    # only a clean exit means core recorded the event and holds the incident open
    return done.returncode == 0

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

    # only classify carries an anchor — every other kind is forwarded verbatim
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
  def dispatch_domain_writer(self, *,
                             repo: Path,
                             group: str,
                             payload: dict,
                             result_names: list[str]) -> dict:
    """
    Queue a `wiki.domain-writer` job for one domain group via `dispatch-job`.

    The job returns the group's folder note and its stale block docs as result
    files, which `domain-collect` later lands in the generated tree.

    Guarantees:
      - The caller's `payload` reaches `request.json` unchanged; no field is added, renamed, or
        removed here.
      - The `dedup_key` combines the domain-spec kind with the group key, so repeated dispatches
        for one group collapse into one pending job while other groups stay independent.

    Args:
      repo: Absolute path to the repository root.
      group: Dot-separated domain group key the job regenerates.
      payload: Caller-assembled request dict (`kind`, group, gloss, docs,
        stale_docs, folder_note_path, hash, language, catalog_blocks, catalog_groups).
      result_names: File names the job returns under `result/` — the folder note's
        and every stale doc's.

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

    # the bundle core reads off stdin — layout, config.json and READY ordering stay core's; the
    # writer returns its files in the declared result slots, never in the working tree
    bundle: dict = {
      "expert":    self.EXPERT_DOMAIN_WRITER,
      "payload":   payload,
      "result":    list(result_names),
      "dedup_key": f"{self.KIND_DOMAIN_SPEC}:{group}",
    }
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

  # ------------------------------------------------------------------
  def query_jobs(self, *, repo: Path, expert: str) -> list[dict]:
    """
    List one expert's job bundles via `list-jobs`.

    Args:
      repo: Absolute path to the repository root.
      expert: Expert name whose queue is listed.

    Returns:
      Core's job descriptors, each carrying `expert`, `job_id`, `path`, and `status`; empty when
      core answered with anything but a JSON array, and any entry that is not an object is dropped.

    Raises:
      RuntimeError: When the core subprocess exits non-zero.
      json.JSONDecodeError: When the core subprocess stdout is not valid JSON.
    """
    listing = self._run_core([ self._CMD_LIST_JOBS, self._ARG_EXPERT, expert, self._ARG_CWD, str(repo) ], {}, repo)
    return [ entry for entry in listing if isinstance(entry, dict) ] if isinstance(listing, list) else []

  # ------------------------------------------------------------------
  def query_job(self, *, repo: Path, expert: str, job_id: str) -> dict:
    """
    Read one job's status and response via `collect-job`.

    Args:
      repo: Absolute path to the repository root.
      expert: Expert name the job was dispatched to.
      job_id: The job's identifier.

    Returns:
      Core's `{status, response}` dict for the job; empty when core answered with a JSON value
      that is not an object.

    Raises:
      RuntimeError: When the core subprocess exits non-zero.
      json.JSONDecodeError: When the core subprocess stdout is not valid JSON.
    """
    return self._call_core(self._CMD_COLLECT, { self._JOB_EXPERT: expert, self._JOB_ID: job_id }, repo)

  # ------------------------------------------------------------------
  def consume_job(self, *, repo: Path, expert: str, job_id: str) -> dict:
    """
    Retire one job via `consume-job`, releasing its dedup key.

    Args:
      repo: Absolute path to the repository root.
      expert: Expert name the job was dispatched to.
      job_id: The job's identifier.

    Returns:
      Core's `{"status": "ok"}` acknowledgement; empty when core answered with a JSON value that
      is not an object.

    Raises:
      RuntimeError: When the core subprocess exits non-zero.
      json.JSONDecodeError: When the core subprocess stdout is not valid JSON.
    """
    return self._call_core(self._CMD_CONSUME, { self._JOB_EXPERT: expert, self._JOB_ID: job_id }, repo)

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
      Parsed JSON object from the subprocess stdout; empty when core printed a JSON value that is
      not an object.

    Raises:
      RuntimeError: When the subprocess exits non-zero.
      json.JSONDecodeError: When the subprocess stdout is not valid JSON.
    """
    # every body-in verb answers with one JSON object
    parsed = self._run_core([ subcommand ], body, repo)
    return parsed if isinstance(parsed, dict) else {}

  # ------------------------------------------------------------------
  def _run_core(self, argv: list[str], body: dict, repo: Path) -> object:
    """
    Run `lazycortex-core` with the given arguments and a JSON body on stdin.

    Args:
      argv: The subcommand followed by any command-line flags it takes.
      body: Payload dict serialised to JSON on stdin.
      repo: Absolute path to the repository root.

    Returns:
      The parsed JSON value the subprocess printed.

    Raises:
      RuntimeError: When the subprocess exits non-zero.
      json.JSONDecodeError: When the subprocess stdout is not valid JSON.
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

    # run core with the repo root exported, the body on stdin
    env = os.environ.copy()
    env[self._ENV_REPO_ROOT] = str(repo)
    proc = subprocess.run(
      [ sys.executable, str(self._cli), *argv ],
      input = json.dumps(body),
      capture_output = True,
      text = True,
      env = env,
      check = False, encoding = "utf-8",
    )

    # guard: non-zero exit from core — surface stdout+stderr for diagnosis
    if proc.returncode != 0:
      raise RuntimeError(
        f"lazycortex-core {argv[0]} exit={proc.returncode} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
      )
    return json.loads(proc.stdout)
