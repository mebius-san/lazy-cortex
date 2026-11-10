"""
Deterministic apply-transition worker — the Python primitive backing the
`lazy-spec.request-apply` md-scan routine.

Replaces the LLM-driven `lazy-spec.request-apply` agent. Reads the resolved
routing prose from a post-finalize request file, enacts the named
attach / spawn / reference targets — a spawn scaffolds the asset folder
and its folder-note alone (documents come later, from the coordinator's
launch checkboxes), an attach records the request's attribution on the
existing target's primary doc, a reference registers a link only —
opens a review cycle on every populated doc, then stamps terminal markers
(`request_class`, `request_status`, `request/<status>` mirror tag,
status callout) and strips the `# Routing` section. Atomic commit
under the `lazy-spec.request-apply` bot identity.

Routing prose grammar (parsed leniently — the router agent emits free
text, so the patterns below match the conventional shapes):

- **Class verdict** — the word `class` (case-insensitive) followed by a
  colon or a bar (`|`) separator, anywhere in the routing section, then the
  verdict, with optional asterisks / backticks around it (`Class: <verdict>`,
  `**Class:** <verdict>`, `Class | <verdict>`).
  Verdict is one of `feature` / `change` / `bug` / `task` / `spec` /
  `plan` / `feedback` / `unknown`.
- **Spawn target** — a `Target:` / `Spawn:` line that mentions any shipped
  asset type (every type `asset_types.builtin_defaults()` ships, e.g.
  `feature` / `change` / `bug` / `content` / `research`) or any asset type
  a product declares, and a slug in backticks (the prose form the router
  emits, e.g. "Spawn one cross-cutting change entity — `slug`").
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

- `path=<dir>` on a spawn line — the folder under the product's
  `spec_path` the asset lands in; absent falls back to the asset
  type's own `default_path`.
- `tools=<tool>[,...]` on a spawn line — the tools the asset is
  realised and checked with; absent leaves them undetermined for the
  coordinator to settle on its own wake.
- `product=<key>` on a spawn line — the spawning product, the sole way
  one decision fans a request out across several products in one apply
  run.
- `targets=<path>[,...]` on a `change`-kind spawn line — design-cascade
  targets, each a product-relative path token of any depth.
- `drop=<name>[,...]` on an attach line — the sibling documents the attach
  deletes from the attached asset, each a bare sibling filename (no path
  separator, no `:`) that is neither the asset's status folder-note nor its start
  document, matched without regard to letter case; absent or empty cancels and
  deletes nothing. `drop=` is refused on a level-document target, which is
  never dropped.

A fourth verb, `spawn-product key=<key> path=<spec_path> :: <description>`,
registers a whole design-only product: `key=`, `path=` and the `::` separator
are all mandatory. A well-formed line (one carrying `::`) that carries any field other than
`key=` / `path=` fails the run before anything is written; a line without `::` is skipped. Enacting one
writes the `products[<key>]` record, creates the spec folder, backfills the
product level note, seeds its `vision.md`, stamps the request's attribution on
that document and opens its review — all inside the one apply commit.

An `attach` target naming a level document (`vision.md` / `design.md` /
`tech.md` sitting directly in the content root or in a registered product's
`spec_path`, plus `use-cases.md` / `ui-design.md` at a product root) is stamped on the
document itself: a level has no status folder-note above its documents, so none is looked for.

A spawn line's asset type is validated against the shipped
declarations plus whatever every registered product declares, so an
operator's own type is admissible without touching this worker. The two
level roles are never admissible — a product or a catalog is registered
through `spawn-product`, never spawned as an asset kind.
A `reference <path>` line names an existing asset the router judges
already implements the request — registers a link via `spec_targets`
on the request itself, spawns/attaches nothing.

Inputs read:

- `<repo>/.claude/lazy.settings.json[products]` — to map a product key
  to its `spec_path` (used during spawn-target enaction to resolve the
  folder-note path the scaffolder writes).
- The post-finalize request file passed as the positional argument.

Outputs written:

- Spawn targets: folder + folder-note scaffolds via the
  `scaffold-asset` subprocess (no documents).
- Each attach target's primary doc: `spec_source_requests` frontmatter
  + `## Requests` projection inside `# Sources`.
- Each change spawn naming design-cascade targets: `spec_targets`
  frontmatter on its status folder-note.
- Reference targets: `spec_targets` frontmatter on the request file
  itself — never on the referenced asset, whose doc and folder-note
  stay untouched.
- Each populated doc's folder-note: `## Source requests` bullet.
- An attach target whose `drop=` field names documents: the asset's live
  expert job cancelled via the `lazycortex-core cancel-job` CLI and its
  `active_job` marker cleared, review stopped on a best-effort basis on each
  named sibling, then the siblings deleted from the worktree. The deleted
  paths still tracked by git are staged in the run's single commit. An attach
  never rolls back and never flips a gate, whatever the asset type.
- Before any document is dropped or job cancelled, every attach and reference
  target is resolved, and every attach target is also checked (cancelled /
  halted refusals); a reference target only has to resolve and is never refused
  as cancelled or halted. Every `drop=` name must be a bare sibling filename (no
  path separator, no `:`) that is neither the asset's status folder-note nor its
  start document, matched without regard to letter case, and `drop=` is
  refused on a level-document target (a level document is never dropped). An
  unresolvable or refused target, an invalid `drop=` name, or a `drop=` on a
  level-document target aborts the run with nothing dropped.
- On a `drop=` failure: once a running job is confirmed cancelled, any failure
  before the asset's first deletion (clearing the job's tracking record,
  reading the folder, a surviving named sibling, any other error) halts the
  asset via `flip_gate.halt_asset` with `PLAN_DROP_PARTIAL` exactly once before
  the run aborts, and so does a job whose cancel is not confirmed. With no job
  cancelled and nothing deleted, only a surviving named sibling halts the
  asset; any other failure (e.g. the core CLI cannot be resolved) aborts the
  run without a halt. After the asset's first deletion its own drop halts
  nothing: the run-level handler halts each asset that lost something in the
  pass (`PLAN_DROP_PARTIAL`), for any exception (another target's drop, an
  error later in the same asset's drop, the attribution, a reference write,
  the review opening, the request stamp or the commit). An asset whose own
  folder lost documents is halted with those deletions; an asset whose live
  job was cancelled with nothing deleted is halted with none. Never an outer
  or nested asset. Every target's drop runs before any target's attribution.
  A non-`SystemExit` error propagates unchanged after the halt.
- Each populated doc: review cycle opened via the `lazycortex-review`
  CLI's `start` subcommand (opening writer round), never `submit`.
- Request file: `request_class` / `request_status` frontmatter,
  `request/<status>` mirror tag, status callout above first H1,
  `# Routing` stripped.
- One atomic commit under the bot identity covering every path.

Exit codes: `0` on success (including idempotent no-op on a
terminal-status file); `1` on a logical error written to stdout as a
JSON `error` object; `2` when the request file argument is missing or is
not a markdown file.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import NoReturn


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from summary_render import apply_container_stats  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_paths import (  # noqa: E402
    find_settings_root, read_text, require_plugin_cli, resolve_core_cli, spec_content_root, write_text_atomic,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    BOOL_TRUE,
    LEVEL_ROLES,
    Gate,
    HaltReason,
    JobMarker,
    LevelDoc,
    PlanReview,
    Section,
    SpecHaltKey,
    SpecTargetsKey,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import asset_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import catalog_note  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import iconize_inline  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_markers import Markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The shipped types' folders, for a prose path-form spawn target parsed with no settings at hand.
# `feature` (and every other type whose `default_path` is the product root itself) contributes no
# folder of its own — only a type that still owns a dedicated default folder belongs here.
_SHIPPED_FOLDER_KINDS = { "changes": "change", "bugs": "bug" }


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
    TAGS: Frontmatter key holding a file's tag list.
    SPEC_SOURCE_REQUESTS: Frontmatter key listing the requests that populated a doc.
    STATUS_DRAFT: The pre-terminal `request_status` value.
    STATUS_ACCEPTED: The accepted terminal `request_status` value.
    STATUS_REJECTED: The rejected terminal `request_status` value.
    CLASS_UNKNOWN: The unclassified `request_class` value.
    ROLE_REQUEST: The canonical `spec_role` value for a request file.
    TAG_PREFIX: Prefix of the request-status mirror tag.
    DESIGN_MD: Filename of the design doc.
    BUG_MD: Filename of the bug-layout design-side doc.
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
    DECISION_VERB_SPAWN_PRODUCT: The routing-decision verb registering a whole design-only product.
    DECISION_KEY_PREFIX: Prefix marking the mandatory `key=` field naming a spawned product's key.
    SETTINGS_SPEC: Settings section holding the vault-wide spec configuration.
    LANGUAGE: Settings key naming a product's authoring language.
    ICON: Settings key naming a product's explorer icon.
    ICON_PRODUCT: The default explorer icon every registered product carries.
    NOTE_KEY: Result key under which `catalog-note backfill` reports the note it wrote.
    CLI_SETTINGS_GET: The `lazycortex-core` subcommand reading one settings section.
    CLI_SETTINGS_SET: The `lazycortex-core` subcommand persisting one settings section.
    CLI_SEED_DOC: The `lazycortex-specs` subcommand seeding one document beside a folder-note.
    CLI_CWD_FLAG: The flag naming the repo a sibling CLI resolves settings against.
    SEED_DOC_FLAG: The `seed-doc` flag naming the produced document.
    VISION_DOC_TOKEN: The `<name>:<type>` token seeding a level's own vision document.
    DECISION_DESC_SEP: Token separating a routing-decision line's target spec from its free-text description.
    DECISION_TARGETS_PREFIX: Prefix marking the optional design-cascade `targets=` field on a change-spawn line.
    DECISION_PRODUCT_PREFIX: Prefix marking the optional spawning-product `product=` field on a spawn line.
    DECISION_PATH_PREFIX: Prefix marking the optional `path=` field naming a spawn's folder.
    DECISION_TOOLS_PREFIX: Prefix marking the optional `tools=` field naming a spawn's tools.
    DECISION_DROP_PREFIX: Prefix marking the optional `drop=` field naming an attach's dropped docs.
    SCAFFOLD_PATH_FLAG: The `scaffold-asset` flag naming the folder the asset lands in.
    SCAFFOLD_GROUP_NOTE_KEY: The scaffold result key naming the group folder-note it seeded.
    SPEC_TOOLS_KEY: Frontmatter key listing the tools the asset is realised and checked with.
    ASSET_TYPES: Settings key holding a product's own asset-type declarations.
    SOURCE_REQUESTS_H2: Sub-heading marking a folder-note's source-requests list.
    HISTORY_H2: Sub-heading marking a doc's history log.
    CALLOUT_SUCCESS: The callout text stamped on an accepted request.
    CALLOUT_WARNING: The callout text stamped on a rejected request.
    STATUS_TAG_PATTERN: Regex pattern matching an existing status tag to replace.
    REJECT_HINT: Recovery-hint text appended to a rejection callout.
    REJECT_REASON_DEFAULT: Default rejection reason when routing names no target.
    GIT: The git executable name.
    PROG: CLI program name shown in `--help` output.
    CLI_LAZYCORTEX_SPECS: Plugin name used to resolve the `lazycortex-specs` CLI.
    CLI_LAZYCORTEX_REVIEW: Plugin name used to resolve the `lazycortex-review` CLI.
    ENV_REPO_ROOT: Env var passed to the `lazycortex-core` CLI naming the repo it should
      resolve settings and job storage against.
    REVIEW_STOP_TIMEOUT_S: Seconds the best-effort `lazycortex-review stop` subprocess may run.
    MD_SUFFIX: The markdown file extension.
    BOT_NAME_DEFAULT: Default git author name for the apply-transition commit.
    BOT_EMAIL_DEFAULT: Default git author email for the apply-transition commit.
    ARG_FILE: CLI positional argument name for the request file.
    ARG_AUTHOR_NAME: CLI flag overriding the commit author name.
    ARG_AUTHOR_EMAIL: CLI flag overriding the commit author email.
    REVIEW_START_IDEMPOTENT_MARK: Substring identifying an already-active review start as a no-op.
    ERR_NO_PRODUCTS: Error message used when a spawn target needs products but none are registered.
    CAT_LOGICAL: The error category for invalid-input failures.
    OUT_OUTCOME: The stdout-envelope field carrying the outcome token.
    OUT_ERROR: The stdout-envelope field carrying a failure's own object.
    OUT_CATEGORY: The error object's field naming the failure category.
    OUT_MESSAGE: The error object's field carrying the one-line cause.
    OUT_SKIP: The stdout-envelope field naming which no-op a skip was.
    OUT_RESULT: The stdout-envelope field carrying the request's terminal verdict.
    OUT_REQUEST_CLASS: The stdout-envelope field carrying the classified request class.
    OUT_SPAWN_COUNT: The stdout-envelope field counting the assets the pass spawned.
    OUT_ATTACH_COUNT: The stdout-envelope field counting the folder-notes the pass attached to.
    OUT_POPULATED_COUNT: The stdout-envelope field counting the documents the pass stamped.
    OUT_WARNINGS: The stdout-envelope field listing the pass's non-fatal warnings.
    OUTCOME_SUCCESS: Outcome token for a completed apply transition.
    OUTCOME_ERROR: Outcome token for a failed apply transition.
    OUTCOME_TERMINAL_SKIP: Outcome token for a no-op on an already-terminal request.
    OUTCOME_NO_ROUTING_SKIP: Outcome token for a no-op on a request with no routing section.
    CLASS_ENUM: The closed set of valid `request_class` verdicts.
  """

  # Frontmatter key naming a file's spec-role discriminator.
  SPEC_ROLE = "spec_role"
  # Frontmatter key naming a request's lifecycle status.
  REQUEST_STATUS = "request_status"
  # Frontmatter key naming a request's routed classification.
  REQUEST_CLASS = "request_class"
  # Frontmatter key naming a doc's terminal review outcome.
  REVIEW_RESULT = "review_result"
  # Frontmatter key marking a doc as opted into the review loop.
  REVIEW_ACTIVE = "review_active"
  # Frontmatter key naming a doc's current review round.
  REVIEW_ROUND = "review_round"
  # Frontmatter key holding a file's tag list.
  TAGS = "tags"
  # Frontmatter key listing the requests that populated a doc.
  SPEC_SOURCE_REQUESTS = "spec_source_requests"
  # The pre-terminal `request_status` value.
  STATUS_DRAFT = "draft"
  # The accepted terminal `request_status` value.
  STATUS_ACCEPTED = "accepted"
  # The rejected terminal `request_status` value.
  STATUS_REJECTED = "rejected"
  # The unclassified `request_class` value.
  CLASS_UNKNOWN = "unknown"
  # The canonical `spec_role` value for a request file.
  ROLE_REQUEST = "request"
  # Prefix of the request-status mirror tag.
  TAG_PREFIX = "request/"
  # Filename of the design doc.
  DESIGN_MD = "design.md"
  # Filename of the bug-layout design-side doc.
  BUG_MD = "bug.md"
  # The change asset kind.
  CHANGE_KIND = "change"
  # The `.claude` directory segment.
  CLAUDE_DIR = ".claude"
  # Filename of the settings file.
  SETTINGS_FILE = "lazy.settings.json"
  # Settings key holding the product registry.
  PRODUCTS = "products"
  # Settings key naming a product's spec directory.
  SPEC_PATH = "spec_path"
  # The `.git` entry checked to detect a repo checkout.
  GIT_DIR = ".git"
  # Directory segment holding request files.
  REQUESTS_DIR = "requests"
  # Filename of the requests folder-note.
  REQUESTS_NOTE = "requests.md"
  # Heading marking a request's routing section.
  ROUTING_H1 = "# Routing"
  # Heading marking a file's history log section.
  HISTORY_H1 = "# History"
  # Opening marker of an embedded routing-decision comment.
  ROUTING_DECISION_OPEN = "<!-- routing-decision"
  # Closing marker of an embedded HTML comment.
  ROUTING_DECISION_CLOSE = "-->"
  # The routing-decision verb for a spawn target.
  DECISION_VERB_SPAWN = "spawn"
  # The routing-decision verb for an attach target.
  DECISION_VERB_ATTACH = "attach"
  # The routing-decision verb for a reference target — an existing asset the router judges already implements the
  # request; registers a link, spawns/attaches nothing.
  DECISION_VERB_REFERENCE = "reference"
  # The routing-decision verb registering a whole design-only product.
  DECISION_VERB_SPAWN_PRODUCT = "spawn-product"
  # Prefix marking the mandatory `key=` field naming a spawned product's key.
  DECISION_KEY_PREFIX = "key="
  # Token separating a routing-decision line's target spec from its free-text description.
  DECISION_DESC_SEP = "::"
  # Prefix marking the optional design-cascade `targets=` field on a change-spawn line.
  DECISION_TARGETS_PREFIX = "targets="
  # Prefix marking the optional spawning-product `product=` field on a spawn line.
  DECISION_PRODUCT_PREFIX = "product="
  # Prefix marking the optional `path=` field naming a spawn's folder.
  DECISION_PATH_PREFIX = "path="
  # Prefix marking the optional `tools=` field naming a spawn's tools.
  DECISION_TOOLS_PREFIX = "tools="
  # Prefix marking the optional `drop=` field naming an attach's dropped docs.
  DECISION_DROP_PREFIX = "drop="
  # The `scaffold-asset` flag naming the folder the asset lands in.
  SCAFFOLD_PATH_FLAG = "--path"
  # The scaffold result key naming the group folder-note it seeded.
  SCAFFOLD_GROUP_NOTE_KEY = "group_note"
  # Frontmatter key listing the tools the asset is realised and checked with.
  SPEC_TOOLS_KEY = "spec_tools"
  # Settings key holding a product's own asset-type declarations.
  ASSET_TYPES = "asset_types"
  # Settings section holding the vault-wide spec configuration.
  SETTINGS_SPEC = "spec"
  # Settings key naming a product's authoring language.
  LANGUAGE = "language"
  # Settings key naming a product's explorer icon.
  ICON = "icon"
  # The default explorer icon every registered product carries.
  ICON_PRODUCT = "LiPackage"
  # Result key under which `catalog-note backfill` reports the note it wrote.
  NOTE_KEY = "note"
  # Sub-heading marking a folder-note's source-requests list.
  SOURCE_REQUESTS_H2 = "## Source requests"
  # Sub-heading marking a doc's history log.
  HISTORY_H2 = "## History"
  # The callout text stamped on an accepted request.
  CALLOUT_SUCCESS = "[!success] Request accepted #status/accepted"
  # The callout text stamped on a rejected request.
  CALLOUT_WARNING = "[!warning] Request rejected #status/rejected"
  # Regex pattern matching an existing status tag to replace.
  STATUS_TAG_PATTERN = r"#status/\S+"
  # Recovery-hint text appended to a rejection callout.
  REJECT_HINT = "To re-open: clear request_status, clear review_result, restore review_active: true."
  # Default rejection reason when routing names no target.
  REJECT_REASON_DEFAULT = "Routing prose named no resolvable target."
  # The git executable name.
  GIT = "git"
  # CLI program name shown in `--help` output.
  PROG = "lazycortex-specs apply-request"
  # Plugin name used to resolve the `lazycortex-specs` CLI.
  CLI_LAZYCORTEX_SPECS = "lazycortex-specs"
  # Plugin name used to resolve the `lazycortex-review` CLI.
  CLI_LAZYCORTEX_REVIEW = "lazycortex-review"
  # The `lazycortex-core` subcommand reading one settings section.
  CLI_SETTINGS_GET = "settings-get"
  # The `lazycortex-core` subcommand persisting one settings section.
  CLI_SETTINGS_SET = "settings-set"
  # The `lazycortex-specs` subcommand seeding one document beside a folder-note.
  CLI_SEED_DOC = "seed-doc"
  # The flag naming the repo a sibling CLI resolves settings against.
  CLI_CWD_FLAG = "--cwd"
  # The `seed-doc` flag naming the produced document.
  SEED_DOC_FLAG = "--doc"
  # The `<name>:<type>` token seeding a level's own vision document.
  VISION_DOC_TOKEN = f"{LevelDoc.VISION}:system-vision"
  # Env var passed to the `lazycortex-core` CLI naming the repo it should resolve settings and job storage against.
  ENV_REPO_ROOT = "LAZY_REPO_ROOT"
  # Seconds the best-effort `lazycortex-review stop` subprocess may run.
  REVIEW_STOP_TIMEOUT_S = 60
  # The markdown file extension.
  MD_SUFFIX = ".md"
  # Default git author name for the apply-transition commit.
  BOT_NAME_DEFAULT = "lazy-spec.request-apply"
  # Default git author email for the apply-transition commit.
  BOT_EMAIL_DEFAULT = "lazy-spec.request-apply@bot.invalid"
  # CLI positional argument name for the request file.
  ARG_FILE = "file"
  # CLI flag overriding the commit author name.
  ARG_AUTHOR_NAME = "--author-name"
  # CLI flag overriding the commit author email.
  ARG_AUTHOR_EMAIL = "--author-email"
  # Substring identifying an already-active review start as a no-op.
  REVIEW_START_IDEMPOTENT_MARK = "already"
  # Error message used when a spawn target needs products but none are registered.
  ERR_NO_PRODUCTS = (
      "no products registered in lazy.settings.json; cannot resolve spawn target"
  )
  # The error category for invalid-input failures.
  CAT_LOGICAL = "logical"
  # The stdout-envelope field carrying the outcome token; the calling routine parses the envelope.
  OUT_OUTCOME = "outcome"
  # The stdout-envelope field carrying a failure's own object.
  OUT_ERROR = "error"
  # The error object's field naming the failure category.
  OUT_CATEGORY = "category"
  # The error object's field carrying the one-line cause.
  OUT_MESSAGE = "message"
  # The stdout-envelope field naming which no-op a skip was.
  OUT_SKIP = "skip"
  # The stdout-envelope field carrying the request's terminal verdict.
  OUT_RESULT = "result"
  # The stdout-envelope field carrying the classified request class.
  OUT_REQUEST_CLASS = "request_class"
  # The stdout-envelope field counting the assets the pass spawned.
  OUT_SPAWN_COUNT = "spawn_count"
  # The stdout-envelope field counting the folder-notes the pass attached to.
  OUT_ATTACH_COUNT = "attach_count"
  # The stdout-envelope field counting the documents the pass stamped.
  OUT_POPULATED_COUNT = "populated_count"
  # The stdout-envelope field listing the pass's non-fatal warnings.
  OUT_WARNINGS = "warnings"
  # Outcome token for a completed apply transition.
  OUTCOME_SUCCESS = "success"
  # Outcome token for a failed apply transition.
  OUTCOME_ERROR = "error"
  # Outcome token for a no-op on an already-terminal request.
  OUTCOME_TERMINAL_SKIP = "terminal-state-skip"
  # Outcome token for a no-op on a request with no routing section.
  OUTCOME_NO_ROUTING_SKIP = "no-routing-skip"
  # The closed set of valid `request_class` verdicts.
  CLASS_ENUM = ( "feature", "change", "bug", "task", "spec", "plan", "feedback", "unknown" )


def _fail(category: str, message: str) -> NoReturn:
  """
  Print a JSON error object to stdout and exit non-zero.

  Args:
    category: Error category — one of `logical` (input invalid) or `technical`
      (internal failure).
    message: Single-line human-readable cause.

  Raises:
    SystemExit: Always — exits with status `1` after printing the JSON error object.
  """
  print(json.dumps({ _K.OUT_OUTCOME: _K.OUTCOME_ERROR,
                     _K.OUT_ERROR: { _K.OUT_CATEGORY: category, _K.OUT_MESSAGE: message } }))
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


def _resolve_sibling_cli(name: str, repo: Path) -> Path:
  """
  Locate a required sibling plugin's CLI binary other than the core plugin's.

  Args:
    name: CLI filename (e.g. `lazycortex-specs`, `lazycortex-review`).
    repo: Repository root whose own plugin tree is one of the searched stages.

  Returns:
    Absolute path to the resolved CLI binary.

  Raises:
    SystemExit: When no lookup stage carries the named CLI; the error names every stage searched.
  """
  try:
    return require_plugin_cli(name, repo)
  except RuntimeError as error:
    _fail(_K.CAT_LOGICAL, str(error))


def _resolve_core(repo: Path) -> Path:
  """
  Locate the core plugin's CLI binary.

  Args:
    repo: Repository root whose own plugin tree is one of the searched stages.

  Returns:
    Absolute path to the resolved `lazycortex-core` binary.

  Raises:
    SystemExit: When no lookup stage carries the core CLI; the error names every stage searched.
  """
  try:
    return resolve_core_cli(repo)
  except RuntimeError as error:
    _fail(_K.CAT_LOGICAL, str(error))


def parse_frontmatter(text: str) -> tuple[dict, int]:
  """
  Parse a markdown file's YAML frontmatter into a flat dict + end offset.

  Args:
    text: Full file text.

  Returns:
    Two-tuple `(values, fm_end)` where `values` carries scalar and list-typed entries
    and `fm_end` is the byte offset of the first character after the closing fence.
    Returns `({}, 0)` when no frontmatter is present.
  """
  block, fm_end = spec_frontmatter.block(text)

  # each line is a key, a list item under the open key, or noise
  values: dict = {}
  current_list_key: str | None = None
  for line in block.splitlines():
    stripped = line.strip()

    # guard: skip blank lines and comment markers
    if not stripped or stripped.startswith("#"):
      continue

    # a list continuation line (`- value`, indented or not) joins the open list key
    if stripped.startswith("- ") and current_list_key:
      values[current_list_key].append(spec_frontmatter.strip_comment(stripped[2:].strip()).strip('"').strip("'"))
      continue

    # guard: not a key:value line
    if ":" not in line:
      continue

    # the key and its value, with any trailing comment dropped
    key, _, raw_val = line.partition(":")
    key = key.strip()
    val_str = spec_frontmatter.strip_comment(raw_val.strip())

    # guard: empty key
    if not key:
      continue

    # an empty value opens a list under this key; any other value closes the open list
    if val_str == "":
      current_list_key = key
      values[key] = []
    else:
      values[key] = val_str
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

  - `spawn <kind> <slug> [targets=<path>[,<path>...]] [:: <description>]`
  - `attach <folder-note-path> [:: <description>]`

  A line without `::` is legacy-valid and yields an empty description.
  `targets=` is recognised only on a `change`-kind spawn line; it is ignored
  (left as an empty list) for every other kind. Any other line shape (blank,
  prose, malformed) is silently skipped — the parser is forgiving on unknown
  content so the router can mix structured decisions with operator-readable
  notes inside the same block without breaking apply.

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
  # knows the product resolves them before handing the set down here; the level roles are
  # subtracted either way — a product or a catalog is registered through `spawn-product`
  kinds = known_kinds if known_kinds is not None else frozenset(asset_types.builtin_defaults())
  kinds = kinds - LEVEL_ROLES

  # Decision: `reference` targets and `product=` fields are parsed by their own functions, not by
  # widening this function's return tuple — every caller unpacks the tuple positionally, and a
  # field only two verbs carry would force every one of them to take and discard it.

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

    # a spawn line names its kind and slug in fixed positions
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
            targets = [ part.strip() for part in tok[len(_K.DECISION_TARGETS_PREFIX):].split(",") if part.strip() ]
            break
      pair = ( kind, slug )
      if pair not in seen_spawn:
        seen_spawn.add(pair)
        spawn.append(( kind, slug, description, targets ))
      continue

    # an attach line names its target folder-note, deduplicated in order of appearance
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
  a third verb alongside `spawn` / `attach`.

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

    # only a `reference <path>` line is collected here, every other verb belongs to another parser
    if len(tokens) < 2 or tokens[0].lower() != _K.DECISION_VERB_REFERENCE:
      continue
    target = tokens[1]
    if target not in seen:
      seen.add(target)
      reference.append(( target, description ))
  return reference


def _parse_spawn_product_targets(block: str) -> list[tuple[str, str, str]]:
  """
  Scan a `<!-- routing-decision ... -->` block body for `spawn-product` lines.

  Grammar: `spawn-product key=<key> path=<spec_path> :: <description>`. `key=`, `path=` and the
  `::` separator are all mandatory — a line missing any of them names no product and is skipped,
  exactly as every other malformed decision line is, so a routing block carrying nothing else
  leaves the request rejected. A line carrying any token other than `key=` and `path=` fails the
  whole run, so the apply exits before anything is written.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    List of `(key, spec_path, description)` tuples, dedup applied per product key (preserves
    insertion order, first occurrence wins).

  Raises:
    SystemExit: When a `spawn-product` line carries a token other than `key=` and `path=`; the run
      fails with a logical error.
  """
  targets: list[tuple[str, str, str]] = []
  seen: set[str] = set()
  for raw_line in block.splitlines():
    stripped = raw_line.strip()

    # guard: skip blank lines — a non-decision prose line is dropped by a later guard instead
    if not stripped:
      continue
    head, sep, desc_part = stripped.partition(_K.DECISION_DESC_SEP)
    tokens = head.split()

    # guard: not a `spawn-product ...` line, or the mandatory `::` separator is absent
    if not tokens or tokens[0].lower() != _K.DECISION_VERB_SPAWN_PRODUCT or not sep:
      continue

    # every field is scanned rather than read positionally, so their order stays free
    fields: dict[str, str] = {}
    for tok in tokens[1:]:
      prefix = next(
        ( known for known in ( _K.DECISION_KEY_PREFIX, _K.DECISION_PATH_PREFIX ) if tok.startswith(known) ), None
      )
      # guard: a field the grammar does not know is refused, never silently dropped
      if prefix is None:
        _fail(_K.CAT_LOGICAL, f"spawn-product line carries an unknown field '{tok}': {stripped}")
      fields[prefix] = tok[len(prefix):].strip()
    key = fields.get(_K.DECISION_KEY_PREFIX, "")
    spec_path = fields.get(_K.DECISION_PATH_PREFIX, "")

    # guard: a line missing `key=` or `path=` names no product, and a key already seen repeats one
    if not key or not spec_path or key in seen:
      continue
    seen.add(key)
    targets.append(( key, spec_path, desc_part.strip() ))
  return targets


def _parse_spawn_products(block: str) -> dict[tuple[str, str], str]:
  """
  Scan a `<!-- routing-decision ... -->` block body for a spawn line's own `product=<key>` field.

  `product=` names the product one spawn line targets explicitly — the sole way one routing
  decision fans a request out across several products in the same apply run
  (`lazy-spec.coordination-playbook.md` Chapter 7). Recognised on ANY spawn kind, anywhere after the
  slug and before `::`, order-independent relative to `targets=`.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    Dict `{(kind, slug): product_key}` — only entries whose spawn line actually carried a
    non-empty `product=` field; a spawn line without one is simply absent from the dict.
  """
  return _parse_spawn_field(block, _K.DECISION_PRODUCT_PREFIX)


def _parse_spawn_field(block: str, prefix: str) -> dict[tuple[str, str], str]:
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

    # only a `spawn <kind> <slug> ...` line is collected here, every other verb belongs to another parser
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


def _parse_spawn_paths(block: str) -> dict[tuple[str, str], str]:
  """
  Scan a routing-decision block for each spawn line's own `path=` field.

  Args:
    block: Inner text of the comment block (between the opening and closing markers).

  Returns:
    Dict `{(kind, slug): folder}` — the folder under the product's `spec_path` the asset lands
    in; a spawn line without the field is absent, and the type's `default_path` applies instead.
  """
  return _parse_spawn_field(block, _K.DECISION_PATH_PREFIX)


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
           for key, raw in _parse_spawn_field(block, _K.DECISION_TOOLS_PREFIX).items() }


def _parse_attach_drops(block: str) -> dict[str, list[str]]:
  """
  Scan a routing-decision block for each attach line's own `drop=` field.

  `drop=` names the sibling documents the attach deletes from the attached asset. An attach
  line without it drops nothing at all — no job is cancelled and every file stays.

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

    # only an `attach <path> ...` line is collected here, every other verb belongs to another parser
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
  match = re.search(
      rf"(?s){re.escape(_K.ROUTING_DECISION_OPEN)}\s*(.*?)\s*{re.escape(_K.ROUTING_DECISION_CLOSE)}",
      routing_text,
  )
  return match.group(1) if match else None


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


def _parse_routing(
    body: str, folder_kinds: dict[str, str] | None = None,
) -> tuple[str | None, list[tuple[str, str]], list[str], str]:
  """
  Extract the class verdict + spawn / attach targets from a `# Routing` section.

  Args:
    body: Request body (post-frontmatter).
    folder_kinds: Folder name to asset type, the map a prose path-form spawn target derives its
      kind from (`asset_types.folder_map`); None keeps the two shipped folders (`bugs`,
      `changes`) only.

  Returns:
    Four-tuple `(class_verdict, spawn_list, attach_list, routing_text)`.
    `class_verdict` is the lowercased verdict word or `None` when absent; when the
    structured decision block carries spawn lines of one uniform kind that is a known
    request class, that kind is the verdict and overrides any prose marker. Any other
    uniform kind leaves the prose class verdict standing.
    `spawn_list` carries `(kind, slug)` pairs. `attach_list` carries folder-note
    paths — on the prose path, wikilinks whose last segment equals the previous
    one; the structured `<!-- routing-decision -->` branch takes its `attach`
    tokens verbatim, with no such shape check. `routing_text` is the raw inner
    text of the section (empty when no section is present).
  """

  # Domain(spec.requests):
  # # Routing grammar — prose verdict versus structured decision
  # A request carries its routing decision in one of two grammars. The older one is prose an
  # operator wrote: a class verdict named anywhere in the routing section as the word class
  # followed by a colon or a bar and the class, and spawn or attach intents phrased as
  # sentences, recognised by the words they contain. The newer one is a structured decision block,
  # one decision per line, each naming a verb and its target with an optional human description.
  # When the structured block is present, its spawn and attach decisions are authoritative in full
  # and the prose describing them is not consulted — the block's vocabulary is
  # language-independent, while the prose markers are English only, so a vault authored in
  # another language can express a decision only through the block. The prose class verdict is
  # the one exception: it is read first and stands as the request's class unless the block's spawn
  # lines all name one kind that is a known request class. In that case the decisions themselves
  # settle the class, being stronger evidence than a word somebody typed above them. Once a
  # decision has been applied, the routing section is removed
  # from the request outright: it is an instruction to the apply pass, not a record, and leaving it
  # behind would invite a second application of decisions already enacted.

  # the routing section, located by its heading
  match = re.search(
      rf"(?ms)^{re.escape(_K.ROUTING_H1)}\s*$(.*?)(?=^# \S|\Z)",
      body,
  )

  # guard: the request carries no routing section at all
  if not match:
    return None, [], [], ""

  # the section's own raw text, everything below its heading
  routing_text = match.group(1)

  # the prose class verdict, kept only when it names a known request class
  cls: str | None = None
  class_match = re.search(
      r"(?im)\bclass\b\s*[:|]\s*\**\s*`?([a-z][a-z-]*)`?",
      routing_text,
  )
  if class_match:
    candidate = class_match.group(1).lower()
    if candidate in _K.CLASS_ENUM:
      cls = candidate

  # primary source: the structured `<!-- routing-decision ... -->` block; when present, its spawn
  # and attach lines replace the prose targets, and the prose class verdict above stands unless the
  # block's spawn lines share one known request class. format:
  # one decision per line, each with an optional `:: <description>` suffix and,
  # on a change spawn, an optional `targets=` field (see _parse_routing_decision_rich):
  #     spawn <kind> <slug> [targets=<path>[,...]] [:: <description>]
  #     attach <repo-relative-folder-note-path> [:: <description>]
  if (decision_block := _extract_decision_block(routing_text)) is not None:
    spawn_structured, attach_structured = _parse_routing_decision(decision_block)

    # promote the block's single uniform spawn kind to the request class
    kinds = { kind for kind, _slug in spawn_structured }
    if len(kinds) == 1:
      candidate = next(iter(kinds))
      if candidate in _K.CLASS_ENUM:
        cls = candidate

    # the structured block is authoritative in full — no prose fallback past this point
    return cls, spawn_structured, attach_structured, routing_text

  # the prose-form spawn accumulators, deduplicated in order of appearance
  spawn: list[tuple[str, str]] = []
  seen_spawn: set[tuple[str, str]] = set()

  # the kinds a prose spawn line may name: every declared type of the product, every shipped
  # type name always included — `feature` / `content` / `research` own no folder of their own
  # but stay spawnable kinds all the same — longest first so a kind whose name extends another
  # is never cut short by the shorter one
  # the level roles ship as asset types because the level notes scaffold from the same
  # declarations, but neither is ever spawned as an asset — a product is registered through
  # `spawn-product`, and the catalog root predates every request. Subtracted from the folder map
  # too, so the path-form pass below cannot derive one from a `product/` segment either (the
  # same subtraction the structured block's own vocabulary applies)
  kinds_by_folder = {
      folder: kind
      for folder, kind in (folder_kinds if folder_kinds is not None else _SHIPPED_FOLDER_KINDS).items()
      if kind not in LEVEL_ROLES
  }
  kind_names = (set(kinds_by_folder.values()) | set(asset_types.builtin_defaults())) - LEVEL_ROLES
  kind_alt = "|".join(re.escape(kind) for kind in sorted(kind_names, key = lambda name: (-len(name), name)))

  # spawn line shape examples:
  #   "Spawn one cross-cutting change entity — `slug`"
  #   "Spawn change: slug"
  #   "spawn: bug — `slug`"
  for match in re.finditer(
      rf"(?im)\bspawn\b[^\n]*?\b({kind_alt})\b[^\n]*?`([a-z][a-z0-9-]*)`",
      routing_text,
  ):
    pair = ( match.group(1).lower(), match.group(2) )
    if pair not in seen_spawn:
      seen_spawn.add(pair)
      spawn.append(pair)

  # Plain `<kind>: <slug>` form (router may emit a structured fallback). A trailing
  # `:: <description>` suffix (the block grammar's per-target description) is tolerated
  # and ignored here — this prose fallback surfaces only the identity, never the detail.
  for match in re.finditer(
      rf"(?im)^\s*(?:[-*]\s*)?(?:spawn[^\n:]*[:|]\s*)?({kind_alt})\s*[:|]\s*"
      r"`?([a-z][a-z0-9-]*)`?\s*(?:::.*)?$",
      routing_text,
  ):
    pair = ( match.group(1).lower(), match.group(2) )

    # collect only pairs the prose-form pass above has not already recorded
    if pair not in seen_spawn:
      seen_spawn.add(pair)
      spawn.append(pair)

  # Path-form spawn target — router may emit the full repo-relative spawn path in
  # backticks (e.g. "spawn `request/products/test/changes/<slug>`"). The kind is the type
  # whose folder is the second-to-last path segment — every declared type, not only the
  # shipped two — and the slug is the last path segment; a backtick path with no shipped
  # folder segment (a bare `<slug>` at the product root included) is left to the prose-form
  # and structured parsers above, since no folder segment here names a spawnable kind.
  for match in re.finditer(
      r"(?im)\bspawn\b[^\n]*?`([^`\s]+/[a-z][a-z0-9_-]*/[a-z][a-z0-9-]*)`",
      routing_text,
  ):
    parts = match.group(1).rstrip("/").split("/")

    # guard: a folder no declared type owns names no spawnable kind
    if (kind := kinds_by_folder.get(parts[-2])) is None:
      continue

    # collect only pairs the prose-form passes above have not already recorded
    pair = ( kind, parts[-1] )
    if pair not in seen_spawn:
      seen_spawn.add(pair)
      spawn.append(pair)

  # the attach targets: fresh folder-note wikilinks, deduplicated in order of appearance
  attach: list[str] = []
  seen_attach: set[str] = set()
  for match in re.finditer(r"\[\[([^\]|]+?)(?:\|[^\]]*?)?\]\]", routing_text):
    target = match.group(1).strip()
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
    The body with the routing section excised; the blank lines meeting at the cut collapse to
    at most one blank line, and blank runs anywhere else are left as they are. Lines inside a
    fenced code block never start or end the section.
  """
  lines = spec_frontmatter.split_lines(body, keepends = True)

  # a `# Routing` or H1 line quoted inside a fenced code block is code, never a section edge
  fenced = spec_frontmatter.fenced_lines(lines)
  first = next(( idx for idx, row in enumerate(lines) if not fenced[idx] and row.rstrip() == _K.ROUTING_H1 ), None)

  # guard: no routing section — nothing to excise, nothing to collapse
  if first is None:
    return body

  # the section runs to the next real H1, or to the end of the body
  last = next(( idx for idx in range(first + 1, len(lines)) if not fenced[idx] and re.match(r"# \S", lines[idx]) ),
              len(lines))
  start = sum(len(row) for row in lines[:first])
  end = start + sum(len(row) for row in lines[first:last])

  # only the seam the excision leaves is collapsed; blank runs elsewhere (a code block) are content
  head, tail = body[:start].rstrip("\n"), body[end:].lstrip("\n")
  seam = len(body[:start]) - len(head) + len(body[end:]) - len(tail)
  return head + "\n" * min(seam, 2) + tail


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
  for line in spec_frontmatter.split_lines(head, keepends = True):
    if line.startswith("> "):
      if re.search(_K.STATUS_TAG_PATTERN, line):
        in_status_callout = True
        continue

      # drop the continuation lines of the status callout being stripped
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
    for link in wikilinks:
      lines.append(f"> [[{link}]]")
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

  # a body without an H1 gets the callout at its start
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
  return spec_frontmatter.set_scalar(fm_text, key, value)


def set_fm_list(fm_text: str, key: str, values: list[str]) -> str:
  """
  Add or replace a `key:` list block inside a `---`-delimited frontmatter block.

  Args:
    fm_text: Full frontmatter text including the opening / closing fences.
    key: List-typed key name.
    values: Replacement member list, each rendered as a YAML scalar (quoted only when YAML
      would otherwise read it differently).

  Returns:
    Frontmatter text with the list set; an existing inline or multi-line list is replaced in
    place, a missing key is appended before the closing fence.
  """
  return spec_frontmatter.write_list(fm_text, key, values)


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
  # the request mirror tag is the shared sweep bound to the `request/` prefix
  return spec_frontmatter.sweep_tag(fm_text, _K.TAG_PREFIX, new_tag_member)


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
  return _sweep_request_tag(fm_text, f"{_K.TAG_PREFIX}{request_status}")


def _request_h1_title(body: str) -> str:
  """
  Extract the first H1 title (without the leading `# `) from a body.

  Args:
    body: Body text.

  Returns:
    The title text, or `"request"` when no H1 is present.
  """
  match = re.search(r"(?m)^# (.+)$", body)
  return match.group(1).strip() if match else "request"


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

    # leave out the routing section — it is the apply worker's input, not body content
    if title.lower() == _K.ROUTING_H1[2:].lower():
      continue

    # leave out the history section — it is per-document review state, not request prose
    if title.lower() == _K.HISTORY_H1[2:].lower():
      continue
    segments.append(f"# {title}\n{sec.group(2).rstrip()}\n")
  return "\n".join(segments).strip()


def _today_iso() -> str:
  """
  Return today's UTC date in `YYYY-MM-DD` form.

  Returns:
    ISO-formatted date string.
  """
  return _dt.datetime.now(_dt.UTC).date().isoformat()


def _has_spec_note(folder: Path) -> bool:
  """
  Report whether a folder holds a folder-note the spec tree already owns.

  Any `spec_role` at all claims the folder: a level note names another product, and a
  `status` note names an asset whose folder a product may not sit on top of. A folder-note
  carrying no role is a plain group folder — operator-zone ground a nested product spawns onto.

  Args:
    folder: The candidate product directory; it need not exist.

  Returns:
    True when `<folder>/<folder.name>.md` exists and carries any `spec_role` value.
  """
  note = folder / f"{folder.name}{_K.MD_SUFFIX}"

  # guard: no folder-note at all — nothing claims the folder
  if not note.is_file():
    return False
  fm, _end = parse_frontmatter(note.read_text(encoding = "utf-8"))
  return bool(fm.get(_K.SPEC_ROLE))


class _Attach:
  """
  Inline attach primitive for the apply transition.

  Replaces the LLM-driven `spec.request-attach` skill, recording an attach target's request
  attribution on its primary doc on behalf of one apply run.

  Responsibilities:
    - Resolve an attach target's primary doc from its declared asset type.
    - Track a doc's `spec_source_requests` frontmatter and its `## Requests` body projection,
      without duplicating an already-listed request.
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
  def ensure_source_request(doc_path: Path, request_wikilink: str,
                            request_display: str) -> bool:
    """
    Add the request to `spec_source_requests` frontmatter and re-project the body bullet list.

    Guarantees:
      - Never appends a request already listed in `spec_source_requests`.
      - The frontmatter list and the body `# Sources` / `## Requests` projection stay in step.

    Args:
      doc_path: Path to the target authored doc.
      request_wikilink: The request file's vault-relative wikilink path.
      request_display: Display gloss for the wikilink bullet.

    Returns:
      `True` when the doc text changed, `False` when the request was already listed.
    """

    # Contract:
    # Once a request is listed in the doc's `spec_source_requests`, this method MUST NOT
    # append it again on a later call; the frontmatter list and the body `# Sources` /
    # `## Requests` projection MUST stay in step, so a caller reading either sees the same
    # set of requests ever recorded through this method.

    # the doc split into its frontmatter and body, the two projections this method keeps in step
    text = read_text(doc_path)
    values, fm_end = parse_frontmatter(text)

    # the entries already listed, each reduced to its bare wikilink target
    listed = [ raw.strip().strip('"').strip("'").split("|")[0].strip("[]")
               for raw in values.get(_K.SPEC_SOURCE_REQUESTS) or [] ]

    # guard: idempotent — request already listed
    if request_wikilink in listed:
      return False

    # the request joins both projections, frontmatter list and body section, in one write
    write_text_atomic(doc_path,
                      _Attach.append_source_requests_fm(text[:fm_end], f"[[{request_wikilink}]]")
                      + _Attach._project_requests_body(text[fm_end:], [ *listed, request_wikilink ],
                                                       request_wikilink, request_display))
    return True

  @staticmethod
  def append_source_requests_fm(fm_text: str, member: str) -> str:
    """
    Append `member` to the `spec_source_requests:` frontmatter list (create when absent).

    Args:
      fm_text: Full frontmatter text.
      member: Wikilink-bracketed reference to append (e.g. `[[path/to/req]]`).

    Returns:
      Frontmatter text with the member appended to the list, or with the list
      created when the key was previously absent.
    """
    return spec_frontmatter.write_list(
        fm_text, _K.SPEC_SOURCE_REQUESTS,
        [ *spec_frontmatter.read_list(fm_text, _K.SPEC_SOURCE_REQUESTS), member ])

  @staticmethod
  def _project_requests_body(body: str, targets: list[str], request_wikilink: str,
                             request_display: str) -> str:
    """
    Re-project the `## Requests` bullets from every request the doc lists, keeping existing bullets.

    The new request's bullet shows `request_display` and today's date.

    Args:
      body: Doc body (post-frontmatter).
      targets: Every request wikilink target the frontmatter lists, the new one included.
      request_wikilink: Wikilink target of the request being attached.
      request_display: Display text for the new request's bullet.

    Returns:
      Body with the projection markers holding one bullet per listed request; the `# Sources`
      container and `## Requests` sub-section are created on demand when absent.
    """
    # the shared projection keeps every listed request's bullet and dates the new one today
    return Markers().project_requests(body, targets, today = _today_iso(),
                                      displays = { request_wikilink: request_display })


class _FolderNote:
  """
  Folder-note edits — appends the request wikilink to `## Source requests`.
  """

  @staticmethod
  def append_source_request(folder_note: Path, request_wikilink: str,
                            request_display: str) -> bool:
    """
    Append `- [[<wikilink>|<display>]] — <today>` to the folder-note's `## Source requests` section.

    Unions the same bullet into the `spec_source_requests` frontmatter list, the set `seed-doc`
    copies onto checkbox-seeded docs; a re-run against an already-listed request changes neither
    projection.

    Guarantees:
      - The `spec_source_requests` frontmatter list and the `## Source requests` body section
        stay in step; after a successful append, both carry the same wikilink.
      - Never appends a wikilink already present under either projection.

    Args:
      folder_note: Path to `<slug>/<slug>.md`.
      request_wikilink: Request file's wikilink target.
      request_display: Display gloss for the bullet.

    Returns:
      `True` when the folder-note changed, `False` when the bullet was already present
      (idempotent re-run).
    """

    # Contract:
    # Every append MUST keep the `spec_source_requests` frontmatter list and the
    # `## Source requests` body section in step: both carry the same wikilink, the
    # frontmatter entry quoted, so a caller reading only the frontmatter sees the full
    # union of requests ever appended through this method. A wikilink already present
    # under either projection MUST NOT be appended again.

    # the note's current text, the only thing the idempotence check reads
    text = read_text(folder_note)

    # guard: idempotent — the note already links this request under either projection
    if f"[[{request_wikilink}]]" in text or f"[[{request_wikilink}|" in text:
      return False

    # the new bullet, dated today
    bullet = f"- [[{request_wikilink}|{request_display}]] — {_today_iso()}"

    # an existing section takes the bullet at its end; a missing one is created around it
    match = re.search(
        rf"(?ms)^{re.escape(_K.SOURCE_REQUESTS_H2)}\s*$(.*?)(?=^## \S|^# \S|\Z)", text,
    )
    if match:
      cleaned = match.group(1).rstrip("\n")
      new_text = (text[:match.start(1)] + cleaned + ("\n\n" if cleaned else "\n") + bullet + "\n"
                  + text[match.end(1):])
    else:
      # the new section goes above the protected `# History` H1, else above an unmigrated note's legacy
      # `## History` heading, else at the end, so it never lands inside the history section
      hist_idx = next((idx for idx in (text.find(f"\n{Section.HISTORY}\n"), text.find(f"\n{_K.HISTORY_H2}\n"))
                       if idx >= 0), -1)
      block_text = f"{_K.SOURCE_REQUESTS_H2}\n\n{bullet}\n\n"
      if hist_idx >= 0:
        new_text = text[:hist_idx + 1] + block_text + text[hist_idx + 1:]
      else:
        new_text = text.rstrip() + "\n\n" + block_text

    # the frontmatter union is what seed-doc copies onto checkbox-seeded docs — the body bullet
    # alone is invisible to it, so both projections are maintained together
    _fm_values, fm_end = parse_frontmatter(new_text)
    write_text_atomic(folder_note,
                      _Attach.append_source_requests_fm(new_text[:fm_end], f"[[{request_wikilink}]]")
                      + new_text[fm_end:])
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
    populated_docs: Docs whose attribution changed via an attach target during this run.
    spawn_folder_notes: Folder-notes created by enacting a spawn target during this run.
    spawn_group_notes: Group folder-notes the scaffolder seeded while enacting spawns this run.
    attach_folder_notes: Folder-notes populated by enacting an attach target during this run.
    warnings: Non-fatal issues collected during this run, such as an unresolvable design-cascade
      target named in a change spawn's `targets=` field.
    dropped_docs: Sibling documents deleted from disk by an attach `drop=` during this run; those still
      tracked by git are staged in the run's single commit.
    cancelled_assets: Folders of attached assets whose live expert job an attach `drop=` cancelled during this
      run without deleting any of their documents.
    spawn_product_dirs: Spec folders created by enacting a `spawn-product` target during this run.
    settings_written: True once this run has persisted a settings section, so the settings file
      joins the commit set.
  """

  def __init__(self, *, file_path: Path, author_name: str, author_email: str) -> None:
    """
    Construct an apply orchestrator scoped to one request file.

    Args:
      file_path: Absolute path to the request markdown file.
      author_name: Git author name for the atomic commit (bot identity).
      author_email: Git author email for the atomic commit.

    Raises:
      SystemExit: When no lookup stage can find the `lazycortex-specs` or `lazycortex-review`
        sibling CLI.
    """
    self.file_path = file_path.resolve()
    self.repo = _repo_root(self.file_path.parent)
    self.author_name = author_name
    self.author_email = author_email
    self.specs_cli = _resolve_sibling_cli(_K.CLI_LAZYCORTEX_SPECS, self.repo)
    self.review_cli = _resolve_sibling_cli(_K.CLI_LAZYCORTEX_REVIEW, self.repo)
    self.populated_docs: list[Path] = []
    self.spawn_folder_notes: list[Path] = []
    self.spawn_group_notes: list[Path] = []
    self.attach_folder_notes: list[Path] = []
    self.warnings: list[str] = []
    self.dropped_docs: list[Path] = []
    self.cancelled_assets: set[Path] = set()
    self.spawn_product_dirs: list[Path] = []
    self.settings_written = False

  @property
  def request_wikilink(self) -> str:
    """
    The request file's wikilink target — the repo-relative path with the `.md` suffix dropped.
    """
    return str(self.file_path.resolve().relative_to(self.repo).with_suffix(""))

  @property
  def _settings_path(self) -> Path:
    """
    This repo's tracked settings file — `.claude/lazy.settings.json` under the repo root.
    """

    # Decision: raw read over `_read_settings_section` — `_read_settings_section` spawns the
    # `lazycortex-core` CLI per call and aborts the whole run on any read error, while every
    # reader of this property owes its own caller a different fallback or wording for an absent
    # or malformed file (a silent fallback to the shipped asset types, a logical-refusal message,
    # an empty record), which only a direct read lets each one supply for itself.

    # build the path only — reading it is each caller's own business, per the Decision above
    return self.repo / _K.CLAUDE_DIR / _K.SETTINGS_FILE

  def _load_product_record(self, product: str) -> dict:
    """
    Look up a product's effective record from `.claude/lazy.settings.json`.

    Args:
      product: Product compound-key.

    Returns:
      The product's effective record (`resolve_product.effective_record`) — its own keys over
      its ancestors' (`spec_path` and friends).

    Raises:
      SystemExit: When the settings file is missing or malformed, the key names no registered
        product, or that product's record carries no `spec_path`.
    """

    # guard: no settings file to read the product registry from
    if not self._settings_path.exists():
      _fail(_K.CAT_LOGICAL, f".claude/lazy.settings.json absent at {self._settings_path}")

    # the parsed settings, refused outright when they are not valid JSON
    try:
      data = json.loads(self._settings_path.read_text(encoding = "utf-8"))
    except json.JSONDecodeError as error:
      _fail(_K.CAT_LOGICAL, f".claude/lazy.settings.json malformed: {error}")

    # the product's own record, as registered
    products_section = data.get(_K.PRODUCTS) or {}
    record = products_section.get(product) if isinstance(products_section, dict) else None

    # guard: the key names no registered product
    if not isinstance(record, dict):
      _fail(_K.CAT_LOGICAL,
            f"product '{product}' not registered in lazy.settings.json[{_K.PRODUCTS}]")

    # guard: a registered product without a spec root cannot hold assets
    if _K.SPEC_PATH not in record:
      _fail(_K.CAT_LOGICAL, f"product '{product}' has no {_K.SPEC_PATH}")

    # the effective record, with every key the product leaves undeclared inherited from its ancestors
    return resolve_product.effective_record(self.repo, product)

  def _default_product(self) -> str:
    """
    Pick the default product key — the alphabetically first one nothing registered encloses.

    Returns:
      The first top-level product key from settings, falling back to the first key of all when
      the registry declares no top-level product at all.

    Raises:
      SystemExit: When the settings file is malformed, or no product is registered at all,
        so a spawn has nothing to land under.
    """

    # Domain(spec.config):
    # # An unattributed spawn lands in a top-level product
    # A routing decision that names no product at all still has to land its asset somewhere, and
    # the catalog answers with the first of its outermost products in name order. A product
    # nested inside another is never that answer: it was carved out to hold one narrower slice
    # of its parent's work, so filing an asset nobody attributed into it would claim a scope the
    # decision never named. The parent that encloses it is the honest default, and the operator
    # moves the asset down a level once they judge it belongs there.

    # opt: registry loaded once and handed down — a preloaded registry answers as a disk read would

    # load the product registry, refusing logically when the settings file will not parse
    try:
      registry = resolve_product.load_products(self.repo)
    except json.JSONDecodeError as error:
      _fail(_K.CAT_LOGICAL, f".claude/lazy.settings.json malformed: {error}")
    keys = sorted(key for key, record in registry.items() if isinstance(record, dict))

    # guard: at least one product must exist before apply can act on a spawn
    if not keys:
      _fail(_K.CAT_LOGICAL, _K.ERR_NO_PRODUCTS)

    # the first top-level product wins, falling back to the first of all when every one is nested
    top_level = [
        key for key in keys
        if not resolve_product.ancestor_chain(self.repo, key, products = registry)
    ]
    return (top_level or keys)[0]

  def _record_for_note(self, note: Path) -> dict:
    """
    Resolve the effective record of the product whose `spec_path` contains one asset note.

    Args:
      note: Absolute path of the asset's status folder-note.

    Returns:
      The owning product's effective record (`resolve_product.effective_record_by_path`), or `{}`
      when the note sits outside the content root, the settings file is missing or malformed, or
      no registered product's `spec_path` covers it.
    """
    try:
      rel = note.relative_to(spec_content_root(self.repo))
    except ValueError:
      # guard: a note outside the content root is owned by no registered product
      return {}
    try:
      _key, record = resolve_product.effective_record_by_path(self.repo, rel.as_posix())
    except (OSError, json.JSONDecodeError):
      # guard: a malformed or unreadable settings file resolves to no product record, as before
      return {}
    return record or {}

  def _read_known_kinds(self) -> frozenset[str]:
    """
    Collect every asset type a spawn line may name in this repo.

    The shipped set plus the declarations of every registered product: a routing decision names
    a type, not a product, so a type any product declares is admissible on any spawn line and
    the product it lands in is settled separately by `product=`.

    Returns:
      The admissible type names, the shipped set alone when no settings file is readable.
    """
    kinds = set(asset_types.builtin_defaults())

    # guard: no readable settings — only the shipped declarations apply
    if not self._settings_path.exists():
      return frozenset(kinds)

    # unparseable settings fall back to the shipped declarations as well
    try:
      data = json.loads(self._settings_path.read_text(encoding = "utf-8"))
    except json.JSONDecodeError:
      return frozenset(kinds)

    # every product's own asset types join the shipped ones
    for record in (data.get(_K.PRODUCTS) or {}).values():
      if isinstance(record, dict):
        kinds.update(record.get(_K.ASSET_TYPES) or {})
    return frozenset(kinds)

  def _spawn(self, kind: str, slug: str, *, product: str | None = None,
             path: str = "", tools: list[str] | None = None) -> tuple[Path, str]:
    """
    Run the scaffold-asset subprocess to create the new entity folder.

    Args:
      kind: The asset type the routing decision named.
      slug: Asset slug.
      product: The spawning decision line's own `product=` field, when given — the sole way
        one routing decision fans a request out across several products in the same apply run
        (playbook Chapter 7). Falls back to `_default_product()` (the first TOP-LEVEL product
        key) when omitted, matching every pre-multi-product routing decision on a single-product
        repo.
      path: The decision's own `path=` field, empty to fall back to the type's `default_path`.
      tools: The decision's own `tools=` field, empty to leave the asset's tools undetermined.

    Returns:
      Two-tuple of the new folder-note's absolute path
      (`<content_root>/<spec_path>/<folder>/<slug>/<slug>.md`, where the content root is
      `spec.vault_root`, default `specs`) and the spawning product's `spec_path`.

    Raises:
      SystemExit: When the named product resolves to no record, or the scaffold-asset
        subprocess fails.
    """
    product = product or self._default_product()
    record = self._load_product_record(product)
    spec_path = record[_K.SPEC_PATH]

    # the scaffolder lands assets under the content root (`spec.vault_root`, default `specs`),
    # so the note is read back through the same base — `repo / spec_path` misses it
    folder_note = (spec_content_root(self.repo) / spec_path
                   / (path or asset_types.default_path(kind, record)) / slug / f"{slug}.md")

    # guard: idempotent — an earlier apply attempt already scaffolded this asset
    if folder_note.exists():
      return folder_note, spec_path

    # the scaffolder run, placed under the operator's folder when the decision named one
    argv = [ sys.executable, str(self.specs_cli), "scaffold-asset", product, kind, slug ]
    if path:
      argv += [ _K.SCAFFOLD_PATH_FLAG, path ]
    res = subprocess.run(
        argv,
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False, encoding = "utf-8",
    )

    # guard: the scaffolder refused — nothing was created to continue from
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
      note_text = read_text(folder_note)
      _values, fm_end = parse_frontmatter(note_text)
      write_text_atomic(folder_note,
          set_fm_list(note_text[:fm_end], _K.SPEC_TOOLS_KEY, tools) + note_text[fm_end:])
    return folder_note, spec_path

  def _read_settings_section(self, section: str) -> dict:
    """
    Read one tracked section of the consumer's settings through the `lazycortex-core` CLI.

    Args:
      section: Top-level settings section name.

    Returns:
      The section's tracked content, empty when the section itself holds no object; a section
      the CLI cannot produce aborts the run instead of returning.

    Raises:
      SystemExit: When the `lazycortex-core` sibling CLI cannot be resolved, or the CLI exits
        non-zero, or its output is not JSON.
    """
    res = subprocess.run(
        [ sys.executable, str(_resolve_core(self.repo)), _K.CLI_SETTINGS_GET, section,
          _K.CLI_CWD_FLAG, str(self.repo) ],
        cwd = str(self.repo), capture_output = True, text = True, check = False, encoding = "utf-8",
    )

    # guard: the section is unreadable — abort rather than enact against guessed content
    if res.returncode != 0:
      _fail(_K.CAT_LOGICAL,
            f"settings-get {section} failed: exit={res.returncode} "
            f"stderr={res.stderr.strip()[:240]}")

    # the section as JSON, refused outright when the CLI printed anything else
    try:
      loaded = json.loads(res.stdout or "{}")
    except json.JSONDecodeError as error:
      _fail(_K.CAT_LOGICAL, f"settings-get {section} returned malformed JSON: {error}")
    return loaded if isinstance(loaded, dict) else {}

  def _write_settings_section(self, section: str, value: dict) -> None:
    """
    Persist one tracked settings section through the `lazycortex-core` CLI.

    Args:
      section: Top-level settings section name.
      value: Whole section content to store; surrounding sections stay untouched.

    Raises:
      SystemExit: When the `lazycortex-core` sibling CLI cannot be resolved, or the
        `settings-set` CLI exits non-zero.
    """
    res = subprocess.run(
        [ sys.executable, str(_resolve_core(self.repo)), _K.CLI_SETTINGS_SET, section,
          _K.CLI_CWD_FLAG, str(self.repo) ],
        input = json.dumps(value), cwd = str(self.repo),
        capture_output = True, text = True, check = False, encoding = "utf-8",
    )

    # guard: a failed write leaves the enactment half-done, so it aborts the whole run
    if res.returncode != 0:
      _fail(_K.CAT_LOGICAL,
            f"settings-set {section} failed: exit={res.returncode} "
            f"stderr={res.stderr.strip()[:240]}")

    # the settings file changed, so it must reach this pass's commit pathspec
    self.settings_written = True

  def _is_language_inherited(self, ancestor_key: str | None) -> bool:
    """
    Report whether a product spawned under `ancestor_key` already inherits a language.

    Args:
      ancestor_key: The nearest enclosing product's compound-key, or None at the top level.

    Returns:
      True when that ancestor's effective record supplies a non-empty `language`.
    """
    # guard: no product encloses the new one — there is nothing to inherit from
    if ancestor_key is None:
      return False
    inherited = resolve_product.effective_record(self.repo, ancestor_key).get(_K.LANGUAGE)
    return isinstance(inherited, str) and bool(inherited)

  def _register_product(self, key: str, spec_path: str) -> None:
    """
    Write a spawned product's settings record, refusing to claim a directory already in use.

    An existing directory refuses the registration only when it is somebody else's: a folder
    already carrying a folder-note with any `spec_role` is another product's level or another
    asset's status, and so is any occupied folder no registered product encloses. A folder
    inside a registered product's tree whose folder-note carries no role — a plain group
    folder — is that product's own ground, which a nested product spawns onto.

    A key already on record under the very same `spec_path` is re-applied as a no-op, leaving the
    recorded record as an operator may have edited it. Every refusal is raised before the first
    settings write. `language` is written only when no enclosing product already supplies one, and
    the saved record carries no `source` block and no empty asset-type, tool-type, or guideline
    placeholder keys.

    Args:
      key: The product compound-key the routing decision named.
      spec_path: The product's content-root-relative spec directory.

    Raises:
      SystemExit: When the key is on record under a different `spec_path`, when another key is
        already registered at this very `spec_path`, when its directory already carries a
        folder-note declaring any `spec_role` (another product's level note or an asset's
        status note), when its directory exists outside every registered product's tree, when
        the `lazycortex-core` sibling CLI cannot be resolved, when reading a settings section
        fails (a non-zero `settings-get` exit or malformed JSON output), or when persisting the
        product record fails (a non-zero `settings-set` exit).
    """

    # every refusal is raised here, before the registry is read for writing
    self._validate_product_target(key, spec_path)

    # the registry as it stands, and whatever it already records under this key
    products = self._read_settings_section(_K.PRODUCTS)
    recorded = products.get(key)

    # guard: a key already on record under the same path is re-applied idempotently, never rewritten
    if isinstance(recorded, dict) and recorded.get(_K.SPEC_PATH) == spec_path:
      return

    # the nearest registered product enclosing this path — the ancestor a nested product inherits
    # its effective record from; None at the top level
    ancestor_key, _ancestor = resolve_product.resolve_product_by_path(self.repo, spec_path)

    # the record carries no `source` block and no empty asset-type, tool-type or guideline
    # placeholders: a request registers the spec tree only, and `tool_types` is inherited whole
    # from the nearest declaring ancestor, so an empty one here would shadow what they declare
    record: dict = { _K.SPEC_PATH: spec_path }

    # Domain(spec.config):
    # # A nested product never shadows its ancestors' language
    # A product spawned from a request is given the vault's own document language only when no
    # product enclosing it already supplies one. A nested product that carries no language of
    # its own keeps following the language its ancestors set, so a parent's choice reaches the
    # whole tree beneath it instead of being overridden by the vault default at each level.

    # the vault's own language, when it declares one; a vault that declares none leaves the key
    # absent, so the product keeps following whatever `spec.language` becomes
    language = self._read_settings_section(_K.SETTINGS_SPEC).get(_K.LANGUAGE)
    if isinstance(language, str) and language and not self._is_language_inherited(ancestor_key):
      record[_K.LANGUAGE] = language

    # the product's default icon, then the registration itself written back to the settings
    record[_K.ICON] = _K.ICON_PRODUCT
    products[key] = record
    self._write_settings_section(_K.PRODUCTS, products)

  def _validate_product_target(self, key: str, spec_path: str) -> None:
    """
    Refuse a `spawn-product` target the registry or the disk cannot take, writing nothing.

    A key already on record under the very same `spec_path` is accepted without further checks.
    Neither the settings nor the disk are touched.

    Args:
      key: The product compound-key the routing decision named.
      spec_path: The product's content-root-relative spec directory.

    Raises:
      SystemExit: When the key is on record under a different `spec_path`, when another key is
        already registered at this very `spec_path`, when its directory already carries a
        folder-note declaring any `spec_role` (another product's level note or an asset's
        status note), when its directory exists outside every registered product's tree, when
        the `lazycortex-core` sibling CLI cannot be resolved, or when reading a settings
        section fails (a non-zero `settings-get` exit or malformed JSON output).
    """

    # the registry as it stands, and whatever it already records under this key
    recorded = self._read_settings_section(_K.PRODUCTS).get(key)

    # guard: the key is already registered — only a matching path is accepted, as a no-op
    if isinstance(recorded, dict):
      # guard: the registry keeps the path the coordinators watch, the decision names the folder to
      # scaffold — a divergence would coordinate one tree and scaffold another, so it is never guessed
      if recorded.get(_K.SPEC_PATH) != spec_path:
        _fail(_K.CAT_LOGICAL,
              f"spawn-product '{key}': registered spec_path "
              f"'{recorded.get(_K.SPEC_PATH)}' does not match the decision's path '{spec_path}'")
      return

    # the nearest registered product enclosing this path
    ancestor_key, ancestor = resolve_product.resolve_product_by_path(self.repo, spec_path)

    # guard: the path itself is already somebody's product root — a second key over the same tree
    # would give one folder two level notes and two coordinators, whatever the disk looks like
    if ancestor is not None and ancestor.get(_K.SPEC_PATH) == spec_path:
      _fail(_K.CAT_LOGICAL,
            f"spawn-product '{key}': path '{spec_path}' is already registered "
            f"under the key '{ancestor_key}'")

    # the product's directory on disk, which the remaining guards inspect
    target = spec_content_root(self.repo) / spec_path

    # guard: a folder already carrying a spec folder-note of its own is taken — a level note
    # names another product, a status note names an asset; neither is ground a spawn may claim
    if _has_spec_note(target):
      _fail(_K.CAT_LOGICAL,
            f"spawn-product '{key}': path '{spec_path}' already carries a spec folder-note "
            "and belongs to another product or asset")

    # guard: a fresh key must not claim a tree somebody else already put there; an existing
    # folder inside a registered product's own tree is that product's ground, not somebody else's
    if target.exists() and ancestor_key is None:
      _fail(_K.CAT_LOGICAL,
            f"spawn-product '{key}': path '{spec_path}' already exists on disk and belongs to "
            "no registered product")

  def _seed_level_vision(self, key: str, note: Path) -> Path:
    """
    Seed a level note's own `vision.md` through the `seed-doc` CLI, skipping an existing one.

    Args:
      key: The product compound-key the document is seeded under.
      note: Absolute path to the product's level folder-note.

    Returns:
      Absolute path to the level's vision document.

    Raises:
      SystemExit: When the `seed-doc` CLI exits non-zero.
    """
    vision = note.parent / LevelDoc.VISION

    # guard: idempotent — an earlier apply attempt already seeded the document
    if vision.is_file():
      return vision

    # the vision seeded through the specs CLI, from the product's own template chain
    res = subprocess.run(
        [ sys.executable, str(self.specs_cli), _K.CLI_SEED_DOC, key,
          str(note.relative_to(self.repo)), _K.SEED_DOC_FLAG, _K.VISION_DOC_TOKEN,
          _K.CLI_CWD_FLAG, str(self.repo) ],
        cwd = str(self.repo), capture_output = True, text = True, check = False, encoding = "utf-8",
    )

    # guard: an unseeded vision leaves the product without the first rung of its ladder
    if res.returncode != 0:
      _fail(_K.CAT_LOGICAL,
            f"seed-doc failed for product '{key}': exit={res.returncode} "
            f"stderr={res.stderr.strip()[:240]}")
    return vision

  def _spawn_product(self, key: str, spec_path: str, request_display: str) -> Path:
    """
    Enact one `spawn-product` decision, leaving the new product registered with its level note and a
    seeded `vision.md` that carries the request's attribution.

    Every write lands in this pass's single commit.

    Every refusal over the registry or the directory is raised before this enactment's first write.

    Args:
      key: The product compound-key the routing decision named.
      spec_path: The product's content-root-relative spec directory.
      request_display: Display gloss used in the vision document's `## Requests` bullet.

    Returns:
      Absolute path to the product's level folder-note.

    Raises:
      SystemExit: When the product key or its `spec_path` conflicts with an existing registration,
        when the directory already carries a folder-note declaring any `spec_role` (another
        product's level note or an asset's status note), when the directory exists outside
        every registered product's tree, when reading or persisting a settings section fails,
        when the `lazycortex-core` sibling CLI cannot be resolved, when the level note is
        refused, or when seeding the level's `vision.md` fails.
    """

    # the product's settings record comes first, so every later write has a registered key
    self._register_product(key, spec_path)

    # the product's spec root on disk, recorded so the commit carries it
    folder = spec_content_root(self.repo) / spec_path
    folder.mkdir(parents = True, exist_ok = True)
    self.spawn_product_dirs.append(folder)

    # the product's level note, created or brought up to the level schema; a refused level note ends the apply
    try:
      note = self.repo / catalog_note.backfill(self.repo, product = key, root = False)[_K.NOTE_KEY]
    except scaffold_asset.ScaffoldRefusal as refusal:
      _fail(refusal.category, refusal.message)

    # attribution on the document itself is the review trigger, exactly as an attach's is
    vision = self._seed_level_vision(key, note)
    if _Attach.ensure_source_request(vision, self.request_wikilink, request_display):
      self.populated_docs.append(vision)
    return note

  def _level_doc_target(self, attach_target: str) -> Path | None:
    """
    Decide whether a routing attach target names a level document rather than an asset.

    A level document is one of `LevelDoc.BASENAMES` sitting directly in the spec content root or
    in a registered product's own `spec_path`; the `.md` suffix is optional in the token.

    Args:
      attach_target: The attach line's own target token, repo-relative.

    Returns:
      The document's absolute path when it is a level document, `None` otherwise.
    """
    candidate = self.repo / (
        attach_target if attach_target.endswith(_K.MD_SUFFIX)
        else attach_target + _K.MD_SUFFIX)

    # guard: only the level ladder's own filenames, and only for a file that exists
    if candidate.name not in LevelDoc.BASENAMES or not candidate.is_file():
      return None
    content_root = spec_content_root(self.repo)

    # a product's own level documents sit directly in its spec_path, never deeper
    record = self._record_for_note(candidate)
    if record and candidate.parent == content_root / str(record.get(_K.SPEC_PATH, "")):
      return candidate

    # the catalog root's level documents sit directly in the content root
    return candidate if candidate.parent == content_root else None

  def _resolve_folder_note_path(self, wikilink_target: str) -> Path:
    """
    Project a repo-relative wikilink target onto its folder-note path, with no existence check.

    Args:
      wikilink_target: Repo-relative path without the `.md` suffix (e.g.
        `Server/products/dashboards/csv-export/csv-export`).

    Returns:
      Absolute candidate folder-note path — may or may not exist on disk.
    """
    return self.repo / Path(wikilink_target + ".md")

  def _resolve_attach_folder_note(self, attach_target: str) -> Path:
    """
    Map a routing wikilink target onto an absolute folder-note path.

    Args:
      attach_target: The wikilink content (e.g. `request/products/test/csv-export/csv-export`).

    Returns:
      Absolute path to the resolved folder-note.

    Raises:
      SystemExit: When the target does not resolve to an existing folder-note.
    """
    candidate = self._resolve_folder_note_path(attach_target)

    # guard: the wikilink names no folder-note on disk
    if not candidate.is_file():
      _fail(_K.CAT_LOGICAL,
            f"attach target '{attach_target}' does not resolve to a folder-note ({candidate})")
    return candidate

  def _resolve_change_target(self, spec_path: str, raw_target: str) -> Path | None:
    """
    Resolve a change spawn's raw design-cascade target to its folder-note path.

    Args:
      spec_path: The spawning change's product `spec_path`.
      raw_target: Token from the routing decision's `targets=` field — a path relative to the
        product's `spec_path`, any number of segments: `<folder>/<slug>` under a group folder,
        a nested asset's full path, or a bare slug for an asset at the product root.

    Returns:
      The resolved folder-note path when it exists on disk, `None` when the
      token is malformed or names no existing asset.
    """
    parts = [ part for part in raw_target.split("/") if part ]

    # guard: an empty token, or one stepping out of the product tree, names nothing
    if not parts or any(part in (".", "..") for part in parts):
      return None
    # `spec_path` is content-root-relative, so the token resolves under the content root
    candidate = spec_content_root(self.repo).joinpath(spec_path, *parts, f"{parts[-1]}{_K.MD_SUFFIX}")
    return candidate if candidate.is_file() else None

  def _validate_change_targets(self, spec_path: str,
                               raw_targets: list[str]) -> tuple[list[str], list[str]]:
    """
    Partition a change spawn's raw design-cascade targets into resolvable and unresolvable sets.

    Args:
      spec_path: The spawning change's product `spec_path`.
      raw_targets: Product-relative path tokens from the routing decision's `targets=` field.

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
      valid_targets: Product-relative path tokens, of any depth, confirmed to resolve to real
        assets.
    """
    text = read_text(folder_note)
    _, fm_end = parse_frontmatter(text)
    fm_text = set_fm_list(text[:fm_end], SpecTargetsKey.TARGETS, valid_targets)
    write_text_atomic(folder_note, fm_text + text[fm_end:])

  def _write_reference_targets(self, resolved_paths: list[str]) -> None:
    """
    Write the request's resolved `reference` decision targets into its own frontmatter.

    The referenced asset's own doc and folder-note are left untouched — no doc edit, no
    `spec_source_requests` attribution, no review opened. The link lives only on the request
    file's own `spec_targets`.

    Args:
      resolved_paths: Repo-relative folder-note paths (wikilink form, no `.md` suffix) the
        `reference` decision named — every one already confirmed to resolve to a real asset.
    """

    # ref: `lazy-spec.coordination-playbook.md` Chapter 7 — a reference target is recorded in the
    # request's own `spec_targets`, the list key a change's design cascade also writes

    # the resolved targets land in the request's own frontmatter, and nowhere else
    text = read_text(self.file_path)
    _, fm_end = parse_frontmatter(text)
    write_text_atomic(self.file_path,
                      set_fm_list(text[:fm_end], SpecTargetsKey.TARGETS, resolved_paths) + text[fm_end:])

  def _cancel_active_job(self, job_info: dict) -> bool:
    """
    Cancel an asset's live expert job via the `lazycortex-core cancel-job` CLI.

    Unlike a best-effort follow-up, a caller cannot treat this as fire-and-forget: a False
    return means the job may still be running and must be handled accordingly rather than
    letting the document deletion proceed.

    Args:
      job_info: The tracked active-job marker (`checkbox` / `expert` / `job_id`).

    Returns:
      True when the CLI exits zero (the job is cancelled or was already terminal); False on a
      non-zero exit, meaning the job may still be live.

    Raises:
      SystemExit: When no lookup stage can find the `lazycortex-core` sibling CLI.
    """
    # the core CLI resolves the job against this repo's runtime, named through the environment
    env = os.environ.copy()
    env[_K.ENV_REPO_ROOT] = str(self.repo)

    # the cancel request names the job by its expert and id; only a clean exit counts as cancelled
    res = subprocess.run(
        [ sys.executable, str(_resolve_core(self.repo)), "cancel-job" ],
        input = json.dumps({
            "expert": job_info.get(JobMarker.EXPERT),
            "job_id": job_info.get(JobMarker.JOB_ID),
        }),
        capture_output = True,
        text = True,
        cwd = str(self.repo),
        env = env,
        check = False, encoding = "utf-8",
    )
    return res.returncode == 0

  def _stop_review_best_effort(self, doc_path: Path) -> None:
    """
    Stop review, best-effort, on a sibling doc an attach `drop=` names for deletion.

    Safe to call unconditionally, whether or not the doc was ever opened into review; any
    failure degrades to a silent skip, since the doc is about to be deleted regardless.

    Args:
      doc_path: Absolute path to the sibling document being dropped.
    """
    try:
      subprocess.run(
          [ sys.executable, str(self.review_cli), "stop", str(doc_path.resolve()) ],
          capture_output = True, text = True, cwd = str(self.repo),
          timeout = _K.REVIEW_STOP_TIMEOUT_S, check = False, encoding = "utf-8",
      )
    # waiver: fire-and-forget follow-up — the sibling doc is being dropped regardless of its
    # review state; ANY stop failure (CLI crash, timeout) must degrade to a silent skip, never raise
    except (OSError, subprocess.SubprocessError):
      pass


  def _drop_attached_docs(self, folder_note: Path, drop_docs: list[str]) -> None:
    """
    Delete the sibling documents an attach line's `drop=` names from the attached asset.

    Applies to every asset type and never flips a gate. An empty `drop_docs` cancels and deletes
    nothing. Otherwise the asset's live expert job is cancelled, review on each named sibling is
    stopped on a best-effort basis, and the siblings are deleted; each deleted path is recorded
    in `dropped_docs` for the run's single commit as soon as it is deleted. A failed review stop
    never aborts the drop. Once a running job is confirmed cancelled, any failure before this
    asset's first deletion (clearing the job's tracking record, reading the folder, a surviving
    named sibling, any other error) halts the asset here with `PLAN_DROP_PARTIAL` exactly once
    before the failure propagates, because a half-dropped asset is worse than an intact one. A job
    that cannot be confirmed cancelled halts the asset too. With no job cancelled and nothing
    deleted, only a surviving named sibling halts the asset; any other failure, such as an
    unresolvable core CLI, propagates without a halt. After this asset's first deletion the caller
    halts the asset once with those deletions. A completed drop that cancelled the job but deleted
    nothing is recorded in `cancelled_assets`. Every failure aborts the whole apply run before the
    request is attributed, and all drops precede any attribution. When a later step of the run
    fails with any error, the caller halts every asset of the targets dropped before it that lost
    documents or had its job cancelled.

    Args:
      folder_note: Absolute path to the asset's `<slug>/<slug>.md`.
      drop_docs: Bare sibling filenames, already validated by the caller, that the attach decision's
        own `drop=` field named. An empty list cancels and deletes nothing — which documents are
        dropped is the router's decision, not a fixed list this worker knows.

    Raises:
      SystemExit: When `cancel-job` does not confirm the active job is no longer live, or when a
        named sibling survives its deletion attempt while nothing of this asset was deleted yet;
        the asset is halted here first. Also raised, without a halt here, when a named sibling
        survives after this asset's first deletion (the caller halts the asset with its deleted
        paths) and when no lookup stage can find the `lazycortex-core` sibling CLI needed to
        cancel the job.
      OSError: When clearing the job's tracking record or reading the asset folder fails before
        this asset's first deletion; the asset is halted here first once a running job was cancelled,
        otherwise the error propagates without a halt.
      Exception: Any other failure before the first deletion propagates unchanged, after the halt
        here when a running job was cancelled; any failure after the first deletion propagates
        unchanged and the caller halts the asset with the deletions made so far.
    """

    # Domain(spec.lifecycle):
    # # Attach drop
    # The drop is the one destructive part of an attach. When the routing decision names documents to drop, any
    # expert job still running against the asset is cancelled first, review on each named document is stopped, and
    # only then are the documents removed. When the pass completes, the deletions land in the same apply commit as
    # the rest of the run; when it fails after a deletion, they land in the halt record instead. Which documents are
    # named is the router's judgement, not a fixed list, so a decision naming none deletes and cancels nothing. A
    # drop never flips a gate, whatever the asset type.
    #
    # A failure before anything was lost stops the pass without a halt, because the asset lost nothing: the tooling
    # to cancel the job cannot be found, or no job was running and nothing has been deleted yet. The one exception is
    # a named document that survives its deletion, which halts the asset even then. Once a running job is confirmed
    # cancelled, the asset has lost something, so any failure before its first deletion halts it here, exactly once:
    # the job's tracking record cannot be cleared, the folder cannot be read, or a document survives. A job that
    # cannot be confirmed cancelled halts it as well. A failure after the first deletion is halted by the pass as a
    # whole, with the deletions recorded. A later failure in the pass also halts an asset whose job was cancelled but
    # none of whose documents was deleted, with no deleted paths. Either way the whole pass stops before the request
    # is attributed. A cancelled job with documents half deleted is a state nothing downstream can tell apart from
    # intended work, so the automation must not act on it; halting leaves a state an operator can see and resolve.

    # guard: an empty drop list touches nothing — no job cancel, no sidecar change, no deletion
    if not drop_docs:
      return

    # the asset folder holds every named sibling and is the unit a halt marks
    asset_dir = folder_note.parent

    # step 1a — read the tracked job off the runtime sidecar; the folder-note carries no marker
    cancelled = False
    job_info = spec_job_markers.read(self.repo, folder_note)[JobMarker.ACTIVE_JOB]
    if isinstance(job_info, dict):
      # step 1b — a live expert job must be cancelled before any named document is touched
      # guard: cancel-job could not confirm the job is dead — deleting documents a live job may
      # still write is worse than leaving them, so halt the asset and abort rather than continue
      if not self._cancel_active_job(job_info):
        flip_gate.halt_asset(asset_dir, HaltReason.PLAN_DROP_PARTIAL)
        _fail(_K.CAT_LOGICAL,
              f"attach drop halted on {asset_dir.name}: cancel-job did not confirm "
              "the active job is no longer live")

      # the job is confirmed dead, so its stale marker comes off the sidecar below
      cancelled = True

    # once the job was cancelled the asset has lost something, so any failure before its first deletion halts
    # it here exactly once; after a first deletion the run-level handler halts it with those deletions instead
    halted = False
    deleted_any = False
    try:
      # step 1c — the cancelled job is no longer tracked on the note
      if cancelled:
        spec_job_markers.update(self.repo, folder_note, { JobMarker.ACTIVE_JOB: None })

      # step 2 — best-effort review stop on each dropped sibling before it is deleted
      named_siblings = [ asset_dir / name for name in drop_docs ]
      for sibling in named_siblings:
        if sibling.is_file():
          self._stop_review_best_effort(sibling)

      # step 3 — drop the named siblings from the worktree; a survivor means a half-done drop
      # Each deleted path is recorded the moment it is gone, for the run's own apply commit rather
      # than staged here for whichever commit happens to run next, so an error raised mid-drop still
      # finds every deletion so far and the caller's handler halts the asset with them in its commit.
      for sibling in named_siblings:
        if sibling.exists():
          try:
            sibling.unlink()
          # a failed unlink (e.g. a non-empty directory in the file's place) is diagnosed by the
          # existence re-check right below, not by the exception itself
          except OSError:
            pass

          # guard: the sibling survived its own deletion attempt — abort rather than attribute the
          # request to an asset that is only partly dropped; once a sibling of this asset is already
          # deleted, the caller's handler halts it with those deletions, so only an asset that lost
          # nothing yet is halted here and no asset is ever halted twice
          if sibling.exists():
            if not deleted_any:
              flip_gate.halt_asset(asset_dir, HaltReason.PLAN_DROP_PARTIAL)
              halted = True
            _fail(_K.CAT_LOGICAL,
                  f"attach drop halted on {asset_dir.name}: {sibling.name} did not unlink")

          # the deletion joins the run's single apply commit, which stages it by explicit path
          self.dropped_docs.append(sibling)
          deleted_any = True
    except BaseException:
      # guard: a cancelled job with nothing deleted and no halt yet leaves the asset halted before re-raising
      if cancelled and not deleted_any and not halted:
        flip_gate.halt_asset(asset_dir, HaltReason.PLAN_DROP_PARTIAL)
      raise

    # a completed drop that cancelled the job but deleted nothing is remembered, so a later failure of the
    # pass still halts the asset that lost its job; one that deleted something is found through its deletions
    if cancelled and not deleted_any:
      self.cancelled_assets.add(asset_dir)

  def _attach_to_folder_note(self, folder_note: Path,
                             request_display: str) -> list[Path]:
    """
    Record the request's attribution on an attach target's primary doc and folder-note.

    The target's body is never seeded — the writer reads the request first-hand from its job
    context, so attribution is the whole delta an attach lands.

    Args:
      folder_note: Absolute path to `<slug>/<slug>.md`.
      request_display: Display gloss used in the `## Requests` and folder-note bullets.

    Returns:
      List of authored docs whose attribution changed (used to open review on each).
    """
    # the product's own declarations decide the primary doc — a type declared only by this product
    # would otherwise silently fall back to the shipped default
    primary_path = folder_note.parent / _Attach.primary_doc_for_kind(
        _Attach.kind_from_folder_note(folder_note), self._record_for_note(folder_note))
    populated: list[Path] = []
    if primary_path.is_file():
      # attribution is the review trigger: a changed source list re-enters the doc into review
      if _Attach.ensure_source_request(primary_path, self.request_wikilink, request_display):
        populated.append(primary_path)
    _FolderNote.append_source_request(folder_note, self.request_wikilink, request_display)
    return populated

  def _open_review(self, doc_path: Path) -> None:
    """
    Open a review cycle on a populated doc via the `lazycortex-review` CLI.

    Args:
      doc_path: Absolute path to the populated authored doc.

    Raises:
      SystemExit: When the review CLI exits non-zero for a reason other than an already-open
        review.
    """
    res = subprocess.run(
        [ sys.executable, str(self.review_cli), PlanReview.START_VERB, str(doc_path) ],
        cwd = str(self.repo),
        capture_output = True,
        text = True,
        check = False, encoding = "utf-8",
    )

    # guard: review-start is idempotent — non-zero exit on already-open is benign;
    # surface only when stderr names an unexpected failure
    if res.returncode != 0 and _K.REVIEW_START_IDEMPOTENT_MARK not in (res.stderr or "").lower():
      _fail(_K.CAT_LOGICAL,
            f"lazycortex-review {PlanReview.START_VERB} failed on {doc_path}: "
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
    text = read_text(self.file_path)
    _, fm_end = parse_frontmatter(text)

    # the frontmatter takes the terminal class, status and mirror tag
    fm_text = _stamp_request_terminal(
        text[:fm_end], request_class = request_class, request_status = request_status,
    )

    # the body loses its routing section and any older status callout, then gains the new one
    body = _strip_routing(text[fm_end:])
    body = _strip_prior_status_callout(body)
    body = _insert_status_callout(body, _format_status_callout(
        accepted = request_status == _K.STATUS_ACCEPTED, wikilinks = resolved_wikilinks,
        reason = reject_reason,
    ))
    write_text_atomic(self.file_path, fm_text + body)

  def _touched_paths(self, inbox: Path) -> list[str]:
    """
    Collect the repo-relative paths this apply pass is responsible for.

    Args:
      inbox: The requests folder-note, whose container stats are refreshed on every pass.

    Returns:
      Repo-relative path strings — the request file, the inbox note when present, each
      populated document, each attach target, the whole folder of each spawned asset and of each
      spawned product, and the settings file when this pass registered anything in it.
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

    # a spawned product's level note and seeded vision both live under its own spec folder
    paths.extend(self.spawn_product_dirs)

    # the product record is part of the same atomic apply
    if self.settings_written:
      paths.append(self._settings_path)

    # the same path can arrive from several sources, and git rejects a duplicated pathspec
    pathspec: list[str] = []
    for path in paths:
      rel = str(path.resolve().relative_to(self.repo))
      if rel not in pathspec:
        pathspec.append(rel)
    return pathspec

  def _commit(self, *, subject: str) -> None:
    """
    Commit the paths this pass touched, their icon repaint and the dropped documents under the bot identity.

    Notes:
      - The requests inbox note's stats line is refreshed first and joins the commit.

    Args:
      subject: One-line commit subject describing the pass.

    Raises:
      SystemExit: When the commit itself fails.
    """
    # the inbox stats line goes stale on every apply, so refresh it before it joins the commit set
    inbox = spec_content_root(find_settings_root(self.file_path.parent)) / _K.REQUESTS_DIR / _K.REQUESTS_NOTE
    if inbox.is_file():
      apply_container_stats(inbox)

    # the resolve-walk behind the touched set is not free, and the same set feeds the repaint
    # and the commit pathspec below
    touched_paths = self._touched_paths(inbox)

    # fold the touched notes' icon repaint into this same commit so no separate icons commit
    # follows; the repaint op itself skips non-markdown paths
    touched_paths.extend(iconize_inline.repaint_paths(self.repo, touched_paths))

    # a dropped document rides the commit as a deletion, each named once; one the index never knew
    # drops out of the pathspec on its own, and a re-run that changed nothing commits nothing
    dropped = [ str(doc.resolve().relative_to(self.repo)) for doc in self.dropped_docs ]
    touched_paths.extend(rel for rel in dict.fromkeys(dropped) if rel not in touched_paths)
    try:
      flip_gate.commit_paths(
          self.repo, touched_paths, subject = subject,
          author_name = self.author_name, author_email = self.author_email, repaint = False,
      )

    # a failed commit leaves the tree dirty and would halt the daemon silently, so the run aborts loudly
    except subprocess.CalledProcessError as error:
      stderr = os.fsdecode(error.stderr or b"")
      _fail(_K.CAT_LOGICAL, f"git commit failed: exit={error.returncode} stderr={stderr.strip()[:240]}")

  def run(self) -> int:
    """
    Drive one apply transition on the request file.

    Guarantees:
      - Every attach and reference target is resolved and checked before any document is dropped or any
        expert job cancelled; a refusal aborts the run with no attached asset touched. Assets the same request
        spawns are created before the checks and are not covered.
      - Cancelled and halted refusals apply to attach targets only; a reference target must merely resolve.
      - A `drop=` name is refused when it is not a bare sibling filename (a path separator or `:` in it
        included) or when it names the asset's status note or start document, in any letter case. A name that
        passes this rule but cannot be deleted, such as a folder, is not refused up front; the drop halts that
        asset when the document survives.
      - An attach line onto a level document that carries any `drop=` name is refused up front, with nothing
        dropped or cancelled on any attached asset.
      - Every attach target's documents are dropped before any target is attributed to the request, so a
        failed drop leaves no start document attributed, neither on disk nor in a halt commit.
      - Once the drop of an attach asset has completed having deleted one of its documents or cancelled its
        live expert job, a later failure of any kind halts each such asset with `PLAN_DROP_PARTIAL` and then
        propagates unchanged. The halt of an asset whose own folder lost documents carries its deleted paths;
        an asset whose job was cancelled while none of its documents was deleted is halted with none. This
        includes a failure inside one asset's own drop after its first deletion: that asset is
        halted once, by this handler, with its already-deleted paths; the drop halts the asset itself only when
        nothing of it was deleted yet.
      - An asset is never halted for the deletions of an outer or nested asset.

    Returns:
      Exit code: `0` on success or idempotent terminal-state skip.

    Raises:
      SystemExit: On any logical refusal — an unresolvable or refused target, a `drop=` name that is not a
        bare sibling filename (a path separator or `:` in it included) or that names the asset's status
        note or start document in any letter case, an attach line onto a level document that carries any
        `drop=` name (refused up front), an occupied `spec_path`, a registered key whose path
        diverges from the decision's, two `spawn-product` targets of the decision over one `spec_path`
        (every `spawn-product` target is refused before the first is registered), a failed sibling CLI,
        a named sibling that survives its deletion after the asset's first deletion (the run-level
        handler halts the asset with its deleted paths before the abort), or a failed review opening, request
        stamp or commit — carrying a JSON error object on stdout and exit `1`.
      Exception: Any non-`SystemExit` error raised after a document was dropped or an expert job was cancelled
        propagates unchanged, after the assets that lost documents or whose job was cancelled are halted.
    """

    # Contract:
    # Every attach and reference target MUST be resolved and checked against its refusal guards before any
    # document is dropped or any expert job is cancelled. An unresolvable target, a cancelled or halted
    # attach target, a drop name that is not a bare sibling filename (one containing a path separator or a
    # colon included), a drop name that matches the asset's status note or start document in any letter
    # case, and an attach line onto a level document that carries any drop name each abort the run, with
    # nothing dropped or cancelled on any attached asset. A reference target is only required to
    # resolve. Assets the same request spawns are created before the checks and are not covered by this
    # promise. A drop name that passes the name rule but cannot be deleted, for instance a folder, is not
    # refused up front: the drop halts that asset when the document survives.

    # Contract:
    # Once the drop of an attach asset has completed having deleted one of its documents or cancelled its
    # live expert job, any later failure of the same run, of whatever kind, MUST halt each such asset with
    # PLAN_DROP_PARTIAL, and then propagate unchanged: a refusal stays a refusal and any other error
    # reaches the caller as itself. The halt of an asset whose own folder lost documents carries that
    # asset's deleted paths; an asset whose job was cancelled while none of its documents was deleted is
    # halted all the same, with no deleted paths. This also covers a failure inside one asset's own drop
    # after its first deletion: that asset is halted once, by the run-level handler, with its
    # already-deleted paths in the halt commit, while the drop halts the asset itself only when nothing of
    # it was deleted yet. An asset is NEVER halted for the deletions of an outer or nested asset.

    # Contract:
    # The documents of every attach target MUST be dropped before any target is attributed to the request,
    # so a failed drop leaves no start document attributed, neither on disk nor in a halt commit.

    # Domain(spec.lifecycle):
    # # One attach pass, all or nothing
    # A request can attach to or reference several assets at once, so every one of them is checked before anything is
    # touched: each must resolve. An attached asset must in addition be neither cancelled nor halted; a reference
    # touches nothing on the referenced asset, so those two refusals never apply to it. A document named for dropping
    # must be a plain document sitting directly in the attached asset's own folder, never its status note nor its
    # start document, matched regardless of letter case. A level document is never dropped, so a request naming
    # documents to drop from one is refused up front like any other bad name. A name that could reach outside the
    # folder, through path separators, a parent-directory step, or a drive or stream colon, is refused. A named
    # document that passes this name rule but cannot be deleted, for instance because it is a folder, is not refused
    # up front: the drop halts that asset when the document survives its deletion. Only when all checks pass does any
    # document get dropped or any job get cancelled, so a refusal anywhere refuses the whole pass with every attached
    # asset exactly as it was. New assets the same request spawns are created before the checks, because an attach
    # may target a product spawned in the same request, so the promise covers the attached assets and not the
    # request's new ones.
    #
    # The documents of every attached asset are dropped before any asset is attributed to the request, so a failed
    # drop leaves no asset attributed.
    #
    # Any failure after the drops, of whatever kind, halts exactly the attached assets that lost something in this
    # pass, and then the failure propagates. An asset lost something when documents were deleted from its own folder,
    # or when a running job against it was cancelled, even if no document of it was deleted. The failure may be
    # another asset's drop failing, a failure inside the asset's own drop after its first deletion, the request's
    # attribution, the review not reopening, or the pass not being recorded. An asset around such an asset or nested
    # inside it lost nothing of its own and is never halted.

    # the frontmatter status decides whether this pass has anything left to do
    text = read_text(self.file_path)
    values, fm_end = parse_frontmatter(text)

    # guard: terminal-state idempotence (md-scan filter normally excludes these,
    # but a same-tick race could still hand us one)
    if values.get(_K.REQUEST_STATUS) in ( _K.STATUS_ACCEPTED, _K.STATUS_REJECTED ):
      print(json.dumps({ _K.OUT_OUTCOME: _K.OUTCOME_SUCCESS, _K.OUT_SKIP: _K.OUTCOME_TERMINAL_SKIP }))
      return 0

    # the `# Routing` section the router wrote is the whole instruction set for this pass
    body = text[fm_end:]
    cls, spawn_targets, attach_targets, routing_text = _parse_routing(
        body, asset_types.folder_map(self.repo),
    )
    request_class = cls or values.get(_K.REQUEST_CLASS) or _K.CLASS_UNKNOWN

    # the identity-only spawn/attach lists above carry no descriptions or cascade targets —
    # pull those from the rich parse of the same structured block, when one is present;
    # `reference` targets and a spawn line's own `product=` field are parsed separately, via
    # `_parse_reference_targets` and `_parse_spawn_products` (see the `# Decision:` note on
    # `_parse_routing_decision_rich`)
    decision_block = _extract_decision_block(routing_text)
    spawn_cascades: dict[tuple[str, str], list[str]] = {}

    # a `:: description` tail is tolerated on every line but seeded nowhere — writers read the
    # request itself from job context, so only structural fields are consumed here
    reference_targets: list[str] = []
    spawn_product: dict[tuple[str, str], str] = {}
    spawn_paths: dict[tuple[str, str], str] = {}
    spawn_tools: dict[tuple[str, str], list[str]] = {}
    attach_drops: dict[str, list[str]] = {}
    product_targets: list[tuple[str, str, str]] = []
    if decision_block is not None:
      spawn_rich, _attach_rich = _parse_routing_decision_rich(
          decision_block, known_kinds = self._read_known_kinds())
      for kind, slug, _description, targets in spawn_rich:
        spawn_cascades[( kind, slug )] = targets
      reference_targets = [ path for path, _description in _parse_reference_targets(decision_block) ]
      spawn_product = _parse_spawn_products(decision_block)
      spawn_paths = _parse_spawn_paths(decision_block)
      spawn_tools = _parse_spawn_tools(decision_block)
      attach_drops = _parse_attach_drops(decision_block)
      product_targets = _parse_spawn_product_targets(decision_block)

    # the display gloss must come from the request's OWN H1, not from `# Routing` (which is the
    # first H1 in the raw body before strip). Read from `_request_content_block` which already
    # filters out `# Routing` and `# History` sections.
    request_display = _request_h1_title(_request_content_block(body))

    # a routing section naming no target of any kind has nothing to apply, so the request is
    # rejected outright — a `reference`-only decision is NOT this case: it is a full accept
    # (playbook Chapter 7 / upstream § 10 — a request made up of reference targets alone is
    # still a fully accepted request)
    if not spawn_targets and not attach_targets and not reference_targets and not product_targets:
      self._stamp_request_file(
          request_class = request_class,
          request_status = _K.STATUS_REJECTED,
          resolved_wikilinks = [],
          reject_reason = _K.REJECT_REASON_DEFAULT,
      )
      self._commit(
          subject = f"apply: stamp rejected on {self.file_path.relative_to(self.repo)}",
      )
      print(json.dumps({ _K.OUT_OUTCOME: _K.OUTCOME_SUCCESS, _K.OUT_RESULT: _K.STATUS_REJECTED,
                         _K.OUT_REQUEST_CLASS: request_class }))
      return 0

    # the wikilinks of every target this pass resolves, stamped into the accepted request's callout
    resolved_wikilinks: list[str] = []

    # every product target is checked before the first is written, against the registry and the
    # disk and against the other targets of this decision, so a refused line leaves the settings
    # untouched instead of half a decision registered
    claimed: dict[str, str] = {}
    for key, spec_path, _description in product_targets:
      self._validate_product_target(key, spec_path)

      # guard: two targets of one decision over the same tree would register it twice
      if (other := claimed.setdefault(spec_path, key)) != key:
        _fail(_K.CAT_LOGICAL,
              f"spawn-product '{key}': path '{spec_path}' is also claimed by '{other}' in this decision")

    # an enclosing product is registered before the products nested in it, so a nested folder
    # never appears on disk ahead of its parent's registration
    product_targets.sort(key = lambda target: len(PurePosixPath(target[1]).parts))

    # a product is registered before any asset spawn, so a spawn line may already name it in its
    # own `product=` field within the same routing decision
    for key, spec_path, _description in product_targets:
      resolved_wikilinks.append(str(self._spawn_product(key, spec_path, request_display)
                                    .relative_to(self.repo).with_suffix("")))

    # a spawn target scaffolds its folder and folder-note alone — documents are seeded later,
    # by the coordinator's launch checkboxes, so only the note's attribution is written here
    for kind, slug in spawn_targets:
      folder_note, spec_path = self._spawn(
          kind, slug, product = spawn_product.get(( kind, slug )),
          path = spawn_paths.get(( kind, slug ), ""),
          tools = spawn_tools.get(( kind, slug )))
      resolved_wikilinks.append(str(folder_note.relative_to(self.repo).with_suffix("")))
      _FolderNote.append_source_request(folder_note, self.request_wikilink, request_display)
      self.spawn_folder_notes.append(folder_note)

      # a change spawn may cascade its design onto existing assets via routing's targets= field
      if kind == _K.CHANGE_KIND:
        if raw_targets := spawn_cascades.get(( kind, slug ), []):
          valid, invalid = self._validate_change_targets(spec_path, raw_targets)
          for raw in invalid:
            self.warnings.append(
                f"spec_targets: '{raw}' does not resolve to an existing asset "
                f"(change '{slug}')",
            )
          if valid:
            self._write_spec_targets(folder_note, valid)

    # every attach target is resolved and checked against its refusal guards before anything is
    # dropped — a refusal on a later target must never find an earlier target's documents already
    # gone or its job already cancelled; each entry names the level document or the asset
    # folder-note the target resolved to, flagged True for a level document
    attach_plan: list[tuple[str, Path, bool]] = []
    for target in attach_targets:
      # a level has no status note above its documents, so a level document is stamped directly
      # and re-enters review on its own, with nothing else to resolve or roll back
      if (level_doc := self._level_doc_target(target)) is not None:
        # guard: a level document is never dropped, so a `drop=` field on a level target is refused rather than
        # ignored
        if attach_drops.get(target):
          _fail(_K.CAT_LOGICAL, f"attach target '{target}' is a level document — `drop=` is refused there")
        attach_plan.append(( target, level_doc, True ))
        continue

      # an asset target is read through its status folder-note, whose state gates what follows
      folder_note = self._resolve_attach_folder_note(target)
      fm_values, _ = parse_frontmatter(folder_note.read_text(encoding = "utf-8"))

      # guard: a cancelled asset refuses every attach outright, before any named document is
      # deleted — an attach would otherwise destroy siblings and reopen review on a dead asset
      if fm_values.get(Gate.SPEC_CANCELLED, "").strip().lower() == BOOL_TRUE:
        _fail(_K.CAT_LOGICAL,
              f"attach target '{target}' is cancelled — automation is refused")

      # guard: all automation stays off a halted asset until an operator resolves it by hand —
      # an attach must neither delete documents nor attribute and reopen review
      if fm_values.get(SpecHaltKey.HALTED, "").strip().lower() == BOOL_TRUE:
        _fail(_K.CAT_LOGICAL,
              f"attach target '{target}' is halted — automation is refused until an "
              "operator resolves it")

      # every `drop=` name is checked here, before any cancel or deletion of any target: only a bare
      # sibling filename is droppable, never the status note itself nor the start document the attach
      # reopens for review; a name free of both separators and of `:` cannot be absolute or
      # drive-relative either. The comparison ignores letter case, since on a case-insensitive
      # filesystem a differently cased name opens the same file
      start_doc = _Attach.primary_doc_for_kind(
          _Attach.kind_from_folder_note(folder_note), self._record_for_note(folder_note))
      undroppable = { doc_name.casefold() for doc_name in ( folder_note.name, start_doc ) }
      for name in attach_drops.get(target, []):
        # guard: a path-shaped name could reach outside the asset folder or into a nested asset; a `:`
        # marks a drive-relative path or an alternate data stream, never a bare sibling filename
        if "/" in name or "\\" in name or ":" in name or name in ( "", ".", ".." ):
          _fail(_K.CAT_LOGICAL,
                f"attach target '{target}': drop name '{name}' is not a bare sibling filename")

        # guard: the status note and the start document are the asset itself, never droppable siblings
        if name.casefold() in undroppable:
          _fail(_K.CAT_LOGICAL,
                f"attach target '{target}': drop name '{name}' names the asset's status note or "
                "start document")

      # the asset passed every guard, so its folder-note joins the plan
      attach_plan.append(( target, folder_note, False ))

    # a reference target registers only a link — no scaffold, no seed, no review, and the
    # target's own doc/folder-note is never touched (playbook Chapter 7 / upstream § 10);
    # existence is still validated, reusing the same resolver an attach target uses, and before
    # any drop (any unresolvable target aborts the whole run via `_fail`, so every survivor is real)
    for target in reference_targets:
      self._resolve_attach_folder_note(target)

    # an attach target already exists, so only the attribution delta applies, plus the deletion
    # of any documents its `drop=` field names; no gate moves, whatever the asset type — attach
    # or a change was the operator's choice at routing
    # once the first document is dropped, an abort from there on would leave the asset dirty and
    # un-halted, so every asset that lost documents is halted with its deletions before the abort
    # propagates — a failing drop on a later target included, and any error, not only a refusal
    try:
      # every target's `drop=` documents are deleted before any target is attributed, so a drop that
      # fails on a later target never finds an earlier target's start document already attributed;
      # an empty `drop=` leaves the asset's files, its job and its review state as they are
      for target, target_path, is_level in attach_plan:
        if not is_level:
          self._drop_attached_docs(target_path, attach_drops.get(target, []))

      # only once every drop has landed does any target take the request's attribution
      for target, target_path, is_level in attach_plan:
        # a level document takes the attribution directly; the token may carry `.md`, a wikilink
        # never does — the spawn branch drops it the same way
        if is_level:
          resolved_wikilinks.append(str(target_path.relative_to(self.repo).with_suffix("")))
          if _Attach.ensure_source_request(target_path, self.request_wikilink, request_display):
            self.populated_docs.append(target_path)
          continue

        # the attribution step itself is unconditional — a drop never decides whether it runs
        resolved_wikilinks.append(target)
        self.populated_docs.extend(self._attach_to_folder_note(target_path, request_display))
        self.attach_folder_notes.append(target_path)

      # the reference targets were resolved above; they land as links only
      resolved_wikilinks.extend(reference_targets)
      if reference_targets:
        self._write_reference_targets(reference_targets)

      # every doc whose attribution changed re-enters the review loop through a writer round
      for doc in self.populated_docs:
        self._open_review(doc)

      # the stamp records where the request landed, and the commit makes the whole pass atomic
      self._stamp_request_file(
          request_class = request_class,
          request_status = _K.STATUS_ACCEPTED,
          resolved_wikilinks = resolved_wikilinks,
          reject_reason = None,
      )
      self._commit(
          subject = f"apply: stamp accepted + strip Routing on {self.file_path.relative_to(self.repo)}",
      )
    except BaseException:
      # each attach asset whose documents this run deleted, or whose job it cancelled, is halted, its deletions in
      # the commit; a drop names bare siblings only, so an asset's deletions sit directly in its own folder and a
      # nested asset's never count toward the asset around it. An asset halts itself in its own drop only before it
      # lost any document, so it records no deletion here and is never halted twice.
      for _target, target_path, is_level in attach_plan:
        asset_deleted = [ doc for doc in self.dropped_docs if not is_level and doc.parent == target_path.parent ]
        if asset_deleted or (not is_level and target_path.parent in self.cancelled_assets):
          flip_gate.halt_asset(target_path.parent, HaltReason.PLAN_DROP_PARTIAL, extra_paths = asset_deleted)
      raise

    # the counts let the calling routine report what this pass produced
    print(json.dumps({
        _K.OUT_OUTCOME: _K.OUTCOME_SUCCESS,
        _K.OUT_RESULT: _K.STATUS_ACCEPTED,
        _K.OUT_REQUEST_CLASS: request_class,
        _K.OUT_SPAWN_COUNT: len(self.spawn_folder_notes),
        _K.OUT_ATTACH_COUNT: len(self.attach_folder_notes),
        _K.OUT_POPULATED_COUNT: len(self.populated_docs),
        _K.OUT_WARNINGS: self.warnings,
    }))
    return 0


def main(argv: list[str]) -> int:
  """
  Run the `apply-request` subcommand against one request file.

  Guarantees:
    - Re-running the subcommand on a `spawn-product` decision for a key already on record under the same
      `spec_path` is a no-op: the recorded product record is never rewritten, so a re-run never clobbers
      fields an operator has since edited.
    - Every `spawn-product` target of a routing decision is validated before the first is registered, against
      the registry, the disk, and the other targets of the same decision, so two targets over one `spec_path`
      are refused. A refusal of any target, including a well-formed `spawn-product` line (one carrying the
      `::` separator) with any field other than `key` and `path`, ends the run with exit status `1` before
      the first settings write. A refused decision registers no product, creates no product folder, persists
      nothing else, and leaves `lazy.settings.json` byte-identical.
    - Nested `spawn-product` targets are registered enclosing-product-first, whatever order the decision
      lists them in.
    - A `reference` routing decision touches nothing on the referenced asset: no doc edit, no
      `spec_source_requests` attribution, no review opened.

  Args:
    argv: Subcommand argv tail (positional `<file>` + optional `--author-*` flags).

  Returns:
    Process exit code: `0` on success or idempotent skip; `2` when the file does not exist or
    is not a markdown file.

  Raises:
    SystemExit: With status `2` when argument parsing fails, or with status `1` when the apply
      pass hits a logical error.
  """
  parser = argparse.ArgumentParser(prog = _K.PROG)
  parser.add_argument(_K.ARG_FILE, type = Path)
  parser.add_argument(_K.ARG_AUTHOR_NAME, default = _K.BOT_NAME_DEFAULT)
  parser.add_argument(_K.ARG_AUTHOR_EMAIL, default = _K.BOT_EMAIL_DEFAULT)
  args = parser.parse_args(argv)
  file_path: Path = args.file

  # guard: a relative path from argparse — resolve it to absolute before use
  if not file_path.is_absolute():
    file_path = file_path.resolve()

  # guard: a missing file, or one that is not a markdown request
  if not file_path.exists() or file_path.suffix.lower() != _K.MD_SUFFIX:
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2

  # Contract:
  # Re-running apply-request on a spawn-product decision for a key already on record under the
  # same spec_path is a no-op. The recorded product record is never rewritten, so a re-run
  # never clobbers fields an operator has since edited.

  # Contract:
  # Every spawn-product target of a routing decision is validated before the first one is
  # registered: against the registry, against the disk, and against the other targets of the
  # same decision, so two targets over one spec_path are refused. A refusal of any target,
  # whether an occupied or already-registered spec_path, a spec_path shared by two targets, or
  # a well-formed spawn-product line (one carrying the :: separator) with any field other than
  # key and path, ends the run with exit status 1 before the first settings write. A refused
  # decision registers no product, creates no product folder, persists nothing else, and leaves
  # lazy.settings.json byte-identical, so it never leaves half a registration.

  # Contract:
  # Nested spawn-product targets are registered enclosing-product-first, whatever order the
  # decision lists them in.

  # Contract:
  # A reference routing decision touches nothing on the referenced asset: no doc edit,
  # no spec_source_requests attribution, no review opened. The link lives only on the
  # request file's own spec_targets.

  # one apply pass over the request, its exit code handed straight back
  return _Apply(
      file_path = file_path,
      author_name = args.author_name,
      author_email = args.author_email,
  ).run()


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
