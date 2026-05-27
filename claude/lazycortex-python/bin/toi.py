from __future__ import annotations

import argparse
import ast
import os
import sys
# noinspection PyCompatibility
import tomllib

from collections import defaultdict

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# hardcoded exclusions that should never be scanned
HARDCODED_EXCLUDES = ['.venv', '__pycache__']


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

# define alias for (module, line number)
ImportInfo = tuple[str | None, int]

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

    # record each imported symbol and its source module
    for alias in node.names:
      name = alias.asname or alias.name
      self.imported_names[name] = (node.module, node.lineno)


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

    # record each import symbol and source module
    for alias in node.names:
      name = alias.asname or alias.name
      self.imported_names[name] = (alias.name, node.lineno)


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


def analyze_file(path: str) -> tuple[list[tuple[int, str | None, str]], str | None]:
  """
  Analyze a Python file to identify type-only import opportunities.
  
  Args:
    path: path to the Python file to analyze
    
  Returns:
    Tuple containing a suggestion list and optional warning message.
  """
  # imports that must always be in the main scope even if only used in annotations
  runtime_required = {'InitVar'}
  
  # read and parse the file into an AST
  with open(path, 'r', encoding = 'utf-8') as f:
    source = f.read()
  tree = ast.parse(source, filename = path)

  # initialize and apply the analyzer
  analyzer = TypeOnlyImportAnalyzer()
  analyzer.visit(tree)

  # collect type-only import suggestions, excluding runtime-required imports
  suggestions = [
    (lineno, mod, name)
    for name, (mod, lineno) in analyzer.imported_names.items()
    if name in analyzer.ann_refs and name not in analyzer.runtime_refs and name not in runtime_required
  ]

  # emit a warning if TYPE_CHECKING is used but future import is missing
  warning = None
  if analyzer.has_type_checking_block and not analyzer.has_future_annotations:
    relpath = os.path.relpath(path, start = os.getcwd())
    warning = f'{relpath}:1: warning: uses TYPE_CHECKING but lacks `from __future__ import annotations`'

  return suggestions, warning


def walk_dir(root: str, exclude_substrings: list[str]) -> tuple[SuggestionsMap, list[str], int]:
  """
  Walk the directory tree and analyze all Python files for type-only imports.
  
  Args:
    root: root directory path to scan
    exclude_substrings: list of substrings to exclude from file paths
    
  Returns:
    Tuple containing suggestion map, warning list, and files processed count.
  """
  # initialize containers for results and warnings
  all_suggestions: SuggestionsMap = defaultdict(list)
  warnings: list[str] = []
  files_processed = 0

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
          suggestions, warning = analyze_file(path)
          files_processed += 1
          if suggestions:
            all_suggestions[path].extend(suggestions)
          if warning:
            warnings.append(warning)
        except SyntaxError as e:
          print(f'[!] Syntax error in {path}: {e}', file = sys.stderr)

  return all_suggestions, warnings, files_processed


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
  results, warnings, files_processed = walk_dir(base_path, exclude_substrings)

  # print all suggestions in file:line format
  for filepath, suggestions in results.items():
    relpath = os.path.relpath(filepath, start = os.getcwd())
    for lineno, mod, name in suggestions:
      print(f'{relpath}:{lineno}: note: import {name} from {mod} is only used in type hints')

  # print all file-level warnings
  for warning in warnings:
    print(warning)

  # print success message if no issues found
  if not results and not warnings:
    print(f'Success: no issues found in {files_processed} source files')


# run main if this is the top-level script
if __name__ == '__main__':
  main()
