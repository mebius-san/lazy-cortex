"""
Audit check implementations for /lazy-python.audit.

CLI: `python3 audit_checks.py check<N> <consumer_repo_dir>` runs the named check;
emits a JSON `{"severity": "PASS"|"WARN"|"FAIL", "message": "..."}` line to stdout
and returns 0 (the skill aggregates severities; a non-zero return would mean the
check itself crashed, not a finding).
"""
from __future__ import annotations

from typing import Protocol, TypeAlias

import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import pcf  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from venv_spec import VenvSpec  # noqa: E402  # pylint: disable=import-error,wrong-import-position

# One value of a JSON settings file.
JsonValue: TypeAlias = dict | list | str | float | bool | None


# Allow override via env (Claude Code sets CLAUDE_PLUGIN_ROOT; consumer install → cache path, not dev source).
# Default fallback resolves to .../plugins/claude/lazycortex-python, the parent of this bin/.
# Single assignment so PLUGIN_ROOT reads as the module constant it is.
_env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
PLUGIN_ROOT = Path(_env_root).resolve() if _env_root else _BIN.parent


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

  RULES = (
    "lazy-python.style.md", "lazy-python.docstrings.md", "lazy-python.tests.md", "lazy-python.failing-tests.md",
  )

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Compare each consumer rule mirror against the plugin canon and aggregate severity.

    Returns:
      Finding dict with `severity` (PASS, WARN, or FAIL) and a `message` string.
    """
    # sort every rule into absent, drifted, or matching its canon
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

    # drift outranks absence; a clean pass means every mirror matches
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

    # guard: without a rules directory there is nothing to list or scan
    if not rules_dir.exists():
      return {"severity": "WARN", "message": "consumer .claude/rules/ does not exist — run /lazy-python.install"}

    # collect every reference path the mirrored rules cite
    cited: set[str] = set()
    for entry in sorted(os.listdir(rules_dir)):
      # guard: only the plugin's own mirrored rules cite reference paths
      if not fnmatch.fnmatch(entry, "lazy-python.*.md"):
        continue
      cited.update(self.PATTERN.findall((rules_dir / entry).read_text(encoding = "utf-8")))

    # an unresolved citation fails; citing nothing at all only warns
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
    ("rules/lazy-python.failing-tests.md", "failing-tests rule"),
    ("references/lazy-python.coding-guidelines.md", "coding canon"),
    ("references/lazy-python.documenting-guidelines.md", "documenting canon"),
    ("references/lazy-python.comment-guidelines.md", "comment canon"),
    ("references/lazy-python.testing-guidelines.md", "testing canon"),
    ("references/lazy-python.checking-guidelines.md", "checking canon"),
    ("references/lazy-python.guidelines-index.md", "index"),
    ("bin/chk", "chk aggregator"),
    ("bin/tst", "tst aggregator"),
    ("bin/cfg", "cfg venv configurator"),
    ("bin/_ensure_venv.sh", "venv resolver"),
    ("bin/_cfg_venv.sh", "shared venv configure logic"),
    ("bin/venv_spec.py", "venv requirement reader"),
    ("bin/pcf.py", "pcf checker"),
    ("bin/toi.py", "toi checker"),
    ("bin/pch.py", "pch checker"),
    ("bin/mypy_protected_access.py", "protected-access mypy plugin"),
    ("hooks/lazy-python.check-style.sh", "PostToolUse hook"),
    ("hooks/hooks.json", "PostToolUse hook manifest"),
    ("skills/lazy-python.check-style/SKILL.md", "check-style skill"),
    ("agents/lazy-python.docstring-writer.md", "docstring-writer agent"),
    ("agents/lazy-python.test-writer.md", "test-writer agent"),
    ("agents/lazy-python.code-reviewer.md", "code-reviewer agent"),
    ("agents/lazy-python.bug-hunter.md", "bug-hunter agent"),
    ("agents/lazy-python.contract-writer.md", "contract-writer agent"),
    ("agents/lazy-python.domain-writer.md", "domain-writer agent"),
    ("templates/pyproject-defaults.toml", "pyproject template"),
    ("templates/cfg-wrapper.sh", "cfg-py wrapper template"),
    ("templates/chk-wrapper.sh", "chk-py wrapper template"),
    ("templates/tst-wrapper.sh", "tst-py wrapper template"),
    ("templates/python/python-template.py", "python file template"),
    ("templates/python/init-template.py", "__init__.py file template"),
    ("templates/python/scaffold.entries.json", "scaffold manifest"),
    ("templates/mypy-protected-access-shim.py", "protected-access shim template"),
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
  Verify consumer `cli/cfg-py`, `cli/chk-py` and `cli/tst-py` are deployed, open with a shebang, and have
  substituted bin paths.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  WRAPPERS: tuple = ("cfg-py", "chk-py", "tst-py")
  PLACEHOLDER = re.compile(r'\{\{[A-Z_]+_BIN_PATH\}\}')

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Check every wrapper for presence, a leading shebang, and placeholder substitution.

    Returns:
      Finding dict with `severity` (PASS, WARN, or FAIL) and a `message` string.
    """
    # probe each wrapper: absent or shebang-less counts as missing, a leftover placeholder as broken
    bin_dir = self.consumer_dir / "cli"
    missing: list[str] = []
    broken: list[str] = []
    for name in self.WRAPPERS:
      wrapper = bin_dir / name
      if not wrapper.exists():
        missing.append(name)
        continue
      if not wrapper.read_text(encoding = "utf-8").startswith("#!"):
        missing.append(f"{name} (no shebang)")
        continue
      if self.PLACEHOLDER.search(wrapper.read_text(encoding = "utf-8")):
        broken.append(name)

    # a broken wrapper outranks a missing one
    if broken:
      return {"severity": "FAIL", "message": f"wrappers contain unsubstituted placeholders: {broken}"}
    if missing:
      return {"severity": "WARN", "message": f"wrappers missing or no shebang: {missing}"}
    return {"severity": "PASS", "message": "all wrappers deployed, shebang-led, and substituted"}


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

    # guard: no pyproject.toml at all, so no checker stack can be configured
    if not pyproject.exists():
      return {"severity": "FAIL", "message": "pyproject.toml not found in consumer root"}

    # guard: an unparseable pyproject.toml has no sections to look up
    try:
      data = tomllib.loads(pyproject.read_text(encoding = "utf-8"))
    except tomllib.TOMLDecodeError as error:
      return {"severity": "FAIL", "message": f"pyproject.toml is not valid TOML: {error}"}

    # collect the required sections the tool table lacks
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
    # mark each topic whose overlay is absent or opens with the wrong header
    overlay_dir = self.consumer_dir / "docs/guidelines"
    bad: list[str] = []
    for topic in self.TOPICS:
      overlay_file = overlay_dir / f"{topic}_guidelines.md"
      if not overlay_file.exists():
        bad.append(f"{topic} (missing)")
        continue

      # the header is the first non-empty line
      first_line = ""
      for line in overlay_file.read_text(encoding = "utf-8").splitlines():
        if line.strip():
          first_line = line
          break
      expected = self.HEADER_PATTERN.format(topic = topic)
      if not first_line.startswith(expected):
        bad.append(f"{topic} (wrong header)")

    # three or more bad overlays fail, fewer warn
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

    # guard: the mirrored rule file is absent, so the install never ran here
    if not rule.exists():
      return {
        "severity": "WARN",
        "message": f"{self.RULE_REL} not found — consumer has not run /lazy-python.install",
      }
    body = rule.read_text(encoding = "utf-8")
    if self.MARKER not in body:
      return {
        "severity": "WARN",
        "message": f"{self.MARKER!r} not found in {self.RULE_REL} — re-run /lazy-python.install",
      }

    # Domain(install.reconciliation):
    # # Scaffold registry entries must hold literal consumer paths
    # A scaffold registry entry is read as a literal string, never expanded as an environment
    # reference, so an entry that still names a shipped plugin location or an unresolved
    # placeholder never resolves for the consumer; only a path already rewritten to the
    # consumer's own tree at install time works.

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
    body = claude_md.read_text(encoding = "utf-8")
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

    # guard: an unparseable manifest has no hook entries to scan
    try:
      data = json.loads(manifest.read_text(encoding = "utf-8"))
    except json.JSONDecodeError as error:
      return {"severity": "FAIL", "message": f"{self.MANIFEST_REL} is not valid JSON: {error}"}

    # look for a PostToolUse entry that runs the check-style hook
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
  Read-only mirror of the venv resolution chk-py / tst-py apply before every run, including whether a project
  venv is current.

  Attributes:
    consumer_dir: Absolute path to the consumer repository root.
  """

  TOOLS: tuple = ("mypy", "pylint", "pytest", "ruff")
  PLUGINS: tuple = ("pytest_clarity", "pytest_sugar", "xdist")

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

    # guard: a missing or non-executable venv python cannot run the plugin import probe
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

    # guard: no pyproject.toml, so the key cannot be configured
    if not pyproject.exists():
      return ""
    try:
      data = tomllib.loads(pyproject.read_text(encoding = "utf-8"))
    except tomllib.TOMLDecodeError:
      return ""
    value = data.get("tool", {}).get("lazy-python", {}).get(key)

    # guard: key absent from the section, report it as unset
    if value is None:
      return ""
    if isinstance(value, bool):
      return "true" if value else "false"
    return str(value)

  def run(self) -> dict:
    """
    Walk the venv resolution order chk-py / tst-py follow and report venv readiness.

    A project venv counts as ready only when it carries the checker tools and was configured against the
    current `pyproject.toml`.

    Returns:
      Finding dict with `severity` (PASS or WARN) and a `message` string.
    """

    # Domain(install.reconciliation):
    # # Python environment resolution order
    # The tooling looks for a Python execution environment in a fixed order: an already
    # activated environment carrying the checker tools is used as it is; otherwise the
    # project's own environment — the explicitly configured one, or the project-local one
    # when none is configured — must be configured against the project's current
    # requirements. A missing or stale project environment is built or updated from the
    # project's requirements before the checks run, unless installing is forbidden there, in
    # which case the run fails and names the configure command. A found-but-incomplete
    # candidate is reported as broken rather than skipped in favor of a later one.

    # probe 1: $VIRTUAL_ENV
    virtual_env = os.environ.get("VIRTUAL_ENV", "")
    if virtual_env:
      venv = Path(virtual_env)
      if self._venv_has_tools(venv):
        return {"severity": "PASS", "message": f"$VIRTUAL_ENV venv satisfies probe-1 ({venv})"}
      return {"severity": "WARN", "message": f"$VIRTUAL_ENV venv missing tools ({venv})"}

    # probe 2: the target venv — [tool.lazy-python].venv when set, else <consumer>/.venv
    configured = self._read_pyproject_key("venv")
    target = Path(configured).expanduser() if configured else Path(".venv")
    if not target.is_absolute():
      target = self.consumer_dir / target
    if target.exists():
      if not self._venv_has_tools(target):
        return {"severity": "WARN", "message": f"project venv {target} is missing checker tools — run cfg-py"}
      if not self._venv_is_fresh(target):
        return {"severity": "WARN",
                "message": f"project venv {target} is stale (not configured against the current pyproject.toml)"
                           " — run cfg-py"}
      return {"severity": "PASS", "message": f"project venv {target} is configured and fresh"}

    # no project venv yet — chk-py / tst-py create it on first run unless opted out or uv is missing
    if self._read_pyproject_key("bootstrap-fallback") == "false":
      return {"severity": "WARN",
              "message": f"no project venv at {target} AND bootstrap-fallback = false — run cfg-py"}

    # guard: every create / install step goes through uv, so its absence makes the venv unbuildable
    if not shutil.which("uv"):
      return {"severity": "WARN",
              "message": "no project venv AND uv missing — neither cfg-py nor chk-py can build it"}

    # no venv yet, but nothing blocks cfg-py or the first chk-py from creating one
    return {"severity": "PASS", "message": f"no project venv yet; cfg-py or the first chk-py creates {target}"}

  def _venv_is_fresh(self, venv: Path) -> bool:
    """
    Tell whether a venv was configured against the consumer's current `pyproject.toml` requirements.

    Args:
      venv: Root directory of the venv.

    Returns:
      `True` when its recorded requirement fingerprint matches; `False` otherwise, including when
      `pyproject.toml` cannot be parsed.
    """

    # guard: an unparseable pyproject.toml leaves nothing to be fresh against
    try:
      spec = VenvSpec(project_dir = self.consumer_dir)
    except tomllib.TOMLDecodeError:
      return False
    return spec.is_fresh(venv)


# ----------------------------------------------------------------------------------------
class Check12DomainDictionary:
  """
  Verify a domain-groups dictionary exists once the sources carry `Domain(...)` blocks.

  Attributes:
    DOMAIN_RE: Pattern matching a `Domain(...)` marker comment in a source file.
    PRUNED_DIRS: Directory names never descended into while scanning for markers.
    consumer_dir: Absolute path to the consumer repository root.
  """

  DOMAIN_RE = re.compile(r'#\s*Domain\s*\(')
  PRUNED_DIRS = ("node_modules", "__pycache__")

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def _marked_sources(self) -> list[str]:
    """
    Collect the Python sources carrying at least one `Domain(...)` marker comment.

    Returns:
      Sorted list of repo-relative paths, empty when no source is marked.
    """
    # limit: walks the worktree instead of the tracked set, so an ignored .py counts too;
    # switch to `git ls-files` if generated Python ever starts carrying markers
    marked: list[str] = []
    for root, dirs, files in os.walk(self.consumer_dir):
      dirs[:] = [name for name in dirs if not name.startswith(".") and name not in self.PRUNED_DIRS]
      for name in files:
        # guard: only Python sources carry the marker this check counts
        if not name.endswith(".py"):
          continue
        source = Path(root) / name
        try:
          text = source.read_text(errors = "replace", encoding = "utf-8")
        # a source that cannot be read yields no marker; the audit reports on what it could read
        except OSError:
          continue
        if self.DOMAIN_RE.search(text):
          marked.append(str(source.relative_to(self.consumer_dir)))
    return sorted(marked)

  def run(self) -> dict:
    """
    Report whether the marked sources have a dictionary to resolve their groups against.

    Returns:
      Finding dict with `severity` (PASS or WARN) and a `message` string.
    """

    # Domain(wiki.domains):
    # # Domain dictionary becomes required only once knowledge is filed
    # A domain-groups dictionary is optional until at least one source in the project actually
    # carries a domain knowledge marker; only from that point does the dictionary's absence
    # become a finding, since before any marker exists there is nothing yet for a dictionary
    # to resolve groups against.

    dictionary = pcf.resolve_dictionary(self.consumer_dir)

    # a dictionary is present, so every group in code has something to resolve against
    if dictionary.exists():
      return {"severity": "PASS", "message": f"domain-groups dictionary present ({dictionary})"}

    # no dictionary — a finding only once the code actually files knowledge under groups
    marked = self._marked_sources()
    if not marked:
      return {"severity": "PASS", "message": "no Domain(...) blocks in the sources — no dictionary needed yet"}
    return {
      "severity": "WARN",
      "message": (f"{len(marked)} source(s) carry Domain(...) blocks but no dictionary at {dictionary} "
                  "— run /lazy-python.knowledge-sweep to build it"),
    }


# ----------------------------------------------------------------------------------------
class Check13MypyPlugin:
  """
  Audit check for the consumer's protected-access mypy plugin wiring and the currency of its deployed shim.

  Attributes:
    SHIM_REL: Repo-relative path of the shim the consumer's `[tool.mypy]` plugin entry names.
    SHIM_TEMPLATE_REL: Plugin-relative path of the shipped shim the deployed copy must equal.
    consumer_dir: Absolute path to the consumer repository root.
  """

  SHIM_REL = "cli/mypy/protected_access.py"
  SHIM_TEMPLATE_REL = "templates/mypy-protected-access-shim.py"

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  def run(self) -> dict:
    """
    Check the `[tool.mypy]` plugin entry, the shim's presence, and the shim's currency.

    Returns:
      Finding dict with `severity` (PASS, WARN, or FAIL) and a `message` string.
    """
    pyproject = self.consumer_dir / "pyproject.toml"

    # guard: no pyproject.toml at all, so no mypy configuration can name the plugin
    if not pyproject.exists():
      return {"severity": "FAIL", "message": "pyproject.toml not found in consumer root"}

    # guard: a file that does not parse carries no readable mypy configuration
    try:
      data = tomllib.loads(pyproject.read_text(encoding = "utf-8"))
    except tomllib.TOMLDecodeError as error:
      return {"severity": "FAIL", "message": f"pyproject.toml is not valid TOML: {error}"}

    # the `[tool.mypy]` table, or None when `tool` itself is not a table
    tool = data.get("tool", {})
    mypy = tool.get("mypy", {}) if isinstance(tool, dict) else None

    # guard: a `tool` or `tool.mypy` that is not a table cannot carry a plugin list, and install cannot merge into it
    if not isinstance(mypy, dict):
      return {
        "severity": "WARN",
        "message": f'`tool` / `tool.mypy` in pyproject.toml is not a table — make [tool.mypy] a table '
                   f'with plugins = ["{self.SHIM_REL}"] by hand',
      }

    # the plugin entries as mypy reads them; mypy also reads `plugins` as one comma-separated string
    plugins = mypy.get("plugins", [])
    listed = [entry.strip() for entry in plugins.split(",")] if isinstance(plugins, str) else plugins

    # guard: install extends only a list, so any other form without the shim is the operator's to edit
    if not isinstance(plugins, list) and (not isinstance(listed, list) or self.SHIM_REL not in listed):
      return {
        "severity": "WARN",
        "message": f'[tool.mypy] `plugins` is not a list and does not name "{self.SHIM_REL}" — add it by hand '
                   f'(/lazy-python.install edits only a list)',
      }

    # a `plugins` list without the shim leaves mypy blind to it
    if self.SHIM_REL not in listed:
      return {
        "severity": "WARN",
        "message": f'[tool.mypy] `plugins` does not list "{self.SHIM_REL}" — run /lazy-python.install',
      }

    # the deployed shim the plugin entry names
    shim = self.consumer_dir / self.SHIM_REL

    # guard: the plugin entry points at a file that was never deployed
    if not shim.exists():
      return {"severity": "WARN", "message": f"{self.SHIM_REL} is missing — run /lazy-python.install"}

    # the shim is deployed verbatim, so any byte difference from the template is drift
    if shim.read_bytes() != (PLUGIN_ROOT / self.SHIM_TEMPLATE_REL).read_bytes():
      return {
        "severity": "WARN",
        "message": f"{self.SHIM_REL} is stale against the plugin template — run /lazy-python.install",
      }

    # wired and current
    return {"severity": "PASS", "message": f"protected-access plugin wired and {self.SHIM_REL} current"}


# ----------------------------------------------------------------------------------------
class Check14WorktreeVenv:
  """
  Audit check that isolated job worktrees of a `workspace: branch` expert can reach the project venv.

  Attributes:
    SETTINGS_REL: Repo-relative path of the tracked settings file.
    LOCAL_REL: Repo-relative path of the local settings overlay.
    consumer_dir: Absolute path to the consumer repository root.
  """

  SETTINGS_REL = ".claude/lazy.settings.json"
  LOCAL_REL = ".claude/lazy.settings.local.json"

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir

  @classmethod
  def _merge(cls, base: JsonValue, overlay: JsonValue) -> JsonValue:
    """
    Merge a local-overlay value onto a tracked one.

    Objects merge key by key, lists keep the tracked entries and append the overlay's new ones, and any other overlay
    value replaces the tracked one.

    Args:
      base: The tracked value.
      overlay: The local-overlay value laid on top of it.

    Returns:
      The merged value.
    """

    # Domain(settings.versioning):
    # # Overlay onto tracked settings by value type
    # Effective settings come from two layers: the committed, shared file and a personal overlay kept beside
    # it. The overlay is laid on the shared file by the type of each value, so it only has to state what it
    # changes. Objects combine key by key, recursively, and a key present in only one layer is kept as it is.
    # A list keeps every shared entry in its original order and appends only the overlay entries not already
    # there. Any other overlay value, a scalar or a value of a different type from the shared one, replaces
    # the shared value.

    # objects merge key by key, lists append the overlay's new entries, anything else is replaced
    if isinstance(base, dict) and isinstance(overlay, dict):
      return cls._merge_objects(base, overlay)
    if isinstance(base, list) and isinstance(overlay, list):
      return base + [ item for item in overlay if item not in base ]
    return overlay

  @classmethod
  def _merge_objects(cls, base: dict, overlay: dict) -> dict:
    """
    Merge a local-overlay object onto a tracked one, key by key.

    Args:
      base: The tracked object.
      overlay: The local-overlay object laid on top of it.

    Returns:
      A new object holding every tracked key, each overlay key merged onto its tracked value or added.
    """
    merged = { **base }

    # each overlay key merges onto the tracked value it shares a key with, or joins as new
    for key, value in overlay.items():
      merged[key] = cls._merge(merged[key], value) if key in merged else value
    return merged

  @staticmethod
  def _names_path(cmd: str, link: str, venv: Path) -> bool:
    """
    Tell whether a shell command names a venv path as one of its words.

    Args:
      cmd: The shell command.
      link: The venv's repo-relative path.
      venv: The venv's absolute path.

    Returns:
      True when a word of the command, normalised, equals the relative or the absolute venv path.
    """
    # a command shlex cannot split, such as one with an unclosed quote, is split on whitespace instead
    try:
      words = shlex.split(cmd)
    except ValueError:
      words = cmd.split()

    # a word right after `-m` is a Python module name, never a path, so it is left out of the comparison
    paths = [ word for index, word in enumerate(words) if word and ( index == 0 or words[index - 1] != "-m" ) ]

    # each word is compared as a path, so `./.venv/` names `.venv` while `.venv-tools` does not
    targets = { link, os.path.normpath(venv) }
    return any(os.path.normpath(word) in targets for word in paths)

  def _read_settings(self) -> dict:
    """
    Read the tracked settings file with its local overlay merged on top.

    Returns:
      The effective settings; an empty mapping when neither file exists.

    Raises:
      ValueError: If a layer is not valid JSON.
    """
    merged: dict = {}
    for rel in ( self.SETTINGS_REL, self.LOCAL_REL ):
      path = self.consumer_dir / rel

      # guard: an absent layer declares nothing
      if not path.is_file():
        continue

      # the layer's content; an empty file reads as an empty object
      data = json.loads(path.read_text(encoding = "utf-8") or "{}")

      # a layer that is a JSON object merges onto what the layers before it gave
      if isinstance(data, dict):
        merged = self._merge_objects(merged, data)
    return merged

  def run(self) -> dict:
    """
    Report whether a branch expert's worktrees miss the project venv or cannot reach it.

    A venv given as a relative path outside the checkout is reported with the fix of making it absolute; a venv
    inside the checkout is reported unless a shared link carries it or a shell word of the bootstrap command, once
    normalised, equals its relative or absolute path.

    Returns:
      Finding dict with `severity` (PASS or WARN) and a `message` string.
    """

    # Domain(install.reconciliation):
    # # Venv reach of isolated job worktrees
    # An expert that runs its jobs in an isolated working copy needs the project venv there as much as the
    # operator's checkout does. A venv at an absolute place outside the checkout is reached by its
    # configured path from any copy; a relative location that climbs out of the checkout lands elsewhere
    # in every copy and no sharing can carry it. A venv inside the checkout reaches a copy only when it is
    # listed among the paths shared as links, or when the preparation command names that path as a word
    # of its own — a longer word that merely contains it builds something else, and the word that follows
    # a module switch names a module, never a path. With neither, the checker runners break inside every
    # such job.

    # guard: settings that do not parse name no experts and no worktree environment
    try:
      settings = self._read_settings()
    except ValueError as error:
      return {"severity": "WARN", "message": f"{self.SETTINGS_REL} or its local overlay is not valid JSON: {error}"}

    # the experts whose jobs run in a worktree, in name order
    experts = settings.get("experts")
    branch_experts = sorted(
      name for name, entry in ( experts.items() if isinstance(experts, dict) else () )
      if isinstance(entry, dict) and entry.get("workspace") == "branch"
    )

    # guard: no expert runs in a worktree, so no worktree needs the venv
    if not branch_experts:
      return {"severity": "PASS", "message": "no expert with workspace: branch — no job runs in a worktree"}

    # guard: without a readable pyproject.toml the venv location is unknown
    try:
      spec = VenvSpec(project_dir = self.consumer_dir)
    except tomllib.TOMLDecodeError as error:
      return {"severity": "WARN", "message": f"pyproject.toml is not valid TOML, venv location unknown: {error}"}

    # the venv's repo-relative path, or None when it lies outside the checkout
    link = spec.worktree_link()

    # a relative venv climbing out of the checkout names another place in every worktree, and no link can carry it
    if spec.is_unreachable_from_worktrees():
      return {
        "severity": "WARN",
        "message": (f"workspace: branch expert(s) {', '.join(branch_experts)} run in job worktrees, which resolve "
                    f"the relative venv {spec.target_venv()} against their own root — make "
                    "[tool.lazy-python].venv an absolute path"),
      }

    # an absolute venv outside the checkout is reached from every worktree by its configured path
    if link is None:
      return {"severity": "PASS", "message": f"project venv {spec.target_venv()} lies outside the checkout"}

    # the effective git block: its links, and its bootstrap command
    daemon = settings.get("daemon")
    git = daemon.get("git") if isinstance(daemon, dict) else None
    git = git if isinstance(git, dict) else {}
    entries = git.get("worktree_links")
    links = {Path(entry).as_posix() for entry in entries if isinstance(entry, str) and entry} \
      if isinstance(entries, list) else set()
    cmd = git.get("worktree_bootstrap_cmd")

    # the bootstrap command names the venv only by a shell word that is the venv path itself
    named = isinstance(cmd, str) and self._names_path(cmd, link, spec.target_venv())

    # the venv is carried as a link, or the bootstrap command names it
    if link in links or named:
      return {
        "severity": "PASS",
        "message": f"project venv {link} reaches the job worktrees of {', '.join(branch_experts)}",
      }
    return {
      "severity": "WARN",
      "message": (f"workspace: branch expert(s) {', '.join(branch_experts)} run in job worktrees, but project venv "
                  f"{link} "
                  "is in neither daemon.git.worktree_links nor daemon.git.worktree_bootstrap_cmd — "
                  "re-run /lazy-python.install"),
    }


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
    "check12": Check12DomainDictionary,
    "check13": Check13MypyPlugin,
    "check14": Check14WorktreeVenv,
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
