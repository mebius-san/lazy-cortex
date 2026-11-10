from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    LEVEL_ROLES, SpecKey, SpecValue,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_markers import Markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The two frontmatter lists the `# Sources` container projects.
SOURCE_DOCS = "spec_source_docs"
SOURCE_REQUESTS = "spec_source_requests"

# The refusal reasons: a folder-note, and a document type that carries no source lists.
REASON_FOLDER_NOTE = "folder-note"
REASON_NO_SOURCES = "no-source-docs"

# The value a projection field takes when its sub-section was already in step.
UNCHANGED = "unchanged"

# The verb's output keys and status word.
_DOC = "doc"
_DOCS = "docs"
_REQUESTS = "requests"
_TOUCHED = "touched_paths"
_STATUS = "status"
_REASON = "reason"
_REFUSED = "refused"

# The wikilink brackets, the display separator and the quotes a frontmatter member may carry.
_LINK_OPEN = "[["
_LINK_CLOSE = "]]"
_PIPE = "|"
_QUOTES = "\"'"
_SEP = "/"

# The settings key naming a product's catalog folder.
_SPEC_PATH = "spec_path"

# The verb's exit codes.
_EXIT_OK = 0
_EXIT_REFUSED = 1


# ----------------------------------------------------------------------------------------
class SourcesRefreshRefusedError(Exception):
  """
  Refusal to refresh a document's sources sections.

  Attributes:
    reason: Short reason word naming why the document was refused.
  """

  def __init__(self, reason: str) -> None:
    # the exception's own message is the reason itself
    super().__init__(reason)

    # the reason, kept for callers that report it without parsing the message
    self.reason: str = reason


def _parse_target(member: str) -> str:
  """
  Reduce a frontmatter list member to its wikilink target.

  Args:
    member: Member text, possibly quoted, bracketed or glossed.

  Returns:
    The bare target path.
  """
  # a member may be quoted, bracketed and glossed; the target is what remains
  bare = member.strip().strip(_QUOTES).strip()
  bare = bare.removeprefix(_LINK_OPEN).removesuffix(_LINK_CLOSE)
  return bare.split(_PIPE, 1)[0].strip()


def _load_product_paths(repo: Path) -> dict[str, str]:
  """
  Collect the catalog path of every configured product.

  Args:
    repo: Repository root holding the settings.

  Returns:
    Map from a product's catalog path, in short form and in vault form, to the product key.
  """
  vault = spec_paths.spec_content_root(repo).relative_to(repo).as_posix()

  # every product path is known in its short form and in the vault form
  paths: dict[str, str] = {}
  for key, record in resolve_product.load_products(repo).items():
    spec_path = record.get(_SPEC_PATH) if isinstance(record, dict) else None
    if isinstance(spec_path, str) and spec_path:
      paths[spec_path] = key
      paths[f"{vault}{_SEP}{spec_path}"] = key
  return paths


def _require_source_lists(doc: Path, repo: Path, values: dict) -> None:
  """
  Refuse documents that carry no source lists.

  Args:
    doc: Path of the document.
    repo: Repository root.
    values: Parsed frontmatter values of the document.

  Raises:
    SourcesRefreshRefusedError: If the document is a folder-note, or its type is undeclared or carries no stages.
  """

  # Domain(spec.notes):
  # # Which documents carry source lists
  # Only an authored document whose type keeps a stage carries source lists, because only such a document is written
  # from requests and companion documents. A folder-note never does, whether it is an asset's status note or a
  # catalog or product level note: it is a status artifact that summarises, and it has no references of its own.

  role = values.get(SpecKey.ROLE)

  # guard: a folder-note is a status artifact with no companion references
  if role == SpecValue.ROLE_STATUS or role in LEVEL_ROLES:
    raise SourcesRefreshRefusedError(REASON_FOLDER_NOTE)

  # the document's type and the declaration its product resolves for it
  doc_type = spec_doc_types.doc_type_of(doc)
  rel = doc.resolve().relative_to(repo).as_posix() if doc.resolve().is_relative_to(repo) else doc.as_posix()
  product, _record = resolve_product.resolve_product_by_path(repo, rel)
  declaration = spec_doc_types.resolve(repo, doc_type, product) if doc_type else None

  # guard: only a stage-bearing authored document carries the source lists
  if not declaration or not declaration.get(spec_doc_types.DocTypeFlag.STAGES):
    raise SourcesRefreshRefusedError(REASON_NO_SOURCES)


def refresh_sources(doc: Path, *, set_docs: list[str] | None = None, today: str | None = None) -> dict:
  """
  Re-project a document's `## Requests` and `## Docs` sections from its frontmatter lists.

  Guarantees:
    - The document is written only when its text actually changes; an already-in-step document is left untouched and
      reports no touched path.
    - Nothing is committed; the caller owns the commit.

  Args:
    doc: Path of the document to refresh.
    set_docs: Targets that replace `spec_source_docs` before projecting; the list is left as is when `None`.
    today: Date, as `YYYY-MM-DD`, stamped on new request bullets; the current date when `None`.

  Returns:
    Result mapping with the document path, the `docs` and `requests` entries holding a bullet count or
    `"unchanged"`, and `touched_paths` listing the document when it was written.

  Raises:
    SourcesRefreshRefusedError: If the document is a folder-note, or its type is undeclared or carries no stages.
  """

  # Contract:
  # The document is written only when its text actually changes; a refresh that finds the sections
  # already in step leaves the file untouched and reports no touched path.

  # Contract:
  # The refresh never commits; the caller owns the commit and folds the reported touched paths into it.

  # the settings root and the document's current text and frontmatter
  repo = spec_paths.find_settings_root(doc.parent)
  original = spec_paths.read_text(doc)
  values, fm_end = spec_frontmatter.parse(original)
  _require_source_lists(doc, repo, values)

  # an explicit docs list replaces the frontmatter's before anything is projected
  front, body = original[:fm_end], original[fm_end:]
  if set_docs is not None:
    front = spec_frontmatter.write_list(front, SOURCE_DOCS, [ f"{_LINK_OPEN}{target}{_LINK_CLOSE}"
                                                              for target in set_docs ])

  # the targets both sub-sections project, each named once in listed order
  docs = list(dict.fromkeys(_parse_target(member) for member in spec_frontmatter.read_list(front, SOURCE_DOCS)))
  requests = list(dict.fromkeys(
      _parse_target(member) for member in spec_frontmatter.read_list(front, SOURCE_REQUESTS)))

  # both sub-sections are projected from the frontmatter, requests first as the container lays them out
  markers = Markers()
  projected_requests = markers.project_requests(body, requests, today = flip_gate.effective_today(today))
  projected = markers.project_docs(projected_requests, docs, products = _load_product_paths(repo))

  # the document is written only when a byte changed
  text = front + projected
  touched = []
  if text != original:
    spec_paths.write_text_atomic(doc, text)
    touched.append(str(doc))

  # `## Docs` counts as changed when its projection or the frontmatter moved; `## Requests` when its own projection did
  docs_changed = projected != projected_requests or front != original[:fm_end]
  return { _DOC: str(doc), _DOCS: len(docs) if docs_changed else UNCHANGED,
           _REQUESTS: len(requests) if projected_requests != body else UNCHANGED, _TOUCHED: touched }


def main(argv: list[str]) -> int:
  """
  Run the `refresh-sources` command.

  Prints one JSON line: the refresh result, or a refusal record with its reason and the document.

  Args:
    argv: Command-line arguments after the verb: the document, optional `--set-docs` targets and `--today`.

  Returns:
    Exit code `0` on success and `1` on a refusal.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs refresh-sources")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("doc", type = Path)
  # waiver: argparse CLI signature -- repeatable option flag taking any number of targets
  parser.add_argument("--set-docs", nargs = "*", action = "extend", default = None)
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--today", default = None)
  args = parser.parse_args(argv)

  # one JSON line carries the result; a refusal is printed and carried by the exit code
  try:
    result = refresh_sources(args.doc, set_docs = args.set_docs, today = args.today)
  except SourcesRefreshRefusedError as refused:
    print(json.dumps({ _STATUS: _REFUSED, _REASON: refused.reason, _DOC: str(args.doc) }, ensure_ascii = False))
    return _EXIT_REFUSED
  print(json.dumps(result, ensure_ascii = False))
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
