"""`commit-doc` — the coordinator's one commit per wake.

Commits the working-tree state of one review document under the coordinator's registered
git identity, with the `Doc-Review-Phase: mechanical` trailer and the document's icon
repaint folded into the same commit (via `git_ops.commit_mechanical`, the same machinery
the postman uses). The coordinator never runs a raw `git commit`: every pen write of a
wake — question callouts, command mini-plan marks, `# History` lines, verb-made
frontmatter and banner writes — lands through this verb, once, at the end of the wake.

A wake that changed nothing is a clean no-op: when the document is unmodified and the
repaint finds nothing to touch, no commit is made and `{"committed": false}` is printed.

The author identity comes from the consumer's `experts["review.coordinator"]`
`git_author` entry (seeded at install time); a checkout without one falls back to the
`review.coordinator@bot.invalid` default so the commit is still recognisable.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
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
import git_ops as _git_ops  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import JobKey, Paths  # noqa: E402


# the coordinator's expert name and fallback identity — the registered settings entry wins
_COORDINATOR_EXPERT = "review.coordinator"
_FALLBACK_EMAIL = "review.coordinator@bot.invalid"


def _coordinator_author(repo: Path) -> dict:
  """
  Resolve the coordinator's git author identity from the consumer's settings.

  Args:
    repo: Repository root to resolve `.claude/lazy.settings.json` against.

  Returns:
    Mapping with `name` and `email` keys — the registered `git_author` of the
    `review.coordinator` expert, or the shipped fallback identity when the settings
    file or the entry is absent or unreadable.
  """
  path = repo / Paths.CLAUDE_DIR / Paths.SETTINGS_FILE
  try:
    settings = json.loads(path.read_text())
  except (OSError, json.JSONDecodeError):
    settings = {}
  # waiver: 'experts'/'git_author' are lazy.settings.json's own wire-shape keys, not keys.py-promoted constants
  author = settings.get("experts", {}).get(_COORDINATOR_EXPERT, {}).get("git_author", {})
  # guard: an entry without both fields would half-apply — fall back whole
  if not isinstance(author, dict) or not author.get(JobKey.NAME) or not author.get(JobKey.EMAIL):
    return {JobKey.NAME: _COORDINATOR_EXPERT, JobKey.EMAIL: _FALLBACK_EMAIL}
  return {JobKey.NAME: author[JobKey.NAME], JobKey.EMAIL: author[JobKey.EMAIL]}


def commit_doc(repo: Path, file_path: Path, subject: str) -> dict:
  """
  Commit the document's working-tree state as the coordinator's single wake commit.

  Args:
    repo: Repository root.
    file_path: Absolute path to the review document.
    subject: Commit subject line, written verbatim.

  Returns:
    `{"committed": true, "sha": <sha>}` when a commit was made, or `{"committed": false}`
    when the document is unmodified and the repaint touched nothing.
  """
  rel = str(file_path.relative_to(repo))
  status = subprocess.run(
      # waiver: git CLI vocabulary
      ["git", "-C", str(repo), "status", "--porcelain", "--", rel],
      capture_output=True, text=True, check=False,
  ).stdout.strip()
  extras = _git_ops.repaint_inline(repo, [rel])
  # guard: nothing changed this wake — no commit, and saying so is the verb's contract
  if not status and not extras:
    return {"committed": False}
  sha = _git_ops.commit_mechanical(repo, file_path, author=_coordinator_author(repo), message=subject)
  # waiver: 'committed'/'sha' are this verb's own wire-shape keys, printed for the coordinator to read
  return {"committed": True, "sha": sha}


def main(argv: list[str]) -> int:
  """
  Commit one review document's wake state and print the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: `0` on success (including the clean no-op), `2` when the file does not exist
    or the subject is empty.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazycortex-review commit-doc")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--subject", required=True)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default=".")
  args = parser.parse_args(argv)

  # `file` resolves against `--repo` unless it's already absolute, mirroring the other verbs
  repo = Path(args.repo).resolve()
  file_path = (repo / args.file).resolve()
  if not file_path.is_file():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2
  # guard: a commit needs a subject — an empty one would land an unreadable history line
  if not args.subject.strip():
    # waiver: one-shot CLI error string, not a domain key
    sys.stderr.write("empty --subject\n")
    return 2

  # the CLI's whole contract is this one summary line
  print(json.dumps(commit_doc(repo, file_path, args.subject)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
