"""
Guideline review phase for the chk aggregator.

Builds the review manifest (changed Python files plus every applicable guideline
layer), prints the dispatch directive for the lazy-python.code-reviewer agent,
and renders the agent's findings in the same shape the other checkers use.

The script never calls the agent itself unless CHK_REVIEW=headless is set — it is
part of the check pipeline, which also runs from pre-commit and CI where no LLM
is available.
"""

from __future__ import annotations

from typing import TypeAlias

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys

from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# one finding as written by the reviewer agent: file, line, severity, rule, message
Finding: TypeAlias = dict[str, object]

# agent dispatched to perform the review
REVIEWER_AGENT = 'lazycortex-python:lazy-python.code-reviewer'

# repo-relative directory holding manifests and findings
REVIEW_DIR = Path('.logs') / 'lazy-python' / 'review'

# guideline layers as (directory, filename pattern), outermost (canon) first
CANON_LAYER = ('references', 'lazy-python.*-guidelines.md')
OVERLAY_LAYER = ('docs/guidelines', '*.md')
RULES_LAYER = ('.claude/rules', '*.md')

# project-wide note files read as the last overlay layer
PROJECT_NOTES = ['CLAUDE.md', '.claude/CLAUDE.md']

# opening fence of a rule file's YAML frontmatter
FRONTMATTER_FENCE = '---'

# severity ordering — the highest one present decides the exit code
SEVERITY_RANK = { 'INFO': 0, 'WARN': 1, 'FAIL': 2 }


def list_matching(base: Path, pattern: str) -> list[Path]:
  """
  List the files of one flat directory whose names match a pattern.

  Args:
    base: Directory to list.
    pattern: fnmatch pattern applied to the file name.

  Returns:
    Sorted paths of the matching files; empty when the directory is absent.
  """
  # guard: the layer directory does not exist in this repo
  if not base.is_dir():
    return []

  return sorted(base / name for name in os.listdir(base)
                if fnmatch.fnmatch(name, pattern) and (base / name).is_file())


def list_python_tree(base: Path) -> list[Path]:
  """
  List every Python file under a directory tree.

  Args:
    base: Directory to walk.

  Returns:
    Sorted paths of the Python files found below it.
  """
  found: list[Path] = []
  for root, _dirs, names in os.walk(base):
    found.extend(Path(root) / name for name in names if name.endswith('.py'))

  return sorted(found)


def run_git(repo: Path, *args: str) -> list[str]:
  """
  Run a git command in the repo and return its stdout lines.

  Args:
    repo: Repository root the command runs in.
    args: Git arguments following the executable name.

  Returns:
    Non-empty stdout lines, or an empty list when git fails or is absent.
  """
  # git may be missing or the directory may not be a repo — treat both as "no scope"
  try:
    out = subprocess.run(['git', '-C', str(repo), *args],
                         capture_output = True, text = True, check = False)
  except OSError:
    return []

  # guard: git reported a failure, nothing usable on stdout
  if out.returncode != 0:
    return []

  return [line for line in out.stdout.splitlines() if line]


def resolve_scope(repo: Path, paths: list[str]) -> list[str]:
  """
  Resolve the set of Python files under review.

  Args:
    repo: Repository root.
    paths: Explicit paths passed on the command line; empty means "current diff".

  Returns:
    Sorted repo-relative paths of the Python files to review.
  """
  # a bare '.' is the aggregator's default target, not a request to review the whole tree
  explicit = [raw for raw in paths if raw not in ('.', './')]

  # explicit paths win — expand directories, keep files
  if explicit:
    paths = explicit
    found: list[str] = []
    for raw in paths:
      target = (repo / raw).resolve()
      if target.is_dir():
        found.extend(str(found_py.relative_to(repo)) for found_py in list_python_tree(target))
      elif target.suffix == '.py' and target.is_file():
        found.append(str(target.relative_to(repo)))
    return sorted(set(found))

  # default scope — everything the working tree changed against HEAD, plus untracked
  changed = run_git(repo, 'diff', '--name-only', 'HEAD')
  changed += run_git(repo, 'ls-files', '--others', '--exclude-standard')

  return sorted({ name for name in changed
                  if name.endswith('.py') and (repo / name).is_file() })


def rule_applies(text: str) -> bool:
  """
  Decide whether a rule file governs Python sources.

  Args:
    text: Full rule file content.

  Returns:
    True when the rule is always loaded or scopes at least one path glob to Python
    files. Body mentions of `.py` do not count — only the frontmatter scope does.
  """
  # guard: no frontmatter at all, the rule declares no scope
  if not text.startswith(FRONTMATTER_FENCE):
    return False

  closing = text.find(f'\n{FRONTMATTER_FENCE}', len(FRONTMATTER_FENCE))

  # guard: unterminated frontmatter, treat the rule as unscoped
  if closing < 0:
    return False

  front = text[len(FRONTMATTER_FENCE):closing]

  return 'always_loaded' in front or '.py' in front


def collect_guidelines(repo: Path, plugin_root: Path) -> dict[str, list[str]]:
  """
  Collect every guideline layer the reviewer must read, canon first.

  Args:
    repo: Repository root — source of the overlay, rule, and note layers.
    plugin_root: Plugin root — source of the canonical guidelines.

  Returns:
    Layer name mapped to the paths belonging to it; empty layers are omitted.
  """
  # canonical guidelines ship with the plugin and are read by absolute path
  layers: dict[str, list[str]] = {
    'canon': [str(found) for found in list_matching(plugin_root / CANON_LAYER[0], CANON_LAYER[1])],
  }

  # project overlay overrides the canon on conflict
  overlay = [str(found.relative_to(repo))
             for found in list_matching(repo / OVERLAY_LAYER[0], OVERLAY_LAYER[1])]
  if overlay:
    layers['overlay'] = overlay

  # session rules that scope themselves to Python files
  rules = []
  for rule in list_matching(repo / RULES_LAYER[0], RULES_LAYER[1]):
    if rule_applies(rule.read_text(encoding = 'utf-8', errors = 'replace')):
      rules.append(str(rule.relative_to(repo)))
  if rules:
    layers['rules'] = rules

  # project-wide notes are the last overlay layer
  notes = [name for name in PROJECT_NOTES if (repo / name).is_file()]
  if notes:
    layers['project_notes'] = notes

  return layers


def scope_key(repo: Path, files: list[str]) -> str:
  """
  Build a content key identifying this exact review scope.

  Args:
    repo: Repository root.
    files: Repo-relative paths under review.

  Returns:
    Hex digest over every file's path and content — stable across re-runs that
    changed nothing, so an already-reviewed scope is not re-dispatched.
  """
  digest = hashlib.sha256()
  for name in files:
    digest.update(name.encode('utf-8'))
    digest.update((repo / name).read_bytes())

  return digest.hexdigest()


def find_cached(review_dir: Path, key: str) -> Path | None:
  """
  Find findings already produced for this scope key.

  Args:
    review_dir: Directory holding previous manifests and findings.
    key: Scope key of the current review.

  Returns:
    Path of the matching findings file, or None when the scope is not reviewed yet.
  """
  # guard: nothing reviewed in this repo so far
  if not review_dir.is_dir():
    return None

  for found in reversed(list_matching(review_dir, '*.findings.json')):
    try:
      data = json.loads(found.read_text(encoding = 'utf-8'))
    except (OSError, ValueError):
      continue
    if data.get('scope_key') == key:
      return found

  return None


def load_findings(path: Path) -> list[Finding]:
  """
  Load a findings document written by the reviewer agent.

  Args:
    path: Findings file path.

  Returns:
    The findings list; an empty list when the document carries none.

  Raises:
    SystemExit: The file is missing or is not valid JSON.
  """
  try:
    data = json.loads(path.read_text(encoding = 'utf-8'))
  except (OSError, ValueError) as error:
    print(f'review: cannot read findings from {path}: {error}', file = sys.stderr)
    raise SystemExit(1) from error

  return data.get('findings') or []


def print_findings(findings: list[Finding]) -> int:
  """
  Print findings in the checker output shape and decide the exit code.

  Args:
    findings: Findings loaded from the reviewer's document.

  Returns:
    1 when at least one FAIL is present, 0 otherwise.
  """
  # guard: a clean review still prints a summary line
  if not findings:
    print('Success: no guideline issues found')
    return 0

  worst = 0
  for item in findings:
    severity = str(item.get('severity', 'WARN')).upper()
    worst = max(worst, SEVERITY_RANK.get(severity, 1))
    location = f"{item.get('file', '?')}:{item.get('line', 0)}"
    rule = item.get('rule', 'guideline')
    print(f"{location}: {severity.lower()}: [{rule}] {item.get('message', '')}")

  counts = f'{len(findings)} finding(s)'
  if worst >= SEVERITY_RANK['FAIL']:
    print(f'Found blocking guideline issues: {counts}')
    return 1

  print(f'Found non-blocking guideline issues: {counts}')
  return 0


def write_manifest(repo: Path, plugin_root: Path, files: list[str], key: str) -> tuple[Path, Path]:
  """
  Write the review manifest for the current scope.

  Args:
    repo: Repository root.
    plugin_root: Plugin root holding the canonical guidelines.
    files: Repo-relative paths under review.
    key: Scope key of the current review.

  Returns:
    Manifest path and the findings path the agent is expected to write.
  """
  stamp = datetime.now(UTC).strftime('%Y-%m-%d_%H-%M-%S')
  review_dir = repo / REVIEW_DIR
  review_dir.mkdir(parents = True, exist_ok = True)

  manifest_path = review_dir / f'{stamp}.json'
  findings_path = review_dir / f'{stamp}.findings.json'

  manifest = {
    'generated': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC'),
    'repo': str(repo),
    'scope_key': key,
    'files': files,
    'guidelines': collect_guidelines(repo, plugin_root),
    'findings_path': str(findings_path.relative_to(repo)),
  }
  manifest_path.write_text(json.dumps(manifest, indent = 2) + '\n', encoding = 'utf-8')

  return manifest_path, findings_path


def dispatch_headless(repo: Path, manifest_path: Path) -> int:
  """
  Run the reviewer agent through the Claude CLI and render its findings.

  Args:
    repo: Repository root the CLI runs in.
    manifest_path: Manifest the agent reads.

  Returns:
    Exit code from rendering the findings, or 1 when the CLI is unavailable.
  """
  prompt = (f'Dispatch the {REVIEWER_AGENT} agent against the review manifest at '
            f'{manifest_path}. Return nothing; the agent writes its findings file.')

  # the CLI is optional — a machine without it falls back to the manifest workflow
  try:
    result = subprocess.run(['claude', '-p', prompt], cwd = str(repo), check = False)
  except OSError as error:
    print(f'review: headless mode requested but the claude CLI is unavailable: {error}',
          file = sys.stderr)
    return 1

  # guard: the CLI itself failed, there is nothing to render
  if result.returncode != 0:
    print('review: headless dispatch failed', file = sys.stderr)
    return 1

  manifest = json.loads(manifest_path.read_text(encoding = 'utf-8'))
  findings_path = repo / manifest['findings_path']

  # guard: the agent produced no findings document
  if not findings_path.is_file():
    print(f'review: agent wrote no findings at {findings_path}', file = sys.stderr)
    return 1

  return print_findings(load_findings(findings_path))


def cmd_review(repo: Path, plugin_root: Path, paths: list[str]) -> int:
  """
  Build the manifest for the current scope and print the dispatch directive.

  Args:
    repo: Repository root.
    plugin_root: Plugin root holding the canonical guidelines.
    paths: Explicit paths, or empty for the current diff.

  Returns:
    Process exit code — always 0 unless headless rendering reports a blocker.
  """
  files = resolve_scope(repo, paths)

  # guard: nothing changed, the phase has no work
  if not files:
    print('review: SKIPPED — no changed Python files in scope')
    return 0

  key = scope_key(repo, files)

  # an unchanged scope keeps the findings of its previous review
  cached = find_cached(repo / REVIEW_DIR, key)
  if cached is not None:
    print(f'review: scope unchanged since {cached.name} — reusing findings')
    return print_findings(load_findings(cached))

  manifest_path, findings_path = write_manifest(repo, plugin_root, files, key)

  # headless mode is the only path where this script talks to an agent itself
  if os.environ.get('CHK_REVIEW') == 'headless':
    return dispatch_headless(repo, manifest_path)

  print(f'review: PENDING — {len(files)} file(s) in scope')
  print(f'review: manifest {manifest_path.relative_to(repo)}')
  print(f'review: dispatch agent {REVIEWER_AGENT} with that manifest, '
        f'then render its findings:')
  print(f'review:   chk-py review --render {findings_path.relative_to(repo)}')

  return 0


def main() -> None:
  """
  Parse arguments and run the requested review action.
  """
  parser = argparse.ArgumentParser(description = 'guideline review phase')
  parser.add_argument('paths', nargs = '*', help = 'paths to review (default: current diff)')
  parser.add_argument('--render', metavar = 'FINDINGS',
                      help = 'render a findings document produced by the reviewer agent')
  parser.add_argument('--plugin-root', default = str(Path(__file__).resolve().parent.parent),
                      help = 'plugin root holding the canonical guidelines')
  args = parser.parse_args()

  repo = Path.cwd().resolve()

  # render mode only reads an existing document, it never builds a manifest
  if args.render:
    sys.exit(print_findings(load_findings(Path(args.render))))

  sys.exit(cmd_review(repo, Path(args.plugin_root).resolve(), args.paths))


# run main if this is the top-level script
if __name__ == '__main__':
  main()
