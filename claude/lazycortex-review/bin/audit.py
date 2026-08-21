"""Read-only validation of a consumer's lazy-review configuration.

Checks performed (one finding per check):

- `lazy.settings.json` is present and valid JSON.
- `review.classes` is a list; each entry has `paths` (list of str) and a unique `class` identity token
  and `experts` (dict).
- Every expert name referenced in `main` / `<section>` / `final` is
  registered in the top-level `experts` dict.
- Every registered expert has a non-empty `agent` AND a non-empty
  `git_author` block.
- `review.edit_marker_style` is one of the four supported
  styles (`simple`/`diff`/`criticmarkup`/`html`).
- New-schema `experts.validation` / `experts.terminal` writer objects
  satisfy the section-schema rules (Task 4.1).
- Every `#review/<tag>` callout across the documents matched by
  `review.classes[].paths` belongs to the closed vocabulary: `command`
  / `question` / `concern` plus every `banner.py` state tag (Task 10).

Output is a JSON record with `level` (PASS/WARN/FAIL) and a list of
`findings`. Exit code: 0 on PASS, 1 on WARN, 2 on FAIL.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

import banner as _banner
# waiver: `claude/lazycortex-specs/bin/note_ops.py` shares this basename; in a whole-project mypy run the bare
# `import note_ops` below resolves to that unrelated module instead (this dir's `__init__.py` makes review's
# own copy package-qualified as `bin.note_ops`), so mypy checks the attribute against the wrong file's shape
import note_ops as _note_ops  # type: ignore
from keys import Bucket, JobKey, Phase, Position, ReviewStatus, Style, Tag

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_VALID_STYLES = {"simple", "diff", "criticmarkup", "html"}
_SECTION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_FLAT_NAME_RE = re.compile(r"^[a-z0-9_-]+$")

# Finding id for a duplicated `class` identity token. Unlike its per-entry siblings, which are
# built as `f"class_{i}_..."`, this one names a collision between two entries and so carries no
# single index.
_CHECK_CLASS_IDENTITY_DUP = "class_identity_dup"

# The closed vocabulary for `#review/<tag>` callouts (Task 10): the three operator/coordinator-
# facing marker tags plus every banner state tag `banner.py` itself recognises. Computed from
# `banner.State` rather than hardcoded so a future banner state stays in sync automatically.
# The banner-state half never actually rejects anything today — `note_ops.build_report`'s own
# `callouts` list already excludes tags in that same set (they are reported via `banner`
# instead) — but the union is kept explicit rather than trimmed to the reachable subset, so this
# check stays correct against the vocabulary the spec defines rather than against whatever
# `note_ops` happens to pre-filter this release.
_VALID_CALLOUT_TAGS = {"command", "question", "concern"} | {state.value for state in _banner.State}


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

  Returns:
    The name with every `.` replaced by `-`.
  """
  return name.replace(".", "-")


def _check_section_writers_new_schema(settings: dict, findings: list[dict]) -> None:
  """
  Apply seven rules for the new section-writer schema (Task 4.1).

  Validates every writer object under `experts.validation.<sid>` and
  `experts.terminal.<sid>` in each `review.classes` entry.
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
          _add(findings, ReviewStatus.FAIL,"section-id-alphabet",
               f'section-id "{section_id}" violates ^[a-z][a-z0-9_-]*$'
               f" — needed for tag parsing (#expert/<flat-name>/<section-id>)")
        # Rule 2: uniqueness across umbrellas
        if section_id in seen_section_ids and seen_section_ids[section_id] != umbrella:
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL,"section-id-collision",
               f'section-id "{section_id}" declared in both validation and terminal'
               f" — tag #expert/<flat-name>/{section_id} would be ambiguous")
        seen_section_ids[section_id] = umbrella
        # Rule 3: writer-object must be a dict with required fields
        if not isinstance(writer, dict):
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL,"writer-object-shape",
               f"writer at {class_name}.experts.{umbrella}.{section_id} must be a dict")
          continue
        for field in (JobKey.NAME, JobKey.SECTION, JobKey.POSITION):
          if field not in writer:
            # waiver: one-off human-facing message
            _add(findings, ReviewStatus.FAIL,"writer-missing-field",
                 f'writer at {class_name}.experts.{umbrella}.{section_id}'
                 f' missing required field "{field}"')
        # Rule 2 (cross-repo): repo field is deprecated; "." is silently accepted
        # waiver: external-format field name, not an internal key
        if "repo" in writer and writer["repo"] != ".":
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL,"repo-field-redundant",
               f'writer {writer.get(JobKey.NAME, "")!r} has `repo` field — drop it; every writer '
               f'runs in this repo (the field is deprecated; "." is silently accepted)')
        # Rule 4: position enum
        position = writer.get(JobKey.POSITION)
        if position is not None and position not in (Position.TOP, Position.BOTTOM):
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL,"position-enum",
               f'writer at {class_name}.experts.{umbrella}.{section_id}'
               f' has position="{position}" — must be "top" or "bottom"')
        # Rule 5: section non-empty
        section_title = writer.get(JobKey.SECTION)
        if section_title is not None and (
            not isinstance(section_title, str) or not section_title.strip()
        ):
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL,"section-title-empty",
               f"writer at {class_name}.experts.{umbrella}.{section_id}"
               f" has empty section title")
        # Rule 6: flat-name alphabet (existing: flattened dot-name)
        name = writer.get(JobKey.NAME, "")
        if name:
          flat = _flatten_expert_name(name)
          if not _FLAT_NAME_RE.match(flat):
            # waiver: one-off human-facing message
            _add(findings, ReviewStatus.FAIL,"flat-name-alphabet",
                 f'expert "{name}" flattens to "{flat}"'
                 f" which violates tag-safe alphabet ^[a-z0-9_-]+$")
        # Rule 7: name resolves in root experts catalog
        if name and name not in root_experts:
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL,"expert-not-registered",
               f'expert "{name}" referenced in'
               f" {class_name}.experts.{umbrella}.{section_id}"
               f" is not registered in root experts catalog")


def _collect_review_files(repo_root: Path, paths: list[str]) -> list[Path]:
  """
  Walk `repo_root` and collect every file whose repo-relative path matches any glob in `paths`.

  Mirrors `dispatcher.py`'s own `_iter_class_files` (that module is being retired — see
  `collect_ops.py`'s module docstring), reimplemented here rather than imported per the
  lazycortex-review coordinator migration's own-verbs-only boundary.

  Args:
    repo_root: Repository root the glob patterns are relative to.
    paths: Glob patterns (e.g. `"request/*.md"`) a matching file's repo-relative path must satisfy.

  Returns:
    Absolute paths of matching files, in filesystem walk order.
  """
  matches: list[Path] = []
  for base, subdirs, files in os.walk(str(repo_root)):
    # dot-folders (.git, .claude, .logs, .experts, ...) never hold review documents
    subdirs[:] = [sub for sub in subdirs if not sub.startswith(".")]
    for name in files:
      full = Path(base) / name
      rel = full.relative_to(repo_root).as_posix()
      # PurePosixPath.match honors shell-glob semantics where `*` does NOT cross `/`, unlike
      # `fnmatch.fnmatch` (the recursive-glob idiom the `Path.glob`/`rglob` ban prescribes), whose `*` matches `/`
      # too and would let a shallow class pattern (`request/*.md`) swallow files that belong to
      # a deeper-nested class (`request/products/*/changes/*/design.md`) — same rationale as
      # dispatcher.py's own `_iter_class_files`.
      if any(PurePosixPath(rel).match(pat) for pat in paths):
        matches.append(full)
  return matches


def _check_callout_tags(repo_root: Path, settings: dict, findings: list[dict]) -> None:
  """
  Collect every `#review/<tag>` callout across the documents matched by `review.classes[].paths`
  and FAIL on any tag outside the closed vocabulary (Task 10).

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
      # guard: a file matched by more than one class is scanned only once
      if file_path in seen:
        continue
      seen.add(file_path)

      # parse the file's structural report once, to read off every callout it carries below
      # waiver: type: ignore[attr-defined] — the basename collision with
      # claude/lazycortex-specs/bin/note_ops.py (see the import comment above) makes mypy check
      # this attribute access against the wrong module's shape
      report = _note_ops.build_report(file_path.read_text())  # type: ignore[attr-defined]

      # every callout not in the closed vocabulary FAILs, named by its repo-relative path and line
      # waiver: 'callouts'/'tag'/'line' are note_ops.build_report's own wire-shape keys, not keys.py-promoted constants
      for callout in report["callouts"]:
        tag = callout["tag"]
        # guard: known vocabulary — nothing to report
        if tag[len(Tag.REVIEW_PREFIX):] in _VALID_CALLOUT_TAGS:
          continue
        # waiver: one-off human-facing message
        _add(findings, ReviewStatus.FAIL, "callout-tag-unknown",
             f'{file_path.relative_to(repo_root).as_posix()}:{callout["line"]}'
             f' unknown callout tag "{tag}"'
             f" — expected one of {sorted(_VALID_CALLOUT_TAGS)}")


def _check_all(settings: dict, findings: list[dict], *, repo_root: Path | None = None) -> None:
  """
  Apply all audit rules to a parsed settings dict.

  Args:
    settings: Parsed `lazy.settings.json` contents.
    findings: Mutable findings list to append to.
    repo_root: Repository root to resolve `review.classes[].paths` against for the
      callout-tag-vocabulary check; `None` skips that check (a bare settings dict, with no
      repository to resolve paths against, per `run`'s own dict-input branch).
  """
  # edit_marker_style
  style = settings.get(JobKey.REVIEW, {}).get(JobKey.EDIT_MARKER_STYLE, Style.SIMPLE)
  if style not in _VALID_STYLES:
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL,"edit_marker_style",
         f"unknown style {style!r}; expected one of {sorted(_VALID_STYLES)}")

  # the class list is the spine of the review config; everything below hangs off it
  review = settings.get(JobKey.REVIEW) or {}
  classes = review.get(JobKey.CLASSES) or []
  if not isinstance(classes, list):
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL,"review_classes_shape",
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
    if not isinstance(class_cfg, dict):
      _add(findings, ReviewStatus.FAIL,f"class_{i}_shape",
           f"class #{i} is not an object")
      continue
    paths = class_cfg.get(JobKey.PATHS)
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
      _add(findings, ReviewStatus.FAIL,f"class_{i}_paths",
           f"class #{i} 'paths' must be a non-empty list of strings")

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
    if not isinstance(experts, dict):
      _add(findings, ReviewStatus.FAIL,f"class_{i}_experts_shape",
           f"class #{i} 'experts' must be an object")
      continue
    # validation and terminal use the new dict-of-writer-object schema;
    # they are validated separately by _check_section_writers_new_schema.
    # A leftover `history` group (the retired historian chain entry, Task
    # 11) is not validated at all — it is simply ignored here, same as any
    # other key this audit does not know about.
    new_schema_umbrellas = {Bucket.VALIDATION, Bucket.TERMINAL}
    for group_key, members in experts.items():
      # guard: new-schema umbrellas are validated elsewhere; a leftover history
      # group is intentionally unvalidated (Task 11 retired the historian chain)
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
    _add(findings, ReviewStatus.WARN,"no_classes",
         # waiver: one-off human-facing message
         "no review.classes configured — run /lazy-review.configure")

  # the section-writer schema has its own rules, checked as a separate pass
  _check_section_writers_new_schema(settings, findings)

  # the callout-tag vocabulary check needs real files on disk; skipped when no repo_root was
  # given (a bare settings dict has no repository to resolve `review.classes[].paths` against)
  if repo_root is not None:
    _check_callout_tags(repo_root, settings, findings)


def run(settings_or_path: Path | dict) -> dict:
  """
  Run all audit checks and return a findings bundle.

  Accepts either a `Path` to a `lazy.settings.json` file (classic CLI usage) or a
  pre-parsed settings `dict` (used by unit tests and programmatic callers that already
  hold the parsed config).

  Returns:
    A bundle dict with keys `level` (`PASS`, `WARN`, or `FAIL`) and `findings` (list of
    finding records).
  """
  findings: list[dict] = []
  if isinstance(settings_or_path, dict):
    _check_all(settings_or_path, findings)
    return _bundle(findings)
  settings_path: Path = settings_or_path
  if not settings_path.exists():
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL,"settings_present",
         f"missing {settings_path} — run /lazy-review.install first")
    return _bundle(findings)
  try:
    settings = json.loads(settings_path.read_text())
  except json.JSONDecodeError as exc:
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL,"settings_parse", f"invalid JSON: {exc}")
    return _bundle(findings)
  # the classic layout is <repo_root>/.claude/lazy.settings.json (Paths.CLAUDE_DIR /
  # Paths.SETTINGS_FILE), so the settings file's grandparent is the repo root
  _check_all(settings, findings, repo_root = settings_path.parent.parent)
  return _bundle(findings)


def _bundle(findings: list[dict]) -> dict:
  """
  Compute the aggregate level and wrap findings into a result bundle.

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
  parser = argparse.ArgumentParser(prog="lazy-review.audit")
  parser.add_argument(
      # waiver: argparse CLI signature, not a domain key
      "--settings",
      type=Path,
      default=Path(".claude/lazy.settings.json"),
  )
  args = parser.parse_args(argv)
  report = run(args.settings.resolve())
  print(json.dumps(report, indent=2))
  return {ReviewStatus.PASS: 0, ReviewStatus.WARN: 1, ReviewStatus.FAIL: 2}[report[JobKey.LEVEL]]


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
