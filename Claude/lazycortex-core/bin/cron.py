"""Minimal cron parser for the lazycortex-core schedule routine type.

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
    """Raised for unparseable cron expressions or impossible specs."""


_FIELD_BOUNDS = [
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day
    (1, 12),  # month
    (0, 6),   # day of week (Sun=0..Sat=6)
]


def _parse_field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for piece in spec.split(","):
        piece = piece.strip()
        if not piece:
            raise CronError(f"empty piece in field {spec!r}")
        if "/" in piece:
            base, step_str = piece.split("/", 1)
            try:
                step = int(step_str)
            except ValueError:
                raise CronError(f"bad step in {piece!r}")
            if step <= 0:
                raise CronError(f"step must be > 0 in {piece!r}")
        else:
            base, step = piece, 1

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

        if start < lo or end > hi:
            raise CronError(f"value out of range [{lo},{hi}] in {piece!r}")
        if start > end:
            raise CronError(f"start > end in {piece!r}")

        out.update(range(start, end + 1, step))

    if not out:
        raise CronError(f"empty field {spec!r}")
    return out


def parse(cron_str: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    """Parse a 5-field cron expression. Returns (minute, hour, day, month, dow) sets."""
    parts = cron_str.split()
    if len(parts) != 5:
        raise CronError(f"expected 5 fields, got {len(parts)}: {cron_str!r}")
    fields = []
    for spec, (lo, hi) in zip(parts, _FIELD_BOUNDS):
        fields.append(_parse_field(spec, lo, hi))
    return tuple(fields)


def _python_weekday_to_cron(wd: int) -> int:
    # datetime.weekday(): Mon=0..Sun=6. cron: Sun=0..Sat=6.
    return (wd + 1) % 7


def matches(spec, dt: datetime) -> bool:
    minute, hour, day, month, dow = spec
    return (
        dt.minute in minute and
        dt.hour in hour and
        dt.day in day and
        dt.month in month and
        _python_weekday_to_cron(dt.weekday()) in dow
    )


def next_fire(spec, after_dt: datetime) -> datetime:
    """Find the next datetime strictly greater than after_dt at which spec fires.

    Searches at minute granularity (cron's resolution). Bounded scan: 4 years
    covers every valid 5-field pattern; impossible patterns (e.g. Feb 30) raise.
    """
    cur = after_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = after_dt + timedelta(days=4 * 366)
    while cur < end:
        if matches(spec, cur):
            return cur
        cur += timedelta(minutes=1)
    raise CronError("no fire within 4 years; cron spec is unsatisfiable")


def due_since(spec, last_run: datetime, now: datetime) -> bool:
    """True if a fire boundary fell in (last_run, now]. Skip-on-miss policy:
    multiple missed boundaries collapse to a single True (the routine fires
    once on the next tick, not once per missed boundary)."""
    if last_run >= now:
        return False
    return next_fire(spec, last_run) <= now
