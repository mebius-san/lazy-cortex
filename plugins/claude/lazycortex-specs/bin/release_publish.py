"""
Logic behind the `lazycortex-specs release-publish <release-note>` verb — the `Publish` tick of a release.

Publishing freezes a built release, one whose `spec_built` gate is true: when the product declares a `production`
deploy target, the release is deployed there first and a failure changes nothing but the release's journal; on
success every asset the release carries is released, stamped and tagged with the version, the release note itself is
marked `spec_released` with its moment, the product's manifest takes the version, and the whole set lands in one
commit under the verb's bot identity. Once that commit has landed, the
release owner's level note is woken once (`release-published`), best-effort: any failure finding or waking the owner
only writes a line to stderr and never changes the publish outcome, and a failed deploy wakes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import coordinator_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import release_deploy  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import release_version  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    AssetState, Gate, HistoryEvent, ReleaseConfigKey, ReleaseKey, SpecMomentKey, SpecStateKey,
)


_ENCODING = "utf-8"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"
_TAGS_KEY = "tags"
_WIKILINK_OPEN = "[["
_WIKILINK_CLOSE = "]]"
_WIKILINK_DISPLAY = "|"
_WIKILINK_ANCHOR = "#"
_TRUE = "true"
_MOMENT_MIDNIGHT = "T00:00:00Z"
_UTC_OFFSET = "+00:00"
_UTC_SUFFIX = "Z"

# The bot identity the publish commit is authored under
PUBLISH_NAME = "lazy-spec.release-publish"

# Refusal messages
_MSG_PUBLISHED = "release is already published"
_MSG_NO_PRODUCT = "no product covers the release note"

# Result keys and values
_OUTCOME = "outcome"
_REASON = "reason"
_OUTCOME_REFUSED = "refused"
_OUTCOME_DEPLOY_FAILED = "deploy-failed"
_OUTCOME_PUBLISHED = "published"
_VERSION = "version"
_ASSETS = "assets"
_MANIFEST = "manifest"
_TARGET = "target"
_EXIT_CODE = "exit_code"
_LOG = "log"


def _refusal(reason: str) -> dict:
  """
  Build a refusal result.

  Args:
    reason: Why nothing was published.

  Returns:
    `{"outcome": "refused", "reason": <reason>}`.
  """
  return { _OUTCOME: _OUTCOME_REFUSED, _REASON: reason }


def _moment(today: str | None) -> str:
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


def resolve_included_notes(vault: Path, release_text: str) -> list[Path]:
  """
  Resolve the status notes a release's `spec_includes` links to.

  Args:
    vault: The vault root holding `.claude/lazy.settings.json`.
    release_text: The release note's text.

  Returns:
    One note path per wikilink, in the order listed; display text and anchors are ignored.
  """
  notes: list[Path] = []
  for link in spec_frontmatter.read_list(release_text, ReleaseKey.INCLUDES):
    target = link.removeprefix(_WIKILINK_OPEN).removesuffix(_WIKILINK_CLOSE)
    target = target.split(_WIKILINK_DISPLAY, 1)[0].split(_WIKILINK_ANCHOR, 1)[0].strip()
    notes.append(spec_paths.resolve_wikilink(target, vault))
  return notes


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

  # the version's tag joins the tags the asset already carries, earlier release tags included: an asset shipped
  # again in a later release carries every version it changed in
  tags = spec_frontmatter.read_list(text, _TAGS_KEY)
  tag = release_version.version_tag(version)
  if tag not in tags:
    text = spec_frontmatter.write_list(text, _TAGS_KEY, [ *tags, tag ])
  spec_paths.write_text_atomic(note, text)


def publish(repo: Path, release_note: Path, *, today: str | None = None) -> dict:
  """
  Publish a built release: deploy to production when declared, then release its assets and freeze its version.

  The release note itself is marked `spec_released` with its moment, which is what `spec_released` means on a
  release: published.

  Once the publish commit has landed, the release owner's level note is woken once (`release-published`).
  The wake is best-effort: any failure finding or waking the owner only writes a line to stderr and never
  changes the publish outcome. A failed production deploy wakes nothing.

  Guarantees:
    - A failed production deploy changes nothing but the release's `# History`: no included asset, the release's
      own frontmatter and the manifest keep their bytes.
    - A successful publish lands every write — the included assets' notes, the release note and the manifest — in
      one commit under the publish bot identity, so no intermediate state is ever committed. The owner wake that
      follows, and anything its job later commits, are not part of that commit.
    - A successful publish wakes the release owner, when the release has one, exactly once and only after the
      publish commit has landed; a failed production deploy or a refusal wakes nobody.
    - A failure of the owner wake never changes the publish outcome: the release stays published and is reported
      as published.

  Args:
    repo: Repository root — the deploy's working directory, the manifest's and the commit's root.
    release_note: The release's status note.
    today: Optional ISO date pinned into the moment stamped beside each released gate, the release's own included.

  Returns:
    `{"outcome": "published", "version", "assets": [repo-relative notes], "manifest"}` on success;
    `{"outcome": "deploy-failed", "target", "exit_code", "log"}` when the production deploy failed, with only the
    release's `# History` written and committed; `{"outcome": "refused", "reason"}` when the release's own
    `spec_built` gate is not true, the release is already published, carries no version, no product covers it, or an
    included note is not on disk.

  Raises:
    ValueError: If the settings file is not valid JSON, the product's manifest has an unknown format or no version
      field to replace, or an included note lies outside `repo`.
    RuntimeError: If the history verb refuses to journal a line on the release note.
    subprocess.CalledProcessError: If staging or committing the publish fails.
    OSError: If a note, the settings file or the manifest cannot be read or written.
  """

  # Contract:
  # When the production deploy fails, the only file this function writes is the release note, and only its
  # `# History` section: every included asset's note, the release's frontmatter and the manifest MUST keep their
  # bytes. When the publish succeeds, every file it writes MUST land in the one commit it makes, in a repository;
  # no write of a successful publish is left for a later commit. The owner wake that follows the commit, and
  # anything the job it starts later commits, are outside that commit and are not writes of the publish.

  # Contract:
  # A successful publish wakes the release owner, when the release has one, exactly once and only after the
  # publish commit has landed. A publish whose production deploy failed, or that was refused, wakes nobody.

  # Contract:
  # A failure of the owner wake NEVER changes the publish outcome: the release stays published and the result
  # is still reported as published.

  # the release note's own state decides whether there is anything to publish
  text = release_note.read_text(encoding = _ENCODING)
  fm_values, _end = spec_frontmatter.parse(text)
  version = fm_values.get(ReleaseKey.VERSION, "").strip()

  # guard: the release ladder itself must have reached built — an accepted test report and the merged build
  if not flip_gate.is_true(fm_values, Gate.BUILT):
    return _refusal(f"release's {Gate.BUILT} is not true")

  # guard: a published release is frozen
  if flip_gate.is_true(fm_values, Gate.RELEASED):
    return _refusal(_MSG_PUBLISHED)

  # guard: no version, no tag to put on anything
  if not version:
    return _refusal(f"release carries no {ReleaseKey.VERSION}")

  # the product record names the deploy targets and the manifest
  vault = spec_paths.find_settings_root(release_note.resolve().parent)
  _key, record = resolve_product.effective_record_by_path(
      vault, release_note.resolve().relative_to(vault).as_posix())

  # guard: rejects a release note that no product covers
  if record is None:
    return _refusal(_MSG_NO_PRODUCT)

  # guard: every included note must be on disk before anything irreversible runs — a renamed or deleted asset
  # refuses the publish rather than failing it after production has been deployed
  assets = resolve_included_notes(vault, text)
  missing = [ note for note in assets if not note.is_file() ]
  if missing:
    return _refusal(f"included note is missing: {missing[0].resolve().relative_to(repo.resolve()).as_posix()}")

  # the production deploy comes first: its failure leaves the release unpublished with one journal line
  lines: list[str] = []
  if release_deploy.find_target_config(record, ReleaseConfigKey.PRODUCTION) is not None:
    result = release_deploy.run_target(repo, record, ReleaseConfigKey.PRODUCTION,
                                       log_dir = repo / release_deploy.LOG_DIR)
    summary = release_deploy.to_dict(repo, result)
    line = release_deploy.render_history_line(release_note, result, summary[_LOG])
    if not result.ok:
      history_journal.append_to_file(release_note, line, today, repo = repo)
      release_version.commit_paths(repo, [ release_note ], author = PUBLISH_NAME,
                                   subject = f"{PUBLISH_NAME}: production deploy of {version} failed")
      return {
          _OUTCOME: _OUTCOME_DEPLOY_FAILED, _TARGET: result.target, _EXIT_CODE: result.exit_code,
          _LOG: summary[_LOG],
      }
    lines.append(line)

  # every carried asset is released by this version; each write is idempotent, so a publish interrupted before
  # the release note's own write below can simply run again
  moment = _moment(today)
  for note in assets:
    release_asset(note, version, moment)

  # the manifest takes the version when the product names one
  release_section = record.get(ReleaseConfigKey.SECTION) or {}
  manifest = release_section.get(ReleaseConfigKey.MANIFEST, "") if isinstance(release_section, dict) else ""
  touched = [ release_note, *assets ]
  if manifest:
    release_version.write_manifest_version(repo / manifest, version)
    touched.append(repo / manifest)

  # the release is marked released last and journals the publish — the one write that ends the release's open state
  released_text = spec_frontmatter.set_scalar(text, Gate.RELEASED, _TRUE)
  released_text = spec_frontmatter.set_scalar(released_text, f"{Gate.RELEASED}{SpecMomentKey.AT_SUFFIX}", moment)
  spec_paths.write_text_atomic(release_note, released_text)
  lines.append(note_explainers.history_line(release_note, HistoryEvent.PUBLISHED, version = version,
                                            count = str(len(assets))))
  for line in lines:
    history_journal.append_to_file(release_note, line, today, repo = repo)

  # one commit carries the whole publish
  release_version.commit_paths(repo, touched, author = PUBLISH_NAME,
                               subject = f"{PUBLISH_NAME}: {version} published from {release_note.parent.name}")

  # the owner's level coordinator is told once the publish has landed, so it can rehang `Start release` and rewrite
  # its brief; best-effort, a failing wake never undoes or fails the publish
  try:
    coordinator_dispatch.wake_release_owner_on_publish(repo, release_note.parent, today = today)
  # waiver: the publish is already committed — no failure finding or waking the owner may change its outcome
  except Exception as error:
    sys.stderr.write(f"release-publish: owner wake failed after the publish: {error}\n")

  # the published outcome: the version, the assets it carried and the manifest written for it
  return {
      _OUTCOME: _OUTCOME_PUBLISHED, _VERSION: version,
      _ASSETS: [ note.resolve().relative_to(repo.resolve()).as_posix() for note in assets ], _MANIFEST: manifest,
  }


def main(argv: list[str]) -> int:
  """
  Publish a release from the command line; `--today` pins the moment stamped beside each released gate.

  The repository root comes from the `LAZY_REPO_ROOT` environment variable, falling back to the process working
  directory.

  Notes:
    - Prints the JSON result of `publish` on stdout.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 when published, 1 on a refusal or a failed deploy, 2 when the note does not exist.
  """
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
  result = publish(repo, note, today = args.today)
  print(json.dumps(result))
  return 0 if result[_OUTCOME] == _OUTCOME_PUBLISHED else 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
