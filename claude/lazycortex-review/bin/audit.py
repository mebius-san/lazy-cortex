"""Read-only validation of a consumer's lazy-review configuration.

Checks performed (one finding per check):

- `lazy.settings.json` is present and valid JSON.
- `review.classes` is a list; each entry has `paths` (list of str)
  and `experts` (dict).
- Every expert name referenced in `main` / `<section>` /
  `history` / `final` is registered in the
  top-level `experts` dict.
- Every registered expert has a non-empty `agent` AND a non-empty
  `git_author` block.
- `review.edit_marker_style` is one of the four supported
  styles (`simple`/`diff`/`criticmarkup`/`html`).
- New-schema `experts.validation` / `experts.terminal` writer objects
  satisfy the section-schema rules (Task 4.1).

Output is a JSON record with `level` (PASS/WARN/FAIL) and a list of
`findings`. Exit code: 0 on PASS, 1 on WARN, 2 on FAIL.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import re
import sys
from pathlib import Path

from keys import Bucket, JobKey, Phase, Position, ReviewStatus, Style

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_VALID_STYLES = {"simple", "diff", "criticmarkup", "html"}
_SECTION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_FLAT_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
_FLAT_PART_RE = re.compile(r"^[a-z0-9_-]+$")


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


def _parse_expert_name(name: str) -> tuple[str, str]:
  """
  Split an `expert@repo` name into `(expert_part, repo_part)`.

  Local mirror of the `expert_name` parser shipped by `lazycortex-core`;
  cross-plugin import is an anti-pattern per the inter-plugin boundary contract.
  Keep this implementation in sync with the upstream module.

  Returns:
    A two-tuple `(expert_part, repo_part)`. Returns `(name, ".")` when no `@` is
    present. Returns `(name, "")` when the syntax is malformed (empty expert or repo part).
  """
  if "@" not in name:
    return name, "."
  expert, _, repo = name.rpartition("@")
  if not expert or not repo:
    return name, ""  # signal malformed; caller will FAIL
  return expert, repo


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
               f'writer {writer.get(JobKey.NAME, "")!r} has `repo` field — use @<repo> in `name` instead '
               f'(this field is deprecated; "." is silently accepted)')
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
    # Rule 6b (cross-repo): each part of expert@repo must pass alphabet check
        if name and "@" in name:
          expert_part, repo_part = _parse_expert_name(name)
          if not _FLAT_PART_RE.match(expert_part):
            # waiver: one-off human-facing message
            _add(findings, ReviewStatus.FAIL,"flat-name-alphabet",
                 f'expert part {expert_part!r} of {name!r} fails alphabet '
                 f'^[a-z0-9_-]+$ (left side)')
          if repo_part not in (".", "") and not _FLAT_PART_RE.match(repo_part):
            # waiver: one-off human-facing message
            _add(findings, ReviewStatus.FAIL,"flat-name-alphabet",
                 f'repo part {repo_part!r} of {name!r} fails alphabet '
                 f'^[a-z0-9_-]+$ (right side)')
    # Rule 7: name resolves in root experts catalog
        if name and name not in root_experts:
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL,"expert-not-registered",
               f'expert "{name}" referenced in'
               f" {class_name}.experts.{umbrella}.{section_id}"
               f" is not registered in root experts catalog")


def _check_all(settings: dict, findings: list[dict]) -> None:
  """
  Apply all audit rules to a parsed settings dict.
  """
  # edit_marker_style
  style = settings.get(JobKey.REVIEW, {}).get(JobKey.EDIT_MARKER_STYLE, Style.SIMPLE)
  if style not in _VALID_STYLES:
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL,"edit_marker_style",
         f"unknown style {style!r}; expected one of {sorted(_VALID_STYLES)}")

  review = settings.get(JobKey.REVIEW) or {}
  classes = review.get(JobKey.CLASSES) or []
  if not isinstance(classes, list):
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.FAIL,"review_classes_shape",
         # waiver: one-off human-facing message
         "'review.classes' must be a list")
    return

  experts_tbl = settings.get(JobKey.EXPERTS) or {}
  referenced: set[str] = set()

  for i, class_cfg in enumerate(classes):
    if not isinstance(class_cfg, dict):
      _add(findings, ReviewStatus.FAIL,f"class_{i}_shape",
           f"class #{i} is not an object")
      continue
    paths = class_cfg.get(JobKey.PATHS)
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
      _add(findings, ReviewStatus.FAIL,f"class_{i}_paths",
           f"class #{i} 'paths' must be a non-empty list of strings")
    experts = class_cfg.get(JobKey.EXPERTS) or {}
    if not isinstance(experts, dict):
      _add(findings, ReviewStatus.FAIL,f"class_{i}_experts_shape",
           f"class #{i} 'experts' must be an object")
      continue
  # validation and terminal use the new dict-of-writer-object schema;
  # they are validated separately by _check_section_writers_new_schema.
  # history uses a single writer-object {"name": ...}; repo is not allowed.
    new_schema_umbrellas = {Bucket.VALIDATION, Bucket.TERMINAL}
    history_val = experts.get(Phase.HISTORY)
    if history_val is not None:
      if not isinstance(history_val, dict):
        _add(findings, ReviewStatus.FAIL,f"class_{i}_history_shape",
             f'class #{i} experts.history must be a single writer object {{"name": ...}};'
             # waiver: reporting the type name of an arbitrary config value in an error message; type(x).__name__ is the right idiom — no class-system object here
             f" got {type(history_val).__name__}")
      else:
        name_val = history_val.get(JobKey.NAME)
        if not name_val or not isinstance(name_val, str):
          _add(findings, ReviewStatus.FAIL,f"class_{i}_history_name",
               f'class #{i} experts.history missing required field "name"'
               f' (must be a non-empty string)')
        else:
          referenced.add(name_val)
        # waiver: external-format field name, not an internal key
        if "repo" in history_val:
          _add(findings, ReviewStatus.FAIL,f"class_{i}_history_repo_forbidden",
               f'class #{i} experts.history must be a single writer object {{"name": ...}};'
               f' "repo" is not allowed (historian always runs in the local repo)')
      # Rule (cross-repo): @<repo> syntax is forbidden on history.name
        name_val = history_val.get(JobKey.NAME, "")
        if isinstance(name_val, str) and "@" in name_val:
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL,"history-repo-syntax-forbidden",
               f'experts.history.name {name_val!r} uses @<repo> syntax — '
               f'historian must run locally, no cross-repo dispatch allowed')
      # Rule (cross-repo): historian commits the Doc-Review trailer
      # locally, so it MUST have can_commit_in_repo=true. Default
      # (false) would inject the foreign-execution no-commit clause
      # into the historian's prompt and silently break the trailer.
        if name_val and isinstance(name_val, str) and name_val in experts_tbl:
          h_entry = experts_tbl.get(name_val) or {}
          # waiver: external-format field name, not an internal key
          if isinstance(h_entry, dict) and not h_entry.get("can_commit_in_repo", False):
            # waiver: one-off human-facing message
            _add(findings, ReviewStatus.WARN,"history-needs-commit-permission",
                 f'historian {name_val!r} has can_commit_in_repo=false (or unset) — '
                 f'historian commits the Doc-Review trailer locally; set '
                 f'experts.{name_val}.can_commit_in_repo=true')
    for group_key, members in experts.items():
      # guard: new-schema umbrellas and history are validated elsewhere, not here
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

  if not classes:
    # waiver: one-off human-facing message
    _add(findings, ReviewStatus.WARN,"no_classes",
         # waiver: one-off human-facing message
         "no review.classes configured — run /lazy-review.configure")

# Rule (cross-repo): expert@repo names must reference a declared repos key
  repos_block = (settings.get(JobKey.REPOS) or {})
  declared_keys = {k for k in repos_block if k != JobKey.VERSION}
  for i, class_cfg in enumerate(classes):
    # guard: skip non-dict class entries — nothing to read experts from
    if not isinstance(class_cfg, dict):
      continue
    experts_cfg = (class_cfg.get(JobKey.EXPERTS) or {})
    # guard: malformed experts block (not a dict) has no groups to repo-check
    if not isinstance(experts_cfg, dict):
      continue
    for group_key, members in experts_cfg.items():
      collected_names: list[str] = []
      if group_key in (Bucket.VALIDATION, Bucket.TERMINAL) and isinstance(members, dict):
        collected_names = [w.get(JobKey.NAME, "") for w in members.values()
                           if isinstance(w, dict)]
      elif group_key == Phase.HISTORY:
          # history is single writer; @-check handled above; skip repo-key check
        continue
      elif isinstance(members, list):
        collected_names = [m.get(JobKey.NAME, "") for m in members
                           if isinstance(m, dict)]
      for name in collected_names:
        # guard: skip empty names and plain (non-cross-repo) expert names
        if not name or "@" not in name:
          continue
        _, repo_part = _parse_expert_name(name)
        # guard: local-repo sentinel ("." / empty) needs no declared repos key
        if repo_part in (".", ""):
          continue
        if repo_part not in declared_keys:
          # waiver: one-off human-facing message
          _add(findings, ReviewStatus.FAIL,"repo-key-not-declared",
               f'expert {name!r} references repo {repo_part!r} '
               f'not declared in `repos` — add `repos.{repo_part}: {{}}` '
               f'to lazy.settings.json')

  _check_section_writers_new_schema(settings, findings)


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
  _check_all(settings, findings)
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
