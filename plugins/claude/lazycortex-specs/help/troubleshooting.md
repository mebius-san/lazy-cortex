---
chapter_type: troubleshooting
summary: Common failure modes across lazycortex-specs skills — symptoms, likely causes, and targeted fixes.
last_regen: 2026-11-12
no_diagram: true
source_skills:
  - lazy-spec.add-asset-type
  - lazy-spec.coverage
  - lazy-spec.create-asset
  - lazy-spec.create-from-code
  - lazy-spec.create-request
  - lazy-spec.drive
  - lazy-spec.flip-gate
  - lazy-spec.install
  - lazy-spec.lookup
  - lazy-spec.product-config
  - lazy-spec.record-decision
  - lazy-spec.refresh-sources
  - lazy-spec.request-classify
  - lazy-spec.request-find-candidates
  - lazy-spec.resolve-dependency
  - lazy-spec.set-stage
  - lazy-spec.sync-with-code
  - lazy-spec.upstream-run
  - lazy-spec.audit
source_sha: d87a299e3d354b9cf3ae8f1383512a1374b8efc7
surface_sha: d7336d9d046ab72ea22ef0514fdb23002570e64a2794edc6fefa960d71a0e94f
---
# Troubleshooting

## `/lazy-spec.install` aborts: plugin not installed

**Symptom**: The install skill aborts immediately, saying `lazycortex-specs@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json`.

**Likely cause**: The plugin isn't enabled in this Claude Code environment yet — `enabledPlugins` in `settings.json` has no entry for it.

**Fix**: Add `"lazycortex-specs@lazycortex": true` to `enabledPlugins` in your `settings.json`, restart Claude Code, then re-run `/lazy-spec.install`.

---

## `/lazy-spec.install` stops with `aborted:vault-root-not-subdir`

**Symptom**: The install run stops at the start with `aborted:vault-root-not-subdir` and writes nothing.

**Likely cause**: The configured spec vault root is `.` (the repository root), an absolute path, or a path that climbs out of the repository through `..`. The spec catalog must live in a sub-directory of the repository.

**Fix**: Move the spec catalog into a sub-directory of the repository (the default is `specs`), point the vault root at that directory, and re-run `/lazy-spec.install`.

---

## `/lazy-spec.install` reports `refreshed` for a routine you already registered

**Symptom**: A repeat install run reports `refreshed` (rather than `unchanged`) for `lazy-spec.gate-tick`, `lazy-spec.coordinator-watch`, `lazy-spec.collect`, or `lazy-spec.upstream-tick`, even though you already ran install before.

**Likely cause**: Re-running `/lazy-spec.install` no longer leaves an existing routine alone — every registration step calls the routine registrar in reconcile mode. Install-managed keys (the routine type, its path mask or `path_filter`, its frontmatter filter, its `command:` worker) are rewritten to the current shipped shape on every run; the keys that are genuinely yours — `interval_sec`, `timeout_sec`, `priority`, `cron`, `branch`, `hooks_enabled`, `ignore_halt`, and a hand-set `group` — are left exactly as they stand. `refreshed` means one of the managed keys had drifted from what the plugin currently ships (an older filter shape, a narrower glob, a stale worker) and reconcile corrected it; `unchanged` means nothing needed correcting. `lazy-spec.collect` is the postman routine that delivers a finished expert job's terminal marker back into the asset's status folder-note. `lazy-spec.upstream-tick` runs the unattended `upstream/` fetch/detect pass on a schedule — install only registers it once at least one source is configured under `spec.upstream`, skipping silently otherwise.

**Fix**: Nothing to do — a `refreshed` outcome on a managed key is install catching the routine up, not discarding your customization. If you deliberately changed one of the install-managed keys itself (not the operator ones above), that override does not survive reconcile; it is rewritten back to the shipped shape on every run.

---

## `/lazy-spec.install` aborts: `routine <name> already registered`

**Symptom**: An install run aborts partway through, printing `routine <name> already registered` for one of the plugin's routines instead of reporting `registered` / `refreshed` / `unchanged`.

**Likely cause**: The install step that reached this routine called the plain (non-reconcile) registrar instead of passing its `--managed` key list — the plain call refuses outright on a name it already knows, rather than reconciling it. This should not happen on a normal run of the shipped skill; it points at a stale or hand-modified install step.

**Fix**: Re-invoke `/lazy-spec.install` — every shipped step calls the registrar in reconcile mode, so a normal re-run reports `refreshed` or `unchanged` instead of aborting. If the abort persists across re-runs, treat it as a bug in the install skill itself worth reporting rather than something to fix by hand.

---

## `/lazy-spec.install` refuses to reconcile a routine, asking `merge-shipped` or `keep-local`

**Symptom**: An install run stops on one routine (most often `lazy-spec.coordinator-watch` or `lazy-spec.request-apply`) with a `RoutineConfigError`-driven question naming a shape conflict, offering `merge-shipped` or `keep-local`.

**Likely cause**: Reconcile can rewrite individual managed keys, but it cannot merge across a genuine shape change — the recorded entry's `type` differs from what's shipped now, or it still carries an older shape (e.g. the `expert:` + `request:` pair where the shipped routine now uses `command:`). That only happens on a checkout whose routine was registered before a later plugin release changed the routine's shape.

**Fix**: Pick `merge-shipped` to unregister the old entry and re-register the shipped shape, carrying your operator keys (schedule, branch, etc.) over from the removed entry — this is the normal choice. Pick `keep-local` only if you deliberately want to keep running the old shape; the conflict question resurfaces on every install run until you resolve it one way or the other.

---

## `/lazy-spec.product-config` aborts with `aborted:no-vault-spec`

**Symptom**: Running the wizard in create mode (registering a brand-new product) aborts immediately, saying there is neither a `vision.md` nor a pre-vision `design.md` at the spec content-root.

**Likely cause**: The project-wide vault spec — the content-root `vision.md` that states what the project is, for whom, and what counts as success, the document every product split is a consequence of — hasn't been seeded yet. Registering the first product is gated on that file existing (an older, pre-vision content-root `design.md` with no `vision.md` beside it is also accepted as a legal starting state).

**Fix**: Run `/lazy-spec.install` — its Step 6.9 seeds a draft `vision.md` at the content-root when neither file exists — fill it in, then re-run `/lazy-spec.product-config`.

---

## `/lazy-spec.product-config` aborts pointing at `lazycortex-experts`

**Symptom**: The wizard reaches the expert-assignment step and aborts with a message saying a chosen expert name is not registered.

**Likely cause**: The use-case-writer, designer, system-designer, architect, ui-designer, planner, developer, tester, data-writer, researcher, or editor persona you selected for one of the built-in review roles is not a key in the `experts` settings section. This happens when the persona has not been composed yet or the name was mistyped.

**Fix**: Compose the missing persona via `lazycortex-experts` first, then re-run `/lazy-spec.product-config`. Do not type a free-form name that does not exist in the registry — the skill validates every name against `settings-get experts`.

---

## `/lazy-spec.product-config` does not ask about settings a nested product already has

**Symptom**: You registered a product whose `spec_path` sits inside another product's folder, and the wizard skipped questions it asks for a top-level product (asset types, language, mode, review experts), recording them as `inherited`.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the install path that `~/.claude/plugins/installed_plugins.json` records for the plugin, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

**Likely cause**: Products may nest, and the innermost product owns its tree. A `spec_path` under another product's `spec_path` is legal: the wizard resolves the ancestor chain and, for every step whose value the parent already carries, records `inherited` instead of asking. Nothing was skipped by mistake.

**Fix**: If the inherited value is what you want, nothing to do. To give the nested product its own value, re-run `/lazy-spec.product-config` in edit mode on it and declare the value there; an own value wins over the inherited one. For review experts, declaring them generates the product's own review classes, which win over the ancestor's by depth.

---

## `/lazy-spec.product-config` refuses because the `spec_path` ends in a reserved name

**Symptom**: The wizard rejects the path at Step 2, saying the final path segment collides with a reserved name.

**Likely cause**: The folder leaf of `spec_path` is one of the six names reserved for the product-root documents themselves — `vision`, `design`, `ui-design`, `tech`, `use-cases`, `decisions` — because the product's own folder-note shares that leaf's basename, which would collide with the like-named document sitting beside it at the product root (the same six names `/lazy-spec.audit` Check 0 refuses on an existing product). `ui-design` joined the reserved set once the plugin gained a product-level `ui-design.md` — the shared look for the whole product, above the per-asset `ui-design.md` documents.

**Fix**: Choose a `spec_path` whose final segment isn't one of those six names, then re-run `/lazy-spec.product-config`.

---

## `/lazy-spec.product-config` refuses because the product key already exists

**Symptom**: The wizard aborts saying the chosen key is already present in `products`.

**Likely cause**: The product key is an arbitrary string the operator types (lowercase-with-hyphens recommended) — it is not derived from the product's `spec_path` or folder layout — and a product is already registered under that exact key.

**Fix**: If you want to edit the existing product, re-invoke `/lazy-spec.product-config` with that product's key or path — the skill enters edit mode. If you genuinely need a new sibling product, pick a different key.

---

## `/lazy-spec.product-config` skips a declared type, leaving it with no review class

**Symptom**: A project-declared asset type (added via `/lazy-spec.add-asset-type`) never gets its documents reviewed — no `[!question]` about it, but documents of that type sit outside the review loop indefinitely.

**Likely cause**: The type is declared `review: true`, but the operator never answered the `AskUserQuestion` that assigns its experts during a `/lazy-spec.product-config` run — the wizard emits no class for a type it has no expert answer for.

**Fix**: Re-run `/lazy-spec.product-config` and answer the expert-assignment question for that type when it appears, or declare the type `review: false` via `/lazy-spec.add-asset-type` if it genuinely should never be reviewed.

---

## `/lazy-spec.product-config` aborts at Step 12 before writing review classes

**Symptom**: After finishing the wizard — icon, experts, categories all answered — the skill aborts right before the review-class write, naming a dangling expert. No `products` or `review` settings are written.

**Likely cause**: Immediately before the write, the skill re-checks every expert name the generated classes are about to carry — every `main` writer, every `validation`/`terminal` writer — against the registered experts one more time. This catches a case the earlier per-role questions don't — for example an expert removed from the registry between answering the wizard and reaching this step, or a reconciled class carrying an expert name that is no longer registered.

**Fix**: Compose the missing persona via `lazycortex-experts`, then re-run `/lazy-spec.product-config`. Nothing was written on the abort, so there is no partial state to clean up.

---

## `/lazy-review.audit` reports FAIL after `/lazy-spec.product-config` writes review classes

**Symptom**: The final report includes an `audit: FAIL` line from `lazy-review.audit`, naming a schema violation in the generated classes.

**Likely cause**: The expert re-verification immediately before the write (above) already rules out dangling expert names, so a post-write audit FAIL points at something else — a section-writer schema violation in the generated `experts.validation` / `experts.terminal` structure.

**Fix**: Read the audit output for the offending class and field, then re-run `/lazy-spec.product-config` — Step 12 regenerates the review classes fresh each time, so fixing the upstream cause (e.g. correcting a role assignment) resolves it on the next pass.

---

## `/lazy-spec.audit` refuses to check a product

**Symptom**: The audit run stops immediately at Check 0, reporting the product key is not in `lazy.settings.json[products]`.

**Likely cause**: The product key you passed (or resolved from a path) has no registration — it was never created, or the key was mistyped.

**Fix**: Run `/lazy-spec.product-config` to register the product, then re-invoke `/lazy-spec.audit <product>`.

---

## `/lazy-spec.audit` reports a reserved product slug with no fix offered

**Symptom**: Check 0 fails, naming the product folder leaf as `vision`, `design`, `ui-design`, `tech`, `use-cases`, or `decisions`, and the report names no repair verb for it.

**Likely cause**: The product folder's basename collides with the product-level `vision.md` / `design.md` / `ui-design.md` / `tech.md` / `use-cases.md` / `decisions.md` files that live at the product root — a structural naming conflict no verb resolves.

**Fix**: Rename the product's folder (and its `spec_path` entry via `/lazy-spec.product-config` edit mode) to a leaf that isn't `vision`, `design`, `ui-design`, `tech`, `use-cases`, or `decisions`, then re-run `/lazy-spec.audit`.

---

## `/lazy-spec.audit` FAILs a product's or the catalog root's level note with `unknown-key: spec_doc_type`

**Symptom**: Agent D's `note-check` delegation reports a FAIL naming `unknown-key` on `spec_doc_type` for the product folder-note (`<spec_path>/<leaf>.md`) or the catalog root's own note — even though nothing was hand-edited.

**Likely cause**: An older `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> doc-type backfill` run derived a type from the level note's own `product` / `catalog` role and wrote `spec_doc_type: <role>` onto it — a key no level-note schema has ever declared room for. Only the asset status note and the operator-zone group notes were excluded from typing before this was fixed; a level note slipped through and picked up a stray key that `note-check` now rejects.

**Fix**: Two verbs clear this, and the finding names whichever fits. For the whole catalog in one pass, re-run `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> doc-type backfill` (or re-run `/lazy-spec.install`, whose Step 7c calls it) — reporting the count under a `cleaned` counter alongside `touched` / `skipped`. For a single note, run `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> note-drop-key <note_dir> spec_doc_type` directly — the same verb the coordinators reach for to clean up a stray key on their own wake, so a level note under an active coordinator usually self-heals before this audit pass ever reports it. Re-run `/lazy-spec.audit` afterward to confirm the FAIL clears.

---

## `/lazy-spec.audit` runs clean but never fixes anything

**Symptom**: The report lists warnings and errors, but re-checking the product afterward shows nothing changed.

**Likely cause**: `/lazy-spec.audit` is read-only in every invocation — it reports and stops, and it has no apply mode at all. Repair is a separate move you make.

**Fix**: Run the route the report names beside each finding — `/lazy-spec.set-stage` for a stage/tag drift, `/lazy-spec.flip-gate` for a gate, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> note-set-key` / `note-drop-key` for a frontmatter key, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> doc-type backfill` / `asset-type backfill` / `pins` for a missing key across the catalog, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> upstream-doctor --apply` for a `dangling-request-link` finding on a mirrored upstream unit, `/lazy-spec.sync-with-code` for a stale tech doc, `/lazy-spec.product-config` for a product or repo record. Findings with no named verb are hand edits. `/lazy-core.doctor` runs this audit as one of its delegated checks and drives a fix/waive loop over the merged findings if you want one place to work through them.

---

## A layout or body-shape finding never clears

**Symptom**: You resolved several findings, but a layout or body-shape one (a stray `docs/` subfolder, an old-shape note body, content outside the vault root) is still reported on the next run.

**Likely cause**: Nothing in the plugin moves or rewrites existing spec content — no skill, no CLI verb. These findings exist to tell you what to move; they are never repaired for you.

**Fix**: Resolve the finding by hand — move the files, rewrite the section — following the instruction the report gives for that specific finding, then re-run `/lazy-spec.audit` to confirm it clears.

---

## `/lazy-spec.audit` keeps warning that a container folder-note has no `# Coordinator rules` section

**Symptom**: Every audit run reports a WARN naming a container folder-note (e.g. `bugs/bugs.md`) as missing its `# Coordinator rules` section, alongside the same warning for the product folder-note.

**Likely cause**: The rule-chain the coordinator reads before deciding anything on any asset (playbook → vault doc → product note → container notes top-down → asset note) now spans container-level notes too, not just the product root — a container folder-note that has never needed group-wide constraints simply has nothing written yet, which is expected rather than broken.

**Fix**: Nothing is required — this is a WARN, not a FAIL, and an empty section is not owed. If you do want group-scoped constraints for that container, add the empty `# Coordinator rules` section yourself, carrying the `#protected/spec/coordinator-rules` tag the templates use, then author the constraints under it.

---

## `/lazy-spec.audit` reports `vault-spec-missing`

**Symptom**: A doctor run's Check 11 reports `[WARN] vault-spec-missing` — neither the content-root `vision.md` nor a pre-vision `design.md` exists.

**Likely cause**: The catalog was registered before the mandatory-vault-spec contract landed, or `/lazy-spec.install` was never re-run afterward — the content-root `vision.md` that every product split is a consequence of was never seeded. If a content-root `design.md` exists but no `vision.md` sits beside it, doctor reports `[INFO] pre-vision vault` instead — a legal starting state, migrated by hand whenever you're ready, not a WARN.

**Fix**: Re-run `/lazy-spec.install` — its Step 6.9 seeds a draft `vision.md` at the content-root when neither file exists — then fill it in. This is a WARN, not a FAIL: the rest of the catalog keeps working while it's absent.

---

## `/lazy-spec.audit` reports an unfolded decision-candidate in an approved document

**Symptom**: The report includes a FAIL naming a `[!decision-candidate]` callout — ticked or not — still present in a document that is `spec_stage: approved`, or that carries `review_result: approved` / `approved-with-concerns`.

**Likely cause**: The writer round never folded the operator's verdict on the candidate before the document shipped as approved, so the approval carried a live questionnaire forward into the approved text. This check is scoped to living docs — a `[!decision-candidate]` in a tool's report document (`code-report` / `test-report`, or any other declared report type) is a standing to-do, never a finding.

**Fix**: Reopen the document's review at the writer round (`/lazy-review.start`) so the callout is folded into the approved text, then re-run `/lazy-spec.audit` to confirm it clears. Never delete the callout by hand — that hides the debt without resolving it.

---

## `/lazy-spec.audit` FAILs a start document's type

**Symptom**: The report includes a FAIL under "Start document type" naming an asset's `design.md`, most often on a content asset (`spec_asset_type: content`) created before the `content-design` document type existed.

**Likely cause**: The document an asset's type names as its start document must carry that type. A content asset's `design.md` still carries `spec_doc_type: design` from before content assets got their own `content-design` type, so the review loop treats it as an ordinary feature design: the feature-design class reviews it, with the architect as its validator, instead of the content-design class, whose validator is the data writer.

**Fix**: The audit only reports; it names the document and the repair is a hand edit. Set that one frontmatter value, `spec_doc_type`, to `content-design`, then re-run `/lazy-spec.audit` to confirm the FAIL clears.

---

## `/lazy-spec.audit` FAILs a cancelled document

**Symptom**: The report includes a FAIL on an asset's start document (for example `design.md` of a feature, `bug.md` of a bug) or a product's `architecture.md` carrying `spec_stage: cancelled`.

**Likely cause**: An asset is abandoned as a whole, never through the document that defines it. `/lazy-spec.set-stage` refuses `cancelled` on those documents, so the value arrived by a hand edit. A `tech` document, an asset's `test-plan.md` and a release's plan documents (`code-plan`, `test-plan`) may legitimately be cancelled.

**Fix**: Move the document out of `cancelled` with `/lazy-spec.set-stage`. If the whole asset is abandoned, cancel it with `/lazy-spec.flip-gate <asset> spec_cancelled`. Then re-run `/lazy-spec.audit`.

---

## A content asset's design is never picked up by the `content-design` review class

**Symptom**: A content asset's `design.md` is reviewed by the wrong experts, or a fresh install or product wizard run leaves no review class for content designs.

**Likely cause**: Either the document still carries the old `design` type (see the previous entry), or the `content-design` class was never written to `review.classes` because `/lazy-spec.install` and `/lazy-spec.product-config` have not been re-run since the type shipped. The class needs a designer and an editor, and its validator is the data writer, so a missing persona also leaves it unassigned.

**Fix**: Re-run `/lazy-spec.install`, which appends the `content-design` class when no existing entry carries it, then re-run `/lazy-spec.product-config` and answer the expert-assignment questions for the designer, data-writer, and editor roles. Fix any stale `spec_doc_type` the audit reports.

---

## `/lazy-spec.create-asset` refuses naming an unknown product

**Symptom**: The skill prints a refusal naming the product key and suggesting `/lazy-spec.product-config`.

**Likely cause**: The product compound-key you passed has no record in `lazy.settings.json[products]`. The product was never registered, or the key was mistyped.

**Fix**: Run `/lazy-spec.product-config` to register the product, then re-invoke `/lazy-spec.create-asset <product> <type> <slug>`. Verify the compound-key matches exactly what the wizard wrote into config. This applies equally to `/lazy-spec.create-feature`, `/lazy-spec.create-change`, and `/lazy-spec.create-bug` — all three are thin wrappers over `/lazy-spec.create-asset` and refuse the same way.

---

## `/lazy-spec.create-asset` refuses naming an unknown asset type

**Symptom**: The skill rejects the asset type, saying it is neither one of the plugin's shipped declarations nor a key in the product's `asset_types`.

**Likely cause**: You passed a type nothing declares. The shipped set is `feature`, `change`, `bug`, `content`, `research`; anything else must be declared on the product first.

**Fix**: Run `/lazy-spec.add-asset-type <product> <type-name>` to declare the type, then re-invoke `/lazy-spec.create-asset`.

---

## `/lazy-spec.create-asset` ends `refused:logical` with `target folder already exists`

**Symptom**: The skill ends `refused:logical` saying the target folder already exists, and scaffolds nothing.

**Likely cause**: An asset with that slug is already in the product.

**Fix**: Pick another slug, or work the existing asset instead of creating a new one.

---

## `/lazy-spec.create-asset` ends `refused:logical` with `invalid --target token`

**Symptom**: The skill ends `refused:logical` saying the `--target` token is invalid.

**Likely cause**: The `--target` value is empty, has an empty segment, or steps through `.` or `..`.

**Fix**: Pass the target as `<folder>/<slug>` counted from the product root, then re-invoke `/lazy-spec.create-asset`.

---

## `/lazy-spec.create-asset` refuses saying the type has no playbook

**Symptom**: The skill refuses before scaffolding anything, saying the asset type declares neither a `playbook` nor an `alias_of`.

**Likely cause**: The type's declaration under `products[<key>].asset_types` is incomplete — the coordinator would have no law to work an asset of this type under, so the skill refuses to create one rather than leave it stranded.

**Fix**: Complete the declaration via `/lazy-spec.add-asset-type <product> <existing-type-name>` — the wizard resumes at the playbook question — then re-invoke `/lazy-spec.create-asset`.

---

## `/lazy-spec.create-asset` refuses saying the type declares no start document

**Symptom**: The skill refuses, saying the asset type carries no `start_doc` token and there is no default layout to fall back on.

**Likely cause**: The type's declaration under `products[<key>].asset_types` is missing `start_doc` — usually an interrupted `/lazy-spec.add-asset-type` run, or a hand-edited entry.

**Fix**: Re-run `/lazy-spec.add-asset-type <product> <existing-type-name>` and answer the start-document question with a `<file>.md:<doc-type>` pair, then re-invoke `/lazy-spec.create-asset`.

---

## `/lazy-spec.add-asset-type` refuses naming an unknown product

**Symptom**: The skill refuses immediately, naming the product key you passed and pointing at `/lazy-spec.product-config`.

**Likely cause**: The product compound-key has no record in `lazy.settings.json[products]` — the product was never registered, or the key was mistyped.

**Fix**: Run `/lazy-spec.product-config` to register the product, then re-invoke `/lazy-spec.add-asset-type <product> <type-name>`.

---

## `/lazy-spec.add-asset-type` refuses because the type already exists

**Symptom**: The skill rejects the new type name, saying it is already a key in the product's own `asset_types`.

**Likely cause**: A type with that exact name was declared before — re-running the skill with the same name does not overwrite it. Reusing one of the *shipped* names is not a refusal: that is a per-field override of the shipped type for this product, and the wizard says so plainly before continuing.

**Fix**: Pick a different type name, or edit the existing declaration under `products[<key>].asset_types` directly if you only meant to change its icon, folder, start document, or playbook.

---

## `/lazy-spec.add-asset-type` aborts saying an icon is required

**Symptom**: The wizard aborts after you decline every icon option, saying a type cannot be declared without one.

**Likely cause**: You declined both the iconize suggestion and the emoji fallback without supplying either.

**Fix**: Re-run `/lazy-spec.add-asset-type` and answer the icon question with an iconize icon name or an emoji — nothing is written until an icon is set.

---

## `/lazy-spec.add-asset-type` keeps re-asking for the start document

**Symptom**: The wizard rejects the typed value for the start document and asks the question again instead of continuing.

**Likely cause**: The typed token isn't exactly `<file>.md:<doc-type>` — either it's missing the colon, the left side isn't a `.md` filename, or the doc type on the right isn't declared anywhere the skill can see (neither the plugin's shipped `lazy-spec.doc-types.json` nor the product's own `doc_types`).

**Fix**: Supply a token whose doc type is already declared, or declare the missing doc type on the product first, then answer the question with the corrected `<file>.md:<doc-type>` pair.

---

## The coordinator raises a question saying a newly declared type has no playbook

**Symptom**: After `/lazy-spec.add-asset-type` finishes and an asset of the new type is created, `spec.coordinator` raises a `[!question]` on it saying the type carries no playbook.

**Likely cause**: The declaration got written with neither `playbook` nor `alias_of` set — usually because a prior `/lazy-spec.add-asset-type` run was interrupted between writing the type block and choosing its playbook.

**Fix**: Re-invoke `/lazy-spec.add-asset-type <product> <existing-type-name>` — the wizard resumes at the playbook question and appends the missing field without touching anything already written. The coordinator picks up the fix on the asset's next wake.

---

## `/lazy-spec.create-from-code` refuses an unregistered product or no-ops on a design-only product

**Symptom**: The skill either refuses with "product not registered" or prints "product has no code binding" and stops without writing any files.

**Likely cause**: For the "not registered" case, the product key is not in `products`. For the "design-only" case, the product record exists but has no `source` block naming the paths of its code.

**Fix**: For an unregistered product, run `/lazy-spec.product-config` first. For a design-only product, re-run `/lazy-spec.product-config` in edit mode to add its source paths — the wizard adds the `source.paths` block without clobbering the product's existing `asset_types` / `tool_types` declarations or any other field it did not ask about.

---

## `/lazy-spec.create-request` aborts with nothing to capture

**Symptom**: The skill aborts saying it has no idea to capture.

**Likely cause**: You ran the skill without giving it a raw idea, and didn't supply one when the wizard asked.

**Fix**: Re-invoke `/lazy-spec.create-request` and give it a sentence or two describing the idea before the wizard's clarifying questions run.

---

## `/lazy-spec.create-request` finds no `requests/` folder

**Symptom**: The vault-wide `requests/` inbox does not exist when you capture an idea.

**Likely cause**: Nothing has created the inbox in this vault yet. Requests live in one vault-wide inbox, not in per-product folders.

**Fix**: Create the `requests/` folder at the vault root and capture the idea again; the inbox is the only location the skill uses.

---

## `/lazy-spec.request-classify` stops or returns `unknown`

**Symptom**: Classification aborts naming a file path, or answers `unknown`.

**Likely cause**: Three cases. A file path was given that does not exist, and the skill deliberately does not fall back to an empty body. The request body has no readable content after the frontmatter, which yields `unknown` so the caller asks for content. Or the project settings are unreadable or missing, in which case the skill falls back to the shipped asset types (`feature`, `change`, `bug`, `content`, `research`) plus the closed meta classes and still answers.

**Fix**: Correct the path, add real content to the request body, or restore the project settings (re-run `/lazy-spec.install`) so project-declared asset types take part in classification.

---

## `/lazy-spec.record-decision` refuses to record, supersede, obsolete, or promote a decision

**Symptom**: The `decide` primitive refuses with one of: `no such record: D-NNN`, `no such doc`, or `spec_role '<x>' is not a living doc`.

**Likely cause**: The first two are a mismatched target — the id you gave `supersede` or `obsolete` doesn't exist in that file's `## D-NNN` headings, or the path you gave `promote` doesn't exist at all. The third means you pointed `promote` at a document whose role isn't `design` / `bug` / `tech` / `architecture` — a plan never promotes (a plan only decomposes decisions already accepted elsewhere) and a report never promotes (it carries decision-candidates, not decisions).

**Fix**: Re-check the id against the file's own headings, or the path itself, for the first two. For the third, put the decision statement in the correct living doc and promote from there — never force a promote against a plan or a report.

---

## `/lazy-spec.record-decision promote` refuses: the owning asset is cancelled, halted, or released

**Symptom**: `promote` refuses unconditionally, naming `spec_cancelled`, `spec_halted`, or `spec_released` as the reason.

**Likely cause**: `promote` checks all three flags before writing anything into the decisions registry — a decision doesn't get promoted out of an asset that is cancelled, currently halted, or already shipped.

**Fix**: Clear the flag first (`/lazy-spec.flip-gate <asset> spec_cancelled --off`, or resolve whatever halted the asset), then re-run `promote`. Nothing forces the transfer — the decision block stays in place, unpromoted, until you do.

---

## `/lazy-spec.record-decision` reports `duplicate: D-NNN`

**Symptom**: The command reports `duplicate: D-NNN` and nothing new appears in the decisions file.

**Likely cause**: This is not a failure — an existing record already carries the same normalized thesis and body as the one you tried to add.

**Fix**: Nothing to fix. If you meant a genuinely different decision, reword it so its thesis is distinguishable from `D-NNN`, then re-run.

---

## I flipped a gate out of order — `/lazy-spec.flip-gate` didn't stop me

**Symptom**: `/lazy-spec.flip-gate <asset> <gate>` succeeded even though the gate's usual precondition (the doc it depends on isn't approved yet, or an earlier gate is still `false`) doesn't actually hold.

**Likely cause**: The primitive no longer checks a gate's readiness before flipping — it performs the mutation unconditionally, refusing only an unknown gate name, a gate the note's own ladder does not carry, opening a middle gate on a design-only note, and any flip on a cancelled asset. Deciding whether a gate is actually ready is `spec.coordinator`'s job when IT calls the primitive (reasoning from `lazy-spec.coordination-playbook.md`); when you call `/lazy-spec.flip-gate` yourself, the interactive confirmation is your own chance to double-check, not a safety net the primitive re-verifies.

**Fix**: Check the readiness table in `lazy-spec.lifecycle-protocol.md` Part 2 for what the gate SHOULD require, then flip it back with `--off` (also unconditional apart from the gate-name, note-ladder and cancelled-asset refusals) if it was flipped prematurely. `spec.coordinator` will re-derive the correct state on its next wake and, for a derived gate (`spec_design_done`, or a release's `spec_plan_done`), may flip it forward again on its own once the actual precondition holds.

---

## `/lazy-spec.flip-gate` refuses with "asset cancelled"

**Symptom**: The gate flip is refused with a message that the asset is cancelled.

**Likely cause**: `spec_cancelled: true` on the asset's status folder-note freezes all gate progression. No flip — on or off — is allowed while an asset is cancelled.

**Fix**: Uncancel the asset by running `/lazy-spec.flip-gate <asset> spec_cancelled --off` if you want to resume it (its cancelled documents return to `draft`), or leave it cancelled if the work is truly abandoned. After uncancelling, gate flips proceed normally.

---

## `/lazy-spec.flip-gate` refuses: gate is not on a design-only ladder, or is unknown

**Symptom**: The flip is refused with "gate `<gate>` is not on a design-only ladder", "unknown gate", or "is not on the `<role>` ladder".

**Likely cause**: A middle gate (`spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_built`) was asked on a note other than a release's. A design-only asset has none of them, because its code lands through a release whose own note carries those gates. Otherwise the gate name is a typo, or belongs to the other ladder (an asset gate on a level note, or a level gate on an asset note).

**Fix**: Pass a gate the note's own ladder carries; for the middle gates, flip them on the release's note.

---

## `/lazy-spec.flip-gate` cannot resolve the asset

**Symptom**: The skill prints a refusal saying the input matches zero or more than one asset.

**Likely cause**: The path or slug you passed is ambiguous — it could map to multiple products or categories — or it does not match any asset folder.

**Fix**: Pass the unambiguous asset directory path (e.g. `Server/products/api/csv-export`).

---

## `/lazy-spec.drive` refuses to start: a daemon is live

**Symptom**: The skill refuses immediately with `refused-daemon-live`, naming a signal (a running process, a launchd job, or a recent runtime log) that means the runtime daemon could still act on this checkout.

**Likely cause**: `/lazy-spec.drive` drives one asset through its ladder by hand, in the same session, with no daemon in the loop — running it while the daemon is also live risks a job being dispatched twice, once by the daemon and once by the drive session, and the daemon's clean-tree invariant would conflict with the drive session's own uncommitted state.

**Fix**: Stop the daemon, or point it at another checkout with `/lazy-core.daemon-setup` (the skill that owns `daemon.run_here`), before driving by hand. Per the plugin's own contract, going back to daemon mode after a drive session requires the session to close `closed-clean` first — resolve any dirty paths `/lazy-spec.drive` reports at the end of its run before restarting the daemon.

---

## `/lazy-spec.drive`'s dialog loop keeps hitting its 20-iteration ceiling

**Symptom**: The drive loop stops itself after 20 iterations without the ladder settling, and the skill reports this rather than continuing.

**Likely cause**: Either a genuine ladder bug — worth reporting rather than working around — or the asset is caught in a legitimate multi-round cascade that outgrew a single session's patience. The ceiling is a deliberate fixed cap, not a setting to raise.

**Fix**: Re-invoke `/lazy-spec.drive` on the same asset — its resume phase picks up exactly where the loop left off, so a multi-round cascade completes over a couple of re-invocations. If the same asset keeps hitting the ceiling with no progress between runs, that is the ladder bug to report.

---

## `/lazy-spec.drive` reports `no-such-checkbox`, `no-such-question` or `no-such-option`

**Symptom**: A menu pick fails with a gesture result carrying `reason: no-such-checkbox`, `no-such-question` or `no-such-option`.

**Likely cause**: The label or index you picked names nothing on the note any more. The coordinator rewrote the gates section or the question callout after the menu was built.

**Fix**: Rebuild the menu and pick again.

---

## `/lazy-spec.drive` reports `no-such-note`, `no-gates-section` or `no-commands-section`

**Symptom**: A menu pick fails with a gesture result carrying `reason: no-such-note`, `no-gates-section` or `no-commands-section`.

**Likely cause**: The note path is wrong, or the note lacks the section the gesture writes into.

**Fix**: Check the path, or let the coordinator's next wake restore the section, then run the pick again.

---

## `/lazy-spec.drive` aborts: can't find the lazycortex-core CLI

**Symptom**: The skill aborts immediately, saying the `lazycortex-core` CLI cannot be resolved.

**Likely cause**: `lazycortex-core` — the plugin `/lazy-spec.drive` calls to resolve settings and dispatch jobs — could not be found: the plugin registry yields no match. Either the session's plugin-directory export step did not run, or there are no development sources and `~/.claude/plugins/installed_plugins.json` records no `lazycortex-core@lazycortex` entry.

**Fix**: Re-run the skill's first phase so the export happens, or install or update `lazycortex-core` so the registry records it, then re-invoke `/lazy-spec.drive` on the same asset.

---

## `/lazy-spec.drive` aborts partway through: agent not found

**Symptom**: The drive session gets partway through the ladder, then aborts naming an agent it can't locate for the job it's about to dispatch. The message reads either `agent not found in dev plugin: <ref>` pointing at a plugin source tree, or `agents not found:` pointing at a plugin cache directory.

**Likely cause**: For the first form, the exported dev source directory for that plugin does not carry the agent this job needs. For the second, the installed version of the plugin that should ship that agent predates it — usually because that plugin was updated on another machine or checkout but not the one you're running `/lazy-spec.drive` from.

**Fix**: For the dev-source form, add the agent to that source tree, or drop the stale dev directory from the export. For the cache form, update the plugin that owns the missing agent to its latest published version. Then re-invoke `/lazy-spec.drive` on the same asset — its resume phase picks up exactly where the abort left off.

---

## `/lazy-spec.set-stage` refuses: document carries no `spec_doc_type`

**Symptom**: The skill refuses, saying the target document carries no `spec_doc_type`.

**Likely cause**: Per-file stage now resolves purely from the document's declared type, never from its filename or path — an untyped document (usually predating the type-declaration model, or a hand-created file) has no type key to resolve.

**Fix**: Run `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> doc-type backfill` to type every document in the catalog that's missing the key, or add `spec_doc_type` to that one document by hand, then re-invoke `/lazy-spec.set-stage`.

---

## `/lazy-spec.set-stage` refuses: type is not declared in this product's scope

**Symptom**: The skill refuses, saying the document's type is not declared in this product's scope — neither the shipped set nor a project-level declaration.

**Likely cause**: The `spec_doc_type` value is a typo, or names a type nobody has declared for this product via `/lazy-spec.add-asset-type`.

**Fix**: Correct the typo, or declare the type under `products[<key>].doc_types` via `/lazy-spec.add-asset-type`, then re-invoke `/lazy-spec.set-stage`.

---

## `/lazy-spec.set-stage` refuses: type carries no `spec_stage`

**Symptom**: The skill refuses, saying the document's type carries no `spec_stage`.

**Likely cause**: The type's declaration exists but is marked `stages: false` — the shipped `code-report`, `test-report`, and `decisions` types (and any project type declaring the same) have no independently-settable stage; their lifecycle is tracked another way.

**Fix**: Nothing to set on that document — its lifecycle isn't per-file-stage-driven. If you expected it to be, check the type's declaration under `products[<key>].doc_types`.

---

## `/lazy-spec.set-stage` refuses: stage isn't in the closed set

**Symptom**: The skill refuses, saying the stage value isn't in the closed set.

**Likely cause**: You passed a stage outside `empty | draft | approved | rejected | cancelled | deferred` — often a leftover from an older model (`review`, `done`, `wtr`).

**Fix**: Pass `draft` and set `review_active: true` for a doc that's currently in review, `approved` once it's accepted, or whichever closed-set value matches your intent.

---

## `/lazy-spec.set-stage` refuses: document carries a decision-candidate

**Symptom**: Requesting `approved` refuses, naming a `[!decision-candidate]` callout at a specific line — ticked or not.

**Likely cause**: Before landing `approved`, the skill now scans the document's body outside code fences for any `[!decision-candidate]` callout. Approving with one still in place would ship an unfolded questionnaire inside the approved text — the same condition `/lazy-spec.audit` flags afterward as an unfolded-candidate FAIL.

**Fix**: Fold the callout through the document's review first — reopen it at the writer round via `/lazy-review.start` — then re-invoke `/lazy-spec.set-stage <doc> approved`. Never delete the callout by hand to clear the refusal.

---

## `/lazy-spec.set-stage` refuses: document is an attachment of `<owner>`

**Symptom**: The skill refuses, saying the target document is an attachment of another document and its stage mirrors the owner's.

**Likely cause**: The file carries `spec_owner_doc`, marking it a markdown attachment — its `spec_stage` is a mirror the owner's own stage cascade writes, never set directly (except while the attachment is itself under active review, when nobody writes the file).

**Fix**: Set the stage on the owner document instead — `/lazy-spec.set-stage <owner-doc> <stage>` cascades the same stage to every sibling attachment (except one currently in review) in the same commit.

---

## `/lazy-spec.set-stage` refuses: document is deferred

**Symptom**: The skill refuses, saying the target document is deferred and cannot take the stage you asked for.

**Likely cause**: The document's `spec_stage` currently reads `deferred` — parked out of sight of the coordinator — and the stage you passed is neither `draft` nor `cancelled`.

**Fix**: Run `/lazy-spec.set-stage <doc> draft` first — `draft` and `cancelled` are the only ways out of `deferred`, and `cancelled` abandons the document instead of bringing it back. Once `draft` lands, the coordinator starts reacting to the document again, and you can move it on to whatever stage you actually intended.

---

## `/lazy-spec.set-stage` refuses: `--restamp` is valid only with `approved`

**Symptom**: The skill refuses, saying `--restamp` is valid only with `approved`.

**Likely cause**: The `--restamp` flag was passed together with a stage other than `approved`.

**Fix**: Drop the flag, or pass `approved`.

---

## `/lazy-spec.set-stage` refuses with a decision-promotion reason

**Symptom**: Requesting `approved` refuses with a reason from the decision-promotion step, and the document keeps its previous stage.

**Likely cause**: Approving a document promotes its decisions, and the owning asset is cancelled, halted, or released, so the promotion is refused. Nothing was written.

**Fix**: Clear the asset's flag first (see the `/lazy-spec.record-decision promote` entry above), then request the stage again; until then commit nothing for that document.

---

## `/lazy-spec.set-stage` refuses: cancelled isn't allowed on this file

**Symptom**: The skill refuses to set `cancelled` on the target file.

**Likely cause**: `design.md` is mandatory for every asset — both the asset-level document (`design` type) and the product-root / content-root pair (`system-design` type) — alongside `bug.md` and the product's `architecture.md`; none of the four can be cancelled individually. Cancellation belongs on `tech.md` (`system-tech` type), `test-plan.md` (no dedicated test cases or test pass needed), or a release's `code-plan.md` (a build that needs no separate plan).

**Fix**: Set `cancelled` on `tech.md`, `test-plan.md`, or a release's `code-plan.md` instead, whichever fits. If the whole asset is abandoned, cancel it at the asset level via `/lazy-spec.flip-gate` instead of a single file.

---

## `/lazy-spec.sync-with-code` refuses or no-ops for a product

**Symptom**: The skill either refuses naming an unregistered product, or reports `design-only` for a product and syncs nothing for it.

**Likely cause**: The product key is missing from `products`, or the product has no `source` block naming the paths of its code. A whole-tree run lists only registered keys and quietly skips design-only products with the `design-only` outcome; a run naming a single design-only product stops with that message.

**Fix**: Register the product via `/lazy-spec.product-config`, or add its source paths in edit mode. Then re-run `/lazy-spec.sync-with-code`.

---

## `/lazy-spec.sync-with-code` never proposes a `spec_develop_done` flip despite landed code

**Symptom**: Commits objectively implementing an open release's included assets are on the default branch, but the sync wizard never surfaces a `spec_develop_done` proposal for the release.

**Likely cause**: `spec_plan_done` doesn't read `true` yet. The skill checks this itself before proposing (`/lazy-spec.flip-gate` no longer double-checks a gate's readiness on its own — see "I flipped a gate out of order" above), so an unmet plan gate silently withholds the proposal rather than surfacing one that would land wrong. A design-only asset never gets this proposal: it has no `spec_develop_done` of its own, and the sync reports its landed code as implemented outside a release instead.

**Fix**: Settle the release's plan — the build's architecture revision must be settled and the release's `code-plan.md`, if one was ever authored, must reach `spec_stage: approved` (or absence itself satisfies the gate) — then flip the release's `spec_plan_done` yourself via `/lazy-spec.flip-gate`, or let `spec.coordinator` derive and flip it on its next wake. Re-run `/lazy-spec.sync-with-code` afterward.

---

## `/lazy-spec.sync-with-code` reports `no-head`

**Symptom**: The sync state check reports `reason: no-head` and the run stops.

**Likely cause**: The repository's HEAD is unreadable: there is no commit yet, or the directory is not a git checkout.

**Fix**: Make the first commit (or run from a git checkout), then re-invoke `/lazy-spec.sync-with-code`.

---

## A document `/lazy-spec.sync-with-code` created is ignored by the coordinator

**Symptom**: After a sync run, a new asset `design.md` or `test-plan.md`, or a product's `architecture.md`, exists, but no coordinator wake or review reacts to it, even though the wiki's topics index already lists it.

**Likely cause**: Every authored document a sync run creates is born parked at `spec_stage: deferred`, so the coordinator leaves it alone until you decide it is ready. The wiki does not wait: it curates deferred documents too, and the topics index shows `[spec_stage: deferred]` beside the entry so a reader can tell it from approved text. Editing an existing document never changes its stage.

**Fix**: When you want the document worked, run `/lazy-spec.set-stage <doc> draft`; the coordinator starts reacting to it from that moment, and the wiki's badge changes to `[spec_stage: draft]`. To abandon it instead, run `/lazy-spec.set-stage <doc> cancelled` — `draft` and `cancelled` are the only two exits from `deferred`.

---

## An approved asset keeps showing the same drift after `/lazy-spec.sync-with-code`

**Symptom**: Run after run, the report lists an asset under "approved assets left untouched", and its documents still disagree with the code.

**Likely cause**: Before touching an asset that holds an approved document, the skill asks once for the whole asset whether to bring it in line. You answered `leave`, so the asset was skipped for that run. A later run finds the same drift and asks again.

**Fix**: Re-run `/lazy-spec.sync-with-code <product> --full` (or pass the asset itself) and answer `update`. Every finding of that asset is applied and its approved documents keep their stage.

---

## An asset is reported "ahead of the code" after `/lazy-spec.sync-with-code`

**Symptom**: Run after run, the report lists an asset as ahead of the code, and its design still describes behaviour the code does not have yet. Nothing in it was rewritten.

**Likely cause**: The asset's documents state a target design from review, and the code has not reached it. The skill asks once for the whole asset, whatever its stages read, whether that design still stands, because the code may simply be behind a design someone reviewed. You answered `keep`, so the asset was left untouched this run. A later run that finds the same gap asks again.

**Fix**: If the code is meant to catch up, leave it as it is. If the design was abandoned, re-run `/lazy-spec.sync-with-code` on the product or the asset and answer `update`: the asset is brought in line with the code and its design records are marked obsolete.

---

## `/lazy-spec.sync-with-code` finished but nothing is committed

**Symptom**: The run reports its edits, yet `git status` shows modified, created, or deleted spec files, and the history has no new commit.

**Likely cause**: This is by design. The skill edits freely but commits only after you have read the whole diff and said yes. Declining the commit, or ending the session before answering, leaves the edits in the working tree.

**Fix**: Read the diff, then commit the files yourself if you accept it. Nothing is lost: the edits stay in the working tree until you decide.

---

## `/lazy-spec.coverage` refuses or has nothing to gap-scan

**Symptom**: The skill either refuses naming an unregistered product, or reports "no code binding — nothing to gap-scan" and stops.

**Likely cause**: The product key isn't in `lazy.settings.json[products]`, or the product record has no `source` block — a design-only product has no code to compare the spec tree against.

**Fix**: Register the product via `/lazy-spec.product-config` for the first case. For the second, add its source paths in edit mode if the product does have code; a genuinely design-only product simply has no gap-scan surface, and that is expected rather than an error.

---

## `/lazy-spec.coverage` reports `structure-absent` or `domains-not-configured`

**Symptom**: The gap-scan runs but reports that the structure map or the domain tree isn't built or configured for this repo.

**Likely cause**: `docs/structure.md` hasn't been generated yet, or `lazy-wiki.domains` has no configuration for this project.

**Fix**: Run `lazy-wiki.structure rebuild` and, for richer signal, `/lazy-wiki.configure domains` followed by `lazy-wiki.domain-sync`. Neither is strictly required — the coverage scan still runs against the raw source tree without them, just with less precision.

---

## `/lazy-spec.upstream-run` returns every count as `0`

**Symptom**: The manual pass runs but reports zero mirrored, zero detected, zero of everything.

**Likely cause**: No `<repo-key>` entry exists yet under `spec.upstream` in `lazy.settings.json`, or a configured mount's `units` glob matches nothing in the source's current tree.

**Fix**: Add a source entry for the upstream repo (see the plugin's upstream configuration reference), or widen the mount's `units` glob so it actually matches files in the source tree.

---

## `/lazy-spec.upstream-run` reports an entry in `errors`

**Symptom**: The pass completes, but one source shows up under `errors` in the result.

**Likely cause**: That source's `url` or `branch` was unreachable, or an existing local clone's `origin` no longer matches the configured `url` — a clone is never re-pointed automatically once it drifts from config.

**Fix**: Fix connectivity to the unreachable source, or reconcile the clone's remote by hand (`git remote set-url origin <url>` inside the clone) to match what's configured. Every other configured source still ran normally in the same pass.

---

## `/lazy-spec.upstream-run` shows a unit stuck at `new` with no checkbox

**Symptom**: A mirrored upstream unit stays marked `new` indefinitely and never grows a launch checkbox to act on.

**Likely cause**: The unit's mirrored root note (`source/<unit>.md`) is a status note without `spec_released: true` — a deliberate gate that withholds the checkbox until the upstream asset is published.

**Fix**: Check the unit's own folder-note `# Actions` section for the actual state. Nothing to do until the upstream asset is published; this is expected gating, not a stuck run.

---

## `/lazy-spec.resolve-dependency` refuses with a malformed dependency entry

**Symptom**: The primitive refuses, naming a dependency entry that lacks a required key.

**Likely cause**: The entry in the product's `dependencies` array doesn't match either of the two documented shapes — it has neither a `product:` nor an `external:` key.

**Fix**: Fix the entry via `/lazy-spec.product-config` (edit mode) so it matches one of the two shapes, then re-invoke `/lazy-spec.resolve-dependency`.

---

## `/lazy-spec.resolve-dependency` refuses: product not found

**Symptom**: The primitive refuses, naming a product key from a dependency entry that doesn't resolve.

**Likely cause**: A `product:` entry points at a key that isn't in `products` — unregistered, or mistyped.

**Fix**: Register the missing product via `/lazy-spec.product-config`, or correct the key spelling in the dependency entry.

---

## `/lazy-spec.lookup` refuses: anchor not found

**Symptom**: A lookup call refuses, naming the anchor you passed and listing the registered product keys instead of returning matches.

**Likely cause**: The anchor you gave isn't a key in `lazy.settings.json[products]`, or a vault-relative path you gave doesn't resolve to a folder or file under the vault root — a typo, or a product that hasn't been registered yet.

**Fix**: Correct the product key or path, or register the product first via `/lazy-spec.product-config`, then re-invoke `/lazy-spec.lookup` with the corrected anchor. A query with no anchor at all always succeeds — it just searches the whole vault instead of a scoped subtree.

---

## `/lazy-spec.lookup` refuses: a product-relative path without a product

**Symptom**: A lookup call refuses, saying a product-relative path anchor was given with no product to resolve it against.

**Likely cause**: A product-relative path (e.g. a bare `csv-export`, or `bugs/crash`) is ambiguous on its own — the same path can exist under more than one product.

**Fix**: Pass the product key alongside the anchor, or give the full vault-relative path instead (e.g. `Server/products/api/csv-export`).

---

## `/lazy-spec.request-find-candidates` refuses when the request's class is unknown

**Symptom**: The candidate search refuses, saying the request hasn't been classified yet.

**Likely cause**: Classification runs before candidate search in the request-routing flow — an `unknown` class means that step hasn't settled.

**Fix**: Let the routing pass classify the request first, then let candidate search run again on the classified request.

---

## `/lazy-spec.request-find-candidates` refuses naming an unregistered product

**Symptom**: The candidate search refuses, naming a product key that isn't registered, alongside the list of products that are.

**Likely cause**: The request names (or was tagged with) a product compound-key that has no record in `lazy.settings.json[products]` — a typo, or a product nobody has registered yet.

**Fix**: Register the product via `/lazy-spec.product-config` if it genuinely doesn't exist yet, or correct the product reference on the request, then let the routing pass search candidates again.

---

## A request's apply pass fails: attach target doesn't resolve to a folder-note

**Symptom**: Once you confirm the routing, the request stays at its pre-apply state and the apply worker's error names an attach target that "does not resolve to a folder-note".

**Likely cause**: The routing decision's `attach <path>` line names a repo-relative path that either doesn't exist or is neither a `<slug>/<slug>.md` folder-note nor a system document of a level — `vision.md`, `design.md` or `tech.md` at the content root or a product root, or `use-cases.md` / `ui-design.md` at a product root, which apply stamps directly — a stale or hand-typed path in the `routing-decision` block.

**Fix**: Edit the `routing-decision` block in the request's `# Routing` section to the correct folder-note or system-document path, then re-confirm the routing.

---

## The routing offers both attach and change for the same asset

**Symptom**: The routing `[!question]` on a request's `# Routing` section lists two options for one existing asset — attach the request to it, or spawn a change that names it via `targets=` — and an apply run that once refused an attach to an implemented feature no longer does.

**Likely cause**: This is the intended behaviour. Whether a request revises an existing asset's own documents or travels through a separate change asset is your decision, not the routing coordinator's, so the question offers both for every existing asset the request would modify; the coordinator may only say which one it recommends. Implementation lives in the product's release, never in the asset, so apply no longer refuses an attach because of implementation signals.

**Fix**: Tick the option you want for each asset — `attach` to have the asset's own documents revised (the documents its `drop=` names are deleted, the design is reviewed again, and no gate is flipped), or the change-spawn to leave them as they are until the change's design cascades into them. See [requests](requests.md).

---

## A request's apply pass refuses: attach target is halted

**Symptom**: The apply worker refuses, saying the attach target is halted and automation is refused until an operator resolves it.

**Likely cause**: The target asset carries `spec_halted: true` from an earlier, unrelated failure (a dead job, an import drift, …) — every automated action on a halted asset is refused until a human clears it.

**Fix**: Resolve whatever halted the asset first (see its `# Gates` `[!failure]` callout for the reason), then re-confirm the routing once the asset is no longer halted.

---

## `/lazy-spec.refresh-sources` refuses on a non-authored doc

**Symptom**: The skill refuses with `reason: folder-note` or `reason: no-source-docs`.

**Likely cause**: `lazy-spec.refresh-sources` only operates on stage-bearing authored docs — `design.md`, `tech.md`, `code-plan.md`, `test-plan.md`, or `bug.md` — the docs that carry `spec_source_docs` / `spec_source_requests` frontmatter. `folder-note` means you pointed it at a status or level note. `no-source-docs` means the target's document type is undeclared or carries no stages, as with a `code-report.md` / `test-report.md` journal or another file type.

**Fix**: Re-invoke `/lazy-spec.refresh-sources` against one of the five stage-bearing authored docs in that folder.

---

## A note's one-line description stays empty

**Symptom**: The `# Summary` section of a product root, a catalog root, or an asset note shows nothing under its explainer line, or shows an old placeholder.

**Likely cause**: The description is written by the coordinator that owns the note, on a wake. A level or asset that has never been woken — a product registered but carrying no assets, for instance — has never had one written.

**Fix**: Give the coordinator a reason to wake, or run `/lazy-spec.drive` to walk the notes in session mode. A group note (`bugs/`, `changes/`) deliberately carries no description at all — only its counts.
