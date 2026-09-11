"""
Host-local subscription-rate-limit flag shared by every token-burning process on this machine.

The flag lives outside any repository, so a daemon in one checkout, a daemon in another, and the
`lazy-claude` wrapper in a third-party repository all observe the same windows. One file per
rate-limit window keeps writers of different windows from ever contending; two writers of the same
window race harmlessly, since both describe the same window.

Every read failure is fail-open: an unreadable or malformed record is treated as not raised and
reported on stderr, never raised as an exception into the caller's flow.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from constants import DaemonKey, RateLimitGuardKey, RateLimitRecordKey, RateLimitTrigger

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The literal path contract between every writer and reader on this host — daemons in any
# checkout, and the `lazy-claude` wrapper in repositories that know nothing about lazycortex.
FLAG_REL = "lazycortex/rate-limit"
# Warning-trigger stop threshold shipped as the default: a warning frame halts only at or
# above this share of the window (operator decision, 2026-08-19).
WARNING_THRESHOLD_DEFAULT = 0.9

# The shortest window the provider enforces, used as the lifetime of a record whose frame
# carried no reset timestamp at all.
FALLBACK_TTL_SEC = 5 * 3600
# Filename stem for a frame that named no window type.
UNKNOWN_KEY = "unknown"
# Window-type characters accepted into a filename; anything else is filed as unknown rather
# than trusted as a path segment.
_SAFE_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def account_identity() -> str:
  """
  Resolve the identity of the account the current process spends tokens under.

  Scopes rate-limit flag records to the account currently spending tokens, so a record raised
  under one account cannot gate a different account sharing the same host.

  Guarantees:
    - Resolution follows a fixed precedence: an explicit token's digest, then the machine
      login's account id, then a shared unknown bucket for a process with neither — so two
      processes spending under the same account always agree on the identity string.

  Returns:
    A short stable identity string; never empty, never the raw token.
  """

  # Contract:
  # The identity resolves via a fixed precedence — an explicit token, then the machine
  # login's account id, then a shared unknown bucket — so two processes spending under the
  # same account always resolve to the same identity string on this host.

  # Domain(runtime.job-execution):
  # # Per-account rate-limit scoping
  # Daemons on one host can spend tokens under different accounts, and each account has its own
  # usage windows, so a window raised by one account must not gate a process spending under a
  # different account. The account identity used to scope a window is the effective credential
  # the spending process carries: the digest of an exported token when one is set, else the id of
  # the machine login's account, else a shared bucket for a process with neither. A record written
  # before this scoping existed carries no account identity and stays host-global, gating every
  # process on the host regardless of the account it spends under.

  # an explicit token is the effective account, whatever the machine login says
  token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
  if token:
    # waiver: digest-length literal — 12 hex chars are ample for a per-host account set
    return "tok-" + hashlib.sha256(token.encode()).hexdigest()[:12]

  # ambient login: the account id recorded by the Claude CLI's own config
  try:
    # waiver: external Claude Code config path and field names, not internal keys
    cfg = json.loads((Path.home() / ".claude.json").read_text())
    uuid = str((cfg.get("oauthAccount") or {}).get("accountUuid") or "")
  except (OSError, json.JSONDecodeError):
    uuid = ""
  if uuid:
    # waiver: digest-length literal — see above
    return "acc-" + uuid[:12]

  # no token, no login record — every such process shares one bucket
  return UNKNOWN_KEY


def flag_dir() -> Path:
  """
  Return the host-local directory holding one record file per rate-limit window.

  Returns:
    Absolute path to the flag directory, which need not exist yet.
  """

  # Domain(runtime.job-execution):
  # # Host-wide rate-limit window flag
  # The rate-limit guard keeps one shared, host-local flag directory rather than a per-repository
  # or per-process one. A daemon running out of one checkout, a daemon running out of a different
  # checkout, and a wrapper script in a third-party repository that knows nothing about this
  # project all read and write the same directory, so a window closed by any one of them is seen
  # as closed by every other token-burning process sharing the host and spending under the same
  # account, while a record written before per-account scoping existed stays visible to every
  # process on the host regardless of account.

  # waiver: environment-variable name, not a domain key
  base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
  return Path(base) / FLAG_REL


def config(daemon: dict) -> dict:
  """
  Resolve the guard configuration from a `daemon` settings section.

  Every trigger defaults to enabled and the warning threshold to its shipped default, so a
  section predating the guard — or one a migration has not reached — protects rather than
  exposes the subscription.

  Guarantees:
    - Every guard key defaults to its protecting value when the settings section omits it:
      every trigger enabled, and the warning threshold at its shipped default.

  Args:
    daemon: The parsed `daemon` section of `lazy.settings.json`.

  Returns:
    A dict carrying every guard key with its effective value — the boolean triggers plus the
    float `warning_utilization_threshold`.
  """

  # Contract:
  # Every guard key MUST default to its protecting value — triggers enabled, threshold at
  # `WARNING_THRESHOLD_DEFAULT` — whenever the settings section omits it, so an unconfigured
  # or not-yet-migrated project is guarded exactly as a configured one would be.

  # Domain(runtime.job-execution):
  # # Guard defaults protect, never expose
  # A settings section that predates this guard, or one a migration has not yet reached, carries
  # no opinion on any of these keys — and a missing opinion is read as the safest one rather than
  # the loosest. Every trigger defaults to enabled and the warning threshold to its shipped value,
  # so an unconfigured project stops spending on a raised window exactly as a configured one
  # would, instead of silently running unguarded until an operator opts in.

  # resolve the guard block, defaulting every key toward protecting the subscription
  raw = daemon.get(DaemonKey.RATE_LIMIT_GUARD)
  block = raw if isinstance(raw, dict) else {}
  return {
    RateLimitGuardKey.ENABLED:            bool(block.get(RateLimitGuardKey.ENABLED, True)),
    RateLimitGuardKey.ON_ALLOWED_WARNING: bool(block.get(RateLimitGuardKey.ON_ALLOWED_WARNING, True)),
    RateLimitGuardKey.ON_REJECTED:        bool(block.get(RateLimitGuardKey.ON_REJECTED, True)),
    RateLimitGuardKey.ON_OVERAGE:         bool(block.get(RateLimitGuardKey.ON_OVERAGE, True)),
    RateLimitGuardKey.WARNING_UTILIZATION_THRESHOLD:
        float(block.get(RateLimitGuardKey.WARNING_UTILIZATION_THRESHOLD, WARNING_THRESHOLD_DEFAULT)),
  }


def frames(stdout: str) -> list[dict]:
  """
  Extract every rate-limit payload carried by a stream-json stdout buffer.

  Guarantees:
    - A line that fails to parse, or whose payload is not a rate-limit event, is skipped
      rather than raised, so extraction never aborts on one malformed line.

  Args:
    stdout: Raw stdout produced by a `claude -p --output-format stream-json` invocation.

  Returns:
    The payload dicts in the order they appeared; empty when the buffer carries none.
  """

  # Contract:
  # A line that is not valid JSON, or whose payload is not a rate-limit event object, is
  # skipped rather than raised — extraction never aborts on one malformed line.

  found: list[dict] = []
  for line in stdout.splitlines():
    raw = line.strip()
    # guard: skip the parse for every line that cannot be the frame this function wants —
    # a transcript is megabytes and only these few lines carry the marker
    # waiver: external Claude Code stream-json field name, not an internal key
    if not raw or "rate_limit_event" not in raw:
      continue
    try:
      frame = json.loads(raw)
    except json.JSONDecodeError:
      continue
    # guard: only rate-limit events carry a payload this module reads
    # waiver: external Claude Code stream-json field name, not an internal key
    if not isinstance(frame, dict) or frame.get("type") != "rate_limit_event":
      continue
    # waiver: external Claude Code stream-json field name, not an internal key
    info = frame.get("rate_limit_info")
    # guard: the event carried no payload object to read
    if not isinstance(info, dict):
      continue
    found.append(info)
  return found


def triggered(info: dict, cfg: dict) -> str | None:
  """
  Decide whether a rate-limit payload trips the guard under the given configuration.

  Guarantees:
    - A trigger disabled in `cfg` is never reported as fired, regardless of the payload's contents.

  Args:
    info: One rate-limit payload as carried by a stream frame.
    cfg: The effective guard configuration, as returned by `config`.

  Returns:
    The trigger token that fired, or None when the payload is benign or its trigger is disabled.
  """

  # Contract:
  # A trigger disabled in the configuration MUST NEVER be reported as fired, regardless of the
  # payload's contents; only a trigger explicitly enabled in `cfg` can produce a non-None result.

  # waiver: external Claude Code stream-json field name, not an internal key
  status = info.get("status")

  # Domain(runtime.job-execution):
  # # Warning-trigger stop threshold
  # The provider marks a frame as an allowed warning long before the window is actually
  # exhausted, so treating every such frame as a stop signal would halt work far earlier than
  # necessary. The guard instead stops only once the measured utilization reaches a configured
  # share of the window, letting work continue through the early portion of a warning window and
  # stopping only as the window's true exhaustion approaches.

  # guard: a warning stops the daemon only at a measured utilization at or above the
  # threshold — the provider marks frames `allowed_warning` long before exhaustion, and a
  # frame with no reading never stops (unknown is not at-threshold)
  if status == RateLimitTrigger.ALLOWED_WARNING and cfg.get(RateLimitGuardKey.ON_ALLOWED_WARNING, True):
    # waiver: external Claude Code stream-json field name, not an internal key
    utilization = info.get("utilization")
    threshold = float(cfg.get(RateLimitGuardKey.WARNING_UTILIZATION_THRESHOLD, WARNING_THRESHOLD_DEFAULT))
    if isinstance(utilization, (int, float)) and float(utilization) >= threshold:
      return RateLimitTrigger.ALLOWED_WARNING
    return None
  # guard: the window is already closed
  if status == RateLimitTrigger.REJECTED and cfg.get(RateLimitGuardKey.ON_REJECTED, True):
    return RateLimitTrigger.REJECTED
  # guard: spend has crossed into paid overage — an absent field means unknown, never "no"
  # waiver: external Claude Code stream-json field name, not an internal key
  if info.get("isUsingOverage") is True and cfg.get(RateLimitGuardKey.ON_OVERAGE, True):
    return RateLimitTrigger.OVERAGE
  return None


def record(info: dict, trigger: str, *, writer: str) -> Path:
  """
  Persist one raised window to the host-local flag directory.

  A record whose window has already reopened by the time it lands is written anyway and reported
  on stderr; readers ignore it, so a clock skew degrades to no protection rather than to a
  permanent stop.

  Guarantees:
    - A written record stays visible to every reader running under the same account identity as
      the writer, until the window's reset time passes, regardless of which process or checkout
      wrote it.
    - A legacy record carrying no account field stays visible to every reader on this host.

  Args:
    info: The rate-limit payload that raised the flag.
    trigger: The trigger token that fired for this payload.
    writer: Label identifying the writing process, stored for operator diagnosis.

  Returns:
    Path to the record file written.
  """

  # Contract:
  # A record written here MUST become visible to every reader running under the same account
  # identity as the writer, and remains visible until the window's reset time passes, regardless
  # of which process or checkout wrote it. A legacy record carrying no account field stays
  # visible to every reader on this host, whatever account it runs under.

  # Domain(runtime.job-execution):
  # # Fallback expiry for a window with no reported reset
  # Not every rate-limit frame names when its window reopens. When one does not, the raised flag
  # still needs a lifetime, so it is bounded by the shortest window the provider is known to
  # enforce rather than left open-ended — a record that outlives its true window merely blocks
  # work a little longer than necessary, while a record with no expiry at all would block it
  # forever.

  now = time.time()
  # the identity is used twice below (record field + filename) and may cost a config read
  account = account_identity()
  # a frame carrying no reset timestamp still bounds the record — by the shortest window
  resets = _resets_at(info, trigger)
  effective = resets if resets is not None else now + FALLBACK_TTL_SEC
  entry = {
    RateLimitRecordKey.RESETS_AT:        effective,
    # waiver: external Claude Code stream-json field name, not an internal key
    RateLimitRecordKey.STATUS:           str(info.get("status") or ""),
    # waiver: external Claude Code stream-json field name, not an internal key
    RateLimitRecordKey.IS_USING_OVERAGE: info.get("isUsingOverage") is True,
    RateLimitRecordKey.TRIGGER:          trigger,
    RateLimitRecordKey.WRITER:           writer,
    RateLimitRecordKey.WRITTEN_AT:       now,
    RateLimitRecordKey.ACCOUNT:          account,
  }
  # a record born expired protects nothing — say so where the operator will see it
  if effective <= now:
    sys.stderr.write(
      f"rate-limit flag: record for {_window_key(info)} is already expired on write "
      f"(resets_at={effective}, now={now}) — clock skew?\n"
    )

  # one file per (window, account), in the directory every reader on this host watches —
  # two accounts raising the same window must never overwrite each other's records
  # waiver: filesystem suffix idiom, not a domain key
  target = flag_dir() / f"{_window_key(info)}--{account}.json"
  target.parent.mkdir(parents = True, exist_ok = True)

  # atomic replace so a concurrent reader never sees a half-written record
  # waiver: temp-file naming idiom, not a domain constant
  fd, tmp = tempfile.mkstemp(prefix = ".flag.", suffix = ".tmp", dir = str(target.parent))
  # noinspection PyBroadException
  try:
    # waiver: stdlib file-mode idiom
    with os.fdopen(fd, "w") as fh:
      json.dump(entry, fh, indent = 2)
    os.replace(tmp, target)
  except Exception:
    # best-effort cleanup before re-raising — nothing on this host ever collects an orphan
    # temp file in the shared flag directory
    try:
      os.unlink(tmp)
    except OSError:
      pass
    raise
  return target


def live() -> list[dict]:
  """
  Read every record whose window has not yet reopened.

  Guarantees:
    - An unreadable, malformed, or non-object record is reported on stderr and treated as not raised.
    - A read failure never reaches the caller as an exception.
    - A record whose window has already reopened is excluded, regardless of when it was written.
    - A record raised under a different account identity than the caller's own is excluded;
      a legacy record with no account field stays visible to every reader on this host.

  Returns:
    The unexpired records; empty when nothing is raised, the directory is absent, or every
    record on disk is expired or unreadable.
  """

  # Contract:
  # Every read path treats an unreadable, malformed, or non-object record as NOT raised: the
  # condition is reported on stderr and the read continues. A read failure NEVER propagates as
  # an exception into the caller's flow.

  # Contract:
  # A record MUST stop being reported as raised once its window's reset time passes; expiry
  # alone releases every caller blocked on it, with no action required from any writer.

  # Contract:
  # A record raised under a different account identity than the caller's own is excluded from
  # the result; a legacy record carrying no account field stays visible to every reader on
  # this host, whatever account it runs under.

  # Domain(runtime.job-execution):
  # # Fail-open reading of the rate-limit flag
  # The flag exists to keep automated work from overrunning the operator's subscription, not to
  # act as a hard security boundary. When a record cannot be trusted — missing, unreadable, or
  # malformed — the guard treats the affected window as not raised rather than refusing to
  # proceed, so a broken or corrupted flag degrades to no protection instead of leaving every
  # process on the host stuck waiting on a signal it can no longer read.

  base = flag_dir()
  # guard: no writer has ever raised the flag on this host
  if not base.is_dir():
    return []
  now = time.time()
  # loop-invariant: the reader's own identity, checked against every record below
  own = account_identity()
  raised: list[dict] = []
  try:
    names = sorted(os.listdir(base))
  except OSError as e:
    sys.stderr.write(f"rate-limit flag: cannot list {base}: {e}\n")
    return []
  for name in names:
    # guard: only record files belong to this contract
    # waiver: filesystem suffix idiom, not a domain key
    if not name.endswith(".json"):
      continue
    try:
      entry = json.loads((base / name).read_text())
    except (OSError, json.JSONDecodeError) as e:
      sys.stderr.write(f"rate-limit flag: ignoring unreadable record {name}: {e}\n")
      continue
    # guard: a record that is not an object cannot carry a window
    if not isinstance(entry, dict):
      sys.stderr.write(f"rate-limit flag: ignoring malformed record {name}\n")
      continue
    resets = entry.get(RateLimitRecordKey.RESETS_AT)
    # guard: no usable reset timestamp, or the window has already reopened
    if not isinstance(resets, (int, float)) or now >= float(resets):
      continue
    owner = entry.get(RateLimitRecordKey.ACCOUNT)
    # guard: another account's window says nothing about this reader's budget; a record
    # without the field predates the scoping and stays visible to everyone
    if isinstance(owner, str) and owner and owner != own:
      continue
    raised.append(entry)
  return raised


def is_raised() -> bool:
  """
  Report whether any rate-limit window is currently closed on this host.

  Returns:
    True while at least one unexpired record exists.
  """
  return bool(live())


def resets_at() -> float | None:
  """
  Report when the last currently-closed window reopens.

  Returns:
    The largest reset timestamp across unexpired records, or None when nothing is raised.
  """
  raised = live()
  # guard: nothing raised — there is no reopening to wait for
  if not raised:
    return None
  return max(float(e[RateLimitRecordKey.RESETS_AT]) for e in raised)


def _window_key(info: dict) -> str:
  """
  Derive the record filename stem naming the window a payload describes.

  Args:
    info: One rate-limit payload as carried by a stream frame.

  Returns:
    The window type when the payload names one safe to use as a filename, else the unknown stem.
  """
  # waiver: external Claude Code stream-json field name, not an internal key
  raw = info.get("rateLimitType")
  # guard: absent or non-string window type files under the shared unknown stem
  if not isinstance(raw, str) or not raw:
    return UNKNOWN_KEY
  # a provider-supplied string becomes a path segment here — accept only the known alphabet
  if not set(raw) <= _SAFE_KEY_CHARS:
    return UNKNOWN_KEY
  return raw


def _resets_at(info: dict, trigger: str) -> float | None:
  """
  Pick the reset timestamp that describes the window the given trigger closed.

  Args:
    info: One rate-limit payload as carried by a stream frame.
    trigger: The trigger token that fired for this payload.

  Returns:
    The reset timestamp in epoch seconds, or None when the payload carried neither field.
  """
  # waiver: external Claude Code stream-json field name, not an internal key
  window = info.get("resetsAt")
  # waiver: external Claude Code stream-json field name, not an internal key
  overage = info.get("overageResetsAt")

  # Domain(runtime.job-execution):
  # # Two independent reset clocks
  # The provider tracks a plain rate-limit window and a paid-overage window as two separate
  # clocks, each closing and reopening on its own schedule. Which one actually describes the
  # block that just occurred depends on which trigger fired: an overage block is bounded by the
  # overage window reopening, while every other block is bounded by the plain window reopening.

  # an overage trigger is bounded by the overage window, every other trigger by the plain one
  first, second = (overage, window) if trigger == RateLimitTrigger.OVERAGE else (window, overage)
  for value in (first, second):
    # guard: keep the first field that actually carried a number
    if isinstance(value, (int, float)):
      return float(value)
  return None
