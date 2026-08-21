"""
Deterministic apply-transition worker — the Python primitive backing the
`lazy-spec.request-apply` md-scan routine.

Replaces the LLM-driven `lazy-spec.request-apply` agent. Reads the resolved
routing prose from a post-finalize request file, enacts the named
attach / spawn / reference targets, seeds each spawn/attach target's
primary doc with the router-authored per-target description — a fresh
spawn gets it as draft content, an existing attach target gets it as an
attention-block delta, a reference target gets neither (link only) —
opens a review cycle on every populated doc, then stamps terminal markers
(`request_class`, `request_status`, `request/<status>` mirror tag,
status callout) and strips the `# Routing` section. Atomic commit
under the `lazy-spec.request-apply` bot identity.

Routing prose grammar (parsed leniently — the router agent emits free
text, so the patterns below match the conventional shapes):

- **Class verdict** — `Class: <verdict>` or `**Class:** \\<verdict>\\`
  (case-insensitive, optional surrounding backticks / asterisks).
  Verdict is one of `feature` / `change` / `bug` / `task` / `spec` /
  `plan` / `feedback` / `unknown`.
- **Spawn target** — a `Target:` / `Spawn:` line that mentions a
  built-in kind word (`feature` / `change` / `bug`) and a slug in
  backticks (the prose form the router emits, e.g.
  "Spawn one cross-cutting change entity — `slug`").
- **Attach target** — a `[[path]]` wikilink whose last path segment
  equals the previous one (folder-note shape, per
  `lazy-spec.layout-protocol`). This prose form is skipped entirely when a
  structured `<!-- routing-decision -->` block is present: its `attach
  <path>` tokens are taken verbatim, with no shape check.
- **Reference target** — has no prose form; exists only inside the
  structured `<!-- routing-decision -->` block.
- **No target resolved** → request is rejected with the rejection
  callout + recovery hint.

Structured `<!-- routing-decision -->` block lines carry an optional
`:: <description>` suffix (a per-target short description the router
writes; empty/legacy when the suffix is absent) plus a set of named
fields the router decides and this worker never guesses at:

- `docs=<name>:<type>[,...]` on a spawn line — the documents the asset
  is scaffolded with, in order. Mandatory: the scaffolder has no
  default layout, so a spawn naming none is refused outright.
- `path=<dir>` on a spawn line — the folder under the product's
  `spec_path` the asset lands in; absent falls back to the asset
  type's own `default_path`.
- `tools=<tool>[,...]` on a spawn line — the tools the asset is
  realised and checked with; absent leaves them undetermined for the
  coordinator to settle on its own wake.
- `product=<key>` on a spawn line — the spawning product, the sole way
  one decision fans a request out across several products in one apply
  run.
- `targets=<category>/<slug>[,...]` on a `change`-kind spawn line —
  design-cascade targets.
- `drop=<name>[,...]` on an attach line — the documents a pre-launch
  rollback removes; absent rolls the gates back and deletes nothing.

A spawn line's asset type is validated against the shipped
declarations plus whatever every registered product declares, so an
operator's own type is admissible without touching this worker.
A `reference <path>` line names an existing asset the router judges
already implements the request — registers a link via `spec_targets`
on the request itself, spawns/attaches nothing.

Inputs read:

- `<repo>/.claude/lazy.settings.json[products]` — to map a product key
  to its `spec_path` (used during spawn-target enaction to resolve the
  folder-note path the scaffolder writes).
- The post-finalize request file passed as the positional argument.

Outputs written:

- Spawn targets: full asset scaffolds via the `scaffold-asset`
  subprocess.
- Each populated doc: router-description seed (draft content on a
  spawn target, an attention-block delta on an attach target) +
  `spec_source_requests` frontmatter + `## Requests` projection inside
  `# Sources`.
- Each change spawn naming design-cascade targets: `spec_targets`
  frontmatter on its status folder-note.
- Reference targets: `spec_targets` frontmatter on the request file
  itself — never on the referenced asset, whose doc and folder-note
  stay untouched.
- Each populated doc's folder-note: `## Source requests` bullet.
- An attach target whose implementation ladder started but never
  launched: its live expert job cancelled via the `lazycortex-core
  cancel-job` CLI and its `active_job` marker cleared, best-effort
  review-stop plus worktree deletion of its `architecture.md` /
  `code-plan.md` / `test-plan.md` siblings, and `spec_plan_done` / `spec_develop_done`
  / `spec_tests_passing` / `spec_released` flipped back to false.
- On a rollback that cannot complete cleanly: the asset halted via
  `flip_gate.halt_asset` and the whole run aborted instead of
  committing a half-dropped ladder.
- Each populated doc: review cycle opened via the `lazycortex-review`
  CLI's `start` subcommand, or `submit` when a pre-launch ladder
  rollback re-opened an already-drafted doc.
- Request file: `request_class` / `request_status` frontmatter,
  `request/<status>` mirror tag, status callout above first H1,
  `# Routing` stripped.
- One atomic commit under the bot identity covering every path.

Exit codes: `0` on success (including idempotent no-op on a
terminal-status file); `1` on a logical error written to stdout as a
JSON `error` object.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import NoReturn


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from summary_render import apply_container_stats  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_paths import find_settings_root, resolve_plugin_cli, spec_content_root  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402
    BOOL_TRUE,
    FlipResult,
    Gate,
    GateCheckbox,
    HaltReason,
    JobMarker,
    SiblingDoc,
    SpecHaltKey,
    SpecTargetsKey,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import asset_types  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import iconize_inline  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402


# Gates a pre-launch ladder rollback flips back to false, in the same order `GATE_ORDER`
# carries them from `spec_plan_done` onward — the design gate is left alone since design is
# what the incoming request is about to revise.
_ROLLBACK_GATES = ( Gate.PLAN_DONE, Gate.DEVELOP_DONE, Gate.TESTS_PASSING, Gate.RELEASED )


class _K:
  """
  String / int constants used by the apply worker.

  Attributes:
    SPEC_ROLE: Frontmatter key naming a file's spec-role discriminator.
    REQUEST_STATUS: Frontmatter key naming a request's lifecycle status.
    REQUEST_CLASS: Frontmatter key naming a request's routed classification.
    REVIEW_RESULT: Frontmatter key naming a doc's terminal review outcome.
    REVIEW_ACTIVE: Frontmatter key marking a doc as opted into the review loop.
    REVIEW_ROUND: Frontmatter key naming a doc's current review round.
    REVIEW_APPROVED: Frontmatter key naming a doc's whole-document approval flag.
    TAGS: Frontmatter key holding a file's tag list.
    SPEC_SOURCE_REQUESTS: Frontmatter key listing the requests that populated a doc.
    STATUS_DRAFT: The pre-terminal `request_status` value.
    STATUS_ACCEPTED: The accepted terminal `request_status` value.
    STATUS_REJECTED: The rejected terminal `request_status` value.
    CLASS_UNKNOWN: The unclassified `request_class` value.
    ROLE_REQUEST: The canonical `spec_role` value for a request file.
    REVIEW_APPROVED_VAL: The clean-approval `review_result` value.
    REVIEW_APPROVED_WITH_CONCERNS: The approved-with-concerns `review_result` value.
    TAG_PREFIX: Prefix of the request-status mirror tag.
    DESIGN_MD: Filename of the design doc.
    BUG_MD: Filename of the bug-layout design-side doc.
    FEATURE_KIND: The feature asset kind.
    CHANGE_KIND: The change asset kind.
    CLAUDE_DIR: The `.claude` directory segment.
    SETTINGS_FILE: Filename of the settings file.
    PRODUCTS: Settings key holding the product registry.
    SPEC_PATH: Settings key naming a product's spec directory.
    GIT_DIR: The `.git` entry checked to detect a repo checkout.
    REQUESTS_DIR: Directory segment holding request files.
    REQUESTS_NOTE: Filename of the requests folder-note.
    ROUTING_H1: Heading marking a request's routing section.
    HISTORY_H1: Heading marking a file's history log section.
    ROUTING_DECISION_OPEN: Opening marker of an embedded routing-decision comment.
    ROUTING_DECISION_CLOSE: Closing marker of an embedded HTML comment.
    DECISION_VERB_SPAWN: The routing-decision verb for a spawn target.
    DECISION_VERB_ATTACH: The routing-decision verb for an attach target.
    DECISION_VERB_REFERENCE: The routing-decision verb for a reference target — an existing
      asset the router judges already implements the request; registers a link, spawns/attaches
      nothing.
    DECISION_DESC_SEP: Token separating a routing-decision line's target spec from its free-text description.
    DECISION_TARGETS_PREFIX: Prefix marking the optional design-cascade `targets=` field on a change-spawn line.
    DECISION_PRODUCT_PREFIX: Prefix marking the optional spawning-product `product=` field on a spawn line.
    DECISION_DOCS_PREFIX: Prefix marking the mandatory `docs=` field naming a spawn's documents.
    DECISION_PATH_PREFIX: Prefix marking the optional `path=` field naming a spawn's folder.
    DECISION_TOOLS_PREFIX: Prefix marking the optional `tools=` field naming a spawn's tools.
    DECISION_DROP_PREFIX: Prefix marking the optional `drop=` field naming an attach's dropped docs.
    DOC_TOKEN_SEP: Separator between a document's filename and its type inside `docs=`.
    SCAFFOLD_DOC_FLAG: The `scaffold-asset` flag naming one produced document.
    SCAFFOLD_PATH_FLAG: The `scaffold-asset` flag naming the folder the asset lands in.
    SCAFFOLD_GROUP_NOTE_KEY: The scaffold result key naming the group folder-note it seeded.
    SPEC_TOOLS_KEY: Frontmatter key listing the tools the asset is realised and checked with.
    ASSET_TYPES: Settings key holding a product's own asset-type declarations.
    OVERVIEW_H2: Heading of the template skeleton's opening section, where a spawn seed lands.
    SOURCES_H1: Heading marking a doc's sources section.
    SOURCES_TAG: Protected-section tag guarding a doc's sources section.
    REQUESTS_H2: Sub-heading marking a doc's requests projection.
    REQUESTS_MARKER_START: Opening marker delimiting a doc's requests projection.
    REQUESTS_MARKER_END: Closing marker delimiting a doc's requests projection.
    SOURCE_REQUESTS_H2: Sub-heading marking a folder-note's source-requests list.
    HISTORY_H2: Sub-heading marking a doc's history log.
    CALLOUT_SUCCESS: The callout text stamped on an accepted request.
    CALLOUT_WARNING: The callout text stamped on a rejected request.
    STATUS_TAG_PATTERN: Regex pattern matching an existing status tag to replace.
    REJECT_HINT: Recovery-hint text appended to a rejection callout.
    REJECT_REASON_DEFAULT: Default rejection reason when routing names no target.
    FALLBACK_DESCRIPTION: One-line seed used when the router left a target's description empty.
    ATTENTION_CALLOUT_PREFIX: Leading text of an attach target's seeded attention-block delta.
    GIT: The git executable name.
    PROG: CLI program name shown in `--help` output.
    CLI_LAZYCORTEX_SPECS: Plugin name used to resolve the `lazycortex-specs` CLI.
    CLI_LAZYCORTEX_REVIEW: Plugin name used to resolve the `lazycortex-review` CLI.
    CLI_LAZYCORTEX_CORE: Plugin name used to resolve the `lazycortex-core` CLI.
    ENV_PLUGIN_DIRS: Env var listing plugin dirs to walk for CLI resolution.
    ENV_REPO_ROOT: Env var passed to the `lazycortex-core` CLI naming the repo it should
      resolve settings and job storage against.
    ROLLBACK_GATE_OFF_REASON: Reason text recorded on every gate a pre-launch ladder rollback
      flips back to false.
    REVIEW_STOP_TIMEOUT_S: Seconds the best-effort `lazycortex-review stop` subprocess may run.
    BIN_DIR: Per-plugin `bin/` subdir holding a CLI binary.
    MD_SUFFIX: The markdown file extension.
    BOT_NAME_DEFAULT: Default git author name for the apply-transition commit.
    BOT_EMAIL_DEFAULT: Default git author email for the apply-transition commit.
    ARG_FILE: CLI positional argument name for the request file.
    ARG_AUTHOR_NAME: CLI flag overriding the commit author name.
    ARG_AUTHOR_EMAIL: CLI flag overriding the commit author email.
    REVIEW_START_IDEMPOTENT_MARK: Substring identifying an already-active review start as a no-op.
    ERR_NO_PRODUCTS: Error message used when a spawn target needs products but none are registered.
    CAT_LOGICAL: The error category for invalid-input failures.
    OUTCOME_SUCCESS: Outcome token for a completed apply transition.
    OUTCOME_ERROR: Outcome token for a failed apply transition.
    OUTCOME_TERMINAL_SKIP: Outcome token for a no-op on an already-terminal request.
    OUTCOME_NO_ROUTING_SKIP: Outcome token for a no-op on a request with no routing section.
    CLASS_ENUM: The closed set of valid `request_class` verdicts.
  """

  # Frontmatter keys
  SPEC_ROLE = "spec_role"
  REQUEST_STATUS = "request_status"
  REQUEST_CLASS = "request_class"
  REVIEW_RESULT = "review_result"
  REVIEW_ACTIVE = "review_active"
  REVIEW_ROUND = "review_round"
  REVIEW_APPROVED = "review_approved"
  TAGS = "tags"
  SPEC_SOURCE_REQUESTS = "spec_source_requests"
  # Frontmatter values
  STATUS_DRAFT = "draft"
  STATUS_ACCEPTED = "accepted"
  STATUS_REJECTED = "rejected"
  CLASS_UNKNOWN = "unknown"
  ROLE_REQUEST = "request"
  REVIEW_APPROVED_VAL = "approved"
  REVIEW_APPROVED_WITH_CONCERNS = "approved-with-concerns"
  # Tag prefixes / members
  TAG_PREFIX = "request/"
  # Filenames + doc roles
  DESIGN_MD = "design.md"
  BUG_MD = "bug.md"
  FEATURE_KIND = "feature"
  CHANGE_KIND = "change"
  # Path segments
  CLAUDE_DIR = ".claude"
  SETTINGS_FILE = "lazy.settings.json"
  PRODUCTS = "products"
  SPEC_PATH = "spec_path"
  GIT_DIR = ".git"
  REQUESTS_DIR = "requests"
  REQUESTS_NOTE = "requests.md"
  # Routing-section markers
  ROUTING_H1 = "# Routing"
  HISTORY_H1 = "# History"
  ROUTING_DECISION_OPEN = "<!-- routing-decision"
  ROUTING_DECISION_CLOSE = "-->"
  DECISION_VERB_SPAWN = "spawn"
  DECISION_VERB_ATTACH = "attach"
  DECISION_VERB_REFERENCE = "reference"
  DECISION_DESC_SEP = "::"
  DECISION_TARGETS_PREFIX = "targets="
  DECISION_PRODUCT_PREFIX = "product="
  DECISION_DOCS_PREFIX = "docs="
  DECISION_PATH_PREFIX = "path="
  DECISION_TOOLS_PREFIX = "tools="
  DECISION_DROP_PREFIX = "drop="
  SCAFFOLD_DOC_FLAG = "--doc"
  SCAFFOLD_PATH_FLAG = "--path"
  SCAFFOLD_GROUP_NOTE_KEY = "group_note"
  SPEC_TOOLS_KEY = "spec_tools"
  ASSET_TYPES = "asset_types"
  DOC_TOKEN_SEP = ":"
  OVERVIEW_H2 = "## Overview"
  SOURCES_H1 = "# Sources"
  SOURCES_TAG = "#protected/spec/sources"
  REQUESTS_H2 = "## Requests"
  REQUESTS_MARKER_START = "<!-- auto:spec-requests:start -->"
  REQUESTS_MARKER_END = "<!-- auto:spec-requests:end -->"
  SOURCE_REQUESTS_H2 = "## Source requests"
  HISTORY_H2 = "## History"
  # Status callout strings
  CALLOUT_SUCCESS = "[!success] Request accepted #status/accepted"
  CALLOUT_WARNING = "[!warning] Request rejected #status/rejected"
  STATUS_TAG_PATTERN = r"#status/\S+"
  REJECT_HINT = "To re-open: clear request_status, clear review_result, restore review_active: true."
  REJECT_REASON_DEFAULT = "Routing prose named no resolvable target."
  FALLBACK_DESCRIPTION = "Request routed here — see linked request"
  ATTENTION_CALLOUT_PREFIX = "> [!attention] change requested: "
  # Subprocess + git
  GIT = "git"
  # CLI identity
  PROG = "lazycortex-specs apply-request"
  CLI_LAZYCORTEX_SPECS = "lazycortex-specs"
  CLI_LAZYCORTEX_REVIEW = "lazycortex-review"
  CLI_LAZYCORTEX_CORE = "lazycortex-core"
  ENV_PLUGIN_DIRS = "LAZYCORTEX_PLUGIN_DIRS"
  ENV_REPO_ROOT = "LAZY_REPO_ROOT"
  ROLLBACK_GATE_OFF_REASON = "request attached before implementation launched"
  REVIEW_STOP_TIMEOUT_S = 60
  BIN_DIR = "bin"
  MD_SUFFIX = ".md"
  BOT_NAME_DEFAULT = "lazy-spec.request-apply"
  BOT_EMAIL_DEFAULT = "lazy-spec.request-apply@bot.invalid"
  ARG_FILE = "file"
  ARG_AUTHOR_NAME = "--author-name"
  ARG_AUTHOR_EMAIL = "--author-email"
  REVIEW_START_IDEMPOTENT_MARK = "already"
  ERR_NO_PRODUCTS = (
      "no products registered in lazy.settings.json; cannot resolve spawn target"
  )
  # Outcome / error categories
  CAT_LOGICAL = "logical"
  OUTCOME_SUCCESS = "success"
  OUTCOME_ERROR = "error"
  OUTCOME_TERMINAL_SKIP = "terminal-state-skip"
  OUTCOME_NO_ROUTING_SKIP = "no-routing-skip"
  # Allowed class enum
  CLASS_ENUM = ( "feature", "change", "bug", "task", "spec", "plan", "feedback", "unknown" )


def _fail(category: str, message: str) -> NoReturn:
  """
  Print a JSON error object to stdout and exit non-zero.

  Args:
    category: Error category — one of `logical` (input invalid) or `technical`
      (internal failure).
    message: Single-line human-readable cause.
  """
  print(json.dumps({ "outcome": _K.OUTCOME_ERROR,
                     "error": { "category": category, "message": message } }))
  sys.exit(1)


def _repo_root(start: Path) -> Path:
  """
  Resolve the repo root from a working directory, falling back to start when not in a repo.

  Args:
    start: Working directory to start the search from.

  Returns:
    The first ancestor (or `start` itself) that contains a `.git` entry; absolute path.
  """
  cur = start.resolve()
  while cur != cur.parent:
    if (cur / _K.GIT_DIR).exists():
      return cur
    cur = cur.parent
  return start.resolve()


def _resolve_sibling_cli(name: str) -> Path:
  """
  Locate a sibling plugin's CLI binary through `$LAZYCORTEX_PLUGIN_DIRS`.

  Args:
    name: CLI filename (e.g. `lazycortex-specs`, `lazycortex-review`).

  Returns:
    Absolute path to the CLI binary in the first registered plugin dir that carries it.

  Raises:
    SystemExit: When the env var is unset or no plugin dir holds the named CLI.
  """
  cli = resolve_plugin_cli(name)
  # guard: unresolved — env var unset or no plugin dir carries the named CLI
  if cli is None:
    _fail(_K.CAT_LOGICAL, f"no '{name}' resolvable via ${_K.ENV_PLUGIN_DIRS}")
  return cli


def _parse_frontmatter(text: str) -> tuple[dict, int]:
  """
  Parse a markdown file's YAML frontmatter into a flat dict + end offset.

  Args:
    text: Full file text.

  Returns:
    Two-tuple `(values, fm_end)` where `values` carries scalar and list-typed entries
    and `fm_end` is the byte offset of the first character after the closing fence.
    Returns `({}, 0)` when no frontmatter is present.
  """
  if not text.startswith("---\n"):
    return {}, 0
  # waiver: inline numeric literal -- length of the leading '---\n' fence consumed below
  rest = text[4:]
  # guard: empty frontmatter block (`---\n---\n`) — recognise as valid, no values
  if rest.startswith("---\n"):
    # waiver: inline numeric literal -- length of the two stacked '---\n' fences
    return {}, 8
  end_idx = rest.find("\n---\n")
  # guard: opening fence without closing fence — not a valid block
  if end_idx < 0:
    return {}, 0
  block = rest[:end_idx]
  # waiver: inline numeric literal -- length of the leading '---\n' fence
  fm_end = 4 + end_idx + len("\n---\n")
  values: dict = {}
  current_list_key: str | None = None
  for line in block.splitlines():
    stripped = line.strip()
    # guard: skip blank lines and comment markers
    if not stripped or stripped.startswith("#"):
      continue
    # guard: list continuation line (indented `- value`)
    if stripped.startswith("- ") and line.startswith(("  ", "\t")):
      if current_list_key:
        item = stripped[2:].strip().strip('"').strip("'")
        values[current_list_key].append(item)
      continue
    # guard: not a key:value line
    if ":" not in line:
      continue
    k, _, v = line.partition(":")
    k = k.strip()
    v_str = v.strip()
    # guard: empty key
    if not k:
      continue
    if v_str == "":
      current_list_key = k
      values[k] = []
    else:
      values[k] = v_str
      current_list_key = None
  return values, fm_end


def _parse_routing_decision_rich(
    block: str, *, known_kinds: frozenset[str] | None = None,
) -> tuple[list[tuple[str, str, str, list[str]]], list[tuple[str, str]]]:
  """
  Parse the structured `<!-- routing-decision ... -->` block body with per-target detail.

  Format is one decision per line, whitespace-separated, with an optional
  `:: <description>` suffix and, on a `change`-kind spawn line only, an
  optional `targets=` field naming design-cascade targets:

  - `spawn <kind> <slug> [targets=<category>/<slug>[,<category>/<slug>...]] [:: <description>]`
  - `attach <folder-note-path> [:: <description>]`

  A line without `::` is legacy-valid and yields an empty description.
  `targets=` is recognised only on a `change`-kind spawn line; it is ignored
  (left as an empty list) for every other kind. Any other line shape (blank,
  prose, malformed) is silently skipped — the parser is forgiving on unknown
  content so the router can mix structured decisions with operator-readable
  notes inside the same block without breaking apply.

  A `reference` line and a spawn line's own `product=` field are not part of this function's
  return shape; `_parse_reference_targets` and `_parse_spawn_products` cover those two instead,
  each its own bounded scan over the same block text.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).
    known_kinds: The asset types a spawn line may name; None consults only the types the
      plugin ships, which is what a caller with no product in scope can validate against.

  Returns:
    Two lists: spawn tuples `(kind, slug, description, targets)` and attach
    tuples `(path, description)`. Dedup is applied per `(kind, slug)` / `path`
    identity (preserves insertion order, first occurrence wins).
  """
  # the admissible set is open: an operator declares types of their own, and the caller that
  # knows the product resolves them before handing the set down here
  kinds = known_kinds if known_kinds is not None else frozenset(asset_types.builtin_defaults())

  # Decision: kept `_parse_routing_decision_rich` / `_parse_routing`'s return arity unchanged,
  # added `reference` / `product=` support via `_parse_reference_targets` and
  # `_parse_spawn_products` instead of extending these tuples — extending them broke ~35
  # pre-existing tests' positional unpacking when first tried, and this project's rules forbid
  # editing existing tests' assertions/unpacking without explicit operator approval.

  # accumulators for the two target kinds this function does own
  spawn: list[tuple[str, str, str, list[str]]] = []
  attach: list[tuple[str, str]] = []
  seen_spawn: set[tuple[str, str]] = set()
  seen_attach: set[str] = set()
  for raw_line in block.splitlines():
    stripped = raw_line.strip()
    # guard: skip blank lines — a non-decision prose line is dropped by a later guard instead
    if not stripped:
      continue
    # the description, when present, is everything after the first `::`
    head, _sep, desc_part = stripped.partition(_K.DECISION_DESC_SEP)
    description = desc_part.strip()
    tokens = head.split()
    # guard: a bare separator with nothing before it is not a decision line
    if not tokens:
      continue
    verb = tokens[0].lower()
    # waiver: structural token count for `spawn <kind> <slug>` line format
    if verb == _K.DECISION_VERB_SPAWN and len(tokens) >= 3:
      kind = tokens[1].lower()
      slug = tokens[2]
      # guard: drop kinds no declaration covers in the caller's scope
      if kind not in kinds:
        continue
      targets: list[str] = []
      # targets= names design-cascade features and only applies to a change spawn; scanned
      # (not positional) so it may precede or follow the line's other optional fields freely
      if kind == _K.CHANGE_KIND:
        for tok in tokens[3:]:
          if tok.startswith(_K.DECISION_TARGETS_PREFIX):
            raw_targets = tok[len(_K.DECISION_TARGETS_PREFIX):]
            targets = [ t.strip() for t in raw_targets.split(",") if t.strip() ]
            break
      pair = ( kind, slug )
      if pair not in seen_spawn:
        seen_spawn.add(pair)
        spawn.append(( kind, slug, description, targets ))
      continue
    if verb == _K.DECISION_VERB_ATTACH and len(tokens) >= 2:
      target = tokens[1]
      if target not in seen_attach:
        seen_attach.add(target)
        attach.append(( target, description ))
      continue
  return spawn, attach


def _parse_reference_targets(block: str) -> list[tuple[str, str]]:
  """
  Scan a `<!-- routing-decision ... -->` block body for `reference <path> [:: <desc>]` lines.

  A `reference` line names an existing asset the router judges already implements the request
  (`lazy-spec.coordination-playbook.md` Chapter 7 / `docs/tasks/lazycortex-specs.upstream.md` § 10) —
  a third verb alongside `spawn` / `attach`, parsed here rather than by
  `_parse_routing_decision_rich` (see the `# Decision:` note on that function).

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    List of `(path, description)` tuples, dedup applied per path (preserves insertion order,
    first occurrence wins).
  """
  reference: list[tuple[str, str]] = []
  seen: set[str] = set()
  for raw_line in block.splitlines():
    stripped = raw_line.strip()
    # guard: skip blank lines — a non-decision prose line is dropped by a later guard instead
    if not stripped:
      continue
    head, _sep, desc_part = stripped.partition(_K.DECISION_DESC_SEP)
    description = desc_part.strip()
    tokens = head.split()
    # guard: not a `reference <path>` line — every other verb is another function's business
    if len(tokens) < 2 or tokens[0].lower() != _K.DECISION_VERB_REFERENCE:
      continue
    target = tokens[1]
    if target not in seen:
      seen.add(target)
      reference.append(( target, description ))
  return reference


def _parse_spawn_products(block: str) -> dict[tuple[str, str], str]:
  """
  Scan a `<!-- routing-decision ... -->` block body for a spawn line's own `product=<key>` field.

  `product=` names the product one spawn line targets explicitly — the sole way one routing
  decision fans a request out across several products in the same apply run
  (`lazy-spec.coordination-playbook.md` Chapter 7). Recognised on ANY spawn kind, anywhere after the
  slug and before `::`, order-independent relative to `targets=`. Parsed here rather than by
  `_parse_routing_decision_rich` (see the `# Decision:` note on that function).

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    Dict `{(kind, slug): product_key}` — only entries whose spawn line actually carried a
    non-empty `product=` field; a spawn line without one is simply absent from the dict.
  """
  return _spawn_field(block, _K.DECISION_PRODUCT_PREFIX)


def _spawn_field(block: str, prefix: str) -> dict[tuple[str, str], str]:
  """
  Scan a routing-decision block for one named field on each spawn line.

  Every optional spawn field is scanned rather than read positionally, so it may appear before
  or after any other field on the same line and the parser stays forgiving about their order.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).
    prefix: The `<name>=` token the field is written with.

  Returns:
    Dict `{(kind, slug): raw_value}` — only spawn lines that carried the field with a non-empty
    value; a line without it is simply absent.
  """
  found: dict[tuple[str, str], str] = {}
  for raw_line in block.splitlines():
    stripped = raw_line.strip()
    # guard: skip blank lines — a non-decision prose line is dropped by a later guard instead
    if not stripped:
      continue
    head, _sep, _desc_part = stripped.partition(_K.DECISION_DESC_SEP)
    tokens = head.split()
    # guard: not a `spawn <kind> <slug> ...` line with room for optional fields
    # waiver: structural token count for `spawn <kind> <slug>` line format, same as the sibling
    # guard in `_parse_routing_decision_rich`
    if len(tokens) < 3 or tokens[0].lower() != _K.DECISION_VERB_SPAWN:
      continue
    for tok in tokens[3:]:
      if tok.startswith(prefix):
        value = tok[len(prefix):].strip()
        if value:
          found[( tokens[1].lower(), tokens[2] )] = value
        break
  return found


def _parse_spawn_docs(block: str) -> dict[tuple[str, str], list[tuple[str, str]]]:
  """
  Scan a routing-decision block for each spawn line's own `docs=` field.

  `docs=` is the document set the spawned asset is scaffolded with — the router's decision in
  full, since `scaffold-asset` has no default layout of its own. An entry that does not carry
  the `<name>:<type>` shape is dropped rather than guessed at.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    Dict `{(kind, slug): [(filename, doc_type), ...]}` in the order the line declares them;
    a spawn line whose `docs=` resolved to no well-formed entry is absent.
  """
  parsed: dict[tuple[str, str], list[tuple[str, str]]] = {}
  for key, raw in _spawn_field(block, _K.DECISION_DOCS_PREFIX).items():
    pairs = [ entry.partition(_K.DOC_TOKEN_SEP) for entry in raw.split(",") if entry.strip() ]
    docs = [ ( name.strip(), doc_type.strip() ) for name, sep, doc_type in pairs
             if sep and name.strip() and doc_type.strip() ]
    if docs:
      parsed[key] = docs
  return parsed


def _parse_spawn_paths(block: str) -> dict[tuple[str, str], str]:
  """
  Scan a routing-decision block for each spawn line's own `path=` field.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    Dict `{(kind, slug): folder}` — the folder under the product's `spec_path` the asset lands
    in; a spawn line without the field is absent, and the type's `default_path` applies instead.
  """
  return _spawn_field(block, _K.DECISION_PATH_PREFIX)


def _parse_spawn_tools(block: str) -> dict[tuple[str, str], list[str]]:
  """
  Scan a routing-decision block for each spawn line's own `tools=` field.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    Dict `{(kind, slug): [tool, ...]}` — a spawn line without the field is absent, which leaves
    the asset's tools undetermined for the coordinator to settle on its own wake.
  """
  return { key: [ tool.strip() for tool in raw.split(",") if tool.strip() ]
           for key, raw in _spawn_field(block, _K.DECISION_TOOLS_PREFIX).items() }


def _parse_attach_drops(block: str) -> dict[str, list[str]]:
  """
  Scan a routing-decision block for each attach line's own `drop=` field.

  `drop=` names the documents a pre-launch rollback removes from the attached asset. An attach
  line without it drops nothing at all — the gates still roll back, the files stay.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    Dict `{attach_path: [filename, ...]}` — an attach line without the field is absent.
  """
  drops: dict[str, list[str]] = {}
  for raw_line in block.splitlines():
    stripped = raw_line.strip()
    # guard: skip blank lines — a non-decision prose line is dropped by a later guard instead
    if not stripped:
      continue
    head, _sep, _desc_part = stripped.partition(_K.DECISION_DESC_SEP)
    tokens = head.split()
    # guard: not an `attach <path> ...` line with room for optional fields
    # waiver: structural token count for the `attach <path>` line format
    if len(tokens) < 2 or tokens[0].lower() != _K.DECISION_VERB_ATTACH:
      continue
    for tok in tokens[2:]:
      if tok.startswith(_K.DECISION_DROP_PREFIX):
        names = [ name.strip() for name in tok[len(_K.DECISION_DROP_PREFIX):].split(",") if name.strip() ]
        if names:
          drops[tokens[1]] = names
        break
  return drops


def _extract_decision_block(routing_text: str) -> str | None:
  """
  Extract the inner text of an embedded `<!-- routing-decision ... -->` comment.

  Args:
    routing_text: Raw inner text of a `# Routing` section.

  Returns:
    The comment's inner text, or `None` when no such comment is present.
  """
  m = re.search(
      rf"(?s){re.escape(_K.ROUTING_DECISION_OPEN)}\s*(.*?)\s*{re.escape(_K.ROUTING_DECISION_CLOSE)}",
      routing_text,
  )
  return m.group(1) if m else None


def _parse_routing_decision(block: str) -> tuple[list[tuple[str, str]], list[str]]:
  """
  Parse the structured `<!-- routing-decision ... -->` block body.

  Preserves the `(kind, slug)` / path shape existing callers expect, omitting the
  per-target description and change-spawn cascade targets available to newer callers.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    Two lists: spawn-pair list (`(kind, slug)`) and attach-path list. Dedup is
    applied within each list (preserves insertion order).
  """
  spawn_rich, attach_rich = _parse_routing_decision_rich(block)
  spawn = [ ( kind, slug ) for kind, slug, _description, _targets in spawn_rich ]
  attach = [ path for path, _description in attach_rich ]
  return spawn, attach


def _parse_routing(body: str) -> tuple[str | None, list[tuple[str, str]], list[str], str]:
  """
  Extract the class verdict + spawn / attach targets from a `# Routing` section.

  Args:
    body: Request body (post-frontmatter).

  Returns:
    Four-tuple `(class_verdict, spawn_list, attach_list, routing_text)`.
    `class_verdict` is the lowercased verdict word or `None` when absent; when the
    structured decision block carries spawn lines of one uniform kind, that kind is the
    verdict and overrides any prose marker.
    `spawn_list` carries `(kind, slug)` pairs. `attach_list` carries folder-note
    paths — on the prose path, wikilinks whose last segment equals the previous
    one; the structured `<!-- routing-decision -->` branch takes its `attach`
    tokens verbatim, with no such shape check. `routing_text` is the raw inner
    text of the section (empty when no section is present).

    A `reference` line and a spawn line's own `product=` field never reach this
    function's return shape — `_parse_reference_targets` and `_parse_spawn_products`
    cover those two instead, each called separately against the same decision block
    by the caller that needs them (see the `# Decision:` note on
    `_parse_routing_decision_rich`).
  """
  m = re.search(
      rf"(?ms)^{re.escape(_K.ROUTING_H1)}\s*$(.*?)(?=^# \S|\Z)",
      body,
  )
  if not m:
    return None, [], [], ""
  routing_text = m.group(1)
  cls: str | None = None
  cm = re.search(
      r"(?im)\bclass\b\s*[:|]\s*\**\s*`?([a-z][a-z-]*)`?",
      routing_text,
  )
  if cm:
    candidate = cm.group(1).lower()
    if candidate in _K.CLASS_ENUM:
      cls = candidate
  # PRIMARY: structured `<!-- routing-decision ... -->` block. When present, its
  # contents are authoritative and prose-parsing is skipped entirely. Format:
  # one decision per line, each with an optional `:: <description>` suffix and,
  # on a change spawn, an optional `targets=` field (see _parse_routing_decision_rich):
  #     spawn <kind> <slug> [targets=<category>/<slug>[,...]] [:: <description>]
  #     attach <repo-relative-folder-note-path> [:: <description>]
  decision_block = _extract_decision_block(routing_text)
  if decision_block is not None:
    spawn_structured, attach_structured = _parse_routing_decision(decision_block)

    # Decision: one uniform spawn kind in the structured block overrides the prose verdict,
    # not the other way round — the prose marker is English-only (`class:`), so a localized
    # vault's routing prose never matches it, while the block's kind is language-independent
    # and authoritative by the block's own contract. Spawnless or mixed-kind decisions keep
    # whatever the prose parse produced.

    # promote the block's single uniform spawn kind to the request class
    kinds = { kind for kind, _slug in spawn_structured }
    if len(kinds) == 1:
      candidate = next(iter(kinds))
      if candidate in _K.CLASS_ENUM:
        cls = candidate

    # the structured block is authoritative in full — no prose fallback past this point
    return cls, spawn_structured, attach_structured, routing_text
  spawn: list[tuple[str, str]] = []
  seen_spawn: set[tuple[str, str]] = set()
  # Spawn line shape examples:
  #   "Spawn one cross-cutting change entity — `slug`"
  #   "Spawn change: slug"
  #   "spawn: bug — `slug`"
  for sm in re.finditer(
      r"(?im)\bspawn\b[^\n]*?\b(feature|change|bug)\b[^\n]*?`([a-z][a-z0-9-]*)`",
      routing_text,
  ):
    pair = ( sm.group(1).lower(), sm.group(2) )
    if pair not in seen_spawn:
      seen_spawn.add(pair)
      spawn.append(pair)
  # Plain `<kind>: <slug>` form (router may emit a structured fallback). A trailing
  # `:: <description>` suffix (the block grammar's per-target description) is tolerated
  # and ignored here — this prose fallback surfaces only the identity, never the detail.
  for sm in re.finditer(
      r"(?im)^\s*(?:[-*]\s*)?(?:spawn[^\n:]*[:|]\s*)?(feature|change|bug)\s*[:|]\s*"
      r"`?([a-z][a-z0-9-]*)`?\s*(?:::.*)?$",
      routing_text,
  ):
    pair = ( sm.group(1).lower(), sm.group(2) )
    # collect only pairs the prose-form pass above has not already recorded
    if pair not in seen_spawn:
      seen_spawn.add(pair)
      spawn.append(pair)
  # Path-form spawn target — router may emit the full repo-relative spawn path in
  # backticks (e.g. "spawn `request/products/test/changes/<slug>`"). The kind is
  # the singular of the second-to-last path segment ("changes" → "change"); the
  # slug is the last path segment.
  for sm in re.finditer(
      r"(?im)\bspawn\b[^\n]*?`([^`\s]+/(?:features|changes|bugs)/[a-z][a-z0-9-]*)`",
      routing_text,
  ):
    path_target = sm.group(1)
    parts = path_target.rstrip("/").split("/")
    slug = parts[-1]
    folder = parts[-2]
    kind = { "features": "feature", "changes": "change", "bugs": "bug" }[folder]
    pair = ( kind, slug )
    # collect only pairs the prose-form passes above have not already recorded
    if pair not in seen_spawn:
      seen_spawn.add(pair)
      spawn.append(pair)
  attach: list[str] = []
  seen_attach: set[str] = set()
  for wm in re.finditer(r"\[\[([^\]|]+?)(?:\|[^\]]*?)?\]\]", routing_text):
    target = wm.group(1).strip()
    parts = target.split("/")
    # collect only fresh folder-note links, whose shape is "<...>/<slug>/<slug>"
    if len(parts) >= 2 and parts[-1] == parts[-2] and target not in seen_attach:
      seen_attach.add(target)
      attach.append(target)
  return cls, spawn, attach, routing_text


def _strip_routing(body: str) -> str:
  """
  Remove the entire `# Routing` H1 section from a body.

  Args:
    body: Request body (post-frontmatter).

  Returns:
    The body with the routing section excised; consecutive blank lines collapsed
    to at most one blank line.
  """
  pat = rf"(?ms)^{re.escape(_K.ROUTING_H1)}\s*$.*?(?=^# \S|\Z)"
  out = re.sub(pat, "", body, count = 1)
  return re.sub(r"\n{3,}", "\n\n", out)


def _strip_prior_status_callout(body: str) -> str:
  """
  Drop any leading `> [!...] ... #status/<x>` callout block above the first H1.

  Args:
    body: Body text starting at or before the first H1.

  Returns:
    Body with the leading status callout (and one trailing blank line) removed
    when present; unchanged otherwise.
  """
  m_h1 = re.search(r"(?m)^# ", body)
  # guard: no H1 — leave body as-is
  if not m_h1:
    return body
  head = body[:m_h1.start()]
  tail = body[m_h1.start():]
  out_lines: list[str] = []
  in_status_callout = False
  for line in head.splitlines(keepends = True):
    if line.startswith("> "):
      if re.search(_K.STATUS_TAG_PATTERN, line):
        in_status_callout = True
        continue
      # guard: continuation line of a callout we are already eating
      if in_status_callout:
        continue
      out_lines.append(line)
      continue
    if in_status_callout and line.strip() == "":
      in_status_callout = False
      continue
    in_status_callout = False
    out_lines.append(line)
  return "".join(out_lines) + tail


def _format_status_callout(*, accepted: bool, wikilinks: list[str], reason: str | None) -> str:
  """
  Render the apply transition's status callout block.

  Args:
    accepted: True for the success callout, False for the rejection callout.
    wikilinks: Resolved-target wikilink paths to list in the success callout body.
    reason: Optional rejection reason line; only used when `accepted is False`.

  Returns:
    Multi-line callout block without trailing newline.
  """
  if accepted:
    lines = [ f"> {_K.CALLOUT_SUCCESS}" ]
    for wl in wikilinks:
      lines.append(f"> [[{wl}]]")
    return "\n".join(lines)
  lines = [ f"> {_K.CALLOUT_WARNING}" ]
  if reason:
    lines.append(f"> {reason}")
  lines.append(f"> {_K.REJECT_HINT}")
  return "\n".join(lines)


def _insert_status_callout(body: str, callout: str) -> str:
  """
  Insert the rendered status callout one blank line above the first H1.

  Args:
    body: Body with any prior status callout already stripped.
    callout: Rendered callout block (no trailing newline).

  Returns:
    Body with the callout placed above the first H1 (or at the start when no H1).
  """
  m_h1 = re.search(r"(?m)^# ", body)
  # guard: no H1 — prepend at start
  if not m_h1:
    return callout + "\n\n" + body
  return body[:m_h1.start()] + callout + "\n\n" + body[m_h1.start():]


def _set_fm_scalar(fm_text: str, key: str, value: str) -> str:
  """
  Add or replace a scalar `key: value` line inside a `---`-delimited frontmatter block.

  Args:
    fm_text: Full frontmatter text including the opening / closing fences.
    key: Scalar key name.
    value: Replacement value (string-rendered).

  Returns:
    Frontmatter text with the key set; existing lines are replaced in place,
    missing keys are appended before the closing fence.
  """
  pat = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$")
  if pat.search(fm_text):
    return pat.sub(f"{key}: {value}", fm_text, count = 1)
  # guard: closing fence absent — leave untouched (parser would not recognise this as a block)
  _, fm_end_probe = _parse_frontmatter(fm_text)
  if fm_end_probe == 0:
    return fm_text
  close_idx = fm_text.rfind("---\n")
  # guard: should be unreachable when fm_end_probe > 0, but defensive against partial fences
  if close_idx <= 0:
    return fm_text
  return fm_text[:close_idx] + f"{key}: {value}\n" + fm_text[close_idx:]


def _set_fm_list(fm_text: str, key: str, values: list[str]) -> str:
  """
  Add or replace a `key:` list block inside a `---`-delimited frontmatter block.

  Args:
    fm_text: Full frontmatter text including the opening / closing fences.
    key: List-typed key name.
    values: Replacement member list, rendered as unquoted `- <value>` lines.

  Returns:
    Frontmatter text with the list set; an existing inline `[]` or multi-line
    `- ` block is replaced in place, a missing key is appended before the
    closing fence.
  """
  block_lines = "\n".join(f"  - {v}" for v in values)
  replacement = f"{key}:\n{block_lines}\n" if values else f"{key}: []\n"
  pat_inline = re.compile(rf"(?m)^{re.escape(key)}\s*:\s*\[\s*\]\s*$\n?")
  pat_block = re.compile(rf"(?m)^{re.escape(key)}\s*:\s*\n(?:\s+- .*\n)*")
  if pat_inline.search(fm_text):
    return pat_inline.sub(replacement, fm_text, count = 1)
  if pat_block.search(fm_text):
    return pat_block.sub(replacement, fm_text, count = 1)
  # guard: closing fence absent — leave untouched (parser would not recognise this as a block)
  close_idx = fm_text.rfind("---\n")
  if close_idx <= 0:
    return fm_text
  return fm_text[:close_idx] + replacement + fm_text[close_idx:]


def _del_fm_key(fm_text: str, key: str) -> str:
  """
  Remove a scalar `key: value` line from a `---`-delimited frontmatter block.

  Args:
    fm_text: Full frontmatter text including the opening / closing fences.
    key: Scalar key name to remove.

  Returns:
    Frontmatter text with the key's line removed; unchanged when the key is absent.
  """
  pat = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$\n?")
  return pat.sub("", fm_text, count = 1)


def _is_launched_feature(fm: dict, folder_note: Path) -> bool:
  """
  Decide whether a feature has already launched its implementation.

  Mirrors the launched-feature definition the coordinator (`lazy-spec.coordinator.md`) uses to keep a
  launched feature off the attach path in the first place — this check is the worker-side
  safety net for a coordinator mistake, not the primary enforcement.

  Args:
    fm: The folder-note's parsed frontmatter.
    folder_note: Absolute path to the feature's `<slug>/<slug>.md`, used to check for a
      `code-report.md` sibling.

  Returns:
    True when `spec_develop_done` is true, the active job's checkbox is `Start implementation`,
    or a `code-report.md` sibling already exists.
  """
  # signal 1 — the develop-done gate is the strongest, most direct launched marker
  if fm.get(Gate.DEVELOP_DONE, "").strip().lower() == BOOL_TRUE:
    return True

  # signal 2 — an active job dispatched for the implementation checkbox counts as launched
  # even before spec_develop_done itself flips true
  job_info = spec_job_markers.read(flip_gate._repo_root(folder_note.parent), folder_note)[JobMarker.ACTIVE_JOB]
  if isinstance(job_info, dict) and job_info.get(JobMarker.CHECKBOX) == GateCheckbox.START_IMPLEMENTATION:
    return True

  # signal 3 — a code-report.md sibling can only exist once implementation has actually run
  return (folder_note.parent / SiblingDoc.CODE_REPORT).is_file()


def _has_ladder_started(fm: dict, folder_note: Path) -> bool:
  """
  Decide whether a feature's implementation ladder has already been set in motion.

  Args:
    fm: The folder-note's parsed frontmatter.
    folder_note: Absolute path to the feature's `<slug>/<slug>.md`.

  Returns:
    True when an `architecture.md` / `code-plan.md` / `test-plan.md` sibling exists, or any gate
    from `spec_plan_done` onward already reads true; False for an untouched feature.
  """
  if (
      (folder_note.parent / SiblingDoc.ARCHITECTURE).is_file()
      or (folder_note.parent / SiblingDoc.CODE_PLAN).is_file()
      or (folder_note.parent / SiblingDoc.TEST_PLAN).is_file()
  ):
    return True
  return any(fm.get(gate, "").strip().lower() == BOOL_TRUE for gate in _ROLLBACK_GATES)


def _sweep_request_tag(fm_text: str, new_tag_member: str) -> str:
  """
  Replace every `request/*` member in the `tags:` block with the new one; keep other tags.

  Args:
    fm_text: Full frontmatter text.
    new_tag_member: Replacement tag (e.g. `request/accepted`).

  Returns:
    Frontmatter text with the `request/*` mirror-tag swept and rewritten;
    non-`request/*` members untouched.
  """
  tags_re = re.compile(r"(?m)^tags\s*:\s*\n((?:\s+- .*\n)*)")
  m = tags_re.search(fm_text)
  if not m:
    close_idx = fm_text.rfind("---\n")
    # guard: cannot splice without a closing fence
    if close_idx < 0:
      return fm_text
    return fm_text[:close_idx] + f"tags:\n  - {new_tag_member}\n" + fm_text[close_idx:]
  existing = m.group(1)
  kept: list[str] = []
  added = False
  for line in existing.splitlines(keepends = True):
    stripped = line.strip()
    # guard: not a `- ` list member, keep the line verbatim and move on
    if not stripped.startswith("- "):
      kept.append(line)
      continue
    member = stripped[2:].strip()
    if member.startswith(_K.TAG_PREFIX):
      if not added:
        kept.append(f"  - {new_tag_member}\n")
        added = True
      continue
    kept.append(line)
  if not added:
    kept.append(f"  - {new_tag_member}\n")
  new_block = "".join(kept)
  return fm_text[:m.start(1)] + new_block + fm_text[m.end(1):]


def _stamp_request_terminal(fm_text: str, *, request_class: str, request_status: str) -> str:
  """
  Apply the apply transition's frontmatter mutations to a request file.

  Args:
    fm_text: Full frontmatter text.
    request_class: Class verdict (the eight-value enum from `_K.CLASS_ENUM`).
    request_status: Lifecycle terminal — `accepted` or `rejected`.

  Returns:
    Frontmatter text with `request_class`, `request_status`, and the mirror tag stamped.
  """
  fm_text = _set_fm_scalar(fm_text, _K.REQUEST_CLASS, request_class)
  fm_text = _set_fm_scalar(fm_text, _K.REQUEST_STATUS, request_status)
  fm_text = _sweep_request_tag(fm_text, f"{_K.TAG_PREFIX}{request_status}")
  return fm_text


def _request_h1_title(body: str) -> str:
  """
  Extract the first H1 title (without the leading `# `) from a body.

  Args:
    body: Body text.

  Returns:
    The title text, or `"request"` when no H1 is present.
  """
  m = re.search(r"(?m)^# (.+)$", body)
  return m.group(1).strip() if m else "request"


def _request_content_block(body: str) -> str:
  """
  Extract the H1 + section content of a request body, skipping `# Routing` and `# History`.

  Args:
    body: Request body (post-frontmatter, post-status-callout).

  Returns:
    Concatenated content of the first H1 section and any non-routing/non-history H1
    sections following it, separated by blank lines.
  """
  segments: list[str] = []
  for sec in re.finditer(r"(?ms)^# (\S.*?)$(.*?)(?=^# \S|\Z)", body):
    title = sec.group(1).strip()
    # guard: skip the routing section — it is the apply worker's input, not body content
    if title.lower() == _K.ROUTING_H1[2:].lower():
      continue
    # guard: skip the history section — it is per-document review state, not request prose
    if title.lower() == _K.HISTORY_H1[2:].lower():
      continue
    chunk = f"# {title}\n{sec.group(2).rstrip()}\n"
    segments.append(chunk)
  return "\n".join(segments).strip()


def _today_iso() -> str:
  """
  Return today's UTC date in `YYYY-MM-DD` form.

  Returns:
    ISO-formatted date string.
  """
  return _dt.datetime.now(_dt.UTC).date().isoformat()


class _Attach:
  """
  Inline attach primitive for the apply transition.

  Replaces the LLM-driven `spec.request-attach` skill, seeding a target's primary doc with the
  router's per-target description on behalf of one apply run.

  Responsibilities:
    - Seed a spawn target's primary doc with draft content, or an attach target's primary doc
      with an attention-block delta.
    - Track a doc's `spec_source_requests` frontmatter and its `## Requests` body projection,
      without duplicating an already-listed request.
    - Append the originating request to the entity's folder-note `## Source requests` list.
  """

  @staticmethod
  def primary_doc_for_kind(kind: str, record: dict | None = None) -> str:
    """
    Return the entity's primary doc filename.

    Args:
      kind: The asset type the entity was spawned as.
      record: The owning product's settings record, so a product-declared type resolves its own
        `start_doc`; `None` consults only the shipped declarations.

    Returns:
      The filename half of the type's declared `start_doc`, falling back to `design.md` for a
      type that declares none.
    """
    name, _doc_type = asset_types.start_doc(kind, record or {})
    return name or _K.DESIGN_MD

  @staticmethod
  def kind_from_folder_note(folder_note: Path) -> str:
    """
    Infer the entity kind from a folder-note's path.

    Args:
      folder_note: Path to the entity's `<slug>/<slug>.md` folder-note.

    Returns:
      The note's own `spec_asset_type`, falling back to `change` on a note that carries none —
      the folder the note sits in is never consulted, since a type's folder is the caller's
      choice rather than a property of the type.
    """
    declared = asset_types.type_of(folder_note) if folder_note.is_file() else ""
    return declared or _K.CHANGE_KIND

  @staticmethod
  def _splice_before_sources(text: str, block: str) -> str:
    """
    Splice a content block into a doc's body, before `# Sources` when present.

    Args:
      text: Full doc text (frontmatter + body).
      block: Content to insert — landed at end-of-doc when no `# Sources`
        heading exists, otherwise immediately before it.

    Returns:
      The doc text with `block` spliced in.
    """
    sources_idx = text.find(f"\n{_K.SOURCES_H1}\n")
    if sources_idx < 0:
      return text.rstrip() + "\n\n" + block + "\n"
    head = text[:sources_idx].rstrip()
    tail = text[sources_idx:]
    return head + "\n\n" + block + "\n" + tail

  @staticmethod
  def _replace_overview_stub(text: str, block: str) -> str | None:
    """
    Replace the `## Overview` section's italic template stub with a content block.

    Args:
      text: Full doc text (frontmatter + body).
      block: Content that becomes the section's body.

    Returns:
      The doc text with the stub replaced, or `None` when the doc carries no `## Overview`
      section or its content is not a lone `_…_` template stub — the caller falls back to
      the end-of-body splice then.
    """
    # the lookahead is the guard that matters: the section body must be NOTHING but the lone
    # italic stub before the next heading — an Overview a human already wrote never matches,
    # so the seed can only ever replace scaffolding, not authored prose
    match = re.search(
        rf"(?ms)^{re.escape(_K.OVERVIEW_H2)}\s*\n(_[^\n]*_\s*\n)(?=\s*^#|\s*\Z)",
        text,
    )
    # guard: no Overview skeleton to seed into — the doc is not template-shaped
    if not match:
      return None
    return text[:match.start(1)] + block + "\n" + text[match.end(1):]

  @staticmethod
  def seed_body_content(doc_path: Path, content_block: str) -> bool:
    """
    Seed a content block into a doc — into the `## Overview` stub, else before `# Sources`.

    Guarantees:
      An `## Overview` section carrying anything other than the lone template stub is never
      overwritten — the seed then falls back to the pre-`# Sources` splice.

    Args:
      doc_path: Path to the target authored doc.
      content_block: Content to splice into the doc.

    Returns:
      `True` when the doc text changed, `False` otherwise.
    """
    text = doc_path.read_text()
    # guard: skip empty content blocks
    if not content_block.strip():
      return False

    # Decision: the seed replaces the Overview stub rather than trailing the skeleton — the
    # protocol calls it the doc's INITIAL content, and a pointer buried under Boundaries is
    # one the writer and the operator both miss (found live on the first spawned asset).
    new_text = _Attach._replace_overview_stub(text, content_block)
    if new_text is None:
      new_text = _Attach._splice_before_sources(text, content_block)
    if new_text == text:
      return False
    doc_path.write_text(new_text)
    return True

  @staticmethod
  def append_attention_block(doc_path: Path, seed: str) -> bool:
    """
    Append a `[!attention] change requested` callout to a doc, before `# Sources` when present.

    Args:
      doc_path: Path to the target authored doc.
      seed: Description text to display (already resolved to the fallback
        sentence when the router left none).

    Returns:
      `True` when the doc text changed, `False` otherwise.
    """
    text = doc_path.read_text()
    block = f"{_K.ATTENTION_CALLOUT_PREFIX}{seed}"
    new_text = _Attach._splice_before_sources(text, block)
    if new_text == text:
      return False
    doc_path.write_text(new_text)
    return True

  @staticmethod
  def ensure_source_request(doc_path: Path, request_wikilink: str,
                            request_display: str) -> bool:
    """
    Add the request to `spec_source_requests` frontmatter and re-project the body bullet list.

    Args:
      doc_path: Path to the target authored doc.
      request_wikilink: The request file's vault-relative wikilink path.
      request_display: Display gloss for the wikilink bullet.

    Returns:
      `True` when the doc text changed, `False` when the request was already listed.
    """
    text = doc_path.read_text()
    fm_text = text[:_parse_frontmatter(text)[1]]
    body = text[_parse_frontmatter(text)[1]:]
    values, _ = _parse_frontmatter(text)
    existing = values.get(_K.SPEC_SOURCE_REQUESTS) or []
    target_member = f"[[{request_wikilink}]]"
    # guard: idempotent — request already listed
    for raw in existing:
      raw_clean = raw.strip().strip('"').strip("'")
      pure = raw_clean.split("|")[0].strip("[]")
      if pure == request_wikilink:
        return False
    fm_text = _Attach._append_source_requests_fm(fm_text, target_member)
    body = _Attach._project_requests_body(body, request_wikilink, request_display)
    doc_path.write_text(fm_text + body)
    return True

  @staticmethod
  def _append_source_requests_fm(fm_text: str, member: str) -> str:
    """
    Append `member` to the `spec_source_requests:` frontmatter list (create when absent).

    Args:
      fm_text: Full frontmatter text.
      member: Wikilink-bracketed reference to append (e.g. `[[path/to/req]]`).

    Returns:
      Frontmatter text with the member appended to the list, or with the list
      created when the key was previously absent.
    """
    pat_inline = re.compile(rf"(?m)^{re.escape(_K.SPEC_SOURCE_REQUESTS)}\s*:\s*\[\s*\]\s*$")
    pat_block = re.compile(
        rf"(?m)^{re.escape(_K.SPEC_SOURCE_REQUESTS)}\s*:\s*\n((?:\s+- .*\n)*)",
    )
    if pat_inline.search(fm_text):
      replacement = (
          f"{_K.SPEC_SOURCE_REQUESTS}:\n  - \"{member}\""
      )
      return pat_inline.sub(replacement, fm_text, count = 1)
    m = pat_block.search(fm_text)
    if m:
      existing = m.group(1)
      new_block = existing + f"  - \"{member}\"\n"
      return fm_text[:m.start(1)] + new_block + fm_text[m.end(1):]
    close_idx = fm_text.rfind("---\n")
    # guard: cannot splice without a closing fence
    if close_idx < 0:
      return fm_text
    inject = f"{_K.SPEC_SOURCE_REQUESTS}:\n  - \"{member}\"\n"
    return fm_text[:close_idx] + inject + fm_text[close_idx:]

  @staticmethod
  def _project_requests_body(body: str, request_wikilink: str,
                             request_display: str) -> str:
    """
    Append the request bullet inside the `## Requests` projection markers.

    Args:
      body: Doc body (post-frontmatter).
      request_wikilink: Wikilink target.
      request_display: Display gloss.

    Returns:
      Body with the new bullet appended between the projection markers; the
      `# Sources` container and `## Requests` sub-section are created on demand
      when absent.
    """
    # the dated bullet is the projection's unit, and doubles as the idempotence key below
    today = _today_iso()
    new_bullet = f"- [[{request_wikilink}|{request_display}]] — {today}"
    start_marker = _K.REQUESTS_MARKER_START
    end_marker = _K.REQUESTS_MARKER_END

    # an existing marker pair means the projection is already in place, so append inside it
    if start_marker in body and end_marker in body:
      pat = re.compile(
          rf"({re.escape(start_marker)}\n)(.*?)(\n?{re.escape(end_marker)})",
          re.DOTALL,
      )
      m = pat.search(body)
      if m:
        block = m.group(2)
        # guard: bullet already projected, a re-run must not duplicate it
        if new_bullet in block:
          return body
        new_block = block.rstrip("\n")
        new_block = (new_block + "\n" if new_block else "") + new_bullet
        return body[:m.start(2)] + new_block + body[m.end(2):]

    # no marker pair yet, so the whole container and sub-section are created around the bullet
    container = "\n".join([
        "",
        _K.SOURCES_H1,
        _K.SOURCES_TAG,
        "",
        _K.REQUESTS_H2,
        start_marker,
        new_bullet,
        end_marker,
        "",
    ])
    return body.rstrip() + "\n" + container


class _FolderNote:
  """
  Folder-note edits — appends the request wikilink to `## Source requests`.
  """

  @staticmethod
  def append_source_request(folder_note: Path, request_wikilink: str,
                            request_display: str) -> bool:
    """
    Append `- [[<wikilink>|<display>]] — <today>` to the folder-note's `## Source requests` section.

    Args:
      folder_note: Path to `<slug>/<slug>.md`.
      request_wikilink: Request file's wikilink target.
      request_display: Display gloss for the bullet.

    Returns:
      `True` when the folder-note text changed, `False` when the bullet was already
      present (idempotent re-run).
    """
    text = folder_note.read_text()
    today = _today_iso()
    bullet = f"- [[{request_wikilink}|{request_display}]] — {today}"
    if f"[[{request_wikilink}]]" in text or f"[[{request_wikilink}|" in text:
      return False
    section_re = re.compile(
        rf"(?ms)^{re.escape(_K.SOURCE_REQUESTS_H2)}\s*$(.*?)(?=^## \S|^# \S|\Z)",
    )
    m = section_re.search(text)
    if m:
      block = m.group(1)
      cleaned = block.rstrip("\n")
      new_block = cleaned + ("\n\n" if cleaned else "\n") + bullet + "\n"
      new_text = text[:m.start(1)] + new_block + text[m.end(1):]
    else:
      # Insert section before ## History anchor when present, otherwise append.
      # NOTE: The status folder-note body shape uses `# History` (H1, Section.HISTORY) since A4.
      # HISTORY_H2 = "## History" is a stale anchor — the `## Source requests` block is written
      # into the operator-zone of the folder-note, where the legacy H2 anchor may still appear in
      # pre-migration notes. This constant and the insertion logic are intentionally left as-is
      # pending an A9-code task that updates the anchor to Section.HISTORY and verifies the insert
      # correctly lands above the protected `# History` section.
      hist_idx = text.find(f"\n{_K.HISTORY_H2}\n")
      block_text = f"{_K.SOURCE_REQUESTS_H2}\n\n{bullet}\n\n"
      if hist_idx >= 0:
        new_text = text[:hist_idx + 1] + block_text + text[hist_idx + 1:]
      else:
        new_text = text.rstrip() + "\n\n" + block_text
    folder_note.write_text(new_text)
    return True


class _Apply:
  """
  Top-level orchestrator for one request's apply transition.

  Represents a single apply run against one request file, from its routing decision through to
  a terminal, committed state.

  Responsibilities:
    - Enact the routing decision's spawn and attach targets against the product's spec tree.
    - Track the docs, folder-notes, and non-fatal warnings this run has produced.
    - Open a review cycle on every doc it populates and commit the run's changes atomically
      under the bot identity.

  Attributes:
    file_path: Absolute path to the request markdown file being applied.
    repo: Repository root containing the request file.
    author_name: Git author name used for the atomic commit.
    author_email: Git author email used for the atomic commit.
    specs_cli: Resolved path to the sibling `lazycortex-specs` CLI.
    review_cli: Resolved path to the sibling `lazycortex-review` CLI.
    populated_docs: Docs that received a router-description seed during this run.
    spawn_folder_notes: Folder-notes created by enacting a spawn target during this run.
    spawn_group_notes: Group folder-notes the scaffolder seeded while enacting spawns this run.
    attach_folder_notes: Folder-notes populated by enacting an attach target during this run.
    warnings: Non-fatal issues collected during this run, such as an unresolvable design-cascade
      target named in a change spawn's `targets=` field.
    submit_docs: Populated docs that must re-enter review via `submit` (skipping the opening
      writer round) instead of `start`, because a pre-launch ladder rollback re-opened them.
  """

  def __init__(self, *, file_path: Path, author_name: str, author_email: str) -> None:
    """
    Construct an apply orchestrator scoped to one request file.

    Args:
      file_path: Absolute path to the request markdown file.
      author_name: Git author name for the atomic commit (bot identity).
      author_email: Git author email for the atomic commit.
    """
    self.file_path = file_path.resolve()
    self.repo = _repo_root(self.file_path.parent)
    self.author_name = author_name
    self.author_email = author_email
    self.specs_cli = _resolve_sibling_cli(_K.CLI_LAZYCORTEX_SPECS)
    self.review_cli = _resolve_sibling_cli(_K.CLI_LAZYCORTEX_REVIEW)
    self.populated_docs: list[Path] = []
    self.spawn_folder_notes: list[Path] = []
    self.spawn_group_notes: list[Path] = []
    self.attach_folder_notes: list[Path] = []
    self.warnings: list[str] = []
    self.submit_docs: list[Path] = []

  @property
  def request_wikilink(self) -> str:
    """
    The request file's wikilink target — the repo-relative path with the `.md` suffix dropped.
    """
    rel = self.file_path.resolve().relative_to(self.repo)
    return str(rel.with_suffix(""))

  def _load_product_record(self, product: str) -> dict:
    """
    Look up a product record from `.claude/lazy.settings.json`.

    Args:
      product: Product compound-key.

    Returns:
      The product record (`spec_path` and friends).
    """
    settings_path = self.repo / _K.CLAUDE_DIR / _K.SETTINGS_FILE
    if not settings_path.exists():
      _fail(_K.CAT_LOGICAL, f".claude/lazy.settings.json absent at {settings_path}")
    try:
      data = json.loads(settings_path.read_text())
    except json.JSONDecodeError as e:
      _fail(_K.CAT_LOGICAL, f".claude/lazy.settings.json malformed: {e}")
    products_section = data.get(_K.PRODUCTS) or {}
    record = products_section.get(product) if isinstance(products_section, dict) else None
    if not isinstance(record, dict):
      _fail(_K.CAT_LOGICAL,
            f"product '{product}' not registered in lazy.settings.json[{_K.PRODUCTS}]")
    if _K.SPEC_PATH not in record:
      _fail(_K.CAT_LOGICAL, f"product '{product}' has no {_K.SPEC_PATH}")
    return record

  def _default_product(self) -> str:
    """
    Pick the default product key.

    Returns:
      The first product key from settings; aborts when no product is registered.
    """
    settings_path = self.repo / _K.CLAUDE_DIR / _K.SETTINGS_FILE
    data = json.loads(settings_path.read_text())
    products_section = data.get(_K.PRODUCTS) or {}
    keys = sorted(
        k for k, v in products_section.items()
        if isinstance(k, str) and not k.startswith("_") and isinstance(v, dict)
    )
    # guard: at least one product must exist before apply can act on a spawn
    if not keys:
      _fail(_K.CAT_LOGICAL, _K.ERR_NO_PRODUCTS)
    return keys[0]

  def _record_for_note(self, note: Path) -> dict:
    """
    Resolve the settings record of the product whose `spec_path` contains one asset note.

    Args:
      note: Absolute path of the asset's status folder-note.

    Returns:
      The owning product's record, or `{}` when no registered product's `spec_path` covers it.
    """
    settings_path = self.repo / _K.CLAUDE_DIR / _K.SETTINGS_FILE
    # guard: no readable settings — no product record to resolve against
    if not settings_path.exists():
      return {}
    try:
      data = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
      return {}
    # the deepest matching spec_path wins, so a product nested under another resolves to itself
    best: dict = {}
    best_depth = -1
    for record in (data.get(_K.PRODUCTS) or {}).values():
      # guard: the version sentinel and any record without a usable spec_path cover no note
      if not isinstance(record, dict) or not isinstance(record.get(_K.SPEC_PATH), str):
        continue
      root = spec_content_root(self.repo) / record[_K.SPEC_PATH]
      depth = len(Path(record[_K.SPEC_PATH]).parts)
      if note.is_relative_to(root) and depth > best_depth:
        best, best_depth = record, depth
    return best

  def _known_kinds(self) -> frozenset[str]:
    """
    Collect every asset type a spawn line may name in this repo.

    The shipped set plus the declarations of every registered product: a routing decision names
    a type, not a product, so a type any product declares is admissible on any spawn line and
    the product it lands in is settled separately by `product=`.

    Returns:
      The admissible type names, the shipped set alone when no settings file is readable.
    """
    settings_path = self.repo / _K.CLAUDE_DIR / _K.SETTINGS_FILE
    kinds = set(asset_types.builtin_defaults())
    # guard: no readable settings — only the shipped declarations apply
    if not settings_path.exists():
      return frozenset(kinds)
    try:
      data = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
      return frozenset(kinds)
    for record in (data.get(_K.PRODUCTS) or {}).values():
      if isinstance(record, dict):
        kinds.update(record.get(_K.ASSET_TYPES) or {})
    return frozenset(kinds)

  def _spawn(self, kind: str, slug: str, *, product: str | None = None,
             docs: list[tuple[str, str]] | None = None, path: str = "",
             tools: list[str] | None = None) -> tuple[Path, str]:
    """
    Run the scaffold-asset subprocess to create the new entity folder.

    Args:
      kind: The asset type the routing decision named.
      slug: Asset slug.
      product: The spawning decision line's own `product=` field, when given — the sole way
        one routing decision fans a request out across several products in the same apply run
        (playbook Chapter 7). Falls back to `_default_product()` (first registered product key)
        when omitted, matching every pre-multi-product routing decision on a single-product repo.
      docs: The `(filename, doc_type)` pairs the decision's own `docs=` field named; the
        scaffold has no default layout, so a spawn naming none is refused.
      path: The decision's own `path=` field, empty to fall back to the type's `default_path`.
      tools: The decision's own `tools=` field, empty to leave the asset's tools undetermined.

    Returns:
      Two-tuple of the new folder-note's absolute path
      (`<content_root>/<spec_path>/<folder>/<slug>/<slug>.md`, where the content root is
      `spec.vault_root`, default `specs`) and the spawning product's `spec_path`.
    """
    # guard: the document set is the router's decision in full — a spawn without one cannot land
    if not docs:
      _fail(_K.CAT_LOGICAL, f"spawn {kind} '{slug}' names no {_K.DECISION_DOCS_PREFIX} documents")
    product = product or self._default_product()
    record = self._load_product_record(product)
    spec_path = record[_K.SPEC_PATH]
    folder = path or asset_types.default_path(kind, record)
    # the scaffolder lands assets under the content root (`spec.vault_root`, default `specs`),
    # so the note is read back through the same base — `repo / spec_path` misses it
    target_folder = spec_content_root(self.repo) / spec_path / folder / slug
    folder_note = target_folder / f"{slug}.md"
    if folder_note.exists():
      # Idempotent — earlier apply attempt already scaffolded; no-op.
      return folder_note, spec_path
    argv = [ str(self.specs_cli), "scaffold-asset", product, kind, slug ]
    for name, doc_type in docs:
      argv += [ _K.SCAFFOLD_DOC_FLAG, f"{name}{_K.DOC_TOKEN_SEP}{doc_type}" ]
    if path:
      argv += [ _K.SCAFFOLD_PATH_FLAG, path ]
    res = subprocess.run(
        argv,
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False,
    )
    if res.returncode != 0:
      _fail(_K.CAT_LOGICAL,
            f"scaffold-asset failed for {kind} '{slug}': "
            f"exit={res.returncode} stderr={res.stderr.strip()[:240]}")

    # a group folder-note the scaffolder seeded must reach the commit set — left untracked it
    # halts the runtime daemon's clean-tree check; a missing/empty key or non-JSON stdout means
    # nothing was seeded
    try:
      seeded_group = (json.loads(res.stdout) or {}).get(_K.SCAFFOLD_GROUP_NOTE_KEY, "")
    except json.JSONDecodeError:
      seeded_group = ""
    if seeded_group:
      self.spawn_group_notes.append(self.repo / seeded_group)

    # the router's own tool judgement overrides whatever the type's declaration seeded
    if tools:
      note_text = folder_note.read_text()
      _values, fm_end = _parse_frontmatter(note_text)
      folder_note.write_text(
          _set_fm_list(note_text[:fm_end], _K.SPEC_TOOLS_KEY, tools) + note_text[fm_end:])
    return folder_note, spec_path

  def _resolve_folder_note_path(self, wikilink_target: str) -> Path:
    """
    Project a repo-relative wikilink target onto its folder-note path, with no existence check.

    Args:
      wikilink_target: Repo-relative path without the `.md` suffix (e.g.
        `Server/products/dashboards/features/csv-export/csv-export`).

    Returns:
      Absolute candidate folder-note path — may or may not exist on disk.
    """
    return self.repo / Path(wikilink_target + ".md")

  def _resolve_attach_folder_note(self, attach_target: str) -> Path:
    """
    Map a routing wikilink target onto an absolute folder-note path.

    Args:
      attach_target: The wikilink content (e.g. `request/products/test/features/csv-export/csv-export`).

    Returns:
      Absolute path to the resolved folder-note.
    """
    candidate = self._resolve_folder_note_path(attach_target)
    if not candidate.is_file():
      _fail(_K.CAT_LOGICAL,
            f"attach target '{attach_target}' does not resolve to a folder-note ({candidate})")
    return candidate

  def _resolve_change_target(self, spec_path: str, raw_target: str) -> Path | None:
    """
    Resolve a change spawn's raw design-cascade target to its folder-note path.

    Args:
      spec_path: The spawning change's product `spec_path`.
      raw_target: `<category>/<slug>` token from the routing decision's `targets=` field.

    Returns:
      The resolved folder-note path when it exists on disk, `None` when the
      token is malformed or names no existing asset.
    """
    parts = raw_target.split("/")
    # guard: a cascade target names exactly one category and one slug
    if len(parts) != 2:
      return None
    category, slug = parts
    candidate = self._resolve_folder_note_path(f"{spec_path}/{category}/{slug}/{slug}")
    return candidate if candidate.is_file() else None

  def _validate_change_targets(self, spec_path: str,
                               raw_targets: list[str]) -> tuple[list[str], list[str]]:
    """
    Partition a change spawn's raw design-cascade targets into resolvable and unresolvable sets.

    Args:
      spec_path: The spawning change's product `spec_path`.
      raw_targets: `<category>/<slug>` tokens from the routing decision's `targets=` field.

    Returns:
      Two-tuple `(valid, invalid)` of raw token strings.
    """
    valid: list[str] = []
    invalid: list[str] = []
    for raw in raw_targets:
      if self._resolve_change_target(spec_path, raw) is not None:
        valid.append(raw)
      else:
        invalid.append(raw)
    return valid, invalid

  def _write_spec_targets(self, folder_note: Path, valid_targets: list[str]) -> None:
    """
    Write a change's resolved design-cascade targets into its status folder-note frontmatter.

    Args:
      folder_note: Absolute path to the change's `<slug>/<slug>.md`.
      valid_targets: `<category>/<slug>` tokens confirmed to resolve to real assets.
    """
    text = folder_note.read_text()
    _, fm_end = _parse_frontmatter(text)
    fm_text = _set_fm_list(text[:fm_end], SpecTargetsKey.TARGETS, valid_targets)
    folder_note.write_text(fm_text + text[fm_end:])

  def _write_reference_targets(self, resolved_paths: list[str]) -> None:
    """
    Write the request's resolved `reference` decision targets into its own frontmatter.

    Reuses `spec_targets` — the same list-typed key a change's design-cascade writes on its own
    folder-note (`_write_spec_targets` above) — rather than a second mechanism, per playbook
    Chapter 7 / `docs/tasks/lazycortex-specs.upstream.md` § 10.

    Guarantees:
      - The referenced asset's own doc and folder-note are never touched — no doc edit, no
        `spec_source_requests` attribution, no review opened. The link lives only on the
        request file's own `spec_targets`.

    Args:
      resolved_paths: Repo-relative folder-note paths (wikilink form, no `.md` suffix) the
        `reference` decision named — every one already confirmed to resolve to a real asset by
        `_resolve_attach_folder_note`.
    """

    # Contract:
    # A `reference` routing decision touches NOTHING on the referenced asset — no doc edit, no
    # `spec_source_requests` attribution, no review opened. The link lives ONLY on the request
    # file's own `spec_targets`.

    text = self.file_path.read_text()
    _, fm_end = _parse_frontmatter(text)
    fm_text = _set_fm_list(text[:fm_end], SpecTargetsKey.TARGETS, resolved_paths)
    self.file_path.write_text(fm_text + text[fm_end:])

  def _cancel_active_job(self, job_info: dict) -> bool:
    """
    Cancel a feature's live expert job via the `lazycortex-core cancel-job` CLI.

    Unlike a best-effort follow-up, a caller cannot treat this as fire-and-forget: a False
    return means the job may still be running and must be handled accordingly rather than
    letting the rollback proceed.

    Args:
      job_info: The tracked active-job marker (`checkbox` / `expert` / `job_id`).

    Returns:
      True when the CLI exits zero (the job is cancelled or was already terminal); False on a
      non-zero exit, meaning the job may still be live.
    """
    cli = _resolve_sibling_cli(_K.CLI_LAZYCORTEX_CORE)
    env = os.environ.copy()
    env[_K.ENV_REPO_ROOT] = str(self.repo)
    res = subprocess.run(
        [ str(cli), "cancel-job" ],
        input = json.dumps({
            "expert": job_info.get(JobMarker.EXPERT),
            "job_id": job_info.get(JobMarker.JOB_ID),
        }),
        capture_output = True,
        text = True,
        cwd = str(self.repo),
        env = env,
        check = False,
    )
    return res.returncode == 0

  def _stop_review_best_effort(self, doc_path: Path) -> None:
    """
    Stop review, best-effort, on a sibling doc about to be dropped.

    Safe to call unconditionally, whether or not the doc was ever opened into review; any
    failure degrades to a silent skip, since the doc is about to be deleted regardless.

    Args:
      doc_path: Absolute path to the `architecture.md` / `code-plan.md` / `test-plan.md` sibling
        being dropped.
    """
    try:
      subprocess.run(
          [ str(self.review_cli), "stop", str(doc_path.resolve()) ],
          capture_output = True, text = True, cwd = str(self.repo),
          timeout = _K.REVIEW_STOP_TIMEOUT_S, check = False,
      )
    # waiver: fire-and-forget follow-up — the sibling doc is being dropped regardless of its
    # review state; ANY stop failure (CLI crash, timeout) must degrade to a silent skip, never raise
    except (OSError, subprocess.SubprocessError):
      pass

  def _rollback_pre_launch_ladder(self, folder_note: Path, drop_docs: list[str]) -> None:
    """
    Roll a feature's implementation ladder back to the pre-launch state.

    Enacted when an attach request lands on a not-yet-halted feature whose ladder has already
    started but has not yet launched implementation (the caller refuses to call this at all on
    an already-halted asset). On success the feature ends in the same gate state as one that
    never started its ladder. Every failure halts the asset (a half-dropped ladder — job
    cancelled, pre-launch siblings gone, but the gates never actually flipped — is worse than an
    intact one) and aborts the whole apply run without proceeding to the attach seed, whether
    the failure is a job that never confirmed cancelled, a pre-launch sibling surviving its own
    deletion, or a gate flip refused outright by a cancelled asset after the earlier steps
    already ran.

    Args:
      folder_note: Absolute path to the feature's `<slug>/<slug>.md`.
      drop_docs: Bare filenames the attach decision's own `drop=` field named. An empty list
        rolls the gates back and leaves every file on disk — which documents a rollback removes
        is the router's decision, not a fixed ladder this worker knows.
    """
    asset_dir = folder_note.parent

    # Step 1a — read the tracked job off the runtime sidecar; the folder-note carries no marker.
    job_info = spec_job_markers.read(self.repo, folder_note)[JobMarker.ACTIVE_JOB]
    if isinstance(job_info, dict):
      # Step 1b — a live expert job must be cancelled before anything else touches the ladder.
      # guard: cancel-job could not confirm the job is dead — a half-dropped ladder is worse
      # than an intact one, so halt the asset and abort rather than continue past a live job
      if not self._cancel_active_job(job_info):
        flip_gate.halt_asset(asset_dir, HaltReason.PLAN_DROP_PARTIAL)
        _fail(_K.CAT_LOGICAL,
              f"pre-launch rollback halted on {asset_dir.name}: cancel-job did not confirm "
              "the active job is no longer live")

      # Step 1c — the job is confirmed dead, so its stale marker comes off the sidecar.
      spec_job_markers.update(self.repo, folder_note, { JobMarker.ACTIVE_JOB: None })

    # Step 2 — best-effort review stop on each pre-launch sibling before it is deleted.
    ladder_siblings = [ asset_dir / name for name in drop_docs ]
    for sibling in ladder_siblings:
      if sibling.is_file():
        self._stop_review_best_effort(sibling)

    # Step 3 — drop the pre-launch siblings from the worktree; a survivor means a half-dropped ladder.
    # Deleted paths are named explicitly to the first Step 4 commit below, rather than staged
    # here for whichever commit happens to run next.
    deleted_siblings: list[Path] = []
    for sibling in ladder_siblings:
      if sibling.exists():
        try:
          sibling.unlink()
        # a failed unlink (e.g. a non-empty directory in the file's place) is diagnosed by the
        # existence re-check right below, not by the exception itself
        except OSError:
          pass
        # guard: the sibling survived its own deletion attempt — halt rather than proceed
        # to flip gates over a ladder that is only partly dropped; any sibling already deleted
        # this same pass rides into this halt's commit too, named explicitly
        if sibling.exists():
          flip_gate.halt_asset(asset_dir, HaltReason.PLAN_DROP_PARTIAL, extra_paths = deleted_siblings)
          _fail(_K.CAT_LOGICAL,
                f"pre-launch rollback halted on {asset_dir.name}: {sibling.name} did not unlink")
        deleted_siblings.append(sibling)

    # Step 4 — flip every gate from spec_plan_done onward back to false, unconditionally. Only
    # the first flip's commit carries the Step 3 deletions — each commit names its own paths.
    for gate_index, gate in enumerate(_ROLLBACK_GATES):
      result = flip_gate.flip_gate(
          asset_dir, gate, off = True, auto = True, reason = _K.ROLLBACK_GATE_OFF_REASON,
          extra_paths = deleted_siblings if gate_index == 0 else None,
      )
      # guard: a cancelled asset refuses every flip (on or off) and mutates nothing — the job
      # is already cancelled and the pre-launch siblings already gone, so continuing silently would
      # leave the gates lying about a ladder that no longer exists
      if result.get(FlipResult.STATUS) == FlipResult.REFUSED:
        # waiver: "reason" mirrors flip_gate.flip_gate's own untyped result-dict key (see
        # flip_gate.py's refusal returns) — no FlipResult constant names it
        refused_reason = result.get("reason")
        # by this point Steps 1-3 already cancelled the job and deleted the pre-launch siblings —
        # a refused flip still leaves that half-done, exactly like the Step 1b / Step 3
        # failures above, so it halts the same way instead of aborting into a dirty tree; the
        # deletions ride into this halt's commit whether or not an earlier flip already
        # committed them (best-effort staging drops what has nothing left to stage)
        flip_gate.halt_asset(asset_dir, HaltReason.PLAN_DROP_PARTIAL, extra_paths = deleted_siblings)
        _fail(_K.CAT_LOGICAL,
              f"pre-launch rollback refused on {asset_dir.name}: {gate} flip was refused "
              f"({refused_reason})")

  def _attach_to_folder_note(self, folder_note: Path, description: str,
                             request_display: str, *, is_spawn: bool) -> list[Path]:
    """
    Seed the entity's primary doc with the router's per-target description.

    Also keeps the doc's source-request attribution current, so the doc and its folder-note
    both reflect that this request populated them.

    Args:
      folder_note: Absolute path to `<slug>/<slug>.md`.
      description: Router-authored description for this target; empty when the router left
        none, or when no structured routing-decision block was present at all.
      request_display: Display gloss used in the `## Requests` and folder-note bullets.
      is_spawn: True for a just-scaffolded target, seeding the primary doc's own draft content;
        False for an existing attach target, seeding an attention-block delta instead.

    Returns:
      List of authored docs that were populated (used to open review on each).
    """
    kind = _Attach.kind_from_folder_note(folder_note)
    # the product's own declarations decide the start doc — a type declared only by this product
    # would otherwise silently fall back to the shipped default
    primary = _Attach.primary_doc_for_kind(kind, self._record_for_note(folder_note))
    primary_path = folder_note.parent / primary
    seed = description.strip() or _K.FALLBACK_DESCRIPTION
    populated: list[Path] = []
    if primary_path.is_file():
      if is_spawn:
        changed_body = _Attach.seed_body_content(primary_path, seed)
      else:
        changed_body = _Attach.append_attention_block(primary_path, seed)
      changed_sources = _Attach.ensure_source_request(
          primary_path, self.request_wikilink, request_display,
      )
      if changed_body or changed_sources:
        populated.append(primary_path)
    _FolderNote.append_source_request(folder_note, self.request_wikilink, request_display)
    return populated

  def _open_review(self, doc_path: Path, *, verb: str = "start") -> None:
    """
    Open a review cycle on a populated doc via the `lazycortex-review` CLI.

    Args:
      doc_path: Absolute path to the populated authored doc.
      verb: The review CLI subcommand to invoke — `start` for a fresh opening writer round
        (the default, used by a spawn's draft seed and a plain attach's attention delta), or
        `submit` to skip that round when the doc already carries prior content (used after a
        pre-launch ladder rollback re-opens an already-drafted `design.md`).
    """
    res = subprocess.run(
        [ str(self.review_cli), verb, str(doc_path) ],
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False,
    )
    # guard: review-start/submit is idempotent — non-zero exit on already-open is benign;
    # surface only when stderr names an unexpected failure
    if res.returncode != 0 and _K.REVIEW_START_IDEMPOTENT_MARK not in (res.stderr or "").lower():
      _fail(_K.CAT_LOGICAL,
            f"lazycortex-review {verb} failed on {doc_path}: "
            f"exit={res.returncode} stderr={res.stderr.strip()[:240]}")

  def _stamp_request_file(self, *, request_class: str, request_status: str,
                          resolved_wikilinks: list[str], reject_reason: str | None) -> None:
    """
    Apply the request file's terminal mutations: frontmatter + status callout + Routing strip.

    Args:
      request_class: Eight-value enum verdict.
      request_status: `accepted` or `rejected`.
      resolved_wikilinks: Wikilink paths to enumerate in the success callout body.
      reject_reason: Optional one-line rejection reason.
    """
    text = self.file_path.read_text()
    _, fm_end = _parse_frontmatter(text)
    fm_text = text[:fm_end]
    body = text[fm_end:]
    fm_text = _stamp_request_terminal(
        fm_text, request_class = request_class, request_status = request_status,
    )
    body = _strip_routing(body)
    body = _strip_prior_status_callout(body)
    accepted = request_status == _K.STATUS_ACCEPTED
    callout = _format_status_callout(
        accepted = accepted, wikilinks = resolved_wikilinks, reason = reject_reason,
    )
    body = _insert_status_callout(body, callout)
    self.file_path.write_text(fm_text + body)

  def _touched_paths(self, inbox: Path) -> list[str]:
    """
    Collect the repo-relative paths this apply pass is responsible for.

    Args:
      inbox: The requests folder-note, whose container stats are refreshed on every pass.

    Returns:
      Repo-relative path strings — the request file, the inbox note when present, each
      populated document, each attach target, and the whole folder of each spawned asset.
    """
    paths = [ self.file_path ]
    if inbox.is_file():
      paths.append(inbox)
    paths.extend(self.populated_docs)
    paths.extend(self.attach_folder_notes)
    # a spawn scaffolds a whole asset folder, so the folder — not just its note — is the unit
    paths.extend(note.parent for note in self.spawn_folder_notes)
    # a group folder-note the scaffolder seeded is a sibling of the asset folder, never inside it
    paths.extend(self.spawn_group_notes)

    # the same path can arrive from several sources, and git rejects a duplicated pathspec
    seen: list[str] = []
    for path in paths:
      rel = str(path.resolve().relative_to(self.repo))
      if rel not in seen:
        seen.append(rel)
    return seen

  def _commit(self, *, subject: str) -> None:
    """
    Stage the paths this pass touched and commit them under the bot identity in one atomic step.

    Args:
      subject: One-line commit subject describing the staged diff.
    """
    # the inbox stats line goes stale on every apply, so refresh it before it joins the commit set
    inbox = spec_content_root(find_settings_root(self.file_path.parent)) / _K.REQUESTS_DIR / _K.REQUESTS_NOTE
    if inbox.is_file():
      apply_container_stats(inbox)

    # the resolve-walk behind the touched set is not free, and the same set feeds the repaint,
    # the staging pathspec, and the commit pathspec below
    touched_paths = self._touched_paths(inbox)

    # fold the touched notes' icon repaint into this same commit so no separate icons commit
    # follows; the repaint op itself skips non-markdown paths
    touched_paths.extend(iconize_inline.repaint_paths(self.repo, touched_paths))

    # never `git add -A` — the worktree belongs to the operator and may carry unrelated work
    add_res = subprocess.run(
        [ _K.GIT, "add", "--", *touched_paths ],
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False,
    )
    # guard: staging failed, the commit below would snapshot the wrong set
    if add_res.returncode != 0:
      _fail(_K.CAT_LOGICAL,
            f"git add failed: exit={add_res.returncode} stderr={add_res.stderr.strip()[:240]}")

    # an idempotent re-run on terminal state stages nothing, so ask git whether anything landed
    status_res = subprocess.run(
        [ _K.GIT, "diff", "--cached", "--quiet" ],
        cwd = str(self.repo),
        check = False,
    )
    # guard: empty staged diff — nothing to commit on this apply pass
    if status_res.returncode == 0:
      return

    # commit under the request bot's identity so the operator's authorship stays untouched
    commit_res = subprocess.run(
        [
            _K.GIT,
            "-c", f"user.name={self.author_name}",
            "-c", f"user.email={self.author_email}",
            "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", subject, "--", *touched_paths,
        ],
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False,
    )
    # guard: a failed commit leaves the tree dirty and would halt the daemon silently
    if commit_res.returncode != 0:
      _fail(_K.CAT_LOGICAL,
            f"git commit failed: exit={commit_res.returncode} "
            f"stderr={commit_res.stderr.strip()[:240]}")

  def run(self) -> int:
    """
    Drive one apply transition on the request file.

    Returns:
      Exit code: `0` on success or idempotent terminal-state skip; `1` on logical error.
    """
    # the frontmatter status decides whether this pass has anything left to do
    text = self.file_path.read_text()
    values, fm_end = _parse_frontmatter(text)
    status = values.get(_K.REQUEST_STATUS)
    # guard: terminal-state idempotence (md-scan filter normally excludes these,
    # but a same-tick race could still hand us one)
    if status in ( _K.STATUS_ACCEPTED, _K.STATUS_REJECTED ):
      print(json.dumps({ "outcome": _K.OUTCOME_SUCCESS, "skip": _K.OUTCOME_TERMINAL_SKIP }))
      return 0

    # the `# Routing` section the router wrote is the whole instruction set for this pass
    body = text[fm_end:]
    cls, spawn_targets, attach_targets, routing_text = _parse_routing(body)
    request_class = cls or values.get(_K.REQUEST_CLASS) or _K.CLASS_UNKNOWN

    # the identity-only spawn/attach lists above carry no descriptions or cascade targets —
    # pull those from the rich parse of the same structured block, when one is present;
    # `reference` targets and a spawn line's own `product=` field are parsed separately, via
    # `_parse_reference_targets` and `_parse_spawn_products` (see the `# Decision:` note on
    # `_parse_routing_decision_rich`)
    decision_block = _extract_decision_block(routing_text)
    spawn_desc: dict[tuple[str, str], str] = {}
    spawn_cascades: dict[tuple[str, str], list[str]] = {}
    attach_desc: dict[str, str] = {}
    # a reference target's own description is never seeded anywhere — unlike spawn/attach, no
    # doc is ever written for it, so only the resolved path itself is kept
    reference_targets: list[str] = []
    spawn_product: dict[tuple[str, str], str] = {}
    spawn_docs: dict[tuple[str, str], list[tuple[str, str]]] = {}
    spawn_paths: dict[tuple[str, str], str] = {}
    spawn_tools: dict[tuple[str, str], list[str]] = {}
    attach_drops: dict[str, list[str]] = {}
    if decision_block is not None:
      spawn_rich, attach_rich = _parse_routing_decision_rich(
          decision_block, known_kinds = self._known_kinds())
      for kind, slug, description, targets in spawn_rich:
        spawn_desc[( kind, slug )] = description
        spawn_cascades[( kind, slug )] = targets
      for path, description in attach_rich:
        attach_desc[path] = description
      reference_targets = [ path for path, _description in _parse_reference_targets(decision_block) ]
      spawn_product = _parse_spawn_products(decision_block)
      spawn_docs = _parse_spawn_docs(decision_block)
      spawn_paths = _parse_spawn_paths(decision_block)
      spawn_tools = _parse_spawn_tools(decision_block)
      attach_drops = _parse_attach_drops(decision_block)
    # Display gloss must come from the request's OWN H1, not from `# Routing` (which is the
    # first H1 in the raw body before strip). Read from `_request_content_block` which already
    # filters out `# Routing` and `# History` sections.
    request_display = _request_h1_title(_request_content_block(body))

    # a routing section naming no target of any kind has nothing to apply, so the request is
    # rejected outright — a `reference`-only decision is NOT this case: it is a full accept
    # (playbook Chapter 7 / upstream § 10 — a request made up of reference targets alone is
    # still a fully accepted request)
    resolved_wikilinks: list[str] = []
    if not spawn_targets and not attach_targets and not reference_targets:
      self._stamp_request_file(
          request_class = request_class,
          request_status = _K.STATUS_REJECTED,
          resolved_wikilinks = [],
          reject_reason = _K.REJECT_REASON_DEFAULT,
      )
      self._commit(
          subject = f"apply: stamp rejected on {self.file_path.relative_to(self.repo)}",
      )
      print(json.dumps({ "outcome": _K.OUTCOME_SUCCESS, "result": _K.STATUS_REJECTED,
                         "request_class": request_class }))
      return 0

    # a spawn target scaffolds its asset first, then gets seeded with its own draft content
    for kind, slug in spawn_targets:
      folder_note, spec_path = self._spawn(
          kind, slug, product = spawn_product.get(( kind, slug )),
          docs = spawn_docs.get(( kind, slug )), path = spawn_paths.get(( kind, slug ), ""),
          tools = spawn_tools.get(( kind, slug )))
      rel = folder_note.relative_to(self.repo).with_suffix("")
      resolved_wikilinks.append(str(rel))
      description = spawn_desc.get(( kind, slug ), "")
      populated = self._attach_to_folder_note(
          folder_note, description, request_display, is_spawn = True,
      )
      self.populated_docs.extend(populated)
      self.spawn_folder_notes.append(folder_note)
      # a change spawn may cascade its design onto existing assets via routing's targets= field
      if kind == _K.CHANGE_KIND:
        raw_targets = spawn_cascades.get(( kind, slug ), [])
        if raw_targets:
          valid, invalid = self._validate_change_targets(spec_path, raw_targets)
          for raw in invalid:
            self.warnings.append(
                f"spec_targets: '{raw}' does not resolve to an existing asset "
                f"(change '{slug}')",
            )
          if valid:
            self._write_spec_targets(folder_note, valid)

    # an attach target already exists, so only the attention-block delta applies — but a feature
    # whose ladder already started rolls back to the pre-launch state first (the rule that, before
    # code is launched, a request edits the spec directly via gate rollback plus a new review);
    # a launched feature must never reach this path at all (the router should have
    # spawned a change instead, so a launched target here is a worker-side refusal, not a rollback)
    for target in attach_targets:
      folder_note = self._resolve_attach_folder_note(target)
      fm_values, _ = _parse_frontmatter(folder_note.read_text())
      # guard: a cancelled asset refuses every attach outright, before any rollback runs — a
      # rollback would destroy the pre-launch siblings and only discover the refusal at its own
      # step 4, and a plain (non-rollback) attach would otherwise reopen review on a dead asset
      if fm_values.get(Gate.SPEC_CANCELLED, "").strip().lower() == BOOL_TRUE:
        _fail(_K.CAT_LOGICAL,
              f"attach target '{target}' is cancelled — automation is refused")
      # guard: all automation stays off a halted asset until an operator resolves it by hand,
      # regardless of ladder state — a plain attach must not seed + reopen review either
      if fm_values.get(SpecHaltKey.HALTED, "").strip().lower() == BOOL_TRUE:
        _fail(_K.CAT_LOGICAL,
              f"attach target '{target}' is halted — automation is refused until an "
              "operator resolves it")

      # a feature whose ladder already started rolls back to the pre-launch state before the
      # attach seed runs; every other kind (and a not-yet-started feature) attaches plainly
      rolled_back = False
      if _Attach.kind_from_folder_note(folder_note) == _K.FEATURE_KIND:
        # guard: a launched feature must never be silently attached — the router should have
        # spawned a change instead, so this is a refusal, not a rollback
        if _is_launched_feature(fm_values, folder_note):
          _fail(_K.CAT_LOGICAL,
                f"attach target '{target}' is a launched feature — routing must spawn a "
                "change instead of attaching")
        if _has_ladder_started(fm_values, folder_note):
          # not halted (checked above) — safe to roll the ladder back before the attach seed runs
          self._rollback_pre_launch_ladder(folder_note, attach_drops.get(target, []))
          rolled_back = True

      # the attach-seed flow itself is unconditional — a rollback only changes what state it
      # seeds onto, never whether it runs
      resolved_wikilinks.append(target)
      description = attach_desc.get(target, "")
      populated = self._attach_to_folder_note(
          folder_note, description, request_display, is_spawn = False,
      )
      self.populated_docs.extend(populated)
      # a rolled-back feature's primary doc already carries prior content, so it re-enters
      # review via `submit` (skip the opening writer round) instead of `start`
      if rolled_back:
        self.submit_docs.extend(populated)
      self.attach_folder_notes.append(folder_note)

    # a reference target registers only a link — no scaffold, no seed, no review, and the
    # target's own doc/folder-note is never touched (playbook Chapter 7 / upstream § 10);
    # existence is still validated, reusing the same resolver an attach target uses (any
    # unresolvable target aborts the whole run via `_fail`, so every survivor here is real)
    for target in reference_targets:
      self._resolve_attach_folder_note(target)
      resolved_wikilinks.append(target)
    if reference_targets:
      self._write_reference_targets(reference_targets)

    # every doc that received content enters the review loop
    for doc in self.populated_docs:
      self._open_review(doc, verb = "submit" if doc in self.submit_docs else "start")

    # the stamp records where the request landed, and the commit makes the whole pass atomic
    self._stamp_request_file(
        request_class = request_class,
        request_status = _K.STATUS_ACCEPTED,
        resolved_wikilinks = resolved_wikilinks,
        reject_reason = None,
    )
    rel_path = self.file_path.relative_to(self.repo)
    self._commit(
        subject = f"apply: stamp accepted + strip Routing on {rel_path}",
    )

    # the counts let the calling routine report what this pass produced
    print(json.dumps({
        "outcome": _K.OUTCOME_SUCCESS,
        "result": _K.STATUS_ACCEPTED,
        "request_class": request_class,
        "spawn_count": len(self.spawn_folder_notes),
        "attach_count": len(self.attach_folder_notes),
        "populated_count": len(self.populated_docs),
        "warnings": self.warnings,
    }))
    return 0


def main(argv: list[str]) -> int:
  """
  Run the `apply-request` subcommand against one request file.

  Args:
    argv: Subcommand argv tail (positional `<file>` + optional `--author-*` flags).

  Returns:
    Process exit code: `0` on success / idempotent skip, `1` on logical error,
    `2` on argparse failure / missing file.
  """
  parser = argparse.ArgumentParser(prog = _K.PROG)
  parser.add_argument(_K.ARG_FILE, type = Path)
  parser.add_argument(_K.ARG_AUTHOR_NAME, default = _K.BOT_NAME_DEFAULT)
  parser.add_argument(_K.ARG_AUTHOR_EMAIL, default = _K.BOT_EMAIL_DEFAULT)
  args = parser.parse_args(argv)
  file_path: Path = args.file
  # argparse hands relative paths straight through, so resolve to absolute here
  if not file_path.is_absolute():
    file_path = file_path.resolve()
  # guard: filesystem path idiom — markdown file extension check
  if not file_path.exists() or file_path.suffix.lower() != _K.MD_SUFFIX:
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2
  apply = _Apply(
      file_path = file_path,
      author_name = args.author_name,
      author_email = args.author_email,
  )
  return apply.run()


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
