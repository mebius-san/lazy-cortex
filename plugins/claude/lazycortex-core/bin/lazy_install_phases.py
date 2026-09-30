"""
Reusable phases extracted from `lazy-core.install` for testability.

Each function takes a repo path and is idempotent — repeated calls on an
already-bootstrapped repository complete without side effects beyond the
initial materialisation.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

# waiver: flat sibling import inside the plugin's bin/ dir — resolved at runtime via PYTHONPATH, not by pylint
from constants import DaemonKey, GitConfigKey, SettingsFile, SettingsKey  # pylint: disable=import-error
# waiver: flat sibling import inside the plugin's bin/ dir — resolved at runtime via PYTHONPATH, not by pylint
from lazy_settings import load_tracked_section, save_section  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ---------- .gitignore primitives ----------

def ensure_gitignore_lines(repo: Path | str, lines: list[str]) -> str:
  """
  Ensure each entry in `lines` is present in the repository's `.gitignore`.

  Accepts both the trailing-slash and no-slash form of an entry as already-present, so
  passing `.logs/` is a no-op when `.logs` is already listed. Missing entries are appended
  in the order given. Creates `.gitignore` when it is absent. Idempotent.

  Guarantees:
    - The file's existing line-ending style is preserved: a CRLF `.gitignore` is written back
      CRLF throughout, an LF one LF, including any line this call appends.

  Args:
    repo: Path to the repository root.
    lines: Entries to ensure are present in `.gitignore`.

  Returns:
    `"updated"` when at least one line was appended, `"already-present"` when every
    requested line was already present.
  """

  # Domain(install.reconciliation):
  # # Slash-variant equivalence for an ignore entry
  # A directory entry in an ignore file means the same thing whether it is written with or
  # without its trailing slash, so an idempotent write must recognise both spellings as the same
  # entry — otherwise a repeated install run would keep appending an equivalent line in a
  # different notation forever. Removing an entry asks the opposite question and is answered
  # exactly, with no tolerance: a caller that names a precise line to strip is trusted to have
  # named the form that is actually there, and only that exact form is taken out.

  repo = Path(repo)
  # waiver: filesystem filename idiom, not a domain constant
  gi = repo / ".gitignore"
  # read untranslated so a CRLF file is written back CRLF
  # waiver: stdlib encoding idiom
  existing = gi.read_bytes().decode("utf-8") if gi.exists() else ""
  newline = "\r\n" if "\r\n" in existing else "\n"
  existing_set = { line.strip() for line in existing.splitlines() }

  # collect entries that are neither present as-is nor as their slash-variant
  to_append = []
  for line in lines:
    stripped = line.strip()
    variants = { stripped, stripped.rstrip("/"), stripped + "/" }

    # an entry absent in every variant form is the only one that still needs writing
    if not existing_set & variants:
      to_append.append(stripped)

  # guard: no work to do — every requested entry is already present
  if not to_append:
    # waiver: install-phase outcome token, not a reusable domain key
    return "already-present"

  # Contract:
  # The file's existing line-ending style is preserved: a CRLF `.gitignore` is written back
  # CRLF throughout, an LF one LF, including any line this call appends.

  # append the missing entries, keeping the file newline-terminated on both sides of the seam
  suffix = "" if existing.endswith("\n") or not existing else newline
  appended = "".join(f"{ln}{newline}" for ln in to_append)
  runtime_state.atomic_write_text(gi, f"{existing}{suffix}{appended}")
  # waiver: install-phase outcome token, not a reusable domain key
  return "updated"


def remove_gitignore_lines(repo: Path | str, lines: list[str]) -> str:
  """
  Remove every line matching any entry in `lines` from the repository's `.gitignore`.

  Matches by exact stripped equality — the caller passes the exact form they want gone,
  with no slash-variant tolerance (unlike `ensure_gitignore_lines`). No-op when
  `.gitignore` is absent. Idempotent.

  Guarantees:
    - The file's existing line-ending style is preserved: a CRLF `.gitignore` is written back
      CRLF throughout, an LF one LF.

  Args:
    repo: Path to the repository root.
    lines: Exact entries to strip from `.gitignore`.

  Returns:
    `"removed"` when at least one line was stripped, `"already-absent"` when no matching
    line was present or the file did not exist.
  """
  repo = Path(repo)
  # waiver: filesystem filename idiom, not a domain constant
  gi = repo / ".gitignore"

  # guard: nothing to scrub when the file does not exist
  if not gi.exists():
    # waiver: install-phase outcome token, not a reusable domain key
    return "already-absent"

  # filter the file down to the lines the caller did not ask to remove
  targets = { ln.strip() for ln in lines }
  # read untranslated so a CRLF file is written back CRLF
  # waiver: stdlib encoding idiom
  source = gi.read_bytes().decode("utf-8")
  newline = "\r\n" if "\r\n" in source else "\n"
  src_lines = source.splitlines()
  kept = [ ln for ln in src_lines if ln.strip() not in targets ]

  # guard: every source line survived the filter — nothing matched
  if len(kept) == len(src_lines):
    # waiver: install-phase outcome token, not a reusable domain key
    return "already-absent"

  # Contract:
  # The file's existing line-ending style is preserved: a CRLF `.gitignore` is written back
  # CRLF throughout, an LF one LF.

  # write the survivors back, newline-terminated unless the filter emptied the file out
  body = newline.join(kept)
  runtime_state.atomic_write_text(gi, body + (newline if body else ""))
  # waiver: install-phase outcome token, not a reusable domain key
  return "removed"


# the attribute line that makes git store and check out every text file with LF
_GITATTRIBUTES_LF_RULE = "* text=auto eol=lf"


def ensure_gitattributes_lf(repo: Path | str) -> str:
  """
  Ensure the repository's `.gitattributes` carries `* text=auto eol=lf`, inserted as its first line (after any BOM).

  Makes git on every machine — any OS, any `core.autocrlf` — store and check out text files with
  LF, underneath every more specific rule the file already carries. Creates `.gitattributes`
  when it is absent. A line already present anywhere in the file counts.

  Guarantees:
    - A leading UTF-8 byte-order mark stays the file's first bytes, and the rule line is
      inserted immediately after it; every other operator byte already in the file follows
      the inserted rule line unchanged, in order, and no existing line is ever removed or
      reordered.
    - A file that already carries the rule line, compared after stripping, is left
      byte-identical; a re-run performs no write.
    - The file's existing line-ending style is preserved: a CRLF file receives a
      CRLF-terminated rule line, an LF file an LF-terminated one.

  Args:
    repo: Path to the repository root.

  Returns:
    `"created"` when the file was absent, `"updated"` when the line was inserted into an existing
    file, `"already-present"` when the file already carried the line.

  Raises:
    FileNotFoundError: If `repo` is not an existing directory.
    UnicodeDecodeError: If an existing `.gitattributes` is not valid UTF-8.
  """

  # Domain(install.reconciliation):
  # # A repository-wide default goes underneath the operator's own rules
  # In an attributes file a later matching rule overrides an earlier one, so a catch-all default
  # placed first sets the baseline for every text file while each more specific rule the operator
  # wrote after it still wins for the files it names. Seeding therefore inserts the default at the
  # top and never touches, drops, or reorders what is already there.

  repo = Path(repo)

  # guard: never materialise a repository root the caller did not already have
  if not repo.is_dir():
    raise FileNotFoundError(f"repository root not found: {repo}")

  # read untranslated so a CRLF file is written back CRLF
  # waiver: filesystem filename idiom, not a domain constant
  ga = repo / ".gitattributes"
  existed = ga.exists()
  # waiver: stdlib encoding idiom
  existing = ga.read_bytes().decode("utf-8") if existed else ""

  # Contract:
  # A file that already carries the rule line, compared after stripping, is left
  # byte-identical; a re-run performs no write.

  # guard: the rule is already on record — the file stays byte-identical
  if any(line.strip() == _GITATTRIBUTES_LF_RULE for line in existing.splitlines()):
    # waiver: install-phase outcome token, not a reusable domain key
    return "already-present"

  # Contract:
  # A leading UTF-8 byte-order mark stays the file's first bytes, and the rule line is
  # inserted immediately after it. Every other operator byte already in the file follows
  # the inserted rule line unchanged, in order; no existing line is ever removed or
  # reordered.

  # Contract:
  # The file's existing line-ending style is preserved: a CRLF file receives a
  # CRLF-terminated rule line, an LF file an LF-terminated one.

  # prepend the rule in the file's own line-ending style, leaving every operator byte after it; a
  # leading BOM stays first, or git would read it as part of the operator's first pattern
  newline = "\r\n" if "\r\n" in existing else "\n"
  bom = "﻿" if existing.startswith("﻿") else ""
  runtime_state.atomic_write_text(ga, f"{bom}{_GITATTRIBUTES_LF_RULE}{newline}{existing[len(bom):]}")
  # waiver: install-phase outcome tokens, not reusable domain keys
  return "updated" if existed else "created"


def index_has_crlf(repo: Path | str) -> bool:
  """
  Report whether git's index holds a text file with CRLF line endings.

  Such content is not rewritten by an `eol=lf` attribute on its own; the operator renormalizes it
  once with `git add --renormalize .`.

  Args:
    repo: Path to the repository root.

  Returns:
    True when `git ls-files --eol` reports at least one `i/crlf` entry; False otherwise, including
    when `repo` is not a git repository.
  """
  # the first column of each row is the index-side line-ending verdict
  # waiver: git's own `ls-files --eol` tokens, not domain keys
  return any(
    row.split()[:1] == [ "i/crlf" ]
    for row in (_git_capture(Path(repo), [ "ls-files", "--eol" ]) or "").splitlines()
  )


def ensure_self_ignoring_dir(directory: Path | str) -> str:
  """
  Create `directory` if absent and drop a self-ignoring `.gitignore` into it.

  Marks an auto-created service directory (`.logs/`, `.runtime/`, `.experts/`, a worktree
  root) as ignored by git without adding any entry to the consumer's tracked root
  `.gitignore`.

  Guarantees:
    - An existing `.gitignore` inside `directory`, whatever it contains, is left byte-for-byte
      untouched.
    - Idempotent: repeated calls after the first materialisation make no further changes.

  Args:
    directory: Path to the service directory the `.gitignore` protects.

  Returns:
    `"created"` when the directory and/or a new `.gitignore` were materialised,
    `"already-present"` when both already existed.
  """

  # Contract:
  # An existing `.gitignore` inside `directory`, whatever it contains, is left
  # byte-for-byte untouched; only a missing file is written.

  directory = Path(directory)
  dir_existed = directory.is_dir()
  directory.mkdir(parents = True, exist_ok = True)
  # waiver: filesystem filename idiom, not a domain constant
  gi = directory / ".gitignore"

  # guard: an existing file — operator content or a prior run — is never touched
  if gi.exists():
    # waiver: install-phase outcome token, not a reusable domain key
    return "already-present" if dir_existed else "created"
  gi.write_text("*\n", encoding = "utf-8")
  # waiver: install-phase outcome token, not a reusable domain key
  return "created"


# ---------- bootstrap phases ----------

def bootstrap_logs_dir(repo: Path | str) -> str:
  """
  Create `.logs/` and `.runtime/` at the repository root, each self-ignoring.

  `.logs/` holds the runtime journal (daemon output, recall logs, commit-recorder feed).
  `.runtime/` holds non-log daemon state — currently `state.json`, carrying the `last_run`,
  `git_watch`, and `daemon_halted` blocks.

  Guarantees:
    - Each directory gains its own self-ignoring `.gitignore` unless one already exists there.
    - Any root-`.gitignore` lines appended by an earlier version of this phase are left in
      place, unchanged.
    - Idempotent.

  Args:
    repo: Path to the repository root.

  Returns:
    `"bootstrapped"` when at least one directory or `.gitignore` was materialised,
    `"already-present"` when both directories and both local `.gitignore` files already
    existed.
  """
  repo = Path(repo)

  # create each runtime directory and its own self-ignoring .gitignore, tracking
  # whether the call materialised anything new
  materialised_any = False
  for name in (".logs", ".runtime"):
    # waiver: install-phase outcome token, not a reusable domain key
    if ensure_self_ignoring_dir(repo / name) == "created":
      materialised_any = True

  # Contract:
  # A root-`.gitignore` line left over from an earlier version of this phase is never
  # removed; only missing entries are appended.

  # legacy root-.gitignore lines from earlier versions of this phase stay as they are —
  # the operator's call, never removed
  gi_outcome = ensure_gitignore_lines(repo, [ ".logs/", ".runtime/" ])

  # any materialisation at all — a fresh directory, a fresh local .gitignore, or a fresh
  # root-.gitignore line — counts as a bootstrap
  if materialised_any or gi_outcome == "updated":
    # waiver: install-phase outcome token, not a reusable domain key
    return "bootstrapped"
  # waiver: install-phase outcome token, not a reusable domain key
  return "already-present"


_STALE_LOG_HOOK_PATTERN = re.compile(
  r"\$\{CLAUDE_PLUGIN_ROOT\}/lazycortex-log/hooks/"
)


def migrate_log_hooks(settings_path: Path | str) -> str:
  """
  Strip hook commands referencing the retired `lazycortex-log/hooks/` path from settings.

  Removes any hook command whose `command` string contains the
  `${CLAUDE_PLUGIN_ROOT}/lazycortex-log/hooks/` prefix from the given Claude Code
  settings file. Empty matcher blocks left behind by the removal are dropped; empty event
  lists are dropped. Unrelated hooks are preserved. Idempotent: a second run on
  already-clean settings is a no-op.

  Guarantees:
    - A hook command that does not reference the retired path is left in the settings
      file exactly as it was.

  Args:
    settings_path: Path to the Claude Code settings file to migrate.

  Returns:
    `"migrated"` when one or more stale entries were stripped (possibly emptying matcher
    blocks or event lists that were dropped), `"no-stale-entries"` when the file was
    absent or contained no stale entries.
  """
  settings_path = Path(settings_path)

  # guard: nothing to migrate when the settings file does not exist
  if not settings_path.exists():
    # waiver: install-phase outcome token, not a reusable domain key
    return "no-stale-entries"

  # Contract:
  # A hook command that does not reference the retired `lazycortex-log/hooks/` path is
  # left in the settings file exactly as it was.

  # pull in the hook table this migration rewrites
  # waiver: stdlib encoding idiom
  settings = json.loads(settings_path.read_text(encoding = "utf-8"))
  # waiver: external Claude Code settings field name, not an internal key
  hooks = settings.get("hooks", {})
  changed = False

  # walk each event group, dropping stale hook commands and any matcher block that empties out
  for event in list(hooks.keys()):
    event_entries = hooks.get(event) or []
    new_event_entries = []
    for entry in event_entries:
      kept_hooks = [
        # waiver: external Claude Code settings field name, not an internal key
        h for h in entry.get("hooks", [])
        if not (isinstance(h, dict)
                # waiver: external Claude Code settings field name, not an internal key
                and isinstance(h.get("command"), str)
                # waiver: external Claude Code settings field name, not an internal key
                and _STALE_LOG_HOOK_PATTERN.search(h["command"]))
      ]
      # waiver: external Claude Code settings field name, not an internal key
      if len(kept_hooks) != len(entry.get("hooks", [])):
        changed = True
      if kept_hooks:
        new_event_entries.append({ **entry, "hooks": kept_hooks })
      else:
        # matcher block now empty — drop it entirely
        changed = True
    if new_event_entries:
      hooks[event] = new_event_entries
    else:
      del hooks[event]
      changed = True

  # rewrite the file only when the walk actually stripped something
  if changed:
    # waiver: external Claude Code settings field name, not an internal key
    settings["hooks"] = hooks
    runtime_state.atomic_write_text(settings_path, json.dumps(settings, indent = 2) + "\n")
    # waiver: install-phase outcome token, not a reusable domain key
    return "migrated"
  # waiver: install-phase outcome token, not a reusable domain key
  return "no-stale-entries"


def bootstrap_lazy_settings_local_gitignore(repo: Path | str) -> str:
  """
  Ensure `.claude/lazy.settings.local.json` is listed in the repository's `.gitignore`.

  The local-overlay companion to the tracked `lazy.settings.json` lives at
  `.claude/lazy.settings.local.json` and carries per-machine or personal configuration
  that must not be committed. This mirrors the convention Claude Code follows for its own
  `.claude/settings.local.json`. No directory or file is created — the local-overlay file
  is opt-in and materialises only when the consumer or a skill writes a local override;
  this step only reserves a slot in `.gitignore` so accidental commits are impossible.
  Idempotent.

  Args:
    repo: Path to the repository root.

  Returns:
    `"bootstrapped"` when the `.gitignore` line was appended, `"already-present"` when
    the line was already there.
  """
  outcome = ensure_gitignore_lines(repo, [ ".claude/lazy.settings.local.json" ])
  # waiver: install-phase outcome token, not a reusable domain key
  return "bootstrapped" if outcome == "updated" else "already-present"


def bootstrap_lazyignore(repo: Path | str, template: Path | str) -> str:
  """
  Seed the repository root `.lazyignore` from the shipped template when absent.

  `.lazyignore` is a git excludes file carrying the *extra* excludes (on top of
  `.gitignore`) that every tree-walking routine honours via git's ignore engine —
  venvs, `node_modules`, `__pycache__`, and in-tree worktrees. The consumer's own
  edits are authoritative: an existing `.lazyignore` is never overwritten, so the
  seed only ever creates a missing file. No-op when the template source is absent.
  Idempotent.

  Guarantees:
    - An existing `.lazyignore` is never overwritten; the consumer's own content is
      always left exactly as it was.

  Args:
    repo: Path to the repository root.
    template: Path to the shipped `.lazyignore` template to copy from.

  Returns:
    `"seeded"` when the template was copied into a previously-absent
    `.lazyignore`, `"already-present"` when the consumer already has one,
    `"template-missing"` when the shipped template source could not be read.
  """
  repo = Path(repo)
  template = Path(template)
  # waiver: filesystem filename idiom, not a domain constant
  target = repo / ".lazyignore"

  # Domain(install.reconciliation):
  # # A standing precondition, not a one-time seed
  # Most of what an install phase writes is seeded once and then left alone, but an ignore entry
  # a daemon's own job execution actually depends on cannot wait for a first-time seed: an
  # untracked workspace directory left behind by an in-flight job makes the checkout's working
  # tree look dirty to every later check, and a daemon halts rather than run against a dirty
  # tree. So this one entry is ensured on every single run, even on a checkout that was
  # bootstrapped long before this precondition existed.

  # The worktree-root gitignore entry is a precondition of every `workspace: branch` job, not a
  # first-seed nicety: an untracked `<worktree_root>/job-<id>/` makes the primary checkout's
  # `git status --porcelain` non-empty and the daemon halts on `uncommitted_changes`. So it runs
  # on EVERY invocation, idempotently, before the seed-only guard below — repos installed before
  # this line shipped get the entry on their next install/setup. The root is the configured one,
  # not a hardcoded name.
  git_cfg = load_tracked_section(repo / SettingsFile.REL, SettingsKey.DAEMON).get(DaemonKey.GIT) or {}
  # waiver: filesystem path idiom, not a domain constant
  worktree_root = str(git_cfg.get(GitConfigKey.WORKTREE_ROOT, ".worktrees")).strip("/")
  ensure_gitignore_lines(repo, [ f"{worktree_root}/" ])

  # Contract:
  # An existing `.lazyignore` is never overwritten; the consumer's own content is
  # always left exactly as it was.

  # guard: consumer already has a .lazyignore — their copy is authoritative
  if target.exists():
    # waiver: install-phase outcome token, not a reusable domain key
    return "already-present"

  # guard: shipped template absent — nothing to seed from
  if not template.is_file():
    # waiver: install-phase outcome token, not a reusable domain key
    return "template-missing"

  # seed the consumer's copy from the shipped template
  # waiver: stdlib encoding idiom
  target.write_text(template.read_text(encoding = "utf-8"), encoding = "utf-8")

  # the install chain distinguishes a phase that planted the file from one that found it
  # already there, so a re-run reads as quiet rather than as work redone
  # waiver: install-phase outcome token, not a reusable domain key
  return "seeded"


# waiver: external Claude Code filesystem locations, not reusable domain keys
_INSTALLED_PLUGINS_REL = ".claude/plugins/installed_plugins.json"
# waiver: external Claude Code filesystem location, not a reusable domain key
_SETTINGS_JSON_REL = ".claude/settings.json"
# waiver: external Claude Code filesystem location, not a reusable domain key
_SETTINGS_LOCAL_JSON_REL = ".claude/settings.local.json"
# waiver: the interpreter command every plugin call site falls back to when the override is unset
_DEFAULT_PYTHON_COMMAND = "python3"
# waiver: external env-var name every plugin call site expands, not an internal key
_PYTHON_ENV_VAR = "LAZYCORTEX_PYTHON"


def record_python_env(repo: Path | str, command: str, executable: str) -> str:
  """
  Record the interpreter command an install probe resolved, for call sites to reuse later.

  Skips recording when the resolved command is the default `python3`, since every call site
  already falls back to it. Otherwise persists `LAZYCORTEX_PYTHON` into the repository's
  `.claude/settings.local.json` `env` block, preserving any other content already there.

  Guarantees:
    - An existing `LAZYCORTEX_PYTHON` value is never overwritten.
    - Other settings already in `.claude/settings.local.json` are never discarded.

  Args:
    repo: Path to the repository root.
    command: Interpreter command the probe resolved (`python3`, `python`, or `py -3`).
    executable: Absolute path to the interpreter, recorded when `command` has more than one word.

  Returns:
    `"not-needed"` when `command` is the default `python3` and nothing was written,
    `"recorded"` when the value was newly written, `"unchanged"` when the same value was
    already on record, `"kept-local"` when a different value was already on record and the
    file was left untouched.

  Raises:
    json.JSONDecodeError: If the local settings file exists but is not valid JSON.
  """

  # Contract:
  # An interpreter override the operator already has on record is never overwritten;
  # the operator's own value always wins over the one the probe resolved.

  # Contract:
  # Recording never discards other settings already in the local settings file;
  # the interpreter override is the only thing added.

  # guard: the fallback every call site already uses needs no record
  if command == _DEFAULT_PYTHON_COMMAND:
    # waiver: install-phase outcome token, not a reusable domain key
    return "not-needed"

  # call sites expand the variable quoted, as one word — a multi-word command (`py -3`) is replaced by its interpreter's path
  value = command if len(command.split()) == 1 else Path(executable).as_posix()

  # merge into the local settings' env block, creating the file when absent
  path = Path(repo) / _SETTINGS_LOCAL_JSON_REL
  # waiver: stdlib encoding idiom
  settings = json.loads(path.read_text(encoding = "utf-8")) if path.exists() else {}
  # waiver: external Claude Code settings field name, not an internal key
  env = settings.setdefault("env", {})

  # guard: a value already on record is the operator's and is never overwritten
  if _PYTHON_ENV_VAR in env:
    # waiver: install-phase outcome tokens, not reusable domain keys
    return "unchanged" if env[_PYTHON_ENV_VAR] == value else "kept-local"

  # absent — record the resolved command and write the merged settings back
  env[_PYTHON_ENV_VAR] = value
  path.parent.mkdir(parents = True, exist_ok = True)
  runtime_state.atomic_write_text(path, json.dumps(settings, indent = 2) + "\n")
  # waiver: install-phase outcome token, not a reusable domain key
  return "recorded"


def _installed_entries(installed_plugins: Path, plugin_key: str) -> list:
  """
  Read the install-record entries for one plugin key from an `installed_plugins.json` manifest.

  Gives install-phase callers the per-project install history recorded for a plugin key, so
  they can determine where the plugin was previously installed.

  Args:
    installed_plugins: Path to the `installed_plugins.json` manifest.
    plugin_key: The `<plugin>@<marketplace>` key to look up.

  Returns:
    The install-record entries for `plugin_key`, or an empty list when the manifest is
    absent or the key is unknown or empty.
  """
  # guard: no manifest on disk — plugin was never installed on this machine
  if not installed_plugins.exists():
    return []
  # waiver: stdlib encoding idiom
  data = json.loads(installed_plugins.read_text(encoding = "utf-8"))
  # waiver: external Claude Code manifest field name, not an internal key
  plugins = data.get("plugins", data)
  return plugins.get(plugin_key) or []


def _plugin_enabled(plugin_key: str, *settings_paths: Path) -> bool:
  """
  Report whether a plugin key is activated across a precedence-ordered set of settings files.

  Used by install-phase callers to check plugin activation across the project and user
  settings scopes without parsing each file separately.

  Notes:
    - Settings files that are absent or contain invalid JSON are skipped without raising.

  Args:
    plugin_key: The `<plugin>@<marketplace>` key to test.
    settings_paths: Settings files in increasing-precedence order; a later file's entry
      overrides an earlier file's entry for the same key.

  Returns:
    `True` when the merged `enabledPlugins` view activates `plugin_key`, `False` otherwise.
  """
  merged: dict = {}
  for path in settings_paths:
    # guard: skip a settings file that is absent
    if not path.exists():
      continue
    try:
      # waiver: stdlib encoding idiom
      data = json.loads(path.read_text(encoding = "utf-8"))
    except json.JSONDecodeError:
      # guard: an unparseable settings file contributes no signal
      continue
    # waiver: external Claude Code settings field name, not an internal key
    merged.update(data.get("enabledPlugins") or {})
  return bool(merged.get(plugin_key))


def detect_install_scope(
    plugin_key: str, project_root: Path | str = ".", home: Path | str | None = None
) -> str:
  """
  Resolve which scope a plugin's config should target.

  Used by install-phase callers to route generated config into the project checkout or the
  user's global settings, following wherever the plugin is actually enabled rather than
  where it was originally installed.

  Args:
    plugin_key: The `<plugin>@<marketplace>` key to detect.
    project_root: Path whose `.claude/` holds the project settings and is the project scope.
    home: Home directory holding the global `.claude/`; defaults to the current user's home.

  Returns:
    `"project"` when the plugin is enabled at the project scope, `"user"` when it is enabled
    only at the user scope or the install record's own scope resolves there, and
    `"not-installed"` when the plugin has no install record at all, regardless of enablement.
  """

  # Domain(install.reconciliation):
  # # Install-scope resolution follows activation, not history
  # Where a plugin's generated configuration should land is decided by where the plugin is
  # actually switched on right now, never by where it happened to be installed originally — a
  # plugin installed once at the user scope but later enabled for one project must have its
  # config land in that project. Project-level activation is the strongest signal and wins
  # outright even when the original install record claims the user scope. Only when neither
  # settings scope shows the plugin active does the original install record's own scope decide,
  # preferring the project scope when the record lists both.

  home = Path.home() if home is None else Path(home)
  project_root = Path(project_root)

  # the shared cache is the sole proof the plugin is installed on this machine
  entries = _installed_entries(home / _INSTALLED_PLUGINS_REL, plugin_key)

  # guard: no install record aborts regardless of any enablement flag — there are no sources to sync
  if not entries:
    # waiver: install-scope detection signal, not a reusable domain key
    return "not-installed"

  # project activation is the strongest signal — it wins even when the install record's own
  # scope says "user" (install-scope records where /plugin install ran, not where it is active)
  if _plugin_enabled(
      plugin_key,
      project_root / _SETTINGS_JSON_REL,
      project_root / _SETTINGS_LOCAL_JSON_REL,
  ):
    # waiver: external Claude Code install scope value
    return "project"

  # enabled only in the global settings → target the user scope
  if _plugin_enabled(
      plugin_key,
      home / _SETTINGS_JSON_REL,
      home / _SETTINGS_LOCAL_JSON_REL,
  ):
    # waiver: external Claude Code install scope value
    return "user"

  # neither settings file activates the plugin — fall back to the install record's own scope,
  # preferring project when both scopes appear in the array
  scopes = { entry.get("scope") for entry in entries }
  # waiver: external Claude Code install scope value
  return "project" if "project" in scopes else "user"


def bootstrap_daemon_git(repo: Path | str) -> str:
  """
  Seed the `daemon.git` block of the repository's tracked settings from the checkout itself.

  Both fields are derived, never asked: `base_branch` is the branch currently checked out,
  and `remote_sync` is `"pull_push"` when the checkout has an `origin` remote — a daemon
  that commits routine output into a checkout nobody else reads must publish it, and a
  checkout without a remote has nowhere to publish to. `post_push_hook` stays operator
  territory and is never seeded. Absent-only: a block already carrying content is left
  untouched, so an operator's hand-written configuration survives every re-run.

  Guarantees:
    - An operator-authored `daemon.git` block is never overwritten; once it carries any
      content, this phase leaves it untouched on every later run.

  Args:
    repo: Path to the repository root.

  Returns:
    `"seeded"` when the block was written, `"kept-local"` when a non-empty block was
    already on record, `"skipped-no-branch"` when the checkout has no branch to ride
    (not a repository, or a detached `HEAD`).
  """

  # Domain(install.reconciliation):
  # # Derived-only automation git block
  # The checkout's own git state is the sole source for the settings a daemon's git behaviour
  # reads — never a question asked of the operator — because the checkout already carries the
  # one true answer: which branch is checked out, and whether a remote exists to publish routine
  # commits to. A checkout with no remote has nowhere to publish generated commits, so nothing is
  # assumed there. Once an operator has written anything into this block by hand, it is never
  # touched again by this derivation, on any later run.

  repo = Path(repo)
  branch = _git_capture(repo, [ "rev-parse", "--abbrev-ref", "HEAD" ])

  # guard: no branch to ride — not a repo, or a detached HEAD the daemon must not check out
  if branch is None or branch == "HEAD":
    # waiver: install-phase outcome token, not a reusable domain key
    return "skipped-no-branch"

  # read the daemon section the seed would land in
  settings = repo / SettingsFile.REL
  section = load_tracked_section(settings, SettingsKey.DAEMON)

  # Contract:
  # An operator-authored `daemon.git` block is never overwritten; once any content is
  # recorded there, this phase leaves it untouched on every later run.

  # guard: an operator-written block is authoritative — never overwrite what is already there
  if section.get(DaemonKey.GIT):
    # waiver: install-phase outcome token, not a reusable domain key
    return "kept-local"

  # derive the block from the checkout itself — a remote means routine output has somewhere to go
  block = { GitConfigKey.BASE_BRANCH: branch }
  if _git_capture(repo, [ "remote", "get-url", "origin" ]) is not None:
    block[GitConfigKey.REMOTE_SYNC] = "pull_push"

  # persist the derived block into the tracked settings
  section[DaemonKey.GIT] = block
  save_section(settings, SettingsKey.DAEMON, section)
  # waiver: install-phase outcome token, not a reusable domain key
  return "seeded"


def _git_capture(repo: Path, args: list[str]) -> str | None:
  """
  Run a read-only git command in `repo` and return its stripped stdout.

  Args:
    repo: Working directory the command runs in.
    args: Git arguments, without the leading `git`.

  Returns:
    The command's stripped stdout, or `None` when git is absent or exited non-zero.
  """
  try:
    done = subprocess.run(
      [ "git", *args ], cwd = repo, capture_output = True, text = True, check = False, encoding = "utf-8",
    )
  except OSError:
    return None

  # guard: non-zero exit means the fact is unavailable, not empty
  if done.returncode != 0:
    return None
  return done.stdout.strip() or None


def bootstrap_memory_dir(repo: Path | str) -> str:
  """
  Create `.memory/` at the repository root and strip any legacy `!.memory/` gitignore line.

  `.memory/` is the version-tracked store for persona-marked experts' long-term notes and
  lives in git the normal way, with no negation rule. Earlier versions of this skill
  appended `!.memory/` defensively against sweeping consumer gitignores such as
  `.[a-z]*`; that line is now considered selective paranoia and is migrated away on
  upgrade. Idempotent.

  Args:
    repo: Path to the repository root.

  Returns:
    `"bootstrapped"` when the directory was created or a legacy `!.memory/` line was
    removed, `"already-present"` when the directory existed and no legacy line was
    present.
  """
  repo = Path(repo)
  # waiver: filesystem filename idiom, not a domain constant
  mem = repo / ".memory"
  mem_existed = mem.is_dir()
  if not mem_existed:
    mem.mkdir(parents = True, exist_ok = True)

  # migrate away the legacy negation line earlier versions appended
  gi_outcome = remove_gitignore_lines(repo, [ "!.memory/", "!.memory" ])

  # a fresh directory or a scrubbed legacy line each count as work done
  # waiver: install-phase outcome token, not a reusable domain key
  if not mem_existed or gi_outcome == "removed":
    # waiver: install-phase outcome token, not a reusable domain key
    return "bootstrapped"
  # waiver: install-phase outcome token, not a reusable domain key
  return "already-present"
