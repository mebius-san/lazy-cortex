#!/usr/bin/env python3

"""
Drop-in `claude` wrapper giving third-party daemons the subscription rate-limit guard.

A standalone daemon replaces the word `claude` in its launch command with the installed copy of
this wrapper (`~/.local/bin/lazy-claude`) and gains two behaviours: a headless call whose own
account has a closed rate-limit window is refused with the distinctive exit code 75 before any
tokens burn, and a headless call that streams JSON feeds the frames it sees back into the
host-local flag, stamped with the caller's account, for every reader under that account.
Interactive sessions pass straight through — the guard never refuses the operator.

The wrapper is self-contained: it imports nothing from the plugin tree and carries its own copy of
the flag contract of `rate_limit_flag.py` — the flag directory, the per-window-and-account record
files, the account-identity resolution, and the reading rules. Windows of another account never
refuse the call; records without an account stay host-global. Unlike the runtime, the wrapper
carries no configuration — it always reads and always writes the flag, all triggers active, with no
warning-utilization threshold — and its writes never raise. Switching a daemon back to the bare
`claude` word is the off switch.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Decision: duplicate the flag contract of `rate_limit_flag.py` here, not import it — install copies
# this single file out of the plugin to a stable host path, where no sibling module is importable

# The contract code a trained daemon reads as "rate limit — skip this tick quietly"; an untrained
# one sees an error, which is honest too. Mirrors BSD sysexits EX_TEMPFAIL.
EXIT_RATE_LIMITED = 75
# BSD sysexits EX_UNAVAILABLE: PATH holds no real `claude` to wrap.
EXIT_NO_CLAUDE = 69
# The literal path contract shared with `rate_limit_flag.py` — the host-local flag directory.
FLAG_REL = "lazycortex/rate-limit"
# Lifetime of a record whose frame carried no reset timestamp — the shortest provider window.
FALLBACK_TTL_SEC = 5 * 3600
# Filename stem for a frame that named no window type.
UNKNOWN_KEY = "unknown"
# Window-type characters accepted into a filename; anything else files as unknown.
_SAFE_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
# The wrapped executable's bare name, looked up on PATH.
_CLAUDE = "claude"
# Argument tokens that mark a headless (non-interactive) invocation.
_HEADLESS_TOKENS = ("-p", "--print")
# Argument token whose value selects the output format.
_OUTPUT_FORMAT_TOKEN = "--output-format"
# The output-format value whose stream this wrapper can read frames from.
_STREAM_JSON = "stream-json"
# Writer label stored on every record this wrapper writes.
_WRITER = "lazy-claude"
# Record field holding the account identity, shared with `rate_limit_flag.py`.
_ACCOUNT_FIELD = "account"
# Prefix opening every diagnostic line this wrapper writes to stderr.
STDERR_PREFIX = "lazy-claude:"


def read_account_identity() -> str:
  """
  Resolve the identity of the account the current process spends tokens under.

  Names the budget a rate-limit window belongs to, so a record written for one account is recognised by
  every reader running under that same account.

  Guarantees:
    - Resolution follows a fixed precedence: an explicit token's digest, then the machine login's account id,
      then a shared unknown bucket — so two processes spending under the same account, wrapper or runtime,
      always agree on the identity string.
    - Never raises: whatever the state of the machine's login record, the call returns an identity.

  Returns:
    A short stable identity string; never empty, never the raw token.
  """

  # Contract:
  # The identity resolves via a fixed precedence — an explicit token, then the machine
  # login's account id, then a shared unknown bucket — so two processes spending under the
  # same account, wrapper or runtime, always resolve to the same identity string on this host.

  # Contract:
  # Resolution NEVER raises: whatever the state of the machine's login record,
  # the call returns an identity.

  # an explicit token is the effective account, whatever the machine login says
  # waiver: external Claude Code environment-variable name, not a domain key
  token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
  if token:
    # surrogateescape round-trips the raw bytes of a non-UTF-8 environment value instead of raising
    # waiver: digest-length literal shared with rate_limit_flag.py, duplicated by the standalone contract
    return "tok-" + hashlib.sha256(token.encode("utf-8", "surrogateescape")).hexdigest()[:12]

  # ambient login: the account id recorded by the Claude CLI's own config
  try:
    # waiver: external Claude Code config path and field names, not internal keys
    cfg = json.loads((Path.home() / ".claude.json").read_text(encoding = "utf-8"))
    # waiver: external Claude Code config field names, not internal keys
    uuid = str((cfg.get("oauthAccount") or {}).get("accountUuid") or "")
  # ValueError covers both a JSON parse failure and a file that is not valid UTF-8; AttributeError
  # covers a config that is not an object; RuntimeError is what `Path.home()` raises when no home
  # directory resolves
  except (OSError, ValueError, AttributeError, RuntimeError):
    uuid = ""

  # a recorded login account names the bucket by its id
  if uuid:
    # waiver: digest-length literal — see above
    return "acc-" + uuid[:12]

  # no token, no login record — every such process shares one bucket
  return UNKNOWN_KEY


def flag_dir() -> Path:
  """
  Return the host-local directory holding one record file per rate-limit window and account.

  Returns:
    Absolute path to the flag directory, which need not exist yet.
  """
  # waiver: environment-variable name, not a domain key
  base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
  return Path(base) / FLAG_REL


def is_raised() -> bool:
  """
  Report whether a rate-limit window of the caller's own account is currently closed on this host.

  Fail-open: an unreadable or malformed record, or one with an unusable reset time, never blocks the
  call — it is reported on stderr and skipped, matching the guarantee `rate_limit_flag.read_live_records` gives
  every other reader.

  Guarantees:
    - Never raises: an unreadable or malformed record, or one whose reset time is present but not a
      number naming a calendar date, is reported on stderr naming the record file and treated as
      absent, and the call still returns a verdict; a record with no reset time is skipped silently.
    - A record raised under a different account identity than the caller's own never gates the call;
      a record carrying no account field gates every caller on this host.

  Returns:
    True while at least one record with an unexpired reset timestamp exists that belongs to the caller's account
    or carries no account.
  """

  # Contract:
  # An unreadable or malformed record, and a record whose reset time is present but unusable
  # (not a number, or not representable as a calendar date), never blocks the call; it is
  # reported on stderr naming the record file and treated as absent instead of raising. A record
  # with no reset time is skipped silently.

  # Contract:
  # A record raised under a different account identity than the caller's own never gates
  # the call; a record carrying no account field gates every caller on this host,
  # whatever account it runs under.

  base = flag_dir()

  # guard: no writer has ever raised the flag on this host
  if not base.is_dir():
    return False
  now = time.time()

  # loop-invariant: the reader's own identity, checked against every record below
  own = read_account_identity()
  try:
    names = sorted(os.listdir(base))
  except OSError as error:
    sys.stderr.write(f"{STDERR_PREFIX} cannot list {base}: {error}\n")
    return False
  for name in names:
    # guard: only record files belong to this contract
    # waiver: filesystem suffix idiom, not a domain key
    if not name.endswith(".json"):
      continue
    try:
      entry = json.loads((base / name).read_text(encoding = "utf-8"))
    # ValueError covers both a JSON parse failure and a file that is not valid UTF-8
    except (OSError, ValueError) as error:
      sys.stderr.write(f"{STDERR_PREFIX} ignoring unreadable record {name}: {error}\n")
      continue

    # guard: a record that is not an object carries no window — reported so a broken writer is visible
    if not isinstance(entry, dict):
      sys.stderr.write(f"{STDERR_PREFIX} ignoring malformed record {name}\n")
      continue
    # waiver: record field name shared with rate_limit_flag.py, duplicated by the standalone contract
    resets = entry.get("resets_at")

    # guard: a record without a reset timestamp holds nothing up
    if resets is None:
      continue

    # guard: a reset that is not a number naming a date cannot be compared with the clock — reported so
    # a broken writer is visible, then skipped
    if not isinstance(resets, (int, float)) or not _is_date(resets):
      sys.stderr.write(f"{STDERR_PREFIX} ignoring record {name}: reset time is not a number naming a date\n")
      continue

    # an expired reset timestamp holds nothing up
    if now >= float(resets):
      continue

    # another account's window says nothing about this caller's budget; a record
    # without the field predates the scoping and stays visible to everyone
    owner = entry.get(_ACCOUNT_FIELD)
    if isinstance(owner, str) and owner and owner != own:
      continue
    return True
  return False


def parse_frames(text: str) -> list[dict]:
  """
  Extract every rate-limit payload carried by a stream-json buffer or line.

  Args:
    text: Raw stream-json output, one or more lines.

  Returns:
    The payload dicts in the order they appeared; empty when the text carries none.
  """
  found: list[dict] = []
  for line in text.splitlines():
    raw = line.strip()

    # the parse is skipped for every line that cannot be the frame this function wants
    # waiver: external Claude Code stream-json field name, not an internal key
    if not raw or "rate_limit_event" not in raw:
      continue
    try:
      frame = json.loads(raw)
    except json.JSONDecodeError:
      continue

    # only rate-limit events carry a payload this wrapper reads
    # waiver: external Claude Code stream-json field name, not an internal key
    if not isinstance(frame, dict) or frame.get("type") != "rate_limit_event":
      continue
    # waiver: external Claude Code stream-json field name, not an internal key
    info = frame.get("rate_limit_info")
    if isinstance(info, dict):
      found.append(info)
  return found


def evaluate_trigger(info: dict) -> str | None:
  """
  Decide whether a rate-limit payload trips the guard.

  All three triggers are permanently active — the wrapper has no configuration.

  Args:
    info: One rate-limit payload as carried by a stream frame.

  Returns:
    The trigger token that fired, or None when the payload is benign.
  """

  # Domain(runtime.job-execution):
  # # Immediate trigger, no warning threshold
  # A daemon with its own configuration can tolerate an early rate-limit warning up to a chosen
  # share of the window before it actually stops. A standalone wrapper substituted for a
  # third-party daemon's own launch command carries no such per-daemon configuration to read a
  # threshold from, so it treats any warning or rejection frame as an immediate trigger instead —
  # trading the daemon's graduated tolerance for a simpler rule that is safe for every caller
  # regardless of what it knows about itself.

  # waiver: external Claude Code stream-json field name, not an internal key
  status = info.get("status")

  # the two provider statuses that close a window
  # waiver: provider status tokens, a fixed external contract
  if status in ("allowed_warning", "rejected"):
    return str(status)

  # spend has crossed into paid overage — an absent field means unknown, never "no"
  # waiver: external Claude Code stream-json field name, not an internal key
  if info.get("isUsingOverage") is True:
    # waiver: trigger token shared with rate_limit_flag.py, duplicated by the standalone contract
    return "overage"
  return None


def save_record(info: dict, trigger: str) -> None:
  """
  Persist one raised window to the host-local flag directory.

  Best-effort: a write failure is reported on stderr and swallowed — the guard must never take
  down the daemon it protects.

  A reset the payload names that cannot be read as a date (for example milliseconds sent as seconds)
  is reported on stderr and treated as absent, so the record carries the fallback expiry instead.

  Guarantees:
    - Never raises: a write failure of any kind is reported on stderr and swallowed instead of
      propagating to the caller.
    - A failed write leaves no temporary file behind in the flag directory.
    - A written record carries the writer's account identity, so it gates every reader running under the
      same account, wrapper or runtime.
    - A record is filed per (window, account) under the same file-name scheme the runtime uses, so two accounts
      raising the same window never overwrite each other's records.
    - A written record always carries a reset time that can be read as a calendar date; a reset the payload
      names that cannot be read as one is reported on stderr and replaced by the fallback expiry, exactly as
      for a payload with no reset.

  Args:
    info: The rate-limit payload that raised the flag.
    trigger: The trigger token that fired for this payload.
  """

  # Contract:
  # A write failure of any kind is reported on stderr and swallowed; this function never raises
  # and never takes down the process that called it.

  # Contract:
  # A failed write leaves no temporary file behind in the shared flag directory.

  # Contract:
  # A written record carries the writer's account identity, so it gates every reader
  # running under the same account, whether that reader is the wrapper or the runtime.

  # Contract:
  # Records are filed per (window, account) under the same file-name scheme the runtime uses,
  # so two accounts raising the same window never overwrite each other's records, and a record
  # the wrapper writes is the same file the runtime would write for that window and account.

  # Contract:
  # A record written here MUST carry a reset time that can be read as a calendar date.
  # A reset the payload names that cannot be read as one (overflow, non-finite, out of range,
  # e.g. milliseconds sent as seconds) is reported on stderr and replaced by the fallback expiry,
  # exactly as for a payload with no reset.

  now = time.time()

  # an overage trigger is bounded by the overage window, every other trigger by the plain one
  # waiver: external Claude Code stream-json field names, not internal keys
  first, second = ("overageResetsAt", "resetsAt") if trigger == "overage" else ("resetsAt", "overageResetsAt")
  resets: int | float | None = None
  for key in (first, second):
    value = info.get(key)
    if isinstance(value, (int, float)):
      resets = value
      break

  # derive the per-window filename, trusting only the known alphabet as a path segment
  # waiver: external Claude Code stream-json field name, not an internal key
  raw_key = info.get("rateLimitType")
  window = raw_key if isinstance(raw_key, str) and raw_key and set(raw_key) <= _SAFE_KEY_CHARS else UNKNOWN_KEY

  # guard: a reset no date can hold (milliseconds sent as seconds, overflow, non-finite) is
  # repaired to absent, so every reader can still format the record it lands on
  if resets is not None and not _is_date(resets):
    sys.stderr.write(f"{STDERR_PREFIX} ignoring reset {resets!r} for {window} — not representable as a date\n")
    resets = None

  # a record born expired protects nothing — the warning is the only clock-skew signal a
  # third-party daemon's host ever emits
  effective = resets if resets is not None else now + FALLBACK_TTL_SEC
  if effective <= now:
    sys.stderr.write(
      f"{STDERR_PREFIX} record for {window} is already expired on write "
      f"(resets_at={effective}, now={now}) — clock skew?\n"
    )

  # the identity is used twice below (record field + filename) and may cost a config read
  account = read_account_identity()

  # field names shared with rate_limit_flag.py, duplicated by the standalone contract
  # waiver: record and stream-json field names, a fixed cross-writer contract
  entry = {
    "resets_at": effective,
    # waiver: external Claude Code stream-json field name, not an internal key
    "status": str(info.get("status") or ""),
    # waiver: external Claude Code stream-json field name, not an internal key
    "is_using_overage": info.get("isUsingOverage") is True,
    "trigger": trigger,
    "writer": _WRITER,
    "written_at": now,
    _ACCOUNT_FIELD: account,
  }
  # noinspection PyBroadException
  try:
    # one file per (window, account), named exactly as rate_limit_flag.py names it — two accounts
    # raising the same window must never overwrite each other's records
    # waiver: filesystem suffix idiom and record-name separator, shared with rate_limit_flag.py
    target = flag_dir() / f"{window}--{account}.json"
    target.parent.mkdir(parents = True, exist_ok = True)

    # atomic replace so a concurrent reader never sees a half-written record
    # waiver: temp-file naming idiom, not a domain constant
    fd, tmp = tempfile.mkstemp(prefix = ".flag.", suffix = ".tmp", dir = str(target.parent))
    # noinspection PyBroadException
    try:
      # waiver: stdlib file-mode idiom
      with os.fdopen(fd, "w", encoding = "utf-8") as fh:
        json.dump(entry, fh, indent = 2)
      os.replace(tmp, target)
    except Exception:
      # best-effort cleanup before surfacing the failure below — nothing on this host ever
      # collects an orphan temp file in the shared flag directory
      try:
        os.unlink(tmp)
      except OSError:
        pass
      raise
  # waiver: the guard must never take down the daemon it protects, whatever the write failure was
  # pylint: disable-next=broad-exception-caught
  except Exception as error:
    sys.stderr.write(f"{STDERR_PREFIX} cannot write rate-limit flag: {error}\n")


def _is_date(value: int | float) -> bool:
  """
  Report whether an epoch-seconds value can be turned into a calendar date.

  Args:
    value: Candidate reset timestamp in epoch seconds.

  Returns:
    True when the value names a representable UTC date; False for an overflowing, non-finite,
    or out-of-range value.
  """
  try:
    datetime.fromtimestamp(float(value), tz = UTC)
  except (OverflowError, ValueError, OSError):
    return False
  return True


def find_real_claude() -> str | None:
  """
  Locate the real `claude` executable by scanning PATH, excluding this wrapper itself.

  Returns:
    Absolute path to the first `claude` on PATH that is not this script, or None when PATH
    holds no other candidate.
  """
  own = Path(sys.argv[0]).resolve()
  # waiver: environment-variable name, not a domain key
  for entry in os.environ.get("PATH", "").split(os.pathsep):
    # guard: an empty PATH entry historically means "current directory" — never a claude home
    if not entry:
      continue
    candidate = Path(entry) / _CLAUDE

    # only an executable file that is not this very wrapper qualifies
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
      continue

    # PATH may list the wrapper's own directory first — never wrap ourselves
    if candidate.resolve() == own:
      continue
    return str(candidate)
  return None


def is_headless(argv: list[str]) -> bool:
  """
  Report whether an argument vector marks a headless `claude -p` / `--print` invocation.

  Args:
    argv: The argument vector after the program name.

  Returns:
    True when a headless token is present.
  """
  return any(token in _HEADLESS_TOKENS for token in argv)


def is_stream_json(argv: list[str]) -> bool:
  """
  Report whether the caller asked for stream-json output.

  Both argument spellings are recognised: the two-token `--output-format stream-json` and the
  single-token `--output-format=stream-json`.

  Args:
    argv: The argument vector after the program name.

  Returns:
    True when the stream-json output format is requested.
  """
  for idx, arg in enumerate(argv):
    if arg == _OUTPUT_FORMAT_TOKEN and idx + 1 < len(argv) and argv[idx + 1] == _STREAM_JSON:
      return True
    if arg == f"{_OUTPUT_FORMAT_TOKEN}={_STREAM_JSON}":
      return True
  return False


def run_streaming(real: str, argv: list[str]) -> int:
  """
  Run a stream-json headless call, forwarding its output while reading rate-limit frames.

  Stdout lines are forwarded verbatim as they arrive, so the caller's own stream parsing is
  unaffected; each line is also offered to the frame reader, and any tripped trigger is recorded.

  Guarantees:
    - Every stdout line reaches the caller unmodified and as soon as it arrives, before
      any rate-limit frame inspection runs on it.

  Args:
    real: Absolute path to the real `claude` executable.
    argv: The argument vector after the program name, forwarded unchanged.

  Returns:
    The child's exit code.
  """

  # Contract:
  # Every stdout line is written to the caller verbatim and immediately, unaffected by
  # the frame inspection that runs after it.

  # stdin, stderr, and the exit code pass through untouched; only stdout is tapped
  with subprocess.Popen([ real, *argv ], stdout = subprocess.PIPE, text = True, encoding = "utf-8") as proc:
    # PIPE above guarantees a stream; the check narrows the Optional for the reader loop
    if proc.stdout is not None:
      # forward each line as it arrives, feeding the flag from the same bytes
      for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        for info in parse_frames(line):
          if (trigger := evaluate_trigger(info)) is not None:
            save_record(info, trigger)
    proc.wait()
    return proc.returncode


def main(argv: list[str]) -> int:
  """
  Dispatch one wrapper invocation: passthrough, refuse, or stream-and-record.

  Guarantees:
    - An interactive (non-headless) invocation always passes straight through with no
      rate-limit check; only a headless call is ever subject to refusal.

  Args:
    argv: The argument vector after the program name.

  Returns:
    The exit code to terminate with; interactive calls never return (the process is replaced).
  """
  real = find_real_claude()

  # guard: no real claude anywhere on PATH — nothing to wrap
  if real is None:
    # waiver: one-off human-facing message
    sys.stderr.write(f"{STDERR_PREFIX} no `claude` executable found on PATH\n")
    return EXIT_NO_CLAUDE

  # Domain(runtime.job-execution):
  # # Guard scope: headless calls only
  # The rate-limit guard protects unattended, automated calls from burning tokens against a
  # closed window — it was never meant to stand between an operator and their own interactive
  # session. An interactive invocation always passes straight through with no check at all; only
  # a headless, non-interactive call is ever subject to refusal, since that is the shape every
  # unattended daemon actually uses to spend tokens on its own.

  # Contract:
  # An interactive (non-headless) invocation always passes straight through with no
  # rate-limit check at all; only a headless call is ever subject to refusal.

  # Interactive session: replace this process outright — no pre-check, no pipe, no TTY breakage.
  # The guard never refuses the operator their own session.
  if not is_headless(argv):
    os.execv(real, [ real, *argv ])

  # guard: headless under a raised flag — refuse before any tokens burn
  if is_raised():
    # waiver: one-off human-facing message
    sys.stderr.write(f"{STDERR_PREFIX} rate-limit flag raised — skipping headless call\n")
    return EXIT_RATE_LIMITED

  # a stream-json caller shares its frames with the host; a text caller just runs
  if is_stream_json(argv):
    return run_streaming(real, argv)
  return subprocess.run([ real, *argv ], check = False).returncode


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
