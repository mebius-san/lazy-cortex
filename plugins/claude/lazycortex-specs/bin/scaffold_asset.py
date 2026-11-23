"""
Deterministic asset scaffolder — the Python primitive backing the
`lazycortex-specs scaffold-asset` CLI subcommand.

Replaces the `lazy-spec.create-asset` skill's mechanical work for the
nested-from-worker path (`lazy-spec.request-apply`'s spawn branch invokes
this script directly). The operator-facing wizard at
`skills/lazy-spec.create-asset/SKILL.md` retains its preamble + question
flow for operator-invoked use; this primitive owns the deterministic
scaffold + stage-stamp step it used to perform via Step 5.

CLI: `scaffold-asset <product> <asset_type> <slug> [--doc <name>:<spec_doc_type>]
[--doc ...] [--path <dir>] [--target <folder>/<slug>] [--target ...] [--cwd <repo>]`. There is no built-in category map and no default
document layout — the `--doc` list is the produced document set in full, and
a call naming none scaffolds the folder and its folder-note alone.

Inputs read:

- `<repo>/.claude/lazy.settings.json[products][<key>]` — resolves `spec_path`
  and the type's own declaration at `asset_types.<name>`, carrying `icon`,
  optional `color`, `playbook`, optional `alias_of`, optional `default_path`,
  and `start_doc` as `<file>:<doc_type>`.
- Each produced document's template is resolved by its own declared type,
  never by its filename.
- Templates from one of (first hit wins): per-product override,
  project-wide override, plugin baseline.

Outputs written:

- `<spec_path>/<folder>/<slug>/<slug>.md` — folder-note, carrying
  `spec_asset_type`. The target folder is `--path` when given, otherwise the type's declared
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

import argparse
import functools
import json
import os
import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import NoReturn

  from collections.abc import Callable


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import asset_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import note_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import resolve_product as product_registry  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import summary_render  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from spec_keys import SpecTargetsKey  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from spec_markers import Markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# ----------------------------------------------------------------------------------------
class Keys:
  """
  String/int constants used by the scaffolder.

  Attributes:
    PRODUCTS: Settings key holding the product registry.
    SPEC_PATH: Settings key naming a product's spec directory.
    PRODUCT_TAG_PREFIX: Tag namespace every product tag sits under, ahead of the product's `spec_path`.
    ASSET_TYPES: Settings key holding a product's operator-defined asset-type declarations.
    ASSET_TYPE: Frontmatter key naming the asset's own type on its status folder-note.
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
    LAYER_PRODUCT_OVERRIDE: Layer label — the consumer's per-product file in a context folder.
    LAYER_CONSUMER_CONTEXT: Layer label — the consumer's file in a context folder.
    LAYER_PLUGIN_CONTEXT: Layer label — the plugin's file in a context folder.
    LAYER_BASE_PREFIX: Label prefix for the alias base's three context layers.
    LAYER_CONSUMER_LINEAR: Layer label — the consumer's file in the linear base.
    LAYER_PLUGIN_LINEAR: Layer label — the plugin's file in the linear base.
    LAYER_PLUGIN_SHARED: Layer label — the plugin's file in the type-agnostic base.
    DOC_TYPE: Frontmatter key naming a seeded document's type.
    MD_SUFFIX: Markdown file extension, stripped to derive a document's type from its filename.
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
    ARG_TARGET: CLI repeatable flag naming one asset a change modifies, as `<folder>/<slug>`.
    HELP_PRODUCT: CLI help text for the product argument.
    HELP_TYPE: CLI help text for the type argument.
    HELP_DOC: CLI help text for the `--doc` flag.
    HELP_PATH: CLI help text for the `--path` flag.
    HELP_SLUG: CLI help text for the slug argument.
    HELP_CWD: CLI help text for the `--cwd` flag.
    HELP_TARGET: CLI help text for the `--target` flag.
    OUT_FILE: Output JSON key naming a produced doc's repo-relative path.
    OUT_STAGE: Output JSON key naming a produced doc's initial stage.
    GIT_DIR: The `.git` entry checked to detect a repo checkout.
  """

  # Settings key holding the product registry.
  PRODUCTS = "products"
  # Settings key naming a product's spec directory.
  SPEC_PATH = "spec_path"
  # Tag namespace every product tag sits under, ahead of the product's `spec_path`.
  PRODUCT_TAG_PREFIX = "product/"
  # Settings key holding a product's operator-defined asset-type declarations.
  ASSET_TYPES = "asset_types"
  # Frontmatter key naming the asset's own type on its status folder-note.
  ASSET_TYPE = "spec_asset_type"
  # Key naming an asset type's icon.
  ICON = "icon"
  # Frontmatter key listing a folder-note's authored sibling docs.
  SPEC_SOURCE_DOCS = "spec_source_docs"
  # Frontmatter key carrying the folder-note's icon.
  ICONIZE_ICON = "iconize_icon"
  # Frontmatter key carrying the folder-note's optional icon color.
  ICONIZE_COLOR = "iconize_color"
  # Filename of the folder-note template.
  FOLDER_NOTE_TMPL = "asset-note.md"
  # Filename of the group folder-note template.
  GROUP_NOTE_TMPL = "group-note.md"
  # Filename stem of the design doc.
  DESIGN_STEM = "design"
  # Filename stem of the tech doc.
  TECH_STEM = "tech"
  # The `.claude` directory segment.
  CLAUDE_DIR = ".claude"
  # Filename of the settings file.
  SETTINGS_FILE = "lazy.settings.json"
  # The templates directory segment.
  TEMPLATES_DIR = "templates"
  # The per-type template directory serving every asset type.
  LINEAR_TMPL_DIR = "spec.docs"
  # The type-agnostic template directory serving a type with no directory of its own.
  SHARED_TMPL_DIR = "spec.asset"
  # Layer label — the consumer's per-product file in a context folder.
  LAYER_PRODUCT_OVERRIDE = "product-override"
  # Layer label — the consumer's file in a context folder.
  LAYER_CONSUMER_CONTEXT = "consumer-context"
  # Layer label — the plugin's file in a context folder.
  LAYER_PLUGIN_CONTEXT = "plugin-context"
  # Label prefix for the alias base's three context layers.
  LAYER_BASE_PREFIX = "base-"
  # Layer label — the consumer's file in the linear base.
  LAYER_CONSUMER_LINEAR = "consumer-linear"
  # Layer label — the plugin's file in the linear base.
  LAYER_PLUGIN_LINEAR = "plugin-linear"
  # Layer label — the plugin's file in the type-agnostic base.
  LAYER_PLUGIN_SHARED = "plugin-shared"
  # Frontmatter key naming a seeded document's type.
  DOC_TYPE = "spec_doc_type"
  # Markdown file extension, stripped to derive a document's type from its filename.
  MD_SUFFIX = ".md"
  # Opening HTML marker delimiting the folder-note's sibling-docs block.
  DOCS_MARKER_START = "<!-- auto:spec-docs:start -->"
  # Closing HTML marker delimiting the folder-note's sibling-docs block.
  DOCS_MARKER_END = "<!-- auto:spec-docs:end -->"
  # The error category for invalid-input failures.
  CAT_LOGICAL = "logical"
  # Outcome token for a failed scaffold.
  OUTCOME_ERROR = "error"
  # Outcome token for a completed scaffold.
  OUTCOME_SUCCESS = "success"
  # The doc-stage value for a doc awaiting approval.
  STAGE_DRAFT = "draft"
  # The doc-stage value for a scaffolded but unwritten doc.
  STAGE_EMPTY = "empty"
  # The path segment a `--path` value may never carry.
  PARENT_SEGMENT = ".."
  # CLI program name shown in `--help` output.
  PROG = "lazycortex-specs scaffold-asset"
  # CLI positional argument name for the product compound-key.
  ARG_PRODUCT = "product"
  # CLI positional argument name for the asset type.
  ARG_TYPE = "asset_type"
  # CLI repeatable flag naming one produced document as `<name>:<type>`.
  ARG_DOC = "--doc"
  # CLI flag overriding the folder the asset lands in.
  ARG_PATH = "--path"
  # Separator inside a `--doc` value.
  DOC_TOKEN_SEP = ":"
  # CLI positional argument name for the asset slug.
  ARG_SLUG = "slug"
  # CLI flag overriding the repo root.
  ARG_CWD = "--cwd"
  # CLI repeatable flag naming one asset a change modifies, as `<folder>/<slug>`.
  ARG_TARGET = "--target"
  # CLI help text for the product argument.
  HELP_PRODUCT = "Product compound-key"
  # CLI help text for the type argument.
  HELP_TYPE = "Asset type, as declared in asset_types"
  # CLI help text for the `--doc` flag.
  HELP_DOC = "Produced document as <name>:<spec_doc_type>; repeatable, may be absent"
  # CLI help text for the `--path` flag.
  HELP_PATH = "Folder under spec_path the asset lands in; defaults to the type's default_path"
  # CLI help text for the slug argument.
  HELP_SLUG = "Asset slug (lowercase-with-hyphens)"
  # CLI help text for the `--cwd` flag.
  HELP_CWD = "Override repo root"
  # CLI help text for the `--target` flag.
  HELP_TARGET = "Asset the change modifies, as <folder>/<slug> under spec_path; repeatable, kept in order"
  # Output JSON key naming a produced doc's repo-relative path.
  OUT_FILE = "file"
  # Output JSON key naming a produced doc's initial stage.
  OUT_STAGE = "stage"
  # The `.git` entry checked to detect a repo checkout.
  GIT_DIR = ".git"


# The citation key's line in a template's frontmatter, in any YAML spelling.
_FM_DOCS_KEY_RE = re.compile(rf"(?m)^{Keys.SPEC_SOURCE_DOCS}[ \t]*:")


# ----------------------------------------------------------------------------------------
class ScaffoldRefusal(Exception):
  """
  Refusal of a scaffold request, carrying the category and message of the CLI's error object.

  Raised for every refusal of a scaffold, template or seeding request, so a caller can turn it into its own
  outcome; a CLI entry point wrapped by `refusal_exits` leaves it as the JSON error object and exit status 1.

  Attributes:
    category: Error category — `logical` when the input is invalid, `technical` for an internal failure.
    message: Single-line human-readable cause.
  """

  def __init__(self, category: str, message: str) -> None:
    """
    Record the refusal's category and message.

    Args:
      category: Error category — `logical` or `technical`.
      message: Single-line human-readable cause.
    """
    # the message doubles as the exception's own text
    super().__init__(message)

    # the two halves of the CLI's error object
    self.category = category
    self.message = message


def repo_root(cwd: Path) -> Path:
  """
  Resolve the repo root from a working directory, falling back to cwd when not in a repo.

  Args:
    cwd: Working directory to start the search from.

  Returns:
    The first ancestor (or `cwd` itself) that contains a `.git` entry; absolute path.
  """
  cur = cwd.resolve()
  while cur != cur.parent:
    if (cur / Keys.GIT_DIR).exists():
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


def fail(category: str, message: str) -> NoReturn:
  """
  Refuse the request by raising a `ScaffoldRefusal`.

  Args:
    category: Error category — one of `logical` (input invalid) or `technical`
      (internal failure).
    message: Single-line human-readable cause.

  Raises:
    ScaffoldRefusal: Always, carrying the given category and message.
  """
  raise ScaffoldRefusal(category, message)


def exit_refused(refusal: ScaffoldRefusal) -> NoReturn:
  """
  Print the refusal as the CLI's JSON error object on stdout and exit with status 1.

  Args:
    refusal: The refusal to report.

  Raises:
    SystemExit: Always, with status `1`, after printing `{"outcome": "error", "error": {"category", "message"}}`.
  """
  print(json.dumps({ "outcome": Keys.OUTCOME_ERROR,
                     "error": { "category": refusal.category, "message": refusal.message } }))
  sys.exit(1)


def refusal_exits(entry: Callable[[list[str]], int]) -> Callable[[list[str]], int]:
  """
  Wrap a CLI entry point so a `ScaffoldRefusal` raised under it leaves as the JSON error object and exit status 1.

  Args:
    entry: The CLI entry point taking the argv tail and returning an exit code.

  Returns:
    The wrapped entry point, keeping the original's name and docstring.
  """

  @functools.wraps(entry)
  def guarded(argv: list[str]) -> int:
    # a refusal raised anywhere under the entry point leaves as the CLI's error object and exit status
    try:
      return entry(argv)
    except ScaffoldRefusal as refusal:
      exit_refused(refusal)

  # the wrapped entry point keeps the original's name and docstring
  return guarded


def resolve_product(repo: Path,
                    product: str,
                    *,
                    products: dict | None = None,
                    catalog_guidelines: dict[str, list[str]] | None = None) -> dict:
  """
  Load the product's effective record — its own keys over its ancestors' (`resolve_product.effective_record`).

  Args:
    repo: Repository root.
    product: Product compound-key (e.g. `test`, `dashboards`).
    products: An already-read products registry, such as the merged one the runtime dispatches from; None reads
      the tracked settings file.
    catalog_guidelines: The catalog-wide `spec.guidelines` already read; None reads them from the tracked settings
      file.

  Returns:
    The merged record dict (with at least `spec_path`).

  Raises:
    ScaffoldRefusal: When no registry is handed in and the settings file is missing, cannot be read, is not UTF-8
      text, is not valid JSON or is not a JSON object; or when the product key is absent or its `spec_path` is
      missing.
    ValueError: When a registry is handed in without `catalog_guidelines` and the tracked settings file exists but
      cannot be read, is not UTF-8 text, is not valid JSON or is not a JSON object; with `catalog_guidelines` handed
      in, the tracked file is not read for the catalog-wide guidelines.
  """
  registry = products if products is not None else _load_tracked_registry(repo)
  record = registry.get(product)

  # guard: the product is not registered, or its record is not a mapping
  if not isinstance(record, dict):
    fail(Keys.CAT_LOGICAL,
          f"product '{product}' not registered in lazy.settings.json[{Keys.PRODUCTS}]; "
          "run /lazy-spec.product-config")

  # guard: a product without a spec directory has nowhere to scaffold into
  if Keys.SPEC_PATH not in record:
    fail(Keys.CAT_LOGICAL, f"product '{product}' has no {Keys.SPEC_PATH}")
  return product_registry.effective_record(repo, product, products = registry,
                                           catalog_guidelines = catalog_guidelines)


def _load_tracked_registry(repo: Path) -> dict:
  """
  Read the products registry from the tracked settings file.

  Args:
    repo: Repository root.

  Returns:
    Product key to record, as the tracked settings file declares them.

  Raises:
    ScaffoldRefusal: When the settings file is missing, cannot be read, is not UTF-8 text, is not valid JSON or is
      not a JSON object.
  """
  settings_path = repo / Keys.CLAUDE_DIR / Keys.SETTINGS_FILE

  # guard: no settings file, no product registry to resolve against
  if not settings_path.exists():
    fail(Keys.CAT_LOGICAL, f".claude/lazy.settings.json absent at {settings_path}")

  # guard: the product registry is refused outright when the settings cannot be read or do not parse;
  # `ValueError` covers a JSON syntax error, bytes that are not UTF-8 text and JSON that is not an object
  try:
    return product_registry.load_products(repo)
  except (OSError, ValueError) as error:
    fail(Keys.CAT_LOGICAL, f".claude/lazy.settings.json malformed: {error}")


def resolve_alias_base(asset_type: str, record: dict) -> str:
  """
  Resolve the base type an operator-declared type aliases, if any.

  Args:
    asset_type: Asset type key.
    record: Product record carrying the product's own `asset_types` declarations.

  Returns:
    The base type key, or the empty string when the type is concrete.

  Raises:
    ScaffoldRefusal: When `alias_of` names an unknown base, or the base is itself an alias.
  """
  try:
    return asset_types.alias_base(asset_type, record)
  except ValueError as err:
    fail(Keys.CAT_LOGICAL, str(err))


def template_layers(repo: Path, context: str, product: str, name: str, *,
                     alias_base: str = "", ancestors: list[str] | None = None) -> list[tuple[str, Path]]:
  """
  List the template lookup chain for one context and filename, most specific first.

  Args:
    repo: Repository root.
    context: Template context — an asset type, `product`, or `vault`.
    product: Product compound-key for the per-product layer; empty collapses it.
    name: Target filename (`design.md`, `asset-note.md`).
    alias_base: Base context whose own three layers plus one per ancestor product follow the
      context's, or empty.
    ancestors: The product's ancestor keys outermost first (`resolve_product.ancestor_chain`);
      each adds an override layer between the product's own and the project-wide one.

  Returns:
    `(label, path)` pairs in lookup order; paths need not exist.
  """
  def chain(cat: str, prefix: str) -> list[tuple[str, Path]]:
    cat_dir = f"spec.{cat}"
    tmpl_dir = repo / Keys.CLAUDE_DIR / Keys.TEMPLATES_DIR / cat_dir
    layers = [ (prefix + Keys.LAYER_PRODUCT_OVERRIDE, tmpl_dir / product / name) ]

    # one override layer per ancestor, innermost first, between the product's own and the project-wide one
    layers.extend(
        (prefix + Keys.LAYER_PRODUCT_OVERRIDE, tmpl_dir / ancestor / name)
        for ancestor in reversed(ancestors or [])
    )
    layers.append((prefix + Keys.LAYER_CONSUMER_CONTEXT, tmpl_dir / name))
    layers.append((prefix + Keys.LAYER_PLUGIN_CONTEXT, _plugin_root() / Keys.TEMPLATES_DIR / cat_dir / name))
    return layers

  # the context's own three layers plus one per ancestor product, the alias base's same set,
  # then the three shared floors
  layers = chain(context, "") + (chain(alias_base, Keys.LAYER_BASE_PREFIX) if alias_base else [])
  layers.append((Keys.LAYER_CONSUMER_LINEAR,
                 repo / Keys.CLAUDE_DIR / Keys.TEMPLATES_DIR / Keys.LINEAR_TMPL_DIR / name))
  layers.append((Keys.LAYER_PLUGIN_LINEAR, _plugin_root() / Keys.TEMPLATES_DIR / Keys.LINEAR_TMPL_DIR / name))
  layers.append((Keys.LAYER_PLUGIN_SHARED, _plugin_root() / Keys.TEMPLATES_DIR / Keys.SHARED_TMPL_DIR / name))
  return layers


def template_doc_type(path: Path) -> str:
  """
  Read the `spec_doc_type` a template declares in its frontmatter.

  Args:
    path: The template file.

  Returns:
    The declared type, or an empty string when the file declares none.
  """
  typed = re.search(r"(?m)^spec_doc_type[ \t]*:[ \t]*(\S+)(?:[ \t]+#.*)?[ \t]*$",
                    spec_frontmatter.block(path.read_text(encoding = "utf-8"))[0])
  return typed.group(1) if typed else ""


def resolve_template(repo: Path, category: str, product: str, name: str, *,
                      alias_base: str = "", expect_type: str = "", products: dict | None = None) -> Path:
  """
  Pick the first existing template path across the layered override chain.

  The lookup key is the context and the target filename; the document type is what the chosen
  file declares in its own frontmatter, and a caller that expects a type only checks it.

  Guarantees:
    - An alias category's own template chain (per-product, project-wide, plugin) outranks the base
      category's chain in full: an alias-local template wins over every base layer, not only the
      layer matching its own.
    - With `expect_type` set, the returned file declares that `spec_doc_type` or none at all — a
      file declaring another type is refused, never substituted.
    - With `expect_type` set, a filename no layer carries still resolves to a template of that type from the
      same override chain, so a custom-named document seeds from its type; it is refused only when the chain
      holds no template of that type.

  Args:
    repo: Repository root.
    category: Template context — an asset type (`feature` / `change` / `bug` / operator-defined),
      `product`, or `vault`.
    product: Product compound-key, used for per-product override layer.
    name: Template filename (e.g. `asset-note.md`, `design.md`).
    alias_base: Base context when `category` is an alias or falls through to another; empty otherwise.
    expect_type: The `spec_doc_type` the chosen file must declare or leave undeclared; empty skips
      the check and the by-type fallback.
    products: The products registry the product's ancestors are read from; None reads the tracked settings file.

  Returns:
    Absolute path to the chosen template file.

  Raises:
    ScaffoldRefusal: When no layer carries the named template (nor, with a type expected, any template
      of that type), or the first file found declares a type other than `expect_type`.
  """

  # Domain(spec.declarations):
  # # A produced document is styled through three layers, most specific first
  # Every document a declaration produces is rendered from a template, and a product or the
  # whole project may restyle any of them without ever touching the plugin's own shipped copy:
  # a per-product version wins over a project-wide version, which wins over the plugin's own
  # baseline. A type that only borrows another type's playbook still consults its own full
  # layering before falling back to anything the borrowed type supplies, so an alias can be
  # restyled on its own without touching the type it borrows behaviour from. Two shared floors
  # sit beneath every declared type: one shared by every type that keeps to the common
  # document set, and one beneath that shared by every type regardless of what documents it
  # declares, so a freshly declared type needs no templates of its own to produce a working
  # folder-note. The document type is never part of the key: a file is found by where it is
  # used and what it is called, and it says for itself what type it produces.

  # Contract:
  # An alias category's own template chain (per-product, project-wide, plugin) outranks the
  # base category's chain in full: an alias-local template MUST win over every base layer,
  # not only the layer matching its own. With `expect_type` set, the file returned declares
  # that type or none — a same-named file of another type is never substituted for it.

  # Contract:
  # With `expect_type` set, a filename that no layer carries still resolves to a template of that
  # type from the same override chain, so a custom-named document seeds from its type. The lookup
  # is refused only when the chain holds no template of that type either.

  ancestors = product_registry.ancestor_chain(repo, product, products = products) if product else []
  candidates = template_layers(repo, category, product, name, alias_base = alias_base, ancestors = ancestors)
  for _label, candidate in candidates:
    # guard: a layer without the file is simply skipped
    if not candidate.is_file():
      continue
    declared = template_doc_type(candidate)

    # guard: a same-named file of another type is another document — never substitute it silently;
    # an untyped consumer override written before typing landed is stamped by the caller instead
    if expect_type and declared and declared != expect_type:
      fail(Keys.CAT_LOGICAL,
            f"template '{candidate}' declares spec_doc_type '{declared}', expected '{expect_type}'")
    return candidate

  # a custom filename (`notes.md` typed `design`) has no file of its own: the first template in
  # the same chain that declares the expected type seeds it
  if expect_type:
    for _label, candidate in candidates:
      # guard: a layer whose folder is absent holds no template of any type
      if not candidate.parent.is_dir():
        continue
      for filename in sorted(os.listdir(candidate.parent)):
        sibling = candidate.parent / filename
        if filename.endswith(Keys.MD_SUFFIX) and sibling.is_file() and template_doc_type(sibling) == expect_type:
          return sibling
  fail(Keys.CAT_LOGICAL,
        f"no template '{name}' for category '{category}' in product '{product}' "
        f"(checked: {', '.join(str(path) for _label, path in candidates)})")


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
    ScaffoldRefusal: When the explicit path would place the asset outside `spec_path`.
  """

  # Domain(spec.declarations):
  # # An asset never lands outside its product's own tree
  # When an asset's landing folder is named explicitly rather than taken from its type's own
  # default, that folder must still resolve inside the product's own document tree — reaching
  # outside it, whether by an absolute path or by climbing upward, would scatter the catalog
  # across locations nothing else in the product expects to find it in.

  # guard: the caller named no folder — the type's own declaration decides
  if not explicit:
    return asset_types.default_path(asset_type, record)

  # guard: a path climbing out of the product's own tree would scatter the catalog
  if Path(explicit).is_absolute() or Keys.PARENT_SEGMENT in Path(explicit).parts:
    fail(Keys.CAT_LOGICAL, f"--path '{explicit}' escapes the product's spec_path")
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
    ScaffoldRefusal: When neither the plugin nor the product declares the type.
  """
  pair = asset_types.icon_color(asset_type, record)

  # guard: an undeclared type has no declaration to scaffold from at all
  if pair is None:
    fail(Keys.CAT_LOGICAL,
          f"asset type '{asset_type}' is not built-in and not declared in the product's "
          f"{Keys.ASSET_TYPES}")
  return pair


def parse_doc_token(token: str) -> tuple[str, str]:
  """
  Split one `--doc` value into the filename and the document type it is seeded as.

  Args:
    token: The raw `<name>:<spec_doc_type>` value.

  Returns:
    A `(filename, doc_type)` pair.

  Raises:
    ScaffoldRefusal: When the value does not carry exactly one separator with both halves present.
  """
  name, sep, doc_type = token.partition(Keys.DOC_TOKEN_SEP)

  # guard: a malformed token would otherwise seed a document under an invented type
  if not sep or not name or not doc_type or Keys.DOC_TOKEN_SEP in doc_type:
    fail(Keys.CAT_LOGICAL, f"--doc '{token}' must have the name:type shape")
  return name, doc_type


def _initial_stage(repo: Path, doc_type: str, product: str, *, products: dict | None = None) -> str:
  """
  Resolve the stage a freshly seeded document starts at.

  Args:
    repo: Repository root the declarations are resolved against.
    doc_type: The document's own declared type.
    product: Product compound-key scoping the declaration lookup.
    products: The products registry the declarations are read from; None reads the tracked settings file.

  Returns:
    `draft` for a type declared stage-bearing, `empty` for every other.
  """
  declaration = spec_doc_types.resolve(repo, doc_type, product, products = products) or {}
  return Keys.STAGE_DRAFT if declaration.get(spec_doc_types.DocTypeFlag.STAGES) else Keys.STAGE_EMPTY


def _inject_type_key(text: str, asset_type: str) -> str:
  """
  Write the asset's own type into a folder-note's frontmatter.

  Args:
    text: Full folder-note text including the leading frontmatter block.
    asset_type: The asset type to stamp.

  Returns:
    Text carrying the type key.
  """
  return spec_frontmatter.insert_before_close(text, f"{Keys.ASSET_TYPE}: {asset_type}\n")


def product_leaf(record: dict) -> str:
  """
  Derive the product's leaf — the last segment of its `spec_path`, which older product tags carried.

  Args:
    record: Product record.

  Returns:
    The leaf segment.
  """
  return record[Keys.SPEC_PATH].split("/")[-1]


def product_tag(record: dict) -> str:
  """
  Derive the product's `<product_tag>`: its whole `spec_path` under the `product/` namespace.

  Args:
    record: Product record.

  Returns:
    Tag string suitable for injection into the `{{product_tag}}` template token.
  """

  # Domain(spec.config):
  # # Product tag
  # Every spec document carries the tag of the product that owns it: `product/` followed by that product's
  # whole tree path as the registry records it (`core` → `product/core`, `core/runtime` →
  # `product/core/runtime`), so a nested product's tag sits inside its parent product's tag. The older
  # forms — the bare last segment of the tree path, and `product/` followed by that last segment alone —
  # are stale.

  # the registry's spec_path, verbatim, under the product namespace
  return f"{Keys.PRODUCT_TAG_PREFIX}{record[Keys.SPEC_PATH]}"


def resolve_owning_product(repo: Path,
                           folder: Path,
                           *,
                           product: str,
                           record: dict,
                           products: dict | None = None,
                           catalog_guidelines: dict[str, list[str]] | None = None) -> tuple[str, dict]:
  """
  Resolve the innermost registered product owning `folder`, the named product when none does.

  Args:
    repo: Repository root.
    folder: Absolute asset folder; it need not exist yet.
    product: The product key the caller named.
    record: The named product's effective record.
    products: The products registry the folder is attributed in; None reads the tracked settings file.
    catalog_guidelines: The catalog-wide `spec.guidelines` already read; None reads them from the tracked settings
      file.

  Returns:
    The `(key, effective_record)` pair of the owning product, or `(product, record)` when the
    folder sits outside the repository or no registered product covers it.

  Raises:
    ValueError: When the tracked settings file exists but cannot be read, is not UTF-8 text, is not valid JSON or is
      not a JSON object; the file is read only for what the caller did not hand in (`products`, then
      `catalog_guidelines`).
  """

  # Domain(spec.config):
  # # Innermost product owns a nested document
  # A document inside a nested product's tree belongs to the innermost product covering it, not to an enclosing one.
  # Its tag is `product/` plus that product's own whole tree path and its product pin names that product,
  # so the values of any enclosing product are stale for it, however the caller named the product.

  # the folder's repo-relative path is what the product resolver attributes an owner from
  try:
    rel = folder.resolve().relative_to(repo.resolve()).as_posix()
  except ValueError:
    # guard: a folder outside the repository has no owner to resolve — keep the caller's product
    return product, record
  key, owner = product_registry.effective_record_by_path(repo, rel, products = products,
                                                         catalog_guidelines = catalog_guidelines)
  return (key, owner) if key is not None and owner is not None else (product, record)


def substitute(text: str, tokens: dict) -> str:
  """
  Apply `{{key}}` token substitution against the provided mapping.

  Args:
    text: Template source text.
    tokens: Mapping from token name (without braces) to replacement string.

  Returns:
    Substituted text. Unknown tokens are left as-is.
  """
  def repl(hit: re.Match) -> str:
    key = hit.group(1).strip()
    return tokens.get(key, hit.group(0))
  return re.sub(r"\{\{([^{}]+)\}\}", repl, text)


def ensure_doc_type(text: str, doc_type: str) -> str:
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
  # guard: the template already declares the key — nothing to add (a text without frontmatter
  # has no block to stamp into, and the splice below leaves it untouched)
  if re.search(r"(?m)^spec_doc_type[ \t]*:", spec_frontmatter.block(text)[0]):
    return text
  return spec_frontmatter.insert_before_close(text, f"{Keys.DOC_TYPE}: {doc_type}\n")


def inject_iconize(text: str, icon: str, color: str) -> str:
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
  inject = f"{Keys.ICONIZE_ICON}: {icon}\n"
  if color:
    # the colour is always double-quoted: a bare `#rrggbb` opens a YAML comment and the key
    # parses as empty (`lazy-obsidian.iconize-protocol.md`, Data model)
    inject += f'{Keys.ICONIZE_COLOR}: "{color}"\n'

  # a text without a frontmatter block is returned untouched by the splice
  return spec_frontmatter.insert_before_close(text, inject)


def _default_source_docs() -> list[tuple[str, str]]:
  """
  Return the default `spec_source_docs` list for an authored doc at scaffold time.

  A fresh document cites nothing. The key records only what the vault layout cannot derive —
  requests and cross-references between assets — and the documents of the asset's own level are
  read by rule rather than by link, so scaffolding one as a citation would only invite drift.

  Returns:
    The empty list — a scaffolded document starts with no source documents at all.
  """

  # Domain(spec.notes):
  # # A fresh document cites only what the vault layout cannot already tell you
  # A document that has just been created starts with no recorded citations at all: citing
  # something the vault's own layout already reveals — the sibling documents an asset holds
  # alongside it — would only give a fresh copy of a fact editors would then have to keep in
  # sync by hand. The citation list exists for relationships the layout cannot show on its
  # own, chiefly the requests that led to a document's existence and links across separate
  # assets, and a document earns those citations only once someone actually adds them.

  return []


def _set_source_docs(text: str, docs: list[tuple[str, str]]) -> str:
  """
  Set the template's docs citations in `spec_source_docs` frontmatter and in the `## Docs` sub-section.

  Frontmatter carries only the wikilink targets. Each body bullet reads `[[<target>|<display>]]`; an operator
  may later override a display and the projection preserves that edit.

  The frontmatter key is rewritten only when the template declares it, and a template without the marked docs
  region gains none. Bullets the template shipped in the docs marker pair never survive; only the given pairs are
  projected.

  Args:
    text: Full file text with the template scaffold.
    docs: `(wikilink_target, display)` pairs to project.

  Returns:
    Text with the frontmatter list and the body projection updated.
  """

  # the frontmatter half is rewritten whole in whatever YAML spelling the template carried —
  # a block list when the caller cited anything, the empty inline list when it cited nothing;
  # a template that never declared the key does not gain it
  fm_lines, fm_end = spec_frontmatter.block(text)
  if _FM_DOCS_KEY_RE.search(fm_lines):
    text = spec_frontmatter.write_list(
        text[:fm_end], Keys.SPEC_SOURCE_DOCS, [ f"[[{target}]]" for target, _ in docs ]) + text[fm_end:]

  # guard: a template without the marked region does not gain one
  if Keys.DOCS_MARKER_START not in text or Keys.DOCS_MARKER_END not in text:
    return text

  # the whole marked region is emptied first, so bullets a template shipped go with it
  markers = Markers()
  return markers.project_docs(markers.rewrite_between(text, Markers.DOCS_MARKER_ID, ""),
                              [ target for target, _ in docs ], displays = dict(docs))


@refusal_exits
def main(argv: list[str]) -> int:
  """
  Run the `scaffold-asset` subcommand: scaffold a new asset folder under a product.

  Args:
    argv: Subcommand argv tail (`<product> <type> <slug> [--doc <name>:<type> ...] [--path <dir>]
      [--target <folder>/<slug> ...] [--cwd <repo>]`).

  Returns:
    Process exit code: `0` on success, `1` on logical error, `2` on argparse failure.
  """
  # the three positionals name the asset; --doc names each produced document; --cwd pins the repo
  parser = argparse.ArgumentParser(prog = Keys.PROG)
  parser.add_argument(Keys.ARG_PRODUCT, help = Keys.HELP_PRODUCT)
  parser.add_argument(Keys.ARG_TYPE, help = Keys.HELP_TYPE)
  parser.add_argument(Keys.ARG_SLUG, help = Keys.HELP_SLUG)
  # waiver: argparse CLI signature -- the repeatable-flag action name
  parser.add_argument(Keys.ARG_DOC, action = "append", default = [], help = Keys.HELP_DOC)
  parser.add_argument(Keys.ARG_PATH, default = None, help = Keys.HELP_PATH)
  parser.add_argument(Keys.ARG_CWD, default = None, help = Keys.HELP_CWD)
  # waiver: argparse CLI signature -- the repeatable-flag action name
  parser.add_argument(Keys.ARG_TARGET, action = "append", default = [], help = Keys.HELP_TARGET)
  args = parser.parse_args(argv)

  # an empty --doc list scaffolds the folder and its folder-note alone — documents are seeded
  # later, by the coordinator's launch checkboxes, never by the scaffold itself
  layout = [ parse_doc_token(token) for token in args.doc ]

  # the repo root pins every path; the scaffold itself takes the parsed arguments
  repo = Path(args.cwd).resolve() if args.cwd else repo_root(Path.cwd())
  print(json.dumps(
      scaffold(repo, args.product, args.asset_type, args.slug, layout = layout, path = args.path or "",
               targets = args.target)))
  return 0


def ensure_group_note(repo: Path,
                      group_dir: Path,
                      *,
                      asset_type: str,
                      owner_key: str,
                      owner_record: dict,
                      alias_base: str = "",
                      tokens: dict | None = None,
                      products: dict | None = None,
                      catalog_guidelines: dict[str, list[str]] | None = None) -> Path | None:
  """
  Return a folder's same-named group note, writing it first when the folder has none.

  A note written here is built from the landing type's group-note template chain. It carries the icon of the type
  that owns the folder and no colour, and lands healed with its stats region counted. The product's own root has no
  group note of its own and is never given one. The folder must lie inside the owning product's tree.

  Guarantees:
    - An existing note is never touched, so an operator-edited group note always survives.
    - Every folder other than the product's own root leaves the call with its group note in place, and the result is
      that note's path; None is returned only for the product's own root.

  Args:
    repo: Repository root.
    group_dir: Absolute folder the note is written for; the note is named after the folder. Must lie inside the
      owning product's tree, that is under the content root joined with the owner's `spec_path`.
    asset_type: The asset type whose template chain supplies the note.
    owner_key: Key of the product owning the folder.
    owner_record: The owning product's effective record.
    alias_base: Base context when `asset_type` is an alias, or empty.
    tokens: Template tokens to substitute, or none.
    products: The products registry the template chain's ancestors and the note's language are read from; None reads
      the tracked settings file.
    catalog_guidelines: The catalog-wide `spec.guidelines` already read; None reads them from the tracked settings
      file.

  Returns:
    The group note's path, existing or newly written; None when the folder is the product's own root. A caller that
    needs to know whether the note is fresh checks for its existence before the call.

  Raises:
    ValueError: When `group_dir` lies outside the owning product's tree, whether or not a note exists there; this
      is checked before anything else. When a note is about to be written and the settings file is read for the
      products registry or the catalog-wide guidelines and cannot be read, is not valid JSON, not UTF-8 text or
      not a JSON object.
    ScaffoldRefusal: When a note is about to be written and no group-note template resolves for the type; never
      raised when a note already exists or the folder is the product's own root.
    RuntimeError: When a note is about to be written, its own language and its product's yield nothing, and the
      core plugin's CLI cannot be resolved, its language verb exits non-zero, or the verb exits zero but answers
      nothing.
    OSError: When the group-note template cannot be read or the note cannot be written.
  """

  # Contract:
  # A note that already exists in the folder is never rewritten, merged into or otherwise touched,
  # so an operator-edited group note always survives every caller.

  # Contract:
  # Every folder other than the product's own root leaves the call with its group note in place,
  # and the result is that note's path, whether it already existed or was just written;
  # None is returned only for the product's own root.

  # Domain(spec.declarations):
  # # A shared folder gets its own note only once, from whichever asset arrives first
  # A folder several assets share is not itself an asset, so it earns an editable note of its
  # own only the first time something lands in it or is moved into it — never rewritten afterward,
  # and never created at all over a note the operator or an enclosing asset already owns, or at
  # the product's own root, which is a different worker's concern entirely. The note identifies
  # the folder itself, taking its icon from whichever declared type calls that folder its own
  # default home, regardless of which asset or move actually happened to trigger the seed.

  # the folder is read as the owner sees it — relative to its own tree, which it must lie in
  owner_root = spec_paths.spec_content_root(repo) / owner_record[Keys.SPEC_PATH]
  owner_folder = group_dir.relative_to(owner_root).as_posix()
  group_note = group_dir / f"{group_dir.name}.md"

  # guard: the product root's note is the product wizard's, never a group note
  if group_dir == owner_root:
    return None

  # guard: a note already there is returned as it is, never touched
  if group_note.exists():
    return group_note

  # the note comes from the landing type's template chain
  group_template = resolve_template(repo, asset_type, owner_key, Keys.GROUP_NOTE_TMPL, alias_base = alias_base,
                                     products = products)
  group_text = substitute(group_template.read_text(encoding = "utf-8"), tokens or {})

  # the type that calls this folder its default home names the note's icon
  # waiver: sibling-module declaration walk -- the one merged-declaration view every specs primitive shares
  home_type = next((name for name in asset_types.declared(owner_record)
                    if asset_types.default_path(name, owner_record) == owner_folder), "")

  # Domain(obsidian.icon-resolution):
  # # Container colour is the state axis
  # Colour marks state: an asset's folder takes its colour from its own state, and a document
  # takes its colour from its stage. A container holds no state of its own, so only one kind of
  # container is painted at all — the product root, in a neutral tone a product may override, so
  # a product reads apart from the group folders beneath it. An ordinary group folder — a
  # declared type's own folder or an ad-hoc one — carries no colour key whatsoever, only the
  # icon of the type that owns it as its default folder. A type's declared colour never reaches
  # that folder; it reaches only the asset status notes of that type, as their seed colour.

  # an ordinary container takes the owning type's icon and no colour at all: colour is the
  # state axis and a shelf has no state (the intake shelves are the deliberate exception)
  if home_type and (home_paint := asset_types.icon_color(home_type, owner_record)):
    group_text = inject_iconize(group_text, home_paint[0], "")

  # the note lands healed, its stats region counted from the folder as it stands
  spec_paths.write_text_atomic(group_note, note_explainers.heal_note_text(
      group_note, group_text, products = products, catalog_guidelines = catalog_guidelines))
  summary_render.apply_container_stats(group_note, products = products, catalog_guidelines = catalog_guidelines)
  return group_note


def scaffold(repo: Path,
             product: str,
             asset_type: str,
             slug: str,
             *,
             layout: list[tuple[str, str]] | None = None,
             path: str = "",
             targets: list[str] | None = None,
             products: dict | None = None,
             catalog_guidelines: dict[str, list[str]] | None = None) -> dict:
  """
  Scaffold a new asset folder under a product.

  Guarantees:
    - An existing target asset folder is never merged into or overwritten; the scaffold refuses
      the request and creates nothing under it.
    - Every seeded document's `spec_source_docs` citations and `## Docs` projection come from the
      scaffold alone; citations a template layer ships never survive into the seeded document.
    - With both `products` and `catalog_guidelines` handed in, every product lookup of the scaffold uses them and
      the tracked settings file is not read for product records or catalog-wide guidelines; only the content
      root's `spec.vault_root` is still read from it.

  Args:
    repo: Repository root.
    product: The product key the asset is created under.
    asset_type: The asset type.
    slug: The asset slug, naming the folder and its status note.
    layout: The documents to seed, as `(file, doc_type)` pairs; empty seeds the folder and its note alone.
    path: Folder under the product root overriding the type's `default_path`, or empty.
    targets: Product-relative `<folder>/<slug>` tokens of the assets a change modifies, written as the
      folder-note's `spec_targets` in the given order; none or empty leaves the key absent.
    products: The products registry the caller already read, such as the merged one the runtime dispatches from (an
      overlay-only product, say); none reads the tracked registry. Every product lookup of the scaffold reads it.
    catalog_guidelines: The catalog-wide `spec.guidelines` the caller already read; none reads them from the tracked
      settings file.

  Returns:
    The result object: `outcome`, repo-relative `folder` and `folder_note`, the `docs` seeded with their
    stages, and the `group_note` seeded, if any.

  Raises:
    ScaffoldRefusal: When the type, template or target folder refuses the scaffold, when the product is refused
      (no `products` given and the settings file missing or unreadable, product not registered, no `spec_path`), or a
      `targets` token fails the shape rule of `note-set-key` (non-empty segments, no `.` or `..` step), before
      anything is written.
    ValueError: When a registry is handed in without `catalog_guidelines` and the tracked settings file exists but
      cannot be read, is not UTF-8 text, is not valid JSON or is not a JSON object; with `catalog_guidelines` handed
      in, the tracked file is not read for the catalog-wide guidelines.
    RuntimeError: When a seeded note's own language and its product's yield nothing and the core plugin's CLI
      cannot be resolved, its language verb exits non-zero, or the verb exits zero but answers nothing.
  """

  # Contract:
  # With both `products` and `catalog_guidelines` handed in, every product lookup of the scaffold is answered from
  # them, and the tracked settings file is not read for product records or catalog-wide guidelines; only the
  # content root's `spec.vault_root` is still read from it. A product known only to the caller's registry, such
  # as one declared in the local overlay, therefore scaffolds exactly as declared.

  # guard: a malformed target token is refused before anything is written
  if (bad := [ token for token in targets or [] if not note_ops.is_asset_path_token(token) ]):
    fail(Keys.CAT_LOGICAL, f"invalid --target token: {', '.join(bad)}")

  # the product record supplies every type-scaled decision the scaffold needs; it is read from the registry the
  # caller handed in, else from the tracked settings file
  record = resolve_product(repo, product, products = products, catalog_guidelines = catalog_guidelines)

  # the asset folder the scaffold writes into, under the named product's tree
  folder = _type_folder(asset_type, record, path)
  target_folder = spec_paths.spec_content_root(repo) / record[Keys.SPEC_PATH] / folder / slug

  # a `--path` reaching into a nested product's tree lands the asset in that product: its tag,
  # pins, templates, paint and stages are the innermost owner's, never the caller's key's
  owner_key, owner_record = resolve_owning_product(repo, target_folder, product = product, record = record,
                                                   products = products, catalog_guidelines = catalog_guidelines)

  # an alias type borrows the base's templates; folder and icon stay its own
  alias_base = resolve_alias_base(asset_type, owner_record)
  icon, color = _icon_color(asset_type, owner_record)

  # Contract:
  # An existing target asset folder is never merged into or overwritten; the scaffold refuses the
  # request with a logical error and creates nothing under it.

  # guard: target folder already there, refuse rather than silently overwrite authored docs
  if target_folder.exists():
    fail(Keys.CAT_LOGICAL, f"target folder already exists: {target_folder}")
  target_folder.mkdir(parents = True, exist_ok = False)

  # the substitution tokens every seeded template is filled with: the owning product, its tag and the slug. The
  # `category` token keeps its name for template compatibility and carries the type verbatim.
  tokens = { "product": owner_key, "product_tag": product_tag(owner_record),
             "slug": slug, "category": asset_type }

  # the asset's own status folder-note, seeded from the type's template chain
  note_template = resolve_template(repo, asset_type, owner_key, Keys.FOLDER_NOTE_TMPL,
                                    alias_base = alias_base, products = products)
  note_text = substitute(note_template.read_text(encoding = "utf-8"), tokens)
  note_text = inject_iconize(note_text, icon, color)
  note_text = _inject_type_key(note_text, asset_type)

  # the assets a change modifies, in the order given; no targets leaves the key absent
  if targets:
    note_text = spec_frontmatter.write_list(note_text, SpecTargetsKey.TARGETS, targets)

  # the folder-note lands on disk, healed
  note_path = target_folder / f"{slug}.md"
  spec_paths.write_text_atomic(note_path, note_explainers.heal_note_text(
      note_path, note_text, products = products, catalog_guidelines = catalog_guidelines))

  # Contract:
  # Every seeded document's source-docs citations and `## Docs` projection come from the scaffold
  # alone. A template layer that ships its own citations MUST NOT survive into the seeded document.

  # one doc per --doc entry, each seeded with its cross-reference block and its declared stage
  produced: list[dict] = []
  for doc, doc_type in layout or []:
    tmpl_path = resolve_template(repo, asset_type, owner_key, doc,
                                  alias_base = alias_base, expect_type = doc_type, products = products)
    doc_text = substitute(tmpl_path.read_text(encoding = "utf-8"), tokens)
    doc_text = ensure_doc_type(doc_text, doc_type)

    # the type's own paint: the icon names the kind of document, the registry's matchers own
    # the colour from the first `set-stage` onward. A journal never gets a stage and so keeps
    # this seed for life — which is why no matcher enumerates journals.
    if (doc_paint := spec_doc_types.icon_color(repo, doc_type, owner_key, products = products)):
      doc_text = inject_iconize(doc_text, doc_paint[0], doc_paint[1] or "")
    doc_text = _set_source_docs(doc_text, _default_source_docs())
    doc_path = target_folder / doc
    spec_paths.write_text_atomic(doc_path, doc_text)
    produced.append({ Keys.OUT_FILE: str(doc_path.relative_to(repo)),
                      Keys.OUT_STAGE: _initial_stage(repo, doc_type, owner_key, products = products) })

  # the immediate parent group folder gets its note when this asset is its first arrival, last so a
  # refusal anywhere above leaves no stray note behind
  # limit: only the immediate parent group is seeded; land an asset at each deeper level, or author its note by hand
  group_dir = target_folder.parent
  existed = ( group_dir / f"{group_dir.name}.md" ).exists()
  group_note = ensure_group_note(repo, group_dir, asset_type = asset_type, owner_key = owner_key,
                                 owner_record = owner_record, alias_base = alias_base, tokens = tokens,
                                 products = products, catalog_guidelines = catalog_guidelines)

  # the result names the group note only when this scaffold wrote it
  seeded_group = str(group_note.relative_to(repo)) if group_note and not existed else ""

  # repo-relative paths in the result so the calling skill can quote them straight back
  return {
      "outcome": Keys.OUTCOME_SUCCESS,
      "folder": str(target_folder.relative_to(repo)),
      "folder_note": str(note_path.relative_to(repo)),
      "docs": produced,
      "group_note": seeded_group,
  }
