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
  gi = repo / ".gitignore"
  existing = gi.read_text(encoding = "utf-8") if gi.exists() else ""
  existing_set = { line.strip() for line in existing.splitlines() }

  # collect entries that are neither present as-is nor as their slash-variant
  to_append = []
  for line in lines:
    stripped = line.strip()
    variants = { stripped, stripped.rstrip("/"), stripped + "/" }
    # guard: skip entries already covered by an existing line variant
    if not (existing_set & variants):
      to_append.append(stripped)

  # guard: no work to do — every requested entry is already present
  if not to_append:
    return "already-present"

  suffix = "" if existing.endswith("\n") or not existing else "\n"
  appended = "".join(f"{ln}\n" for ln in to_append)
  gi.write_text(f"{existing}{suffix}{appended}", encoding = "utf-8")
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
  gi = repo / ".gitignore"
  # guard: nothing to scrub when the file does not exist
  if not gi.exists():
    return "already-absent"

  targets = { ln.strip() for ln in lines }
  src_lines = gi.read_text(encoding = "utf-8").splitlines()
  kept = [ ln for ln in src_lines if ln.strip() not in targets ]

  # guard: every source line survived the filter — nothing matched
  if len(kept) == len(src_lines):
    return "already-absent"

  body = "\n".join(kept)
  gi.write_text(body + ("\n" if body else ""), encoding = "utf-8")
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

  if dir_created_any or gi_outcome == "updated":
    return "bootstrapped"
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
    return "no-stale-entries"

  settings = json.loads(settings_path.read_text(encoding = "utf-8"))
  hooks = settings.get("hooks", {})
  changed = False

  # walk each event group, dropping stale hook commands and any matcher block that empties out
  for event in list(hooks.keys()):
    event_entries = hooks.get(event) or []
    new_event_entries = []
    for entry in event_entries:
      kept_hooks = [
        h for h in entry.get("hooks", [])
        if not (isinstance(h, dict)
                and isinstance(h.get("command"), str)
                and _STALE_LOG_HOOK_PATTERN.search(h["command"]))
      ]
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
    settings["hooks"] = hooks
    settings_path.write_text(json.dumps(settings, indent = 2) + "\n", encoding = "utf-8")
    return "migrated"
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
  return "bootstrapped" if outcome == "updated" else "already-present"


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
  mem = repo / ".memory"
  mem_existed = mem.is_dir()
  if not mem_existed:
    mem.mkdir(parents = True, exist_ok = True)

  gi_outcome = remove_gitignore_lines(repo, [ "!.memory/", "!.memory" ])

  if not mem_existed or gi_outcome == "removed":
    return "bootstrapped"
  return "already-present"
