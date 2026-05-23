"""
Minimal cron parser for the lazycortex-core schedule routine type.

Standard 5-field POSIX-cron format:
    minute hour day month dow
       0-59  0-23 1-31  1-12 0-6 (Sun=0..Sat=6)

Per field, supported syntax:
    *               any value in range
    N               literal value
    N-M             inclusive range
    */S             step from field minimum
    N-M/S           ranged step
    a,b,c           list of any of the above

Field name aliases (JAN, MON, etc.) are NOT supported in v1 — numeric only.

Day / day-of-week semantics: when BOTH fields are restricted (not full `*`),
this implementation uses AND, not POSIX cron's OR. Most common patterns
(daily-at-9, every-N-hours, weekly-monday) only restrict one of the two,
so the deviation rarely matters; the wizard warns on the both-restricted case.

Stdlib only — no croniter dep so the daemon stays portable across systems
with bare `python3`.
"""
from __future__ import annotations
from datetime import datetime, timedelta


class CronError(ValueError):
  """
  Raised for unparseable cron expressions or impossible specs.
  """


_FIELD_BOUNDS = [
  (0, 59),  # minute
  (0, 23),  # hour
  (1, 31),  # day
  (1, 12),  # month
  (0, 6),   # day of week (Sun=0..Sat=6)
]


def _parse_field(spec: str, lo: int, hi: int) -> set[int]:
  """
  Expand one cron field into the set of integer values it matches.

  Args:
    spec: Raw field text from the cron expression (e.g. `*`, `5`, `1-10`, `*/15`, `1-10/2`, `1,3,5`).
    lo: Inclusive lower bound for valid values in this field.
    hi: Inclusive upper bound for valid values in this field.

  Returns:
    The set of every integer in `[lo, hi]` that satisfies the field expression.

  Raises:
    CronError: If the field is syntactically invalid, contains an out-of-range value,
      uses an inverted range, has a non-positive step, or expands to the empty set.
  """
  out: set[int] = set()
  # walk the comma-separated pieces; each piece independently contributes values to the union
  for piece in spec.split(","):
    piece = piece.strip()
    # guard: empty piece is a syntax error
    if not piece:
      raise CronError(f"empty piece in field {spec!r}")
    # split off the optional `/step` suffix before parsing the base range
    if "/" in piece:
      base, step_str = piece.split("/", 1)
      try:
        step = int(step_str)
      except ValueError:
        raise CronError(f"bad step in {piece!r}")
      # guard: step must be a positive integer
      if step <= 0:
        raise CronError(f"step must be > 0 in {piece!r}")
    else:
      base, step = piece, 1

    # resolve the base into a [start, end] interval
    if base == "*":
      start, end = lo, hi
    elif "-" in base:
      try:
        a, b = (int(x) for x in base.split("-", 1))
      except ValueError:
        raise CronError(f"bad range in {piece!r}")
      start, end = a, b
    else:
      try:
        v = int(base)
      except ValueError:
        raise CronError(f"bad value in {piece!r}")
      start, end = v, v

    # guard: interval must lie inside the field's allowed range
    if start < lo or end > hi:
      raise CronError(f"value out of range [{lo},{hi}] in {piece!r}")
    # guard: inverted intervals (start > end) are rejected
    if start > end:
      raise CronError(f"start > end in {piece!r}")

    out.update(range(start, end + 1, step))

  # guard: a field that expands to no values is unsatisfiable
  if not out:
    raise CronError(f"empty field {spec!r}")
  return out


def parse(cron_str: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
  """
  Parse a 5-field cron expression into per-field value sets.

  Args:
    cron_str: Full cron expression with five whitespace-separated fields
      (minute, hour, day, month, day-of-week).

  Returns:
    Tuple of five sets — minute, hour, day, month, day-of-week — each holding every
    integer at which the corresponding field fires.

  Raises:
    CronError: If the expression does not contain exactly five fields, or if any
      individual field fails to parse.
  """
  parts = cron_str.split()
  # guard: must have exactly five whitespace-separated fields
  if len(parts) != 5:
    raise CronError(f"expected 5 fields, got {len(parts)}: {cron_str!r}")
  fields = []
  for spec, (lo, hi) in zip(parts, _FIELD_BOUNDS):
    fields.append(_parse_field(spec, lo, hi))
  return tuple(fields)


def _python_weekday_to_cron(wd: int) -> int:
  """
  Convert a Python `datetime.weekday()` value to the cron day-of-week convention.

  Args:
    wd: Weekday in Python's convention where Monday is 0 and Sunday is 6.

  Returns:
    The same day expressed in cron's convention where Sunday is 0 and Saturday is 6.
  """
  # datetime.weekday(): Mon=0..Sun=6. cron: Sun=0..Sat=6.
  return (wd + 1) % 7


def matches(spec, dt: datetime) -> bool:
  """
  Report whether a given moment satisfies a parsed cron specification.

  Args:
    spec: Tuple of five value sets as returned by `parse` (minute, hour, day, month, dow).
    dt: Moment in time to test against the specification.

  Returns:
    True when every field of `spec` contains the corresponding component of `dt`, false otherwise.
  """
  minute, hour, day, month, dow = spec
  return (
    dt.minute in minute and
    dt.hour in hour and
    dt.day in day and
    dt.month in month and
    _python_weekday_to_cron(dt.weekday()) in dow
  )


def next_fire(spec, after_dt: datetime) -> datetime:
  """
  Find the next moment strictly after a reference time at which the cron spec fires.

  Args:
    spec: Tuple of five value sets as returned by `parse`.
    after_dt: Reference moment; the result is strictly greater than this value.

  Returns:
    The next datetime at which `spec` fires, with second and microsecond zeroed.

  Raises:
    CronError: If no firing moment exists within four years of the reference time,
      indicating the specification is unsatisfiable (e.g. February 30).
  """
  # advance to the next whole minute (cron's resolution) before scanning
  cur = after_dt.replace(second = 0, microsecond = 0) + timedelta(minutes = 1)
  end = after_dt + timedelta(days = 4 * 366)
  # bounded linear scan at minute granularity; four years covers every valid 5-field pattern
  while cur < end:
    if matches(spec, cur):
      return cur
    cur += timedelta(minutes = 1)
  raise CronError("no fire within 4 years; cron spec is unsatisfiable")


def due_since(spec, last_run: datetime, now: datetime) -> bool:
  """
  Report whether a cron spec has any firing boundary in the half-open interval `(last_run, now]`.

  Implements a skip-on-miss policy: multiple missed boundaries collapse to a single True,
  so the routine fires once on the next tick rather than once per missed boundary.

  Args:
    spec: Tuple of five value sets as returned by `parse`.
    last_run: Upper-exclusive lower bound of the interval — typically the previous fire time.
    now: Inclusive upper bound of the interval — typically the current moment.

  Returns:
    True if at least one cron firing falls in `(last_run, now]`, false otherwise.
  """
  # guard: degenerate interval — nothing can be due when the window is empty or inverted
  if last_run >= now:
    return False
  return next_fire(spec, last_run) <= now
