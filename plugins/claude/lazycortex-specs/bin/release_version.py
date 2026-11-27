"""
Logic behind the `lazycortex-specs release-version <note> (--set <version> | --bump <part> --product <key>)` verb.

The verb writes a release's SemVer version into its status note together with the version's mirror tag, reads
the previous version from the product's manifest or from its published releases, and moves a manifest's version
field when a release is published.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import Gate, HistoryEvent, ReleaseConfigKey, ReleaseKey  # noqa: E402


_ENCODING = "utf-8"
_TAGS_KEY = "tags"

# The bump parts in the order the version's numbers carry them
PARTS = ( "major", "minor", "patch" )
# The version a product's first release carries, whatever bump was asked for
_FIRST_VERSION = "0.1.0"

# The bot identity the version verb commits under; every release verb derives its own the same way
VERSION_NAME = "lazy-spec.release-version"
_BOT_DOMAIN = "@bot.invalid"
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# The manifest formats this verb reads and writes, by file suffix
_JSON_SUFFIX = ".json"
_TOML_SUFFIX = ".toml"
_VERSION_FIELD = "version"
# The TOML tables a version is looked up in, the first that carries one wins
_TOML_TABLES = ( ( "project", ), ( "tool", "poetry" ) )
_TOML_HEADER_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
# One JSON string literal, quotes and escapes included
_JSON_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
_TOML_VERSION_RE = re.compile(r'^(\s*version\s*=\s*")[^"]*(".*)$')

# Result keys
_STATUS = "status"
_REASON = "reason"
_VERSION = "version"
_TAG = "tag"
_PREVIOUS = "previous"
_CHANGED = "changed"
_STATUS_SET = "set"
_STATUS_REFUSED = "refused"
_STATUS_NOOP = "noop"
# The `spec_version_pinned` value of a version an operator set outright
_TRUE = "true"
# The noop reason of a bump over a version an operator set outright
_MSG_PINNED = "the release's version is pinned by an operator-set version; a bump leaves it standing"


def parse(version: str) -> tuple[int, int, int]:
  """
  Split a bare SemVer version into its three numbers.

  Args:
    version: The version text, three dot-separated numbers and nothing else.

  Returns:
    The major, minor and patch numbers.

  Raises:
    ValueError: If the text is not a bare SemVer version.
  """
  # guard: a prefix, a missing number or a non-digit is no version this verb handles
  if (match := _SEMVER_RE.match(version.strip())) is None:
    raise ValueError(f"not a bare SemVer version: {version!r}")
  major, minor, patch = ( int(number) for number in match.groups() )
  return major, minor, patch


def bump(previous: str | None, part: str) -> str:
  """
  Raise one number of a version, zeroing the lower ones.

  Args:
    previous: The version to bump, or None when the product has no previous version at all.
    part: `major`, `minor` or `patch`.

  Returns:
    The bumped version, or the first version when there was no previous one.

  Raises:
    ValueError: If `part` is not one of the three, or `previous` is not a bare SemVer version.
  """

  # Domain(spec.lifecycle):
  # # How a release's version moves
  # A release carries a bare three-number version. The product coordinator judges which of the three
  # numbers the whole delta moves — a delta of fixes the last, a delta that adds behaviour the middle,
  # a delta that breaks what consumers rely on the first — and every number below the moved one
  # returns to zero. The previous version is read from the product's manifest when the product names
  # one, otherwise it is the highest version among the product's published releases, those in the
  # archive included, so archiving old releases never resets the version line. A product with
  # neither starts at zero-point-one-point-zero whatever movement was asked for. A rebuild only
  # ever moves the version upward, and a published version is frozen.

  # guard: an unknown part is a caller typo
  if part not in PARTS:
    raise ValueError(f"unknown version part: {part!r}")

  # a product's first release starts the count whatever bump was asked for
  if previous is None:
    return _FIRST_VERSION

  # the asked number goes up by one, every number below it returns to zero
  numbers = list(parse(previous))
  index = PARTS.index(part)
  numbers[index] += 1
  for lower in range(index + 1, len(numbers)):
    numbers[lower] = 0
  return ".".join(str(number) for number in numbers)


def render_version_tag(version: str) -> str:
  """
  Render a version as its Obsidian mirror tag.

  Args:
    version: A bare SemVer version.

  Returns:
    The tag under the release prefix, with the dots replaced by hyphens.
  """
  return ReleaseKey.TAG_PREFIX + version.replace(".", "-")


def read_manifest_version(path: Path) -> str:
  """
  Read the version field of a JSON or TOML manifest.

  Args:
    path: The manifest file.

  Returns:
    The version text as the manifest carries it.

  Raises:
    ValueError: If the format is unknown or the manifest carries no version field.
  """
  text = path.read_text(encoding = _ENCODING)

  # a JSON manifest carries the field at its top level
  if path.suffix == _JSON_SUFFIX:
    value = json.loads(text).get(_VERSION_FIELD)
    if isinstance(value, str) and value:
      return value
    raise ValueError(f"no version field in {path}")

  # a TOML manifest carries it in the first known table that has one
  if path.suffix == _TOML_SUFFIX:
    data = tomllib.loads(text)
    for table in _TOML_TABLES:
      node: object = data
      for key in table:
        node = node.get(key, {}) if isinstance(node, dict) else {}
      value = node.get(_VERSION_FIELD) if isinstance(node, dict) else None
      if isinstance(value, str) and value:
        return value
    raise ValueError(f"no version field in {path}")
  raise ValueError(f"unknown manifest format: {path}")


def _locate_json_version(text: str) -> tuple[int, int] | None:
  """
  Locate the top-level `version` string value in a JSON manifest's text.

  Args:
    text: The manifest's text, a JSON object.

  Returns:
    The start and end offsets of the value's string literal, quotes included; None when the top level carries no
    `version` key, carries it more than once, or its value is not a string.
  """
  spans: list[tuple[int, int] | None] = []
  stack: list[str] = []
  expect_key = False
  index = 0
  while index < len(text):
    char = text[index]

    # a string is a key or a value; only a top-level key named `version` is followed to its value
    if char == '"':
      # guard: a quote that opens no string literal leaves the text unreadable, so nothing is located
      if (string_match := _JSON_STRING_RE.match(text, index)) is None:
        return None
      end = string_match.end()
      value = json.loads(text[index:end])
      if expect_key and len(stack) == 1 and value == _VERSION_FIELD:
        start = text.index(":", end) + 1
        while text[start].isspace():
          start += 1
        literal = _JSON_STRING_RE.match(text, start)
        spans.append(( start, literal.end() ) if literal is not None else None)
      expect_key = False
      index = end
      continue

    # the brackets track the depth; an object opens on its first key, and a comma inside one opens the next
    if char in "{[":
      stack.append(char)
      expect_key = char == "{"
    elif char in "}]":
      stack.pop()
      expect_key = False
    elif char == ",":
      expect_key = bool(stack) and stack[-1] == "{"
    index += 1

  # guard: the value is located only when exactly one top-level key names it and its value is a string
  if len(spans) != 1:
    return None
  return spans[0]


def render_manifest_version(path: Path, version: str) -> str:
  """
  Render a JSON or TOML manifest's text with its version field replaced, leaving every other byte as it was.

  Guarantees:
    - A JSON manifest keeps every byte of its text except the single top-level `version` string value.
    - A manifest whose top-level `version` is missing, repeated or not a string, that is not valid JSON, or whose
      suffix names no known format is refused with `ValueError`; a `version` nested deeper does not count.

  Args:
    path: The manifest file.
    version: The version to write.

  Returns:
    The manifest's new text.

  Raises:
    ValueError: If the format is unknown, the text is not valid for its format, or the version field cannot be
      located unambiguously.
  """

  # Contract:
  # A JSON manifest keeps every byte of its text except the single top-level `version` string value. A manifest
  # whose top-level `version` is missing, repeated or not a string (a `version` nested deeper does not count),
  # that is not valid JSON, or whose suffix names no known format is refused with `ValueError`, never guessed at;
  # a caller can thus tell before it deploys anything whether the manifest can take the version.

  text = path.read_text(encoding = _ENCODING)

  # a JSON manifest keeps every byte but the one top-level version string; invalid JSON is refused first
  if path.suffix == _JSON_SUFFIX:
    try:
      json.loads(text)
    except json.JSONDecodeError as error:
      raise ValueError(f"manifest is not valid JSON: {path}: {error}") from error
    span = _locate_json_version(text)

    # guard: a missing, repeated or non-string top-level version cannot be replaced in place
    if span is None:
      raise ValueError(f"no single top-level string version field in {path}")
    return text[:span[0]] + json.dumps(version, ensure_ascii = False) + text[span[1]:]

  # guard: only JSON and TOML are known
  if path.suffix != _TOML_SUFFIX:
    raise ValueError(f"unknown manifest format: {path}")

  # a TOML manifest keeps every byte but the one version line of the table the version lives in
  lines = text.split("\n")
  for table in _TOML_TABLES:
    header = ".".join(table)
    inside = False
    for index, line in enumerate(lines):
      if (match := _TOML_HEADER_RE.match(line)) is not None:
        inside = match.group(1).strip() == header
        continue
      if inside and (match := _TOML_VERSION_RE.match(line)) is not None:
        lines[index] = f"{match.group(1)}{version}{match.group(2)}"
        return "\n".join(lines)
  raise ValueError(f"no version field in {path}")


def write_manifest_version(path: Path, version: str) -> None:
  """
  Replace the version field of a JSON or TOML manifest, leaving every other byte as it was.

  Guarantees:
    - A refused write, one that raises `ValueError`, leaves the manifest file with its bytes from before the call.

  Args:
    path: The manifest file.
    version: The version to write.

  Raises:
    ValueError: If the format is unknown, the text is not valid for its format, or the version field cannot be
      located unambiguously; the file then keeps its bytes.
  """

  # Contract:
  # A refused write, one that raises `ValueError`, leaves the manifest file with its bytes from before the call.

  # the new text is rendered whole before anything is written, so a refusal leaves the file as it was
  spec_paths.write_text_atomic(path, render_manifest_version(path, version))


def _read_published_versions(releases_dir: Path) -> list[str]:
  """
  Collect the versions of the published releases under a releases folder and its archive.

  Args:
    releases_dir: The product's `releases/` folder.

  Returns:
    The `spec_version` of every release note, in the folder or its archive, whose `spec_released` is true,
    unordered.
  """
  # every release folder's own note, published ones only, in the releases folder and its archive
  versions: list[str] = []
  for folder in ( releases_dir, releases_dir / ReleaseKey.ARCHIVE ):
    # guard: a product without releases, or without an archive yet, has nothing published there
    if not folder.is_dir():
      continue

    # each numbered folder's own note is read for its version and its published gate
    for entry in sorted(os.listdir(folder)):
      note = folder / entry / f"{entry}.md"

      # guard: only a numbered folder with its own note is a release
      if not (entry.isascii() and entry.isdigit()) or not note.is_file():
        continue

      # a published release contributes its version
      fm_values, _fm_end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))
      version = fm_values.get(ReleaseKey.VERSION, "").strip()
      if version and flip_gate.is_true(fm_values, Gate.RELEASED):
        versions.append(version)
  return versions


def read_previous_version(repo: Path, record: dict, releases_dir: Path) -> str | None:
  """
  Find the version a product's next release builds on.

  Args:
    repo: Repository root.
    record: The product's record from `lazy.settings.json`.
    releases_dir: The product's `releases/` folder.

  Returns:
    The manifest's version when the record's `release.manifest` names one, otherwise the highest version among
    the published releases, archived ones included, otherwise None.
  """
  # the manifest is the point of reference whenever the product names one
  release_section = record.get(ReleaseConfigKey.SECTION) or {}
  manifest = release_section.get(ReleaseConfigKey.MANIFEST, "") if isinstance(release_section, dict) else ""
  if manifest:
    return read_manifest_version(repo / manifest)

  # otherwise the highest published release, if any
  versions = _read_published_versions(releases_dir)
  return max(versions, key = parse) if versions else None


def find_bump_noop_reason(note: Path, version: str) -> str | None:
  """
  Say why a bumped version must not be written over the version a release note already carries.

  Args:
    note: The release's status note.
    version: The bumped version about to be written.

  Returns:
    The reason when the note's current `spec_version` is a bare SemVer version at or above `version`; None when the
    bump moves the version up, or the note carries no readable version.

  Raises:
    ValueError: If `version` is not a bare SemVer version.
    OSError: If the note cannot be read.
  """

  # Domain(spec.lifecycle):
  # # A bump never moves a release's version down
  # A bump over the previous version only ever raises a release's version. When the release already carries a
  # version as high as the bumped one or higher — an operator who set a higher version by hand, or an earlier bump —
  # the bump writes nothing and the version the release carries stands.

  # the version the note carries now, if any
  fm_values, _fm_end = spec_frontmatter.parse(note.read_text(encoding = _ENCODING))
  current = fm_values.get(ReleaseKey.VERSION, "").strip().strip("\"'")

  # guard: a note without a readable version has nothing a bump could lower
  if not _SEMVER_RE.match(current):
    return None

  # a bump that does not move the version up writes nothing
  if parse(version) <= parse(current):
    return f"bumped version {version} is not above the release's current {current}"
  return None


def commit_paths(repo: Path, paths: list[Path], *, author: str, subject: str) -> bool:
  """
  Commit exactly `paths` under a release verb's bot identity, the icon repaint folded in.

  Commits the verb's own writes together with the icon repaint they trigger. Makes no commit when `repo` is not a
  git repository, a path lies outside `repo`, or nothing changed.

  Args:
    repo: The repository root.
    paths: The files the verb wrote.
    author: The verb's bot name; its email is derived from it.
    subject: The commit subject.

  Returns:
    True when a commit was made.

  Raises:
    subprocess.CalledProcessError: If the commit fails.
  """
  # the shared pathspec commit, under the verb's bot identity, its icon repaint folded in
  return flip_gate.commit_paths(repo, paths, subject = subject, author_name = author,
                                author_email = f"{author}{_BOT_DOMAIN}")


def set_release_version(note: Path, version: str, *, pin: bool = False) -> dict:
  """
  Write a version and its mirror tag onto a release note.

  Args:
    note: The release's status note.
    version: The bare SemVer version to write.
    pin: Whether the version is pinned too, so a later bump leaves it standing.

  Returns:
    `{"status": "set", "version", "tag", "changed"}` on success, `changed` false when the note already carried
    exactly this version, tag and pin; `{"status": "refused", "reason"}` when the release is published.

  Raises:
    ValueError: If `version` is not a bare SemVer version.
    OSError: If the note cannot be read or written.
  """
  parse(version)
  text = note.read_text(encoding = _ENCODING)
  fm_values, _fm_end = spec_frontmatter.parse(text)

  # guard: a published release's version is frozen
  if flip_gate.is_true(fm_values, Gate.RELEASED):
    return { _STATUS: _STATUS_REFUSED, _REASON: "release is published; its version is frozen" }

  # the version's tag replaces any older release tag, every other tag stays
  tag = render_version_tag(version)
  tags = spec_frontmatter.read_list(text, _TAGS_KEY)
  new_tags = [ item for item in tags if not item.startswith(ReleaseKey.TAG_PREFIX) ] + [ tag ]
  changed = (
      fm_values.get(ReleaseKey.VERSION, "").strip() != version or tags != new_tags
      or (pin and not flip_gate.is_true(fm_values, ReleaseKey.VERSION_PINNED))
  )
  if changed:
    updated = spec_frontmatter.set_scalar(text, ReleaseKey.VERSION, version)
    if pin:
      updated = spec_frontmatter.set_scalar(updated, ReleaseKey.VERSION_PINNED, _TRUE)
    spec_paths.write_text_atomic(note, spec_frontmatter.write_list(updated, _TAGS_KEY, new_tags))
  return { _STATUS: _STATUS_SET, _VERSION: version, _TAG: tag, _CHANGED: changed }


def main(argv: list[str]) -> int:
  """
  Write a release's version from an explicit value or from a bump over the product's previous version.

  The run works in the nearest directory, within the note's checkout, that holds `.claude/lazy.settings.json`,
  searched upward from the note, else that checkout's root; the `--bump` form reads the product record from it and
  both forms commit into it.

  Guarantees:
    - A `--bump` never lowers or repeats a version: a bumped value not above the note's current `spec_version`
      writes and commits nothing, prints `{"status": "noop", ...}` and exits 0.
    - A `--set` pins the version: it writes `spec_version_pinned: true` in the version's own commit, and a later
      `--bump` on the pinned note writes and commits nothing, prints `{"status": "noop", ...}` and exits 0.

  Notes:
    - Prints a JSON summary on stdout with the keys `version`, `tag`, `previous` and `changed`, or the refusal
      object with `status` and `reason`.
    - A `--bump` noop prints `{"status": "noop", "reason", "version", "previous"}`, `version` being the bumped
      value it declined.
    - A `--set` that changed the note's version also records a line naming the operator-set version in the note's
      `# History` journal, committed together with the version; `--bump`, and a `--set` of the version the note
      already carries, record none.
    - When the journal refuses that line, or the history verb cannot be resolved, the note is restored to its
      previous content, nothing is committed, and the error goes to stderr.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success or a `--bump` noop, 1 on a refusal, 2 when the path names no file, the product is
    unknown, the version or manifest cannot be read, or a `--set` write cannot record its History line.
  """

  # Contract:
  # A `--set` pins the version it writes: `spec_version_pinned: true` lands in the same commit as the version, and a
  # `--bump` on a pinned note MUST write and commit nothing, printing `{"status": "noop", ...}` and exiting 0.

  # Domain(spec.lifecycle):
  # # An operator-set version is pinned
  # A version an operator sets outright is a decision, not an arithmetic result, so it stands until the operator
  # sets another one: no later bump over the previous release replaces it, whether the bump would raise it or not.

  # Contract:
  # A `--bump` only ever raises the version a release note carries: a bumped value not above the note's current
  # `spec_version` MUST write and commit nothing, and the verb prints `{"status": "noop", ...}` and exits 0.
  # Callers MUST treat that status as success with the carried version standing; an operator-set version is
  # never lowered by a bump.

  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs release-version")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("note", type = Path)
  group = parser.add_mutually_exclusive_group(required = True)
  # waiver: argparse CLI signature -- option name and its attribute
  group.add_argument("--set", dest = "explicit")
  # waiver: argparse CLI signature -- option name
  group.add_argument("--bump", choices = PARTS)
  # waiver: argparse CLI signature -- option name
  parser.add_argument("--product", default = "")
  args = parser.parse_args(argv)
  note: Path = args.note.resolve()

  # guard: a path that names no file has no frontmatter to write into
  if not note.is_file():
    sys.stderr.write(f"no such note: {note}\n")
    return 2

  # the version to write, given outright or bumped over the product's previous one, under the note's own settings:
  # the note path is the explicit start
  repo = spec_locator.query_settings_root(note.parent)
  previous: str | None = None
  try:
    if args.explicit is not None:
      version = args.explicit
    else:
      # guard: an unknown product has no previous version to bump from
      if (record := resolve_product.resolve_product_by_key(repo, args.product)) is None:
        sys.stderr.write(f"unknown product: {args.product!r}\n")
        return 2
      previous = read_previous_version(repo, record, note.parent.parent)
      version = bump(previous, args.bump)

      # guard: an operator-set version is pinned; no bump ever replaces it, and nothing is written
      if flip_gate.is_true(spec_frontmatter.parse(note.read_text(encoding = _ENCODING))[0],
                           ReleaseKey.VERSION_PINNED):
        print(json.dumps({ _STATUS: _STATUS_NOOP, _REASON: _MSG_PINNED, _VERSION: version, _PREVIOUS: previous }))
        return 0

      # guard: a bump only ever moves the version up; a version at or above it stands and nothing is written
      if (reason := find_bump_noop_reason(note, version)) is not None:
        print(json.dumps({ _STATUS: _STATUS_NOOP, _REASON: reason, _VERSION: version, _PREVIOUS: previous }))
        return 0
    original = note.read_text(encoding = _ENCODING)
    result = set_release_version(note, version, pin = args.explicit is not None)
  except (ValueError, OSError) as error:
    sys.stderr.write(f"{error}\n")
    return 2

  # an operator-set version leaves its own line in the note's journal, riding the version's commit; a journal
  # that refuses the line takes the version write back with it, so nothing is left uncommitted
  set_anew = spec_frontmatter.parse(original)[0].get(ReleaseKey.VERSION, "").strip() != version
  if result[_STATUS] == _STATUS_SET and set_anew and args.explicit is not None:
    try:
      history_journal.append_to_file(
          note, note_explainers.history_line(note, HistoryEvent.VERSION_SET, version = result[_VERSION]),
          repo = repo)
    except RuntimeError as error:
      spec_paths.write_text_atomic(note, original)
      sys.stderr.write(f"{error}\n")
      return 2

  # a refusal is reported as itself; a write carries the summary, committed under the verb's own identity
  if result[_STATUS] == _STATUS_REFUSED:
    print(json.dumps(result))
    return 1
  if result[_CHANGED]:
    commit_paths(repo, [ note ], author = VERSION_NAME,
                 subject = f"{VERSION_NAME}: {result[_VERSION]} on {note.parent.name}")
  print(json.dumps({
      _VERSION: result[_VERSION], _TAG: result[_TAG], _PREVIOUS: previous, _CHANGED: result[_CHANGED],
  }))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
