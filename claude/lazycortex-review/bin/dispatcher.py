"""Per-file orchestration — wire the pure state machine to the file
system, git, and the expert runtime.

One `process_one_file(repo, file_path)` call:

1. Loads `review.classes` from `<repo>/.claude/lazy.settings.json`.
2. Locates the file's review class.
3. Parses the file (frontmatter + body).
4. Walks git history to derive per-file state.
5. Builds :class:`state_machine.TickInputs` and calls `decide`.
6. Executes the returned :class:`state_machine.TickAction` (dispatch
   a job, collect a pending job, write a mechanical commit, etc).
7. Returns the per-file summary dict.

The dispatcher does ONE thing per file per scan tick (the banner-tick
invariant). The runtime daemon's `lazy-review.scan` md-scan routine
calls `process_one_file` once per matching file per tick and the
next tick re-evaluates from scratch.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# deferred imports below module code; position intentional (ruff E402 noqa guards it)
# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
# pylint: disable=import-error,wrong-import-position,deprecated-module

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Any

  from collections.abc import Iterable


# lazy-review reaches lazycortex-core ONLY via its published CLI — no
# Python-import coupling, no filesystem-walk binary discovery. See
# the inter-plugin boundary contract for the pattern.


def _resolve_core_cli() -> Path:
  """
  Find the `lazycortex-core` CLI binary.

  Two-stage lookup — env-first, then the plugin cache — so consumer
  behaviour matches operator expectation regardless of how
  `lazycortex-review` was invoked:

    1. Walk `$LAZYCORTEX_PLUGIN_DIRS` (set by the daemon when it
       spawns subprocess routines) for `<dir>/bin/lazycortex-core`.
    2. Fall back to the highest-versioned binary in the plugin cache
       under `~/.claude/plugins/cache/<registry>/lazycortex-core/<version>/bin/lazycortex-core`.
       Used when the env is unset (e.g. an operator running
       `lazycortex-review process-file` by hand outside the daemon's
       process tree, or by a consumer install that doesn't run the
       daemon at all).

  Returns:
    Absolute path to the resolved `lazycortex-core` binary.

  Raises:
    RuntimeError: When both lookup stages fail to find a binary.
  """
  # Stage 1 — env (operator-controlled order via --plugin-dir flags).
  dirs = os.environ.get("LAZYCORTEX_PLUGIN_DIRS", "").split(os.pathsep)
  for d in dirs:
    # guard: empty path segment (from a trailing/double pathsep) — skip it
    if not d:
      continue
    cli = Path(d) / Paths.BIN_DIR / Plugin.CORE
    if cli.is_file():
      return cli
# Stage 2 — plugin cache. Layout: <cache>/<registry>/lazycortex-core/<version>/bin/lazycortex-core.
  cache = Path.home() / Paths.PLUGIN_CACHE
  if cache.is_dir():
    plugin_dirs = [
        registry / Plugin.CORE
        for registry in cache.iterdir()
        if registry.is_dir() and (registry / Plugin.CORE).is_dir()
    ]
    all_versions = [v for pd in plugin_dirs for v in pd.iterdir() if v.is_dir()]
    if all_versions:
      latest = sorted(all_versions, key=lambda v: v.name, reverse=True)[0]
      cli = latest / Paths.BIN_DIR / Plugin.CORE
      if cli.is_file():
        return cli
  raise RuntimeError(
      "lazycortex-core CLI not resolvable: $LAZYCORTEX_PLUGIN_DIRS "
      "yields no match and the plugin cache has no lazycortex-core "
      "version with a bin/lazycortex-core entry. Either pass "
      "--plugin-dir to the daemon, or install lazycortex-core into "
      "the Claude Code plugin cache."
  )


def _call_core(subcommand: str, body: dict, repo: Path) -> dict:
  """
  Invoke `lazycortex-core <subcommand>` with a JSON body on stdin.

  The sole inter-plugin contract this module uses — both the write
  path (`dispatch-job`) and the read path (`collect-job`) flow
  through here. No filesystem layout assumptions; no Python import
  of sibling-plugin modules.

  Returns:
    Parsed JSON response dict from the CLI's stdout.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess as _subprocess
  cli = _resolve_core_cli()
  env = os.environ.copy()
  env[EnvVar.LAZY_REPO_ROOT] = str(repo)
  proc = _subprocess.run(
      [str(cli), subcommand],
      input=json.dumps(body),
      capture_output=True,
      text=True,
      env=env,
      check=False,
  )
  if proc.returncode != 0:
    raise RuntimeError(
        f"lazycortex-core {subcommand} exit={proc.returncode} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
  return json.loads(proc.stdout)


def _record_to_ledger(
    repo: Path,
    incident: str,
    cause: str,
    detail: str,
    *,
    expert: str | None = None,
) -> None:
  """
  Emit a review-consumer error incident to the core ledger. Best-effort, never raises.

  Pre-checks open incidents for the same `incident` key so a repeated
  tick on the same condition does not append a new event each time.

  Idempotency is per-incident; callers pick a stable key (e.g. `review-broken:<rel>`
  for parse-failure, `review-logical:<rel>:<section>` for logical-error per section).
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess as _subprocess
  try:
    cli = _resolve_core_cli()
    env = os.environ.copy()
    env[EnvVar.LAZY_REPO_ROOT] = str(repo)
    # guard: idempotency pre-check — skip emit when an open incident already covers this condition
    ls = _subprocess.run(
        [str(cli), "error-list", "--state", "open"],
        cwd=str(repo), capture_output=True, text=True, env=env, check=False,
    )
    if ls.returncode == 0:
      try:
        # guard: an open incident already covers this condition — don't re-emit
        if any(r.get(JobKey.INCIDENT) == incident for r in json.loads(ls.stdout)):
          return
      except (ValueError, json.JSONDecodeError):
        pass
    args = [str(cli), "error-record", "--kind", "job_error", "--cause", cause,
            "--incident", incident, "--detail", detail]
    if expert:
      args.extend(["--expert", expert])
    _subprocess.run(args, cwd=str(repo), capture_output=True, text=True, env=env, check=False)
  # waiver: error-ledger contract — error-record is fire-and-forget; a failed report must not abort the caller
  except Exception:
    pass


def _record_broken_to_ledger(repo: Path, file_path: Path) -> None:
  """
  Emit a file-parse-failure incident to the core ledger. Best-effort, never raises.

  Pre-checks open incidents for the same incident key so a repeated
  tick on the same broken file does not append a new event each time.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess as _subprocess
  try:
    cli = _resolve_core_cli()
    try:
      rel = file_path.relative_to(repo)
    except ValueError:
      rel = file_path
    incident = f"review-broken:{rel}"
    env = os.environ.copy()
    env[EnvVar.LAZY_REPO_ROOT] = str(repo)
    # guard: idempotency pre-check — skip emit when an open incident already covers this file
    ls = _subprocess.run(
        [str(cli), "error-list", "--state", "open"],
        cwd=str(repo), capture_output=True, text=True, env=env, check=False,
    )
    if ls.returncode == 0:
      try:
        # guard: an open incident already covers this file — don't re-emit
        if any(r.get(JobKey.INCIDENT) == incident for r in json.loads(ls.stdout)):
          return
      except (ValueError, json.JSONDecodeError):
        pass
    _subprocess.run(
        [str(cli), "error-record", "--kind", "job_error", "--cause", "broken",
         "--incident", incident,
         "--detail", f"parse failure after 3 repair attempts: {rel}"],
        cwd=str(repo), capture_output=True, text=True, env=env, check=False,
    )
  # waiver: error-ledger contract — error-record is fire-and-forget; a failed report must not abort the caller
  except Exception:
    pass


def _core_dispatch_job(repo: Path, bundle: dict) -> dict:
  """
  Queue a new expert job via the `dispatch-job` CLI.

  When the caller did not supply `protocols` in the bundle, fills it
  from the `LAZYCORTEX_ROUTINE_PROTOCOLS` env var — that is how the
  daemon's `command:`-shape routine spawn surfaces the routine's
  declared `protocols:` list to its subprocess.

  Returns:
    Response dict from the `dispatch-job` CLI call.
  """
  if JobKey.PROTOCOLS not in bundle:
    env_value = os.environ.get("LAZYCORTEX_ROUTINE_PROTOCOLS", "")
    protocols = [p for p in env_value.split(";") if p]
    bundle = {**bundle, JobKey.PROTOCOLS: protocols}
  return _call_core(CoreCommand.DISPATCH_JOB, bundle, repo)


def _parse_expert_name(name: str) -> tuple[str, str]:
  """
  Parse an expert name into `(expert, repo_key)` components.

  Returns:
    Tuple of `(bare_expert_name, repo_key)` where `repo_key` is `"."` for
    local experts and a named repos-block key for cross-repo ones.
  """
  if "@" not in name:
    return name, "."
  expert, _, repo = name.rpartition("@")
  if not expert or not repo:
    raise ValueError(f"malformed expert name {name!r}")
  return expert, repo


def _load_repos_block(local_repo: Path) -> dict:
  """
  Read the `repos` block from `<local_repo>/.claude/lazy.settings.json`.

  Returns:
    Mapping of repo keys to their config dicts, with `_version` stripped.
    Returns `{}` on a missing file or parse error.
  """
  settings_path = Path(local_repo) / Paths.CLAUDE_DIR / Paths.SETTINGS_FILE
  if not settings_path.exists():
    return {}
  try:
    data = json.loads(settings_path.read_text() or "{}")
  except json.JSONDecodeError:
    return {}
  block = data.get(JobKey.REPOS) or {}
  if not isinstance(block, dict):
    return {}
  return {k: v for k, v in block.items() if k != JobKey.VERSION}


def _resolve_target_repo(local_repo: Path, repo_key: str) -> Path:
  """
  Resolve a `repo_key` to an absolute filesystem path.

  Returns:
    Absolute resolved path of the target repo.

  Raises:
    RuntimeError: When `repo_key` is not declared in `lazy.settings.json` or
      its `path` field is missing.
  """
  local_repo = Path(local_repo).resolve()
  if repo_key == ".":
    return local_repo
  repos = _load_repos_block(local_repo)
  if repo_key not in repos:
    raise RuntimeError(
        f"repos.{repo_key} not declared in .claude/lazy.settings.json"
    )
  raw_path = (repos[repo_key] or {}).get(JobKey.PATH)
  if not raw_path:
    raise RuntimeError(
        f"repos.{repo_key} missing `path` field in lazy.settings.json"
    )
  return Path(raw_path).expanduser().resolve()


_LOOKUP_CACHE: dict[tuple[str, str], dict | None] = {}


def _reset_lookup_cache() -> None:
  """
  Clear the per-run expert-lookup cache.
  """
  _LOOKUP_CACHE.clear()


def _core_lookup_expert(target_repo: Path, name: str) -> dict | None:
  """
  Look up an expert entry in the target repo via the `lookup-expert` CLI.

  Results are cached by `(target_repo, name)` within the current run scope.

  Returns:
    Expert entry dict when found, or `None` when absent or on CLI error.
  """
  key = (str(target_repo), name)
  if key in _LOOKUP_CACHE:
    return _LOOKUP_CACHE[key]
  try:
    out = _call_core(CoreCommand.LOOKUP_EXPERT, {JobKey.NAME: name}, target_repo)
  except Exception:
    _LOOKUP_CACHE[key] = None
    return None
  entry = out.get(JobKey.ENTRY) if out.get(JobKey.FOUND) else None
  _LOOKUP_CACHE[key] = entry
  return entry


# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import banner as _banner  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import body as _body  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import edit_markup as _edit_markup  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import finalize as _finalize  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import frontmatter as _fm  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import git_ops as _git_ops  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import hashlib as _hashlib  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import history as _history  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from keys import (  # noqa: E402
    Action, Bucket, CommitterKind, CoreCommand, EnvVar, ErrorCause, JobFile, JobKey, JobStatus,
    Kind, Outcome, Paths, Phase, Plugin, Position, ReviewKey, Role, Style,
)
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import parser as _parser  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import payload as _payload  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import reapply as _reapply  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import state_machine as _sm  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from errors import ParseError  # noqa: E402


# -------------------------------------------------------- settings load


def load_settings(repo: Path) -> dict:
  """
  Read `<repo>/.claude/lazy.settings.json`.

  Returns:
    Parsed settings dict, or `{}` when the file is absent or unparseable.
  """
  p = repo / Paths.CLAUDE_DIR / Paths.SETTINGS_FILE
  if not p.exists():
    return {}
  try:
    return json.loads(p.read_text())
  except json.JSONDecodeError:
    return {}


def review_classes(settings: dict) -> list[dict]:
  """
  Extract the list of review class configurations from a settings dict.

  Args:
    settings: Parsed contents of `lazy.settings.json`.

  Returns:
    List of review class entries, or an empty list when none are configured.
  """
  return list(settings.get(JobKey.REVIEW, {}).get(JobKey.CLASSES, []))


def experts_table(settings: dict) -> dict[str, dict]:
  """
  Extract the experts registry from a settings dict.

  Args:
    settings: Parsed contents of `lazy.settings.json`.

  Returns:
    Mapping of expert dispatch names to their configuration dicts, or an empty dict when absent.
  """
  return dict(settings.get(JobKey.EXPERTS, {}))


class ExpertConfigError(ValueError):
  """
  Raised when the experts table violates the unique-email-per-expert invariant.
  """


def validate_experts_emails(experts_tbl: dict) -> None:
  """
  Validate that the experts table satisfies the author-identity contract.

  Every expert must have a non-empty `git_author.email` and email values
  must be globally unique across experts. The author email is used to
  classify trailerless commits as bot vs. operator; ambiguous or missing
  emails break that classification. Version markers, missing, and non-dict
  entries are skipped.

  Raises:
    ExpertConfigError: When any expert lacks an email or two experts share one.
  """
  email_to_owner: dict[str, str] = {}
  missing: list[str] = []
  duplicates: list[tuple[str, str, str]] = []  # (email, owner_a, owner_b)
  for name, entry in experts_tbl.items():
    # guard: skip the _version sentinel and any malformed (non-dict) entry
    if name == JobKey.VERSION or not isinstance(entry, dict):
      continue
    author = entry.get(JobKey.GIT_AUTHOR) or {}
    email = (author.get(JobKey.EMAIL) or "").strip()
    if not email:
      missing.append(name)
      continue
    if email in email_to_owner:
      duplicates.append((email, email_to_owner[email], name))
    else:
      email_to_owner[email] = name

  problems: list[str] = []
  if missing:
    problems.append(
        # waiver: one-off human-facing message
        "experts without git_author.email: " + ", ".join(sorted(missing))
    )
  if duplicates:
    for email, a, b in duplicates:
      problems.append(
          f"duplicate git_author.email {email!r} shared by {a!r} and {b!r}"
      )
  if problems:
    raise ExpertConfigError(
        "experts table violates unique-email invariant — "
        "the dispatcher's author-identity fallback can't classify "
        "agent commits unambiguously. Fix:\n  - "
        + "\n  - ".join(problems)
    )


def _participating_bot_emails(experts_tbl: dict, class_cfg: dict) -> set[str]:
  """
  Return the set of `git_author.email` values for experts that participate in this review class.

  Experts registered globally but not in this class are outsiders —
  their commits are treated as operator commits by the state machine.

  Returns:
    Set of email strings for participating experts.
  """
  participants: set[str] = set()
  for group_key, members in (class_cfg.get(JobKey.EXPERTS) or {}).items():
    if group_key == Phase.HISTORY:
        # history is a single writer object {"name": ...}, not a list.
      if isinstance(members, dict) and members.get(JobKey.NAME):
        participants.add(members[JobKey.NAME])
      continue
    # guard: non-list member group is malformed — skip it
    if not isinstance(members, list):
      continue
    for member in members:
      if isinstance(member, dict) and JobKey.NAME in member:
        participants.add(member[JobKey.NAME])
  emails: set[str] = set()
  for name in participants:
    entry = experts_tbl.get(name) or {}
    author = entry.get(JobKey.GIT_AUTHOR) or {}
    email = (author.get(JobKey.EMAIL) or "").strip()
    if email:
      emails.add(email)
  return emails


def _email_is_bot(email: str, bot_emails: set[str]) -> bool:
  """
  Return True when `email` belongs to a registered bot or a dotted-prefix subsystem it owns.

  Exact match covers the registered bot email itself. Suffix-prefix-dot match covers
  any email of shape `<subsystem>.<known-bot>`, treating it as the bot's own family
  so subsystem commits (e.g. memory writes under `memory.<expert>@<domain>`) are
  classified as bot commits, not operator anchors.

  Returns:
    True when the email identifies a bot or a bot-owned subsystem.
  """
  if email in bot_emails:
    return True
  return any(email.endswith(f".{bot}") for bot in bot_emails)


# -------------------------------------------------------- file discovery


def _iter_class_files(repo: Path, paths: list[str]) -> Iterable[Path]:
  """
  Walk `repo` and yield every file whose repo-relative path matches any glob in `paths`.

  Yields:
    Absolute paths of matching files in filesystem walk order.
  """
  # PurePosixPath.match honors shell-glob semantics where `*` does NOT cross `/`, so
  # `request/*.md` matches only direct children — unlike `fnmatch.fnmatch`, which
  # treats `*` as "any character including /" and silently makes class 1 (request/*.md)
  # swallow files that belong to deeper-nested classes (request/products/*/changes/*/design.md).
  # Unlike the core md-scan sieve (which additionally supports recursive `**`
  # for its coarse discovery globs), class paths stay precise single-segment
  # globs — this matcher is the routing precision the sieve deliberately lacks.
  repo_str = str(repo)
  for base, dirs, files in os.walk(repo_str):
      # Skip dot-folders by default (.git, .claude internals).
    dirs[:] = [d for d in dirs if d != Paths.GIT_DIR]
    for name in files:
      full = Path(base) / name
      rel = full.relative_to(repo).as_posix()
      for pat in paths:
        if PurePosixPath(rel).match(pat):
          yield full
          break


# ----------------------------------------------------- state derivation


_TRUTHY = {"true", "yes", "1", "on"}


# The canonical frontmatter key is `review_approved` — joins the
# `review_*` namespace alongside `review_active` and
# `review_round`.
def _read_review_approved(meta: dict) -> str | None:
  """
  Return the document's `review_approved` frontmatter value.

  Returns:
    The raw string value, or `None` when the key is absent.
  """
  return meta.get(ReviewKey.APPROVED)


def _write_review_approved(fm_text: str, value: bool) -> str:
  """
  Set `review_approved` in `fm_text` to `value`.

  Returns:
    Updated frontmatter text with `review_approved` set.
  """
  return _fm.set_field(fm_text, ReviewKey.APPROVED, value)


def _to_bool(value: str | None) -> bool:
  if value is None:
    return False
  return value.strip().lower() in _TRUTHY


# waiver: class-config key names; live alongside the helper that reads them
_DOMAIN_READY_WHEN = "domain_ready_when"
_RULE_IN = "in"
_RULE_NOT_IN = "not_in"


def _eval_domain_ready(class_cfg: dict, meta: dict) -> bool:
  """
  Evaluate the consumer-supplied `domain_ready` predicate for a review-class document.

  Consumers (e.g. `lazycortex-specs` for the request class) declare a
  `domain_ready_when` block in the class config — a mapping of frontmatter key
  to a constraint dict with `in` / `not_in` lists. The predicate is the AND of
  all declared constraints: every key must satisfy its constraint for the
  predicate to evaluate `True`. An absent or empty block returns `True` (no
  domain gate), preserving the historical behaviour review-only fixtures
  always relied on.

  This is the wiring that replaces the previous `domain_ready=True  # consumer-
  supplied predicate goes here later` stub in the banner-tick call site —
  consumers now have a declarative hook into the `ACTION_NEEDED` gate.

  Args:
    class_cfg: Per-class configuration block read from `lazy.settings.json`.
    meta: Parsed frontmatter of the document at the current tick.

  Returns:
    `True` when every declared constraint matches the current frontmatter (or
    when no constraints are declared); `False` when any constraint fails.
  """
  rules = class_cfg.get(_DOMAIN_READY_WHEN) or {}
  if not rules:
    return True
  for key, spec in rules.items():
    value = meta.get(key)
    allowed = spec.get(_RULE_IN)
    excluded = spec.get(_RULE_NOT_IN)
    if allowed is not None and value not in allowed:
      return False
    if excluded is not None and value in excluded:
      return False
  return True


def _to_int(value: int | str | None, default: int = 0) -> int:
  if value is None:
    return default
  if isinstance(value, int) and not isinstance(value, bool):
    return value
# remaining: str (a stray bool falls through to the default)
  if isinstance(value, str):
    try:
      return int(value.strip())
    except ValueError:
      return default
  return default


def _parse_main_done(value: str | None) -> list[str]:
  """
  Parse the `review_main_done` frontmatter value into a list of flat writer names.

  Accepts a bracketed inline list (`[a, b]` / `[]`) or a bare comma-separated
  form (`a, b`) for hand-edited fixtures. `None`, absent, or empty brackets
  produce an empty list.

  Returns:
    List of flat writer name strings committed in the current round.
  """
  if value is None:
    return []
  raw = value.strip()
  if raw.startswith("[") and raw.endswith("]"):
    raw = raw[1:-1]
  return [item.strip() for item in raw.split(",") if item.strip()]


def _serialize_main_done(names: list[str]) -> str:
  """
  Render a `review_main_done` list to its bracketed inline form (`[a, b]` / `[]`).

  Returns:
    Serialized string ready to write verbatim into frontmatter.
  """
  return "[" + ", ".join(names) + "]"


@dataclass(frozen=True)
class _ChainState:
  last_commit_is_human: bool
  last_contentful_sha: str | None = None  # for body-change check in caller


def _chain_state(
    *,
    history: list[_git_ops.CommitRecord],
    bot_emails: set[str] | None = None,
) -> _ChainState:
  """
  Derive the single git-sourced lifecycle signal: did the operator just commit?

  The lifecycle stage is carried by the explicit `review_phase` frontmatter
  key; the only surviving git signal is the operator-detect. The topmost
  contentful commit (walking past mechanical banner-ticks, history-entry
  appends, and no-trailer bot commits) either carries a `Doc-Review-Phase`
  trailer (a bot wrote it) or it does not (the operator wrote it).

  `last_commit_is_human` is True iff the most-recent contentful commit
  carries no `Doc-Review-Phase` trailer and is authored by a non-bot
  identity. `last_contentful_sha` is that commit's sha.

  No-trailer commits whose author email matches a registered bot are
  classified as bot commits, not operator anchors, so out-of-loop bot
  activity does not mis-trigger a fresh main round.

  Args:
    history: Commit records for the file, most-recent-first.
    bot_emails: Set of `git_author.email` values for registered bots in this
      review class.

  Returns:
    `_ChainState` with `last_commit_is_human` and `last_contentful_sha`.
  """
  bot_emails = bot_emails or set()
  # Classifies the most-recent *contentful* commit on this file, walking
  # past mechanical banner-ticks and historian entries. Without this
  # skip, a mechanical commit on top would mask whether the operator or
  # an expert is actually the last to touch the document.
  last_committer_kind: str | None = None  # "human" | "expert" | "final" | "bot"
  last_contentful_sha: str | None = None

  for record in history:
    trailers = record.trailers
    phase, _expert, _round = _git_ops.parse_phase_trailer(trailers)
    # The only thing the operator-detect cares about is whether a
    # `Doc-Review-Phase` trailer is PRESENT (a bot wrote it) or
    # ABSENT (the operator wrote it). The trailer's content (phase
    # name, `expert=` segment, `round=` segment) no longer
    # drives any lifecycle decision — that lives in
    # `review_phase` + `review_main_done` frontmatter.
    has_trailer = bool(phase)
    is_history_trailer = phase.startswith(Phase.HISTORY)
    is_mechanical = phase == Phase.MECHANICAL
    is_final = phase == Phase.FINALIZE
    # Author-identity fallback when no Doc-Review-Phase trailer.
    # Bots that commit outside the review-loop protocol (e.g. the
    # md-scan opt-in commit) carry a registered bot email but no
    # phase trailer; they must not be misread as the operator.
    is_bot_no_trailer = (not has_trailer) and _email_is_bot(record.author_email, bot_emails)

    # Skip pass-through commits (mechanical banner-ticks, history-
    # entry appends, no-trailer bot commits) when classifying "who
    # made the last contentful change". They don't reset gates that
    # wait for operator/expert action.
    if (
        last_committer_kind is None
        and not is_mechanical
        and not is_history_trailer
        and not is_bot_no_trailer
    ):
      if is_final:
        last_committer_kind = CommitterKind.FINAL
      elif has_trailer:
        last_committer_kind = CommitterKind.EXPERT
      else:
        last_committer_kind = CommitterKind.HUMAN
      last_contentful_sha = record.sha
      break

  last_commit_is_human = last_committer_kind == CommitterKind.HUMAN

  return _ChainState(
      last_commit_is_human=last_commit_is_human,
      last_contentful_sha=last_contentful_sha,
  )


def _has_history_for(history: list[_git_ops.CommitRecord], anchor_sha: str) -> bool:
  """
  Return True iff any commit above `anchor_sha` in `history` carries a `history:*` trailer.

  `history` is most-recent-first; "above" means earlier indexes.

  Returns:
    True when a historian commit exists more recent than `anchor_sha`.
  """
  for record in history:
    if record.sha == anchor_sha:
      return False
    phase, _e, _r = _git_ops.parse_phase_trailer(record.trailers)
    if phase.startswith(Phase.HISTORY):
      return True
  return False


# -------------------------------------------- compute_inputs (public)


def _flatten(name: str) -> str:
  return _parser.flatten_expert_name(name)


def _resolve_mode(
    *,
    action_kind: str,
    class_cfg: dict,
    section_id: str,
) -> str:
  """
  Compute the structural `mode` string for a writer dispatch.

  The mode is the wire-side ownership classification the protocol enforces;
  one of `main` / `validation` / `terminal` / `history` / `repair`. It is
  independent of the per-expert `role` annotation.

  Returns:
    Mode string for the dispatch bundle.
  """
  if action_kind == Phase.MAIN:
    return Phase.MAIN
  if action_kind == Phase.SECTION:
    experts = (class_cfg or {}).get(JobKey.EXPERTS, {}) or {}
    if section_id in (experts.get(Bucket.TERMINAL) or {}):
      return Bucket.TERMINAL
    return Bucket.VALIDATION
  if action_kind == Outcome.REPAIR:
    return Outcome.REPAIR
  return Phase.HISTORY


def _resolve_wire_role(
    class_cfg: dict,
    *,
    action_kind: str,
    expert_name: str,
    section_id: str,
) -> str:
  """
  Look up the wire-side `role` annotation for an expert dispatch.

  The `role` is a free-form string the operator may declare per-expert in
  `review.classes[].experts.<bucket>[<key>].role`. When not declared, falls
  back to the canonical bucket mapping (`main` → `"main"`,
  `validation` → `"validator"`, `terminal` → `"terminal"`).

  Returns:
    Role string to forward verbatim in the dispatch bundle.
  """
  experts = (class_cfg or {}).get(JobKey.EXPERTS, {}) or {}
  if action_kind == Phase.MAIN:
    for entry in experts.get(Phase.MAIN, []) or []:
      if entry.get(JobKey.NAME) == expert_name:
        role = entry.get(JobKey.ROLE)
        if role:
          return role
        break
    return Phase.MAIN
  if action_kind == Phase.SECTION:
    for bucket, fallback in (("validation", "validator"), ("terminal", "terminal")):
      slot = (experts.get(bucket) or {}).get(section_id)
      if slot:
          # Production schema: slot is a writer-object dict.
          # Some test fixtures pre-date the dict normalisation
          # and pass a list of writer-objects — first entry
          # wins in that case.
        writer = slot[0] if isinstance(slot, list) and slot else slot
        role = writer.get(JobKey.ROLE) if isinstance(writer, dict) else None
        return role if role else fallback
# Unconfigured bucket — surface the canonical placeholder so
# the dispatcher's commit / phase machinery keeps a meaningful
# string rather than the section-id.
    return Phase.SECTION
  return section_id


def _resolve_fm_policy(
    class_cfg: dict,
    *,
    action_kind: str,
    expert_name: str,
    section_id: str = "",
) -> tuple[set[str], set[str]]:
  """
  Return the per-expert frontmatter write policy `(allow, require)`.

  `allow` is the set of keys the expert may write; absent means the expert
  owns only the document body. `require` is a subset of `allow` that must
  be present after the round; a missing required key fails the round.
  State keys (`review_*`) are daemon-managed and are never declared here.

  Returns:
    Tuple of `(allow_set, require_set)` for the matched expert entry.
  """
  experts = (class_cfg or {}).get(JobKey.EXPERTS, {}) or {}
  entry: object = None
  if action_kind == Phase.MAIN:
    for e in experts.get(Phase.MAIN, []) or []:
      if e.get(JobKey.NAME) == expert_name:
        entry = e
        break
  elif action_kind == Phase.SECTION:
    for bucket in ("validation", "terminal"):
      slot = (experts.get(bucket) or {}).get(section_id)
      if slot:
        entry = slot[0] if isinstance(slot, list) and slot else slot
        break
# guard: undeclared expert (or non-dict slot) writes no frontmatter
  if not isinstance(entry, dict):
    return set(), set()
  fm = entry.get(JobKey.FRONTMATTER) or {}
  return set(fm.get(JobKey.ALLOW) or []), set(fm.get(JobKey.REQUIRE) or [])


def _filter_fm_overlay(agent_meta: dict, allow_fm_keys: set[str]) -> dict:
  """
  Reduce an agent's returned frontmatter to the keys it was permitted to write.

  Daemon state keys and any key the expert overstepped into are dropped.
  An undeclared expert with an empty allowlist writes no frontmatter.

  Returns:
    Filtered dict containing only the permitted frontmatter keys.
  """
  return {k: v for k, v in agent_meta.items() if k in allow_fm_keys}


def _gather_section_writers(class_cfg: dict) -> list[tuple[str, str, str, bool, bool, str]]:
  """
  Return all section-writer entries from the class config.

  Each entry is `(name, section_id, section_title, post_approve, is_terminal, position)`.
  Covers both the `validation` umbrella (non-terminal, triggers revert-to-main on
  concerns) and the `terminal` umbrella (persist through finalize, do not trigger
  revert-to-main). Pipeline-phase keys (`main` / `history`) are ignored.

  Returns:
    List of 6-tuples describing each registered section writer.
  """
  out: list[tuple[str, str, str, bool, bool, str]] = []
  experts_cfg = class_cfg.get(JobKey.EXPERTS) or {}
  for umbrella_key, post_approve, is_terminal in (
      ("validation", True, False),
      ("terminal",   True, True),
  ):
    umbrella_cfg = experts_cfg.get(umbrella_key) or {}
    # guard: malformed umbrella config (not a section-keyed dict) — skip it
    if not isinstance(umbrella_cfg, dict):
      continue
    for section_id, writer in umbrella_cfg.items():
      # guard: malformed writer entry (not a dict) — skip it
      if not isinstance(writer, dict):
        continue
      name     = writer.get(JobKey.NAME, "")
      section  = writer.get(Phase.SECTION, "")
      position = writer.get(JobKey.POSITION, Position.BOTTOM)
      out.append((name, section_id, section, post_approve, is_terminal, position))
  return out


def _effective_main_writers(class_cfg: dict, meta: dict) -> list[str]:
  """
  Return the effective main-writer name list for one document.

  A non-blank `review_expert` in the document frontmatter replaces the
  class `experts.main` list entirely for that document; otherwise the
  class order is preserved.

  Returns:
    Ordered list of expert names to use as main writers for the document.
  """
  override = meta.get(ReviewKey.EXPERT)
  if isinstance(override, str) and override.strip():
    return [override.strip()]
  return [m[JobKey.NAME] for m in (class_cfg.get(JobKey.EXPERTS, {}).get(Phase.MAIN) or [])]


def _derive_dispatch_state(
    *,
    last_commit_is_human: bool,
    has_pending_work: bool,
) -> _banner.DispatchState:
  """
  Map `(operator-just-committed?, any-writer-pending?)` to a banner `DispatchState`.

  A human commit with pending work maps to `OPERATOR_COMMITTED`. Without pending
  work the chain is exhausted and maps to `CHAIN_EXHAUSTED` regardless of who
  committed last. In-flight work with no operator commit maps to `CHAIN_IN_PROGRESS`.

  Returns:
    The `DispatchState` for the current tick's banner computation.
  """
  if last_commit_is_human and has_pending_work:
    return _banner.DispatchState.OPERATOR_COMMITTED
  if has_pending_work:
    return _banner.DispatchState.CHAIN_IN_PROGRESS
  return _banner.DispatchState.CHAIN_EXHAUSTED


def compute_inputs(
    repo: Path,
    class_cfg: dict,
    file_path: Path,
) -> tuple[_sm.TickInputs, dict]:
  """
  Build the state-machine inputs and action-handler context for one file tick.

  Returns:
    Tuple of `(TickInputs, context_dict)` where `context_dict` carries file
    text, parsed metadata, class config, git history, and operator-commit info
    needed by the action handler.
  """
  text = file_path.read_text()
  try:
    meta, _body_text = _fm.parse(text)
    parse_failed = False
  except ParseError:
    meta = {}
    parse_failed = True

  review_active = _to_bool(meta.get(ReviewKey.ACTIVE))
  review_round = _to_int(meta.get(ReviewKey.ROUND), default=1)
  approved = _to_bool(_read_review_approved(meta))
  # Validation-round counter + finalize-with-concerns frontmatter flag.
  # The counter is monotonic and incremented by the dispatcher whenever
  # a post-approve validation writer commits a non-empty section.
  # Threshold (per-class `concerns_decision_threshold`, default 2)
  # flips the state machine into the concerns-decision pause (operator
  # chooses continue vs finalize-with-concerns).
  validation_round = _to_int(meta.get(ReviewKey.VALIDATION_ROUND), default=0)
  approved_with_concerns_active = _to_bool(meta.get(ReviewKey.APPROVED_WITH_CONCERNS))
  # Per-class threshold for the concerns-decision pause (spec
  # § review-class configuration). Stays at 2 in every class that
  # doesn't override (one auto-revert round, then pause). Setting to 1
  # = immediate pause on first concerns round, no auto-revert.
  concerns_decision_threshold = _to_int(
      class_cfg.get(JobKey.CONCERNS_DECISION_THRESHOLD), default=2,
  )
  concerns_decision_threshold = max(concerns_decision_threshold, 1)

  main_writers = _effective_main_writers(class_cfg, meta)
  section_writers_full = _gather_section_writers(class_cfg)

  # Resolve participating bot emails — only experts referenced by THIS
  # class's `experts:` block, looked up in the global experts table.
  # An expert that exists globally but doesn't participate in this
  # file's review-class is treated as an outsider — its commit looks
  # like an operator commit (anchors a fresh round, etc.).
  settings = load_settings(repo)
  experts_tbl = experts_table(settings)
  validate_experts_emails(experts_tbl)
  bot_emails = _participating_bot_emails(experts_tbl, class_cfg)
  # A per-document `review_expert` override is not in the class
  # `experts:` block, so `_participating_bot_emails` misses it. Add its
  # email here so the override writer's commit is read as a bot commit,
  # not an operator anchor. Same key path as `_participating_bot_emails`.
  _override = meta.get(ReviewKey.EXPERT)
  if isinstance(_override, str) and _override.strip():
    _ov_author = (experts_tbl.get(_override.strip()) or {}).get(JobKey.GIT_AUTHOR) or {}
    _ov_email = (_ov_author.get(JobKey.EMAIL) or "").strip()
    if _ov_email:
      bot_emails.add(_ov_email)

  history = _git_ops.history_for_file(repo, file_path) if not parse_failed else []
  chain = _chain_state(
      history=history,
      bot_emails=bot_emails,
  )

  # Phase-driven main progress (spec § Target model): the set of
  # main writers that already committed this round is the explicit
  # `review_main_done` frontmatter list (flat-names), NOT the
  # `expert=` segments of commit trailers. Pre-approve pending =
  # `experts.main` minus that list, config order preserved. Once
  # approved, the pre-approve cycle is dormant (validators / terminals
  # own the phase) so main pending is empty.
  main_done = _parse_main_done(meta.get(ReviewKey.MAIN_DONE))
  main_done_flat = {_flatten(n) for n in main_done}
  if approved:
    main_pending_names: list[str] = []
  else:
    main_pending_names = [
        n for n in main_writers if _flatten(n) not in main_done_flat
    ]

# Banner state.
  current_banner = _banner.extract(_body_text) if not parse_failed else None
  body_for_gates = _body_text if not parse_failed else ""

  # Section-writer pending list with H1 title for the action. A
  # section writer is "pending" when its owned H1 section is absent
  # from the body — the body-presence probe, NOT a trailer walk. Built
  # BEFORE dispatch_state computation below so the banner's notion of
  # "agents can advance" can use the pre-approve subset only — post-
  # approve writers do not advance the pre-approve chain (final-as-
  # section pattern), so they must not block the banner from reaching
  # READY pre-approve.
  section_pending_full: list[_sm.SectionWriterRef] = [
      (name, section_id, title, post_approve, is_terminal, position)
      for (name, section_id, title, post_approve, is_terminal, position) in section_writers_full
      if _body.section_content_for_owner(body_for_gates, (_flatten(name), section_id)) is None
  ]

  # Pre-approve and post-approve gates differ. Pre-approve section
  # writers are part of the main cycle and gated by main-writer
  # idleness + no operator block. Post-approve section writers
  # (final-as-section pattern) fire AFTER the approve commit, so the
  # operator-anchor for the current round is the approve commit
  # itself — at that moment main_pending re-populates (operator
  # commit resets the round) and any operator-block in body is
  # pre-approve scaffolding. Neither gate applies to post-approve
  # writers; gating them by main_pending would prevent the final-as-
  # section pattern from ever firing. (Bug 26 second half.)
  #
  # The operator-block predicate is per-writer: a `[!question]` /
  # `[!attention]` inside a writer's owned H1 is NOT a block for that
  # writer — the writer placed the callout and is the only one who
  # can retire it. Bug 27.
  # Set of terminal-section owner flat-names — passed to
  # `_has_operator_block` so a `[!question]` inside a terminal
  # section with at least one `- [x]` tick is treated as answered
  # (operator's tick IS the answer; the question stays in the
  # document by design).
  terminal_owners = {
      _flatten(name)
      for (name, _role, _title, _post_approve, is_terminal, _position) in section_writers_full
      if is_terminal
  }
  section_pending_pre_approve: list[_sm.SectionWriterRef] = []
  if not main_pending_names:
    for ref in section_pending_full:
      # waiver: inline numeric literal, not a domain constant
      name, _role, _title, post_approve = ref[0], ref[1], ref[2], ref[3]
      # guard: only pre-approve writers gate here; post-approve are handled later
      if post_approve:
        continue
      if _has_operator_block(
          body_for_gates,
          ignore_owned_by=_flatten(name),
          terminal_owners=terminal_owners,
      ):
        continue
      section_pending_pre_approve.append(ref)
  section_pending_post_approve: list[_sm.SectionWriterRef] = [
      # waiver: inline numeric literal, not a domain constant
      ref for ref in section_pending_full if ref[3]
  ]
  # `section_pending_full` retained for downstream callers that don't
  # care about phase — currently none, but preserve the variable name.
  section_pending_full = section_pending_pre_approve + section_pending_post_approve

  # Probe: is any post-approve VALIDATION section non-empty? Walks
  # the body's H1 sections owned by any post-approve validation writer
  # (NOT terminal — terminal sections are operator choices, not
  # validation concerns, and never trigger revert-to-main; their
  # persistence through finalize is what lets the post-finalize
  # transition read them). Only meaningful after approve; cheap to
  # compute otherwise. Computed BEFORE the banner block because the
  # concerns-decision-pending predicate (Bug 44 redesign) feeds into
  # the banner's desired_state.
  post_approve_validation_writers = [
      (name, group)
      for (name, group, _title, post_approve, is_terminal, _position) in section_writers_full
      if post_approve and not is_terminal
  ]
  any_post_approve_section_non_empty = any(
      _body.section_has_concerns(body_for_gates, (_flatten(name), group))
      for (name, group) in post_approve_validation_writers
  )
  # Concerns-decision pause is active when the doc is approved,
  # at least one validation H1 holds non-empty content, the validation
  # counter has crossed the per-class `concerns_decision_threshold`,
  # AND the operator hasn't yet chosen finalize-with-concerns. While
  # this holds, the dispatcher renders the CONCERNS_DECISION banner
  # and does no other work — the operator must explicitly tick one
  # of the two checkboxes (continue / approve with concerns).
  concerns_decision_pending = (
      approved
      and any_post_approve_section_non_empty
      and validation_round >= concerns_decision_threshold
      and not approved_with_concerns_active
  )

  if not parse_failed:
    operator_blocked = _has_operator_block(
        _body_text, terminal_owners=terminal_owners,
    )
    # Banner uses ONLY pre-approve section pending: post-approve
    # writers gated on `approved == True` and do not advance the
    # pre-approve chain. Without this filter, a registered
    # post-approve writer (e.g. validation.final_check / test-
    # developer) sits in the body-presence pending set forever pre-
    # approve → agents_can_advance_section stays truthy →
    # dispatch_state = CHAIN_IN_PROGRESS → banner stuck on IN_PROCESS
    # → operator never sees the Ready callout to tick approve.
    # (Bug 26.)
    agents_can_advance_section = section_pending_pre_approve and not operator_blocked
    dispatch_state = _derive_dispatch_state(
        last_commit_is_human=chain.last_commit_is_human,
        has_pending_work=bool(main_pending_names or agents_can_advance_section),
    )
    # review_phase passed so desired_state can return IN_PROCESS for the
    # validators / terminals barriers (chain still in flight, NOT finalize).
    # Without this the generic post-tick repaint paints "Waiting: finalize"
    # over a doc whose phase is actually validators / terminals — the title
    # misrepresents the live phase to the operator. Caller-side
    # `waiting_context` (line 1281-1283) supplies the matching title.
    _review_phase_raw = meta.get(ReviewKey.PHASE)
    _review_phase_for_banner = (
        _review_phase_raw.strip() or None
        if isinstance(_review_phase_raw, str) else None
    )
    desired = _banner.desired_state(
        body=_body_text,
        dispatch_state=dispatch_state,
        approved=approved,
        domain_ready=_eval_domain_ready(class_cfg, meta),
        concerns_decision_pending=concerns_decision_pending,
        review_phase=_review_phase_for_banner,
    )
  else:
    desired = _banner.State.IN_PROCESS  # no body to inspect

# Detect a ticked approve checkbox in body. The operator's `- [x]`
# tick lives inside the Ready banner. Captured here so the state
# machine can mirror it into frontmatter `approved: true` before
# the next banner-repaint strips the entire Ready callout.
  approve_ticked = (
      not parse_failed
      and not approved
      and _APPROVE_TICKED_RE.search(_body_text) is not None
  )
  # Bug 44 redesign: operator gestures live inside the
  # CONCERNS_DECISION pause banner body. Two distinct checkboxes:
  #   - "continue review cycle" → operator wants the standard revert-
  #     to-main + main-writer fold loop.
  #   - "approve with concerns" → operator accepts the outstanding
  #     concerns as-is and wants finalize to preserve them.
  continue_review_ticked = (
      not parse_failed
      and _CONTINUE_REVIEW_TICKED_RE.search(_body_text) is not None
  )
  approve_with_concerns_ticked = (
      not parse_failed
      and not approved_with_concerns_active
      and _APPROVE_WITH_CONCERNS_TICKED_RE.search(_body_text) is not None
  )

  # Layout map: (flat_name, section_id) → position ("top" | "bottom").
  # Passed through TickInputs → reapply → body.reassemble so each
  # section lands in its configured slot. Built from section_writers_full
  # where the 6-tuple is (name, section_id, title, post_approve,
  # is_terminal, position); _flatten(name) gives the owner key.
  section_layout: dict[tuple[str, str], str] = {
      (_flatten(name), section_id): position
      for (name, section_id, _title, _post_approve, _is_terminal, position)
      in section_writers_full
  }
  # Spec Stage 6 finalize-wait: if a terminal writer left
  # `[!question] #review/question` callouts in its owned section
  # unanswered, state machine must NOT finalize. Same predicate the
  # banner uses for ACTION_NEEDED.
  any_unanswered_question = _banner._any_unanswered_question(body_for_gates) if not parse_failed else False
  # Post-writer mechanical cleanup (Bug 73) is an inline atomic-tick
  # follow-up: `_run_atomic_tick_cleanup` runs in the SAME
  # `process_one_file` call as the main writer's collect commit
  # (appends the main writer to `review_main_done` + bumps
  # `review_round`). Post-approve validator / terminal counter bumps
  # belong to the barrier collect path. There is no separate cleanup
  # action in `decide()` — the inline cleanup is the sole path.
  # Spec § Stage 1: bootstrap is the first commit lazy-review makes
  # on a fixture freshly opted-in by an external trigger. The trigger
  # sets `review_active: true`; bootstrap fills in the remaining
  # reserved frontmatter (`review_round: 1`, `review_approved:
  # false`) and creates an empty `# History` section. The piggy-
  # back logic lives in the banner-repaint apply-action; this flag
  # ensures the banner-repaint branch fires even when current banner
  # happens to match desired (e.g. an external trigger already put
  # the banner in place).
  if not parse_failed:
      # Tag-first: presence keys on the historian ownership tag, not a
      # literal `# History` heading (a content H1 titled History is not
      # the historian's section).
    history_section_present = _parser.find_history(_body_text) is not None
  else:
    history_section_present = True  # don't trigger bootstrap on unparseable docs
  needs_bootstrap = review_active and not parse_failed and (
      ReviewKey.ROUND not in meta
      or ReviewKey.APPROVED not in meta
      or not history_section_present
  )
  # Post-approve barrier (spec § Stage 5/6). `review_phase` is the
  # explicit frontmatter phase flag; per-writer status comes from the
  # live job queue + body section probe, never from commit-message
  # parsing. Empty unless the document is in an active barrier phase.
  review_phase_raw = meta.get(ReviewKey.PHASE)
  review_phase = (
      review_phase_raw.strip() or None
      if isinstance(review_phase_raw, str) else None
  )
  barrier = _compute_barrier_inputs(
      repo, class_cfg, file_path,
      body=body_for_gates,
      review_phase=review_phase,
      section_writers_full=section_writers_full,
      last_commit_is_human=chain.last_commit_is_human,
      operator_commit_sha=chain.last_contentful_sha,
  ) if (approved and not parse_failed) else {
      JobKey.TO_DISPATCH: [], JobKey.OPEN: False, JobKey.READY: False, JobKey.WAITING_CONTEXT: None,
  }
  # Finalize gate: never finalize while a historian entry is in flight.
  historian_jobs_outstanding = (
      _historian_jobs_outstanding(repo, class_cfg, file_path)
      if not parse_failed else False
  )
  # Waiting-banner context: in a barrier, name the phase; otherwise
  # "writer" when the chain is mid-flight pre-approve, else generic.
  waiting_context = barrier.get(JobKey.WAITING_CONTEXT)
  if waiting_context is None and not approved and (main_pending_names or section_pending_pre_approve):
    waiting_context = Bucket.WRITER
  inputs = _sm.TickInputs(
      parse_failed=parse_failed,
      # waiver: inline numeric literal, not a domain constant
      repair_attempts_remaining=3,  # caller resets on success
      approved=approved,
      main_chain_pending=[(n, Phase.MAIN) for n in main_pending_names],
      section_writer_pending=section_pending_pre_approve,
      current_banner=current_banner,
      desired_banner=desired,
      review_active=review_active,
      approve_checkbox_ticked=approve_ticked,
      post_approve_section_writer_pending=section_pending_post_approve,
      any_post_approve_section_non_empty=any_post_approve_section_non_empty,
      validation_round=validation_round,
      approve_with_concerns_ticked=approve_with_concerns_ticked,
      approved_with_concerns_active=approved_with_concerns_active,
      continue_review_ticked=continue_review_ticked,
      concerns_decision_pending=concerns_decision_pending,
      any_unanswered_question=any_unanswered_question,
      section_layout=section_layout,
      needs_bootstrap=needs_bootstrap,
      review_phase=review_phase,
      barrier_writers_to_dispatch=barrier[JobKey.TO_DISPATCH],
      barrier_open=barrier[JobKey.OPEN],
      barrier_ready_to_collect=barrier[JobKey.READY],
      operator_reset_pending=barrier.get(JobKey.RESET, False),
      historian_jobs_outstanding=historian_jobs_outstanding,
      waiting_context=waiting_context,
  )
  context = {
      JobKey.TEXT: text,
      JobKey.BODY: _body_text if not parse_failed else "",
      JobKey.META: meta,
      JobKey.CLASS_CFG: class_cfg,
      ReviewKey.ROUND: review_round,
      JobKey.HISTORY: history,
      JobKey.APPROVED: approved,
      # Phase-driven operator-detect: True iff the topmost contentful
      # commit on this file carries no Doc-Review-Phase trailer and is
      # authored by a non-bot identity. The banner-repaint apply branch
      # reads this to decide whether an operator-committed new pre-approve
      # round started (→ reset `review_main_done` + `review_phase: main`).
      "last_commit_is_human": chain.last_commit_is_human,
      # Explicit current phase from frontmatter (or None when absent —
      # the mid-review reconstruct signal).
      ReviewKey.PHASE: review_phase,
      # Operator's last contentful commit sha (or None when no contentful
      # commit exists). Persisted into the dispatched job payload as
      # `_operator_sha_at_dispatch` so the next tick's barrier-input
      # computation can compare current `chain.last_contentful_sha`
      # against the dispatch-time anchor — that catches NEW operator
      # commits (legitimate respawn) without false-positive looping on
      # the dispatcher's own mechanical commits (Bug 107).
      "operator_commit_sha": chain.last_contentful_sha,
  }
  return inputs, context


_APPROVE_TICKED_RE = re.compile(
    r"^>\s*-\s*\[x\]\s*approve the whole document\b[^\n]*$",
    re.MULTILINE | re.IGNORECASE,
)
_CONTINUE_REVIEW_TICKED_RE = re.compile(
    r"^>\s*-\s*\[x\]\s*continue review cycle\b[^\n]*$",
    re.MULTILINE | re.IGNORECASE,
)
_APPROVE_WITH_CONCERNS_TICKED_RE = re.compile(
    r"^>\s*-\s*\[x\]\s*approve with concerns\b[^\n]*$",
    re.MULTILINE | re.IGNORECASE,
)


def _has_operator_block(
    body: str,
    *,
    ignore_owned_by: str | None = None,
    terminal_owners: set[str] | None = None,
) -> bool:
  """
  Return True iff `body` contains an open operator-block callout.

  Open callouts are `[!question] #review/question` and `[!attention] #review/concern`.
  Callouts inside the H1 section owned by `ignore_owned_by` are excluded — the
  owning section writer placed them and must not be blocked by its own callouts.
  For each terminal-owner section that contains at least one `- [x]` row, that
  section's callouts are treated as answered (operator's tick is the answer).

  Args:
    body: Document body text to inspect.
    ignore_owned_by: Flat expert name whose owned section callouts are excluded.
    terminal_owners: Set of flat expert names with terminal-action sections.

  Returns:
    True when at least one unanswered operator-block callout is present.
  """
  body_no_fences = _parser.strip_code_fences(body)
  if ignore_owned_by:
    owned_text = _body._extract_section_by_flat_name(body_no_fences, ignore_owned_by)
    if owned_text is not None:
      body_no_fences = body_no_fences.replace(owned_text, "")
# Terminal sections use the apply-after-tick gesture (Bug 31): the
# operator's `- [x]` may live ANYWHERE in the section (bare list
# item OR ticked option inside a callout). The callout itself is a
# documentation reminder of what was asked; the tick is the answer.
# If any tick exists in the section, drop the whole section so its
# callouts don't block the chain.
  for owner in (terminal_owners or set()):
    # guard: the caller's own section is excluded from the block scan
    if owner == ignore_owned_by:
      continue
    section_text = _body._extract_section_by_flat_name(body_no_fences, owner)
    # guard: owner has no section in the body — nothing to drop
    if section_text is None:
      continue
    if re.search(r"^\s*-\s*\[x\]", section_text, re.MULTILINE):
      body_no_fences = body_no_fences.replace(section_text, "")
# For everything else (main-body callouts, validation H1 sections):
# spec § Top banner line 578 / § Stage 6 line 264 — callout is
# answered when there is `- [x]` INSIDE its own body. Per-callout
# granularity, not per-section. Drop answered callouts so the
# blocking regex only sees the ones still waiting on an operator
# tick.
  body_no_fences = _strip_answered_callouts(body_no_fences)
  return bool(
      re.search(r"^>\s*\[!question\][^\n]*#review/question", body_no_fences, re.MULTILINE)
      or re.search(r"^>\s*\[!attention\][^\n]*#review/concern", body_no_fences, re.MULTILINE)
  )


def _strip_answered_callouts(body: str) -> str:
  """
  Remove `[!question]` and `[!attention]` callout blocks that have an answer inside.

  A callout is answered when it contains a `- [x]` line within its own body.
  Answered callouts are replaced with an empty string so downstream gate
  regexes only see unanswered ones. Terminal-section callouts are handled
  by the caller before this function is invoked.

  Returns:
    Body text with answered callouts removed.
  """
  lines = body.split("\n")
  out: list[str] = []
  i = 0
  while i < len(lines):
    m = re.match(
        r"^>\s*\[!(?:question|attention)\][^\n]*#review/(?:question|concern)",
        lines[i],
    )
    if not m:
      out.append(lines[i])
      i += 1
      continue
  # Found a callout opening — scan its continuation lines (every
  # contiguous `>`-prefixed line).
    j = i + 1
    while j < len(lines) and lines[j].startswith(">"):
      j += 1
    block = "\n".join(lines[i:j])
    if re.search(r"^>\s*-\s*\[x\]", block, re.MULTILINE):
        # Answered — drop it.
      pass
    else:
      out.extend(lines[i:j])
    i = j
  return "\n".join(out)


# ------------------------------------------------------- apply_action


def _expert_author(
    experts_tbl: dict, expert_name: str,
    *, local_repo: Path | None = None,
) -> dict:
  """
  Resolve `git_author` for an expert.

  Local experts are read from `experts_tbl`; cross-repo names (`expert@repo`)
  are looked up from the target repo's settings. Always returns a dict with
  `name` and `email` keys, using fallbacks derived from the bare expert name
  when the entry is absent.

  Returns:
    Dict with `"name"` and `"email"` keys for use as a git commit author.

  Raises:
    RuntimeError: When a cross-repo lookup is requested but `local_repo` is not supplied.
  """
  expert, repo_key = _parse_expert_name(expert_name)
  if repo_key == ".":
    entry = experts_tbl.get(expert) or {}
  else:
    if local_repo is None:
      raise RuntimeError(
          f"cross-repo author resolution requires local_repo for {expert_name!r}"
      )
    target = _resolve_target_repo(local_repo, repo_key)
    entry = _core_lookup_expert(target, expert) or {}
  author = entry.get(JobKey.GIT_AUTHOR) or {}
  return {
      JobKey.NAME:  author.get(JobKey.NAME,  expert),
      JobKey.EMAIL: author.get(JobKey.EMAIL, f"{expert}@bot.invalid"),
  }


def _bot_author() -> dict:
  """
  Return the git author dict for mechanical bot commits.

  Returns:
    Dict with `"name"` and `"email"` keys identifying the lazy-review bot.
  """
  return {"name": "lazy-review", "email": "lazy-review@bot.invalid"}


# waiver: `meta` kept for the uniform reconstruct signature; unused in this branch
def _reconstruct_phase(  # pylint: disable=unused-argument
    *,
    meta: dict,
    body: str,
    class_cfg: dict,
    approved: bool,
) -> tuple[str, list[str] | None]:
  """
  Reconstruct `(review_phase, review_main_done)` for a mid-review document lacking an explicit phase.

  One-shot upgrade for documents that have `review_active: true` and a
  `review_round` but no `review_phase` yet. Derives the phase from observed
  body and approval state:

  - Not approved + open operator-block callout → `"awaiting-operator"`,
    `main_done=None` (round is over, do not overwrite).
  - Not approved + no block → `"main"` with empty `main_done` list.
  - Approved → `"validators"` or `"terminals"` based on which post-approve
    sections are already present; `main_done=None`.

  Returns:
    Tuple `(phase, main_done)` where `main_done is None` means the caller
    should not write `review_main_done`.
  """
  section_writers_full = _gather_section_writers(class_cfg)
  if not approved:
      # guard: chain exhausted, operator's turn — keep the round closed.
    if _has_operator_block(body):
      return Bucket.AWAITING_OPERATOR, None
    return Phase.MAIN, []
# Approved → a post-approve barrier phase. Pick validators when the
# class has any validators still without a landed section; else
# terminals when terminals remain; else default to the first
# non-empty barrier bucket.
  has_validators = any(pa and not term for (_n, _s, _t, pa, term, _p) in section_writers_full)
  has_terminals = any(pa and term for (_n, _s, _t, pa, term, _p) in section_writers_full)
  validator_section_present = any(
      _body.section_content_for_owner(body, (_flatten(name), sec_id)) is not None
      for (name, sec_id, _t, pa, term, _p) in section_writers_full
      if pa and not term
  )
  if has_validators and not validator_section_present:
    return Bucket.VALIDATORS, None
  if has_terminals:
    return Bucket.TERMINALS, None
  if has_validators:
    return Bucket.VALIDATORS, None
# No post-approve writers at all → straight to finalize next tick.
  return "finalizing", None


def apply_action(
    repo: Path,
    settings: dict,
    class_cfg: dict,
    file_path: Path,
    inputs: _sm.TickInputs,
    action: _sm.TickAction,
    context: dict,
) -> dict:
  """
  Execute `action` and return a per-tick summary dict.

  Returns:
    Dict describing what was done: commit shas, dispatched job ids,
    status strings, and any errors encountered.
  """
  # waiver: heterogeneous per-tick log summary (commit shas, job ids, counts, messages); Any is the honest value type for this JSON-bound dict
  summary: dict[str, Any] = {JobKey.KIND: action.kind, JobKey.FILE: str(file_path)}
  text = context[JobKey.TEXT]
  body = context[JobKey.BODY]
  history_records = context[JobKey.HISTORY]
  edit_marker_style = (
      settings.get(JobKey.REVIEW, {}).get(JobKey.EDIT_MARKER_STYLE, Style.SIMPLE)
  )
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  _experts_tbl = experts_table(settings)  # noqa: F841

  if action.kind == Outcome.SKIP:
      # spec § Class 3 (file parse failure): when repair attempts are exhausted and the file is
      # still unparseable, register the file with the core error ledger as `broken`. Pre-check
      # via `error-list` so a repeated tick on the same broken file does not append a new event
      # every time — the folder collapses by incident anyway, but skipping the emit keeps the
      # journal lean until the file-body [!error] callout + frontmatter exclusion lands.
      # The callout/exclusion side is a deliberate follow-up; this closes the ledger half.
    if inputs.parse_failed and inputs.repair_attempts_remaining == 0:
      _record_broken_to_ledger(repo, file_path)
    return summary

  if action.kind == Action.APPROVE_MIRROR:
      # Mirror the operator's `- [x] approve the whole document` tick
      # (which lives inside the Ready banner body) into the frontmatter
      # approval flag (`review_approved: true`). Atomic-tick: bundle
      # the banner-repaint (Ready → Waiting) AND the edit-marker
      # fold-down in the same bot commit — the banner-tick invariant
      # allows multiple mechanical actions in one bot commit (just not
      # mixed with expert commits).
      #
      # Why the fold-down here: operator approved the document AS IS,
      # so any pre-approve edit-markers (`\`\`\`diff` fences for style
      # `diff`, ==add==/~~rm~~ for `simple`, etc.) become accepted
      # final text. The validator/terminal that fires next must see the
      # clean baseline; otherwise it reviews scaffolding instead of
      # content. (Finalize also strips markers — this is the same
      # transform, applied earlier in the post-approve lifecycle.)
    fm_text = text[: len(text) - len(body)]
    fm_text = _write_review_approved(fm_text, True)
    # Enter the post-approve barrier (spec § Stage 5). The explicit
    # phase flag — not commit-message parsing — anchors the whole
    # post-approve phase, so an operator answer to a later terminal
    # question never re-opens it. Pick the FIRST non-empty phase:
    # `validators` if the class has any, else `terminals`, else
    # leave unset (no post-approve writers → straight to finalize).
    # Without this, a terminal-only class would sit in a validator
    # phase that never transitions and finalize before routing runs.
    _swf = _gather_section_writers(class_cfg)
    _has_validators = any(pa and not term for (_n, _s, _t, pa, term, _p) in _swf)
    _has_terminals = any(pa and term for (_n, _s, _t, pa, term, _p) in _swf)
    initial_phase = (
        Bucket.VALIDATORS if _has_validators
        else Bucket.TERMINALS if _has_terminals
        else None
    )
    if initial_phase is not None:
      fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, initial_phase)
    try:
      body_after_strip = _edit_markup.strip_markers(
          body, style=edit_marker_style,
      )
    except ValueError:
        # Unknown style — passthrough (defensive; same fallback as
        # the historian source pre-strip).
      body_after_strip = body
  # Bug 88: strip the RESOLVED validator-owned sections from the
  # previous revert-cycle. Operator approved AS IS, so the validator
  # sections the main writer already lifted into body are stale —
  # drop them by ownership (preserve terminal-owned sections like
  # `# Routing` + operator body + `# History`). The next
  # validator barrier writes fresh sections. The resolved sections
  # still carry their 2-part `#expert/…` tag and are caught by
  # ownership here.
    _terminal_ids = {sid for (_n, sid, _t, pa, term, _p) in _swf if pa and term}
    body_after_strip = _body.strip_owned_h1_sections(
        body_after_strip, preserve_section_ids=_terminal_ids,
    )
    new_body = _banner.replace_banner(
        body_after_strip, _banner.State.IN_PROCESS,
        approved=True,
        continue_review=False,
        approve_with_concerns=False,
        waiting_context=initial_phase,
    )
    file_path.write_text(fm_text + new_body)
    sha = _git_ops.commit_mechanical(
        repo, file_path,
        author=_bot_author(),
        message=f"review: approve → frontmatter + banner → Waiting: {initial_phase or 'done'}",
    )
    summary[JobKey.COMMIT_SHA] = sha
    # Spec § historian subsystem: the approve-mirror commit is the
    # SOLE historian trigger — one clean approved state → one entry.
    # Kicked here (not per writer-commit). Snapshot is the file we
    # just wrote (markers folded).
    try:
      kick = _kick_historian_for_writer_commit(
          repo, settings, class_cfg, file_path,
          writer_commit_sha=sha,
          history_records=history_records,
      )
      summary[JobKey.HISTORY_KICK] = kick
    except Exception as exc:
      summary[JobKey.HISTORY_KICK_ERROR] = str(exc)
    return summary

  if action.kind == Action.APPROVE_WITH_CONCERNS_MIRROR:
      # Bug 44 redesign: operator ticked `- [x] approve with concerns`
      # on the CONCERNS_DECISION pause banner. Mirror the choice into
      # frontmatter so the next tick's state machine sees the active
      # flag and dispatches finalize with `with_concerns=True`,
      # which preserves validation-owned H1 sections in the body.
    fm_text = text[: len(text) - len(body)]
    fm_text = _fm.set_field(fm_text, ReviewKey.APPROVED_WITH_CONCERNS, True)
    file_path.write_text(fm_text + body)
    sha = _git_ops.commit_mechanical(
        repo, file_path,
        author=_bot_author(),
        # waiver: one-off human-facing message
        message="review: approve with concerns → frontmatter",
    )
    summary[JobKey.COMMIT_SHA] = sha
    return summary

  if action.kind == Action.CONTINUE_REVIEW_MIRROR:
      # Bug 44 redesign: operator ticked `- [x] continue review cycle`
      # on the CONCERNS_DECISION pause banner. The choice is a one-
      # shot signal — we drop `review_approved: false` so the
      # document re-enters the main cycle. Atomic-tick: bundle the
      # banner-repaint (CONCERNS_DECISION → Waiting) in the same bot
      # commit.
      #
      # Bug 73 / inv 4: `review_round` is NOT bumped here — the
      # bump is a separate mechanical bot-commit (the inline atomic-tick
      # cleanup) emitted after the main writer's next commit.
    fm_text = text[: len(text) - len(body)]
    fm_text = _write_review_approved(fm_text, False)
    # Phase-driven re-entry into the main cycle (spec transition
    # concerns-pause → main): explicit `review_phase: main` + a fresh
    # empty `review_main_done` so the next tick re-runs the main
    # writers from scratch.
    fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, Phase.MAIN)
    fm_text = _fm.set_field(fm_text, ReviewKey.MAIN_DONE, _serialize_main_done([]))
    new_body = _banner.replace_banner(
        body, _banner.State.IN_PROCESS,
        approved=False,
        continue_review=False,
        approve_with_concerns=False,
    )
    file_path.write_text(fm_text + new_body)
    sha = _git_ops.commit_mechanical(
        repo, file_path,
        author=_bot_author(),
        # waiver: one-off human-facing message
        message="review: continue review cycle + banner → Waiting",
    )
    summary[JobKey.COMMIT_SHA] = sha
    return summary

  if action.kind == Action.REVERT_TO_MAIN:
      # Final-as-section revert: the operator approved BUT a
      # post-approve writer left non-empty content in its owned H1
      # section. Kick the document back into a fresh main-writer
      # round so the operator can react to those concerns.
      #
      # Atomic-tick invariant (spec § Orthogonal rules): the
      # `review_approved: false` flip + banner repaint to Waiting
      # MUST land in the same bot-commit. Two consecutive mechanical
      # bot-commits invite an operator commit between them and break
      # the atomicity of the revert.
      #
      # Bug 73 / inv 4: `review_round` is NOT bumped here — that
      # bump is bundled with the next main-writer's commit by
      # `_run_atomic_tick_cleanup` (atomic-tick on the writer side).
      # Post-approve section contents are PRESERVED in the body so
      # the next main-writer round can read them as
      # `concerns`.
    fm_text = text[: len(text) - len(body)]
    fm_text = _write_review_approved(fm_text, False)
    # Phase-driven revert (spec transition validators → main): explicit
    # `review_phase: main` + a fresh empty `review_main_done`.
    fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, Phase.MAIN)
    fm_text = _fm.set_field(fm_text, ReviewKey.MAIN_DONE, _serialize_main_done([]))
    new_body = _banner.replace_banner(body, _banner.State.IN_PROCESS)
    file_path.write_text(fm_text + new_body)
    sha = _git_ops.commit_mechanical(
        repo, file_path,
        author=_bot_author(),
        # waiver: one-off human-facing message
        message="review: revert to main (final concerns) + banner → Waiting",
    )
    summary[JobKey.COMMIT_SHA] = sha
    return summary

  if action.kind == Action.BANNER_REPAINT:
    fm_text = text[: len(text) - len(body)]
    # Spec § Stage 1 — review opening: the bootstrap subsystem sees a
    # file with `review_active: true` but no other backing review fields →
    # it makes one bootstrap commit with the remaining markup: `review_round:
    # 1`, `review_approved: false`, banner, and an empty `# History` section.
    #
    # The state machine has no explicit `kind="bootstrap"` action.
    # Instead the bootstrap is woven into the very first banner-
    # repaint that lands for a fixture — that commit already paints
    # the banner; here we extend it to also write the missing
    # frontmatter reserved fields and create `# History` if absent,
    # so the bootstrap is a single commit per spec.
    meta = context.get(JobKey.META, {})
    if ReviewKey.ROUND not in meta:
      fm_text = _fm.set_field(fm_text, ReviewKey.ROUND, 1)
    if ReviewKey.APPROVED not in meta:
      fm_text = _fm.set_field(fm_text, ReviewKey.APPROVED, False)
  # Phase-driven lifecycle (spec § Target model): every banner-
  # repaint that opens or re-opens the pre-approve cycle stamps the
  # explicit `review_phase` + `review_main_done` frontmatter, so
  # the state machine reads the stage from frontmatter instead of
  # walking commit trailers. Three cases land here:
  #   - bootstrap (`review_round` was absent): fresh opt-in →
  #     `review_phase: main` + `review_main_done: []`.
  #   - mid-review reconstruct (`review_round` present but
  #     `review_phase` absent): a document mid-review at the moment
  #     of the phase-driven upgrade — derive the phase from observed
  #     body / approval state (handled by `_reconstruct_phase`).
  #   - operator new pre-approve round (`review_phase` present, the
  #     operator just committed, not approved): reset the round →
  #     `review_phase: main` + `review_main_done: []`. The
  #     `review_round` bump itself stays in the post-main atomic-tick
  #     cleanup (unchanged from the trailer-era behaviour).
    review_phase_now = context.get(ReviewKey.PHASE)
    approved_now = bool(context.get(JobKey.APPROVED))
    operator_committed = bool(context.get(JobKey.LAST_COMMIT_IS_HUMAN))
    # `fm_resets_writer_round` is True whenever this commit sets the FM
    # to `review_phase: main` + `review_main_done: []`. The banner painted
    # in this same commit MUST then be IN_PROCESS / Waiting: writer — not
    # whatever `action.banner_state` was computed against the PRE-reset
    # state (which can be READY when chain-exhausted-with-ticks). Painting
    # READY over a freshly-reset writer round leaves the commit with
    # inconsistent FM (writer round pending) + banner (chain exhausted).
    fm_resets_writer_round = False
    if ReviewKey.ROUND not in meta:
        # Bootstrap — first commit on a freshly opted-in fixture.
      fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, Phase.MAIN)
      fm_text = _fm.set_field(fm_text, ReviewKey.MAIN_DONE, _serialize_main_done([]))
      fm_resets_writer_round = True
    elif review_phase_now is None:
        # Mid-review reconstruct (one-shot upgrade). Reached only on a
        # parseable doc — `decide` routes parse failures to repair,
        # never to banner-repaint.
      recon_phase, recon_main_done = _reconstruct_phase(
          meta=meta, body=body, class_cfg=class_cfg, approved=approved_now,
      )
      fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, recon_phase)
      if recon_main_done is not None:
        fm_text = _fm.set_field(
            fm_text, ReviewKey.MAIN_DONE, _serialize_main_done(recon_main_done),
        )
      if recon_phase == Phase.MAIN and not recon_main_done:
        fm_resets_writer_round = True
    elif operator_committed and not approved_now and review_phase_now in (Phase.MAIN, Bucket.AWAITING_OPERATOR):
        # Operator committed a new pre-approve round (iterated without
        # approving) → re-open the main phase and clear the done-set.
      fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, Phase.MAIN)
      fm_text = _fm.set_field(fm_text, ReviewKey.MAIN_DONE, _serialize_main_done([]))
      fm_resets_writer_round = True
  # Defensive — start.py / open_request.py already clear this on
  # the opt-in commit. If the file reached this branch with
  # `review_active: true` AND a stale `review_result`, drop
  # the terminal discriminator so the apply-gate routine doesn't
  # fire on a doc that's mid-review.
    if ReviewKey.RESULT in meta:
      fm_text = _fm.unset_field(fm_text, ReviewKey.RESULT)
  # Paint the banner AFTER the FM has been finalised so an FM-reset
  # (bootstrap / reconstruct-to-main / operator-iterated) can override the
  # `action.banner_state` precomputed against the pre-reset state. When
  # `fm_resets_writer_round` is True, the chain is NOT exhausted regardless
  # of body state — a writer round is pending again — so the banner must
  # reflect IN_PROCESS / Waiting: writer.
    effective_banner_state = (
        _banner.State.IN_PROCESS if fm_resets_writer_round else action.banner_state
    )
    effective_waiting_context = (
        Bucket.WRITER if fm_resets_writer_round else None
    )
    new_body = _banner.replace_banner(
        body, effective_banner_state,
        approved=context[JobKey.APPROVED],
        continue_review=inputs.continue_review_ticked,
        approve_with_concerns=inputs.approved_with_concerns_active or inputs.approve_with_concerns_ticked,
        waiting_context=effective_waiting_context,
    )
    new_body = _history.ensure_history_section(new_body)
    file_path.write_text(fm_text + new_body)
    sha = _git_ops.commit_mechanical(
        repo, file_path,
        author=_bot_author(),
        message=f"review: banner → {effective_banner_state.value}",
    )
    summary[JobKey.COMMIT_SHA] = sha
    return summary

  if action.kind == Phase.FINALIZE:
      # Strip edit markers; drop banner + approve checkbox; remove
      # system callouts; strip owned H1 sections (Routing, Final
      # check, …); set review_active=false. Delegated to finalize.py
      # so this dispatcher branch and the standalone `lazy-review
      # finalize` CLI share one transformation contract.
      #
      # Terminal-action sections (`experts.terminal.<group>`) are
      # preserved through the strip so the post-finalize transition
      # (e.g. `spec.request-handler` apply mode reading routing
      # ticks) can still read the operator's choices. The transition
      # is responsible for stripping the section once its work is
      # done. (Bug 31.)
      # Spec § Stage 7: preserve-set is a set of SECTION-ID
      # (the second component of the `#expert/<flat>/<section-id>`
      # ownership tag — the key under `experts.terminal.<id>` /
      # `experts.validation.<id>` in config). Terminal section-ids
      # always preserve (apply transition reads them); validation
      # section-ids preserve only when `approved_with_concerns` is
      # active (see below). The `_role` field in the section-writer
      # 6-tuple IS the section-id, set by `_gather_section_writers`
      # from the umbrella dict key.
    preserve_section_ids = {
        _role
        for (_name, _role, _title, _post_approve, is_terminal, _position) in _gather_section_writers(class_cfg)
        if is_terminal
    }
    # Validation section-ids (post-approve, non-terminal). When
    # "approve with concerns" is active, the operator chose (on the
    # CONCERNS_DECISION pause banner) to keep the validation-umbrella
    # concerns in the finalized document: add them to the preserve set
    # so the strip leaves them in place, AND pass them as
    # `normalize_section_ids` so finalize strips their `#expert/…`
    # ownership tag (Bug 88) — the concerns survive as plain prose, not
    # as review-owned sections. `finalize_text` also stamps an
    # `approved-with-concerns` status callout instead of clean
    # `approved`.
    validation_section_ids = {
        _role
        for (_name, _role, _title, post_approve, is_terminal, _position) in _gather_section_writers(class_cfg)
        if post_approve and not is_terminal
    }
    if inputs.approved_with_concerns_active:
      preserve_section_ids = preserve_section_ids | validation_section_ids
    new_text = _finalize.finalize_text(
        text,
        style=edit_marker_style,
        preserve_section_ids=preserve_section_ids,
        with_concerns=inputs.approved_with_concerns_active,
        normalize_section_ids=(
            validation_section_ids
            if inputs.approved_with_concerns_active else None
        ),
    )
    file_path.write_text(new_text)
    sha = _git_ops.commit_final(
        repo, file_path,
        author=_bot_author(),
        # waiver: one-off human-facing message
        message="review: finalize",
    )
    summary[JobKey.COMMIT_SHA] = sha
    return summary

  if action.kind == Action.BARRIER_DISPATCH:
      # Queue ALL pending writers of the active barrier at once (spec
      # § Stage 5 dispatch-all). No commit — the pump drains them; the
      # sweep-collect tick lands their sections together.
    dispatched: list[str] = []
    for ref in inputs.barrier_writers_to_dispatch:
      name, sec_id = ref[0], ref[1]
      try:
        _dispatch_barrier_writer(
            repo, settings, class_cfg, file_path, name, sec_id, context,
        )
        dispatched.append(f"{name}#{sec_id}")
      except Exception as exc:  # pragma: no cover — surfaced in summary
        summary.setdefault(JobKey.DISPATCH_ERRORS, []).append(f"{name}#{sec_id}: {exc}")
    summary[JobKey.STATUS] = "barrier-dispatched"
    summary[JobKey.DISPATCHED] = dispatched
    return summary

  if action.kind == Action.BARRIER_COLLECT:
    return _barrier_collect(
        repo, settings, class_cfg, file_path, inputs, context, summary,
    )

  if action.kind == Action.RESET_APPROVAL:
      # Post-approve operator body-edit outside owned sections (spec
      # § Stage 6 boundary): drop approval + barrier phase, re-open the
      # validator barrier from a fresh main round.
    fm_text = text[: len(text) - len(body)]
    fm_text = _write_review_approved(fm_text, False)
    # Phase-driven reset (spec transition terminals → main on
    # operator_reset): explicit `review_phase: main` + a fresh empty
    # `review_main_done` so the validator barrier re-opens from a
    # clean main round.
    fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, Phase.MAIN)
    fm_text = _fm.set_field(fm_text, ReviewKey.MAIN_DONE, _serialize_main_done([]))
    new_body = _banner.replace_banner(
        body, _banner.State.IN_PROCESS, waiting_context=Bucket.WRITER,
    )
    file_path.write_text(fm_text + new_body)
    sha = _git_ops.commit_mechanical(
        repo, file_path,
        author=_bot_author(),
        # waiver: one-off human-facing message
        message="review: operator edited body post-approve → reset approval",
    )
    summary[JobKey.COMMIT_SHA] = sha
    return summary

  if action.kind == Outcome.REPAIR:
    return _dispatch_repair(
        repo, settings, class_cfg, file_path, inputs, context, summary,
    )

  if action.kind == Phase.MAIN:
    return _dispatch_writer(
        repo, settings, class_cfg, file_path, inputs, action, context, summary,
    )

  summary[JobKey.ERROR] = f"unknown action kind: {action.kind}"
  return summary


# ------------------------------- atomic-tick post-writer mechanical cleanup


# waiver: `section_id` kept for the uniform cleanup signature; unused in this branch
def settle_post_main_round(
    fm_text: str,
    body: str,
    meta: dict,
    class_cfg: dict,
    *,
    add_done_writers: list[str],
    review_round: int,
) -> tuple[str, str, int]:
  """
  Apply the frontmatter + banner state the dispatcher produces when a main-writer round closes.

  Shared by the natural per-writer-commit cleanup path (triggered when a writer's commit
  closes a main round) and by `lazy-review.submit` (which leapfrogs the opening round by simulating that every
  main writer in the class already committed). Bumps `review_round` by the number of
  simulated commits (`len(add_done_writers)`), appends each writer to `review_main_done`
  in dedup-preserving order, sets `review_phase` to `awaiting-operator` when the appended
  list covers every main writer of the class (else stays `main`), and replaces the body
  banner with the dispatcher's desired-state (Ready when no open operator-block callouts
  remain in body, else Action needed).

  Skipped entirely when the document is already approved (`review_approved: true`) — the
  post-approve barrier owns the phase from that point onward.

  Args:
    fm_text: Frontmatter section of the document (between `---` fences, inclusive).
    body: Body section of the document (everything after the frontmatter).
    meta: Parsed frontmatter dict.
    class_cfg: Review class config from `review.classes[*]`.
    add_done_writers: Flat-name list of writers to append to `review_main_done`. The
      natural path passes a single-item list (the writer that just committed); submit
      passes the full main-writer set.
    review_round: Current `review_round` value before this settlement.

  Returns:
    Tuple of `(new_fm_text, new_body, new_review_round)`. `new_body` carries the
    target banner.
  """
  delta = max(1, len(add_done_writers))
  new_round = review_round + delta
  fm_text = _fm.set_field(fm_text, ReviewKey.ROUND, new_round)
  main_writers = _effective_main_writers(class_cfg, meta)
  approved_now = _to_bool(_read_review_approved(meta))
  if main_writers and not approved_now:
    done = _parse_main_done(meta.get(ReviewKey.MAIN_DONE))
    done_flat = { _flatten(n) for n in done }
    for name in add_done_writers:
      if _flatten(name) not in done_flat:
        done.append(_flatten(name))
        done_flat.add(_flatten(name))
    fm_text = _fm.set_field(
        fm_text, ReviewKey.MAIN_DONE, _serialize_main_done(done),
    )
    main_covered = all(_flatten(n) in done_flat for n in main_writers)
    new_phase = "awaiting-operator" if main_covered else "main"
    fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, new_phase)
  # Phase-aware banner: post-main cleanup may be invoked when the document
  # is approved (cycle 2 re-entry shapes), in which case the phase comes
  # from the freshly-updated fm_text (post-bookkeeping) or from meta. Read
  # the post-update phase so desired_state sees the correct value when
  # branching the approved=True FINALIZING vs validators/terminals →
  # IN_PROCESS gate.
  _phase_meta, _ = _fm.parse(fm_text + body)
  _review_phase_for_banner_raw = _phase_meta.get(ReviewKey.PHASE)
  _review_phase_for_banner = (
      _review_phase_for_banner_raw.strip() or None
      if isinstance(_review_phase_for_banner_raw, str) else None
  )
  target_banner = _banner.desired_state(
      body = body,
      dispatch_state = _banner.DispatchState.CHAIN_EXHAUSTED,
      approved = approved_now,
      domain_ready = _eval_domain_ready(class_cfg, meta),
      concerns_decision_pending = False,
      review_phase = _review_phase_for_banner,
  )
  # When desired_state returned IN_PROCESS for a validators/terminals phase,
  # supply the matching waiting_context so the rendered title reads
  # "Waiting: validators" / "Waiting: terminals" instead of bare "Waiting".
  _waiting_context_for_banner: str | None = None
  if target_banner is _banner.State.IN_PROCESS and approved_now:
    if _review_phase_for_banner == Bucket.VALIDATORS:
      _waiting_context_for_banner = Bucket.VALIDATORS
    elif _review_phase_for_banner == Bucket.TERMINALS:
      _waiting_context_for_banner = Bucket.TERMINALS
  new_body = _banner.replace_banner(
      body, target_banner, waiting_context = _waiting_context_for_banner,
  )
  return fm_text, new_body, new_round


# waiver: uniform tick-cleanup signature shared across writer kinds; several params are unused by this variant
def _run_atomic_tick_cleanup(  # pylint: disable=unused-argument
    repo: Path,
    file_path: Path,
    class_cfg: dict,
    writer_kind: str,
    expert_name: str,
    section_id: str,
    review_round: int,
) -> dict:
  """
  Run post-writer mechanical cleanup in the same dispatcher tick as the writer's commit.

  For a main-writer commit, bumps `review_round` and updates `review_main_done`
  and `review_phase` frontmatter under bot identity. Per the atomic-tick invariant
  these mechanical actions land in the same tick so no operator commit can slip
  between. Post-approve validator and terminal writers are handled by the barrier
  collect path and never reach this helper.

  Returns:
    Dict with optional `cleanup_commit_sha` and `new_review_round` keys, or
    an empty dict for any `writer_kind` other than `"main"`.
  """
  result: dict = {}
  raw = file_path.read_text()
  meta, body = _fm.parse(raw)
  fm_text = raw[: len(raw) - len(body)]
  new_body = body
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  _section_writers_full = _gather_section_writers(class_cfg)  # noqa: F841
  # Banner state to land alongside the cleanup commit (atomic-tick
  # invariant — the relaxed banner-tick rule allows a single bot
  # commit to carry banner + frontmatter changes; bundling them here
  # keeps the visible banner state consistent with the new chain
  # state without waiting for a follow-up tick.
  # guard: only the main-writer cleanup runs through this helper;
  # post-approve writers are handled by the barrier collect path.
  if writer_kind != Phase.MAIN:
    return result
  # Atomic-tick invariant (spec § Orthogonal rules): banner repaint is
  # bundled into the same cleanup commit, not deferred to the next tick.
  # `settle_post_main_round` produces both the frontmatter overlay (round
  # bump + review_main_done append + review_phase transition) and the
  # target banner state in one shot — same primitive lazy-review.submit
  # invokes to leapfrog the opening writer round.
  fm_text, new_body, new_round = settle_post_main_round(
      fm_text = fm_text,
      body = new_body,
      meta = meta,
      class_cfg = class_cfg,
      add_done_writers = [expert_name],
      review_round = review_round,
  )
  message = f"review: post-main cleanup (review_round → {new_round})"
  result[JobKey.NEW_REVIEW_ROUND] = new_round
  file_path.write_text(fm_text + new_body)
  try:
    sha = _git_ops.commit_mechanical(
        repo, file_path,
        author=_bot_author(),
        message=message,
    )
  except _git_ops.GitOpsError as exc:
      # Empty-diff is possible for a no-op cleanup (main commit
      # in a pre-approve round with no validation sections to clear,
      # bump alone bumped the round but if review_round was already
      # at the target value somehow, the diff is empty). Treat as
      # benign — nothing to commit, no follow-up needed.
    # waiver: git CLI vocabulary
    if "nothing to commit" in str(exc):
      return result
    raise
  result[JobKey.CLEANUP_COMMIT_SHA] = sha
  return result


# --------------------------------------------- writer dispatch / collect


def _dispatch_writer(
    repo: Path,
    settings: dict,
    class_cfg: dict,
    file_path: Path,
    inputs: _sm.TickInputs,
    action: _sm.TickAction,
    context: dict,
    summary: dict,
) -> dict:
  """
  Dispatch a fresh main-writer job or collect an existing one.

  Returns early with `status=pending` when the agent has not responded yet.
  Main-writer dispatch only — post-approve validator and terminal writers
  flow through the barrier collect path, not this helper.

  Returns:
    Updated `summary` dict with status, commit sha, and job info.
  """
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  expert_name, section_id = action.expert  # type: ignore[misc]
  kind = "review"
  text = context[JobKey.TEXT]
  body = context[JobKey.BODY]
  review_round = context[ReviewKey.ROUND]
  experts_tbl = experts_table(settings)
  edit_marker_style = (
      settings.get(JobKey.REVIEW, {}).get(JobKey.EDIT_MARKER_STYLE, Style.SIMPLE)
  )
  dedup_key = str(file_path)
  existing = _find_done_job(repo, expert_name, dedup_key)
  job_id = existing.get(JobKey.JOB_ID)
  if existing.get(JobKey.STATUS) == JobStatus.PENDING:
    summary[JobKey.STATUS] = "pending"
    summary[JobKey.EXPERT] = expert_name
    summary[JobKey.JOB_ID] = job_id
    return summary
# Resolve the wire-side role / mode for the main-writer dispatch.
# `role` is a free-form string the operator may declare per-expert
# in `review.classes[].experts.main[].role`; the dispatcher
# forwards it verbatim to the agent. When unset it falls back to the
# canonical `main` label. `mode` is the structural ownership
# classification the protocol enforces — always `main` here.
  wire_role = _resolve_wire_role(
      class_cfg, action_kind=action.kind,
      expert_name=expert_name, section_id=section_id,
  )
  wire_mode = _resolve_mode(
      action_kind=action.kind, class_cfg=class_cfg, section_id=section_id,
  )

  if existing.get(JobKey.STATUS) == Outcome.MISSING:
      # Dispatch a fresh job — one atomic call through the core CLI.
      # Core (dispatch-job subcommand) handles dir creation, config.json
      # composition from settings.experts, source/result writes, and
      # READY-touched-last ordering. We just shape the bundle.
    stripped = _body.strip_for_main_writer(text)
    # Main-writer payload extension: forward non-empty post-approve
    # section contents as `concerns`. The main-writer
    # body view (strip_for_main_writer) drops these sections, so the
    # only way for the writer to learn about validation concerns is
    # through this payload field.
    concerns: list[dict] = []
    for (name, group, title, post_approve, is_terminal, _position) in _gather_section_writers(class_cfg):
      if not post_approve or is_terminal:
          # Terminal sections (apply-after-tick) carry operator
          # ticks, not validation concerns — they must not be
          # lifted as `[!question]` callouts in the main body.
        continue
      content = _body.section_content_for_owner(body, (_flatten(name), group))
      # guard: empty or whitespace-only section carries no concern to lift
      if content is None or not any(line.strip() for line in content.split("\n")):
        continue
      concerns.append({
          JobKey.GROUP:             group,
          JobKey.WRITER:            name,
          JobKey.SECTION_H1_TITLE:  title,
          JobKey.CONTENT:           content.strip("\n"),
      })
    request_payload = _payload.build_request(
        kind=kind,
        mode=wire_mode,
        role=wire_role,
        round_=review_round,
        source_path=f"source/{file_path.name}",
        context_paths=[],
        result_path=f"result/{file_path.name}",
        edit_marker_style=edit_marker_style,
        concerns=concerns or None,
    )
    # Operator-conflict guard: stamp both the content snapshot (legacy /
    # fallback) and the operator-sha anchor (Bug 107 round 3 + Bug 112 fix).
    # Collect-time `_operator_touched_since_dispatch` prefers the anchor —
    # comparing against `chain.last_contentful_sha` walks past intervening
    # bot commits (historian / mechanical) and only trips on real operator
    # edits.
    request_payload[JobKey.FILE_SNAPSHOT_HASH] = _file_snapshot_hash(file_path)
    _operator_commit_sha = context.get(JobKey.OPERATOR_COMMIT_SHA)
    # guard: only stamp the anchor when an operator-commit exists (None on a
    # brand-new file with no contentful commit yet)
    if _operator_commit_sha is not None:
      request_payload[JobKey.OPERATOR_SHA_AT_DISPATCH] = _operator_commit_sha
    bare_expert, repo_key = _parse_expert_name(expert_name)
    target_repo = _resolve_target_repo(repo, repo_key)
    # Preflight (cross-repo only): verify the expert is registered in the
    # target repo BEFORE writing a bundle there. Without this the bundle
    # uploads and the foreign pump fails with `config.json: missing agent`
    # (visible only as DEAD on the foreign side). Pre-check surfaces the
    # config error on the dispatching side, which is where the operator
    # is looking.
    if target_repo != repo.resolve():
      if _core_lookup_expert(target_repo, bare_expert) is None:
        summary[JobKey.STATUS] = "failed:expert-not-registered-in-target"
        summary[JobKey.EXPERT] = expert_name
        summary[JobKey.ERROR] = (
            f"expert {bare_expert!r} not registered in target repo "
            f"{repo_key!r} at {target_repo} — add it to "
            f"{target_repo}/.claude/lazy.settings.json[experts]"
        )
        return summary
    bundle = {
        JobKey.EXPERT: bare_expert,
        JobKey.PAYLOAD: request_payload,
        JobKey.SOURCE: {file_path.name: stripped},
        JobKey.RESULT: [file_path.name],
        JobKey.DEDUP_KEY: dedup_key,
    }
    if target_repo != repo.resolve():
      bundle[JobKey.DISPATCHED_FROM] = str(repo)
    _core_dispatch_job(target_repo, bundle)
    summary[JobKey.STATUS] = "dispatched"
    summary[JobKey.EXPERT] = expert_name
    return summary

# guard: a finished job always carries its job_id (pending / missing returned above)
  if job_id is None:
    summary[JobKey.STATUS] = "error:missing-job-id"
    summary[JobKey.EXPERT] = expert_name
    return summary
# Job finished — apply its response. Every return path below MUST
# consume the job (mark it CONSUMED) so the next tick treats it as
# missing and dispatches fresh instead of re-reading the stale
# response.
  response = existing.get(JobKey.RESPONSE, {})
  bare_expert, repo_key = _parse_expert_name(expert_name)
  target_repo = _resolve_target_repo(repo, repo_key) if "@" in expert_name else repo
  consume_kwargs: dict = {JobKey.DISPATCHED_FROM: str(repo)} if target_repo != repo.resolve() else {}
  # Operator-conflict check: if the file changed since dispatch,
  # operator's work wins, discard the agent's response.
  job_dir = target_repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / bare_expert / job_id
  try:
    req_payload = json.loads((job_dir / JobFile.REQUEST).read_text())
  except (OSError, json.JSONDecodeError):
    req_payload = {}
  if _operator_touched_since_dispatch(
      file_path, req_payload,
      operator_commit_sha = context.get(JobKey.OPERATOR_COMMIT_SHA),
  ):
    _core_consume_job(target_repo, bare_expert, job_id, **consume_kwargs)
    summary[JobKey.STATUS] = "discarded:operator-conflict"
    summary[JobKey.EXPERT] = expert_name
    summary[JobKey.JOB_ID] = job_id
    return summary
  try:
    _payload.validate_response(response, kind=kind)
  except Exception as exc:  # pragma: no cover — surfaces as logical-error callout later
    _core_consume_job(target_repo, bare_expert, job_id, **consume_kwargs)
    summary[JobKey.ERROR] = f"response_invalid: {exc}"
    return summary
# Phase trailer (Bug 24): main-writer commits always land as `main`.
  phase = Phase.MAIN
  outcome = response.get(JobKey.OUTCOME)
  if outcome == Outcome.EMPTY:
    empty_sha = _git_ops.commit_empty(
        repo, round_=review_round, expert=expert_name,
        author=_expert_author(experts_tbl, expert_name, local_repo=repo),
        message=f"review: {section_id} {expert_name} (empty)",
        phase=phase,
    )
    _core_consume_job(target_repo, bare_expert, job_id, **consume_kwargs)
    # Atomic-tick: main-writer review_round bump in same tick.
    cleanup = _run_atomic_tick_cleanup(
        repo, file_path, class_cfg,
        writer_kind=action.kind, expert_name=expert_name,
        section_id=section_id, review_round=review_round,
    )
    summary.update(cleanup)
    summary[JobKey.STATUS] = "collected:empty"
    summary[JobKey.COMMIT_SHA] = empty_sha
    return summary
  if outcome == Outcome.EDITED:
      # Unified transport (wire-kind refactor): the main writer returns
      # the full document body via `result/<file>`.
    result_relpath = response[JobKey.RESULT][0]
    if isinstance(result_relpath, dict):
      result_relpath = result_relpath.get(JobKey.PATH)
    job_dir = target_repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / bare_expert / job_id
    result_file = job_dir / result_relpath
    agent_body_full = result_file.read_text()
    # Split frontmatter off the agent reply.
    agent_meta, agent_body = _fm.parse(agent_body_full)
    # Per-expert frontmatter policy (review.classes[].experts.*.frontmatter): the
    # overlay is filtered to `allow`; `require` is enforced inside reapply (a required
    # key absent from both the overlay and the operator doc raises). A main writer
    # declares neither and owns the document BODY only; state keys (`review_*`) are
    # daemon-managed via mechanical `_fm.set_field` writes, never the agent overlay.
    allow_fm, require_fm = _resolve_fm_policy(
        class_cfg, action_kind=action.kind, expert_name=expert_name,
    )
    agent_overlay = _filter_fm_overlay(agent_meta, allow_fm)
    try:
        # body.reassemble expects the pipeline phase ('main' /
        # 'section' / 'final'); the main writer owns the full body.
      reapply_result = _reapply.reapply(
          operator_text=text,
          agent_body=agent_body,
          phase=action.kind,
          agent_frontmatter_overlay=agent_overlay,
          owned_owner=None,
          section_layout=inputs.section_layout,
          require_fm=frozenset(require_fm),
      )
    except Exception as exc:
      _core_consume_job(target_repo, bare_expert, job_id, **consume_kwargs)
      summary[JobKey.ERROR] = f"reapply_failed: {exc}"
      return summary
  # Body drift is graceful — the diagnostic is surfaced via summary
  # so logging / UX layers can pick it up.
    if reapply_result.ownership_violation is not None:
      summary[JobKey.OWNERSHIP_VIOLATION] = {
          JobKey.EXPERT: reapply_result.ownership_violation.expert,
          JobKey.MESSAGE: reapply_result.ownership_violation.message,
      }
    new_text = reapply_result.text
    # Bug 73: the writer's commit lands clean — no cross-owner
    # section removals, no frontmatter bumps. The follow-up mech
    # commit (atomic-tick cleanup below) bumps `review_round` under
    # bot identity, preserving inv 4 (review_round bump in its own
    # mechanical commit).
    file_path.write_text(new_text)
    history_msg = response.get(JobKey.HISTORY_ENTRY, f"{expert_name} edited the document.")
    # Bug 58 part 4: empty-diff guard. When the writer returned
    # `outcome=edited` but the reassembled file is byte-equal to the
    # operator's current text (e.g. ownership tag mismatch outside the
    # section graft — see Bug 58/60, or any other agent-side error that
    # leaves the file unchanged), `git commit` exits non-zero with
    # "nothing to commit, working tree clean". Without this guard the
    # caller's md-scan iteration sees a non-zero exit and (pre-Bug 59)
    # aborts the whole tick; even post-Bug 59 it would log a repeating
    # error every 5s. Catch the specific signature, fall through to the
    # single shared consume call below, and surface the situation as a
    # `category=empty_diff` summary so operators see ONE entry instead
    # of an unbounded retry stream.
    sha: str | None = None
    empty_diff = False
    # Inv 11 + § consume subsystem: every path past this block
    # (success / empty-diff / real-error re-raise) MUST mark the job
    # CONSUMED. `try / finally` guarantees the consume call fires
    # even when a non-"nothing to commit" GitOpsError propagates out
    # (permission denied, hook refusal, disk full, …). Without this
    # the dedup_key blocks fresh dispatch and the pipeline freezes
    # on this file forever; the scan loop's per-file isolation
    # (Bug 59) still surfaces the error to the daemon log so the
    # operator can react.
    try:
      try:
        sha = _git_ops.commit_review_round(
            repo, file_path,
            round_=review_round,
            expert=expert_name,
            author=_expert_author(experts_tbl, expert_name, local_repo=repo),
            history_message=history_msg,
            phase=phase,
        )
      except _git_ops.GitOpsError as exc:
        # waiver: git CLI vocabulary
        if "nothing to commit" not in str(exc):
          raise
        empty_diff = True
      if empty_diff:
          # Inv 11 ("One commit per response"): the writer
          # responded, so a commit with the `Doc-Review-Phase` +
          # `expert=` trailer MUST land. Without it `_chain_state`
          # leaves the writer in `main_pending` and the next tick
          # re-dispatches forever (the dedup-key is cleared by the
          # consume below). Land an empty commit with the proper
          # trailer so the chain advances exactly like the explicit
          # `outcome=empty` path above.
        sha = _git_ops.commit_empty(
            repo,
            round_=review_round,
            expert=expert_name,
            author=_expert_author(experts_tbl, expert_name, local_repo=repo),
            message=f"review: {section_id} {expert_name} (empty_diff)",
            phase=phase,
        )
    finally:
      _core_consume_job(target_repo, bare_expert, job_id, **consume_kwargs)
    if empty_diff:
      summary[JobKey.STATUS] = "collected:empty_diff"
      summary[JobKey.CATEGORY] = "empty_diff"
      summary[JobKey.COMMIT_SHA] = sha
      summary[JobKey.ERROR] = (
          f"empty_diff: {expert_name} returned outcome=edited "
          f"but the reassembled file is byte-equal to the operator's "
          f"current text (likely ownership-tag mismatch in agent "
          f"output, or empty owned-section content). Landed empty "
          f"commit to satisfy inv 11 and advance the chain."
      )
      # Atomic-tick: writer round / validation round bump in same tick
      # even on empty-diff so the chain advances cleanly.
      cleanup = _run_atomic_tick_cleanup(
          repo, file_path, class_cfg,
          writer_kind=action.kind, expert_name=expert_name,
          section_id=section_id, review_round=review_round,
      )
      summary.update(cleanup)
      return summary
  # Atomic-tick post-writer cleanup (Bug 73 + atomic-tick invariant):
  # same dispatcher tick as the main-writer commit, under bot
  # identity. Bumps `review_round` + `review_main_done` and
  # repaints the banner against the new chain state.
    cleanup = _run_atomic_tick_cleanup(
        repo, file_path, class_cfg,
        writer_kind=action.kind, expert_name=expert_name,
        section_id=section_id, review_round=review_round,
    )
    summary.update(cleanup)
    # Spec § historian subsystem (barrier model): the historian is
    # NO LONGER kicked per writer-commit. The sole trigger is the
    # approve-mirror service commit (see the `approve-mirror` action
    # handler) — one clean approved state → one `# History` entry.
    # Writer-commit rounds (main iterations, validators, terminals)
    # are intermediate states and do not narrate.
    summary[JobKey.STATUS] = "collected:edited"
    summary[JobKey.COMMIT_SHA] = sha
    return summary

  _core_consume_job(target_repo, bare_expert, job_id, **consume_kwargs)
  # spec § Class 3 (trigger #2 logical-error): main-writer outcome=error category=logical falls
  # through the empty/edited branches above; record the incident before returning so the operator
  # has a per-section signal instead of a silent stall on a writer that can't proceed.
  err = (response or {}).get(JobKey.ERROR) or {}
  if outcome == JobKey.ERROR and isinstance(err, dict) and err.get(JobKey.CATEGORY) == ErrorCause.LOGICAL:
    try:
      rel = file_path.relative_to(repo)
    except ValueError:
      rel = file_path
    _record_to_ledger(
        repo,
        incident=f"review-logical:{rel}:{section_id}",
        cause=ErrorCause.LOGICAL,
        detail=f"{expert_name}: {str(err.get(JobKey.MESSAGE) or '')[:200]}",
        expert=expert_name,
    )
  summary[JobKey.ERROR] = f"unhandled_outcome: {outcome}"
  return summary


# --------------------------------------------- historian dispatch / collect


_BANNER_BLOCK_FOR_NOOP_GUARD_RE = re.compile(
    r"(?ms)^>\s*\[!\w+\][^\n]*#review/(?:in-process|action-needed|ready|concerns-decision)"
    r"[^\n]*\n(?:>[^\n]*\n)*(?:\n)*"
)


def _diff_is_content_bearing(source_path: Path, context_path: Path) -> tuple[bool, str]:
  """
  Return `(has_content_diff, hint_sentence)` for the noop-guard.

  Compares the source and context files after stripping banner-state callouts.
  When the stripped line lists differ, the historian's `noop` response was
  likely an LLM bias; the caller should override to `summarized` using the
  returned hint sentence to keep the history audit trail growing.
  The hint sentence is deterministic and marked as auto-detected.

  Returns:
    Tuple of `(has_content_diff, hint_sentence)` where `hint_sentence` is
    empty when no content difference was detected.
  """
  try:
      # guard: tolerate missing source/context files (e.g. job dir
      # cleanup race) — treat as no override.
    if not source_path.exists() or not context_path.exists():
      return False, ""
    src = source_path.read_text()
    ctx = context_path.read_text()
  except OSError:
    return False, ""
  src_stripped = _BANNER_BLOCK_FOR_NOOP_GUARD_RE.sub("", src)
  ctx_stripped = _BANNER_BLOCK_FOR_NOOP_GUARD_RE.sub("", ctx)
  src_lines = [ln.rstrip() for ln in src_stripped.splitlines() if ln.strip()]
  ctx_lines = [ln.rstrip() for ln in ctx_stripped.splitlines() if ln.strip()]
  if src_lines == ctx_lines:
    return False, ""
  src_set = set(src_lines)
  ctx_set = set(ctx_lines)
  added = len(src_set - ctx_set)
  removed = len(ctx_set - src_set)
  hint = (
      f"Document changed: ~{added} line(s) added, ~{removed} line(s) "
      f"removed (auto-detected; historian returned noop on a content-"
      f"bearing diff and the noop was overridden — see Bug 45)."
  )
  return True, hint


def _kick_historian_for_writer_commit(
    repo: Path,
    settings: dict,
    class_cfg: dict,
    file_path: Path,
    *,
    writer_commit_sha: str,
    history_records: list[_git_ops.CommitRecord],
) -> dict:
  """
  Dispatch a historian job for the writer commit that just landed.

  One job per writer-commit, kicked unconditionally for substantive rounds.
  The caller must skip this call when the writer's outcome was `empty` or
  `empty_diff` — those rounds have nothing to narrate.

  The job snapshot uses the current file state as source and the file at the
  most recent prior historian commit as context (falling back to the oldest
  known commit). The job payload carries `_target_file`, `_writer_commit_sha`,
  and `_writer_commit_timestamp` for pickup filtering and chronological insertion.

  Returns:
    Summary dict with `status="dispatched"` when queued, or
    `status="skipped:no_historian"` when the class has no historian configured.
  """
  historian_name = _historian_for_class(class_cfg)
  if not historian_name:
    return {JobKey.STATUS: "skipped:no_historian"}
  edit_marker_style = settings.get(JobKey.REVIEW, {}).get(JobKey.EDIT_MARKER_STYLE, Style.SIMPLE)
  text = file_path.read_text()
  # Pre-strip edit-marker fences + banner-state callouts on both
  # source and context so the historian's anti-noop predicate works
  # as designed (it counts non-whitespace diff lines; unstripped diff
  # fences would be counted as content and the historian would
  # mis-narrate banners / scaffolding).
  try:
    source_text = _edit_markup.strip_markers(text, style=edit_marker_style)
  except ValueError:
    source_text = text
  source_text = _body.strip_banner_callouts(source_text)
  request_payload = _payload.build_request(
      kind=Phase.HISTORY,
      mode=Phase.HISTORY,
      role=Role.HISTORIAN,
      round_=0,
      source_path=f"source/{file_path.name}",
      context_paths=[f"context/prior-{file_path.name}"],
      result_path="",
      edit_marker_style=edit_marker_style,
  )
  timestamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
  request_payload[JobKey.TARGET_FILE] = str(file_path)
  request_payload[JobKey.WRITER_COMMIT_SHA] = writer_commit_sha
  request_payload[JobKey.WRITER_COMMIT_TIMESTAMP] = timestamp
  bundle: dict = {
      JobKey.EXPERT: historian_name,
      JobKey.PAYLOAD: request_payload,
      JobKey.SOURCE: {file_path.name: source_text},
      # dedup_key includes the writer-commit-sha so parallel
      # historian jobs (one per writer-commit) can co-exist in the
      # queue. Without the sha suffix the second dispatch for the
      # same file would dedup with the first and be silently dropped.
      JobKey.DEDUP_KEY: f"{file_path}@{writer_commit_sha}",
  }
  prior_sha = _last_historian_anchor(history_records)
  if prior_sha is not None:
    prior = _show_blob(repo, prior_sha, file_path) or ""
    try:
      prior = _edit_markup.strip_markers(prior, style=edit_marker_style)
    except ValueError:
      pass
    prior = _body.strip_banner_callouts(prior)
    bundle[JobKey.CONTEXT] = {f"prior-{file_path.name}": prior}
  _core_dispatch_job(repo, bundle)
  return {
      JobKey.STATUS: JobStatus.DISPATCHED,
      JobKey.EXPERT: historian_name,
      JobKey.DEDUP_KEY: bundle[JobKey.DEDUP_KEY],
  }


def _pickup_historian_responses(
    repo: Path,
    settings: dict,
    class_cfg: dict,
    file_path: Path,
) -> dict:
  """
  Collect all completed historian jobs for `file_path` and write their history entries.

  Runs every tick before the state machine, independent of it. Each successful
  pickup writes one chronologically-inserted `# History` entry under the historian's
  identity and marks the job consumed. `noop` outcomes are either upgraded to a
  substantive placeholder via the anti-noop predicate or land an empty placeholder
  commit. Multiple jobs may be picked up in a single pass. A failed pickup is logged
  per-job but does not abort the remaining pickups.

  Returns:
    Dict with `picked_up` count and a `jobs` list of per-job result dicts.
  """
  historian_name = _historian_for_class(class_cfg)
  if not historian_name:
    return {JobKey.PICKED_UP: 0, JobKey.JOBS: []}
  experts_tbl = experts_table(settings)
  edir = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / historian_name
  if not edir.exists():
    return {JobKey.PICKED_UP: 0, JobKey.JOBS: []}
  target = str(file_path)
  picked: list[dict] = []
  # Sort by job-dir mtime so older completions land first — keeps
  # commit order roughly aligned with dispatch order (history entries
  # themselves are chronologically inserted by timestamp, so order
  # of pickup mostly affects git-log readability, not file layout).
  job_dirs = []
  for jdir in edir.iterdir():
      # guard: not a job dir
    if not jdir.is_dir():
      continue
    try:
      job_dirs.append((jdir.stat().st_mtime, jdir))
    except OSError:
      continue
  job_dirs.sort()
  for _mtime, jdir in job_dirs:
      # guard: job terminated or already consumed
    if (jdir / JobFile.DEAD).exists():
      continue
    # guard: CONSUMED job's response was already applied or discarded
    if (jdir / Outcome.CONSUMED).exists():
      continue
  # guard: agent hasn't finished yet
    if not (jdir / JobFile.DONE).exists():
      continue
    req_file = jdir / JobFile.REQUEST
    # guard: missing or unreadable request — skip without consuming
    try:
      req = json.loads(req_file.read_text())
    except (OSError, json.JSONDecodeError):
      continue
  # guard: job belongs to a different file
    if req.get(JobKey.TARGET_FILE) != target:
      continue
    try:
      response = json.loads((jdir / JobFile.RESPONSE).read_text())
    except (OSError, json.JSONDecodeError):
      response = {}
    outcome = response.get(JobKey.OUTCOME, "")
    timestamp = (
        req.get(JobKey.WRITER_COMMIT_TIMESTAMP)
        or time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    )
    if outcome == Outcome.NOOP:
      source_p = jdir / JobKey.SOURCE / file_path.name
      context_p = jdir / JobKey.CONTEXT / f"prior-{file_path.name}"
      has_content, hint = _diff_is_content_bearing(source_p, context_p)
      if has_content:
        outcome = Outcome.SUMMARIZED
        response = {**response, JobKey.OUTCOME: Outcome.SUMMARIZED, JobKey.HISTORY_ENTRY: hint}
    pick: dict = {JobKey.JOB_ID: jdir.name, JobKey.OUTCOME: outcome, JobKey.TIMESTAMP: timestamp}
    if outcome == Outcome.SUMMARIZED:
      sentence = response.get(JobKey.HISTORY_ENTRY, "")
      base_text = file_path.read_text()
      repaired = response.get(JobKey.REPAIRED_HISTORY_SECTION)
      if repaired:
        base_text = _history.splice_history_body(base_text, repaired)
      new_text = _history.insert_entry(
          base_text,
          timestamp_utc=timestamp,
          sentence=sentence,
      )
      file_path.write_text(new_text)
      try:
        sha = _git_ops.commit_history(
            repo, file_path,
            author=_expert_author(experts_tbl, historian_name, local_repo=repo),
            message=f"history: {sentence[:60]}",
        )
        pick[JobKey.COMMIT_SHA] = sha
      except _git_ops.GitOpsError as exc:
        pick[JobKey.ERROR] = f"commit_failed: {exc}"
    elif outcome == Outcome.NOOP:
      try:
        sha = _git_ops.commit_history_placeholder(
            repo, file_path,
            author=_expert_author(experts_tbl, historian_name, local_repo=repo),
            # waiver: one-off human-facing message
            message="history: noop (metadata-only revision)",
        )
        pick[JobKey.COMMIT_SHA] = sha
      except _git_ops.GitOpsError as exc:
        pick[JobKey.ERROR] = f"commit_failed: {exc}"
    else:
      pick[JobKey.ERROR] = f"unknown_outcome: {outcome!r}"
    _core_consume_job(repo, historian_name, jdir.name)
    picked.append(pick)
  return {JobKey.PICKED_UP: len(picked), JobKey.JOBS: picked}



_RESET_SEED_SUBJECT_PREFIX = "reset(seed):"


def _last_historian_anchor(
    history_records: list,
) -> str | None:
  """
  Return the sha of the most recent historian commit before the current HEAD.

  A historian commit carries a `history:append` or `history:noop`
  `Doc-Review-Phase` trailer. When no prior historian commit exists in the
  walk window, falls back to the oldest known commit so the historian sees
  the full file lifetime on first dispatch. Returns `None` when the file has
  zero or one total commit (nothing to diff against).

  Walk window: starts strictly after HEAD and **stops at the first commit
  whose subject begins with `reset(seed):`** — a deliberate life-cycle reset
  of the fixture (`reset(seed): RUN N — re-init …` from the test harness or
  any operator-authored reseed). Crossing this boundary would feed the
  historian a pre-reset file state as `context`, producing a reconstructed
  `### ts` entry that describes a body no longer present in `source` (Bug
  122). On boundary-hit the anchor falls back to the oldest commit visited
  BEFORE the boundary (the oldest post-reset commit); when the reset fires
  before any commits are visited (boundary at index 1), the anchor is
  `None` — no meaningful post-reset diff window exists.

  Returns:
    Commit sha string, or `None` when there is nothing to diff against or
    when the walk hit a `reset(seed):` boundary before visiting any non-reset
    commit.
  """
  if len(history_records) < 2:
    return None
  # Skip index 0 (current HEAD): we want what's strictly OLDER. Walk back
  # looking for the most recent historian-tagged commit; stop at the
  # reset-seed boundary if one fires first.
  last_post_reset_sha: str | None = None
  for record in history_records[1:]:
    subject = (getattr(record, "subject", "") or "").lstrip()
    # guard: reset-seed commits mark a fixture-lifecycle boundary; the
    # pre-reset body lives a different life and must not become context
    if subject.startswith(_RESET_SEED_SUBJECT_PREFIX):
      return last_post_reset_sha
    trailers = getattr(record, "trailers", None) or {}
    phase, _e, _r = _git_ops.parse_phase_trailer(trailers)
    if phase.startswith(Phase.HISTORY):
      return record.sha
    last_post_reset_sha = record.sha
  # No prior historian commit found AND no reset boundary hit — fall back
  # to the oldest known commit on the file. Diff window = entire file
  # lifetime (`last_post_reset_sha` ends up holding the file's oldest sha
  # because we updated it on every non-reset, non-historian iteration).
  return last_post_reset_sha


# --------------------------------------------- repair dispatch / collect


# waiver: `class_cfg`/`inputs` kept for the uniform dispatch signature; unused in this branch
def _dispatch_repair(  # pylint: disable=unused-argument
    repo: Path,
    settings: dict,
    class_cfg: dict,
    file_path: Path,
    inputs: _sm.TickInputs,
    context: dict,
    summary: dict,
) -> dict:
  """
  Dispatch or collect a repair job for a broken file.

  Returns:
    Updated `summary` dict with status and commit sha when a repair was applied.
  """
  text = context[JobKey.TEXT]
  repairer = settings.get(JobKey.REVIEW, {}).get(JobKey.DOC_DOCTOR, Role.DOC_DOCTOR)
  dedup_key = str(file_path)
  existing = _find_done_job(repo, repairer, dedup_key)
  job_id = existing.get(JobKey.JOB_ID)
  if existing.get(JobKey.STATUS) == JobStatus.PENDING:
    summary[JobKey.STATUS] = "pending"
    return summary
  if existing.get(JobKey.STATUS) == Outcome.MISSING:
    request_payload = _payload.build_request(
        kind=Outcome.REPAIR, mode=Outcome.REPAIR, role=Outcome.REPAIR,
        round_=context[ReviewKey.ROUND],
        source_path=f"source/{file_path.name}",
        context_paths=[],
        result_path=f"result/{file_path.name}",
        edit_marker_style=Style.SIMPLE,
    )
    # Operator-conflict guard: stamp both the content snapshot (legacy /
    # fallback) and the operator-sha anchor (Bug 112 fix) so collect-time
    # `_operator_touched_since_dispatch` can skip intervening bot commits.
    request_payload[JobKey.FILE_SNAPSHOT_HASH] = _file_snapshot_hash(file_path)
    _operator_commit_sha = context.get(JobKey.OPERATOR_COMMIT_SHA)
    # guard: only stamp the anchor when an operator-commit exists
    if _operator_commit_sha is not None:
      request_payload[JobKey.OPERATOR_SHA_AT_DISPATCH] = _operator_commit_sha
    _core_dispatch_job(repo, {
        JobKey.EXPERT: repairer,
        JobKey.PAYLOAD: request_payload,
        JobKey.SOURCE: {file_path.name: text},
        JobKey.RESULT: [file_path.name],
        JobKey.DEDUP_KEY: dedup_key,
    })
    summary[JobKey.STATUS] = "dispatched"
    return summary
# guard: a finished repair job always carries its job_id (pending / missing returned above)
  if job_id is None:
    summary[JobKey.STATUS] = "error:missing-job-id"
    return summary
  response = existing.get(JobKey.RESPONSE, {})
  # Operator-conflict check. Every return path below MUST mark the
  # job consumed.
  job_dir = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / repairer / job_id
  try:
    req_payload = json.loads((job_dir / JobFile.REQUEST).read_text())
  except (OSError, json.JSONDecodeError):
    req_payload = {}
  if _operator_touched_since_dispatch(
      file_path, req_payload,
      operator_commit_sha = context.get(JobKey.OPERATOR_COMMIT_SHA),
  ):
    _core_consume_job(repo, repairer, job_id)
    summary[JobKey.STATUS] = "discarded:operator-conflict"
    return summary
  if response.get(JobKey.OUTCOME) == Outcome.EDITED:
    rel = response[JobKey.RESULT][0]
    if isinstance(rel, dict):
      rel = rel.get(JobKey.PATH)
    repaired_text = (Path(repo) / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / repairer / job_id / rel).read_text()
    file_path.write_text(repaired_text)
    sha = _git_ops.commit_mechanical(
        repo, file_path,
        author=_bot_author(),
        # waiver: one-off human-facing message
        message="review: doc_doctor repair",
    )
    _core_consume_job(repo, repairer, job_id)
    summary[JobKey.STATUS] = "collected:repaired"
    summary[JobKey.COMMIT_SHA] = sha
    return summary
  summary[JobKey.STATUS] = "repair_failed"
  return summary


# ----------------------------------------------------------- helpers


def _file_snapshot_hash(file_path: Path) -> str:
  """
  Return the SHA-256 hex digest of the file's current content.

  Stored in the dispatch payload and compared at collect time; a mismatch
  signals that the operator touched the file while the agent was working.

  Returns:
    Hex-encoded SHA-256 digest string.
  """
  return _hashlib.sha256(file_path.read_bytes()).hexdigest()


# ------------------------------------------------- post-approve barrier state


def _barrier_dedup_key(file_path: Path, section_id: str) -> str:
  """
  Return the section-scoped dedup key for a barrier writer's job.

  Scoped as `<file>#<section_id>` so all writers of a barrier —
  including two sections owned by the same expert — coexist in the queue.

  Returns:
    Dedup key string for the barrier job.
  """
  return f"{file_path}#{section_id}"


def _newest_job_payload(
    repo: Path, expert_name: str, dedup_key: str, *, include_consumed: bool,
) -> dict | None:
  """
  Return the newest `request.json` payload for `(expert, dedup_key)` by mtime.

  Args:
    repo: Repository root path.
    expert_name: Expert name, bare or `expert@repo` form.
    dedup_key: Job dedup key to match.
    include_consumed: When True, includes already-consumed job dirs; used by
      the selective-respawn freshness check which must see the most recent
      dispatch regardless of consume state.

  Returns:
    The payload dict from the newest matching job, or `None` when none exists.
  """
  bare, _repo_key = _parse_expert_name(expert_name)
  # guard: cross-repo barrier writers — defer to a later pass
  if "@" in expert_name:
    return None
  edir = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / bare
  if not edir.exists():
    return None
  best: tuple[float, dict] | None = None
  for jdir in edir.iterdir():
    # guard: only job subdirectories hold a request.json
    if not jdir.is_dir():
      continue
    req = jdir / JobFile.REQUEST
    # guard: job dir without a request.json carries no dedup key to match
    if not req.exists():
      continue
    try:
      data = json.loads(req.read_text())
    except (OSError, json.JSONDecodeError):
      continue
    # guard: request belongs to a different dedup key — not this barrier job
    if data.get(JobKey.DEDUP_TRACKER) != dedup_key:
      continue
    # guard: skip already-consumed jobs unless the caller asked to include them
    if (not include_consumed) and (jdir / Outcome.CONSUMED).exists():
      continue
    mtime = req.stat().st_mtime
    # waiver: short-circuit guard ensures best is a tuple at best[0]; pylint can't track it
    if best is None or mtime > best[0]:  # pylint: disable=unsubscriptable-object
      best = (mtime, data)
  return best[1] if best else None


def _barrier_job_status(repo: Path, expert_name: str, dedup_key: str) -> str:
  """
  Return the live job-queue status of a barrier writer's job.

  Status is derived from the job queue, not from commit-message parsing.
  `"missing"` covers both never-dispatched and dispatched-then-consumed jobs;
  the body-section probe determines whether a fresh dispatch is needed.
  Cross-repo barrier writers are not yet supported and always report `"missing"`.

  Returns:
    One of `"missing"` / `"pending"` / `"done"` / `"dead"`.
  """
  bare, _repo_key = _parse_expert_name(expert_name)
  # guard: cross-repo barrier writers — defer to a later pass
  if "@" in expert_name:
    return Outcome.MISSING
  edir = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / bare
  if not edir.exists():
    return Outcome.MISSING
  best: tuple[float, Path] | None = None
  for jdir in edir.iterdir():
    # guard: only job subdirectories hold a request.json
    if not jdir.is_dir():
      continue
    req = jdir / JobFile.REQUEST
    # guard: job dir without a request.json carries no dedup key to match
    if not req.exists():
      continue
    try:
      data = json.loads(req.read_text())
    except (OSError, json.JSONDecodeError):
      continue
    # guard: request belongs to a different dedup key — not this barrier job
    if data.get(JobKey.DEDUP_TRACKER) != dedup_key:
      continue
    mtime = req.stat().st_mtime
    # waiver: short-circuit guard ensures best is a tuple at best[0]; pylint can't track it
    if best is None or mtime > best[0]:  # pylint: disable=unsubscriptable-object
      best = (mtime, jdir)
  if best is None:
    return Outcome.MISSING
  jdir = best[1]
  if (jdir / Outcome.CONSUMED).exists():
    return Outcome.MISSING
  if (jdir / JobFile.DEAD).exists():
    return JobStatus.DEAD
  if (jdir / JobFile.DONE).exists():
    return JobStatus.DONE
  return JobStatus.PENDING


def _historian_jobs_outstanding(repo: Path, class_cfg: dict, file_path: Path) -> bool:
  """
  Return True iff a historian job for `file_path` is still uncollected.

  Covers in-flight jobs (no DONE/DEAD) and DONE-but-not-CONSUMED jobs where
  pickup failed to land the entry. DEAD jobs do not block finalize. Drives
  the finalize gate so a late history entry never writes into a closed document.

  Returns:
    True when at least one uncollected historian job exists for the file.
  """
  historian_name = _historian_for_class(class_cfg)
  if not historian_name:
    return False
  edir = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / historian_name
  if not edir.exists():
    return False
  target = str(file_path)
  for jdir in edir.iterdir():
    # guard: only job subdirectories hold a request.json
    if not jdir.is_dir():
      continue
  # guard: terminal-state jobs never block finalize
    if (jdir / Outcome.CONSUMED).exists() or (jdir / JobFile.DEAD).exists():
      continue
    try:
      data = json.loads((jdir / JobFile.REQUEST).read_text())
    except (OSError, json.JSONDecodeError):
      continue
    if data.get(JobKey.TARGET_FILE) == target:
      return True
  return False


_H1_LINE_RE = re.compile(r"^# .+$")
_TAG_LINE_RE = re.compile(r"^#[A-Za-z]")


def _operator_diff_line_ranges(repo: Path, file_path: Path, sha: str = "HEAD") -> list[tuple[int, int]]:
  """
  Return new-side 1-based line ranges that commit `sha` changed versus its parent.

  Line numbers index `sha`'s file state. The caller must read section spans
  from the same revision to avoid off-by-one masking from intervening
  mechanical commits. Empty when there is no parent or no diff.

  Returns:
    List of `(start, end)` inclusive 1-based line ranges changed by the commit.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess as _sp
  rel = str(file_path.relative_to(repo)) if file_path.is_absolute() else str(file_path)
  out = _sp.run(
      ["git", "-C", str(repo), "diff", "--unified=0", f"{sha}~1", sha, "--", rel],
      check=False, capture_output=True, text=True,
  )
  # guard: no parent commit / git error
  if out.returncode != 0:
    return []
  ranges: list[tuple[int, int]] = []
  for line in out.stdout.splitlines():
      # guard: only hunk headers carry the +start,count we need
    if not line.startswith("@@"):
      continue
    match = re.search(r"\+(\d+)(?:,(\d+))?", line)
    # guard: hunk header without a parseable +start — skip it
    if match is None:
      continue
    start = int(match.group(1))
    count = int(match.group(2)) if match.group(2) is not None else 1
    # guard: pure-deletion hunk (+N,0) — attribute to the boundary line
    if count == 0:
      ranges.append((start, start))
    else:
      ranges.append((start, start + count - 1))
  return ranges


def _file_text_at_rev(repo: Path, file_path: Path, sha: str | None) -> str:
  """
  Return the file content at revision `sha`.

  Falls back to the working-tree file when `sha` is `None` or the git show fails.

  Returns:
    File text string at the requested revision, or current working-tree content.
  """
  if not sha:
    return file_path.read_text()
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess as _sp
  rel = str(file_path.relative_to(repo)) if file_path.is_absolute() else str(file_path)
  out = _sp.run(
      ["git", "-C", str(repo), "show", f"{sha}:{rel}"],
      check=False, capture_output=True, text=True,
  )
  return out.stdout if out.returncode == 0 else file_path.read_text()


def _section_line_spans(text: str) -> list[tuple[str, int, int]]:
  """
  Return per-H1-section `(owner_tag, start_line, end_line)` tuples, 1-based inclusive.

  `owner_tag` is the leading `#…`-prefixed tag on the section's first non-empty
  content line, or `""` for untagged operator content.

  Returns:
    List of `(owner_tag, start_line, end_line)` tuples covering each H1 section.
  """
  lines = text.split("\n")
  h1 = [i for i, ln in enumerate(lines) if _H1_LINE_RE.match(ln)]
  spans: list[tuple[str, int, int]] = []
  for k, si in enumerate(h1):
    ei = (h1[k + 1] - 1) if k + 1 < len(h1) else (len(lines) - 1)
    tag = ""
    for j in range(si + 1, ei + 1):
      stripped = lines[j].strip()
      # guard: skip blank lines before the first content line
      if not stripped:
        continue
      if _TAG_LINE_RE.match(stripped):
        tag = stripped.split()[0]
      break
    spans.append((tag, si + 1, ei + 1))
  return spans


def _ranges_overlap(ranges: list[tuple[int, int]], start: int, end: int) -> bool:
  """
  Return True iff `[start, end]` overlaps any range in `ranges`.

  Returns:
    True when at least one range in `ranges` intersects `[start, end]`.
  """
  return any(a <= end and start <= b for (a, b) in ranges)


def _line_in_ranges(line: int, ranges: list[tuple[int, int]]) -> bool:
  """
  Return True iff `line` falls within any range in `ranges`.

  Returns:
    True when `line` is covered by at least one `(start, end)` range.
  """
  return any(a <= line <= b for (a, b) in ranges)


def _operator_post_approve_analysis(
    repo: Path,
    file_path: Path,
    section_writers_full: list,
    *,
    op_sha: str | None = None,
) -> tuple[set, bool]:
  """
  Classify a post-approve operator commit into respawn targets and a reset flag.

  `respawn_section_ids` are terminal section-ids whose owned line range was
  touched by the commit's diff — those writers' prior output is stale and
  must be re-run. `reset_pending` is True when the diff touched any line
  outside every owned H1 section and the frontmatter/banner preamble,
  indicating a free-prose edit that invalidates the approval.

  Both the diff and section spans are taken from `op_sha` so a mechanical
  commit on top cannot mask the operator's edit. Falls back to HEAD and the
  working tree when `op_sha` is `None`.

  Args:
    repo: Repository root path.
    file_path: Path to the reviewed file.
    section_writers_full: Full section-writer list from the class config.
    op_sha: The operator's contentful commit sha, or `None` for HEAD fallback.

  Returns:
    Tuple `(respawn_section_ids, reset_pending)`.
  """
  sha = op_sha or "HEAD"
  touched = _operator_diff_line_ranges(repo, file_path, sha)
  # guard: the operator commit changed nothing on this file
  if not touched:
    return set(), False
  text = _file_text_at_rev(repo, file_path, op_sha)
  spans = _section_line_spans(text)
  first_h1 = min((s for (_t, s, _e) in spans), default=None)
  # Terminal section line ranges, keyed by section-id.
  term_spans: dict[str, tuple[int, int]] = {}
  for (name, sec_id, _title, post_approve, is_terminal, _pos) in section_writers_full:
      # guard: only post-approve terminal writers are selectively respawnable
    if not (post_approve and is_terminal):
      continue
    owner_tag = f"#expert/{_flatten(name)}/{sec_id}"
    for (tag, s, e) in spans:
      if tag == owner_tag:
        term_spans[sec_id] = (s, e)
        break
# Protected (no-reset) ranges: the frontmatter/banner preamble before
# the first H1, plus every tagged (owned) H1 section.
  protected: list[tuple[int, int]] = []
  if first_h1 is not None and first_h1 > 1:
    protected.append((1, first_h1 - 1))
  protected.extend((s, e) for (tag, s, e) in spans if tag)
  respawn = {sid for sid, (s, e) in term_spans.items() if _ranges_overlap(touched, s, e)}
  reset = any(
      not _line_in_ranges(ln, protected)
      for (a, b) in touched
      for ln in range(a, b + 1)
  )
  return respawn, reset


# waiver: `class_cfg` kept for the uniform barrier signature; unused in this branch
def _compute_barrier_inputs(  # pylint: disable=unused-argument
    repo: Path,
    class_cfg: dict,
    file_path: Path,
    *,
    body: str,
    review_phase: str | None,
    section_writers_full: list,
    last_commit_is_human: bool,
    operator_commit_sha: str | None = None,
) -> dict:
  """
  Derive post-approve barrier inputs for the state machine.

  Per-writer status comes from the live job queue and the body section probe,
  never from commit-message parsing. In the terminal phase, a post-approve
  operator commit triggers selective respawn of only the terminals whose owned
  section was touched; a free-prose edit sets `reset` to re-open the validator
  barrier.

  Returns:
    Dict with `to_dispatch`, `open`, `ready`, `reset`, and `waiting_context` keys.
  """
  to_dispatch: list = []
  out = {
      JobKey.TO_DISPATCH: to_dispatch,
      JobKey.OPEN: False,
      JobKey.READY: False,
      JobKey.RESET: False,
      JobKey.WAITING_CONTEXT: None,
  }
  # guard: only the two post-approve barrier phases carry barrier state
  if review_phase not in (Bucket.VALIDATORS, Bucket.TERMINALS):
    return out
  is_validator_phase = review_phase == Bucket.VALIDATORS
  out[JobKey.WAITING_CONTEXT] = review_phase
  # Selective respawn + body-edit reset for a post-approve operator
  # commit in the terminal phase (spec § Stage 6). Validators never see
  # an operator commit mid-barrier, so the analysis only applies once the
  # validator barrier has cleared into the terminal phase.
  respawn_ids: set = set()
  if (not is_validator_phase) and last_commit_is_human:
    respawn_ids, reset = _operator_post_approve_analysis(
        repo, file_path, section_writers_full,
        op_sha=operator_commit_sha,
    )
    out[JobKey.RESET] = reset
  done_or_dead = 0
  for ref in section_writers_full:
    name, sec_id, _title, post_approve, is_terminal, _position = ref
    # guard: not a post-approve writer / not this phase's bucket
    if not post_approve:
      continue
    # guard: terminal writers belong to the terminal phase, not the validator phase
    if is_validator_phase and is_terminal:
      continue
    # guard: validation writers belong to the validator phase only
    if (not is_validator_phase) and (not is_terminal):
      continue
    dkey = _barrier_dedup_key(file_path, sec_id)
    status = _barrier_job_status(repo, name, dkey)
    has_section = _body.section_content_for_owner(
        body, (_flatten(name), sec_id),
    ) is not None
    if status == JobStatus.PENDING:
      out[JobKey.OPEN] = True
    elif status in ("done", "dead"):
        # Selective respawn on a terminal-state job: respawn only if
        # (a) operator touched this section AND (b) the existing job
        # was dispatched in response to an OLDER operator commit. The
        # job's `_operator_sha_at_dispatch` payload field is the
        # anchor — set to `chain.last_contentful_sha` at the moment
        # of dispatch. When a fresh respawn lands DONE its anchor
        # equals the current operator sha → not stale → done_or_dead
        # ++ → barrier-collect proceeds. Comparing operator-sha (not
        # file content) avoids the false-positive loop where
        # mechanical banner-repaint commits between the operator-tick
        # and the respawn-dispatch shift the file hash without any
        # new operator action. Legacy jobs (no anchor in payload) are
        # treated as stale once → re-dispatched once → from then on
        # the anchor exists and the check stabilises. DEAD jobs
        # always count as done_or_dead (terminal failure).
      is_stale = False
      if status == JobStatus.DONE and sec_id in respawn_ids and operator_commit_sha is not None:
        payload = _newest_job_payload(repo, name, dkey, include_consumed=False)
        anchor = (payload or {}).get(JobKey.OPERATOR_SHA_AT_DISPATCH)
        is_stale = anchor != operator_commit_sha
      if is_stale:
        to_dispatch.append(ref)
      else:
        done_or_dead += 1
    # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
    else:  # noqa: PLR5501  -- missing-section branch; nested if/elif kept readable
        # First-ever dispatch is needed when the section is not in
        # the body yet. Otherwise, respawn when the operator has
        # committed AFTER the most recent job (including the just-
        # consumed one) was dispatched — same operator-sha anchor
        # check as the done branch. After a fresh respawn collects +
        # consumes, the CONSUMED job's anchor equals the current
        # operator sha → no further respawn (avoids the infinite
        # re-dispatch loop in the post-collect state where the file
        # hash differs from dispatch state due to the collect's own
        # mechanical commit).
      if not has_section:
        to_dispatch.append(ref)
      elif sec_id in respawn_ids and operator_commit_sha is not None:
        payload = _newest_job_payload(repo, name, dkey, include_consumed=True)
        anchor = (payload or {}).get(JobKey.OPERATOR_SHA_AT_DISPATCH)
        if anchor != operator_commit_sha:
          to_dispatch.append(ref)
  out[JobKey.READY] = (
      not to_dispatch and not out[JobKey.OPEN] and done_or_dead > 0
  )
  return out


def _dispatch_barrier_writer(
    repo: Path,
    settings: dict,
    class_cfg: dict,
    file_path: Path,
    expert_name: str,
    section_id: str,
    context: dict,
) -> None:
  """
  Queue one barrier writer's job with a section-scoped dedup key.

  No commit is made here — the sweep-collect tick lands the section later.
  """
  text = context[JobKey.TEXT]
  review_round = context[ReviewKey.ROUND]
  operator_commit_sha = context.get(JobKey.OPERATOR_COMMIT_SHA)
  edit_marker_style = settings.get(JobKey.REVIEW, {}).get(JobKey.EDIT_MARKER_STYLE, Style.SIMPLE)
  wire_role = _resolve_wire_role(
      class_cfg, action_kind=Phase.SECTION,
      expert_name=expert_name, section_id=section_id,
  )
  wire_mode = _resolve_mode(
      action_kind=Phase.SECTION, class_cfg=class_cfg, section_id=section_id,
  )
  stripped = _body.strip_for_section_writer(
      text, owner=(_flatten(expert_name), section_id),
  )
  request_payload = _payload.build_request(
      kind=Kind.REVIEW,
      mode=wire_mode,
      role=wire_role,
      round_=review_round,
      source_path=f"source/{file_path.name}",
      context_paths=[],
      result_path=f"result/{file_path.name}",
      edit_marker_style=edit_marker_style,
  )
  request_payload[JobKey.FILE_SNAPSHOT_HASH] = _file_snapshot_hash(file_path)
  # guard: only stamp the operator anchor when one exists (no contentful
  # commit yet on a brand-new file → operator_commit_sha is None)
  if operator_commit_sha is not None:
    request_payload[JobKey.OPERATOR_SHA_AT_DISPATCH] = operator_commit_sha
  bare_expert, repo_key = _parse_expert_name(expert_name)
  target_repo = _resolve_target_repo(repo, repo_key)
  bundle: dict = {
      JobKey.EXPERT: bare_expert,
      JobKey.PAYLOAD: request_payload,
      JobKey.SOURCE: {file_path.name: stripped},
      JobKey.RESULT: [file_path.name],
      JobKey.DEDUP_KEY: _barrier_dedup_key(file_path, section_id),
  }
  if target_repo != repo.resolve():
    bundle[JobKey.DISPATCHED_FROM] = str(repo)
  _core_dispatch_job(target_repo, bundle)


def _find_barrier_job(repo: Path, expert_name: str, dedup_key: str) -> tuple | None:
  """
  Locate the newest non-consumed barrier job for `(expert, dedup_key)`.

  Local-only; cross-repo barrier collect is not yet supported.

  Returns:
    Tuple `(job_dir, response_dict_or_None, status)` where status is
    `"done"` / `"dead"` / `"pending"`, or `None` when no live job exists.
  """
  bare, _repo_key = _parse_expert_name(expert_name)
  edir = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / bare
  if not edir.exists():
    return None
  best: tuple[float, Path] | None = None
  for jdir in edir.iterdir():
    # guard: only job subdirectories hold a request.json
    if not jdir.is_dir():
      continue
    req = jdir / JobFile.REQUEST
    # guard: job dir without a request.json carries no dedup key to match
    if not req.exists():
      continue
    try:
      data = json.loads(req.read_text())
    except (OSError, json.JSONDecodeError):
      continue
    # guard: request belongs to a different dedup key — not this barrier job
    if data.get(JobKey.DEDUP_TRACKER) != dedup_key:
      continue
  # guard: already collected
    if (jdir / Outcome.CONSUMED).exists():
      continue
    mtime = req.stat().st_mtime
    # waiver: short-circuit guard ensures best is a tuple at best[0]; pylint can't track it
    if best is None or mtime > best[0]:  # pylint: disable=unsubscriptable-object
      best = (mtime, jdir)
  if best is None:
    return None
  jdir = best[1]
  if (jdir / JobFile.DEAD).exists():
    return (jdir, None, "dead")
  if not (jdir / JobFile.DONE).exists():
    return (jdir, None, "pending")
  try:
    resp = json.loads((jdir / JobFile.RESPONSE).read_text())
  except (OSError, json.JSONDecodeError):
    resp = {}
  return (jdir, resp, "done")


def _collect_one_barrier_section(
    repo: Path,
    settings: dict,
    file_path: Path,
    inputs: _sm.TickInputs,
    ref: tuple,
    response: dict | None,
    status: str,
) -> str | None:
  """
  Apply one barrier writer's response to its owned H1 section and commit.

  Commits under the writer's identity with phase `section:<id>`. A `DEAD`
  status or `outcome=empty` response triggers the no-concerns treatment.

  Returns:
    The commit sha, or `None` on a benign empty-diff or when the round is
    left uncommitted due to a failed or require-not-met response.
  """
  expert_name, section_id, title, _post_approve, is_terminal, _position = ref
  experts_tbl = experts_table(settings)
  text = file_path.read_text()
  _meta, body = _fm.parse(text)
  owner = (_flatten(expert_name), section_id)
  section_title = title or section_id.replace("_", " ").capitalize()
  owner_tag = f"#expert/{_flatten(expert_name)}/{section_id}"
  is_empty = (status == JobStatus.DEAD) or (not response) or (response.get(JobKey.OUTCOME) == Outcome.EMPTY)
  # An errored response (outcome=="error") carries no "result" key; the unconditional
  # response["result"][0] in the else-branch below would otherwise crash-loop the scan.
  is_failed = (response is not None) and (
    response.get(JobKey.OUTCOME) == JobKey.ERROR or JobKey.RESULT not in response
  )
  # guard: failed round — leave section uncommitted; daemon re-dispatches (mirrors require-not-met below).
  if (not is_empty) and is_failed:
      # spec § Class 3 (trigger #2 logical-error): when a review expert returns
      # outcome=error category=logical, the input is invalid and retry won't help — register the
      # incident so the operator sees it instead of an invisible per-tick re-dispatch loop. Other
      # categories (transient → runner retries; technical → log+exit) do NOT land here.
    err = (response or {}).get(JobKey.ERROR) or {}
    if isinstance(err, dict) and err.get(JobKey.CATEGORY) == ErrorCause.LOGICAL:
      try:
        rel = file_path.relative_to(repo)
      except ValueError:
        rel = file_path
      _record_to_ledger(
          repo,
          incident=f"review-logical:{rel}:{section_id}",
          cause=ErrorCause.LOGICAL,
          detail=f"{expert_name}: {str(err.get(JobKey.MESSAGE) or '')[:200]}",
          expert=expert_name,
      )
    return None
  agent_overlay: dict = {}
  require_fm: frozenset[str] = frozenset()
  if is_empty:
    if is_terminal:
      current = _body.section_content_for_owner(body, owner) or ""
      cleaned = _body.strip_review_callouts(current).strip("\n")
      agent_body = (
          f"# {section_title}\n{owner_tag}\n\n{cleaned}\n"
          if cleaned else f"# {section_title}\n{owner_tag}\n"
      )
    else:
      marker = "> [!check] No concerns"
      agent_body = f"# {section_title}\n{owner_tag}\n\n{marker}\n"
  else:
      # guard: a non-empty, non-failed response is always a dict carrying a result payload
    if response is None:
      return None
    result_relpath = response[JobKey.RESULT][0]
    if isinstance(result_relpath, dict):
      result_relpath = result_relpath.get(JobKey.PATH)
    _bare, _rk = _parse_expert_name(expert_name)
    # ref carries no job dir; re-locate to read the result file.
    found = _find_barrier_job(repo, expert_name, _barrier_dedup_key(file_path, section_id))
    result_text = ""
    if found is not None:
      result_text = (found[0] / result_relpath).read_text()
    agent_meta, section_body = _fm.parse(result_text)
    stripped_body = section_body.strip("\n")
    if stripped_body:
      agent_body = f"# {section_title}\n{owner_tag}\n\n{stripped_body}\n"
    else:
      marker = "> [!check] No concerns"
      agent_body = f"# {section_title}\n{owner_tag}\n\n{marker}\n"
    allow_fm, _require = _resolve_fm_policy(
        _class_for_file(settings, repo, file_path) or {},
        action_kind=Phase.SECTION, expert_name=expert_name, section_id=section_id,
    )
    require_fm = frozenset(_require)
    agent_overlay = _filter_fm_overlay(agent_meta, allow_fm)
  try:
    reapply_result = _reapply.reapply(
        operator_text=text,
        agent_body=agent_body,
        phase=Phase.SECTION,
        agent_frontmatter_overlay=agent_overlay,
        owned_owner=owner,
        section_layout=inputs.section_layout,
        require_fm=require_fm,
    )
  except ValueError:
      # require not met (e.g. router declares require: [request_class] but did not
      # classify) — leave the section uncommitted so the bad round is not silently
      # applied; the daemon re-dispatches on the next tick.
    return None
  new_text = reapply_result.text
  _cur_meta2, cur_body2 = _fm.parse(new_text)
  cur_fm2 = new_text[: len(new_text) - len(cur_body2)]
  cur_body2 = _body.rewrite_section_h1(cur_body2, owner, section_title)
  file_path.write_text(cur_fm2 + cur_body2)
  try:
    return _git_ops.commit_review_round(
        repo, file_path,
        round_=inputs.validation_round,
        expert=expert_name,
        author=_expert_author(experts_tbl, expert_name, local_repo=repo),
        history_message=f"{section_id} {expert_name} (barrier)",
        phase=f"section:{section_id}",
    )
  except _git_ops.GitOpsError as exc:
    # waiver: git CLI vocabulary
    if "nothing to commit" in str(exc):
      return _git_ops.commit_empty(
          repo, round_=inputs.validation_round, expert=expert_name,
          author=_expert_author(experts_tbl, expert_name, local_repo=repo),
          message=f"review: {section_id} {expert_name} (barrier empty_diff)",
          phase=f"section:{section_id}",
      )
    raise


# waiver: `context` kept for the uniform barrier signature; unused in this branch
def _barrier_collect(  # pylint: disable=unused-argument
    repo: Path,
    settings: dict,
    class_cfg: dict,
    file_path: Path,
    inputs: _sm.TickInputs,
    context: dict,
    summary: dict,
) -> dict:
  """
  Sweep-collect all barrier writers and land a single decision commit.

  Writes one commit per barrier writer under its own identity, then one
  mechanical decision commit that transitions the phase.

  Returns:
    Updated `summary` dict with `section_commits`, `decision_commit_sha`,
    and `status`.
  """
  phase = inputs.review_phase
  is_validator_phase = phase == Bucket.VALIDATORS
  section_writers_full = _gather_section_writers(class_cfg)
  section_commits: list[str] = []
  # Operator-wins (spec § What if the operator committed while the expert
  # works): if the operator touched the file since these barrier
  # jobs were dispatched, discard the whole pass — consume the stale
  # jobs so they don't re-trigger and re-plan next tick against the
  # operator's updated document. The normal per-tick consume path runs
  # this check too; the barrier collect must honour it as well.
  _phase_refs = [
      r for r in section_writers_full
      # waiver: inline numeric literal, not a domain constant
      if r[3] and (bool(r[4]) == (not is_validator_phase))
  ]
  _found_jobs = [
      (r, _find_barrier_job(repo, r[0], _barrier_dedup_key(file_path, r[1])))
      for r in _phase_refs
  ]
  _live_jobs = [(r, f) for (r, f) in _found_jobs if f is not None and f[2] in ("done", "dead")]
  for _r, _f in _live_jobs:
      # guard: only a DONE job carries a snapshot worth comparing
    if _f[2] != JobStatus.DONE:
      continue
    try:
      _payload = json.loads((_f[0] / JobFile.REQUEST).read_text())
    except (OSError, json.JSONDecodeError):
      _payload = {}
    if _operator_touched_since_dispatch(
        file_path, _payload,
        operator_commit_sha = context.get(JobKey.OPERATOR_COMMIT_SHA),
    ):
      for _r2, _f2 in _live_jobs:
        _bare2, _rk2 = _parse_expert_name(_r2[0])
        _core_consume_job(repo, _bare2, _f2[0].name)
      summary[JobKey.STATUS] = "barrier-discarded:operator-conflict"
      return summary
    break
  for ref in section_writers_full:
    name, sec_id, _title, post_approve, is_terminal, _position = ref
    # guard: pre-approve writers are not barrier collectors
    if not post_approve:
      continue
    # guard: terminal writers are collected outside the validator phase
    if is_validator_phase and is_terminal:
      continue
    # guard: validation writers are collected only in the validator phase
    if (not is_validator_phase) and (not is_terminal):
      continue
    found = _find_barrier_job(repo, name, _barrier_dedup_key(file_path, sec_id))
    # guard: nothing live (already collected) or still in flight
    if found is None or found[2] == JobStatus.PENDING:
      continue
    jdir, resp, status = found
    sha = _collect_one_barrier_section(
        repo, settings, file_path, inputs, ref, resp, status,
    )
    if sha:
      section_commits.append(sha)
    bare, _rk = _parse_expert_name(name)
    _core_consume_job(repo, bare, jdir.name)
  summary[JobKey.SECTION_COMMITS] = section_commits
  # ----- decision commit (one, mechanical, atomic-tick) --------------
  raw = file_path.read_text()
  meta, body = _fm.parse(raw)
  fm_text = raw[: len(raw) - len(body)]
  new_body = body
  if is_validator_phase:
    validation_writers = [
        (_flatten(name), sec_id)
        for (name, sec_id, _t, pa, term, _p) in section_writers_full
        if pa and not term
    ]
    any_concern = any(
        _body.section_has_concerns(body, owner) for owner in validation_writers
    )
    if any_concern:
      new_vr = _to_int(meta.get(ReviewKey.VALIDATION_ROUND), default=0) + 1
      fm_text = _fm.set_field(fm_text, ReviewKey.VALIDATION_ROUND, new_vr)
      threshold = _to_int(class_cfg.get(JobKey.CONCERNS_DECISION_THRESHOLD), default=2)
      threshold = max(threshold, 1)
      if new_vr < threshold:
          # 5a revert-to-main (spec transition validators → main):
          # explicit `review_phase: main` + fresh empty
          # `review_main_done` so the next pre-approve round re-runs
          # the main writers; drop the approve mirror.
        fm_text = _write_review_approved(fm_text, False)
        fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, Phase.MAIN)
        fm_text = _fm.set_field(fm_text, ReviewKey.MAIN_DONE, _serialize_main_done([]))
        new_body = _banner.replace_banner(
            new_body, _banner.State.IN_PROCESS, waiting_context=Bucket.WRITER,
        )
        msg = f"review: validator barrier → revert (validation_round → {new_vr})"
      else:
          # 5b concerns-decision pause (spec transition validators →
          # concerns-pause): the operator chooses continue vs
          # approve-with-concerns. Stay approved; phase carries the
          # pause so the next tick renders the pause banner.
        fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, Bucket.CONCERNS_PAUSE)
        new_body = _banner.replace_banner(new_body, _banner.State.CONCERNS_DECISION)
        msg = f"review: validator barrier → pause (validation_round → {new_vr})"
      summary[JobKey.NEW_VALIDATION_ROUND] = new_vr
    else:
      has_terminals = any(
          pa and term for (_n, _s, _t, pa, term, _p) in section_writers_full
      )
      if has_terminals:
        fm_text = _fm.set_field(fm_text, ReviewKey.PHASE, Bucket.TERMINALS)
        new_body = _banner.replace_banner(
            new_body, _banner.State.IN_PROCESS, waiting_context=Bucket.TERMINALS,
        )
        msg = "review: validator barrier clear → terminals"
      else:
          # No terminals → clear the phase; next tick finalizes
          # (historian-gated). Banner reflects ready-to-finalize.
        fm_text = _fm.unset_field(fm_text, ReviewKey.PHASE)
        new_body = _banner.replace_banner(new_body, _banner.State.READY)
        msg = "review: validator barrier clear → finalize"
  else:
      # Terminal barrier — decide on the COLLECTED body:
      #  - any terminal section still missing (writer pending/errored,
      #    its section never grafted) → HOLD: the round is not done.
      #    Never "clear" a barrier whose terminal writer produced
      #    nothing (Bug 101); keep the Waiting banner so the next tick
      #    re-dispatches the missing writer.
      #  - all present + an unanswered [!question] → hand to the operator.
      #  - all present + no question → clear; the next tick finalizes
      #    (historian-gated). Banner is Waiting-on-finalize, NOT the
      #    pre-approval Ready-to-approve prompt — the doc is already
      #    approved, so State.READY would render a stale approve checkbox.
    terminal_owners = [
        (_flatten(name), sec_id)
        for (name, sec_id, _t, pa, term, _p) in section_writers_full
        if pa and term
    ]
    all_terminals_present = all(
        _body.section_content_for_owner(new_body, owner) is not None
        for owner in terminal_owners
    )
    # guard: terminal section(s) not yet produced — hold, do not clear.
    if not all_terminals_present:
      new_body = _banner.replace_banner(
          new_body, _banner.State.IN_PROCESS, waiting_context=Bucket.TERMINALS,
      )
      msg = "review: terminal barrier hold (section pending)"
    elif _banner._any_unanswered_question(new_body):
      new_body = _banner.replace_banner(new_body, _banner.State.ACTION_NEEDED)
      msg = "review: terminal barrier → action needed"
    else:
      new_body = _banner.replace_banner(
          new_body, _banner.State.IN_PROCESS, waiting_context=Phase.FINALIZE,
      )
      msg = "review: terminal barrier clear → finalize"
  file_path.write_text(fm_text + new_body)
  try:
    decision_sha = _git_ops.commit_mechanical(
        repo, file_path, author=_bot_author(), message=msg,
    )
    summary[JobKey.DECISION_COMMIT_SHA] = decision_sha
  except _git_ops.GitOpsError as exc:
      # guard: a no-op decision (banner already matched) is benign
    # waiver: git CLI vocabulary
    if "nothing to commit" not in str(exc):
      raise
  summary[JobKey.STATUS] = "barrier-collected"
  return summary


def _find_done_job(repo: Path, expert: str, dedup_key: str) -> dict:
  """
  Locate a job by expert name, routing to local or remote queue as appropriate.

  Returns:
    Dict with `status` (`"pending"` / `"done"` / `"missing"`), optional `job_id`,
    and optional `response`, using the same shape for both local and remote routes.
  """
  if "@" in expert:
    return _find_done_job_remote(repo, expert, dedup_key)
  return _find_done_job_local(repo, expert, dedup_key)


def _find_done_job_local(repo: Path, expert: str, dedup_key: str) -> dict:
  """
  Locate a local job for `expert` whose dedup key matches.

  Active jobs (READY present, no DONE) map to `"pending"`.
  Terminal jobs (DONE present) map to `"done"` with response loaded.
  No matching job maps to `"missing"`.

  Returns:
    Dict with `status` (`"pending"` / `"done"` / `"missing"`), optional `job_id`,
    and optional `response`.
  """
  edir = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / expert
  if not edir.exists():
    return {JobKey.STATUS: Outcome.MISSING}
  candidates: list[tuple[float, Path]] = []
  for jdir in edir.iterdir():
    # guard: only job subdirectories hold a request.json
    if not jdir.is_dir():
      continue
    req_file = jdir / JobFile.REQUEST
    # guard: job dir without a request.json carries no dedup key to match
    if not req_file.exists():
      continue
    try:
      req = json.loads(req_file.read_text())
    except (OSError, json.JSONDecodeError):
      continue
    # guard: request belongs to a different dedup key — not this dispatch
    if req.get(JobKey.DEDUP_TRACKER) != dedup_key:
      continue
  # Skip terminal-failure markers in active-search: DEAD is a kill
  # marker, the job is gone. CONSUMED means the consumer has
  # already applied or discarded this job's response — for dedup
  # purposes the job is finished. Treat both as missing so a
  # fresh dispatch can replace them.
    # guard: DEAD is a kill marker — the job is gone, treat as missing
    if (jdir / JobFile.DEAD).exists():
      continue
    # guard: CONSUMED job is finished for dedup — let a fresh dispatch replace it
    if (jdir / Outcome.CONSUMED).exists():
      continue
    candidates.append((req_file.stat().st_mtime, jdir))
  if not candidates:
    return {JobKey.STATUS: Outcome.MISSING}
# Newest matching job wins. There should normally be only one active
# match at a time (dedup_key in dispatch_job prevents fresh creation
# while one is active), but multiple DONE jobs can accumulate before
# cleanup — pick the most recent.
  candidates.sort(reverse=True)
  _mtime, jdir = candidates[0]
  job_id = jdir.name
  if not (jdir / JobFile.DONE).exists():
    return {JobKey.STATUS: JobStatus.PENDING, JobKey.JOB_ID: job_id}
  resp_path = jdir / JobFile.RESPONSE
  response = {}
  if resp_path.exists():
    try:
      response = json.loads(resp_path.read_text())
    except (OSError, json.JSONDecodeError):
      response = {}
  return {JobKey.STATUS: JobStatus.DONE, JobKey.JOB_ID: job_id, JobKey.RESPONSE: response}


def _find_done_job_remote(local_repo: Path, expert_name_raw: str, dedup_key: str) -> dict:
  """
  Locate a cross-repo job by walking the remote-jobs tracker directory.

  Walks `<local_repo>/.experts/.remote-jobs/<label>/<expert>/<id>.json` tracker
  files until one matches `dedup_key`, then calls the core `collect-job` CLI
  against the target repo.

  Returns:
    Dict in the same shape as the local variant: `status`, optional `job_id`,
    and optional `response`.
  """
  expert, repo_key = _parse_expert_name(expert_name_raw)
  try:
    target = _resolve_target_repo(local_repo, repo_key)
  except RuntimeError:
    return {JobKey.STATUS: Outcome.MISSING}
  base = local_repo / JobFile.EXPERTS_DIR / JobFile.REMOTE_JOBS_DIR
  if not base.exists():
    return {JobKey.STATUS: Outcome.MISSING}
# Scan all label dirs (registry key OR basename fallback) for a tracker
# whose dedup_key matches — the local-side label is the dispatcher's
# choice (Task 6's reverse_lookup), not necessarily repo_key.
  for label_dir in base.iterdir():
    # guard: only label subdirectories hold per-expert tracker dirs
    if not label_dir.is_dir():
      continue
    cand_dir = label_dir / expert
    # guard: this label has no tracker dir for the expert
    if not cand_dir.is_dir():
      continue
    for tracker_file in cand_dir.iterdir():
      # guard: only .json tracker files carry a dedup_key to match
      # waiver: filesystem path idiom
      if tracker_file.suffix != ".json":
        continue
      try:
        tracker = json.loads(tracker_file.read_text())
      except (OSError, json.JSONDecodeError):
        continue
      # guard: tracker belongs to a different dispatch — keep scanning
      if tracker.get(JobKey.DEDUP_KEY) != dedup_key:
        continue
      job_id = tracker_file.stem
      try:
        collect = _call_core(CoreCommand.COLLECT_JOB, {
            JobKey.EXPERT: expert, JobKey.JOB_ID: job_id,
        }, target)
      except Exception:
        return {JobKey.STATUS: Outcome.MISSING}
      collect[JobKey.JOB_ID] = job_id
      return collect
  return {JobKey.STATUS: Outcome.MISSING}


def _operator_touched_since_dispatch(
    file_path: Path,
    payload: dict,
    *,
    operator_commit_sha: str | None = None,
) -> bool:
  """
  Return True iff the operator touched the file since the job was dispatched.

  Prefers the operator-sha anchor when both `payload._operator_sha_at_dispatch`
  and the current `operator_commit_sha` are available — anchor equality means
  no operator touch (intervening mechanical/bot commits are transparent).
  Falls back to content-hash comparison for legacy payloads without the anchor.

  Returns:
    True when the operator has committed since the job was dispatched.
  """
  anchor = payload.get(JobKey.OPERATOR_SHA_AT_DISPATCH)
  # guard: anchor approach — both anchor (in payload) and current operator-sha
  # (caller's `chain.last_contentful_sha`) are needed; this path skips bot edits.
  if anchor is not None and operator_commit_sha is not None:
    return anchor != operator_commit_sha
  snap = payload.get(JobKey.FILE_SNAPSHOT_HASH)
  # guard: no snapshot recorded and no anchor → can't detect; assume no-op
  if not snap:
    return False
  return _file_snapshot_hash(file_path) != snap


def _core_consume_job(repo: Path, expert: str, job_id: str, *, dispatched_from: str | None = None) -> None:
  """
  Mark a job as consumed so the next lookup treats it as missing.

  Idempotent. Errors are swallowed — a failed consume means the job
  may be re-applied on the next tick, but that is preferable to aborting
  the per-tick flow. When `dispatched_from` is set, the core CLI also
  cleans up the `.remote-jobs/` tracker on the local side.
  """
  body: dict = {JobKey.EXPERT: expert, JobKey.JOB_ID: job_id}
  if dispatched_from is not None:
    body[JobKey.DISPATCHED_FROM] = dispatched_from
  try:
    _call_core(CoreCommand.CONSUME_JOB, body, repo)
    return
  # Fallback: touch CONSUMED locally so the job is invisible to the next
  # `_find_done_job` lookup. Without this fallback, a transient core-CLI
  # failure leaves the DONE response reachable forever and `_dedup_key`
  # blocks fresh dispatch indefinitely.
  # waiver: function docstring states "Errors are swallowed"; the fallback is intentional best-effort
  except Exception:
    pass
  try:
    local_repo = Path(dispatched_from) if dispatched_from else repo
    jdir = local_repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / expert / job_id
    if jdir.exists():
      (jdir / Outcome.CONSUMED).touch()
  # cross-repo: also touch on the target side if the dispatch
  # crossed repos.
    if dispatched_from is not None:
      target_jdir = repo / JobFile.EXPERTS_DIR / JobFile.JOBS_DIR / expert / job_id
      if target_jdir.exists():
        (target_jdir / Outcome.CONSUMED).touch()
  except OSError:
    pass


def _show_blob(repo: Path, sha: str, path: Path) -> str | None:
  """
  Return the content of `path` at git revision `sha`, or `None` on failure.

  Returns:
    File text at the requested revision, or `None` when the git show fails.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess
  rel = str(path.relative_to(repo)) if path.is_absolute() else str(path)
  out = subprocess.run(
      ["git", "-C", str(repo), "show", f"{sha}:{rel}"],
      check=False, capture_output=True, text=True,
  )
  if out.returncode != 0:
    return None
  return out.stdout


def _phase_of(trailers: dict) -> str:
  """
  Classify a commit by its `Doc-Review-Phase` trailer value.

  Returns:
    One of `"main"` / `"section"` / `"mechanical"` / `"history:append"` /
    `"history:noop"` / `"finalize"` / `""` (operator commit or unrecognised).
  """
  phase, _e, _r = _git_ops.parse_phase_trailer(trailers)
  return phase


def _historian_for_class(class_cfg: dict) -> str:
  """
  Return the historian expert name configured for this review class.

  Returns:
    The configured historian name, or `"historian"` when not declared.
  """
  hw = class_cfg.get(JobKey.EXPERTS, {}).get(Phase.HISTORY) or {}
  if isinstance(hw, dict) and hw.get(JobKey.NAME):
    return hw[JobKey.NAME]
  return Role.HISTORIAN


def _body_content_changed(repo: Path, file_path: Path, commit_sha: str) -> bool:
  """
  Return True iff the contentful body of `file_path` at `commit_sha` differs from its parent.

  "Contentful body" excludes review scaffold: frontmatter, banner callouts, owned
  sections, and `# History`. Only operator-facing prose is compared. When anything
  goes wrong (missing parent, unreadable blob, parse error), conservatively returns
  True so historian dispatches are never silently swallowed.

  Returns:
    True when the substantive body content changed between `commit_sha` and its parent.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess as _subprocess
  parent = _subprocess.run(
      ["git", "-C", str(repo), "rev-parse", f"{commit_sha}^"],
      check=False, capture_output=True, text=True,
  )
  if parent.returncode != 0:
      # No parent — e.g. initial commit. Treat as content change.
    return True
  parent_sha = parent.stdout.strip()
  cur_text = _show_blob(repo, commit_sha, file_path)
  prev_text = _show_blob(repo, parent_sha, file_path)
  if cur_text is None or prev_text is None:
    return True
  try:
      # Compare just the body (post strip of banner / approve line /
      # owned sections / History / system callouts). Frontmatter is
      # intentionally excluded — review_active flips, approved flips,
      # etc. are metadata and not narratable by historian. System
      # callouts (#review/<x>-tagged) are scaffolding the writer adds
      # to ask the operator something; per the functional spec the
      # historian narrates substance, not scaffolding, so callouts
      # are stripped before the comparison.
    _, cur_body = _fm.parse(cur_text)
    _, prev_body = _fm.parse(prev_text)
    # Strip only banner-state callouts (#review/in-process /
    # action-needed / ready). Writer-authored [!question] / [!attention]
    # callouts are SUBSTANCE — historian narrates them ("asked five
    # clarification questions"). Stripping them would suppress historian
    # on every clarification round (Bug 29).
    cur_stripped = _body.strip_banner_callouts(
        _body._strip_owned_meta_and_history(cur_body)
    )
    prev_stripped = _body.strip_banner_callouts(
        _body._strip_owned_meta_and_history(prev_body)
    )
  except Exception:
    return True
  return cur_stripped != prev_stripped


# ----------------------------------------------------------- process_one_file


def _class_for_file(settings: dict, repo: Path, file_path: Path) -> dict | None:
  """
  Find the first review class whose `paths:` glob set matches the given file.

  Returns:
    The matching class config dict, or `None` when no class matches.
  """
  fp = file_path.resolve()
  for class_cfg in review_classes(settings):
    for hit in _iter_class_files(repo, class_cfg.get(JobKey.PATHS) or []):
      if hit.resolve() == fp:
        return class_cfg
  return None


def process_one_file(repo: Path, file_path: Path) -> dict:
  """
  Run the full state-machine pipeline on exactly one file.

  Locates the file's review class, runs the historian pickup pass, computes
  state-machine inputs, decides the action, and applies it. The sole
  operator-facing dispatch entrypoint; invoked once per matching file per
  scan tick by the daemon's md-scan routine.

  Returns:
    Per-file summary dict describing what was done this tick.
  """
  settings = load_settings(repo)
  class_cfg = _class_for_file(settings, repo, file_path)
  if class_cfg is None:
    return {
        JobKey.FILE: str(file_path),
        JobKey.KIND: Outcome.SKIP,
        JobKey.REASON: "no_matching_review_class",
    }
# Spec § historian subsystem: pickup pass runs every tick before
# the state machine evaluates inputs, so any historian responses
# that completed since last tick land in `# History` (and become
# visible to compute_inputs's gates) immediately. Failures inside
# the pickup are surfaced via the per-job summary, never abort
# the tick.
  history_pickup = _pickup_historian_responses(repo, settings, class_cfg, file_path)
  try:
    inputs, context = compute_inputs(repo, class_cfg, file_path)
  except Exception as exc:
    return {
        JobKey.FILE: str(file_path),
        JobKey.ERROR: f"compute_inputs_failed: {exc}",
    }
  action = _sm.decide(inputs)
  summary = apply_action(
      repo, settings, class_cfg, file_path, inputs, action, context,
  )
  if history_pickup.get(JobKey.PICKED_UP, 0) > 0:
    summary[JobKey.HISTORY_PICKUP] = history_pickup
  return summary
