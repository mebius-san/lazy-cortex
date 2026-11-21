"""
Logic behind the `lazycortex-specs release-publish <release-note>` verb — the `Publish` tick of a release.

Publishing freezes a built release: its assets are released under the release's version, the product's manifest takes
that version, and the whole set lands in one commit. The promises of a publish — what refuses it, how the reviews of
the release folder are stopped and put back, how a production deploy is recorded, which members are released, and
who is woken afterwards — live in the docstrings of `publish` and `main`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import string
import sys
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import asset_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import coordinator_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import release_delta  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import release_deploy  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import release_version  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_halt  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    AssetState, AssetTypeKey, Gate, HistoryEvent, LangId, LevelDoc, MemberBuildState, ReleaseConfigKey, ReleaseKey,
    Section, SpecMomentKey, SpecStateKey, Stage, StageKey,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from spec_lockit import Lockit  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from summary_render import apply_container_stats  # noqa: E402  # pylint: disable=import-error,wrong-import-position


_ENCODING = "utf-8"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"
_TAGS_KEY = "tags"
_TRUE = "true"
_MOMENT_MIDNIGHT = "T00:00:00Z"
_UTC_OFFSET = "+00:00"
_UTC_SUFFIX = "Z"

# The bot identity the publish commit is authored under
PUBLISH_NAME = "lazy-spec.release-publish"

# The note added to an exception of a publish that fails after its production deploy succeeded, so a caller knows
# the deploy ran and must not be repeated unseen
DEPLOYED_NOTE = "release-publish: the production deploy ran before the publish failed"

# The name the publish reports a failure on stderr under
_PUBLISH_LOG = "release-publish"

# Refusal messages
_MSG_PUBLISHED = "release is already published"
_MSG_NO_PRODUCT = "no product covers the release note"
_MSG_CANCELLED = "release is cancelled"
_MSG_REBUILD_OWED = "release owes a rebuild"
# The refusal reason of a release whose current build has no successful last staging deploy; the build number follows
_MSG_STAGING_NOT_DEPLOYED = "no successful last staging deploy for build"


# The placeholders of a deploy line the staging check pins; every other one matches any text
_FIELD_BUILD = "build"
_FIELD_TARGET = "target"

# The suffix of a document that can be under review
_MD_SUFFIX = ".md"

# Result keys and values
_OUTCOME = "outcome"
_REASON = "reason"
_OUTCOME_REFUSED = "refused"
_OUTCOME_DEPLOY_FAILED = "deploy-failed"
_OUTCOME_PUBLISHED = "published"
_OUTCOME_ERROR = "error"
_VERSION = "version"
_ASSETS = "assets"
_MANIFEST = "manifest"
_TARGET = "target"
_EXIT_CODE = "exit_code"
_LOG = "log"
_REAPPROVED = "reapproved"
_UNBUILT = "unbuilt"
_CANCELLED = "cancelled"
_DEPLOYED = "deployed"


def _create_refusal(reason: str) -> dict:
  """
  Build a refusal result.

  Args:
    reason: Why nothing was published.

  Returns:
    `{"outcome": "refused", "reason": <reason>}`.
  """
  return { _OUTCOME: _OUTCOME_REFUSED, _REASON: reason }


def _format_moment(today: str | None) -> str:
  """
  Return the ISO 8601 UTC moment stamped beside the released gate.

  Args:
    today: An ISO date pinned by the caller, or None to read the clock.

  Returns:
    `<today>T00:00:00Z` when a date was pinned, else the current UTC time to the second, `Z`-suffixed.
  """
  # a pinned date is stamped at its midnight; the clock is read otherwise
  if today is not None:
    return f"{today}{_MOMENT_MIDNIGHT}"
  return datetime.now(UTC).replace(microsecond = 0).isoformat().replace(_UTC_OFFSET, _UTC_SUFFIX)


def _parse_moment(raw: str) -> datetime | None:
  """
  Parse an ISO 8601 moment as frontmatter carries it.

  Args:
    raw: The frontmatter value, possibly quoted, `Z`-suffixed or empty.

  Returns:
    The timezone-aware moment, UTC assumed when the text names no offset; None when the text is empty or no moment.
  """
  text = raw.strip().strip("\"'")

  # guard: an empty value names no moment
  if not text:
    return None

  # an unparseable value names no moment either
  try:
    moment = datetime.fromisoformat(text)
  except ValueError:
    return None
  return moment if moment.tzinfo is not None else moment.replace(tzinfo = UTC)


def find_build_moment(fm_values: dict) -> datetime | None:
  """
  Read the moment a release's members were last built from.

  Args:
    fm_values: The release note's parsed frontmatter.

  Returns:
    The release's `spec_impl_build_at`, or its `spec_build_at` when it records no implementation build moment; None
    when it records neither.
  """

  # Domain(spec.lifecycle):
  # # The members were built at the last implementation build
  # A release is built anew when its implementation is, and also when only its tests are rebuilt. A test-only
  # rebuild builds none of the members' code, so the moment the members were built is the last implementation
  # build. A release that records no implementation build moment falls back to its last build of any kind.

  # the implementation build's moment wins; the last build of any kind stands in for it
  return _parse_moment(str(fm_values.get(ReleaseKey.IMPL_BUILD_AT, ""))) \
      or _parse_moment(str(fm_values.get(ReleaseKey.BUILD_AT, "")))


def _compile_deploy_line(event: str, lang: str, build: str) -> re.Pattern[str]:
  """
  Compile the pattern of one deploy line of a named build to the staging target, as one language renders it.

  Args:
    event: The deploy event key, `deployed-build` or `deploy-failed-build`.
    lang: The language the line is rendered in.
    build: The build number the line names.

  Returns:
    A pattern matching the line's tail with that build and the staging target, any log and exit code.
  """
  parts: list[str] = []
  for literal, field, _spec, _conv in string.Formatter().parse(
      Lockit.text(note_explainers.HISTORY_KEY_PREFIX + event, lang)):
    parts.append(re.escape(literal))

    # guard: a trailing literal names no field
    if field is None:
      continue

    # the build and the target are pinned; the log and the exit code are any text
    pinned = { _FIELD_BUILD: build, _FIELD_TARGET: ReleaseConfigKey.STAGING }.get(field)
    parts.append(re.escape(pinned) if pinned is not None else ".*?")
  return re.compile(r"(?:^|\s)" + "".join(parts) + r"\s*$")


def is_staging_deploy_succeeded(text: str, build: str) -> bool:
  """
  Tell whether a release's last staging deploy of a build succeeded.

  The lines read are the ones `release-deploy --build` journals, in any language the plugin writes in.

  Guarantees:
    - True only when the `# History` holds a successful staging deploy line for exactly `build` and no failed
      staging deploy line for it after that one.
    - Lines of other builds never count, whatever language a line is written in, and an empty `build` is never
      deployed.

  Args:
    text: The release note's text.
    build: The number of the release's current build; empty when it records none.

  Returns:
    True when the note's `# History` holds a successful staging deploy of `build` with no failed one after it; False
    otherwise, and always for an empty `build`.
  """

  # Domain(spec.lifecycle):
  # # A build is published only once its staging deploy succeeded
  # A product that declares a staging target runs every build there before it is published. A build is published only
  # when its last staging deploy succeeded. A build never deployed to staging, as after a rebuild of the tests alone,
  # or whose last staging deploy failed, never reached the place it is checked in, so it is not published, whatever
  # else the release reads. A deploy of another build counts for nothing: only the deploys of the current build
  # decide.

  # Contract:
  # A build counts as deployed to staging only when the release's `# History` holds a successful staging deploy
  # line for exactly that build and no failed staging deploy line for it after that one. Lines of other builds
  # never count, a line counts in whatever language it is written, and an empty build is never deployed.

  # guard: a release without a build has no deploy of it to read
  if not build:
    return False

  # each language's success and failure lines for this build
  ok_lines = [ _compile_deploy_line(HistoryEvent.DEPLOYED_BUILD, lang, build) for lang in LangId ]
  failed_lines = [ _compile_deploy_line(HistoryEvent.DEPLOY_FAILED_BUILD, lang, build) for lang in LangId ]

  # the `# History` section runs from its heading to the next H1
  succeeded = False
  in_history = False
  for line in text.splitlines():
    if line.startswith("# "):
      in_history = line.strip() == Section.HISTORY
      continue

    # guard: only the journal's own lines count
    if not in_history:
      continue

    # the later of the two outcomes wins
    if any(rx.search(line) for rx in failed_lines):
      succeeded = False
    elif any(rx.search(line) for rx in ok_lines):
      succeeded = True
  return succeeded


def _read_approval(doc: Path) -> tuple[bool, datetime | None]:
  """
  Read whether a document stands approved, and its approval moment.

  Args:
    doc: The document.

  Returns:
    Whether the document is on disk with `spec_stage: approved`, and its `spec_approved_at` moment, None when it
    carries none or is not on disk.
  """

  # guard: a document not on disk is neither approved nor stamped
  if not doc.is_file():
    return False, None

  # the stage and the approval stamp both come from the document's frontmatter
  fm_values, _end = spec_frontmatter.parse(doc.read_text(encoding = _ENCODING))
  approved = str(fm_values.get(StageKey.STAGE, "")).strip().strip("\"'") == Stage.APPROVED
  return approved, _parse_moment(str(fm_values.get(SpecMomentKey.APPROVED_AT, "")))


def read_member_build_state(vault: Path, note: Path, build_at: datetime | None) -> MemberBuildState:
  """
  Read how an included asset's change stands against the release's last implementation build.

  The member's own product and asset type decide which document starts it.

  Args:
    vault: The vault root holding `.claude/lazy.settings.json`.
    note: The asset's status note.
    build_at: The moment the release's members were last built, or None when the release records none.

  Returns:
    `unbuilt` when the type names a start document that is missing, not approved, or carries no approval moment;
    `reapproved` when the start document, or an approved `ui-design.md` beside it, was approved after `build_at`;
    `built` otherwise, and always for a type naming no start document.
  """

  # Domain(spec.lifecycle):
  # # Only a change that was built ships as released
  # A release ships what its build tested. An included asset whose starting document is missing, is not approved,
  # or carries no approval moment never had an approved change for the build to carry, so it was never built: it
  # takes the version's tag, yet it is not marked released, and the publish leaves its state as its own coordinator
  # painted it: no design of it was accepted for the build, so nothing about it is settled by this release. An
  # asset whose starting document, or whose approved interface design, was approved again after the release's
  # members were last built takes the tag and stays unreleased too: the version carries the design that was built
  # and tested, and the new one waits for the next release. Only such a re-approved asset, whose design is
  # accepted, is set awaiting the next release. A release that records no build moment counts every approved
  # member as built.

  # the asset's own product and type name its start document
  fm_values, _end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))
  _key, record = resolve_product.effective_record_by_path(vault, note.resolve().relative_to(vault).as_posix())
  start_file, _doc_type = asset_types.start_doc(fm_values.get(AssetTypeKey.TYPE, "").strip(), record or {})

  # guard: a type without a start document has no design a build could have missed
  if not start_file:
    return MemberBuildState.BUILT

  # the start document's own approval decides whether there was a change to build
  approved, approved_at = _read_approval(note.parent / start_file)

  # guard: a change never approved with a moment was never built
  if not approved or approved_at is None:
    return MemberBuildState.UNBUILT

  # a later approval than the build, of the design or of the approved interface design, was not built
  ui_approved, ui_approved_at = _read_approval(note.parent / LevelDoc.UI_DESIGN)
  later = [ approved_at, *( [ ui_approved_at ] if ui_approved and ui_approved_at is not None else [] ) ]
  if build_at is not None and any(moment > build_at for moment in later):
    return MemberBuildState.REAPPROVED
  return MemberBuildState.BUILT


def defer_member(note: Path, version: str, *, repaint: bool = True) -> None:
  """
  Tag an asset the build did not carry, re-approved after it or never built, with this version and, when asked, set
  it awaiting the next release.

  Args:
    note: The asset's status note.
    version: The published version.
    repaint: Whether the asset is painted `awaiting-release`; False keeps the state its own coordinator painted.
  """
  text = note.read_text(encoding = _ENCODING)

  # a member whose change was never built keeps the state its own coordinator paints; only a built design waits
  if repaint:
    text = spec_frontmatter.set_scalar(text, SpecStateKey.STATE, AssetState.AWAITING_RELEASE)
  spec_paths.write_text_atomic(note, _add_version_tag(text, version))


def _add_version_tag(text: str, version: str) -> str:
  """
  Add a version's tag to a note's tags, keeping every tag it already carries.

  Args:
    text: The note's text.
    version: The published version.

  Returns:
    The text with the version's tag appended, unchanged when the tag is already there.
  """
  # the version's tag joins the tags the asset already carries, earlier release tags included: an asset shipped
  # again in a later release carries every version it changed in
  tags = spec_frontmatter.read_list(text, _TAGS_KEY)
  tag = release_version.render_version_tag(version)
  if tag not in tags:
    return spec_frontmatter.write_list(text, _TAGS_KEY, [ *tags, tag ])
  return text


def _find_all_folder_docs(release_note: Path) -> list[Path]:
  """
  List the markdown documents beside a release note.

  Args:
    release_note: The release's status note.

  Returns:
    The markdown files of the release folder itself, the note aside, sorted by name.
  """
  # only a markdown document beside the release note can be under review
  return [
      doc for doc in sorted(release_note.parent.iterdir())
      if doc != release_note and doc.suffix == _MD_SUFFIX and doc.is_file()
  ]


def _find_all_containers(folders: list[Path]) -> list[Path]:
  """
  List the container notes above the given folders.

  Args:
    folders: The folders whose containers count them.

  Returns:
    Every container note above any of the folders, each once, in the order first met.
  """
  # a container counting several folders is listed once
  return list(dict.fromkeys(container for folder in folders for container in flip_gate.containers_above(folder)))


def _refresh_containers(folders: list[Path]) -> list[Path]:
  """
  Refresh the stats region of every container note above the given folders.

  Args:
    folders: The release folder and the folders of the assets the publish wrote.

  Returns:
    The container notes whose content changed, each once, in the order first met.
  """
  changed: list[Path] = []
  for folder in folders:
    for container in flip_gate.containers_above(folder):
      # guard: a container an earlier folder already changed is listed once
      if container in changed:
        continue

      # a container whose region moved joins the publish commit
      if apply_container_stats(container):
        changed.append(container)
  return changed


def release_asset(note: Path, version: str, moment: str) -> None:
  """
  Mark one included asset as released by this version: ready for downstream consumers and painted done at once.

  Args:
    note: The asset's status note.
    version: The published version.
    moment: The ISO 8601 UTC moment the release happened.
  """
  text = note.read_text(encoding = _ENCODING)
  text = spec_frontmatter.set_scalar(text, Gate.RELEASED, _TRUE)
  text = spec_frontmatter.set_scalar(text, f"{Gate.RELEASED}{SpecMomentKey.AT_SUFFIX}", moment)
  text = spec_frontmatter.set_scalar(text, SpecStateKey.STATE, AssetState.DONE)
  spec_paths.write_text_atomic(note, _add_version_tag(text, version))


def publish(repo: Path, release_note: Path, *, today: str | None = None) -> dict:
  """
  Publish a built release: deploy to production when declared, then release its assets and freeze its version.

  A release whose build, merge, tests or settled code plan is not complete is refused.

  The release note itself is marked `spec_released` with its moment, which is what `spec_released` means on a
  release: published.

  Once the publish commit has landed, the release owner's level note is woken once (`release-published`) and so is
  every member the publish wrote. The wakes are best-effort: any failure finding or waking them only writes a line
  to stderr and never changes the publish outcome. A failed production deploy wakes neither the release owner nor the
  members, whose wakes run only after the publish commit has landed; it raises again only the `job-done` wake of
  every review whose stop cancelled a job or left no readable report.

  A product whose manifest version cannot be replaced in place is refused before anything runs. A failure after a
  successful production deploy and before the publish commit lands rolls back every other write, journals the deploy
  on the release note and commits that note alone; the re-raised exception carries `DEPLOYED_NOTE`.

  Guarantees:
    - A failed production deploy changes nothing but the release's `# History`: no included asset, the release's
      own frontmatter and the manifest keep their bytes.
    - A refused publish writes nothing: every file keeps its bytes. A release that reads `spec_rebuild_owed: true`,
      and one whose product declares a `staging` deploy target without a successful staging deploy of the release's
      current build, are refused.
    - A release whose product names a manifest whose version cannot be replaced in place is refused before any
      review is stopped and before any deploy runs; every file keeps its bytes.
    - A successful publish lands every write — the documents whose review it stopped, the included assets' notes, the
      release note, the manifest and the container notes whose stats region changed — in one commit under the
      publish bot identity, so no intermediate state is ever committed. The owner wake that follows, and anything its
      job later commits, are not part of that commit.
    - A member reading `spec_cancelled: true` keeps its bytes, never takes the version's tag and is reported under
      `cancelled`.
    - A member whose start document, or approved `ui-design.md`, was approved after the release's build moment —
      `spec_impl_build_at`, else `spec_build_at` — takes the version's tag but is not released and is reported under
      `reapproved`. Without either moment no approved member counts as re-approved.
    - A member whose start document is missing, not approved, or carries no `spec_approved_at` is treated the same
      way and reported under `unbuilt`, whatever the build moment.
    - A `reapproved` or `unbuilt` member keeps the `spec_state` its own coordinator painted, except a `reapproved`
      member whose note reads `spec_design_done: true`, which reads `awaiting-release`.
    - Every document of the release folder still under review has its review stopped before anything else is
      written; a stop that fails refuses the publish and every file keeps its bytes.
    - A stop that fails, a failed production deploy, and any exception after the stops and before the publish
      commit has landed give every stopped document, the failing one included, its bytes back and raise again the
      `job-done` wake of every review whose stop cancelled a job or left no readable report.
    - An exception raised while the publish writes, before its commit has landed, also restores every held file —
      the release note, the members, the manifest and the containers — and is re-raised; the one carve-out is the
      record of a succeeded production deploy, described next.
    - A production deploy that succeeded is never lost from the record when the publish then fails: the re-raised
      exception carries the note `DEPLOYED_NOTE`, and when the failure came before the publish commit landed, the
      deploy's `# History` line is appended to the restored release note and committed alone. A failure recording
      that line is only written to stderr and never replaces the exception.
    - An exception raised after the publish commit has landed restores no file and raises no wake: the committed
      tree stays as HEAD has it, and the exception is re-raised.
    - `assets` lists only the released members, and only those are counted in the History `published` line.
    - A successful publish wakes the release owner, when the release has one, exactly once and only after the
      publish commit has landed. A failed production deploy, or a refusal because a review could not be stopped,
      wakes neither the release owner nor any asset the release carries; it only raises again the `job-done` wake of
      every review whose stop cancelled a job or left no readable report. A refusal that comes before any review is
      stopped wakes nobody.
    - A failure of the owner wake never changes the publish outcome: the release stays published and is reported
      as published.

  Args:
    repo: Repository root — the deploy's working directory, the manifest's and the commit's root.
    release_note: The release's status note.
    today: Optional ISO date pinned into the moment stamped beside each released gate, the release's own included.

  Returns:
    `{"outcome": "published", "version", "assets", "reapproved", "unbuilt", "cancelled", "manifest"}` on success,
    the four lists holding repo-relative notes: the released members, the members tagged but left awaiting the next
    release because a later approval was not built, the members tagged but left awaiting it because their change
    was never built, and the cancelled members skipped; `{"outcome": "deploy-failed", "target", "exit_code", "log"}`
    when the production deploy failed, with only the release's `# History` written and committed;
    `{"outcome": "refused", "reason"}` when the release reads `spec_cancelled: true`, is already published, any of
    its `spec_built`, `spec_develop_done`, `spec_tests_passing` or `spec_plan_done` gates is not true, it
    reads `spec_rebuild_owed: true`, it carries no version, no product covers it, its product declares a `staging`
    deploy target and the release's current build has no successful last staging deploy, an included note is not on
    disk,
    the product's manifest version cannot be replaced in place, or a review in the release folder could not be
    stopped, the reason then naming that document. A refusal, like a failed deploy, gives every stopped document its
    bytes back; it wakes neither the release owner nor any member, and raises again only the `job-done` wake of every
    review whose stop cancelled a job or left no readable report, so a refusal that comes before any review is
    stopped wakes nobody.

  Raises:
    ValueError: If the settings file exists but cannot be read, is not valid JSON, not UTF-8 text or not a JSON
      object (a `spec_paths.SettingsError` naming the file), or an included note lies outside `repo`.
    VaultRootError: If the spec content root cannot be resolved: `spec.vault_root` is refused, or the settings file
      cannot be read as a JSON object.
    RuntimeError: If the history verb refuses to journal a line on the release note.
    subprocess.CalledProcessError: If staging or committing the publish fails.
    OSError: If a note or the manifest cannot be read or written.
    Exception: Any other failure while the deploy runs or the publish writes, raised again once every stopped review
      and held file is put back.
  """

  # Contract:
  # When the production deploy fails, the only file this function writes is the release note, and only its
  # `# History` section: every included asset's note, the release's frontmatter and the manifest MUST keep their
  # bytes. When the publish succeeds, every file it writes MUST land in the one commit it makes, in a repository:
  # the documents whose review it stopped, the included notes, the release note, the manifest and every container
  # note above the release folder or a written member whose stats region changed; no write of a successful publish
  # is left for a later commit. The owner wake that follows the commit, and anything the job it starts later
  # commits, are outside that commit and are not writes of the publish.

  # Contract:
  # A refused publish writes nothing: a cancelled, already published, unbuilt (`spec_built`, `spec_develop_done`
  # or `spec_tests_passing` not true, or `spec_plan_done` not true), rebuild-owing (`spec_rebuild_owed: true`),
  # versionless or uncovered release, a release whose product declares a `staging` deploy target without a
  # successful staging deploy of the release's current build, a release with an included note missing from disk,
  # and a release with a review that could not be stopped, keep every byte of every file.

  # Contract:
  # A release whose product names a manifest whose version cannot be replaced in place (unknown format, invalid
  # content, or no single top-level string version) is refused before any review is stopped and before any deploy
  # runs, so no production deploy ever precedes a publish that would fail on the manifest; every file keeps its
  # bytes.

  # Contract:
  # A member note reading `spec_cancelled: true` is skipped: it keeps its bytes, never takes the version's tag, and
  # is reported under `cancelled`, not under `assets`.

  # Contract:
  # A member whose start document, or approved `ui-design.md`, was approved after the release's build moment
  # (`spec_impl_build_at`, else `spec_build_at`) receives the version's tag but is NOT marked released; it is
  # reported under `reapproved`. A member whose start document is missing, not approved, or carries no approval
  # moment is treated the same and reported under `unbuilt`, with or without a build moment.
  # Without a build moment no approved member counts as re-approved.

  # Contract:
  # A `reapproved` or `unbuilt` member keeps the `spec_state` its own coordinator painted: the publish NEVER
  # rewrites it, except for a `reapproved` member whose note reads `spec_design_done: true`, which is painted
  # `awaiting-release`.

  # Contract:
  # Every document of the release folder under review has its review stopped before any other write, and the
  # stopped documents ride the publish commit; a stop that fails refuses the publish with every file at its bytes.

  # Contract:
  # Reviews stopped by a publish that does not land are put back: a stop that fails, a failed production deploy, or
  # an exception after the stops and before the publish commit has landed gives every stopped document, the failing
  # one included, its bytes back and raises again the `job-done` wake of every review whose stop cancelled a job or
  # left no readable report.

  # Contract:
  # An exception raised while the publish writes, before its commit has landed, restores every file it holds — the
  # release note, the members, the manifest and the containers above them — to its bytes from before the call, and
  # is re-raised. The one carve-out is the record of a succeeded production deploy, which the release note then
  # carries as described in the next contract.

  # Contract:
  # A production deploy that succeeded is never lost from the record when the publish then fails: the re-raised
  # exception carries the note `DEPLOYED_NOTE`, and when the failure came before the publish commit landed, the
  # deploy's `# History` line is appended to the restored release note and committed alone. A failure recording that
  # line is only written to stderr and never replaces the exception.

  # Contract:
  # An exception raised after the publish commit has landed restores no file and raises no wake: the committed tree
  # stays as HEAD has it, and the exception is re-raised.

  # Contract:
  # `assets` lists only the members the publish released, and only those are counted in the History `published`
  # line; cancelled, re-approved and unbuilt members are listed under their own keys.

  # Domain(spec.lifecycle):
  # # What a publish carries
  # Only a built release is published: its code is merged, its tests pass and its build is done. A cancelled release
  # is abandoned and a published one is frozen, so neither is published. A published release carries every member
  # except a cancelled one: an abandoned member ships nothing, takes no version tag and is not counted among the
  # members the release shipped. A release that owes a rebuild is not published either, because its build no
  # longer matches what it carries; and neither is a release of a product with a staging target whose current
  # build has no successful last staging deploy, because that build never reached the place it is checked in.
  # A release whose manifest version cannot be moved to the release's version is refused before anything is
  # deployed, so that production is never deployed for a publish that could not land. A production deploy that ran
  # stays on record in the release's journal even when the publish then fails, so the next publish never deploys
  # again without a trace.
  # A publish also ends the review of every document in the release folder, so that nothing is still being written
  # into what ships. A publish that does not land, because it is refused, because its production deploy fails or
  # because it fails part-way before the publish commit has landed, leaves those reviews exactly as they were, and
  # every review whose stop cancelled a job, or left no readable report to rule that out, has its wake raised again
  # so it carries on, once its document is back as it was; a review whose stop plainly cancelled nothing is not
  # woken. That holds for the review whose own stop failed as well: a refused publish wakes it when its report shows
  # a cancelled job or cannot be read. A refusal that comes before any review is stopped has none to wake. A failed
  # production deploy publishes nothing and does not wake the product that owns releases; the same reviews, and only
  # those, are woken again.
  # A failure after the publish commit has landed puts nothing back: the
  # published state stands and the failure is reported.

  # Contract:
  # A successful publish wakes the release owner, when the release has one, exactly once and only after the
  # publish commit has landed. A publish whose production deploy failed, or that was refused because a review could
  # not be stopped, wakes neither the release owner nor any asset the release carries; the only wakes it raises are
  # the `job-done` wakes of the reviews whose stop cancelled a job or left no readable report to rule that out. A
  # refusal that comes before any review is stopped wakes nobody.

  # Contract:
  # A failure of the owner wake NEVER changes the publish outcome: the release stays published and the result
  # is still reported as published.

  # the release note's own state decides whether there is anything to publish
  text = release_note.read_text(encoding = _ENCODING)
  fm_values, _end = spec_frontmatter.parse(text)
  version = fm_values.get(ReleaseKey.VERSION, "").strip()

  # guard: a cancelled release is abandoned, never published
  if flip_gate.is_true(fm_values, Gate.SPEC_CANCELLED):
    return _create_refusal(_MSG_CANCELLED)

  # guard: a published release is frozen
  if flip_gate.is_true(fm_values, Gate.RELEASED):
    return _create_refusal(_MSG_PUBLISHED)

  # guard: the release ladder itself must have reached built — the merged code, the passing tests, the build and
  # the settled code plan, which a rollback can take back into review after the build gates re-closed
  for gate in ( Gate.BUILT, Gate.DEVELOP_DONE, Gate.TESTS_PASSING, Gate.PLAN_DONE ):
    if not flip_gate.is_true(fm_values, gate):
      return _create_refusal(f"release's {gate} is not true")

  # guard: a release that owes a rebuild ships a build that no longer matches what it carries
  if flip_gate.is_true(fm_values, ReleaseKey.REBUILD_OWED):
    return _create_refusal(_MSG_REBUILD_OWED)

  # guard: no version, no tag to put on anything
  if not version:
    return _create_refusal(f"release carries no {ReleaseKey.VERSION}")

  # the product record names the deploy targets and the manifest
  vault = spec_paths.find_settings_root(release_note.resolve().parent)
  _key, record = resolve_product.effective_record_by_path(
      vault, release_note.resolve().relative_to(vault).as_posix())

  # guard: rejects a release note that no product covers
  if record is None:
    return _create_refusal(_MSG_NO_PRODUCT)

  # the build the release carries, the one its staging deploy must have reached
  build = str(fm_values.get(ReleaseKey.BUILD, "")).strip().strip("\"'")

  # guard: a build with no successful last staging deploy never reached the target its tests run against
  if release_deploy.find_target_config(record, ReleaseConfigKey.STAGING) is not None \
      and not is_staging_deploy_succeeded(text, build):
    return _create_refusal(f"{_MSG_STAGING_NOT_DEPLOYED} {build}".rstrip())

  # the included notes the release names, and those of them no longer on disk
  assets = release_delta.resolve_included_notes(vault, text)
  missing = [ note for note in assets if not note.is_file() ]

  # guard: every included note must be on disk before anything irreversible runs — a renamed or deleted asset
  # refuses the publish rather than failing it after production has been deployed
  if missing:
    return _create_refusal(
        f"included note is missing: {missing[0].resolve().relative_to(repo.resolve()).as_posix()}")

  # the manifest the product names takes the version, so its version field must be replaceable before production
  release_section = record.get(ReleaseConfigKey.SECTION) or {}
  manifest = release_section.get(ReleaseConfigKey.MANIFEST, "") if isinstance(release_section, dict) else ""

  # guard: a manifest whose version cannot be replaced would fail the publish only after production was deployed
  if manifest:
    try:
      release_version.render_manifest_version(repo / manifest, version)
    except (ValueError, OSError) as error:
      return _create_refusal(f"manifest {manifest}: {error}")

  # every review still running in the release folder stops before anything else is written: a frozen release takes
  # no further rounds, and a stop that fails refuses the publish with every review taken back
  halt = review_halt.ReviewHalt()

  # guard: a review that cannot be stopped would keep rewriting a frozen release
  if not halt.stop(_find_all_folder_docs(release_note)):
    halt.rollback()
    return _create_refusal(f"{halt.failed_doc.name if halt.failed_doc else ''}: {halt.failure}")

  # the production deploy comes next: any exception before it ends takes the stopped reviews back
  lines: list[str] = []
  # noinspection PyBroadException
  try:
    deployed = _deploy_production(repo, release_note, record)
  # waiver: the rollback boundary catches every exception on purpose, an interrupt included — a stopped review
  # must never stay stopped over a deploy that did not end, and the exception is re-raised unchanged
  except BaseException:
    halt.rollback()
    raise

  # a product with a production target journals its deploy; a failed one leaves the release unpublished
  if deployed is not None:
    result, summary, line = deployed

    # a failed deploy publishes nothing: the stopped reviews are taken back and only its journal line lands
    if not result.ok:
      halt.rollback()
      history_journal.append_to_file(release_note, line, today, repo = repo)
      release_version.commit_paths(repo, [ release_note ], author = PUBLISH_NAME,
                                   subject = f"{PUBLISH_NAME}: production deploy of {version} failed")
      return {
          _OUTCOME: _OUTCOME_DEPLOY_FAILED, _TARGET: result.target, _EXIT_CODE: result.exit_code,
          _LOG: summary[_LOG],
      }
    lines.append(line)

  # every file the publish writes is held, so a failure part-way gives each its bytes back and the stopped reviews
  # their wakes
  # noinspection PyBroadException
  try:
    halt.keep([ release_note, *assets, *( [ repo / manifest ] if manifest else [] ),
                *_find_all_containers([ release_note.parent, *( note.parent for note in assets ) ]) ])
    halt.hold_head(repo)

    # a cancelled member is abandoned and ships nothing; a member re-approved after the build ships its built
    # design but stays unreleased; every other carried asset is released by this version
    moment = _format_moment(today)
    build_at = find_build_moment(fm_values)
    cancelled: list[Path] = []
    reapproved: list[Path] = []
    unbuilt: list[Path] = []
    released: list[Path] = []
    for note in assets:
      if flip_gate.is_true(spec_frontmatter.parse(note.read_text(encoding = _ENCODING))[0], Gate.SPEC_CANCELLED):
        cancelled.append(note)
        continue

      # a member the build did not carry is tagged and waits; a built one is released
      build_state = read_member_build_state(vault, note, build_at)
      if build_state == MemberBuildState.BUILT:
        release_asset(note, version, moment)
        released.append(note)
        continue
      member_fm = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))[0]
      defer_member(note, version, repaint = build_state == MemberBuildState.REAPPROVED
                   and flip_gate.is_true(member_fm, Gate.DESIGN_DONE))
      ( reapproved if build_state == MemberBuildState.REAPPROVED else unbuilt ).append(note)

    # the manifest takes the version when the product names one
    touched = [ release_note, *halt.stopped, *reapproved, *unbuilt, *released ]
    if manifest:
      release_version.write_manifest_version(repo / manifest, version)
      touched.append(repo / manifest)

    # the release is marked released last and journals the publish — the one write that ends its open state
    released_text = spec_frontmatter.set_scalar(text, Gate.RELEASED, _TRUE)
    released_text = spec_frontmatter.set_scalar(released_text, f"{Gate.RELEASED}{SpecMomentKey.AT_SUFFIX}", moment)
    spec_paths.write_text_atomic(release_note, released_text)
    lines.append(note_explainers.history_line(release_note, HistoryEvent.PUBLISHED, version = version,
                                              count = str(len(released))))
    for line in lines:
      history_journal.append_to_file(release_note, line, today, repo = repo)

    # every container counting the release or a written member reads the new states in the same commit
    written_members = [ *reapproved, *unbuilt, *released ]
    touched.extend(_refresh_containers([ release_note.parent, *( note.parent for note in written_members ) ]))

    # one commit carries the whole publish
    release_version.commit_paths(repo, touched, author = PUBLISH_NAME,
                                 subject = f"{PUBLISH_NAME}: {version} published from {release_note.parent.name}")
  # waiver: the rollback boundary catches every exception on purpose, an interrupt included — a write must never
  # outlive a publish commit that did not land, and the exception is re-raised unchanged
  except BaseException as error:
    # a failure before the publish commit takes every write back; one after it leaves the committed tree alone
    restored = halt.rollback_uncommitted()
    if not restored:
      sys.stderr.write(f"{_PUBLISH_LOG}: failed after the publish commit landed, nothing restored\n")

    # a production deploy that ran stays on record, so the next publish never deploys it again unseen
    if deployed is not None:
      if restored:
        _record_deploy(repo, release_note, deployed[2], version, today)
      error.add_note(DEPLOYED_NOTE)
    raise

  # the owner's level coordinator is told once the publish has landed, so it can rehang `Start release` and rewrite
  # its brief; best-effort, a failing wake never undoes or fails the publish
  try:
    coordinator_dispatch.wake_release_owner_on_publish(repo, release_note.parent, today = today)
  # waiver: the publish is already committed — no failure finding or waking the owner may change its outcome
  except Exception as error:
    sys.stderr.write(f"{_PUBLISH_LOG}: owner wake failed after the publish: {error}\n")

  # every member the publish wrote is told once, so its brief follows the state the publish painted on it
  try:
    coordinator_dispatch.wake_release_members(repo, written_members, today = today)
  # waiver: the publish is already committed — no failure waking a member may change its outcome
  except Exception as error:
    sys.stderr.write(f"{_PUBLISH_LOG}: member wake failed after the publish: {error}\n")

  # the published outcome: the version, the assets it carried and the manifest written for it
  return {
      _OUTCOME: _OUTCOME_PUBLISHED, _VERSION: version, _ASSETS: _to_relative(repo, released),
      _REAPPROVED: _to_relative(repo, reapproved), _UNBUILT: _to_relative(repo, unbuilt),
      _CANCELLED: _to_relative(repo, cancelled), _MANIFEST: manifest,
  }


def _record_deploy(repo: Path, release_note: Path, line: str, version: str, today: str | None) -> None:
  """
  Journal a production deploy whose publish failed, and commit the release note alone.

  Notes:
    - A failure journaling or committing the line writes one line to stderr and is not raised.

  Args:
    repo: Repository root.
    release_note: The release's status note, its bytes as they were before the publish.
    line: The deploy's `# History` line.
    version: The version that was deployed.
    today: Optional ISO date pinned as the line's day group.
  """
  # the line lands on the restored note and is committed alone
  try:
    history_journal.append_to_file(release_note, line, today, repo = repo)
    release_version.commit_paths(repo, [ release_note ], author = PUBLISH_NAME,
                                 subject = f"{PUBLISH_NAME}: production deploy of {version} recorded")
  # waiver: the publish is already failing — a failure recording its deploy is reported, never raised over it
  except Exception as error:
    sys.stderr.write(f"{_PUBLISH_LOG}: recording the production deploy failed: {error}\n")


def _deploy_production(repo: Path, release_note: Path,
                       record: dict) -> tuple[release_deploy.DeployResult, dict, str] | None:
  """
  Run the product's production deploy target, when it names one.

  Notes:
    - Runs the target's command and writes its log under the deploy log directory.

  Args:
    repo: Repository root.
    release_note: The release's status note.
    record: The product record naming the deploy targets.

  Returns:
    The deploy's result, its JSON summary and the `# History` line it leaves; None when the product names no
    production target.
  """

  # guard: a product without a production target has nothing to deploy
  if release_deploy.find_target_config(record, ReleaseConfigKey.PRODUCTION) is None:
    return None

  # the target runs once, and its outcome is rendered for the result and the journal
  result = release_deploy.run_target(repo, record, ReleaseConfigKey.PRODUCTION,
                                     log_dir = repo / release_deploy.LOG_DIR)
  summary = release_deploy.to_dict(repo, result)
  return result, summary, release_deploy.render_history_line(release_note, result, summary[_LOG])


def _to_relative(repo: Path, notes: list[Path]) -> list[str]:
  """
  Render notes as repo-relative POSIX paths.

  Args:
    repo: Repository root.
    notes: Notes inside the repository.

  Returns:
    One repo-relative path per note, in the given order.
  """
  return [ note.resolve().relative_to(repo.resolve()).as_posix() for note in notes ]


def main(argv: list[str]) -> int:
  """
  Publish a release from the command line; `--today` pins the moment stamped beside each released gate.

  The repository root comes from the `LAZY_REPO_ROOT` environment variable, falling back to the process working
  directory.

  Guarantees:
    - An exception raised by the publish is printed as one JSON object `{"outcome": "error", "reason"}` and ends
      with exit code 2; one that carries the note `DEPLOYED_NOTE` adds `"deployed": true`; a refusal and a failed
      deploy end with exit code 1, and a publish with 0.

  Notes:
    - Prints the JSON result of `publish` on stdout.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 when published, 1 on a refusal or a failed deploy, 2 when the note does not exist or the publish
    raised, the latter printing `{"outcome": "error", "reason"}`, plus `"deployed": true` when the production deploy
    had succeeded before the failure.
  """

  # Contract:
  # An exception raised by the publish is printed on stdout as the JSON object `{"outcome": "error", "reason"}` and
  # ends the run with exit code 2, so a caller always reads JSON; an exception that carries the note
  # `DEPLOYED_NOTE` adds `"deployed": true`, so a caller learns that production was deployed. A refusal or a failed
  # production deploy ends the run with exit code 1, and only a published release with 0.

  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs release-publish")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("note")
  # waiver: argparse CLI signature -- option name
  parser.add_argument("--today", default = None)
  args = parser.parse_args(argv)
  repo = scaffold_asset.repo_root(Path(os.environ.get(_ENV_REPO_ROOT) or Path.cwd()))
  note = (repo / args.note).resolve()

  # guard: the note names the release; nothing to publish without it
  if not note.is_file():
    sys.stderr.write(f"no such note: {note}\n")
    return 2

  # the publish's result goes to stdout whole; a failure is reported in the same shape, so a caller always reads JSON
  try:
    result = publish(repo, note, today = args.today)
  # waiver: the CLI boundary — every failure of the publish is reported as an `error` outcome with exit 2
  except Exception as error:
    failure: dict = { _OUTCOME: _OUTCOME_ERROR, _REASON: f"{type(error).__name__}: {error}" }
    if DEPLOYED_NOTE in getattr(error, "__notes__", ()):
      failure[_DEPLOYED] = True
    print(json.dumps(failure))
    return 2
  print(json.dumps(result))
  return 0 if result[_OUTCOME] == _OUTCOME_PUBLISHED else 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
