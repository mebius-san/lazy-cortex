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

from datetime import UTC, datetime, timedelta

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


CronSpec = tuple[set[int], set[int], set[int], set[int], set[int]]

# the scheduler's own search window: how far past the reference moment the next fire is looked for
# waiver: inline numeric literals (years and the longest year in days), not domain constants
DEFAULT_HORIZON_DAYS = 4 * 366

# one full calendar cycle: every pairing of a weekday with a date, 29 February included, comes round
# once in any 28 years that hold no century year without a leap day
# waiver: inline numeric literals (years and the longest year in days), not domain constants
CYCLE_HORIZON_DAYS = 28 * 366

# a fixed start for a search over one full calendar cycle; the cycle it opens ends before 2100, the
# nearest century year without a leap day
# waiver: inline numeric literals (a calendar date), not domain constants
CYCLE_START = datetime(2000, 1, 1, tzinfo = UTC)

# the longest year in days, used to word a search window in years
_DAYS_PER_LONG_YEAR = 366


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
    # waiver: the loop variable is deliberately rebound — each field is normalised in place before parsing
    piece = piece.strip()  # noqa: PLW2901

    # guard: empty piece is a syntax error
    if not piece:
      raise CronError(f"empty piece in field {spec!r}")

    # split off the optional `/step` suffix before parsing the base range
    if "/" in piece:
      base, step_str = piece.split("/", 1)
      try:
        step = int(step_str)
      except ValueError as exc:
        raise CronError(f"bad step in {piece!r}") from exc

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
      except ValueError as exc:
        raise CronError(f"bad range in {piece!r}") from exc
      start, end = a, b
    else:
      try:
        v = int(base)
      except ValueError as exc:
        raise CronError(f"bad value in {piece!r}") from exc
      start, end = v, v

    # guard: interval must lie inside the field's allowed range
    if start < lo or end > hi:
      raise CronError(f"value out of range [{lo},{hi}] in {piece!r}")

    # guard: inverted intervals (start > end) are rejected
    if start > end:
      raise CronError(f"start > end in {piece!r}")

    # the field is matched by value, not by expression, so every piece is banked as the
    # concrete set it stands for and overlapping pieces fold together
    out.update(range(start, end + 1, step))

  # guard: a field that expands to no values is unsatisfiable
  if not out:
    raise CronError(f"empty field {spec!r}")
  return out


def parse(cron_str: str) -> CronSpec:
  """
  Parse a 5-field cron expression into per-field value sets.

  Guarantees:
    - The five sets in the returned tuple are always positioned minute, hour, day,
      month, day-of-week, in that fixed order.

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

  # Contract:
  # The returned tuple's five sets are always positioned minute, hour, day, month,
  # day-of-week, in that fixed order; every caller that destructures the tuple
  # positionally relies on this order never changing.

  parts = cron_str.split()

  # guard: must have exactly five whitespace-separated fields
  # waiver: inline numeric literal (cron field count), not a domain constant
  if len(parts) != 5:
    raise CronError(f"expected 5 fields, got {len(parts)}: {cron_str!r}")

  # parts verified to be exactly 5 above → unpack the five parsed fields directly
  minute, hour, day, month, dow = (
    _parse_field(spec, lo, hi) for spec, (lo, hi) in zip(parts, _FIELD_BOUNDS, strict=False)
  )
  return (minute, hour, day, month, dow)


def _python_weekday_to_cron(wd: int) -> int:
  """
  Convert a Python `datetime.weekday()` value to the cron day-of-week convention.

  Args:
    wd: Weekday in Python's convention where Monday is 0 and Sunday is 6.

  Returns:
    The same day expressed in cron's convention where Sunday is 0 and Saturday is 6.
  """
  # datetime.weekday(): Mon=0..Sun=6. cron: Sun=0..Sat=6.
  # waiver: inline numeric literal (days per week), not a domain constant
  return (wd + 1) % 7


def matches(spec: CronSpec, dt: datetime) -> bool:
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


def next_fire(spec: CronSpec, after_dt: datetime, *, horizon_days: int = DEFAULT_HORIZON_DAYS) -> datetime:
  """
  Find the next moment strictly after a reference time at which the cron spec fires.

  Args:
    spec: Tuple of five value sets as returned by `parse`.
    after_dt: Reference moment; the result is strictly greater than this value.
    horizon_days: Length of the search window in days, counted from the reference moment; the default window
      is four years, and a spec that fires only in rarer years needs a wider one.

  Returns:
    The next datetime at which `spec` fires, with second and microsecond zeroed.

  Raises:
    CronError: If no firing moment exists within the search horizon of the reference time,
      indicating the specification is unsatisfiable (e.g. February 30) or fires only beyond the horizon.
  """
  # advance to the next whole minute (cron's resolution) before scanning
  cur = after_dt.replace(second = 0, microsecond = 0) + timedelta(minutes = 1)
  end = after_dt + timedelta(days = horizon_days)
  _minute, _hour, day, month, dow = spec

  # bounded linear scan: a day whose date or weekday the spec excludes is stepped over whole, and
  # only the minutes of a day that can fire are walked one by one
  while cur < end:
    # the day cannot fire at any minute → the scan resumes at the next midnight
    if cur.day not in day or cur.month not in month or _python_weekday_to_cron(cur.weekday()) not in dow:
      cur = (cur + timedelta(days = 1)).replace(hour = 0, minute = 0)
      continue
    if matches(spec, cur):
      return cur
    cur += timedelta(minutes = 1)
  raise CronError(f"no fire within {horizon_days // _DAYS_PER_LONG_YEAR} years; cron spec is unsatisfiable")


def due_since(spec: CronSpec, last_run: datetime, now: datetime) -> bool:
  """
  Report whether a cron spec has any firing boundary in the half-open interval `(last_run, now]`.

  Implements a skip-on-miss policy: multiple missed boundaries collapse to a single True,
  so the routine fires once on the next tick rather than once per missed boundary.

  Guarantees:
    - Any number of missed firing boundaries inside the checked interval collapses into
      a single True verdict rather than one signal per missed boundary.
    - For every expression that can fire within one full 28-year calendar cycle the call answers and never raises,
      however far away the next firing lies; an expression that can never fire still raises `CronError`.

  Args:
    spec: Tuple of five value sets as returned by `parse`.
    last_run: Upper-exclusive lower bound of the interval — typically the previous fire time.
    now: Inclusive upper bound of the interval — typically the current moment.

  Returns:
    True if at least one cron firing falls in `(last_run, now]`, false otherwise.

  Raises:
    CronError: If the spec can never fire; its search covers a full 28-year calendar cycle.
  """

  # Contract:
  # Any number of missed firing boundaries inside the checked interval collapses into a
  # single True verdict; the interval is never reported as more than one due signal no
  # matter how many boundaries it actually contains.

  # Contract:
  # For every expression that can fire within one full 28-year calendar cycle the call answers and NEVER
  # raises, however far away the next firing lies; an expression that can never fire still raises `CronError`.

  # Domain(runtime.daemon-loop):
  # # Skip-on-miss due policy
  # A schedule counts as due once at least one of its firing moments falls inside the window
  # since it was last checked, no matter how many moments were actually missed while the
  # daemon was stopped or busy. Every missed firing in that window collapses into the same
  # single due signal rather than queuing one catch-up run per missed moment, so a routine
  # that was offline for a long stretch resumes with one run instead of a growing backlog.

  # guard: degenerate interval — nothing can be due when the window is empty or inverted
  if last_run >= now:
    return False

  # the search covers one full calendar cycle, so every expression that validation accepts gets an answer
  # here: one that fires only in some years is found however far away its next firing lies
  return next_fire(spec, last_run, horizon_days = CYCLE_HORIZON_DAYS) <= now
