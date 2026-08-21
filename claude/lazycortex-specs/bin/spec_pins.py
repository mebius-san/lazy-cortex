"""
One-shot `wiki_pinned_topics` backfill — the `pins` CLI subcommand.

Templates write `wiki_pinned_topics` frontmatter on every freshly-scaffolded role-bearing
document (`lazy-spec.layout-protocol`'s closed `spec_role` set minus `request`, which is never
pinned — its frontmatter comes from a worker, not a template). Files created before the pin
landed in a template — or created from a per-product / per-category override the plugin update
never touches — carry no pin. This module walks the spec content-root once, adds the pin to
every role-bearing document missing it, and reports the count touched. Idempotent: a document
that already carries `wiki_pinned_topics` is left alone. Never commits — the caller owns that,
per `dev.plugin-boundaries.md`'s no-silent-side-effects convention for a one-shot primitive.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

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
import flip_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_decisions  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402


# ----------------------------------------------------------------------------------------
class _K:
  """
  String constants used by the `pins` backfill primitive.

  Attributes:
    SPEC_ROLE: Frontmatter key naming a doc's role.
    WIKI_PINNED_TOPICS: Frontmatter key the pin block is written under.
    TOUCHED: Result-dict key counting documents a pin was added to.
    SKIPPED: Result-dict key counting role-bearing documents left untouched.
    MD_SUFFIX: Markdown file extension, used to filter the content-root walk.
    ENCODING: File encoding used throughout this module.
    ARG_CWD: CLI flag overriding the repository root.
    ARG_CWD_HELP: CLI help text for `--cwd`.
    PROG: CLI program name shown in `--help` output.
    ENV_REPO_ROOT: Env var naming the repository root, read when `--cwd` is not passed.
  """

  SPEC_ROLE = "spec_role"
  WIKI_PINNED_TOPICS = "wiki_pinned_topics"
  TOUCHED = "touched"
  SKIPPED = "skipped"
  MD_SUFFIX = ".md"
  ENCODING = "utf-8"
  ARG_CWD = "--cwd"
  ARG_CWD_HELP = "Repository root (defaults to $LAZY_REPO_ROOT or cwd)."
  PROG = "lazycortex-specs pins"
  ENV_REPO_ROOT = "LAZY_REPO_ROOT"


# The closed `spec_role` set (`lazy-spec.layout-protocol.md`) minus `request` — a request's
# frontmatter is worker-written, never template-rendered, and never carries a wiki pin. The
# doc-kind axis value is the role name itself, verbatim (spec-decisions-design.md § on the
# doc-kind axis / how specs get their wiki pins) — no per-role remapping.
_PIN_ROLES = frozenset({
    "design", "architecture", "code-plan", "code-report", "test-plan", "test-report",
    "bug", "tech", "status", "decisions",
})

_SPEC_ROLE_LINE_RE = re.compile(r"(?m)^spec_role:\s*(\S+)\s*$")


def _pin_block(role: str, product: str, category: str | None) -> str:
  """
  Render the `wiki_pinned_topics` YAML block for one document.

  Args:
    role: The document's `spec_role` value; becomes the `doc-kind` pin verbatim.
    product: The owning product's settings-dict key.
    category: The owning asset's singular category axis value, or `None` at product level
      (no category pin — a product document has no category).

  Returns:
    The block's lines, joined, with no leading/trailing newline.
  """
  lines = [f"{_K.WIKI_PINNED_TOPICS}:", f"  - wiki/doc-kind/{role}", f"  - wiki/product/{product}"]
  if category is not None:
    lines.append(f"  - wiki/category/{category}")
  return "\n".join(lines)


def _insert_pin(fm_text: str, role: str, product: str, category: str | None) -> str:
  """
  Insert the pin block into a frontmatter slice, right after its `spec_role:` line.

  Mirrors the placement every role-bearing template already uses, so a backfilled document's
  frontmatter reads identically to one that was pinned at scaffold time.

  Args:
    fm_text: The document's frontmatter text (opening/closing `---` fences included).
    role: The document's `spec_role` value.
    product: The owning product's settings-dict key.
    category: The owning asset's singular category axis value, or `None` at product level.

  Returns:
    The updated frontmatter text, or `fm_text` unchanged when no `spec_role: <role>` line could
    be located (a malformed document `lazy-spec.doctor` would already be flagging separately).
  """
  block = _pin_block(role, product, category)
  new_text, count = _SPEC_ROLE_LINE_RE.subn(lambda m: m.group(0) + "\n" + block, fm_text, count = 1)
  return new_text if count == 1 else fm_text


def backfill(repo: Path) -> dict:
  """
  Walk the spec content-root and add `wiki_pinned_topics` to every document missing it.

  Every `.md` file under the content-root is read once; a file with no `spec_role`, or one
  outside the closed pin-eligible set (`request` above all — see `_PIN_ROLES`), is not a
  candidate and is not counted at all. Among candidates, one already carrying
  `wiki_pinned_topics` is left untouched and counted `skipped`; a candidate whose parent
  directory resolves to no registered product (the same product/asset context resolution the
  `decide` primitive uses, raising `ValueError`) is also `skipped` — nothing to pin against.

  Args:
    repo: Absolute repository root (holds `.claude/lazy.settings.json`).

  Returns:
    `{"touched": N, "skipped": M}` — `N` documents gained the pin, `M` role-bearing documents
    were left alone (already pinned, or unresolvable to a product).
  """
  settings_root = spec_paths.find_settings_root(repo)
  content_root = spec_paths.spec_content_root(settings_root)
  touched = 0
  skipped = 0
  for dirpath, _dirnames, filenames in os.walk(content_root):
    for name in filenames:
      # guard: only markdown files can carry spec_role frontmatter
      if not name.endswith(_K.MD_SUFFIX):
        continue
      path = Path(dirpath) / name
      text = path.read_text(encoding = _K.ENCODING)
      fm_values, fm_end = flip_gate._parse_frontmatter(text)
      role = fm_values.get(_K.SPEC_ROLE, "")
      # guard: not a role-bearing document this primitive pins (includes `request` and group-notes)
      if role not in _PIN_ROLES:
        continue
      # guard: already pinned — idempotent no-op
      if _K.WIKI_PINNED_TOPICS in fm_values:
        skipped += 1
        continue
      try:
        ctx = spec_decisions._resolve_context(path)
      except ValueError:
        # guard: parent directory covered by no registered product — nothing to pin against
        skipped += 1
        continue
      fm_text = text[:fm_end]
      new_fm = _insert_pin(fm_text, role, ctx.product, ctx.category)
      # guard: the spec_role line could not be located for insertion — treat as skipped, not a crash
      if new_fm == fm_text:
        skipped += 1
        continue
      path.write_text(new_fm + text[fm_end:], encoding = _K.ENCODING)
      touched += 1
  return { _K.TOUCHED: touched, _K.SKIPPED: skipped }


def main(argv: list[str]) -> int:
  """
  Run the `pins` subcommand: backfill `wiki_pinned_topics` across the spec catalog.

  Args:
    argv: Subcommand argv tail (only the optional `--cwd` flag).

  Returns:
    Process exit code: always `0`.
  """
  parser = argparse.ArgumentParser(prog = _K.PROG)
  parser.add_argument(_K.ARG_CWD, default = None, help = _K.ARG_CWD_HELP)
  args = parser.parse_args(argv)

  # resolve the repo the same way every other lazycortex-specs subcommand does: explicit flag,
  # then the daemon-exported env var, then cwd
  repo_raw = args.cwd or os.environ.get(_K.ENV_REPO_ROOT) or os.getcwd()
  repo = Path(repo_raw).resolve()
  result = backfill(repo)
  print(json.dumps(result))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
