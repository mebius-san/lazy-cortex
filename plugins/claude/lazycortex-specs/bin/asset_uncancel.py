"""
Logic behind un-cancelling an asset — the `lazycortex-specs flip-gate <asset> spec_cancelled --off` call.

Clearing an asset's cancellation also returns every authored document of the asset that sits at `cancelled` to
`draft`, so the asset can take its ordinary path again: review, then approval. The documents move through the
stage primitive, so each one's `spec/<stage>` tag follows, and the cleared flag and the moved documents land in one
commit. Every other `flip-gate` call is handed to the gate-flip primitive unchanged.
"""
from __future__ import annotations

import argparse
import json
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
import set_stage  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import FlipResult, Gate, Stage  # noqa: E402


_MD_SUFFIX = ".md"
_STAGE_KEY = "spec_stage"

# waiver: the result's own wire-shape keys, read by the coordinator and the tests
_DRAFTED_KEY = "drafted"
_REFUSED_KEY = "refused"
_DOC_KEY = "doc"
_REASON_KEY = "reason"


def uncancel(asset_dir: Path, *, auto: bool = False, reason: str = "", today: str | None = None) -> dict:
  """
  Clear an asset's cancellation and return its cancelled documents to `draft`.

  Guarantees:
    - On a cancelled asset the cleared flag and every moved document land in one commit, when the asset is in a
      git repository.
    - A document whose move to `draft` is refused keeps its bytes and is reported in the result with its reason.
    - An asset that is not cancelled has no document moved.

  Notes:
    - Each moved document is rewritten in place and its `spec/<stage>` tag follows the new stage.
    - Only authored documents directly in the asset folder at `cancelled` are candidates; the status note never is.

  Args:
    asset_dir: The asset folder holding its status note `<asset_dir.name>.md`.
    auto: When True, mark the flip's run-log reason with an `auto:` prefix.
    reason: Optional note recorded in the flip's run log.
    today: Optional ISO date pinned into the flip's run log.

  Returns:
    The gate-flip result for `spec_cancelled` turned off, plus `"drafted"` — the file names of the documents moved
    to `draft`, sorted — and `"refused"` — one `{"doc", "reason"}` entry per document left where it was.
  """

  # Contract:
  # On a cancelled asset inside a git repository, the cleared flag and every document moved to `draft`
  # land in ONE commit.

  # Contract:
  # A document whose move to `draft` is refused keeps its bytes and is reported in the result with its reason.

  # Contract:
  # An asset that is not cancelled has NO document moved.

  # Domain(spec.lifecycle):
  # # Un-cancelling an asset
  # A cancelled asset can be taken back. Clearing its cancellation returns every one of its documents that was
  # abandoned with it to draft, so the asset walks its ordinary path again: each document is reviewed, then
  # approved. Until then the asset refuses every checkpoint move but the clearing itself. A document that cannot be
  # moved stays where it is and is named, never guessed at. Clearing the flag on an asset that was never cancelled
  # moves nothing — a single document cancelled on a live asset stays cancelled.

  note = asset_dir / f"{asset_dir.name}.md"
  fm_values, _end = spec_frontmatter.parse(spec_paths.read_text(note))
  drafted: list[str] = []
  refused: list[dict] = []
  touched: list[Path] = []

  # only a cancelled asset has documents abandoned with it to bring back
  if flip_gate.is_true(fm_values, Gate.SPEC_CANCELLED):
    for doc in _cancelled_docs(asset_dir, note):
      result = set_stage.apply_stage(doc, Stage.DRAFT)
      if result.status == set_stage.StageStatus.REFUSED:
        refused.append({ _DOC_KEY: doc.name, _REASON_KEY: result.reason or "" })
        continue
      drafted.append(doc.name)
      touched.extend(Path(path) for path in result.touched_paths)

  # the cleared flag carries the moved documents into the flip's own commit
  flipped = flip_gate.flip_gate(asset_dir, Gate.SPEC_CANCELLED, off = True, auto = auto, reason = reason,
                                today = today, extra_paths = touched)
  return { **flipped, _DRAFTED_KEY: sorted(drafted), _REFUSED_KEY: refused }


def _cancelled_docs(asset_dir: Path, note: Path) -> list[Path]:
  """
  List the markdown documents directly in an asset folder that sit at `cancelled`.

  Args:
    asset_dir: The asset folder.
    note: The asset's status note, never a candidate.

  Returns:
    The documents whose frontmatter carries `spec_stage: cancelled`, sorted by name.
  """
  # every markdown file in the folder itself, the status note aside, whose stage reads cancelled
  docs: list[Path] = []
  for path in sorted(asset_dir.iterdir()):

    # guard: only a markdown file other than the status note is an authored document
    if not path.is_file() or path.suffix != _MD_SUFFIX or path == note:
      continue
    values, _end = spec_frontmatter.parse(spec_paths.read_text(path))
    if values.get(_STAGE_KEY, "").strip() == Stage.CANCELLED:
      docs.append(path)
  return docs


def main(argv: list[str]) -> int:
  """
  Run the `flip-gate` verb: un-cancel on `spec_cancelled --off`, otherwise flip through the gate primitive.

  Args:
    argv: The `flip-gate` arguments, excluding the program name, exactly as the gate primitive takes them.

  Returns:
    Exit code: 0 when the un-cancel flipped, 1 when it was refused, 2 when the asset note is missing; every other
    call returns the gate primitive's own exit code.
  """
  # only the un-cancel shape is taken here; the parse never fails on the primitive's other options
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs flip-gate", add_help = False)
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_dir", nargs = "?", type = Path)
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("gate", nargs = "?", default = None)
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--off", action = "store_true")
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--auto", action = "store_true")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--reason", default = "")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--halt", default = None)
  args, extra = parser.parse_known_args(argv)

  # guard: anything but a plain un-cancel is the gate primitive's own call
  if extra or args.halt is not None or args.asset_dir is None or args.gate != Gate.SPEC_CANCELLED or not args.off:
    return flip_gate.main(argv)
  asset_dir: Path = args.asset_dir.resolve()

  # guard: the asset's status note must exist
  if not (asset_dir / f"{asset_dir.name}.md").is_file():
    return flip_gate.main(argv)

  # the un-cancel's result goes to stdout whole
  result = uncancel(asset_dir, auto = args.auto, reason = args.reason)
  print(json.dumps(result))
  return 0 if result[FlipResult.STATUS] == FlipResult.FLIPPED else 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
