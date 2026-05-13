"""Recovery primitives for the lazycortex-core runtime daemon halt state.

The lazy-runtime.recover skill walks an operator through cleanup +
resume after a halt. This module is the pure-Python core: read the
halt context, apply the operator-chosen cleanup mode, verify the tree
is clean, then atomically clear the daemon_halted block.

The cleanup modes wrap real git commands. `commit` uses `git add -A`
because the operator has explicitly chosen to commit everything dirty
— that is the whole point of the mode. The skill MUST surface the
dirty paths to the operator before they pick a mode (so the choice is
informed); this module assumes the choice was already informed.
"""
from __future__ import annotations
import subprocess
from pathlib import Path
import runtime_state


class RecoverError(Exception):
    """Raised when recovery cannot proceed (still dirty, bad mode, etc.)."""


VALID_MODES = {"commit", "stash", "discard", "abort"}


def read_halt(repo: Path) -> dict | None:
    """Return the current daemon_halted block, or None if not halted."""
    return runtime_state.get_halted(repo)


def is_clean(repo: Path) -> bool:
    """Whether `git status --porcelain` is empty in repo. Outside a git
    repo, returns True (consistent with _check_working_tree's None=clean
    convention)."""
    try:
        rc = subprocess.run(
            ["git", "--no-optional-locks", "-c", "color.status=never", "status", "--porcelain"],
            cwd=str(repo), capture_output=True, text=True,
        )
    except FileNotFoundError:
        return True
    if rc.returncode != 0:
        return True
    return rc.stdout.strip() == ""


def cleanup(repo: Path, mode: str, message: str | None = None) -> None:
    """Apply the operator-chosen cleanup mode to the working tree.

    mode ∈ {commit, stash, discard, abort}.
      - commit: stage everything (`git add -A`) and commit with `message`.
      - stash:  `git stash push -u -m <marker>`.
      - discard: reset tracked changes + clean untracked.
      - abort:  no-op (operator backed out).
    """
    if mode not in VALID_MODES:
        raise RecoverError(f"unknown cleanup mode: {mode!r}")

    if mode == "abort":
        return

    if mode == "commit":
        if not message:
            raise RecoverError("commit mode requires a non-empty message")
        subprocess.run(["git", "add", "-A"],
                       cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message],
                       cwd=str(repo), check=True, capture_output=True)
        return

    if mode == "stash":
        subprocess.run(
            ["git", "stash", "push", "-u", "-m", "lazycortex-runtime: halt recovery"],
            cwd=str(repo), check=True, capture_output=True,
        )
        return

    if mode == "discard":
        subprocess.run(["git", "checkout", "--", "."],
                       cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "clean", "-fd"],
                       cwd=str(repo), check=True, capture_output=True)
        return


def resume(repo: Path) -> None:
    """Clear the daemon_halted block iff the tree is clean.

    Raises RecoverError with the dirty paths when still dirty.
    """
    if not is_clean(repo):
        rc = subprocess.run(
            ["git", "--no-optional-locks", "-c", "color.status=never", "status", "--porcelain"],
            cwd=str(repo), capture_output=True, text=True,
        )
        raise RecoverError(
            "working tree still dirty; refusing to resume:\n"
            f"{rc.stdout.strip()}"
        )
    runtime_state.clear_halted(repo)


def cleanup_and_resume(repo: Path, mode: str, message: str | None = None) -> None:
    """Convenience: cleanup then resume in one call."""
    cleanup(repo, mode, message)
    resume(repo)
