"""
Deterministic asset scaffolder — the Python primitive backing the
`lazycortex-specs scaffold-asset` CLI subcommand.

Replaces the `spec.create-asset` skill's mechanical work for the
nested-from-agent path (`spec.request-apply` → `spec.request-spawn`
→ this script). The operator-facing wizard at
`skills/spec.create-asset/SKILL.md` retains its preamble + question
flow for operator-invoked use; this primitive owns the deterministic
scaffold + stage-stamp step it used to perform via Step 5.

Args (positional): `<product> <category> <slug>`. Built-in categories
`feature` / `change` / `bug` are recognised; operator-defined categories
are looked up in `products[<key>].asset_categories`.

Inputs read:

- `<repo>/.claude/lazy.settings.json[products][<key>]` — resolves
  `spec_path`, `language`, optional `asset_categories[<category>]`
  (`icon` / `color`).
- Templates from one of (first hit wins): per-product override,
  project-wide override, plugin baseline.

Outputs written:

- `<spec_path>/<folder>/<slug>/<slug>.md` — folder-note.
- `<spec_path>/<folder>/<slug>/<doc>.md` — authored docs per layout.

Stdout: a JSON object describing the produced asset. On error: a JSON
object with `error` field and non-zero exit.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

from typing import NoReturn

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

import spec_paths

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class _K:
  """
  String/int constants used by the scaffolder.
  """

  # Settings + frontmatter keys
  PRODUCTS = "products"
  SPEC_PATH = "spec_path"
  ASSET_CATEGORIES = "asset_categories"
  ICON = "icon"
  COLOR = "color"
  SPEC_SOURCE_DOCS = "spec_source_docs"
  ICONIZE_ICON = "iconize_icon"
  ICONIZE_COLOR = "iconize_color"
  # Filenames
  FOLDER_NOTE_TMPL = "asset-note.md"
  DESIGN_MD = "design.md"
  PLAN_MD = "plan.md"
  BUG_MD = "bug.md"
  # Doc stems (basename without extension) for sibling wikilinks
  DESIGN_STEM = "design"
  BUG_STEM = "bug"
  TECH_STEM = "tech"
  # Path segments
  CLAUDE_DIR = ".claude"
  SETTINGS_FILE = "lazy.settings.json"
  TEMPLATES_DIR = "templates"
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
  # Layout-protocol convention: spec_path always has at least two segments
  # before the trailing key when the canonical `<subsystem>/products/<key>`
  # shape applies; that's three or more parts total.
  CANONICAL_PATH_MIN_PARTS = 3
  PRODUCTS_SEGMENT = "products"
  # CLI argparse
  PROG = "lazycortex-specs scaffold-asset"
  ARG_PRODUCT = "product"
  ARG_CATEGORY = "category"
  ARG_SLUG = "slug"
  ARG_CWD = "--cwd"
  HELP_PRODUCT = "Product compound-key"
  HELP_CATEGORY = "Asset category"
  HELP_SLUG = "Asset slug (lowercase-with-hyphens)"
  HELP_CWD = "Override repo root"
  # Output JSON keys
  OUT_FILE = "file"
  OUT_STAGE = "stage"
  # Repo discovery
  GIT_DIR = ".git"


class _Category:
  """
  Built-in asset categories and their fixed folder + doc-set + icon mapping.
  """

  BUILTIN_FOLDERS = { "feature": "features", "change": "changes", "bug": "bugs" }
  BUILTIN_LAYOUT = { "feature": [ _K.DESIGN_MD, _K.PLAN_MD ],
                     "change":  [ _K.DESIGN_MD, _K.PLAN_MD ],
                     "bug":     [ _K.BUG_MD, _K.PLAN_MD ] }
  BUILTIN_ICONS = { "feature": "LiRocket", "change": "LiRefreshCcw", "bug": "LiBug" }
  DEFAULT_LAYOUT = [ _K.DESIGN_MD, _K.PLAN_MD ]


_DOC_DEFAULT_STAGE = { _K.DESIGN_MD: _K.STAGE_DRAFT, _K.BUG_MD: _K.STAGE_DRAFT,
                       _K.PLAN_MD: _K.STAGE_EMPTY }


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
          "run /spec.product-config")
  if _K.SPEC_PATH not in record:
    _fail(_K.CAT_LOGICAL, f"product '{product}' has no {_K.SPEC_PATH}")
  return record


def _resolve_template(repo: Path, category: str, product: str, name: str) -> Path:
  """
  Pick the first existing template path across the three-layer override chain.

  Args:
    repo: Repository root.
    category: Asset category (`feature` / `change` / `bug` / operator-defined).
    product: Product compound-key, used for per-product override layer.
    name: Template filename (e.g. `asset-note.md`, `design.md`).

  Returns:
    Absolute path to the chosen template file.

  Raises:
    SystemExit: When no layer carries the named template.
  """
  cat_dir = f"spec.{category}"
  candidates = [
    repo / _K.CLAUDE_DIR / _K.TEMPLATES_DIR / cat_dir / product / name,
    repo / _K.CLAUDE_DIR / _K.TEMPLATES_DIR / cat_dir / name,
    _plugin_root() / _K.TEMPLATES_DIR / cat_dir / name,
  ]
  for p in candidates:
    if p.is_file():
      return p
  _fail(_K.CAT_LOGICAL,
        f"no template '{name}' for category '{category}' in product '{product}' "
        f"(checked: {', '.join(str(p) for p in candidates)})")


def _category_folder(category: str, record: dict) -> str:
  """
  Map a category to its on-disk folder name.

  Built-in categories map by the fixed dict; operator-defined categories use the
  category key verbatim as the folder name.

  Args:
    category: Asset category key.
    record: Product record (for asset_categories lookup on operator-defined).

  Returns:
    Folder name segment.

  Raises:
    SystemExit: When the category is neither built-in nor declared in the product's
      `asset_categories`.
  """
  if category in _Category.BUILTIN_FOLDERS:
    return _Category.BUILTIN_FOLDERS[category]
  cats = (record.get(_K.ASSET_CATEGORIES) or {})
  if category not in cats:
    _fail(_K.CAT_LOGICAL,
          f"category '{category}' is not built-in and not declared in "
          f"product's {_K.ASSET_CATEGORIES} ({sorted(cats)})")
  return category


def _layout(category: str, record: dict) -> list[str]:
  """
  Return the list of authored-doc filenames for the given category.

  Built-in categories use the fixed layout. Operator-defined categories use the
  default `design.md` + `plan.md` shape until extended.

  Args:
    category: Asset category key.
    record: Product record (reserved for operator-defined layout extensions).

  Returns:
    List of authored-doc filenames (excludes the folder-note).
  """
  # guard: record reserved for operator-defined layout hooks
  _ = record
  if category in _Category.BUILTIN_LAYOUT:
    return _Category.BUILTIN_LAYOUT[category]
  return _Category.DEFAULT_LAYOUT


def _icon_color(category: str, record: dict) -> tuple[str, str]:
  """
  Resolve the (icon, color) pair for the asset's folder-note `iconize_*` frontmatter.

  Operator-defined categories declared in `asset_categories` can carry `icon`
  and optional `color`. Built-in categories use their fixed default icon when the
  operator hasn't overridden them.

  Args:
    category: Asset category key.
    record: Product record.

  Returns:
    Tuple `(icon, color)`. `color` is empty string when not set.

  Raises:
    SystemExit: When the category has no icon (not built-in, not in
      `asset_categories`).
  """
  cats = (record.get(_K.ASSET_CATEGORIES) or {})
  cat_cfg = cats.get(category) or {}
  if _K.ICON in cat_cfg:
    return cat_cfg[_K.ICON], cat_cfg.get(_K.COLOR, "")
  if category in _Category.BUILTIN_ICONS:
    return _Category.BUILTIN_ICONS[category], ""
  _fail(_K.CAT_LOGICAL,
        f"category '{category}' has no icon (not built-in, no {_K.ASSET_CATEGORIES}.{_K.ICON})")


def _product_tag(record: dict) -> str:
  """
  Derive the product's `<product_tag>` from its `spec_path` (drops the subsystem prefix).

  Args:
    record: Product record.

  Returns:
    Tag string suitable for injection into the `{{product_tag}}` template token.
  """
  spec_path = record[_K.SPEC_PATH]
  parts = spec_path.split("/")
  if len(parts) >= 2 and parts[-2] == _K.PRODUCTS_SEGMENT:
    return f"{_K.PRODUCTS_SEGMENT}/" + parts[-1]
  return parts[-1]


def _subsystem(record: dict) -> str:
  """
  Resolve the subsystem prefix from `spec_path` for the `{{subsystem}}` token.

  Args:
    record: Product record.

  Returns:
    Leading path segment when the path has the canonical shape; empty otherwise.
  """
  spec_path = record[_K.SPEC_PATH]
  parts = spec_path.split("/")
  if len(parts) >= _K.CANONICAL_PATH_MIN_PARTS and parts[-2] == _K.PRODUCTS_SEGMENT:
    return parts[0]
  return ""


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


def _inject_iconize(text: str, icon: str, color: str) -> str:
  """
  Inject `iconize_icon` (and optional `iconize_color`) into a folder-note's
  YAML frontmatter block.

  Args:
    text: Full file text including the leading `---\\n...\\n---` frontmatter.
    icon: Icon name (e.g. `LiRocket`).
    color: Optional color string; empty value skips the `iconize_color` line.

  Returns:
    Text with the iconize keys spliced into the frontmatter.
  """
  m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
  if not m:
    return text
  fm_body = m.group(1)
  inject = f"{_K.ICONIZE_ICON}: {icon}"
  if color:
    inject += f"\n{_K.ICONIZE_COLOR}: {color}"
  new_fm = fm_body + "\n" + inject
  return f"---\n{new_fm}\n---\n" + text[m.end():]


def _default_source_docs(spec_path: str, category_folder: str, slug: str,
                         doc: str, layout: list[str],
                         product: str) -> list[tuple[str, str]]:
  """
  Return the default `spec_source_docs` list for an authored doc at scaffold time.

  Each entry is a `(target, display)` tuple. The default display is shape-aware so
  the rendered body bullet reads sensibly without the operator having to rewrite it:

  - Product-level docs (`<spec_path>/<role>`) render as `<product> — product <role>`.
  - Sibling-asset docs (`<spec_path>/<category>/<slug>/<role>`) render as `<slug> — <role>`.

  Args:
    spec_path: Product's `spec_path`.
    category_folder: Folder name segment (e.g. `changes`).
    slug: Asset slug.
    doc: Authored-doc filename.
    layout: The complete authored-doc set (used to detect bug-layout for sibling resolution).
    product: Product compound-key, used for the product-doc display gloss.

  Returns:
    List of `(wikilink_target, display)` tuples in projection order.
  """
  product_docs: list[tuple[str, str]] = [
      (f"{spec_path}/{_K.DESIGN_STEM}",
       f"{product} — product {_K.DESIGN_STEM}"),
      (f"{spec_path}/{_K.TECH_STEM}",
       f"{product} — product {_K.TECH_STEM}"),
  ]
  if doc == _K.PLAN_MD:
    sibling_stem = _K.BUG_STEM if _K.BUG_MD in layout else _K.DESIGN_STEM
    sibling_target = f"{spec_path}/{category_folder}/{slug}/{sibling_stem}"
    sibling_display = f"{slug} — {sibling_stem}"
    return [ (sibling_target, sibling_display), *product_docs ]
  return product_docs


def _set_source_docs(text: str, docs: list[tuple[str, str]]) -> str:
  """
  Rewrite `spec_source_docs` frontmatter and project the body's `## Docs`
  sub-section under `# Sources` from the same list.

  Frontmatter carries only the wikilink targets (canonical reference list). The
  body bullet uses `[[<target>|<display>]]` so the rendered text reads sensibly
  without operator rewrites; the operator may later override individual displays
  and the projection writer (per `spec.sources-protocol`) preserves those edits.

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
    argv: Subcommand argv tail (positional `<product> <category> <slug>`).

  Returns:
    Process exit code: `0` on success, `1` on logical error, `2` on argparse failure.
  """
  parser = argparse.ArgumentParser(prog=_K.PROG)
  parser.add_argument(_K.ARG_PRODUCT, help=_K.HELP_PRODUCT)
  parser.add_argument(_K.ARG_CATEGORY, help=_K.HELP_CATEGORY)
  parser.add_argument(_K.ARG_SLUG, help=_K.HELP_SLUG)
  parser.add_argument(_K.ARG_CWD, default=None, help=_K.HELP_CWD)
  args = parser.parse_args(argv)
  repo = Path(args.cwd).resolve() if args.cwd else _repo_root(Path.cwd())
  record = _resolve_product(repo, args.product)
  folder = _category_folder(args.category, record)
  layout = _layout(args.category, record)
  icon, color = _icon_color(args.category, record)
  product_tag = _product_tag(record)
  subsystem = _subsystem(record).capitalize() or args.product.capitalize()
  spec_path = record[_K.SPEC_PATH]
  content_root = spec_paths.spec_content_root(repo)
  target_folder = content_root / spec_path / folder / args.slug
  if target_folder.exists():
    _fail(_K.CAT_LOGICAL, f"target folder already exists: {target_folder}")
  target_folder.mkdir(parents=True, exist_ok=False)
  tokens = { "product": args.product, "product_tag": product_tag,
             "subsystem": subsystem, "slug": args.slug }
  note_template = _resolve_template(repo, args.category, args.product, _K.FOLDER_NOTE_TMPL)
  note_text = _substitute(note_template.read_text(), tokens)
  note_text = _inject_iconize(note_text, icon, color)
  note_path = target_folder / f"{args.slug}.md"
  note_path.write_text(note_text)
  produced: list[dict] = []
  for doc in layout:
    tmpl_path = _resolve_template(repo, args.category, args.product, doc)
    doc_text = _substitute(tmpl_path.read_text(), tokens)
    docs = _default_source_docs(spec_path, folder, args.slug, doc, layout, args.product)
    doc_text = _set_source_docs(doc_text, docs)
    doc_path = target_folder / doc
    doc_path.write_text(doc_text)
    produced.append({ _K.OUT_FILE: str(doc_path.relative_to(repo)),
                      _K.OUT_STAGE: _DOC_DEFAULT_STAGE.get(doc, _K.STAGE_EMPTY) })
  today = _dt.datetime.now(_dt.UTC).date().isoformat()
  history_lines = [
      f"{today} — spec.create-asset · scaffolded {args.category} "
      f"'{args.slug}' under {args.product}"
  ]
  for p in produced:
    history_lines.append(
        f"{today} — spec.set-stage · {Path(p[_K.OUT_FILE]).name} "
        f"spec_stage empty→{p[_K.OUT_STAGE]}"
    )
  _append_history(note_path, history_lines)
  print(json.dumps({
      "outcome": _K.OUTCOME_SUCCESS,
      "folder": str(target_folder.relative_to(repo)),
      "folder_note": str(note_path.relative_to(repo)),
      "docs": produced,
      "history_lines": len(history_lines),
  }))
  return 0
