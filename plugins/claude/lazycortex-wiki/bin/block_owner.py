from __future__ import annotations

import ast
import hashlib

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Encoding the owner digest is computed over.
_ENCODING = "utf-8"

# Node types whose leading string statement is a docstring, dropped before serialisation.
_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

# Node types that own the blocks written inside their body.
_SCOPE_OWNERS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

# The syntax-tree field holding a module, class or function body.
_BODY_FIELD = "body"

# Fields a newer Python grammar added, with the value its parser writes when the new syntax is not used;
# a field at that value renders like its absence on an older Python.
_NEUTRAL_FIELDS = { "is_lazy": 0 }


# ----------------------------------------------------------------------------------------
class OwnerIndex:
  """
  Index of one source file that maps a comment block's line to the digest of the code owning it.
  """

  def __init__(self, source: str) -> None:
    """
    Prepare owner lookups for one source file.

    Construction is cheap and never fails: a file that does not parse as Python is accepted and owned as a whole.

    Args:
      source: Full text of the source file.
    """
    # the raw text backs both the parse and the whole-file fallback for a file that is not Python
    self._source: str = source

    # opt: the module is parsed once, on the first lookup, and reused; correct because the source text is fixed
    # at construction and never changes afterwards
    self._tree: ast.Module | None = None
    self._parsed: bool = False

  def digest_at(self, line: int) -> str:
    """
    Return the digest of the code that owns the block written at `line`.

    A file that does not parse as Python is owned as a whole, so its digest covers the entire text.

    Guarantees:
      - For a file that parses as Python, the digest is unchanged by reformatting, comments,
        docstrings and line position of the owning code, and by edits outside the owner.
      - The digest is identical across supported Python versions for the same code.
      - A file that does not parse as Python is digested from its whole text.

    Args:
      line: 1-based line of the block's header.

    Returns:
      Hex sha256 digest of the owner's canonical form.
    """

    # Contract:
    # For a file that parses as Python, the digest is unchanged by reformatting, comments,
    # docstrings and line position of the owning code, and by edits outside the owner.
    # The digest is identical across supported Python versions for the same code.
    # A file that does not parse as Python is digested from its whole text.

    # Domain(wiki.domains):
    # # The code a knowledge block is about
    # A knowledge comment describes the nearest construct that contains it. Written inside a function
    # or method, it describes that whole function or method. Written directly in a class body, it
    # describes the whole class, methods included. At the top level of a module it describes the
    # statement it sits inside or, since a comment describes what comes after it, the statement that
    # follows it, and the whole module when nothing follows. Where constructs nest, the innermost
    # one wins.

    # the module, parsed on the first lookup
    tree = self._parse()

    # guard: not Python — the whole file is the only owner there is
    if tree is None:
      return self._hash(self._source)
    return self._hash(self._serialise(self._find_owner_at(tree, line)))

  def _parse(self) -> ast.Module | None:
    """
    Parse the source on first use and return the module.

    Returns:
      The parsed module, or None when the source does not parse as Python.
    """
    # guard: already parsed — the cached result stands
    if self._parsed:
      return self._tree

    # first lookup: parse once and remember the outcome, a failure included
    self._parsed = True
    try:
      self._tree = ast.parse(self._source)
    except (SyntaxError, ValueError):
      self._tree = None
    return self._tree

  @staticmethod
  def _find_owner_at(tree: ast.Module, line: int) -> ast.AST:
    """
    Find the node that owns a block written at `line`.

    Args:
      tree: Parsed module of the file.
      line: 1-based line of the block's header.

    Returns:
      The innermost function or class whose span holds `line`, else the top-level statement that
      holds or follows it, else the module itself.
    """
    # the innermost scope owner wins: descend while a child def/class still spans the line
    owner: ast.AST | None = None
    nodes: list[ast.stmt] = list(tree.body)
    while nodes:
      hit = next(
        ( node for node in nodes
          if isinstance(node, _SCOPE_OWNERS) and node.lineno <= line <= (node.end_lineno or node.lineno) ),
        None,
      )
      # guard: no def or class at this level spans the line — the deepest one found so far stands
      if hit is None:
        break
      owner = hit
      nodes = [ child for child in ast.walk(hit) if child is not hit and isinstance(child, _SCOPE_OWNERS) ]

    # guard: a function or class holds the block — no module-level statement is consulted
    if owner is not None:
      return owner

    # at module level the containing statement owns the block, else the one right after it
    for stmt in tree.body:
      if stmt.lineno <= line <= (stmt.end_lineno or stmt.lineno) or stmt.lineno > line:
        return stmt
    return tree

  @classmethod
  def _serialise(cls, node: object) -> str:
    """
    Render a syntax-tree value in a canonical form stable across supported Python versions.

    Args:
      node: A syntax-tree node, a list of them, or a leaf value.

    Returns:
      The canonical text of `node`.
    """

    # Decision: an own walker, not `ast.dump` — its output changed in Python 3.13 (empty optional fields
    # omitted), so a daemon and a session on either side of that release would disagree on every digest.
    # A field a later grammar adds is rendered only when it departs from its plain-syntax value, for the
    # same reason (Python 3.15 writes `is_lazy` on every import).

    # guard: a list has no fields of its own — it renders element by element
    if isinstance(node, list):
      return "[" + ",".join(cls._serialise(item) for item in node) + "]"

    # guard: a leaf value has no fields — it renders by its repr
    if not isinstance(node, ast.AST):
      return repr(node)

    # each field in declaration order; empty optional fields are skipped, so a field a newer Python
    # adds with an empty default leaves the form unchanged
    parts: list[str] = []
    for name, raw in ast.iter_fields(node):
      docstring_body = name == _BODY_FIELD and isinstance(node, _DOCSTRING_OWNERS) and isinstance(raw, list)
      value = cls._strip_docstring(raw) if docstring_body else raw

      # guard: an empty optional field, or a newer field at its plain-syntax value, contributes nothing
      if value is None or value == [] or (name in _NEUTRAL_FIELDS and value == _NEUTRAL_FIELDS[name]):
        continue
      parts.append(f"{name}={cls._serialise(value)}")

    # the node type name heads its own fields
    # waiver: stdlib `ast` nodes carry no class-name accessor; the node type name is the canonical identifier
    return f"{type(node).__name__}({','.join(parts)})"

  @staticmethod
  def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """
    Drop a leading docstring statement from a body.

    Args:
      body: Statements of a module, class or function body.

    Returns:
      `body` without its first statement when that statement is a bare string literal.
    """
    # guard: the body does not open with a string literal — there is no docstring to drop
    if not (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
      return body
    return body[1:]

  @staticmethod
  def _hash(text: str) -> str:
    """
    Return the hex digest of a canonical form.

    Args:
      text: Text to digest.

    Returns:
      Hex sha256 digest of `text`.
    """
    return hashlib.sha256(text.encode(_ENCODING)).hexdigest()
