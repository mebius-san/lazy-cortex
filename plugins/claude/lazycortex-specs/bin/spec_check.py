"""
Read-only structural check of the markdown files under a spec directory.

Implements the `spec-check` verb of the specs CLI, used by the `lazy-spec.audit` skill. Every finding is a mapping
with `path` (relative to the scanned root), `kind` and `detail`; `kind` comes from the closed set of finding
kinds held in the module's constants. The check never writes a file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import set_stage  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import AttachmentKey, Section, SpecKey, StageKey  # noqa: E402


# The closed set of finding kinds.
STAGE_NOT_IN_SET = "stage-not-in-set"
STAGE_TAG_MIRROR = "stage-tag-mirror"
ATTACHMENT_STAGE_MIRROR = "attachment-stage-mirror"
GATE_BLOCK_UNLABELLED = "gate-block-unlabelled"
CHECKBOX_OUTSIDE_GATE = "checkbox-outside-gate"

# The keys of one finding.
_PATH = "path"
_KIND = "kind"
_DETAIL = "detail"

# The verb's exit codes: a finished check whatever it found, and a missing directory.
_EXIT_OK = 0
_EXIT_USAGE = 2

# The markdown suffix, the hidden-entry prefix, the frontmatter list of tags and the stage tag family.
_MD = ".md"
_HIDDEN = "."
_TAGS = "tags"
_STAGE_TAG_PREFIX = "spec/"
_TRUE = "true"
_ENCODING = "utf-8"

# The roles of a coordination folder-note, the notes that carry a `# Gates` section.
_NOTE_ROLES = frozenset({ "status", "product", "catalog" })

# The frontmatter fence and the H1 heading prefix that bound a note's sections.
_FENCE = "---"
_H1_PREFIX = "# "

# A callout's opening line, a gate callout's opening line capturing its label, and a checkbox line at any depth.
_QUOTE = ">"
_CALLOUT_HEAD_RE = re.compile(r"^>\s*\[!")
_GATE_HEAD_RE = re.compile(r"^>\s*\[!gate\](.*)$")
_CHECKBOX_RE = re.compile(r"^(?:>\s*)*[-*]\s+\[[ xX]\]")


def _build_finding(path: str, kind: str, detail: str) -> dict[str, str]:
  """
  Build one finding.

  Args:
    path: The document path relative to the scanned root.
    kind: The finding kind, one of the module's kind constants.
    detail: The human-readable explanation of the finding.

  Returns:
    The finding mapping with `path`, `kind` and `detail`.
  """
  return { _PATH: path, _KIND: kind, _DETAIL: detail }


def _is_staged_type(repo: Path, rel_repo: str, doc_type: str) -> bool:
  """
  Tell whether a document type carries a stage in the product the document sits under.

  Args:
    repo: The settings root of the repository.
    rel_repo: The document path relative to the repository root.
    doc_type: The document type name.

  Returns:
    True when the type's declaration, resolved in the scope of that product, has `stages: true`.
  """
  # the type's own declaration, in the scope of the product the document sits under
  product, _record = resolve_product.resolve_product_by_path(repo, rel_repo)
  declaration = spec_doc_types.resolve(repo, doc_type, product)
  return bool(declaration and declaration.get(spec_doc_types.DocTypeFlag.STAGES))


def _find_all_stage_findings(rel: str, text: str, values: dict) -> list[dict[str, str]]:
  """
  Report stage problems of a staged document.

  A value outside the stage set is reported as
  `stage-not-in-set`. Stage tags other than exactly `spec/<stage>` (missing, stale or duplicated) are reported as
  `stage-tag-mirror`. A document without a stage gets no finding.

  Args:
    rel: The document path relative to the scanned root.
    text: The full document text.
    values: The document's frontmatter values.

  Returns:
    The findings, empty when the stage and its tag are consistent or the document has no stage.
  """
  stage = values.get(StageKey.STAGE, "")

  # guard: a staged type without a stage is no closed-set or mirror question
  if not stage:
    return []

  # the value against the closed set
  found: list[dict[str, str]] = []
  if stage not in set_stage.STAGES:
    found.append(_build_finding(rel, STAGE_NOT_IN_SET,
                                f"spec_stage `{stage}` is not in the closed set {' | '.join(set_stage.STAGES)}"))

  # the mirror tag family must hold exactly the stage's own tag
  mirror = [ tag for tag in spec_frontmatter.read_list(text, _TAGS) if tag.startswith(_STAGE_TAG_PREFIX) ]
  if mirror != [ f"{_STAGE_TAG_PREFIX}{stage}" ]:
    found.append(_build_finding(rel, STAGE_TAG_MIRROR, f"spec_stage `{stage}` but stage tags {mirror}"))
  return found


def _find_all_attachment_findings(path: Path, rel: str, values: dict) -> list[dict[str, str]]:
  """
  Report an attachment whose stage differs from its owner document's stage.

  Nothing is reported while the attachment has `review_active: true`, when the owner file is missing, or when the
  owner carries no stage.

  Args:
    path: The attachment file path.
    rel: The attachment path relative to the scanned root.
    values: The attachment's frontmatter values.

  Returns:
    A single `attachment-stage-mirror` finding, or an empty list when there is nothing to report.
  """
  owner = path.parent / values[AttachmentKey.OWNER_DOC]

  # guard: an attachment in its own review catches up on its finalize wake, and a missing owner mirrors nothing
  if values.get(SpecKey.REVIEW_ACTIVE) == _TRUE or not owner.is_file():
    return []

  # the attachment's stage must copy its owner's
  owner_stage = spec_frontmatter.parse(spec_paths.read_text(owner))[0].get(StageKey.STAGE, "")
  stage = values.get(StageKey.STAGE, "")

  # guard: an owner without a stage, or an attachment already at it, is no drift
  if not owner_stage or stage == owner_stage:
    return []
  return [ _build_finding(rel, ATTACHMENT_STAGE_MIRROR,
                          f"spec_stage `{stage or 'none'}` differs from owner `{owner.name}` at `{owner_stage}`") ]


def _gates_lines(lines: list[str]) -> list[str]:
  """
  Extract the lines of the `# Gates` section.

  The heading is looked up outside the frontmatter and outside code fences; the section ends at the next H1.

  Args:
    lines: The document lines.

  Returns:
    The lines of the section body, empty when the section is absent.
  """
  # the body starts after a leading frontmatter block
  start = 0
  if lines and lines[0].rstrip() == _FENCE:
    start = next(( idx + 1 for idx in range(1, len(lines)) if lines[idx].rstrip() == _FENCE ), len(lines))

  # the `# Gates` heading outside every code fence, up to the next H1
  fenced = spec_frontmatter.fenced_lines(lines)
  head = next(( idx for idx in range(start, len(lines))
                if not fenced[idx] and lines[idx].rstrip() == Section.GATES ), None)

  # guard: a note without the section has no blocks to check
  if head is None:
    return []

  # the section's lines, from below the heading to the next H1 outside a fence
  end = next(( idx for idx in range(head + 1, len(lines)) if not fenced[idx] and lines[idx].startswith(_H1_PREFIX) ),
             len(lines))
  return lines[head + 1:end]


def _find_all_gate_findings(rel: str, text: str) -> list[dict[str, str]]:
  """
  Report malformed launch-checkbox blocks in the `# Gates` section.

  A `[!gate]` callout whose head line carries no label is reported as `gate-block-unlabelled`. A checkbox line
  that sits inside no callout is reported as `checkbox-outside-gate`; gate, question and conflict callouts all
  count as callouts.

  Args:
    rel: The document path relative to the scanned root.
    text: The full document text.

  Returns:
    The findings, empty when the section is absent or well-formed.
  """
  section = _gates_lines(spec_frontmatter.split_lines(text))
  found: list[dict[str, str]] = []
  inside = [ False ] * len(section)
  pos = 0
  while pos < len(section):
    # a line that opens no callout belongs to none: scan on
    if not _CALLOUT_HEAD_RE.match(section[pos]):
      pos += 1
      continue

    # the callout runs over the consecutive quoted lines, stopping where another callout opens
    end = pos + 1
    while end < len(section) and section[end].startswith(_QUOTE) and not _CALLOUT_HEAD_RE.match(section[end]):
      end += 1
    inside[pos:end] = [ True ] * ( end - pos )

    # a gate callout names its label on its head line
    gate = _GATE_HEAD_RE.match(section[pos])
    if gate is not None and not gate.group(1).strip():
      found.append(_build_finding(rel, GATE_BLOCK_UNLABELLED,
                                  f"`[!gate]` block without a label: `{section[pos].strip()}`"))
    pos = end

  # every checkbox in the section sits inside a callout
  found.extend(_build_finding(rel, CHECKBOX_OUTSIDE_GATE, f"checkbox outside any callout: `{line.strip()}`")
               for line, held in zip(section, inside, strict = True) if not held and _CHECKBOX_RE.match(line))
  return found


def _scan_file(repo: Path, root: Path, path: Path) -> list[dict[str, str]]:
  """
  Collect the findings of one markdown file.

  Gate findings apply when the file's `spec_role` is status, product or catalog. Stage and attachment findings apply
  only when its `spec_doc_type` is declared with `stages: true`.

  Args:
    repo: The settings root of the repository.
    root: The scanned root the finding paths are relative to.
    path: The markdown file to check.

  Returns:
    The findings of the file, empty when it is consistent.
  """
  text = spec_paths.read_text(path)
  values, _end = spec_frontmatter.parse(text)
  rel = path.relative_to(root).as_posix()
  found: list[dict[str, str]] = []

  # a coordination folder-note's launch-checkbox blocks
  if values.get(SpecKey.ROLE) in _NOTE_ROLES:
    found.extend(_find_all_gate_findings(rel, text))

  # the document's declared type
  doc_type = spec_doc_types.doc_type_of(path)

  # guard: only a document of a staged type carries a stage to check
  if not doc_type or not _is_staged_type(repo, path.relative_to(repo).as_posix(), doc_type):
    return found

  # the stage and its tag, then an attachment's mirror of its owner
  found.extend(_find_all_stage_findings(rel, text, values))
  if values.get(AttachmentKey.OWNER_DOC):
    found.extend(_find_all_attachment_findings(path, rel, values))
  return found


def scan_spec_tree(root: Path) -> list[dict[str, str]]:
  """
  Check every markdown file under a spec directory.

  Hidden files and directories are skipped. The repository settings root is located from the given directory.
  Files are visited in sorted order, so the findings come in a stable order.

  Args:
    root: The spec directory to scan.

  Returns:
    All findings, with paths relative to `root`.
  """
  root = root.resolve()
  repo = spec_paths.find_settings_root(root).resolve()
  found: list[dict[str, str]] = []

  # every markdown file under the root, hidden entries skipped, in a stable order
  for current, dirs, files in os.walk(root):
    dirs[:] = sorted(name for name in dirs if not name.startswith(_HIDDEN))
    for name in sorted(files):
      # guard: only a markdown file carries frontmatter to check
      if not name.endswith(_MD) or name.startswith(_HIDDEN):
        continue
      found.extend(_scan_file(repo, root, Path(current) / name))
  return found


def main(argv: list[str]) -> int:
  """
  Run the `spec-check` verb.

  Prints one JSON line `{"root": <absolute root>, "findings": [...]}` on standard output. Findings are an ordinary
  outcome and never change the exit code.

  Args:
    argv: The command-line arguments after the verb name.

  Returns:
    Exit code 0 when the check ran, whatever it found; 2 when the directory is missing or the arguments are invalid.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs spec-check")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("dir", type = Path)
  args = parser.parse_args(argv)
  root = args.dir.resolve()

  # guard: a check needs a directory to walk
  if not root.is_dir():
    sys.stderr.write(f"spec-check: not a directory: {root}\n")
    return _EXIT_USAGE

  # one JSON line carries the root and every finding
  print(json.dumps({ "root": str(root), "findings": scan_spec_tree(root) }, ensure_ascii = False))
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
