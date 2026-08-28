"""
Deterministic single-document seeder — the Python primitive backing the
`lazycortex-specs seed-doc` CLI subcommand.

Seeds ONE authored doc beside an existing asset's status folder-note, from
the same per-type template chain `scaffold-asset` uses. The coordinator's
launch checkboxes are the intended caller: a spawn scaffolds the folder and
its folder-note alone, and every document is seeded later, one checkbox
tick at a time, through this primitive.

CLI: `seed-doc <product> <folder-note-path> --doc <name>:<spec_doc_type>
[--cwd <repo>]`. The folder-note path is repo-relative and must exist; the
target doc must not. The seeded doc starts at stage `empty` and inherits
the folder-note's `spec_source_requests` list, so the review dispatcher's
`context_from_frontmatter` can resolve the originating request(s) when the
doc's writer is dispatched.

Stdout: a JSON object with `outcome` and the created doc's repo-relative
path under `doc`. On error: a JSON object with `error` field and non-zero
exit.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import datetime as _dt
import json
import re
from pathlib import Path

import apply_request
import scaffold_asset
import spec_doc_types

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_PROG = "lazycortex-specs seed-doc"
_ARG_NOTE = "note"
_HELP_DOC = "Produced document as <name>:<spec_doc_type>; exactly one, required"
_HELP_NOTE = "Repo-relative path of the asset's status folder-note"
_STAGE_KEY = "spec_stage"
_SOURCE_REQUESTS_KEY = "spec_source_requests"


def _note_source_requests(note_text: str) -> list[str]:
  """
  Read the folder-note's `spec_source_requests` wikilink values.

  Args:
    note_text: Full folder-note text (frontmatter + body).

  Returns:
    The list values in declaration order, unquoted; empty when the key is absent or empty.
  """
  _fm, fm_end = apply_request._parse_frontmatter(note_text)
  match = re.search(
      rf"(?m)^{_SOURCE_REQUESTS_KEY}:\n((?:^  - .*\n)*)", note_text[:fm_end])
  # guard: key absent or carrying no block items — nothing to inherit
  if not match:
    return []
  return [ line.strip()[2:].strip().strip('"') for line in match.group(1).splitlines() ]


def _set_stage_empty(fm_text: str) -> str:
  """
  Force the frontmatter's `spec_stage` to `empty`.

  Args:
    fm_text: The doc's frontmatter slice, including both `---` fences.

  Returns:
    The frontmatter with `spec_stage: empty` — replacing a template-supplied value, or inserted
    before the closing fence when the template carried none.
  """
  if re.search(rf"(?m)^{_STAGE_KEY}:", fm_text):
    return re.sub(rf"(?m)^{_STAGE_KEY}:.*$", f"{_STAGE_KEY}: {scaffold_asset._K.STAGE_EMPTY}",
                  fm_text, count = 1)
  return fm_text.rstrip("\n").removesuffix("---") + f"{_STAGE_KEY}: {scaffold_asset._K.STAGE_EMPTY}\n---\n"


def main(argv: list[str]) -> int:
  """
  Run the `seed-doc` subcommand: seed one authored doc beside an existing folder-note.

  Guarantees:
    - An existing target document is never overwritten: the request is refused with a JSON
      error object and a non-zero exit status, and the existing file is never opened for
      writing.
    - A refusal at any guard — a missing folder-note, a malformed `--doc` token, or an existing
      target document — writes nothing to disk.

  Args:
    argv: CLI arguments after the subcommand token —
      `<product> <folder-note-path> --doc <name>:<type> [--cwd <repo>]`.

  Returns:
    Process exit code — `0` on success (refusals exit via SystemExit with a JSON error object).
  """

  # Contract:
  # A refusal at any guard — a missing folder-note, a malformed `--doc` token, or an existing
  # target document — writes nothing to disk: no document file, template substitution, or
  # folder-note history entry is created before the guard that refuses the request runs.

  parser = argparse.ArgumentParser(prog = _PROG)
  parser.add_argument(scaffold_asset._K.ARG_PRODUCT, help = scaffold_asset._K.HELP_PRODUCT)
  parser.add_argument(_ARG_NOTE, help = _HELP_NOTE)
  parser.add_argument(scaffold_asset._K.ARG_DOC, required = True, help = _HELP_DOC)
  parser.add_argument(scaffold_asset._K.ARG_CWD, default = None, help = scaffold_asset._K.HELP_CWD)
  args = parser.parse_args(argv)

  # resolve the repo, the product record, and the note before any write
  repo = Path(args.cwd).resolve() if args.cwd else scaffold_asset._repo_root(Path.cwd())
  record = scaffold_asset._resolve_product(repo, args.product)
  note_path = repo / args.note
  # guard: the asset must already exist — seeding never scaffolds a folder
  if not note_path.is_file():
    scaffold_asset._fail(scaffold_asset._K.CAT_LOGICAL,
                         f"folder-note does not exist: {args.note}")
  name, doc_type = scaffold_asset._parse_doc_token(args.doc)
  doc_path = note_path.parent / name

  # Contract:
  # An existing target document is never overwritten: when `doc_path` already exists, `main`
  # refuses the request with a JSON error object on stdout and a non-zero exit status, and the
  # existing file on disk is never opened for writing.

  # guard: an authored doc on disk is never overwritten
  if doc_path.exists():
    scaffold_asset._fail(scaffold_asset._K.CAT_LOGICAL,
                         f"target doc already exists: {name}")

  # the note's own declarations drive the template chain, exactly as a scaffold's would
  note_text = note_path.read_text()
  note_fm, _fm_end = apply_request._parse_frontmatter(note_text)
  asset_type = note_fm.get(scaffold_asset._K.ASSET_TYPE, "") or scaffold_asset._K.DESIGN_STEM
  alias_base = scaffold_asset._alias_base(asset_type, record)
  slug = note_path.stem
  tokens = { "product": args.product, "product_tag": scaffold_asset._product_tag(record),
             "slug": slug, "category": asset_type }
  tmpl_path = scaffold_asset._resolve_template(
      repo, asset_type, args.product,
      scaffold_asset._template_name(repo, doc_type, args.product), alias_base = alias_base)
  doc_text = scaffold_asset._substitute(tmpl_path.read_text(), tokens)
  doc_text = scaffold_asset._ensure_doc_type(doc_text, doc_type)
  # the type's own paint: the icon names the kind of document, matchers own the colour later
  if (doc_paint := spec_doc_types.icon_color(repo, doc_type, args.product)):
    doc_text = scaffold_asset._inject_iconize(doc_text, doc_paint[0], doc_paint[1] or "")

  # the seeded doc is an unwritten skeleton inheriting the note's request attribution
  _doc_fm, doc_fm_end = apply_request._parse_frontmatter(doc_text)
  fm_text = _set_stage_empty(doc_text[:doc_fm_end])
  # quoted like every other writer of the key — bare `[[...]]` parses as a nested YAML list
  fm_text = apply_request._set_fm_list(fm_text, _SOURCE_REQUESTS_KEY,
                                       [ f"\"{link}\"" for link in _note_source_requests(note_text) ])
  doc_path.write_text(fm_text + doc_text[doc_fm_end:])

  # the folder-note history records the seed, mirroring the scaffold's own journal lines
  today = _dt.datetime.now(_dt.UTC).date().isoformat()
  scaffold_asset._append_history(
      note_path, [ f"{today} — lazy-spec.seed-doc · {name} seeded ({_STAGE_KEY} empty)" ])

  # the caller folds the reported path into its commit and review dispatch
  print(json.dumps({
      "outcome": scaffold_asset._K.OUTCOME_SUCCESS,
      "doc": str(doc_path.relative_to(repo)),
  }))
  return 0
