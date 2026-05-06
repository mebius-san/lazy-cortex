---
chapter_type: troubleshooting
summary: Common failure modes across lazycortex-log skills — symptoms, likely causes, and fixes.
last_regen: 2026-05-05
diagram_spec:
  anchor: "Diagnostic flowchart"
  request: "Decision tree branching first on which skill aborted (install vs. clean); for install, split on 'plugin not installed' vs. 'cache is empty'; for clean, split on '.logs/claude/ absent' vs. 'Step 1 canonical resolver failed'; each leaf names the fix."
  kind_hint: decision-tree
source_skills:
  - lazy-log.install
  - lazy-log.clean
---
# Troubleshooting

## `/lazy-log.install` aborts: "plugin not installed"

**Symptom**: Running `/lazy-log.install` stops immediately with a message like "plugin not installed" or "no entry found in `installed_plugins.json`".

**Likely cause**: `lazycortex-log@lazycortex` is not listed in `enabledPlugins` in your `settings.json`, so the plugin was never registered. The skill checks `~/.claude/plugins/installed_plugins.json` and aborts when it finds no entry.

**Fix**: Add `"lazycortex-log@lazycortex": true` to the `enabledPlugins` block in your `settings.json` (project scope for per-repo use, global scope for cross-project use), then restart Claude Code and re-run `/lazy-log.install`.

---

## `/lazy-log.install` aborts: "plugin cache is empty"

**Symptom**: Running `/lazy-log.install` aborts with a message like "plugin cache is empty" or "glob returned zero rule files".

**Likely cause**: The plugin is registered in `enabledPlugins` but its rule files have not been downloaded into the local cache — typically because the plugin was enabled without a subsequent plugin update, or a previous update failed partway through.

**Fix**: Run `/plugin update lazycortex-log@lazycortex` to refresh the cache, then re-run `/lazy-log.install`.

---

## `/lazy-log.clean` aborts immediately: ".logs/claude/ absent"

**Symptom**: Running `/lazy-log.clean` exits right away with a message that `.logs/claude/` does not exist or is absent.

**Likely cause**: No logged skill or agent has ever run in this repo, so the log directory has never been created. The skill has nothing to classify and aborts rather than silently no-op.

**Fix**: Run any skill that writes a run log (for example `/lazy-log.install` or `/lazy-log.audit`) to create the directory, then re-run `/lazy-log.clean`.

---

## `/lazy-log.clean` Step 1 aborts: canonical resolver failed

**Symptom**: `/lazy-log.clean` reaches Step 1 and immediately aborts with "failed: \<reason\>", where the reason mentions Python, `CLAUDE_PLUGIN_ROOT`, or malformed JSON.

**Likely cause**: The `resolve-canonical.py` helper script could not run. Common sub-causes: Python 3 is not on `PATH`, the `CLAUDE_PLUGIN_ROOT` environment variable is unset (meaning the plugin runtime did not inject it), or the plugin cache contains a corrupt JSON file. Without a canonical name set, every log folder would be incorrectly flagged as an orphan, so the skill halts.

**Fix**: Re-run `/lazy-log.install` to ensure the plugin is properly set up and the cache is coherent, then retry `/lazy-log.clean`. If the error specifically mentions Python, confirm that `python3` is available in your shell environment.

---

## Diagnostic flowchart
