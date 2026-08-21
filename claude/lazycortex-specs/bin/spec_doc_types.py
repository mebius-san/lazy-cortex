"""
Document-type declarations for the spec catalog — the `doc-type` CLI's resolver half.

A spec document's type is the `spec_doc_type` frontmatter key, and the set of legal values is
open: this plugin ships nine declarations in `references/lazy-spec.doc-types.json`, and a
product declares its own under `products[<key>].doc_types.<type>` in `.claude/lazy.settings.json`.
A declaration carries three independent flags — `stages` (the document carries `spec_stage` and
is the only kind `lazy-spec.set-stage` accepts), `review` (the document goes through the review
loop under the same-named class), `append_only` (the file is only ever appended to) — the
optional `icon` / `color` pair a fresh document of the type is painted with at creation, and an
optional `template` naming the linear per-type template file.

Every consumer asks here instead of comparing a basename against a closed list; validation
everywhere is "a declaration for this type exists", never "this name is in the enum".
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402


# ----------------------------------------------------------------------------------------
class DocTypeFlag:
  """
  Flag names a document-type declaration carries.

  Attributes:
    STAGES: Whether the type carries `spec_stage` and is settable by `lazy-spec.set-stage`.
    REVIEW: Whether the type goes through the review loop under its same-named class.
    APPEND_ONLY: Whether the file may only be appended to, never rewritten.
    ICON: Iconize icon name a document of the type is seeded with at creation.
    COLOR: Optional iconize colour paired with the icon.
    TEMPLATE: Optional filename of the type's linear template.
  """

  STAGES = "stages"
  REVIEW = "review"
  APPEND_ONLY = "append_only"
  ICON = "icon"
  COLOR = "color"
  TEMPLATE = "template"


# ----------------------------------------------------------------------------------------
class _K:
  """
  Path and settings-key constants used by the declaration resolver.

  Attributes:
    DOC_TYPE: Frontmatter key naming a document's type.
    DOC_TYPES: Settings key holding a product's own type declarations.
    PRODUCTS: Settings key holding the product registry.
    REFERENCES_DIR: The plugin subdirectory holding the shipped declaration file.
    DEFAULTS_FILE: Filename of the shipped declaration file.
    SETTINGS_REL: Repo-relative path of the settings file.
    ENCODING: File encoding used throughout this module.
    TEMPLATES_DIR: The plugin subdirectory holding the shipped template trees.
    DOC_TEMPLATES_DIR: The template subdirectory holding one file per document type.
    REVIEW: Settings key holding the review section.
    CLASSES: Settings key holding the review-class registry.
    CLASS: Field naming one review class.
    CLASS_PRODUCT_SEP: Separator between a class name and the product qualifying it.
  """

  DOC_TYPE = "spec_doc_type"
  DOC_TYPES = "doc_types"
  PRODUCTS = "products"
  REFERENCES_DIR = "references"
  DEFAULTS_FILE = "lazy-spec.doc-types.json"
  SETTINGS_REL = Path(".claude") / "lazy.settings.json"
  ENCODING = "utf-8"
  TEMPLATES_DIR = "templates"
  DOC_TEMPLATES_DIR = "spec.docs"
  REVIEW = "review"
  CLASSES = "classes"
  CLASS = "class"
  CLASS_PRODUCT_SEP = "@"


# waiver: CLI verb tokens -- dispatch keys for this module's own argparse router
_VERB_OF = "of"
_VERB_RESOLVE = "resolve"
_VERB_LIST = "list"
_VERB_BACKFILL = "backfill"
_VERB_RENAME = "rename"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"
_OUT_DOC_TYPE = "doc_type"
_OUT_DECLARED = "declared"
_OUT_TYPES = "types"

# waiver: rename-result field names -- the JSON report shape this module's `rename` verb prints
_OUT_DECLARATION = "declaration"
_OUT_DOCS = "docs"
_OUT_FILES = "files"
_OUT_TEMPLATE = "template"
_OUT_CLASSES = "classes"
_OUT_COPIES = "copies"
_OUT_ROLES = "roles"

# The directory-name prefix marking a per-category template family (`spec.bug`, `spec.change`, …).
_SPEC_TMPL_PREFIX = "spec."

# waiver: backfill-only frontmatter tokens -- keys and result fields the one-shot migration uses
_SPEC_ROLE = "spec_role"
_STATUS_ROLE = "status"
_MD_SUFFIX = ".md"
_TOUCHED = "touched"
_SKIPPED = "skipped"

# The frontmatter anchors the new key lands against: below `spec_role` when the document has one
# (a scalar key — the next line is free), otherwise above `tags` — a block-mapping key whose list
# items follow on the next lines, so writing below it would split the key from its items.
_FM_ROLE_ANCHOR_RE = re.compile(r"(?m)^spec_role\s*:.*$")
_FM_TAGS_ANCHOR_RE = re.compile(r"(?m)^tags\s*:.*$")

# The opening frontmatter fence, used when a document carries neither anchor line.
_FM_OPEN_FENCE = "---\n"


# Flag defaults applied to any declaration that omits them — a project type declaring only
# `{"review": true}` is a review-only, non-staged, rewritable document, never an error.
_FLAG_DEFAULTS = {
    DocTypeFlag.STAGES: False,
    DocTypeFlag.REVIEW: False,
    DocTypeFlag.APPEND_ONLY: False,
}


def _plugin_root() -> Path:
  """
  Return the lazycortex-specs plugin root (parent of this script's `bin/`).

  Returns:
    Absolute path of the plugin root directory.
  """
  return Path(__file__).resolve().parent.parent


def shipped_defaults() -> dict[str, dict]:
  """
  Read the plugin's own document-type declarations.

  Returns:
    Mapping of type name to its declaration dict, every flag key present.
  """
  path = _plugin_root() / _K.REFERENCES_DIR / _K.DEFAULTS_FILE
  raw = json.loads(path.read_text(encoding = _K.ENCODING)).get(_K.DOC_TYPES) or {}
  return { name: { **_FLAG_DEFAULTS, **decl } for name, decl in raw.items() }


def _product_types(repo: Path, product: str | None) -> dict[str, dict]:
  """
  Read one product's own `doc_types` declarations from settings.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    product: Product settings key, or None when the caller has no product in scope.

  Returns:
    Mapping of type name to its raw declaration dict; empty when the product declares none.
  """
  # guard: no product in scope — only the shipped set applies
  if not product:
    return {}
  path = repo / _K.SETTINGS_REL
  # guard: no settings file — nothing a product could have declared
  if not path.is_file():
    return {}
  try:
    data = json.loads(path.read_text(encoding = _K.ENCODING))
  except json.JSONDecodeError:
    return {}
  record = (data.get(_K.PRODUCTS) or {}).get(product) or {}
  declared = record.get(_K.DOC_TYPES)
  return declared if isinstance(declared, dict) else {}


def declared_types(repo: Path, product: str | None = None) -> dict[str, dict]:
  """
  Return every document type visible in one product's scope.

  The product's own declarations are merged key-by-key over the shipped ones, so a product may
  flip a single flag of a shipped type without restating the rest.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    product: Product settings key, or None to see only the shipped set.

  Returns:
    Mapping of type name to its merged declaration dict, every flag key present.
  """
  merged = shipped_defaults()
  for name, decl in _product_types(repo, product).items():
    merged[name] = { **_FLAG_DEFAULTS, **merged.get(name, {}), **decl }
  return merged


def resolve(repo: Path, doc_type: str, product: str | None = None) -> dict | None:
  """
  Resolve one document type's declaration in a product's scope.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    doc_type: The `spec_doc_type` value to look up.
    product: Product settings key, or None to consult only the shipped set.

  Returns:
    The merged declaration dict, or None when neither the plugin nor the product declares it.
  """
  return declared_types(repo, product).get(doc_type)


def icon_color(repo: Path, doc_type: str, product: str | None = None) -> tuple[str, str] | None:
  """
  Resolve the icon and colour a document of this type is seeded with at creation.

  The seed is the kind half of the paint contract: the icon says what kind of document this
  is, and the registry's matchers say what state it is in. A journal, which
  never carries `spec_stage`, keeps its seed for life; an authored document keeps it until
  its first `lazy-spec.set-stage`, after which the stage matchers claim it.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    doc_type: The `spec_doc_type` value to look up.
    product: Product settings key, or None to consult only the shipped set.

  Returns:
    An `(icon, color)` pair with an empty colour when the declaration names none, or None
    when the type is undeclared or declares no icon.
  """
  declaration = resolve(repo, doc_type, product)
  # guard: an undeclared type, or one naming no icon, has no seed to report
  if not declaration or not declaration.get(DocTypeFlag.ICON):
    return None
  return declaration[DocTypeFlag.ICON], declaration.get(DocTypeFlag.COLOR, "")


def _derive_type(path: Path, role: str) -> str:
  """
  Derive a legacy document's type from what the file already states.

  `spec_role` wins over the basename when both are available.

  Args:
    path: The document being backfilled.
    role: Its `spec_role` value, or the empty string when it carries none.

  Returns:
    The derived type name, or the empty string when the document is not a typed document
    (the status folder-note, or a stranger carrying neither a role nor a type-named basename).
  """
  # guard: the status folder-note is a folder marker, not a typed document
  if role == _STATUS_ROLE:
    return ""

  # Decision: derive from `spec_role`, not from the basename — the two agree for every role the
  # catalog ships today, but the role is doctor-validated, so it still names the right type on a
  # document whose filename has drifted, which the basename by definition cannot.

  # the role is authoritative whenever the document carries one
  if role:
    return role

  # no role to read: fall back to the filename, accepted only when it names a shipped type
  stem = path.name[: -len(_MD_SUFFIX)]
  return stem if stem in shipped_defaults() else ""


def _insert_type(fm_text: str, doc_type: str) -> tuple[str, int]:
  """
  Insert a `spec_doc_type` line into a frontmatter block, anchored to a neighboring key.

  The line lands directly below a `spec_role` line when the block carries one, or directly above a `tags`
  line when it carries that instead, keeping the tag list attached to its key. A document carrying neither
  anchor still gets the key — it goes to the top of the block, directly under the opening fence.

  Args:
    fm_text: The document's frontmatter block, fences included.
    doc_type: The type name to write.

  Returns:
    A two-tuple `(new_frontmatter, insertions)`; `insertions` is `0` when there is no
    frontmatter block to write into at all.
  """
  line = f"{_K.DOC_TYPE}: {doc_type}"

  # below `spec_role` — a scalar key, the following line is safe to claim
  role = _FM_ROLE_ANCHOR_RE.search(fm_text)
  if role:
    return fm_text[:role.end()] + "\n" + line + fm_text[role.end():], 1

  # above `tags` — a block-mapping key; writing below it would orphan its list items
  tags = _FM_TAGS_ANCHOR_RE.search(fm_text)
  if tags:
    return fm_text[:tags.start()] + line + "\n" + fm_text[tags.start():], 1

  # guard: no anchor line and no opening fence — nothing that parses as frontmatter
  if not fm_text.startswith(_FM_OPEN_FENCE):
    return fm_text, 0
  return _FM_OPEN_FENCE + line + "\n" + fm_text[len(_FM_OPEN_FENCE):], 1


def backfill(repo: Path) -> dict:
  """
  Walk the spec content-root and add `spec_doc_type` to every typed document missing it.

  A file that derives no type (status folder-note, group-note, an untyped stranger) is not a
  candidate and is not counted at all.

  Guarantees:
    - Running this twice in a row leaves the second run with `touched == 0` and every file
      byte-identical: a document already carrying the key is counted `skipped`, never rewritten.
    - No git command is ever run; every change is left in the worktree for the caller to commit.

  Args:
    repo: Absolute repository root (holds `.claude/lazy.settings.json`).

  Returns:
    `{"touched": N, "skipped": M}` — `N` documents gained the key, `M` already carried it.
  """
  # Contract: idempotent and commit-free — a second run touches nothing and leaves every file
  # byte-identical, and the migration never stages or commits what it wrote. Callers chain this
  # into their own commit (`lazy-spec.install` Step 7c does exactly that), so a hidden commit
  # here would land unreviewed content under the caller's identity.
  content_root = spec_paths.spec_content_root(spec_paths.find_settings_root(repo))
  touched = 0
  skipped = 0
  for dirpath, _dirnames, filenames in os.walk(content_root):
    for name in filenames:
      # guard: only markdown files carry spec frontmatter
      if not name.endswith(_MD_SUFFIX):
        continue
      path = Path(dirpath) / name
      text = path.read_text(encoding = _K.ENCODING)
      # waiver: sibling-module frontmatter parser -- the one parser every specs primitive shares
      fm_values, fm_end = flip_gate._parse_frontmatter(text)
      doc_type = _derive_type(path, fm_values.get(_SPEC_ROLE, ""))
      # guard: nothing to derive a type from — not a candidate at all
      if not doc_type:
        continue
      # guard: already typed — idempotent no-op
      if _K.DOC_TYPE in fm_values:
        skipped += 1
        continue
      new_fm, count = _insert_type(text[:fm_end], doc_type)
      # guard: no anchor line to insert after — leave the file for the doctor to report
      if count != 1:
        skipped += 1
        continue
      path.write_text(new_fm + text[fm_end:], encoding = _K.ENCODING)
      touched += 1
  return { _TOUCHED: touched, _SKIPPED: skipped }


def doc_type_of(path: Path) -> str:
  """
  Read one document's `spec_doc_type` frontmatter value.

  The basename is never consulted — a document named `races.md` carrying
  `spec_doc_type: design` is a design document.

  Args:
    path: The markdown document to read.

  Returns:
    The declared type name, or the empty string when the key is absent.
  """
  # waiver: sibling-module frontmatter parser -- the one parser every specs primitive shares
  fm_values, _fm_end = flip_gate._parse_frontmatter(path.read_text(encoding = _K.ENCODING))
  return fm_values.get(_K.DOC_TYPE, "")


def _rename_declaration(old: str, new: str) -> bool:
  """
  Rename one type's key in the shipped declaration file, leaving its flags untouched.

  The `template` field is a filename rather than a flag: when it names the retired type's own
  template, it follows the file `_rename_template` moves, so the declaration never points at a
  template that is no longer there.

  Args:
    old: The type name being retired.
    new: The type name replacing it.

  Returns:
    True when the file was rewritten, False when it declares no such type.
  """
  path = _plugin_root() / _K.REFERENCES_DIR / _K.DEFAULTS_FILE
  data = json.loads(path.read_text(encoding = _K.ENCODING))
  declared = data.get(_K.DOC_TYPES) or {}
  # guard: nothing declared under the old name — a second run lands here
  if old not in declared:
    return False
  moved = dict(declared[old])
  if moved.get(DocTypeFlag.TEMPLATE) == f"{old}{_MD_SUFFIX}":
    moved[DocTypeFlag.TEMPLATE] = f"{new}{_MD_SUFFIX}"
  data[_K.DOC_TYPES] = { (new if name == old else name): (moved if name == old else decl)
                         for name, decl in declared.items() }
  path.write_text(json.dumps(data, indent = 2, ensure_ascii = False) + "\n", encoding = _K.ENCODING)
  return True


def _retype_frontmatter(text: str, old: str, new: str) -> tuple[str, bool, bool]:
  """
  Rewrite a document's `spec_doc_type` and `spec_role` frontmatter values from one type name to another.

  Args:
    text: The document's full text.
    old: The type name being retired.
    new: The type name replacing it.

  Returns:
    `(updated, typed, roled)` — the rewritten text, whether the `spec_doc_type` line matched the
    retired name, and whether the `spec_role` line did.
  """
  # decide which of the two keys this rename is allowed to rewrite in this document
  # waiver: sibling-module frontmatter parser -- the one parser every specs primitive shares
  fm_values, fm_end = flip_gate._parse_frontmatter(text)
  head = text[:fm_end]
  typed = fm_values.get(_K.DOC_TYPE) == old
  roled = fm_values.get(_SPEC_ROLE) == old

  # rewrite only the lines that actually carry the retired name, whitespace-tolerant like the
  # parser that just matched them, normalizing to the single-space form
  if typed:
    head = re.sub(rf"(?m)^{_K.DOC_TYPE}:\s*{re.escape(old)}\s*$", f"{_K.DOC_TYPE}: {new}", head, count = 1)
  if roled:
    head = re.sub(rf"(?m)^{_SPEC_ROLE}:\s*{re.escape(old)}\s*$", f"{_SPEC_ROLE}: {new}", head, count = 1)
  return head + text[fm_end:], typed, roled


def _move_retyped(source: Path, target: Path, old: str, new: str) -> bool:
  """
  Move one template file to its new name, rewriting the type keys its own frontmatter carries.

  Args:
    source: The template file under the retired name.
    target: The destination path under the new name.
    old: The type name being retired.
    new: The type name replacing it.

  Returns:
    True when the file was moved, False when the target already exists — an existing target is
    never overwritten, and the source stays in place for the doctor to surface.
  """
  # guard: never overwrite — a file already under the new name keeps its own content
  if target.exists():
    return False

  # a worktree copy-then-unlink, never `git mv` — this primitive leaves the index alone
  shutil.copy2(source, target)
  updated, _typed, _roled = _retype_frontmatter(target.read_text(encoding = _K.ENCODING), old, new)
  target.write_text(updated, encoding = _K.ENCODING)
  source.unlink()
  return True


def _rename_template(old: str, new: str) -> bool:
  """
  Rename one type's shipped template file to the new type's name.

  The moved file's own `spec_doc_type` / `spec_role` frontmatter values follow, so a document
  seeded from it never carries the retired name.

  Args:
    old: The type name being retired.
    new: The type name replacing it.

  Returns:
    True when a template was moved, False when the type ships none.
  """
  templates = _plugin_root() / _K.TEMPLATES_DIR / _K.DOC_TEMPLATES_DIR
  source = templates / f"{old}{_MD_SUFFIX}"
  # guard: a type shipping no template has nothing to move
  if not source.is_file():
    return False
  return _move_retyped(source, templates / f"{new}{_MD_SUFFIX}", old, new)


def _rename_copies(repo: Path, old: str, new: str) -> int:
  """
  Rename every per-category template copy of one type, in the plugin tree and the repo overrides.

  Template resolution asks for a file named after the type across the `spec.*` override chain, so
  a copy left under the retired name silently stops resolving and the seed falls back to the
  linear base. Each moved copy's own `spec_doc_type` / `spec_role` values follow the rename.

  Args:
    repo: Repository root holding the `.claude/templates/` override tree.
    old: The type name being retired.
    new: The type name replacing it.

  Returns:
    The number of copy files renamed. The linear `spec.docs` template in the plugin tree is
    counted by `_rename_template`, never here — but a consumer's own linear override at
    `.claude/templates/spec.docs/<type>.md` has no `_rename_template` counterpart, so this
    function renames it and counts it like any other copy. A copy whose target name already
    exists is skipped and not counted.
  """
  plugin_templates = _plugin_root() / _K.TEMPLATES_DIR
  count = 0
  for root in ( plugin_templates, repo / _K.SETTINGS_REL.parent / _K.TEMPLATES_DIR ):
    # guard: a tree without templates has no copies to move
    if not root.is_dir():
      continue
    for dirpath, _dirnames, filenames in os.walk(root):
      parts = Path(dirpath).relative_to(root).parts
      # guard: only spec.* families hold per-type copies, nested per-product layers included
      if not parts or not parts[0].startswith(_SPEC_TMPL_PREFIX):
        continue
      # guard: the linear plugin dir is _rename_template's, never a copy
      if root == plugin_templates and parts[0] == _K.DOC_TEMPLATES_DIR:
        continue
      # guard: this family carries no copy under the retired name
      if f"{old}{_MD_SUFFIX}" not in filenames:
        continue

      # move the copy to the new name, its own frontmatter keys following
      if _move_retyped(Path(dirpath) / f"{old}{_MD_SUFFIX}", Path(dirpath) / f"{new}{_MD_SUFFIX}", old, new):
        count += 1
  return count


def _rename_classes(repo: Path, old: str, new: str) -> int:
  """
  Rename every review class named after one type, product-qualified variants included.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.
    old: The type name being retired.
    new: The type name replacing it.

  Returns:
    The number of class entries renamed.
  """
  path = repo / _K.SETTINGS_REL
  # guard: no settings file — no class registry to rewrite
  if not path.is_file():
    return 0
  try:
    data = json.loads(path.read_text(encoding = _K.ENCODING))
  except json.JSONDecodeError:
    return 0
  entries = (data.get(_K.REVIEW) or {}).get(_K.CLASSES)
  # guard: no class registry declared at all
  if not isinstance(entries, list):
    return 0
  renamed = 0
  for entry in entries:
    # guard: a malformed entry carries no class name to match
    if not isinstance(entry, dict):
      continue
    name = entry.get(_K.CLASS)
    base, sep, product = (name or "").partition(_K.CLASS_PRODUCT_SEP)
    if base == old:
      entry[_K.CLASS] = f"{new}{sep}{product}"
      renamed += 1
  if renamed:
    path.write_text(json.dumps(data, indent = 2, ensure_ascii = False) + "\n", encoding = _K.ENCODING)
  return renamed


def rename(repo: Path, old: str, new: str) -> dict:
  """
  Rename one document type everywhere it is recorded, in the declaration and on disk.

  The declaration key moves with its flags intact, every catalog document carrying the old
  type in its `spec_doc_type` or `spec_role` has the matching value rewritten, and a document
  whose basename matched the old type is also renamed to match the new one. The shipped
  template and every per-category template copy under `spec.*` directories, in both the
  plugin's own template tree and the repo's override tree, follow with their own frontmatter
  rewritten, and every review class named after the type — product-qualified variants
  included — is renamed with it. A document whose basename never matched the old type keeps
  the name it has.

  Guarantees:
    - Running this twice in a row leaves the second run finding nothing under the retired
      name and reporting zero in every counter.
    - No git command is ever run; every change is left in the worktree for the caller to
      commit.
    - No existing file is ever overwritten: a template copy, linear template, or catalog
      document already sitting under the new name keeps its own content — the source stays
      in place and the pair is not counted.
    - A document retyped only through its `spec_role` keeps its filename; the on-disk rename
      requires the `spec_doc_type` match.

  Args:
    repo: Absolute repository root (holds `.claude/lazy.settings.json`).
    old: The type name being retired.
    new: The type name replacing it.

  Returns:
    `{"declaration": bool, "docs": N, "files": M, "template": bool, "classes": K, "copies": C,
    "roles": R}` — whether the declaration moved, how many documents were retyped, how many
    were also renamed on disk, whether a template moved, how many review classes followed,
    how many per-category template copies were renamed, and how many documents had their
    `spec_role` rewritten.
  """
  # Contract: idempotent, commit-free, and overwrite-free — a second run finds nothing under the
  # retired name and reports zero in every counter, and nothing is ever staged or committed:
  # every change lands in the worktree for the caller to fold into its own commit. A file already
  # existing under the new name — template copy, linear template, or catalog document — keeps its
  # own content, the source staying in place and the pair uncounted. The on-disk rename fires
  # only on a `spec_doc_type` match; a document retyped through `spec_role` alone keeps its
  # filename.
  content_root = spec_paths.spec_content_root(spec_paths.find_settings_root(repo))
  docs = 0
  files = 0
  roles = 0
  for dirpath, _dirnames, filenames in os.walk(content_root):
    for name in filenames:
      # guard: only markdown files carry spec frontmatter
      if not name.endswith(_MD_SUFFIX):
        continue
      path = Path(dirpath) / name
      updated, typed, roled = _retype_frontmatter(path.read_text(encoding = _K.ENCODING), old, new)
      # guard: a document of another type and role is none of this rename's business
      if not typed and not roled:
        continue
      path.write_text(updated, encoding = _K.ENCODING)
      docs += typed
      roles += roled
      # a document named after its own type follows the rename; a custom name is kept
      if typed and name == f"{old}{_MD_SUFFIX}":
        renamed = path.with_name(f"{new}{_MD_SUFFIX}")
        # guard: never overwrite — a sibling already under the new name keeps its own content
        if not renamed.exists():
          shutil.copy2(path, renamed)
          path.unlink()
          files += 1
  return { _OUT_DECLARATION: _rename_declaration(old, new), _OUT_DOCS: docs, _OUT_FILES: files,
           _OUT_TEMPLATE: _rename_template(old, new), _OUT_CLASSES: _rename_classes(repo, old, new),
           _OUT_COPIES: _rename_copies(repo, old, new), _OUT_ROLES: roles }


def _repo_from_args(cwd: str | None) -> Path:
  """
  Resolve the repository root the same way every other lazycortex-specs subcommand does.

  Args:
    cwd: The explicit `--cwd` value, or None.

  Returns:
    Absolute repository root: the flag, then the daemon-exported env var, then the process cwd.
  """
  return Path(cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()


def main(argv: list[str]) -> int:
  """
  Run the `doc-type` subcommand: read a document's type or a type's declaration, or rename one.

  Args:
    argv: Subcommand argv tail (`of <file>`, `resolve <type>`, `list`, `backfill`, or
      `rename <old> <new>`).

  Returns:
    Exit code: `0` on success, `1` when `resolve` finds no declaration, `2` on argparse failure.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs doc-type")
  # waiver: argparse CLI signature -- subparser slot each verb registers into
  sub = parser.add_subparsers(dest = "verb", required = True)
  p_of = sub.add_parser(_VERB_OF)
  # waiver: argparse CLI signature -- positional argument name
  p_of.add_argument("file", type = Path)
  p_resolve = sub.add_parser(_VERB_RESOLVE)
  # waiver: argparse CLI signature -- positional argument name
  p_resolve.add_argument("doc_type")
  p_list = sub.add_parser(_VERB_LIST)
  p_backfill = sub.add_parser(_VERB_BACKFILL)
  # waiver: argparse CLI signature -- option flag + default
  p_backfill.add_argument("--cwd", default = None)
  p_rename = sub.add_parser(_VERB_RENAME)
  # waiver: argparse CLI signature -- positional argument names
  p_rename.add_argument("old")
  # waiver: argparse CLI signature -- positional argument names
  p_rename.add_argument("new")
  # waiver: argparse CLI signature -- option flag + default
  p_rename.add_argument("--cwd", default = None)
  for verb_parser in (p_resolve, p_list):
    # waiver: argparse CLI signature -- option flag + default
    verb_parser.add_argument("--product", default = None)
    # waiver: argparse CLI signature -- option flag + default
    verb_parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # `of` needs no repo at all — the answer lives in the document's own frontmatter
  if args.verb == _VERB_OF:
    print(json.dumps({ _OUT_DOC_TYPE: doc_type_of(args.file.resolve()) }))
    return 0

  # the remaining verbs all work against a repository root, resolved the same way
  repo = _repo_from_args(args.cwd)
  if args.verb == _VERB_BACKFILL:
    print(json.dumps(backfill(repo)))
    return 0
  if args.verb == _VERB_RENAME:
    print(json.dumps(rename(repo, args.old, args.new)))
    return 0
  if args.verb == _VERB_LIST:
    print(json.dumps({ _OUT_TYPES: sorted(declared_types(repo, args.product)) }))
    return 0
  declaration = resolve(repo, args.doc_type, args.product)
  # guard: no declaration anywhere — the caller's validation fails on this exit code
  if declaration is None:
    print(json.dumps({ _OUT_DECLARED: False, _K.DOC_TYPE: args.doc_type }))
    return 1
  print(json.dumps({ _OUT_DECLARED: True, _K.DOC_TYPE: args.doc_type, **declaration }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
