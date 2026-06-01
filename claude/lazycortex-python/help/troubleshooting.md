---
chapter_type: troubleshooting
summary: Symptoms, causes, and fixes for lazycortex-python install, audit, and style checks.
last_regen: 2026-06-01
diagram_spec:
  anchor: "Diagnostic flowchart"
  request: "Decision-tree routing install/audit/check-style failures: top-level branch on skill invoked (install vs audit vs check-style); install branch splits on phase (source-not-found, rule-read-only, wrapper-template-missing, pyproject-absent, pch-no-inspect-sh, scaffold-sync-fails); audit branch splits on check number (check1 drift, check2 broken-pointer, check3 artifact-missing, check4 placeholder, check10 invalid-json, check11 venv-degraded); check-style branch splits on step (step3-manual-vs-chk, step5-test-gate, step6-violations-persist); each leaf names the fix action"
  kind_hint: decision-tree
source_skills:
  - lazy-python.install
  - lazy-python.audit
  - lazy-python.check-style
---
# Troubleshooting

## `/lazy-python.install` stops immediately: "plugin source not found"

**Symptom**: Running `/lazy-python.install` aborts at the very first phase with a message that `${CLAUDE_PLUGIN_ROOT}` is unset or contains no `rules/lazy-python.*.md` files.

**Likely cause**: The `lazycortex-python` plugin is not installed or not enabled in `~/.claude/settings.json`, so Claude Code never set `CLAUDE_PLUGIN_ROOT` for it.

**Fix**: Confirm `lazycortex-python@lazycortex` appears under `enabledPlugins` in `~/.claude/settings.json` and that the marketplace entry for `lazycortex` is present. Restart Claude Code after saving, then re-run `/lazy-python.install`.

---

## `/lazy-python.install` Step 1 fails: rule file is read-only

**Symptom**: Phase 1 of the install exits with a permission error when trying to write one of the three mirrored rule files under `.claude/rules/`.

**Likely cause**: A previous session or version-control operation left a `lazy-python.*.md` rule file with no write permission. The mirror step always overwrites, so a locked file blocks it.

**Fix**: Unlock the affected file (`chmod u+w .claude/rules/lazy-python.<name>.md`) and re-run `/lazy-python.install`. The mirror is intentionally clobbered — do not hand-edit the file after unlocking; the install will write the correct canon content.

---

## `/lazy-python.install` Step 2 fails: wrapper template missing

**Symptom**: Phase 2 cannot find `chk-wrapper.sh` or `tst-wrapper.sh` under the plugin's `templates/` directory, leaving `cli/chk-py` and `cli/tst-py` undeployed.

**Likely cause**: The local plugin cache is incomplete — the templates directory was not fully synced when the plugin was installed or last updated.

**Fix**: Run `/plugin update lazycortex-python@lazycortex` to restore the full plugin cache, then re-run `/lazy-python.install`.

---

## `pyproject.toml` is absent and checker sections never merged

**Symptom**: `/lazy-python.install` Phase 3 completes but the seven checker sections (`[tool.pcf]`, `[tool.toi]`, `[tool.pytest]`, `[tool.mypy]`, `[tool.pylint]`, `[tool.ruff]`, and optionally `[tool.pch]`) are missing when you run `/lazy-python.audit`. The audit reports `check5 FAIL` (three or more sections missing, or `pyproject.toml` not found).

**Likely cause**: The project has no `pyproject.toml` at the repo root. Phase 3 merges into the existing file; it does not create one from scratch.

**Fix**: Create a minimal `pyproject.toml` at the repo root (a `[build-system]` section is enough to start), then re-run `/lazy-python.install`. Phase 3 will append all missing sections.

---

## `chk-py pch` always skips: PyCharm `inspect.sh` not found

**Symptom**: Running `chk-py pch <file>.py` exits immediately with a message that `inspect.sh` was not found. `/lazy-python.audit` reports `check6 WARN`.

**Likely cause**: PyCharm is not installed, or its `inspect.sh` script is not on `$PATH`. The `pch` component of the aggregator depends on this script to run PyCharm's offline inspections.

**Fix**: The rest of the checker stack (`pcf`, `toi`, `mypy`, `pylint`, `pytest`, `ruff`) is unaffected. Install PyCharm and ensure its `bin/inspect.sh` is on `$PATH` if full `pch` coverage is needed. Until then, `check6 WARN` is expected and safe to ignore.

---

## `/lazy-python.install` Step 6 scaffold-sync fails or skips

**Symptom**: After install, `cli/chk-py` and the rules are in place, but new `*.py` files are not being matched to the Python scaffold template by `lazy-core.scaffold`. The audit's `check8` reports `WARN` (scaffold registry entry absent).

**Likely cause**: Phase 6 dispatches `lazy-core.scaffold-sync`. If `lazycortex-core` is not installed or its `scaffold-sync` skill is not reachable, the registry entry in `.claude/rules/lazy-core.scaffold.md` is never written.

**Fix**: Verify `lazycortex-core` is installed and enabled, then re-run `/lazy-python.install`. Phase 6 will retry the `scaffold-sync` dispatch and upsert the `python-template.py` entry.

---

## `/lazy-python.audit` `check1` reports `FAIL` — rule drift detected

**Symptom**: Audit check 1 shows `FAIL` with a message that one or more `.claude/rules/lazy-python.*.md` files differ from the plugin canon.

**Likely cause**: A rule file under `.claude/rules/` was hand-edited after install. The mirror is plugin-managed; consumer edits are not supported and will be clobbered on the next install run.

**Fix**: Re-run `/lazy-python.install`. Phase 1 intentionally overwrites the mirror with the current plugin canon. If you need project-specific overrides, add them to the overlay files under `docs/guidelines/` — writer agents read those after the canon and overlay rules win on conflict.

---

## `/lazy-python.audit` `check2` reports `FAIL` — broken reference pointer

**Symptom**: Check 2 exits `FAIL` reporting that a mirrored rule cites a `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.*.md` path that no longer exists in the plugin.

**Likely cause**: Either the plugin's canon was reorganised (a references file was renamed or removed) and your local mirror is stale, or the plugin shipped an inconsistent release.

**Fix**: Re-run `/lazy-python.install` first — the new mirror may reference the correct path and resolve the check. If the error persists after reinstall, the plugin itself has a broken reference; file an issue against `lazycortex-python@lazycortex`.

---

## `/lazy-python.audit` `check3` reports `FAIL` — plugin tree incomplete

**Symptom**: Check 3 exits `FAIL` listing one or more artifact paths (rules, references, binaries, hook script, `hooks.json`, skill files, agent files, templates) that are absent from `${CLAUDE_PLUGIN_ROOT}`.

**Likely cause**: The plugin was only partially synced to the local cache, or a file was deleted from the plugin directory after install.

**Fix**: Run `/plugin update lazycortex-python@lazycortex` to restore the full plugin tree, then re-run `/lazy-python.audit` to confirm all checks pass.

---

## `/lazy-python.audit` `check4` reports `FAIL` — unsubstituted placeholder in wrapper

**Symptom**: Check 4 exits `FAIL` reporting that `cli/chk-py` or `cli/tst-py` still contains a `{{CHK_BIN_PATH}}` or `{{TST_BIN_PATH}}` literal — the template was copied but the path substitution never ran.

**Likely cause**: Phase 2 of the install was interrupted after copying the wrapper template but before completing the substitution and `chmod +x` steps.

**Fix**: Re-run `/lazy-python.install`. Phase 2 redeploys both wrappers from scratch, performing substitution and setting the executable bit. The step is idempotent.

---

## `/lazy-python.audit` `check10` reports `FAIL` — `hooks.json` is invalid JSON

**Symptom**: Check 10 exits `FAIL` (not `WARN`) with a JSON parse error on the plugin's `hooks/hooks.json` manifest. The PostToolUse check-style hook will not auto-register until this is fixed.

**Likely cause**: The plugin cache on disk is corrupted — the `hooks.json` file was partially written or manually edited.

**Fix**: Run `/plugin update lazycortex-python@lazycortex` to restore the manifest, then re-run `/lazy-python.audit` to confirm `check10` passes.

---

## `/lazy-python.audit` `check11` reports `WARN` — venv degraded

**Symptom**: Check 11 shows `WARN`. Running `cli/chk-py` immediately fails because `mypy`, `pylint`, `pytest`, or `ruff` is not found, or the `pytest-clarity`/`pytest-sugar` plugins are absent from the venv.

**Likely cause**: The venv probe could not find a usable virtual environment — either no `$VIRTUAL_ENV` is active, no `.venv` exists in the project root, no `[tool.lazy-python].venv` entry in `pyproject.toml`, and the plugin-data fallback either has not been bootstrapped or is stale.

**Fix**: Activate a project venv that has `mypy`, `pylint`, `pytest`, and `ruff` installed (or create one with `uv venv && uv pip install mypy pylint pytest ruff pytest-clarity pytest-sugar`). Re-run `/lazy-python.audit`; check 11 will upgrade to `PASS` once it finds the venv. Alternatively, re-run `/lazy-python.install` to trigger the fallback bootstrap via `_ensure_venv.sh` if `uv` is on `$PATH`.

---

## `chk-py` reports clean but `/lazy-python.check-style` still finds issues

**Symptom**: Step 4 of `/lazy-python.check-style` shows no `chk-py` violations, but Step 3 (manual review) already recorded issues — or the user can see obvious style problems that the checker did not flag.

**Likely cause**: The automated checkers cover syntactic and type-level rules; they do not enforce semantic docstring quality, contract consistency (docstring vs. signature drift), guard-clause presence, method ordering, or comment preservation. A clean `chk-py` run does not mean the file is review-complete.

**Fix**: This is expected behaviour. The manual review in Step 3 is mandatory precisely because the checkers have this gap. Work through the manual-review categories (docstring quality, contract consistency, guard clauses, method organization, naming, comment preservation) and apply targeted fixes via Step 5 before treating the file as done.

---

## `/lazy-python.check-style` Step 5 stops and asks before editing a test file

**Symptom**: During the fix pass, the skill pauses and asks via `AskUserQuestion` whether it may edit a file under `tests/**`, naming the specific file.

**Likely cause**: A violation found in Step 3 or Step 4 is inside a test file. The skill enforces a hard gate: test files may not be silently modified to keep the suite green.

**Fix**: This is correct behaviour, not a bug. If the test file genuinely has a style violation unrelated to the test's contract (e.g. a line-length issue), approve the edit. If the violation is in an assertion, the underlying production code likely has a regression — fix the production code, not the test.

---

## `/lazy-python.check-style` Step 6 still reports violations after fixes landed

**Symptom**: After Step 5 applied targeted fixes, the re-verify pass in Step 6 reports that violations remain. The skill surfaces the remaining list and asks how to proceed rather than looping.

**Likely cause**: The fix was targeted at a single file or line, but the violation spans multiple files (a removed public API, a broken import chain, a cross-file type reference) or the canon rule was misread and the fix introduced a different issue.

**Fix**: Read the remaining violation list carefully. If the issue is cross-file, run `chk-py all -q` manually to see the full picture and address each file in turn. If the violation is a misread rule, consult `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.coding-guidelines.md` for the canonical wording before re-applying the fix.

---

## Diagnostic flowchart
