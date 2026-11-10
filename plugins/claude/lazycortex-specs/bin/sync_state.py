from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
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
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The tracked state corner and the checkpoint file names, current and pre-convention.
_STATE_DIR = ".state"
_FILE_TEMPLATE = "lazy-spec.sync-{key}.json"
_LEGACY_TEMPLATE = "spec-sync-{key}.json"

# The checkpoint's keys, in the order they are written.
LAST_COMMIT = "last_commit"
LAST_SYNC = "last_sync"
SOURCE_PATHS = "source_paths"

# The product record's code binding.
_SOURCE = "source"
_PATHS = "paths"

# The refusal reasons.
REASON_UNKNOWN = "unknown-product"
REASON_DESIGN_ONLY = "design-only"
REASON_NO_HEAD = "no-head"

# The verb's actions.
_ACTION_READ = "read"
_ACTION_WRITE = "write"

# The verb's output keys and status word.
_PRODUCT = "product"
_PATH = "path"
_CHECKPOINT = "checkpoint"
_RENAMED_FROM = "renamed_from"
_TOUCHED = "touched_paths"
_STATUS = "status"
_REASON = "reason"
_REFUSED = "refused"

# The JSON indent of the checkpoint file.
_INDENT = 2

# The verb's exit codes.
_EXIT_OK = 0
_EXIT_REFUSED = 1


# ----------------------------------------------------------------------------------------
class SyncStateRefusedError(Exception):
  """
  Refusal of a sync checkpoint read or write for a product.

  Attributes:
    reason: The refusal reason word: `unknown-product` when the settings `products` hold no record for the key,
      `design-only` when the record has no `source` block, `no-head` when there is no commit to record.
  """

  def __init__(self, reason: str) -> None:
    # the exception's own message is the reason itself
    super().__init__(reason)

    # the reason, kept for callers that report it without parsing the message
    self.reason: str = reason


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class CheckpointRead:
  """
  Outcome of reading one product's sync checkpoint.

  Attributes:
    path: The absolute path of the product's current checkpoint file.
    checkpoint: The parsed checkpoint content, or none when the file does not exist.
    renamed_from: The absolute pre-convention path this read renamed onto the current name, or none when no rename
      happened.
  """

  path: str
  checkpoint: dict | None
  renamed_from: str | None


def _require_source_paths(repo: Path, product: str) -> list[str]:
  """
  Return the code paths bound to a code-bound product.

  Args:
    repo: The repository root holding the settings.
    product: The product key.

  Returns:
    The string entries of the product record's source paths, in record order.

  Raises:
    SyncStateRefusedError: If the product has no record, or its record has no code binding.
  """
  record = resolve_product.resolve_product_by_key(repo, product)

  # guard: an unregistered product has no checkpoint to keep
  if not isinstance(record, dict):
    raise SyncStateRefusedError(REASON_UNKNOWN)

  # the product's code binding, when it has one
  source = record.get(_SOURCE)

  # guard: a product with no code binding has nothing to sync against
  if not isinstance(source, dict):
    raise SyncStateRefusedError(REASON_DESIGN_ONLY)
  return [ path for path in source.get(_PATHS) or [] if isinstance(path, str) ]


def _state_path(repo: Path, template: str, product: str) -> Path:
  """
  Return the tracked-state path of a product's checkpoint file under a given file name pattern.

  Args:
    repo: The repository root.
    template: The checkpoint file name pattern, with the product key as its placeholder.
    product: The product key.

  Returns:
    The path of the checkpoint file in the repository's tracked state directory.
  """
  return repo / _STATE_DIR / template.format(key = product)


def load_migrated_checkpoint(repo: Path, product: str) -> CheckpointRead:
  """
  Read a code-bound product's sync checkpoint.

  Guarantees:
    - A leftover under the retired pre-convention name is moved onto the current name with its content unchanged, so
      the product never holds two checkpoint files.

  Notes:
    - Renames the pre-convention file when only that file exists; never commits.

  Args:
    repo: The repository root holding the settings.
    product: The product key.

  Returns:
    The current checkpoint path, its parsed content or none when absent, and the old path when this read renamed it.

  Raises:
    SyncStateRefusedError: If the product has no record, or its record has no code binding.
  """

  # Contract:
  # A checkpoint left under the retired pre-convention name is moved onto the current name
  # with its content unchanged, so the product never holds two checkpoint files.

  # the record is checked first, only for the refusal it raises; the source paths themselves are not needed here
  _require_source_paths(repo, product)

  # the current and the pre-convention checkpoint paths
  path = _state_path(repo, _FILE_TEMPLATE, product)
  legacy = _state_path(repo, _LEGACY_TEMPLATE, product)

  # a pre-convention leftover moves onto the current name before it is read
  renamed_from = None
  if not path.is_file() and legacy.is_file():
    os.replace(legacy, path)
    renamed_from = str(legacy)

  # an absent checkpoint reads as none; a present one is its parsed JSON
  checkpoint = json.loads(spec_paths.read_text(path)) if path.is_file() else None
  return CheckpointRead(path = str(path), checkpoint = checkpoint, renamed_from = renamed_from)


def write_checkpoint(repo: Path, product: str, *, head: str | None = None, today: str | None = None) -> list[str]:
  """
  Record the current sync point of a code-bound product in its checkpoint file.

  Guarantees:
    - The whole file is rewritten with its keys in a fixed order and a trailing newline, so equal inputs give a
      byte-identical file.
    - Afterwards the checkpoint exists only under the current name; a file under the retired pre-convention name is
      never left beside it.

  Notes:
    - Writes the checkpoint file only; never commits, so the caller folds the returned paths into its own commit.

  Args:
    repo: The repository root holding the settings.
    product: The product key.
    head: The commit to record; the repository's current HEAD when omitted.
    today: The sync date as `YYYY-MM-DD`; the current UTC date when omitted.

  Returns:
    The paths the caller's commit must carry: the checkpoint path first, then the retired path when it is gone from
    disk but git still tracks it.

  Raises:
    SyncStateRefusedError: If the product has no record, its record has no code binding, or no commit is given and
      HEAD cannot be read.
  """

  # Contract:
  # The whole checkpoint file is rewritten with its keys in a fixed order and a trailing newline,
  # so equal inputs always give a byte-identical file in the tracked state directory.

  # Contract:
  # After a write the product's checkpoint exists only under the current name;
  # a file under the retired pre-convention name is never left beside it.

  # the record's code binding is checked before anything is written
  source_paths = _require_source_paths(repo, product)
  commit = head or flip_gate.git_field(repo, [ "rev-parse", "HEAD" ], "")

  # guard: a checkpoint without a commit would make the next run's window meaningless
  if not commit:
    raise SyncStateRefusedError(REASON_NO_HEAD)

  # the read renames a pre-convention leftover onto the current name first
  read = load_migrated_checkpoint(repo, product)

  # the whole file is rewritten from the record and HEAD, keys in a fixed order
  data = { LAST_COMMIT: commit, LAST_SYNC: flip_gate.effective_today(today), SOURCE_PATHS: source_paths }
  path = Path(read.path)
  path.parent.mkdir(parents = True, exist_ok = True)
  spec_paths.write_text_atomic(path, json.dumps(data, indent = _INDENT, ensure_ascii = False) + "\n")

  # the renamed-away file rides the commit while git still tracks it, so its deletion lands too
  legacy = _state_path(repo, _LEGACY_TEMPLATE, product)
  touched = [ read.path ]
  if not legacy.exists() and flip_gate.git_field(
      repo, [ "ls-files", "--error-unmatch", "--", str(legacy.relative_to(repo)) ], ""):
    touched.append(str(legacy))
  return touched


def _refusal(product: str, reason: str) -> dict:
  """
  Build the JSON-ready payload that reports a refusal.

  Args:
    product: The product key the refusal concerns.
    reason: The refusal reason word.

  Returns:
    The mapping printed for a refused action, carrying the refused status, the reason, and the product.
  """
  return { _STATUS: _REFUSED, _REASON: reason, _PRODUCT: product }


def main(argv: list[str]) -> int:
  """
  Run the `sync-state` verb: read or write a product's sync checkpoint and print one JSON line.

  Notes:
    - `read <product>` prints `product`, `path`, `checkpoint` and `renamed_from`.
    - `write <product> [--head SHA] [--today YYYY-MM-DD]` prints `product`, `path` and `touched_paths`.
    - A refusal prints `status` `refused` with `reason` and `product`; the repository is the settings root found from
      the current directory.
    - Never commits.

  Args:
    argv: The command-line arguments after the verb name.

  Returns:
    Exit code 0 on success, 1 when the action was refused; an argument error exits with code 2.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs sync-state")
  # waiver: argparse CLI signature -- positional argument names and choices
  parser.add_argument("action", choices = [ _ACTION_READ, _ACTION_WRITE ])
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("product")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--head", default = None)
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--today", default = None)
  args = parser.parse_args(argv)
  repo = spec_paths.find_settings_root(Path.cwd())

  # one JSON line per action; a refusal is printed and carried by the exit code
  try:
    if args.action == _ACTION_READ:
      read = load_migrated_checkpoint(repo, args.product)
      out = { _PRODUCT: args.product, _PATH: read.path, _CHECKPOINT: read.checkpoint,
              _RENAMED_FROM: read.renamed_from }
    else:
      touched = write_checkpoint(repo, args.product, head = args.head, today = args.today)
      out = { _PRODUCT: args.product, _PATH: touched[0], _TOUCHED: touched }
  except SyncStateRefusedError as refused:
    print(json.dumps(_refusal(args.product, refused.reason), ensure_ascii = False))
    return _EXIT_REFUSED
  print(json.dumps(out, ensure_ascii = False))
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
