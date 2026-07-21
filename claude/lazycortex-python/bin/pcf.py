"""
Python Code Format checker for Python files.

Check code formatting according to project guidelines:
- Import organization (block order, blank lines, TYPE_CHECKING separation)
- Docstring formatting (line length, section order, formatting rules)
- Other code format guidelines from Documentation Standards
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
import tokenize
# noinspection PyCompatibility
import tomllib

from collections import defaultdict
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# hardcoded exclusions that should never be scanned
HARDCODED_EXCLUDES = ['.venv', '__pycache__']

# default configuration values
DEFAULT_CONFIG = {
  'max_line_length': 117,
  'check_imports': True,
  'check_docstrings': True,
  'check_docstring_content': True,
  'check_line_length': True,
  'check_code_format': True,
  'check_assert': True,
  'check_magic_literal': True,
  # extra docstring-content patterns rejected as banned (substring match, any section).
  # populated from pyproject.toml [tool.pcf] banned_docstring_phrases.
  'banned_docstring_phrases': [],
  # consumer-registered docstring sections, each {name, style, after|before, ref_exempt}.
  # populated from pyproject.toml [tool.pcf] extra_docstring_sections.
  'extra_docstring_sections': [],
  # class attribute names whose declaration exempts a class from D2 (private labels in Attributes:).
  # populated from pyproject.toml [tool.pcf] d2_exempt_marker_attrs.
  'd2_exempt_marker_attrs': [],
  # private identifiers tolerated in docstring narrative by D9.
  # populated from pyproject.toml [tool.pcf] private_name_allowlist.
  'private_name_allowlist': [],
  # extra numeric values never flagged as magic, merged onto the built-in trivial set.
  # populated from pyproject.toml [tool.pcf] allowed_magic_numbers (e.g. angle constants).
  'allowed_magic_numbers': [],
  # extra string values never flagged as magic, merged onto the built-in trivial set.
  # populated from pyproject.toml [tool.pcf] allowed_magic_strings.
  'allowed_magic_strings': [],
}


def load_config(start_path: str | None = None) -> dict:
  """
  Load configuration from pyproject.toml.

  Search for pyproject.toml starting from the given path and moving up to parent directories.

  Args:
    start_path: starting a directory path to search for pyproject.toml.

  Returns:
    Configuration dictionary with default values overridden by pyproject.toml settings.
  """
  config: dict = DEFAULT_CONFIG.copy()

  # determine a starting path
  if start_path is None:
    start_path = os.getcwd()

  # search for pyproject.toml in parent directories
  current = Path(start_path).resolve()
  pyproject_path = None

  while current != current.parent:
    candidate = current / 'pyproject.toml'
    if candidate.exists():
      pyproject_path = candidate
      break
    current = current.parent

  # load configuration if pyproject.toml found
  if pyproject_path:
    try:
      with open(pyproject_path, 'rb') as f:
        pyproject = tomllib.load(f)
      pcf_config = pyproject.get('tool', {}).get('pcf', {})
      config.update(pcf_config)
      config['_project_root'] = str(pyproject_path.parent)
    except (OSError, tomllib.TOMLDecodeError):
      pass

  return config


def resolve_config_for_file(base_config: dict,
                            file_path: str,
                            project_root: str) -> dict:
  """
  Resolve the effective config for a file by applying per-folder overrides.

  Args:
    base_config: base configuration dictionary from `load_config`.
    file_path: absolute path to the file being analyzed.
    project_root: absolute path to the project root directory.

  Returns:
    Configuration dictionary with matching overrides applied.
  """
  overrides = base_config.get('overrides', {})

  # guard: no overrides configured
  if not overrides:
    return base_config

  rel_path = os.path.relpath(file_path, project_root)

  # start with base config excluding the overrides key
  effective = { k: v for k, v in base_config.items() if k != 'overrides' }

  # apply matching overrides (last-match-wins)
  for pattern, override_values in overrides.items():
    prefix = pattern.rstrip('/')
    if rel_path.startswith(prefix + '/') or rel_path == prefix:
      effective.update(override_values)

  return effective


# type alias for a suggestion map
SuggestionsMap = dict[str, list[tuple[int, str]]]

# known third-party packages (common ones in this project)
THIRD_PARTY_PACKAGES = frozenset({
  'numpy', 'np', 'torch', 'pandas', 'pd', 'requests', 'flask', 'fastapi',
  'pydantic', 'pytest', 'hypothesis', 'google', 'firebase_admin', 'openai',
  'anthropic', 'PIL', 'cv2', 'scipy', 'sklearn', 'tensorflow', 'keras',
  'matplotlib', 'seaborn', 'yaml', 'json5', 'toml', 'dotenv', 'uvicorn',
  'starlette', 'httpx', 'aiohttp', 'asyncio', 'celery', 'redis', 'sqlalchemy',
  'alembic', 'boto3', 'botocore', 'paramiko', 'cryptography', 'jwt', 'bcrypt',
  'passlib', 'email_validator', 'phonenumbers', 'pytz', 'dateutil', 'arrow',
  'slack_sdk', 'twilio', 'stripe', 'sendgrid', 'mailchimp',
})

# standard library modules (Python 3.12)
# noinspection SpellCheckingInspection
STDLIB_MODULES = frozenset({
  'abc', 'argparse', 'array', 'ast', 'asyncio', 'atexit', 'base64', 'bisect',
  'builtins', 'calendar', 'cmath', 'codecs', 'collections', 'colorsys',
  'concurrent', 'configparser', 'contextlib', 'copy', 'csv', 'ctypes',
  'dataclasses', 'datetime', 'decimal', 'difflib', 'dis', 'email', 'enum',
  'errno', 'faulthandler', 'filecmp', 'fileinput', 'fnmatch', 'fractions',
  'ftplib', 'functools', 'gc', 'getopt', 'getpass', 'gettext', 'glob',
  'graphlib', 'gzip', 'hashlib', 'heapq', 'hmac', 'html', 'http', 'imaplib',
  'importlib', 'inspect', 'io', 'ipaddress', 'itertools', 'json', 'keyword',
  'linecache', 'locale', 'logging', 'lzma', 'mailbox', 'math', 'mimetypes',
  'mmap', 'multiprocessing', 'netrc', 'numbers', 'operator', 'os', 'pathlib',
  'pdb', 'pickle', 'pkgutil', 'platform', 'plistlib', 'poplib', 'posixpath',
  'pprint', 'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr',
  'queue', 'quopri', 'random', 're', 'readline', 'reprlib', 'rlcompleter',
  'runpy', 'sched', 'secrets', 'select', 'selectors', 'shelve', 'shlex',
  'shutil', 'signal', 'site', 'smtpd', 'smtplib', 'sndhdr', 'socket',
  'socketserver', 'sqlite3', 'ssl', 'stat', 'statistics', 'string', 'stringprep',
  'struct', 'subprocess', 'sunau', 'symtable', 'sys', 'sysconfig', 'syslog',
  'tabnanny', 'tarfile', 'telnetlib', 'tempfile', 'termios', 'test', 'textwrap',
  'threading', 'time', 'timeit', 'tkinter', 'token', 'tokenize', 'tomllib',
  'trace', 'traceback', 'tracemalloc', 'tty', 'turtle', 'turtledemo', 'types',
  'typing', 'unicodedata', 'unittest', 'urllib', 'uu', 'uuid', 'venv',
  'warnings', 'wave', 'weakref', 'webbrowser', 'winreg', 'winsound', 'wsgiref',
  'xdrlib', 'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib',
  '_thread', '__future__',
})

# regex matching any error-suppression directive (used to distinguish suppression
# comments from plain justification comments).  PyCharm `# noinspection` directives
# are included, so they are not mistaken for justifications, but they are never
# flagged as forbidden suppressions.
SUPPRESSION_RE = re.compile(
  r'#\s*(?:type:\s*ignore|noqa|pylint:\s*disable(?:-next)?|noinspection)\b[^\n#]*'
)

# regex matching a waiver comment with non-empty explanation text
WAIVER_RE = re.compile(r'#\s*waiver:\s*\S')

# regex matching a TMP marker comment (with or without colon)
TMP_RE = re.compile(r'#\s*TMP\b')


_BROAD_EXCEPTION_NAMES = {"Exception", "BaseException"}


def _except_handler_catches_broadly(handler_type: ast.expr | None) -> bool:
  """
  Determine whether an except-handler clause catches `Exception` / `BaseException` / bare-except.

  Bare `except:` clauses have `handler_type is None`; `except Exception` / `except BaseException`
  are `ast.Name` nodes; `except (Exception, ValueError)` is an `ast.Tuple` whose elements include
  at least one broad name. Any of these is "broad" for the silent-swallow check.

  Args:
    handler_type: The `type` attribute of an `ast.ExceptHandler` — `None` for bare-except,
      an `ast.Name` for a single class, or an `ast.Tuple` for a multi-class clause.

  Returns:
    `True` when the handler catches `Exception` or `BaseException` (or is bare-except);
    `False` for narrower clauses such as `except OSError`.
  """
  # guard: bare except — by definition catches everything
  if handler_type is None:
    return True
  if isinstance(handler_type, ast.Name):
    return handler_type.id in _BROAD_EXCEPTION_NAMES
  if isinstance(handler_type, ast.Tuple):
    return any(
        isinstance(el, ast.Name) and el.id in _BROAD_EXCEPTION_NAMES
        for el in handler_type.elts
    )
  return False


def _except_handler_body_is_silent(body: list[ast.stmt]) -> bool:
  """
  Determine whether an except-handler body is a silent swallow (only `pass`).

  An expert handler body is "silent" when its sole executable statement is `pass` — it
  logs nothing, returns nothing, raises nothing, calls no notifier. Bodies with any other
  statement (`return`, `raise`, a call expression, an assignment) are NOT silent and are
  outside the check's scope. Pure-comment bodies are unreachable in Python (the parser
  injects an `ast.Pass` so the function lists exactly one statement when authors wrote
  only comments inside the handler).

  Args:
    body: The `body` attribute of an `ast.ExceptHandler` — the list of statements inside
      the `except` block.

  Returns:
    `True` when the body is exactly `[Pass()]`; `False` otherwise.
  """
  return len(body) == 1 and isinstance(body[0], ast.Pass)


def _has_waiver(source_lines: list[str], lineno: int) -> bool:
  """
  Check whether a source line has a waiver comment nearby.

  A waiver is a `# waiver: <explanation>` comment found:
  - Inline on the line itself, on the line immediately above, or immediately below.
  - As a class-level waiver: a comment at body indent level anywhere in the class
    body, covering all direct class-body statements (not code inside methods).

  Args:
    source_lines: list of source code lines.
    lineno: the 1-based line number to check.

  Returns:
    True if a waiver comment with explanation text is present, False otherwise.
  """
  idx = lineno - 1

  # check inline on the line itself
  if idx < len(source_lines) and WAIVER_RE.search(source_lines[idx]):
    return True

  # check the line immediately above (covers inline waivers like
  # `@overload  # waiver: ...` above a def signature)
  prev_idx = idx - 1
  if prev_idx >= 0 and WAIVER_RE.search(source_lines[prev_idx]):
    return True

  # walk further up through contiguous comment-only lines to support
  # multi-line waivers (`# waiver: ...` followed by `# ...` continuation
  # lines before the suppression directive)
  prev_idx -= 1
  while prev_idx >= 0:
    prev_stripped = source_lines[prev_idx].strip()
    if not prev_stripped.startswith('#'):
      break
    if WAIVER_RE.search(source_lines[prev_idx]):
      return True
    prev_idx -= 1

  # check the line below
  next_idx = idx + 1
  if next_idx < len(source_lines) and WAIVER_RE.search(source_lines[next_idx]):
    return True

  # check for class-level waiver
  if _has_class_level_waiver(source_lines, lineno):
    return True

  return False


def _has_tmp_marker_at_line(source_lines: list[str], lineno: int) -> bool:
  """
  Check whether the source line at `lineno` (1-based) carries an inline `# TMP` marker.

  Args:
    source_lines: list of source code lines.
    lineno: the 1-based line number to check.

  Returns:
    True if the line itself has a `# TMP` comment (inline or standalone).
  """
  idx = lineno - 1
  # guard: out-of-range lineno
  if idx < 0 or idx >= len(source_lines):
    return False
  return bool(TMP_RE.search(source_lines[idx]))


def _has_class_level_waiver(source_lines: list[str], lineno: int) -> bool:
  """
  Check whether the enclosing class has a class-level waiver covering this line.

  A class-level waiver is a `# waiver: <explanation>` comment at body indent
  level anywhere in the class body (outside methods). It covers all direct
  class-body statements but not code inside methods.

  Args:
    source_lines: list of source code lines.
    lineno: the 1-based line number to check.

  Returns:
    True if a class-level waiver covers this line, False otherwise.
  """
  idx = lineno - 1
  line = source_lines[idx]
  stripped = line.strip()

  # guard: blank or comment-only lines don't need class waivers
  if not stripped or stripped.startswith('#'):
    return False

  current_indent = len(line) - len(line.lstrip())

  # guard: top-level lines can't be in a class body
  if current_indent < 2:
    return False

  class_indent = current_indent - 2

  # scan upward to find the enclosing class definition
  scan = idx - 1
  while scan >= 0:
    scan_line = source_lines[scan]
    scan_stripped = scan_line.strip()

    # skip blank lines
    if not scan_stripped:
      scan -= 1
      continue

    scan_indent = len(scan_line) - len(scan_line.lstrip())

    # guard: def/async def at current indent → inside a method, not class body
    if scan_indent == current_indent and (
      scan_stripped.startswith(('def ', 'async def '))
    ):
      return False

    # found class definition at expected parent indent
    if scan_indent == class_indent and scan_stripped.startswith('class '):
      return _check_class_def_waiver(source_lines, scan)

    # hit non-class code at or below expected class indent → left the class scope
    if scan_indent <= class_indent and not scan_stripped.startswith(
      ('#', '@', ')', '"""', "'''")
    ):
      # guard: allow multi-line class definitions (continuation lines)
      if not scan_stripped.startswith('class '):
        return False

    scan -= 1

  return False


def _check_class_def_waiver(source_lines: list[str], class_idx: int) -> bool:
  """
  Check for a class-level waiver anywhere in the class body.

  Scans past the class definition line and its docstring, then looks for
  `# waiver:` comments at body indent level anywhere in the class body.
  Returns True if found.

  Args:
    source_lines: list of source code lines.
    class_idx: 0-based index of the `class` definition line.

  Returns:
    True if a class-level waiver is present, False otherwise.
  """
  class_indent = len(source_lines[class_idx]) - len(source_lines[class_idx].lstrip())
  body_indent = class_indent + 2

  scan = class_idx + 1
  in_docstring = False
  docstring_delim: str | None = None
  past_docstring = False

  while scan < len(source_lines):
    line = source_lines[scan]
    stripped = line.strip()

    # skip blank lines
    if not stripped:
      scan += 1
      continue

    # handle docstring detection and traversal
    if not past_docstring:
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delim = stripped[:3]
          # single-line docstring
          if stripped.count(docstring_delim) >= 2 and len(stripped) > 3:
            past_docstring = True
            scan += 1
            continue
          in_docstring = True
          scan += 1
          continue
        # no docstring — proceed to body scanning
        past_docstring = True
        # fall through to check this line
      else:
        if docstring_delim and stripped.endswith(docstring_delim):
          in_docstring = False
          past_docstring = True
        scan += 1
        continue

    # past docstring: scan class body for waiver at body indent level
    line_indent = len(line) - len(line.lstrip())

    # guard: left class scope
    if line_indent <= class_indent and stripped:
      break

    # check for waiver at body indent
    if line_indent == body_indent and stripped.startswith('#') and WAIVER_RE.search(line):
      return True

    scan += 1

  return False


# import block types in expected order
class ImportBlockType:
  """
  Enum-like class for import block types.
  """

  FUTURE = 0        # from __future__ import annotations
  TYPING = 1        # from typing import ... (except TYPE_CHECKING)
  STDLIB = 2        # standard library imports
  THIRD_PARTY = 3   # third-party imports
  TIV_PROJECT = 4   # from tiv.* imports
  LOCAL = 5         # relative imports (from .*, from ..*)
  TYPE_CHECKING = 6 # from typing import TYPE_CHECKING + if TYPE_CHECKING block

  NAMES = {
    0: 'future',
    1: 'typing',
    2: 'stdlib',
    3: 'third-party',
    4: 'tiv-project',
    5: 'local',
    6: 'TYPE_CHECKING',
  }


# ----------------------------------------------------------------------------------------
# waiver: AST visitor methods must follow visit_NodeType naming convention required by ast.NodeVisitor
# pylint: disable=invalid-name
class ImportFormatAnalyzer(ast.NodeVisitor):
  """
  AST visitor that analyzes an import format according to project guidelines.

  Collects information about import statements and checks for format violations.
  """

  def __init__(self, 
               source_lines: list[str], 
               is_init_file: bool = False,
               file_path: str | None = None) -> None:
    """
    Initialize the import format analyzer.

    Args:
      source_lines: list of source code lines for blank line analysis.
      is_init_file: whether the file is an __init__.py file.
      file_path: path to the file being analyzed, used for parent module import checks.
    """
    # source lines for blank line analysis
    self.source_lines = source_lines
    self.is_init_file = is_init_file
    self.file_path = file_path

    # list of (line_number, block_type, node) for all imports
    self.imports: list[tuple[int, int, ast.Import | ast.ImportFrom]] = []

    # list of issues found: `(line_number, message)`
    self.issues: list[tuple[int, str]] = []

    # track if we're inside `TYPE_CHECKING` block
    self.in_type_checking_block = False

    # track TYPE_CHECKING import line
    self.type_checking_import_line: int | None = None

    # track if TYPE_CHECKING block exists
    self.has_type_checking_block = False

    # track the line number where `if TYPE_CHECKING` starts
    self.type_checking_block_line: int | None = None

    # track the last import line number
    self.last_import_line = 0

    # track the first import line number
    self.first_import_line: int | None = None

    # track the first non-import code line
    self.first_code_line: int | None = None

    # track scope depth (0 = module level)
    self.scope_depth = 0

    # track if `from __future__ import annotations` exists
    self.has_future_annotations = False


  def _classify_import(self, node: ast.Import | ast.ImportFrom) -> int:
    """
    Classify an import node into its block type.

    Args:
      node: the import AST node.

    Returns:
      The ImportBlockType constant for this import.
    """
    # handle TYPE_CHECKING block imports
    if self.in_type_checking_block:
      return ImportBlockType.TYPE_CHECKING

    # handle ImportFrom nodes
    if isinstance(node, ast.ImportFrom):
      module = node.module or ''

      # future imports
      if module == '__future__':
        return ImportBlockType.FUTURE

      # relative imports (check BEFORE module name checks to handle `from ..types`)
      if node.level > 0:
        return ImportBlockType.LOCAL

      # typing imports (from typing and from types)
      if module == 'typing':
        # check if this is just TYPE_CHECKING import
        names = [alias.name for alias in node.names]
        if names == ['TYPE_CHECKING']:
          return ImportBlockType.TYPE_CHECKING
        return ImportBlockType.TYPING

      # types module imports (treated as typing block per guidelines)
      if module == 'types':
        return ImportBlockType.TYPING

      # tiv project imports
      if module.startswith('tiv.') or module == 'tiv':
        return ImportBlockType.TIV_PROJECT

      # check top-level module
      top_module = module.split('.')[0]

      # third-party imports
      if top_module in THIRD_PARTY_PACKAGES:
        return ImportBlockType.THIRD_PARTY

      # stdlib imports
      if top_module in STDLIB_MODULES:
        return ImportBlockType.STDLIB

      # assume third-party for unknown
      return ImportBlockType.THIRD_PARTY

    # handle plain Import nodes
    if isinstance(node, ast.Import):
      for alias in node.names:
        module = alias.name.split('.')[0]

        # stdlib
        if module in STDLIB_MODULES:
          return ImportBlockType.STDLIB

        # third-party
        if module in THIRD_PARTY_PACKAGES:
          return ImportBlockType.THIRD_PARTY

        # tiv project
        if module == 'tiv':
          return ImportBlockType.TIV_PROJECT

      # assume third-party for unknown
      return ImportBlockType.THIRD_PARTY

    return ImportBlockType.STDLIB


  _SUPPRESSION_RE = SUPPRESSION_RE


  def _has_local_import_waiver(self, lineno: int) -> bool:
    """
    Check whether a local import has a waiver comment.

    Args:
      lineno: the 1-based line number of the import statement.

    Returns:
      True if a `# waiver:` comment with explanation is present, False otherwise.
    """
    return _has_waiver(self.source_lines, lineno)


  def visit_Import(self, node: ast.Import) -> None:
    """
    Visit an import statement.

    Args:
      node: the Import AST node.
    """
    # flag local (in-function) imports unless waived
    if self.scope_depth > 0:
      if not self._has_local_import_waiver(node.lineno):
        self.issues.append((
          node.lineno,
          "local (in-function) import -- all imports must be at module level"
          " (add '# waiver: <reason>' to exempt)"
        ))
      self.generic_visit(node)
      return

    # only track module-level imports before the first code line
    # (scope_depth == 0 or in TYPE_CHECKING block at module level)
    if self.first_code_line is None:
      block_type = self._classify_import(node)
      self.imports.append((node.lineno, block_type, node))
      # track first and last import lines
      if self.first_import_line is None:
        self.first_import_line = node.lineno
      self.last_import_line = max(self.last_import_line, node.lineno)
    self.generic_visit(node)


  def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
    """
    Visit an import-from statement.

    Args:
      node: the ImportFrom AST node.
    """
    # flag local (in-function) imports unless waived
    if self.scope_depth > 0:
      if not self._has_local_import_waiver(node.lineno):
        self.issues.append((
          node.lineno,
          "local (in-function) import -- all imports must be at module level"
          " (add '# waiver: <reason>' to exempt)"
        ))
      self.generic_visit(node)
      return

    # only track module-level imports before the first code line
    if self.first_code_line is None:
      block_type = self._classify_import(node)
      self.imports.append((node.lineno, block_type, node))
      # track first and last import lines
      if self.first_import_line is None:
        self.first_import_line = node.lineno
      self.last_import_line = max(self.last_import_line, node.lineno)

      # track TYPE_CHECKING import specifically
      if (node.module == 'typing' and
          not self.in_type_checking_block and
          len(node.names) == 1 and
          node.names[0].name == 'TYPE_CHECKING'):
        self.type_checking_import_line = node.lineno

      # track `from __future__ import annotations`
      if node.module == '__future__':
        names = [alias.name for alias in node.names]
        if 'annotations' in names:
          self.has_future_annotations = True

      # check for unnamed relative imports
      if node.level > 0 and not node.module:
        self.issues.append((
          node.lineno,
          "unnamed relative import detected (use 'from .module import X' instead of 'from . import X')"
        ))

      # check for wildcard imports outside __init__.py
      for alias in node.names:
        if alias.name == '*' and not self.is_init_file:
          self.issues.append((
            node.lineno,
            "wildcard import outside __init__.py"
          ))

    self.generic_visit(node)


  def visit_If(self, node: ast.If) -> None:
    """
    Visit an if statement to detect TYPE_CHECKING blocks.

    Args:
      node: the If AST node.
    """
    # check if this is a TYPE_CHECKING block at module level before the first code
    if (isinstance(node.test, ast.Name) and node.test.id == 'TYPE_CHECKING' and
        self.scope_depth == 0 and self.first_code_line is None):
      self.has_type_checking_block = True
      self.type_checking_block_line = node.lineno
      self.in_type_checking_block = True
      # visit the body
      for child in node.body:
        # waiver: ast.stmt is a subclass of AST but mypy does not see it
        self.visit(child) # type: ignore[arg-type]
      self.in_type_checking_block = False
      # update the last import line to include the block
      if node.body:
        last_stmt = node.body[-1]
        self.last_import_line = max(self.last_import_line, last_stmt.end_lineno or last_stmt.lineno)
    else:
      # record the first code line if this is not TYPE_CHECKING at module level
      if self.first_code_line is None and self.scope_depth == 0:
        self.first_code_line = node.lineno
      self.generic_visit(node)


  def visit_ClassDef(self, node: ast.ClassDef) -> None:
    """
    Visit a class definition to track the first code line and scope.

    Args:
      node: the ClassDef AST node.
    """
    if self.first_code_line is None and self.scope_depth == 0:
      self.first_code_line = node.lineno
    # increment scope depth and visit children
    self.scope_depth += 1
    self.generic_visit(node)
    self.scope_depth -= 1


  def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
    """
    Visit a function definition to track the first code line and scope.

    Args:
      node: the FunctionDef AST node.
    """
    if self.first_code_line is None and self.scope_depth == 0:
      self.first_code_line = node.lineno
    # increment scope depth and visit children
    self.scope_depth += 1
    self.generic_visit(node)
    self.scope_depth -= 1


  def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
    """
    Visit an async function definition to track the first code line and scope.

    Args:
      node: the AsyncFunctionDef AST node.
    """
    if self.first_code_line is None and self.scope_depth == 0:
      self.first_code_line = node.lineno
    # increment scope depth and visit children
    self.scope_depth += 1
    self.generic_visit(node)
    self.scope_depth -= 1


  def visit_Assign(self, node: ast.Assign) -> None:
    """
    Visit an assignment to track the first code line.

    Args:
      node: the Assign AST node.
    """
    if self.first_code_line is None:
      self.first_code_line = node.lineno


  def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
    """
    Visit an annotated assignment to track the first code line.

    Args:
      node: the AnnAssign AST node.
    """
    if self.first_code_line is None:
      self.first_code_line = node.lineno


  def visit_Expr(self, node: ast.Expr) -> None:
    """
    Visit an expression statement to track the first code line.

    Args:
      node: the Expr AST node.
    """
    # guard: skip module docstrings
    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
      return
    if self.first_code_line is None:
      self.first_code_line = node.lineno


  def _check_import_order(self) -> None:
    """
    Check that imports are in the correct block order.
    """
    # guard: imports exist
    if not self.imports:
      return

    # track the highest block type seen so far
    current_block_type = -1

    # in __init__.py files, collect wildcard import lines for special handling
    wildcard_import_lines: set[int] = set()
    if self.is_init_file:
      for ln, _bt, node in self.imports:
        if isinstance(node, ast.ImportFrom):
          if any(alias.name == '*' for alias in node.names):
            wildcard_import_lines.add(ln)

    for lineno, block_type, _node in self.imports:
      # skip TYPE_CHECKING block contents for order check (they have their own rules)
      if block_type == ImportBlockType.TYPE_CHECKING:
        # but check that TYPE_CHECKING comes after all other imports
        if current_block_type < ImportBlockType.TYPE_CHECKING - 1:
          # TYPE_CHECKING should be last
          pass
        continue

      # check block order
      if block_type < current_block_type:
        # special case for __init__.py files: allow tiv-project imports after
        # local wildcard imports (per guidelines, wildcard imports come first
        # after future imports, then other imports including tiv-project)
        if self.is_init_file and current_block_type == ImportBlockType.LOCAL:
          # check if the "local" block was actually wildcard imports
          # if so, allow tiv-project and other imports after it
          if wildcard_import_lines:
            # this is expected - tiv-project imports after wildcard imports
            current_block_type = max(current_block_type, block_type)
            continue

        expected = ImportBlockType.NAMES.get(current_block_type, 'unknown')
        actual = ImportBlockType.NAMES.get(block_type, 'unknown')
        self.issues.append((
          lineno,
          f"import block order violation: {actual} import after {expected} block"
        ))

      current_block_type = max(current_block_type, block_type)


  def _check_blank_lines(self) -> None:
    """
    Check blank line rules between import blocks.
    """
    # guard: at least two imports needed for blank line checks
    if not self.imports or len(self.imports) < 2:
      return

    # filter out TYPE_CHECKING block internal imports for this check
    # also filter out the standalone TYPE_CHECKING import (it's part of TYPE_CHECKING block)
    main_imports = [(ln, bt, n) for ln, bt, n in self.imports if bt != ImportBlockType.TYPE_CHECKING]
    # guard: at least two main imports needed
    if len(main_imports) < 2:
      return

    # collect line numbers of TYPE_CHECKING related imports to skip in blank line counting
    type_checking_lines = set()
    for ln, bt, n in self.imports:
      if bt == ImportBlockType.TYPE_CHECKING:
        type_checking_lines.add(ln)
        if hasattr(n, 'end_lineno') and n.end_lineno:
          for skip_ln in range(ln, n.end_lineno + 1):
            type_checking_lines.add(skip_ln)

    prev_line, prev_block, prev_node = main_imports[0]

    # track end line for multi-line imports
    def get_end_line(import_node: ast.Import | ast.ImportFrom, start_line: int) -> int:
      return import_node.end_lineno if import_node.end_lineno else start_line

    for lineno, block_type, node in main_imports[1:]:
      # check blank lines between different blocks
      if block_type != prev_block:
        # use the end line of previous import for multi-line imports
        prev_end_line = get_end_line(prev_node, prev_line)

        # check if there's a TYPE_CHECKING import between these blocks
        # if so, skip the blank line check as the TYPE_CHECKING import naturally
        # creates additional blank lines around it
        has_type_checking_between = False
        for check_line in range(prev_end_line + 1, lineno):
          if check_line in type_checking_lines:
            has_type_checking_between = True
            break

        if has_type_checking_between:
          # skip the blank line check when TYPE_CHECKING is between blocks
          prev_line = lineno
          prev_block = block_type
          prev_node = node
          continue

        # count blank lines between the end of previous import and start of current
        blank_count = 0
        for check_line in range(prev_end_line + 1, lineno):
          if check_line <= len(self.source_lines):
            line_content = self.source_lines[check_line - 1].strip()
            if not line_content:
              blank_count += 1

        # should be exactly 1 blank line between different blocks
        if blank_count == 0:
          self.issues.append((
            lineno,
            f"missing blank line before {ImportBlockType.NAMES.get(block_type, 'unknown')} import block"
          ))
        elif blank_count > 1:
          self.issues.append((
            lineno,
            f"too many blank lines ({blank_count}) "
            f"before {ImportBlockType.NAMES.get(block_type, 'unknown')} "
            f"import block (expected 1)"
          ))

      prev_line = lineno
      prev_block = block_type
      prev_node = node


  def _check_type_checking_separation(self) -> None:
    """
    Check that TYPE_CHECKING import is properly separated.
    """
    # guard: TYPE_CHECKING block exists
    if not self.has_type_checking_block:
      return

    # find TYPE_CHECKING import among typing imports
    typing_imports = [(ln, n) for ln, bt, n in self.imports
                      if bt == ImportBlockType.TYPING and isinstance(n, ast.ImportFrom)]

    for lineno, import_node in typing_imports:
      # guard: import_node must be ImportFrom (pre-filtered above)
      if not isinstance(import_node, ast.ImportFrom):
        continue
      names = [alias.name for alias in import_node.names]
      if 'TYPE_CHECKING' in names and len(names) > 1:
        self.issues.append((
          lineno,
          "TYPE_CHECKING must be imported separately from other typing imports"
        ))


  def _check_type_checking_adjacency(self) -> None:
    """
    Check that TYPE_CHECKING import is immediately followed by if TYPE_CHECKING block.

    Per guidelines: TYPE_CHECKING import must be placed just before the `if TYPE_CHECKING`:
    block with no blank lines or other code/imports between them.
    """
    # guard: both TYPE_CHECKING import and block lines are known
    if self.type_checking_import_line is None or self.type_checking_block_line is None:
      return

    # check for lines between import and of block
    import_line = self.type_checking_import_line
    block_line = self.type_checking_block_line

    # they should be adjacent (block_line = import_line + 1)
    if block_line != import_line + 1:
      # count blank lines and non-blank lines between them
      blank_count = 0
      non_blank_lines = []
      for check_line in range(import_line + 1, block_line):
        if check_line <= len(self.source_lines):
          line_content = self.source_lines[check_line - 1].strip()
          if not line_content:
            blank_count += 1
          else:
            non_blank_lines.append(check_line)

      # report non-blank lines (other imports or code) between them - more important
      if non_blank_lines:
        self.issues.append((
          self.type_checking_import_line,
          "'from typing import TYPE_CHECKING' must be placed immediately "
          "before 'if TYPE_CHECKING:' (found other code/imports between them)"
        ))
      elif blank_count > 0:
        # only report blank lines if there are no non-blank lines
        self.issues.append((
          block_line,
          f"no blank lines allowed between 'from typing import TYPE_CHECKING' "
          f"and 'if TYPE_CHECKING:' (found {blank_count})"
        ))


  def _classify_type_checking_import(self, node: ast.Import | ast.ImportFrom) -> int:
    """
    Classify an import inside the `TYPE_CHECKING` block to its logical block type.

    Args:
      node: the Import or ImportFrom AST node.

    Returns:
      The logical ImportBlockType constant for this import.
    """
    # handle ImportFrom nodes
    if isinstance(node, ast.ImportFrom):
      module = node.module or ''

      # relative imports (check BEFORE module name checks to handle `from ..types`)
      if node.level > 0:
        return ImportBlockType.LOCAL

      # typing imports (from typing and from types)
      if module in ('typing', 'types'):
        return ImportBlockType.TYPING

      # tiv project imports
      if module.startswith('tiv.') or module == 'tiv':
        return ImportBlockType.TIV_PROJECT

      # check top-level module
      top_module = module.split('.')[0]

      # third-party imports
      if top_module in THIRD_PARTY_PACKAGES:
        return ImportBlockType.THIRD_PARTY

      # stdlib imports
      if top_module in STDLIB_MODULES:
        return ImportBlockType.STDLIB

      # assume third-party for unknown
      return ImportBlockType.THIRD_PARTY

    # handle plain Import nodes (e.g., `import numpy as np`)
    if isinstance(node, ast.Import):
      for alias in node.names:
        module = alias.name.split('.')[0]

        # stdlib
        if module in STDLIB_MODULES:
          return ImportBlockType.STDLIB

        # third-party
        if module in THIRD_PARTY_PACKAGES:
          return ImportBlockType.THIRD_PARTY

        # tiv project
        if module == 'tiv':
          return ImportBlockType.TIV_PROJECT

      # assume third-party for unknown
      return ImportBlockType.THIRD_PARTY

    return ImportBlockType.THIRD_PARTY


  def _check_type_checking_block_blank_lines(self) -> None:
    """
    Check blank line rules between import blocks inside TYPE_CHECKING.

    Per guidelines: import blocks inside TYPE_CHECKING must also be separated
    by a single blank line, just like regular import blocks.
    """
    # guard: TYPE_CHECKING block exists
    if not self.has_type_checking_block:
      return

    # collect imports inside the `TYPE_CHECKING` block
    # exclude the `from typing import TYPE_CHECKING` import itself (it's not inside the block)
    # include both ast.Import and ast.ImportFrom nodes
    tc_imports = [(ln, n) for ln, bt, n in self.imports
                  if bt == ImportBlockType.TYPE_CHECKING
                  and isinstance(n, (ast.Import, ast.ImportFrom))
                  and ln != self.type_checking_import_line]

    # guard: at least two TYPE_CHECKING imports needed
    if len(tc_imports) < 2:
      return

    # classify each import and check blank lines between different blocks
    prev_line, prev_node = tc_imports[0]
    prev_block = self._classify_type_checking_import(prev_node)

    # track end line for multi-line imports
    def get_end_line(import_node: ast.Import | ast.ImportFrom, start_line: int) -> int:
      return import_node.end_lineno if import_node.end_lineno else start_line

    for lineno, node in tc_imports[1:]:
      block_type = self._classify_type_checking_import(node)

      # check blank lines between different blocks
      if block_type != prev_block:
        # use the end line of previous import for multi-line imports
        prev_end_line = get_end_line(prev_node, prev_line)

        # count blank lines between the end of previous import and start of current
        blank_count = 0
        for check_line in range(prev_end_line + 1, lineno):
          if check_line <= len(self.source_lines):
            line_content = self.source_lines[check_line - 1].strip()
            if not line_content:
              blank_count += 1

        # should be exactly 1 blank line between different blocks
        if blank_count == 0:
          self.issues.append((
            lineno,
            f"missing blank line before {ImportBlockType.NAMES.get(block_type, 'unknown')} "
            f"import block inside TYPE_CHECKING"
          ))
        elif blank_count > 1:
          self.issues.append((
            lineno,
            f"too many blank lines ({blank_count}) before {ImportBlockType.NAMES.get(block_type, 'unknown')} "
            f"import block inside TYPE_CHECKING (expected 1)"
          ))

      prev_line = lineno
      prev_block = block_type
      prev_node = node


  def _check_type_checking_block_order(self) -> None:
    """
    Check import block ordering inside TYPE_CHECKING.

    Per guidelines: imports inside TYPE_CHECKING must follow the same block order
    as regular imports: typing -> stdlib -> third-party -> tiv-project -> local.
    """
    # guard: TYPE_CHECKING block exists
    if not self.has_type_checking_block:
      return

    # collect imports inside the `TYPE_CHECKING` block (same filter as blank-line check)
    tc_imports = [(ln, n) for ln, bt, n in self.imports
                  if bt == ImportBlockType.TYPE_CHECKING
                  and isinstance(n, (ast.Import, ast.ImportFrom))
                  and ln != self.type_checking_import_line]

    # guard: at least two imports for order check
    if len(tc_imports) < 2:
      return

    # classify each import and track the highest block type seen so far
    highest_block = self._classify_type_checking_import(tc_imports[0][1])

    for lineno, node in tc_imports[1:]:
      block_type = self._classify_type_checking_import(node)

      if block_type < highest_block:
        self.issues.append((
          lineno,
          f"import block order violation inside TYPE_CHECKING: "
          f"{ImportBlockType.NAMES.get(block_type, 'unknown')} import after "
          f"{ImportBlockType.NAMES.get(highest_block, 'unknown')} block"
        ))
      elif block_type > highest_block:
        highest_block = block_type


  def _check_multiline_format(self) -> None:
    """
    Check multi-line format rules for tiv/local imports.

    Per guidelines: For imports from the `tiv` package or for local package imports
    always use multi-line with parentheses except for one item imports.
    """
    for lineno, block_type, node in self.imports:
      # guard: only check ImportFrom nodes
      if not isinstance(node, ast.ImportFrom):
        continue

      # to determine if this is a tiv or local import
      # for TYPE_CHECKING block imports, we need to re-classify to check the actual type
      is_tiv_or_local = block_type in (ImportBlockType.TIV_PROJECT, ImportBlockType.LOCAL)

      # also check imports inside `TYPE_CHECKING` block
      if block_type == ImportBlockType.TYPE_CHECKING:
        module = node.module or ''
        # check if it's a tiv import inside TYPE_CHECKING
        if module.startswith('tiv.') or module == 'tiv':
          is_tiv_or_local = True
        # check if it's a local (relative) import inside TYPE_CHECKING
        elif node.level > 0:
          is_tiv_or_local = True

      # guard: only check tiv or local imports
      if not is_tiv_or_local:
        continue

      # guard: only check imports with multiple items
      if len(node.names) <= 1:
        continue

      # check if this is a multi-line import (uses parentheses)
      # a single-line import will have the same start and end line
      start_line = node.lineno
      end_line = node.end_lineno or node.lineno

      if start_line == end_line:
        # single-line import with multiple items - violation!
        module = node.module or ''
        if node.level > 0:
          # relative import
          dots = '.' * node.level
          module_str = f"{dots}{module}" if module else dots
        else:
          module_str = module

        names = [alias.name for alias in node.names]
        self.issues.append((
          lineno,
          f"tiv/local import with multiple items must use multi-line format with parentheses: "
          f"'from {module_str} import {', '.join(names)}'"
        ))


  def _check_copyright_spacing(self) -> None:
    """
    Check for exactly 1 blank line between copyright comment and imports.

    The copyright header is a block of consecutive comment lines at the start
    of the file. There must be exactly 1 blank line between the last copyright
    comment line and the first import statement.
    """
    # guard: file has imports
    if self.first_import_line is None:
      return

    # find the end of the copyright comment block
    # copyright is a consecutive block of comment lines starting from line 1
    copyright_end_line = 0
    for line_idx, line in enumerate(self.source_lines):
      line_content = line.strip()
      # copyright lines start with #
      if line_content.startswith('#'):
        copyright_end_line = line_idx + 1  # 1-indexed
      else:
        # the first non-comment line ends the copyright block
        break

    # guard: copyright header found
    if copyright_end_line == 0:
      return

    # count blank lines between the copyright end and first import
    blank_count = 0
    for check_line in range(copyright_end_line + 1, self.first_import_line):
      if check_line <= len(self.source_lines):
        line_content = self.source_lines[check_line - 1].strip()
        if not line_content:
          blank_count += 1
        else:
          # found non-blank content between copyright and import
          break

    # require exactly 1 blank line between copyright and imports
    if blank_count != 1:
      self.issues.append((
        self.first_import_line,
        f"expected exactly 1 blank line between copyright comment and imports (found {blank_count})"
      ))


  def _check_trailing_blank_lines(self) -> None:
    """
    Check for exactly 2 blank lines between imports and code.

    The codebase uses separator lines (# ---...) before class definitions.
    There must be exactly 2 blank lines between the last import and either
    the separator line or the first code line.
    """
    # guard: file has both code and imports
    if self.first_code_line is None or self.last_import_line == 0:
      return

    # count blank lines between the last import and first non-blank content
    blank_count = 0
    separator_line = None
    for check_line in range(self.last_import_line + 1, self.first_code_line):
      if check_line <= len(self.source_lines):
        line_content = self.source_lines[check_line - 1].strip()
        if line_content.startswith('# ---'):
          separator_line = check_line
          break

        # found non-blank, non-separator content (e.g., comment)
        if line_content:
          break
        blank_count += 1

    # require exactly 2 blank lines before separator or code
    if blank_count != 2:
      target_line = separator_line if separator_line else self.first_code_line
      self.issues.append((
        target_line,
        f"expected exactly 2 blank lines after imports before code/separator (found {blank_count})"
      ))


  def _check_future_annotations(self) -> None:
    """
    Check that `from __future__ import annotations` is present.

    Per guidelines: each Python file MUST contain `from __future__ import annotations`.
    Skip __init__.py files as they are mainly for re-exporting.
    """
    # guard: skip __init__.py files
    if self.is_init_file:
      return

    if not self.has_future_annotations:
      self.issues.append((
        1,
        "missing required 'from __future__ import annotations' import"
      ))


  def _check_type_checking_block(self) -> None:
    """
    Check that the `if TYPE_CHECKING`:block is present.

    Per guidelines: each Python file MUST contain the `if TYPE_CHECKING` block.
    Skip __init__.py files as they are mainly for re-exporting.
    """
    # guard: skip __init__.py files
    if self.is_init_file:
      return

    if not self.has_type_checking_block:
      self.issues.append((
        1,
        "missing required 'if TYPE_CHECKING:' block"
      ))


  def _check_wildcard_import_position(self) -> None:
    """
    Check that wildcard imports in __init__.py files are properly positioned.

    Per guidelines: wildcard imports in __init__.py must come after
    `from __future__ import annotations` and before any other imports.
    """
    # guard: only check __init__.py files
    if not self.is_init_file:
      return

    # collect wildcard imports and other imports
    wildcard_imports: list[tuple[int, ast.ImportFrom]] = []
    future_import_line: int | None = None
    first_non_future_non_wildcard_line: int | None = None

    for lineno, block_type, node in self.imports:
      # guard: skip TYPE_CHECKING block imports
      if block_type == ImportBlockType.TYPE_CHECKING:
        continue

      # track future imports
      if block_type == ImportBlockType.FUTURE:
        future_import_line = lineno
        continue

      # check if this is a wildcard import
      if isinstance(node, ast.ImportFrom):
        is_wildcard = any(alias.name == '*' for alias in node.names)
        if is_wildcard:
          wildcard_imports.append((lineno, node))
          continue

      # track first non-future, non-wildcard import
      if first_non_future_non_wildcard_line is None:
        first_non_future_non_wildcard_line = lineno

    # check each wildcard import
    for lineno, node in wildcard_imports:
      # check that wildcard comes after future import
      if future_import_line is not None and lineno < future_import_line:
        self.issues.append((
          lineno,
          "wildcard import must come after 'from __future__ import annotations'"
        ))

      # check that wildcard comes before other imports
      if first_non_future_non_wildcard_line is not None and lineno > first_non_future_non_wildcard_line:
        self.issues.append((
          lineno,
          "wildcard import must come before any other non-future imports in __init__.py"
        ))


  def _check_parent_module_imports(self) -> None:
    """
    Check that files do not import from their parent module.

    Per guidelines: submodules should not import from parent modules.
    For example, `tiv.core.math` should not import from `tiv.core`,
    and relative imports should not go up to the parent package.
    Sibling imports like `from ..entity import X` are allowed.
    """
    # guard: file path provided
    if not self.file_path:
      return

    # normalize a path and extract module hierarchy
    norm_path = self.file_path.replace('\\', '/')

    # find the tiv module root
    tiv_idx = norm_path.find('/tiv/')
    # guard: file is inside tiv package
    if tiv_idx == -1:
      return

    # get the relative path from tiv root
    rel_path = norm_path[tiv_idx + 1:]  # e.g., "tiv/core/math/values.py"

    # remove the.py extension and convert to a module path
    if rel_path.endswith('.py'):
      rel_path = rel_path[:-3]

    # handle __init__.py files
    if rel_path.endswith('/__init__'):
      rel_path = rel_path[:-9]  # remove "/__init__"

    # convert path to module notation
    current_module = rel_path.replace('/', '.')  # e.g., "tiv.core.math.values"

    # get the parent module (the package containing this file)
    parts = current_module.split('.')
    # guard: module has at least two parts
    if len(parts) < 2:
      return

    # for a file like tiv/core/math/values.py, the package is tiv.core.math
    # and the parent package is tiv.core
    package_parts = parts[:-1]  # e.g., ["tiv", "core", "math"]
    # guard: package has at least two levels
    if len(package_parts) < 2:
      return

    # check each import
    for lineno, _, node in self.imports:
      # guard: only check ImportFrom nodes
      if not isinstance(node, ast.ImportFrom):
        continue

      # check absolute imports
      if node.level == 0 and node.module:
        import_parts = node.module.split('.')

        # check if import is from a parent package
        # e.g., for tiv/core/math/values.py (package: tiv.core.math)
        # importing from tiv.core is a parent import
        for depth in range(1, len(package_parts)):
          parent_parts = package_parts[:depth]
          if import_parts == parent_parts:
            self.issues.append((
              lineno,
              f"import from parent module '{node.module}' is not allowed"
            ))
            break

      # check relative imports that go to parent
      elif node.level > 0:
        # calculate the target package after going up `level` levels
        # e.g., for tiv/core/math/values.py (package: tiv.core.math)
        # level 1 = from current package (from .X import Y) - stays in tiv.core.math
        # level 2 = go up 1 level (from ..X import Y) - goes to tiv.core, then add X
        # level 3 = go up 2 levels (from ...X import Y) - goes to tiv, then add X

        # guard: level exceeds package depth
        if node.level > len(package_parts):
          continue

        # calculate the base package after going up (level - 1) levels
        #  1: stay at package_parts (no going up)
        # level 2: go up 1 level
        #  3: go up 2 levels
        levels_up = node.level - 1
        base_parts = package_parts[:len(package_parts) - levels_up]

        # if there's a module specified, add it to get the target
        if node.module:
          target_parts = base_parts + node.module.split('.')
        else:
          # no module means importing directly from the base (from .. import X)
          target_parts = base_parts

        # check if the target is a parent of the current package
        # a parent is any prefix of package_parts (excluding the full package itself)
        for depth in range(1, len(package_parts)):
          parent_parts = package_parts[:depth]
          if target_parts == parent_parts:
            if node.module:
              self.issues.append((
                lineno,
                f"relative import from parent module '{'.' * node.level}{node.module}' "
                f"resolves to '{'.'.join(target_parts)}' which is not allowed"
              ))
            else:
              self.issues.append((
                lineno,
                f"relative import from parent module (level {node.level}) is not allowed"
              ))
            break


  def analyze(self) -> list[tuple[int, str]]:
    """
    Run all checks and return a list of issues.

    Returns:
      List of (line_number, message) tuples for each issue found.
    """
    self._check_future_annotations()
    self._check_type_checking_block()
    self._check_copyright_spacing()
    self._check_import_order()
    self._check_blank_lines()
    self._check_type_checking_separation()
    self._check_type_checking_adjacency()
    self._check_type_checking_block_blank_lines()
    self._check_type_checking_block_order()
    self._check_multiline_format()
    self._check_wildcard_import_position()
    self._check_parent_module_imports()
    self._check_trailing_blank_lines()

    return sorted(self.issues, key = lambda x: x[0])


# ----------------------------------------------------------------------------------------
class CodeFormatAnalyzer:
  """
  Analyzer for code formatting according to project guidelines.

  Checks code formatting rules including line length, indentation, spacing around operators,
  and blank line rules between classes and methods.
  """

  def __init__(self,
               source_lines: list[str],
               *,
               max_line_length: int = 117,
               is_init_file: bool = False,
               check_line_length: bool = True,
               check_indentation: bool = True,
               check_assert: bool = True):
    """
    Initialize the CodeFormatAnalyzer.

    Args:
      source_lines: list of source code lines.
      max_line_length: maximum allowed line length.
      is_init_file: whether this is an __init__.py file.
      check_line_length: whether to check line length.
      check_indentation: whether to check indentation.
      check_assert: whether to check for assert statements.
    """
    self.source_lines = source_lines
    self.max_line_length = max_line_length
    self.is_init_file = is_init_file
    self.check_line_length = check_line_length
    self.check_indentation = check_indentation
    self.check_assert = check_assert
    self.issues: list[tuple[int, str]] = []


  def _check_line_length(self) -> None:
    """
    Check that code lines do not exceed the maximum length.

    Skip lines that are inside docstrings or are long string literals/URLs.
    """
    in_docstring = False
    docstring_delimiter = None

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.strip()

      # track docstring state
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delimiter = stripped[:3]
          # guard: single-line docstring
          if len(stripped) > 3 and stripped.endswith(docstring_delimiter):
            continue
          in_docstring = True
          continue
      else:
        if docstring_delimiter and stripped.endswith(docstring_delimiter):
          in_docstring = False
          docstring_delimiter = None
        continue

      # guard: skip empty lines and comment-only lines
      if not stripped or stripped.startswith('#'):
        continue

      # skip lines with long URLs or file paths
      # noinspection HttpUrlsUsage
      url_schemes = { 'http://', 'https://', 'file://' }
      # guard: skip lines with URLs
      if any(scheme in line for scheme in url_schemes):
        continue
      # guard: skip long string literals
      if stripped.startswith(('"', "'")):
        continue

      # check actual line length
      if len(line) > self.max_line_length:
        self.issues.append((
          line_num,
          f"line exceeds {self.max_line_length} chars ({len(line)} chars)"
        ))


  def _check_indentation(self) -> None:
    """
    Check that indentation uses two spaces.

    Per guidelines: use two spaces for indentation.
    """
    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1

      # guard: skip empty lines
      if not line.strip():
        continue

      # count leading spaces
      leading_spaces = len(line) - len(line.lstrip(' '))

      # skip lines that start with tabs (different error)
      if line.startswith('\t'):
        self.issues.append((
          line_num,
          "line uses tabs for indentation instead of spaces"
        ))
        continue

      # check if indentation is multiple of 2 (allowing for continuation lines)
      # continuation lines can have odd indentation for alignment
      # only check for clearly wrong indentation (1, 3 spaces at start of block)
      if leading_spaces == 1:
        self.issues.append((
          line_num,
          "indentation should use two spaces (found 1 space)"
        ))


  def _check_named_arg_spacing(self) -> None:
    """
    Check spacing around = in function calls with named arguments.

    Per guidelines: always put spaces around '=' in function calls with named arguments.
    """
    # pattern for named arguments without spaces: name=value (but not ==, !=, <=, >=)
    # this is a simplified check - full check would require AST analysis
    named_arg_pattern = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*=[^=]')

    in_docstring = False
    docstring_delimiter = None

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.strip()

      # track docstring state
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delimiter = stripped[:3]
          if not (len(stripped) > 3 and stripped.endswith(docstring_delimiter)):
            in_docstring = True
          continue
      else:
        if docstring_delimiter and stripped.endswith(docstring_delimiter):
          in_docstring = False
          docstring_delimiter = None
        continue

      # guard: skip comments
      if stripped.startswith('#'):
        continue

      # guard: skip function definitions
      if stripped.startswith(('def ', 'async def ')):
        continue

      # guard: skip class definitions
      if stripped.startswith('class '):
        continue

      # guard: skip assignment statements
      if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*', stripped):
        continue

      # guard: skip decorator lines
      if stripped.startswith('@'):
        continue

      # check for named arguments without spaces
      matches = named_arg_pattern.findall(line)
      for match in matches:
        # guard: skip dictionary-like patterns
        if ':' in line and '{' in line:
          continue
        self.issues.append((
          line_num,
          f"named argument should have spaces around '=' (found '{match[:-1]}')"
        ))
        break  # only report the first issue per line


  def _check_blank_lines_between_methods(self) -> None:
    """
    Check blank line rules between methods in classes.

    Per guidelines: use exactly 2 blank lines between any class method and other code.
    """
    in_class = False
    class_indent = 0
    prev_non_blank_line = 0
    blank_count = 0
    in_docstring = False
    docstring_delimiter = None

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.strip()

      # track docstring state
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delimiter = stripped[:3]
          if not (len(stripped) > 3 and stripped.endswith(docstring_delimiter)):
            in_docstring = True
          prev_non_blank_line = line_num
          blank_count = 0
          continue
      else:
        if docstring_delimiter and stripped.endswith(docstring_delimiter):
          in_docstring = False
          docstring_delimiter = None
        prev_non_blank_line = line_num
        blank_count = 0
        continue

      # count leading spaces
      leading_spaces = len(line) - len(line.lstrip()) if stripped else 0

      # detect class definition
      if stripped.startswith('class '):
        in_class = True
        class_indent = leading_spaces
        prev_non_blank_line = line_num
        blank_count = 0
        continue

      # if we're back to class indent level or less, we're out of the class
      if in_class and stripped and leading_spaces <= class_indent:
        if not stripped.startswith('class '):
          in_class = False

      # track blank lines
      if not stripped:
        blank_count += 1
        continue

      # check for method definition inside a class
      if in_class and stripped.startswith(('def ', 'async def ')):
        method_indent = leading_spaces
        # should be indented more than class
        if method_indent > class_indent:
          # check if the previous non-blank was not right after docstring or decorator
          if prev_non_blank_line > 0:
            prev_stripped = self.source_lines[prev_non_blank_line - 1].strip()
            # skip check if the previous line was class def, decorator, or docstring end
            if not (prev_stripped.startswith(('class ', '@')) or
                    prev_stripped.endswith(('"""', "'''"))):
              if blank_count != 2:
                self.issues.append((
                  line_num,
                  f"expected 2 blank lines before method (found {blank_count})"
                ))

      prev_non_blank_line = line_num
      blank_count = 0


  def _check_silent_broad_except(self) -> None:
    """
    Flag handlers that catch `Exception` / `BaseException` / bare-except AND swallow silently.

    A handler whose declared type is `Exception`, `BaseException`, or absent (bare `except:`),
    AND whose body consists only of `pass` (after stripping comments), hides every failure
    in the protected region including `KeyboardInterrupt`, logic bugs, and the very errors
    the project's error_ledger is meant to surface. Either narrow the exception class
    (`except OSError`, `except subprocess.CalledProcessError`, …) or do something in the
    body (log, return a typed status, re-raise). Exempt with `# waiver: <reason>` on the
    line above the `except` clause when the swallow is intentional per a documented contract
    (e.g. the error-ledger contract declares `error-record` to be fire-and-forget).
    """
    try:
      tree = ast.parse('\n'.join(self.source_lines))
    # waiver: AST parsing failures are reported by the py_compile check; pcf must not block on them
    except SyntaxError:
      return
    for node in ast.walk(tree):
      # guard: skip nodes that are not exception handlers
      if not isinstance(node, ast.ExceptHandler):
        continue
      # guard: skip handlers that declare a narrow exception class — only broad catches are flagged
      if not _except_handler_catches_broadly(node.type):
        continue
      # guard: skip handlers whose body does something (log, return, re-raise) — only silent swallows flag
      if not _except_handler_body_is_silent(node.body):
        continue
      line_num = node.lineno
      # guard: waiver comment present — exemption granted
      if _has_waiver(self.source_lines, line_num):
        continue
      self.issues.append((
        line_num,
        "silent broad-except: handler catches Exception/BaseException/bare-except and body is `pass` only"
        " -- narrow the exception class or do something in the body, or add a"
        " '# waiver: <reason>' comment to exempt"
      ))


  def _check_error_suppression(self) -> None:
    """
    Check for forbidden error suppression comments.

    Per project guidelines, `# type: ignore`, `# noqa`, `# pylint: disable`, and
    `# pylint: disable-next` are forbidden without explicit user approval.
    PyCharm `# noinspection` directives are ignored (not flagged).
    """
    suppression_pattern = re.compile(
      r'#\s*(?:type:\s*ignore|noqa|pylint:\s*disable(?:-next)?)\b'
    )
    in_docstring = False
    docstring_delimiter = None

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.strip()

      # track docstring state
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delimiter = stripped[:3]
          if not (len(stripped) > 3 and stripped.endswith(docstring_delimiter)):
            in_docstring = True
          continue
      else:
        if docstring_delimiter and stripped.endswith(docstring_delimiter):
          in_docstring = False
          docstring_delimiter = None
        continue

      # search for suppression patterns in code lines
      match = suppression_pattern.search(line)
      if match:
        # guard: waiver comment present — exemption granted
        if _has_waiver(self.source_lines, line_num):
          continue

        self.issues.append((
          line_num,
          f"error suppression comment found: '{match.group().strip()}'"
          " -- fix root cause or add a '# waiver: <reason>' comment to exempt"
        ))


  def _check_double_backticks(self) -> None:
    """
    Check for double backticks that should be single backticks.

    Per project guidelines, use single backticks for inline code references.
    Triple backticks (code fences) are allowed.
    """
    # match exactly two backticks that aren't preceded or followed by another backtick
    double_bt_pattern = re.compile(r'(?<!\x60)\x60\x60(?!\x60)')

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      if double_bt_pattern.search(line):
        self.issues.append((
          line_num,
          "double backticks found -- use single backticks for inline code references"
        ))


  def _check_guard_comments(self) -> None:
    """
    Check that guard clauses have a `# guard:` comment on the preceding line.

    Detect `if` statements inside method bodies whose body is a guard clause and flag
    if the preceding line does not contain `# guard:`. Two patterns are recognized:
    - Single-statement body: `return`, `return None`, `raise`, or `continue`.
    - Multi-statement body ending with `raise`: validation logic that builds an error
      message or records diagnostics before raising (but not normal branches that happen
      to end with `return` or `continue`).
    """
    lines = self.source_lines
    total = len(lines)

    for idx, line in enumerate(lines):
      stripped = line.strip()
      leading = len(line) - len(line.lstrip())

      # guard: only check inside method bodies (indentation >= 4 for 2-space style)
      if leading < 4:
        continue

      # guard: must be an `if` statement (not elif/else)
      if not stripped.startswith('if ') and not stripped.startswith('if('):
        continue

      # find the first non-blank body line to verify indentation
      next_idx = idx + 1
      while next_idx < total and not lines[next_idx].strip():
        next_idx += 1

      # guard: reached end of file
      if next_idx >= total:
        continue

      next_stripped = lines[next_idx].strip()
      next_leading = len(lines[next_idx]) - len(lines[next_idx].lstrip())

      # guard: body must be indented more than the `if`
      if next_leading <= leading:
        continue

      # check if the first body line is a single-statement guard pattern
      is_single_guard = (
        next_stripped in {'return', 'return None', 'continue'}
        or next_stripped.startswith(('return None  #', 'raise ', 'continue  #'))
      )

      is_guard = False
      if is_single_guard:
        # verify this is a single-statement body (next line returns to same or lower indent)
        after_idx = next_idx + 1
        while after_idx < total and not lines[after_idx].strip():
          after_idx += 1
        if after_idx >= total:
          is_guard = True
        else:
          after_leading = len(lines[after_idx]) - len(lines[after_idx].lstrip())
          # guard: single-stmt when the next line is back at or below `if` indent, or is elif/else
          if after_leading <= leading or lines[after_idx].strip().startswith(('elif ', 'else:')):
            is_guard = True
      else:
        # multi-statement body — only flag if the LAST body-level line is `raise` and the
        # body contains no control-flow (if/for/while/return/etc.). A true guard body is
        # only error setup (assignments, method calls, diagnostics) before the raise.
        _control_flow_prefixes = (
          'if ', 'if(', 'elif ', 'else:', 'for ', 'while ', 'with ',
          'return', 'continue', 'break', 'yield', 'try:', 'except', 'finally:',
        )
        scan_idx = next_idx
        last_body_idx = next_idx
        has_control_flow = False
        real_stmt_count = 0
        while scan_idx < total:
          scan_stripped = lines[scan_idx].strip()
          scan_leading = len(lines[scan_idx]) - len(lines[scan_idx].lstrip())
          # guard: blank lines inside the body — skip
          if not scan_stripped:
            scan_idx += 1
            continue
          # guard: line at or below the if-indent means we exited the body
          if scan_leading <= leading:
            break
          # only inspect body-level lines (not nested sub-blocks)
          if scan_leading == next_leading:
            if scan_stripped.startswith(_control_flow_prefixes):
              has_control_flow = True
            # count real code statements (not comments, not the raise itself)
            if not scan_stripped.startswith(('#', 'raise ')):
              real_stmt_count += 1
          last_body_idx = scan_idx
          scan_idx += 1

        last_stripped = lines[last_body_idx].strip()
        last_leading = len(lines[last_body_idx]) - len(lines[last_body_idx].lstrip())
        # guard: only `raise` at the body's own indentation qualifies, with no control-flow,
        # and at least one real code statement before the raise (not just comments)
        if (last_stripped.startswith('raise ')
            and last_leading == next_leading
            and not has_control_flow
            and real_stmt_count > 0):
          # guard: if followed by elif/else, this is a branch, not a guard
          if scan_idx < total and lines[scan_idx].strip().startswith(('elif ', 'else:')):
            pass
          else:
            is_guard = True

      # guard: not a guard pattern
      if not is_guard:
        continue

      # now check if the preceding comment block has `# guard:`
      # scan upward through consecutive comment lines to handle multi-line guard comments
      prev_idx = idx - 1
      while prev_idx >= 0 and not lines[prev_idx].strip():
        prev_idx -= 1
      found_guard_comment = False
      while prev_idx >= 0:
        prev_stripped = lines[prev_idx].strip()
        # guard: not a comment line — stop scanning
        if not prev_stripped.startswith('#'):
          break
        if '# guard:' in lines[prev_idx]:
          found_guard_comment = True
          break
        prev_idx -= 1

      # guard: preceding comment block already has guard comment
      if found_guard_comment:
        continue

      self.issues.append((
        idx + 1,
        "possible guard clause without '# guard:' comment on the preceding line"
      ))


  def _check_typing_cast(self) -> None:
    """
    Check for forbidden `typing.cast()` usage.

    Per project guidelines, `typing.cast()` has zero runtime validation and is forbidden.
    Use `obj.cast_to(TargetClass)` or `isinstance()` instead.
    """
    cast_import_re = re.compile(r'^\s*from\s+typing\s+import\s+.*\bcast\b')
    qualified_cast_re = re.compile(r'\btyping\.cast\s*\(')
    bare_cast_re = re.compile(r'\bcast\s*\(')

    in_docstring = False
    docstring_delimiter = None
    has_cast_import = False

    # first pass: detect whether `from typing import cast` is present
    for line in self.source_lines:
      if cast_import_re.match(line):
        has_cast_import = True
        break

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.strip()

      # track docstring state
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delimiter = stripped[:3]
          if not (len(stripped) > 3 and stripped.endswith(docstring_delimiter)):
            in_docstring = True
          continue
      else:
        if docstring_delimiter and stripped.endswith(docstring_delimiter):
          in_docstring = False
          docstring_delimiter = None
        continue

      # guard: skip comment-only lines
      if stripped.startswith('#'):
        continue

      # guard: skip string-only lines (continuation strings, string assignments)
      if stripped.startswith(('"', "'", 'f"', "f'", 'r"', "r'", 'b"', "b'")):
        continue

      # guard: waiver present — skip this line
      if _has_waiver(self.source_lines, line_num):
        continue

      # guard: import line — usage is checked at call sites
      if cast_import_re.match(line):
        continue

      # check for `typing.cast(...)` qualified calls
      if qualified_cast_re.search(line):
        self.issues.append((
          line_num,
          "typing.cast() is forbidden"
          " -- use obj.cast_to(TargetClass) or isinstance() instead"
          " (add '# waiver: <reason>' to exempt)"
        ))
        continue

      # check for bare `cast(...)` calls only when the import was detected
      if has_cast_import and bare_cast_re.search(line):
        code_before_cast = line[:line.find('cast')]
        # guard: skip lines where `cast` is part of a method call (e.g., `obj.cast(`)
        if code_before_cast.rstrip().endswith('.'):
          continue
        self.issues.append((
          line_num,
          "typing.cast() usage found"
          " -- use obj.cast_to(TargetClass) or isinstance() instead"
          " (add '# waiver: <reason>' to exempt)"
        ))


  def _check_raw_dunder_name(self) -> None:
    """
    Check for raw `__name__` access on class objects.

    Per project guidelines, `type(obj).__name__`, `self.__class__.__name__`,
    and `cls.__name__` are forbidden on CoreClass subclasses.
    Use `self.class_name`, `cls.get_class_name()`, `self.class_id`, etc.
    """
    # type(X).__name__ or type(X) .__name__
    type_name_re = re.compile(r'type\s*\([^)]*\)\s*\.\s*__name__')
    # X.__name__ where X ends with a word character (covers cls.__name__,
    # obj.__class__.__name__, self._val_cls.__name__, etc.)
    attr_name_re = re.compile(r'\w\s*\.\s*__name__')

    in_docstring = False
    docstring_delimiter = None

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.strip()

      # track docstring state
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delimiter = stripped[:3]
          if not (len(stripped) > 3 and stripped.endswith(docstring_delimiter)):
            in_docstring = True
          continue
      else:
        if docstring_delimiter and stripped.endswith(docstring_delimiter):
          in_docstring = False
          docstring_delimiter = None
        continue

      # guard: skip comment-only lines
      if stripped.startswith('#'):
        continue

      # guard: skip plain string-only lines but NOT f-strings (f-strings contain expressions)
      if (stripped.startswith(('"', "'", 'r"', "r'", 'b"', "b'"))
          and not stripped.startswith(('f"', "f'"))):
        continue

      # guard: waiver present — skip this line
      if _has_waiver(self.source_lines, line_num):
        continue

      # guard: no __name__ pattern on this line
      if not (type_name_re.search(line) or attr_name_re.search(line)):
        continue

      # check for type(X).__name__
      if type_name_re.search(line):
        self.issues.append((
          line_num,
          "type(obj).__name__ is forbidden"
          " -- use obj.class_name, cls.get_class_name(), or resolve_class_id() instead"
          " (add '# waiver: <reason>' to exempt)"
        ))
        continue

      # check for X.__name__ (attribute access on identifier)
      self.issues.append((
        line_num,
        "raw .__name__ access is forbidden"
        " -- use self.class_name, cls.get_class_name(), or resolve_class_id() instead"
        " (add '# waiver: <reason>' to exempt)"
      ))


  def _check_separator_format(self) -> None:
    """
    Check that separator lines use exactly 88 dashes.

    Per project guidelines, the separator format is:
    `# ` followed by exactly 88 `-` characters (90 chars total).
    """
    # match lines that look like separators: `# ` followed by 10+ dashes and nothing else
    separator_re = re.compile(r'^# -{10,}$')
    expected = '# ' + '-' * 88

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.rstrip()

      if separator_re.match(stripped):
        # guard: waiver present
        if _has_waiver(self.source_lines, line_num):
          continue
        # guard: correct format
        if stripped == expected:
          continue
        dash_count = len(stripped) - 2  # subtract `# `
        self.issues.append((
          line_num,
          f"separator line has {dash_count} dashes (expected 88)"
        ))


  def _check_bare_type_annotation(self) -> None:
    """
    Check for bare `type`, `type[object]`, or `type[Any]` used as a type annotation.

    Per project guidelines, bare `type` (e.g., `: type`, `-> type`, `type | None`),
    `type[object]`, and `type[Any]` are forbidden in annotations. Use `type[SpecificClass]` instead.
    """
    # annotation contexts where bare `type` appears
    ann_colon_re = re.compile(r':\s*type\s*(?:[|,)\]=]|\s*$)')
    ann_return_re = re.compile(r'->\s*type\s*(?:[|:]|\s*$)')
    ann_union_l_re = re.compile(r'(?<![_.\w])type\s*\|')
    ann_union_r_re = re.compile(r'\|\s*type\s*(?:[|,)\]=]|\s*$)')
    # noinspection RegExpRedundantEscape
    # \] needed inside char class to avoid closing it
    ann_generic_re = re.compile(r'[,\[]\s*type\s*[\],|]')
    # annotation contexts where `type[object]` or `type[Any]` appears
    type_object_re = re.compile(r'(?<![_.\w])type\[object]')
    type_any_re = re.compile(r'(?<![_.\w])type\[Any]')
    # false-positive exclusion: isinstance(x, type)
    isinstance_re = re.compile(r'isinstance\s*\([^)]*,\s*type\s*\)')
    # strip single-line string literals to avoid matching inside strings
    string_strip_re = re.compile(r'''f?r?b?"[^"]*"|f?r?b?'[^']*' '''.strip())

    in_docstring = False
    docstring_delimiter = None

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.strip()

      # track docstring state
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delimiter = stripped[:3]
          if not (len(stripped) > 3 and stripped.endswith(docstring_delimiter)):
            in_docstring = True
          continue
      else:
        if docstring_delimiter and stripped.endswith(docstring_delimiter):
          in_docstring = False
          docstring_delimiter = None
        continue

      # guard: skip comment-only lines
      if stripped.startswith('#'):
        continue

      # guard: skip string-only lines
      if stripped.startswith(('"', "'", 'f"', "f'", 'r"', "r'", 'b"', "b'")):
        continue

      # guard: waiver present
      if _has_waiver(self.source_lines, line_num):
        continue

      # strip string literals and inline comments from code
      code = string_strip_re.sub('""', line)
      code = code.split('#')[0]

      # guard: exclude isinstance(x, type) calls
      if isinstance_re.search(code):
        code = isinstance_re.sub('', code)

      # check for type[object] — equally meaningless as bare type
      if type_object_re.search(code):
        self.issues.append((
          line_num,
          "'type[object]' in annotation is forbidden"
          " -- use 'type[SpecificClass]' instead"
          " (add '# waiver: <reason>' to exempt)"
        ))
        continue

      # check for type[Any] — equally meaningless as bare type
      if type_any_re.search(code):
        self.issues.append((
          line_num,
          "'type[Any]' in annotation is forbidden"
          " -- use 'type[SpecificClass]' or bare 'type' instead"
          " (add '# waiver: <reason>' to exempt)"
        ))
        continue

      # check all annotation context patterns
      if (ann_colon_re.search(code) or ann_return_re.search(code)
          or ann_union_l_re.search(code) or ann_union_r_re.search(code)
          or ann_generic_re.search(code)):
        self.issues.append((
          line_num,
          "bare 'type' in annotation is forbidden"
          " -- use 'type[SpecificClass]' instead"
          " (add '# waiver: <reason>' to exempt)"
        ))


  def _check_any_annotation(self) -> None:
    """
    Check for `Any` used in type annotations.

    Per project guidelines, `Any` is forbidden in annotations.
    Auto-exempt: `*args: Any`, `**kwargs: Any`, and any usage inside dunder methods.
    """
    bare_any_re = re.compile(r'(?<![_\w])Any(?![_\w])')
    # exempt: *args: Any or **kwargs: Any
    kwargs_args_exempt_re = re.compile(r'\*{1,2}\w+:\s*Any\b')
    # track function definitions
    func_def_re = re.compile(r'^(\s*)def\s+(\w+)\s*\(')
    # strip single-line string literals
    string_strip_re = re.compile(r'''f?r?b?"[^"]*"|f?r?b?'[^']*' '''.strip())

    in_docstring = False
    docstring_delimiter = None
    current_func_name = ''
    current_func_indent = -1

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.strip()

      # track docstring state
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delimiter = stripped[:3]
          if not (len(stripped) > 3 and stripped.endswith(docstring_delimiter)):
            in_docstring = True
          continue
      else:
        if docstring_delimiter and stripped.endswith(docstring_delimiter):
          in_docstring = False
          docstring_delimiter = None
        continue

      # guard: skip comment-only lines
      if stripped.startswith('#'):
        continue

      # guard: skip string-only lines
      if stripped.startswith(('"', "'", 'f"', "f'", 'r"', "r'", 'b"', "b'")):
        continue

      # track function context for dunder method detection
      func_match = func_def_re.match(line)
      if func_match:
        current_func_indent = len(func_match.group(1))
        current_func_name = func_match.group(2)
      elif stripped and not stripped.startswith(('@', ')', ',')):
        # non-blank, non-continuation, non-decorator line
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= current_func_indent:
          current_func_name = ''
          current_func_indent = -1

      # strip string literals and inline comments from code
      code = string_strip_re.sub('""', line)
      code = code.split('#')[0]

      # guard: no Any token on this line
      if not bare_any_re.search(code):
        continue

      # guard: skip import lines
      if stripped.startswith(('from ', 'import ')):
        continue

      # guard: waiver present
      if _has_waiver(self.source_lines, line_num):
        continue

      # guard: *args: Any / **kwargs: Any — auto-exempt
      if kwargs_args_exempt_re.search(code):
        code_remaining = kwargs_args_exempt_re.sub('', code)
        # guard: no remaining Any after removing exempt *args/**kwargs
        if not bare_any_re.search(code_remaining):
          continue

      # guard: inside a dunder method — auto-exempt
      if current_func_name.startswith('__') and current_func_name.endswith('__'):
        continue

      self.issues.append((
        line_num,
        "'Any' in type annotation is forbidden"
        " -- use a specific type, protocol, or generic instead"
        " (add '# waiver: <reason>' to exempt)"
      ))


  def _check_assert_statements(self) -> None:
    """
    Check for assert statements in production code.

    Assert statements are stripped by `python -O` and should not be used
    for production validation logic.
    """
    assert_re = re.compile(r'^\s*assert\b')
    in_docstring = False
    docstring_delimiter = None

    for idx, line in enumerate(self.source_lines):
      line_num = idx + 1
      stripped = line.strip()

      # track docstring state
      if not in_docstring:
        if stripped.startswith(('"""', "'''")):
          docstring_delimiter = stripped[:3]
          if not (len(stripped) > 3 and stripped.endswith(docstring_delimiter)):
            in_docstring = True
          continue
      else:
        if docstring_delimiter and stripped.endswith(docstring_delimiter):
          in_docstring = False
          docstring_delimiter = None
        continue

      # guard: skip comment-only lines
      if stripped.startswith('#'):
        continue

      # guard: not an assert line
      if not assert_re.match(line):
        continue

      # guard: waiver present
      if _has_waiver(self.source_lines, line_num):
        continue

      self.issues.append((
        line_num,
        "assert statement found -- assert is stripped by python -O;"
        " use explicit validation instead"
        " (add '# waiver: <reason>' to exempt)"
      ))


  def analyze(self) -> list[tuple[int, str]]:
    """
    Run all code format checks and return a list of issues.

    Returns:
      List of (line_number, message) tuples for each issue found.
    """
    if self.check_line_length:
      self._check_line_length()
    if self.check_indentation:
      self._check_indentation()
    self._check_silent_broad_except()
    self._check_error_suppression()
    self._check_double_backticks()
    self._check_guard_comments()
    self._check_typing_cast()
    self._check_raw_dunder_name()
    self._check_separator_format()
    self._check_bare_type_annotation()
    self._check_any_annotation()
    if self.check_assert:
      self._check_assert_statements()
    # disabled: too noisy and conflicts with some patterns
    # self._check_named_arg_spacing()
    # disabled: complex to get right without full AST
    # self._check_blank_lines_between_methods()

    return sorted(self.issues, key = lambda x: x[0])


# ----------------------------------------------------------------------------------------
# valid docstring section names and their expected order
DOCSTRING_SECTIONS_ORDER = [
  'Responsibilities',
  'Guarantees',
  'Subclassing',
  'Overriding',
  'Methods',
  'Notes',
  'Type Parameters',
  'Attributes',
  'Args',
  'Returns',
  'Yields',
  'Raises',
]

# sections that must use bulleted lists
BULLETED_SECTIONS = {
  'Responsibilities', 'Guarantees', 'Subclassing', 'Overriding', 'Methods', 'Notes',
}

# sections that must use definition lists (name: description)
DEFINITION_SECTIONS = {'Type Parameters', 'Attributes', 'Args', 'Raises'}

# sections that must use plain indented text
PLAIN_SECTIONS = {'Returns', 'Yields'}


# regex: marker tags forbidden inside docstring text (D7).
# these belong in code comments, never in docstring bodies.
_DOCSTRING_MARKERS_RE = re.compile(r'\b(TODO|TMP|DBG|REF|opt|guard|DOC\s*\():')

# regex: imperative summary with 3+ comma-separated clauses joined by ", and " (D6).
# matches forms like "Enter X, install Y, and render Z."
_COMMA_CHAINED_SUMMARY_RE = re.compile(
  r'^[A-Z]\w+\s+[^.,]+,\s+[^.,]+,\s+and\s+[^.,]+\.\s*$'
)

# regex: leading-underscore identifier referenced in narrative text (D9).
# excludes dunders like __init__ and standalone underscore.
_PRIVATE_NAME_RE = re.compile(r'(?<![\w_])(_[a-z]\w*)\b')

# Sections where private-name narrative references (D9) are tolerated:
# Subclassing/Overriding target subclass authors who legitimately need private hooks;
# Notes/Type Parameters/Args/Returns/Raises/Attributes either describe
# advanced detail or are checked by other rules (D2).
_D9_SKIP_SECTIONS = frozenset({
  'Subclassing', 'Overriding', 'Notes', 'Type Parameters',
  'Args', 'Raises', 'Attributes',
})

# Connecting prepositions that turn a comma-list into criteria/scope rather than steps (D6).
_D6_LIST_PREPOSITIONS = frozenset({
  'for', 'by', 'with', 'using', 'from', 'to', 'over',
  'as', 'into', 'across', 'on', 'against', 'about', 'of',
})


# ----------------------------------------------------------------------------------------
# waiver: AST visitor methods must follow visit_NodeType naming convention required by ast.NodeVisitor
# pylint: disable=invalid-name
class DocstringAnalyzer(ast.NodeVisitor):
  """
  AST visitor that analyzes docstrings according to project guidelines.

  Checks docstring formatting rules including line length, section order, section formatting,
  and various documentation standards from the project guidelines.
  """

  def __init__(self,
               source_lines: list[str],
               *,
               max_line_length: int = 117,
               check_line_length: bool = True,
               check_docstring_content: bool = True,
               banned_docstring_phrases: list[str] | None = None,
               extra_docstring_sections: list[dict] | None = None,
               d2_exempt_marker_attrs: list[str] | None = None,
               private_name_allowlist: list[str] | None = None):
    """
    Initialize the DocstringAnalyzer.

    Args:
      source_lines: list of source code lines.
      max_line_length: maximum allowed line length in docstrings.
      check_line_length: whether to check docstring line length.
      check_docstring_content: whether to run extended docstring-content checks (D1-D9).
      banned_docstring_phrases: substrings rejected anywhere in a docstring body (D5 input).
      extra_docstring_sections: consumer-registered docstring sections from `[tool.pcf]`.
      d2_exempt_marker_attrs: class attribute names whose declaration exempts a class from D2.
      private_name_allowlist: private identifiers tolerated in docstring narrative by D9.
    """
    self.source_lines = source_lines
    self.max_line_length = max_line_length
    self.check_line_length = check_line_length
    self.check_docstring_content = check_docstring_content
    self.banned_docstring_phrases = list(banned_docstring_phrases or [])
    self.d2_exempt_marker_attrs = frozenset(d2_exempt_marker_attrs or [])
    self.private_name_allowlist = frozenset(private_name_allowlist or [])
    self.issues: list[tuple[int, str]] = []
    self._visited_nodes: set[int] = set()
    # stack of per-class context for D2: each entry is (has_d2_exempt_marker, class_constants).
    # `has_d2_exempt_marker` is True when the enclosing class declares or mutates a
    # configured D2-exempt marker attribute; `class_constants` is the set of names assigned
    # at class-body scope -- both grant exemption from D2 for private labels in `Attributes:`.
    self._class_ctx_stack: list[tuple[bool, set[str]]] = []
    self.sections_order = list(DOCSTRING_SECTIONS_ORDER)
    self.bulleted_sections = set(BULLETED_SECTIONS)
    self.definition_sections = set(DEFINITION_SECTIONS)
    self.plain_sections = set(PLAIN_SECTIONS)
    self.d9_skip_sections = set(_D9_SKIP_SECTIONS)
    self.ref_exempt_sections: set[str] = set()
    self._merge_extra_sections(extra_docstring_sections or [])


  def _merge_extra_sections(self, entries: list[dict]) -> None:
    """
    Merge consumer-declared docstring sections into the section machinery.

    Each entry names a section, its list style, an optional order anchor
    (`after` / `before` an existing section), and an optional `ref_exempt`
    flag that shields the section's body from D5/D7/D9. Definition-style
    sections are skipped by the D9 narrative scan like the built-in
    definition sections. Malformed entries are skipped -- a checker must
    not crash on a config typo.

    Args:
      entries: raw `extra_docstring_sections` entries from `[tool.pcf]`.
    """
    style_sets = {
      'bulleted': self.bulleted_sections,
      'definition': self.definition_sections,
      'plain': self.plain_sections,
    }
    for entry in entries:
      # guard: malformed entry shape
      if not isinstance(entry, dict):
        continue
      name = entry.get('name')
      style = entry.get('style')
      # guard: unusable or duplicate section name
      if not isinstance(name, str) or not name or name in self.sections_order:
        continue
      # guard: unknown list style
      if style not in style_sets:
        continue
      after = entry.get('after')
      before = entry.get('before')
      # resolve insertion position: after/before an existing section, else append
      if isinstance(after, str) and after in self.sections_order:
        pos = self.sections_order.index(after) + 1
      elif isinstance(before, str) and before in self.sections_order:
        pos = self.sections_order.index(before)
      else:
        pos = len(self.sections_order)
      self.sections_order.insert(pos, name)
      style_sets[style].add(name)
      # guard: definition sections are name/description label lists -- D9 skips them
      # like the built-in definition sections (Attributes, Args, Raises, Type Parameters)
      if style == 'definition':
        self.d9_skip_sections.add(name)
      # ref-exempt sections are skipped by D5/D7 (line scan) and D9 (section scan)
      if entry.get('ref_exempt'):
        self.ref_exempt_sections.add(name)
        self.d9_skip_sections.add(name)


  def _get_docstring_info(self, 
                          node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
                          ) -> tuple[str | None, int | None]:
    """
    Extract a docstring and its starting line number from a node.

    Args:
      node: AST node to extract docstring from.

    Returns:
      Tuple of (docstring_text, start_line) or (None, None) if no docstring.
    """
    if not node.body:
      return None, None

    first_stmt = node.body[0]
    if not isinstance(first_stmt, ast.Expr):
      return None, None

    expr_value = first_stmt.value
    if isinstance(expr_value, ast.Constant) and isinstance(expr_value.value, str):
      return expr_value.value, first_stmt.lineno

    return None, None


  def _check_docstring_line_length(self, 
                                   docstring: str, 
                                   start_line: int,
                                   node_name: str) -> None:
    """
    Check that docstring lines do not exceed the maximum length.

    Args:
      docstring: the docstring text.
      start_line: line number where the docstring starts.
      node_name: name of the node for error messages.
    """
    lines = docstring.split('\n')
    for idx, line in enumerate(lines):
      # calculate actual line number in a source
      actual_line = start_line + idx
      # get the actual source line to include leading spaces in length calculation
      source_idx = actual_line - 1
      if source_idx < len(self.source_lines):
        source_line = self.source_lines[source_idx].rstrip('\n')
        line_length = len(source_line)
      else:
        line_length = len(line.strip())
      # check line length including leading spaces
      if line_length > self.max_line_length:
        self.issues.append((
          actual_line,
          f"docstring line exceeds {self.max_line_length} chars in '{node_name}' ({line_length} chars)"
        ))


  def _parse_sections(self, docstring: str) -> list[tuple[str, int, list[str]]]:
    """
    Parse docstring into sections.

    Args:
      docstring: the docstring text.

    Returns:
      List of (section_name, relative_line, content_lines) tuples.
    """
    sections: list[tuple[str, int, list[str]]] = []
    lines = docstring.split('\n')
    current_section: str | None = None
    current_content: list[str] = []
    section_start_line = 0

    for idx, line in enumerate(lines):
      stripped = line.strip()

      # check if this is a section header
      is_section = False
      for section_name in self.sections_order:
        if stripped == f'{section_name}:':
          is_section = True
          # save previous section if exists
          if current_section is not None:
            sections.append((current_section, section_start_line, current_content))
          current_section = section_name
          current_content = []
          section_start_line = idx
          break

      if not is_section and current_section is not None:
        current_content.append(line)

    # save the last section
    if current_section is not None:
      sections.append((current_section, section_start_line, current_content))

    return sections


  def _check_section_order(self, 
                           sections: list[tuple[str, int, list[str]]], 
                           start_line: int,
                           node_name: str) -> None:
    """
    Check that sections appear in the correct order.

    Args:
      sections: list of parsed sections.
      start_line: line number where the docstring starts.
      node_name: name of the node for error messages.
    """
    section_names = [sec[0] for sec in sections]
    expected_indices = []

    for sec_name in section_names:
      if sec_name in self.sections_order:
        expected_indices.append(self.sections_order.index(sec_name))

    # check if indices are in ascending order
    for idx in range(1, len(expected_indices)):
      if expected_indices[idx] < expected_indices[idx - 1]:
        prev_section = section_names[idx - 1]
        curr_section = section_names[idx]
        sec_line = sections[idx][1]
        self.issues.append((
          start_line + sec_line,
          f"section '{curr_section}' should come before '{prev_section}' in '{node_name}'"
        ))


  def _check_bulleted_section(self, 
                              section_name: str, 
                              content: list[str], 
                              start_line: int,
                              section_rel_line: int,
                              node_name: str) -> None:
    """
    Check that a bulleted section has proper formatting.

    Allows multi-line bullet items where continuation lines don't start with a bullet.

    Args:
      section_name: name of the section.
      content: content lines of the section.
      start_line: docstring start line.
      section_rel_line: relative line of section header.
      node_name: name of the node for error messages.
    """
    # track whether we're inside a bullet item (allows continuation lines)
    in_bullet_item = False
    for idx, line in enumerate(content):
      stripped = line.strip()
      if not stripped:
        # the empty line ends the current bullet item context
        in_bullet_item = False
        continue
      # check if the line starts with a bullet (- )
      if stripped.startswith('- '):
        in_bullet_item = True
      elif not in_bullet_item:
        # non-bullet line that isn't a continuation of a previous bullet
        self.issues.append((
          start_line + section_rel_line + idx + 1,
          f"'{section_name}' section must use bulleted list (- ) in '{node_name}'"
        ))
        break


  def _check_definition_section(self, 
                                section_name: str, 
                                content: list[str], 
                                start_line: int,
                                section_rel_line: int,
                                node_name: str) -> None:
    """
    Check that a definition section has proper formatting.

    Bullets are allowed as continuation lines under an argument description,
    but not as the argument name itself. A definition line has format "name: description".
    Continuation lines (including bullets) must be more indented than the definition.

    Args:
      section_name: name of the section.
      content: content lines of the section.
      start_line: docstring start line.
      section_rel_line: relative line of section header.
      node_name: name of the node for error messages.
    """
    # find the base indentation level for definitions (first non-empty line)
    base_indent: int | None = None
    for line in content:
      if line.strip():
        base_indent = len(line) - len(line.lstrip())
        break

    # guard: section has content
    if base_indent is None:
      return

    for idx, line in enumerate(content):
      stripped = line.strip()
      # guard: skip empty lines
      if not stripped:
        continue

      # calculate current line indentation
      current_indent = len(line) - len(line.lstrip())

      # only check for bullets at the base indentation level (definition names)
      # bullets in continuation lines (more indented) are allowed
      if current_indent == base_indent and stripped.startswith(('- ', '* ')):
        self.issues.append((
          start_line + section_rel_line + idx + 1,
          f"'{section_name}' section must not use bullets for definition names in '{node_name}'"
        ))
        break


  def _check_section_formatting(self, 
                                sections: list[tuple[str, int, list[str]]], 
                                start_line: int,
                                node_name: str) -> None:
    """
    Check section content formatting.

    Args:
      sections: list of parsed sections.
      start_line: line number where the docstring starts.
      node_name: name of the node for error messages.
    """
    for section_name, rel_line, content in sections:
      if section_name in self.bulleted_sections:
        self._check_bulleted_section(section_name, content, start_line, rel_line, node_name)
      elif section_name in self.definition_sections:
        self._check_definition_section(section_name, content, start_line, rel_line, node_name)


  def _check_empty_line_before_section(self, 
                                       docstring: str, 
                                       start_line: int,
                                       node_name: str) -> None:
    """
    Check that sections have empty line before them.

    Args:
      docstring: the docstring text.
      start_line: line number where the docstring starts.
      node_name: name of the node for error messages.
    """
    lines = docstring.split('\n')
    for idx, line in enumerate(lines):
      stripped = line.strip()
      for section_name in self.sections_order:
        if stripped == f'{section_name}:':
          # check if the previous non-empty line exists and there's no blank before
          if idx > 0:
            prev_line = lines[idx - 1].strip()
            if prev_line:
              self.issues.append((
                start_line + idx,
                f"section '{section_name}' must have empty line before it in '{node_name}'"
              ))
          break


  def _check_property_sections(self, 
                               node: ast.FunctionDef, 
                               docstring: str, 
                               start_line: int) -> None:
    """
    Check that property docstrings don't have Args/Returns/Yields sections.

    Args:
      node: the function node.
      docstring: the docstring text.
      start_line: line number where the docstring starts.
    """
    # check if this is a property
    is_property = any(
      isinstance(dec, ast.Name) and dec.id == 'property'
      for dec in node.decorator_list
    )
    # guard: node is a property
    if not is_property:
      return

    lines = docstring.split('\n')
    forbidden = ['Args:', 'Returns:', 'Yields:']
    for idx, line in enumerate(lines):
      stripped = line.strip()
      if stripped in forbidden:
        self.issues.append((
          start_line + idx,
          f"property '{node.name}' must not have '{stripped[:-1]}' section"
        ))


  def _check_impl_details(self,
                          docstring: str,
                          start_line: int,
                          node_name: str) -> None:
    """
    Check for implementation detail phrases in the Summary and Scope area of a docstring.

    Per project guidelines, docstrings must describe WHAT, not HOW. Phrases that
    narrate internal mechanisms (validation, dispatch, internal state) are
    forbidden in Summary/Scope.

    Args:
      docstring: the docstring text.
      start_line: line number where the docstring starts.
      node_name: name of the node for error messages.
    """
    impl_patterns = re.compile(
      r'(?:^|\.\s+)(?:It validates|It sets up|It assigns|It creates|It checks|It iterates'
      r'|It loops|It calls|It initializes|It processes|It parses|It computes'
      r'|It builds|It constructs|It fetches|It reads|It writes|It updates'
      r'|It modifies|It deletes|It removes|It stores|It caches|It converts'
      r'|Internally,|Under the hood|This method internally|The implementation'
      r'|This class internally)\b'
    )

    # only check Summary/Scope (before the first section header)
    section_header = re.compile(r'^\s{0,4}(Args|Returns|Yields|Raises|Attributes'
                                r'|Responsibilities|Guarantees|Subclassing|Overriding'
                                r'|Notes|Type Parameters):')
    lines = docstring.split('\n')
    for idx, line in enumerate(lines):
      # stop at the first section header
      if section_header.match(line):
        break
      match = impl_patterns.search(line)
      if match:
        actual_line = start_line + idx
        self.issues.append((
          actual_line,
          f"implementation detail phrase in docstring of '{node_name}': "
          f"'{match.group()}' -- describe WHAT, not HOW"
        ))


  def _class_has_d2_exempt_marker(self, node: ast.ClassDef) -> bool:
    """
    Detect whether the class body declares a configured D2-exempt marker attribute.

    The declaration is a standing exemption for D2: classes that declare or mutate
    one of the configured marker attribute names are allowed to surface their private
    fields in the `Attributes:` section. Dynamic mutation of a marker name from inside
    `__init_subclass__` or other class-body methods is also accepted.

    Args:
      node: class definition AST node.

    Returns:
      True if the class body declares or mutates a configured marker attribute anywhere.
    """
    # guard: no marker attributes configured -- the escape hatch is disabled
    if not self.d2_exempt_marker_attrs:
      return False
    for item in node.body:
      # match: <name> = {...}
      if isinstance(item, ast.Assign):
        for target in item.targets:
          if isinstance(target, ast.Name) and target.id in self.d2_exempt_marker_attrs:
            return True
      # match: <name>: ClassVar[...] = {...}
      elif isinstance(item, ast.AnnAssign):
        target = item.target
        if isinstance(target, ast.Name) and target.id in self.d2_exempt_marker_attrs:
          return True
    # walk the entire class body (including nested methods like `__init_subclass__`)
    # to detect dynamic mutation of a configured marker via `cls._marker_attr[...]`
    return any(
      isinstance(sub, ast.Attribute) and sub.attr in self.d2_exempt_marker_attrs
      for sub in ast.walk(node)
    )


  def _class_constant_names(self, node: ast.ClassDef) -> set[str]:
    """
    Collect names of class-level constants (private and public) declared in the body.

    Class-level constants such as `_cls_data_ver` or `_data_dtype` are an established
    project pattern for class-versioning and type-shape metadata. Their presence in
    `Attributes:` is a deliberate documentation choice and must not be flagged by D2.

    Args:
      node: class definition AST node.

    Returns:
      Set of names assigned at class-body scope (skipping nested method bodies).
    """
    names: set[str] = set()
    for item in node.body:
      if isinstance(item, ast.Assign):
        for target in item.targets:
          if isinstance(target, ast.Name):
            names.add(target.id)
      elif isinstance(item, ast.AnnAssign):
        target = item.target
        if isinstance(target, ast.Name):
          names.add(target.id)
    return names


  def _check_single_line_docstring(self,
                                   docstring: str,
                                   start_line: int,
                                   node_name: str) -> None:
    """
    D1: reject `\"\"\"text\"\"\"` single-line docstring form.

    Per `documenting_guidelines.md` line 61, the opening `\"\"\"` must be
    followed by a newline.

    Args:
      docstring: the cleaned docstring text.
      start_line: source line of the opening `\"\"\"`.
      node_name: enclosing class/function name for the message.
    """
    # guard: multi-line docstring is fine
    if '\n' in docstring:
      return
    # guard: source line missing (defensive)
    if start_line - 1 >= len(self.source_lines):
      return
    src_line = self.source_lines[start_line - 1]
    # both opening and closing triple-quotes on the same source line == single-line form
    if src_line.count('"""') >= 2 or src_line.count("'''") >= 2:
      self.issues.append((
        start_line,
        f"D1 single-line docstring in '{node_name}'; use multi-line "
        f'""" form (newline after opening quotes)'
      ))


  def _check_attributes_private_names(self,
                                      sections: list[tuple[str, int, list[str]]],
                                      start_line: int,
                                      node_name: str) -> None:
    """
    D2: reject private-name labels in the `Attributes:` section.

    Private names are permitted in two cases: the enclosing class declares or
    mutates a configured D2-exempt marker attribute (the project's escape hatch,
    see `[tool.pcf] d2_exempt_marker_attrs`), or the label matches a class-level
    constant declared in the class body (the project's metadata-documentation
    pattern, e.g. `_cls_data_ver`).

    Args:
      sections: parsed docstring sections.
      start_line: source line of the docstring opening `\"\"\"`.
      node_name: enclosing class/function name for the message.
    """
    has_marker, class_consts = (
      self._class_ctx_stack[-1] if self._class_ctx_stack else (False, set())
    )
    # guard: enclosing class permits private attributes via a configured D2-exempt marker
    if has_marker:
      return
    for section_name, rel_line, content in sections:
      # guard: only inspect Attributes
      if section_name != 'Attributes':
        continue
      for idx, line in enumerate(content):
        stripped = line.strip()
        # match definition labels of form `_name:` (with optional indent stripped)
        m = re.match(r'^_(\w+)\s*:', stripped)
        if m:
          full_name = '_' + m.group(1)
          # guard: skip class-level constants (deliberate metadata documentation)
          if full_name in class_consts:
            continue
          actual_line = start_line + rel_line + idx + 1
          self.issues.append((
            actual_line,
            f"D2 private attribute '{full_name}' in Attributes of '{node_name}' "
            f"(allowed only for class constants or when the class declares a configured D2-exempt marker)"
          ))


  def _check_returns_section_required(self,
                                      node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
                                      sections: list[tuple[str, int, list[str]]],
                                      start_line: int) -> None:
    """
    D4: require `Returns:` section when the function's return annotation is non-None.

    Properties are exempt (they document via Summary). `__init__` is exempt (returns
    None implicitly). `Yields:` is accepted as a substitute for generator functions.

    Args:
      node: function or class AST node.
      sections: parsed docstring sections.
      start_line: source line of the docstring opening `\"\"\"`.
    """
    # guard: only function-like nodes have return annotations
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
      return
    # guard: no return annotation means we can't tell -- skip
    if node.returns is None:
      return
    # guard: explicit `-> None` annotation
    if isinstance(node.returns, ast.Constant) and node.returns.value is None:
      return
    no_return_names = ('NoReturn', 'Never')
    # guard: bare `NoReturn` / `Never` annotation -- the function never returns a value, so a Returns section is meaningless
    if isinstance(node.returns, ast.Name) and node.returns.id in no_return_names:
      return
    # guard: qualified `typing.NoReturn` / `typing.Never` annotation -- same reasoning as the bare form
    if isinstance(node.returns, ast.Attribute) and node.returns.attr in no_return_names:
      return
    is_property = any(
      isinstance(dec, ast.Name) and dec.id == 'property'
      for dec in node.decorator_list
    )
    # guard: properties never carry Returns sections
    if is_property:
      return
    # guard: dunder methods follow well-known Python data-model semantics --
    # an explicit Returns: section would be redundant noise
    if node.name.startswith('__') and node.name.endswith('__'):
      return
    has_returns = any(s[0] == 'Returns' for s in sections)
    has_yields = any(s[0] == 'Yields' for s in sections)
    # guard: Returns or Yields satisfies the requirement
    if has_returns or has_yields:
      return
    # render the return annotation for the message
    try:
      return_repr = ast.unparse(node.returns)
    except (AttributeError, ValueError):
      return_repr = '<non-None>'
    self.issues.append((
      start_line,
      f"D4 missing 'Returns:' section in '{node.name}' (return type is {return_repr})"
    ))


  def _ref_exempt_line_indices(self, docstring: str) -> set[int]:
    """
    Return line indices that fall inside ref-exempt sections.

    Ref-exempt sections are registered by the consumer via `[tool.pcf]
    extra_docstring_sections` with `ref_exempt = true`; their bodies carry
    `# REF:` lines and generator-owned content that project tooling consumes,
    so D5/D7/D9 must not flag them.

    Args:
      docstring: the cleaned docstring text.

    Returns:
      Set of line indices (0-based, into `docstring.split('\\n')`) that the
      caller should skip.
    """
    # guard: no ref-exempt sections registered
    if not self.ref_exempt_sections:
      return set()
    lines = docstring.split('\n')
    skip: set[int] = set()
    in_exempt = False
    for idx, line in enumerate(lines):
      stripped = line.strip()
      # guard: enter a ref-exempt section
      if stripped.endswith(':') and stripped[:-1] in self.ref_exempt_sections:
        in_exempt = True
        skip.add(idx)
        continue
      # any other top-level section header ends the ref-exempt scope
      if stripped.endswith(':') and stripped[:-1] in self.sections_order:
        in_exempt = False
        continue
      # guard: line is inside a ref-exempt section
      if in_exempt:
        skip.add(idx)
    return skip


  def _check_banned_phrases(self,
                            docstring: str,
                            start_line: int,
                            node_name: str) -> None:
    """
    D5: reject configured banned phrases anywhere in the docstring body.

    Banned phrases are loaded from `pyproject.toml` `[tool.pcf]
    banned_docstring_phrases`. Substring match is case-sensitive and applies
    to all sections, including Summary. Ref-exempt sections registered via
    `[tool.pcf]` are skipped.

    Args:
      docstring: the cleaned docstring text.
      start_line: source line of the docstring opening `\"\"\"`.
      node_name: enclosing class/function name for the message.
    """
    # guard: nothing configured
    if not self.banned_docstring_phrases:
      return
    lines = docstring.split('\n')
    skip_idx = self._ref_exempt_line_indices(docstring)
    for phrase in self.banned_docstring_phrases:
      # guard: skip empty phrases (defensive against config typos)
      if not phrase:
        continue
      for idx, line in enumerate(lines):
        # guard: ref-exempt section content is owned by consumer tooling
        if idx in skip_idx:
          continue
        if phrase in line:
          self.issues.append((
            start_line + idx,
            f"D5 banned docstring phrase in '{node_name}': '{phrase}'"
          ))


  def _check_comma_chained_summary(self,
                                   node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
                                   docstring: str,
                                   start_line: int,
                                   node_name: str) -> None:
    """
    D6: reject comma-chained imperative summaries (3+ clauses joined by `, and`).

    Form `X, Y, and Z.` is the canonical implementation-step chain banned by
    `documenting_guidelines.md` line 21. Class summaries are noun-phrases and
    are exempt; method summaries are also exempt when a connecting preposition
    (`for`, `by`, `with`, ...) precedes the first comma -- such summaries list
    criteria/scope, not sequential steps.

    Args:
      node: function or class AST node.
      docstring: the cleaned docstring text.
      start_line: source line of the docstring opening `\"\"\"`.
      node_name: enclosing class/function name for the message.
    """
    # guard: class summaries are noun-phrases; D6 targets imperative method chains
    if isinstance(node, ast.ClassDef):
      return
    lines = docstring.split('\n')
    # find the first non-empty line == summary
    for idx, line in enumerate(lines):
      stripped = line.strip()
      # guard: skip leading blanks
      if not stripped:
        continue
      if _COMMA_CHAINED_SUMMARY_RE.match(stripped):
        # check for a connecting preposition before the first comma -- if present,
        # the comma-list is scope/criteria, not a sequence of steps
        head = stripped.split(',', 1)[0].lower()
        head_words = set(head.split())
        if head_words & _D6_LIST_PREPOSITIONS:
          break
        self.issues.append((
          start_line + idx,
          f"D6 comma-chained implementation steps in summary of '{node_name}'"
        ))
      # only the first non-empty line is the summary -- stop after it
      break


  def _check_marker_in_docstring(self,
                                 docstring: str,
                                 start_line: int,
                                 node_name: str) -> None:
    """
    D7: reject development-marker tokens inside docstring text.

    The configured marker tokens (TODO, TMP, DBG, REF, opt, guard, and the
    `DOC(...)` tag) belong in code comments, never in docstring bodies (per
    `documenting_guidelines.md` line 19 zero-tolerance blocker).

    Skips ref-exempt sections entirely -- sections registered via
    `[tool.pcf]` with `ref_exempt = true` carry `# REF:` lines as source
    references that consumer tooling strips at runtime.

    Args:
      docstring: the cleaned docstring text.
      start_line: source line of the docstring opening `\"\"\"`.
      node_name: enclosing class/function name for the message.
    """
    lines = docstring.split('\n')
    skip_idx = self._ref_exempt_line_indices(docstring)
    for idx, line in enumerate(lines):
      # guard: ref-exempt section content is owned by consumer tooling
      if idx in skip_idx:
        continue
      m = _DOCSTRING_MARKERS_RE.search(line)
      if m:
        # guard: skip backtick-wrapped marker literals (meta-references to the
        # marker syntax in checker/rule docstrings, not actual marker usages).
        before = line[: m.start()]
        after = line[m.end():]
        wrapped = (
          (before.rstrip().endswith('`') or before.rstrip().endswith('`#'))
          and (after.lstrip().startswith('`') or '`' in after.split(' ', 1)[0])
        )
        # guard: meta-references to marker syntax are not violations
        if wrapped:
          continue
        self.issues.append((
          start_line + idx,
          f"D7 marker '{m.group(0)}' inside docstring of '{node_name}'; "
          f"markers belong in code comments"
        ))


  def _check_private_names_in_narrative(self,
                                        docstring: str,
                                        start_line: int,
                                        node_name: str) -> None:
    """
    D9: reject private-name token references in caller-facing docstring narrative.

    A leading-underscore lowercase token in narrative text signals that the
    docstring is narrating internal components -- a violation of the "describe
    WHAT, not HOW" rule (`documenting_guidelines.md` lines 22 and 309).

    Sections that legitimately reference private names are skipped:
    `Subclassing:` / `Overriding:` document hooks subclass authors must use;
    `Notes:` carries advanced-usage detail; `Attributes:` / `Args:` / `Raises:`
    are definition lists checked by other rules; `Type Parameters:` describes
    type variables; ref-exempt sections registered via `[tool.pcf]` cite code
    via `# REF:` lines.

    Args:
      docstring: the cleaned docstring text.
      start_line: source line of the docstring opening `\"\"\"`.
      node_name: enclosing class/function name for the message.
    """
    lines = docstring.split('\n')
    current_section: str | None = None
    for idx, line in enumerate(lines):
      stripped = line.strip()
      # detect section header transitions
      header_hit = False
      for sec_name in self.sections_order:
        if stripped == f'{sec_name}:':
          current_section = sec_name
          header_hit = True
          break
      # guard: header line itself is not narrative
      if header_hit:
        continue
      # guard: skip sections that legitimately reference private names
      if current_section in self.d9_skip_sections:
        continue
      # scan for private-name tokens in caller-facing narrative
      for m in _PRIVATE_NAME_RE.finditer(line):
        name = m.group(1)
        # guard: skip allowlisted tokens
        if name in self.private_name_allowlist:
          continue
        # detect string-literal or template-placeholder context: '_name' and
        # {_effects.gen_rules} are literal values, not code references.
        prev_char = line[m.start() - 1] if m.start() > 0 else ''
        # guard: skip string-literal and template-placeholder contexts
        if prev_char in ("'", '"', '{'):
          continue
        self.issues.append((
          start_line + idx,
          f"D9 private internal '{name}' referenced in docstring of '{node_name}'"
        ))
        # one report per line is enough -- avoid spamming on the same line
        break


  def _analyze_docstring(self,
                         node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
                         _is_method: bool = False) -> None:
    """
    Analyze a single docstring for issues.

    Args:
      node: AST node containing the docstring.
      _is_method: whether this is a method inside a class (reserved for future use).
    """
    node_id = id(node)
    # guard: skip already-visited nodes
    if node_id in self._visited_nodes:
      return
    self._visited_nodes.add(node_id)

    docstring, start_line = self._get_docstring_info(node)
    # guard: node has docstring
    if docstring is None or start_line is None:
      return

    node_name = node.name

    # check line length (if enabled)
    if self.check_line_length:
      self._check_docstring_line_length(docstring, start_line, node_name)

    # parse and check sections
    sections = self._parse_sections(docstring)
    if sections:
      self._check_section_order(sections, start_line, node_name)
      self._check_section_formatting(sections, start_line, node_name)
      self._check_empty_line_before_section(docstring, start_line, node_name)

    # check for implementation detail phrases in Summary/Scope
    self._check_impl_details(docstring, start_line, node_name)

    # property-specific checks
    if isinstance(node, ast.FunctionDef):
      self._check_property_sections(node, docstring, start_line)

    # extended docstring-content checks (D1-D9, gated by config)
    if self.check_docstring_content:
      self._check_single_line_docstring(docstring, start_line, node_name)
      if sections:
        self._check_attributes_private_names(sections, start_line, node_name)
      self._check_returns_section_required(node, sections or [], start_line)
      self._check_banned_phrases(docstring, start_line, node_name)
      # D6 (comma-chained summary) retired: too ambiguous between step-chains
      # and noun-phrase scope/return-tuple lists. Step chains in practice trip
      # D5 banned phrases or `_check_impl_details` reliably enough.
      self._check_marker_in_docstring(docstring, start_line, node_name)
      # guard: D9 only fires on caller-facing hosts; private classes/methods
      # are implementer-facing, so private-name references are legitimate prose.
      if not node_name.startswith('_'):
        self._check_private_names_in_narrative(docstring, start_line, node_name)


  def visit_Module(self, node: ast.Module) -> None:
    """
    Visit a module and analyze docstrings of top-level definitions.

    Args:
      node: module AST node.
    """
    for item in node.body:
      if isinstance(item, ast.ClassDef):
        self.visit_ClassDef(item)
      elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
        self._analyze_docstring(item)


  def visit_ClassDef(self, node: ast.ClassDef) -> None:
    """
    Visit a class definition and analyze its docstring.

    Args:
      node: class definition AST node.
    """
    # track per-class D2 exemption context: configured marker presence + class constants
    ctx = (self._class_has_d2_exempt_marker(node), self._class_constant_names(node))
    self._class_ctx_stack.append(ctx)
    try:
      self._analyze_docstring(node)

      # visit methods and nested classes within the class
      for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
          self._analyze_docstring(item, _is_method = True)
        elif isinstance(item, ast.ClassDef):
          # recursively visit nested classes
          self.visit_ClassDef(item)
    finally:
      self._class_ctx_stack.pop()


  def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
    """
    Visit a function definition and analyze its docstring.

    Args:
      node: function definition AST node.
    """
    # only analyze top-level functions (not methods, they're handled in visit_ClassDef)
    self._analyze_docstring(node)


  def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
    """
    Visit an async function definition and analyze its docstring.

    Args:
      node: async function definition AST node.
    """
    self._analyze_docstring(node)


  def analyze(self) -> list[tuple[int, str]]:
    """
    Run all docstring checks and return a list of issues.

    Returns:
      List of (line_number, message) tuples for each issue found.
    """
    return sorted(self.issues, key = lambda x: x[0])


# ----------------------------------------------------------------------------------------
# magic-literal detection: supporting tables and helpers.

# logger/warning method names (last attribute of the call's func).
_LOGGER_METHOD_NAMES = frozenset({
  'debug', 'info', 'warning', 'error', 'critical', 'exception', 'log', 'warn',
})

# built-in call names whose string arguments are messages, not magic values.
# note: `print` is intentionally NOT included -- bare prints should surface during cleanup.
_MESSAGE_CALL_NAMES = frozenset({
  'warn', 'filterwarnings',
})

# regex functions that accept a pattern string as the first argument.
_REGEX_FUNC_NAMES = frozenset({
  'compile', 'match', 'search', 'sub', 'subn', 'findall', 'finditer', 'split', 'fullmatch',
})

# functions whose first positional string is a type/class name, not a value.
_NAME_ARG_CALL_NAMES = frozenset({
  'TypeVar', 'NewType', 'ParamSpec', 'TypeVarTuple',
  'NamedTuple', 'TypedDict', 'Enum', 'IntEnum', 'StrEnum', 'Flag', 'IntFlag',
  'namedtuple',
  # project-level dynamic enum builder: FooInit.build_field_names_enum('FooType')
  'build_field_names_enum',
})

# dataclass-style field constructors whose `default`/`default_factory` kwarg is data, not magic.
_FIELD_CALL_NAMES = frozenset({
  'field', 'Field',
})

# filesystem path constructors.
_PATH_CTOR_NAMES = frozenset({
  'Path', 'PurePath', 'PurePosixPath', 'PureWindowsPath', 'PosixPath', 'WindowsPath',
})

# builtins that take an attribute name as their second argument.
_ATTR_NAME_BUILTINS = frozenset({
  'getattr', 'setattr', 'hasattr', 'delattr',
})

# file-open call names whose mode (2nd positional) and encoding/mode kwargs are standard constants.
# includes stdlib archive/compressed-file constructors whose `mode` kwarg semantics match `open`.
_OPEN_CALL_NAMES = frozenset({
  'open', 'GzipFile', 'BZ2File', 'LZMAFile', 'ZipFile', 'TarFile',
})

# keyword-argument names exempted on file-open calls.
_OPEN_EXEMPT_KWARGS = frozenset({ 'mode', 'encoding' })

# special string tokens exempt as the sole positional of `float(...)`.
_FLOAT_TOKEN_STRINGS = frozenset({ 'inf', '-inf', '+inf', 'nan', '-nan', 'Infinity', 'NaN' })

# env-var boolean idiom tokens -- POSIX/shell convention, not domain values.
_ENV_BOOL_STRINGS = frozenset({ '0', '1', 'true', 'false', 'yes', 'no', 'on', 'off' })

# env-read call tails whose literal `'0'`/`'1'`-style defaults/comparators are shell-conventional.
_ENV_READ_CALL_TAILS = frozenset({ 'getenv' })

# base-class names that mark an enum class body.
_ENUM_BASE_NAMES = frozenset({
  'Enum', 'IntEnum', 'StrEnum', 'Flag', 'IntFlag', 'ReprEnum',
  'CoreEnum', 'CoreIntEnum', 'CoreStrEnum', 'CoreFlag', 'CoreIntFlag',
})

# numeric values that are never flagged as magic (powers of two and their reciprocals).
_TRIVIAL_NUMBERS: frozenset[float] = frozenset({ -1, 0, 0.25, 0.5, 1, 2, 4 })

# chars that identify a string as a format placeholder template.
_FORMAT_PLACEHOLDER_CHARS = ('{', '}', '%')

# regex: string consists only of non-word characters (whitespace/punctuation).
_PUNCT_ONLY_RE = re.compile(r'^[^\w]+$')

# string values that are never flagged as magic (universal Python repr / YAML / display idioms).
# - '_', '__'        : underscore markers and separators
# - 'None'           : literal Python repr of `None`, used in display formatters
# - 'set()'          : literal Python repr of an empty set, used in display formatters
# - 'null'           : YAML/JSON null token, used by serializers
_TRIVIAL_STRINGS = frozenset({ '_', '__', 'None', 'set()', 'null' })

# maximum length of a literal value shown in the issue message.
_MAX_LITERAL_DISPLAY_LEN = 40

# call-function names that introspect membership (used with `'X' in vars(obj)` / `'X' in dir(obj)`).
_MEMBER_LIST_CALL_NAMES = frozenset({ 'vars', 'dir' })

# method names whose first positional string arg is a field/attribute name that must
# resolve to a project identifier (e.g. `db.field_filter('_store_mode', '==', value)`).
_FIELD_NAME_METHOD_NAMES = frozenset({ 'field_filter' })

# regex matching a Python identifier token (used to split forward-reference strings into names).
_IDENT_TOKEN_RE = re.compile(r'\b[_A-Za-z][_A-Za-z0-9]*\b')

# identifier tokens that are Python keywords/builtins and never need project-index lookup.
_SKIP_TOKEN_NAMES = frozenset({ 'None', 'True', 'False', 'Any', 'Optional', 'Union', 'Literal' })

# cache of project-wide identifier sets, keyed by project root.
_PROJECT_IDENTIFIERS_CACHE: dict[str, frozenset[str]] = {}


def _load_project_identifiers(project_root: str) -> frozenset[str]:
  """
  Return the frozen set of all identifier tokens found in `project_root`'s `.py` files.

  Used to validate string literals appearing in member-name contexts
  (e.g., `'_foo' in cls.__dict__`): if the literal matches any identifier
  declared anywhere in the project, it is considered a real member name.

  Only NAME tokens from the tokenizer are collected, so identifier-like substrings
  appearing inside string literals, comments, or docstrings are excluded.

  Args:
    project_root: project root directory to scan recursively.

  Returns:
    Frozen set of identifier tokens seen across all `.py` files under `project_root`.
  """
  cached = _PROJECT_IDENTIFIERS_CACHE.get(project_root)
  if cached is not None:
    return cached

  idents: set[str] = set()
  for dirpath, dirnames, filenames in os.walk(project_root):
    # guard: prune excluded dirs so os.walk does not descend into them (e.g., .venv, __pycache__)
    dirnames[:] = [ d for d in dirnames if d not in HARDCODED_EXCLUDES ]
    for fname in filenames:
      # guard: only Python source files
      if not fname.endswith('.py'):
        continue
      path = os.path.join(dirpath, fname)
      try:
        with open(path, 'rb') as f:
          token_stream = tokenize.tokenize(f.readline)
          for tok in token_stream:
            if tok.type == tokenize.NAME:
              idents.add(tok.string)
      except (OSError, tokenize.TokenError, SyntaxError):
        continue

  frozen = frozenset(idents)
  _PROJECT_IDENTIFIERS_CACHE[project_root] = frozen
  return frozen


_CALLERS_WAIVER_TAG: str = 'pcf-external-callers-may-inline-literals'

# Strict tag form: standalone `#` comment line, `-- ` separator, non-empty reason.
_CALLERS_WAIVER_STRICT_RE: re.Pattern[str] = re.compile(
  r'^\s*#\s*waiver:\s*pcf-external-callers-may-inline-literals\s*--\s*(\S.*)$'
)
# Lenient detection: any line mentioning the tag (used to flag malformed/misplaced tags).
_CALLERS_WAIVER_ANY_RE: re.Pattern[str] = re.compile(
  r'#\s*waiver:\s*pcf-external-callers-may-inline-literals\b'
)

# Project-wide cache of callable tail names whose bodies carry a valid callers-waiver.
_WAIVERED_TAILS_CACHE: dict[str, frozenset[str]] = {}

# Project-wide cache of class names whose bodies carry a valid class-scope callers-waiver.
_WAIVERED_CLASSES_CACHE: dict[str, frozenset[str]] = {}


def _collect_waivered_tails_from_tree(tree: ast.Module, source_lines: list[str]) -> set[str]:
  """
  Return callable tail names whose bodies carry a valid external-callers-may-inline-literals waiver.

  For each tag-matching line found in `source_lines`, the innermost `FunctionDef`
  or `AsyncFunctionDef` body covering that line owns the waiver. The function's
  own name is added; for an `__init__` the enclosing class name is also added,
  so constructor call-sites resolve via the class tail.

  Args:
    tree: parsed AST module for the source.
    source_lines: source lines of the same module.

  Returns:
    Set of callable tail names exempted by this module's valid waivers.
  """
  tails: set[str] = set()

  tag_lines: list[int] = []
  for idx, line in enumerate(source_lines, start = 1):
    if _CALLERS_WAIVER_STRICT_RE.match(line):
      tag_lines.append(idx)
  # guard: no tags in this module
  if not tag_lines:
    return tails

  funcs: list[tuple[int, int, str, str | None]] = []

  def _walk(node: ast.AST, cls_name: str | None) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
      start = node.body[0].lineno
      last = node.body[-1]
      end = getattr(last, 'end_lineno', last.lineno) or last.lineno
      funcs.append((start, end, node.name, cls_name))
    new_cls = node.name if isinstance(node, ast.ClassDef) else cls_name
    for child in ast.iter_child_nodes(node):
      _walk(child, new_cls)

  _walk(tree, None)

  for lineno in tag_lines:
    candidates = [ f for f in funcs if f[0] <= lineno <= f[1] ]
    # guard: stray tag at non-function position -- ignored here, reported by validator
    if not candidates:
      continue
    innermost = min(candidates, key = lambda f: f[1] - f[0])
    _start, _end, fname, cname = innermost
    tails.add(fname)
    # guard: constructor waivers also exempt calls via the class name (ArgumentSpec(...))
    if fname == '__init__' and cname is not None:
      tails.add(cname)

  return tails


def _load_waivered_callable_tails(project_root: str) -> frozenset[str]:
  """
  Return the project-wide set of callable tail names exempted by callers-waivers.

  Scans every `.py` file under `project_root` whose contents mention the tag,
  parses each, and aggregates the tails reported by `_collect_waivered_tails_from_tree`.

  Args:
    project_root: project root directory to scan recursively.

  Returns:
    Frozen set of tail names. Empty if no valid waivers exist in the project.
  """
  cached = _WAIVERED_TAILS_CACHE.get(project_root)
  if cached is not None:
    return cached

  tails: set[str] = set()
  for dirpath, dirnames, filenames in os.walk(project_root):
    # guard: prune excluded dirs (e.g., .venv, __pycache__)
    dirnames[:] = [ d for d in dirnames if d not in HARDCODED_EXCLUDES ]
    for fname in filenames:
      # guard: only Python source files
      if not fname.endswith('.py'):
        continue
      path = os.path.join(dirpath, fname)
      try:
        with open(path, 'r', encoding = 'utf-8') as f:
          source = f.read()
      except OSError:
        continue
      # guard: skip files that do not mention the tag at all (fast path)
      if _CALLERS_WAIVER_TAG not in source:
        continue
      try:
        tree = ast.parse(source, filename = path)
      except SyntaxError:
        continue
      tails.update(_collect_waivered_tails_from_tree(tree, source.splitlines()))

  frozen = frozenset(tails)
  _WAIVERED_TAILS_CACHE[project_root] = frozen
  return frozen


def _collect_waivered_classes_from_tree(tree: ast.Module, source_lines: list[str]) -> set[str]:
  """
  Return class names whose bodies carry a valid class-scope callers-may-inline-literals waiver.

  For each tag-matching line, the innermost enclosing scope (class or function body)
  determines ownership. Tag lines whose innermost scope is a `ClassDef` body contribute
  that class's name. Tag lines whose innermost scope is a function body are
  function-scope and handled by `_collect_waivered_tails_from_tree`; this collector
  ignores them.

  Args:
    tree: parsed AST module for the source.
    source_lines: source lines of the same module.

  Returns:
    Set of class names exempted by this module's valid class-scope waivers.
  """
  classes: set[str] = set()

  tag_lines: list[int] = []
  for idx, line in enumerate(source_lines, start = 1):
    if _CALLERS_WAIVER_STRICT_RE.match(line):
      tag_lines.append(idx)
  # guard: no tags in this module
  if not tag_lines:
    return classes

  # (start, end, name, kind) for every class/function body
  nodes: list[tuple[int, int, str, str]] = []

  def _walk(node: ast.AST) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
      start = node.body[0].lineno
      last = node.body[-1]
      end = getattr(last, 'end_lineno', last.lineno) or last.lineno
      nodes.append((start, end, node.name, 'func'))
    elif isinstance(node, ast.ClassDef) and node.body:
      start = node.body[0].lineno
      last = node.body[-1]
      end = getattr(last, 'end_lineno', last.lineno) or last.lineno
      nodes.append((start, end, node.name, 'class'))
    for child in ast.iter_child_nodes(node):
      _walk(child)

  _walk(tree)

  for lineno in tag_lines:
    candidates = [ n for n in nodes if n[0] <= lineno <= n[1] ]
    # guard: tag outside any scope -- reported by validator, ignored here
    if not candidates:
      continue
    innermost = min(candidates, key = lambda n: n[1] - n[0])
    _start, _end, name, kind = innermost
    # guard: class-scope only -- function-scope handled by the tails collector
    if kind == 'class':
      classes.add(name)

  return classes


def _load_waivered_classes(project_root: str) -> frozenset[str]:
  """
  Return the project-wide set of class names exempted by class-scope callers-waivers.

  Scans every `.py` file under `project_root` whose contents mention the tag,
  parses each, and aggregates the class names reported by
  `_collect_waivered_classes_from_tree`.

  Args:
    project_root: project root directory to scan recursively.

  Returns:
    Frozen set of class names. Empty if no valid class-scope waivers exist.
  """
  cached = _WAIVERED_CLASSES_CACHE.get(project_root)
  if cached is not None:
    return cached

  classes: set[str] = set()
  for dirpath, dirnames, filenames in os.walk(project_root):
    # guard: prune excluded dirs (e.g., .venv, __pycache__)
    dirnames[:] = [ d for d in dirnames if d not in HARDCODED_EXCLUDES ]
    for fname in filenames:
      # guard: only Python source files
      if not fname.endswith('.py'):
        continue
      path = os.path.join(dirpath, fname)
      try:
        with open(path, 'r', encoding = 'utf-8') as f:
          source = f.read()
      except OSError:
        continue
      # guard: skip files that do not mention the tag at all (fast path)
      if _CALLERS_WAIVER_TAG not in source:
        continue
      try:
        tree = ast.parse(source, filename = path)
      except SyntaxError:
        continue
      classes.update(_collect_waivered_classes_from_tree(tree, source.splitlines()))

  frozen = frozenset(classes)
  _WAIVERED_CLASSES_CACHE[project_root] = frozen
  return frozen


def _is_env_read_call(call: ast.Call) -> bool:
  """
  Return True if `call` reads an environment variable.

  Matches `os.getenv(...)`, bare `getenv(...)`, and `os.environ.get(...)`.

  Args:
    call: the Call AST node.

  Returns:
    True if the call is a recognized env-var read.
  """
  func = call.func
  tail = _resolve_func_tail(func)
  # guard: `getenv(...)` / `os.getenv(...)` / `anything.getenv(...)`
  if tail in _ENV_READ_CALL_TAILS:
    return True
  # `<expr>.environ.get(...)` (typically `os.environ.get(...)`)
  if isinstance(func, ast.Attribute) and func.attr == 'get':
    receiver = func.value
    if isinstance(receiver, ast.Attribute) and receiver.attr == 'environ':
      return True
  return False


def _is_os_environ_ref(expr: ast.expr) -> bool:
  """
  Return True if `expr` refers to `os.environ` or its keys view.

  Matches `os.environ`, bare `environ`, and `os.environ.keys()` (same shape for
  membership tests). Other `.items()`/`.values()` are not recognized because
  they do not appear on the RHS of a name membership check.

  Args:
    expr: the AST expression node.

  Returns:
    True if the expression resolves to `os.environ` (or its `.keys()`).
  """
  # `os.environ` attribute access (also matches bare `environ` via attr == 'environ')
  if isinstance(expr, ast.Attribute) and expr.attr == 'environ':
    receiver = expr.value
    return isinstance(receiver, ast.Name) and receiver.id == 'os'
  # `os.environ.keys()` -- membership check shape
  if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) \
      and expr.func.attr == 'keys':
    return _is_os_environ_ref(expr.func.value)
  return False


def _resolve_func_tail(func: ast.expr) -> str | None:
  """
  Return the last segment of a call's func expression.

  For `foo.bar.baz(...)` returns `'baz'`; for `foo(...)` returns `'foo'`;
  for a complex expression like `x[0](...)` returns `None`.

  Args:
    func: the AST expression node used as a call's `func`.

  Returns:
    The final name segment, or `None` if not resolvable.
  """
  # guard: simple name call
  if isinstance(func, ast.Name):
    return func.id
  # guard: attribute-chain call
  if isinstance(func, ast.Attribute):
    return func.attr
  return None


# ----------------------------------------------------------------------------------------
# waiver: AST visitor methods must follow visit_NodeType naming convention required by ast.NodeVisitor
# pylint: disable=invalid-name
class MagicLiteralAnalyzer(ast.NodeVisitor):
  """
  AST visitor that flags magic numeric and string literals used inline.

  Applies the "Magic Literals" rule from `docs/guidelines/coding_guidelines.md`:
  every magic literal in a flagging context must be a named constant or carry a
  `# waiver: <reason>` comment. The detailed flag/skip policy is documented in
  that guideline section and mirrored here.
  """

  def __init__(self, source_lines: list[str], project_root: str | None = None,
               allowed_numbers: list[float] | None = None,
               allowed_strings: list[str] | None = None) -> None:
    """
    Initialize the magic-literal analyzer.

    Args:
      source_lines: list of source code lines, used for waiver detection.
      project_root: optional project root directory; when provided, enables
        cross-file validation of string literals used as member names.
      allowed_numbers: extra numeric values never flagged as magic, merged onto
        the built-in trivial set.
      allowed_strings: extra string values never flagged as magic, merged onto
        the built-in trivial set.
    """
    self.source_lines = source_lines
    self.project_root = project_root

    # trivial-literal sets: built-in defaults widened by consumer config
    self.trivial_numbers = _TRIVIAL_NUMBERS | frozenset(allowed_numbers or [])
    self.trivial_strings = _TRIVIAL_STRINGS | frozenset(allowed_strings or [])

    # lazy-loaded set of project-wide identifiers (populated on first member-name check)
    self._project_idents: frozenset[str] | None = None

    # lazy-loaded set of callable tails exempted by external-callers-may-inline-literals waivers
    self._waivered_tails: frozenset[str] | None = None

    # lazy-loaded set of class names exempted by class-scope callers waivers
    self._waivered_classes: frozenset[str] | None = None

    # list of issues found: `(line_number, message)`
    self.issues: list[tuple[int, str]] = []


  def visit(self, node: ast.AST) -> None:
    """
    Walk the tree root and dispatch to `visit_*` methods.

    Annotates every node with `parent` and `parent_field` on the first call, then
    defers to the base implementation.

    Args:
      node: the root AST node (typically the module).
    """
    # guard: annotate parents only on the root invocation (module has no parent)
    if not hasattr(node, 'parent'):
      self._annotate_parents(node)
      # guard: per-module tag-validation runs once, at the root entry
      if isinstance(node, ast.Module):
        self._validate_callers_waivers(node)
    super().visit(node)


  @staticmethod
  def _annotate_parents(root: ast.AST) -> None:
    """
    Annotate every descendant of `root` with `.parent` and `.parent_field`.

    Args:
      root: the root AST node.
    """
    # module root has no parent
    # waiver: ast.AST has no declared `parent` slot so direct assignment fails mypy
    setattr(root, 'parent', None)  # noqa: B010
    # waiver: ast.AST has no declared `parent_field` slot so direct assignment fails mypy
    setattr(root, 'parent_field', None)  # noqa: B010

    for parent in ast.walk(root):
      for field_name, value in ast.iter_fields(parent):
        if isinstance(value, list):
          for item in value:
            if isinstance(item, ast.AST):
              # waiver: ast.AST has no declared `parent` slot so direct assignment fails mypy
              setattr(item, 'parent', parent)  # noqa: B010
              # waiver: ast.AST has no declared `parent_field` slot so direct assignment fails mypy
              setattr(item, 'parent_field', field_name)  # noqa: B010
        elif isinstance(value, ast.AST):
          # waiver: ast.AST has no declared `parent` slot so direct assignment fails mypy
          setattr(value, 'parent', parent)  # noqa: B010
          # waiver: ast.AST has no declared `parent_field` slot so direct assignment fails mypy
          setattr(value, 'parent_field', field_name)  # noqa: B010


  def visit_Constant(self, node: ast.Constant) -> None:
    """
    Check a Constant node for magic-literal violations.

    Args:
      node: the Constant AST node.
    """
    value = node.value

    # guard: bools are Constant(True/False); never magic
    if isinstance(value, bool):
      return

    # guard: only strings and numbers can be magic literals
    if not isinstance(value, (str, int, float)):
      return

    # guard: numeric value in the trivial set
    if isinstance(value, (int, float)) and value in self.trivial_numbers:
      return

    # guard: string that is empty, in the trivial set, punctuation-only, or a format template
    if isinstance(value, str):
      # guard: empty string
      if not value:
        return
      # guard: trivial marker string (underscore, dunder-placeholder, etc.)
      if value in self.trivial_strings:
        return
      # guard: whitespace/punctuation only
      if _PUNCT_ONLY_RE.match(value):
        return
      # guard: format placeholder template
      if any(ch in value for ch in _FORMAT_PLACEHOLDER_CHARS):
        return

    # guard: not in a flagging context
    if not self._is_flag_context(node):
      return

    # guard: skip-context match
    if self._is_skip_context(node):
      return

    # guard: waiver present on surrounding line
    if _has_waiver(self.source_lines, node.lineno):
      return

    # guard: inside a TMP-marked statement or block
    if self._has_tmp_coverage(node):
      return

    # validated-name context: member-name probes (`'X' in __dict__` / `in vars()` / `in dir()`)
    # and TypeVar/NewType bound-string forward references. Skip if every identifier token in
    # the string exists in the project, flag with a stronger message otherwise.
    if isinstance(value, str) and self._is_validated_name_context(node):
      idents = self._get_project_identifiers()
      # guard: no project index available -- fall back to skip (trust the name)
      if idents is None:
        return
      missing = [ tok for tok in _IDENT_TOKEN_RE.findall(value)
                  if tok not in _SKIP_TOKEN_NAMES and tok not in idents
                  and not (tok.startswith('__') and tok.endswith('__')) ]
      # guard: every token resolves to a known identifier -- real name reference
      if not missing:
        return
      # unknown name(s) -- likely typo or stale reference
      display = ', '.join(repr(tok) for tok in missing)
      self.issues.append((
        node.lineno,
        f"name reference {display} not found in the project -- typo or stale reference?",
      ))
      return

    self.issues.append((
      node.lineno,
      self._format_message(value),
    ))


  def _get_project_identifiers(self) -> frozenset[str] | None:
    """
    Return the project-wide identifier set, loaded lazily on first use.

    Returns:
      Frozen set of identifiers, or None if no project root was configured.
    """
    # guard: no project root -- validation disabled
    if self.project_root is None:
      return None
    if self._project_idents is None:
      self._project_idents = _load_project_identifiers(self.project_root)
    return self._project_idents


  def _get_waivered_tails(self) -> frozenset[str]:
    """
    Return callable tails exempted by external-callers-may-inline-literals waivers.

    Returns:
      Frozen set of tail names. Empty when no project root is configured or
      when no valid waivers exist in the project.
    """
    # guard: no project root -- treat as empty
    if self.project_root is None:
      return frozenset()
    if self._waivered_tails is None:
      self._waivered_tails = _load_waivered_callable_tails(self.project_root)
    return self._waivered_tails


  def _get_waivered_classes(self) -> frozenset[str]:
    """
    Return class names exempted by class-scope external-callers-may-inline-literals waivers.

    Returns:
      Frozen set of class names. Empty when no project root is configured or
      when no valid class-scope waivers exist in the project.
    """
    # guard: no project root -- treat as empty
    if self.project_root is None:
      return frozenset()
    if self._waivered_classes is None:
      self._waivered_classes = _load_waivered_classes(self.project_root)
    return self._waivered_classes


  def _has_formatter_receiver(self, func: ast.expr) -> bool:
    """
    Return True if `func` is an attribute chain whose root is a waivered formatter class.

    Matches:
      - Instance method calls: `Cls().m(...)`, `Cls().m.n(...)`.
      - Classmethod calls:     `Cls.m(...)`, `Cls.at('x').format(...)`.
      - Ctor-chain calls:      `Cls(x).m1(...).m2(...)`.
      - Any `.logger.<method>(...)` chain, regardless of the root receiver
        (receiver-type-agnostic; kept as a built-in shorthand).

    The chain's innermost receiver must resolve to a class name in the project-wide
    class-scope waiver set (see `_get_waivered_classes`), either as a bare `Name`
    (classmethod call) or as a `Call.func` (constructor call), or the chain must
    traverse a `.logger` attribute hop.

    Args:
      func: the `func` expression of an outer Call node.

    Returns:
      True if a waivered formatter-class method call is detected.
    """
    cur: ast.expr | None = func
    while isinstance(cur, ast.Attribute):
      # any `.logger.<method>` hop in the chain marks this as a logger call
      if cur.attr == 'logger':
        return True
      cur = cur.value
    waivered = self._get_waivered_classes()
    # classmethod call: `Cls.method(...)` -- root is a bare Name
    if isinstance(cur, ast.Name):
      return cur.id in waivered
    # instance method call: `Cls().method(...)` -- root is a constructor Call
    if isinstance(cur, ast.Call):
      ctor_tail = _resolve_func_tail(cur.func)
      return ctor_tail in waivered
    return False


  def _validate_callers_waivers(self, tree: ast.Module) -> None:
    """
    Emit issues for malformed or misplaced `pcf-external-callers-may-inline-literals` tags.

    Rules enforced:
      - Tag must be a standalone comment line (optional leading whitespace, then `#`).
      - Tag must carry a non-empty reason after `--`.
      - Tag must lie inside a `FunctionDef`/`AsyncFunctionDef` body (function-scope)
        OR directly inside a `ClassDef` body, not nested in any method (class-scope).

    Args:
      tree: the parsed module AST.
    """
    func_ranges: list[tuple[int, int]] = []
    class_body_ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
        start = node.body[0].lineno
        last = node.body[-1]
        end = getattr(last, 'end_lineno', last.lineno) or last.lineno
        func_ranges.append((start, end))
      elif isinstance(node, ast.ClassDef) and node.body:
        start = node.body[0].lineno
        last = node.body[-1]
        end = getattr(last, 'end_lineno', last.lineno) or last.lineno
        class_body_ranges.append((start, end))

    misplaced_msg = (
      "misplaced pcf-external-callers-may-inline-literals waiver"
      " -- must be a standalone comment line inside a function/method body,"
      " or directly in a class body (not nested in a method)"
    )
    empty_reason_msg = (
      "pcf-external-callers-may-inline-literals waiver must have a non-empty reason after `--`"
    )

    for idx, line in enumerate(self.source_lines, start = 1):
      # guard: quick filter -- skip lines without the tag token
      if _CALLERS_WAIVER_ANY_RE.search(line) is None:
        continue
      # guard: inline trailing tag (line does not start with a '#' comment)
      stripped = line.lstrip()
      if not stripped.startswith('#'):
        self.issues.append((idx, misplaced_msg))
        continue
      # guard: tag without a non-empty reason after `--`
      if not _CALLERS_WAIVER_STRICT_RE.match(line):
        self.issues.append((idx, empty_reason_msg))
        continue
      # guard: function-scope placement -- tag inside any function body (including methods)
      if any(start <= idx <= end for start, end in func_ranges):
        continue
      # guard: class-scope placement -- tag directly in a class body (method-local
      # placement is already caught by func_ranges above, so this matches only direct
      # class-body children)
      if any(start <= idx <= end for start, end in class_body_ranges):
        continue
      # neither scope matched -- misplaced
      self.issues.append((idx, misplaced_msg))


  @staticmethod
  def _is_validated_name_context(node: ast.Constant) -> bool:
    """
    Return True if `node` is a string literal whose value must refer to a real project name.

    Covers:
      - Member-name probes: `'X' in EXPR.__dict__`, `'X' in vars(EXPR)`, `'X' in dir(EXPR)`.
      - Member-name `.get` lookups: `EXPR.__dict__.get('X', ...)`, `vars(EXPR).get('X', ...)`.
      - TypeVar/NewType bound-string forward references:
        `TypeVar('T', bound = '_BaseClass')`.
      - Field-name first positional arg of `.field_filter(...)` method calls:
        `db.field_filter('_store_mode', '==', value)`.

    Args:
      node: the Constant AST node.

    Returns:
      True if the literal is used as a name reference that must be validated.
    """
    parent = getattr(node, 'parent', None)

    # member-name probe: LHS of `in`/`not in` Compare against __dict__ / vars / dir
    if isinstance(parent, ast.Compare) and parent.left is node:
      if parent.ops and isinstance(parent.ops[0], (ast.In, ast.NotIn)):
        if parent.comparators:
          comp = parent.comparators[0]
          if isinstance(comp, ast.Attribute) and comp.attr == '__dict__':
            return True
          if isinstance(comp, ast.Call):
            tail = _resolve_func_tail(comp.func)
            if tail in _MEMBER_LIST_CALL_NAMES:
              return True

    # TypeVar/NewType(..., bound = 'X') kwarg
    if isinstance(parent, ast.keyword) and parent.arg == 'bound':
      call = getattr(parent, 'parent', None)
      if isinstance(call, ast.Call):
        tail = _resolve_func_tail(call.func)
        if tail in _NAME_ARG_CALL_NAMES:
          return True

    # first positional of TypeVar/NewType/NamedTuple/Enum/...: declared symbol name,
    # must resolve against the project identifier index.
    if isinstance(parent, ast.Call) and parent.args and parent.args[0] is node:
      tail = _resolve_func_tail(parent.func)
      if tail in _NAME_ARG_CALL_NAMES:
        return True

    # field-name arg of `.field_filter(...)`: first positional is the field name
    if isinstance(parent, ast.Call) and parent.args and parent.args[0] is node:
      tail = _resolve_func_tail(parent.func)
      if tail in _FIELD_NAME_METHOD_NAMES:
        return True

    # member-name `.get` lookup: `EXPR.__dict__.get('name', default)` or `vars(EXPR).get('name', ...)`
    # first positional is the attribute name, same semantic as `'name' in EXPR.__dict__`.
    if isinstance(parent, ast.Call) and parent.args and parent.args[0] is node:
      func = parent.func
      if isinstance(func, ast.Attribute) and func.attr == 'get':
        receiver = func.value
        # `<anything>.__dict__.get(...)`
        if isinstance(receiver, ast.Attribute) and receiver.attr == '__dict__':
          return True
        # `vars(<anything>).get(...)` or `dir(<anything>).get(...)` (dir returns list, but be consistent)
        if isinstance(receiver, ast.Call):
          recv_tail = _resolve_func_tail(receiver.func)
          if recv_tail in _MEMBER_LIST_CALL_NAMES:
            return True

    # attribute-name 2nd positional of getattr/setattr/hasattr/delattr: a literal name
    # must resolve to a real project identifier (dynamic name exprs never reach this visitor).
    if isinstance(parent, ast.Call) and len(parent.args) >= 2 and parent.args[1] is node:
      tail = _resolve_func_tail(parent.func)
      if tail in _ATTR_NAME_BUILTINS:
        return True

    return False


  def _has_tmp_coverage(self, node: ast.Constant) -> bool:
    """
    Return True if `node` lies inside a `# TMP`-marked statement or block.

    Matches an inline `# TMP` on the literal's own line, and a `# TMP` on the
    line immediately above any enclosing statement in the AST ancestor chain.

    Args:
      node: the Constant AST node (must have `.parent` annotations).

    Returns:
      True if a TMP marker covers this literal.
    """
    # inline TMP on the literal's own line
    if _has_tmp_marker_at_line(self.source_lines, node.lineno):
      return True

    # line immediately above the literal's own line (covers the case where the literal sits
    # on the first line of a TMP-covered statement, so no distinct ancestor lineno exists)
    if _has_tmp_marker_at_line(self.source_lines, node.lineno - 1):
      return True

    # walk ancestors; for each distinct lineno, check the line immediately above
    checked: set[int] = { node.lineno }
    cur: ast.AST | None = getattr(node, 'parent', None)
    while cur is not None:
      lineno = getattr(cur, 'lineno', None)
      if isinstance(lineno, int) and lineno not in checked:
        checked.add(lineno)
        # guard: check line above the ancestor's first line
        if _has_tmp_marker_at_line(self.source_lines, lineno - 1):
          return True
      cur = getattr(cur, 'parent', None)

    return False


  @staticmethod
  def _is_flag_context(node: ast.Constant) -> bool:
    """
    Return True if `node`'s parent is one of the flagging positions.

    Args:
      node: the Constant AST node (must have `.parent`/`.parent_field`).

    Returns:
      True if the literal appears in a context where magic values are forbidden.
    """
    parent = getattr(node, 'parent', None)
    field_name = getattr(node, 'parent_field', None)
    # guard: orphaned node (should not happen after annotation)
    if parent is None:
      return False

    # Call positional or keyword argument
    if isinstance(parent, ast.Call) and field_name in ('args',):
      return True
    if isinstance(parent, ast.keyword):
      return True

    # Compare left or comparator
    if isinstance(parent, ast.Compare):
      return True

    # Subscript slice (guard: trivial int index already filtered above)
    if isinstance(parent, ast.Subscript) and field_name == 'slice':
      return True

    # Return value
    if isinstance(parent, ast.Return) and field_name == 'value':
      return True

    # Augmented assign RHS
    if isinstance(parent, ast.AugAssign) and field_name == 'value':
      return True

    # BinOp operand where the other operand is not a Constant
    if isinstance(parent, ast.BinOp):
      other = parent.right if field_name == 'left' else parent.left
      return not isinstance(other, ast.Constant)

    return False


  def _is_skip_context(self, node: ast.Constant) -> bool:
    """
    Return True if one of the skip conditions applies to `node`.

    Args:
      node: the Constant AST node.

    Returns:
      True if the literal should be exempted from flagging.
    """
    # direct-parent checks (fast path)
    parent = getattr(node, 'parent', None)
    field_name = getattr(node, 'parent_field', None)

    # function default argument (FunctionDef.defaults / kw_defaults / Lambda.args defaults)
    if field_name in ('defaults', 'kw_defaults'):
      return True

    # f-string piece
    if isinstance(parent, (ast.JoinedStr, ast.FormattedValue)):
      return True

    # match/case pattern
    if isinstance(parent, (ast.MatchValue, ast.MatchSingleton)):
      return True

    # first statement of a module/class/function where the value is a str -> docstring
    if self._is_docstring(node):
      return True

    # env-var boolean idiom: `os.getenv(VAR) == '1'`, `os.environ.get(VAR) != '0'`, etc.
    # the '0'/'1'/'true'/... string is shell convention, not a domain value.
    if self._is_env_bool_compare(node):
      return True

    # main-guard idiom: `__name__ == '__main__'` (either side of the compare)
    if isinstance(parent, ast.Compare) \
        and isinstance(node.value, str) and node.value == '__main__':
      others: list[ast.expr] = [ parent.left, *parent.comparators ]
      for other in others:
        # guard: skip the literal itself when iterating the compare's operands
        if other is node:
          continue
        if isinstance(other, ast.Name) and other.id == '__name__':
          return True

    # env-var name membership: `<const> in os.environ` / `<const> not in os.environ`
    if isinstance(parent, ast.Compare) and parent.left is node \
        and parent.ops and isinstance(parent.ops[0], (ast.In, ast.NotIn)):
      for comp in parent.comparators:
        if _is_os_environ_ref(comp):
          return True

    # env-var name subscript: `os.environ[<const>]`
    if isinstance(parent, ast.Subscript) and field_name == 'slice' \
        and _is_os_environ_ref(parent.value):
      return True

    # walk-up checks
    return self._has_skip_ancestor(node)


  @staticmethod
  def _is_docstring(node: ast.Constant) -> bool:
    """
    Return True if `node` is the value of a docstring `Expr` statement.

    Args:
      node: the Constant AST node.

    Returns:
      True if the node is the first statement's string value in module/class/function.
    """
    # guard: docstrings are always string values
    if not isinstance(node.value, str):
      return False

    parent = getattr(node, 'parent', None)
    # guard: docstring value lives under an Expr statement
    if not (isinstance(parent, ast.Expr) and getattr(node, 'parent_field', None) == 'value'):
      return False

    grandparent = getattr(parent, 'parent', None)
    # guard: docstring Expr is the first body element of a module/class/function
    if not isinstance(grandparent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
      return False

    return bool(grandparent.body) and grandparent.body[0] is parent


  @staticmethod
  def _is_env_bool_compare(node: ast.Constant) -> bool:
    """
    Return True if `node` is an env-var boolean comparator (`'0'`, `'1'`, `'true'`, ...).

    Matches Compare nodes whose LHS is an env-var read -- `os.getenv(VAR)`,
    `os.environ.get(VAR)`, etc. -- and whose RHS is the tested literal.

    Args:
      node: the Constant AST node.

    Returns:
      True if the literal is the RHS of an env-var boolean compare.
    """
    # guard: only string literals in the env-bool set qualify
    if not (isinstance(node.value, str) and node.value in _ENV_BOOL_STRINGS):
      return False

    parent = getattr(node, 'parent', None)
    # guard: literal must be a comparator of a Compare node
    if not (isinstance(parent, ast.Compare) and node in parent.comparators):
      return False

    left = parent.left
    # guard: LHS must be an env-var read call (or a `.lower()` / `.strip()` chain on one)
    while isinstance(left, ast.Call) and isinstance(left.func, ast.Attribute) \
        and left.func.attr in ('lower', 'upper', 'strip', 'lstrip', 'rstrip'):
      left = left.func.value
    return isinstance(left, ast.Call) and _is_env_read_call(left)


  def _has_skip_ancestor(self, node: ast.Constant) -> bool:
    """
    Walk up from `node` and return True if any ancestor triggers a skip.

    Args:
      node: the Constant AST node.

    Returns:
      True if a skip-triggering ancestor is found.
    """
    cur_field = getattr(node, 'parent_field', None)
    cur = getattr(node, 'parent', None)
    child = node

    while cur is not None:
      # Call-based skips (apply only when we came up directly through the Call)
      if isinstance(cur, ast.Call) and self._call_skips_literal(cur, child, cur_field):
        return True

      # Raise-argument literal
      if isinstance(cur, ast.Raise):
        return True

      # Assert-message literal (assert cond, "message")
      if isinstance(cur, ast.Assert) and cur_field == 'msg':
        return True

      # Literal[...] / Annotated[...] subscript
      if isinstance(cur, ast.Subscript) and self._is_literal_annotated(cur):
        return True

      # Assign/AnnAssign RHS with ALL_CAPS Name target, or a dunder target
      if isinstance(cur, (ast.Assign, ast.AnnAssign)) and cur_field == 'value':
        if self._assign_is_constant_def(cur):
          return True

      # enum class body
      if isinstance(cur, ast.ClassDef) and self._class_is_enum(cur):
        return True

      # decorator list membership: ancestor is a decorator when its parent_field == 'decorator_list'
      if getattr(cur, 'parent_field', None) == 'decorator_list':
        return True

      child = cur
      cur_field = getattr(cur, 'parent_field', None)
      cur = getattr(cur, 'parent', None)

    return False


  def _call_skips_literal(self, call: ast.Call, child: ast.AST, child_field: str | None) -> bool:
    """
    Return True if `call`'s target identity exempts the literal passed in `child`.

    Args:
      call: the enclosing Call node.
      child: the direct child node that led up to `call`.
      child_field: the field name on `call` via which `child` is attached.

    Returns:
      True if the call is one of the exempted forms (print, logger, re, TypeVar, etc.).
    """
    tail = _resolve_func_tail(call.func)
    # guard: unresolvable call target
    if tail is None:
      return False

    # external-callers-may-inline-literals: the callee opted in via a body-level waiver.
    # Any literal in the call's argument tree (direct or nested inside expressions) is
    # exempted; literals in the `func` chain (receiver) are not.
    if tail in self._get_waivered_tails():
      # guard: literal reached this Call via an argument position, not via the receiver chain
      if child_field in ('args', 'keywords'):
        return True

    # logger/warnings methods: any literal inside the call is a message/format
    if tail in _LOGGER_METHOD_NAMES:
      return True

    # formatter class/instance method call: any class that opts in via a class-scope
    # `pcf-external-callers-may-inline-literals` waiver, or any `.logger.<method>` chain
    if self._has_formatter_receiver(call.func):
      return True

    # message-style builtins
    if tail in _MESSAGE_CALL_NAMES:
      return True

    # regex calls: pattern/replacement strings are not magic
    if tail in _REGEX_FUNC_NAMES and isinstance(call.func, ast.Attribute):
      # guard: the attribute chain must start at `re`
      root = call.func.value
      if isinstance(root, ast.Name) and root.id == 're':
        return True

    # dataclasses.field/pydantic.Field: default/default_factory kwargs are data
    if tail in _FIELD_CALL_NAMES:
      kw_node: ast.keyword | None = None
      if isinstance(child, ast.keyword):
        kw_node = child
      elif isinstance(child, ast.Constant):
        const_parent = getattr(child, 'parent', None)
        if isinstance(const_parent, ast.keyword):
          kw_node = const_parent
      if kw_node is not None and kw_node.arg in ('default', 'default_factory'):
        return True

    # path constructors: first positional string is a filesystem path
    if tail in _PATH_CTOR_NAMES:
      if call.args and call.args[0] is child:
        return True

    # open(...) / Path(...).open(...): mode (2nd positional) and encoding kwarg are standard
    if tail in _OPEN_CALL_NAMES:
      # guard: 2nd positional is the mode string
      if len(call.args) >= 2 and call.args[1] is child:
        return True
      # guard: keyword arg `mode` or `encoding`
      if isinstance(child, ast.keyword) and child.arg in _OPEN_EXEMPT_KWARGS:
        return True
      if isinstance(child, ast.Constant):
        kw_parent = getattr(child, 'parent', None)
        if isinstance(kw_parent, ast.keyword) and kw_parent.arg in _OPEN_EXEMPT_KWARGS:
          return True

    # .format(...) receiver: when the literal IS the attribute's value (template owner)
    # -- handled at Attribute level, not here (the literal is `call.func.value`, not in `args`)

    # float('inf') / float('nan') idiom: the string names a language-level token, not magic
    if tail == 'float' and isinstance(child, ast.Constant) and child_field == 'args':
      if len(call.args) == 1 and call.args[0] is child and child.value in _FLOAT_TOKEN_STRINGS:
        return True

    # os.getenv(VAR, '0') default / os.environ.get(VAR, '0') default:
    # '0'/'1'/'true'/'false'/... are shell-conventional booleans, not domain values.
    if _is_env_read_call(call) and isinstance(child, ast.Constant) and child_field == 'args':
      # guard: first positional is the env-var name (external identifier, not domain)
      if call.args and call.args[0] is child and isinstance(child.value, str):
        return True
      # guard: second positional is the env-bool default
      if isinstance(child.value, str) and child.value in _ENV_BOOL_STRINGS:
        return True

    return False


  @staticmethod
  def _is_literal_annotated(subscript: ast.Subscript) -> bool:
    """
    Return True if `subscript` is `Literal[...]` or `Annotated[...]`.

    Args:
      subscript: the Subscript AST node.

    Returns:
      True if the outer name is `Literal` or `Annotated`.
    """
    value = subscript.value
    if isinstance(value, ast.Name):
      return value.id in ('Literal', 'Annotated')
    if isinstance(value, ast.Attribute):
      return value.attr in ('Literal', 'Annotated')
    return False


  @staticmethod
  def _assign_is_constant_def(assign: ast.Assign | ast.AnnAssign) -> bool:
    """
    Return True if `assign` is a constant-definition: ALL_CAPS/dunder target, or at class-body scope.

    Class-body assignments (even with non-ALL_CAPS targets) are treated as the class's
    complex constants (e.g., `_protected_fields = { ... }`, `_cls_data_ver = { ... }`).

    Args:
      assign: the Assign or AnnAssign AST node.

    Returns:
      True if the assignment defines a constant rather than uses a literal inline.
    """
    # class-body-level assignment: the RHS IS the class's constant value
    parent = getattr(assign, 'parent', None)
    parent_field = getattr(assign, 'parent_field', None)
    if isinstance(parent, ast.ClassDef) and parent_field == 'body':
      return True

    targets: list[ast.expr] = list(assign.targets) if isinstance(assign, ast.Assign) else [ assign.target ]
    for tgt in targets:
      if isinstance(tgt, ast.Name):
        ident = tgt.id
        # guard: dunder name (e.g., __slots__, __all__, __version__)
        if ident.startswith('__') and ident.endswith('__'):
          return True
        # guard: ALL_CAPS constant (allow leading underscore, e.g., _CORE_CLASS_PREFIX)
        letters = ident.lstrip('_')
        if letters and letters == letters.upper() and any(ch.isalpha() for ch in letters):
          return True
    return False


  @staticmethod
  def _class_is_enum(class_def: ast.ClassDef) -> bool:
    """
    Return True if `class_def` inherits from one of the known enum base classes.

    Args:
      class_def: the ClassDef AST node.

    Returns:
      True if any base's name is in `_ENUM_BASE_NAMES`.
    """
    for base in class_def.bases:
      tail = _resolve_func_tail(base)
      if tail is not None and tail in _ENUM_BASE_NAMES:
        return True
    return False


  @staticmethod
  def _format_message(value: str | int | float) -> str:
    """
    Build the issue message for a flagged literal.

    Args:
      value: the magic literal value.

    Returns:
      The formatted issue message string.
    """
    display: str | int | float = value
    if isinstance(value, str) and len(value) > _MAX_LITERAL_DISPLAY_LEN:
      display = value[:_MAX_LITERAL_DISPLAY_LEN] + '...'
    return (
      f"magic literal {display!r}"
      " -- move it to an Enum or a class-level constants container"
      " (add '# waiver: <reason>' to exempt)"
    )


  def analyze(self) -> list[tuple[int, str]]:
    """
    Return the list of issues found, sorted by line number.

    Returns:
      List of (line_number, message) tuples for each issue found.
    """
    return sorted(self.issues, key = lambda x: x[0])


def analyze_file(path: str, config: dict | None = None) -> list[tuple[int, str]]:
  """
  Analyze a Python file for code format issues.

  Args:
    path: path to the Python file to analyze.
    config: configuration dictionary with settings.

  Returns:
    List of (line_number, message) tuples for each issue found.
  """
  # use default config if not provided
  if config is None:
    config = DEFAULT_CONFIG.copy()

  # read and parse the file
  with open(path, 'r', encoding = 'utf-8') as f:
    source = f.read()

  source_lines = source.splitlines()
  tree = ast.parse(source, filename = path)

  all_issues: list[tuple[int, str]] = []

  # check if this is an __init__.py file
  is_init_file = os.path.basename(path) == '__init__.py'

  # run import format checks if enabled
  if config.get('check_imports', True):
    import_analyzer = ImportFormatAnalyzer(source_lines, is_init_file, file_path = path)
    import_analyzer.visit(tree)
    all_issues.extend(import_analyzer.analyze())

  # run docstring checks if enabled
  if config.get('check_docstrings', True):
    mll_raw = config.get('max_line_length', 117)
    max_line_length = mll_raw if isinstance(mll_raw, int) else 117
    # only check docstring line length if both check_docstrings and check_line_length are enabled
    check_docstring_line_length = bool(config.get('check_line_length', True))
    check_docstring_content = bool(config.get('check_docstring_content', True))
    banned_phrases_raw = config.get('banned_docstring_phrases', []) or []
    banned_phrases = (
      [ p for p in banned_phrases_raw if isinstance(p, str) ]
      if isinstance(banned_phrases_raw, list) else []
    )
    extra_sections_raw = config.get('extra_docstring_sections', []) or []
    extra_sections = (
      [ e for e in extra_sections_raw if isinstance(e, dict) ]
      if isinstance(extra_sections_raw, list) else []
    )
    d2_markers_raw = config.get('d2_exempt_marker_attrs', []) or []
    d2_markers = (
      [ n for n in d2_markers_raw if isinstance(n, str) ]
      if isinstance(d2_markers_raw, list) else []
    )
    private_allowlist_raw = config.get('private_name_allowlist', []) or []
    private_allowlist = (
      [ n for n in private_allowlist_raw if isinstance(n, str) ]
      if isinstance(private_allowlist_raw, list) else []
    )
    docstring_analyzer = DocstringAnalyzer(
      source_lines,
      max_line_length = max_line_length,
      check_line_length = check_docstring_line_length,
      check_docstring_content = check_docstring_content,
      banned_docstring_phrases = banned_phrases,
      extra_docstring_sections = extra_sections,
      d2_exempt_marker_attrs = d2_markers,
      private_name_allowlist = private_allowlist
    )
    docstring_analyzer.visit(tree)
    all_issues.extend(docstring_analyzer.analyze())

  # run magic-literal checks if enabled
  if bool(config.get('check_magic_literal', True)):
    project_root_raw = config.get('_project_root')
    project_root = project_root_raw if isinstance(project_root_raw, str) else None
    allowed_numbers_raw = config.get('allowed_magic_numbers', []) or []
    allowed_numbers = (
      [ n for n in allowed_numbers_raw if isinstance(n, (int, float)) and not isinstance(n, bool) ]
      if isinstance(allowed_numbers_raw, list) else []
    )
    allowed_strings_raw = config.get('allowed_magic_strings', []) or []
    allowed_strings = (
      [ s for s in allowed_strings_raw if isinstance(s, str) ]
      if isinstance(allowed_strings_raw, list) else []
    )
    magic_analyzer = MagicLiteralAnalyzer(
      source_lines,
      project_root = project_root,
      allowed_numbers = allowed_numbers,
      allowed_strings = allowed_strings,
    )
    magic_analyzer.visit(tree)
    all_issues.extend(magic_analyzer.analyze())

  # run code format checks if enabled (line length and other code format rules)
  check_code_format = bool(config.get('check_code_format', True))
  check_line_length_global = bool(config.get('check_line_length', True))
  if check_code_format:
    mll_raw = config.get('max_line_length', 117)
    max_line_length = mll_raw if isinstance(mll_raw, int) else 117
    # only check code line length if both check_code_format and check_line_length are enabled
    check_code_line_length = check_line_length_global
    code_analyzer = CodeFormatAnalyzer(
      source_lines,
      max_line_length = max_line_length,
      is_init_file = is_init_file,
      check_line_length = check_code_line_length,
      check_indentation = True,
      check_assert = bool(config.get('check_assert', True))
    )
    all_issues.extend(code_analyzer.analyze())

  return sorted(all_issues, key = lambda x: x[0])


def walk_dir(root: str, 
             exclude_substrings: list[str], 
             config: dict | None = None) -> tuple[SuggestionsMap, int]:
  """
  Walk the directory tree and analyze all Python files for code format issues.

  Args:
    root: root directory path to scan.
    exclude_substrings: list of substrings to exclude from file paths.
    config: configuration dictionary with settings.

  Returns:
    Tuple containing issues map and files processed count.
  """
  # initialize containers for results
  all_issues: SuggestionsMap = defaultdict(list)
  files_processed = 0

  # combine hardcoded and user-provided exclusions
  all_excludes = HARDCODED_EXCLUDES + exclude_substrings

  project_root = config.get('_project_root', root) if config else root

  # recursively walk directory and process all .py files
  for dirpath, _, filenames in os.walk(root):
    for fname in filenames:
      if fname.endswith('.py'):
        path = os.path.join(dirpath, fname)
        # guard: skip excluded paths
        if any(sub in path for sub in all_excludes):
          continue
        try:
          file_config = resolve_config_for_file(config, path, project_root) if config else config
          issues = analyze_file(path, file_config)
          files_processed += 1
          if issues:
            all_issues[path].extend(issues)
        except SyntaxError as err:
          print(f'[!] Syntax error in {path}: {err}', file = sys.stderr)

  return all_issues, files_processed


def main() -> None:
  """
  The main entry point for the Python code format checker CLI tool.

  Parse command line arguments, scan directories, and report findings.
  """
  # setup CLI parser
  parser = argparse.ArgumentParser(description = "Check Python code format in files")
  parser.add_argument('path', nargs = '?', default = '.',
                      help = 'root directory to scan')
  parser.add_argument('--exclude', action = 'append', metavar = 'SUBSTRING',
                      help = 'exclude files or directories containing this substring')
  parser.add_argument('--no-imports', action = 'store_true',
                      help = 'disable import format checks')
  parser.add_argument('--no-docstrings', action = 'store_true',
                      help = 'disable docstring format checks')
  parser.add_argument('--no-line-length', action = 'store_true',
                      help = 'disable line length checks')
  parser.add_argument('--no-code-format', action = 'store_true',
                      help = 'disable code format checks (indentation, etc.)')
  parser.add_argument('--no-assert', action = 'store_true',
                      help = 'disable assert statement checks')
  parser.add_argument('--max-line-length', type = int, default = None,
                      help = 'maximum line length (default: 117)')
  args = parser.parse_args()

  # get a path from CLI or use the current directory
  base_path = os.path.abspath(args.path)

  # load configuration from pyproject.toml
  config = load_config(base_path)

  # get excludes from config, CLI args can extend the list
  config_excludes = list(config.get('exclude', []))

  # raw (untrimmed) config excludes — used for the single-file exclude check below.
  # the directory-mode trimming (next block) is about not silently skipping an explicitly
  # requested directory; it must not weaken the exclude decision for a single file.
  raw_config_excludes = list(config_excludes)

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

  # override config with CLI arguments
  if args.no_imports:
    config['check_imports'] = False
  if args.no_docstrings:
    config['check_docstrings'] = False
  if args.no_line_length:
    config['check_line_length'] = False
  if args.no_code_format:
    config['check_code_format'] = False
  if args.no_assert:
    config['check_assert'] = False
  if args.max_line_length is not None:
    config['max_line_length'] = args.max_line_length

  # single-file or directory mode
  if os.path.isfile(base_path):
    # single-file mode
    # honor the exclude list for an explicitly-passed file, same model as directory mode
    # (walk_dir): a file matching a hardcoded or [tool.pcf] exclude substring is skipped.
    # this makes a hook-invoked excluded file (e.g. under .venv / ~archive / a project
    # exclude path) a clean no-op rather than a forced scan. Uses the untrimmed config
    # excludes — a single file target should never weaken the exclude decision the way a
    # directory target deliberately does.
    single_file_excludes = list(raw_config_excludes)
    if args.exclude:
      single_file_excludes.extend(args.exclude)
    all_excludes = HARDCODED_EXCLUDES + single_file_excludes
    # guard: explicitly-passed file is on the exclude list → skip without analyzing
    if any(sub in base_path for sub in all_excludes):
      print('Skipped: 1 excluded source file')
      return
    project_root = config.get('_project_root', os.getcwd())
    file_config = resolve_config_for_file(config, base_path, project_root)
    try:
      issues = analyze_file(base_path, file_config)
    except SyntaxError as err:
      print(f'[!] Syntax error in {base_path}: {err}', file = sys.stderr)
      sys.exit(1)
    relpath = os.path.relpath(base_path, start = os.getcwd())
    if issues:
      for lineno, message in issues:
        print(f'{relpath}:{lineno}: note: {message}')
      print('Found issues in 1 source file')
    else:
      print('Success: no issues found in 1 source file')
  else:
    # directory mode
    results, files_processed = walk_dir(base_path, exclude_substrings, config)

    # print all issues in file:line format
    for filepath, issues in results.items():
      relpath = os.path.relpath(filepath, start = os.getcwd())
      for lineno, message in issues:
        print(f'{relpath}:{lineno}: note: {message}')

    # print summary at the end
    if not results:
      print(f'Success: no issues found in {files_processed} source files')
    else:
      print(f'Found issues in {len(results)} of {files_processed} source files')


# run main if this is the top-level script
if __name__ == '__main__':
  main()
