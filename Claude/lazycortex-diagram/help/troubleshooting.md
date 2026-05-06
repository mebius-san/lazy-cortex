---
chapter_type: troubleshooting
summary: Common failure modes across lazycortex-diagram skills — symptoms, likely causes, and fixes.
last_regen: 2026-05-05
diagram_spec:
  anchor: "Diagnostic flowchart"
  request: "Decision-tree routing failures across lazycortex-diagram skills. Top-level branch on which skill is failing: install vs draw vs fix. Install branch splits on 'plugin not installed' vs 'cache empty'. Draw branch splits on input validation failures (target_file not found, anchor not found, empty request, unsupported format) vs kind-resolution failures (no-kind-fits-request) vs scheme failures (scheme-not-found) vs template-compatibility failure (format-not-supported-for-kind) vs drawer-agent failures (failed:<reason>, split-into-N, skipped-below-threshold). Fix branch splits on no-fence-under-anchor, cannot-infer-format, cannot-infer-kind, and then the same scheme/drawer-agent leaves shared with the draw branch. Each leaf labels the troubleshooting entry that resolves it."
source_skills:
  - lazy-diagram.draw
  - lazy-diagram.fix
  - lazy-diagram.install
---
# Troubleshooting

## Plugin not found when running /lazy-diagram.install

**Symptom**: `/lazy-diagram.install` aborts immediately with "plugin not installed" and no further steps execute.

**Likely cause**: `lazycortex-diagram@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` — the plugin was never enabled or the entry was removed.

**Fix**: Add `"lazycortex-diagram@lazycortex": true` to the `enabledPlugins` block in your `settings.json`, restart Claude Code, then re-run `/lazy-diagram.install`.

---

## /lazy-diagram.install aborts with "plugin cache is empty"

**Symptom**: `/lazy-diagram.install` detects the plugin but then aborts saying the plugin cache is empty and zero rule files were found.

**Likely cause**: The plugin is enabled but its file cache was never populated — either the initial download failed, or the cache was cleared.

**Fix**: Run `/plugin update lazycortex-diagram@lazycortex` to refresh the cache, then re-run `/lazy-diagram.install`.

---

## /lazy-diagram.draw aborts: target file not found

**Symptom**: `/lazy-diagram.draw` fails at Step 1 with `[FAIL] target_file not found`.

**Likely cause**: The path supplied as `target_file` does not exist on disk — it may be a typo, a relative path, or a file not yet created.

**Fix**: Verify the absolute path is correct. If the file does not exist yet, create it first, then re-run `/lazy-diagram.draw` with the correct `target_file=<abs path>`.

---

## /lazy-diagram.draw aborts: anchor heading not found

**Symptom**: `/lazy-diagram.draw` fails at Step 1 with `[FAIL] anchor not found in target_file`.

**Likely cause**: The heading text passed as `anchor_section` does not appear verbatim as an H2 or H3 in the target file — casing, extra spaces, or a missing `##` prefix are common causes.

**Fix**: Open the target file and confirm the exact heading text, including `##` or `###` prefix. Pass the heading to `anchor_section=` exactly as it appears, then re-run.

---

## /lazy-diagram.draw aborts: empty request

**Symptom**: `/lazy-diagram.draw` fails at Step 1 with `[FAIL] empty request`.

**Likely cause**: The `request` parameter was omitted or passed as an empty string.

**Fix**: Supply a non-empty `request=<one-line description>` that describes what the diagram should depict, then re-run.

---

## /lazy-diagram.draw aborts: unsupported format

**Symptom**: `/lazy-diagram.draw` fails at Step 1 with `[FAIL] unsupported format=<value>`.

**Likely cause**: The `format` parameter was pinned to a value other than `mermaid` or `ascii`.

**Fix**: Correct `format=` to either `mermaid` or `ascii`, or omit it and let the skill choose automatically.

---

## Skill cannot match the request to any diagram kind

**Symptom**: `/lazy-diagram.draw` reports `failed:no-kind-fits-request` at Step 3 and stops without producing a diagram.

**Likely cause**: No row in the kind-selection heuristic matched the request phrasing. Requests that are too abstract ("show how it works"), too brief (one word), or that describe a concept the heuristic does not cover will produce this outcome.

**Fix**: Rephrase the request to name actors, entities, states, or decision points explicitly (e.g. "sequence diagram showing how the CI pipeline calls the deploy service"). Alternatively, pin `kind=<kind>` from the available list and re-run.

---

## Scheme file not found

**Symptom**: `/lazy-diagram.draw` or `/lazy-diagram.fix` aborts with `failed:scheme-not-found:<name>` at the scheme-resolution step.

**Likely cause**: A `scheme=<name>` was pinned but no matching `styles-<name>.json` file exists in the plugin templates.

**Fix**: Omit `scheme=` to fall back to the `default` scheme, or verify the scheme name by checking the style files available under `${CLAUDE_PLUGIN_ROOT}/templates/diagram.mermaid/`. Re-run with a valid name or without the `scheme=` parameter.

---

## Format not supported for the chosen kind

**Symptom**: `/lazy-diagram.draw` aborts with `failed:format-not-supported-for-kind=<kind>` at Step 5.

**Likely cause**: No template file exists for the `(kind, format)` combination — for example, requesting `format=ascii` for a `sequence` diagram when only a mermaid template ships for that kind.

**Fix**: Check what templates are available under `${CLAUDE_PLUGIN_ROOT}/templates/diagram.<format>/`. Either switch to a supported format (drop or change `format=`) or choose a kind that has a template for the format you need.

---

## Drawer agent returns a failure reason

**Symptom**: `/lazy-diagram.draw` or `/lazy-diagram.fix` reports `failed:<reason>` at the dispatch step — common reasons include `missing-in-style:<role>` or a note that the request was too sparse.

**Likely cause**: The drawer agent encountered a problem rendering the diagram. `missing-in-style:<role>` means the scheme JSON is missing a required colour role; a "too sparse" message means the request or host-section prose did not provide enough named elements for the drawer to produce a valid body.

**Fix**: Check the reason string. For `missing-in-style:<role>`, the scheme file needs attention — re-run `/lazy-diagram.install` to sync the current shipped scheme files, then retry. For a sparse-request failure, add more specific terminology to the `request=` parameter (for draw) or expand the prose in the host section (for fix), then re-run.

---

## Skill returns split-into-N instead of a diagram

**Symptom**: `/lazy-diagram.draw` or `/lazy-diagram.fix` reports `split-into-N` and surfaces a suggested seam list, but no fence is written.

**Likely cause**: The request or host-section prose spans multiple logical diagrams. The drawer agent determined that a single fence would exceed the density bounds for the kind.

**Fix**: Split the request into N separate `/lazy-diagram.draw` calls — one per suggested seam — placing each under its own heading in the target file. For fix, split the section into sub-sections first, then re-run fix per sub-section.

---

## Diagram is skipped as below-threshold

**Symptom**: `/lazy-diagram.draw` or `/lazy-diagram.fix` reports `skipped-below-threshold` and writes nothing.

**Likely cause**: The request or host-section prose has fewer elements than the kind's lower bound (for example, a `flow` diagram requires at least two decision points and four distinct nodes; the request only described one step).

**Fix**: Either expand the request or prose to describe more elements that meet the kind's lower bound, or accept that plain prose is the appropriate artifact for this section and omit the diagram call.

---

## /lazy-diagram.fix aborts: no fence under anchor

**Symptom**: `/lazy-diagram.fix` fails at Step 1 with `[FAIL] no fence under anchor`.

**Likely cause**: The anchor section exists in the target file but contains no `` ```mermaid `` or `` ```text `` fence. Fix only operates on pre-existing fences.

**Fix**: Use `/lazy-diagram.draw` first to create the initial diagram under the heading, then re-run `/lazy-diagram.fix` if drift develops later.

---

## /lazy-diagram.fix cannot infer the format

**Symptom**: `/lazy-diagram.fix` fails at Step 2 with `[FAIL] cannot infer format from info-string=<X>`.

**Likely cause**: The existing fence uses an info-string that is neither `mermaid` nor `text` — for example a bare `` ``` `` or a custom tag added manually.

**Fix**: Pin `format=mermaid` or `format=ascii` explicitly when calling `/lazy-diagram.fix`.

---

## /lazy-diagram.fix cannot infer the diagram kind

**Symptom**: `/lazy-diagram.fix` fails at Step 2 with `[FAIL] cannot infer kind from fence syntax` and lists candidate kinds.

**Likely cause**: The fence's syntax marker (e.g. `flowchart`) matches multiple kinds — `flow`, `nav`, `tree`, `decision-tree`, `controls-scheme`, or `screen-scheme` all use `flowchart` syntax. The skill refuses to guess.

**Fix**: Pin `kind=<one>` from the candidate list shown in the failure message and re-run `/lazy-diagram.fix`.

---

## Diagnostic flowchart
