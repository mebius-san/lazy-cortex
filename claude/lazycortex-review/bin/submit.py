"""`/lazy-review.submit <file> [--expert <name>]` — open a document
for review skipping the opening main-writer round.

Same bootstrap as `start` (`review_active: true`, `review_round: 1`,
`review_approved: false`, Waiting banner, `review_result` cleared),
plus a skip-seed: `review_main_done` is pre-filled with every main
writer of the document and `review_phase` is set to `main`. The
dispatcher then computes an empty main-pending set, so the opening writer
round never runs and the document lands on the operator's Ready banner
(see the dispatch_state submit branch).

`--expert` (optional) writes `review_expert` — a per-document
override of the class `experts.main` honoured by the dispatcher. When
given, the seeded writer set is `[expert]`; otherwise it is the class's
`experts.main` list, resolved from `.claude/lazy.settings.json`.

The commit is made under the OPERATOR's git identity (no Doc-Review
trailer) so the dispatcher's next tick sees a human commit.

Returns 0 on success, 2 when the file is not a markdown file, 3 when an
`--expert` is given that is not in the global experts table, 4 when the
file matches no configured review class (and no `--expert` given to
seed from).
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# deferred imports below module code; position intentional (ruff E402 noqa guards it)
# pylint: disable=import-error,wrong-import-position

import argparse
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

import frontmatter as _fm  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from keys import Bucket, JobKey, Phase, ReviewKey, Trailer  # noqa: E402
# waiver: deferred sibling imports follow the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import start as _start  # noqa: E402


def open_submit(
    file_path: Path,
    *,
    expert: str | None = None,
    main_writers: list[str],
) -> bool:
  """
  Apply submit bootstrap and leapfrog to post-main-settled state.

  Reuses `start.open_review` for the initial frontmatter set
  (`review_active: true`, `review_round: 1`, `review_approved: false`, optional
  `review_expert`) then invokes the dispatcher's shared `settle_post_main_round`
  primitive — the same primitive the natural per-writer-commit cleanup path uses.
  The result is the exact state the dispatcher produces when every main writer of
  the round has just committed: `review_phase: awaiting-operator`,
  `review_main_done: [<every main writer>]`, `review_round` bumped by the
  writer-count, and the body banner replaced with `Ready to approve`.

  This matches the lazy-review.submit contract: the operator hands a document
  whose body diffs are already pre-authored (a machine writer wrote them outside
  the review loop), and submit lands the document on the operator's Ready banner
  without dispatching the opening writer round.

  Args:
    file_path: The markdown document to bootstrap.
    expert: Optional per-document main-writer override; writes `review_expert` when provided.
    main_writers: Flat-name list to mark done — `[expert]` when an override is given, else
      the class `experts.main` names. The caller resolves this set.

  Returns:
    `True` if the document changed; `False` on an idempotent re-run.
  """
  # waiver: deferred sibling import — dispatcher pulls the full review stack, only needed on this primitive call; bare-name resolved at runtime (type: ignore)
  import dispatcher as _d  # type: ignore
  text = file_path.read_text()
  # Reuse start's bootstrap (review_active / round / approved / banner /
  # review_result clear / optional review_expert).
  _start.open_review(file_path, expert=expert)  # bootstrap, writes in place, no commit
  bootstrapped = file_path.read_text()
  meta, body = _fm.parse(bootstrapped)
  fm_text = bootstrapped[: len(bootstrapped) - len(body)]
  # Idempotency: detect already-settled state. When `review_phase: awaiting-operator`
  # AND every requested main writer is already present in `review_main_done`, the
  # leapfrog was applied on a prior run; calling `settle_post_main_round` again would
  # re-bump `review_round` (the helper bumps unconditionally per "writer commit"
  # event). The early return preserves the on-disk content and surfaces no-op.
  current_done_flat = { _d._flatten(n) for n in _d._parse_main_done(meta.get(ReviewKey.MAIN_DONE, "")) }
  already_settled = (
      meta.get(ReviewKey.PHASE) == Bucket.AWAITING_OPERATOR
      and all(_d._flatten(n) in current_done_flat for n in main_writers)
  )
  # guard: caller resolves the class before invoking; if class_cfg is absent here
  # the bootstrap was idempotent (already opted-in) and the document is mid-cycle
  # — nothing to settle.
  if already_settled:
    new_text = bootstrapped
  else:
    repo = _repo_root_for(file_path)
    settings = _d.load_settings(repo)
    class_cfg = _d._class_for_file(settings, repo, file_path)
    if class_cfg is None:
      new_text = bootstrapped
    else:
      review_round = int(meta.get(ReviewKey.ROUND, 1))
      fm_text, body, _new_round = _d.settle_post_main_round(
          fm_text = fm_text,
          body = body,
          meta = meta,
          class_cfg = class_cfg,
          add_done_writers = main_writers,
          review_round = review_round,
      )
      new_text = fm_text + body
      file_path.write_text(new_text)
  if new_text == text:
    return False
  return True


def _flatten(name: str) -> str:
  """
  Normalize an expert name to the flat form stored in `review_main_done`.

  Args:
    name: Expert name, possibly containing dots or slashes.

  Returns:
    Name with dots and slashes replaced by hyphens.
  """
  return name.replace(".", "-").replace("/", "-")


def _serialize_done(names: list[str]) -> str:
  """
  Render the bracketed inline list that `review_main_done` stores.

  Args:
    names: Flat expert names to serialize.

  Returns:
    Bracketed comma-separated string, e.g. `[a, b]` or `[]` when empty.
  """
  return "[" + ", ".join(names) + "]"


def _resolve_main_writers(file_path: Path, expert: str | None) -> list[str] | None:
  """
  Resolve the writer set to pre-seed into `review_main_done`.

  Args:
    file_path: The document being submitted, used to locate its review class.
    expert: Per-document main-writer override; when provided the result is `[expert]`.

  Returns:
    List of expert names to seed, or `None` when no review class matches and no expert was given.
  """
  # waiver: deferred sibling import — dispatcher pulls the full review stack, needed only on this class-resolution path; bare-name resolved at runtime (type: ignore)
  import dispatcher as _d  # type: ignore
  if expert:
    return [expert]
  repo = _repo_root_for(file_path)
  settings = _d.load_settings(repo)
  class_cfg = _d._class_for_file(settings, repo, file_path)
  if not class_cfg:
    return None
  return [m[JobKey.NAME] for m in (class_cfg.get(JobKey.EXPERTS, {}).get(Phase.MAIN) or [])]


def _expert_known(file_path: Path, expert: str) -> bool:
  """
  Check whether an expert name is registered in the global experts table.

  Args:
    file_path: Any file inside the repo, used to locate `lazy.settings.json`.
    expert: Expert name to look up.

  Returns:
    `True` if the name exists in the global experts table; `False` otherwise.
  """
  # waiver: deferred sibling import — dispatcher pulls the full review stack, needed only on this lookup path; bare-name resolved at runtime (type: ignore)
  import dispatcher as _d  # type: ignore
  repo = _repo_root_for(file_path)
  settings = _d.load_settings(repo)
  return expert in _d.experts_table(settings)


def _repo_root_for(file_path: Path) -> Path:
  """
  Locate the repository root for the given file.

  Args:
    file_path: Any file whose ancestor directories are searched.

  Returns:
    Nearest ancestor directory containing a `.git` entry, or `file_path.parent`
    when none is found within 20 levels.
  """
  cur = file_path.parent
  # waiver: inline numeric literal, not a domain constant
  for _ in range(20):
    # waiver: filesystem path idiom
    if (cur / ".git").exists():
      return cur
    if cur.parent == cur:
      break
    cur = cur.parent
  return file_path.parent


def _atomic_commit(file_path: Path) -> None:
  """Stage + commit under the caller's git identity with the
    `Doc-Review-Phase: initial` trailer (Bug 113 fix: chain classifies
    submit's commit as non-human, so the dispatcher's operator-iterated
    reset rule does not stomp the post-main settled state submit just
    applied)."""
  cwd = file_path.parent
  subprocess.run(
      ["git", "add", "--", str(file_path.name)],
      cwd=cwd, check=True, capture_output=True,
  )
  subprocess.run(
      [
          "git", "commit", "-q",
          "-m", f"review: submit {file_path.name}",
          "-m", f"{Trailer.PHASE}: {Phase.INITIAL}",
      ],
      cwd=cwd, check=True, capture_output=True,
  )


def main(argv: list[str]) -> int:
  """
  Open a document for review skipping the opening writer round.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 success, 2 not-markdown, 3 unknown expert, 4 no review class.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.submit")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file", type=Path)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--expert", default=None)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-commit", action="store_true",
                      # waiver: argparse CLI signature, not a domain key
                      help="apply mutations but do not commit")
  args = parser.parse_args(argv)
  file_path: Path = args.file.resolve()
  # waiver: filesystem path idiom
  if not file_path.exists() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2
  if args.expert and not _expert_known(file_path, args.expert):
    sys.stderr.write(f"unknown expert (not in experts table): {args.expert}\n")
    # waiver: inline numeric literal, not a domain constant
    return 3
  writers = _resolve_main_writers(file_path, args.expert)
  if writers is None:
    sys.stderr.write(f"no review class matches: {file_path}\n")
    # waiver: inline numeric literal, not a domain constant
    return 4
  changed = open_submit(file_path, expert=args.expert, main_writers=writers)
  if changed and not args.no_commit:
    _atomic_commit(file_path)
  print(f"submitted: {file_path} (changed={changed})")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
