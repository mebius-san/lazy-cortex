"""Writer dispatch for review documents, backing the `dispatch-writer` verb of the review CLI.

One call builds the whole core `dispatch-job` bundle for one expert turn on one review document: the request
payload, the source view, the context files, the result file, the protocols, and the dedup key of a section
writer. The document's `active_job` runtime marker is written before the job is queued through the core CLI, so
the job's completion wakes the coordinator.

The module also exposes the two body views a writer is handed: the body with its edit markup untouched, and the
body with the markup resolved.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Sequence


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import review_locator as _review_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import body as _body  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import collect_ops as _collect_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
import coordinator_dispatch as _coordinator_dispatch  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import core_settings as _core_settings  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import decisions_context as _decisions_context  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import doc_class as _doc_class  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import edit_markup as _edit_markup  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import finalize as _finalize  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import guidelines_context as _guidelines_context  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import job_markers as _job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import parser as _parser  # noqa: E402  # pylint: disable=wrong-import-position,deprecated-module,import-error
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import payload as _payload  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import structure_repair as _structure_repair  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from errors import (  # noqa: E402
    DispatchQueueError, DispatchRefusalError, JobConsumeError, ParseError, QueueAnswerError, SettingsReadError,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    Bucket, JobFile, JobKey, JobMarker, JobStatus, Kind, Outcome, Phase, ReviewKey, ReviewProtocol,
)


# The bundle fields that carry content existing in no file, keyed by the file name it becomes.
_SOURCE_INLINE = "source_inline"
_CONTEXT_INLINE = "context_inline"

# The bundle field that sets the commit right of one job, overriding the expert's default.
_CAN_COMMIT_IN_REPO = "can_commit_in_repo"

# The job-directory buckets a payload path starts with.
_SOURCE_DIR = "source/"
_CONTEXT_DIR = "context/"
_RESULT_DIR = "result/"

# The request field naming the decisions registries by repo-relative path; the same name the spec plugin's
# dispatches use, so one expert protocol reads both.
_DECISIONS_KEY = "decisions"
# The payload key naming the plugin canon guideline files the expert reads in place, by absolute path.
_GUIDELINES_KEY = "guidelines"

# The context file a repair job finds its structural defect report under.
_DEFECTS_FILE = "structure-defects.json"

# The warning a repair dispatch reports when the structural defect report could not be produced, filled with the
# failure that stopped it.
DEFECTS_UNAVAILABLE_TEMPLATE = "structure defects unavailable: {error}"

# The warning a main dispatch reports for a frontmatter value naming no file, filled with the key and the value.
_FRONTMATTER_UNRESOLVED_TEMPLATE = "frontmatter {key}: {value!r} names no file in the repository"

# The warning a main dispatch reports when a refused spec content root leaves frontmatter values resolved against the
# repository root alone, filled with the refusal.
_FRONTMATTER_ROOT_REFUSED_TEMPLATE = "frontmatter context resolved against the repository root only: {error}"

# The warning a main dispatch reports for one non-empty stderr line of a class verb that answered, filled with the
# entry's file name and the line.
_VERB_WARNING_TEMPLATE = "verb for {name}: {line}"

# The refusal of a main dispatch whose class verb exited non-zero, filled with the entry's file name, the exit code,
# the command and the verb's own error text.
_VERB_FAILED_TEMPLATE = "verb for {name} exited {code}: {command}: {error}"

# The reason a refusal names for a failed class verb that printed no reason of its own.
_VERB_NO_REASON = "the verb gave no reason"

# The prefix every plugin CLI a class may run carries, and the one placeholder an argument may hold, standing for
# the document's repo-relative path.
_PLUGIN_CLI_PREFIX = "lazycortex-"
_DOC_PLACEHOLDER = "{doc}"

# How long one verb of a class may run before the dispatch is refused.
_VERB_TIMEOUT_SECONDS: float = 60

# The text codec of a verb's output and the decode-error mode that keeps a stray byte from failing the read.
_VERB_ENCODING = "utf-8"
_VERB_DECODE_ERRORS = "replace"

# The key of a failed verb's JSON answer that carries its own reason.
_VERB_ERROR_KEY = "error"

# The settings section that names the spec content root.
_SPEC_SECTION = "spec"

# The wikilink brackets a frontmatter value may be wrapped in.
_WIKILINK_OPEN = "[["
_WIKILINK_CLOSE = "]]"

# The only document suffix the review loop works on, and the suffix a section writer's result file takes.
_MARKDOWN_SUFFIX = ".md"

# The frontmatter literal of a document inside the review loop.
_ACTIVE_LITERAL = "true"

# The round a repair job reports when the broken frontmatter yields none.
_NO_ROUND = 0

# The two statuses the verb reports, the second being core's own dedup-hit token.
_STATUS_DISPATCHED = "dispatched"
_STATUS_QUEUED = "already-queued"

# The output field saying whether the document's job marker was put back after a failure that followed its write.
_MARKER_RESTORED = "marker_restored"

# The verb's exit codes: queued, the queue call failed, the request was refused.
_EXIT_OK = 0
_EXIT_FAILED = 1
_EXIT_REFUSED = 2

# The CLI's program name and argument spellings.
_PROG = "lazycortex-review dispatch-writer"
_ARG_FILE = "file"
_ARG_EXPERT = "expert"
_ARG_SECTION_ID = "--section-id"
_ARG_SECTION = "--section"
_ARG_POSITION = "--position"
_ARG_CONTEXT = "--context"
_ARG_REPAIR = "--repair"
_ARG_REPO = "--repo"
_POSITIONS = ( "top", "bottom" )
_APPEND = "append"
_STORE_TRUE = "store_true"


def read_body_view(file_path: Path) -> str:
  """
  Return a review document's body without its frontmatter.

  The edit markup stays exactly as written in the document.

  Args:
    file_path: The review document.

  Returns:
    The document text after the frontmatter block.

  Raises:
    ParseError: If the frontmatter fence is not closed.
  """
  # the body half alone, edit markup exactly as written
  _meta, body = _fm.parse(file_path.read_text(encoding = "utf-8"))
  return body


def read_resolved_body_view(file_path: Path) -> str:
  """
  Return a review document's body with its edit markup resolved.

  The markup is resolved per the edit-marker style the document pins. A document pinning an unknown style
  yields the raw body instead.

  Args:
    file_path: The review document.

  Returns:
    The body without frontmatter, with the edit markup resolved, or the raw body when the style is unknown.

  Raises:
    ParseError: If the frontmatter fence is not closed.
  """
  # split the document once — only the body half reaches the writer
  body = read_body_view(file_path)

  # resolve the body's edit markup per the document's pinned style; an unknown style must not
  # kill the dispatch — `body` stays the raw document half and the view degrades gracefully
  try:
    return _edit_markup.strip_markers(body, style = _finalize.read_document_edit_marker_style(file_path))
  except ValueError:
    return body


def _parse_meta(text: str, *, is_repair: bool) -> dict[str, str]:
  """
  Read the frontmatter keys of a review document.

  Args:
    text: The full document text.
    is_repair: Whether the dispatch is a structure repair, which tolerates broken frontmatter.

  Returns:
    The frontmatter keys, or an empty mapping for a repair whose frontmatter does not parse.

  Raises:
    DispatchRefusalError: If the frontmatter does not parse and the dispatch is not a repair.
  """
  # a repair works on a document whose frontmatter may not parse; it then reads as carrying none
  try:
    return _fm.parse(text)[0]
  except ParseError as error:
    # guard: a writer cannot be given a document whose frontmatter is broken
    if not is_repair:
      raise DispatchRefusalError(f"frontmatter does not parse: {error}") from error
    return {}


def _read_round(meta: dict[str, str], *, is_repair: bool) -> int:
  """
  Read the review round of a document.

  Args:
    meta: The document's frontmatter keys.
    is_repair: Whether the dispatch is a structure repair, which tolerates a missing round.

  Returns:
    The round number, or zero for a repair whose frontmatter carries no readable round.

  Raises:
    DispatchRefusalError: If the round is missing or not an integer and the dispatch is not a repair.
  """
  # the round is an integer the entry verb seeded and every landing bumps
  try:
    return int(str(meta.get(ReviewKey.ROUND, "")).strip())
  except ValueError as error:
    # guard: a writer round with no readable number is a broken review state
    if not is_repair:
      raise DispatchRefusalError(f"{ReviewKey.ROUND} is missing or not an integer") from error
    return _NO_ROUND


def _read_style(file_path: Path) -> str:
  """
  Resolve the edit-marker style that applies to a document.

  Args:
    file_path: The review document.

  Returns:
    The style the document pins, or the repository's configured style when the frontmatter cannot be parsed.
  """
  # the pin needs parseable frontmatter; a broken block falls back to the settings value
  try:
    return _finalize.read_document_edit_marker_style(file_path)
  except ParseError:
    return _finalize.read_settings_edit_marker_style(file_path)


def _resolve_class(review: dict, repo: Path, file_path: Path, *, is_repair: bool) -> dict | None:
  """
  Find the review class that governs a document.

  Args:
    review: The merged `review` settings section.
    repo: The directory whose settings hold `review`, which the class globs are relative to.
    file_path: The review document.
    is_repair: Whether the dispatch is a structure repair, which goes on without a class.

  Returns:
    The matching class entry, or `None` when no class applies or the frontmatter cannot be parsed.

  Raises:
    DispatchRefusalError: If no class matches the document and the dispatch is not a repair.
  """
  # the class needs parseable frontmatter; a repair goes on without one
  try:
    class_cfg = _doc_class.class_for_file({ JobKey.REVIEW: review }, repo, file_path)
  except ParseError:
    class_cfg = None

  # guard: a writer's mode, role and section come from the class, so no class means no dispatch
  if class_cfg is None and not is_repair:
    raise DispatchRefusalError(f"no review class matches {file_path}")
  return class_cfg


def _find_all_section_entries(class_cfg: dict, bucket: str) -> dict[str, dict]:
  """
  List the section writers a class declares in one bucket.

  Args:
    class_cfg: The review class entry.
    bucket: The bucket to read.

  Returns:
    The writer entries of the bucket keyed by section id.
  """
  # one bucket's section-id-to-writer map, entries of any other shape left out
  entries = (class_cfg.get(JobKey.EXPERTS) or {}).get(bucket) or {}
  return { section_id: entry for section_id, entry in entries.items() if isinstance(entry, dict) }


def _resolve_writer(
    class_cfg: dict, meta: dict[str, str], expert: str, section_id: str | None,
) -> tuple[str, dict]:
  """
  Decide the mode in which an expert writes on a document and find its class entry.

  Args:
    class_cfg: The review class entry.
    meta: The document's frontmatter keys.
    expert: The expert asked to write.
    section_id: The section the expert owns, or `None` for a main writer.

  Returns:
    The writer's mode and its class entry.

  Raises:
    DispatchRefusalError: If the section is unknown or owned by another writer, a section writer names no section, or
      the expert is not in the document's class chain.
  """

  # Domain(review.dispatch):
  # # A writer's mode comes from its place in the class
  # What a writer may hand back is decided by where the document's class lists it, never by the
  # writer's name or its role label. A writer in the class's main list rewrites the body. A
  # writer that owns a validation section or a terminal section writes that section alone, and
  # the section it owns has to be named, because one writer may own several. A document may
  # name a single main writer of its own, and that name then replaces the class's main list
  # entirely. A writer the class lists nowhere has no turn on the document.

  # a named section selects its owner entry in the validation or the terminal bucket
  if section_id is not None:
    for bucket in ( Bucket.VALIDATION, Bucket.TERMINAL ):
      entry = _find_all_section_entries(class_cfg, bucket).get(section_id)

      # this bucket does not declare the section; the other one may
      if entry is None:
        continue

      # guard: the section belongs to another writer
      if entry.get(JobKey.NAME) != expert:
        raise DispatchRefusalError(f"section {section_id!r} is owned by {entry.get(JobKey.NAME)!r}, not {expert!r}")
      return bucket, entry
    raise DispatchRefusalError(f"the document's class declares no section {section_id!r}")

  # a non-blank per-document override replaces the class's main list entirely
  override = str(meta.get(ReviewKey.EXPERT, "")).strip().strip("\"'")
  main_entries = [ entry for entry in (class_cfg.get(JobKey.EXPERTS) or {}).get(Phase.MAIN) or []
                   if isinstance(entry, dict) ]
  own_entry = next(( entry for entry in main_entries if entry.get(JobKey.NAME) == expert ), None)
  if expert == override if override else own_entry is not None:
    return Phase.MAIN, own_entry or {}

  # the sections the expert writes as a section writer, none for an expert outside the class chain
  owned = [ section_id for bucket in ( Bucket.VALIDATION, Bucket.TERMINAL )
            for section_id, entry in _find_all_section_entries(class_cfg, bucket).items()
            if entry.get(JobKey.NAME) == expert ]

  # guard: a section writer named without its section cannot be told which section to write
  if owned:
    raise DispatchRefusalError(f"{expert!r} is a section writer; pass {_ARG_SECTION_ID} (one of {owned})")
  raise DispatchRefusalError(f"{expert!r} is not in the document's class chain")


def _collect_concerns(class_cfg: dict, doc_body: str) -> list[dict]:
  """
  Gather the validation findings that currently stand in a document.

  Args:
    class_cfg: The review class entry.
    doc_body: The document body without frontmatter.

  Returns:
    One entry per validation section holding text, naming its section, its writer, its title and its content.
  """

  # Domain(review.dispatch):
  # # Validation findings reach the main writer as concerns
  # A main writer cannot edit a validation section, and yet it is the one who answers what the
  # validator found. So every validation section of the class that currently holds any text
  # travels to the main writer beside the document, named by its section and its author. A
  # section that is absent or holds only blank lines says nothing and is left out.

  concerns: list[dict] = []
  for section_id, entry in _find_all_section_entries(class_cfg, Bucket.VALIDATION).items():
    name = str(entry.get(JobKey.NAME, ""))
    content = _body.section_content_for_owner(doc_body, ( _parser.flatten_expert_name(name), section_id ))

    # guard: an absent or blank section carries no concern
    if content is None or not content.strip():
      continue
    concerns.append({
        JobKey.GROUP: section_id,
        JobKey.WRITER: name,
        JobKey.SECTION_H1_TITLE: entry.get(JobKey.SECTION) or section_id.replace("_", " ").capitalize(),
        JobKey.CONTENT: content.strip("\n"),
    })
  return concerns


def _resolve_context_path(repo: Path, raw: str) -> str:
  """
  Turn a context path named by the caller into a repository-relative path.

  Args:
    repo: The repository root.
    raw: The path as the caller gave it, taken against the repository root.

  Returns:
    The existing path relative to the repository root, in POSIX form.

  Raises:
    DispatchRefusalError: If the path does not exist or lies outside the repository.
  """
  # the path is taken against the repository root and named back relative to it
  target = (repo / raw).resolve()

  # guard: the pump copies only what the working tree holds
  if not target.exists():
    raise DispatchRefusalError(f"context path does not exist: {raw}")

  # guard: a job never reads from outside the repository
  try:
    return target.relative_to(repo).as_posix()
  except ValueError as error:
    raise DispatchRefusalError(f"context path is outside the repository: {raw}") from error


def _validate_unique_names(names: Sequence[str]) -> None:
  """
  Validate that no two context files of a job share a file name.

  Args:
    names: The file names of every context file the job carries.

  Raises:
    DispatchRefusalError: If two context files share a file name.
  """
  # the pump copies every context file flat by its basename, so two of one name would overwrite each other
  repeated = sorted({ name for name in names if names.count(name) > 1 })

  # guard: two context files of one basename cannot both reach the job
  if repeated:
    raise DispatchRefusalError(f"context files share a basename: {repeated}")


def _resolve_frontmatter_value(repo: Path, content_root: Path | None, value: str) -> str | None:
  """
  Turn one frontmatter value into the repository file it names.

  Args:
    repo: The repository root.
    content_root: The spec content root a value may be relative to, or `None` when it is not known.
    value: A `[[wikilink]]`, with an optional alias or anchor, or a bare repository-relative path.

  Returns:
    The existing file relative to the repository root, in POSIX form, found under the repository root first and then
    under the content root; `None` when the value names no file inside the repository.
  """
  # the link syntax is peeled off: brackets, then alias, then anchor
  name = value.strip().strip("\"'")
  if name.startswith(_WIKILINK_OPEN) and name.endswith(_WIKILINK_CLOSE):
    name = name[len(_WIKILINK_OPEN):-len(_WIKILINK_CLOSE)]
  name = name.partition("|")[0].partition("#")[0].strip()

  # guard: a blank value names nothing
  if not name:
    return None

  # a link names a note without its suffix
  if not name.lower().endswith(_MARKDOWN_SUFFIX):
    name = f"{name}{_MARKDOWN_SUFFIX}"

  # the repository root answers first, the spec content root second; the first existing file inside the repository
  # wins
  for base in ( repo, content_root ):
    # guard: the content root is unknown
    if base is None:
      continue

    # the value read under this base, symlinks and `..` steps resolved so a path out of the repository shows
    target = (base / name).resolve()

    # an existing file inside the repository is the job input this value names
    if target.is_file() and target.is_relative_to(repo):
      return target.relative_to(repo).as_posix()
  return None


def _collect_frontmatter_context(repo: Path, text: str, *, settings_root: Path,
                                 class_cfg: dict | None) -> tuple[list[str], list[str]]:
  """
  Collect the context files that the document's frontmatter names under the keys its review class declares.

  A value resolves against the repository root first and then the spec content root from the merged `spec` settings
  section; when those settings cannot be read or the content root is refused, only the repository root is tried. A
  value that names no file, and a refused content root, are reported as warnings and never refuse the dispatch.

  Args:
    repo: The repository root.
    text: The full document text.
    settings_root: The directory whose `.claude/lazy.settings.json` configures the document; the spec content
      root is read from its settings and lies under it.
    class_cfg: The review class entry, or `None` when no class applies.

  Returns:
    The repository-relative paths of the files the values name, and one warning per value that names no file plus
    one for a refused content root.

  Raises:
    DispatchRefusalError: If the class declares its frontmatter context keys as anything but a list of strings, an
      empty string, object, number or `false` included; only an absent field names no keys.
  """

  # Domain(review.dispatch):
  # # Frontmatter values name context for the main writer
  # A review class may name keys of the document's frontmatter whose values point at other files. Each file
  # found becomes context for the main writer, so the writer sees the material the document itself says it
  # depends on. A value is either a wikilink, where an alias or an anchor is dropped and the `.md` suffix is
  # implied, or a bare path. The repository root is tried first and the spec content root second. A file
  # outside the repository is never context, whatever the value says. A value that names no file is only a
  # warning and never refuses the turn, because a document's own pointers may be stale or ahead of the files;
  # this differs from command answers, whose absence refuses the turn. A class field that is not a list of
  # key names refuses the dispatch, because a bare string would otherwise be read as one key per character.
  # Only the main writer reads this context; section writers and repairs never receive it.

  # the class names the frontmatter keys whose values are context files; only an absent field names none
  declared = (class_cfg or {}).get(JobKey.CONTEXT_FROM_FRONTMATTER)

  # guard: a present field that is not a list of key names — an empty string, object, number or `false` included,
  # and a bare string that would pass for one key per character — is malformed, never "no keys"
  if declared is not None and (not isinstance(declared, list) or not all(isinstance(key, str) for key in declared)):
    raise DispatchRefusalError(f"{JobKey.CONTEXT_FROM_FRONTMATTER} is not a list of key names: {declared!r}")

  # the declared key names, none when the class leaves the field out
  keys: list[str] = declared or []

  # the content root comes from the merged `spec` section; unreadable settings leave the repository root alone
  content_root: Path | None = None
  warnings: list[str] = []
  if keys:
    try:
      spec_cfg = _core_settings.read_merged_sections(settings_root, _SPEC_SECTION)[_SPEC_SECTION]
    except SettingsReadError:
      spec_cfg = None

    # a refused root leaves the repository root alone too, and is reported, never silently dropped
    try:
      content_root = _core_settings.spec_content_root(settings_root, spec_cfg) if spec_cfg is not None else None
    except SettingsReadError as error:
      warnings.append(_FRONTMATTER_ROOT_REFUSED_TEMPLATE.format(error = error))

  # every declared key's values, each resolved to a context file or reported as a warning
  paths: list[str] = []
  for key in keys:
    # a bare wikilink or path is the single item; an inline array or an empty value (a block list) reads item by item
    raw = _fm.parse(text)[0].get(key, "").strip()
    is_scalar = bool(raw) and ( not raw.startswith("[") or raw.startswith(_WIKILINK_OPEN) )
    values = [ raw ] if is_scalar else _fm.read_list_field(text, key)

    # a blank or empty-quoted item names nothing and is not reported
    for value in ( item for item in values if item.strip().strip("\"'").strip() ):
      resolved = _resolve_frontmatter_value(repo, content_root, value)

      # an unresolvable value is reported, never a refusal
      if resolved is None:
        warnings.append(_FRONTMATTER_UNRESOLVED_TEMPLATE.format(key = key, value = value))
        continue
      paths.append(resolved)
  return paths, warnings


def _parse_verb_entries(class_cfg: dict | None) -> list[tuple[str, list[str]]]:
  """
  Parse the CLI verb entries the review class declares as context.

  Args:
    class_cfg: The review class entry, or `None` when no class applies.

  Returns:
    The context file name and the command of each entry, in declaration order; empty when the class declares none.

  Raises:
    DispatchRefusalError: If the field is not a list, or an entry is not an object with a plain file name and a
      non-empty command of strings whose first item is a bare plugin CLI name.
  """
  entries = (class_cfg or {}).get(JobKey.CONTEXT_FROM_VERBS)

  # guard: a class without the field runs no verb
  if entries is None:
    return []

  # guard: a field that is not a list of entries
  if not isinstance(entries, list):
    raise DispatchRefusalError(f"{JobKey.CONTEXT_FROM_VERBS} is not a list: {entries!r}")

  # every entry is a plain file name and a command led by a bare plugin CLI name
  read: list[tuple[str, list[str]]] = []
  for entry in entries:
    name = entry.get(JobKey.NAME) if isinstance(entry, dict) else None
    command = entry.get(JobKey.COMMAND) if isinstance(entry, dict) else None

    # guard: a name that is not a plain file name for the job's flat context bucket
    if not isinstance(name, str) or not name or name == ".." or name != Path(name).name:
      raise DispatchRefusalError(f"{JobKey.CONTEXT_FROM_VERBS} entry has no plain file {JobKey.NAME}: {entry!r}")

    # guard: a command that is not a bare plugin CLI name followed by string arguments
    if (
        not isinstance(command, list) or not command or not all( isinstance(arg, str) for arg in command )
        or not command[0].startswith(_PLUGIN_CLI_PREFIX) or command[0] != Path(command[0]).name
    ):
      raise DispatchRefusalError(
          f"{JobKey.CONTEXT_FROM_VERBS} entry {name!r} has no {JobKey.COMMAND} led by a bare "
          f"{_PLUGIN_CLI_PREFIX}<plugin> CLI name: {command!r}"
      )

    # a well-formed entry joins the verbs to run, in declaration order
    read.append(( name, command ))
  return read


def _parse_verb_error(proc: subprocess.CompletedProcess[str]) -> str:
  """
  Parse the reason a failed verb gave for its failure.

  Args:
    proc: The finished verb run.

  Returns:
    The `error` of the stdout JSON when it is a non-empty string; otherwise the stripped stderr, else the stripped
    stdout when stdout is not a JSON object, else the text that says the verb gave no reason.
  """
  # a stdout that is not JSON carries no error of the verb's own
  try:
    answer = json.loads(proc.stdout)
  except ValueError:
    answer = None

  # the verb's own non-empty reason names the failure best; its stderr may hold unrelated notes
  if isinstance(answer, dict) and isinstance(error := answer.get(_VERB_ERROR_KEY), str) and error.strip():
    return error

  # otherwise its diagnostics, then a stdout that is no JSON answer, and the refusal says when there is nothing
  return proc.stderr.strip() or ( "" if isinstance(answer, dict) else proc.stdout.strip() ) or _VERB_NO_REASON


def _run_context_verbs(repo: Path, rel_doc: str, class_cfg: dict | None) -> tuple[dict[str, str], list[str]]:
  """
  Run the CLI verbs the review class declares and return their answers as context, with the verbs' warnings.

  Each verb is a plugin CLI run under the current interpreter from the repository root, with a 60 s limit; `{doc}` in
  an argument stands for the document's repository-relative path. A verb that answers successfully may also print
  warnings, one per non-empty stderr line; each is reported attributed to its entry and does not withdraw the answer.
  A verb that fails refuses the dispatch with a message naming the entry, the exit code, the command and the verb's
  own error.

  Notes:
    - Spawns one subprocess per declared verb, one after another.

  Args:
    repo: The repository root.
    rel_doc: The document's repository-relative path in POSIX form.
    class_cfg: The review class entry, or `None` when no class applies.

  Returns:
    The answers, each declared file name mapped to the stdout its verb printed, and the warnings of the answering
    verbs; both empty when the class declares no verb.

  Raises:
    DispatchRefusalError: If an entry is malformed, its CLI cannot be resolved, or its verb cannot start, exits
      non-zero, runs past the time limit, or answers nothing.
  """

  # Domain(review.dispatch):
  # # Command answers reach the main writer as computed context
  # A review class may declare commands of other plugins whose answers about the document become
  # context for the main writer. The answers are computed when the main writer's turn is set up
  # and exist in no file, so they travel as computed content, never as a path. The writer is
  # meant to work from them, so any way an answer can fail to arrive refuses the turn before
  # anything is written: a malformed declaration, a command no lookup finds, a command that
  # fails, one that hangs past the time limit, one that answers nothing, or a name that clashes
  # with another context file. When a command fails, the refusal names the command, its exit
  # code and the reason the command itself gave in its answer. An empty reason counts as none, and
  # an answer that is the command's own structured result is never mistaken for a reason. With no
  # reason in the answer, the command's diagnostic output stands in, and when the command gave no
  # reason at all the refusal says so. A command that answers successfully may also print its
  # own warnings on its diagnostic stream: each non-empty line travels with the dispatch as a
  # warning attributed to that command, and the answer is still required. A missing answer is
  # never downgraded to a warning, which differs from context named by the document's
  # frontmatter, where an unresolved value is only a warning.
  # Section writers and repairs never receive these answers.

  # every declared verb runs in turn, its answer kept under the entry's file name
  answers: dict[str, str] = {}
  warnings: list[str] = []
  for name, command in _parse_verb_entries(class_cfg):
    try:
      cli = _git_ops.resolve_plugin_cli(command[0], repo = repo)
    except RuntimeError as error:
      raise DispatchRefusalError(f"verb for {name}: {error}") from error
    args = [ arg.replace(_DOC_PLACEHOLDER, rel_doc) for arg in command[1:] ]

    # the verb runs under this interpreter from the repository root; a spawn failure or a hang is a refusal
    try:
      proc = subprocess.run(
          [ sys.executable, str(cli), *args ], cwd = repo, capture_output = True, text = True, check = False,
          encoding = _VERB_ENCODING, errors = _VERB_DECODE_ERRORS, timeout = _VERB_TIMEOUT_SECONDS,
      )
    except subprocess.TimeoutExpired as error:
      raise DispatchRefusalError(
          f"verb for {name} ran past {_VERB_TIMEOUT_SECONDS} s: {command}"
      ) from error
    except OSError as error:
      raise DispatchRefusalError(f"verb for {name} could not start: {error}") from error

    # guard: a failing verb gives no answer to work from
    if proc.returncode != 0:
      raise DispatchRefusalError(_VERB_FAILED_TEMPLATE.format(
          name = name, code = proc.returncode, command = command, error = _parse_verb_error(proc),
      ))

    # guard: an empty answer is missing information
    if not proc.stdout.strip():
      raise DispatchRefusalError(f"verb for {name} answered nothing: {command}")

    # the answer is context under the entry's declared file name
    answers[name] = proc.stdout

    # an answering verb's own stderr lines travel with the dispatch as warnings
    warnings.extend(
        _VERB_WARNING_TEMPLATE.format(name = name, line = line.strip())
        for line in proc.stderr.splitlines() if line.strip()
    )
  return answers, warnings


def _build_protocols(review: dict, class_cfg: dict | None) -> list[str]:
  """
  List the protocols a writer job carries.

  Args:
    review: The merged `review` settings section.
    class_cfg: The review class entry, or `None` when no class applies.

  Returns:
    The protocol references without repeats, the review plugin's own protocol first.
  """
  # the plugin's own wire contract, then the section default list, then the class's own list
  declared = [ *(review.get(JobKey.PROTOCOLS) or []), *((class_cfg or {}).get(JobKey.PROTOCOLS) or []) ]
  return list(dict.fromkeys([ ReviewProtocol.DOC_REVIEW, *( ref for ref in declared if isinstance(ref, str) ) ]))


# waiver: too-many-locals — the bundle is one wire object whose every field is derived here, side by side
def _build_bundle(  # pylint: disable=too-many-locals
    repo: Path, file_path: Path, expert: str, *,
    section_id: str | None, section: str | None, position: str | None,
    context_paths: Sequence[str], is_repair: bool,
) -> tuple[dict, list[str]]:
  """
  Build the core `dispatch-job` bundle for one expert turn on one review document.

  Every request check runs here, before the caller has a side effect to undo.

  A main-mode dispatch also carries the context its review class declares for the main writer. Context that cannot
  be found is reported as a warning, while a failing context source refuses the dispatch.

  A writer dispatch also carries the guidelines its role reads: repository-relative guideline paths join the
  context, while the absolute paths of the plugin canon are named in the request's `guidelines` field. A repair
  carries neither.

  A main-mode dispatch on a report class also tells the writer that its document is a report. Every dispatch on a
  report class (main writer, section writer or repair) withholds the right to commit in the repository; a job on a
  document of any other class, and a repair whose frontmatter is too broken to name a class, keeps the expert's
  own commit right.

  Args:
    repo: The repository root.
    file_path: The review document.
    expert: The expert asked to write.
    section_id: The section the expert owns, or `None` for a main writer or a repair.
    section: The title of the section, overriding the class entry.
    position: Where a new section lands, overriding the class entry.
    context_paths: Extra repository files the job reads as context.
    is_repair: Whether the job repairs the document's structure instead of writing as an expert.

  Returns:
    The bundle, whose request names the plugin canon's absolute guideline paths in its `guidelines` field, and the
    warnings to report with the dispatch: the guideline warnings, one per frontmatter value that
    names no file, one per context a refused spec content root narrowed, the stderr lines of the class verbs that
    answered, and a repair's unavailable defect report.

  Raises:
    DispatchRefusalError: If the request is invalid: a section flag on a repair, a title or position without a
      section, a document that is not a markdown file inside the repository, a document outside the review loop,
      an unreadable round or settings, an unmatched class or writer, a context path that is missing or outside
      the repository, a malformed frontmatter-key or verb declaration, a verb that cannot be resolved, cannot start,
      exits non-zero, times out or answers nothing, or two context files, whether given by `--context`, named by
      frontmatter or answered by a verb, that share a file name.
  """

  # Domain(review.dispatch):
  # # A repair turn is not bound by a writer's preconditions
  # A writer's turn exists only on a document that is inside the review loop, whose frontmatter parses,
  # whose round is a readable number and whose class lists the writer. A structure repair exists to mend
  # a document that has gone wrong, so it asks for none of that: it runs on broken frontmatter, an unreadable
  # round, a document outside the loop or one that matches no class. It still has to be a markdown file
  # inside the repository, it rewrites the whole file and so owns no section, and it is given neither
  # guidelines nor decisions. Its report of structural defects is only a hint: when the report cannot be
  # computed, the repair goes ahead without it and says so.

  # guard: a repair rewrites the whole file, so it owns no section
  if is_repair and (section_id is not None or section is not None or position is not None):
    raise DispatchRefusalError(f"{_ARG_REPAIR} takes no section flag")

  # guard: a title or a position describes a section that has to be named
  if section_id is None and (section is not None or position is not None):
    raise DispatchRefusalError(f"{_ARG_SECTION} and {_ARG_POSITION} need {_ARG_SECTION_ID}")

  # guard: only an existing markdown file is a review document
  if not file_path.is_file() or file_path.suffix.lower() != _MARKDOWN_SUFFIX:
    raise DispatchRefusalError(f"not a markdown file: {file_path}")

  # guard: the job names its document by a path inside the repository
  try:
    rel_doc = file_path.relative_to(repo).as_posix()
  except ValueError as error:
    raise DispatchRefusalError(f"document is outside the repository: {file_path}") from error

  # the document's own state: its frontmatter keys and, for a writer, proof it is under review
  text = file_path.read_text(encoding = "utf-8")
  meta = _parse_meta(text, is_repair = is_repair)

  # guard: a writer turn exists only on a document inside the review loop
  if not is_repair and str(meta.get(ReviewKey.ACTIVE, "")).strip().lower() != _ACTIVE_LITERAL:
    raise DispatchRefusalError(f"{ReviewKey.ACTIVE} is not true on {rel_doc}")

  # the document's review round, which a writer turn needs readable and a repair may lack
  round_ = _read_round(meta, is_repair = is_repair)

  # the merged `review` section of the document's nearest settings names the classes and the protocol defaults
  settings_root = _core_settings.query_settings_root_for(file_path)
  try:
    review = _core_settings.read_merged_sections(settings_root, JobKey.REVIEW)[JobKey.REVIEW]
  except SettingsReadError as error:
    raise DispatchRefusalError(str(error)) from error

  # the review class the document falls under, none for a repair
  class_cfg = _resolve_class(review, settings_root, file_path, is_repair = is_repair)

  # the writer's structural mode and its config entry; a repair has neither class nor entry to consult
  mode, entry = ( Outcome.REPAIR, {} ) if is_repair else _resolve_writer(class_cfg or {}, meta, expert, section_id)

  # the writer's guidelines: the enabled plugins' canon for its role, then the product's declared guidelines
  guidelines = (
      { _guidelines_context.PATHS_KEY: [], _guidelines_context.WARNINGS_KEY: [] } if is_repair
      else _guidelines_context.collect(file_path, expert)
  )
  warnings = list(guidelines[_guidelines_context.WARNINGS_KEY])

  # the guideline paths split by where the expert reads them: an absolute path into a plugin tree is read in place
  # from the payload's `guidelines`, a repo path is copied into `context` ahead of what the coordinator named
  canon_paths = [ path for path in guidelines[_guidelines_context.PATHS_KEY] if Path(path).is_absolute() ]
  repo_guidelines = [ path for path in guidelines[_guidelines_context.PATHS_KEY] if not Path(path).is_absolute() ]

  # Decision: only the main writer reads the class's frontmatter keys — section writers judge the document, and a
  # repair mends it; neither works from the request the document came from

  # the files the class's frontmatter keys name, for the main writer alone
  frontmatter_paths, frontmatter_warnings = (
      _collect_frontmatter_context(repo, text, settings_root = settings_root, class_cfg = class_cfg)
      if mode == Phase.MAIN else ( [], [] )
  )
  warnings.extend(frontmatter_warnings)
  path_context = list(dict.fromkeys([
      *repo_guidelines, *( _resolve_context_path(repo, raw) for raw in context_paths ),
      *frontmatter_paths,
  ]))

  # in-memory context: a repair's defect report or the main writer's verb answers, their names reserved up front so
  # a clash refuses before any verb runs
  inline_context: dict[str, str] = {}
  verb_names = [ name for name, _command in _parse_verb_entries(class_cfg) ] if mode == Phase.MAIN else []
  _validate_unique_names([
      *( Path(rel).name for rel in path_context ), *( [ _DEFECTS_FILE ] if is_repair else [] ), *verb_names,
  ])

  # the verbs the class declares answer for the main writer alone; any that fails refuses the dispatch, and an
  # answering verb's own warnings join the report
  if mode == Phase.MAIN:
    answers, verb_warnings = _run_context_verbs(repo, rel_doc, class_cfg)
    inline_context.update(answers)
    warnings.extend(verb_warnings)

  # a repair's defect report is a hint: when it cannot be computed the job goes without it, and says so
  if is_repair:
    try:
      inline_context[_DEFECTS_FILE] = json.dumps(_structure_repair.build_check_report(file_path))
    except (ValueError, RuntimeError, OSError) as error:
      warnings.append(DEFECTS_UNAVAILABLE_TEMPLATE.format(error = error))

  # every context file's name inside the job, the copied files first and then the in-memory ones
  context_names = [ *( Path(rel).name for rel in path_context ), *inline_context ]

  # the request the job receives, through the payload contract's own builder
  result_name = f"{section_id}{_MARKDOWN_SUFFIX}" if section_id is not None else file_path.name
  request = _payload.build_request(
      kind = Outcome.REPAIR if is_repair else Kind.REVIEW,
      mode = mode,
      role = Outcome.REPAIR if is_repair else str(entry.get(JobKey.ROLE) or mode),
      round_ = round_,
      source_path = f"{_SOURCE_DIR}{file_path.name}",
      context_paths = [ f"{_CONTEXT_DIR}{name}" for name in context_names ],
      result_path = f"{_RESULT_DIR}{result_name}",
      edit_marker_style = _read_style(file_path),
      concerns = _collect_concerns(class_cfg or {}, _fm.parse(text)[1]) if mode == Phase.MAIN else None,
  )
  request[JobKey.TARGET_FILE] = str(file_path)

  # a job with no context file carries no context field at all
  if not context_names:
    del request[JobKey.CONTEXT]

  # Domain(review.dispatch):
  # # A report's writer is told it writes on a report
  # A report is reviewed as a discussion, and its main writer owes a verdict on the whole report with every
  # answer. The writer cannot tell a report from the document it reads: while a round runs, the report shows
  # the same in-process banner as any other document. So the main writer's request of a report says so in a
  # field of its own, and no other request carries that field. No job on a report changes anything in the
  # repository beyond its answer: the main writer, every validator and terminal writer, and a structure repair
  # are all dispatched without the right to commit, whatever the expert may do elsewhere. A job on any other
  # document keeps the expert's own commit right, and so does a repair whose frontmatter is too broken to tell
  # which class, and so whether a report, the document belongs to.

  # only the main writer of a report class is told the document is a report; a repair whose frontmatter names no
  # class has no report class to read
  report_class = (class_cfg or {}).get(JobKey.REPORT) is True
  is_report = mode == Phase.MAIN and report_class
  if is_report:
    request[JobKey.REPORT] = True

  # the plugin canon is named by absolute path, in resolver order; a dispatch without one carries no field
  if canon_paths:
    request[_GUIDELINES_KEY] = canon_paths

  # Domain(review.dispatch):
  # # Decisions registries are named, never copied
  # A writer reads what was already decided for the asset its document belongs to and for the
  # product that owns it. Both registries are living files that other work keeps adding to, and
  # both carry the same file name, so the job is told where they are and reads them as they
  # stand when it runs. The asset's registry is named first and the product's second; that
  # order is the only thing that tells them apart. A repair fixes structure and gets neither.

  # a writer is pointed at the decisions registries in the working tree; a repair has no use for them
  decisions, decisions_warnings = ( [], [] ) if is_repair else _decisions_context.collect_paths(repo, file_path)
  warnings.extend(decisions_warnings)
  if decisions:
    request[_DECISIONS_KEY] = decisions

  # Domain(review.dispatch):
  # # A section's title and landing position have three sources
  # A section writer's section takes its title and its landing position from the first source that names
  # them: the explicit request of the coordinator, then the writer's own entry in the document's class.
  # When neither names one, the section lands with the defaults of the step that places the result into
  # the document.

  # the payload is the only place a section writer's owned section is named
  if section_id is not None:
    request[JobKey.EXPERT] = expert
    request[JobKey.SECTION_ID] = section_id
    for key, given in ( ( JobKey.SECTION, section ), ( JobKey.POSITION, position ) ):
      # the flag wins over the class entry; with neither, the landing applies its own default
      if value := given or entry.get(key):
        request[key] = value

  # the bundle around the request: who runs it, under which contracts, and where the output goes
  bundle: dict = {
      JobKey.EXPERT: expert,
      JobKey.PAYLOAD: request,
      JobKey.PROTOCOLS: _build_protocols(review, class_cfg),
      JobKey.RESULT: request[JobKey.RESULT],
  }

  # every job on a report runs without the right to commit; a job on any other document keeps the expert's own
  if report_class:
    bundle[_CAN_COMMIT_IN_REPO] = False

  # Domain(review.dispatch):
  # # The source view follows the writer's job
  # A repair fixes the file's own structure, so it is handed the file itself, as it stands when
  # the job is claimed. A main writer revises the body and is handed the body with its edit
  # markup untouched. A validation or terminal writer judges the final state and is handed the
  # body with the markup resolved. Neither body view exists as a file, so both travel as text.

  # the source: the whole file by path for a repair, a computed body view as text for a writer
  if is_repair:
    bundle[JobKey.SOURCE] = [ { JobKey.PATH: rel_doc } ]
  else:
    view = read_body_view(file_path) if mode == Phase.MAIN else read_resolved_body_view(file_path)
    bundle[_SOURCE_INLINE] = { file_path.name: view }

  # the context buckets appear only when they hold something
  if path_context:
    bundle[JobKey.CONTEXT] = [ { JobKey.PATH: rel } for rel in path_context ]
  if inline_context:
    bundle[_CONTEXT_INLINE] = inline_context

  # Domain(review.dispatch):
  # # One job per owned section
  # A section writer's job is identified by the document and the section together, so however
  # many wakes ask for the same section there is one job. A main writer's turn and a repair
  # carry no such identity: each dispatch of theirs is a new job.

  # only a section writer's job is keyed, by its document and section
  if section_id is not None:
    bundle[JobKey.DEDUP_KEY] = f"{file_path}#{section_id}"
  return bundle, warnings


def _job_dir(repo: Path, expert: str, job_id: str) -> Path:
  """
  Name the bundle directory of one expert job.

  Args:
    repo: The repository root.
    expert: The expert the job was queued for.
    job_id: The job's identifier.

  Returns:
    The job's bundle directory, whether or not it exists.
  """
  return repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / expert / job_id


def _is_failed_job(repo: Path, expert: str, job_id: str) -> bool:
  """
  Tell whether a job the queue still holds under a dedup key has failed.

  Args:
    repo: The repository root.
    expert: The expert the job was queued for.
    job_id: The job's identifier.

  Returns:
    True when the job finished and its response reports an `error` outcome; False for a job still in flight,
    one that finished with any other outcome, and one whose response cannot be read.
  """
  jdir = _job_dir(repo, expert, job_id)

  # guard: only a finished job can have failed; a dead or cancelled one never answers a dedup hit
  if _collect_ops.read_job_status(jdir) != JobStatus.DONE:
    return False

  # the response's own outcome says whether the finished job failed
  try:
    response = json.loads((jdir / JobFile.RESPONSE).read_text(encoding = "utf-8"))
  except (OSError, ValueError):
    return False
  return isinstance(response, dict) and response.get(JobKey.OUTCOME) == Outcome.ERROR


def _queue(repo: Path, expert: str, bundle: dict) -> dict:
  """
  Send a bundle to the core queue.

  Notes:
    - When the answer is a dedup hit on a job that finished with an error, that job is retired through core and
      the bundle is queued once more.

  Args:
    repo: The repository root.
    expert: The expert the job is queued for.
    bundle: The core `dispatch-job` bundle.

  Returns:
    Core's answer to the queue call.

  Raises:
    DispatchRefusalError: When the failed job holding the section cannot be retired.
    QueueAnswerError: When core reported a queue call as successful but its answer cannot be used; it passes through
      unchanged from either queue call.
    RuntimeError: When a queue call fails; the message is `the queue call failed: <reason>`.
  """
  try:
    # the first queue call: its answer says whether a job was made or one already holds the section
    answer = _ask_core(repo, bundle)

    # Domain(review.dispatch):
    # # A failed section job does not hold its section
    # A section has one job at a time, and a job that is running, or finished with an answer nobody
    # has collected yet, holds the section against a second dispatch. A job that finished by
    # reporting an error holds nothing: it has no answer to collect, so asking for the section
    # again retires it and starts a new job.

    # anything but a dedup hit on a failed job is the answer as it stands
    held_id = str(answer.get(JobKey.JOB_ID))
    if answer.get(JobKey.STATUS) != _STATUS_QUEUED or not _is_failed_job(repo, expert, held_id):
      return answer

    # a failed job is retired through core; while core refuses, the section stays held and no job is made
    try:
      _collect_ops.consume_job(repo, _job_dir(repo, expert, held_id))
    except JobConsumeError as error:
      raise DispatchRefusalError(
          f"the failed job {held_id} holds the section and could not be retired: {error}"
      ) from error

    # the key is free now, so the same bundle queues as a new job
    return _ask_core(repo, bundle)
  except (RuntimeError, OSError, ValueError) as error:
    raise RuntimeError(f"the queue call failed: {error}") from error


def _ask_core(repo: Path, bundle: dict) -> dict:
  """
  Make one core queue call and take its answer.

  Args:
    repo: The repository root.
    bundle: The core `dispatch-job` bundle.

  Returns:
    Core's answer, a JSON object.

  Raises:
    QueueAnswerError: When core reported success but its answer is not JSON or is JSON that is not an object, so
      whether the job was queued is not known.
    RuntimeError: When core cannot be found or refuses the call.
    OSError: When core cannot be launched.
  """
  # the plugin's one core `dispatch-job` call lives in `coordinator_dispatch`, looked up at call time
  try:
    # waiver: the whole-project mypy run resolves the bare name to lazycortex-specs' same-named module, which has
    # no `core_dispatch_job`; at runtime the sys.path.insert above loads this bin's own sibling
    answer = _coordinator_dispatch.core_dispatch_job(repo, bundle)  # type: ignore[attr-defined]
  # core ran and reported success, and what it printed cannot be read: the job may stand in the queue
  except ValueError as error:
    raise QueueAnswerError(f"core answered the queue call with output that cannot be read: {error}") from error

  # guard: an answer that is not an object says nothing about the job, which may stand in the queue all the same
  if not isinstance(answer, dict):
    raise QueueAnswerError("core answered the queue call with JSON that is not an object")
  return answer


def _restore_marker(repo: Path, file_path: Path, previous: str | None) -> bool:
  """
  Put the document's `active_job` marker back to the value it held before a dispatch.

  Notes:
    - A marker that cannot be put back is reported on stderr, and the caller keeps the error it is already raising.
    - Never raises `OSError`.

  Args:
    repo: The repository root.
    file_path: The review document.
    previous: The job id the marker held before the dispatch, or `None` when it named no job.

  Returns:
    `True` when the marker was put back, `False` when it could not be.
  """
  # a marker that cannot be put back is reported; the error that stopped the dispatch stays the one raised
  try:
    _job_markers.update(repo, file_path, { JobMarker.ACTIVE_JOB: previous })
  except OSError as error:
    sys.stderr.write(
        f"dispatch-writer: {file_path}: the job marker could not be restored to {previous!r}: {error}\n"
    )
    return False
  return True


def dispatch_writer(
    repo: Path, file_path: Path, expert: str, *,
    section_id: str | None = None, section: str | None = None, position: str | None = None,
    context_paths: Sequence[str] = (), is_repair: bool = False,
) -> dict:
  """
  Queue one expert turn on a review document.

  Builds the whole job bundle, marks the document as having a job in flight, and queues the job through the core
  CLI.

  Guarantees:
    - A request refused before the document's `active_job` marker is written leaves no trace: `DispatchRefusalError`
      is raised with `marker_restored` of `None`, no job is queued, nothing is written, and the marker holds the
      value it held before the call. A refusal after the marker was written, because the section is held by a
      failed job that core refuses to retire, raises `DispatchRefusalError` with `marker_restored` of `True` or
      `False` and queues no job; with `True` the marker holds the value it held before the call.
    - The document's `active_job` marker names the job before the queue is called. When the queue call failed,
      because core is unreachable or refuses, no job was queued: a restore is attempted, `DispatchQueueError` is
      raised with `marker_restored` of `True` or `False`, and with `True` the marker is put back to the value it
      held before this call. When that restore itself fails, the marker is not back: it still names the job id
      prepared by this call, a job that was never queued, `marker_restored` is `False`, stderr carries one line
      naming the document, and the error that stopped the dispatch is still the one raised.
    - When core reported the queue call as successful but its answer cannot be used (the output is not JSON, or is
      JSON that is not an object), whether the job was queued is not known. The marker is not put back: it keeps
      naming the job id prepared by this call, so a job that was queued can still deliver its completion, and
      `DispatchQueueError` is raised with `marker_restored` of `False`. The job may or may not stand in the queue.
      This also holds for the second queue call made after a failed job was retired.

  Args:
    repo: The repository root.
    file_path: The review document.
    expert: The expert asked to write.
    section_id: The section the expert owns, or `None` for a main writer or a repair.
    section: The title of the section, overriding the class entry.
    position: Where a new section lands, overriding the class entry.
    context_paths: Extra repository files the job reads as context.
    is_repair: Whether the job repairs the document's structure instead of writing as an expert.

  Returns:
    A report with `job_id`, `status` (`dispatched` or `already-queued`) and `warnings`.

  Raises:
    DispatchRefusalError: If the request is invalid, or the dispatch cannot be prepared: an unreadable document,
      unreachable settings, a context verb the review class declares that cannot run or gives no answer, or a job
      marker that cannot be written; its `marker_restored` is `None`. Also when the
      section is held by a failed job that core refuses to retire; the marker is put back first, and
      `marker_restored` says whether that succeeded.
    DispatchQueueError: If the queue call fails; `marker_restored` says whether the job marker was put back (a
      failed restore is also reported on stderr). Also if core reports the queue call as successful but its answer
      cannot be used; the marker is kept, `marker_restored` is `False`, and the job may be queued.
    RuntimeError: If the queue call went through but the marker could not be pointed at the standing job.
  """

  # Contract:
  # A request refused before the document's `active_job` marker is written MUST leave no trace:
  # `DispatchRefusalError` is raised with `marker_restored` of `None`, no job is queued, nothing is written, and
  # the marker holds the value it held before the call.
  # A refusal after the marker was written, because the section is held by a failed job that core refuses to
  # retire, raises `DispatchRefusalError` with `marker_restored` of `True` or `False`, and no job is queued. With
  # `True` the marker holds the value it held before the call; `False` is the failed restore stated by the rule
  # on the marker below.

  # Contract:
  # The document's `active_job` marker MUST name the job BEFORE the queue is called.
  # How a queue call ends decides what `marker_restored` of the raised `DispatchQueueError` means.
  # A queue call that FAILED, because core is unreachable or refuses, queued no job. A restore of the marker is
  # attempted and `marker_restored` of `True` or `False` says how it went; a late refusal as stated above carries
  # the same flag. With `True` the marker is put back to the value it held before this call. When that restore
  # itself fails, the marker is NOT back: it still names the job id prepared by this call, a job that was never
  # queued. `marker_restored` is `False`, stderr carries one line naming the document, and the error that stopped
  # the dispatch is still the one raised.
  # A queue call that core reported as successful but whose answer cannot be used, because the output is not JSON
  # or is JSON that is not an object, leaves it unknown whether the job was queued. The marker is NOT put back: it
  # keeps naming the job id prepared by this call, so a job that was queued can still deliver its completion.
  # `DispatchQueueError` is raised with `marker_restored` of `False`, and the job may or may not stand in the
  # queue. This holds as well when the unusable answer comes from the second queue call made after a failed job
  # was retired.

  # every check runs here, before anything is written; whatever stops the build stops it as a refusal
  try:
    bundle, warnings = _build_bundle(
        repo, file_path, expert, section_id = section_id, section = section, position = position,
        context_paths = context_paths, is_repair = is_repair,
    )
  except (RuntimeError, OSError, ValueError) as error:
    raise DispatchRefusalError(f"the dispatch could not be prepared: {error}") from error

  # the marker goes up first: it is what turns the job's completion into a coordinator wake
  previous = _job_markers.read(repo, file_path)[JobMarker.ACTIVE_JOB]
  job_id = uuid.uuid4().hex[:12]
  bundle[JobKey.JOB_ID] = job_id
  try:
    _job_markers.update(repo, file_path, { JobMarker.ACTIVE_JOB: job_id })
  except OSError as error:
    raise DispatchRefusalError(f"the job marker could not be written: {error}") from error

  # queue the job; a call that does not come back leaves the marker as it was found
  is_settled = False
  try:
    answer = _queue(repo, expert, bundle)
    is_settled = True
  except DispatchRefusalError as error:
    # the refusal came after the marker was written, so it carries what became of the marker
    is_settled = True
    error.marker_restored = _restore_marker(repo, file_path, previous)
    raise
  except QueueAnswerError as error:
    # core reported success, so the job may be queued: the marker keeps naming it, and the caller is told so
    is_settled = True
    raise DispatchQueueError(str(error), marker_restored = False) from error
  except RuntimeError as error:
    # the error the caller reads carries what became of the marker, whichever way the restore went
    is_settled = True
    raise DispatchQueueError(str(error), marker_restored = _restore_marker(repo, file_path, previous)) from error
  finally:
    # any other way out without a queued job puts the marker back as well
    if not is_settled:
      _restore_marker(repo, file_path, previous)

  # Domain(review.jobs):
  # # A repeated request adopts the standing job
  # When a section is asked for while its job still stands, no second job is made and the turn belongs
  # to the job already there. The document's in-flight marker then names that standing job and not the
  # one prepared for the repeated request, because the standing job is the one that will deliver the answer.

  # a dedup hit answers with the live job's id, and the turn then belongs to that job
  queued_id = str(answer.get(JobKey.JOB_ID) or job_id)
  if queued_id != job_id:
    # the queue call went through; a marker that cannot be re-pointed is reported as what it is
    try:
      _job_markers.update(repo, file_path, { JobMarker.ACTIVE_JOB: queued_id })
    except OSError as error:
      raise RuntimeError(
          f"job {queued_id} holds the turn, but the document's job marker could not be pointed at it: {error}"
      ) from error
  return {
      JobKey.JOB_ID: queued_id,
      JobKey.STATUS: _STATUS_QUEUED if answer.get(JobKey.STATUS) == _STATUS_QUEUED else _STATUS_DISPATCHED,
      JobKey.WARNINGS: warnings,
  }


def main(argv: list[str]) -> int:
  """
  Run the `dispatch-writer` verb.

  Prints one JSON object on stdout: the dispatch report on success, or `{"error": ...}` on failure. A queue failure
  and a refusal that came after the document's job marker was written add `"marker_restored"`, `true` when the
  marker was put back and `false` when it was not: either it could not be put back, or it was kept because core
  reported a queue call as successful with an answer that cannot be used, so the job may be queued. A refusal before
  the marker was written, and every other failure, print `{"error": ...}` alone.

  Args:
    argv: Command-line arguments: the document, the expert, then optional section, context, repair and repo flags;
      `--repo` names a directory inside the repository (default: `$LAZY_REPO_ROOT`, then the working directory).

  Returns:
    Exit code: 0 when the job was queued, 1 when the queue call failed, core's answer to a queue call it reported as
    successful cannot be used, or the marker could not be re-pointed after a dedup hit (the printed error says
    which), 2 when the request was refused, including a failure while
    preparing the dispatch and a late refusal that came after the job marker was written.
  """
  # the verb's arguments: the document and the expert
  parser = argparse.ArgumentParser(prog = _PROG)
  parser.add_argument(_ARG_FILE)
  parser.add_argument(_ARG_EXPERT)

  # the section, context, repair and repo flags only the coordinator knows
  parser.add_argument(_ARG_SECTION_ID, default = None)
  parser.add_argument(_ARG_SECTION, default = None)
  parser.add_argument(_ARG_POSITION, default = None, choices = _POSITIONS)
  parser.add_argument(_ARG_CONTEXT, action = _APPEND, default = None)
  parser.add_argument(_ARG_REPAIR, action = _STORE_TRUE)
  parser.add_argument(_ARG_REPO, default = None)
  args = parser.parse_args(argv)

  # a relative file names a document inside the repository the dispatch acts in
  repo = _review_locator.query_repo_root(args.repo)
  try:
    report = dispatch_writer(
        repo, (repo / args.file).resolve(), args.expert,
        section_id = args.section_id, section = args.section, position = args.position,
        context_paths = args.context or (), is_repair = args.repair,
    )
  # the request was refused; a refusal that came after the marker was written says what became of the marker
  except DispatchRefusalError as error:
    marker = {} if error.marker_restored is None else { _MARKER_RESTORED: error.marker_restored }
    print(json.dumps({ JobKey.ERROR: str(error), **marker }))
    return _EXIT_REFUSED
  # the queue call failed after the marker was written; the output says what became of the marker
  except DispatchQueueError as error:
    print(json.dumps({ JobKey.ERROR: str(error), _MARKER_RESTORED: error.marker_restored }))
    return _EXIT_FAILED
  # the dispatch failed after its first side effect; the message says which step
  except (RuntimeError, OSError, ValueError) as error:
    print(json.dumps({ JobKey.ERROR: str(error) }))
    return _EXIT_FAILED

  # the one JSON object the coordinator reads: the job, its status, and what to journal
  print(json.dumps(report))
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
