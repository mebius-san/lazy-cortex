"""
Install phase implementations for /lazy-python.install.

CLI: `python3 install_phases.py phase<N> <consumer_repo_dir>` runs the named phase
against the consumer repo. Phases are idempotent; safe to re-run.

Phases:
  phase1 — mirror plugin rules into <consumer>/.claude/rules/
  phase2 — deploy chk-py and tst-py wrappers into <consumer>/cli/
  phase3 — bootstrap consumer pyproject.toml with checker sections
  phase4 — probe for PyCharm inspect.sh CLI (pch prereq)
  phase5 — scaffold project overlay guidelines under docs/guidelines/
  phase7 — offer to append lazy-python discipline pointer to consumer's CLAUDE.md

Scaffold-template sync (formerly phase6) is no longer a phase here — the install
skill's Step 6 dispatches `lazycortex-core:lazy-core.scaffold-sync`, which copies
the template into the consumer's `.claude/templates/python/` and upserts the
registry entry pointing at that consumer-local path.

The PostToolUse check-style hook (formerly phase8) is no longer registered by
install — it auto-registers from the plugin's `hooks/hooks.json` manifest when the
plugin is enabled; no phase writes to the consumer's settings.json.
"""
from __future__ import annotations

from typing import Protocol

import os
import shutil
import stat
import sys
import tomllib
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# location of the plugin tree (this file lives at .../skills/lazy-python.install/bin/install_phases.py)
# Allow override via env (Claude Code sets CLAUDE_PLUGIN_ROOT; consumer install → cache path, not dev source).
# Default fallback resolves to .../claude/lazycortex-python via parents[3].
# Single assignment so PLUGIN_ROOT reads as the module constant it is.
_THIS_FILE = Path(__file__).resolve()
_env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
PLUGIN_ROOT = Path(_env_root).resolve() if _env_root else _THIS_FILE.parents[3]


# ----------------------------------------------------------------------------------------
class _InstallPhase(Protocol):
  """
  Protocol for a single install-phase handler.

  Each concrete phase accepts the consumer repository directory at construction time and performs
  one idempotent installation step when `run` is called.

  Responsibilities:
    - Accept the consumer directory at construction.
    - Execute a single install step and return a POSIX exit code.
  """

  # waiver: Protocol type-stubs (`...` body) need no docstring; adding one re-trips pcf D1.
  # pylint: disable=missing-function-docstring  # Protocol type-stubs carry no docstrings

  def __init__(self, *, consumer_dir: Path) -> None: ...

  def run(self) -> int: ...


# ----------------------------------------------------------------------------------------
class Phase1MirrorRules:
  """
  Install phase that copies plugin rule files into the consumer's `.claude/rules/` directory.
  """

  RULES = ("lazy-python.style.md", "lazy-python.docstrings.md", "lazy-python.tests.md")

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.target_dir: Path = consumer_dir / ".claude/rules"

  def run(self) -> int:
    """
    Copy each plugin rule into the consumer's rules dir.

    Returns:
      0 on success.
    """
    self.target_dir.mkdir(parents = True, exist_ok = True)
    for name in self.RULES:
      source = PLUGIN_ROOT / "rules" / name
      target = self.target_dir / name
      shutil.copyfile(source, target)
    return 0


# ----------------------------------------------------------------------------------------
class Phase2Wrappers:
  """
  Install phase that writes `chk-py` and `tst-py` wrapper scripts into the consumer's `cli/`
  directory and ensures `.venv/` is listed in the consumer's `.gitignore`.
  """

  WRAPPERS = (
    ("chk-wrapper.sh", "chk-py", "{{CHK_BIN_PATH}}", "bin/chk"),
    ("tst-wrapper.sh", "tst-py", "{{TST_BIN_PATH}}", "bin/tst"),
  )

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.target_dir: Path = consumer_dir / "cli"
    self.gitignore: Path = consumer_dir / ".gitignore"

  def run(self) -> int:
    """
    Write executable wrapper scripts to the consumer's `cli/` directory and update `.gitignore`.

    Returns:
      0 on success.
    """
    self.target_dir.mkdir(parents = True, exist_ok = True)
    for template_name, target_name, placeholder, bin_rel in self.WRAPPERS:
      template = (PLUGIN_ROOT / "templates" / template_name).read_text()
      abs_bin = str((PLUGIN_ROOT / bin_rel).resolve())
      content = template.replace(placeholder, abs_bin)
      target = self.target_dir / target_name
      target.write_text(content)
      target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    self._ensure_venv_gitignored()
    return 0

  def _ensure_venv_gitignored(self) -> None:
    """
    Append `.venv/` to the consumer's `.gitignore` when absent.
    """
    existing = self.gitignore.read_text() if self.gitignore.exists() else ""
    present = any(line.strip() in (".venv", ".venv/") for line in existing.splitlines())
    # guard: already ignored → leave the file byte-for-byte
    if present:
      print("gitignore-already-present")
      return
    prefix = existing if existing == "" or existing.endswith("\n") else existing + "\n"
    self.gitignore.write_text(prefix + ".venv/\n")
    print("gitignore-ensured")


# ----------------------------------------------------------------------------------------
class Phase3Pyproject:
  """Bootstrap consumer's `pyproject.toml` with checker-stack sections from the template.

  Sections added: `[tool.pcf]`, `[tool.pcf.overrides]`, `[tool.toi]`, `[tool.pch]`,
  `[tool.pytest.ini_options]`, `[tool.mypy]`, `[tool.pylint]`, `[tool.ruff]` (and any
  nested keys, e.g. `[tool.ruff.lint]`). Existing top-level sections in the consumer's
  pyproject.toml are NOT overwritten — the consumer's configuration always wins.
  Idempotent — re-running is a no-op once every checker section is present.
  """

  # Always-deployed checker sections. pch is added only when PyCharm is present —
  # it spins up a headless PyCharm and is meaningless without it, so it is deployed
  # only when the install skill sets the matching env flag (see OPTIONAL_SECTIONS + run()).
  CHECKER_SECTIONS = ("pcf", "toi", "pytest", "mypy", "pylint", "ruff")
  OPTIONAL_SECTIONS = {"pch": "LAZY_PYTHON_ENABLE_PCH"}

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.target: Path = consumer_dir / "pyproject.toml"
    self.template: Path = PLUGIN_ROOT / "templates/pyproject-defaults.toml"

  def run(self) -> int:
    """
    Merge missing checker sections from the template into the consumer's `pyproject.toml`.

    Returns:
      0 on success.
    """
    template_text = self.template.read_text()

    if self.target.exists():
      existing_text = self.target.read_text()
    else:
      existing_text = '[project]\nname = "consumer"\nversion = "0.1.0"\n'

    existing_data = tomllib.loads(existing_text)
    existing_tool = existing_data.get("tool", {})

    # Always-on sections, plus any opt-in section whose env flag is set by the skill.
    wanted = list(self.CHECKER_SECTIONS)
    wanted += [s for s, env in self.OPTIONAL_SECTIONS.items() if os.environ.get(env)]

    # Determine which wanted sections are MISSING under [tool] in the consumer file.
    missing = [s for s in wanted if s not in existing_tool]

    # Idempotent no-op when every checker section is already present.
    if not missing:
      # guard: ensure file exists even if no merge happened (first run on missing file is still a write)
      if not self.target.exists():
        self.target.write_text(existing_text)
      return 0

    # Extract each missing section's raw text block from the template (preserves comments + formatting).
    appended_blocks: list[str] = []
    for section_name in missing:
      block = self._extract_section_block(template_text, section_name)
      if block:
        appended_blocks.append(block)

    new_content = existing_text.rstrip() + "\n\n" + "\n\n".join(appended_blocks) + "\n"
    self.target.write_text(new_content)
    return 0

  @classmethod
  def _extract_section_block(cls, toml_text: str, top_name: str) -> str:
    """
    Extract a top-level `[tool.<top_name>]` TOML section and all its nested sub-headers verbatim.

    Returns:
      The raw text lines of the matched section, stripped of trailing whitespace.
    """
    target_prefix = f"[tool.{top_name}"
    out: list[str] = []
    in_section = False
    for line in toml_text.splitlines():
      stripped = line.strip()
      if stripped.startswith("["):
        # New section header — flip in/out based on whether it matches the target prefix.
        in_section = stripped.startswith(target_prefix)
      if in_section:
        out.append(line)
    return "\n".join(out).rstrip()


# ----------------------------------------------------------------------------------------
class Phase4Pch:
  """
  Install phase that probes for the PyCharm `inspect.sh` CLI tool and reports its availability.
  """

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> int:
    """
    Check whether `inspect.sh` is available on PATH and emit a status word to stdout.

    Returns:
      0 always; absence of `inspect.sh` is a warning, not a failure.
    """
    if shutil.which("inspect.sh"):
      print("pch-ready: inspect.sh found on PATH")
    else:
      print("pch-missing-inspect-sh: pch.py requires PyCharm's inspect.sh on PATH (warn only).")
    return 0


# ----------------------------------------------------------------------------------------
class Phase5Overlay:
  """
  Install phase that creates per-topic guideline overlay stub files under the consumer's
  `docs/guidelines/` directory.
  """

  TOPICS = ("coding", "documenting", "testing", "checking")

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.target_dir: Path = consumer_dir / "docs/guidelines"

  def run(self) -> int:
    """
    Write a stub overlay file for each topic that does not already exist.

    Returns:
      0 on success.
    """
    self.target_dir.mkdir(parents = True, exist_ok = True)
    for topic in self.TOPICS:
      target = self.target_dir / f"{topic}_guidelines.md"
      # guard: never clobber a consumer-authored overlay
      if target.exists():
        continue
      target.write_text(self._stub_content(topic))
    return 0

  @classmethod
  def _stub_content(cls, topic: str) -> str:
    """
    Compose the stub file body for the given topic.

    Returns:
      A markdown string containing a canonical header and orientation comments.
    """
    return (
      f"# Project additions to {topic} guidelines\n"
      "\n"
      f"<!-- This file is read by lazy-python.* agents/skills after the canon. -->\n"
      f"<!-- Canon lives at ${{CLAUDE_PLUGIN_ROOT}}/references/lazy-python.{topic}-guidelines.md. -->\n"
      "<!-- Add project-specific deltas below; on conflict they override the canon. -->\n"
    )


# ----------------------------------------------------------------------------------------
class Phase7ClaudeMd:
  """
  Install phase that appends a lazy-python discipline pointer bullet to the consumer's
  `CLAUDE.md` under its `## Guidelines` section.
  """

  MARKER = "lazy-python plugin rules"
  BULLET = (
    "- Python style/docstring/test discipline is enforced by lazy-python plugin rules at "
    "`.claude/rules/lazy-python.*.md`. See `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.guidelines-index.md` "
    "for the full canon, and `docs/guidelines/*.md` for project-specific overlays."
  )

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.target: Path | None = self._resolve_target(consumer_dir)

  @staticmethod
  def _resolve_target(consumer_dir: Path) -> Path | None:
    """
    Locate the consumer's `CLAUDE.md`, preferring the repo root over `.claude/CLAUDE.md`.

    Returns:
      Path to the located file, or `None` if neither location exists.
    """
    root = consumer_dir / "CLAUDE.md"
    if root.exists():
      return root
    dot_claude = consumer_dir / ".claude/CLAUDE.md"
    if dot_claude.exists():
      return dot_claude
    return None

  def run(self) -> int:
    """
    Append the discipline pointer bullet to the consumer's `CLAUDE.md` when consent is given.

    Returns:
      0 on success or when the step is skipped due to missing consent or missing file.
    """
    accept = os.environ.get("LAZY_PYTHON_INSTALL_ACCEPT", "0") == "1"
    # guard: decline → leave the consumer's CLAUDE.md untouched (owner is the consumer)
    if not accept:
      print("claude-md-pointer-skipped")
      return 0
    # guard: no CLAUDE.md anywhere → nothing to append to; do not silently create one
    if self.target is None:
      print("claude-md-pointer-skipped: no CLAUDE.md (root or .claude/)")
      return 0
    content = self.target.read_text()
    # guard: idempotency — bullet already present
    if self.MARKER in content:
      print("claude-md-pointer-already-present")
      return 0
    # Append to ## Guidelines section, or add the section + bullet at end
    if "## Guidelines" in content:
      new_content = self._append_to_guidelines(content)
    else:
      new_content = content.rstrip() + "\n\n## Guidelines\n\n" + self.BULLET + "\n"
    self.target.write_text(new_content)
    print("claude-md-pointer-added")
    return 0

  @classmethod
  def _append_to_guidelines(cls, content: str) -> str:
    """
    Insert the pointer bullet at the end of the `## Guidelines` section in the given text.

    Returns:
      The full file content with the bullet appended inside the `## Guidelines` section.
    """
    lines = content.splitlines(keepends = True)
    out: list[str] = []
    in_section = False
    inserted = False
    for line in lines:
      # Detect the start of the Guidelines section
      if line.strip() == "## Guidelines":
        out.append(line)
        in_section = True
        continue
      # Next top-level section closes the Guidelines block — inject before it
      if in_section and line.startswith("## ") and line.strip() != "## Guidelines":
        if out and not out[-1].endswith("\n"):
          out.append("\n")
        out.append(cls.BULLET + "\n\n")
        out.append(line)
        in_section = False
        inserted = True
        continue
      out.append(line)
    # guard: hit EOF still inside the Guidelines section → append the bullet at end
    if in_section and not inserted:
      if out and not out[-1].endswith("\n"):
        out.append("\n")
      out.append(cls.BULLET + "\n")
    return "".join(out)


def main() -> int:
  """
  Dispatch a single named phase against a consumer repository directory.

  Returns:
    0 on success, 2 on usage error or unknown phase name.
  """
  # guard: argv shape — need at least phase + consumer-dir
  if len(sys.argv) < 3:
    print(f"usage: {sys.argv[0]} phase<N> <consumer_repo_dir>", file = sys.stderr)
    return 2
  phase = sys.argv[1]
  consumer_dir = Path(sys.argv[2]).resolve()
  phases: dict[str, type[_InstallPhase]] = {
    "phase1": Phase1MirrorRules,
    "phase2": Phase2Wrappers,
    "phase3": Phase3Pyproject,
    "phase4": Phase4Pch,
    "phase5": Phase5Overlay,
    "phase7": Phase7ClaudeMd,
  }
  handler = phases.get(phase)
  if handler is None:
    print(f"unknown phase: {phase!r}; supported: {sorted(phases)}", file = sys.stderr)
    return 2
  return handler(consumer_dir = consumer_dir).run()


if __name__ == "__main__":
  sys.exit(main())
