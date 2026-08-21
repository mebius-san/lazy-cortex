#!/usr/bin/env python3

"""
Drop-in `claude` wrapper giving third-party daemons the subscription rate-limit guard.

A standalone daemon replaces the word `claude` in its launch command with the installed copy of
this wrapper (`~/.local/bin/lazy-claude`) and gains two behaviours: a headless call under a raised
rate-limit flag is refused with the distinctive exit code 75 before any tokens burn, and a headless
call that streams JSON feeds the frames it sees back into the host-local flag for every other
reader. Interactive sessions pass straight through — the guard never refuses the operator.

Self-contained by contract: `lazy-core.install` copies this single file out of the plugin to a
stable host path, so it imports nothing from the plugin tree and duplicates the flag-directory
contract of `rate_limit_flag.py` on purpose. The wrapper carries no configuration: it always reads
and always writes the flag, all triggers active; switching a daemon back to the bare `claude` word
is the off switch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


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


def flag_dir() -> Path:
  """
  Return the host-local directory holding one record file per rate-limit window.

  Returns:
    Absolute path to the flag directory, which need not exist yet.
  """
  # waiver: environment-variable name, not a domain key
  base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
  return Path(base) / FLAG_REL


def is_raised() -> bool:
  """
  Report whether any rate-limit window is currently closed on this host.

  Fail-open: an unreadable or malformed record never blocks the call — it is reported on stderr
  and skipped, matching the guarantee `rate_limit_flag.live` gives every other reader.

  Returns:
    True while at least one record with an unexpired reset timestamp exists.
  """
  base = flag_dir()
  # guard: no writer has ever raised the flag on this host
  if not base.is_dir():
    return False
  now = time.time()
  try:
    names = sorted(os.listdir(base))
  except OSError as e:
    sys.stderr.write(f"lazy-claude: cannot list {base}: {e}\n")
    return False
  for name in names:
    # guard: only record files belong to this contract
    # waiver: filesystem suffix idiom, not a domain key
    if not name.endswith(".json"):
      continue
    try:
      entry = json.loads((base / name).read_text())
    except (OSError, json.JSONDecodeError) as e:
      sys.stderr.write(f"lazy-claude: ignoring unreadable record {name}: {e}\n")
      continue
    # guard: a record that is not an object carries no window — report it like the sibling reader
    if not isinstance(entry, dict):
      sys.stderr.write(f"lazy-claude: ignoring malformed record {name}\n")
      continue
    # waiver: record field name shared with rate_limit_flag.py, duplicated by the standalone contract
    resets = entry.get("resets_at")
    # guard: a live window holds the flag up; anything else is expired or malformed
    if isinstance(resets, (int, float)) and now < float(resets):
      return True
  return False


def frames(text: str) -> list[dict]:
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
    # guard: skip the parse for every line that cannot be the frame this function wants
    # waiver: external Claude Code stream-json field name, not an internal key
    if not raw or "rate_limit_event" not in raw:
      continue
    try:
      frame = json.loads(raw)
    except json.JSONDecodeError:
      continue
    # guard: only rate-limit events carry a payload this wrapper reads
    # waiver: external Claude Code stream-json field name, not an internal key
    if not isinstance(frame, dict) or frame.get("type") != "rate_limit_event":
      continue
    # waiver: external Claude Code stream-json field name, not an internal key
    info = frame.get("rate_limit_info")
    if isinstance(info, dict):
      found.append(info)
  return found


def triggered(info: dict) -> str | None:
  """
  Decide whether a rate-limit payload trips the guard.

  All three triggers are permanently active — the wrapper has no configuration.

  Args:
    info: One rate-limit payload as carried by a stream frame.

  Returns:
    The trigger token that fired, or None when the payload is benign.
  """
  # waiver: external Claude Code stream-json field name, not an internal key
  status = info.get("status")
  # guard: the two provider statuses that close a window
  # waiver: provider status tokens, a fixed external contract
  if status in ("allowed_warning", "rejected"):
    return str(status)
  # guard: spend has crossed into paid overage — an absent field means unknown, never "no"
  # waiver: external Claude Code stream-json field name, not an internal key
  if info.get("isUsingOverage") is True:
    # waiver: trigger token shared with rate_limit_flag.py, duplicated by the standalone contract
    return "overage"
  return None


def record(info: dict, trigger: str) -> None:
  """
  Persist one raised window to the host-local flag directory.

  Best-effort: a write failure is reported on stderr and swallowed — the guard must never take
  down the daemon it protects.

  Args:
    info: The rate-limit payload that raised the flag.
    trigger: The trigger token that fired for this payload.
  """
  now = time.time()
  # an overage trigger is bounded by the overage window, every other trigger by the plain one
  # waiver: external Claude Code stream-json field names, not internal keys
  first, second = ("overageResetsAt", "resetsAt") if trigger == "overage" else ("resetsAt", "overageResetsAt")
  resets: float | None = None
  for key in (first, second):
    value = info.get(key)
    if isinstance(value, (int, float)):
      resets = float(value)
      break

  # derive the per-window filename, trusting only the known alphabet as a path segment
  # waiver: external Claude Code stream-json field name, not an internal key
  raw_key = info.get("rateLimitType")
  window = raw_key if isinstance(raw_key, str) and raw_key and set(raw_key) <= _SAFE_KEY_CHARS else UNKNOWN_KEY

  # a record born expired protects nothing — the warning is the only clock-skew signal a
  # third-party daemon's host ever emits
  effective = resets if resets is not None else now + FALLBACK_TTL_SEC
  if effective <= now:
    sys.stderr.write(
      f"lazy-claude: record for {window} is already expired on write "
      f"(resets_at={effective}, now={now}) — clock skew?\n"
    )

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
  }
  try:
    target = flag_dir() / f"{window}.json"
    target.parent.mkdir(parents = True, exist_ok = True)
    # atomic replace so a concurrent reader never sees a half-written record
    # waiver: temp-file naming idiom, not a domain constant
    fd, tmp = tempfile.mkstemp(prefix = ".flag.", suffix = ".tmp", dir = str(target.parent))
    try:
      # waiver: stdlib file-mode idiom
      with os.fdopen(fd, "w") as fh:
        json.dump(entry, fh, indent = 2)
      os.replace(tmp, target)
    except OSError:
      # best-effort cleanup of the orphan temp file before surfacing the failure below
      try:
        os.unlink(tmp)
      except OSError:
        pass
      raise
  except OSError as e:
    sys.stderr.write(f"lazy-claude: cannot write rate-limit flag: {e}\n")


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
    # guard: only an executable file that is not this very wrapper qualifies
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
      continue
    # guard: PATH may list the wrapper's own directory first — never wrap ourselves
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
  return any(a in _HEADLESS_TOKENS for a in argv)


def wants_stream_json(argv: list[str]) -> bool:
  """
  Report whether the caller asked for stream-json output.

  Both argument spellings are recognised: the two-token `--output-format stream-json` and the
  single-token `--output-format=stream-json`.

  Args:
    argv: The argument vector after the program name.

  Returns:
    True when the stream-json output format is requested.
  """
  for i, arg in enumerate(argv):
    if arg == _OUTPUT_FORMAT_TOKEN and i + 1 < len(argv) and argv[i + 1] == _STREAM_JSON:
      return True
    if arg == f"{_OUTPUT_FORMAT_TOKEN}={_STREAM_JSON}":
      return True
  return False


def run_streaming(real: str, argv: list[str]) -> int:
  """
  Run a stream-json headless call, forwarding its output while reading rate-limit frames.

  Stdout lines are forwarded verbatim as they arrive, so the caller's own stream parsing is
  unaffected; each line is also offered to the frame reader, and any tripped trigger is recorded.

  Args:
    real: Absolute path to the real `claude` executable.
    argv: The argument vector after the program name, forwarded unchanged.

  Returns:
    The child's exit code.
  """
  # stdin, stderr, and the exit code pass through untouched; only stdout is tapped
  with subprocess.Popen([ real, *argv ], stdout = subprocess.PIPE, text = True) as proc:
    # guard: PIPE above guarantees a stream; the check narrows the Optional for the reader loop
    if proc.stdout is not None:
      # forward each line as it arrives, feeding the flag from the same bytes
      for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        for info in frames(line):
          trigger = triggered(info)
          if trigger is not None:
            record(info, trigger)
    proc.wait()
    return proc.returncode


def main(argv: list[str]) -> int:
  """
  Dispatch one wrapper invocation: passthrough, refuse, or stream-and-record.

  Args:
    argv: The argument vector after the program name.

  Returns:
    The exit code to terminate with; interactive calls never return (the process is replaced).
  """
  real = find_real_claude()
  # guard: no real claude anywhere on PATH — nothing to wrap
  if real is None:
    # waiver: one-off human-facing message
    sys.stderr.write("lazy-claude: no `claude` executable found on PATH\n")
    return EXIT_NO_CLAUDE

  # Interactive session: replace this process outright — no pre-check, no pipe, no TTY breakage.
  # The guard never refuses the operator their own session.
  if not is_headless(argv):
    os.execv(real, [ real, *argv ])

  # guard: headless under a raised flag — refuse before any tokens burn
  if is_raised():
    # waiver: one-off human-facing message
    sys.stderr.write("lazy-claude: rate-limit flag raised — skipping headless call\n")
    return EXIT_RATE_LIMITED

  # a stream-json caller shares its frames with the host; a text caller just runs
  if wants_stream_json(argv):
    return run_streaming(real, argv)
  return subprocess.run([ real, *argv ], check = False).returncode


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
