"""
Pytest plugin that makes a test run yield the CPU to the rest of the machine.

Every pytest process of a run, the controller and each xdist worker alike, lowers its own scheduling
priority, so interactive work on the same machine stays responsive. The automatic xdist worker count
is capped so that two CPUs stay free, and never drops below one worker. A worker count named
explicitly through the environment is left to xdist.
"""
from __future__ import annotations

import ctypes
import os
import sys

import pytest

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Niceness a test process runs at on POSIX, unless it already runs at a higher one
TEST_NICENESS = 10

# CPUs left free of xdist workers when the worker count is automatic
RESERVED_CPUS = 2

# Environment variable through which the operator names the automatic worker count explicitly
XDIST_WORKERS_ENV = "PYTEST_XDIST_AUTO_NUM_WORKERS"

# Windows priority class a test process is moved to
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

# Windows priority class below the target one; a process already there is left alone
IDLE_PRIORITY_CLASS = 0x00000040


# ----------------------------------------------------------------------------------------
# waiver: a `-p`-loaded plugin module holds its hooks as module-level functions, so their
# shared helper is a module-level function as well
def _lower_priority() -> None:
  """
  Lower the scheduling priority of the current process.

  The process is moved to the below-normal level on Windows and to a niceness of at least `10` elsewhere.
  The lowering is best-effort: when the system refuses it, the priority stays as it was. A process that already
  runs at a lower priority keeps it, and processes it spawns inherit the lowered priority.
  """

  # Domain(pytool.host-load):
  # # Test run priority
  # A test run is background work: it must give the processor up to whatever the operator is
  # doing interactively on the same machine. A cap on the number of parallel workers cannot
  # guarantee that, because several runs started at once from different sessions add up to
  # more runnable processes than the machine has cores. So every process of a test run lowers
  # its own scheduling priority, and everything it spawns inherits the lowered priority. On
  # POSIX the process raises its niceness to `10`; on Windows it moves to the below-normal
  # priority class. The lowering never goes the other way: a process that already runs at a
  # lower priority than the target keeps it.

  # Windows has no niceness: there the process moves to the below-normal priority class
  if sys.platform == "win32":
    # the signatures are declared because ctypes defaults every result to a C `int`, which
    # truncates the 64-bit process handle `GetCurrentProcess` returns
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetPriorityClass.argtypes = [ ctypes.c_void_p ]
    kernel32.GetPriorityClass.restype = ctypes.c_ulong
    kernel32.SetPriorityClass.argtypes = [ ctypes.c_void_p, ctypes.c_ulong ]

    # an idle-class process is already below the target; a failed call leaves the priority as it was
    if kernel32.GetPriorityClass(kernel32.GetCurrentProcess()) != IDLE_PRIORITY_CLASS:
      kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)

    # the niceness path below is POSIX-only
    return

  # niceness is relative, so only the missing part up to the target is added; lowering the
  # priority is best-effort and a refusal by the system must never fail the test run
  try:
    if (current := os.nice(0)) < TEST_NICENESS:
      os.nice(TEST_NICENESS - current)
  except OSError:
    pass


# ----------------------------------------------------------------------------------------
# waiver: pytest discovers hook implementations as module-level functions by name — they
# cannot be methods on a class in a `-p`-loaded plugin module
def pytest_configure() -> None:
  """
  Lower the priority of the process pytest is configuring.

  Runs in the controller and in every xdist worker, so the whole test run yields the CPU to the rest of the machine.

  Guarantees:
    - The process priority is only ever lowered, and to a fixed target rather than by a fixed step: a process that
      already runs at or below the target priority is left unchanged, so a worker that inherited the lowered
      priority from its controller is not lowered a second time.
    - A failure to change the priority never fails or aborts the test run.
  """

  # Contract:
  # The process priority is only ever lowered, and lowered to a fixed target rather than by a
  # fixed step: configuring a process that already runs at or below the target priority
  # changes nothing, so an xdist worker that inherited the lowered priority from its
  # controller is not lowered a second time.

  # Contract:
  # A failure to change the priority never fails or aborts the test run.

  # the controller and every xdist worker pass through here; children inherit the result
  _lower_priority()


# ----------------------------------------------------------------------------------------
# waiver: pytest discovers hook implementations as module-level functions by name — they
# cannot be methods on a class in a `-p`-loaded plugin module
@pytest.hookimpl(tryfirst = True, optionalhook = True)
def pytest_xdist_auto_num_workers() -> int | None:
  """
  Cap the automatic xdist worker count so that CPUs stay free for the rest of the machine.

  Guarantees:
    - The returned worker count is never below one, whatever the number of CPUs.
    - When the operator names the automatic worker count through the environment, no count is returned and the
      choice is left to xdist.

  Returns:
    The number of CPUs minus two, at least one, or `None` when the environment names the worker count explicitly.
    From Python 3.13 the CPUs are those available to the process; before it, those of the whole machine.
  """

  # Contract:
  # The returned worker count is never below one, whatever the number of CPUs.

  # Contract:
  # When the operator names the automatic worker count through the environment, no count is
  # returned and the choice is left to xdist.

  # Domain(pytool.host-load):
  # # Automatic worker cap
  # A run that asks for an automatic number of parallel workers gets one worker per CPU,
  # minus two CPUs that stay free for the rest of the machine, and never fewer than one
  # worker. From Python 3.13 the CPUs counted are those the process may run on; an older
  # interpreter cannot report that and counts every CPU of the machine. The cap applies only
  # to the automatic count: a worker count the operator names explicitly — on the command
  # line or through the environment — is taken as given.

  # an explicit count in the environment is the operator's choice, so xdist resolves it itself
  if os.environ.get(XDIST_WORKERS_ENV):
    return None

  # the CPUs this process may actually run on are only reported from Python 3.13
  if sys.version_info >= (3, 13):
    return max(1, (os.process_cpu_count() or 1) - RESERVED_CPUS)

  # an older interpreter falls back to the CPUs of the whole machine
  return max(1, (os.cpu_count() or 1) - RESERVED_CPUS)
