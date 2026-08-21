"""
Guideline review phase for the chk aggregator.

Builds the review manifest (changed Python files plus every applicable guideline
layer), prints the dispatch directive for the lazy-python.code-reviewer agent,
and renders the agent's findings in the same shape the other checkers use.

The script never calls the agent itself unless CHK_REVIEW=headless is set — it also
runs from CI, where no LLM is available. A review that has been manifested but not
yet reviewed exits with PENDING_EXIT so it cannot pass unnoticed.

The phase is standalone, not a step of `chk all`, and runs at the end of a unit of
work rather than inside the edit loop.
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
REVIEW_DIR = Path('.runtime') / 'lazy-python' / 'review'

# exit code of a review that is manifested but not yet decided, distinct from a FAIL finding
PENDING_EXIT = 2

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

  # a stable order keeps the manifests built from this listing reproducible
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

  # os.walk yields directories in arbitrary order — sort so callers see one stable tree
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

  # blank lines carry no path, they would poison the scope
  return [line for line in out.stdout.splitlines() if line]


def resolve_scope(repo: Path, paths: list[str], base: str | None = None) -> list[str]:
  """
  Resolve the set of Python files under review.

  Guarantees:
    - Returns paths deduplicated and sorted, regardless of which scope source produced them.
    - When explicit paths are given, they fully determine the scope; the default diff-based
      scope is never combined with them.

  Args:
    repo: Repository root.
    paths: Explicit paths passed on the command line; empty means "current diff".
    base: Git ref the diff is taken against; None means the last commit. A unit of
      work that landed intermediate commits names its starting ref here, so the
      review covers the whole unit rather than the tail after the last commit.

  Returns:
    Sorted repo-relative paths of the Python files to review.
  """

  # Domain(pytool.pipeline-idempotency):
  # # Review scope for a unit of work
  # The set of files a review covers is either an explicit list the caller names, or — when none
  # is given — every Python file changed since a base point plus every new untracked one. The
  # base point defaults to the last commit, but a unit of work that landed several intermediate
  # commits can move it back to where the work started, so the whole unit is reviewed together
  # instead of only the tail since the latest commit. A bare current-directory marker handed down
  # by an outer pipeline counts as "no explicit list", not as a request to review the entire tree.

  # Contract:
  # The returned paths are always deduplicated and sorted, regardless of whether the
  # scope comes from explicit paths or from the git-diff default.

  # Contract:
  # When explicit paths are given, they fully determine the review scope; the
  # diff-based default scope is never combined with them.

  # a bare '.' is the aggregator's default target, not a request to review the whole tree
  explicit = [raw for raw in paths if raw not in ('.', './')]

  # explicit paths win — expand directories, keep files
  if explicit:
    found: list[str] = []
    for raw in explicit:
      target = (repo / raw).resolve()
      if target.is_dir():
        found.extend(str(found_py.relative_to(repo)) for found_py in list_python_tree(target))
      elif target.suffix == '.py' and target.is_file():
        found.append(str(target.relative_to(repo)))
    return sorted(set(found))

  # default scope — everything the working tree changed against the base ref, plus untracked
  changed = run_git(repo, 'diff', '--name-only', base or 'HEAD')
  changed += run_git(repo, 'ls-files', '--others', '--exclude-standard')

  # a path can appear in both git queries, and a deleted file still shows up in the diff
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

  # Domain(pytool.pipeline-idempotency):
  # # Rule-file eligibility for a Python review
  # A repository rule file only enters a Python review's guideline set when its declared scope
  # says so: either it is marked as always loaded, or its scope explicitly names a Python file
  # glob. A rule whose body merely mentions Python source files in prose, without declaring that
  # scope, is left out — only the declared scope decides membership, never incidental wording.

  # guard: no frontmatter at all, the rule declares no scope
  if not text.startswith(FRONTMATTER_FENCE):
    return False

  # find where the frontmatter ends so only the declared scope is inspected, never the body
  closing = text.find(f'\n{FRONTMATTER_FENCE}', len(FRONTMATTER_FENCE))

  # guard: unterminated frontmatter, treat the rule as unscoped
  if closing < 0:
    return False

  # the scope declaration is whatever sits between the two fences
  front = text[len(FRONTMATTER_FENCE):closing]

  # an always-loaded rule governs every file; otherwise a Python glob must be declared
  return 'always_loaded' in front or '.py' in front


def collect_guidelines(repo: Path, plugin_root: Path) -> dict[str, list[str]]:
  """
  Collect every guideline layer the reviewer must read, canon first.

  Guarantees:
    - The returned mapping preserves canon-first insertion order, so iterating it in order
      gives the correct override precedence between conflicting layers.

  Args:
    repo: Repository root — source of the overlay, rule, and note layers.
    plugin_root: Plugin root — source of the canonical guidelines.

  Returns:
    Layer name mapped to the paths belonging to it; empty layers are omitted.
  """

  # Domain(pytool.pipeline-idempotency):
  # # Guideline layer precedence for a code review
  # A review is built from up to four guideline layers, read in a fixed order: the shipped canon
  # first, the project's own overlay next, repository rule files scoped to Python sources after
  # that, and project-wide notes last. Where the overlay repeats or contradicts the canon, the
  # overlay wins — a project narrows or replaces a canon rule by adding an overlay entry rather
  # than editing the canon.

  # Contract:
  # The returned mapping preserves insertion order canon, overlay, rules, project_notes;
  # a layer that appears later in this order takes precedence over one that appears
  # earlier when their guidance conflicts.

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

  # insertion order is canon-first, which is the precedence the reviewer must read them in
  return layers


def scope_key(repo: Path, files: list[str]) -> str:
  """
  Build a content key identifying this exact review scope.

  Guarantees:
    - Identical file lists, in the same order and with identical contents, always produce
      the same digest, regardless of machine or process.

  Args:
    repo: Repository root.
    files: Repo-relative paths under review.

  Returns:
    Hex digest over every file's path and content — stable across re-runs that
    changed nothing, so an already-reviewed scope is not re-dispatched.
  """

  # Domain(pytool.pipeline-idempotency):
  # # Review scope identity
  # A review scope is identified by a hash over every covered file's path and its exact content,
  # not by a timestamp or a scope description. Two runs that hash to the same value are the same
  # review: the later run reuses the earlier verdict instead of dispatching a fresh review, so an
  # unmodified scope is never reviewed twice.

  # Contract:
  # Two calls given the same file list, in the same order, with identical file
  # contents always return the same digest, on any machine and in any process.

  digest = hashlib.sha256()
  for name in files:
    digest.update(name.encode('utf-8'))
    digest.update((repo / name).read_bytes())

  # the digest is the cache key — identical content means the scope is already reviewed
  return digest.hexdigest()


def find_cached(review_dir: Path, key: str) -> Path | None:
  """
  Find findings already produced for this scope key.

  Guarantees:
    - When several stored findings documents match the same scope key, the most
      recently generated one is returned.

  Args:
    review_dir: Directory holding previous manifests and findings.
    key: Scope key of the current review.

  Returns:
    Path of the matching findings file, or None when the scope is not reviewed yet.
  """

  # Contract:
  # When several stored findings documents match the same scope key, the most
  # recently generated one is returned; older matching verdicts are never surfaced.

  # guard: nothing reviewed in this repo so far
  if not review_dir.is_dir():
    return None

  # newest first — a scope reviewed twice keeps the latest verdict, and unreadable files are skipped
  for found in reversed(list_matching(review_dir, '*.findings.json')):
    try:
      data = json.loads(found.read_text(encoding = 'utf-8'))
    except (OSError, ValueError):
      continue
    if data.get('scope_key') == key:
      return found

  # no stored document covers this scope, it has to be reviewed anew
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

  # a document carrying no findings is a clean review, not a malformed one
  return data.get('findings') or []


def print_findings(findings: list[Finding]) -> int:
  """
  Print findings in the checker output shape and decide the exit code.

  Guarantees:
    - Returns 1 exactly when at least one finding carries FAIL severity; WARN and INFO
      findings alone never produce a non-zero result.

  Args:
    findings: Findings loaded from the reviewer's document.

  Returns:
    1 when at least one FAIL is present, 0 otherwise.
  """

  # Domain(pytool.checker-severity):
  # # Severity vocabulary and the blocking threshold
  # Every finding carries one severity drawn from a closed three-level vocabulary: informational,
  # warning, or failure. A phase's overall verdict follows the single worst severity present
  # across all its findings — one failure anywhere blocks the pipeline outright, while a set
  # containing only warnings or informational notes is surfaced without blocking it.

  # Contract:
  # Returns 1 exactly when at least one finding carries FAIL severity; any number of
  # WARN or INFO findings alone never produces a non-zero return.

  # guard: a clean review still prints a summary line
  if not findings:
    print('Success: no guideline issues found')
    return 0

  # render every finding in the shape the other checkers use, tracking the worst severity seen
  worst = 0
  for item in findings:
    severity = str(item.get('severity', 'WARN')).upper()
    worst = max(worst, SEVERITY_RANK.get(severity, 1))
    location = f"{item.get('file', '?')}:{item.get('line', 0)}"
    rule = item.get('rule', 'guideline')
    print(f"{location}: {severity.lower()}: [{rule}] {item.get('message', '')}")

  # a single FAIL anywhere in the set has to block the pipeline
  counts = f'{len(findings)} finding(s)'
  if worst >= SEVERITY_RANK['FAIL']:
    print(f'Found blocking guideline issues: {counts}')
    return 1

  # only INFO/WARN survived — surface them without failing the run
  print(f'Found non-blocking guideline issues: {counts}')
  return 0


def write_manifest(repo: Path, plugin_root: Path, files: list[str], key: str) -> tuple[Path, Path]:
  """
  Write the review manifest for the current scope.

  Guarantees:
    - The `findings_path` recorded in the manifest is exactly where the reviewer agent
      must write its verdict; render mode reads findings from that path only.

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

  # the shared timestamp is what pairs a manifest with the findings file written back for it
  manifest_path = review_dir / f'{stamp}.json'
  findings_path = review_dir / f'{stamp}.findings.json'

  # Contract:
  # The `findings_path` recorded in the manifest is the exact path the reviewer agent
  # must write its verdict to; render mode reads findings from that path and no other.

  # the manifest carries everything the reviewer needs, so it discovers nothing on its own
  manifest = {
    'generated': datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC'),
    'repo': str(repo),
    'scope_key': key,
    'files': files,
    'guidelines': collect_guidelines(repo, plugin_root),
    'findings_path': str(findings_path.relative_to(repo)),
  }
  manifest_path.write_text(json.dumps(manifest, indent = 2) + '\n', encoding = 'utf-8')

  # the caller needs both paths to print the dispatch directive and the render command
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

  # the manifest is authoritative about where the findings land — never recompute that path
  manifest = json.loads(manifest_path.read_text(encoding = 'utf-8'))
  findings_path = repo / manifest['findings_path']

  # guard: the agent produced no findings document
  if not findings_path.is_file():
    print(f'review: agent wrote no findings at {findings_path}', file = sys.stderr)
    return 1

  # headless runs render the verdict themselves, there is no operator step in between
  return print_findings(load_findings(findings_path))


def cmd_review(repo: Path, plugin_root: Path, paths: list[str], base: str | None = None) -> int:
  """
  Build the manifest for the current scope and print the dispatch directive.

  Guarantees:
    - An unresolvable base ref is refused outright: the run exits 1, prints a diagnostic,
      and writes no manifest, instead of reporting an empty scope.
    - A scope whose content exactly matches a previously reviewed scope reuses that
      review's findings instead of being dispatched again.
    - PENDING_EXIT is returned only for a scope that has just been manifested and not yet
      judged; it is never conflated with the success (0) or failure (1) codes.

  Args:
    repo: Repository root.
    plugin_root: Plugin root holding the canonical guidelines.
    paths: Explicit paths, or empty for the current diff.
    base: Git ref the diff is taken against, or None for the last commit.

  Returns:
    Process exit code — PENDING_EXIT while the review is undecided, 1 on a FAIL finding,
    1 on an unresolvable base ref, else 0.
  """

  # Contract:
  # An unresolvable base ref is refused outright: the run exits 1, prints a
  # diagnostic, and writes no manifest, instead of reporting an empty scope.

  # guard: an unknown ref would diff against nothing and report an empty scope, which reads
  # exactly like "nothing to review" — a typo must fail loudly instead of waiving the phase
  if base and not run_git(repo, 'rev-parse', '--verify', '--quiet', f'{base}^{{commit}}'):
    print(f'review: base ref {base!r} does not resolve to a commit', file = sys.stderr)
    return 1

  # the scope decides everything downstream — the key, the manifest, and whether a cache hit applies
  files = resolve_scope(repo, paths, base)

  # guard: nothing changed, the phase has no work
  if not files:
    print('review: SKIPPED — no changed Python files in scope')
    return 0

  # content key identifies this exact scope for the cache lookup that follows
  key = scope_key(repo, files)

  # Contract:
  # A scope whose content exactly matches a previously reviewed scope reuses that
  # review's findings instead of being dispatched again.

  # an unchanged scope keeps the findings of its previous review
  cached = find_cached(repo / REVIEW_DIR, key)
  if cached is not None:
    print(f'review: scope unchanged since {cached.name} — reusing findings')
    return print_findings(load_findings(cached))

  # a scope nobody has reviewed yet needs a fresh manifest for the agent to pick up
  manifest_path, findings_path = write_manifest(repo, plugin_root, files, key)

  # headless mode is the only path where this script talks to an agent itself
  if os.environ.get('CHK_REVIEW') == 'headless':
    return dispatch_headless(repo, manifest_path)

  # no agent available here — hand the operator the dispatch and render directives verbatim
  print(f'review: PENDING — {len(files)} file(s) in scope')
  print(f'review: manifest {manifest_path.relative_to(repo)}')
  print(f'review: dispatch agent {REVIEWER_AGENT} with that manifest, '
        f'then render its findings:')
  print(f'review:   chk-py review --render {findings_path.relative_to(repo)}')
  print('review: a pending review is unfinished work — dispatch the agent, or ask the operator '
        'to waive this scope.')

  # Domain(pytool.pipeline-idempotency):
  # # Pending review outcome
  # A scope that has been prepared for review but not yet judged is neither a pass nor a failure;
  # it reports a distinct pending outcome of its own. This keeps a pipeline gate from mistaking an
  # unreviewed scope for a clean one — the pending state stands until a review actually produces a
  # verdict.

  # Contract:
  # PENDING_EXIT is returned only for a scope that has just been manifested and not yet
  # judged; callers MUST NOT treat it as the success code 0 or the failure code 1.

  # an undecided review must not pass as success, hence a code of its own
  return PENDING_EXIT


def main() -> None:
  """
  Parse arguments and run the requested review action.
  """
  parser = argparse.ArgumentParser(description = 'guideline review phase')
  parser.add_argument('paths', nargs = '*', help = 'paths to review (default: current diff)')
  parser.add_argument('--render', metavar = 'FINDINGS',
                      help = 'render a findings document produced by the reviewer agent')
  parser.add_argument('--base', metavar = 'REF',
                      help = 'diff against this ref instead of the last commit, so a unit of work '
                             'that landed intermediate commits is reviewed whole')
  parser.add_argument('--plugin-root', default = str(Path(__file__).resolve().parent.parent),
                      help = 'plugin root holding the canonical guidelines')
  args = parser.parse_args()

  # the review is always scoped to the repo the caller runs in, never to the plugin's own tree
  repo = Path.cwd().resolve()

  # render mode only reads an existing document, it never builds a manifest
  if args.render:
    sys.exit(print_findings(load_findings(Path(args.render))))

  # default action — manifest the current scope and report whether the review is still pending
  sys.exit(cmd_review(repo, Path(args.plugin_root).resolve(), args.paths, args.base))


# run main if this is the top-level script
if __name__ == '__main__':
  main()
