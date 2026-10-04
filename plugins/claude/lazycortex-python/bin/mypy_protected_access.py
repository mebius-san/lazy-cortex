from __future__ import annotations

import hashlib
from functools import partial
from pathlib import Path, PurePath

from mypy.checker import TypeChecker
from mypy.errorcodes import ErrorCode
from mypy.nodes import TypeInfo
from mypy.plugin import Plugin
from mypy.types import CallableType, Instance, TypeType, get_proper_type

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable

  from mypy.nodes import Context
  from mypy.plugin import AttributeContext, CheckerPluginInterface, MethodContext, ReportConfigContext
  from mypy.types import ProperType, Type


PROTECTED_ACCESS = ErrorCode("protected-access", "Check access to protected class members", "General")

# the documented public API of `collections.namedtuple` and `typing.NamedTuple`, underscored to avoid field clashes
_NAMEDTUPLE_API = frozenset({ "_asdict", "_fields", "_field_defaults", "_make", "_replace" })

# the directory name whose presence on a file's path inside the project marks the file as test code
_TESTS_DIR = "tests"


# ----------------------------------------------------------------------------------------
class ProtectedAccessPlugin(Plugin):
  """
  Mypy plugin that reports access to a protected class member from outside the class hierarchy that declares it.

  A member is protected when its name starts with an underscore and is not public by convention. Public by
  convention are dunder names (two underscores on each side), sunder names (one underscore on each side, as the
  enum value and missing-value hooks use), and, on a namedtuple class only, the five documented namedtuple API
  names (as-dict, fields, field defaults, make, replace). Reading, writing, and calling a protected member is
  allowed only from code lexically inside a class whose MRO contains the declaring class; anything else,
  module-level code included, is reported under the `protected-access` error code.

  Test code is exempt: nothing is reported in a file with a directory named exactly `tests` on its path inside the
  project, at any depth. A file named `tests.py` or a directory such as `tests_util` is checked as usual.

  Guarantees:
    - Each protected access is reported at most once.
    - The type mypy inferred for a checked access is never changed.

  Notes:
    - Not reported: a receiver typed `Any`, access through `getattr` with a string name, and a bound method
      referenced without a call.
    - Not reported either: a method call or a class-object access whose receiver is typed as a `TypeVar`, as
      `Self`, or as a tuple (a `NamedTuple` class or instance included).
    - The project is the current working directory: a file under it is judged by its path inside it, any other
      file by its path as given.
    - Depends on mypy internals outside the plugin API; verified against mypy 2.1.0.
  """

  # Contract:
  # Each protected access is reported at most once.

  # Contract:
  # The plugin never changes the type mypy inferred for an access it checks; checking only reports.

  def get_attribute_hook(self, fullname: str) -> Callable[[AttributeContext], Type] | None:
    """
    Return the protected-access check for an instance attribute.

    Args:
      fullname: Fully qualified attribute name.

    Returns:
      The check for a protected member, or `None` for any other name.
    """
    declaring, name = fullname.rsplit(".", 1)
    # guard: only protected names get a check
    if not _is_protected(name):
      return None
    return partial(self._check_attribute, declaring, name)

  def get_class_attribute_hook(self, fullname: str) -> Callable[[AttributeContext], Type] | None:
    """
    Return the protected-access check for an attribute reached through a class object.

    Args:
      fullname: Fully qualified attribute name.

    Returns:
      The check for a protected member, or `None` for any other name.
    """
    name = fullname.rsplit(".", 1)[-1]
    # guard: only protected names get a check
    if not _is_protected(name):
      return None
    return partial(self._check_class_attribute, name)

  def get_method_hook(self, fullname: str) -> Callable[[MethodContext], Type] | None:
    """
    Return the protected-access check for a method call.

    Args:
      fullname: Fully qualified method name.

    Returns:
      The check for a protected method, or `None` for any other name.
    """
    name = fullname.rsplit(".", 1)[-1]
    # guard: only protected names get a check
    if not _is_protected(name):
      return None
    return partial(self._check_method, name)

  # waiver: ctx is fixed by mypy's Plugin.report_config_data signature
  def report_config_data(self, ctx: ReportConfigContext) -> str:  # pylint: disable=unused-argument
    """
    Return the SHA-256 hex digest of this plugin file, so any edit of the plugin invalidates the mypy cache.

    Args:
      ctx: Report context, unused.

    Returns:
      The SHA-256 hex digest of this plugin file's bytes.
    """
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()

  def _check_attribute(self, declaring: str, name: str, ctx: AttributeContext) -> Type:
    """
    Report an instance attribute access from outside the declaring hierarchy.

    Args:
      declaring: Full name of the declaring class.
      name: Attribute name.
      ctx: Attribute hook context.

    Returns:
      The attribute type mypy inferred, unchanged.
    """
    # the declaring class arrives as a full name; its symbol tells whether it is a namedtuple
    symbol = self.lookup_fully_qualified(declaring)

    # guard: the namedtuple API of a namedtuple is public; the same names on any other class are not
    if symbol is not None and isinstance(symbol.node, TypeInfo) and _is_namedtuple_api(symbol.node, name):
      return ctx.default_attr_type

    # judge the access, then hand mypy its own inferred type back
    self._report(declaring, name, ctx.api, ctx.context)
    return ctx.default_attr_type

  def _check_class_attribute(self, name: str, ctx: AttributeContext) -> Type:
    """
    Report an access through a class object from outside the declaring hierarchy.

    Args:
      name: Attribute name.
      ctx: Attribute hook context.

    Returns:
      The attribute type mypy inferred, unchanged.
    """
    # mypy names this hook after the receiver class, so the declaring class comes from the receiver's MRO
    declaring = _find_declaring_info(ctx.type, name)

    # guard: an unresolvable receiver or declaring class stays silent, and so does a namedtuple's own API
    if declaring is None or _is_namedtuple_api(declaring, name):
      return ctx.default_attr_type

    # judge the access, then hand mypy its own inferred type back
    self._report(declaring.fullname, name, ctx.api, ctx.context)
    return ctx.default_attr_type

  def _check_method(self, name: str, ctx: MethodContext) -> Type:
    """
    Report a method call from outside the declaring hierarchy.

    Args:
      name: Method name.
      ctx: Method hook context.

    Returns:
      The return type mypy inferred, unchanged.
    """
    declaring = _find_declaring_info(ctx.type, name)

    # guard: an unresolvable receiver or declaring class stays silent, and so does a namedtuple's own API
    if declaring is None or _is_namedtuple_api(declaring, name):
      return ctx.default_return_type

    # judge the call, then hand mypy its own inferred return type back
    self._report(declaring.fullname, name, ctx.api, ctx.context)
    return ctx.default_return_type

  def _report(self, declaring: str, name: str, api: CheckerPluginInterface, context: Context) -> None:
    """
    Fail the access unless it sits in test code or the enclosing class has the declaring class in its MRO.

    Args:
      declaring: Full name of the declaring class.
      name: Member name.
      api: Checker API of the hook context.
      context: Node the error is reported on.

    Raises:
      TypeError: The hook API is not mypy's type checker, so the enclosing class cannot be read.
    """

    # Domain(pytool.code-discipline):
    # # Protected member access
    # A member whose name starts with an underscore, one or more of them, is protected: it belongs to the class that
    # declares it and to that class's descendants. Reading, writing or calling it is allowed only from code inside a
    # class whose hierarchy contains the declaring class. Code outside any class, module-level code included, has no
    # such right and is checked the same way as code in an unrelated class.
    # Names that only look protected are public: special names with two underscores on each side, names with one
    # underscore on each side (as the enum hooks use), and, on a namedtuple only, its five documented API names
    # (as-dict, fields, field defaults, make, replace), which carry the underscore only so that they cannot clash with
    # field names. The same names on any other class stay protected.

    # guard: the enclosing class is only recorded in the type checker's scope; never skip the check silently
    if not isinstance(api, TypeChecker):
      raise TypeError("protected-access plugin is built for mypy 2.1.0 and found no TypeChecker.scope")

    # guard: test code may touch protected members
    if _is_test_file(api.path):
      return

    # the innermost class enclosing the access, or none for module-level code
    accessing = next((item for item in reversed(api.scope.stack) if isinstance(item, TypeInfo)), None)

    # guard: access from inside the declaring hierarchy is allowed
    if accessing is not None and declaring in { base.fullname for base in accessing.mro }:
      return

    # anything else is a protected access from outside
    api.fail(
      f'Access to protected member "{name}" of "{declaring}" from outside its class hierarchy',
      context, code = PROTECTED_ACCESS,
    )


def _is_protected(name: str) -> bool:
  """
  Tell whether a member name is protected.

  Args:
    name: Member name.

  Returns:
    `True` for a name starting with `_` that is neither a dunder nor a sunder.
  """
  # guard: only a leading underscore can make a name protected
  if not name.startswith("_"):
    return False

  # a dunder (`__x__`) and a sunder (`_x_`) share the trailing underscore that private names lack
  dunder = name.startswith("__") and name.endswith("__")
  sunder = len(name) > 2 and name.endswith("_") and name[1] != "_" and name[-2] != "_"
  return not (dunder or sunder)


def _is_namedtuple_api(declaring: TypeInfo, name: str) -> bool:
  """
  Tell whether a member is part of the documented API of a namedtuple class.

  Args:
    declaring: Class that declares the member.
    name: Member name.

  Returns:
    `True` when the declaring class is a namedtuple and the name is one of its documented API names.
  """
  return declaring.is_named_tuple and name in _NAMEDTUPLE_API


def _is_test_file(path: str) -> bool:
  """
  Tell whether a checked file is test code.

  Args:
    path: Path of the checked file, as mypy received it.

  Returns:
    `True` when a directory of the file's path, taken relative to the current working directory when the file lies
    under it, is named exactly `tests`.
  """

  # Domain(pytool.code-discipline):
  # # Test code is exempt from protected access
  # Tests reach into the internals they verify, so protected access is not reported in test code. A file is test
  # code when a directory named exactly `tests` lies on its path inside the project, at any depth. Directories above
  # the project root do not count. A file named `tests.py` or a directory such as `tests_util` is ordinary code.

  # mypy runs from the project root, so only the directories inside the project decide; an IDE passes absolute paths
  file = Path(path).resolve()
  cwd = Path.cwd().resolve()
  dirs = file.relative_to(cwd).parent.parts if file.is_relative_to(cwd) else PurePath(path).parent.parts
  return _TESTS_DIR in dirs


def _find_declaring_info(receiver: ProperType, name: str) -> TypeInfo | None:
  """
  Resolve the class that declares a member reached through a receiver.

  Args:
    receiver: Static type of the receiver.
    name: Member name.

  Returns:
    The first class in the receiver's MRO that declares the member, or `None` when the receiver names no single
    class or no class in its MRO declares the member.
  """
  info = _find_receiver_info(receiver)
  return info.get_containing_type_info(name) if info is not None else None


def _find_receiver_info(receiver: ProperType) -> TypeInfo | None:
  """
  Resolve the class a method is looked up on from the receiver type.

  Args:
    receiver: Static type of the call receiver.

  Returns:
    The receiver's class, or `None` when the type names no single class.
  """
  # an instance names its class directly
  if isinstance(receiver, Instance):
    return receiver.type

  # a `type[...]` receiver stands for the class of its item, so the member is judged against that instance class
  if isinstance(receiver, TypeType):
    return _find_receiver_info(get_proper_type(receiver.item))

  # a class object is typed as a callable returning the instance; unwrap it to that instance class for the same reason
  if isinstance(receiver, CallableType) and receiver.is_type_obj():
    return _find_receiver_info(get_proper_type(receiver.ret_type))

  # any other type names no single class
  return None


def plugin(_version: str) -> type[Plugin]:
  """
  Return the plugin class for mypy's plugin loader.

  Args:
    _version: Running mypy version, unused.

  Returns:
    The protected-access plugin class.
  """
  return ProtectedAccessPlugin
