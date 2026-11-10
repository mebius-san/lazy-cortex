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

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import Gate, HistoryEvent, ReleaseConfigKey, ReleaseKey  # noqa: E402


_ENCODING = "utf-8"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"
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
_TOML_VERSION_RE = re.compile(r'^(\s*version\s*=\s*")[^"]*(".*)$')
_JSON_INDENT = 2

# Result keys
_STATUS = "status"
_REASON = "reason"
_VERSION = "version"
_TAG = "tag"
_PREVIOUS = "previous"
_CHANGED = "changed"
_STATUS_SET = "set"
_STATUS_REFUSED = "refused"


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
  # one, otherwise it is the highest version among the product's published releases, and a product
  # with neither starts at zero-point-one-point-zero whatever movement was asked for. A rebuild only
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


def version_tag(version: str) -> str:
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


def write_manifest_version(path: Path, version: str) -> None:
  """
  Replace the version field of a JSON or TOML manifest, leaving everything else as it was.

  Args:
    path: The manifest file.
    version: The version to write.

  Raises:
    ValueError: If the format is unknown or the manifest carries no version field to replace.
  """
  text = path.read_text(encoding = _ENCODING)

  # a JSON manifest is rewritten whole, its keys in their order
  if path.suffix == _JSON_SUFFIX:
    data = json.loads(text)
    data[_VERSION_FIELD] = version
    spec_paths.write_text_atomic(path, json.dumps(data, indent = _JSON_INDENT, ensure_ascii = False) + "\n")
    return

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
        spec_paths.write_text_atomic(path, "\n".join(lines))
        return
  raise ValueError(f"no version field in {path}")


def _published_versions(releases_dir: Path) -> list[str]:
  """
  Collect the versions of the published releases under a releases folder.

  Args:
    releases_dir: The product's `releases/` folder.

  Returns:
    The `spec_version` of every release note whose `spec_released` is true, unordered.
  """
  # guard: a product without releases has nothing published
  if not releases_dir.is_dir():
    return []

  # every release folder's own note, published ones only
  versions: list[str] = []
  for entry in sorted(os.listdir(releases_dir)):
    note = releases_dir / entry / f"{entry}.md"

    # guard: a folder without its own note is no release
    if not note.is_file():
      continue
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
    the published releases, otherwise None.
  """
  # the manifest is the point of reference whenever the product names one
  release_section = record.get(ReleaseConfigKey.SECTION) or {}
  manifest = release_section.get(ReleaseConfigKey.MANIFEST, "") if isinstance(release_section, dict) else ""
  if manifest:
    return read_manifest_version(repo / manifest)

  # otherwise the highest published release, if any
  versions = _published_versions(releases_dir)
  return max(versions, key = parse) if versions else None


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


def set_release_version(note: Path, version: str) -> dict:
  """
  Write a version and its mirror tag onto a release note.

  Args:
    note: The release's status note.
    version: The bare SemVer version to write.

  Returns:
    `{"status": "set", "version", "tag", "changed"}` on success, `changed` false when the note already carried
    exactly this version and tag; `{"status": "refused", "reason"}` when the release is published.

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
  tag = version_tag(version)
  tags = spec_frontmatter.read_list(text, _TAGS_KEY)
  new_tags = [ item for item in tags if not item.startswith(ReleaseKey.TAG_PREFIX) ] + [ tag ]
  changed = fm_values.get(ReleaseKey.VERSION, "").strip() != version or tags != new_tags
  if changed:
    updated = spec_frontmatter.set_scalar(text, ReleaseKey.VERSION, version)
    spec_paths.write_text_atomic(note, spec_frontmatter.write_list(updated, _TAGS_KEY, new_tags))
  return { _STATUS: _STATUS_SET, _VERSION: version, _TAG: tag, _CHANGED: changed }


def main(argv: list[str]) -> int:
  """
  Write a release's version from an explicit value or from a bump over the product's previous version.

  The repository root comes from the `LAZY_REPO_ROOT` environment variable, falling back to the repository that
  holds the note; the `--bump` form reads the product record from it and both forms commit into it.

  Notes:
    - Prints a JSON summary on stdout with the keys `version`, `tag`, `previous` and `changed`, or the refusal
      object with `status` and `reason`.
    - A `--set` write that changed the note also records a line naming the operator-set version in the note's
      `# History` journal, committed together with the version; `--bump` and an unchanged note record none.
    - When the journal refuses that line, or the history verb cannot be resolved, the note is restored to its
      previous content, nothing is committed, and the error goes to stderr.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 1 on a refusal, 2 when the path names no file, the product is unknown, the
    version or manifest cannot be read, or a `--set` write cannot record its History line.
  """
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

  # the version to write: given outright, or bumped over the product's previous one
  env_root = os.environ.get(_ENV_REPO_ROOT)
  repo = scaffold_asset.repo_root(Path(env_root) if env_root else note.parent)
  previous: str | None = None
  try:
    if args.explicit is not None:
      version = args.explicit
    else:
      record = resolve_product.resolve_product_by_key(repo, args.product)
      if record is None:
        sys.stderr.write(f"unknown product: {args.product!r}\n")
        return 2
      previous = read_previous_version(repo, record, note.parent.parent)
      version = bump(previous, args.bump)
    original = note.read_text(encoding = _ENCODING)
    result = set_release_version(note, version)
  except (ValueError, OSError) as error:
    sys.stderr.write(f"{error}\n")
    return 2

  # an operator-set version leaves its own line in the note's journal, riding the version's commit; a journal
  # that refuses the line takes the version write back with it, so nothing is left uncommitted
  if result[_STATUS] == _STATUS_SET and result[_CHANGED] and args.explicit is not None:
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
