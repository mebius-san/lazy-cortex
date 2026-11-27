"""
Resolve the guideline paths a review writer dispatch carries.

Per `lazy-spec.config-protocol.md` § `products[<key>].guidelines`, a product's guidelines are
keyed by the dispatched role token plus the wildcard `"*"`, and an asset type's own
`guidelines` reach every job on an asset of that type whatever the role. The declared list is
the ordered union catalog-wide `spec.guidelines` first, then the enclosing products outermost
first, then the owning product's own — role paths, then the asset type's, then the wildcard
set.

The declared list goes through core's `guidelines-resolve` verb (`lazy-core.guidelines-contract.md`),
which puts the canon every enabled plugin declares for the role ahead of it, resolves
`<plugin>:<name>` keys to absolute paths into the plugin tree, keeps repo paths repo-relative,
and drops repeats. The plugin canon depends on the role alone, so the verb runs on every
document, inside a product or not.

The coordinator (`lazy-review.coordination-playbook.md` Chapter 4) reaches this module through
the `guidelines-context` CLI verb before every main or barrier (`validation` / `terminal`)
writer dispatch — never before `doc_doctor`'s repair dispatch. The writer dispatch folds the
repo-relative paths into the dispatch's `context` and lists the absolute ones in the payload's
`guidelines`. The expert reads the real files; nothing is copied here.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import core_settings as _core_settings  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import decisions_context  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import frontmatter as _fm  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from errors import SettingsReadError  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import CoreCommand  # noqa: E402  # pylint: disable=import-error,wrong-import-position


_SPEC_SECTION_KEY = "spec"
_PRODUCTS_KEY = "products"
_SPEC_PATH_KEY = "spec_path"
_GUIDELINES_KEY = "guidelines"
_WILDCARD_ROLE = "*"
_ASSET_TYPES_KEY = "asset_types"
_ASSET_TYPE_KEY = "spec_asset_type"
_EXPERT_KEY_SEP = "."

# The warning a refused spec content root leaves in place of the guidelines, filled with the refusal.
_ROOT_REFUSED_TEMPLATE = "guidelines not collected: {error}"
# The warning a declared path with no file behind it leaves when core cannot check it.
_NOT_FOUND_TEMPLATE = "guideline not found: {rel}"
# The warning a core resolve that could not run leaves, filled with the reason.
_RESOLVE_FAILED_TEMPLATE = "plugin guidelines not resolved: {error}"
# The core `guidelines-resolve` flags, and the stdin key carrying the caller's entries.
_ROLE_FLAG = "--role"
_CWD_FLAG = "--cwd"
_BASE_FLAG = "--base"
_DECLARED_KEY = "declared"
# The key of core's error answer naming why the verb refused.
_ERROR_KEY = "error"

PATHS_KEY = "paths"
WARNINGS_KEY = "warnings"


def role_of(expert: str) -> str:
  """
  Derive the guideline role token from a composed expert key.

  Args:
    expert: The dispatched expert's key, `<domain>.<role>` (`catalog.data-writer`).

  Returns:
    The part after the first dot; the whole key when it carries none.
  """
  return expert.partition(_EXPERT_KEY_SEP)[2] or expert


def _build_product_chain(data: dict, content_root: Path, start_dir: Path) -> list[dict]:
  """
  List the registered product records covering `start_dir`, outermost first.

  Args:
    data: The parsed settings file.
    content_root: The spec content root the products' `spec_path` values hang under.
    start_dir: Absolute directory to attribute — a document's own folder.

  Returns:
    Every product record whose `spec_path` resolves onto or above `start_dir`, ordered from
    the shallowest root to the deepest; empty when no product covers it.
  """
  products = data.get(_PRODUCTS_KEY)

  # guard: no products map at all — nothing to match start_dir against
  if not isinstance(products, dict):
    return []

  # scan every registered product; each covering root is one layer, keyed by its depth for the sort
  covering: list[tuple[int, dict]] = []
  for record in products.values():
    # guard: a non-dict entry can carry no spec_path field to check below
    if not isinstance(record, dict):
      continue

    # guard: only a non-empty spec_path names a product root
    if not isinstance(spec_path := record.get(_SPEC_PATH_KEY), str) or not spec_path:
      continue

    # a root that is start_dir itself or sits above it covers the document
    candidate = content_root / spec_path
    if candidate == start_dir or candidate in start_dir.parents:
      covering.append((len(candidate.parts), record))
  return [ record for _depth, record in sorted(covering, key = lambda pair: pair[0]) ]


def _read_asset_type(doc_path: Path) -> str:
  """
  Read the `spec_asset_type` of the asset folder holding `doc_path`, when it is one.

  Args:
    doc_path: Absolute path to the document under review.

  Returns:
    The declared type name; the empty string outside an asset folder or when the key is absent.
  """
  asset_dir = decisions_context.resolve_asset_dir(doc_path)

  # guard: not inside a spec asset folder — no type to read
  if asset_dir is None:
    return ""

  # the status folder-note is the one place the asset's type is declared
  meta, _body = _fm.parse((asset_dir / f"{asset_dir.name}.md").read_text(encoding = "utf-8"))
  value = meta.get(_ASSET_TYPE_KEY)
  return value if isinstance(value, str) else ""


def _collect_role_paths(layers: list[dict], role: str) -> list[str]:
  """
  Union one role's guideline paths across the config layers, outermost first.

  Args:
    layers: The `guidelines` dicts, catalog first, then products outermost first.
    role: The role key to read from each layer.

  Returns:
    The declared paths in layer order; empty when no layer declares the role.
  """
  paths: list[str] = []
  for layer in layers:
    declared = layer.get(role)
    if isinstance(declared, list):
      paths.extend(path for path in declared if isinstance(path, str))
  return paths


def _collect_type_paths(chain: list[dict], asset_type: str) -> list[str]:
  """
  Resolve the asset type's own guideline paths — the innermost product declaring them wins.

  Args:
    chain: The covering product records, outermost first.
    asset_type: The dispatched asset's `spec_asset_type`; empty when there is none.

  Returns:
    The declared paths, empty when no product declares the field for the type.
  """

  # guard: no asset type — a product-level document carries no type guidelines
  if not asset_type:
    return []

  # asset_types merge key-by-key down the chain, so the deepest declaration of the field wins
  for record in reversed(chain):
    types = record.get(_ASSET_TYPES_KEY)
    decl = types.get(asset_type) if isinstance(types, dict) else None
    declared = decl.get(_GUIDELINES_KEY) if isinstance(decl, dict) else None
    if isinstance(declared, list):
      return [ path for path in declared if isinstance(path, str) ]
  return []


def _run_resolve(root: Path, role: str, declared: list[str]) -> dict[str, list[str]]:
  """
  Ask core's `guidelines-resolve` for the files `role` reads on top of `declared`.

  Args:
    root: The repository the job works in.
    role: The job's role token.
    declared: The caller's guideline entries, in the caller's order.

  Returns:
    Core's answer: `paths` and `warnings`, both lists of strings.

  Raises:
    RuntimeError: When no core CLI is resolvable, the verb exits non-zero, or its answer is not the
      `{paths, warnings}` shape.
  """
  # no core CLI reachable raises — the caller reports it instead of the plugin canon; the declared paths are
  # relative to the settings root, so core checks them there
  cli = _git_ops.require_core_cli(root)
  proc = subprocess.run(
      [ sys.executable, str(cli), CoreCommand.GUIDELINES_RESOLVE, _ROLE_FLAG, role, _CWD_FLAG, str(root),
        _BASE_FLAG, str(root) ],
      input = json.dumps({ _DECLARED_KEY: declared }),
      capture_output = True, text = True, check = False, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
  )

  # the verb answers JSON on stdout in both outcomes; an unparsable answer reads as no answer
  try:
    answer = json.loads(proc.stdout)
  except json.JSONDecodeError:
    answer = None

  # guard: a refusal names its reason in `error`, else on stderr
  if proc.returncode != 0:
    reason = answer.get(_ERROR_KEY) if isinstance(answer, dict) else None
    reason = reason or proc.stderr.strip() or "no reason given"
    raise RuntimeError(f"{CoreCommand.GUIDELINES_RESOLVE} exited {proc.returncode}: {reason}")

  # guard: a success always answers two lists of strings; anything else is a broken wire
  paths = answer.get(PATHS_KEY) if isinstance(answer, dict) else None
  warnings = answer.get(WARNINGS_KEY) if isinstance(answer, dict) else None
  if not isinstance(paths, list) or not isinstance(warnings, list) or not _is_str_list(paths + warnings):
    raise RuntimeError(f"{CoreCommand.GUIDELINES_RESOLVE} answered no {{paths, warnings}} object")

  # core's answer, as the caller reads it
  return { PATHS_KEY: paths, WARNINGS_KEY: warnings }


# waiver: `value` is a field of core's JSON answer and may be any JSON value; the body narrows it
def _is_str_list(value: object) -> bool:
  """
  Tell whether a JSON value is a list of strings.

  Args:
    value: The value to check.

  Returns:
    True for a list whose every item is a string.
  """
  return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _resolve(root: Path, role: str, declared: list[str], warnings: list[str]) -> dict[str, list[str]]:
  """
  Resolve the declared guidelines with the enabled plugins' canon for `role` ahead of them.

  Args:
    root: The repository the declared paths are relative to.
    role: The job's role token.
    declared: The caller's guideline paths, in the caller's order.
    warnings: Warnings the caller already holds; they come first in the answer.

  Returns:
    The `{paths, warnings}` map. When core cannot resolve, `paths` holds the declared paths that are files and
    `warnings` names each missing one and the failure.
  """

  # the core verb owns the plugin layer, key resolution and dedup
  try:
    answer = _run_resolve(root, role, declared)
  except RuntimeError as error:
    # the declared paths are still checked here, so only the plugin canon is missing from the answer
    unique = list(dict.fromkeys(declared))
    return {
        PATHS_KEY: [ rel for rel in unique if (root / rel).is_file() ],
        WARNINGS_KEY: [
            *warnings,
            *( _NOT_FOUND_TEMPLATE.format(rel = rel) for rel in unique if not (root / rel).is_file() ),
            _RESOLVE_FAILED_TEMPLATE.format(error = error),
        ],
    }

  # core answered: its lists follow the warnings the caller already holds
  return { PATHS_KEY: answer[PATHS_KEY], WARNINGS_KEY: [ *warnings, *answer[WARNINGS_KEY] ] }


def collect(doc_path: Path, expert: str) -> dict[str, list[str]]:
  """
  Resolve the guideline paths a writer of `expert` carries while working on `doc_path`.

  Guarantees:
    - A declared guideline path that does not resolve to a file is always reported in
      `warnings`, never silently dropped.
    - Paths come back with the enabled plugins' canon for the role first, then the product's
      role-specific paths, then the asset type's, then the wildcard set, with a path already
      listed never repeated.
    - The plugin canon depends only on the role: it is resolved on every document, also with
      no settings file, unreadable settings, a refused spec content root, or no product
      covering the document, unless core cannot resolve, where the next guarantee applies and
      no canon comes back.
    - When core cannot resolve, the declared paths that are files still come back, and one
      warning names the failure.

  Args:
    doc_path: Absolute path to the document under review.
    expert: The dispatched expert's composed key; its role part selects the role guidelines.

  Returns:
    A map with `paths` — the plugin canon first, absolute, then the declared entries that resolve, in declared
    order, each `<plugin>:<name>` key as an absolute path and each repo path repo-relative — and `warnings`
    naming every entry that does not resolve. Outside a registered product, and when the settings cannot be
    read, only the plugin canon is in `paths`; a refused spec content root adds one warning naming the refusal.
  """

  # Contract:
  # A declared guideline path that does not resolve to a file is never silently dropped; it is
  # always reported back in `warnings` for the coordinator to log.

  # Contract:
  # Paths MUST come back plugin canon first, then role-specific, then the asset type's own, then
  # the wildcard set, with a path already listed never repeated.

  # Contract:
  # The role's plugin canon MUST be returned on every document, with or without settings, readable
  # settings, a spec content root, or a covering product, unless core cannot resolve, per the next
  # contract.

  # Contract:
  # When core cannot resolve, the declared guideline paths that are files MUST still be returned, in
  # declared order and without repeats; each declared path that is not a file is reported in `warnings`,
  # and one more warning names the failure.

  # Domain(review.dispatch):
  # # Guidelines context for a review writer
  # A writer first follows the canon every plugin enabled in the repository declares for the
  # role it is playing, whatever document it works on. On a document inside a registered
  # product it then follows the guidelines the product declares for that role, then the
  # guidelines that belong to the kind of asset the document describes whatever the role — a
  # content record's schema reaches its designer and its data writer alike — and finally the
  # guidelines that apply to every role. Enclosing products contribute theirs before the owning
  # product's own, and the catalog-wide set comes before all of them.

  # the role the expert plays selects both the plugin canon and the declared role guidelines
  role = role_of(expert)

  # the settings file above the document is the only record of products and their guidelines
  settings_root = decisions_context.find_settings_root(doc_path.parent)

  # guard: no settings file above the document — only the plugin canon reaches it
  if settings_root is None:
    return _resolve(doc_path.parent, role, [], [])

  # guard: the merged `spec` and `products` sections; an unreadable settings layer declares nothing
  try:
    data = _core_settings.read_merged_sections(settings_root, _SPEC_SECTION_KEY, _PRODUCTS_KEY)
  except SettingsReadError:
    return _resolve(settings_root, role, [], [])

  # the catalog-wide section, empty when the settings carry none or no mapping
  spec_cfg = data.get(_SPEC_SECTION_KEY)
  spec_cfg = spec_cfg if isinstance(spec_cfg, dict) else {}

  # guard: the spec content root the product paths resolve under; a refused root declares nothing and is reported
  try:
    content_root = _core_settings.spec_content_root(settings_root, spec_cfg)
  except SettingsReadError as error:
    return _resolve(settings_root, role, [], [ _ROOT_REFUSED_TEMPLATE.format(error = error) ])

  # every product whose root covers the document, outermost first, is a layer of guidelines
  chain = _build_product_chain(data, content_root, doc_path.parent)

  # guard: no registered product covers the document — only the plugin canon reaches it
  if not chain:
    return _resolve(settings_root, role, [], [])

  # the catalog-wide layer stands before every product's own, outermost first after it
  raw_layers = [ spec_cfg.get(_GUIDELINES_KEY), *(record.get(_GUIDELINES_KEY) for record in chain) ]
  layers: list[dict] = [ layer for layer in raw_layers if isinstance(layer, dict) ]
  declared = (
      _collect_role_paths(layers, role)
      + _collect_type_paths(chain, _read_asset_type(doc_path))
      + _collect_role_paths(layers, _WILDCARD_ROLE)
  )

  # core puts the plugin canon ahead, checks every path and warns on each that does not resolve
  return _resolve(settings_root, role, declared, [])
