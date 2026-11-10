"""
One-shot `wiki_pinned_topics` backfill — the `pins` CLI subcommand.

Templates write `wiki_pinned_topics` frontmatter on every freshly-scaffolded role-bearing
document (`lazy-spec.layout-protocol`'s closed `spec_role` set minus the two LEVEL-note roles
`product` and `catalog`, whose shared `level-note.md` template ships no `wiki_pinned_topics`
block; `request` sits outside the closed set entirely, its frontmatter worker-written rather
than template-rendered). Files created before the pin landed in a template — or created from a
per-product / per-category override the plugin update never touches — carry no pin. This module
walks the spec content-root once, adds the pin to every role-bearing document missing it, and
reports the count touched. It also repairs a document relocated into a nested product that still
carries the enclosing product's tag and `wiki/product/` pin, and migrates an older-form product tag
(the owner's or an enclosing product's bare leaf, or `product/<leaf>`) to the `product/<spec_path>` form.
Idempotent: a document whose pin and product values are already right is left alone. Never commits —
the caller owns that, per `dev.plugin-boundaries.md`'s no-silent-side-effects convention for a one-shot primitive.
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
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_decisions  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Every role of the closed `spec_role` set (`lazy-spec.layout-protocol.md`) whose document is
# template-rendered with a `wiki_pinned_topics` block — the roles a lost pin can be restored to.
# Excluded are the two LEVEL-note roles `product` and `catalog`: their shared `level-note.md`
# template carries no pin block, so a level note has none to backfill. `request` is excluded for
# a different reason — it is not in the closed set at all, and its frontmatter is worker-written
# rather than template-rendered. The doc-kind axis value is the role name itself, verbatim
# (spec-decisions-design.md § on the doc-kind axis / how specs get their wiki pins) — no
# per-role remapping.
_PIN_ROLES = frozenset({
    "vision", "use-cases", "design", "architecture", "ui-design", "code-plan", "code-report",
    "test-plan", "test-report", "bug", "tech", "status", "decisions", "research",
})

_SPEC_ROLE_LINE_RE = re.compile(r"(?m)^spec_role:\s*(\S+)(?:[ \t]+#.*)?\s*$")

# top-level frontmatter key at the start of a line
_FM_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:")


# ----------------------------------------------------------------------------------------
class Keys:
  """
  String constants used by the `pins` backfill primitive.

  Attributes:
    SPEC_ROLE: Frontmatter key naming a doc's role.
    TAGS: Frontmatter key holding the doc's tags, the product tag among them.
    SPEC_PATH: Product-record key naming the product's folder under the content-root.
    PRODUCT_PIN: Prefix of the product-axis pin value.
    WIKI_PINNED_TOPICS: Frontmatter key the pin block is written under.
    TOUCHED: Result-dict key counting documents a pin was added to or whose stale product values were repaired.
    SKIPPED: Result-dict key counting role-bearing documents left untouched.
    MD_SUFFIX: Markdown file extension, used to filter the content-root walk.
    ENCODING: File encoding used throughout this module.
    ARG_CWD: CLI flag overriding the repository root.
    ARG_CWD_HELP: CLI help text for `--cwd`.
    ARG_CHECK: CLI flag that reports without writing and answers through the exit code.
    ARG_CHECK_HELP: CLI help text for `--check`.
    EXIT_FAILED: Exit code of a failed run, told apart from both `--check` answers.
    PROG: CLI program name shown in `--help` output.
    ENV_REPO_ROOT: Env var naming the repository root, read when `--cwd` is not passed.
  """

  # Frontmatter key naming a doc's role.
  SPEC_ROLE = "spec_role"
  # Frontmatter key holding the doc's tags, the product tag among them.
  TAGS = "tags"
  # Product-record key naming the product's folder under the content-root.
  SPEC_PATH = "spec_path"
  # Prefix of the product-axis pin value.
  PRODUCT_PIN = "wiki/product/"
  # Frontmatter key the pin block is written under.
  WIKI_PINNED_TOPICS = "wiki_pinned_topics"
  # Result-dict key counting documents a pin was added to or whose stale product values were repaired.
  TOUCHED = "touched"
  # Result-dict key counting role-bearing documents left untouched.
  SKIPPED = "skipped"
  # Markdown file extension, used to filter the content-root walk.
  MD_SUFFIX = ".md"
  # File encoding used throughout this module.
  ENCODING = "utf-8"
  # CLI flag overriding the repository root.
  ARG_CWD = "--cwd"
  # CLI help text for `--cwd`.
  ARG_CWD_HELP = "Repository root (defaults to $LAZY_REPO_ROOT or cwd)."
  # CLI flag that reports without writing and answers through the exit code.
  ARG_CHECK = "--check"
  # CLI help text for `--check`.
  ARG_CHECK_HELP = "Write nothing; exit 0 when a document would change, 1 when none would, 2 on failure."
  # Exit code of a failed run, told apart from both `--check` answers.
  EXIT_FAILED = 2
  # CLI program name shown in `--help` output.
  PROG = "lazycortex-specs pins"
  # Env var naming the repository root, read when `--cwd` is not passed.
  ENV_REPO_ROOT = "LAZY_REPO_ROOT"


def _pin_block(role: str, product: str | None, category: str | None) -> str:
  """
  Render the `wiki_pinned_topics` YAML block for one document.

  Args:
    role: The document's `spec_role` value; becomes the `doc-kind` pin verbatim.
    product: The owning product's settings-dict key, or `None` at project level (no product
      pin — a content-root document belongs to no product).
    category: The owning asset's singular category axis value, or `None` at product and
      project level (no category pin — such a document has no category).

  Returns:
    The block's lines, joined, with no leading/trailing newline.
  """
  lines = [f"{Keys.WIKI_PINNED_TOPICS}:", f"  - wiki/doc-kind/{role}"]

  # a project-level document sits above every product — only lower levels carry the axis pins
  if product is not None:
    lines.append(f"  - wiki/product/{product}")
  if category is not None:
    lines.append(f"  - wiki/category/{category}")
  return "\n".join(lines)


def _insert_pin(fm_text: str, role: str, product: str | None, category: str | None) -> str:
  """
  Insert the pin block into a frontmatter slice, right after its `spec_role:` line.

  Mirrors the placement every role-bearing template already uses, so a backfilled document's
  frontmatter reads identically to one that was pinned at scaffold time.

  Args:
    fm_text: The document's frontmatter text (opening/closing `---` fences included).
    role: The document's `spec_role` value.
    product: The owning product's settings-dict key, or `None` at project level.
    category: The owning asset's singular category axis value, or `None` at product and
      project level.

  Returns:
    The updated frontmatter text, or `fm_text` unchanged when no `spec_role: <role>` line could
    be located (a malformed document `lazy-spec.audit` would already be flagging separately).
  """
  block = _pin_block(role, product, category)
  new_text, count = _SPEC_ROLE_LINE_RE.subn(lambda m: m.group(0) + "\n" + block, fm_text, count = 1)
  return new_text if count == 1 else fm_text


def _repair_owner(fm_text: str, products: dict, product: str | None) -> str:
  """
  Rewrite an enclosing product's tag and product pin, and any older-form product tag, to the owner's own.

  An older-form tag — the owner's or an enclosing product's bare leaf, or `product/<leaf>` — is rewritten
  like a stale enclosing value; the current form is `product/<spec_path>`. Only block-form lists are read.

  Args:
    fm_text: The document's frontmatter text.
    products: The products registry.
    product: The owning product's key, or `None` at project level.

  Returns:
    The repaired frontmatter text, or `fm_text` unchanged when nothing was stale.
  """

  # Domain(spec.config):
  # # Innermost product owns a nested document
  # A document inside a nested product's tree belongs to the innermost product covering it, not to an enclosing one.
  # Its tag is `product/` plus that product's own whole tree path and its product pin names that product,
  # so the values of any enclosing product are stale for it. A document relocated into a nested product
  # keeps the old enclosing values until repaired: each is replaced by the innermost owner's value,
  # or dropped when the owner's value is already listed. The older tag forms — the bare last segment of a
  # tree path, and `product/` plus that last segment alone, the owner's own or an enclosing product's —
  # are stale the same way.

  record = products.get(product) if product is not None else None

  # guard: project level, or an owner with no usable spec_path — no product values to repair
  if product is None or not isinstance(record, dict) or not isinstance(record.get(Keys.SPEC_PATH), str):
    return fm_text

  # the owner's own values, and the values the owner and every enclosing product wrote in the current or an
  # older tag form; one equal to the owner's own current value (a top-level product's `product/<leaf>`)
  # is correct, never stale
  ancestor_keys = resolve_product.ancestor_chain(Path("."), product, products = products)
  own = { Keys.TAGS: scaffold_asset.product_tag(record), Keys.WIKI_PINNED_TOPICS: f"{Keys.PRODUCT_PIN}{product}" }
  stale = { Keys.TAGS: { scaffold_asset.product_tag(products[key]) for key in ancestor_keys },
            Keys.WIKI_PINNED_TOPICS: { f"{Keys.PRODUCT_PIN}{key}" for key in ancestor_keys } }
  for leaf in { scaffold_asset.product_leaf(products[key]) for key in [ product, *ancestor_keys ] }:
    stale[Keys.TAGS].update({ leaf, f"{scaffold_asset.Keys.PRODUCT_TAG_PREFIX}{leaf}" })
  for axis, value in own.items():
    stale[axis].discard(value)

  # tag each list item with the top-level key it sits under
  lines = fm_text.splitlines(keepends = True)
  items: list[tuple[str, str | None]] = []
  key = ""
  for line in lines:
    if (head := _FM_KEY_RE.match(line)):
      key = head.group(1)
    items.append((key, line[4:].strip().strip("\"'") if line.startswith("  - ") else None))

  # a stale item becomes the owner's value, or drops when the owner's value is already listed
  out: list[str] = []
  written: set[str] = set()
  for line, (key, item) in zip(lines, items, strict = True):
    if item is None or key not in stale or item not in stale[key]:
      out.append(line)
    elif (key, own[key]) not in items and key not in written:
      out.append(f"  - {own[key]}\n")
      written.add(key)
  return "".join(out)


def backfill(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Walk the spec content-root, add `wiki_pinned_topics` where missing, and repair stale product values.

  Every `.md` file under the content-root is read once; a file with no `spec_role`, or one
  outside the closed pin-eligible set (`request` above all — see `_PIN_ROLES`), is not a
  candidate and is not counted at all. A candidate missing the pin gains it; a candidate inside
  a nested product still carrying an enclosing product's tag or `wiki/product/` pin has both
  rewritten to the owning product's, and an older-form product tag becomes the owner's
  `product/<spec_path>`. A candidate needing none of these is left untouched and counted
  `skipped`; so is one whose parent directory resolves to no registered product (the same
  product/asset context resolution the `decide` primitive uses, raising `ValueError`).

  Guarantees:
    - A dry run writes no file and reports the same counts a real run would.

  Args:
    repo: Absolute repository root (holds `.claude/lazy.settings.json`).
    dry_run: When True, count what would change and write nothing.

  Returns:
    `{"touched": N, "skipped": M}` — `N` documents gained (or would gain) the pin or had stale product
    values repaired, `M` role-bearing documents were left alone (already correct, or unresolvable).
  """

  # Contract:
  # A dry run MUST write no file and MUST report the same counts a real run over the same tree would, so
  # `--check` answers exactly whether a real run has work.

  settings_root = spec_paths.find_settings_root(repo)
  products = resolve_product.load_products(settings_root)
  touched = 0
  skipped = 0
  for dirpath, _dirnames, filenames in os.walk(spec_paths.spec_content_root(settings_root)):
    for name in filenames:
      # guard: only markdown files can carry spec_role frontmatter
      if not name.endswith(Keys.MD_SUFFIX):
        continue
      path = Path(dirpath) / name
      text = spec_paths.read_text(path)
      fm_values, fm_end = flip_gate.parse_frontmatter(text)
      role = fm_values.get(Keys.SPEC_ROLE, "")

      # guard: not a role-bearing document this primitive pins (includes `request` and group-notes)
      if role not in _PIN_ROLES:
        continue

      # a missing pin is inserted against the doc's resolved placement; an unresolvable doc gets none
      fm_text = text[:fm_end]
      new_fm = fm_text
      if Keys.WIKI_PINNED_TOPICS not in fm_values:
        try:
          ctx = spec_decisions.resolve_context(path)
          new_fm = _insert_pin(fm_text, role, ctx.product, ctx.category)
        except ValueError:
          # covered by no registered product — nothing to pin against, the doc stays as is
          pass

      # an enclosing product's tag or pin left behind by a relocation, or an older-form product tag, becomes
      # the innermost owner's, attributed from the document's repo-relative path
      new_fm = _repair_owner(new_fm, products, resolve_product.resolve_product_by_path(
          settings_root, path.relative_to(settings_root).as_posix(), products = products)[0])

      # guard: already correct, unresolvable, or the spec_role line could not be located — skipped
      if new_fm == fm_text:
        skipped += 1
        continue

      # a dry run only counts the document it would rewrite
      if not dry_run:
        spec_paths.write_text_atomic(path, new_fm + text[fm_end:])
      touched += 1
  return { Keys.TOUCHED: touched, Keys.SKIPPED: skipped }


def main(argv: list[str]) -> int:
  """
  Run the `pins` subcommand: backfill `wiki_pinned_topics` and repair stale product values across the spec catalog.

  Guarantees:
    - With `--check`, writes nothing and exits 0 when at least one document would change, 1 when none would.
    - Any failure exits 2 under every flag and prints no result, never an answer `--check` gives.

  Args:
    argv: Subcommand argv tail: the optional `--cwd` flag, and `--check`, which reports without writing and
      answers through the exit code whether anything is left to do.

  Returns:
    Process exit code: with `--check`, 0 when a document would change and 1 when none would; 0 otherwise; 2 on
    any failure.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed; also told apart from both `--check` answers.
  """

  # Contract:
  # With `--check` the verb MUST write nothing and exit 0 when at least one document would change, 1 when none
  # would; any failure MUST exit 2, so a migration step's `applies_when` predicate never reads a failure as an answer.

  parser = argparse.ArgumentParser(prog = Keys.PROG)
  parser.add_argument(Keys.ARG_CWD, default = None, help = Keys.ARG_CWD_HELP)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument(Keys.ARG_CHECK, action = "store_true", help = Keys.ARG_CHECK_HELP)
  args = parser.parse_args(argv)

  # resolve the repo the same way every other lazycortex-specs subcommand does: explicit flag,
  # then the daemon-exported env var, then cwd
  repo_raw = args.cwd or os.environ.get(Keys.ENV_REPO_ROOT) or os.getcwd()

  # a check runs dry; any failure exits 2, so no flag ever reads a failure as an answer
  try:
    result = backfill(Path(repo_raw).resolve(), dry_run = args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    sys.stderr.write(f"{Keys.PROG}: {error!r}\n")
    return Keys.EXIT_FAILED

  # the result goes to stdout for the caller to read
  print(json.dumps(result))

  # only a check answers through its exit code
  if args.check:
    return 0 if result[Keys.TOUCHED] else 1
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
