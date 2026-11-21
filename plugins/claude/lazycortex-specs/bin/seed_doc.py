"""
Deterministic single-document seeder — the Python primitive backing the
`lazycortex-specs seed-doc` CLI subcommand.

Seeds ONE authored doc beside an existing asset's status folder-note, from
the same per-type template chain `scaffold-asset` uses. The coordinator's
launch checkboxes are the intended caller: a spawn scaffolds the folder and
its folder-note alone, and every document is seeded later, one checkbox
tick at a time, through this primitive.

A release's `code-plan.md` and `test-plan.md` are seeded already citing, as `spec_source_docs`, the documents they
are written from: the members' designs and the owner's own root documents. A cancelled member contributes nothing.

Refresh mode: `seed-doc --refresh-sources <plan-path> [--cwd <repo>]` re-derives an existing release plan's
`spec_source_docs` and `## Docs` from the release's current members, the way a seed would cite them now, and prints
the `refresh-sources` result; it commits nothing.

CLI: `seed-doc <product> <folder-note-path> --doc <name>:<spec_doc_type>
[--replace-cancelled] [--cwd <repo>]`. The folder-note path is repo-relative and must exist; the
target doc must not, unless `--replace-cancelled` is given and the target sits at `spec_stage: cancelled`, in
which case a fresh seed replaces it and nothing of the old content survives. A target at any other stage is
refused either way, and `--replace-cancelled` beside `--refresh-sources` is refused. The seeded doc starts at
stage `empty` and inherits the folder-note's `spec_source_requests` list, so the review dispatcher's
`context_from_frontmatter` can resolve the originating request(s) when the
doc's writer is dispatched.

Level mode: `seed-doc --root <folder-note-path> --doc <name>:<spec_doc_type>
[--replace-cancelled] [--cwd <repo>]` seeds a system document beside a level folder-note — the
catalog root's or a product's own. A product's level note is resolved to
the registered product whose `spec_path` is its folder, so the product
tokens, the per-product template layer and the paint declarations are the
product's own; at the catalog root the product token carries the content
root's directory name, no product tag is written, and only the project-wide
override layer applies.
Naming a product alongside `--root` is refused; the two spellings never
combine.

Stdout: a JSON object with `outcome` and the created doc's repo-relative
path under `doc`. On error: a JSON object with `error` field and non-zero
exit.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import apply_request  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import asset_types  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import flip_gate  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import release_delta  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import resolve_product  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import scaffold_asset  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import sources_refresh  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import spec_doc_types  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import spec_frontmatter  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import spec_paths  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from spec_keys import Gate, LevelDoc, ReleaseKey, SiblingDoc, SpecKey, SpecValue  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_PROG = "lazycortex-specs seed-doc"
_ARG_NOTE = "note"
_ARG_ROOT = "--root"
_HELP_DOC = "Produced document as <name>:<spec_doc_type>; exactly one, required"
_HELP_NOTE = "Repo-relative path of the asset's status folder-note"
_HELP_ROOT = "Repo-relative path of a level folder-note — the catalog root's or a product's own"
_STAGE_KEY = "spec_stage"
_SOURCE_REQUESTS_KEY = "spec_source_requests"
# waiver: one-off human-facing messages -- the refusal lines and the --refresh-sources flag with its help text
_ERR_ROOT_WITH_PRODUCT = "--root takes no product and no positional folder-note"
_ERR_MODE_INCOMPLETE = "seed-doc needs <product> <folder-note-path>, or --root <folder-note-path>"
_ARG_REFRESH = "--refresh-sources"
_HELP_REFRESH = "Repo-relative path of a release's existing code-plan.md or test-plan.md to re-derive sources for"
_ERR_REFRESH_ALONE = "--refresh-sources takes no product, folder-note, --root or --doc"
_ERR_DOC_REQUIRED = "seed-doc needs --doc <name>:<spec_doc_type>"
_ARG_REPLACE_CANCELLED = "--replace-cancelled"
_HELP_REPLACE_CANCELLED = "Replace an existing target document that sits at spec_stage: cancelled with a fresh seed"
_ERR_REPLACE_WITH_REFRESH = "--replace-cancelled seeds a document; it takes no --refresh-sources"
_STAGE_CANCELLED = "cancelled"

# The template contexts a level document is seeded from: a product root reads `spec.product/`,
# the catalog root reads `spec.vault/` and falls through to `spec.product/` for what the two
# levels share (the level note); the empty product below collapses the per-product layer.
_ROOT_TEMPLATE_CONTEXT_PRODUCT = "product"
_ROOT_TEMPLATE_CONTEXT_VAULT = "vault"
_NO_PRODUCT = ""

# The template token carrying a document's product tag, and the frontmatter list item it fills —
# dropped whole for a document that belongs to no product.
_PRODUCT_TAG_TOKEN = "product_tag"
_PRODUCT_TAG_LINE_RE = re.compile(
    r"^[ \t]*-[ \t]*\{\{[ \t]*" + re.escape(_PRODUCT_TAG_TOKEN) + r"[ \t]*\}\}[ \t]*\n", re.M)

# The release documents written from the included assets' designs, which therefore cite them as sources
_RELEASE_PLAN_DOCS = frozenset({ SiblingDoc.CODE_PLAN, SiblingDoc.TEST_PLAN })


def _note_source_requests(note_text: str) -> list[str]:
  """
  Read the folder-note's `spec_source_requests` wikilink values.

  Args:
    note_text: Full folder-note text (frontmatter + body).

  Returns:
    The list values in declaration order, unquoted; empty when the key is absent or empty.
  """
  _fm, fm_end = apply_request.parse_frontmatter(note_text)
  return spec_frontmatter.read_list(note_text[:fm_end], _SOURCE_REQUESTS_KEY)


def _find_member_start_doc(repo: Path, note: Path) -> Path | None:
  """
  Find the start document of one included asset, by the type its own product declares.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    note: The included asset's status note.

  Returns:
    The start document's path, or None when the note is gone, its type names no start document, or the document is
    not written yet.
  """

  # guard: a member note that is gone has no type to name its start document
  if not note.is_file():
    return None

  # the member's own product decides what its type starts from, wherever the release that carries it lives
  _key, record = resolve_product.effective_record_by_path(repo, note.resolve().relative_to(repo).as_posix())
  start_name, _start_type = asset_types.start_doc(asset_types.type_of(note), record or {})
  start = note.parent / start_name if start_name else None
  return start if start is not None and start.is_file() else None


def _is_cancelled(note: Path) -> bool:
  """
  Tell whether an included asset is cancelled.

  Args:
    note: The included asset's status note.

  Returns:
    True when the note is on disk and reads `spec_cancelled: true`.
  """
  return note.is_file() and flip_gate.is_true(spec_frontmatter.parse(note.read_text(encoding = "utf-8"))[0],
                                              Gate.SPEC_CANCELLED)


def _build_release_plan_sources(repo: Path, release_text: str, *, record: dict, plan_name: str) -> list[str]:
  """
  Name the documents a release's plan is written from.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    release_text: The release note's text.
    record: The effective settings record of the product owning the release.
    plan_name: The plan's filename, `code-plan.md` or `test-plan.md`.

  Returns:
    Wikilink targets. For `test-plan.md`: the owner's root `test-plan.md`, then every included asset's own
    `test-plan.md`, then every included asset's start document. For `code-plan.md`: every included asset's start
    document, then the owner's root `architecture.md`. Assets come in `spec_includes` order; a document that does
    not exist is left out, and a cancelled asset contributes nothing.
  """

  # Domain(spec.notes):
  # # A release's plans cite the documents they are written from
  # The development and test plans of a release are written from the documents of the assets the release carries.
  # Each plan names those documents as its sources the moment it is created, and again whenever the release is
  # rebuilt, so whoever writes it finds them on the plan itself. The development plan cites the starting document
  # of every included asset, in the order the release lists them, then the product's architecture. The test plan
  # cites the product's own test plan, then the test plan of every included asset, then the starting document of
  # every included asset, each in the order the release lists them. A document that does not exist yet is not
  # cited, since a citation must lead somewhere. A cancelled included asset is abandoned and built into nothing,
  # so it contributes no document to either plan.

  # the included assets, in the order the release lists them; a cancelled one is built into nothing, so it cites
  # nothing either
  members = [ note for note in release_delta.resolve_included_notes(repo, release_text) if not _is_cancelled(note) ]
  starts = [ start for start in ( _find_member_start_doc(repo, note) for note in members ) if start is not None ]

  # the owner's root, holding its architecture and its own test plan
  spec_path = record.get(scaffold_asset.Keys.SPEC_PATH)
  root = spec_paths.spec_content_root(repo) / str(spec_path) if spec_path else None

  # a test plan reads the product's test plan and each member's before the members' designs
  if plan_name == SiblingDoc.TEST_PLAN:
    plans = [ root / LevelDoc.TEST_PLAN ] if root is not None else []
    plans.extend(note.parent / SiblingDoc.TEST_PLAN for note in members)
    sources = [ plan for plan in plans if plan.is_file() ] + starts
  else:
    # a development plan reads the members' designs, then the architecture
    sources = [ *starts, *( [ root / LevelDoc.ARCHITECTURE ] if root is not None else [] ) ]
    sources = [ source for source in sources if source.is_file() ]
  return [ spec_paths.build_wikilink_target(source, repo) for source in sources ]


def _is_cancelled_doc(doc: Path) -> bool:
  """
  Tell whether an existing document sits at `spec_stage: cancelled`.

  Args:
    doc: The document on disk.

  Returns:
    True when the document is a readable file whose frontmatter reads `spec_stage: cancelled`.
  """
  # guard: only a readable file has a stage to read
  try:
    text = doc.read_text(encoding = "utf-8")
  except (OSError, UnicodeDecodeError):
    return False

  # the stage the frontmatter records, quotes aside
  stage = spec_frontmatter.parse(text)[0].get(_STAGE_KEY, "")
  return isinstance(stage, str) and stage.strip().strip("\"'") == _STAGE_CANCELLED


def _set_stage_empty(fm_text: str) -> str:
  """
  Force the frontmatter's `spec_stage` to `empty`.

  Args:
    fm_text: The doc's frontmatter slice, including both `---` fences.

  Returns:
    The frontmatter with `spec_stage: empty` — replacing a template-supplied value, or inserted
    before the closing fence when the template carried none.
  """
  # a template without frontmatter gets a whole block, never a lone closing fence
  return spec_frontmatter.set_scalar(fm_text or "---\n---\n", _STAGE_KEY, scaffold_asset.Keys.STAGE_EMPTY)


def _product_for_note(repo: Path, note_path: Path) -> tuple[str, dict]:
  """
  Find the registered product whose `spec_path` is the folder the level note sits in.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    note_path: Absolute path of the level folder-note.

  Returns:
    The `(product_key, effective_record)` pair (`resolve_product.effective_record`), or `("", {})`
    when no registered product owns the folder or the settings cannot be read or do not parse.
  """
  # guard: settings that cannot be read or do not parse register no product; `ValueError` covers a JSON syntax
  # error, bytes that are not UTF-8 text and JSON that is not an object
  try:
    products = resolve_product.load_products(repo)
  except (OSError, ValueError):
    return "", {}
  content_root = spec_paths.spec_content_root(repo)
  folder = note_path.parent.resolve()
  for key, record in products.items():
    if isinstance(record, dict) and scaffold_asset.Keys.SPEC_PATH in record \
        and (content_root / record[scaffold_asset.Keys.SPEC_PATH]).resolve() == folder:
      return key, resolve_product.effective_record(repo, key)
  return "", {}


def _root_seed_inputs(repo: Path, note_path: Path, note_fm: dict, slug: str, doc_name: str,
                      doc_type: str) -> tuple[str, dict, Path]:
  """
  Resolve the product in scope, the template tokens and the template file a level document is seeded from.

  Args:
    repo: Repository root the templates and declarations are resolved against.
    note_path: Absolute path of the level folder-note.
    note_fm: The level folder-note's parsed frontmatter.
    slug: The level folder-note's own filename stem.
    doc_name: Filename of the document being seeded — the template lookup key.
    doc_type: The document's declared type.

  Returns:
    A `(product, tokens, template_path)` triple — the product key owning the level (empty at the
    catalog root), the substitution mapping and the chosen template file.

  Raises:
    ScaffoldRefusal: When no layer of the override chain carries a template for `doc_name`, nor any
      template declaring `doc_type`, or the first one found declares a different type.
  """

  # Domain(spec.declarations):
  # # A level document is named by the level that owns it
  # The catalog root and each product carry their own top-level documents the same way an
  # asset does. A product's own level note sits in the product's declared folder, so the
  # product that owns it names the document, styles it through its own template layer and
  # paints it with its own declarations — exactly as the product's assets are. The catalog root
  # belongs to no product: its document takes its name from the document tree's own top-level directory,
  # carries no product tag at all, and its template comes from the shared per-type set with only the
  # project-wide override layer in front of it.

  # only a product's own level note has a product to resolve; the catalog root never does
  product: str = ""
  record: dict = {}
  if note_fm.get(SpecKey.ROLE) == SpecValue.ROLE_PRODUCT:
    product, record = _product_for_note(repo, note_path)

  # the catalog root has no product record, so the content root's own directory names it and no product
  # tag is written; an empty tag drops the template's product-tag line
  content_root_name = spec_paths.spec_content_root(repo).name
  label, tag = content_root_name, ""
  if product:
    label, tag = product, scaffold_asset.product_tag(record)

  # `project` names the whole document tree — the catalog root's own headings use it, and a product
  # level carries the same value for a template shared by both levels
  tokens = { "product": label, "product_tag": tag, "slug": slug, "project": content_root_name,
             "category": note_fm.get(SpecKey.ROLE, "") }
  return product, tokens, scaffold_asset.resolve_template(
      repo, _ROOT_TEMPLATE_CONTEXT_PRODUCT if product else _ROOT_TEMPLATE_CONTEXT_VAULT, product or _NO_PRODUCT,
      doc_name, alias_base = "" if product else _ROOT_TEMPLATE_CONTEXT_PRODUCT, expect_type = doc_type)


def _drop_empty_tag_line(template: str, tokens: dict) -> str:
  """
  Remove the template's product-tag list item when the document carries no product tag.

  Args:
    template: Template source text.
    tokens: The substitution tokens for this document.

  Returns:
    The template without its `- {{product_tag}}` line when the token is empty; unchanged otherwise.
  """

  # guard: the document has a product tag — the line is substituted as usual
  if tokens.get(_PRODUCT_TAG_TOKEN):
    return template
  return _PRODUCT_TAG_LINE_RE.sub("", template)


def refresh_release_plan(repo: Path, plan: Path) -> dict:
  """
  Re-derive an existing release plan's `spec_source_docs` and `## Docs` from the release's current members.

  Guarantees:
    - The plan cites exactly what a fresh seed of it would cite now.
    - Nothing is committed; the caller owns the commit.
    - A refusal writes nothing.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    plan: The plan, a `code-plan.md` or `test-plan.md` beside a release note.

  Returns:
    The `refresh-sources` result: the plan, the `docs` and `requests` counts or `"unchanged"`, and `touched_paths`.

  Raises:
    ScaffoldRefusal: When the plan is not on disk, is no release plan, or its folder-note is not a release's.
  """

  # Contract:
  # A refreshed plan cites exactly what a fresh seed of it would cite from the release as it stands now, and the
  # refresh commits nothing; a refusal writes nothing.

  note = plan.parent / f"{plan.parent.name}.md"

  # guard: only an existing plan of a release has sources a release derives
  if plan.name not in _RELEASE_PLAN_DOCS or not plan.is_file() or not note.is_file():
    scaffold_asset.fail(scaffold_asset.Keys.CAT_LOGICAL, f"no release plan to refresh: {plan.name}")

  # the release note's frontmatter says whether the folder-note is a release's
  note_text = note.read_text(encoding = "utf-8")
  note_fm, _fm_end = apply_request.parse_frontmatter(note_text)

  # guard: a plan beside any other folder-note derives no sources from members
  if note_fm.get(scaffold_asset.Keys.ASSET_TYPE) != ReleaseKey.ASSET_TYPE:
    scaffold_asset.fail(scaffold_asset.Keys.CAT_LOGICAL, f"not a release plan: {plan.name}")

  # the sources a seed would cite now replace the plan's, frontmatter and `## Docs` alike
  _key, record = resolve_product.effective_record_by_path(
      repo, note.resolve().relative_to(repo.resolve()).as_posix())
  return sources_refresh.refresh_sources(
      plan, set_docs = _build_release_plan_sources(repo, note_text, record = record or {}, plan_name = plan.name))


@scaffold_asset.refusal_exits
def main(argv: list[str]) -> int:
  """
  Run the `seed-doc` subcommand: seed one authored doc beside an existing folder-note.

  Guarantees:
    - Without `--replace-cancelled`, an existing target document is never overwritten, whatever its stage: the
      request is refused with a JSON error object and a non-zero exit status, and the existing file is never opened
      for writing.
    - With `--replace-cancelled`, an existing target document at `spec_stage: cancelled` is replaced by a fresh seed
      at stage `empty` with the usual source requests, and nothing of the old content survives; an existing target
      at any other stage is still refused, and `--replace-cancelled` beside `--refresh-sources` is refused.
    - A refusal at any guard — a missing folder-note, a malformed or missing `--doc` token, an existing
      target document that is not replaced, a product named alongside `--root`, `--refresh-sources` beside any
      seed argument or beside `--replace-cancelled`, or `--refresh-sources` naming no existing release plan —
      writes nothing to disk.

  Notes:
    - Seeding `code-plan.md` beside a release note also writes the plan's `spec_source_docs` and `## Docs` list: the
      start document of every `spec_includes` member, then the owner's root `architecture.md`. Seeding
      `test-plan.md` there writes the owner's root `test-plan.md`, every member's `test-plan.md`, then every
      member's start document. A document that does not exist is left out.
    - `--refresh-sources <plan-path>` re-derives an existing release plan's lists the same way and seeds nothing.

  Args:
    argv: CLI arguments after the subcommand token — `<product> <folder-note-path> --doc
      <name>:<type> [--replace-cancelled] [--cwd <repo>]`, `--root <folder-note-path> --doc <name>:<type>
      [--replace-cancelled] [--cwd <repo>]`, or `--refresh-sources <plan-path> [--cwd <repo>]`.

  Returns:
    Process exit code — `0` on success.

  Raises:
    SystemExit: On any refusal — a missing folder-note, a malformed or missing `--doc` token, an existing
      target document that is not replaced, a product named alongside `--root`, or a misused `--refresh-sources`,
      including one beside `--replace-cancelled` — carrying a JSON error object on stdout and a non-zero status.
  """

  # Contract:
  # A refusal at any guard — a missing folder-note, a malformed or missing `--doc` token, an existing
  # target document that is not replaced, a product named alongside `--root`, `--refresh-sources` beside any seed
  # argument or beside `--replace-cancelled`, or `--refresh-sources` naming no existing release plan — writes
  # nothing to disk: no document file, template substitution, or folder-note history entry is created before the
  # guard that refuses the request runs.

  # the CLI surface: both target spellings are optional positionals so `--root` can replace them
  parser = argparse.ArgumentParser(prog = _PROG)
  # waiver: argparse CLI signature -- the positionals are optional so `--root` can replace them
  parser.add_argument(scaffold_asset.Keys.ARG_PRODUCT, nargs = "?", default = None,
                      help = scaffold_asset.Keys.HELP_PRODUCT)
  parser.add_argument(_ARG_NOTE, nargs = "?", default = None, help = _HELP_NOTE)
  parser.add_argument(_ARG_ROOT, default = None, help = _HELP_ROOT)
  parser.add_argument(scaffold_asset.Keys.ARG_DOC, default = None, help = _HELP_DOC)
  parser.add_argument(_ARG_REFRESH, default = None, help = _HELP_REFRESH)
  # waiver: argparse CLI signature -- an opt-in switch, off by default so an existing document is never replaced
  # unasked
  parser.add_argument(_ARG_REPLACE_CANCELLED, action = "store_true", help = _HELP_REPLACE_CANCELLED)
  parser.add_argument(scaffold_asset.Keys.ARG_CWD, default = None, help = scaffold_asset.Keys.HELP_CWD)
  args = parser.parse_args(argv)

  # the refresh form re-derives an existing release plan's sources and seeds nothing
  if args.refresh_sources:
    # guard: the refresh form names only the plan; a seed's arguments beside it name a different command
    if args.product or args.note or args.root or args.doc:
      scaffold_asset.fail(scaffold_asset.Keys.CAT_LOGICAL, _ERR_REFRESH_ALONE)

    # guard: replacing a cancelled document is a seed's option, never a refresh's
    if args.replace_cancelled:
      scaffold_asset.fail(scaffold_asset.Keys.CAT_LOGICAL, _ERR_REPLACE_WITH_REFRESH)

    # the plan path is read against the repository the refresh acts in; the result goes out as JSON
    repo = Path(args.cwd).resolve() if args.cwd else scaffold_asset.repo_root(Path.cwd())
    print(json.dumps(refresh_release_plan(repo, repo / args.refresh_sources)))
    return 0

  # guard: a seed names the document it produces
  if not args.doc:
    scaffold_asset.fail(scaffold_asset.Keys.CAT_LOGICAL, _ERR_DOC_REQUIRED)

  # the two spellings name the same seed at different levels and never combine
  if args.root:
    # guard: a product alongside --root would silently pick one of two conflicting scopes
    if args.product or args.note:
      scaffold_asset.fail(scaffold_asset.Keys.CAT_LOGICAL, _ERR_ROOT_WITH_PRODUCT)
    product, note_rel = None, args.root
  else:
    # guard: product mode needs both positionals — argparse cannot express the pairing
    if not args.product or not args.note:
      scaffold_asset.fail(scaffold_asset.Keys.CAT_LOGICAL, _ERR_MODE_INCOMPLETE)
    product, note_rel = args.product, args.note

  # resolve the repo, the product record, and the note before any write
  repo = Path(args.cwd).resolve() if args.cwd else scaffold_asset.repo_root(Path.cwd())
  record = scaffold_asset.resolve_product(repo, product) if product else {}
  note_path = repo / note_rel

  # guard: the note must already exist — seeding never scaffolds a folder
  if not note_path.is_file():
    scaffold_asset.fail(scaffold_asset.Keys.CAT_LOGICAL,
                         f"folder-note does not exist: {note_rel}")
  name, doc_type = scaffold_asset.parse_doc_token(args.doc)
  doc_path = note_path.parent / name

  # Contract:
  # Without `--replace-cancelled`, an existing target document is never overwritten, whatever its stage: `main`
  # refuses the request with a JSON error object on stdout and a non-zero exit status, and the existing file on
  # disk is never opened for writing.

  # Contract:
  # With `--replace-cancelled`, an existing target document at `spec_stage: cancelled` is replaced by a fresh seed:
  # stage `empty`, the usual source requests, and nothing of the old content survives. An existing target at any
  # other stage is still refused exactly as without the flag.

  # Domain(spec.lifecycle):
  # # A cancelled document can give way to a fresh one
  # A document already on disk is never written over by a new seed, whatever stage it is at. The one exception is
  # asked for explicitly: a document that was cancelled can be replaced by a freshly seeded one, as when a release
  # needs a new test plan after its old one was cancelled. The replacement starts empty, like every seed, and
  # nothing of the cancelled document survives — not its text, its review state or its marks. A document at any
  # other stage is still never replaced.

  # guard: an authored doc on disk is never overwritten, except a cancelled one the caller asked to replace
  if doc_path.exists() and not (args.replace_cancelled and _is_cancelled_doc(doc_path)):
    scaffold_asset.fail(scaffold_asset.Keys.CAT_LOGICAL,
                         f"target doc already exists: {name}")

  # the note's own declarations drive the template chain, exactly as a scaffold's would
  note_text = note_path.read_text(encoding = "utf-8")
  note_fm, _fm_end = apply_request.parse_frontmatter(note_text)
  slug = note_path.stem

  # a product's own level note is seeded from the product context even when the caller named
  # the product; only an asset's status note drives the asset-type chain
  if product and note_fm.get(SpecKey.ROLE) != SpecValue.ROLE_PRODUCT:
    # an asset inside a nested product's tree is that product's, whichever key the caller named: its
    # tokens, templates and paint below all come from the owner
    product, record = scaffold_asset.resolve_owning_product(
        repo, note_path.parent, product = product, record = record)
    asset_type = note_fm.get(scaffold_asset.Keys.ASSET_TYPE, "") or scaffold_asset.Keys.DESIGN_STEM
    alias_base = scaffold_asset.resolve_alias_base(asset_type, record)
    tokens = { "product": product, "product_tag": scaffold_asset.product_tag(record),
               "slug": slug, "category": asset_type }
    tmpl_path = scaffold_asset.resolve_template(
        repo, asset_type, product, name, alias_base = alias_base, expect_type = doc_type)
  else:
    product, tokens, tmpl_path = _root_seed_inputs(repo, note_path, note_fm, slug, name, doc_type)
  # the template with an unfilled product-tag line dropped, then every token filled in
  template = _drop_empty_tag_line(tmpl_path.read_text(encoding = "utf-8"), tokens)
  doc_text = scaffold_asset.substitute(template, tokens)
  doc_text = scaffold_asset.ensure_doc_type(doc_text, doc_type)

  # the type's own paint: the icon names the kind of document, matchers own the colour later
  if (doc_paint := spec_doc_types.icon_color(repo, doc_type, product or None)):
    doc_text = scaffold_asset.inject_iconize(doc_text, doc_paint[0], doc_paint[1] or "")

  # Domain(spec.notes):
  # # A freshly seeded document inherits its asset's own request lineage
  # A document seeded beside an asset's status note did not exist when the requests that led
  # to the asset were opened, yet it still needs the same attribution those requests carry, so
  # a reviewer later dispatched against the document can resolve exactly which request or
  # requests motivated it. The seed copies the note's own recorded request lineage onto the
  # new document rather than leaving it to be rediscovered, so that attribution survives even
  # once the asset's status note itself has moved on to citing something else.

  # the seeded doc is an unwritten skeleton inheriting the note's request attribution
  _doc_fm, doc_fm_end = apply_request.parse_frontmatter(doc_text)
  fm_text = _set_stage_empty(doc_text[:doc_fm_end])

  # the list writer quotes each `[[...]]` member — bare, it parses as a nested YAML list
  fm_text = apply_request.set_fm_list(fm_text, _SOURCE_REQUESTS_KEY, _note_source_requests(note_text))
  spec_paths.write_text_atomic(doc_path, fm_text + doc_text[doc_fm_end:])

  # a release's plans cite the included assets' designs and the owner's architecture, frontmatter and `## Docs`
  # alike, so their writers find their sources on the document itself
  if note_fm.get(scaffold_asset.Keys.ASSET_TYPE) == ReleaseKey.ASSET_TYPE and name in _RELEASE_PLAN_DOCS:
    sources_refresh.refresh_sources(
        doc_path, set_docs = _build_release_plan_sources(repo, note_text, record = record, plan_name = name))

  # the caller folds the reported path into its commit and review dispatch; the seed itself
  # leaves no `# History` line — the journal is for events the operator reads, and the commit
  # records the new file
  print(json.dumps({
      "outcome": scaffold_asset.Keys.OUTCOME_SUCCESS,
      "doc": str(doc_path.relative_to(repo)),
  }))
  return 0
