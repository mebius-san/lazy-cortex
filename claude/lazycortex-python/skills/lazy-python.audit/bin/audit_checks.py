"""
Audit check implementations for /lazy-python.audit.

CLI: `python3 audit_checks.py check<N> <consumer_repo_dir>` runs the named check;
emits a JSON `{"severity": "PASS"|"WARN"|"FAIL", "message": "..."}` line to stdout
and returns 0 (the skill aggregates severities; a non-zero return would mean the
check itself crashed, not a finding).

Checks:
  check1 — rules mirror integrity (consumer .claude/rules/ matches plugin canon)
  check2 — references cited from rules resolve to plugin reference files
  check3 — plugin tree has all required artifacts
  check4 — wrappers deployed (consumer cli/{chk,tst}-py executable + substituted)
  check5 — pyproject.toml contains the six always-on checker sections ([tool.pch] is optional)
  check6 — PyCharm inspect.sh is available on $PATH (probe)
  check7 — overlay scaffolding files carry the canonical header
  check8 — scaffold registry entry (consumer-local `.claude/templates/python/python-template.py` in `.claude/rules/lazy-core.scaffold.md`)
  check9 — informational: reports whether CLAUDE.md carries a `lazy-python` pointer (install never writes one)
  check10 — plugin ships a well-formed PostToolUse hook manifest at `hooks/hooks.json`
  check11 — venv probe-then-fallback state mirrors `_ensure_venv.sh`
"""
from __future__ import annotations

from typing import Protocol

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Allow override via env (Claude Code sets CLAUDE_PLUGIN_ROOT; consumer install → cache path, not dev source).
# Default fallback resolves to .../claude/lazycortex-python via parents[3].
# Single assignment so PLUGIN_ROOT reads as the module constant it is.
_THIS_FILE = Path(__file__).resolve()
_env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
PLUGIN_ROOT = Path(_env_root).resolve() if _env_root else _THIS_FILE.parents[3]


# ----------------------------------------------------------------------------------------
class _AuditCheck(Protocol):
  """
  Protocol for a single lazy-python audit check.

  Each implementation receives a consumer repo directory at construction time and produces a
  finding dict on `run`.
  """

  # waiver: Protocol type-stubs (`...` body) need no docstring; adding one re-trips pcf D1.
  # pylint: disable=missing-function-docstring  # Protocol type-stubs carry no docstrings

  def __init__(self, *, consumer_dir: Path) -> None: ...

  def run(self) -> dict: ...


# ----------------------------------------------------------------------------------------
class Check1RulesMirror:
  """
  Verify consumer `.claude/rules/` lazy-python rule mirrors are present and byte-identical to plugin canon.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  RULES = ("lazy-python.style.md", "lazy-python.docstrings.md", "lazy-python.tests.md")

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Compare each consumer rule mirror against the plugin canon and aggregate severity.

    Returns:
      Finding dict with `severity` (PASS, WARN, or FAIL) and a `message` string.
    """
    missing: list[str] = []
    drifted: list[str] = []
    for name in self.RULES:
      target = self.consumer_dir / ".claude/rules" / name
      source = PLUGIN_ROOT / "rules" / name
      if not target.exists():
        missing.append(name)
        continue
      if target.read_bytes() != source.read_bytes():
        drifted.append(name)
    if drifted:
      return {"severity": "FAIL", "message": f"rules drifted from canon: {drifted}"}
    if missing:
      return {"severity": "WARN", "message": f"rules missing from consumer: {missing}"}
    return {"severity": "PASS", "message": "all rule mirrors match canon"}


# ----------------------------------------------------------------------------------------
class Check2ReferencesResolve:
  """
  Verify every `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.*.md` path cited from consumer rules
  resolves to a file in the plugin.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  PATTERN = re.compile(r'\$\{CLAUDE_PLUGIN_ROOT\}/references/(lazy-python\.[a-z-]+\.md)')

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Scan consumer rules for reference pointers and verify each resolves to a plugin reference file.

    Returns:
      Finding dict with `severity` (PASS, WARN, or FAIL) and a `message` string.
    """
    rules_dir = self.consumer_dir / ".claude/rules"
    if not rules_dir.exists():
      return {"severity": "WARN", "message": "consumer .claude/rules/ does not exist — run /lazy-python.install"}
    cited: set[str] = set()
    for rule_file in rules_dir.glob("lazy-python.*.md"):
      cited.update(self.PATTERN.findall(rule_file.read_text()))
    missing = [ref for ref in cited if not (PLUGIN_ROOT / "references" / ref).exists()]
    if missing:
      return {"severity": "FAIL", "message": f"unresolved reference paths: {missing}"}
    if not cited:
      return {"severity": "WARN", "message": "no reference pointers found in consumer rules"}
    return {"severity": "PASS", "message": f"all {len(cited)} reference pointers resolve"}


# ----------------------------------------------------------------------------------------
class Check3ArtifactsPresent:
  """
  Verify the plugin tree has the expected artifact set.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  REQUIRED: tuple = (
    (".claude-plugin/plugin.json", "manifest"),
    (".claude-plugin/overview.md", "overview"),
    ("rules/lazy-python.style.md", "style rule"),
    ("rules/lazy-python.docstrings.md", "docstrings rule"),
    ("rules/lazy-python.tests.md", "tests rule"),
    ("references/lazy-python.coding-guidelines.md", "coding canon"),
    ("references/lazy-python.documenting-guidelines.md", "documenting canon"),
    ("references/lazy-python.testing-guidelines.md", "testing canon"),
    ("references/lazy-python.checking-guidelines.md", "checking canon"),
    ("references/lazy-python.guidelines-index.md", "index"),
    ("bin/chk", "chk aggregator"),
    ("bin/tst", "tst aggregator"),
    ("bin/_ensure_venv.sh", "venv bootstrap"),
    ("bin/pcf.py", "pcf checker"),
    ("bin/toi.py", "toi checker"),
    ("bin/pch.py", "pch checker"),
    ("hooks/lazy-python.check-style.sh", "PostToolUse hook"),
    ("hooks/hooks.json", "PostToolUse hook manifest"),
    ("skills/lazy-python.check-style/SKILL.md", "check-style skill"),
    ("agents/lazy-python.docstring-writer.md", "docstring-writer agent"),
    ("agents/lazy-python.test-writer.md", "test-writer agent"),
    ("templates/pyproject-defaults.toml", "pyproject template"),
    ("templates/chk-wrapper.sh", "chk-py wrapper template"),
    ("templates/tst-wrapper.sh", "tst-py wrapper template"),
    ("templates/python/python-template.py", "python file template"),
    ("templates/python/scaffold.entries.json", "scaffold manifest"),
  )

  def __init__(self, *, consumer_dir: Path) -> None:
    # consumer_dir is the audit context but check3 only looks at PLUGIN_ROOT
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Verify every required artifact exists in the plugin tree.

    Returns:
      Finding dict with `severity` (PASS or FAIL) and a `message` string.
    """
    missing: list[str] = []
    for rel, _label in self.REQUIRED:
      if not (PLUGIN_ROOT / rel).exists():
        missing.append(rel)
    if missing:
      return {"severity": "FAIL", "message": f"missing artifacts: {missing}"}
    return {"severity": "PASS", "message": f"all {len(self.REQUIRED)} artifacts present"}


# ----------------------------------------------------------------------------------------
class Check4Wrappers:
  """
  Verify consumer `cli/chk-py` and `cli/tst-py` are deployed, executable, and have substituted bin paths.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  WRAPPERS: tuple = ("chk-py", "tst-py")
  PLACEHOLDER = re.compile(r'\{\{[A-Z_]+_BIN_PATH\}\}')

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Check both wrappers for presence, executable bit, and placeholder substitution.

    Returns:
      Finding dict with `severity` (PASS, WARN, or FAIL) and a `message` string.
    """
    bin_dir = self.consumer_dir / "cli"
    missing: list[str] = []
    broken: list[str] = []
    for name in self.WRAPPERS:
      wrapper = bin_dir / name
      if not wrapper.exists():
        missing.append(name)
        continue
      if not os.access(wrapper, os.X_OK):
        missing.append(f"{name} (not executable)")
        continue
      if self.PLACEHOLDER.search(wrapper.read_text()):
        broken.append(name)
    if broken:
      return {"severity": "FAIL", "message": f"wrappers contain unsubstituted placeholders: {broken}"}
    if missing:
      return {"severity": "WARN", "message": f"wrappers missing or not executable: {missing}"}
    return {"severity": "PASS", "message": "both wrappers deployed, executable, and substituted"}


# ----------------------------------------------------------------------------------------
class Check5Pyproject:
  """
  Verify consumer `pyproject.toml` contains the six always-on install-bootstrapped checker sections.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  # pch is added by install only when PyCharm is present on the machine, so it is NOT a required section.
  REQUIRED: tuple = ("tool.pcf", "tool.toi", "tool.pytest", "tool.mypy", "tool.pylint", "tool.ruff")

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Parse `pyproject.toml` and check for each required `[tool.<name>]` section.

    Returns:
      Finding dict with `severity` (PASS, WARN, or FAIL) and a `message` string.
    """
    pyproject = self.consumer_dir / "pyproject.toml"
    # guard:
    if not pyproject.exists():
      return {"severity": "FAIL", "message": "pyproject.toml not found in consumer root"}
    try:
      data = tomllib.loads(pyproject.read_text())
    except tomllib.TOMLDecodeError as exc:
      return {"severity": "FAIL", "message": f"pyproject.toml is not valid TOML: {exc}"}
    tool_table = data.get("tool", {})
    missing: list[str] = []
    for section in self.REQUIRED:
      # section names are dotted; first segment is always "tool", remainder selects the subtable
      _tool, _, sub = section.partition(".")
      if sub not in tool_table:
        missing.append(section)
    if len(missing) >= 3:
      return {"severity": "FAIL", "message": f"{len(missing)} of 6 checker sections missing: {missing}"}
    if missing:
      return {"severity": "WARN", "message": f"checker sections missing: {missing}"}
    return {"severity": "PASS", "message": "all 6 checker sections present"}


# ----------------------------------------------------------------------------------------
class Check6InspectSh:
  """
  Verify the PyCharm `inspect.sh` CLI is available on `$PATH` (runtime probe).

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  def __init__(self, *, consumer_dir: Path) -> None:
    # consumer_dir is unused — this is a host-level probe, not a consumer-tree check
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Probe `$PATH` for `inspect.sh`; absence degrades `pch.py` but leaves the rest of the stack intact.

    Returns:
      Finding dict with `severity` (PASS or WARN) and a `message` string.
    """
    found = shutil.which("inspect.sh")
    if found:
      return {"severity": "PASS", "message": f"inspect.sh found at {found}"}
    return {"severity": "WARN",
            "message": "inspect.sh not on $PATH — pch.py will not run, rest of stack is unaffected"}


# ----------------------------------------------------------------------------------------
class Check7Overlay:
  """
  Verify each overlay-scaffolding guideline file exists and carries the canonical header.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  TOPICS: tuple = ("coding", "documenting", "testing", "checking")
  HEADER_PATTERN = "# Project additions to {topic}"

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Check each overlay file exists and its first non-empty line matches the canonical header pattern.

    Returns:
      Finding dict with `severity` (PASS, WARN, or FAIL) and a `message` string.
    """
    overlay_dir = self.consumer_dir / "docs/guidelines"
    bad: list[str] = []
    for topic in self.TOPICS:
      overlay_file = overlay_dir / f"{topic}_guidelines.md"
      if not overlay_file.exists():
        bad.append(f"{topic} (missing)")
        continue
      first_line = ""
      for line in overlay_file.read_text().splitlines():
        if line.strip():
          first_line = line
          break
      expected = self.HEADER_PATTERN.format(topic = topic)
      if not first_line.startswith(expected):
        bad.append(f"{topic} (wrong header)")
    if len(bad) >= 3:
      return {"severity": "FAIL", "message": f"{len(bad)} of 4 overlays missing or wrong header: {bad}"}
    if bad:
      return {"severity": "WARN", "message": f"overlay scaffolding issues: {bad}"}
    return {"severity": "PASS", "message": "all 4 overlay files have correct headers"}


# ----------------------------------------------------------------------------------------
class Check8Scaffold:
  """
  Verify the scaffold registry rule registers the consumer-local `python-template.py` copy.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  RULE_REL = ".claude/rules/lazy-core.scaffold.md"
  MARKER = "python-template.py"
  CONSUMER_LOCAL_PATH = ".claude/templates/python/python-template.py"

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Check that the scaffold rule body registers the consumer-local python-template entry.

    Returns:
      Finding dict with `severity` (PASS or WARN) and a `message` string.
    """
    rule = self.consumer_dir / self.RULE_REL
    # guard:
    if not rule.exists():
      return {
        "severity": "WARN",
        "message": f"{self.RULE_REL} not found — consumer has not run /lazy-python.install",
      }
    body = rule.read_text()
    if self.MARKER not in body:
      return {
        "severity": "WARN",
        "message": f"{self.MARKER!r} not found in {self.RULE_REL} — re-run /lazy-python.install",
      }
    # The entry must point at the consumer-local copy, not a plugin path. `${CLAUDE_PLUGIN_ROOT}`
    # does not expand in rule bodies, so a registry value carrying it (or an absolute cache path)
    # never resolves — scaffold-sync writes the consumer-local path; an env-var / absolute value
    # means the entry came from a pre-scaffold-sync install or was hand-edited.
    if self.CONSUMER_LOCAL_PATH not in body:
      return {
        "severity": "WARN",
        "message": (
          f"scaffold entry for {self.MARKER!r} is not the consumer-local path "
          f"{self.CONSUMER_LOCAL_PATH!r} — re-run /lazy-python.install to resync via scaffold-sync"
        ),
      }
    return {"severity": "PASS", "message": f"scaffold registry registers {self.CONSUMER_LOCAL_PATH}"}


# ----------------------------------------------------------------------------------------
class Check9ClaudeMd:
  """
  Report, informationally, whether the consumer CLAUDE.md carries a `lazy-python` pointer.

  The pointer is optional and is never written by install (the plugin rules load from
  `.claude/rules/` regardless), so absence is never a finding — this check only surfaces
  whether an operator added one by hand.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  POINTER = "lazy-python"

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  @staticmethod
  def _resolve_target(consumer_dir: Path) -> Path | None:
    """
    Return the consumer CLAUDE.md path — repo-root copy preferred, else `.claude/CLAUDE.md`, else `None`.

    Returns:
      Path to the located CLAUDE.md, or `None` if neither candidate exists.
    """
    root = consumer_dir / "CLAUDE.md"
    if root.exists():
      return root
    dot_claude = consumer_dir / ".claude/CLAUDE.md"
    if dot_claude.exists():
      return dot_claude
    return None

  def run(self) -> dict:
    """
    Report whether a CLAUDE.md (at repo root or `.claude/`) mentions the lazy-python pointer.

    Returns:
      Finding dict with `severity` (PASS when a pointer is present, otherwise INFO) and a `message` string.
    """
    claude_md = self._resolve_target(self.consumer_dir)
    # guard: no CLAUDE.md anywhere → nothing to report; install never writes a pointer, so this is not a finding
    if claude_md is None:
      return {"severity": "INFO", "message": "no CLAUDE.md (root or .claude/) — optional; install adds none"}
    rel = claude_md.relative_to(self.consumer_dir).as_posix()
    body = claude_md.read_text()
    if self.POINTER not in body:
      return {
        "severity": "INFO",
        "message": f"no {self.POINTER!r} pointer in {rel} — optional; the plugin rules load from .claude/rules/ regardless",
      }
    return {"severity": "PASS", "message": f"{rel} carries a lazy-python pointer (operator-added)"}


# ----------------------------------------------------------------------------------------
class Check10Hook:
  """
  Verify the plugin ships a well-formed PostToolUse hook manifest at `hooks/hooks.json`.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  MANIFEST_REL = "hooks/hooks.json"
  HOOK_MARKER = "lazy-python.check-style.sh"

  def __init__(self, *, consumer_dir: Path) -> None:
    # consumer_dir is the audit context but check10 only inspects the plugin manifest;
    # the engine auto-registers the hook from it — no consumer settings.json write happens.
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Verify the plugin's `hooks.json` exists, parses as JSON, and declares a PostToolUse entry.

    Returns:
      Finding dict with `severity` (PASS, WARN, or FAIL) and a `message` string.
    """
    manifest = PLUGIN_ROOT / self.MANIFEST_REL
    # guard: manifest absent → engine has nothing to auto-register
    if not manifest.exists():
      return {"severity": "WARN", "message": f"{self.MANIFEST_REL} not found in plugin tree"}
    try:
      data = json.loads(manifest.read_text())
    except json.JSONDecodeError as exc:
      return {"severity": "FAIL", "message": f"{self.MANIFEST_REL} is not valid JSON: {exc}"}
    post_tool_use = data.get("hooks", {}).get("PostToolUse", [])
    for entry in post_tool_use:
      for sub_hook in entry.get("hooks", []):
        command = str(sub_hook.get("command", ""))
        if self.HOOK_MARKER in command:
          return {"severity": "PASS", "message": f"hooks.json declares PostToolUse hook ({self.HOOK_MARKER})"}
    return {"severity": "WARN", "message": f"{self.MANIFEST_REL} has no PostToolUse entry for {self.HOOK_MARKER}"}


# ----------------------------------------------------------------------------------------
class Check11Venv:
  """
  Read-only mirror of the venv probe-then-fallback logic applied at install time.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  TOOLS: tuple = ("mypy", "pylint", "pytest", "ruff")
  PLUGINS: tuple = ("pytest_clarity", "pytest_sugar")

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def _venv_has_tools(self, venv: Path) -> bool:
    """
    Return `True` iff the four required tool binaries are executable and the two pytest plugins import.

    Returns:
      `True` when all probes pass, `False` on the first failure.
    """
    for tool in self.TOOLS:
      bin_path = venv / "bin" / tool
      if not bin_path.exists() or not os.access(bin_path, os.X_OK):
        return False
    python_bin = venv / "bin" / "python"
    # guard: pytest plugins ship no bin — verify they import in the venv's interpreter
    if not python_bin.exists() or not os.access(python_bin, os.X_OK):
      return False
    import_stmt = f"import {', '.join(self.PLUGINS)}"
    probe = subprocess.run(
      [str(python_bin), "-c", import_stmt],
      capture_output = True,
      check = False,
    )
    return probe.returncode == 0

  def _read_pyproject_key(self, key: str) -> str:
    """
    Read `[tool.lazy-python].<key>` from the consumer `pyproject.toml`.

    Returns:
      The value as a string, or an empty string if the file is absent, unparseable, or the key is missing.
    """
    pyproject = self.consumer_dir / "pyproject.toml"
    # guard:
    if not pyproject.exists():
      return ""
    try:
      data = tomllib.loads(pyproject.read_text())
    except tomllib.TOMLDecodeError:
      return ""
    value = data.get("tool", {}).get("lazy-python", {}).get(key)
    # guard:
    if value is None:
      return ""
    if isinstance(value, bool):
      return "true" if value else "false"
    return str(value)

  def run(self) -> dict:
    """
    Walk probes 1-3 plus the repo-root fallback in install order and report venv readiness.

    Returns:
      Finding dict with `severity` (PASS or WARN) and a `message` string.
    """
    # probe 1: $VIRTUAL_ENV
    virtual_env = os.environ.get("VIRTUAL_ENV", "")
    if virtual_env:
      venv = Path(virtual_env)
      if self._venv_has_tools(venv):
        return {"severity": "PASS", "message": f"$VIRTUAL_ENV venv satisfies probe-1 ({venv})"}
      return {"severity": "WARN", "message": f"$VIRTUAL_ENV venv missing tools ({venv})"}

    # probe 2: <consumer>/.venv (also the repo-root fallback target — probe 4 creates/augments it here)
    project_venv = self.consumer_dir / ".venv"
    if project_venv.exists():
      if self._venv_has_tools(project_venv):
        return {"severity": "PASS", "message": "consumer .venv satisfies probe-2"}
      return {"severity": "WARN",
              "message": "consumer .venv exists but missing tools (fallback will augment it in place)"}

    # probe 3: [tool.lazy-python].venv
    configured = self._read_pyproject_key("venv")
    if configured:
      configured_path = Path(configured).expanduser()
      if not configured_path.is_absolute():
        configured_path = self.consumer_dir / configured_path
      if self._venv_has_tools(configured_path):
        return {"severity": "PASS", "message": f"configured venv satisfies probe-3 ({configured})"}
      return {"severity": "WARN", "message": f"configured venv missing tools or absent ({configured})"}

    # no venv found — fallback will create/augment <consumer>/.venv on first chk-py; check opt-out + uv availability
    fallback_flag = self._read_pyproject_key("bootstrap-fallback")
    if fallback_flag == "false":
      return {"severity": "WARN",
              "message": "no venv found AND bootstrap-fallback = false (consumer must configure)"}

    if not shutil.which("uv"):
      return {"severity": "WARN", "message": "no venv found AND uv missing — fallback won't work on first chk-py"}

    return {"severity": "PASS", "message": "no venv yet; fallback creates <consumer>/.venv on first chk-py"}


def main() -> int:
  """
  Dispatch a named check, emit its JSON finding to stdout, and return 0.

  Returns:
    0 on success (severity is in the JSON payload); 2 if invocation arguments are invalid.
  """
  if len(sys.argv) < 3:
    print(f"usage: {sys.argv[0]} check<N> <consumer_repo_dir>", file = sys.stderr)
    return 2
  check_id = sys.argv[1]
  consumer_dir = Path(sys.argv[2]).resolve()
  checks: dict[str, type[_AuditCheck]] = {
    "check1": Check1RulesMirror,
    "check2": Check2ReferencesResolve,
    "check3": Check3ArtifactsPresent,
    "check4": Check4Wrappers,
    "check5": Check5Pyproject,
    "check6": Check6InspectSh,
    "check7": Check7Overlay,
    "check8": Check8Scaffold,
    "check9": Check9ClaudeMd,
    "check10": Check10Hook,
    "check11": Check11Venv,
  }
  handler = checks.get(check_id)
  if handler is None:
    print(f"unknown check: {check_id!r}; supported: {sorted(checks)}", file = sys.stderr)
    return 2
  result = handler(consumer_dir = consumer_dir).run()
  print(json.dumps(result))
  return 0


if __name__ == "__main__":
  sys.exit(main())
