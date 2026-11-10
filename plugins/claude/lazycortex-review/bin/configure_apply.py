from __future__ import annotations

from typing import Literal, TypeAlias

import argparse
import copy
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from types import ModuleType


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import JobKey  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Whether an apply call changed the `review` section itself.
ApplyStatus: TypeAlias = Literal["written", "unchanged"]

# Exit codes of the CLI.
_EXIT_OK = 0
_EXIT_REFUSED = 1

# The CLI's program name, argument spellings and help text.
_PROG = "lazy-review configure-apply"
_ARG_REPO = "--repo"
_ARG_PAYLOAD = "--payload"
_ARG_PAYLOAD_FILE = "--payload-file"
_PAYLOAD_HELP = "the class document as JSON (default: read stdin)"
_PAYLOAD_FILE_HELP = "a file holding the class document as JSON (default: read stdin)"
_STDIN_LABEL = "stdin"

# Wire keys of the stdin document and of the refusal line.
_IN_CLASS = "class"
_IN_SECTION_EXPERTS = "section_experts"
_IN_EDIT_MARKER_STYLE = "edit_marker_style"
_OUT_STATUS = "status"
_OUT_REASON = "reason"
_REFUSED = "refused"

# The sibling module file of the review install bootstrap.
_INSTALL_FILE = "install.py"

# Refusal sentences of malformed stdin documents.
_NO_CLASS = "stdin must be a JSON object carrying a `class` object"
_BAD_SECTION_EXPERTS = "`section_experts` must map `<umbrella>/<section-id>` to writer objects"

# Settings keys this verb reads or writes.
_EDIT_MARKER_STYLE = "edit_marker_style"
_PROTOCOLS = "protocols"
_ROUTINES = "routines"
_WATCH_ROUTINE = "lazy-review.coordinator-watch"
_PATH_FILTER = "path_filter"
_REPO_ROOT_WATCH = "."

# The review install bootstrap, loaded under its own module key: a bare `install` name collides with other
# plugins' modules of the same name in one interpreter.
_INSTALL_KEY = "_lazycortex_review_install"


# ----------------------------------------------------------------------------------------
@dataclass
class ApplyResult:
  """
  Outcome of applying one review class to the repository's settings.

  Attributes:
    status: Whether this call changed the `review` section itself.
    class_token: The class token the call applied.
    watch_root: The watch root on record after the install bootstrap ran.
    path_filter: The coordinator watch's path mask on record after the install bootstrap ran.
    written_sections: The sections this call wrote itself.
  """

  # Whether this call changed the `review` section itself.
  status: ApplyStatus
  # The class token the call applied.
  class_token: str
  # The watch root on record after the install bootstrap ran.
  watch_root: str
  # The coordinator watch's path mask on record after the install bootstrap ran.
  path_filter: str | None
  # The sections this call wrote itself.
  written_sections: list[str] = field(default_factory = list)


def _load_install_module() -> ModuleType:
  """
  Load the sibling review install module under its own module key, once per interpreter.

  Returns:
    The loaded install module.

  Raises:
    RuntimeError: When the sibling install module file cannot be loaded.
  """
  # a module already loaded in this interpreter is returned as it stands
  if _INSTALL_KEY in sys.modules:
    return sys.modules[_INSTALL_KEY]

  # the loader spec for the sibling file, under the module key no other plugin's `install` shares
  spec = importlib.util.spec_from_file_location(_INSTALL_KEY, _BIN / _INSTALL_FILE)

  # guard: the sibling module ships with this file; a missing one is a broken install
  if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {_BIN / _INSTALL_FILE}")

  # registered before execution, so the module's own imports resolve against one copy
  module = importlib.util.module_from_spec(spec)
  sys.modules[_INSTALL_KEY] = module
  spec.loader.exec_module(module)
  return module


def _merge_class(classes: list, class_entry: dict, section_experts: dict[str, dict]) -> None:
  """
  Put a class entry, with its section writers, into the class list in place.

  An entry with the same class token is replaced where it stands and keeps a recorded `protocols` list
  that the new entry lacks; an entry with a new token is appended.

  Args:
    classes: The `review.classes` list, mutated in place.
    class_entry: The class entry to apply; the caller's object is left unchanged.
    section_experts: Section writers keyed `<umbrella>/<section-id>`; each lands in the entry's experts
      under its umbrella.
  """

  # Domain(review.config):
  # # Merging a review class into the configured class list
  # A review class is identified by its class token, and the configuration holds at most one entry per token.
  # Applying a class whose token is already configured replaces that entry where it stands, so the order of
  # the classes never shifts. The replacement keeps the protocol list recorded on the old entry when the new
  # one does not state its own, so reapplying a class never silently drops protocols chosen earlier.
  # A class with a new token is appended to the end of the list.
  # Section writers are addressed as an umbrella and a section id; each is filed in the class's experts under
  # its umbrella, so a class carries all writers of one umbrella together.

  # the caller's entry is copied, so the merge never mutates its input
  entry = copy.deepcopy(class_entry)

  # each section writer lands in the class's own umbrella block
  for ref, writer in section_experts.items():
    umbrella, _, section_id = ref.partition("/")
    entry.setdefault(JobKey.EXPERTS, {}).setdefault(umbrella, {})[section_id] = copy.deepcopy(writer)

  # an entry with the same token is replaced in place and keeps a recorded protocol list the input omits
  for idx, cls in enumerate(classes):
    if isinstance(cls, dict) and cls.get(JobKey.CLASS) == entry.get(JobKey.CLASS):
      if _PROTOCOLS not in entry and _PROTOCOLS in cls:
        entry[_PROTOCOLS] = cls[_PROTOCOLS]
      classes[idx] = entry
      return

  # a new token joins the end of the list
  classes.append(entry)


def apply_class(repo: Path,
                class_entry: dict,
                *,
                edit_marker_style: str | None,
                section_experts: dict[str, dict] | None = None) -> ApplyResult:
  """
  Apply one review class to the repository's settings and widen the coordinator watch to cover it.

  Guarantees:
    - The `review` section is written only when this call changed it.
    - The result reports the watch root and path mask as they stand on disk after the install bootstrap.

  Notes:
    - Runs the install bootstrap, which widens `review.watch_root` and re-derives the watch's path mask.

  Args:
    repo: Repository root whose settings file is updated.
    class_entry: The review class entry to add or replace.
    edit_marker_style: Edit marker style to record; ignored when one is already recorded, and `None` skips it.
    section_experts: Section writers keyed `<umbrella>/<section-id>`, merged into the class entry's experts.

  Returns:
    The apply outcome with the class token, the watch scope on disk, and the sections written.

  Raises:
    SettingsRefusedError: When core cannot read or write the settings file (the install module's exception).
    RuntimeError: When the sibling install module cannot be loaded, the core CLI cannot be resolved, or the
      install bootstrap's routine reconcile refuses.
  """

  # Contract:
  # This call writes the `review` section only when it changed it;
  # a call that changes nothing reports no written section and the status `unchanged`.

  # Contract:
  # The result reports the watch root and path mask as they stand on disk after the install bootstrap,
  # never the values from before it.

  repo = repo.resolve()
  install = _load_install_module()
  cli = install.resolve_core_cli()

  # the review section as the file carries it; the wizard runs only after the install seeded it
  recorded = install.read_section(cli, repo, JobKey.REVIEW)
  review = copy.deepcopy(recorded) if isinstance(recorded, dict) else {}

  # the recorded class list the new entry merges into
  classes = review.get(JobKey.CLASSES)

  # guard: a missing or malformed class list starts over as an empty one
  if not isinstance(classes, list):
    classes = []
    review[JobKey.CLASSES] = classes

  # the class and its section writers land in the list
  _merge_class(classes, class_entry, section_experts or {})

  # the marker style is written only when none is on record
  if edit_marker_style is not None and not review.get(_EDIT_MARKER_STYLE):
    review[_EDIT_MARKER_STYLE] = edit_marker_style

  # the section is written back only when this call changed it
  written: list[str] = []
  if review != recorded:
    install.write_section(cli, repo, JobKey.REVIEW, value = review)
    written.append(JobKey.REVIEW)

  # the install bootstrap widens the watch root and re-derives the watch's path mask from it
  install.install(repo)

  # the result reports the scope as the bootstrap left it on disk
  after = install.read_section(cli, repo, JobKey.REVIEW) or {}
  watch = (install.read_section(cli, repo, _ROUTINES) or {}).get(_WATCH_ROUTINE)
  return ApplyResult(
      status = "written" if written else "unchanged",
      class_token = str(class_entry.get(JobKey.CLASS)),
      watch_root = str(after.get(JobKey.WATCH_ROOT) or _REPO_ROOT_WATCH),
      path_filter = watch.get(_PATH_FILTER) if isinstance(watch, dict) else None,
      written_sections = written,
  )


def _refuse(reason: str) -> int:
  """
  Print the JSON refusal line for `reason`.

  Args:
    reason: Text explaining the refusal.

  Returns:
    The refusal exit code, 1.
  """
  print(json.dumps({ _OUT_STATUS: _REFUSED, _OUT_REASON: reason }))
  return _EXIT_REFUSED


def main(argv: list[str]) -> int:
  """
  Apply the review class document given as JSON and print the JSON result.

  The document comes from `--payload`, else from the file `--payload-file` names, else from standard input. A
  malformed or unreadable document, a refused settings file, an unresolvable core CLI or a refused routine
  reconcile prints `{"status": "refused", "reason": ...}` instead of the result.

  Args:
    argv: Command-line arguments, excluding the program name: `--repo` and optionally one of `--payload` or
      `--payload-file`.

  Returns:
    Exit code 0 on success and 1 when refused. An argument error, including `--payload` given together with
    `--payload-file`, exits 2 through argparse.

  Raises:
    RuntimeError: When the sibling install module cannot be loaded.
  """
  # the verb's arguments: the repo root and at most one of the inline class document or the file holding it
  parser = argparse.ArgumentParser(prog = _PROG)
  parser.add_argument(_ARG_REPO, default = ".")
  source = parser.add_mutually_exclusive_group()
  source.add_argument(_ARG_PAYLOAD, default = None, help = _PAYLOAD_HELP)
  source.add_argument(_ARG_PAYLOAD_FILE, default = None, help = _PAYLOAD_FILE_HELP)
  args = parser.parse_args(argv)

  # the wizard's collected class arrives as one JSON document: inline, in a file, or on stdin
  if args.payload is not None:
    label, document = _ARG_PAYLOAD, args.payload
  elif args.payload_file is not None:
    label = _ARG_PAYLOAD_FILE
    try:
      document = Path(args.payload_file).read_text(encoding = "utf-8")
    except (OSError, UnicodeDecodeError) as error:
      return _refuse(f"{label} read: {error}")
  else:
    label, document = _STDIN_LABEL, sys.stdin.read()

  # the document is parsed once, whichever of the three routes brought it
  try:
    payload = json.loads(document or "null")
  except json.JSONDecodeError as error:
    return _refuse(f"{label} parse: {error}")

  # guard: the document must carry a class object with its token
  if not isinstance(payload, dict) or not isinstance(payload.get(_IN_CLASS), dict):
    return _refuse(_NO_CLASS)

  # the section writers are optional; an absent map is an empty one
  section_experts = payload.get(_IN_SECTION_EXPERTS) or {}

  # guard: section writers are keyed `<umbrella>/<section-id>`
  if not isinstance(section_experts, dict) or not all(
      isinstance(writer, dict) for writer in section_experts.values()
  ):
    return _refuse(_BAD_SECTION_EXPERTS)

  # a settings file core cannot read or write ends the run as a refusal naming the file; a core CLI that
  # cannot be resolved or a refused routine reconcile ends it as a refusal carrying the failure text
  try:
    result = apply_class(
        Path(args.repo), payload[_IN_CLASS],
        edit_marker_style = payload.get(_IN_EDIT_MARKER_STYLE), section_experts = section_experts,
    )
  except _load_install_module().SettingsRefusedError as refusal:
    return _refuse(refusal.reason)
  except RuntimeError as failure:
    return _refuse(str(failure))
  print(json.dumps(asdict(result)))
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
