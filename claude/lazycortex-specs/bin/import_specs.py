"""
Deterministic cross-repo design importer — the primitive behind the
`lazycortex-specs import-specs` CLI subcommand, the `/spec.import` skill,
and the `spec.import-pull` schedule routine.

Pulls a spec-repo by git URL into a gitignored cache, selects assets of
`handoff` products whose stop gate is true, and lands their approved
authored docs read-only (`spec_imported: true`) into this repo per
`docs`-free identity: product compound-key + category + slug.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import flip_gate
import scaffold_asset
import spec_paths

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class _K:
  """
  String constants for the importer.

  Attributes:
    HANDOFF: The product-kind discriminator marking a product as eligible for handoff.
    STOP_AFTER: Settings key naming the gate a product must pass before its assets are exported.
    DEFAULT_STOP: The gate name used when a product declares no explicit `stop_after`.
    PRODUCTS: Settings key holding the product registry.
    STAGE: Frontmatter key naming a doc's lifecycle stage.
    APPROVED: The stage value a doc must carry to be eligible for export.
    GIT_DIR: The `.git` entry checked to detect a repo checkout.
    SPEC_PATH: Settings key naming a product's spec directory.
    ASSET_CATEGORIES: Settings key holding a product's category definitions.
    MD_SUFFIX: The markdown file extension.
    SPEC_SECTION: Settings key naming the spec-repo import configuration block.
    IMPORTS: Settings key holding the list of configured spec-repo import entries.
    GIT_URL: Settings key naming an import entry's remote URL.
    `REF`: Settings key naming an import entry's branch or ref.
    ONLY_PRODUCTS: Settings key restricting an import entry to a subset of product keys.
    IMPORTED: Frontmatter key marking a landed doc as read-only-imported.
    CACHE_DIR: Repo-relative path of the gitignored spec-repo fetch cache.
    SETTINGS_REL: Repo-relative path of the settings file.
    GITIGNORE: The `.gitignore` filename checked and updated for the fetch cache.
    BIN_SEGMENT: Path segment locating a plugin's `bin/` directory.
    CORE_PLUGIN: Plugin name used to resolve the `lazycortex-core` CLI.
    CATEGORY_FOLDER: Key naming an asset's category folder.
    CATEGORY: Key naming an asset's category.
    SLUG: Key naming an asset's slug.
    DOCS: Key naming an asset's list of doc entries.
    NAME: Key naming a doc entry's filename.
    TEXT: Key naming a doc entry's body text.
    OUTCOME_IMPORTED: Outcome token for a newly landed asset.
    OUTCOME_UNCHANGED: Outcome token for an existing asset whose local copy matches the import.
    OUTCOME_DRIFT: Outcome token for an existing asset whose local copy diverged from the import.
    OUTCOME_SKIPPED: Outcome token for an asset that was not landed.
    OUTCOME_SKIPPED_NO_TEMPLATES: Outcome token for an asset skipped because scaffolding refused it.
    DRIFT_ASSETS: Result key listing assets reported with drift.
    AUTO_REGISTERED: Result key listing product keys auto-registered this run.
    ERRORS: Result key listing per-entry error records.
    PROG_IMPORT: CLI program name shown in `--help` output.
    ARG_CWD: CLI flag overriding the repo root.
    SOURCE: Settings key naming a fetched product record's source identifier.
    DEPENDENCIES: Settings key naming a fetched product record's declared dependencies.
  """

  HANDOFF = "handoff"
  STOP_AFTER = "stop_after"
  DEFAULT_STOP = "spec_design_done"
  PRODUCTS = "products"
  STAGE = "spec_stage"
  APPROVED = "approved"
  GIT_DIR = ".git"
  SPEC_PATH = "spec_path"
  ASSET_CATEGORIES = "asset_categories"
  MD_SUFFIX = ".md"
  SPEC_SECTION = "spec"
  IMPORTS = "imports"
  GIT_URL = "git_url"
  REF = "ref"
  ONLY_PRODUCTS = "products"
  IMPORTED = "spec_imported"
  CACHE_DIR = ".experts/.spec-imports"
  SETTINGS_REL = ".claude/lazy.settings.json"
  GITIGNORE = ".gitignore"
  BIN_SEGMENT = "bin"
  CORE_PLUGIN = "lazycortex-core"
  CATEGORY_FOLDER = "category_folder"
  CATEGORY = "category"
  SLUG = "slug"
  DOCS = "docs"
  NAME = "name"
  TEXT = "text"
  OUTCOME_IMPORTED = "imported"
  OUTCOME_UNCHANGED = "unchanged"
  OUTCOME_DRIFT = "drift"
  OUTCOME_SKIPPED = "skipped"
  OUTCOME_SKIPPED_NO_TEMPLATES = "skipped-no-templates"
  DRIFT_ASSETS = "drift_assets"
  AUTO_REGISTERED = "auto_registered"
  ERRORS = "errors"
  PROG_IMPORT = "lazycortex-specs import-specs"
  ARG_CWD = "--cwd"
  SOURCE = "source"
  DEPENDENCIES = "dependencies"


def _slug_of_url(url: str) -> str:
  """
  Turn a git URL (or path) into a filesystem-safe cache-directory slug.

  Args:
    url: Remote URL or local path.

  Returns:
    Lowercase slug of `[a-z0-9-]` chars.
  """
  return re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")


def _fetch(cache_root: Path, url: str, ref: str | None) -> Path:
  """
  Clone (first run) or update (later runs) the spec-repo into the cache.

  Args:
    cache_root: Base cache directory (gitignored).
    url: Git URL or local path of the spec-repo.
    ref: Branch/ref to check out; None means the remote default branch.

  Returns:
    Path of the up-to-date checkout.
  """
  co = cache_root / _slug_of_url(url)
  if not (co / _K.GIT_DIR).exists():
    co.parent.mkdir(parents = True, exist_ok = True)
    args = [ "git", "clone", "--depth", "1", "-q" ]
    if ref:
      args += [ "--branch", ref ]
    subprocess.run([ *args, url, str(co) ], check = True, capture_output = True)
    return co
  # ponytail: clone --branch makes the cache single-branch (remote.origin.fetch
  # pins one ref); a bare `git fetch origin` on a later call with a DIFFERENT ref
  # would silently never create that ref's remote-tracking branch. Fetch it via
  # an explicit refspec instead so `origin/<ref>` always resolves after this call.
  if ref:
    subprocess.run([ "git", "fetch", "-q", "--depth", "1", "origin",
                     f"{ref}:refs/remotes/origin/{ref}" ],
                   cwd = str(co), check = True, capture_output = True)
    target = f"origin/{ref}"
  else:
    subprocess.run([ "git", "fetch", "-q", "--depth", "1", "origin" ],
                   cwd = str(co), check = True, capture_output = True)
    target = "FETCH_HEAD"
  subprocess.run([ "git", "reset", "-q", "--hard", target ],
                 cwd = str(co), check = True, capture_output = True)
  return co


def _handoff_products(settings: dict, only: list[str] | None) -> dict:
  """
  Select products carrying a `handoff` block, optionally narrowed to a key list.

  Args:
    settings: Parsed spec-repo `lazy.settings.json`.
    only: Optional product-key whitelist from the import entry.

  Returns:
    Mapping of product key to record.
  """
  out: dict = {}
  for key, rec in (settings.get(_K.PRODUCTS) or {}).items():
    # guard: schema marker + malformed records carry no handoff
    if not isinstance(rec, dict) or _K.HANDOFF not in rec:
      continue
    # guard: whitelist narrows to the requested product keys only
    if only and key not in only:
      continue
    out[key] = rec
  return out


def _collect_exported(fetched_repo: Path, record: dict) -> list[dict]:
  """
  Collect exportable assets of one handoff product from the fetched checkout.

  An asset qualifies when its status folder-note carries the product's stop
  gate as true; its payload is every authored doc with `spec_stage: approved`.

  Args:
    fetched_repo: Checkout dir of the fetched spec-repo.
    record: The product record (with `spec_path` + `handoff`).

  Returns:
    List of `{category_folder, category, slug, docs:[{name,text}]}` items.
  """
  stop = (record.get(_K.HANDOFF) or {}).get(_K.STOP_AFTER) or _K.DEFAULT_STOP
  base = spec_paths.spec_content_root(fetched_repo) / record[_K.SPEC_PATH]
  out: list[dict] = []
  # guard: product folder absent in the fetched tree — nothing exported yet
  if not base.is_dir():
    return out
  builtin = { v: k for k, v in scaffold_asset._Category.BUILTIN_FOLDERS.items() }
  cats = record.get(_K.ASSET_CATEGORIES) or {}
  for cat_dir in sorted(p for p in base.iterdir() if p.is_dir()):
    if cat_dir.name in builtin:
      category = builtin[cat_dir.name]
    elif cat_dir.name in cats:
      category = cat_dir.name
    else:
      # guard: folder matches neither a built-in nor a declared operator category
      continue
    for asset_dir in sorted(p for p in cat_dir.iterdir() if p.is_dir()):
      note = asset_dir / f"{asset_dir.name}{_K.MD_SUFFIX}"
      # guard: no status folder-note — asset dir isn't a real asset
      if not note.is_file():
        continue
      fm, _end = flip_gate._parse_frontmatter(note.read_text())
      # guard: stop gate not reached — asset still mid-ladder in the spec-repo
      if not flip_gate._is_true(fm, stop):
        continue
      docs: list[dict] = []
      for doc in sorted(asset_dir.iterdir()):
        # guard: skip the status note itself and any non-markdown sibling
        if doc.name == note.name or not doc.name.endswith(_K.MD_SUFFIX):
          continue
        dfm, _e = flip_gate._parse_frontmatter(doc.read_text())
        if dfm.get(_K.STAGE) == _K.APPROVED:
          docs.append({ "name": doc.name, "text": doc.read_text() })
      if docs:
        out.append({ "category_folder": cat_dir.name, "category": category,
                     "slug": asset_dir.name, "docs": docs })
  return out


def _mark_imported(text: str) -> str:
  """
  Inject `spec_imported: true` into a doc's frontmatter block.

  Args:
    text: Full doc text with a leading frontmatter block.

  Returns:
    Text with the marker as the last frontmatter line; unchanged when the
    marker is already present or no frontmatter exists.
  """
  # guard: malformed doc without frontmatter
  if not text.startswith("---\n"):
    return text
  end = text.find("\n---", 4)
  if end < 0:
    return text
  # guard: already marked — scoped to the frontmatter slice so a body line that
  # happens to contain the same text never causes a false-positive skip
  if f"{_K.IMPORTED}: true" in text[:end]:
    return text
  return text[:end] + f"\n{_K.IMPORTED}: true" + text[end:]


def _write_products(dev_repo: Path, products: dict) -> None:
  """
  Persist the products section via the core CLI settings-set boundary.

  Args:
    dev_repo: Dev-repo root.
    products: Full products object to write.
  """
  cli = None
  for d in os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "").split(os.pathsep):
    cand = Path(d) / _K.BIN_SEGMENT / _K.CORE_PLUGIN
    if cand.is_file():
      cli = cand
      break
  # fall back to the dev-vault sibling layout when the daemon env is absent
  if cli is None:
    sib = Path(__file__).resolve().parents[2] / _K.CORE_PLUGIN / _K.BIN_SEGMENT / _K.CORE_PLUGIN
    cli = sib if sib.is_file() else None
  if cli is None:
    raise RuntimeError("lazycortex-core CLI not resolvable for settings-set products")
  env = { **os.environ, "LAZY_REPO_ROOT": str(dev_repo) }
  subprocess.run([ str(cli), "settings-set", _K.PRODUCTS ],
                 input = json.dumps(products), text = True, env = env,
                 cwd = str(dev_repo), check = True, capture_output = True)


def _ensure_product(dev_repo: Path, key: str, fetched_record: dict) -> tuple[dict, bool]:
  """
  Return the dev product record for `key`, auto-registering from the fetched
  record when absent (mirrored `spec_path`; `handoff`, `source`, and
  `dependencies` stripped).

  Args:
    dev_repo: Dev-repo root.
    key: Product compound-key.
    fetched_record: The record as read from the fetched spec-repo settings.

  Returns:
    Tuple of the effective dev product record and whether this call just
    auto-registered it (`False` when the operator had already pre-registered
    the product — its record wins verbatim).
  """
  settings = json.loads((dev_repo / _K.SETTINGS_REL).read_text())
  products = settings.get(_K.PRODUCTS) or {}
  existing = products.get(key)
  # guard: operator pre-registered the product — its spec_path wins
  if isinstance(existing, dict):
    return existing, False
  rec = { k: v for k, v in fetched_record.items()
         if k not in (_K.HANDOFF, _K.SOURCE, _K.DEPENDENCIES) }
  products[key] = rec
  _write_products(dev_repo, products)
  return rec, True


def _land_asset(dev_repo: Path, key: str, record: dict, asset: dict) -> tuple[str, Path]:
  """
  Land one exported asset into the dev repo.

  New asset: scaffold via the standard primitive, then overwrite the design-role
  docs with the imported copies carrying the read-only marker. Existing asset:
  byte-compare; report drift, never overwrite.

  Args:
    dev_repo: Dev-repo root.
    key: Product compound-key.
    record: Dev product record.
    asset: Item from `_collect_exported`.

  Returns:
    Tuple of the outcome word (`imported` / `unchanged` / `drift` /
    `skipped-no-templates`) and the asset's target directory.
  """
  content_root = spec_paths.spec_content_root(dev_repo)
  target = content_root / record[_K.SPEC_PATH] / asset[_K.CATEGORY_FOLDER] / asset[_K.SLUG]
  if not target.exists():
    argv = [ key, asset[_K.CATEGORY], asset[_K.SLUG], _K.ARG_CWD, str(dev_repo) ]
    buf = io.StringIO()
    try:
      with contextlib.redirect_stdout(buf):
        rc = scaffold_asset.main(argv)
    except SystemExit as exc:
      # scaffold's own error path exits rather than returning; treat non-int codes as failure
      rc = exc.code if isinstance(exc.code, int) else 1
    # guard: scaffold refused (e.g. operator category without templates)
    if rc != 0:
      return _K.OUTCOME_SKIPPED_NO_TEMPLATES, target
    for doc in asset[_K.DOCS]:
      (target / doc[_K.NAME]).write_text(_mark_imported(doc[_K.TEXT]))
    return _K.OUTCOME_IMPORTED, target
  drift = False
  for doc in asset[_K.DOCS]:
    local = target / doc[_K.NAME]
    if not local.is_file() or local.read_text() != _mark_imported(doc[_K.TEXT]):
      drift = True
  return (_K.OUTCOME_DRIFT if drift else _K.OUTCOME_UNCHANGED), target


def _ensure_gitignore(dev_repo: Path) -> bool:
  """
  Ensure the dev repo's `.gitignore` excludes the importer's fetch cache.

  Args:
    dev_repo: Dev-repo root.

  Returns:
    `True` when the file was created or the line was appended; `False` when
    the line was already present and nothing changed.
  """
  path = dev_repo / _K.GITIGNORE
  line = f"{_K.CACHE_DIR}/"
  text = path.read_text() if path.is_file() else ""
  # guard: already present — nothing to add
  if line in text.splitlines():
    return False
  sep = "" if not text or text.endswith("\n") else "\n"
  path.write_text(text + sep + line + "\n")
  return True


def _commit_run(dev_repo: Path, paths: list[Path]) -> None:
  """
  Atomically commit exactly the paths this run touched, under the importer
  bot identity.

  Args:
    dev_repo: Dev-repo root.
    paths: Absolute paths landed/modified this run (asset target dirs, the
      settings file when a product was auto-registered, `.gitignore` when
      rewritten). Empty when nothing changed.
  """
  # guard: nothing landed this run — no commit
  if not paths:
    return
  rels = sorted({ str(p.resolve().relative_to(dev_repo.resolve())) for p in paths })
  subprocess.run([ "git", "add", "--", *rels ], cwd = str(dev_repo), check = True,
                 capture_output = True)
  staged = subprocess.run([ "git", "diff", "--cached", "--quiet" ],
                          cwd = str(dev_repo), check = False)
  # guard: paths named but nothing actually changed on disk — no commit
  if staged.returncode == 0:
    return
  subprocess.run([
      "git", "-c", "user.name=spec.import", "-c", "user.email=spec.import@bot.invalid",
      "-c", "commit.gpgsign=false", "commit", "-q", "-m", "spec.import: pull exported designs",
  ], cwd = str(dev_repo), check = True, capture_output = True)


def run(dev_repo: Path) -> dict:
  """
  Execute every `spec.imports` entry of the dev repo once.

  Each entry is processed independently: a failure fetching or reading one
  entry (unreachable `git_url`, malformed settings, an unresolvable product
  field) is recorded in the `errors` list rather than aborting the run — the
  remaining entries still land normally, and the commit step always runs
  once over whatever changed.

  Args:
    dev_repo: Dev-repo root.

  Returns:
    Summary dict: counts per outcome, the per-drift asset list, the product
    keys auto-registered this run, and the per-entry error list.
  """
  # the import entries are the only source of what this run reaches for
  settings = json.loads((dev_repo / _K.SETTINGS_REL).read_text())
  entries = (settings.get(_K.SPEC_SECTION) or {}).get(_K.IMPORTS) or []

  # counters and lists accumulate across every entry, and become the summary returned below
  imported = unchanged = drift = skipped = 0
  drift_assets: list[str] = []
  auto_registered: list[str] = []
  errors: list[dict] = []
  changed: list[Path] = []

  # one checkout per entry, then every handed-off product inside it
  cache = dev_repo / _K.CACHE_DIR
  for entry in entries:
    try:
      co = _fetch(cache, entry[_K.GIT_URL], entry.get(_K.REF))
      fetched = json.loads((co / _K.SETTINGS_REL).read_text())
      for key, rec in _handoff_products(fetched, entry.get(_K.ONLY_PRODUCTS)).items():
        assets = _collect_exported(co, rec)
        # guard: nothing exported yet for this product — registering it now would
        # be premature (registration and landing happen together)
        if not assets:
          continue
        # an unknown product auto-registers here, which mutates settings and joins the commit set
        dev_rec, registered = _ensure_product(dev_repo, key, rec)
        if registered:
          auto_registered.append(key)
          changed.append(dev_repo / _K.SETTINGS_REL)

        # each landed asset feeds exactly one outcome counter
        for asset in assets:
          outcome, target = _land_asset(dev_repo, key, dev_rec, asset)
          if outcome == _K.OUTCOME_IMPORTED:
            imported += 1
            changed.append(target)
          elif outcome == _K.OUTCOME_UNCHANGED:
            unchanged += 1
          elif outcome == _K.OUTCOME_DRIFT:
            drift += 1
            drift_assets.append(f"{key}/{asset[_K.CATEGORY_FOLDER]}/{asset[_K.SLUG]}")
          else:
            skipped += 1
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
      # record one bad entry (unreachable git_url, malformed settings) and carry on, so it
      # cannot abort entries that already fetched fine
      errors.append({ _K.GIT_URL: entry.get(_K.GIT_URL), "error": str(exc)[:200] })

  # the cache dir must stay untracked, so a fresh ignore entry joins the commit set too
  if _ensure_gitignore(dev_repo):
    changed.append(dev_repo / _K.GITIGNORE)

  # one commit over everything this run touched, then the caller gets the tallies
  _commit_run(dev_repo, changed)
  return { _K.OUTCOME_IMPORTED: imported, _K.OUTCOME_UNCHANGED: unchanged,
           _K.OUTCOME_DRIFT: drift, _K.OUTCOME_SKIPPED: skipped,
           _K.DRIFT_ASSETS: drift_assets, _K.AUTO_REGISTERED: auto_registered,
           _K.ERRORS: errors }


def main(argv: list[str]) -> int:
  """
  Run the `import-specs` subcommand.

  Args:
    argv: Subcommand tail (optional `--cwd`).

  Returns:
    Process exit code (`0` even with drift — drift is a report, not an error).
  """
  parser = argparse.ArgumentParser(prog = _K.PROG_IMPORT)
  parser.add_argument(_K.ARG_CWD, default = None)
  args = parser.parse_args(argv)
  dev = Path(args.cwd).resolve() if args.cwd else spec_paths.find_settings_root(Path.cwd())
  print(json.dumps(run(dev)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
