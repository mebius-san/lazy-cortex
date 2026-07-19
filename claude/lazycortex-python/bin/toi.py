from __future__ import annotations

import argparse
import ast
import os
import re
import sys
# noinspection PyCompatibility
import tomllib

from collections import defaultdict

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# hardcoded exclusions that should never be scanned
HARDCODED_EXCLUDES = ['.venv', '__pycache__']

# regex matching a valid waiver comment (non-empty explanation after the colon)
WAIVER_RE = re.compile(r'#\s*waiver:\s*\S')

# regex matching a waiver marker regardless of whether a reason follows
WAIVER_MARKER_RE = re.compile(r'#\s*waiver:')


# ----------------------------------------------------------------------------------------
def load_config() -> dict:
  """
  Load configuration from pyproject.toml.

  Returns:
    Configuration dictionary for the toi tool.
  """
  config_path = 'pyproject.toml'
  if not os.path.exists(config_path):
    return {}

  with open(config_path, 'rb') as fle:
    data = tomllib.load(fle)

  return data.get('tool', {}).get('toi', {})


# ----------------------------------------------------------------------------------------

# define alias for (module, import-statement line number, imported-name line number)
ImportInfo = tuple[str | None, int, int]

# define alias for output structure: filepath -> list of suggestions
SuggestionsMap = dict[str, list[tuple[int, str | None, str]]]


class TypeOnlyImportAnalyzer(ast.NodeVisitor):
  """
  AST visitor to detect imports used only in type annotations.
  
  Analyze Python source code to identify imports that are used exclusively in type
  annotations and could potentially be moved to TYPE_CHECKING blocks.
  
  Responsibilities:
    - Track imported names and their usage contexts (runtime vs annotation).
    - Detect TYPE_CHECKING blocks and future annotations imports.
    - Identify names used only in type annotations.
  
  Guarantees:
    - All imported names are tracked with their source modules and line numbers.
    - Runtime and annotation usage are correctly distinguished.
    - TYPE_CHECKING block detection is accurate.
  
  Attributes:
    imported_names: mapping of imported names to their source modules and line numbers.
    runtime_refs: set of names used in runtime expressions.
    ann_refs: set of names used in type annotations only.
    has_future_annotations: whether `from __future__ import annotations` is present.
    has_type_checking_block: whether any `if TYPE_CHECKING`: block is used.
    in_type_checking: whether currently visiting inside a TYPE_CHECKING block.
  """

  def __init__(self) -> None:
    """
    Initialize the AST analyzer with empty tracking collections.
    
    Sets up all necessary data structures to track imported names, usage contexts,
    and special import patterns during AST traversal.
    """
    # store imported names and their source modules
    self.imported_names: dict[str, ImportInfo] = { }

    # store names used in runtime expressions
    self.runtime_refs: set[str] = set()

    # store names used in type annotations only
    self.ann_refs: set[str] = set()

    # flag to track if `from __future__ import annotations` is present
    self.has_future_annotations: bool = False

    # flag to track if any `if TYPE_CHECKING:` block is used
    self.has_type_checking_block: bool = False

    # flag to indicate if we're inside a TYPE_CHECKING block
    self.in_type_checking: bool = False

    # flag to indicate we're visiting an annotation expression
    self._in_annotation: bool = False


  # waiver: ast visitor methods must use `visit_<NodeType>` naming (PascalCase suffix required by ast.NodeVisitor)
  # pylint: disable=invalid-name
  def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
    """
    Visit ImportFrom nodes to track imported names and detect future annotations.
    
    Args:
      node: the ImportFrom AST node to process
    """
    # check for `from __future__ import annotations`
    if node.module == '__future__':
      for alias in node.names:
        if alias.name == 'annotations':
          self.has_future_annotations = True

    # guard: skip imports inside TYPE_CHECKING — they are already type-only
    if self.in_type_checking:
      return

    # record each imported symbol, its source module, and both the statement
    # line (shared by all names in the block) and the name's own line
    for alias in node.names:
      name = alias.asname or alias.name
      self.imported_names[name] = (node.module, node.lineno, alias.lineno)


  # waiver: ast visitor methods must use `visit_<NodeType>` naming (PascalCase suffix required by ast.NodeVisitor)
  # pylint: disable=invalid-name
  def visit_Import(self, node: ast.Import) -> None:
    """
    Visit Import nodes to track imported names.
    
    Args:
      node: the Import AST node to process
    """
    # guard: skip imports inside TYPE_CHECKING — they are already type-only
    if self.in_type_checking:
      return

    # record each import symbol, source module, and the name's own line
    for alias in node.names:
      name = alias.asname or alias.name
      self.imported_names[name] = (alias.name, node.lineno, alias.lineno)


  # waiver: ast visitor methods must use `visit_<NodeType>` naming (PascalCase suffix required by ast.NodeVisitor)
  # pylint: disable=invalid-name
  def visit_If(self, node: ast.If) -> None:
    """
    Visit If nodes to detect and handle TYPE_CHECKING blocks.
    
    Args:
      node: the If AST node to process
    """
    # detect and enter TYPE_CHECKING blocks
    if isinstance(node.test, ast.Name) and node.test.id == 'TYPE_CHECKING':
      self.has_type_checking_block = True
      prev = self.in_type_checking
      self.in_type_checking = True
      for stmt in node.body:  # type: ast.AST
        self.visit(stmt)
      self.in_type_checking = prev
    else:
      self.generic_visit(node)


  # waiver: ast visitor methods must use `visit_<NodeType>` naming (PascalCase suffix required by ast.NodeVisitor)
  # pylint: disable=invalid-name
  def visit_Name(self, node: ast.Name) -> None:
    """
    Visit Name nodes to record name usage in the runtime or annotation context.
    
    Args:
      node: the Name AST node to process
    """
    # record name usage based on the current context
    if self._in_annotation:
      self.ann_refs.add(node.id)
    else:
      self.runtime_refs.add(node.id)


  # waiver: ast visitor methods must use `visit_<NodeType>` naming (PascalCase suffix required by ast.NodeVisitor)
  # pylint: disable=invalid-name
  def visit_ClassDef(self, node: ast.ClassDef) -> None:
    """
    Visit ClassDef nodes to handle base classes and class body.
    
    Args:
      node: the ClassDef AST node to process
    """
    # visit base classes (used at runtime)
    for base in node.bases:  # type: ast.AST
      self.visit(base)  # mark names like Generic[TypeVar] as runtime-used
    # visit class body
    for stmt in node.body:  # type: ast.AST
      self.visit(stmt)


  # waiver: ast visitor methods must use `visit_<NodeType>` naming (PascalCase suffix required by ast.NodeVisitor)
  # pylint: disable=invalid-name
  def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
    """
    Visit FunctionDef nodes to handle function annotations and body.
    
    Args:
      node: the FunctionDef AST node to process
    """
    # visit return annotation
    self.visit_annotation(node.returns)

    # visit positional and keyword arguments
    for arg in node.args.args + node.args.kwonlyargs:  # type: ast.AST
      self.visit(arg)

    # visit *args and **kwargs if present
    if node.args.vararg:
      # waiver: `ast.arg` is not in `ast.AST` union that `visit()` declares, but it is a valid AST node at runtime
      self.visit(node.args.vararg)  # type: ignore[arg-type]
    if node.args.kwarg:
      # waiver: `ast.arg` is not in `ast.AST` union that `visit()` declares, but it is a valid AST node at runtime
      self.visit(node.args.kwarg)  # type: ignore[arg-type]

    # handle default values for positional arguments
    # these are runtime expressions and should be visited
    # guard: only process if there are defaults (avoid -0 slice returning all args)
    if node.args.defaults:
      positional_args_with_defaults = zip(
          node.args.args[-len(node.args.defaults):],  # only the args with defaults
          node.args.defaults,  # default values (aligned from the end)
          strict = True
      )
      for _, default_1 in positional_args_with_defaults:
        # waiver: `ast.expr` is not in the declared `visit()` param type, but all expr nodes are valid AST nodes
        self.visit(default_1) # type: ignore[arg-type]

    # handle default values for keyword-only arguments
    kwonly_args_with_defaults = zip(
        node.args.kwonlyargs,
        node.args.kw_defaults,
        strict = True
    )
    for _, default_2 in kwonly_args_with_defaults:
      if isinstance(default_2, ast.expr):
        # waiver: `ast.expr` is not in the declared `visit()` param type, but all expr nodes are valid AST nodes
        self.visit(default_2)  # type: ignore[arg-type]

    # visit the function body (runtime content)
    for stmt in node.body:  # type: ast.AST
      self.visit(stmt)


  # waiver: ast visitor methods must use `visit_<NodeType>` naming (PascalCase suffix required by ast.NodeVisitor)
  # pylint: disable=invalid-name
  def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
    """
    Visit AnnAssign nodes to handle annotated assignments.
    
    Args:
      node: the AnnAssign AST node to process
    """
    # visit the annotation part of the assignment
    self.visit_annotation(node.annotation)

    # visit the assigned value (runtime usage)
    if node.value:
      # waiver: `ast.expr` is not in the declared `visit()` param type, but all expr nodes are valid AST nodes
      self.visit(node.value)  # type: ignore[arg-type]


  def visit_arg(self, node: ast.arg) -> None:
    """
    Visit arg nodes to handle function argument annotations.
    
    Args:
      node: the arg AST node to process
    """
    # visit argument annotation if present
    self.visit_annotation(node.annotation)


  def visit_annotation(self, annotation: ast.expr | None) -> None:
    """
    Visit type annotations to track names used in type contexts.
    
    Args:
      annotation: the annotation expression to a process or None
    """
    # guard: skip if no annotation
    if annotation is None:
      return

    # guard: skip pure `TypeAlias` itself — it's never a type-only import
    if isinstance(annotation, ast.Name) and annotation.id == 'TypeAlias':
      return

    # switch to annotation context
    prev = self._in_annotation
    self._in_annotation = True

    # visit all parts of the annotation
    if isinstance(annotation, ast.Name):
      self.ann_refs.add(annotation.id)
    elif isinstance(annotation, ast.Subscript):
      self.visit_annotation(annotation.value)
      self.visit_annotation(annotation.slice)
    elif isinstance(annotation, ast.Tuple):
      for elt in annotation.elts:
        self.visit_annotation(elt)
    else:
      self.visit(annotation)

    # restore context
    self._in_annotation = prev


  # waiver: ast visitor methods must use `visit_<NodeType>` naming (PascalCase suffix required by ast.NodeVisitor)
  # pylint: disable=invalid-name
  def visit_Call(self, node: ast.Call) -> None:
    """
    Visit Call nodes to handle runtime type checks like isinstance and issubclass.
    
    Args:
      node: the Call AST node to process
    """
    # handle isinstance and issubclass runtime type checks
    if isinstance(node.func, ast.Name) and node.func.id in { 'isinstance', 'issubclass' }:
      if len(node.args) >= 2:
        self._mark_runtime_types(node.args[1])

    # continue visiting subnodes
    self.generic_visit(node)


  def _mark_runtime_types(self, node: ast.expr) -> None:
    """
    Mark types as runtime-used when passed to isinstance or issubclass.
    
    Args:
      node: the expression node containing type references
    """
    # record runtime use of types passed to isinstance or issubclass
    if isinstance(node, ast.Name):
      self.runtime_refs.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
      for elt in node.elts:
        self._mark_runtime_types(elt)
    elif isinstance(node, ast.Subscript):
      self._mark_runtime_types(node.value)
    elif isinstance(node, ast.Attribute):
      self.runtime_refs.add(node.attr)


def _line_matches(source_lines: list[str], lineno: int, pattern: re.Pattern[str]) -> bool:
  """
  Check whether a waiver pattern applies to a given line.

  A pattern applies when it matches inline on the line itself or on any line of the
  contiguous block of `#` comment lines immediately above it (multi-line waiver block).

  Args:
    source_lines: list of source code lines.
    lineno: the 1-based line number to check.
    pattern: the compiled regex to match against candidate lines.

  Returns:
    True if the pattern matches inline or in the comment block directly above.
  """
  idx = lineno - 1

  # check inline on the line itself
  if 0 <= idx < len(source_lines) and pattern.search(source_lines[idx]):
    return True

  # walk up through the contiguous block of comment-only lines directly above
  prev = idx - 1
  while prev >= 0:
    stripped = source_lines[prev].strip()
    # guard: stop at the first non-comment line — the block ends here
    if not stripped.startswith('#'):
      break
    if pattern.search(source_lines[prev]):
      return True
    prev -= 1

  return False


def _waiver_status(source_lines: list[str], header_line: int, name_line: int) -> str:
  """
  Classify how a waiver comment affects a type-only import finding.

  A finding is silenced when a valid waiver covers either the imported name's own
  line (silences that name) or the import statement's header line (silences every
  name in the block). A waiver marker with an empty reason never silences.

  Args:
    source_lines: list of source code lines.
    header_line: 1-based line of the `import` / `from ... import (` statement.
    name_line: 1-based line of the specific imported name.

  Returns:
    `waived` when a valid waiver applies, `invalid` when only an empty-reason
    waiver marker applies, `active` otherwise.
  """
  # guard: a valid waiver on the name line or the block header silences the finding
  if _line_matches(source_lines, name_line, WAIVER_RE) \
      or _line_matches(source_lines, header_line, WAIVER_RE):
    return 'waived'

  # guard: an empty-reason waiver marker is present but does not silence
  if _line_matches(source_lines, name_line, WAIVER_MARKER_RE) \
      or _line_matches(source_lines, header_line, WAIVER_MARKER_RE):
    return 'invalid'

  return 'active'


def analyze_file(
    path: str
) -> tuple[list[tuple[int, str | None, str]], str | None, int, list[tuple[int, str | None, str]]]:
  """
  Analyze a Python file to identify type-only import opportunities.

  Args:
    path: path to the Python file to analyze

  Returns:
    Tuple of active suggestions, optional warning message, waived-finding count,
    and the list of findings carrying an invalid (empty-reason) waiver marker.
  """
  # imports that must always be in the main scope even if only used in annotations
  runtime_required = {'InitVar'}

  # read and parse the file into an AST
  with open(path, 'r', encoding = 'utf-8') as f:
    source = f.read()
  tree = ast.parse(source, filename = path)
  source_lines = source.splitlines()

  # initialize and apply the analyzer
  analyzer = TypeOnlyImportAnalyzer()
  analyzer.visit(tree)

  # partition type-only findings by waiver status; the note keeps the import
  # statement line (header) so output is unchanged for waiver-free files
  suggestions: list[tuple[int, str | None, str]] = []
  invalid: list[tuple[int, str | None, str]] = []
  waived = 0
  for name, (mod, header_line, name_line) in analyzer.imported_names.items():
    # guard: only names used solely in annotations are candidates
    if name not in analyzer.ann_refs or name in analyzer.runtime_refs or name in runtime_required:
      continue
    status = _waiver_status(source_lines, header_line, name_line)
    if status == 'waived':
      waived += 1
      continue
    if status == 'invalid':
      invalid.append((header_line, mod, name))
    suggestions.append((header_line, mod, name))

  # emit a warning if TYPE_CHECKING is used but future import is missing
  warning = None
  if analyzer.has_type_checking_block and not analyzer.has_future_annotations:
    relpath = os.path.relpath(path, start = os.getcwd())
    warning = f'{relpath}:1: warning: uses TYPE_CHECKING but lacks `from __future__ import annotations`'

  return suggestions, warning, waived, invalid


def walk_dir(
    root: str, exclude_substrings: list[str]
) -> tuple[SuggestionsMap, list[str], int, int, SuggestionsMap]:
  """
  Walk the directory tree and analyze all Python files for type-only imports.

  Args:
    root: root directory path to scan
    exclude_substrings: list of substrings to exclude from file paths

  Returns:
    Tuple of suggestion map, warning list, files-processed count, total waived
    count, and the map of findings carrying an invalid (empty-reason) waiver.
  """
  # initialize containers for results and warnings
  all_suggestions: SuggestionsMap = defaultdict(list)
  invalid_map: SuggestionsMap = defaultdict(list)
  warnings: list[str] = []
  files_processed = 0
  total_waived = 0

  # combine hardcoded and user-provided exclusions
  all_excludes = HARDCODED_EXCLUDES + exclude_substrings

  # recursively walk directory and process all .py files
  for dirpath, _, filenames in os.walk(root):
    for fname in filenames:
      if fname.endswith('.py'):
        path = os.path.join(dirpath, fname)
        # guard: skip files matching any exclusion substring
        if any(sub in path for sub in all_excludes):
          continue
        try:
          suggestions, warning, waived, invalid = analyze_file(path)
          files_processed += 1
          total_waived += waived
          if suggestions:
            all_suggestions[path].extend(suggestions)
          if invalid:
            invalid_map[path].extend(invalid)
          if warning:
            warnings.append(warning)
        except SyntaxError as e:
          print(f'[!] Syntax error in {path}: {e}', file = sys.stderr)

  return all_suggestions, warnings, files_processed, total_waived, invalid_map


def main() -> None:
  """
  The main entry point for the type-only import analyzer CLI tool.
  
  Parse command line arguments, scan directories, and report findings.
  """
  # load configuration from pyproject.toml
  config = load_config()

  # setup CLI parser
  parser = argparse.ArgumentParser(description = "Detect type-only imports in Python files")
  parser.add_argument('path', nargs = '?', default = '.',
                      help = 'root directory to scan')
  parser.add_argument('--exclude', action = 'append', metavar = 'SUBSTRING',
                      help = 'exclude files or directories containing this substring')
  parser.add_argument('-v', '--verbose', action = 'store_true',
                      help = 'report the waived-finding count and invalid waiver markers')
  args = parser.parse_args()

  # get a path from CLI or use the current directory
  base_path = os.path.abspath(args.path)

  # get excludes from config, CLI args can extend the list
  config_excludes = list(config.get('exclude', []))

  # when a specific path is targeted, drop config exclusions that match the target
  # so that explicitly requested directories (e.g. tests/) are not silently skipped
  target_rel = os.path.relpath(base_path, start = os.getcwd())
  if target_rel != '.':
    target_parts = target_rel.rstrip('/').split('/')
    config_excludes = [ e for e in config_excludes
                        if e not in target_parts ]

  exclude_substrings = config_excludes
  if args.exclude:
    exclude_substrings.extend(args.exclude)

  # run analysis over a directory
  results, warnings, files_processed, total_waived, invalid_map = walk_dir(
      base_path, exclude_substrings
  )

  # print all suggestions in file:line format
  for filepath, suggestions in results.items():
    relpath = os.path.relpath(filepath, start = os.getcwd())
    for lineno, mod, name in suggestions:
      print(f'{relpath}:{lineno}: note: import {name} from {mod} is only used in type hints')

  # print all file-level warnings
  for warning in warnings:
    print(warning)

  # in verbose mode, flag empty-reason waiver markers and report the waived count
  if args.verbose:
    for filepath, findings in invalid_map.items():
      relpath = os.path.relpath(filepath, start = os.getcwd())
      for lineno, mod, name in findings:
        print(f'{relpath}:{lineno}: note: invalid waiver (empty reason) for import '
              f'{name} from {mod} — finding not suppressed')
    print(f'waived: {total_waived}')

  # print success message if no issues found
  if not results and not warnings:
    print(f'Success: no issues found in {files_processed} source files')


# run main if this is the top-level script
if __name__ == '__main__':
  main()
