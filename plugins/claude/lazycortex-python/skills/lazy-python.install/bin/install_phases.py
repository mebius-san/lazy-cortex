"""
Install phase implementations for /lazy-python.install.

CLI: `python3 install_phases.py phase<N> <consumer_repo_dir>` runs the named phase
against the consumer repo. Phases are idempotent; safe to re-run.

Phases:
  phase1 — mirror plugin rules into <consumer>/.claude/rules/
  phase2 — deploy chk-py, tst-py and cli/mypy/protected_access.py into <consumer>/cli/
  phase2b — deploy chk-py and tst-py human wrappers into $HOME/.local/bin
  phase3 — bootstrap consumer pyproject.toml with checker sections
  phase4 — probe for PyCharm inspect.sh CLI (pch prereq)
  phase5 — scaffold project overlay guidelines under docs/guidelines/
  phase6 — record python.env_source when the repo ships an env-bootstrap script
  phase7 — register the code-reviewer agent as an expert in lazy.settings.json

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

import json
import os
import re
import shutil
import stat
import sys
import tomllib
from functools import partial
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


# location of the plugin tree (this file lives at .../skills/lazy-python.install/bin/install_phases.py)
# Allow override via env (Claude Code sets CLAUDE_PLUGIN_ROOT; consumer install → cache path, not dev source).
# Default fallback resolves to .../plugins/claude/lazycortex-python via parents[3].
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

    Notes:
      - Prints a JSON receipt to stdout mapping each rule filename to `installed`, `unchanged`,
        `refreshed`, or `failed`.

    Returns:
      0 when every rule verified successfully, 1 when at least one write failed verification.
    """

    # Contract:
    # Only files shipped by the plugin under its rules directory are ever written to the
    # consumer's rules directory; any other file already present there is left untouched.

    self.target_dir.mkdir(parents = True, exist_ok = True)
    shipped = sorted(name for name in os.listdir(self.source_dir) if name.endswith(".md"))
    states = { name: self._mirror(name) for name in shipped }
    print(json.dumps({ "phase": "phase1", "rules": states }, indent = 2))

    # guard: an unverified write must not read as a successful mirror
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

    # Contract:
    # A successful outcome is reported only after the target has been read back and its
    # bytes verified to match what was shipped; an unverified write is reported as failed.

    # guard: the write is only an outcome once the target actually holds the shipped bytes
    if target.read_bytes() != shipped:
      return "failed"
    return state


# ----------------------------------------------------------------------------------------
class Phase2Wrappers:
  """
  Install phase that writes byte-for-byte copies of the `chk-py` and `tst-py` wrapper scripts and
  the `mypy/protected_access.py` plugin shim into the consumer's `cli/` directory and ensures
  `.venv/` is listed in the consumer's `.gitignore`.

  Guarantees:
    - Leaves a `.gitignore` that already ignores `.venv` byte-for-byte untouched.
  """

  WRAPPERS = (
    ("chk-wrapper.sh", "chk-py"),
    ("tst-wrapper.sh", "tst-py"),
    ("mypy-protected-access-shim.py", "mypy/protected_access.py"),
  )

  def __init__(self, *, consumer_dir: Path) -> None:
    self.consumer_dir: Path = consumer_dir
    self.target_dir: Path = consumer_dir / "cli"
    self.gitignore: Path = consumer_dir / ".gitignore"

  def run(self) -> int:
    """
    Write the `chk-py` and `tst-py` wrappers and the `mypy/protected_access.py` shim to the
    consumer's `cli/` directory and update `.gitignore`.

    Returns:
      0 on success.
    """
    self.target_dir.mkdir(parents = True, exist_ok = True)
    for template_name, target_name in self.WRAPPERS:
      # Templates are path-agnostic: deployed verbatim, they resolve the active
      # plugin install at exec time. No path is substituted here — that is the
      # whole point (a baked path goes stale on the next plugin update). Bytes, not text, so no
      # host turns LF into CRLF: bash rejects a CRLF script and the audit compares the shim bytewise.
      target = self.target_dir / target_name
      target.parent.mkdir(parents = True, exist_ok = True)
      target.write_bytes((PLUGIN_ROOT / "templates" / template_name).read_bytes())
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
    present = any(line.strip() in (".venv", ".venv/") for line in existing.splitlines())

    # Contract:
    # A `.gitignore` that already ignores `.venv` is left byte-for-byte untouched; the
    # ignore line is appended only when genuinely absent.

    # guard: already ignored → leave the file byte-for-byte
    if present:
      print("gitignore-already-present")
      return
    prefix = existing if existing == "" or existing.endswith("\n") else existing + "\n"
    self.gitignore.write_text(prefix + ".venv/\n", encoding = "utf-8")
    print("gitignore-ensured")


# ----------------------------------------------------------------------------------------
class HomeWrappersPhase:
  """
  Install phase that writes `chk-py` and `tst-py` into `$HOME/.local/bin`.

  These are the only files this plugin ever marks executable: they live outside every
  vault, so no mode-blind git client can strip the bit, and they find the repo's own
  `cli/` wrapper by walking up from the caller's directory.

  Guarantees:
    - Reasserts the executable bit on both wrappers every run, even when their content
      is already current.
  """

  TEMPLATES: tuple = (
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
    Write both wrappers, byte-verified, and set the exec bit on the written copies.

    Returns:
      0 on success.
    """
    self.target_dir.mkdir(parents = True, exist_ok = True)
    receipt: dict = {}
    for template, name in self.TEMPLATES:
      src = self.plugin_root / "templates" / template
      dst = self.target_dir / name
      body = src.read_bytes()
      state = "unchanged"
      if not dst.exists():
        state = "installed"
      elif dst.read_bytes() != body:
        state = "refreshed"
      if state != "unchanged":
        dst.write_bytes(body)

      # Contract:
      # The executable bit is reasserted on both wrappers every run, even when their
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

  Adds the `[tool.pcf]`, `[tool.pcf.overrides]`, `[tool.toi]`, `[tool.pch]`,
  `[tool.pytest.ini_options]`, `[tool.mypy]`, `[tool.pylint]`, and `[tool.ruff]` sections
  (and any nested sub-tables, e.g. `[tool.ruff.lint]`) that the consumer's file is missing,
  and completes the missing sub-keys of any of those sections the consumer already has. A
  `[tool.mypy]` `plugins` list the consumer already has gains the template's plugin entries
  it lacks, after the consumer's own.

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
  CHECKER_SECTIONS = ("pcf", "toi", "pytest", "mypy", "pylint", "ruff")
  OPTIONAL_SECTIONS = {"pch": "LAZY_PYTHON_ENABLE_PCH"}

  # the checker section and key whose list install extends instead of leaving alone
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
        partial(self._check_section_keys, section_name, missing_keys),
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
          partial(self._check_section_keys, section_name, []),
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
      toml_text, self._append_to_array(toml_text, self.PLUGINS_SECTION, self.PLUGINS_KEY, absent),
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
  def _check_section_keys(top_name: str, keys: list[str], data: dict) -> bool:
    """
    Tell whether a parsed document has a `[tool.<top_name>]` table carrying the given keys.

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
  def _append_to_array(cls, toml_text: str, top_name: str, key: str, values: list[str]) -> str:
    """
    Append string values to an array a key holds directly under `[tool.<top_name>]`, keeping
    the array's existing entries, comments and layout.

    Notes:
      - A multi-line array whose closing bracket stands on its own line gains one new line per
        call, indented like its first entry; any other array gains the values inline after its
        last entry.

    Args:
      toml_text: Full TOML document to edit.
      top_name: Name of the top-level tool section holding the key.
      key: Bare key whose array value is extended.
      values: String values to append, in order.

    Returns:
      The edited document, or `toml_text` unchanged when the key's array cannot be located.
    """
    opening = cls._find_array_start(toml_text, top_name, key)

    # guard: no `key = [` line directly under the section's own header
    if opening is None:
      return toml_text

    # where the array closes, where its last entry ends, and whether a comma already follows that entry
    close, last_end, has_comma = cls._scan_array(toml_text, opening)

    # guard: an array that never closes cannot be extended
    if close is None:
      return toml_text

    # the new entries as TOML strings, and the start of the line holding the closing bracket
    quoted = ", ".join(json.dumps(value) for value in values)
    line_start = toml_text.rfind("\n", 0, close) + 1

    # a closing bracket alone on its line marks a one-entry-per-line array: the last entry gets its missing comma and
    # the new entries go on a line of their own, indented like the first entry
    if "\n" in toml_text[opening:close] and not toml_text[line_start:close].strip():
      indent = re.search(r"\n([ \t]*)\S", toml_text[opening:close])

      # an empty array keeps the text before the closing line as is
      before_close = toml_text[:line_start]

      # an existing last entry gets its missing comma before the new line is added
      if last_end is not None:
        before_close = toml_text[:last_end] + ("" if has_comma else ",") + toml_text[last_end:line_start]
      return before_close + (indent.group(1) if indent else "  ") + quoted + ",\n" + toml_text[line_start:]

    # an empty inline array takes the values as its only entries
    if last_end is None:
      return toml_text[:opening] + quoted + toml_text[opening:]
    return toml_text[:last_end] + ", " + quoted + toml_text[last_end:]

  @classmethod
  def _find_array_start(cls, toml_text: str, top_name: str, key: str) -> int | None:
    """
    Locate the opening bracket of an array a bare key holds directly under `[tool.<top_name>]`.

    Args:
      toml_text: Full TOML document to scan.
      top_name: Name of the top-level tool section holding the key.
      key: Bare key whose array value is located.

    Returns:
      The offset just past the opening `[`, or `None` when the section header or a
      `key = [` line under it is missing.
    """
    header = f"[tool.{top_name}]"
    key_line = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*\[")
    offset = 0
    in_section = False
    for line in toml_text.splitlines(keepends = True):
      stripped = line.strip()

      # the section's own header switches scanning on
      if stripped == header:
        in_section = True
      # a nested sub-table or the next section ends the section's own keys
      elif in_section and stripped.startswith("["):
        return None
      # the key's `key = [` line inside the section yields the offset just past its opening bracket
      elif in_section and (match := key_line.match(line)):
        return offset + match.end()

      # track the offset of the next line for the match arithmetic above
      offset += len(line)
    return None

  @classmethod
  def _scan_array(cls, toml_text: str, opening: int) -> tuple[int | None, int | None, bool]:
    """
    Walk a TOML array from just past its opening bracket to its closing one.

    Args:
      toml_text: Full TOML document.
      opening: Offset just past the array's opening `[`.

    Returns:
      The offset of the closing `]` (or `None` when the array never closes), the offset just
      past the last entry (or `None` for an empty array), and whether a comma follows that entry.
    """
    depth = 1
    last_end: int | None = None
    has_comma = False
    pos = opening
    while pos < len(toml_text):
      char = toml_text[pos]

      # a comment runs to the end of its line and holds no entry
      if char == "#":
        pos = toml_text.find("\n", pos)
        # guard: a comment that runs to the end of the document leaves the array unterminated
        if pos == -1:
          return None, None, False

        # resume scanning on the line that follows the comment
        continue

      # a string is skipped whole, so brackets and commas inside it are not structure
      if char in "\"'":
        end = cls._find_string_end(toml_text, pos)
        # guard: a string that never closes leaves the array unterminated
        if end is None:
          return None, None, False

        # a string directly in the array is an entry: it becomes the last one and no comma follows it yet
        if depth == 1:
          last_end, has_comma = end, False

        # resume scanning just past the closing quote
        pos = end
        continue

      # brackets nest; the bracket that returns to depth 0 closes the array
      if char == "[":
        depth += 1
      elif char == "]":
        depth -= 1
        if depth == 0:
          return pos, last_end, has_comma
        # a nested array closing back to depth 1 is itself an entry, so it becomes the last one
        if depth == 1:
          last_end, has_comma = pos + 1, False
      # a depth-1 comma separates entries: the entry before it already has its comma
      elif char == "," and depth == 1:
        has_comma = True
      # any other depth-1 token (a number, a bare word) is an entry, so it becomes the last one
      elif not char.isspace() and depth == 1:
        last_end, has_comma = pos + 1, False
      pos += 1
    return None, None, False

  @staticmethod
  def _find_string_end(toml_text: str, start: int) -> int | None:
    """
    Find where a TOML string starting at `start` ends.

    Args:
      toml_text: Full TOML document.
      start: Offset of the string's opening quote.

    Returns:
      The offset just past the closing quote, or `None` when the string never closes.
    """
    quote = toml_text[start]

    # a multi-line string ends at the next triple quote
    if toml_text.startswith(quote * 3, start):
      end = toml_text.find(quote * 3, start + 3)
      return None if end == -1 else end + 3

    # a single-line string ends at its quote; a basic string skips escaped characters
    pos = start + 1
    while pos < len(toml_text) and toml_text[pos] != "\n":
      # an escape hides the next character, so an escaped quote does not end the string
      if quote == '"' and toml_text[pos] == "\\":
        pos += 2
        continue

      # an unescaped quote of the opening kind closes the string
      if toml_text[pos] == quote:
        return pos + 1
      pos += 1
    return None

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
  consumer's `docs/guidelines/` directory.

  Guarantees:
    - Never overwrites an overlay file the consumer has already created for a topic.
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
  keeps working under the plugin runners. This phase never overwrites a value already on record.

  Guarantees:
    - Never overwrites a `python.env_source` value already on record.
    - Auto-records a detected script only when exactly one candidate is found; multiple
      candidates are reported without being recorded.

  Notes:
    - A value already on record is left untouched and reported as `env-source-already-set`.
    - When `LAZY_PYTHON_ENV_SOURCE` is set, its value is recorded as the skill's disambiguated choice.
    - Exactly one detected candidate script is recorded silently.
    - Multiple candidates are reported without recording so the caller can disambiguate.
    - No candidates leaves the settings file unchanged.

  Attributes:
    consumer_dir: Root directory of the consumer repository being installed into.
    settings: Path to the consumer's `.claude/lazy.settings.json` file.
  """

  # Domain(install.reconciliation):
  # # Environment-source detection precedence
  # A value already on record for this setting is treated as final and is never reconsidered
  # by a later install, however detection would resolve today. Only when nothing is recorded
  # yet does detection run at all, and even then an explicit choice always outranks whatever
  # auto-detection would have found. Auto-detection itself only ever commits a value when
  # exactly one recognised candidate exists; finding several is reported without picking one,
  # leaving the ambiguity for a human to resolve rather than silently guessing.

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

    # guard: a recorded value is authoritative — never overwrite it
    if self._already_set():
      print("env-source-already-set")
      return 0

    # an explicit choice made by the operator outranks anything auto-detection would find
    override = os.environ.get(self.OVERRIDE_ENV)

    # guard: the skill passes an explicit choice back when it disambiguated multiple candidates
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

  def _already_set(self) -> bool:
    """
    Report whether an `env_source` key is already present under the `python` section.

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

    # guard: no entry on record yet — register a full copy of the template
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
    "phase2b": HomeWrappersPhase,
    "phase3": Phase3Pyproject,
    "phase4": Phase4Pch,
    "phase5": Phase5Overlay,
    "phase6": Phase6EnvSource,
    "phase7": Phase7Expert,
  }
  handler = phases.get(phase)
  if handler is None:
    print(f"unknown phase: {phase!r}; supported: {sorted(phases)}", file = sys.stderr)
    return 2
  return handler(consumer_dir = consumer_dir).run()


if __name__ == "__main__":
  sys.exit(main())
