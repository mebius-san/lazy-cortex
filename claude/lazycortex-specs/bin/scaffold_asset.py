"""
Deterministic asset scaffolder — the Python primitive backing the
`lazycortex-specs scaffold-asset` CLI subcommand.

Replaces the `lazy-spec.create-asset` skill's mechanical work for the
nested-from-worker path (`lazy-spec.request-apply`'s spawn branch invokes
this script directly). The operator-facing wizard at
`skills/lazy-spec.create-asset/SKILL.md` retains its preamble + question
flow for operator-invoked use; this primitive owns the deterministic
scaffold + stage-stamp step it used to perform via Step 5.

CLI: `scaffold-asset <product> <asset_type> <slug> --doc <name>:<spec_doc_type>
[--doc ...] [--path <dir>]`. There is no built-in category map and no default
document layout — the `--doc` list is the produced document set in full, and
a call naming none is a logical refusal.

Inputs read:

- `<repo>/.claude/lazy.settings.json[products][<key>]` — resolves `spec_path`
  and the type's own declaration at `asset_types.<name>`, carrying `icon`,
  optional `color`, `playbook`, optional `alias_of`, optional `default_path`,
  `start_doc` as `<file>:<doc_type>`, and optional `default_tools`.
- Each produced document's template is resolved by its own declared type,
  never by its filename.
- Templates from one of (first hit wins): per-product override,
  project-wide override, plugin baseline.

Outputs written:

- `<spec_path>/<folder>/<slug>/<slug>.md` — folder-note, carrying
  `spec_asset_type` and, when the type declares any, `spec_tools`. The
  target folder is `--path` when given, otherwise the type's declared
  `default_path`; a path escaping the product's `spec_path` is refused.
- `<spec_path>/<folder>/<slug>/<doc>.md` — one authored doc per `--doc` entry.
- `<spec_path>/<folder>/<folder>.md` — group folder-note, seeded on the first
  asset landing in that group folder. Operator-zone note; icon comes from the
  type whose `default_path` names the folder, or none for an ad-hoc folder.
  Skipped when a note already exists, when the asset nests inside another
  asset, or at the product root. Path reported as the result JSON's
  `group_note` key (empty string when nothing was seeded).

Stdout: a JSON object describing the produced asset. On error: a JSON
object with `error` field and non-zero exit.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

import asset_types
import note_explainers
import spec_doc_types
import spec_paths
import summary_render
from spec_keys import HistoryEvent

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import NoReturn


class _K:
  """
  String/int constants used by the scaffolder.

  Attributes:
    PRODUCTS: Settings key holding the product registry.
    SPEC_PATH: Settings key naming a product's spec directory.
    ASSET_TYPES: Settings key holding a product's operator-defined asset-type declarations.
    ASSET_TYPE: Frontmatter key naming the asset's own type on its status folder-note.
    SPEC_TOOLS: Frontmatter key listing the tools the asset is realised and checked with.
    ICON: Key naming an asset type's icon.
    SPEC_SOURCE_DOCS: Frontmatter key listing a folder-note's authored sibling docs.
    ICONIZE_ICON: Frontmatter key carrying the folder-note's icon.
    ICONIZE_COLOR: Frontmatter key carrying the folder-note's optional icon color.
    FOLDER_NOTE_TMPL: Filename of the folder-note template.
    GROUP_NOTE_TMPL: Filename of the group folder-note template.
    DESIGN_STEM: Filename stem of the design doc.
    TECH_STEM: Filename stem of the tech doc.
    CLAUDE_DIR: The `.claude` directory segment.
    SETTINGS_FILE: Filename of the settings file.
    TEMPLATES_DIR: The templates directory segment.
    LINEAR_TMPL_DIR: The per-type template directory serving every asset type.
    SHARED_TMPL_DIR: The type-agnostic template directory serving a type with no directory of its own.
    DOC_TYPE: Frontmatter key naming a seeded document's type.
    MD_SUFFIX: Markdown file extension, stripped to derive a document's type from its filename.
    HISTORY_HEADING: The `# History` heading appended to a folder-note.
    DOCS_MARKER_START: Opening HTML marker delimiting the folder-note's sibling-docs block.
    DOCS_MARKER_END: Closing HTML marker delimiting the folder-note's sibling-docs block.
    CAT_LOGICAL: The error category for invalid-input failures.
    OUTCOME_ERROR: Outcome token for a failed scaffold.
    OUTCOME_SUCCESS: Outcome token for a completed scaffold.
    STAGE_DRAFT: The doc-stage value for a doc awaiting approval.
    STAGE_EMPTY: The doc-stage value for a scaffolded but unwritten doc.
    PARENT_SEGMENT: The path segment a `--path` value may never carry.
    PROG: CLI program name shown in `--help` output.
    ARG_PRODUCT: CLI positional argument name for the product compound-key.
    ARG_TYPE: CLI positional argument name for the asset type.
    ARG_DOC: CLI repeatable flag naming one produced document as `<name>:<type>`.
    ARG_PATH: CLI flag overriding the folder the asset lands in.
    DOC_TOKEN_SEP: Separator inside a `--doc` value.
    ARG_SLUG: CLI positional argument name for the asset slug.
    ARG_CWD: CLI flag overriding the repo root.
    HELP_PRODUCT: CLI help text for the product argument.
    HELP_TYPE: CLI help text for the type argument.
    HELP_DOC: CLI help text for the `--doc` flag.
    HELP_PATH: CLI help text for the `--path` flag.
    HELP_SLUG: CLI help text for the slug argument.
    HELP_CWD: CLI help text for the `--cwd` flag.
    ERR_NO_DOC: Refusal message for a scaffold naming no document at all.
    OUT_FILE: Output JSON key naming a produced doc's repo-relative path.
    OUT_STAGE: Output JSON key naming a produced doc's initial stage.
    GIT_DIR: The `.git` entry checked to detect a repo checkout.
  """

  # Settings + frontmatter keys
  PRODUCTS = "products"
  SPEC_PATH = "spec_path"
  ASSET_TYPES = "asset_types"
  ASSET_TYPE = "spec_asset_type"
  SPEC_TOOLS = "spec_tools"
  ICON = "icon"
  SPEC_SOURCE_DOCS = "spec_source_docs"
  ICONIZE_ICON = "iconize_icon"
  ICONIZE_COLOR = "iconize_color"
  # Filenames
  FOLDER_NOTE_TMPL = "asset-note.md"
  GROUP_NOTE_TMPL = "group-note.md"
  # Doc stems (basename without extension) for sibling wikilinks
  DESIGN_STEM = "design"
  TECH_STEM = "tech"
  # Path segments
  CLAUDE_DIR = ".claude"
  SETTINGS_FILE = "lazy.settings.json"
  TEMPLATES_DIR = "templates"
  LINEAR_TMPL_DIR = "spec.docs"
  SHARED_TMPL_DIR = "spec.asset"
  DOC_TYPE = "spec_doc_type"
  MD_SUFFIX = ".md"
  # Body markers + headings
  HISTORY_HEADING = "# History"
  DOCS_MARKER_START = "<!-- auto:spec-docs:start -->"
  DOCS_MARKER_END = "<!-- auto:spec-docs:end -->"
  # Error categories + outcome strings
  CAT_LOGICAL = "logical"
  OUTCOME_ERROR = "error"
  OUTCOME_SUCCESS = "success"
  # Stage values
  STAGE_DRAFT = "draft"
  STAGE_EMPTY = "empty"
  # Path segments the CLI validates against
  PARENT_SEGMENT = ".."
  # CLI argparse
  PROG = "lazycortex-specs scaffold-asset"
  ARG_PRODUCT = "product"
  ARG_TYPE = "asset_type"
  ARG_DOC = "--doc"
  ARG_PATH = "--path"
  DOC_TOKEN_SEP = ":"
  ARG_SLUG = "slug"
  ARG_CWD = "--cwd"
  HELP_PRODUCT = "Product compound-key"
  HELP_TYPE = "Asset type, as declared in asset_types"
  HELP_DOC = "Produced document as <name>:<spec_doc_type>; repeatable, at least one"
  HELP_PATH = "Folder under spec_path the asset lands in; defaults to the type's default_path"
  HELP_SLUG = "Asset slug (lowercase-with-hyphens)"
  HELP_CWD = "Override repo root"
  ERR_NO_DOC = "at least one --doc <name>:<type> is required"
  # Output JSON keys
  OUT_FILE = "file"
  OUT_STAGE = "stage"
  # Repo discovery
  GIT_DIR = ".git"


def _repo_root(cwd: Path) -> Path:
  """
  Resolve the repo root from a working directory, falling back to cwd when not in a repo.

  Args:
    cwd: Working directory to start the search from.

  Returns:
    The first ancestor (or `cwd` itself) that contains a `.git` entry; absolute path.
  """
  cur = cwd.resolve()
  while cur != cur.parent:
    if (cur / _K.GIT_DIR).exists():
      return cur
    cur = cur.parent
  return cwd.resolve()


def _plugin_root() -> Path:
  """
  Return the lazycortex-specs plugin root (parent of this script's `bin/`).

  Returns:
    Absolute path of the plugin root directory.
  """
  return Path(__file__).resolve().parent.parent


def _fail(category: str, message: str) -> NoReturn:
  """
  Print a JSON error object to stdout and exit non-zero.

  Args:
    category: Error category — one of `logical` (input invalid) or `technical`
      (internal failure).
    message: Single-line human-readable cause.
  """
  print(json.dumps({ "outcome": _K.OUTCOME_ERROR,
                     "error": { "category": category, "message": message } }))
  sys.exit(1)


def _resolve_product(repo: Path, product: str) -> dict:
  """
  Load and return the product record from `.claude/lazy.settings.json`.

  Args:
    repo: Repository root.
    product: Product compound-key (e.g. `test`, `dashboards`).

  Returns:
    The product record dict (with at least `spec_path`).

  Raises:
    SystemExit: When settings file is missing, malformed, the product key is
      absent, or its `spec_path` is missing.
  """
  settings_path = repo / _K.CLAUDE_DIR / _K.SETTINGS_FILE
  if not settings_path.exists():
    _fail(_K.CAT_LOGICAL, f".claude/lazy.settings.json absent at {settings_path}")
  try:
    data = json.loads(settings_path.read_text())
  except json.JSONDecodeError as e:
    _fail(_K.CAT_LOGICAL, f".claude/lazy.settings.json malformed: {e}")
  products_section = data.get(_K.PRODUCTS) or {}
  record = products_section.get(product) if isinstance(products_section, dict) else None
  if not isinstance(record, dict):
    _fail(_K.CAT_LOGICAL,
          f"product '{product}' not registered in lazy.settings.json[{_K.PRODUCTS}]; "
          "run /lazy-spec.product-config")
  if _K.SPEC_PATH not in record:
    _fail(_K.CAT_LOGICAL, f"product '{product}' has no {_K.SPEC_PATH}")
  return record


def _alias_base(asset_type: str, record: dict) -> str:
  """
  Resolve the base type an operator-declared type aliases, if any.

  Args:
    asset_type: Asset type key.
    record: Product record carrying the product's own `asset_types` declarations.

  Returns:
    The base type key, or the empty string when the type is concrete.

  Raises:
    SystemExit: When `alias_of` names an unknown base, or the base is itself an alias.
  """
  try:
    return asset_types.alias_base(asset_type, record)
  except ValueError as err:
    _fail(_K.CAT_LOGICAL, str(err))


def _resolve_template(repo: Path, category: str, product: str, name: str, *,
                      alias_base: str = "") -> Path:
  """
  Pick the first existing template path across the three-layer override chain.

  For an alias category, templates from the category's own override chain always take
  precedence over templates from the base category's chain.

  Guarantees:
    - An alias category's own template chain (per-product, project-wide, plugin) outranks the base
      category's chain in full: an alias-local template wins over every base layer, not only the
      layer matching its own.

  Args:
    repo: Repository root.
    category: Asset category (`feature` / `change` / `bug` / operator-defined).
    product: Product compound-key, used for per-product override layer.
    name: Template filename (e.g. `asset-note.md`, `design.md`).
    alias_base: Base category key when `category` is an alias; empty otherwise.

  Returns:
    Absolute path to the chosen template file.

  Raises:
    SystemExit: When no layer carries the named template.
  """
  def chain(cat: str) -> list[Path]:
    cat_dir = f"spec.{cat}"
    return [
      repo / _K.CLAUDE_DIR / _K.TEMPLATES_DIR / cat_dir / product / name,
      repo / _K.CLAUDE_DIR / _K.TEMPLATES_DIR / cat_dir / name,
      _plugin_root() / _K.TEMPLATES_DIR / cat_dir / name,
    ]

  # Contract:
  # An alias category's own template chain (per-product, project-wide, plugin) outranks the
  # base category's chain in full: an alias-local template MUST win over every base layer,
  # not only the layer matching its own.

  # assemble the lookup order: the alias's full chain first, then the base's
  candidates = chain(category) + (chain(alias_base) if alias_base else [])
  # the linear per-type base: the last layer, so a per-category or per-product override of the
  # same filename still wins — the base exists so a category needs no template of its own
  candidates.append(_plugin_root() / _K.TEMPLATES_DIR / _K.LINEAR_TMPL_DIR / name)
  # the type-agnostic base: a shipped type that declares no directory of its own (`content`,
  # `research`) still needs a folder-note, and every per-type copy of it is byte-identical
  candidates.append(_plugin_root() / _K.TEMPLATES_DIR / _K.SHARED_TMPL_DIR / name)
  for p in candidates:
    if p.is_file():
      return p
  _fail(_K.CAT_LOGICAL,
        f"no template '{name}' for category '{category}' in product '{product}' "
        f"(checked: {', '.join(str(p) for p in candidates)})")


def _type_folder(asset_type: str, record: dict, explicit: str) -> str:
  """
  Resolve the folder under the product's `spec_path` the asset lands in.

  Args:
    asset_type: Asset type key.
    record: Product record carrying the product's own `asset_types` declarations.
    explicit: The caller's `--path` value, or the empty string when it named none.

  Returns:
    The folder path segment, relative to the product's `spec_path`.

  Raises:
    SystemExit: When the explicit path would place the asset outside `spec_path`.
  """
  # guard: the caller named no folder — the type's own declaration decides
  if not explicit:
    return asset_types.default_path(asset_type, record)
  # guard: a path climbing out of the product's own tree would scatter the catalog
  if Path(explicit).is_absolute() or _K.PARENT_SEGMENT in Path(explicit).parts:
    _fail(_K.CAT_LOGICAL, f"--path '{explicit}' escapes the product's spec_path")
  return explicit


def _icon_color(asset_type: str, record: dict) -> tuple[str, str]:
  """
  Resolve the `(icon, color)` pair the asset's folder-note paints its folder with.

  Args:
    asset_type: Asset type key.
    record: Product record carrying the product's own `asset_types` declarations.

  Returns:
    The icon name and its optional colour, the colour empty when the declaration names none.

  Raises:
    SystemExit: When neither the plugin nor the product declares the type.
  """
  pair = asset_types.icon_color(asset_type, record)
  # guard: an undeclared type has no declaration to scaffold from at all
  if pair is None:
    _fail(_K.CAT_LOGICAL,
          f"asset type '{asset_type}' is not built-in and not declared in the product's "
          f"{_K.ASSET_TYPES}")
  return pair


def _parse_doc_token(token: str) -> tuple[str, str]:
  """
  Split one `--doc` value into the filename and the document type it is seeded as.

  Args:
    token: The raw `<name>:<spec_doc_type>` value.

  Returns:
    A `(filename, doc_type)` pair.

  Raises:
    SystemExit: When the value does not carry exactly one separator with both halves present.
  """
  name, sep, doc_type = token.partition(_K.DOC_TOKEN_SEP)
  # guard: a malformed token would otherwise seed a document under an invented type
  if not sep or not name or not doc_type or _K.DOC_TOKEN_SEP in doc_type:
    _fail(_K.CAT_LOGICAL, f"--doc '{token}' must have the name:type shape")
  return name, doc_type


def _template_name(repo: Path, doc_type: str, product: str) -> str:
  """
  Resolve the template filename a document of one type is seeded from.

  The document's own filename is never the lookup key: typing made templates a linear set by
  type, so a document the caller names `notes.md` and types `design` is seeded from the design
  template exactly like `design.md` is.

  Args:
    repo: Repository root the declarations are resolved against.
    doc_type: The document's own declared type.
    product: Product compound-key scoping the declaration lookup.

  Returns:
    The declared template filename, falling back to the type's own name with the markdown suffix.
  """
  declaration = spec_doc_types.resolve(repo, doc_type, product)
  # guard: a type no declaration covers cannot seed a document at all
  if declaration is None:
    _fail(_K.CAT_LOGICAL, f"document type '{doc_type}' is declared nowhere in product '{product}'")
  return declaration.get(spec_doc_types.DocTypeFlag.TEMPLATE) or f"{doc_type}{_K.MD_SUFFIX}"


def _initial_stage(repo: Path, doc_type: str, product: str) -> str:
  """
  Resolve the stage a freshly seeded document starts at.

  Args:
    repo: Repository root the declarations are resolved against.
    doc_type: The document's own declared type.
    product: Product compound-key scoping the declaration lookup.

  Returns:
    `draft` for a type declared stage-bearing, `empty` for every other.
  """
  declaration = spec_doc_types.resolve(repo, doc_type, product) or {}
  return _K.STAGE_DRAFT if declaration.get(spec_doc_types.DocTypeFlag.STAGES) else _K.STAGE_EMPTY


def _inject_note_keys(text: str, asset_type: str, tools: list[str]) -> str:
  """
  Write the asset's own type, and its declared default tools, into a folder-note's frontmatter.

  A type declaring no default tools writes no `spec_tools` key at all — an absent key reads as
  "not determined yet", which an empty list would wrongly claim to have settled.

  Args:
    text: Full folder-note text including the leading frontmatter block.
    asset_type: The asset type to stamp.
    tools: The type's declared default tools, empty when it declares none.

  Returns:
    Text carrying the type key, and the tools key when there were tools to write.
  """
  fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
  # guard: no frontmatter block to stamp into
  if not fm_match:
    return text
  lines = [ f"{_K.ASSET_TYPE}: {asset_type}" ]
  if tools:
    lines.append(f"{_K.SPEC_TOOLS}: [ " + ", ".join(f'"{tool}"' for tool in tools) + " ]")
  return f"---\n{fm_match.group(1)}\n" + "\n".join(lines) + "\n---\n" + text[fm_match.end():]


def _product_tag(record: dict) -> str:
  """
  Derive the product's `<product_tag>` from its `spec_path` (the leaf segment).

  Args:
    record: Product record.

  Returns:
    Tag string suitable for injection into the `{{product_tag}}` template token.
  """
  return record[_K.SPEC_PATH].split("/")[-1]


def _substitute(text: str, tokens: dict) -> str:
  """
  Apply `{{key}}` token substitution against the provided mapping.

  Args:
    text: Template source text.
    tokens: Mapping from token name (without braces) to replacement string.

  Returns:
    Substituted text. Unknown tokens are left as-is.
  """
  def repl(m: re.Match) -> str:
    key = m.group(1).strip()
    return tokens.get(key, m.group(0))
  return re.sub(r"\{\{([^{}]+)\}\}", repl, text)


def _ensure_doc_type(text: str, doc_type: str) -> str:
  """
  Ensure a seeded document's frontmatter carries `spec_doc_type`.

  The linear templates already declare the key; a consumer override written before typing
  landed does not, and a document without it resolves to no declaration anywhere.

  Args:
    text: Full document text including the leading `---\\n...\\n---` frontmatter.
    doc_type: The type name to stamp.

  Returns:
    Text carrying exactly one `spec_doc_type` line in its frontmatter.
  """
  fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
  # guard: no frontmatter block to stamp into
  if not fm_match:
    return text
  fm_body = fm_match.group(1)
  # guard: the template already declares the key — nothing to add
  if re.search(r"(?m)^spec_doc_type\s*:", fm_body):
    return text
  return f"---\n{fm_body}\n{_K.DOC_TYPE}: {doc_type}\n---\n" + text[fm_match.end():]


def _inject_iconize(text: str, icon: str, color: str) -> str:
  """
  Inject `iconize_icon` (and optional `iconize_color`) into a folder-note's
  YAML frontmatter block.

  Args:
    text: Full file text including the leading `---\\n...\\n---` frontmatter.
    icon: Icon name (e.g. `LiRocket`).
    color: Optional color string; empty value skips the `iconize_color` line, a non-empty one
      is written double-quoted.

  Returns:
    Text with the iconize keys spliced into the frontmatter.
  """
  m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
  if not m:
    return text
  fm_body = m.group(1)
  inject = f"{_K.ICONIZE_ICON}: {icon}"
  if color:
    # the colour is always double-quoted: a bare `#rrggbb` opens a YAML comment and the key
    # parses as empty (`lazy-obsidian.iconize-protocol.md`, Data model)
    inject += f'\n{_K.ICONIZE_COLOR}: "{color}"'
  new_fm = fm_body + "\n" + inject
  return f"---\n{new_fm}\n---\n" + text[m.end():]


def _default_source_docs(spec_path: str, _category_folder: str, _slug: str,
                         _doc: str, _layout: list[tuple[str, str]],
                         product: str) -> list[tuple[str, str]]:
  # waiver: plan removal simplified this — signature retained for forward compat
  """
  Return the default `spec_source_docs` list for an authored doc at scaffold time.

  Each entry is a `(target, display)` tuple. Now returns only product-level docs
  since plan-specific sibling logic was removed with the artifact model change.

  Args:
    spec_path: Product's `spec_path`.
    _category_folder: Unused; retained for forward compatibility.
    _slug: Unused; retained for forward compatibility.
    _doc: Unused; retained for forward compatibility.
    _layout: Unused; retained for forward compatibility.
    product: Product compound-key, used for the product-doc display gloss.

  Returns:
    List of `(wikilink_target, display)` tuples in projection order.
  """
  return [
      (f"{spec_path}/{_K.DESIGN_STEM}",
       f"{product} — product {_K.DESIGN_STEM}"),
      (f"{spec_path}/{_K.TECH_STEM}",
       f"{product} — product {_K.TECH_STEM}"),
  ]


def _set_source_docs(text: str, docs: list[tuple[str, str]]) -> str:
  """
  Rewrite `spec_source_docs` frontmatter and project the body's `## Docs`
  sub-section under `# Sources` from the same list.

  Frontmatter carries only the wikilink targets (canonical reference list). The
  body bullet uses `[[<target>|<display>]]` so the rendered text reads sensibly
  without operator rewrites; the operator may later override individual displays
  and the projection writer (per `lazy-spec.sources-protocol`) preserves those edits.

  Args:
    text: Full file text with the template scaffold.
    docs: `(wikilink_target, display)` tuples to project.

  Returns:
    Text with both the frontmatter array and body projection updated.
  """
  fm_lines = [ f"  - \"[[{target}]]\"" for target, _ in docs ]
  fm_value = "\n".join(fm_lines)
  fm_replacement = (
      f"{_K.SPEC_SOURCE_DOCS}:\n{fm_value}" if docs
      else f"{_K.SPEC_SOURCE_DOCS}: []"
  )
  text = re.sub(rf"^{_K.SPEC_SOURCE_DOCS}:\s*\[\]\s*$", fm_replacement,
                text, count=1, flags=re.MULTILINE)
  body_lines = [ f"- [[{target}|{display}]]" for target, display in docs ]
  body_proj = "\n".join(body_lines)
  marker_block = f"{_K.DOCS_MARKER_START}\n{_K.DOCS_MARKER_END}"
  body_replacement = (
      f"{_K.DOCS_MARKER_START}\n{body_proj}\n{_K.DOCS_MARKER_END}" if docs
      else marker_block
  )
  return text.replace(marker_block, body_replacement, 1)


def _append_history(folder_note_path: Path, lines: list[str]) -> None:
  """
  Append history entries to the folder-note's `# History` section.

  Args:
    folder_note_path: Path to the asset's status folder-note.
    lines: One-line entries to append (without leading `- `).
  """
  text = folder_note_path.read_text()
  if _K.HISTORY_HEADING not in text:
    text += f"\n{_K.HISTORY_HEADING}\n"
  insert_block = "\n".join(f"- {ln}" for ln in lines)
  m = re.search(rf"({re.escape(_K.HISTORY_HEADING)}\n)(.*)$", text, re.DOTALL)
  if m:
    head, tail = m.group(1), m.group(2)
    if tail.strip():
      tail = tail.rstrip("\n") + "\n" + insert_block + "\n"
    else:
      tail = "\n" + insert_block + "\n"
    text = text[:m.start()] + head + tail
  else:
    text += insert_block + "\n"
  folder_note_path.write_text(text)


def main(argv: list[str]) -> int:
  """
  Run the `scaffold-asset` subcommand: scaffold a new asset folder under a product.

  Args:
    argv: Subcommand argv tail (`<product> <type> <slug> --doc <name>:<type> [--path <dir>]`).

  Returns:
    Process exit code: `0` on success, `1` on logical error, `2` on argparse failure.
  """
  # the three positionals name the asset; --doc names each produced document; --cwd pins the repo
  parser = argparse.ArgumentParser(prog=_K.PROG)
  parser.add_argument(_K.ARG_PRODUCT, help=_K.HELP_PRODUCT)
  parser.add_argument(_K.ARG_TYPE, help=_K.HELP_TYPE)
  parser.add_argument(_K.ARG_SLUG, help=_K.HELP_SLUG)
  # waiver: argparse CLI signature -- the repeatable-flag action name
  parser.add_argument(_K.ARG_DOC, action="append", default=[], help=_K.HELP_DOC)
  parser.add_argument(_K.ARG_PATH, default=None, help=_K.HELP_PATH)
  parser.add_argument(_K.ARG_CWD, default=None, help=_K.HELP_CWD)
  args = parser.parse_args(argv)

  # guard: the document set is the caller's decision in full — there is no default layout left
  if not args.doc:
    _fail(_K.CAT_LOGICAL, _K.ERR_NO_DOC)
  layout = [ _parse_doc_token(token) for token in args.doc ]

  # the product record supplies every type-scaled decision the scaffold needs
  repo = Path(args.cwd).resolve() if args.cwd else _repo_root(Path.cwd())
  record = _resolve_product(repo, args.product)
  # an alias type borrows the base's templates; folder and icon stay its own
  alias_base = _alias_base(args.asset_type, record)
  icon, color = _icon_color(args.asset_type, record)
  folder = _type_folder(args.asset_type, record, args.path or "")
  tools = asset_types.default_tools(args.asset_type, record)
  product_tag = _product_tag(record)

  # scaffolding onto an existing folder would silently overwrite authored docs
  spec_path = record[_K.SPEC_PATH]
  content_root = spec_paths.spec_content_root(repo)
  target_folder = content_root / spec_path / folder / args.slug
  # guard: target folder already there, refuse rather than merge into it
  if target_folder.exists():
    _fail(_K.CAT_LOGICAL, f"target folder already exists: {target_folder}")
  target_folder.mkdir(parents=True, exist_ok=False)

  # the status folder-note carries the iconize block that paints the folder in the explorer, plus
  # the asset's own type and — when the type declares any — the tools it is realised with. The
  # `category` token keeps its name for template compatibility and carries the type verbatim.
  tokens = { "product": args.product, "product_tag": product_tag,
             "slug": args.slug, "category": args.asset_type }

  # the asset's own status folder-note, seeded from the type's template chain
  note_template = _resolve_template(repo, args.asset_type, args.product, _K.FOLDER_NOTE_TMPL,
                                    alias_base = alias_base)
  note_text = _substitute(note_template.read_text(), tokens)
  note_text = _inject_iconize(note_text, icon, color)
  note_text = _inject_note_keys(note_text, args.asset_type, tools)
  note_path = target_folder / f"{args.slug}.md"
  note_path.write_text(note_explainers.heal_note_text(note_path, note_text))

  # one doc per --doc entry, each seeded with its cross-reference block and its declared stage
  produced: list[dict] = []
  for doc, doc_type in layout:
    tmpl_path = _resolve_template(repo, args.asset_type, args.product,
                                  _template_name(repo, doc_type, args.product),
                                  alias_base = alias_base)
    doc_text = _substitute(tmpl_path.read_text(), tokens)
    doc_text = _ensure_doc_type(doc_text, doc_type)
    # the type's own paint: the icon names the kind of document, the registry's matchers own
    # the colour from the first `set-stage` onward. A journal never gets a stage and so keeps
    # this seed for life — which is why no matcher enumerates journals.
    if (doc_paint := spec_doc_types.icon_color(repo, doc_type, args.product)):
      doc_text = _inject_iconize(doc_text, doc_paint[0], doc_paint[1] or "")
    docs = _default_source_docs(spec_path, folder, args.slug, doc, layout, args.product)
    doc_text = _set_source_docs(doc_text, docs)
    doc_path = target_folder / doc
    doc_path.write_text(doc_text)
    produced.append({ _K.OUT_FILE: str(doc_path.relative_to(repo)),
                      _K.OUT_STAGE: _initial_stage(repo, doc_type, args.product) })

  # the folder-note history records the scaffold plus every doc's initial stage
  today = _dt.datetime.now(_dt.UTC).date().isoformat()
  history_lines = [
      f"{today} — lazy-spec.create-asset · "
      + note_explainers.history_line(note_path, HistoryEvent.SCAFFOLDED, asset_type = args.asset_type,
                                     slug = args.slug, product = args.product)
  ]
  for p in produced:
    history_lines.append(
        f"{today} — lazy-spec.set-stage · {Path(p[_K.OUT_FILE]).name} "
        f"spec_stage empty→{p[_K.OUT_STAGE]}"
    )
  _append_history(note_path, history_lines)

  # Domain(obsidian.icon-resolution):
  # # Container colour is the state axis
  # Colour marks state: an asset's folder takes its colour from its own state, and a document
  # takes its colour from its stage. A container holds no state of its own, so only one kind of
  # container is painted at all — the product root, in a neutral tone a product may override, so
  # a product reads apart from the group folders beneath it. An ordinary group folder — a
  # declared type's own folder or an ad-hoc one — carries no colour key whatsoever, only the
  # icon of the type that owns it as its default folder. A type's declared colour never reaches
  # that folder; it reaches only the asset status notes of that type, as their seed colour.

  # group folders exist lazily: the folder's first asset seeds its operator-zone folder-note,
  # last so a refusal anywhere above leaves no stray note in the shared group folder. An
  # existing note is never touched — the operator's, or an enclosing asset's own status note
  # (a nested asset's parent) — and the product root's note belongs to the product wizard.
  # The icon comes from the type that OWNS the folder (its `default_path` names it), never from
  # the landing asset's type; an ad-hoc folder no declaration names gets a note without icon keys.
  # limit: only the immediate parent is seeded, a deeper fresh `--path a/b` chain leaves the
  # intermediate levels note-less; seed them by landing an asset in each, or author notes by hand
  group_dir = target_folder.parent
  group_note = group_dir / f"{group_dir.name}.md"
  seeded_group = ""
  if not group_note.exists() and group_dir != content_root / spec_path:
    group_template = _resolve_template(repo, args.asset_type, args.product, _K.GROUP_NOTE_TMPL,
                                       alias_base = alias_base)
    group_text = _substitute(group_template.read_text(), tokens)
    # waiver: sibling-module declaration walk -- the one merged-declaration view every specs primitive shares
    owner = next((name for name in asset_types._declared(record)
                  if asset_types.default_path(name, record) == folder), "")
    # an ordinary container takes the owning type's icon and no colour at all: colour is the
    # state axis and a shelf has no state (the intake shelves are the deliberate exception)
    if owner and (owner_paint := asset_types.icon_color(owner, record)):
      group_text = _inject_iconize(group_text, owner_paint[0], "")
    group_note.write_text(note_explainers.heal_note_text(group_note, group_text))
    summary_render.apply_container_stats(group_note)
    seeded_group = str(group_note.relative_to(repo))

  # repo-relative paths in the result so the calling skill can quote them straight back
  print(json.dumps({
      "outcome": _K.OUTCOME_SUCCESS,
      "folder": str(target_folder.relative_to(repo)),
      "folder_note": str(note_path.relative_to(repo)),
      "docs": produced,
      "history_lines": len(history_lines),
      "group_note": seeded_group,
  }))
  return 0
