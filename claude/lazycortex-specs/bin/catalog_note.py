"""
Level-note backfill — the Python primitive backing the `lazycortex-specs catalog-note` verb.

A level note is the folder-note of the catalog root or of one product: the document the catalog
coordinator owns, carrying the level role, the four level gates, the halt flag, the paint keys,
and the coordinator's own body sections. `lazy-spec.install` seeds the root note through this
verb, and `lazy-spec.product-config` brings each existing product note up to the same schema.

CLI: `catalog-note backfill (<product> | --root) [--today <YYYY-MM-DD>]`. The root form targets
`<vault_root>/<vault_root basename>.md`; the product form targets `<spec_path>/<leaf>.md` under
the content root, following the folder-note convention rather than the product's own key. A
missing note is created from the `level-note.md` template chain; an existing one only gains what
it lacks — no key is rewritten, no section is moved, and the operator's `# Coordinator rules`
and the rendered `# Summary` survive byte-for-byte. A second run over a conforming note writes
nothing at all.

Stdout: a JSON object with `outcome` (`created` / `updated` / `unchanged`), the note's
repo-relative path under `note`, and the frontmatter keys and section headings the run added
under `added`. Nothing is staged or committed — the caller owns the commit.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import sys
from pathlib import Path

import asset_types
import flip_gate
import note_explainers
import note_ops
import scaffold_asset
import spec_paths
from spec_keys import BOOL_FALSE, LEVEL_GATE_ORDER, Section, SpecHaltKey, SpecKey, SpecValue

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class _Out:
  """
  Result-dict field names this verb returns and prints.

  Attributes:
    OUTCOME: The field naming what the run did to the note.
    NOTE: The field carrying the note's repo-relative path.
    ADDED: The field listing every frontmatter key and section heading the run added.
  """

  OUTCOME = "outcome"
  NOTE = "note"
  ADDED = "added"


class _Outcome:
  """
  `_Out.OUTCOME` values this verb reports.

  Attributes:
    CREATED: The note did not exist and was seeded from the template.
    UPDATED: The note existed and gained at least one key or section.
    UNCHANGED: The note already carried the full schema — nothing was written.
  """

  CREATED = "created"
  UPDATED = "updated"
  UNCHANGED = "unchanged"


# The level note's body in canonical order. `# Summary` opens it (the plugin's own précis and
# stats region) and `# Attachments` closes it (the coordinator's registry of the level
# documents' attachments); the five between are the coordinator's own working sections.
_SECTION_ORDER = (
    Section.SUMMARY,
    Section.GATES,
    Section.STATUS_BRIEF,
    Section.COORD_RULES,
    Section.COORD_COMMANDS,
    Section.HISTORY,
    Section.ATTACHMENTS,
)

# Template filename and the category whose override chain resolves it. One template serves both
# level roles — the role reaches it as a token, so a consumer overriding the product category's
# copy re-shapes the catalog root note with it.
_TEMPLATE_NAME = "level-note.md"
_TEMPLATE_CATEGORY = "product"
_ROLE_TOKEN = "role"

# Identity recorded in the `# History` line this verb leaves behind, mirroring the `<actor>` half
# of every other verb's own line.
_ACTOR = "lazy-spec.catalog-note"

# CLI argparse names and help strings.
_PROG = "lazycortex-specs catalog-note"
_VERB_BACKFILL = "backfill"
_ARG_VERB = "verb"
_ARG_PRODUCT = "product"
_ARG_ROOT = "--root"
_ARG_TODAY = "--today"
# waiver: one-off human-facing messages -- argparse help text and one stderr refusal line
_HELP_VERB = "The level-note verb to run"
_HELP_PRODUCT = "Product compound-key whose level note is backfilled; omit for --root"
_HELP_ROOT = "Target the catalog root note instead of a product's own"
_HELP_TODAY = "ISO date pinned into the emitted history line"
_ERR_TARGET = "name exactly one of <product> or --root\n"


def _target(repo: Path, product: str | None, root: bool) -> tuple[Path, str, dict]:
  """
  Resolve which level note a call names, the role that note carries, and its product record.

  The product form follows the Obsidian folder-note convention every other resolver in the
  plugin follows: the note is named after the leaf of the product's `spec_path`, never after
  the product's compound-key, so a key that differs from its folder still names one note.

  Args:
    repo: The settings root holding `.claude/lazy.settings.json`.
    product: The product compound-key, or None for the root form.
    root: True when the catalog root note is the target.

  Returns:
    A `(note_path, role, record)` triple; the record is empty for the root form, which belongs
    to no product.

  Raises:
    SystemExit: When the product form names a key no product registry declares.
  """
  content_root = spec_paths.spec_content_root(repo)
  # guard: the root form has no product record to read — the vault root names its own note
  if root:
    return content_root / f"{content_root.name}.md", SpecValue.ROLE_CATALOG, {}
  record = scaffold_asset._resolve_product(repo, product or "")
  product_dir = content_root / record[scaffold_asset._K.SPEC_PATH]
  return product_dir / f"{product_dir.name}.md", SpecValue.ROLE_PRODUCT, record


def _paint(role: str, record: dict) -> tuple[str, str]:
  """
  Resolve the icon and colour a level note is painted with.

  Args:
    role: The level role the note carries.
    record: The owning product's settings record, empty for the catalog root.

  Returns:
    An `(icon, color)` pair — the product's own declaration where it makes one, the shipped
    registry's declaration for the role otherwise; either half may be empty.
  """
  icon, color = asset_types.icon_color(role, {}) or ( "", "" )
  return ( str(record.get(asset_types.AssetTypeField.ICON) or icon),
           str(record.get(asset_types.AssetTypeField.COLOR) or color) )


def _managed_keys(role: str, record: dict) -> list[tuple[str, str]]:
  """
  Build the frontmatter a level note of one role owes, as `(key, literal)` pairs.

  Args:
    role: The level role the note carries.
    record: The owning product's settings record, empty for the catalog root.

  Returns:
    The role key, the four level gates closed, the halt flag, and the role's paint keys, in
    write order; the colour literal is quoted so YAML never reads it as a comment.
  """
  pairs = [ ( SpecKey.ROLE, role ) ]
  pairs += [ ( gate, BOOL_FALSE ) for gate in LEVEL_GATE_ORDER ]
  pairs.append(( SpecHaltKey.HALTED, BOOL_FALSE ))

  # the resolved paint keys put the folder's icon in the explorer
  icon, color = _paint(role, record)
  if icon:
    pairs.append(( note_ops._ICONIZE_ICON_KEY, icon ))
  if color:
    pairs.append(( note_ops._ICONIZE_COLOR_KEY, f'"{color}"' ))
  return pairs


def _seed_text(repo: Path, role: str, product: str, record: dict) -> str:
  """
  Render a fresh level note from the template chain.

  Args:
    repo: The settings root the template override chain is resolved against.
    role: The level role stamped into the template's role token.
    product: The product compound-key scoping the per-product override layer; empty for the root.
    record: The owning product's settings record, empty for the catalog root.

  Returns:
    The rendered note text, its paint keys already spliced into the frontmatter.

  Raises:
    SystemExit: When no layer of the override chain carries the level-note template.
  """
  template = scaffold_asset._resolve_template(repo, _TEMPLATE_CATEGORY, product, _TEMPLATE_NAME)
  text = scaffold_asset._substitute(template.read_text(), { _ROLE_TOKEN: role })
  icon, color = _paint(role, record)
  return scaffold_asset._inject_iconize(text, icon, color)


def _section_blocks(text: str) -> dict[str, list[str]]:
  """
  Split a note body into its H1 sections, each mapped to its own block of lines.

  A `#tag` line opens no section — only an ATX heading (`# ` with its space) does, so a
  section's protected-owner tag stays inside the section it owns.

  Args:
    text: The body text (post-frontmatter) to split.

  Returns:
    Mapping of each heading line to the lines it owns, the heading line first. Text above the
    first heading belongs to no section and is absent from the mapping.
  """
  blocks: dict[str, list[str]] = {}
  current = ""
  for line in text.splitlines():
    if line.startswith("# "):
      current = line.strip()
      blocks[current] = [ current ]
      continue
    if current:
      blocks[current].append(line)
  return blocks


def _rendered_block(lines: list[str], lang: str) -> list[str]:
  """
  Render one template section into the lines an insertion carries, explainer included.

  Args:
    lines: The template section's own lines, the heading first.
    lang: The vault's authoring language, for the section's explainer line.

  Returns:
    The section's lines followed by one blank line, so consecutive insertions stay separated.
  """
  healed = note_explainers.ensure_explainers("\n".join(lines).rstrip("\n") + "\n", lang)
  return [ *healed.rstrip("\n").splitlines(), "" ]


def _anchor(heading: str, positions: dict[str, int], end: int) -> int:
  """
  Find the line a missing section is inserted before, so the roster keeps its canonical order.

  Args:
    heading: The missing section's heading.
    positions: Line index of every canonical heading the body already carries.
    end: The body's line count, used when no later canonical section is present.

  Returns:
    The insertion index — the first later canonical section's own line, else the body's end.
  """
  tail = _SECTION_ORDER[_SECTION_ORDER.index(heading) + 1:]
  return next(( positions[name] for name in tail if name in positions ), end)


def _insert_sections(body: str, blocks: dict[str, list[str]], lang: str) -> tuple[str, list[str]]:
  """
  Insert every canonical section the body lacks, leaving the present ones untouched.

  Nothing is moved, merged, or dropped: a section already on the note keeps its bytes and its
  place, and a section the roster does not know — an operator's own heading — stays where the
  operator put it.

  Args:
    body: The note body (post-frontmatter).
    blocks: The template's own section blocks, keyed by heading.
    lang: The vault's authoring language, for each inserted section's explainer line.

  Returns:
    A `(body, added)` pair — `added` names the headings inserted, in canonical order, and is
    empty when the body already carried the full roster.
  """
  lines = body.splitlines()
  positions = { line.strip(): idx for idx, line in enumerate(lines) if line.strip() in _SECTION_ORDER }
  missing = [ heading for heading in _SECTION_ORDER if heading not in positions ]
  # guard: the roster is already complete — the body is returned byte-identical
  if not missing:
    return body, []

  # group the insertions by anchor so several missing sections sharing one anchor land as a block
  plan: dict[int, list[str]] = {}
  for heading in missing:
    plan.setdefault(_anchor(heading, positions, len(lines)), []).extend(
        _rendered_block(blocks[heading], lang))

  # apply bottom-up, so every anchor still points at the line it was computed against; an
  # insertion never opens on the heels of the operator's last line — a blank separates them
  for anchor in sorted(plan, reverse = True):
    block = plan[anchor]
    if anchor > 0 and lines[anchor - 1].strip():
      block = [ "", *block ]
    lines[anchor:anchor] = block
  return "\n".join(lines) + "\n", missing


def _apply_keys(text: str, role: str, record: dict) -> tuple[str, list[str]]:
  """
  Add every managed frontmatter key the note lacks, rewriting none that it already carries.

  Args:
    text: The full note text.
    role: The level role the note carries.
    record: The owning product's settings record, empty for the catalog root.

  Returns:
    A `(text, added)` pair — `added` names the keys written, in write order.
  """
  fm, fm_end = flip_gate._parse_frontmatter(text)
  pairs = _managed_keys(role, record)
  # guard: no parseable frontmatter at all — the whole block is written from the managed set
  if fm_end == 0:
    block = "".join(f"{key}: {value}\n" for key, value in pairs)
    return f"---\n{block}---\n" + text, [ key for key, _value in pairs ]

  # an existing key is the operator's or another writer's — only the absent ones are filled in
  missing = [ pair for pair in pairs if pair[0] not in fm ]
  fm_text = text[:fm_end]
  for key, value in missing:
    fm_text = note_ops._set_fm_scalar(fm_text, key, value)
  return fm_text + text[fm_end:], [ key for key, _value in missing ]


def _append_history(text: str, added: list[str], today: str | None) -> str:
  """
  Record one dated audit line for the run under the note's `# History` section.

  Args:
    text: The full note text, its `# History` section already present.
    added: The keys and sections the run added; empty for a freshly created note.
    today: Optional ISO date pinned into the line.

  Returns:
    The note text carrying one more history line.
  """
  detail = f"added: {', '.join(added)}" if added else _Outcome.CREATED
  line = f"- {flip_gate._today(today)} — {_ACTOR} · backfill · {detail}"
  _fm, fm_end = flip_gate._parse_frontmatter(text)
  return text[:fm_end] + flip_gate._append_under_heading(text[fm_end:], Section.HISTORY, line)


def backfill(repo: Path, *, product: str | None, root: bool, today: str | None = None) -> dict:
  """
  Bring one level note up to the level schema, creating it when it is not there yet.

  Idempotent and additive: an existing note keeps every key and every section it already
  carries, byte-for-byte, and gains only what the schema names. A note that already conforms is
  not rewritten at all. Nothing is staged or committed — the caller owns the commit.

  Guarantees:
    - No frontmatter key, body section, or line is ever removed or rewritten: a run only inserts
      what the note lacks, so existing content survives byte-for-byte.
    - A run over a note that already carries the full schema writes nothing to disk and reports
      `unchanged`.

  Args:
    repo: The settings root holding `.claude/lazy.settings.json`.
    product: The product compound-key whose level note is the target, or None for the root form.
    root: True to target the catalog root note instead of a product's own.
    today: Optional ISO date pinned into the emitted history line.

  Returns:
    `{"outcome": "created" | "updated" | "unchanged", "note": <repo-relative path>,
    "added": [...]}` — `added` names the frontmatter keys and section headings the run inserted,
    and is empty for a created note and for an unchanged one.

  Raises:
    SystemExit: When the product form names an unregistered product, or no layer of the
      override chain carries the level-note template.
  """

  # Contract:
  # No frontmatter key, body section, or line is ever removed or rewritten: a run only inserts
  # what the note lacks, so existing content survives byte-for-byte.

  # Contract:
  # A run over a note that already carries the full schema writes nothing to disk and reports
  # `unchanged`.

  # which note this call names, the role it carries, and whether it is there yet
  note, role, record = _target(repo, product, root)
  created = not note.is_file()

  # a fresh note starts as the rendered template; an existing one starts as its own bytes
  seeded = _seed_text(repo, role, "" if root else (product or ""), record)
  text = seeded if created else note.read_text()
  lang = note_explainers.lang_for_note(note)

  # fill in the managed frontmatter, then the missing sections — the template supplies the shape
  text, added_keys = _apply_keys(text, role, record)
  _fm, fm_end = flip_gate._parse_frontmatter(text)
  body, added_sections = _insert_sections(text[fm_end:], _section_blocks(seeded), lang)
  text = text[:fm_end] + body
  added = added_keys + added_sections

  # guard: an existing note that owed nothing is left exactly as it was found
  if not created and not added:
    return { _Out.OUTCOME: _Outcome.UNCHANGED, _Out.NOTE: str(note.relative_to(repo)),
             _Out.ADDED: [] }

  # a created note is healed whole — there is no operator text its explainer pass could disturb
  if created:
    text = note_explainers.heal_note_text(note, text)
  note.parent.mkdir(parents = True, exist_ok = True)
  note.write_text(_append_history(text, added, today))
  return { _Out.OUTCOME: _Outcome.CREATED if created else _Outcome.UPDATED,
           _Out.NOTE: str(note.relative_to(repo)), _Out.ADDED: added }


def main(argv: list[str]) -> int:
  """
  Run the `catalog-note` subcommand from the command line, printing the result as JSON.

  Args:
    argv: Subcommand argv tail — `backfill (<product> | --root) [--today YYYY-MM-DD]`.

  Returns:
    Exit code: 0 on success, 2 when the call names both a product and the root, or neither.
  """
  parser = argparse.ArgumentParser(prog = _PROG)
  # waiver: argparse CLI signature -- positional argument names shown in --help / usage
  parser.add_argument(_ARG_VERB, choices = [ _VERB_BACKFILL ], help = _HELP_VERB)
  parser.add_argument(_ARG_PRODUCT, nargs = "?", default = None, help = _HELP_PRODUCT)
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument(_ARG_ROOT, action = "store_true", help = _HELP_ROOT)
  parser.add_argument(_ARG_TODAY, default = None, help = _HELP_TODAY)
  args = parser.parse_args(argv)

  # guard: the two target forms are exclusive — a call naming both or neither is never guessed
  if bool(args.product) == bool(args.root):
    sys.stderr.write(_ERR_TARGET)
    return 2

  # the verb runs against the repo the caller stands in, exactly like every sibling primitive
  result = backfill(scaffold_asset._repo_root(Path.cwd()), product = args.product,
                    root = args.root, today = args.today)
  print(json.dumps(result))
  return 0
