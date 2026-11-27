from __future__ import annotations

from types import MappingProxyType

import argparse
import ast
import json
import os
import re
import sys
from enum import StrEnum
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Iterator, Mapping


# The module's own flat bin/ directory first on the import path, so its sibling modules resolve
_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from constants import RoutineKey, SettingsFile, SettingsKey  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from lazy_settings import load_section  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from lazy_setup import find_dev_plugins  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from plugin_locator import installed_plugin_roots, query_repo_root  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from shebang_exec import ShebangError, read_shebang  # noqa: E402


# The core CLI verb that carries an in-band failure into the error ledger
_ERROR_RECORD_VERB = "error-record"
# Repo-relative path tail of the core module that writes the error ledger itself
_LEDGER_WRITER_TAIL = "lazycortex-core/bin/error_ledger.py"
# The function of that module that appends an event to the ledger
_LEDGER_WRITER_NAME = "record"
# The one repair route every finding names
_FIX = ("exit non-zero, or report the failure with the core CLI's `error-record --cause <constant>` "
        "per lazy-core.error-ledger")
# A file name or path segment that names a file of errors: `errors.log`, `error.txt`, `failures.json`, `run.err`
_ERROR_FILE_RE = re.compile(r"(?i)(?:^|[/\\._-])(?:errors?|err|failures?|failed)(?:[/\\._-]|$)")
# Text that only a notification of the code's own carries: desktop notifiers, mailers, chat webhooks
_NOTIFY_MARKERS = (
  "notify-send", "terminal-notifier", "display notification", "sendmail", "hooks.slack.com",
  "discord.com/api/webhooks", "discordapp.com/api/webhooks", "api.telegram.org", "ntfy.sh", "api.pushover.net",
)
# The stdlib mail module whose import alone is an own notification channel
_SMTP_MODULE = "smtplib"
# Interpreter basenames whose entry file is read as a shell script
_SHELL_NAMES = frozenset({ "sh", "bash", "zsh", "dash", "ksh" })
# Interpreter basename prefix of a Python entry file (`python`, `python3`, `python3.12`)
_PYTHON_PREFIX = "python"
# The builtin that prints; called in a handler it reports what was caught
_PRINT = "print"
# The stdlib logging module, whose every call writes a record
_LOGGING_MODULE = "logging"
# Name tokens that say a variable or collection holds failures: `failed`, `errors`, `unresolved`, `domain_error`
_FAILURE_TOKENS = frozenset({
  "err", "error", "errors", "fail", "fails", "failed", "failing", "failure", "failures", "skip", "skips", "skipped",
  "problem", "problems", "broken", "unresolved",
})
# Name tokens of a success flag; set to `False` it is an explicit failure marker: `ok`, `is_ok`, `success`
_OK_TOKENS = frozenset({ "ok", "success", "succeeded", "healthy" })
# Name tokens of an exit status; set to a non-zero number it is an explicit failure marker: `rc`, `exit_code`
_STATUS_TOKENS = frozenset({ "rc", "exit", "code", "status", "returncode" })
# One lowercase word of a snake_case or camelCase name
_NAME_TOKEN_RE = re.compile(r"[a-z0-9]+")
# A lowercase-to-uppercase boundary inside a camelCase name
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
# The replacement that splits a camelCase boundary into a snake_case one
_CAMEL_TO_SNAKE = r"\1_\2"
# Constructors that build an empty container when called with no argument
_EMPTY_CONSTRUCTORS = frozenset({ "list", "dict", "set", "tuple", "frozenset", "str" })
# Receivers of a method call that stays inside the module defining the method
_SELF_NAMES = frozenset({ "self", "cls" })
# The stdlib call that imports a module by name at run time
_IMPORT_MODULE = "import_module"
# The builtin and method name that opens a file
_OPEN = "open"
# The keyword argument that carries the mode of `open`
_MODE_KEYWORD = "mode"
# The stream method that writes text
_WRITE = "write"
# The standard streams a handler prints to
_STREAM_NAMES = frozenset({ "stderr", "stdout" })
# Methods that add an item to a collection
_COLLECT_METHODS = frozenset({ "append", "add", "extend", "insert", "update", "setdefault" })
# Process-exit calls whose argument decides success or failure
_EXIT_CALLS = frozenset({ "exit", "_exit", "quit" })
# Logger methods that write a record; called on a logger they report what the handler caught
_LOG_METHODS = frozenset({ "debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log" })
# A receiver name that is a logger: `log`, `logger`, `_LOG`, `LOGGER`
_LOGGER_NAME_RE = re.compile(r"(?i)^_*(?:log|logger|logging)$")
# Write-mode letters of `open`; any of them makes the call a write
_WRITE_MODE_CHARS = frozenset("wax+")
# Path methods that write a whole file
_WRITE_METHODS = frozenset({ "write_text", "write_bytes" })
# Suffix of the stdlib logging handlers that write records to a file
_FILE_HANDLER_SUFFIX = "FileHandler"
# Shell: a `||` fallback that only prints (`cmd || echo "failed" >&2`)
_SH_PRINT_FALLBACK_RE = re.compile(r"\|\|\s*\{?\s*(?:echo|printf|logger)\b")
# Shell: an exit or return with a status other than 0, or a call to the ledger verb
_SH_SIGNAL_RE = re.compile(r"\b(?:exit|return)\s+(?!0\b)\S|error-record")
# Shell: the target of an output redirection or of `tee`
_SH_WRITE_TARGET_RE = re.compile(r"(?:\d|&)?>>?\s*([^\s;|&<>]+)|\btee\b(?:\s+-a)?\s+([^\s;|&<>]+)")
# Shell: the comment leader
_SH_COMMENT = "#"
# Shell: the opener of a command substitution, whose `||` fallback supplies a value instead of reporting
_SH_SUBST_OPEN = "$("
# Shell: the legacy backtick command substitution
_SH_BACKTICK = "`"
# Suffix of a Python sibling module in a plugin's `bin/`
_PY_SUFFIX = ".py"
# Name of a plugin's bin directory
_BIN_DIR = "bin"
# Nodes inside a handler whose statements belong to a construct of their own, not to the handler
_OWN_SCOPE_NODES = ( ast.ExceptHandler, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef )
# Text encoding every scanned file is read in
_ENCODING = "utf-8"


# ----------------------------------------------------------------------------------------
class LedgerFindingKind(StrEnum):
  """
  The ways a routine's code carries a failure past the error ledger.

  Guarantees:
    - Member values are the tokens the report carries as a finding's kind and the audit skill matches literally;
      a value is never changed or reused for another meaning.

  Attributes:
    SWALLOWED_FAILURE: A caught error is printed or logged and the code goes on as a success.
    PRIVATE_ERROR_FILE: Errors are written into a file of the code's own.
    OWN_NOTIFICATION: The code sends a notification of its own.
  """

  # Contract:
  # Member values are the tokens the report carries as a finding's kind and the audit skill matches literally;
  # a value is never changed or reused for another meaning.

  # A caught error is printed or logged and the code goes on as a success.
  SWALLOWED_FAILURE = "swallowed_failure"
  # Errors are written into a file of the code's own.
  PRIVATE_ERROR_FILE = "private_error_file"
  # The code sends a notification of its own.
  OWN_NOTIFICATION = "own_notification"


# ----------------------------------------------------------------------------------------
class SkipKind(StrEnum):
  """
  Why a routine's code was not scanned.

  Guarantees:
    - Member values are the tokens the report carries as a skip reason and the audit skill matches literally;
      a value is never changed or reused for another meaning.

  Attributes:
    PLUGIN_CLI: The routine runs a plugin installed for this repo or the user that the repo does not author.
    UNRESOLVED: The repo authors the plugin but holds no entry file for it, or the plugin is neither authored nor
      installed.
    NOT_SCANNED: The file is in a language the check does not read, or does not parse.
  """

  # Contract:
  # Member values are the tokens the report carries as a skip reason and the audit skill matches literally;
  # a value is never changed or reused for another meaning.

  # The routine runs a plugin installed for this repo or the user that the repo does not author.
  PLUGIN_CLI = "plugin_cli"
  # The repo authors the plugin but holds no entry file for it, or the plugin is neither authored nor installed.
  UNRESOLVED = "unresolved"
  # The file is in a language the check does not read, or does not parse.
  NOT_SCANNED = "not_scanned"


# ----------------------------------------------------------------------------------------
class LanguageKind(StrEnum):
  """
  Languages whose files the check reads.

  Guarantees:
    - Member values are the tokens the report carries as a routine's language and the audit skill matches
      literally; a value is never changed or reused for another meaning.

  Attributes:
    PYTHON: A Python file, read as a syntax tree.
    SHELL: A shell script, read line by line.
  """

  # Contract:
  # Member values are the tokens the report carries as a routine's language and the audit skill matches literally;
  # a value is never changed or reused for another meaning.

  # A Python file, read as a syntax tree.
  PYTHON = "python"
  # A shell script, read line by line.
  SHELL = "shell"


# ----------------------------------------------------------------------------------------
class LedgerAuditKey:
  """
  Keys of the report the `error-ledger-audit` verb prints.

  Guarantees:
    - Member values are the keys of the JSON report that the audit skill reads by name; a value is never renamed
      or reused for another meaning.

  Attributes:
    FINDINGS: The list of findings.
    SCANNED: The list of routines whose code was read.
    SKIPPED: The list of routines whose code was not read.
    KIND: A finding's kind.
    PATH: The repo-relative file a record is about.
    LINE: A finding's 1-based line.
    DETAIL: A finding's description.
    FIX: A finding's repair route.
    ROUTINE: The routine a record is about.
    ENTRY: The repo-relative entry file a routine runs.
    LANGUAGE: The language a routine's code was read as.
    FILES: The repo-relative files read for a routine.
    REASON: Why a routine's code was not read.
  """

  # Contract:
  # Member values are the keys of the JSON report that the audit skill reads by name;
  # a value is never renamed or reused for another meaning.

  # The list of findings.
  FINDINGS = "findings"
  # The list of routines whose code was read.
  SCANNED = "scanned"
  # The list of routines whose code was not read.
  SKIPPED = "skipped"
  # A finding's kind.
  KIND = "kind"
  # The repo-relative file a record is about.
  PATH = "path"
  # A finding's 1-based line.
  LINE = "line"
  # A finding's description.
  DETAIL = "detail"
  # A finding's repair route.
  FIX = "fix"
  # The routine a record is about.
  ROUTINE = "routine"
  # The repo-relative entry file a routine runs.
  ENTRY = "entry"
  # The language a routine's code was read as.
  LANGUAGE = "language"
  # The repo-relative files read for a routine.
  FILES = "files"
  # Why a routine's code was not read.
  REASON = "reason"


# ----------------------------------------------------------------------------------------
class _PythonLedgerScan:
  """
  Scan of one routine's Python files for failures that bypass the error ledger.

  Attributes:
    trees: Parsed modules of the routine's files, keyed by repo-relative path.
    strings: Per file, the module-level names bound to a string literal, with their values.
    modules: Per file, the module name other files import it under.
    aliases: Per file, the local names its imports bind to a sibling module or to a function of one.
    defined: Per file, the names of the functions it defines.
    reporters: Names of the functions that report a failure through the ledger verb or the core ledger writer.
  """


  def __init__(self, trees: dict[str, ast.Module]) -> None:
    """
    Prepare the scan of a set of parsed files.

    Args:
      trees: Repo-relative path to the parsed module, for every file the routine runs.
    """
    # every parsed file, keyed by its repo-relative path, as a read-only copy the caller cannot change
    self.trees: Mapping[str, ast.Module] = MappingProxyType(dict(trees))

    # per file, its module-level names bound to a string literal
    self.strings: dict[str, dict[str, str]] = { rel: _find_all_module_strings(tree) for rel, tree in trees.items() }

    # per file, the module name other files import it under
    self.modules: dict[str, str] = { rel: Path(rel).stem for rel in trees }

    # per file, the local names its imports bind to a sibling module or to a function of one
    self.aliases: dict[str, dict[str, tuple[str, str | None]]] = {
      rel: _find_all_import_aliases(tree, set(self.modules.values())) for rel, tree in trees.items()
    }

    # per file, the names of the functions it defines
    self.defined: dict[str, set[str]] = {
      rel: { node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) }
      for rel, tree in trees.items()
    }

    # opt: tables are built once per scan; valid because every audit run parses its files afresh into a new scan

    # the functions, as module and name, that run the ledger verb or write the ledger, directly or through another
    self.reporters: set[tuple[str, str]] = self._find_all_reporters()


  def _find_all_reporters(self) -> set[tuple[str, str]]:
    """
    Find every function across the files that runs the ledger verb or is the core ledger writer, directly or
    through another such function.

    Returns:
      The functions as `(module, name)` pairs.
    """
    # every function definition with the file it lives in
    functions = [
      (rel, node) for rel, tree in self.trees.items() for node in ast.walk(tree)
      if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]

    # a function naming the verb, or the core function that writes the ledger, is a reporter; one calling a
    # reporter becomes one, until nothing changes
    reporters = { (self.modules[rel], node.name) for rel, node in functions
                  if self._is_naming_verb(rel, node) or _is_ledger_writer(rel, node) }
    grown = True
    while grown:
      added = { (self.modules[rel], node.name) for rel, node in functions
                if (self.modules[rel], node.name) not in reporters
                and self._find_all_called_functions(rel, node) & reporters }
      reporters |= added
      grown = bool(added)
    return reporters


  def _find_all_called_functions(self, rel: str, node: ast.AST) -> set[tuple[str, str]]:
    """
    Find the functions of the scanned files a subtree calls, resolved to the module defining them.

    Args:
      rel: Repo-relative path of the file holding the subtree.
      node: The subtree.

    Returns:
      The called functions as `(module, name)` pairs; a call that resolves to no scanned module is left out.
    """
    return { target for sub in ast.walk(node) if isinstance(sub, ast.Call)
             and (target := self._find_call_target(rel, sub)) is not None }


  def _find_call_target(self, rel: str, call: ast.Call) -> tuple[str, str] | None:
    """
    Find the scanned function a call invokes.

    Args:
      rel: Repo-relative path of the file holding the call.
      call: The call.

    Returns:
      `(module, name)` for a function this file defines, one it imports by name from a sibling, or one called on
      an imported sibling module or on `self` / `cls`; None for any other call.
    """
    # `f()`: a function of this module, else one imported by name from a sibling
    if isinstance(call.func, ast.Name):
      if call.func.id in self.defined[rel]:
        return self.modules[rel], call.func.id
      module, original = self.aliases[rel].get(call.func.id, ("", None))
      return (module, original) if original is not None else None

    # guard: a call on anything but a name has no module to resolve against
    if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
      return None

    # `module.f()` on an imported sibling, or `self.f()` inside the module defining `f`
    receiver = call.func.value.id
    if receiver in _SELF_NAMES:
      return self.modules[rel], call.func.attr
    module, original = self.aliases[rel].get(receiver, ("", ""))
    return (module, call.func.attr) if module and original is None else None


  def _is_naming_verb(self, rel: str, node: ast.AST) -> bool:
    """
    Tell whether a subtree names the ledger verb, as a literal or through a module-level string constant.

    Args:
      rel: Repo-relative path of the file holding the subtree.
      node: The subtree.

    Returns:
      True when any string the subtree spells or names contains the verb.
    """
    return any(_ERROR_RECORD_VERB in text for text in self._find_all_strings(rel, node))


  def _find_all_strings(self, rel: str, node: ast.AST) -> list[str]:
    """
    Read every string a subtree spells as a literal or names through a module-level constant, docstrings aside.

    Args:
      rel: Repo-relative path of the file holding the subtree.
      node: The subtree.

    Returns:
      The strings, in walk order.
    """
    constants = self.strings[rel]

    # a docstring or any other bare string statement runs nothing, so it names nothing
    inert = { sub.value for sub in ast.walk(node)
              if isinstance(sub, ast.Expr) and isinstance(sub.value, ast.Constant) }

    # every spelled or named string of the subtree, in walk order
    found: list[str] = []
    for sub in ast.walk(node):

      # a string literal that is not a bare statement, or a name bound to one at module level
      if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub not in inert:
        found.append(sub.value)
      elif isinstance(sub, ast.Name) and sub.id in constants:
        found.append(constants[sub.id])
    return found


  def _find_all_reporter_handlers(self, rel: str, tree: ast.Module) -> set[ast.ExceptHandler]:
    """
    Find the exception handlers that sit inside the functions of a file that report to the ledger themselves.

    Args:
      rel: Repo-relative path of the file.
      tree: The parsed file.

    Returns:
      The handlers inside every function of the file that runs the ledger verb itself or writes the ledger; a
      function that only calls such a function is not one of them.
    """
    return { sub for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
             and (self._is_naming_verb(rel, node) or _is_ledger_writer(rel, node))
             for sub in ast.walk(node) if isinstance(sub, ast.ExceptHandler) }


  def _find_all_covered_handlers(self, rel: str, tree: ast.Module) -> set[ast.ExceptHandler]:
    """
    Find the exception handlers that sit inside another handler of a file that signals its failure.

    Args:
      rel: Repo-relative path of the file.
      tree: The parsed file.

    Returns:
      The handlers nested at any depth inside a handler that re-raises, exits non-zero, reports to the ledger or
      marks the failure; the signalling handler itself is not among them.
    """

    # Domain(runtime.error-ledger):
    # # A handler inside a signalling handler
    # A handler nested inside another handler that signals its failure is innocent: whatever it prints, the outer
    # handler carries the failure on.

    # every handler at any depth under a handler that signals
    return { inner for outer in ast.walk(tree)
             if isinstance(outer, ast.ExceptHandler) and self._is_signalling(rel, outer)
             for inner in ast.walk(outer) if isinstance(inner, ast.ExceptHandler) and inner is not outer }


  def _find_all_notify_lines(self, rel: str, call: ast.Call) -> list[int]:
    """
    Find the lines of the notifier, mailer or webhook strings a call is handed.

    Args:
      rel: Repo-relative path of the file holding the call.
      call: The call.

    Returns:
      The line of every literal, or module constant use, among the call's arguments that only a notifier carries.
    """
    constants = self.strings[rel]
    lines: list[int] = []
    for argument in [ *call.args, *(keyword.value for keyword in call.keywords) ]:
      for sub in ast.walk(argument):

        # a literal, or a name bound to one at module level, whose text only a notifier carries
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
          text = sub.value
        elif isinstance(sub, ast.Name):
          text = constants.get(sub.id, "")
        else:
          continue
        if any(marker in text for marker in _NOTIFY_MARKERS):
          lines.append(sub.lineno)
    return lines


  def _is_signalling(self, rel: str, handler: ast.ExceptHandler) -> bool:
    """
    Tell whether an exception handler signals the failure it caught.

    Args:
      rel: Repo-relative path of the file holding the handler.
      handler: The handler.

    Returns:
      True when the handler raises, returns or exits with a failure value, sets a failure flag, or runs the
      ledger verb.
    """

    # Domain(runtime.error-ledger):
    # # When a handler signals its failure
    # A handler that prints or logs a caught error is innocent as long as it also signals the failure onward. It
    # signals when it raises, returns or exits with a non-success value, sets a failure flag, or carries the
    # failure in a variable or collection named for failures that the code reports from later. It also signals
    # when it reports the failure to the ledger through the core's recording command, whether directly or through
    # a function that does. Only the handler's own statements count: one inside a nested handler or function
    # belongs to that construct. A handler with none of these lets the failure vanish and the run looks
    # successful.

    # the handler's own nodes; a nested handler or function judges its own statements
    own = list(_list_own_nodes(handler))

    # the ledger verb, spelled in the handler or reached through a reporter function
    called = { target for node in own if isinstance(node, ast.Call)
               and (target := self._find_call_target(rel, node)) is not None }
    if (called & self.reporters
        or any(self._is_naming_verb(rel, node) for node in own if isinstance(node, ast.Constant | ast.Name))):
      return True

    # otherwise the handler signals only through a statement that carries the failure onward
    return any(_is_failure_statement(node) for node in own)


  def _is_error_file_write(self, rel: str, call: ast.Call) -> bool:
    """
    Tell whether a call writes into a file whose path names errors.

    Args:
      rel: Repo-relative path of the file holding the call.
      call: The call.

    Returns:
      True for a write-mode `open`, a whole-file write or a logging file handler whose path names errors.
    """
    # guard: the call writes no file
    if (target := _find_write_target(call)) is None:
      return False
    return any(_ERROR_FILE_RE.search(text) for text in self._find_all_strings(rel, target))


  def find_all_findings(self) -> list[tuple[str, int, LedgerFindingKind]]:
    """
    Find every place in the files where a failure bypasses the error ledger.

    Returns:
      `(path, line, kind)` triples, one per offending construct.
    """

    # Domain(runtime.error-ledger):
    # # Ways a failure bypasses the error ledger
    # The core error ledger is the one channel through which a failure of a routine's code reaches the operator.
    # Code carries a failure past it in exactly three ways, and nothing else is a violation. First, a caught error
    # is printed or logged and the code then goes on as if it had succeeded. Second, errors are written into a
    # file of the code's own, whose name says it holds errors. Third, the code sends a failure notification of its
    # own, by mail, desktop notifier or chat webhook. A line printed to the error stream beside a non-zero exit is
    # not a violation: the exit already carries the failure to the ledger.

    # Domain(runtime.error-ledger):
    # # A failed report is not a bypass
    # Reporting a failure never breaks the work it reports on, so a report that itself fails has no channel
    # left but the error stream. A caught error printed inside the very code that sends the report to the
    # ledger, or inside the code that writes the ledger, is that last resort and not a violation. Code that only
    # hands a failure to such a reporter gets no such allowance for any other failure it catches.

    # every offending construct of every file, gathered before deduplication
    found: list[tuple[str, int, LedgerFindingKind]] = []
    for rel, tree in self.trees.items():
      exempt = self._find_all_reporter_handlers(rel, tree) | self._find_all_covered_handlers(rel, tree)
      for node in ast.walk(tree):

        # a caught error that is reported by hand and then dropped, outside the reporting code and outside a
        # handler that carries the failure on itself
        if (isinstance(node, ast.ExceptHandler) and node not in exempt and _is_reporting_by_hand(node)
            and not self._is_signalling(rel, node)):
          found.append((rel, node.lineno, LedgerFindingKind.SWALLOWED_FAILURE))

        # a write into a file whose name says it holds errors
        if isinstance(node, ast.Call) and self._is_error_file_write(rel, node):
          found.append((rel, node.lineno, LedgerFindingKind.PRIVATE_ERROR_FILE))

        # a mail module of its own
        if isinstance(node, ast.Import | ast.ImportFrom) and _is_smtp_import(node):
          found.append((rel, node.lineno, LedgerFindingKind.OWN_NOTIFICATION))

        # a notifier, mailer or webhook a call is handed; a docstring or comment sends nothing
        if isinstance(node, ast.Call):
          found.extend((rel, line, LedgerFindingKind.OWN_NOTIFICATION)
                       for line in self._find_all_notify_lines(rel, node))

    # a constant passed down through nested calls is one construct, reported once
    return sorted(set(found))


# ----------------------------------------------------------------------------------------
# What each finding kind says is wrong
_DETAILS = MappingProxyType({
  LedgerFindingKind.SWALLOWED_FAILURE: "a caught failure is printed or logged and the code goes on as a success",
  LedgerFindingKind.PRIVATE_ERROR_FILE: "errors are written into a file of the code's own",
  LedgerFindingKind.OWN_NOTIFICATION: "the code sends a failure notification of its own",
})


def _is_ledger_writer(rel: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
  """
  Tell whether a function is the core function that writes the error ledger.

  Args:
    rel: Repo-relative path of the file defining the function.
    node: The function definition.

  Returns:
    True for the ledger's own append function in the core plugin's bin directory.
  """
  return rel.endswith(_LEDGER_WRITER_TAIL) and node.name == _LEDGER_WRITER_NAME


def _find_all_module_strings(tree: ast.Module) -> dict[str, str]:
  """
  Read the module-level names bound to a string literal.

  Args:
    tree: The parsed module.

  Returns:
    Name to its string value.
  """
  return {
    target.id: node.value.value
    for node in tree.body if isinstance(node, ast.Assign)
    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    for target in node.targets if isinstance(target, ast.Name)
  }


def _find_all_import_aliases(tree: ast.Module, siblings: set[str]) -> dict[str, tuple[str, str | None]]:
  """
  Find the local names a module's imports bind to a sibling module or to a function of one.

  Args:
    tree: The parsed module.
    siblings: Module names of the files scanned with it.

  Returns:
    Local name to `(module, None)` for `import module`, or to `(module, function)` for
    `from module import function`; imports of anything but a sibling are left out.
  """
  aliases: dict[str, tuple[str, str | None]] = {}
  for node in ast.walk(tree):

    # `import module [as name]`
    if isinstance(node, ast.Import):
      aliases.update({ alias.asname or alias.name: (alias.name, None) for alias in node.names
                       if alias.name in siblings })

    # `from module import function [as name]`
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in siblings:
      aliases.update({ alias.asname or alias.name: (node.module, alias.name) for alias in node.names })
  return aliases


def _extract_call_name(call: ast.Call) -> str:
  """
  Read the bare name a call invokes.

  Args:
    call: The call.

  Returns:
    The function name for `f()`, the attribute for `x.f()`, an empty string for anything else.
  """
  if isinstance(call.func, ast.Name):
    return call.func.id
  return call.func.attr if isinstance(call.func, ast.Attribute) else ""


def _list_own_nodes(handler: ast.ExceptHandler) -> Iterator[ast.AST]:
  """
  Walk the nodes that belong to a handler itself.

  Args:
    handler: The handler.

  Yields:
    The handler and its descendants, in walk order, leaving out every nested handler and every nested function,
    lambda or class with all they hold.
  """
  pending: list[ast.AST] = [ handler ]
  while pending:
    node = pending.pop(0)
    yield node

    # a nested handler or scope carries statements of its own, judged on their own
    pending.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, _OWN_SCOPE_NODES))


def _is_reporting_by_hand(handler: ast.ExceptHandler) -> bool:
  """
  Tell whether a handler prints or logs.

  Args:
    handler: The handler.

  Returns:
    True when the handler's own statements call `print`, write to a standard stream, or call a logger.
  """
  for node in _list_own_nodes(handler):

    # guard: only a call prints or logs; every other node is passed over
    if not isinstance(node, ast.Call):
      continue

    # `print(...)` itself
    if isinstance(node.func, ast.Name) and node.func.id == _PRINT:
      return True

    # `sys.stderr.write(...)`, a logging module call, or a logger method
    if isinstance(node.func, ast.Attribute):
      receiver_name = _extract_target_name(node.func.value)
      if node.func.attr == _WRITE and receiver_name in _STREAM_NAMES:
        return True
      if _LOGGER_NAME_RE.match(receiver_name) and (node.func.attr in _LOG_METHODS
                                                   or receiver_name == _LOGGING_MODULE):
        return True
  return False


def _is_failure_statement(node: ast.AST) -> bool:
  """
  Tell whether one node of a handler signals failure.

  Args:
    node: A node inside the handler.

  Returns:
    True for a raise, a return or an exit carrying a value that is not empty or zero, a write to a name that says
    it holds a failure, an explicit failure marker, or a failure added to a collection of them.
  """

  # a raise, re-raise included
  if isinstance(node, ast.Raise):
    return True

  # a return or an exit carrying something other than success
  if isinstance(node, ast.Return):
    return node.value is not None and not _is_success_value(node.value)
  if isinstance(node, ast.Call) and _extract_call_name(node) in _EXIT_CALLS:
    return bool(node.args) and not _is_success_value(node.args[0])

  # a failure variable, or an explicit failure marker, the code reads later to fail
  if isinstance(node, ast.Assign | ast.AugAssign):
    targets = node.targets if isinstance(node, ast.Assign) else [ node.target ]
    return any(_is_failure_assignment(_parse_name_tokens(_extract_target_name(target)), node.value)
               for target in targets)

  # the failure joins a collection the code reports from later: `failed.append(name)`
  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _COLLECT_METHODS:
    return bool(_parse_name_tokens(_extract_target_name(node.func.value)) & _FAILURE_TOKENS)
  return False


def _is_failure_assignment(tokens: set[str], value: ast.expr) -> bool:
  """
  Tell whether an assignment to a name made of the given tokens carries a failure onward.

  Args:
    tokens: The lowercase words of the assigned name.
    value: The assigned value.

  Returns:
    True for any value bound to a name that says it holds a failure, `False` bound to a success flag, or a
    non-zero number bound to an exit status.
  """

  # a name that says it holds failures carries whatever it is given
  if tokens & _FAILURE_TOKENS:
    return True

  # guard: only a literal can be an explicit failure marker
  if not isinstance(value, ast.Constant):
    return False

  # `ok = False`, or `rc = 1`
  if tokens & _OK_TOKENS and value.value is False:
    return True
  return (bool(tokens & _STATUS_TOKENS) and isinstance(value.value, int) and not isinstance(value.value, bool)
          and value.value != 0)


def _parse_name_tokens(name: str) -> set[str]:
  """
  Split a snake_case or camelCase name into its lowercase words.

  Args:
    name: The name.

  Returns:
    The words: `domain_error` gives `domain` and `error`, `failedItems` gives `failed` and `items`.
  """
  return set(_NAME_TOKEN_RE.findall(_CAMEL_BOUNDARY_RE.sub(_CAMEL_TO_SNAKE, name).lower()))


def _extract_target_name(node: ast.expr) -> str:
  """
  Read the name an assignment target or a method receiver binds.

  Args:
    node: The expression.

  Returns:
    The name for `x`, the attribute for `a.x`, the subscripted name for `x[k]`, else an empty string.
  """
  if isinstance(node, ast.Subscript):
    return _extract_target_name(node.value)
  if isinstance(node, ast.Name):
    return node.id
  return node.attr if isinstance(node, ast.Attribute) else ""


def _is_success_value(node: ast.expr) -> bool:
  """
  Tell whether an expression is a zero or empty value, which carries no failure onward.

  Args:
    node: The expression.

  Returns:
    True for a falsy literal (`0`, `None`, `False`, `""`), an empty container display (`[]`, `{}`, `()`), or an
    empty container built with no argument (`list()`, `dict()`).
  """

  # a falsy literal
  if isinstance(node, ast.Constant):
    return not node.value

  # an empty display, or an empty constructor call
  if isinstance(node, ast.List | ast.Tuple | ast.Set):
    return not node.elts
  if isinstance(node, ast.Dict):
    return not node.keys
  return (isinstance(node, ast.Call) and not node.args and not node.keywords
          and _extract_call_name(node) in _EMPTY_CONSTRUCTORS)


def _find_write_target(call: ast.Call) -> ast.AST | None:
  """
  Find the expression naming the file a call writes.

  Args:
    call: The call.

  Returns:
    The path expression of a write-mode `open`, a `write_text` / `write_bytes`, or a logging file handler; None
    when the call writes no file.
  """
  name = _extract_call_name(call)

  # a logging handler that writes its records to a file
  if name.endswith(_FILE_HANDLER_SUFFIX):
    return call.args[0] if call.args else None

  # a whole-file write on a path object
  if name in _WRITE_METHODS and isinstance(call.func, ast.Attribute):
    return call.func.value

  # any other call that is not `open` writes no file
  if name != _OPEN:
    return None

  # `open(path, mode)` takes the path first; `path.open(mode)` is called on it
  is_method = isinstance(call.func, ast.Attribute)
  modes = [ *(call.args[0:1] if is_method else call.args[1:2]),
            *(keyword.value for keyword in call.keywords if keyword.arg == _MODE_KEYWORD) ]
  is_write = any(isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                 and _WRITE_MODE_CHARS & set(mode.value) for mode in modes)

  # a read-mode open writes no file; a write-mode one writes the path it was given
  if not is_write:
    return None
  if is_method and isinstance(call.func, ast.Attribute):
    return call.func.value
  return call.args[0] if call.args else None


def _is_smtp_import(node: ast.Import | ast.ImportFrom) -> bool:
  """
  Tell whether an import brings in the stdlib mail module.

  Args:
    node: The import.

  Returns:
    True for `import smtplib` and `from smtplib import ...`.
  """
  if isinstance(node, ast.Import):
    return any(alias.name.split(".")[0] == _SMTP_MODULE for alias in node.names)
  return isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == _SMTP_MODULE


def _find_all_shell_findings(rel: str, text: str) -> list[tuple[str, int, LedgerFindingKind]]:
  """
  Find every line of a shell script where a failure bypasses the error ledger.

  Args:
    rel: Repo-relative path of the script.
    text: The script's text.

  Returns:
    `(path, line, kind)` triples, at most one per kind per line.
  """
  found: list[tuple[str, int, LedgerFindingKind]] = []
  for number, line in enumerate(text.splitlines(), start = 1):

    # guard: a comment or a blank line runs nothing
    if not line.strip() or line.lstrip().startswith(_SH_COMMENT):
      continue

    # Domain(runtime.error-ledger):
    # # A shell fallback that only prints
    # A command whose failure branch only prints a line and lets the script carry on has swallowed that failure,
    # unless the same line goes on to exit or return with a failure status, or to report to the ledger. A print
    # fallback inside a command substitution is different: there it supplies a default value for the substituted
    # text, and the failure it stands in for is not a failure of the script.

    # a `||` fallback that prints and carries on, with no failure exit after it and outside a substitution
    fallback = _SH_PRINT_FALLBACK_RE.search(line)
    if (fallback and not _SH_SIGNAL_RE.search(line, fallback.end())
        and not _is_in_substitution(line, fallback.start())):
      found.append((rel, number, LedgerFindingKind.SWALLOWED_FAILURE))

    # a redirection or `tee` into a file whose name says it holds errors
    targets = [ match.group(1) or match.group(2) for match in _SH_WRITE_TARGET_RE.finditer(line) ]
    if any(_ERROR_FILE_RE.search(target.strip("\"'")) for target in targets):
      found.append((rel, number, LedgerFindingKind.PRIVATE_ERROR_FILE))

    # a notifier, mailer or webhook of the script's own
    if any(marker in line for marker in _NOTIFY_MARKERS):
      found.append((rel, number, LedgerFindingKind.OWN_NOTIFICATION))
  return found


def _is_in_substitution(line: str, position: int) -> bool:
  """
  Tell whether a position of a shell line lies inside a command substitution.

  Args:
    line: The shell line.
    position: Index into the line.

  Returns:
    True inside an open `$(...)` or an open backtick pair, where a `||` fallback supplies a value.
  """
  head = line[:position]

  # an odd number of backticks before the position leaves one open
  if head.count(_SH_BACKTICK) % 2:
    return True

  # each `(` opens a frame that `)` closes; a frame opened by `$(` is a substitution
  frames: list[bool] = []
  for index, char in enumerate(head):
    if char == "(":
      frames.append(head[max(index - 1, 0):index + 1] == _SH_SUBST_OPEN)
    elif char == ")" and frames:
      frames.pop()
  return any(frames)


def _read_all_python_files(entry: Path) -> list[Path]:
  """
  Find a Python entry file and every sibling module it imports, transitively.

  Notes:
    - Reads each file it visits from disk.

  Args:
    entry: The entry file.

  Returns:
    The entry first, then the imported siblings in discovery order; a file that cannot be read or does not parse
    is kept and its imports are not followed.
  """
  # the module names of every Python file beside the entry, the only files an import can reach
  siblings = { name.removesuffix(_PY_SUFFIX) for name in os.listdir(entry.parent) if name.endswith(_PY_SUFFIX) }

  # breadth-first over the files reached so far, starting at the entry
  found = [ entry ]
  pending = [ entry ]
  while pending:
    path = pending.pop(0)

    # guard: a file that cannot be read or parsed stays in the result, its imports unfollowed
    try:
      tree = ast.parse(path.read_text(encoding = _ENCODING), filename = str(path))
    except (OSError, SyntaxError, ValueError):
      continue

    # every bare module name the file imports statically
    names = { alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
              for alias in node.names }
    names |= { node.module.split(".")[0] for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module }
    names |= _find_all_dynamic_imports(tree, siblings)

    # a name is a sibling when the same bin directory holds its module file
    for name in sorted(names & siblings):
      sibling = entry.parent / f"{name}{_PY_SUFFIX}"
      if sibling not in found:
        found.append(sibling)
        pending.append(sibling)
  return found


def _find_all_dynamic_imports(tree: ast.Module, siblings: set[str]) -> set[str]:
  """
  Find the sibling modules a file can load through `importlib.import_module`.

  Args:
    tree: The parsed file.
    siblings: Module names of every `.py` file in the entry's bin directory.

  Returns:
    The literal argument of each call; for a call whose argument is computed, every string of the file that names
    a sibling (a verb-to-module table), or every sibling when no string names one. Empty when the file loads no
    module by name.
  """
  calls = [ node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _extract_call_name(node) == _IMPORT_MODULE ]
  literals = { call.args[0].value for call in calls
               if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str) }

  # when every module the file loads by name is spelled at its call, those names are the whole set
  if all(call.args and isinstance(call.args[0], ast.Constant) for call in calls):
    return literals

  # Decision: a computed module name follows the file's own sibling-naming strings, not the call alone — the
  # table form spells every module once; with no such string nothing is provable, so every sibling is read

  # the sibling names the file spells, else every sibling
  named = { node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in siblings }
  return literals | (named or siblings)


def _read_language(entry: Path) -> LanguageKind | None:
  """
  Read the language of an entry file from its shebang.

  Notes:
    - Reads the first line of the file.

  Args:
    entry: The entry file.

  Returns:
    The language when the shebang names a Python or shell interpreter, else None.
  """
  # guard: an entry with no readable shebang names no interpreter, so no reader applies
  try:
    interpreter = Path(read_shebang(entry)[0]).name
  except ShebangError:
    return None

  # a Python or shell interpreter decides the reader; any other is not read
  if interpreter.startswith(_PYTHON_PREFIX):
    return LanguageKind.PYTHON
  return LanguageKind.SHELL if interpreter in _SHELL_NAMES else None


def _scan_python(repo: Path, entry: Path) -> tuple[list[str], list[tuple[str, int, LedgerFindingKind]], list[str]]:
  """
  Scan a Python entry file and its sibling modules.

  Notes:
    - Reads every file of the entry's module set.

  Args:
    repo: Repository root.
    entry: The entry file.

  Returns:
    The repo-relative files scanned, the findings, and the repo-relative files that did not parse.
  """
  # every file of the entry's module set, parsed, and the ones that do not parse
  trees: dict[str, ast.Module] = {}
  broken: list[str] = []
  for path in _read_all_python_files(entry):
    rel = path.relative_to(repo).as_posix()

    # a file that cannot be read or parsed is recorded as broken and left out of the scan
    try:
      trees[rel] = ast.parse(path.read_text(encoding = _ENCODING), filename = str(path))
    except (OSError, SyntaxError, ValueError):
      broken.append(rel)

  # one scan over every file that parsed, so a reporter in one module counts in another
  return list(trees), _PythonLedgerScan(trees).find_all_findings(), broken


def _scan_shell(rel_entry: str,
                entry: Path) -> tuple[list[str], list[tuple[str, int, LedgerFindingKind]], list[str]]:
  """
  Scan a shell entry script.

  Notes:
    - Reads the script from disk.

  Args:
    rel_entry: Repo-relative path of the script.
    entry: The script.

  Returns:
    The repo-relative files scanned, the findings, and the repo-relative files that could not be read.
  """
  # guard: a script that cannot be read is reported as not scanned
  try:
    # waiver: stdlib decode-error mode, not a domain constant
    text = entry.read_text(encoding = _ENCODING, errors = "replace")
  except OSError:
    return [], [], [ rel_entry ]

  # the script is the one file a shell routine runs
  return [ rel_entry ], _find_all_shell_findings(rel_entry, text), []


def _resolve_entry(repo: Path, plugin: str, installed: dict[str, Path]) -> tuple[Path | None, SkipKind | None]:
  """
  Resolve the entry file a routine's plugin name runs, or the reason none can be read.

  Notes:
    - Inspects the repository's plugin tree on disk.

  Args:
    repo: Repository root.
    plugin: The routine command's first element.
    installed: Plugin name to install root, for the plugins installed for this repo or for the user.

  Returns:
    `(entry, None)` for a plugin the repo authors, installed or not, when it has an entry file. Otherwise
    `(None, reason)`: `SkipKind.PLUGIN_CLI` for a plugin installed for this repo or the user but not authored here,
    `SkipKind.UNRESOLVED` for an authored plugin without an entry file or a plugin neither authored nor installed
    for this repo or the user.
  """

  # Domain(runtime.routines):
  # # Whose code a routine runs
  # A routine names a plugin, never a file. A plugin the repository authors is the repository's own
  # code, whether or not the machine also installs it, and the error-ledger audit reads it from the
  # repository's own entry file. A plugin installed for this repository or the whole user that the
  # repository does not author is read where it is authored, so here it is skipped and yields no
  # finding. A plugin the repository authors without an entry file, or one neither authored nor
  # installed for this repository or the user, cannot be resolved.

  # the repo's own plugin of that name, by its entry file named after the plugin
  if (root := find_dev_plugins(repo).get(plugin)) is not None:
    entry = root / _BIN_DIR / plugin
    return (entry, None) if entry.is_file() else (None, SkipKind.UNRESOLVED)

  # a plugin installed for this repo or the user is authored elsewhere; one known nowhere is unresolved
  return None, SkipKind.PLUGIN_CLI if plugin in installed else SkipKind.UNRESOLVED


def audit(repo: Path, home: Path) -> dict[str, list[dict]]:
  """
  Audit the code a repo's routines run for failures that bypass the core error ledger.

  Guarantees:
    - Reads only; no file is written.
    - A routine whose plugin the repo authors is read from the repo's own entry file even when the machine install
      registry records that plugin; a plugin only the registry records is never scanned, yields no finding and is
      reported as skipped.

  Notes:
    - Reads the repository's settings file with its local overlay, the machine's plugin install registry, and the
      code files of every command routine the repository authors.

  Args:
    repo: Repository root.
    home: Home directory holding the machine's plugin install registry.

  Returns:
    The findings, the routines whose code was scanned, and the routines skipped with their reason, under the
    `LedgerAuditKey` keys.

  Raises:
    ValueError: If the settings file or its local overlay is not valid JSON, or its top level is not a JSON object.
  """

  # Contract:
  # The audit only reads; it never writes, creates or deletes any file.

  # Contract:
  # A routine whose plugin the repo authors is read from the repo's own entry file even when the machine
  # install registry records that plugin; a plugin only the registry records is never scanned, yields no finding
  # and is reported as skipped.

  # the installs the machine's registry records for this repo or the user, and the result lists
  installed = installed_plugin_roots(repo, home)
  scanned: list[dict] = []
  skipped: list[dict] = []
  findings: set[tuple[str, int, LedgerFindingKind]] = set()

  # every command routine, in name order; an expert routine runs agent text, which is never read
  for name, entry_cfg in sorted(load_section(repo / SettingsFile.REL, SettingsKey.ROUTINES).items()):
    command = entry_cfg.get(RoutineKey.COMMAND) if isinstance(entry_cfg, dict) else None

    # guard: no command vector, so no code of the repo's own runs
    if not isinstance(command, list) or not command or not isinstance(command[0], str):
      continue

    # the file the routine runs; a plugin this repo does not author is recorded as skipped
    entry, reason = _resolve_entry(repo, command[0], installed)
    if entry is None:
      skipped.append({ LedgerAuditKey.ROUTINE: name, LedgerAuditKey.REASON: reason, LedgerAuditKey.PATH: None })
      continue

    # the language the entry is read as; one the check does not read is recorded as not scanned
    rel_entry = entry.relative_to(repo).as_posix()
    language = _read_language(entry)
    if language is None:
      skipped.append({ LedgerAuditKey.ROUTINE: name, LedgerAuditKey.REASON: SkipKind.NOT_SCANNED,
                       LedgerAuditKey.PATH: rel_entry })
      continue

    # the entry and, for Python, its sibling modules, read by the language's own scanner
    if language is LanguageKind.PYTHON:
      files, found, broken = _scan_python(repo, entry)
    else:
      files, found, broken = _scan_shell(rel_entry, entry)
    findings.update(found)
    scanned.append({ LedgerAuditKey.ROUTINE: name, LedgerAuditKey.ENTRY: rel_entry,
                     LedgerAuditKey.LANGUAGE: language, LedgerAuditKey.FILES: files })
    skipped.extend({ LedgerAuditKey.ROUTINE: name, LedgerAuditKey.REASON: SkipKind.NOT_SCANNED,
                     LedgerAuditKey.PATH: rel } for rel in broken)

  # one finding per construct even when several routines run the same file, in file and line order
  return {
    LedgerAuditKey.FINDINGS: [
      { LedgerAuditKey.KIND: kind, LedgerAuditKey.PATH: rel, LedgerAuditKey.LINE: line,
        LedgerAuditKey.DETAIL: _DETAILS[kind], LedgerAuditKey.FIX: _FIX }
      for rel, line, kind in sorted(findings)
    ],
    LedgerAuditKey.SCANNED: scanned,
    LedgerAuditKey.SKIPPED: skipped,
  }


def cmd_error_ledger_audit(argv: list[str]) -> int:
  """
  Run the `error-ledger-audit` subcommand: print the audit report as JSON.

  Guarantees:
    - The exit code is 0 whenever a report was printed, whatever it holds; findings never change it.
    - A non-zero exit means no report was printed.

  Notes:
    - Writes the report, or the error object, to standard output as one JSON line.
    - Reads the same files as `audit`.

  Args:
    argv: Argument vector after the subcommand name (optional `--cwd`).

  Returns:
    Process exit code: 0 when the report was printed, findings or not; 1 when the settings file or its local overlay
    is not valid JSON or its top level is not a JSON object.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """

  # Contract:
  # The exit code is 0 whenever a report was printed, whatever it holds; findings never change it.
  # A non-zero exit means no report was printed.

  # the verb's command line: the repo-root override alone
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core error-ledger-audit")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")

  # the report is printed whole; an unreadable settings file is the one failure
  try:
    report = audit(query_repo_root(parser.parse_args(argv).cwd), Path.home())
  except ValueError as error:
    # waiver: the CLI's shared error-JSON key, not a domain key
    print(json.dumps({ "error": str(error) }, ensure_ascii = False))
    return 1
  print(json.dumps(report, ensure_ascii = False))
  return 0
