"""
Migrations for the `review` section of `lazy.settings.json`.

v1 → v2 (`MIGRATIONS[1]`) renames the `plan` review class to `dev-plan`
(rewriting its `*/plan.md` path to `*/dev-plan.md`) and adds a `test-plan`
class (`*/test-plan.md` path) whose experts are copied from the renamed
`dev-plan` class. Idempotent: a section carrying no `plan` class leaves the
rename step untouched, and a section already carrying a `test-plan` class is
not given a second one.

v2 → v3 (`MIGRATIONS[2]`) rewrites the `test-plan` class's `experts.main` to
the tester expert, undoing the v1 → v2 seed that copied `dev-plan`'s main
verbatim — a test plan is the tester's document, not the implementer's.
Guarded: the rewrite only fires while `test-plan`'s `main` still equals
`dev-plan`'s `main` (the untouched copied state); an operator customization
is left alone. Idempotent: once rewritten, `main` no longer equals
`dev-plan`'s, so a second run is a no-op.

v3 → v4 (`MIGRATIONS[3]`) applies the uniform "a checkbox resolves its
expert from its own result document's review class" rule: `dev-plan`'s
`experts.main` moves from the implementer to the planner expert (guarded —
only while it still equals the `lazy-spec.product-config`-seeded default
`claude-plugin.implementer`; an operator customization is left alone), and
two new classes are added when absent — `dev-report` (`*/dev-report.md`,
main `claude-plugin.implementer`) and `test-report` (`*/test-report.md`,
main `claude-plugin.tester`) — so `Start implementation` / `Start testing`
resolve their own dedicated classes instead of borrowing `dev-plan` /
`test-plan`'s. Idempotent: a `dev-plan` main already pointing at the
planner, or a report class already present, is left untouched by a second
run.

v4 → v5 (`MIGRATIONS[4]`) adds `context_from_frontmatter:
["spec_source_requests"]` to the `design` and `bug` classes when the key is
absent, so the main-writer job dispatched for a spawned spec doc carries the
originating request file(s) in its `context/`. Guarded add-if-absent: a
class already declaring the key (an operator customization, or a previous
run of this migration) is left untouched.

v5 → v6 (`MIGRATIONS[5]`) rewrites any class's `experts.terminal.routing.name`
from the retired `spec.request-router` agent to `spec.coordinator`, which now
owns request routing (playbook § 7). Guarded: the rewrite only fires on an
entry whose `terminal.routing.name` still equals `spec.request-router`; an
operator customization pointing routing elsewhere is left alone. Idempotent:
once rewritten, the name no longer matches, so a second run is a no-op.

v6 → v7 (`MIGRATIONS[6]`) adds the `architecture` class (`*/architecture.md`,
main the architect expert, one `validation.planner_review` slot checking
whether the doc carries enough decisions to decompose into a plan — mirrors
`design`'s existing `developer_review` / `tester_review` validation shape)
when absent, and adds that same `planner_review` validation slot to the
existing `design` class (guarded add-if-absent: an operator-customized
`design.validation` block — one that already declares `planner_review` — is
left untouched).

v7 → v8 (`MIGRATIONS[7]`) moves every class's lazycortex-specs protocol
reference onto the plugin's own namespace: a `classes[].protocols[]` member
`lazycortex-specs:spec.<name>` becomes `lazycortex-specs:lazy-spec.<name>`,
matching the renamed reference files. A class without a protocol list, a
protocol from any other plugin, and a section already on the new prefix all
pass through unchanged.

v8 → v9 (`MIGRATIONS[8]`) follows the lazycortex-specs document-type rename
`dev-plan` → `code-plan` / `dev-report` → `code-report` and the historian
retirement: a class named after a retired type is renamed (product-qualified
variants included), EVERY entry's path globs have their `/dev-plan.md` /
`/dev-report.md` suffixes rewritten (a class whose name was already renamed
by the specs plugin's own `doc-type rename` still carries stale globs), and
an `experts.history` block naming the retired `review.historian` expert is
dropped; a history block naming any other expert — an operator
customization — is preserved. Idempotent: a second run finds nothing under
the retired names. Add `9: lambda data: <transformed>` here when a v9 → v10
migration is needed.
"""
from __future__ import annotations

import copy

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import ReviewClassKey, ReviewClassName  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: review-class sub-key literal local to this ladder, not a reusable cross-module key
_PROTOCOLS_KEY = "protocols"

# the reference prefix a specs protocol carried before the plugin took its own namespace
_SPEC_PROTOCOL_OLD_PREFIX = "lazycortex-specs:spec."
_SPEC_PROTOCOL_NEW_PREFIX = "lazycortex-specs:lazy-spec."

# waiver: one-off expert-name literals for these single main-rewrite/class-creation steps, not
# reusable domain values
_TESTER_EXPERT_NAME = "claude-plugin.tester"
_IMPLEMENTER_EXPERT_NAME = "claude-plugin.implementer"
_PLANNER_EXPERT_NAME = "claude-plugin.planner"
_HISTORIAN_EXPERT_NAME = "review.historian"
# waiver: "main" / "name" / "history" are nested experts-entry keys, not tracked in
# ReviewClassKey (which covers whole-class fields only; earlier migrations copy the experts
# block wholesale)
_MAIN_KEY = "main"
_NAME_KEY = "name"
_HISTORY_KEY = "history"
# waiver: v4 -> v5 class-config key + seed value, not tracked in ReviewClassKey (a generic
# dispatcher class-config key, not a whole-class field)
_CONTEXT_FROM_FRONTMATTER_KEY = "context_from_frontmatter"
_SPEC_SOURCE_REQUESTS_KEY = "spec_source_requests"
# waiver: v5 -> v6 nested experts.terminal.routing keys, not tracked in ReviewClassKey (that
# enum covers whole-class fields only; the terminal-writer block is a generic dispatcher shape)
_TERMINAL_KEY = "terminal"
_ROUTING_KEY = "routing"
# waiver: one-off expert-name literals for this single terminal-routing rename step, not
# reusable domain values
_ROUTER_EXPERT_NAME = "spec.request-router"
_COORDINATOR_EXPERT_NAME = "spec.coordinator"
# waiver: one-off expert-name literal for the v6 -> v7 architecture class seed, not a reusable
# domain value; mirrors the naming convention _PLANNER_EXPERT_NAME etc. already use
_ARCHITECT_EXPERT_NAME = "claude-plugin.architect"
# waiver: v6 -> v7 nested experts.validation keys, not tracked in ReviewClassKey (that enum
# covers whole-class fields only; the validation block is a generic dispatcher shape, same
# convention as the v5 -> v6 _TERMINAL_KEY / _ROUTING_KEY waiver above)
_VALIDATION_KEY = "validation"
_PLANNER_REVIEW_KEY = "planner_review"
_SECTION_KEY = "section"
_POSITION_KEY = "position"
# waiver: one-off section-title / position literals for this single validation-slot seed, not
# reusable domain values
_PLANNER_REVIEW_SECTION = "Planner review"
_PLANNER_REVIEW_POSITION = "bottom"
# waiver: one-off filename-glob literal for the single architecture class-creation step, not a
# reusable domain value
_ARCHITECTURE_PATH = "*/architecture.md"

_DEV_PLAN_SEEDED_DEFAULT_MAIN = [ { _NAME_KEY: _IMPLEMENTER_EXPERT_NAME } ]
# waiver: one-off filename-glob literals for a single class-creation step, not reusable domain values
_DEV_REPORT_PATH = "*/dev-report.md"
_TEST_REPORT_PATH = "*/test-report.md"

# waiver: one-off class-token separator + filename-suffix literals for the v8 -> v9 rename step,
# not reusable domain values
_CLASS_PRODUCT_SEP = "@"
_PATH_SUFFIX_RENAMES = { "/dev-plan.md": "/code-plan.md", "/dev-report.md": "/code-report.md" }

# The v8 -> v9 class-token renames, keyed by the retired base name.
_CODE_CLASS_RENAMES = {
    ReviewClassName.DEV_PLAN: ReviewClassName.CODE_PLAN,
    ReviewClassName.DEV_REPORT: ReviewClassName.CODE_REPORT,
}


def _to_dev_plan_entry(entry: dict) -> dict:
  """
  Build the migrated `dev-plan` entry for one legacy `plan` class record.

  Args:
    entry: The `plan` class dict, verbatim from `review.classes`.

  Returns:
    A new dict with `class` renamed to `dev-plan` and every path rewritten
    from its `plan.md` suffix to `dev-plan.md`.
  """
  # waiver: one-off filename-suffix literals for this single rename step, not a reusable domain value
  new_paths = [ p.replace("/plan.md", "/dev-plan.md") for p in entry[ReviewClassKey.PATHS] ]
  return { **entry, ReviewClassKey.CLASS: ReviewClassName.DEV_PLAN, ReviewClassKey.PATHS: new_paths }


def _rename_plan_to_dev_plan(classes: list[dict]) -> list[dict]:
  """
  Rename the `plan` review class to `dev-plan`, rewriting its path suffix.

  Args:
    classes: The `review.classes` list, verbatim from the settings section.

  Returns:
    A new list with the `plan` entry (if any) replaced by its `dev-plan`
    equivalent; every other entry is passed through unchanged.
  """
  # rebuild the list, replacing only the entry whose class is the legacy `plan`
  return [
    _to_dev_plan_entry(entry) if entry.get(ReviewClassKey.CLASS) == ReviewClassName.LEGACY_PLAN else entry
    for entry in classes
  ]


def _add_test_plan_class(classes: list[dict]) -> list[dict]:
  """
  Add a `test-plan` review class copied from `dev-plan`, when missing.

  Args:
    classes: The `review.classes` list, already past the `plan` → `dev-plan`
      rename.

  Returns:
    The list with a `test-plan` entry appended, or unchanged when one is
    already present or no `dev-plan` class exists to copy experts from.
  """
  # guard: a test-plan class already exists — nothing to add
  if any(entry.get(ReviewClassKey.CLASS) == ReviewClassName.TEST_PLAN for entry in classes):
    return classes

  # guard: no dev-plan class to copy experts from — nothing to add
  if (dev_plan := next(
      (entry for entry in classes if entry.get(ReviewClassKey.CLASS) == ReviewClassName.DEV_PLAN), None,
  )) is None:
    return classes

  # new class mirrors dev-plan's experts under its own path
  # waiver: one-off filename literal for this single class-creation step, not a reusable domain value
  test_plan = {
    ReviewClassKey.CLASS: ReviewClassName.TEST_PLAN,
    ReviewClassKey.PATHS: [ "*/test-plan.md" ],
    ReviewClassKey.EXPERTS: copy.deepcopy(dev_plan[ReviewClassKey.EXPERTS]),
  }
  return [ *classes, test_plan ]


def _migrate_plan_classes(data: dict) -> dict:
  """
  Apply the v1 → v2 `plan` → `dev-plan` + `test-plan` class migration.

  Args:
    data: The `review` section content at v1.

  Returns:
    The section content with `classes` migrated; all other keys preserved.
  """
  classes = _add_test_plan_class(_rename_plan_to_dev_plan(data.get(ReviewClassKey.CLASSES, [])))
  return { **data, ReviewClassKey.CLASSES: classes }


def _to_tester_entry(entry: dict) -> dict:
  """
  Build the migrated tester entry for one `test-plan` `experts.main` record.

  Args:
    entry: One `experts.main` entry dict, verbatim from the `test-plan` class.

  Returns:
    A new dict with `name` rewritten to the tester expert; every sibling key
    in the entry is preserved.
  """
  return { **entry, _NAME_KEY: _TESTER_EXPERT_NAME }


def _rewrite_test_plan_main(classes: list[dict]) -> list[dict]:
  """
  Rewrite the `test-plan` class's `experts.main` to the tester expert.

  Args:
    classes: The `review.classes` list, verbatim from the settings section.

  Returns:
    A new list with the `test-plan` entry's `experts.main` rewritten when it
    still equals `dev-plan`'s `main` (the state the v1 → v2 copy step left it
    in). Every other entry is passed through unchanged, as is a `test-plan`
    entry whose `main` has already diverged from `dev-plan`'s (an operator
    customization, or a previous run of this same migration). The whole list
    is passed through unchanged when there is no `dev-plan` class to compare
    against.
  """
  # guard: no dev-plan class to compare against — nothing to guard the rewrite with
  if (dev_plan := next(
      (entry for entry in classes if entry.get(ReviewClassKey.CLASS) == ReviewClassName.DEV_PLAN), None,
  )) is None:
    return classes

  # rebuild the list, rewriting only the test-plan entry's main when it still matches dev-plan's
  dev_plan_main = dev_plan.get(ReviewClassKey.EXPERTS, {}).get(_MAIN_KEY, [])
  result = []
  for entry in classes:
    # not the test-plan entry — pass through untouched
    if entry.get(ReviewClassKey.CLASS) != ReviewClassName.TEST_PLAN:
      result.append(entry)
      continue

    # main has already diverged from dev-plan's — operator customization or already migrated
    experts = entry.get(ReviewClassKey.EXPERTS, {})
    current_main = experts.get(_MAIN_KEY, [])
    if current_main != dev_plan_main:
      result.append(entry)
      continue

    # main still matches dev-plan's copied-by-v2 state — rewrite it to the tester expert
    new_experts = { **experts, _MAIN_KEY: [ _to_tester_entry(main_entry) for main_entry in current_main ] }
    result.append({ **entry, ReviewClassKey.EXPERTS: new_experts })
  return result


def _migrate_test_plan_main_to_tester(data: dict) -> dict:
  """
  Apply the v2 → v3 `test-plan` `experts.main` → tester migration.

  Args:
    data: The `review` section content at v2.

  Returns:
    The section content with `classes` migrated; all other keys preserved.
  """
  classes = _rewrite_test_plan_main(data.get(ReviewClassKey.CLASSES, []))
  return { **data, ReviewClassKey.CLASSES: classes }


def _to_planner_entry(entry: dict) -> dict:
  """
  Build the migrated planner entry for one `dev-plan` `experts.main` record.

  Args:
    entry: One `experts.main` entry dict, verbatim from the `dev-plan` class.

  Returns:
    A new dict with `name` rewritten to the planner expert; every sibling key in the entry is
    preserved.
  """
  return { **entry, _NAME_KEY: _PLANNER_EXPERT_NAME }


def _rewrite_dev_plan_main(classes: list[dict]) -> list[dict]:
  """
  Rewrite the `dev-plan` class's `experts.main` to the planner expert.

  Args:
    classes: The `review.classes` list, verbatim from the settings section.

  Returns:
    A new list with the `dev-plan` entry's `experts.main` rewritten when it still equals the
    `lazy-spec.product-config`-seeded default (`claude-plugin.implementer`). Every other entry is
    passed through unchanged, as is a `dev-plan` entry whose `main` has already diverged from
    that default (an operator customization, or a previous run of this same migration).
  """
  result = []
  for entry in classes:
    # not the dev-plan entry — pass through untouched
    if entry.get(ReviewClassKey.CLASS) != ReviewClassName.DEV_PLAN:
      result.append(entry)
      continue

    # main has already diverged from the seeded default — operator customization or already migrated
    experts = entry.get(ReviewClassKey.EXPERTS, {})
    current_main = experts.get(_MAIN_KEY, [])
    if current_main != _DEV_PLAN_SEEDED_DEFAULT_MAIN:
      result.append(entry)
      continue

    # main still matches the seeded default — rewrite it to the planner expert
    new_experts = { **experts, _MAIN_KEY: [ _to_planner_entry(main_entry) for main_entry in current_main ] }
    result.append({ **entry, ReviewClassKey.EXPERTS: new_experts })
  return result


def _add_report_class(classes: list[dict], name: str, *, path: str, main_name: str) -> list[dict]:
  """
  Add a report review class, when missing.

  Args:
    classes: The `review.classes` list, already past the `dev-plan` main rewrite.
    name: The report class's name (`dev-report` or `test-report`).
    path: The single glob path routing a document to this class.
    main_name: The expert name for the class's `experts.main[0]`.

  Returns:
    The list with the report class appended, or unchanged when one by that name already exists
    — an operator-added or previously-migrated class is never overwritten.
  """
  # guard: this report class already exists — nothing to add
  if any(entry.get(ReviewClassKey.CLASS) == name for entry in classes):
    return classes

  # a fresh class mirrors its dev-plan/test-plan siblings' shape: one main writer, one historian
  report_class = {
    ReviewClassKey.CLASS: name,
    ReviewClassKey.PATHS: [ path ],
    ReviewClassKey.EXPERTS: {
      _MAIN_KEY: [ { _NAME_KEY: main_name } ],
      _HISTORY_KEY: { _NAME_KEY: _HISTORIAN_EXPERT_NAME },
    },
  }
  return [ *classes, report_class ]


def _migrate_planner_and_reports(data: dict) -> dict:
  """
  Apply the v3 → v4 `dev-plan` planner rewrite plus `dev-report` / `test-report` class addition.

  Args:
    data: The `review` section content at v3.

  Returns:
    The section content with `classes` migrated; all other keys preserved.
  """
  classes = _rewrite_dev_plan_main(data.get(ReviewClassKey.CLASSES, []))
  classes = _add_report_class(
      classes, ReviewClassName.DEV_REPORT, path = _DEV_REPORT_PATH, main_name = _IMPLEMENTER_EXPERT_NAME,
  )
  classes = _add_report_class(
      classes, ReviewClassName.TEST_REPORT, path = _TEST_REPORT_PATH, main_name = _TESTER_EXPERT_NAME,
  )
  return { **data, ReviewClassKey.CLASSES: classes }


def _add_context_from_frontmatter(classes: list[dict], name: str) -> list[dict]:
  """
  Add `context_from_frontmatter: ["spec_source_requests"]` to a review class, when absent.

  Args:
    classes: The `review.classes` list, verbatim from the settings section.
    name: The class name to add the key to (`design` or `bug`).

  Returns:
    A new list with the named class's `context_from_frontmatter` key set to
    `["spec_source_requests"]` when the class exists and does not already declare the key. Every
    other entry — and a class that already declares the key (an operator customization, or a
    previous run) — is passed through unchanged.
  """
  result = []
  for entry in classes:
    # not the named class, or it already declares the key — pass through untouched
    if entry.get(ReviewClassKey.CLASS) != name or _CONTEXT_FROM_FRONTMATTER_KEY in entry:
      result.append(entry)
      continue
    result.append({ **entry, _CONTEXT_FROM_FRONTMATTER_KEY: [ _SPEC_SOURCE_REQUESTS_KEY ] })
  return result


def _migrate_context_from_frontmatter(data: dict) -> dict:
  """
  Apply the v4 → v5 `context_from_frontmatter` seed on the `design` and `bug` classes.

  Args:
    data: The `review` section content at v4.

  Returns:
    The section content with `classes` migrated; all other keys preserved.
  """
  classes = data.get(ReviewClassKey.CLASSES, [])
  classes = _add_context_from_frontmatter(classes, ReviewClassName.DESIGN)
  classes = _add_context_from_frontmatter(classes, ReviewClassName.BUG)
  return { **data, ReviewClassKey.CLASSES: classes }


def _rewrite_terminal_routing(classes: list[dict]) -> list[dict]:
  """
  Rewrite `experts.terminal.routing.name` from the retired router to the coordinator.

  Args:
    classes: The `review.classes` list, verbatim from the settings section.

  Returns:
    A new list with any entry's `experts.terminal.routing.name` rewritten from
    `spec.request-router` to `spec.coordinator` when it still equals the retired
    agent's name. Every other entry — and a `terminal.routing.name` that has already
    diverged (an operator customization, or a previous run of this migration) — is
    passed through unchanged.
  """
  result = []
  for entry in classes:
    # resolve the routing writer this entry declares, if any
    experts = entry.get(ReviewClassKey.EXPERTS, {})
    terminal = experts.get(_TERMINAL_KEY, {})
    routing = terminal.get(_ROUTING_KEY, {})

    # routing writer doesn't name the retired router — operator customization, already
    # migrated, or no terminal.routing block at all
    if routing.get(_NAME_KEY) != _ROUTER_EXPERT_NAME:
      result.append(entry)
      continue

    # rewrite only the routing writer's name; every sibling key (section, position) is preserved
    new_routing = { **routing, _NAME_KEY: _COORDINATOR_EXPERT_NAME }
    new_terminal = { **terminal, _ROUTING_KEY: new_routing }
    new_experts = { **experts, _TERMINAL_KEY: new_terminal }
    result.append({ **entry, ReviewClassKey.EXPERTS: new_experts })
  return result


def _migrate_routing_to_coordinator(data: dict) -> dict:
  """
  Apply the v5 → v6 `terminal.routing.name` rename to `spec.coordinator`.

  Args:
    data: The `review` section content at v5.

  Returns:
    The section content with `classes` migrated; all other keys preserved.
  """
  # waiver: single local mirrors the sibling _migrate_* functions' shape in this file
  # (_migrate_test_plan_main_to_tester, _migrate_planner_and_reports, _migrate_context_from_frontmatter)
  classes = _rewrite_terminal_routing(data.get(ReviewClassKey.CLASSES, []))
  return { **data, ReviewClassKey.CLASSES: classes }


def _build_planner_review_entry() -> dict:
  """
  Build the `planner_review` validation-slot entry the v6 → v7 migration seeds.

  Returns:
    A fresh `{name, section, position}` writer dict naming the planner expert, matching the
    shape `design`'s existing `developer_review` / `tester_review` slots already use.
  """
  return {
    _NAME_KEY: _PLANNER_EXPERT_NAME,
    _SECTION_KEY: _PLANNER_REVIEW_SECTION,
    _POSITION_KEY: _PLANNER_REVIEW_POSITION,
  }


def _add_architecture_class(classes: list[dict]) -> list[dict]:
  """
  Add the `architecture` review class, when missing.

  Args:
    classes: The `review.classes` list, verbatim from the settings section.

  Returns:
    The list with an `architecture` class appended — main writer the architect expert, one
    `planner_review` validation slot — or unchanged when a class by that name already exists
    (an operator-added or previously-migrated class is never overwritten).
  """
  # guard: this class already exists — nothing to add
  if any(entry.get(ReviewClassKey.CLASS) == ReviewClassName.ARCHITECTURE for entry in classes):
    return classes

  # a fresh class: one main writer (the architect), one planner-review validation slot
  architecture_class = {
    ReviewClassKey.CLASS: ReviewClassName.ARCHITECTURE,
    ReviewClassKey.PATHS: [ _ARCHITECTURE_PATH ],
    ReviewClassKey.EXPERTS: {
      _MAIN_KEY: [ { _NAME_KEY: _ARCHITECT_EXPERT_NAME } ],
      _VALIDATION_KEY: { _PLANNER_REVIEW_KEY: _build_planner_review_entry() },
    },
  }
  return [ *classes, architecture_class ]


def _add_planner_review_to_design(classes: list[dict]) -> list[dict]:
  """
  Add the `planner_review` validation slot to the `design` class, when absent.

  Args:
    classes: The `review.classes` list, already past the `architecture` class addition.

  Returns:
    A new list with the `design` entry's `experts.validation.planner_review` set when the class
    exists and its `validation` block does not already declare the key. Every other entry — and
    a `design` class that already declares the key (an operator customization, or a previous run
    of this migration) — is passed through unchanged.
  """
  result = []
  for entry in classes:
    # not the design entry — pass through untouched
    if entry.get(ReviewClassKey.CLASS) != ReviewClassName.DESIGN:
      result.append(entry)
      continue

    # already declares the slot — operator customization or already migrated
    experts = entry.get(ReviewClassKey.EXPERTS, {})
    validation = experts.get(_VALIDATION_KEY, {})
    if _PLANNER_REVIEW_KEY in validation:
      result.append(entry)
      continue

    # slot absent — add it, preserving every sibling validation entry already on the class
    new_validation = { **validation, _PLANNER_REVIEW_KEY: _build_planner_review_entry() }
    new_experts = { **experts, _VALIDATION_KEY: new_validation }
    result.append({ **entry, ReviewClassKey.EXPERTS: new_experts })
  return result


def _migrate_architecture_and_planner(data: dict) -> dict:
  """
  Apply the v6 → v7 `architecture` class addition plus `design`'s `planner_review` slot.

  Args:
    data: The `review` section content at v6.

  Returns:
    The section content with `classes` migrated; all other keys preserved.
  """
  classes = _add_architecture_class(data.get(ReviewClassKey.CLASSES, []))
  classes = _add_planner_review_to_design(classes)
  return { **data, ReviewClassKey.CLASSES: classes }


def _migrate_spec_protocol_refs(data: dict) -> dict:
  """
  Move every class's lazycortex-specs protocol reference onto the plugin's own namespace.

  Args:
    data: The `review` section content.

  Returns:
    The section content with each `classes[].protocols[]` member naming a lazycortex-specs
    protocol re-prefixed; protocols from other plugins and every other key are preserved.
  """
  # a class without a protocol list, and a protocol from another plugin, both pass through
  classes = [
    { **c, _PROTOCOLS_KEY: [
      _SPEC_PROTOCOL_NEW_PREFIX + p[len(_SPEC_PROTOCOL_OLD_PREFIX):]
      if isinstance(p, str) and p.startswith(_SPEC_PROTOCOL_OLD_PREFIX) else p
      for p in c[_PROTOCOLS_KEY]
    ] }
    if isinstance(c, dict) and isinstance(c.get(_PROTOCOLS_KEY), list) else c
    for c in data.get(ReviewClassKey.CLASSES, [])
  ]
  return { **data, ReviewClassKey.CLASSES: classes }


def _rewrite_path_suffix(path: str) -> str:
  """
  Rewrite one path glob's retired filename suffix to the renamed type's, when it carries one.

  Args:
    path: One `paths[]` member, verbatim from a class entry.

  Returns:
    The glob with its `/dev-plan.md` / `/dev-report.md` suffix rewritten, or unchanged when it
    ends in neither.
  """
  # rewrite at most the one suffix a glob can end with
  for old, new in _PATH_SUFFIX_RENAMES.items():
    if path.endswith(old):
      return path[: -len(old)] + new
  return path


def _to_code_entry(entry: dict) -> dict:
  """
  Build the v9 form of one class entry.

  The class token is renamed when its base names a retired type (the `@<product>` qualifier is
  kept), every path glob's retired filename suffix is rewritten, and an `experts.history` block
  naming the retired historian expert is dropped; a history block naming any other expert is
  preserved verbatim.

  Args:
    entry: One class dict, verbatim from `review.classes`.

  Returns:
    A new dict in the v9 shape; every key the migration has no business with is preserved.
  """
  result = dict(entry)

  # rename the class token when its base is a retired name, keeping the product qualifier
  base, sep, product = (entry.get(ReviewClassKey.CLASS) or "").partition(_CLASS_PRODUCT_SEP)
  if base in _CODE_CLASS_RENAMES:
    result[ReviewClassKey.CLASS] = f"{_CODE_CLASS_RENAMES[base]}{sep}{product}"

  # rewrite stale path globs on EVERY entry — a class renamed elsewhere still carries them
  paths = entry.get(ReviewClassKey.PATHS)
  if isinstance(paths, list):
    result[ReviewClassKey.PATHS] = [
      _rewrite_path_suffix(p) if isinstance(p, str) else p for p in paths
    ]

  # drop a history block naming the retired historian; any other name — or a hand-edited
  # non-dict value — is preserved verbatim as an operator's choice
  experts = entry.get(ReviewClassKey.EXPERTS)
  if isinstance(experts, dict) and isinstance(experts.get(_HISTORY_KEY), dict) \
      and experts[_HISTORY_KEY].get(_NAME_KEY) == _HISTORIAN_EXPERT_NAME:
    result[ReviewClassKey.EXPERTS] = { k: v for k, v in experts.items() if k != _HISTORY_KEY }

  # the entry in its v9 shape
  return result


def _migrate_code_classes(data: dict) -> dict:
  """
  Apply the v8 → v9 `dev-plan`/`dev-report` → `code-plan`/`code-report` rename plus historian drop.

  Args:
    data: The `review` section content at v8.

  Returns:
    The section content with `classes` migrated; all other keys preserved.
  """
  # rebuild every class entry in its v9 shape; anything that is not a dict passes through
  # waiver: single local mirrors the sibling _migrate_* functions' shape in this file
  classes = [ _to_code_entry(e) if isinstance(e, dict) else e for e in data.get(ReviewClassKey.CLASSES, []) ]
  return { **data, ReviewClassKey.CLASSES: classes }


MIGRATIONS = {
  1: _migrate_plan_classes,
  2: _migrate_test_plan_main_to_tester,
  3: _migrate_planner_and_reports,
  4: _migrate_context_from_frontmatter,
  5: _migrate_routing_to_coordinator,
  6: _migrate_architecture_and_planner,
  7: _migrate_spec_protocol_refs,
  8: _migrate_code_classes,
}
