"""
Logic behind the `lazycortex-specs migrate-spec-tools` verb — moves a consumer off the tool layer.

Nothing on an asset or an asset type says who builds it any more. The verb strips the retired tool-set markup from
status folder-notes and the retired tool fields from every product's asset types, and drops the retired report
review classes no document uses. The settings work covers the tracked settings and the gitignored local overlay
beside them. A product's own `tool_types` declarations, a report class whose documents remain and a product-scoped
report class stay in place and are reported. Settings are written only through the core CLI. It never commits.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import Section, SpecKey, SpecValue  # noqa: E402


# The retired names live here, not in `spec_keys`: the plugin no longer reads any of them, and only this migration
# still has to recognise them in a consumer's files.

# The retired frontmatter key of a status note, the retired fields of an asset-type declaration, and the retired
# per-product tool declarations.
_SPEC_TOOLS_KEY = "spec_tools"
_RETIRED_TYPE_FIELDS = ( "default_tools", "tools" )
_TOOL_TYPES_KEY = "tool_types"

# The tool names the retired shipped declarations carried, frozen here because the plugin ships no declaration file
# any more; a question an earlier release raised could only name these or a product's own `tool_types`.
_BUILTIN_TOOLS = frozenset({ "code", "data", "test", "docs", "research" })

# The retired report document types, which are also the names of their review classes, and the separator of a
# product-scoped `<kind>@<key>` class.
_RETIRED_REPORTS = ( "data-report", "docs-report" )
_SCOPE_SEP = "@"

# The frontmatter key naming a document's type.
_DOC_TYPE_KEY = "spec_doc_type"

# The tracked settings file and its gitignored local overlay, the products section, and the keys leading to an asset
# type's declaration.
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_LOCAL_REL = Path(".claude") / "lazy.settings.local.json"
_PRODUCTS_SECTION = "products"
_ASSET_TYPES_KEY = "asset_types"

# The review section, its list of classes, and the identity key of one class entry.
_REVIEW_SECTION = "review"
_CLASSES_KEY = "classes"
_CLASS_KEY = "class"

# The separator of a reported dotted settings path.
_PATH_SEP = "."

# A question callout's opening line, any callout's opening line, and a checkbox option line inside a callout.
_QUESTION_RE = re.compile(r"^>\s*\[!question\]", re.IGNORECASE)
_CALLOUT_OPEN_RE = re.compile(r"^>\s*\[!")
_OPTION_RE = re.compile(r"^>\s*[-*+]\s+\[[^\]]\]\s?(.*)$")

# The prefix of a quoted line, the prefix of an H1 heading line, and the separator between the tools of one option.
_QUOTE = ">"
_H1_PREFIX = "# "
_OPTION_SEP = ","

# The inline-code mark a tool name in an option may be wrapped in.
_BACKTICK = "`"

# The core verb the settings are written through, and its arguments.
_CORE_SET = "settings-set"
_VERBATIM_FLAG = "--verbatim"
_KEY_FLAG = "--key"
_VALUE_FLAG = "--value"
_SCOPE_FLAG = "--scope"
_LOCAL_SCOPE = "local"
_CWD_FLAG = "--cwd"

_MD_SUFFIX = ".md"
_ENCODING = "utf-8"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# How a subprocess's undecodable output bytes are read: replaced, so odd output never raises.
_DECODE_ERRORS = "replace"

# The seconds a core call may run before it counts as failed.
_CORE_TIMEOUT_S = 120

# The result's wire-shape keys, read by the migration step and the tests.
_KEYS_DROPPED_KEY = "keys_dropped"
_QUESTIONS_CUT_KEY = "questions_cut"
_FIELDS_DROPPED_KEY = "fields_dropped"
_CLASSES_DROPPED_KEY = "classes_dropped"
_CLASSES_KEPT_KEY = "classes_kept"
_CLASSES_SCOPED_KEY = "classes_scoped"
_TOOL_TYPES_FOUND_KEY = "tool_types_found"

# The result keys of the local overlay's settings: each is its tracked twin's key with the local prefix.
_LOCAL_FIELDS_DROPPED_KEY = "local_fields_dropped"
_LOCAL_CLASSES_DROPPED_KEY = "local_classes_dropped"
_LOCAL_CLASSES_KEPT_KEY = "local_classes_kept"
_LOCAL_CLASSES_SCOPED_KEY = "local_classes_scoped"
_LOCAL_TOOL_TYPES_FOUND_KEY = "local_tool_types_found"

# The result keys that count as pending work for `--check`; the others are reported for the operator only.
_PENDING_KEYS = ( _KEYS_DROPPED_KEY, _QUESTIONS_CUT_KEY, _FIELDS_DROPPED_KEY, _CLASSES_DROPPED_KEY,
                  _LOCAL_FIELDS_DROPPED_KEY, _LOCAL_CLASSES_DROPPED_KEY )

# The fields of one `classes_kept` entry.
_DOCUMENTS_FIELD = "documents"

# The products section's own schema-version entry, which is no product record.
_VERSION_KEY = "_version"

# The exit code of a failed run, told apart from both `--check` answers.
_EXIT_FAILED = 2


def migrate(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Move the repository off the tool layer.

  Guarantees:
    - In each settings layer, the tracked file and the local overlay, settings change only by dropping
      `default_tools` and `tools` from every product's asset types and by removing a bare `data-report` or
      `docs-report` review class no markdown document under the spec content root uses; all other keys and entries
      keep their order, and a `tools` key is never written.
    - The tracked settings file and the local overlay are each read and written alone; what is found in one layer is
      never written to the other.
    - An absent local overlay is never created.
    - A product's `tool_types`, a report class whose documents exist and a product-scoped `<kind>@<key>` class are
      left untouched and only reported.
    - On disk only status folder-notes change: the `spec_tools` key and the tool-set questions in `# Status brief`
      leave, and every other byte of such a note, foreign protected sections included, stays byte-for-byte.
    - Level notes and authored documents are never touched.
    - Both settings layers are written before any note.
    - A dry run writes nothing and calls no core `settings-set`.
    - A second run over the output of a first run changes nothing.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, report what would change and write nothing.

  Returns:
    The report of what changed, or would change in a dry run, as a dict with twelve keys. The first two describe the
    status notes, which belong to no settings layer; the next five describe the tracked settings, and the last five
    repeat those five for the local overlay under the `local_` prefix (for example `local_fields_dropped`), with
    empty lists for an absent overlay:
    - `keys_dropped`: settings-root-relative paths of the status notes that lose `spec_tools`, in walk order (sorted
      directories and files).
    - `questions_cut`: settings-root-relative paths of the status notes that lose a tool-set question, in walk order.
    - `fields_dropped`: dotted paths `products.<key>.asset_types.<type>.<field>` of the dropped asset-type fields, in
      settings order.
    - `classes_dropped`: the dropped bare report class tokens, in list order.
    - `classes_kept`: one `{class, documents}` entry per kept report class, in list order, with the documents as
      settings-root-relative paths in walk order.
    - `classes_scoped`: the scoped `<kind>@<key>` class tokens left in place, in list order.
    - `tool_types_found`: dotted paths `products.<key>.tool_types.<name>` from each product's own record, in settings
      order.

  Raises:
    FileNotFoundError: If no settings file exists at or above `repo`.
    ValueError: If the tracked settings or the local overlay is unreadable or not a JSON object.
    OSError: If a note cannot be read or written.
    RuntimeError: If a core call fails, times out or cannot be resolved.
    spec_paths.VaultRootError: If `spec.vault_root` is invalid or the settings are unreadable when the content root
      is resolved.
  """

  # Contract:
  # In each settings layer, the tracked file and the local overlay, settings change only in two places. Every
  # `products.<key>.asset_types.<type>` loses its `default_tools` and `tools` keys, and every other key stays in its
  # order. A bare `data-report` or `docs-report` entry of `review.classes` is removed only when no markdown document
  # under the spec content root carries that `spec_doc_type`, and the list order and every other entry stay as they
  # were. A `tools` key is never written. A product's `tool_types`, a report class whose documents exist and a
  # product-scoped `<kind>@<key>` class are left untouched and only reported.

  # Contract:
  # The tracked settings file and the local overlay are each read and written alone. What is found in one layer is
  # written to that layer only, and a write to one layer never touches the other.

  # Contract:
  # An absent local overlay MUST never be created.

  # Contract:
  # On disk only status folder-notes change. The `spec_tools` key and the tool-set `[!question]` callouts in
  # `# Status brief`, each with one following blank line, leave the note. A tool-set question is one whose every
  # checkbox option names only tool names: the frozen retired set `code`, `data`, `test`, `docs`, `research` plus
  # the owning product's own `tool_types` keys. Every other byte of such a note, foreign protected sections
  # included, MUST stay byte-for-byte. Level notes and authored documents are never touched.

  # Contract:
  # Both settings layers are written before any note.

  # Contract:
  # A dry run MUST write nothing and call no core `settings-set`.

  # Contract:
  # A second run over the output of a first run MUST change nothing.

  settings_root = spec_paths.require_settings_root(repo)
  settings = spec_paths.read_settings(settings_root / _SETTINGS_REL)

  # the overlay is read alone, never merged into the tracked layer; an absent one carries nothing and is never
  # created
  local_path = settings_root / _LOCAL_REL
  local = spec_paths.read_settings(local_path) if local_path.is_file() else {}

  # each layer's products section without the retired asset-type fields
  stored = settings.get(_PRODUCTS_SECTION)
  products, fields_dropped = _drop_type_fields(stored)
  local_products, local_fields_dropped = _drop_type_fields(local.get(_PRODUCTS_SECTION))
  registry = { key: record for key, record in stored.items() if key != _VERSION_KEY } \
      if isinstance(stored, dict) else {}

  # every status note's migrated text, and the documents of each retired report type, from one walk
  rewrites, keys_dropped, questions_cut, report_docs = _migrate_notes(settings_root, registry)

  # each layer's review classes without the retired report classes no document uses
  classes, classes_dropped, classes_kept, classes_scoped = _partition_classes(_get_classes(settings), report_docs)
  local_classes, local_classes_dropped, local_classes_kept, local_classes_scoped = _partition_classes(
      _get_classes(local), report_docs)

  # the report: what each layer and the status notes lost, kept or still carry
  result = {
      _KEYS_DROPPED_KEY: keys_dropped, _QUESTIONS_CUT_KEY: questions_cut, _FIELDS_DROPPED_KEY: fields_dropped,
      _CLASSES_DROPPED_KEY: classes_dropped, _CLASSES_KEPT_KEY: classes_kept, _CLASSES_SCOPED_KEY: classes_scoped,
      _TOOL_TYPES_FOUND_KEY: _find_all_tool_types(stored),
      _LOCAL_FIELDS_DROPPED_KEY: local_fields_dropped, _LOCAL_CLASSES_DROPPED_KEY: local_classes_dropped,
      _LOCAL_CLASSES_KEPT_KEY: local_classes_kept, _LOCAL_CLASSES_SCOPED_KEY: local_classes_scoped,
      _LOCAL_TOOL_TYPES_FOUND_KEY: _find_all_tool_types(local.get(_PRODUCTS_SECTION)),
  }

  # a dry run stops at the report
  if dry_run:
    return result

  # each settings section goes back to its own layer through the core verb only when it changed, both layers before
  # any note is touched
  if fields_dropped:
    _write_settings(settings_root, _PRODUCTS_SECTION, _VERBATIM_FLAG, payload = json.dumps(products))
  if classes_dropped:
    _write_settings(settings_root, _REVIEW_SECTION, _KEY_FLAG, _CLASSES_KEY, _VALUE_FLAG, json.dumps(classes))
  if local_fields_dropped:
    _write_settings(settings_root, _PRODUCTS_SECTION, _SCOPE_FLAG, _LOCAL_SCOPE,
                    payload = json.dumps(local_products))
  if local_classes_dropped:
    _write_settings(settings_root, _REVIEW_SECTION, _SCOPE_FLAG, _LOCAL_SCOPE, _KEY_FLAG, _CLASSES_KEY, _VALUE_FLAG,
                    json.dumps(local_classes))

  # then every changed note
  for note, text in rewrites:
    spec_paths.write_text_atomic(note, text)
  return result


# waiver: the returned `review.classes` value is raw operator-edited JSON of any shape; callers narrow it
def _get_classes(settings: dict) -> object:
  """
  Take the review classes out of one already-parsed settings layer.

  Args:
    settings: One parsed settings layer, the tracked file or the local overlay.

  Returns:
    The `review.classes` value as the layer stores it; None when the layer carries none.
  """
  # the classes list as the layer stores it; a missing or malformed `review` section carries none
  review = settings.get(_REVIEW_SECTION)
  return review.get(_CLASSES_KEY) if isinstance(review, dict) else None


# waiver: `products` is the raw `products` value of operator-edited JSON and may be any JSON value; the body narrows
# it and hands a non-object back as read
def _drop_type_fields(products: object) -> tuple[object, list[str]]:
  """
  Delete the retired tool-set fields from every product's asset types.

  Args:
    products: The products section as stored.

  Returns:
    The section without the retired fields, and the dotted paths `products.<key>.asset_types.<type>.<field>` of the
    dropped fields in settings order.
  """
  # guard: a missing or malformed section carries nothing to delete
  if not isinstance(products, dict):
    return products, []

  # one pass in stored order, so every product, type and remaining key stays where it was
  migrated: dict = {}
  dropped: list[str] = []
  for product, record in products.items():
    # guard: the schema-version entry and a product without asset types go back as read
    if not isinstance(declared := (record.get(_ASSET_TYPES_KEY) if isinstance(record, dict) else None), dict):
      migrated[product] = record
      continue

    # each declaration loses the retired fields it carries; a non-object declaration goes back as read
    types: dict = {}
    for name, decl in declared.items():
      # guard: a non-object declaration carries no fields to delete
      if not isinstance(decl, dict):
        types[name] = decl
        continue
      types[name] = { key: value for key, value in decl.items() if key not in _RETIRED_TYPE_FIELDS }
      dropped.extend(
          _PATH_SEP.join(( _PRODUCTS_SECTION, product, _ASSET_TYPES_KEY, name, key ))
          for key in decl if key in _RETIRED_TYPE_FIELDS
      )
    migrated[product] = { **record, _ASSET_TYPES_KEY: types }
  return migrated, dropped


# waiver: `products` is the raw `products` value of operator-edited JSON and may be any JSON value; the body narrows
# it
def _find_all_tool_types(products: object) -> list[str]:
  """
  List the tool declarations the products carry of their own.

  Args:
    products: The products section as stored.

  Returns:
    The dotted paths `products.<key>.tool_types.<name>` from each product's own record, in settings order.
  """
  # guard: a missing or malformed section declares nothing
  if not isinstance(products, dict):
    return []

  # each product's own declarations, never an inherited one, so a declaration is named once
  found: list[str] = []
  for product, record in products.items():
    declared = record.get(_TOOL_TYPES_KEY) if isinstance(record, dict) else None
    if isinstance(declared, dict):
      found.extend(_PATH_SEP.join(( _PRODUCTS_SECTION, product, _TOOL_TYPES_KEY, name )) for name in declared)
  return found


def _migrate_notes(settings_root: Path, registry: dict) -> tuple[
    list[tuple[Path, str]], list[str], list[str], dict[str, list[str]]]:
  """
  Compute the migrated text of every status note under the spec content root, without writing any.

  Args:
    settings_root: The settings root.
    registry: The products registry without its schema-version entry.

  Returns:
    Four values, with all paths relative to the settings root and in walk order (sorted directories and files):
    - The notes whose text changes, each paired with its new text.
    - The paths of the notes that lose `spec_tools`.
    - The paths of the notes that lose a tool-set question.
    - The paths of the documents of each retired report type, keyed by type.

  Raises:
    OSError: If a note cannot be read.
    spec_paths.VaultRootError: If the spec content root cannot be resolved.
  """
  content_root = spec_paths.spec_content_root(settings_root)
  rewrites: list[tuple[Path, str]] = []
  keys_dropped: list[str] = []
  questions_cut: list[str] = []
  report_docs: dict[str, list[str]] = {}

  # every markdown file under the content root, in a stable order
  for dirpath, dirnames, filenames in os.walk(content_root):
    dirnames.sort()
    for name in sorted(filenames):

      # guard: only markdown files carry frontmatter
      if not name.endswith(_MD_SUFFIX):
        continue

      # the file's text, frontmatter and path, read once for every check below
      note = Path(dirpath) / name
      text = spec_paths.read_text(note)
      frontmatter = spec_frontmatter.parse(text)[0]
      rel = note.relative_to(settings_root).as_posix()

      # a document of a retired report type keeps its review class, whatever its role
      doc_type = frontmatter.get(_DOC_TYPE_KEY, "")
      if isinstance(doc_type, str) and doc_type.strip() in _RETIRED_REPORTS:
        report_docs.setdefault(doc_type.strip(), []).append(rel)

      # guard: only an asset's status note carried the tool set
      role = frontmatter.get(SpecKey.ROLE, "")
      if not isinstance(role, str) or role.strip() != SpecValue.ROLE_STATUS:
        continue

      # the note is judged against its owning product, whose own tool declarations widen the tool names
      record = resolve_product.effective_record_by_path(
          settings_root, note.relative_to(content_root).as_posix(), products = registry)[1]
      new_text, key_dropped, question_cut = _migrate_text(text, record or {})

      # a changed note is reported under each change it carries and queued for writing
      if key_dropped:
        keys_dropped.append(rel)
      if question_cut:
        questions_cut.append(rel)
      if new_text != text:
        rewrites.append(( note, new_text ))
  return rewrites, keys_dropped, questions_cut, report_docs


# waiver: `classes` is the raw `review.classes` value of operator-edited JSON and may be any JSON value; the body
# narrows it and hands a non-list back as read
def _partition_classes(classes: object, report_docs: dict[str, list[str]]) -> tuple[
    object, list[str], list[dict], list[str]]:
  """
  Decide the fate of each retired report class in the review classes.

  Args:
    classes: The `review.classes` value of one settings layer as stored.
    report_docs: The settings-root-relative paths of the documents of each retired report type, keyed by type.

  Returns:
    Four values, each in list order:
    - The classes list without the dropped entries.
    - The dropped class tokens.
    - One `{class, documents}` entry per kept class, with its documents in walk order.
    - The scoped class tokens left in place.
  """
  # guard: a missing or malformed list carries no class to drop
  if not isinstance(classes, list):
    return classes, [], [], []

  # one pass in list order, so every entry left stays where it was
  remaining: list = []
  dropped: list[str] = []
  kept: list[dict] = []
  scoped: list[str] = []
  for entry in classes:
    token = entry.get(_CLASS_KEY) if isinstance(entry, dict) else None
    kind = token.split(_SCOPE_SEP, 1)[0] if isinstance(token, str) else None

    # any class other than a retired report class goes back as read
    if not isinstance(token, str) or kind not in _RETIRED_REPORTS:
      remaining.append(entry)
      continue

    # a scoped class stays as the operator wired it, a class with documents stays for them, any other leaves
    if token != kind:
      scoped.append(token)
      remaining.append(entry)
    elif report_docs.get(token):
      kept.append({ _CLASS_KEY: token, _DOCUMENTS_FIELD: list(report_docs[token]) })
      remaining.append(entry)
    else:
      dropped.append(token)
  return remaining, dropped, kept, scoped


def _migrate_text(text: str, record: dict) -> tuple[str, bool, bool]:
  """
  Remove the retired tool-set markup from one status note's text.

  The `spec_tools` frontmatter key and the tool-set questions leave; every other byte of the text is kept.

  Args:
    text: The note's full text.
    record: The owning product's effective record, or `{}`.

  Returns:
    The migrated text, whether `spec_tools` was dropped, and whether a tool-set question was cut.
  """
  dropped = spec_frontmatter.drop_key(text, _SPEC_TOOLS_KEY)
  fm_end = spec_frontmatter.block(dropped)[1]

  # the body loses its tool-set questions; the frontmatter is carried over as the key drop left it
  body = dropped[fm_end:]
  new_body = _cut_questions(body, record)
  return dropped[:fm_end] + new_body, dropped != text, new_body != body


def _cut_questions(body: str, record: dict) -> str:
  """
  Remove the tool-set questions from a note body's `# Status brief` section.

  Question callouts in other sections and inside code fences are kept, as is every other line, byte for byte.

  Args:
    body: The note body after the frontmatter.
    record: The owning product's effective record, or `{}`.

  Returns:
    The body without the tool-set question callouts and the one blank line that follows each.
  """
  lines = spec_frontmatter.split_lines(body, keepends = True)
  bare = spec_frontmatter.split_lines(body)
  fenced = spec_frontmatter.fenced_lines(bare)

  # one pass over the lines; an H1 outside a fence opens a section, and only `# Status brief` is searched
  out: list[str] = []
  in_brief = False
  index = 0
  while index < len(lines):
    line = bare[index]
    if not fenced[index] and line.startswith(_H1_PREFIX):
      in_brief = line.rstrip() == Section.STATUS_BRIEF

    # a tool-set question leaves together with one blank line after it; any other line is kept
    if in_brief and not fenced[index] and _QUESTION_RE.match(line):
      end = _callout_end(bare, index)
      if _is_tool_set(bare[index:end], record):
        index = end + 1 if end < len(bare) and not bare[end].strip() else end
        continue
    out.append(lines[index])
    index += 1
  return "".join(out)


def _callout_end(lines: list[str], start: int) -> int:
  """
  Find where the callout opening at `start` ends.

  Args:
    lines: The body's lines without their endings.
    start: Index of the callout's opening line.

  Returns:
    Index of the first line after the callout: the first line not quoted, or the opening line of the next callout.
  """
  # the callout runs over the quoted lines that follow it, up to the next callout's own opening
  end = start + 1
  while end < len(lines) and lines[end].startswith(_QUOTE) and not _CALLOUT_OPEN_RE.match(lines[end]):
    end += 1
  return end


def _is_tool_set(callout: list[str], record: dict) -> bool:
  """
  Report whether a question callout asks for a tool set.

  A tool name in an option may be wrapped in backticks, and one option may list several names separated by commas.

  Args:
    callout: The callout's lines.
    record: The owning product's effective record, or `{}`.

  Returns:
    True when the callout has at least one checkbox option and every option names only tools the product sees.
  """
  options = [ match.group(1) for line in callout if (match := _OPTION_RE.match(line)) ]

  # guard: a question without options offers no tool set
  if not options:
    return False

  # the tools the product sees: the retired shipped names and the product's own declarations
  declared = record.get(_TOOL_TYPES_KEY)
  tools = _BUILTIN_TOOLS | set(declared if isinstance(declared, dict) else ())

  # every comma-separated part of every option, unwrapped from inline-code backticks, must be a tool the product sees
  parts = [
    part.strip().removeprefix(_BACKTICK).removesuffix(_BACKTICK).strip()
    for option in options for part in option.split(_OPTION_SEP)
  ]
  return all(part and part in tools for part in parts)


def _write_settings(settings_root: Path, *args: str, payload: str | None = None) -> None:
  """
  Write one settings section, or one key of it, through the core `settings-set` verb.

  Args:
    settings_root: The settings root.
    *args: The section and the verb's further arguments.
    payload: The text sent on stdin, for a whole-section write; None for a keyed write.

  Raises:
    RuntimeError: When the core CLI cannot be resolved or started, runs past its time limit, or exits non-zero.
  """
  # a spawn the system refuses, or a call that runs past its time limit, is a failed core call like any other;
  # undecodable output bytes are replaced, never raised on
  try:
    res = subprocess.run(
        [ sys.executable, str(spec_paths.resolve_core_cli(settings_root)), _CORE_SET, *args,
          _CWD_FLAG, str(settings_root) ],
        input = payload, cwd = str(settings_root), capture_output = True, text = True, check = False,
        encoding = _ENCODING, errors = _DECODE_ERRORS, timeout = _CORE_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as error:
    raise RuntimeError(f"{_CORE_SET} {args[0]} timed out after {_CORE_TIMEOUT_S}s") from error
  except (OSError, ValueError) as error:
    raise RuntimeError(f"{_CORE_SET} {args[0]} could not run: {error}") from error

  # guard: a failed core call leaves the settings unwritten, so the run stops before any note is touched
  if res.returncode != 0:
    raise RuntimeError(
        f"{_CORE_SET} {args[0]} failed: exit={res.returncode} stderr={res.stderr.strip()[:240]} "
        f"stdout={res.stdout.strip()[:240]}")


def main(argv: list[str]) -> int:
  """
  Run `migrate` from the command line and print its result as JSON.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when any of `keys_dropped`, `questions_cut`, `fields_dropped`,
      `classes_dropped`, `local_fields_dropped` or `local_classes_dropped` is non-empty, 1 when all six are empty;
      `classes_kept`, `classes_scoped`, `tool_types_found` and their `local_` twins are reported but are not pending
      work.
    - Any failure of the migration exits 2 under every flag, never an answer `--check` gives.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--check` reports
      without writing and answers through the exit code whether anything is left to migrate, `--cwd` names the
      repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: with `--check`, 0 when pending work remains and 1 when none does; 0 otherwise; 2 when the migration
    failed.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when any of `keys_dropped`, `questions_cut`,
  # `fields_dropped`, `classes_dropped`, `local_fields_dropped` or `local_classes_dropped` is non-empty, 1 when all
  # six are empty; `classes_kept`, `classes_scoped`, `tool_types_found` and their `local_` twins are reported but are
  # not pending work.

  # Contract:
  # Any failure of the migration MUST exit 2 under every flag, so a migration step's `applies_when` predicate never
  # reads a failure as an answer.

  # the verb's flags: two ways to run without writing, and the repository root
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs migrate-spec-tools")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the repo root comes from `--cwd`, else the daemon's env var, else the process cwd
  repo = Path(args.cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()

  # a check runs dry; any failure exits 2, so no flag ever reads a failure as an answer
  try:
    result = migrate(repo, dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    sys.stderr.write(f"migrate-spec-tools: {error!r}\n")
    return _EXIT_FAILED
  # a refused content root is a `BaseException` the broad catch above lets through; it fails the run the same way
  except spec_paths.VaultRootError as error:
    sys.stderr.write(f"migrate-spec-tools: {error!r}\n")
    return _EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result, ensure_ascii = False))

  # only a check answers through its exit code
  if args.check:
    return 0 if any(result[key] for key in _PENDING_KEYS) else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
