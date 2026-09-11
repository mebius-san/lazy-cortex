"""
Document→review-class resolution.

A class's `class` label IS its identity: for a document carrying `spec_doc_type`, the label's
part before `@` is the type it serves, and the part after it (when present) scopes the class to
one product. Resolution is therefore type-first — among the classes serving the document's type,
a product-scoped one whose `paths` cover the file wins, otherwise the bare-type class does.

A document carrying no `spec_doc_type` is not a typed catalog document at all (a free-form
intake file, a consumer's own document class), and falls back to first-match glob scan over
`paths` in list order. This module is the single class resolver for the whole plugin: every
verb that needs a document's class asks here.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import sys
from pathlib import Path, PurePosixPath

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import JobKey  # noqa: E402


# The specs plugin's own frontmatter key, mirrored file-wise rather than imported — a
# cross-plugin Python import breaks across plugin versions (`dev.plugin-boundaries.md` § 2a).
_SPEC_DOC_TYPE = "spec_doc_type"

# The label separator scoping a class to one product: `<type>@<product>`.
_SCOPE_SEP = "@"


def _rel_for(repo: Path, file_path: Path) -> PurePosixPath | None:
  """
  Express a document's path relative to the repository root, POSIX-style.

  Args:
    repo: Repository root the class globs are relative to.
    file_path: The document being matched.

  Returns:
    The repo-relative path, or None when the document is outside the repo or does not exist.
  """
  fp = file_path.resolve()
  # guard: a path outside the repo (or a vanished file) belongs to no class
  try:
    rel = PurePosixPath(fp.relative_to(repo.resolve()).as_posix())
  except ValueError:
    return None
  return rel if fp.is_file() else None


def _paths_match(class_cfg: dict, rel: PurePosixPath) -> bool:
  """
  Check whether any of a class's `paths` globs cover a repo-relative path.

  Args:
    class_cfg: The class config dict.
    rel: The document's repo-relative path.

  Returns:
    True when at least one glob matches; False otherwise.
  """
  return any(rel.match(pat) for pat in class_cfg.get(JobKey.PATHS) or [])


def class_for_file(settings: dict, repo: Path, file_path: Path) -> dict | None:
  """
  Resolve the review class one document belongs to.

  A document carrying `spec_doc_type` matches by type: a `<type>@<product>` class whose `paths`
  cover the file outranks the bare `<type>` class, and a type with no class at all resolves to
  None (a type declared `review: false` is expected to have none). A document with no type falls
  back to the first class whose `paths` match it.

  Guarantees:
    - Among the classes serving a document's `spec_doc_type`, a product-scoped class whose
      `paths` cover the document always outranks the bare, type-only class.
    - A document carrying no `spec_doc_type` resolves to the first configured class whose
      `paths` cover it, in configuration order.

  Args:
    settings: Parsed `lazy.settings.json` contents.
    repo: Repository root the glob patterns are relative to.
    file_path: The document to resolve.

  Returns:
    The matching class config dict, or None when nothing matches.
  """

  # Domain(review.config):
  # # Review-class resolution for a document
  # A document's review class is identified by its class label: the segment before an `@`
  # separator names the document type the class serves, and an optional segment after it
  # scopes the class to one product. Among the classes serving a document's type, the
  # product-scoped class wins whenever its paths cover the file; the bare, type-only class is
  # the fallback otherwise. A type with no matching class at all resolves to no review class,
  # by design. A document carrying no recognized type is not a typed catalog document, and
  # instead resolves to the first configured class whose paths cover it.

  # Contract:
  # Among the classes serving a document's `spec_doc_type`, a product-scoped class whose
  # `paths` cover the document always outranks the bare, type-only class; a type with no
  # matching class resolves to `None`. A document carrying no `spec_doc_type` resolves to
  # the first configured class whose `paths` cover it, in configuration order.

  rel = _rel_for(repo, file_path)

  # guard: not a readable file inside the repo — no class
  if rel is None:
    return None

  # the two inputs every branch below needs: the configured classes and the document's own type
  classes = settings.get(JobKey.REVIEW, {}).get(JobKey.CLASSES) or []
  meta, _body = _fm.parse(file_path.read_text())
  doc_type = meta.get(_SPEC_DOC_TYPE)

  # an untyped document keeps the historical first-match glob behaviour
  if not doc_type:
    for class_cfg in classes:
      if _paths_match(class_cfg, rel):
        return class_cfg
    return None

  # a typed document matches on the label, with the product-scoped entry preferred
  fallback = None
  for class_cfg in classes:
    label = str(class_cfg.get(JobKey.CLASS) or "")
    type_part, _, scope = label.partition(_SCOPE_SEP)
    # guard: a class serving some other type has nothing to say about this document
    if type_part != doc_type:
      continue
    if scope and _paths_match(class_cfg, rel):
      return class_cfg
    if not scope and fallback is None:
      fallback = class_cfg
  return fallback
