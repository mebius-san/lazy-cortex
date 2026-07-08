"""
Reusable phases extracted from `lazy-core.install` for testability.

Each function takes a repo path and is idempotent — repeated calls on an
already-bootstrapped repository complete without side effects beyond the
initial materialisation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

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

  Args:
    repo: Path to the repository root.
    lines: Entries to ensure are present in `.gitignore`.

  Returns:
    `"updated"` when at least one line was appended, `"already-present"` when every
    requested line was already present.
  """
  repo = Path(repo)
  # waiver: filesystem filename idiom, not a domain constant
  gi = repo / ".gitignore"
  # waiver: stdlib encoding idiom
  existing = gi.read_text(encoding = "utf-8") if gi.exists() else ""
  existing_set = { line.strip() for line in existing.splitlines() }

  # collect entries that are neither present as-is nor as their slash-variant
  to_append = []
  for line in lines:
    stripped = line.strip()
    variants = { stripped, stripped.rstrip("/"), stripped + "/" }
    # guard: skip entries already covered by an existing line variant
    if not existing_set & variants:
      to_append.append(stripped)

  # guard: no work to do — every requested entry is already present
  if not to_append:
    # waiver: install-phase outcome token, not a reusable domain key
    return "already-present"

  suffix = "" if existing.endswith("\n") or not existing else "\n"
  appended = "".join(f"{ln}\n" for ln in to_append)
  # waiver: stdlib encoding idiom
  gi.write_text(f"{existing}{suffix}{appended}", encoding = "utf-8")
  # waiver: install-phase outcome token, not a reusable domain key
  return "updated"


def remove_gitignore_lines(repo: Path | str, lines: list[str]) -> str:
  """
  Remove every line matching any entry in `lines` from the repository's `.gitignore`.

  Matches by exact stripped equality — the caller passes the exact form they want gone,
  with no slash-variant tolerance (unlike `ensure_gitignore_lines`). No-op when
  `.gitignore` is absent. Idempotent.

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

  targets = { ln.strip() for ln in lines }
  # waiver: stdlib encoding idiom
  src_lines = gi.read_text(encoding = "utf-8").splitlines()
  kept = [ ln for ln in src_lines if ln.strip() not in targets ]

  # guard: every source line survived the filter — nothing matched
  if len(kept) == len(src_lines):
    # waiver: install-phase outcome token, not a reusable domain key
    return "already-absent"

  body = "\n".join(kept)
  # waiver: stdlib encoding idiom
  gi.write_text(body + ("\n" if body else ""), encoding = "utf-8")
  # waiver: install-phase outcome token, not a reusable domain key
  return "removed"


# ---------- bootstrap phases ----------

def bootstrap_logs_dir(repo: Path | str) -> str:
  """
  Create `.logs/` and `.runtime/` at the repository root and list both in `.gitignore`.

  `.logs/` holds the runtime journal (daemon output, recall logs, commit-recorder feed).
  `.runtime/` holds non-log daemon state — currently `state.json`, which carries the
  `last_run`, `git_watch`, and `daemon_halted` blocks. Missing directories are created;
  missing `.gitignore` lines are appended; existing entries are left untouched.
  Idempotent.

  Args:
    repo: Path to the repository root.

  Returns:
    `"bootstrapped"` when at least one directory was created or at least one `.gitignore`
    line was appended, `"already-present"` when both directories and both `.gitignore`
    lines already existed.
  """
  repo = Path(repo)

  # create each runtime directory, tracking whether the call materialised something new
  dir_created_any = False
  for name in (".logs", ".runtime"):
    d = repo / name
    existed = d.is_dir()
    d.mkdir(exist_ok = True)
    if not existed:
      dir_created_any = True

  gi_outcome = ensure_gitignore_lines(repo, [ ".logs/", ".runtime/" ])

  # waiver: install-phase outcome token, not a reusable domain key
  if dir_created_any or gi_outcome == "updated":
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

  if changed:
    # waiver: external Claude Code settings field name, not an internal key
    settings["hooks"] = hooks
    # waiver: stdlib encoding idiom
    settings_path.write_text(json.dumps(settings, indent = 2) + "\n", encoding = "utf-8")
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

  # guard: consumer already has a .lazyignore — their copy is authoritative
  if target.exists():
    # waiver: install-phase outcome token, not a reusable domain key
    return "already-present"

  # guard: shipped template absent — nothing to seed from
  if not template.is_file():
    # waiver: install-phase outcome token, not a reusable domain key
    return "template-missing"

  # waiver: stdlib encoding idiom
  target.write_text(template.read_text(encoding = "utf-8"), encoding = "utf-8")

  # ensure .worktrees/ is gitignored so in-tree worktrees don't dirty the tree
  # and halt the daemon's _check_working_tree guard
  ensure_gitignore_lines(repo, [ ".worktrees/" ])

  # waiver: install-phase outcome token, not a reusable domain key
  return "seeded"


# waiver: external Claude Code filesystem locations, not reusable domain keys
_INSTALLED_PLUGINS_REL = ".claude/plugins/installed_plugins.json"
# waiver: external Claude Code filesystem location, not a reusable domain key
_SETTINGS_JSON_REL = ".claude/settings.json"
# waiver: external Claude Code filesystem location, not a reusable domain key
_SETTINGS_LOCAL_JSON_REL = ".claude/settings.local.json"


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
  home = Path.home() if home is None else Path(home)
  project_root = Path(project_root)

  # guard: the shared cache is the sole proof the plugin is installed — its absence aborts
  # regardless of any enablement flag, since there are no sources to sync
  entries = _installed_entries(home / _INSTALLED_PLUGINS_REL, plugin_key)
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

  gi_outcome = remove_gitignore_lines(repo, [ "!.memory/", "!.memory" ])

  # waiver: install-phase outcome token, not a reusable domain key
  if not mem_existed or gi_outcome == "removed":
    # waiver: install-phase outcome token, not a reusable domain key
    return "bootstrapped"
  # waiver: install-phase outcome token, not a reusable domain key
  return "already-present"
