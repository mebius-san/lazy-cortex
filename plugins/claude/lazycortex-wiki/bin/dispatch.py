"""
Cross-plugin dispatch for lazycortex-wiki.

Reaches lazycortex-core only through core's published CLI, run as a subprocess,
and never by importing core Python modules.
"""
from __future__ import annotations

import hashlib
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


# Encoding of the JSON exchanged with the core CLI.
_ENCODING = "utf-8"

# Codec error handler that turns a byte that is not valid text into a replacement mark instead of failing.
_DECODE_LOSSY = "replace"

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
    EXPERT_TERMS_CURATOR: Terms-curator expert name in `lazy.settings.json[experts]`.
    KIND_CLASSIFY: Payload `kind` value requesting node classification.
    KIND_LINK: Payload `kind` value requesting node linking.
    KIND_DOMAIN_SPEC: Payload `kind` value requesting a domain-spec (re)generation.
    KIND_NORMALIZE_TAGS: Payload `kind` value requesting a surface's tag-value canon.
    CAUSE_TERMS_REFUSED: Stable cause reported for every refused terms-curator operation and unmatched entry of a
      terms-write call that hands errors back, the first call as well as a final one.
    INCIDENT_TERMS_PREFIX: Prefix of the incident key such a report folds under, followed by the terms scope id, a
      colon and the repo-relative path of the document the error concerns.
    CAUSE_TERMS_BATCH_REFUSED: Stable cause reported when a terms-write call is refused as a whole after an earlier
      call of its job committed.
    INCIDENT_TERMS_BATCH_PREFIX: Prefix of that report's incident key, followed by the terms scope id, a colon and
      the repo-relative path of a document of the job.
    CAUSE_TERMS_LEGACY_UNSETTLED: Stable cause reported for every term line of an old terms section that a
      terms-write call leaves standing in a document of its job.
    INCIDENT_TERMS_LEGACY_PREFIX: Prefix of that report's incident key, followed by the terms scope id, a colon and
      the repo-relative path of the document the line stands in.
    CAUSE_DOMAIN_CODE_UNREADABLE: Stable cause reported while a domain tick's scan meets code files it cannot read.
    INCIDENT_DOMAIN_CODE: The one incident key that report folds under.
    CAUSE_DOMAIN_DICTIONARY_UNREADABLE: Stable cause reported while a domain tick finds the group dictionary absent
      or unreadable.
    INCIDENT_DOMAIN_DICTIONARY: The one incident key that report folds under.
    CAUSE_RELINK_NODE_UNREADABLE: Stable cause reported while a relink pass skips nodes it cannot read.
    INCIDENT_RELINK_PREFIX: Prefix of that report's incident key, followed by the scope whose nodes were skipped.
    CAUSE_RELINK_NAME_SKIPPED: Stable cause reported while a relink plan leaves out changed paths whose names are
      not valid UTF-8.
    INCIDENT_RELINK_PLAN_PREFIX: Prefix of that report's incident key, followed by the planned scope.
    CAUSE_MIRROR_FILE_UNREADABLE: Stable cause reported while a mirror sync skips files it cannot read or decode.
    INCIDENT_MIRROR_PREFIX: Prefix of that report's incident key, followed by the mirror scope.
    CAUSE_DOCTOR_MIRROR_UNREADABLE: Stable cause reported while a doctor run's mirror audit meets files or a source
      listing it cannot read.
    INCIDENT_DOCTOR_MIRROR_PREFIX: Prefix of that report's incident key, followed by the audited scope.
    CAUSE_DOCTOR_DOMAINS_FAILED: Stable cause reported while a doctor run's repo-level domain audit fails.
    INCIDENT_DOCTOR_DOMAINS: The one incident key that report folds under.
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

  # Terms-curator expert name as it appears in `lazy.settings.json[experts]`.
  EXPERT_TERMS_CURATOR = "wiki.terms-curator"

  # Protocol a terms-curator job runs under, and the curate request's kind, role and review switch.
  _TERMS_PROTOCOL       = "lazycortex-wiki:lazy-wiki.terms-protocol"
  _TERMS_KIND_CURATE    = "curate"
  _PAYLOAD_ROLE         = "role"
  _TERMS_ROLE           = "terms-curator"
  _TERMS_FILES          = "files"
  _TERMS_INCLUDE_REVIEW = "include_review"

  # `settings-set` verb and the flags of a keyed write on one settings layer.
  _CMD_SETTINGS_SET = "settings-set"
  _ARG_SCOPE        = "--scope"
  _ARG_KEY          = "--key"
  _ARG_VALUE        = "--value"
  _ARG_DELETE       = "--delete"

  # `daemon-run-here` verb, its read-only action and the flag asking for its JSON verdict.
  _CMD_DAEMON_RUN_HERE = "daemon-run-here"
  _RUN_HERE_CHECK      = "check"
  _ARG_JSON            = "--json"

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

  # `list-jobs` flag adding each bundle's dedup key, the entry field carrying a bundle's status,
  # and the status value of a job no worker has claimed yet.
  _ARG_WITH_DEDUP_KEY = "--with-dedup-key"
  _JOB_STATUS         = "status"
  _STATUS_QUEUED      = "queued"

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
  # Seconds one `error-record` call may take before the report is dropped.
  # limit: a fixed ceiling for every ledger call, ample for one journal append; make it a setting if a slow host
  # needs more
  _LEDGER_TIMEOUT_SEC = 10
  # Whether a ledger call of this instance ran out of its time limit; an instance starts with none.
  _timed_out = False

  # Repo-relative directory of the markers this plugin keeps for the ledger incidents it opened and has not closed,
  # so a success learns whether it has anything to close without spawning core.
  # opt: a marker exists only while the core ledger holds its incident open, which stays true because this plugin
  # is the only writer of every incident it marks; an incident closed by anyone else leaves a stale marker that
  # sends one extra, harmless resolve on the next close of the same key and is then removed.
  _OPEN_INCIDENTS_REL = ".runtime/lazy-wiki/open-incidents"

  # The name of an incident's open-incident record: the first `:` of the key becomes a dot, as record names always
  # had it; every later `:`, `%` itself and the characters a file name cannot carry are percent-encoded. No key
  # prefix holds a dot, so the first dot of a name marks the first colon of its key and two keys never share a
  # record.
  _MARKER_SEPARATOR = "."
  _MARKER_UNSAFE    = str.maketrans({ "%": "%25", "/": "%2F", "\\": "%5C", ":": "%3A" })
  # A name longer than a file name may be, in UTF-8 bytes, keeps a readable prefix and ends in `%H` and the SHA-256
  # hex digest of the whole key. The encoding above writes `%` only before `25`, `2F`, `5C` or `3A`, so no name of
  # a short key holds `%H`, and two long keys share a name only when they share a digest.
  _MARKER_NAME_MAX  = 255
  _MARKER_DIGEST    = "%H"

  # Stable cause a failed retire of finished jobs reports, and the incident-key prefix it folds under,
  # followed by the expert whose jobs were not retired.
  _CAUSE_RETIRE_FAILED     = "retire-finished-failed"
  _INCIDENT_RETIRE_PREFIX  = "wiki-retire:"

  # Stable cause a refused terms-curator operation reports, and the incident-key prefix it folds under, followed
  # by the terms scope and the document the error concerns.
  CAUSE_TERMS_REFUSED     = "terms-operation-refused"
  INCIDENT_TERMS_PREFIX   = "wiki-terms:"

  # Stable cause a terms-write call refused as a whole after an earlier call of its job committed reports, and the
  # incident-key prefix it folds under, followed by the terms scope and the document of the job.
  CAUSE_TERMS_BATCH_REFUSED   = "terms-batch-refused"
  INCIDENT_TERMS_BATCH_PREFIX = "wiki-terms-batch:"

  # Stable cause a term line of an old terms section left standing after a terms-write call reports, and the
  # incident-key prefix it folds under, followed by the terms scope and the document the line stands in.
  CAUSE_TERMS_LEGACY_UNSETTLED = "terms-legacy-line-unsettled"
  INCIDENT_TERMS_LEGACY_PREFIX = "wiki-terms-legacy:"

  # The key of one `source` / `context` / `result` entry of a dispatch bundle that names its path, and the
  # bucket a result entry's path sits under.
  _ENTRY_PATH    = "path"
  _RESULT_BUCKET = "result"

  # Stable cause a domain tick reports while the scan meets code files it cannot read, and the one incident
  # key it folds under: the condition belongs to the repository's domain tree as a whole, not to one file.
  CAUSE_DOMAIN_CODE_UNREADABLE = "domain-code-unreadable"
  INCIDENT_DOMAIN_CODE         = "wiki-domains:unreadable-code"

  # Stable cause a domain verb reports while the group dictionary cannot be found or read, and the one incident
  # key it folds under: the dictionary belongs to the repository's domain tree as a whole.
  CAUSE_DOMAIN_DICTIONARY_UNREADABLE = "domain-dictionary-unreadable"
  INCIDENT_DOMAIN_DICTIONARY         = "wiki-domains:dictionary"

  # Stable cause a relink pass reports while it skips nodes it cannot read, and the incident-key prefix it folds
  # under, followed by the scope whose nodes were skipped.
  CAUSE_RELINK_NODE_UNREADABLE = "relink-node-unreadable"
  INCIDENT_RELINK_PREFIX       = "wiki-relink:"

  # Stable cause a relink plan reports while it leaves out changed paths whose names are not valid UTF-8, and the
  # incident-key prefix it folds under, followed by the planned scope.
  CAUSE_RELINK_NAME_SKIPPED    = "relink-name-skipped"
  INCIDENT_RELINK_PLAN_PREFIX  = "wiki-relink-plan:"

  # Stable cause a mirror sync reports while it skips files it cannot read or decode, and the incident-key prefix
  # it folds under, followed by the mirror scope.
  CAUSE_MIRROR_FILE_UNREADABLE = "mirror-file-unreadable"
  INCIDENT_MIRROR_PREFIX       = "wiki-mirror:"

  # Stable cause a doctor run reports while a scope's mirror audit meets files or a source listing it cannot read,
  # and the incident-key prefix it folds under, followed by the audited scope.
  CAUSE_DOCTOR_MIRROR_UNREADABLE = "doctor-mirror-unreadable"
  INCIDENT_DOCTOR_MIRROR_PREFIX  = "wiki-doctor-mirror:"

  # Stable cause a doctor run reports while its repo-level domain audit fails, and the one incident key it folds
  # under: the audit covers the repository's domain tree as a whole.
  CAUSE_DOCTOR_DOMAINS_FAILED = "doctor-domains-failed"
  INCIDENT_DOCTOR_DOMAINS     = "wiki-doctor:domains"

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

  def __init__(self, *, repo: Path) -> None:
    """
    Resolve the `lazycortex-core` CLI binary on construction.

    Args:
      repo: Repository root the dispatcher works for; the core plugin is looked up for it.

    Raises:
      RuntimeError: When no lookup stage finds a usable `lazycortex-core` binary.
    """
    self._cli = _axes.resolve_core_cli(repo)

  # ------------------------------------------------------------------
  @property
  def has_timed_out(self) -> bool:
    """
    Whether a ledger call of this dispatcher ran out of its time limit.

    Notes:
      - Becomes `True` once a ledger call of this instance, `report_open` or `close_open_incident` reaching core's
        `error-record`, ran out of its time limit, and stays `True` afterwards.
      - A call that core refused or that could not be delivered is no timeout.
      - Read-only.
    """
    return self._timed_out

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
      node_path: Absolute or repo-relative path to the node being curated; its resolved-absolute form and
        the curation `kind` make up the `dedup_key` given by `curator_dedup_key`, so repeated dispatches
        for the same (kind, node) collapse to one pending job while classify and link dispatches for the
        same node are kept distinct.
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
    # A request for expert work carries a deduplication key: a repeat is absorbed by any request under the same
    # key that is still active — waiting, running, or finished but not yet collected by its caller. Before
    # dispatching, the caller tries to release its finished requests under the key, so an earlier finished
    # request normally does not block a new one, while a waiting or running one absorbs the repeat. When the
    # release fails, the ask still goes out and the old finished request absorbs it. The key is built from the
    # kind of work and the target it applies to, so different kinds of work on one target stay independent
    # requests. Were the kind of work left out of the key, an already-finished but not yet collected request
    # would swallow the request of another kind that it spawned itself. The target is reduced to one canonical
    # written form, otherwise the same target named two ways yields two keys and two requests instead of one.

    # the absolute form of the node, the one its dedup key is built from
    abs_node = self._resolve_node(repo, node_path)

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
      "source":    [ { self._ENTRY_PATH: node_rel } ],
      "result":    self._build_result_entries([ "curation.json" ]),
      "dedup_key": self.curator_dedup_key(
        repo = repo, node_path = node_path, kind = payload.get(self._PAYLOAD_KIND, ""),
      ),
    }
    self._retire_finished(repo, bundle)
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

  # ------------------------------------------------------------------
  @classmethod
  def curator_dedup_key(cls, *, repo: Path, node_path: Path, kind: str) -> str:
    """
    Return the dedup key a curator job of one kind for one node is queued under.

    Guarantees:
      - The key is exactly the `dedup_key` that `dispatch_curator` sends to core for the same kind and node.
      - Relative and absolute spellings of one node give the same key.

    Args:
      repo: Absolute path to the repository root.
      node_path: Absolute or repo-relative path to the node.
      kind: The curation kind, one of the `KIND_*` values.

    Returns:
      The key `dispatch_curator` sends to core for that kind and node; relative and absolute
      spellings of one node give the same key.
    """

    # Contract:
    # The returned key is exactly the `dedup_key` that `dispatch_curator` sends to core for the same
    # kind and node, and a relative and an absolute spelling of one node give the same key. Callers
    # match this key against the queue to recognise a node whose job already waits there.

    # the kind and the resolved absolute node path make up the key
    return f"{kind}:{cls._resolve_node(repo, node_path)}"

  # ------------------------------------------------------------------
  @staticmethod
  def _resolve_node(repo: Path, node_path: Path) -> Path:
    """
    Resolve a node path to its absolute form.

    Args:
      repo: Absolute path to the repository root.
      node_path: Absolute or repo-relative path to the node.

    Returns:
      The resolved absolute path; a relative path resolves against `repo`.
    """
    return node_path.resolve() if node_path.is_absolute() else (Path(repo) / node_path).resolve()

  # ------------------------------------------------------------------
  def query_queued_dedup_keys(self, *, repo: Path, expert: str) -> set[str]:
    """
    Return the dedup keys of one expert's jobs that wait unclaimed, via `list-jobs`.

    Guarantees:
      - The returned set holds only the keys of jobs no worker has claimed yet (status `queued`); the key
        of a running job is never returned.

    Args:
      repo: Absolute path to the repository root.
      expert: Expert name whose queue is read.

    Returns:
      The keys of the jobs no worker has claimed yet; a running job is left out. Empty when core
      answered with anything but a JSON array.

    Raises:
      RuntimeError: When the core subprocess exits non-zero.
      json.JSONDecodeError: When the core subprocess stdout is not valid JSON.
      UnicodeDecodeError: When the core subprocess stdout is not valid UTF-8 text.
    """

    # Contract:
    # The returned set holds only the keys of jobs no worker has claimed yet (status `queued`); the key of
    # a running job is NEVER returned. Callers skip a dispatch on a hit, which is safe only for an
    # unclaimed job, because it will still read its source as it stands when claimed. A running job may
    # have read the source before its latest change, so its node must still be dispatched.

    listing = self._run_core(
      [ self._CMD_LIST_JOBS, self._ARG_EXPERT, expert, self._ARG_WITH_DEDUP_KEY, self._ARG_CWD, str(repo) ],
      {}, repo,
    )

    # guard: core answered with something that is not a listing
    if not isinstance(listing, list):
      return set()

    # only a job nobody claimed yet will still read its source as it stands when it is claimed
    return {
      entry[self._JOB_DEDUP_KEY]
      for entry in listing
      if isinstance(entry, dict)
      and entry.get(self._JOB_STATUS) == self._STATUS_QUEUED
      and isinstance(entry.get(self._JOB_DEDUP_KEY), str)
    }

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
      "result":         self._build_result_entries([ self._RESULT_ALIAS_MAP ]),
      "dedup_key":      f"{self.KIND_NORMALIZE_TAGS}:{surface}",
    }
    self._retire_finished(repo, bundle)
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

  # ------------------------------------------------------------------
  def dispatch_terms_curator(self, *,
                             repo: Path,
                             files: list[str],
                             dedup_key: str,
                             include_review: bool = False) -> dict:
    """
    Queue a `wiki.terms-curator` job that curates the terms of the given documents.

    Guarantees:
      - The caller's `dedup_key` reaches core verbatim; it is never prefixed, rewritten or derived.
      - The queued request is a terms `curate` request over exactly the given `files`, under the terms protocol; no
        document is added to or dropped from the list.
      - The request carries `include_review` true only when the caller passes `include_review` true; otherwise the
        key is absent and the curator leaves documents under review alone.
      - A finished earlier job under the same `dedup_key` never blocks the dispatch; a queued or running job
        still collapses the repeat.

    Args:
      repo: Absolute path to the repository root.
      files: Repo-relative documents the job names; the curator reads them from the working tree.
      dedup_key: Key that collapses repeats of one unit of work.
      include_review: Whether the curator may edit documents under an open review round; false by default.

    Returns:
      Parsed JSON response from `dispatch-job`.
    """

    # Contract:
    # The caller's `dedup_key` reaches core verbatim — this method NEVER prefixes, rewrites, or derives it,
    # because callers build the key that collapses repeats of one unit of work.

    # Contract:
    # The queued request is a terms `curate` request over exactly the given `files`, under the terms protocol; no
    # document is added to or dropped from the list. It carries `include_review` true only when the caller passes
    # `include_review` true; otherwise the key is absent and the curator leaves documents under review alone.

    # Contract:
    # A finished earlier job under the same `dedup_key` MUST NOT block the dispatch;
    # a queued or running job still collapses the repeat into itself.

    # a curate request over the named documents, open to documents under review only when the caller says so; the
    # curator reads them from the working tree by path, so nothing is copied into the job
    bundle: dict = {
      "expert":    self.EXPERT_TERMS_CURATOR,
      "payload":   {
        self._PAYLOAD_KIND: self._TERMS_KIND_CURATE,
        self._PAYLOAD_ROLE: self._TERMS_ROLE,
        self._TERMS_FILES:  list(files),
        **( { self._TERMS_INCLUDE_REVIEW: True } if include_review else {} ),
      },
      "protocols": [ self._TERMS_PROTOCOL ],
      "dedup_key": dedup_key,
    }
    self._retire_finished(repo, bundle)
    return self._call_core(self._CMD_DISPATCH, bundle, repo)

  # ------------------------------------------------------------------
  def query_daemon_run_here(self, repo: Path) -> dict:
    """
    Ask core whether the runtime daemon runs from this checkout.

    Guarantees:
      - The answer is always a JSON object; a reply from core that is not an object is answered as an empty one.
      - The check never writes; asking changes neither the daemon gate nor any other state.

    Args:
      repo: Absolute path to the repository root.

    Returns:
      The verdict object, with the state of the daemon gate and, for another checkout, its host and path.
    """

    # Contract:
    # The answer is always a JSON object: a reply from core that is not an object is answered as an empty one,
    # so a caller reading a verdict key never meets a non-mapping.

    # Contract:
    # The check NEVER writes — neither the daemon gate nor any other state is changed by asking.

    # core compares this checkout with the daemon gate and names the entry its verdict rests on
    verdict = self._run_core(
      [ self._CMD_DAEMON_RUN_HERE, self._RUN_HERE_CHECK, self._ARG_CWD, str(repo), self._ARG_JSON ], {}, repo,
    )
    return verdict if isinstance(verdict, dict) else {}

  # ------------------------------------------------------------------
  def save_setting(self, *, repo: Path, section: str, key: str, value: object, layer: str) -> None:
    """
    Write one nested settings value on one layer via core.

    Guarantees:
      - Only the named `key` on the named `layer` changes; every other key of the section and the other settings
        layer stay as they were.

    Args:
      repo: Absolute path to the repository root.
      section: Top-level settings-section name.
      key: Slash-separated path of the nested key inside the section.
      value: JSON-serializable value to store.
      layer: Settings layer to write, `tracked` or `local`.
    """

    # Contract:
    # Only the named `key` on the named `layer` changes; every other key of the section and the other settings
    # layer stay as they were.

    # one nested value on one layer; core keeps the rest of the section and the other layer as they are
    self._run_core(
      [ self._CMD_SETTINGS_SET, section, self._ARG_SCOPE, layer, self._ARG_KEY, key,
        self._ARG_VALUE, json.dumps(value), self._ARG_CWD, str(repo) ],
      {}, repo,
    )

  # ------------------------------------------------------------------
  def delete_setting(self, *, repo: Path, section: str, key: str, layer: str) -> None:
    """
    Remove one nested settings key from one layer via core.

    Guarantees:
      - Only the named `key` leaves the named `layer`; every other key of the section and the other settings
        layer stay as they were.

    Args:
      repo: Absolute path to the repository root.
      section: Top-level settings-section name.
      key: Slash-separated path of the nested key inside the section.
      layer: Settings layer to change, `tracked` or `local`.
    """

    # Contract:
    # Only the named `key` leaves the named `layer`; every other key of the section and the other settings
    # layer stay as they were.

    # one nested key leaves one layer; an absent key is no failure
    self._run_core(
      [ self._CMD_SETTINGS_SET, section, self._ARG_SCOPE, layer, self._ARG_KEY, key, self._ARG_DELETE,
        self._ARG_CWD, str(repo) ],
      {}, repo,
    )

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

    # the expert's retire incident
    incident = f"{self._INCIDENT_RETIRE_PREFIX}{bundle[self._JOB_EXPERT]}"

    # a failed retire must not stop the dispatch — it goes to the error ledger and is marked open here, and the
    # dispatch's own answer reports what happened to the request
    try:
      self._call_core(
        self._CMD_RETIRE,
        { self._JOB_EXPERT: bundle[self._JOB_EXPERT], self._JOB_DEDUP_KEY: bundle[self._JOB_DEDUP_KEY] },
        repo,
      )
    except (RuntimeError, ValueError) as error:
      # waiver: a stdlib exception carries no class_name accessor; its class name is the varying detail of the report
      self.report_open(repo, cause = self._CAUSE_RETIRE_FAILED, incident = incident,
                       detail = f"{type(error).__name__}: {error}")
      return

    # the success is the proof the condition cleared
    self.close_open_incident(repo, incident)

  # ------------------------------------------------------------------
  @classmethod
  def _build_result_entries(cls, names: list[str]) -> list[dict[str, str]]:
    """
    Wrap result filenames into the entries a bundle's `result` carries.

    Args:
      names: The plain filenames the expert is expected to fill.

    Returns:
      One `{"path": "result/<name>"}` entry per filename, in the same order.
    """
    # a result entry names its file the way a response does: under the result bucket
    return [ { cls._ENTRY_PATH: f"{cls._RESULT_BUCKET}/{name}" } for name in names ]

  # ------------------------------------------------------------------
  def report_open(self, repo: Path, *, cause: str, incident: str, detail: str) -> None:
    """
    Open or extend a warning incident in the core error ledger and remember it as open.

    Best-effort: a report that cannot be delivered never raises into the caller.

    Notes:
      - The incident is remembered as open for the repository only when core recorded the report; a report that could
        not be delivered, that core refused, or that core did not take within the call's time limit leaves nothing
        remembered.
      - A call that ran out of its time limit is remembered by `has_timed_out`.

    Args:
      repo: Absolute path to the repository root.
      cause: Stable cause token of the failure.
      incident: Stable incident key that repeated reports fold into.
      detail: One line about this occurrence.
    """
    # only a report core recorded opened an incident, so only that one is remembered as open
    if self._report_warning(repo, cause = cause, incident = incident, detail = detail):
      self._mark_open(self._incident_marker(repo, incident))

  # ------------------------------------------------------------------
  def close_open_incident(self, repo: Path, incident: str) -> None:
    """
    Close an incident remembered as open for the repository, through core's `error-record --resolve`.

    Notes:
      - With nothing remembered under the key, nothing is spawned.
      - The incident stays remembered when core did not accept the close, so a later call retries.
      - A close that ran out of its time limit is remembered by `has_timed_out`.

    Args:
      repo: Absolute path to the repository root.
      incident: Stable incident key in the core error ledger.
    """
    marker = self._incident_marker(repo, incident)

    # guard: no incident under the key is marked open, so nothing needs closing in core
    if not marker.is_file():
      return

    # the marker goes only once core took the close
    if self._resolve_incident(repo, incident):
      self._clear_mark(marker)

  # ------------------------------------------------------------------
  @classmethod
  def is_incident_open(cls, repo: Path, incident: str) -> bool:
    """
    Tell whether an incident is remembered as open for a repository.

    Args:
      repo: Absolute path to the repository root.
      incident: Stable incident key in the core error ledger.

    Returns:
      `True` while the incident is remembered as open, `False` otherwise.
    """
    return cls._incident_marker(repo, incident).is_file()

  # ------------------------------------------------------------------
  @classmethod
  def _incident_marker(cls, repo: Path, incident: str) -> Path:
    """
    Locate the record that tells whether an incident is remembered as open for a repository.

    Notes:
      - The record's name is the incident key with its first `:` written as `.`, every later `:` as `%3A`, `%` as
        `%25`, `/` as `%2F` and a backslash as `%5C`.
      - A name that would exceed 255 bytes in UTF-8 becomes a readable prefix of itself, cut on a whole character,
        followed by `%H` and the SHA-256 hex digest of the whole incident key, so the record name stays within 255
        bytes. A name that fits is never changed.
      - Two different keys never share a record. Short names stay apart because no key prefix holds a `.`, so the
        first `.` of a name marks the first `:` of its key, and a short name never holds `%H`, since `%` is written
        only before `25`, `2F`, `5C` or `3A`. Two long keys share a record only when their digests match. Names of
        `wiki-retire:<expert>` keys are unchanged by this.

    Args:
      repo: Absolute path to the repository root.
      incident: Stable incident key in the core error ledger.

    Returns:
      The path of the open-incident record; it exists only while the incident is remembered as open.
    """
    # the key's prefix, a dot for its first colon, and the rest made filename-safe on every host
    prefix, colon, rest = incident.partition(":")
    name = (
      prefix.translate(cls._MARKER_UNSAFE) + (colon and cls._MARKER_SEPARATOR) + rest.translate(cls._MARKER_UNSAFE)
    ).encode("utf-8")

    # a name too long for a file keeps its readable start, cut on a whole character, and the digest of the whole key
    if len(name) > cls._MARKER_NAME_MAX:
      digest = cls._MARKER_DIGEST + hashlib.sha256(incident.encode("utf-8")).hexdigest()
      # waiver: `ignore` is the stdlib codec error-handler name, which drops the character the byte cut split
      kept = name[: cls._MARKER_NAME_MAX - len(digest)].decode("utf-8", errors = "ignore")
      return Path(repo) / cls._OPEN_INCIDENTS_REL / (kept + digest)

    # a name that fits is the encoded key itself
    return Path(repo) / cls._OPEN_INCIDENTS_REL / name.decode("utf-8")

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
    # a marker that cannot be written leaves the incident to the operator, never breaks the work it reports on
    try:
      marker.parent.mkdir(parents = True, exist_ok = True)
      marker.touch()
    # waiver: best-effort boundary — an unwritable runtime directory must not fail the work it reports on
    except OSError:
      pass

  # ------------------------------------------------------------------
  @staticmethod
  def _clear_mark(marker: Path) -> None:
    """
    Forget an incident that core has accepted as closed.

    Notes:
      - A record that cannot be removed is left in place and never raised into the caller; the close is retried
        on the next close of the same key, whatever closes it.

    Args:
      marker: Open-incident record path of the incident to forget.
    """
    # a marker that cannot be removed only costs one more resolve on the next close of the same key
    try:
      marker.unlink(missing_ok = True)
    # waiver: best-effort boundary — a stale marker is harmless, the next close of the key resolves again
    except OSError:
      pass

  # ------------------------------------------------------------------
  def _resolve_incident(self, repo: Path, incident: str) -> bool:
    """
    Ask core to close an incident in its error ledger via `error-record --resolve`.

    Notes:
      - A close that cannot be delivered, or that core does not take within the call's time limit, is reported as
        not done and never raised into the caller.
      - A close that ran out of its time limit is remembered by `has_timed_out`.

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
        cwd = repo, capture_output = True, check = False,
        timeout = self._LEDGER_TIMEOUT_SEC,
      )
    # waiver: best-effort boundary — a close not delivered in time leaves the marker for the next close
    except subprocess.TimeoutExpired:
      self._timed_out = True
      return False
    # waiver: best-effort boundary — a close that cannot be delivered leaves the marker for the next close
    except (OSError, ValueError):
      return False

    # only a clean exit means core recorded the close
    return done.returncode == 0

  # ------------------------------------------------------------------
  def _report_warning(self, repo: Path, *, cause: str, incident: str, detail: str) -> bool:
    """
    Open, or add to, a `plugin_error` incident at warning severity in the core error ledger.

    Notes:
      - A report that cannot be delivered, or that core does not take within the call's time limit, is dropped and
        never raised into the caller.
      - A report that ran out of its time limit is remembered by `has_timed_out`.

    Args:
      repo: Absolute path to the repository root whose ledger records the event.
      cause: Stable cause token of the failure.
      incident: Stable incident key repeated reports of the same condition fold into.
      detail: One line describing this occurrence.

    Returns:
      `True` when `error-record` exited 0, `False` when the report was not delivered in time or core refused it.
    """
    # core's ledger lives under the working directory of the verb, so it runs from the repo root;
    # a report that cannot be delivered is dropped, never raised into the work it reports on
    try:
      # waiver: stdlib subprocess idiom, the arguments are the error-record wire contract
      done = subprocess.run(
        [ sys.executable, str(self._cli), self._CMD_ERROR_RECORD, self._ARG_KIND, self._KIND_PLUGIN_ERROR,
          self._ARG_CAUSE, cause, self._ARG_INCIDENT, incident, self._ARG_SEVERITY, self._SEVERITY_WARN,
          self._ARG_DETAIL, detail ],
        cwd = repo, capture_output = True, check = False,
        timeout = self._LEDGER_TIMEOUT_SEC,
      )
    # waiver: best-effort boundary — a report not delivered in time is dropped, never raised into the caller
    except subprocess.TimeoutExpired:
      self._timed_out = True
      return False
    # waiver: best-effort boundary — a report that cannot be delivered is dropped, never raised into the caller
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
      "result":    self._build_result_entries(list(result_names)),
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
      UnicodeDecodeError: When the core subprocess stdout is not valid UTF-8 text.
    """
    listing =self._run_core([ self._CMD_LIST_JOBS, self._ARG_EXPERT, expert, self._ARG_CWD, str(repo) ], {}, repo)
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
      UnicodeDecodeError: When the core subprocess stdout is not valid UTF-8 text.
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
      UnicodeDecodeError: When the core subprocess stdout is not valid UTF-8 text.
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
      UnicodeDecodeError: When the subprocess stdout is not valid UTF-8 text.
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
      UnicodeDecodeError: When the subprocess stdout is not valid UTF-8 text.
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
      input = json.dumps(body).encode(_ENCODING),
      capture_output = True,
      env = env,
      check = False,
    )

    # guard: non-zero exit from core — surface stdout+stderr for diagnosis; the output is taken as bytes, so the
    # exit status alone tells success from failure, and in the report a byte that is not valid text becomes a
    # replacement mark
    if proc.returncode != 0:
      raise RuntimeError(
        f"lazycortex-core {argv[0]} exit={proc.returncode} "
        f"stdout={proc.stdout.decode(_ENCODING, errors = _DECODE_LOSSY)!r} "
        f"stderr={proc.stderr.decode(_ENCODING, errors = _DECODE_LOSSY)!r}"
      )

    # the answer itself is parsed strictly: one that is not valid text is no answer, never a patched-up one
    return json.loads(proc.stdout)
