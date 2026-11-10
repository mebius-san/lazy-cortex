"""
Read-only validation of a consumer's lazy-review configuration.

Validates the `review` section of `lazy.settings.json` for structural soundness, expert registration,
section-writer schema, callout vocabulary, and class path scoping; each finding names the failing check
and, where one exists, the repair.

Output is a JSON record with `level` (PASS/WARN/FAIL) and a list of
`findings`. Exit code: 0 on PASS, 1 on WARN, 2 on FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import banner as _banner  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import core_settings as _core_settings  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import doc_class as _doc_class  # pylint: disable=import-error
# waiver: `plugins/claude/lazycortex-specs/bin/note_ops.py` shares this basename; in a whole-project mypy run the bare
# `import note_ops` below resolves to that unrelated module instead (this dir's `__init__.py` makes review's
# own copy package-qualified as `bin.note_ops`), so mypy checks the attribute against the wrong file's shape
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import note_ops as _note_ops  # type: ignore  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from errors import SettingsReadError  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from keys import Bucket, JobKey, Phase, Position, ReviewStatus, Style, Tag  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_VALID_STYLES = {"simple", "diff", "criticmarkup", "html"}
_SECTION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_FLAT_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
# Type-name prefix shared by every level review class (`system-vision`, `system-design`, …) —
# its document is loose at a product root, so its product-scoped glob names one file rather than
# fixing an asset depth.
_LEVEL_TYPE_PREFIX = "system-"

# Finding id for a duplicated `class` identity token. Unlike its per-entry siblings, which are
# built as `f"class_{i}_..."`, this one names a collision between two entries and so carries no
# single index.
_CHECK_CLASS_IDENTITY_DUP = "class_identity_dup"

# The closed vocabulary for `#review/<tag>` callouts: the two operator/coordinator-facing
# marker tags plus every banner state tag `banner.py` itself recognises. Computed from
# `banner.State` rather than hardcoded so a future banner state stays in sync automatically.
# The banner-state half never actually rejects anything today — `note_ops.build_report`'s own
# `callouts` list already excludes tags in that same set (they are reported via `banner`
# instead) — but the union is kept explicit rather than trimmed to the reachable subset, so this
# check stays correct against the vocabulary the spec defines rather than against whatever
# `note_ops` happens to pre-filter this release.
_VALID_CALLOUT_TAGS = {"command", "question"} | {state.value for state in _banner.State}

# Finding message for a section id outside the tag-safe alphabet, filled with the section id.
SECTION_ID_ALPHABET_TEMPLATE = (
    'section-id "{section_id}" violates ^[a-z][a-z0-9_-]*$'
    " — needed for tag parsing (#expert/<flat-name>/<section-id>)"
)
# Finding message for a section id declared under both umbrellas of one class, filled with the section id.
SECTION_ID_COLLISION_TEMPLATE = (
    'section-id "{section_id}" declared in both validation and terminal'
    " — tag #expert/<flat-name>/{section_id} would be ambiguous"
)
# Finding message for a section writer lacking a required field, filled with its location and the field.
WRITER_MISSING_FIELD_TEMPLATE = (
    'writer at {class_name}.experts.{umbrella}.{section_id} missing required field "{field}"'
)
# The repair route a fixed-depth product-scoped glob names: the operator rewrites the class entry's paths there.
OVERRIDE_GLOB_REPAIR_ROUTE = "/lazy-review.configure"
# Finding message for a product-scoped class with a fixed-depth glob, filled with the class label and the repair.
OVERRIDE_GLOB_DEPTH_TEMPLATE = (
    "class {label!r} carries a fixed-depth glob; fix the class entry's paths via {repair}"
)


def _add(findings: list[dict], severity: str, check: str, message: str) -> None:
  """
  Append a finding record to the findings list.

  Args:
    findings: Mutable list to append the finding to.
    severity: Severity level string, one of `PASS`, `WARN`, or `FAIL`.
    check: Short identifier for the check that produced this finding.
    message: Human-readable description of the finding.
  """
  findings.append({JobKey.SEVERITY: severity, JobKey.CHECK: check, JobKey.MESSAGE: message})


def _flatten_expert_name(name: str) -> str:
  """
  Map an expert dispatch name to its Obsidian-tag-safe flat form.

  Args:
    name: Expert dispatch name, possibly containing dots.

  Returns:
    The name with every `.` replaced by `-`.
  """
  return name.replace(".", "-")


def _check_section_writers_new_schema(settings: dict, findings: list[dict]) -> None:
  """
  Check section-writer entries against the new section-writer schema.

  Validates every writer object under `experts.validation.<sid>` and
  `experts.terminal.<sid>` in each `review.classes` entry.

  Args:
    settings: Parsed `lazy.settings.json` contents.
    findings: Mutable findings list to append to.
  """
  classes = settings.get(JobKey.REVIEW, {}).get(JobKey.CLASSES) or []
  root_experts = settings.get(JobKey.EXPERTS) or {}
  for class_cfg in classes:
    # guard: skip non-dict class entries — nothing to read experts from
    if not isinstance(class_cfg, dict):
      continue
    # waiver: one-off human-facing message
    class_name = class_cfg.get(JobKey.CLASS, "<unnamed>")
    experts_cfg = class_cfg.get(JobKey.EXPERTS) or {}

    # guard: malformed experts block (not a dict) has no umbrellas to walk
    if not isinstance(experts_cfg, dict):
      continue
    seen_section_ids: dict[str, str] = {}  # section_id → first umbrella seen
    for umbrella in (Bucket.VALIDATION, Bucket.TERMINAL):
      umbrella_cfg = experts_cfg.get(umbrella) or {}

      # guard: malformed umbrella block (not a dict) has no writers to validate
      if not isinstance(umbrella_cfg, dict):
        continue
      for section_id, writer in umbrella_cfg.items():
        # Rule 1: section-id alphabet
        if not _SECTION_ID_RE.match(section_id):
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL, "section-id-alphabet",
               SECTION_ID_ALPHABET_TEMPLATE.format(section_id = section_id))

        # Rule 2: uniqueness across umbrellas
        if section_id in seen_section_ids and seen_section_ids[section_id] != umbrella:
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL, "section-id-collision",
               SECTION_ID_COLLISION_TEMPLATE.format(section_id = section_id))
        seen_section_ids[section_id] = umbrella

        # Rule 3: writer-object must be a dict with required fields
        if not isinstance(writer, dict):
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL, "writer-object-shape",
               f"writer at {class_name}.experts.{umbrella}.{section_id} must be a dict")
          continue
        for field in (JobKey.NAME, JobKey.SECTION, JobKey.POSITION):
          if field not in writer:
            # waiver: one-off human-facing message
            _add(findings, ReviewStatus.FAIL, "writer-missing-field", WRITER_MISSING_FIELD_TEMPLATE.format(
                class_name = class_name, umbrella = umbrella, section_id = section_id, field = field,
            ))

        # Rule 4: repo field is deprecated; "." is silently accepted
        # waiver: external-format field name, not an internal key
        if "repo" in writer and writer["repo"] != ".":
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL, "repo-field-redundant",
               f'writer {writer.get(JobKey.NAME, "")!r} has `repo` field — drop it; every writer '
               f'runs in this repo (the field is deprecated; "." is silently accepted)')

        # Rule 5: position enum
        position = writer.get(JobKey.POSITION)
        if position is not None and position not in (Position.TOP, Position.BOTTOM):
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL, "position-enum",
               f'writer at {class_name}.experts.{umbrella}.{section_id}'
               f' has position="{position}" — must be "top" or "bottom"')

        # Rule 6: section non-empty
        section_title = writer.get(JobKey.SECTION)
        if section_title is not None and (
            not isinstance(section_title, str) or not section_title.strip()
        ):
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL, "section-title-empty",
               f"writer at {class_name}.experts.{umbrella}.{section_id}"
               f" has empty section title")

        # Rule 7: flat-name alphabet (existing: flattened dot-name)
        name = writer.get(JobKey.NAME, "")
        if name:
          flat = _flatten_expert_name(name)
          if not _FLAT_NAME_RE.match(flat):
            # waiver: one-off human-facing message
            _add(findings, ReviewStatus.FAIL, "flat-name-alphabet",
                 f'expert "{name}" flattens to "{flat}"'
                 f" which violates tag-safe alphabet ^[a-z0-9_-]+$")

        # Rule 8: name resolves in root experts catalog
        if name and name not in root_experts:
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL, "expert-not-registered",
               f'expert "{name}" referenced in'
               f" {class_name}.experts.{umbrella}.{section_id}"
               f" is not registered in root experts catalog")


def _check_watch_root(settings: dict, findings: list[dict]) -> None:
  """
  Fail every class whose globs can match documents outside `review.watch_root`.

  The coordinator's git-watch sees only commits under the watch root, so a class reaching past
  it never enters the loop and nothing reports why. An absent root means the whole repository.

  Args:
    settings: Parsed `lazy.settings.json` contents.
    findings: Mutable findings list to append to.
  """

  # Domain(review.config):
  # # Watch coverage
  # The coordinator hears only about commits inside one watched folder. A class whose documents
  # can live outside that folder never enters the review loop, so every class must sit under it.

  # an absent or bare-slash root is the whole repository
  review = settings.get(JobKey.REVIEW) or {}
  watch_root = str(review.get(JobKey.WATCH_ROOT) or ".").rstrip("/") or "."

  # a whole-repo watch covers every class there is
  if watch_root == ".":
    return

  # each class is judged on its own, so one finding names every glob of that class that escapes
  for i, class_cfg in enumerate(review.get(JobKey.CLASSES) or []):
    # guard: a malformed entry is the shape checks' finding, not this one's
    if not isinstance(class_cfg, dict):
      continue

    # a glob escapes when its own root is not the watch root or a folder below it
    outside = [
        pat for pat in class_cfg.get(JobKey.PATHS) or []
        if isinstance(pat, str)
        and os.path.commonpath([ watch_root, _doc_class.glob_root(pat) ]) != watch_root
    ]
    if outside:
      # waiver: one-off human-facing message
      _add(findings, ReviewStatus.FAIL, "watch_root_coverage",
           f"class {class_cfg.get(JobKey.CLASS) or f'#{i}'!r} globs {outside} reach outside"
           f" review.watch_root {watch_root!r}; re-run /lazy-review.install to widen it")


def _check_override_globs(settings: dict, findings: list[dict]) -> None:
  """
  Warn on a product-scoped class whose glob fixes the asset depth.

  A `<type>@<key>` class written before assets could sit at any depth carries
  `<spec_path>/*/*/<doc>.md`; an asset at the product root or nested deeper falls out of it and
  loses the product's own experts. The finding names `/lazy-review.configure` as the repair route
  for the class entry's paths. A `system-` class is exempt: its document is a level doc loose at
  the product root, so its glob names that one file and fixes no asset depth at all.

  Args:
    settings: Parsed `lazy.settings.json` contents.
    findings: Mutable findings list to append to.
  """
  classes = settings.get(JobKey.REVIEW, {}).get(JobKey.CLASSES) or []
  for class_cfg in classes:
    # guard: only a dict entry carries a label and paths to judge
    if not isinstance(class_cfg, dict):
      continue
    label = str(class_cfg.get(JobKey.CLASS) or "")
    type_part, sep, _key = label.partition("@")

    # a shared class routes by type and never fixed a depth
    if not sep:
      continue

    # a level class (any `system-` type, e.g. `system-vision@<key>`) names one loose
    # document at the product root by design — it carries no asset depth to have fixed
    if type_part.startswith(_LEVEL_TYPE_PREFIX):
      continue
    paths = class_cfg.get(JobKey.PATHS) or []
    if any(isinstance(pat, str) and "**" not in pat for pat in paths):
      # waiver: the finding's check id is a report wire token named at this one call site
      _add(findings, ReviewStatus.WARN, "override_glob_depth",
           OVERRIDE_GLOB_DEPTH_TEMPLATE.format(label = label, repair = OVERRIDE_GLOB_REPAIR_ROUTE))


def _collect_review_files(repo_root: Path, paths: list[str]) -> list[Path]:
  """
  Walk `repo_root` and collect every file whose repo-relative path matches any glob in `paths`.

  Args:
    repo_root: Repository root the glob patterns are relative to.
    paths: Glob patterns (e.g. `"request/*.md"`) a matching file's repo-relative path must satisfy.

  Returns:
    Absolute paths of matching files, in filesystem walk order.
  """

  # Decision: a filesystem walk, not the `git ls-files` listing `sanitize` uses — the audit judges
  # what is on disk, so a document the operator has not committed yet is checked before its first
  # commit routes it into the loop

  # walk the tree once, collecting every file whose repo-relative path matches a glob
  matches: list[Path] = []
  for base, subdirs, files in os.walk(str(repo_root)):
    # dot-folders (.git, .claude, .logs, .experts, ...) never hold review documents
    subdirs[:] = [sub for sub in subdirs if not sub.startswith(".")]
    for name in files:
      full = Path(base) / name
      rel = full.relative_to(repo_root).as_posix()

      # the same matcher the router uses: right-anchored `PurePath.match` for a plain glob, where
      # `*` never crosses `/`, and a repo-root-anchored match with `**` spanning any number of
      # segments for a product override glob — so the audit walks exactly the files the router
      # would route into the class, at any asset depth
      if any(_doc_class.is_glob_match(pat, PurePosixPath(rel)) for pat in paths):
        matches.append(full)
  return matches


def _check_callout_tags(repo_root: Path, settings: dict, findings: list[dict]) -> None:
  """
  Collect every `#review/<tag>` callout across the documents matched by `review.classes[].paths`
  and FAIL on any tag outside the closed vocabulary.

  Args:
    repo_root: Repository root `review.classes[].paths` glob patterns are relative to.
    settings: Parsed `lazy.settings.json` contents.
    findings: Mutable findings list to append to.
  """
  classes = settings.get(JobKey.REVIEW, {}).get(JobKey.CLASSES) or []
  seen: set[Path] = set()
  for class_cfg in classes:
    # guard: malformed class entries are already reported by _check_all's own shape check
    if not isinstance(class_cfg, dict):
      continue
    paths = class_cfg.get(JobKey.PATHS)

    # guard: a malformed/empty/non-string-entry paths list has no files to walk — the shape
    # itself is already reported by _check_all's own class_i_paths check
    if not isinstance(paths, list) or not paths or any(not isinstance(item, str) for item in paths):
      continue
    for file_path in _collect_review_files(repo_root, paths):
      # a file matched by more than one class is scanned only once
      if file_path in seen:
        continue
      seen.add(file_path)

      # parse the file's structural report once, to read off every callout it carries below
      # waiver: type: ignore[attr-defined] — the basename collision with
      # plugins/claude/lazycortex-specs/bin/note_ops.py (see the import comment above) makes mypy check
      # this attribute access against the wrong module's shape
      report = _note_ops.build_report(file_path.read_text(encoding = "utf-8"))  # type: ignore[attr-defined]

      # Domain(review.config):
      # # Closed vocabulary for review callout tags
      # A callout inside a review document may only carry one of the operator-facing marker
      # tags — a command or a question — or the tag of a state the status banner itself can
      # render. Any other tag is a configuration error: it names a state or intent the review
      # system has no way to act on. A concern tag is no longer in the set: validators write
      # plain prose and the main writer turns their findings into questions, so a concern
      # callout had no author and no way to be answered.

      # every callout not in the closed vocabulary FAILs, named by its repo-relative path and line
      # waiver: 'callouts'/'tag'/'line' are note_ops.build_report's own wire-shape keys, not keys.py-promoted constants
      for callout in report["callouts"]:
        # waiver: 'tag' is note_ops.build_report's own wire-shape key, not a keys.py-promoted constant
        tag = callout["tag"]

        # a callout in the known vocabulary produces no finding
        if tag[len(Tag.REVIEW_PREFIX):] in _VALID_CALLOUT_TAGS:
          continue
        # waiver: one-off human-facing message
        _add(findings, ReviewStatus.FAIL, "callout-tag-unknown",
             f'{file_path.relative_to(repo_root).as_posix()}:{callout["line"]}'
             f' unknown callout tag "{tag}"'
             f" — expected one of {sorted(_VALID_CALLOUT_TAGS)}")


def _check_all(settings: dict, findings: list[dict], *, repo_root: Path) -> None:
  """
  Apply all audit rules to a parsed settings dict.

  Args:
    settings: Parsed `lazy.settings.json` contents.
    findings: Mutable findings list to append to.
    repo_root: Repository root that `review.classes[].paths` globs are resolved against.
  """
  # the configured edit-marker style must be one of the supported styles
  style = settings.get(JobKey.REVIEW, {}).get(JobKey.EDIT_MARKER_STYLE, Style.SIMPLE)
  if style not in _VALID_STYLES:
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL, "edit_marker_style",
         f"unknown style {style!r}; expected one of {sorted(_VALID_STYLES)}")

  # the class list is the spine of the review config; everything below hangs off it
  review = settings.get(JobKey.REVIEW) or {}
  classes = review.get(JobKey.CLASSES) or []
  # guard: a malformed `review.classes` cannot be walked; report it and stop
  if not isinstance(classes, list):
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL, "review_classes_shape",
         # waiver: one-off human-facing message
         "'review.classes' must be a list")
    return

  # every expert a class names is collected here and checked against the table below
  experts_tbl = settings.get(JobKey.EXPERTS) or {}
  referenced: set[str] = set()

  # identity tokens seen so far, mapped to the entry index that claimed each one
  seen_tokens: dict[str, int] = {}

  # each class is checked in place, so one broken entry does not hide the rest
  for i, class_cfg in enumerate(classes):
    # guard: a non-object class entry cannot be read; report it and move to the next entry
    if not isinstance(class_cfg, dict):
      _add(findings, ReviewStatus.FAIL,f"class_{i}_shape",
           f"class #{i} is not an object")
      continue
    paths = class_cfg.get(JobKey.PATHS)
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
      _add(findings, ReviewStatus.FAIL,f"class_{i}_paths",
           f"class #{i} 'paths' must be a non-empty list of strings")

    # Domain(review.config):
    # # Class identity versus routing globs
    # A review class entry is addressed by administrative tooling through its own identity
    # token, never through the glob patterns that route documents into it. The token must be
    # unique across every class entry in one configuration — two entries sharing one token
    # would leave anything naming a class directly with an ambiguous target.

    # `class` is the entry's identity: tooling addresses entries by it, globs stay routing-only
    token = class_cfg.get(JobKey.CLASS)
    if not isinstance(token, str) or not token:
      _add(findings, ReviewStatus.WARN, f"class_{i}_identity",
           f"class #{i} carries no 'class' identity token")
    elif token in seen_tokens:
      _add(findings, ReviewStatus.FAIL, _CHECK_CLASS_IDENTITY_DUP,
           f"'class' token {token!r} used by classes #{seen_tokens[token]} and #{i}")
    else:
      seen_tokens[token] = i
    experts = class_cfg.get(JobKey.EXPERTS) or {}
    # guard: a non-object `experts` map cannot be walked; report it and move to the next entry
    if not isinstance(experts, dict):
      _add(findings, ReviewStatus.FAIL,f"class_{i}_experts_shape",
           f"class #{i} 'experts' must be an object")
      continue

    # validation and terminal use the dict-of-writer-object schema and are
    # validated separately by _check_section_writers_new_schema; every other
    # group must be a list of named members
    new_schema_umbrellas = {Bucket.VALIDATION, Bucket.TERMINAL}
    for group_key, members in experts.items():
      # a leftover `history` group is skipped rather than validated: the historian
      # chain it configured no longer runs, so its shape no longer matters
      if group_key in new_schema_umbrellas or group_key == Phase.HISTORY:
        continue
      if not isinstance(members, list):
        _add(findings, ReviewStatus.FAIL,f"class_{i}_group_{group_key}",
             f"class #{i} group {group_key!r} must be a list")
        continue
      for m in members:
        if not isinstance(m, dict) or JobKey.NAME not in m:
          _add(findings, ReviewStatus.FAIL,f"class_{i}_member",
               f"class #{i} group {group_key!r} member missing 'name': {m!r}")
          continue
        referenced.add(m[JobKey.NAME])

  # a class may only reference an expert the top-level table actually declares
  for name in referenced:
    if name not in experts_tbl:
      _add(findings, ReviewStatus.FAIL,f"expert_{name}_missing",
           f"expert {name!r} referenced by a class but not in top-level 'experts'")
      continue
    entry = experts_tbl.get(name, {})
    if not entry.get(JobKey.AGENT):
      _add(findings, ReviewStatus.FAIL,f"expert_{name}_no_agent",
           f"expert {name!r} missing 'agent'")
    author = entry.get(JobKey.GIT_AUTHOR) or {}
    if not author.get(JobKey.NAME) or not author.get(JobKey.EMAIL):
      _add(findings, ReviewStatus.WARN,f"expert_{name}_no_git_author",
           f"expert {name!r} missing git_author.name or git_author.email")

  # a config with no classes parses fine but reviews nothing
  if not classes:
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.WARN, "no_classes",
         # waiver: one-off human-facing message
         "no review.classes configured — run /lazy-review.configure")

  # the section-writer schema has its own rules, checked as a separate pass
  _check_section_writers_new_schema(settings, findings)
  _check_override_globs(settings, findings)
  _check_watch_root(settings, findings)

  # the callout-tag vocabulary check reads the class-routed documents on disk under repo_root
  _check_callout_tags(repo_root, settings, findings)


def run(settings_path: Path) -> dict:
  """
  Audit the merged review settings of the repository that `settings_path` locates and return a findings bundle.

  The tracked `.claude/lazy.settings.json` with the local overlay `.claude/lazy.settings.local.json` merged
  on is audited; the file at `settings_path` is never read, only checked for existence.

  Guarantees:
    - The result's `level` is `FAIL` when any finding is `FAIL`, `WARN` when none is `FAIL` but at
      least one is `WARN`, and `PASS` only when every finding is `PASS`.

  Args:
    settings_path: Path of the settings file, used only to locate the repository root, which is the parent of
      the file's directory; a missing file yields one `FAIL` finding named `settings_present`.

  Returns:
    A bundle dict with keys `level` (`PASS`, `WARN`, or `FAIL`) and `findings` (list of
    finding records).

  Raises:
    RuntimeError: If no core CLI resolves; raised by `core_settings.read_merged_sections` and not caught here.
  """

  # Contract:
  # The result's aggregate `level` MUST be `FAIL` when any finding is `FAIL`, `WARN` when no
  # finding is `FAIL` but at least one is `WARN`, and `PASS` only when every finding is `PASS`.

  findings: list[dict] = []
  # guard: no settings file to audit; report its absence and stop
  if not settings_path.exists():
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL, "settings_present",
         f"missing {settings_path} — run /lazy-review.install first")
    return _bundle(findings)

  # the classic layout is <repo_root>/.claude/lazy.settings.json (Paths.CLAUDE_DIR /
  # Paths.SETTINGS_FILE), so the settings file's grandparent is the repo root
  repo_root = settings_path.parent.parent

  # the review and experts sections as core's own readers see them, overlay merged on, so a value
  # set only in the local overlay is audited, not missed
  try:
    settings: dict = _core_settings.read_merged_sections(repo_root, JobKey.REVIEW, JobKey.EXPERTS)
  except SettingsReadError as error:
    # guard: a settings layer core cannot read is the one finding, and nothing below can run without it
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL, "settings_parse", f"unreadable settings: {error}")
    return _bundle(findings)

  # every check runs against the merged view, and the callout check reads documents under the repo root
  _check_all(settings, findings, repo_root = repo_root)
  return _bundle(findings)


def _bundle(findings: list[dict]) -> dict:
  """
  Compute the aggregate level and wrap findings into a result bundle.

  Args:
    findings: Finding records collected by the checks.

  Returns:
    A dict with `level` set to `FAIL` if any finding is FAIL, `WARN` if any is WARN and none
    are FAIL, or `PASS` otherwise; and `findings` containing the full list.
  """

  levels = {f[JobKey.SEVERITY] for f in findings}
  if ReviewStatus.FAIL in levels:
    level = ReviewStatus.FAIL
  elif ReviewStatus.WARN in levels:
    level = ReviewStatus.WARN
  else:
    level = ReviewStatus.PASS
  return {JobKey.LEVEL: level, JobKey.FINDINGS: findings}


def main(argv: list[str]) -> int:
  """
  Run the audit and print the JSON report to stdout.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 for PASS, 1 for WARN, 2 for FAIL.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazy-review.audit")
  parser.add_argument(
      # waiver: argparse CLI signature, not a domain key
      "--settings",
      type = Path,
      default = Path(".claude/lazy.settings.json"),
      # waiver: one-off human-facing message
      help = "path to the tracked .claude/lazy.settings.json; it only locates the repo root (the parent of "
             "its directory), whose merged settings, the tracked file with the local overlay merged on, are audited",
  )
  args = parser.parse_args(argv)
  report = run(args.settings.resolve())
  print(json.dumps(report, indent = 2))
  return {ReviewStatus.PASS: 0, ReviewStatus.WARN: 1, ReviewStatus.FAIL: 2}[report[JobKey.LEVEL]]


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
