"""
Logic behind the `lazycortex-specs coherence-dispatch <doc>` verb.

The verb queues one coherence check of an approved document against its approved neighbours, found through the
wiki together with the product hierarchy, and records the job on the document's folder-note. The neighbours a
check names stay within a fixed size budget; they travel as paths the expert reads from the working tree. A
document whose check is already recorded there is queued again and its entry is replaced; the replaced check is
cancelled when it has not finished.
"""
from __future__ import annotations

import argparse
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
import coherence  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_tick  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import AssetTypeKey, CoherenceJob, JobMarker, ReleaseKey, Stage, StageKey  # noqa: E402


_ENCODING = "utf-8"
_MD_SUFFIX = ".md"

# The wiki plugin's CLI, its verb listing a node's neighbours, and the verb's repo option
_WIKI_CLI_NAME = "lazycortex-wiki"
_WIKI_NEIGHBOURS_VERB = "neighbours"
_WIKI_REPO_OPTION = "--repo"

# The wiki answer's fields
_WIKI_SCOPE = "scope"
_WIKI_NEIGHBOURS = "neighbours"

# The frontmatter key naming a document's type, and the types that never take part in a check
_DOC_TYPE_KEY = "spec_doc_type"
# The frontmatter key marking a markdown attachment, naming the document it belongs to
_OWNER_DOC_KEY = "spec_owner_doc"
_JOURNAL_TYPES = frozenset({ "code-report", "test-report" })
_RELEASE_PLAN_TYPE = "code-plan"

# The settings key of a product record naming its folder under the content root
_SPEC_PATH_KEY = "spec_path"

# Request and summary fields
_KIND = "kind"
_CHECKED = "checked"
_NEIGHBOURS = "neighbours"
_JOB_ID = "job_id"
_DROPPED = "dropped"
_STATUS = "status"
_REASON = "reason"
_STATUS_SKIPPED = "skipped"
_STATUS_REFUSED = "refused"

# The number of hex digits of a document's digest the dedup key carries
_FINGERPRINT_LEN = 16

# The skip reason when the document has no neighbour to be checked against
NO_NEIGHBOURS = "no-neighbours"
# The skip reason when not even the first neighbour fits the check's text budget
OVER_BUDGET = "over-budget"


def _wiki_neighbours(repo: Path, doc: str) -> list[str] | None:
  """
  Ask the wiki for a document's neighbours.

  Args:
    repo: The repository root.
    doc: The repo-relative document.

  Returns:
    The repo-relative neighbours the wiki lists, or `None` when the wiki cannot answer: its CLI does not resolve,
    fails, prints no JSON object, or answers that no wiki scope covers the document.
  """
  cli = spec_paths.resolve_plugin_cli(_WIKI_CLI_NAME, dev_repo = repo)

  # guard: without the wiki plugin there is no one to ask
  if cli is None:
    return None
  try:
    proc = subprocess.run(
        [ sys.executable, str(cli), _WIKI_NEIGHBOURS_VERB, doc, _WIKI_REPO_OPTION, str(repo) ],
        capture_output = True, text = True, check = False, encoding = _ENCODING,
    )
    answer = json.loads(proc.stdout) if proc.returncode == 0 else None
  except (OSError, json.JSONDecodeError):
    return None

  # guard: an answer that is no object, or one no scope covers, leaves the question to the hierarchy
  if not isinstance(answer, dict) or answer.get(_WIKI_SCOPE) is None:
    return None
  listed = answer.get(_WIKI_NEIGHBOURS)
  return [ path for path in listed if isinstance(path, str) ] if isinstance(listed, list) else []


def _level_docs(folder: Path, repo: Path) -> list[str]:
  """
  List the markdown files lying directly in a level folder.

  Args:
    folder: The product root or catalog root folder.
    repo: The repository root.

  Returns:
    The repo-relative files, not descending into subfolders; empty when the folder does not exist.
  """
  # guard: a product whose folder is missing holds no document
  if not folder.is_dir():
    return []
  return [
      (folder / name).relative_to(repo).as_posix()
      for name in sorted(os.listdir(folder)) if name.endswith(_MD_SUFFIX) and (folder / name).is_file()
  ]


def _hierarchy_neighbours(repo: Path, doc: str) -> tuple[list[str], list[str]]:
  """
  Collect a document's neighbours from the product hierarchy.

  Args:
    repo: The repository root.
    doc: The repo-relative document.

  Returns:
    A pair of lists. The first holds the documents lying directly in the root folder of the document's own product.
    The second holds those lying directly in the root folder of the enclosing level (the parent product, or the
    catalog root for a top-level product) and of each product nested directly inside.

  Raises:
    KeyError: If a product record involved lacks `spec_path`.
  """

  # Domain(spec.coherence):
  # # The product hierarchy always supplies neighbours, wiki or not
  # Whether or not a wiki covers a document, the level documents of its own product, of the product that encloses it,
  # and of the products nested directly inside it are its neighbours. A level document is one lying directly in the
  # root folder of its level, not in the folder of an asset. The catalog root counts as the enclosing level of a
  # top-level product, and a document at the catalog root has the catalog's own level documents and those of the
  # top-level products as neighbours. The wiki's neighbours are added to these, never put in their place.

  settings_root = spec_paths.find_settings_root(repo)
  content_root = spec_paths.spec_content_root(settings_root)
  products = resolve_product.load_products(settings_root)
  key, record = resolve_product.resolve_product_by_path(settings_root, doc, products = products)

  # the folder of every level the document is compared with: its own, the enclosing one, the nested ones
  if key is None or record is None:
    own = content_root
    parent = None
    nested = [ name for name in products
               if not resolve_product.ancestor_chain(settings_root, name, products = products) ]
  else:
    own = content_root / record[_SPEC_PATH_KEY]
    chain = resolve_product.ancestor_chain(settings_root, key, products = products)
    parent = content_root / products[chain[-1]][_SPEC_PATH_KEY] if chain else content_root
    nested = resolve_product.child_keys(settings_root, key, products = products)
  others = [ parent ] if parent is not None else []
  others += [ content_root / products[name][_SPEC_PATH_KEY] for name in nested
              if isinstance(products.get(name), dict) and products[name].get(_SPEC_PATH_KEY) ]
  return _level_docs(own, repo), [ path for folder in others for path in _level_docs(folder, repo) ]


def _is_release_plan(path: Path, doc_type: str) -> bool:
  """
  Tell whether a document is a release's own build plan.

  Args:
    path: The document.
    doc_type: The document's `spec_doc_type`.

  Returns:
    True when the document is typed `code-plan` and its folder-note is a release's.
  """
  note = coherence.folder_note(path)

  # guard: only a plan beside a folder-note can belong to a release
  if doc_type != _RELEASE_PLAN_TYPE or not note.is_file():
    return False
  fm_values, _end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))
  return fm_values.get(AssetTypeKey.TYPE) == ReleaseKey.ASSET_TYPE


def _is_eligible(repo: Path, rel: str) -> bool:
  """
  Tell whether a document takes part in a coherence check as a neighbour.

  Args:
    repo: The repository root.
    rel: The repo-relative document.

  Returns:
    True for an existing approved document of a stage-bearing type that is not a build journal, a release's own
    build plan or an attachment of another document.
  """

  # Domain(spec.coherence):
  # # Only approved authored documents are neighbours in a coherence check
  # A coherence check compares a document only with authored documents that carry a stage and stand approved. A draft
  # is left out because it will still change, and the check on its own approval catches its conflicts. The build
  # journals take no part, and neither does a release's own build plan or a document attached to another one.

  path = repo / rel

  # guard: a path naming no markdown file is no document
  if path.suffix != _MD_SUFFIX or not path.is_file():
    return False
  fm_values, _end = spec_frontmatter.parse(path.read_text(encoding = _ENCODING))
  doc_type = str(fm_values.get(_DOC_TYPE_KEY, "")).strip()

  # guard: an untyped document, an attachment, a journal and a release plan are never compared
  if not doc_type or fm_values.get(_OWNER_DOC_KEY) or doc_type in _JOURNAL_TYPES or _is_release_plan(path, doc_type):
    return False
  key, _record = resolve_product.resolve_product_by_path(spec_paths.find_settings_root(repo), rel)
  declaration = spec_doc_types.resolve(repo, doc_type, key)
  return bool(declaration and declaration.get(spec_doc_types.DocTypeFlag.STAGES)) and \
      str(fm_values.get(StageKey.STAGE, "")).strip() == Stage.APPROVED


def collect_neighbours(repo: Path, doc: str) -> list[str]:
  """
  Collect the approved documents a document is checked against, from the wiki and the product hierarchy together.

  Args:
    repo: The repository root.
    doc: The repo-relative checked document.

  Returns:
    The repo-relative neighbours, sorted and without repeats, the document itself left out.

  Raises:
    KeyError: If a product record involved lacks `spec_path`.
  """
  return sorted(_ranked_neighbours(repo, doc))


def _ranked_neighbours(repo: Path, doc: str) -> list[str]:
  """
  List the eligible neighbours of a document in priority order.

  Args:
    repo: The repository root.
    doc: The repo-relative checked document.

  Returns:
    The wiki's neighbours first, then the level documents of the document's own product root, then those of the
    parent product and of the nested products. Each group is in sorted order, each document appears once at its
    first place, and the document itself is left out.

  Raises:
    KeyError: If a product record involved lacks `spec_path`.
  """
  # the wiki's neighbours first, then the own product's level documents, then the enclosing and nested ones
  own, others = _hierarchy_neighbours(repo, doc)
  tiers = [ sorted(_wiki_neighbours(repo, doc) or []), sorted(own), sorted(others) ]

  # each eligible document once, at its first and so highest-priority place
  ranked: list[str] = []
  for rel in ( rel for tier in tiers for rel in tier ):
    if rel != doc and rel not in ranked and _is_eligible(repo, rel):
      ranked.append(rel)
  return ranked


def _within_budget(repo: Path, ranked: list[str]) -> tuple[list[str], int]:
  """
  Select the leading neighbours whose files fit the budget of a coherence check.

  Each neighbour is kept whole while the running total of their file sizes stays within
  `CoherenceJob.NEIGHBOUR_BUDGET` (150 KB). The first neighbour that would exceed the budget ends the selection: it
  and every later one are dropped.

  Args:
    repo: The repository root.
    ranked: The eligible neighbours in priority order.

  Returns:
    The kept neighbours in priority order, and the count of neighbours dropped.
  """

  # Domain(spec.coherence):
  # # The neighbour text of one check has a fixed budget
  # One coherence check names at most 150 KB of neighbour text, measured as the size on disk of each neighbour's
  # file when the check is queued. Neighbours are taken in priority order: first the wiki's neighbours (See-also
  # targets and backlinks), then the level documents of the checked document's own product, then those of its parent
  # product and its nested products. Within each group the order is sorted. Filling stops at the first document that
  # would exceed the budget, and it and every later one are dropped, so a smaller later document never takes the
  # place of a dropped one. A document is never cut short. The dispatch never writes the checked document's
  # folder-note. When neighbours are dropped, their number travels with the check's tracking entry, and the history
  # line written when the check's result lands names both the conflicts found and the number of neighbours dropped.
  # When not even the first neighbour fits, no check runs, and the number dropped is only reported back to the
  # coordinator, which records it in the note's history itself.

  # the neighbours in priority order, each whole, until the next one would push the total over the budget
  kept: list[str] = []
  total = 0
  for rel in ranked:
    size = (repo / rel).stat().st_size

    # guard: the first document that does not fit ends the fill; it and every later one are dropped
    if total + size > CoherenceJob.NEIGHBOUR_BUDGET:
      break
    kept.append(rel)
    total += size
  return kept, len(ranked) - len(kept)


def _fingerprint(path: Path) -> str:
  """
  Name a document's current text by a short digest.

  Args:
    path: The document.

  Returns:
    The first 16 hex digits of the SHA-256 of the document's bytes.
  """
  return hashlib.sha256(path.read_bytes()).hexdigest()[:_FINGERPRINT_LEN]


def _cancel_superseded(repo: Path, job: dict[str, str]) -> None:
  """
  Retire a document's earlier check that a new one replaces.

  Cancel the check through the core when it has not finished. Retire its bundle through the core when it had
  finished or the cancel succeeded. When the cancel fails, write a line to stderr and leave the bundle as it is.
  The replaced check is no longer tracked in any case.

  Args:
    repo: The repository root.
    job: The replaced `{"doc", "expert", "job_id"}` entry.
  """
  expert, job_id = job[JobMarker.EXPERT], job[JobMarker.JOB_ID]

  # a check still running is cancelled first; one the runtime will not cancel is only dropped from tracking
  if gate_tick.find_active_job_marker(repo, expert, job_id) is None and \
      not gate_dispatch.cancel_job(repo, expert, job_id):
    sys.stderr.write(f"coherence-dispatch: could not cancel superseded job {expert}/{job_id}; no longer tracked\n")
    return

  # a finished or cancelled bundle is retired, so superseded checks do not pile up in the queue
  gate_dispatch.consume_stale_job(repo, expert, job_id)


def _retire_listed(repo: Path, note: Path, doc: str) -> None:
  """
  Retire the check listed for a document on its folder-note when no new check replaces it.

  The listed check is cancelled when it has not finished, as a replaced one is, and its entry is dropped from the
  folder-note's list; the entries of other documents are kept. A document with no listed check leaves the list
  untouched.

  Args:
    repo: The repository root.
    note: The folder-note beside the document.
    doc: The repo-relative checked document.
  """
  jobs = spec_job_markers.coherence_jobs(repo, note)
  listed = [ job for job in jobs if job[JobMarker.DOC] == doc ]

  # guard: nothing listed for the document, nothing to retire
  if not listed:
    return
  for job in listed:
    _cancel_superseded(repo, job)
  kept = [ job for job in jobs if job[JobMarker.DOC] != doc ]
  spec_job_markers.update(repo, note, { JobMarker.COHERENCE_JOBS: kept })


def _queue(repo: Path, doc: str, kept: list[str]) -> str:
  """
  Queue the coherence job of a document through the core runtime.

  Asking again for the same text of a document joins the check already under way; a changed text queues a new one.
  The payload lists the neighbours sorted, by repo-relative path; the job carries no copy of them.

  Args:
    repo: The repository root.
    doc: The repo-relative checked document.
    kept: The repo-relative neighbours the check names.

  Returns:
    The queued job's id.

  Raises:
    RuntimeError: If the core CLI does not resolve or refuses the dispatch.
  """

  # ref: dev.plugin-boundaries § 4 — neighbours travel only as repo-relative paths in the payload, read by the
  # expert from the working tree when the job runs; a `source` manifest would copy them flat by basename and
  # several `design.md` neighbours would overwrite each other

  bundle = {
      gate_dispatch.WireKey.EXPERT: CoherenceJob.EXPERT,
      gate_dispatch.WireKey.PAYLOAD: { _KIND: CoherenceJob.KIND, _CHECKED: doc, _NEIGHBOURS: sorted(kept) },
      gate_dispatch.WireKey.SOURCE: [ doc ],
      gate_dispatch.WireKey.RESULT: [ CoherenceJob.RESULT ],
      gate_dispatch.WireKey.DEDUP_KEY: f"{doc}{CoherenceJob.DEDUP_SUFFIX}:{_fingerprint(repo / doc)}",
      gate_dispatch.WireKey.PROTOCOLS: [ CoherenceJob.PROTOCOL ],
  }
  response = gate_dispatch.core_dispatch_job(repo, bundle)
  job_id = str(response.get(gate_dispatch.WireKey.JOB_ID))

  # a dedup hit on a bundle that already finished is retired and the check queued afresh, once
  if response.get(gate_dispatch.WireKey.STATUS) == gate_dispatch.ALREADY_QUEUED_STATUS and \
      gate_tick.find_active_job_marker(repo, CoherenceJob.EXPERT, job_id) is not None:
    gate_dispatch.consume_stale_job(repo, CoherenceJob.EXPERT, job_id)
    job_id = str(gate_dispatch.core_dispatch_job(repo, bundle).get(gate_dispatch.WireKey.JOB_ID))
  return job_id


def dispatch(repo: Path, doc: str) -> dict:
  """
  Queue a coherence check of a document against its neighbours and record the job on its folder-note.

  A document whose check is already listed on its folder-note is queued again like any other; a document is left
  unqueued only when it has no neighbour to be checked against or when not even the first neighbour fits the text
  budget. In that case the check already listed for the document is retired like a replaced one, since it read a text
  the new approval replaced: it is cancelled when it has not finished and its entry is dropped from the list, while
  the entries of other documents are kept. When a cancel fails, only a line is written to stderr and the entry is
  still replaced or dropped. The folder-note's text is never written or committed here; the number of neighbours
  dropped over the budget is only reported to the caller and, for a queued check, kept with its entry.

  Guarantees:
    - The folder-note lists at most one entry per document; a new job replaces the document's earlier entry in
      place, and the entries of other documents are kept.
    - A failed cancel of a replaced job never prevents the replacement.
    - Whenever neighbours are dropped over the budget, their count is reported in the result, queued or not.
    - The neighbours a check names never total more than the text budget.
    - Neighbours are dropped from the end of the priority order: the first one that does not fit and every later one
      are dropped, so a smaller later neighbour never takes the place of a dropped one.

  Args:
    repo: The repository root.
    doc: The repo-relative checked document.

  Returns:
    - `{"checked", "neighbours", "job_id"}` for the queued job, where `neighbours` lists only what was named,
      sorted, plus `"dropped": n` only when n neighbours were dropped over the budget; the job's entry on the
      folder-note carries the same `"dropped": n` then.
    - `{"checked", "status": "skipped", "reason": "no-neighbours"}` when the document has no neighbour; nothing is
      queued, and the check listed for the document, if any, is retired and dropped from the folder-note's list.
    - `{"checked", "status": "skipped", "reason": "over-budget", "dropped": n}` when not even the first neighbour
      fits the budget; nothing is queued, and the check listed for the document, if any, is retired and dropped
      from the folder-note's list.

  Raises:
    ValueError: If the document or its folder-note does not exist; nothing is queued then.
    RuntimeError: If the core CLI does not resolve or refuses the dispatch.
    KeyError: If a product record involved lacks `spec_path`; nothing is queued then.
  """

  # Domain(spec.coherence):
  # # One check per document text
  # A coherence check is keyed by the checked document and a digest of the exact text it was approved with. Asking
  # again for the same text joins the check already under way; a re-approval that changed the text starts a new
  # check. When a new check replaces one still listed for the document that has not finished, the old one is
  # cancelled and no longer tracked, even if the cancellation fails. A re-approval that queues no check, because the
  # document has no neighbours or not even the first neighbour fits the text budget, retires the listed check the
  # same way: the old check read a text the new approval replaced, and a new approval voids the earlier verdict, so
  # its result must never land.

  # Contract:
  # The folder-note lists at most one entry per document. A new job for a document replaces that document's earlier
  # entry in place, and the entries of other documents are kept.

  # Contract:
  # A failed cancel of a replaced job never prevents the replacement; the entry is replaced regardless.

  # Contract:
  # The neighbours one check names never total more than the text budget.

  # Contract:
  # Neighbours are dropped from the end of the priority order: the first neighbour that does not fit and every later
  # one are dropped, so a smaller later neighbour never takes the place of a dropped one.

  path = repo / doc
  note = coherence.folder_note(path)

  # guard: the check runs for an existing document whose folder-note can track the job
  if not path.is_file():
    raise ValueError(f"no such document: {doc}")

  # guard: without a folder-note nothing tracks the job
  if not note.is_file():
    raise ValueError(f"no folder-note beside {doc}")
  ranked = _ranked_neighbours(repo, doc)

  # guard: with nothing to compare against there is nothing to check, and the earlier check read a text now replaced
  if not ranked:
    _retire_listed(repo, note, doc)
    return { _CHECKED: doc, _STATUS: _STATUS_SKIPPED, _REASON: NO_NEIGHBOURS }
  kept, dropped = _within_budget(repo, ranked)

  # guard: when not even the first neighbour fits, nothing is queued, the earlier check is retired all the same and
  # the drop is only reported
  if not kept:
    _retire_listed(repo, note, doc)
    return { _CHECKED: doc, _STATUS: _STATUS_SKIPPED, _REASON: OVER_BUDGET, _DROPPED: dropped }

  # one job per document on the note: a document already tracked has its entry replaced in place, any other
  # document's check is kept, so the tick lands each result when it finishes
  job_id = _queue(repo, doc, kept)
  entry: dict = { JobMarker.DOC: doc, JobMarker.EXPERT: CoherenceJob.EXPERT, JobMarker.JOB_ID: job_id }
  if dropped:
    entry[JobMarker.DROPPED] = dropped
  jobs = spec_job_markers.coherence_jobs(repo, note)
  listed = any(job[JobMarker.DOC] == doc for job in jobs)
  for job in jobs:
    if job[JobMarker.DOC] == doc and job[JobMarker.JOB_ID] != job_id:
      _cancel_superseded(repo, job)
  jobs = [ entry if job[JobMarker.DOC] == doc else job for job in jobs ] if listed else [ *jobs, entry ]
  spec_job_markers.update(repo, note, { JobMarker.COHERENCE_JOBS: jobs })

  # the neighbours left out over the budget are counted in the summary; the landing history line reports them
  summary: dict[str, str | int | list[str]] = { _CHECKED: doc, _NEIGHBOURS: sorted(kept), _JOB_ID: job_id }
  if dropped:
    summary[_DROPPED] = dropped
  return summary


def main(argv: list[str]) -> int:
  """
  Queue a coherence check of one document from the command line.

  Notes:
    - Prints the `dispatch` summary on stdout, or `{"status": "refused", "reason"}` when the document or its
      folder-note is missing, a product record lacks `spec_path`, or the dispatch failed.
    - A document already listed on its folder-note is queued again; a skip happens only for lack of neighbours.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 when the check was queued or skipped, 1 when it was refused.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs coherence-dispatch")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("doc")
  args = parser.parse_args(argv)
  repo = coherence.repo_root()

  # the whole dispatch, refused as one when the document, its note or the runtime is unusable
  try:
    summary = dispatch(repo, coherence.parse_doc_arg(repo, args.doc))
  except (ValueError, RuntimeError, KeyError) as error:
    print(json.dumps({ _STATUS: _STATUS_REFUSED, _REASON: str(error) }))
    return 1
  print(json.dumps(summary))
  return 0
