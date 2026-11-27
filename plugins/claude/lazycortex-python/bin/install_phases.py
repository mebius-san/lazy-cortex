"""
Install phase implementations for /lazy-python.install.

CLI: `python3 install_phases.py phase<N> <consumer_repo_dir>` runs the named phase
against the consumer repo. Phases are idempotent; safe to re-run.

Phases:
  Numbered phases cover the consumer's rules, tool wrappers, pyproject checker sections, overlay guidelines,
  expert registration and virtual environments; each phase's own docstring states its effect.

Scaffold-template sync and check-style hook registration are not phases: the install skill runs the core CLI
verb `scaffold sync-plugin` for the templates, and the hook registers itself from the plugin's
`hooks/hooks.json` manifest.
"""
from __future__ import annotations

from typing import Protocol

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from functools import partial
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from toml_array import append_to_array  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import python_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
from venv_spec import VenvSpec  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# Location of the plugin tree (this file lives at .../bin/install_phases.py)
# Allow override via env (Claude Code sets CLAUDE_PLUGIN_ROOT; consumer install → cache path, not dev source).
# Default fallback resolves to .../plugins/claude/lazycortex-python, the parent of this bin/.
# Single assignment so PLUGIN_ROOT reads as the module constant it is.
_env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
PLUGIN_ROOT = Path(_env_root).resolve() if _env_root else _BIN.parent


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
  Install phase that mirrors the plugin's shipped rule files into the consumer's `.claude/rules/`
  directory.

  Responsibilities:
    - Write every shipped rule file to the consumer's rules directory and print a JSON receipt
      naming each rule's outcome.

  Guarantees:
    - Leaves any consumer rule file not shipped by the plugin untouched.
    - Verifies each write by re-reading the target before reporting a successful outcome.

  Attributes:
    consumer_dir: Root directory of the consumer repository being installed into.
    source_dir: Directory holding the plugin's shipped rule files.
    target_dir: Consumer's rules directory that receives the mirrored files.
  """

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.source_dir: Path = PLUGIN_ROOT / "rules"
    self.target_dir: Path = consumer_dir / ".claude/rules"

  def run(self) -> int:
    """
    Mirror every shipped rule into the consumer's rules directory.

    Guarantees:
      - Reports a rule as installed or refreshed only after its target has been read back and found to hold
        the shipped bytes; a write that does not verify is reported as failed and the run returns 1.

    Notes:
      - Prints a JSON receipt to stdout mapping each rule filename to `installed`, `unchanged`,
        `refreshed`, or `failed`.

    Returns:
      0 when every rule verified successfully, 1 when at least one write failed verification.
    """

    # Contract:
    # Only files shipped by the plugin under its rules directory are ever written to the
    # consumer's rules directory; any other file already present there is left untouched.

    # Contract:
    # A rule is reported as installed or refreshed only after its target has been read back and
    # found to hold the shipped bytes; a write that does not verify is reported as failed, and
    # the run then returns 1.

    self.target_dir.mkdir(parents = True, exist_ok = True)
    shipped = sorted(name for name in os.listdir(self.source_dir) if name.endswith(".md"))
    states = { name: self._mirror(name) for name in shipped }
    print(json.dumps({ "phase": "phase1", "rules": states }, indent = 2))

    # an unverified write must not read as a successful mirror, so it decides the exit code
    if "failed" in states.values():
      return 1
    return 0

  def _mirror(self, name: str) -> str:
    """
    Reconcile a single shipped rule with its target in the consumer's rules directory.

    Notes:
      - Overwrites the target file when its contents differ from the shipped rule.

    Args:
      name: Filename of the shipped rule.

    Returns:
      One of `installed`, `unchanged`, `refreshed`, `failed`.
    """

    # Domain(install.reconciliation):
    # # Shipped-file reconciliation states
    # A file the plugin ships is fully install-owned: reconciliation never blends shipped
    # and existing content, it either leaves a byte-identical file untouched or replaces it
    # wholesale. The three settled outcomes — freshly created, already identical, replaced
    # because it drifted — are distinct from a failure outcome that only fires when a write
    # does not actually land: the target is read back after writing, and any mismatch there
    # downgrades an apparently completed install step to a failure instead of reporting
    # success on unverified disk state.

    source = self.source_dir / name
    target = self.target_dir / name
    shipped = source.read_bytes()

    # an absent or stale target is replaced wholesale; only identical bytes are left alone
    if not target.exists():
      state = "installed"
    elif target.read_bytes() == shipped:
      return "unchanged"
    else:
      state = "refreshed"
    shutil.copyfile(source, target)

    # the write is only an outcome once the target actually holds the shipped bytes
    if target.read_bytes() != shipped:
      return "failed"
    return state


# ----------------------------------------------------------------------------------------
class Phase2Wrappers:
  """
  Install phase that writes byte-for-byte copies of the `cfg-py`, `chk-py` and `tst-py` wrapper scripts, the
  `lazy_python_locator.py` they and the shim locate the plugin through, and the `mypy/protected_access.py` plugin
  shim into the consumer's `cli/` directory and ensures `.venv/` is listed in the consumer's `.gitignore`.

  Guarantees:
    - Leaves a `.gitignore` that already ignores `.venv` byte-for-byte untouched.

  Attributes:
    consumer_dir: Root directory of the consumer repository.
    target_dir: Directory receiving the wrapper scripts, the plugin locator and the shim.
    gitignore: The consumer's `.gitignore` file.
  """

  WRAPPERS = (
    ("templates/cfg-wrapper.sh", "cfg-py"),
    ("templates/chk-wrapper.sh", "chk-py"),
    ("templates/tst-wrapper.sh", "tst-py"),
    ("templates/mypy-protected-access-shim.py", "mypy/protected_access.py"),
    ("bin/python_locator.py", "lazy_python_locator.py"),
  )

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.target_dir: Path = consumer_dir / "cli"
    self.gitignore: Path = consumer_dir / ".gitignore"

  def run(self) -> int:
    """
    Write the `cfg-py`, `chk-py` and `tst-py` wrappers, the plugin locator and the `mypy/protected_access.py` shim
    to the consumer's `cli/` directory and update `.gitignore`.

    Guarantees:
      - Leaves a `.gitignore` that already ignores `.venv` byte-for-byte untouched.

    Returns:
      0 on success.
    """

    # Contract:
    # A `.gitignore` that already ignores `.venv` is left byte-for-byte untouched; the
    # ignore line is appended only when genuinely absent.

    self.target_dir.mkdir(parents = True, exist_ok = True)
    for source_rel, target_name in self.WRAPPERS:
      # The shipped files are path-agnostic: deployed verbatim, they resolve the active
      # plugin install at exec time through the deployed locator. No path is substituted here — that is the
      # whole point (a baked path goes stale on the next plugin update). Bytes, not text, so no
      # host turns LF into CRLF: bash rejects a CRLF script and the audit compares the shim and the locator bytewise.
      target = self.target_dir / target_name
      target.parent.mkdir(parents = True, exist_ok = True)
      target.write_bytes((PLUGIN_ROOT / source_rel).read_bytes())
    self._ensure_venv_gitignored()
    return 0

  def _ensure_venv_gitignored(self) -> None:
    """
    Append `.venv/` to the consumer's `.gitignore` when absent.
    """

    # Domain(install.reconciliation):
    # # Gitignore line reconciliation
    # Once a line is present anywhere in the consumer's ignore file, install leaves that file
    # byte-for-byte untouched — presence is an exact trimmed-line match, not a content search,
    # so a broader pattern that happens to also ignore the same path still triggers a fresh
    # append. When the line is genuinely absent, it is appended after a trailing newline is
    # guaranteed on any prior content, never inserted elsewhere and never used to justify
    # rewriting a line the consumer already wrote.

    existing = self.gitignore.read_text(encoding = "utf-8") if self.gitignore.exists() else ""

    # guard: already ignored → leave the file byte-for-byte
    if any(line.strip() in (".venv", ".venv/") for line in existing.splitlines()):
      print("gitignore-already-present")
      return
    prefix = existing if existing == "" or existing.endswith("\n") else existing + "\n"
    self.gitignore.write_text(prefix + ".venv/\n", encoding = "utf-8")
    print("gitignore-ensured")


# ----------------------------------------------------------------------------------------
class HomeWrappersPhase:
  """
  Install phase that writes `cfg-py`, `chk-py` and `tst-py` into `$HOME/.local/bin`.

  These are the only files this plugin ever marks executable: they live outside every
  vault, so no mode-blind git client can strip the bit, and they find the repo's own
  `cli/` wrapper from the caller's directory.

  Guarantees:
    - Reasserts the executable bit on every wrapper every run, even when its content
      is already current.

  Attributes:
    consumer_dir: Root directory of the consumer repository.
    plugin_root: Root directory of the plugin shipping the wrapper templates.
    target_dir: Directory receiving the wrappers.
  """

  TEMPLATES: tuple = (
    ("cfg-home-wrapper.sh", "cfg-py"),
    ("chk-home-wrapper.sh", "chk-py"),
    ("tst-home-wrapper.sh", "tst-py"),
  )

  def __init__(self, *, consumer_dir: Path) -> None:
    # consumer_dir is unused — the home wrappers install to a fixed, repo-independent target
    self.consumer_dir: Path = consumer_dir
    self.plugin_root: Path = PLUGIN_ROOT

    # `HOME` is honoured so tests can redirect the target
    self.target_dir: Path = Path(os.environ.get("HOME") or Path.home()) / ".local" / "bin"

  def run(self) -> int:
    """
    Write every wrapper, byte-verified, and set the exec bit on the written copies.

    Returns:
      0 on success.
    """
    self.target_dir.mkdir(parents = True, exist_ok = True)
    receipt: dict = {}
    for template, name in self.TEMPLATES:
      # the shipped wrapper and where its copy goes
      src = self.plugin_root / "templates" / template
      dst = self.target_dir / name
      body = src.read_bytes()

      # an absent copy is installed, a differing one refreshed, an identical one left as it is
      state = "unchanged"
      if not dst.exists():
        state = "installed"
      elif dst.read_bytes() != body:
        state = "refreshed"
      if state != "unchanged":
        dst.write_bytes(body)

      # Contract:
      # The executable bit is reasserted on every wrapper every run, even when its
      # content is already current, so a git client that stripped it is corrected without
      # requiring a content change.

      # apply the exec bit unconditionally, restoring it if a git client stripped it
      dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
      receipt[name] = state
    print(json.dumps({ "phase": "phase2b", "wrappers": receipt }, indent = 2))
    return 0


# ----------------------------------------------------------------------------------------
class Phase3Pyproject:
  """
  Install phase that bootstraps the consumer's `pyproject.toml` with checker-stack sections
  from the template.

  Adds the checker-stack sections (with their nested sub-tables) that the consumer's file is missing,
  and completes the missing sub-keys of any such section the consumer already has. A `[tool.mypy]`
  `plugins` list the consumer already has gains the template's plugin entries it lacks, after the
  consumer's own.

  Guarantees:
    - Never overwrites a sub-key the consumer has already set; a `plugins` list keeps every
      consumer entry, in order.
    - Never writes a file that does not parse as TOML.
    - Idempotent: re-running leaves the file byte-identical once every checker section
      carries every template sub-key and the `plugins` value lists every template entry or
      cannot be edited in place.

  Notes:
    - An edit that cannot be made safely — the section has no header line of its own, the
      `plugins` value is not a list, or the edited file would not parse to the intended
      result — is skipped, and a line starting with `manual-edit:` names the edit to make by
      hand.

  Attributes:
    consumer_dir: Root directory of the consumer repository being installed into.
    target: Path to the consumer's `pyproject.toml` file.
    template: Path to the plugin's template file supplying the checker-stack sections.
  """

  # Always-deployed checker sections. pch is added only when PyCharm is present —
  # it spins up a headless PyCharm and is meaningless without it, so it is deployed
  # only when the install skill sets the matching env flag (see OPTIONAL_SECTIONS + run()).
  CHECKER_SECTIONS = ("pcf", "toi", "pytest", "mypy", "protected_access", "pylint", "ruff")
  OPTIONAL_SECTIONS = {"pch": "LAZY_PYTHON_ENABLE_PCH"}

  # The checker section and key whose list install extends instead of leaving alone
  PLUGINS_SECTION = "mypy"
  PLUGINS_KEY = "plugins"

  # Matches a top-level `key = ...` line (no leading indent) starting a new key's block;
  # an indented continuation line (array/table element) is not a new key.
  _KEY_LINE = re.compile(r"^([A-Za-z0-9_-]+)\s*=")

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.target: Path = consumer_dir / "pyproject.toml"
    self.template: Path = PLUGIN_ROOT / "templates/pyproject-defaults.toml"

  def run(self) -> int:
    """
    Merge missing checker sections and sub-keys from the template into the consumer's
    `pyproject.toml`.

    Returns:
      0 on success.
    """

    # Domain(install.reconciliation):
    # # Checker-configuration section completion
    # A checker-stack section the consumer's project file already declares is never replaced
    # outright; only the sub-keys it is still missing are inserted into it, leaving every
    # sub-key value the consumer already set exactly as configured. A section that is entirely
    # absent is instead appended as a whole verbatim block, preserving the shipped defaults'
    # own comments and formatting. Both paths converge on the same rule: whatever the consumer
    # has explicitly written, at any granularity, always outranks the shipped default. The one
    # value install extends rather than leaves alone is the list of type-checker plugins: a
    # plugin the product needs must load even beside the consumer's own, so the shipped entry
    # joins the end of that list and every consumer entry keeps its place. Where an edit cannot
    # be made without guessing at the consumer's layout, nothing is written and the operator is
    # told which edit to make by hand.

    # the shipped defaults every merge below draws from
    template_text = self.template.read_text(encoding = "utf-8")

    # a repo with no pyproject yet gets a minimal [project] stanza to merge onto
    if self.target.exists():
      existing_text = self.target.read_text(encoding = "utf-8")
    else:
      existing_text = '[project]\nname = "consumer"\nversion = "0.1.0"\n'
    original_text = existing_text

    # the consumer's own [tool] sections decide what still has to be merged in
    existing_data = tomllib.loads(existing_text)
    existing_tool = existing_data.get("tool", {})

    # guard: a `tool` key that is not a table leaves nowhere to merge checker sections into
    if not isinstance(existing_tool, dict):
      print("manual-edit: `tool` in pyproject.toml is not a table — merge the checker sections by hand")
      return 0

    # Always-on sections, plus any opt-in section whose env flag is set by the skill.
    wanted = list(self.CHECKER_SECTIONS)
    wanted += [s for s, env in self.OPTIONAL_SECTIONS.items() if os.environ.get(env)]

    # Determine which wanted sections are MISSING under [tool] in the consumer file.
    missing = [s for s in wanted if s not in existing_tool]

    # Contract:
    # A checker section already present in the consumer's file keeps every sub-key value
    # the consumer has already set; only sub-keys still missing from that section are added.
    # The one value extended rather than kept is the `[tool.mypy]` `plugins` list, under the
    # contract that follows.

    # A section already present may still be a partial write from an older install — complete
    # its own missing sub-keys (never touching a sub-key the consumer already set), in place.
    for section_name in wanted:
      # guard: a wholly-missing section is handled by the whole-block append below
      if section_name in missing:
        continue
      existing_section = existing_tool[section_name]

      # guard: a non-mapping override (rare) has no sub-keys to complete — leave it alone
      if not isinstance(existing_section, dict):
        continue
      template_keys = self._extract_own_keys(template_text, section_name)
      missing_keys = [k for k in template_keys if k not in existing_section]

      # guard: every template sub-key is already present — nothing to inject
      if not missing_keys:
        continue
      injected = "\n".join(template_keys[k] for k in missing_keys)
      existing_text = self._try_edit(
        existing_text, self._insert_after_header(existing_text, section_name, injected),
        partial(self._verify_section_keys, section_name, missing_keys),
        f"[tool.{section_name}] — add the missing keys {', '.join(missing_keys)} by hand",
      )

    # Contract:
    # A `plugins` list the consumer already set keeps every entry in its order; the template's
    # missing entries are appended after them, never replacing or reordering one.

    # a consumer `plugins` list gains the shipped plugin it does not list yet
    existing_text = self._extend_plugins(existing_text, template_text)

    # append each missing section's raw template block (comments + formatting preserved), so
    # the consumer's own content stays byte-identical
    for section_name in missing:
      block = self._extract_section_block(template_text, section_name)
      if block:
        existing_text = self._try_edit(
          existing_text, existing_text.rstrip() + "\n\n" + block + "\n",
          partial(self._verify_section_keys, section_name, []),
          f"[tool.{section_name}] — copy the section from the plugin's pyproject-defaults.toml by hand",
        )

    # Contract:
    # Re-running this phase leaves `pyproject.toml` byte-identical to its prior state once every
    # checker section carries every template sub-key and the `[tool.mypy]` `plugins` value already
    # lists every template entry, or cannot be edited in place — then the `manual-edit:` line is
    # printed and nothing is written.

    # guard: nothing changed and the file already exists — leave it byte-identical
    if existing_text == original_text and self.target.exists():
      return 0

    # Contract:
    # The `pyproject.toml` written here always parses as TOML.

    # write the merged document
    self.target.write_text(existing_text, encoding = "utf-8")
    return 0

  def _extend_plugins(self, toml_text: str, template_text: str) -> str:
    """
    Append the template's `[tool.mypy]` plugin entries to the consumer's existing `plugins` list.

    Notes:
      - A section without a `plugins` key is left to sub-key completion.
      - A `plugins` value that is not a list, or a list that cannot be extended in place, is
        left as written and a `manual-edit:` line names the entries to add by hand.

    Args:
      toml_text: Consumer document to extend.
      template_text: Template document supplying the plugin entries.

    Returns:
      `toml_text` with the missing entries appended, or unchanged when none is missing or the
      list cannot be extended safely.
    """
    section = tomllib.loads(toml_text).get("tool", {}).get(self.PLUGINS_SECTION)

    # guard: without a `plugins` key, sub-key completion adds the whole template value
    if not isinstance(section, dict) or self.PLUGINS_KEY not in section:
      return toml_text

    # the consumer's value as written; mypy also reads it as one comma-separated string whose entries count as listed
    current = section[self.PLUGINS_KEY]
    listed = [entry.strip() for entry in current.split(",")] if isinstance(current, str) else current

    # the shipped entries the consumer does not list yet
    absent = [
      entry for entry in tomllib.loads(template_text)["tool"][self.PLUGINS_SECTION][self.PLUGINS_KEY]
      if not isinstance(listed, list) or entry not in listed
    ]

    # guard: every shipped entry is already listed
    if not absent:
      return toml_text

    # the hand edit to name whenever the list cannot be extended in place
    manual = f"[tool.{self.PLUGINS_SECTION}] {self.PLUGINS_KEY} — add {', '.join(map(json.dumps, absent))} by hand"

    # guard: only a list is extended in place; a string or any other value is the operator's to edit
    if not isinstance(current, list):
      print(f"manual-edit: {manual}")
      return toml_text

    # the edit must change nothing but the list, which must read as the old entries plus the new
    expected = tomllib.loads(toml_text)
    expected["tool"][self.PLUGINS_SECTION][self.PLUGINS_KEY] = current + absent
    return self._try_edit(
      toml_text, append_to_array(toml_text, self.PLUGINS_SECTION, self.PLUGINS_KEY, values = absent),
      expected.__eq__, manual,
    )

  @staticmethod
  def _try_edit(before: str, after: str, check: Callable[[dict], bool], manual: str) -> str:
    """
    Keep an edit only when it changed the document and the result parses to what was intended.

    Notes:
      - A rejected edit prints `manual-edit: <manual>` to stdout.

    Args:
      before: Document before the edit.
      after: Document after the edit.
      check: Predicate the parsed edited document must satisfy.
      manual: Description of the edit for the operator to make by hand.

    Returns:
      `after` when the edit is accepted, otherwise `before`.
    """
    try:
      accepted = after != before and check(tomllib.loads(after))
    # a parse error or a missing key both mean the edit did not land as intended
    except (tomllib.TOMLDecodeError, KeyError, TypeError):
      accepted = False

    # a rejected edit is never written; the operator is told what to do instead
    if not accepted:
      print(f"manual-edit: {manual}")
      return before
    return after

  @staticmethod
  def _verify_section_keys(top_name: str, keys: list[str], data: dict) -> bool:
    """
    Verify that a parsed document has a `[tool.<top_name>]` table carrying the given keys.

    Args:
      top_name: Name of the top-level tool section.
      keys: Keys the section must carry.
      data: Parsed TOML document.

    Returns:
      True when the section is a table holding every key.

    Raises:
      KeyError: The document has no `tool` table or no `[tool.<top_name>]` entry.
      TypeError: `tool` is not a table.
    """
    section = data["tool"][top_name]
    return isinstance(section, dict) and all(key in section for key in keys)

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

  @classmethod
  def _extract_own_keys(cls, toml_text: str, top_name: str) -> dict[str, str]:
    """
    Map each key defined directly under `[tool.<top_name>]` to its raw source text, up to
    the first nested `[tool.<top_name>.*]` sub-table.

    Args:
      toml_text: Full TOML document to scan.
      top_name: Name of the top-level tool section whose own keys are extracted.

    Returns:
      An ordered mapping of key name to its raw text, including any multi-line array
      continuations. A leading comment or blank line ahead of the first key is dropped.
    """
    header = f"[tool.{top_name}]"
    out: dict[str, str] = {}
    in_section = False
    current_key: str | None = None
    current_lines: list[str] = []
    for line in toml_text.splitlines():
      stripped = line.strip()
      if stripped == header:
        in_section = True
        continue

      # guard: not yet inside the target section — skip until the header line
      if not in_section:
        continue

      # a nested sub-table or the next top-level section ends this section's own keys
      if stripped.startswith("["):
        break
      match = cls._KEY_LINE.match(line)
      if match:
        if current_key is not None:
          out[current_key] = "\n".join(current_lines).rstrip()
        current_key = match.group(1)
        current_lines = [line]
      elif current_key is not None:
        current_lines.append(line)
    if current_key is not None:
      out[current_key] = "\n".join(current_lines).rstrip()
    return out

  @classmethod
  def _insert_after_header(cls, toml_text: str, top_name: str, injected: str) -> str:
    """
    Splice raw key lines into a TOML document directly after a top-level tool section's
    header line.

    Args:
      toml_text: Full TOML document to splice into.
      top_name: Name of the top-level tool section whose header is the insertion point.
      injected: Raw key-line text to insert immediately after the header.

    Returns:
      `toml_text` with `injected` spliced in, or unchanged when the header is not found.
    """
    header = f"[tool.{top_name}]"
    lines = toml_text.splitlines(keepends = True)
    for i, line in enumerate(lines):
      if line.strip() == header:
        insert_at = i + 1
        return "".join(lines[:insert_at]) + injected + "\n" + "".join(lines[insert_at:])
    return toml_text


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
  Install phase that creates per-topic guideline overlay stub files under the
  consumer's `docs/guidelines/python/` directory.

  Guarantees:
    - Never overwrites an overlay file the consumer has already created for a topic.
  """

  TOPICS = ("coding", "documenting", "testing", "checking")

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.target_dir: Path = consumer_dir / "docs/guidelines/python"

  def run(self) -> int:
    """
    Write a stub overlay file for each topic that does not already exist.

    Returns:
      0 on success.
    """
    self.target_dir.mkdir(parents = True, exist_ok = True)
    for topic in self.TOPICS:
      target = self.target_dir / f"{topic}_guidelines.md"

      # Contract:
      # An overlay file the consumer has already created for a topic is never overwritten
      # by this phase, regardless of its contents.

      # guard: never clobber a consumer-authored overlay
      if target.exists():
        continue
      target.write_text(self._stub_content(topic), encoding = "utf-8")
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
class Phase6EnvSource:
  """
  Install phase that records `python.env_source` in the consumer's `lazy.settings.json`
  when the repo ships a recognised environment-bootstrap script.

  `python.env_source` names a shell script that `chk-py` / `tst-py` source after the venv is
  active, so a project that exports secret paths or provider credentials from its own wrapper
  keeps working under the plugin runners.

  Guarantees:
    - Never overwrites a `python.env_source` value already on record.
    - Auto-records a detected script only when exactly one candidate is found; multiple
      candidates are reported without being recorded.

  Notes:
    - The outcome is reported on stdout as a status word, followed by the recorded path or the candidate list
      when one applies; an explicit choice passed through
      `LAZY_PYTHON_ENV_SOURCE` is recorded in place of detection.

  Attributes:
    consumer_dir: Root directory of the consumer repository being installed into.
    settings: Path to the consumer's `.claude/lazy.settings.json` file.
  """

  CANDIDATES = ("cli/env", ".env.sh", "scripts/env.sh")
  OVERRIDE_ENV = "LAZY_PYTHON_ENV_SOURCE"

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.settings: Path = consumer_dir / ".claude/lazy.settings.json"

  def run(self) -> int:
    """
    Record `python.env_source` per the phase's decision rule and emit an outcome word.

    Returns:
      0 always; a missing or unwritten value is a benign no-op, not a failure.
    """

    # Contract:
    # Once `python.env_source` is recorded, a later install run never overwrites it,
    # however auto-detection would resolve today.

    # Domain(install.reconciliation):
    # # Environment-source detection precedence
    # A value already on record for this setting is treated as final and is never reconsidered
    # by a later install, however detection would resolve today. Only when nothing is recorded
    # yet does detection run at all, and even then an explicit choice always outranks whatever
    # auto-detection would have found. Auto-detection itself only ever commits a value when
    # exactly one recognised candidate exists; finding several is reported without picking one,
    # leaving the ambiguity for a human to resolve rather than silently guessing.

    # guard: a recorded value is authoritative — never overwrite it
    if self._has_env_source():
      print("env-source-already-set")
      return 0

    # an explicit choice made by the operator outranks anything auto-detection would find
    override = os.environ.get(self.OVERRIDE_ENV)

    # the skill passes an explicit choice back when it disambiguated multiple candidates; it is recorded as given
    if override:
      self._record(override)
      print(f"env-source-recorded: {override}")
      return 0

    # auto-detection: probe the conventional bootstrap-script locations
    found = [c for c in self.CANDIDATES if (self.consumer_dir / c).is_file()]

    # guard: nothing to offer — leave settings untouched
    if not found:
      print("env-source-no-candidate")
      return 0
    if len(found) == 1:
      self._record(found[0])
      print(f"env-source-recorded: {found[0]}")
      return 0

    # Contract:
    # `python.env_source` is auto-recorded only when detection finds exactly one candidate
    # script; multiple candidates are reported and never auto-recorded.

    # report the ambiguity without recording any of the candidates
    print("env-source-multiple: " + ",".join(found))
    return 0

  def _has_env_source(self) -> bool:
    """
    Report whether an `env_source` key is present under the `python` section.

    Returns:
      True when the section carries an `env_source` key (any value), otherwise False.
    """
    section = self._load().get("python")
    return isinstance(section, dict) and "env_source" in section

  def _load(self) -> dict:
    """
    Read the consumer's tracked settings file, tolerating an absent or empty file.

    Returns:
      The parsed settings mapping, or an empty mapping when the file is missing or blank.
    """
    # guard: absent settings file → empty mapping (first-write path)
    if not self.settings.exists():
      return {}
    return json.loads(self.settings.read_text(encoding = "utf-8") or "{}")

  def _record(self, path: str) -> None:
    """
    Persist `path` as `python.env_source`, preserving every other section verbatim.

    Args:
      path: Repo-relative (or absolute) path to the environment-bootstrap script to record.
    """
    data = self._load()
    section = data.get("python")

    # a missing or non-mapping python section starts from an empty one
    if not isinstance(section, dict):
      section = {}
    section["env_source"] = path
    data["python"] = section
    self.settings.parent.mkdir(parents = True, exist_ok = True)
    self.settings.write_text(json.dumps(data, indent = 2) + "\n", encoding = "utf-8")


# ----------------------------------------------------------------------------------------
class Phase7Expert:
  """
  Install phase that registers the code-reviewer agent as an expert in the consumer's
  `lazy.settings.json`, so the review phase is dispatchable from the expert runtime as well
  as from the check pipeline.

  Guarantees:
    - Refreshing an existing expert entry touches only its install-managed fields (`agent`,
      `aspects`); every other field, including operator-set ones, is left untouched.
    - Registering or refreshing the entry never alters any other expert or top-level
      section of the settings file.

  Notes:
    - Registers a full entry when none exists on record; when an entry already exists, only
      its install-managed fields (`agent`, `aspects`) are refreshed on drift, leaving every
      other field, including operator-owned ones, untouched.
    - The entry is additive: every other expert and section in the settings file is preserved
      verbatim.

  Attributes:
    consumer_dir: Root directory of the consumer repository being installed into.
    settings: Path to the consumer's `.claude/lazy.settings.json` file.
  """

  EXPERT_KEY = "python.code-reviewer"
  # The reviewer is a mechanical expert: a file list in, findings out, no state carried between
  # dispatches. An aspect is prompt text prepended to every job, so one here is paid for on every
  # review and repaid on none. `aspects` stays install-managed, so a consumer carrying the memory
  # aspect from an earlier release has it removed on the next install run.
  EXPERT_ENTRY: dict[str, object] = {
    "agent": "lazycortex-python:lazy-python.code-reviewer",
    "aspects": [],
    "git_author": {
      "name": "Python Code Reviewer",
      "email": "python.code-reviewer@bot.invalid",
    },
  }

  # Domain(install.reconciliation):
  # # Managed versus operator-owned entry fields
  # A registered entry is split at the field level: some fields belong to the plugin and are
  # silently corrected back to the shipped values whenever they drift, while every other field
  # is the operator's own and is never touched once the entry exists. This lets an operator
  # freely edit their own fields without an install step ever reverting them, while a plugin
  # upgrade that changes its own managed fields still reaches every existing consumer without
  # requiring a fresh registration.

  # Install-managed fields: this phase's own writing, refreshed on drift. `git_author`
  # is the operator's to set once registered — it is seeded on first registration only.
  MANAGED_FIELDS = ("agent", "aspects")

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.settings: Path = consumer_dir / ".claude/lazy.settings.json"

  def run(self) -> int:
    """
    Ensure the reviewer expert entry exists and its install-managed fields are current.

    Returns:
      0 always; the registration or refresh is additive and cannot fail the install.
    """

    # Contract:
    # Registering or refreshing the reviewer expert entry never alters any other expert
    # entry or any other top-level section of the settings file; both are carried through
    # unchanged.

    data = self._load()
    experts = data.get("experts")

    # a settings file with no experts section yet starts from an empty mapping
    if not isinstance(experts, dict):
      experts = {}

    # no entry on record yet — register a full copy of the template
    if self.EXPERT_KEY not in experts:
      experts[self.EXPERT_KEY] = dict(self.EXPERT_ENTRY)
      data["experts"] = experts
      self._write(data)
      print(f"expert-registered: {self.EXPERT_KEY}")
      return 0

    # an entry on record is compared field-by-field against the shipped form, not accepted whole
    entry = experts[self.EXPERT_KEY]

    # a malformed existing entry (not a mapping) is replaced by a fresh one to refresh into
    if not isinstance(entry, dict):
      entry = {}

    # guard: every install-managed field already matches the shipped form — nothing to refresh
    if all(entry.get(field) == self.EXPERT_ENTRY[field] for field in self.MANAGED_FIELDS):
      print("expert-already-registered")
      return 0

    # Contract:
    # Refreshing an existing expert entry rewrites only its install-managed fields
    # (`agent`, `aspects`); every other field on the entry, including operator-set ones,
    # is left exactly as recorded.

    # correct only the plugin-owned fields; every other field (operator's own) stays as recorded
    for field in self.MANAGED_FIELDS:
      entry[field] = self.EXPERT_ENTRY[field]
    experts[self.EXPERT_KEY] = entry
    data["experts"] = experts
    self._write(data)
    print(f"expert-refreshed: {self.EXPERT_KEY}")
    return 0

  def _load(self) -> dict:
    """
    Read the consumer's tracked settings file, tolerating an absent or empty file.

    Returns:
      The parsed settings mapping, or an empty mapping when the file is missing or blank.
    """
    # guard: absent settings file → empty mapping (first-write path)
    if not self.settings.exists():
      return {}
    return json.loads(self.settings.read_text(encoding = "utf-8") or "{}")

  def _write(self, data: dict) -> None:
    """
    Persist `data` as the consumer's tracked settings file.

    Args:
      data: The full settings mapping to write.
    """
    self.settings.parent.mkdir(parents = True, exist_ok = True)
    self.settings.write_text(json.dumps(data, indent = 2) + "\n", encoding = "utf-8")


# ----------------------------------------------------------------------------------------
class Phase8VenvRefresh:
  """
  Install phase that brings the project venv, and the venv of this host's daemon checkout, up to date.

  Responsibilities:
    - Configure the consumer's target venv when it is missing or stale, and leave a fresh one untouched.
    - Find the checkout this host's runtime daemon runs in, from the repository's daemon gate, and do the same for
      its venv when that venv is a different one.
    - Print one JSON receipt naming the outcome for both, with the failure output of any refresh that failed.

  Guarantees:
    - A venv is fresh by the runners' own rule: the checker tools are present and its stamp matches the current
      requirement inputs; a fresh venv is never changed.
    - A failed refresh, and a daemon checkout that cannot be determined, are reported in the receipt and make the
      phase exit 1; neither is ever dropped.

  Attributes:
    K_PROJECT: Receipt key of the project section.
    K_DAEMON: Receipt key of the daemon section.
    K_ROOT: Receipt key of the section's root directory.
    K_VENV: Receipt key of the section's venv.
    K_STATE: Receipt key of the section's outcome.
    K_DETAIL: Receipt key of the section's failure output.
    K_GATE: Receipt key of the daemon gate verdict.
    K_CHECKOUT: Receipt key of the daemon checkout.
    STATE_FRESH: Outcome token for a venv found fresh.
    STATE_CONFIGURED: Outcome token for a venv configured now.
    STATE_FAILED: Outcome token for a venv that could not be configured.
    STATE_SHARED: Daemon outcome token for a venv that is the project's own.
    STATE_MISSING: Daemon outcome token for a daemon checkout that is gone.
    STATE_SAME: Daemon outcome token for a daemon running in this checkout.
    STATE_NONE: Daemon outcome token for no daemon checkout on this host.
    GATE_OTHER: Daemon gate verdict for a daemon running in another checkout.
    GATE_HERE: Daemon gate verdict for a daemon running in this checkout.
    GATE_INVALID: Daemon gate verdict for an invalid gate shape.
    CORE_PLUGIN: Name of the core plugin that owns the gate verb.
    CORE_CLI_REL: Path of the core command line inside the core plugin root.
    GATE_ARGV: Command-line arguments that run the gate verb.
    GATE_STATE: Field name of the verdict in the gate verb's JSON answer.
    GATE_PATH: Field name of the checkout path in the gate verb's JSON answer.
    ENV_REPO_ROOT: Name of the environment variable that names the repository a refresh works in.
    ENV_PROJECT_DIR: Name of the environment variable a refresh clears.

    consumer_dir: Root directory of the consumer repository being installed into.
  """

  # Receipt keys: the two sections and their fields
  K_PROJECT, K_DAEMON = "project", "daemon"
  K_ROOT, K_VENV, K_STATE, K_DETAIL, K_GATE, K_CHECKOUT = "root", "venv", "state", "detail", "gate", "checkout"
  # Refresh outcomes: the venv was fresh, was configured now, or could not be configured
  STATE_FRESH, STATE_CONFIGURED, STATE_FAILED = "fresh", "configured", "failed"
  # Daemon outcomes besides a refresh: the venv is the project's own, the checkout is gone, the daemon runs in this
  # checkout, or no daemon checkout on this host
  STATE_SHARED, STATE_MISSING, STATE_SAME, STATE_NONE = "shared", "missing", "same", "none"
  # The daemon gate verdicts of the core `daemon-run-here check` verb this phase acts on
  GATE_OTHER, GATE_HERE, GATE_INVALID = "not-this-checkout", "run-here", "invalid-shape"
  # The core plugin, its CLI inside the plugin root, and the gate verb's command line
  CORE_PLUGIN = "lazycortex-core"
  CORE_CLI_REL = Path("bin") / "lazycortex-core"
  GATE_ARGV = ( "daemon-run-here", "check", "--json", "--cwd" )
  # The gate verb's JSON fields
  GATE_STATE, GATE_PATH = "state", "path"
  # The environment names a refresh sets or clears, so cfg resolves the intended project
  ENV_REPO_ROOT, ENV_PROJECT_DIR = "LAZY_REPO_ROOT", "CLAUDE_PROJECT_DIR"

  def __init__(self, *, consumer_dir: Path) -> None:
    """
    Bind the phase to the consumer repository it refreshes.

    Args:
      consumer_dir: Root directory of the consumer repository being installed into.
    """
    self.consumer_dir: Path = consumer_dir

  @staticmethod
  def _find_target_venv(checkout: Path) -> Path:
    """
    Name the venv a checkout's runners use.

    Args:
      checkout: Root of the checkout.

    Returns:
      The checkout's target venv, resolved; the conventional `.venv` at the checkout root when its `pyproject.toml`
      cannot be read.
    """
    # guard: an unreadable pyproject.toml is cfg's to report; the default place stands for the name meanwhile
    try:
      return VenvSpec(project_dir = checkout).target_venv().resolve()
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
      return (checkout / ".venv").resolve()

  def _refresh(self, checkout: Path) -> tuple[str, str]:
    """
    Bring one checkout's venv up to date by the same rule the project's runners apply.

    Notes:
      - Configures the venv when it is missing or stale; a fresh venv is left untouched.

    Args:
      checkout: Root of the checkout whose venv is refreshed.

    Returns:
      The outcome, `fresh`, `configured` or `failed`, and the failure output (empty unless it failed).
    """
    # cfg resolves its project from the repo-root variable, never from a session's project directory
    env = { key: value for key, value in os.environ.items() if key != self.ENV_PROJECT_DIR }
    env[self.ENV_REPO_ROOT] = str(checkout)

    # guard: a cfg that cannot be started is a failed refresh, reported with the reason
    try:
      # waiver: the shell runner and cfg's own flag, not reusable domain keys
      done = subprocess.run([ "bash", str(_BIN / "cfg"), "--if-stale" ], cwd = checkout, env = env,
                            capture_output = True, text = True, check = False)
    except OSError as error:
      return self.STATE_FAILED, str(error)

    # cfg names the outcome on its last stdout line
    answer = done.stdout.strip().splitlines()[-1:]

    # guard: a non-zero exit or any other answer is a failure, reported with cfg's stderr
    if done.returncode != 0 or answer not in ( [ self.STATE_FRESH ], [ self.STATE_CONFIGURED ] ):
      return self.STATE_FAILED, done.stderr.strip()
    return answer[0], ""

  def _refresh_daemon(self, own_venv: Path) -> dict[str, str | None]:
    """
    Refresh the venv of this host's daemon checkout when it differs from the project's own.

    Notes:
      - A daemon checkout that is not on disk is reported, never created.

    Args:
      own_venv: The project's own target venv, already refreshed.

    Returns:
      The daemon section of the receipt: the gate verdict, the checkout, its venv, the outcome and the failure
      detail.
    """
    section: dict[str, str | None] = { self.K_GATE: None, self.K_CHECKOUT: None, self.K_VENV: None,
                                       self.K_STATE: self.STATE_FAILED, self.K_DETAIL: "" }

    # guard: without the core CLI's answer the daemon checkout cannot be determined, and that is reported
    try:
      core, _stage = python_locator.plugin_root(self.CORE_PLUGIN, self.consumer_dir,
                                                sibling_base = PLUGIN_ROOT.parent)
      done = subprocess.run(
          [ sys.executable, str(core / self.CORE_CLI_REL), *self.GATE_ARGV, str(self.consumer_dir) ],
          capture_output = True, text = True, check = False)
      gate = json.loads(done.stdout) if done.returncode == 0 else None
    except (python_locator.PluginNotFoundError, OSError, ValueError) as error:
      section[self.K_DETAIL] = str(error)
      return section

    # guard: a refused or unreadable answer names no checkout; the verb's own output is the report
    if not isinstance(gate, dict):
      section[self.K_DETAIL] = done.stderr.strip() or done.stdout.strip()
      return section

    # the gate verdict the rest of the decision rests on
    section[self.K_GATE] = gate.get(self.GATE_STATE)

    # the daemon runs in this very checkout, whose venv was refreshed already
    if gate.get(self.GATE_STATE) == self.GATE_HERE:
      section[self.K_STATE] = self.STATE_SAME
      return section

    # guard: the gate verb reports an invalid `daemon.run_here` shape, so the daemon checkout cannot be determined
    if gate.get(self.GATE_STATE) == self.GATE_INVALID:
      section[self.K_DETAIL] = f"daemon.run_here gate verdict: {self.GATE_INVALID}"
      return section

    # no daemon checkout on this host
    if gate.get(self.GATE_STATE) != self.GATE_OTHER or not isinstance(gate.get(self.GATE_PATH), str):
      section[self.K_STATE] = self.STATE_NONE
      return section

    # the checkout this host's daemon runs in, as the gate names it
    checkout = Path(gate[self.GATE_PATH]).expanduser().resolve()
    section[self.K_CHECKOUT] = str(checkout)

    # guard: a gate naming a checkout that is not on disk is reported, never created
    if not checkout.is_dir():
      section[self.K_STATE] = self.STATE_MISSING
      return section

    # a venv the project shares with the daemon checkout was refreshed already
    venv = self._find_target_venv(checkout)
    section[self.K_VENV] = str(venv)
    if venv == own_venv:
      section[self.K_STATE] = self.STATE_SHARED
      return section

    # the daemon checkout's own venv, refreshed the same way
    section[self.K_STATE], section[self.K_DETAIL] = self._refresh(checkout)
    return section

  def run(self) -> int:
    """
    Bring the project venv and the daemon checkout's venv up to date.

    Guarantees:
      - A venv that is fresh by the runners' own rule (checker tools present, stamp matching the current
        requirement inputs) is never changed.
      - A failed refresh, and a daemon checkout that cannot be determined, appear in the receipt with their own
        output and make the phase exit 1; neither is ever dropped.

    Notes:
      - Prints one JSON receipt to stdout with a `project` section and a `daemon` section.

    Returns:
      0 when nothing failed, 1 when a refresh failed or the daemon checkout could not be determined.
    """

    # Domain(install.reconciliation):
    # # An install brings the environment up to date
    # Every install run checks the project's environment and, when it is missing or out of date, sets it up from
    # the project's requirements; an environment that is current is left exactly as it is. The checkout the
    # repository's runtime daemon uses on this host has its own environment when it lives elsewhere, and it is
    # checked and set up the same way, since the jobs the daemon runs only ever use the environment they find. A
    # setup that fails is reported with its own output and fails the step; it is never passed over.

    # Contract:
    # A venv that is fresh by the runners' own rule (checker tools present, stamp matching the current requirement
    # inputs) MUST never be changed.

    # Contract:
    # A failed refresh, and a daemon checkout that cannot be determined, MUST appear in the receipt with their own
    # output and make the phase exit 1; neither is ever dropped. The install skill reads the exit code as the step's
    # outcome.

    # the project's own venv first
    own_venv = self._find_target_venv(self.consumer_dir)
    state, detail = self._refresh(self.consumer_dir)
    project = { self.K_ROOT: str(self.consumer_dir), self.K_VENV: str(own_venv), self.K_STATE: state,
                self.K_DETAIL: detail }

    # then the daemon checkout this host's gate names
    daemon = self._refresh_daemon(own_venv)

    # one receipt, and a failure anywhere fails the phase
    print(json.dumps({ self.K_PROJECT: project, self.K_DAEMON: daemon }))
    return 1 if self.STATE_FAILED in ( project[self.K_STATE], daemon[self.K_STATE] ) else 0


def main() -> int:
  """
  Dispatch a single named phase against a consumer repository directory.

  Returns:
    The phase's own exit code — 0 on success, 1 when the phase reports a failure — or 2 on a usage error or an
    unknown phase name.
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
    "phase2b": HomeWrappersPhase,
    "phase3": Phase3Pyproject,
    "phase4": Phase4Pch,
    "phase5": Phase5Overlay,
    "phase6": Phase6EnvSource,
    "phase7": Phase7Expert,
    "phase8": Phase8VenvRefresh,
  }
  handler = phases.get(phase)
  if handler is None:
    print(f"unknown phase: {phase!r}; supported: {sorted(phases)}", file = sys.stderr)
    return 2
  return handler(consumer_dir = consumer_dir).run()


if __name__ == "__main__":
  sys.exit(main())
