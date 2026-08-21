---
chapter_type: troubleshooting
summary: Common failure modes across lazycortex-specs skills — symptoms, likely causes, and targeted fixes.
last_regen: 2026-08-21
no_diagram: true
source_skills:
  - lazy-spec.add-asset-type
  - lazy-spec.audit
  - lazy-spec.coverage
  - lazy-spec.create-asset
  - lazy-spec.create-request
  - lazy-spec.create-from-code
  - lazy-spec.decide
  - lazy-spec.doctor
  - lazy-spec.finalize-branch
  - lazy-spec.flip-gate
  - lazy-spec.install
  - lazy-spec.lookup
  - lazy-spec.product-config
  - lazy-spec.refresh-sources
  - lazy-spec.request-classify
  - lazy-spec.request-find-candidates
  - lazy-spec.resolve-dependency
  - lazy-spec.resolve-repo
  - lazy-spec.set-stage
  - lazy-spec.sync-with-code
  - lazy-spec.upstream-run
source_sha: 159ac1288fe27b2672a13bdafc577c34c46cb8d5
---
# Troubleshooting

## `/lazy-spec.install` aborts: plugin not installed

**Symptom**: The install skill aborts immediately, saying `lazycortex-specs@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json`.

**Likely cause**: The plugin isn't enabled in this Claude Code environment yet — `enabledPlugins` in `settings.json` has no entry for it.

**Fix**: Add `"lazycortex-specs@lazycortex": true` to `enabledPlugins` in your `settings.json`, restart Claude Code, then re-run `/lazy-spec.install`.

---

## `/lazy-spec.install` reports a routine already registered

**Symptom**: The install run reports `routine lazy-spec.gate-tick already registered`, `routine lazy-spec.coordinator-watch already registered`, or `routine lazy-spec.collect already registered` and moves on without rewiring it.

**Likely cause**: A prior install already wired that routine. Re-running `/lazy-spec.install` never overwrites an existing routine registration — this is the expected `routine-already-present` outcome, not a failure. `lazy-spec.collect` is the postman routine that delivers a finished expert job's terminal marker back into the asset's status folder-note — install registers it alongside the gate-tick and coordinator-watch routines.

**Fix**: Nothing to do if the routine's shape is still correct. To change its shape (schedule, paths, filters), run `/lazy-routine.unregister lazy-spec.gate-tick` (or `lazy-spec.coordinator-watch`, or `lazy-spec.collect`) first, then re-run `/lazy-spec.install` so it re-registers fresh.

---

## `/lazy-spec.product-config` aborts pointing at `lazycortex-experts`

**Symptom**: The wizard reaches the expert-assignment step and aborts with a message saying a chosen expert name is not registered.

**Likely cause**: The designer, system-designer, architect, planner, developer, tester, or data-writer persona you selected for one of the built-in review roles is not a key in the `experts` settings section. This happens when the persona has not been composed yet or the name was mistyped.

**Fix**: Compose the missing persona via `lazycortex-experts` first, then re-run `/lazy-spec.product-config`. Do not type a free-form name that does not exist in the registry — the skill validates every name against `settings-get experts`.

---

## `/lazy-spec.product-config` refuses because the `spec_path` is nested

**Symptom**: The wizard rejects the derived path with a message that the `spec_path` sits inside another product's `spec_path`.

**Likely cause**: Products in lazycortex-specs are flat siblings — one product's folder must not be a subdirectory of another product's folder. A path like `Server/products/api/auth` would be rejected if `Server/products/api` is already registered.

**Fix**: Choose a sibling path at the same level as the other product, or introduce an optional namespace folder (e.g. `Server/products/backend/auth` alongside `Server/products/backend/api`). Re-run `/lazy-spec.product-config` with the corrected path.

---

## `/lazy-spec.product-config` refuses because the compound-key already exists

**Symptom**: The wizard aborts saying the derived `<subsystem>[-<namespace>]-<leaf>` key is already present in `products`.

**Likely cause**: A product with the same subsystem/namespace/leaf combination was registered previously.

**Fix**: If you want to edit the existing product, re-invoke `/lazy-spec.product-config` with that product's key or path — the skill enters edit mode. If you genuinely need a new sibling product, pick a different leaf or namespace so the compound-key is unique.

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

**Likely cause**: For the "not registered" case, the product key is not in `products`. For the "design-only" case, the product record exists but has no `source` block binding it to a code repo.

**Fix**: For an unregistered product, run `/lazy-spec.product-config` first. For a design-only product, re-run `/lazy-spec.product-config` in edit mode to attach a source repo — the wizard adds the `source.repo` and `source.paths` block without clobbering the product's existing `asset_types` / `tool_types` declarations or any other field it did not ask about.

---

## `/lazy-spec.create-request` aborts with nothing to capture

**Symptom**: The skill aborts saying it has no idea to capture.

**Likely cause**: You ran the skill without giving it a raw idea, and didn't supply one when the wizard asked.

**Fix**: Re-invoke `/lazy-spec.create-request` and give it a sentence or two describing the idea before the wizard's clarifying questions run.

---

## `/lazy-spec.decide` refuses to record, supersede, obsolete, or promote a decision

**Symptom**: The `decide` primitive refuses with one of: `no such record: D-NNN`, `no such doc`, or `spec_role '<x>' is not a living doc`.

**Likely cause**: The first two are a mismatched target — the id you gave `supersede` or `obsolete` doesn't exist in that file's `## D-NNN` headings, or the path you gave `promote` doesn't exist at all. The third means you pointed `promote` at a document whose role isn't `design` / `bug` / `tech` / `architecture` — a plan never promotes (a plan only decomposes decisions already accepted elsewhere) and a report never promotes (it carries decision-candidates, not decisions).

**Fix**: Re-check the id against the file's own headings, or the path itself, for the first two. For the third, put the decision statement in the correct living doc and promote from there — never force a promote against a plan or a report.

---

## `/lazy-spec.decide promote` refuses: the owning asset is cancelled, halted, or released

**Symptom**: `promote` refuses unconditionally, naming `spec_cancelled`, `spec_halted`, or `spec_released` as the reason.

**Likely cause**: `promote` checks all three flags before writing anything into the decisions registry — a decision doesn't get promoted out of an asset that is cancelled, currently halted, or already shipped.

**Fix**: Clear the flag first (`/lazy-spec.flip-gate <asset> spec_cancelled --off`, or resolve whatever halted the asset), then re-run `promote`. Nothing forces the transfer — the decision block stays in place, unpromoted, until you do.

---

## `/lazy-spec.decide` reports `duplicate: D-NNN`

**Symptom**: The command reports `duplicate: D-NNN` and nothing new appears in the decisions file.

**Likely cause**: This is not a failure — an existing record already carries the same normalized thesis and body as the one you tried to add.

**Fix**: Nothing to fix. If you meant a genuinely different decision, reword it so its thesis is distinguishable from `D-NNN`, then re-run.

---

## I flipped a gate out of order — `/lazy-spec.flip-gate` didn't stop me

**Symptom**: `/lazy-spec.flip-gate <asset> <gate>` succeeded even though the gate's usual precondition (the doc it depends on isn't approved yet, or an earlier gate is still `false`) doesn't actually hold.

**Likely cause**: The primitive no longer checks a gate's readiness before flipping — it performs the mutation unconditionally, refusing only when the asset is cancelled. Deciding whether a gate is actually ready is `spec.coordinator`'s job when IT calls the primitive (reasoning from `lazy-spec.coordination-playbook.md`); when you call `/lazy-spec.flip-gate` yourself, the interactive confirmation is your own chance to double-check, not a safety net the primitive re-verifies.

**Fix**: Check the readiness table in `lazy-spec.lifecycle-protocol.md` Part 2 for what the gate SHOULD require, then flip it back with `--off` (also unconditional, refused only while cancelled) if it was flipped prematurely. `spec.coordinator` will re-derive the correct state on its next wake and, for the two derived gates, may flip it forward again on its own once the actual precondition holds.

---

## `/lazy-spec.flip-gate` refuses with "asset cancelled"

**Symptom**: The gate flip is refused with a message that the asset is cancelled.

**Likely cause**: `spec_cancelled: true` on the asset's status folder-note freezes all gate progression. No flip — on or off — is allowed while an asset is cancelled.

**Fix**: Uncancel the asset by running `/lazy-spec.flip-gate <asset> spec_cancelled --off` if you want to resume it, or leave it cancelled if the work is truly abandoned. After uncancelling, gate flips proceed normally.

---

## `/lazy-spec.flip-gate` cannot resolve the asset

**Symptom**: The skill prints a refusal saying the input matches zero or more than one asset.

**Likely cause**: The path or slug you passed is ambiguous — it could map to multiple products or categories — or it does not match any asset folder.

**Fix**: Pass the unambiguous asset directory path (e.g. `Server/products/api/features/csv-export`).

---

## `/lazy-spec.set-stage` refuses: document carries no `spec_doc_type`

**Symptom**: The skill refuses, saying the target document carries no `spec_doc_type`.

**Likely cause**: Per-file stage now resolves purely from the document's declared type, never from its filename or path — an untyped document (usually predating the type-declaration model, or a hand-created file) has no type key to resolve.

**Fix**: Run `lazycortex-specs doc-type backfill` to type every document in the catalog that's missing the key, or add `spec_doc_type` to that one document by hand, then re-invoke `/lazy-spec.set-stage`.

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

**Likely cause**: You passed a stage outside `empty | draft | approved | rejected | cancelled` — often a leftover from an older model (`review`, `done`, `wtr`).

**Fix**: Pass `draft` and set `review_active: true` for a doc that's currently in review, `approved` once it's accepted, or whichever closed-set value matches your intent.

---

## `/lazy-spec.set-stage` refuses: document is an attachment of `<owner>`

**Symptom**: The skill refuses, saying the target document is an attachment of another document and its stage mirrors the owner's.

**Likely cause**: The file carries `spec_owner_doc`, marking it a markdown attachment — its `spec_stage` is a mirror the owner's own stage cascade writes, never set directly (except while the attachment is itself under active review, when nobody writes the file).

**Fix**: Set the stage on the owner document instead — `/lazy-spec.set-stage <owner-doc> <stage>` cascades the same stage to every sibling attachment (except one currently in review) in the same commit.

---

## `/lazy-spec.set-stage` refuses: cancelled isn't allowed on this file

**Symptom**: The skill refuses to set `cancelled` on the target file.

**Likely cause**: `design.md` is mandatory for every asset — both the asset-level document (`design` type) and the product-root / content-root pair (`system-design` type) — alongside `bug.md` and `architecture.md`; none of the four can be cancelled individually. Cancellation belongs on `tech.md` (`system-tech` type — a docs-only feature), `code-plan.md` (a no-code bug fix or feature), or `test-plan.md` (no dedicated functional test pass needed).

**Fix**: Set `cancelled` on `tech.md`, `code-plan.md`, or `test-plan.md` instead, whichever fits the asset. If the whole asset is abandoned, cancel it at the asset level via `/lazy-spec.flip-gate` instead of a single file.

---

## `/lazy-spec.sync-with-code` refuses or no-ops for a product

**Symptom**: The skill either refuses naming an unregistered product, or prints "product is design-only — no code binding to sync" and stops without syncing.

**Likely cause**: The product is missing from `products` or has no `source` block.

**Fix**: Register the product via `/lazy-spec.product-config`, or attach a source repo in edit mode. Then re-run `/lazy-spec.sync-with-code`.

---

## `/lazy-spec.sync-with-code` aborts with "fetch failed"

**Symptom**: The sync aborts early with a message that `git fetch --prune` failed.

**Likely cause**: The source repo's remote is unreachable — network error, authentication failure, or no remote configured at `local_path`.

**Fix**: Confirm network connectivity and credentials for the source repo. If the repo has no remote, add one (`git remote add origin <url>`). The skill refuses to operate on stale refs, so fix connectivity first, then re-run.

---

## `/lazy-spec.sync-with-code` never proposes a `spec_develop_done` flip despite landed code

**Symptom**: Commits objectively implementing an asset are on the default branch, but the sync wizard never surfaces a `spec_develop_done` proposal for it.

**Likely cause**: `spec_plan_done` doesn't read `true` yet. The skill checks this itself before proposing (`/lazy-spec.flip-gate` no longer double-checks a gate's readiness on its own — see "I flipped a gate out of order" above), so an unmet code-plan gate silently withholds the proposal rather than surfacing one that would land wrong.

**Fix**: Settle the code plan — the asset's `code-plan.md`, if one was ever authored, must reach `spec_stage: approved` (or absence itself satisfies the gate) — then flip `spec_plan_done` yourself via `/lazy-spec.flip-gate`, or let `spec.coordinator` derive and flip it on its next wake. Re-run `/lazy-spec.sync-with-code` afterward.

---

## `/lazy-spec.finalize-branch` aborts with "fetch failed"

**Symptom**: The skill aborts before scanning any pinned specs, with an error naming a repo where `git fetch --prune` failed.

**Likely cause**: Network error, auth failure, or no remote configured in `lazy.settings.json[repos]` for one of the registered repos.

**Fix**: Fix connectivity or credentials for the affected repo, then re-run `/lazy-spec.finalize-branch`. The skill never operates on stale remote refs.

---

## `/lazy-spec.finalize-branch` reports "still open" for a named branch

**Symptom**: When invoked with an explicit branch name, the skill reports "still open" and makes no changes.

**Likely cause**: The branch is not yet an ancestor of the default branch and still exists on the remote — it has not been merged.

**Fix**: Merge the branch via your normal workflow. If the merge used a squash and the ancestry check therefore fails, re-run `/lazy-spec.finalize-branch <branch> --force-merged` after confirming the squash was deliberate. Alternatively, delete the branch — after `fetch --prune` the skill treats a deleted branch as merged.

---

## `/lazy-spec.finalize-branch` never proposes a `spec_released` flip after a merge

**Symptom**: A branch merged and its pins rebased cleanly, but the skill never surfaces a `spec_released` proposal for the asset.

**Likely cause**: `spec_tests_passing` doesn't read `true` yet. The skill checks this itself before proposing (`/lazy-spec.flip-gate` no longer double-checks a gate's readiness on its own), so it skips the proposal instead of surfacing one that would land wrong.

**Fix**: Settle the holding gate. For `spec_tests_passing`, flip it once a green test report exists for the asset's code by running `/lazy-spec.flip-gate <asset> spec_tests_passing`, or let `spec.coordinator` derive it. The branch rebase is already applied regardless — only the release proposal was withheld.

---

## `/lazy-spec.coverage` refuses or has nothing to gap-scan

**Symptom**: The skill either refuses naming an unregistered product, or reports "no code binding — nothing to gap-scan" and stops.

**Likely cause**: The product key isn't in `lazy.settings.json[products]`, or the product record has no `source` block — a design-only product has no code to compare the spec tree against.

**Fix**: Register the product via `/lazy-spec.product-config` for the first case. For the second, attach a source repo in edit mode if the product does have code; a genuinely design-only product simply has no gap-scan surface, and that is expected rather than an error.

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

**Likely cause**: The unit's mirrored root note (`source/<unit>.md`) carries `spec_draft: true` — a deliberate gate that withholds the checkbox until the upstream design itself drops the draft flag.

**Fix**: Check the unit's own folder-note `# Actions` section for the actual state. Nothing to do until the upstream source itself marks the design non-draft; this is expected gating, not a stuck run.

---

## `/lazy-spec.resolve-repo` aborts: repo key not registered

**Symptom**: The primitive aborts, naming `<key>` as not present in `lazy.settings.json[repos]`.

**Likely cause**: The repo key was never registered, or was mistyped.

**Fix**: Register the repo via `/lazy-spec.product-config` — its inline repo wizard writes the `repos[<key>]` record — then re-invoke `/lazy-spec.resolve-repo <key>`.

---

## `/lazy-spec.resolve-repo` aborts: missing `local_path` or `branch`

**Symptom**: The primitive aborts saying the `repos[<key>]` record is incomplete.

**Likely cause**: The repo record is missing `local_path` and/or `branch` — an incomplete manual edit, or a partially-completed inline repo wizard run.

**Fix**: Re-run `/lazy-spec.product-config` and complete the repo wizard for `<key>`, supplying both `local_path` and `branch`, then re-invoke.

---

## `/lazy-spec.resolve-repo` aborts: `local_path` is `.` but the current directory is not a git repo

**Symptom**: The primitive aborts saying `git rev-parse --show-toplevel` failed for the record's same-repo (`.`) form.

**Likely cause**: The repo record uses `local_path: "."` (meaning "the same checkout the skill is running in"), but the command was run from outside a git checkout, or outside the checkout that holds `.claude/lazy.settings.json`.

**Fix**: Run the command from inside the checkout that holds `.claude/lazy.settings.json`, or set an explicit absolute `local_path` on the repo record via `/lazy-spec.product-config` instead of relying on `"."`.

---

## `/lazy-spec.resolve-repo` aborts: no git remotes configured

**Symptom**: The primitive aborts with "no git remotes configured" for the checkout at `local_path`.

**Likely cause**: `git remote` returns nothing for that checkout — the repo was cloned without a remote, or the remote was removed.

**Fix**: Add a remote inside the checkout (`git remote add origin <url>`), then re-invoke `/lazy-spec.resolve-repo <key>`.

---

## `/lazy-spec.resolve-repo` aborts: nested GitLab subgroup path

**Symptom**: The primitive aborts saying the remote URL path has more than two segments.

**Likely cause**: The repo lives in a nested GitLab subgroup (`owner/group/repo`) — nested subgroups aren't supported by the automatic path parser yet.

**Fix**: Set an explicit `forge:` override on the repo record via `/lazy-spec.product-config` and use a flattened two-segment owner/repo reference, or wait for subgroup support.

---

## `/lazy-spec.resolve-repo` aborts: unknown forge

**Symptom**: The primitive aborts saying the remote's hostname is not in the known-forges table.

**Likely cause**: The repo is hosted on a forge instance (self-hosted GitLab, Gitea, Forgejo, …) whose hostname the plugin can't classify automatically, and no explicit override is set on the record.

**Fix**: Add `forge: <key>` (one of `github`, `gitlab`, `bitbucket`, `gitea`, `forgejo`, `sourcehut`) to the repo's record via `/lazy-spec.product-config`, then re-invoke.

---

## `/lazy-spec.resolve-dependency` refuses with a malformed dependency entry

**Symptom**: The primitive refuses, naming a dependency entry that lacks a required key.

**Likely cause**: The entry in the product's `dependencies` array doesn't match any of the three documented shapes — it's missing a `product:`, `repo:`, or `external:` key.

**Fix**: Fix the entry via `/lazy-spec.product-config` (edit mode) so it matches one of the three shapes, then re-invoke `/lazy-spec.resolve-dependency`.

---

## `/lazy-spec.resolve-dependency` refuses: product or repo not found

**Symptom**: The primitive refuses, naming a product or repo key from a dependency entry that doesn't resolve.

**Likely cause**: A `product:` entry points at a key that isn't in `products`, or a `repo:` entry points at a key that isn't in `repos` — unregistered, or mistyped.

**Fix**: Register the missing product or repo via `/lazy-spec.product-config`, or correct the key spelling in the dependency entry.

---

## `/lazy-spec.request-find-candidates` refuses when the request's class is unknown

**Symptom**: The candidate search refuses, saying the request hasn't been classified yet.

**Likely cause**: Classification runs before candidate search in the request-routing flow — an `unknown` class means that step hasn't settled.

**Fix**: Let the routing pass classify the request first, then let candidate search run again on the classified request.

---

## A request's apply pass fails: attach target doesn't resolve to a folder-note

**Symptom**: Once you confirm the routing, the request stays at its pre-apply state and the apply worker's error names an attach target that "does not resolve to a folder-note".

**Likely cause**: The routing decision's `attach <path>` line names a repo-relative path that either doesn't exist or isn't a `<slug>/<slug>.md` folder-note — a stale or hand-typed path in the `routing-decision` block.

**Fix**: Edit the `routing-decision` block in the request's `# Routing` section to the correct folder-note path, then re-confirm the routing.

---

## A request's apply pass refuses: attach target is a launched feature

**Symptom**: The apply worker refuses, saying the attach target is a launched feature and routing must spawn a change instead.

**Likely cause**: The feature the routing named already has `spec_develop_done: true`, an active `Start implementation` job, or a `code-report.md` — it counts as launched, and a request must never attach directly to a launched feature's spec (that would edit an already-implemented feature's docs out from under the code).

**Fix**: Edit the `routing-decision` block to spawn a `change` naming the feature in its `targets=` field instead of attaching — see [requests](requests.md).

---

## A request's apply pass refuses: attach target is halted

**Symptom**: The apply worker refuses, saying the attach target is halted and automation is refused until an operator resolves it.

**Likely cause**: The target asset carries `spec_halted: true` from an earlier, unrelated failure (a dead job, an import drift, …) — every automated action on a halted asset is refused until a human clears it.

**Fix**: Resolve whatever halted the asset first (see its `# Gates` `[!failure]` callout for the reason), then re-confirm the routing once the asset is no longer halted.

---

## `/lazy-spec.refresh-sources` refuses on a non-authored doc

**Symptom**: The skill refuses, saying the target file's `spec_role` isn't an authored-doc role.

**Likely cause**: `lazy-spec.refresh-sources` only operates on `design.md`, `tech.md`, `code-plan.md`, `test-plan.md`, or `bug.md` — the docs that carry `spec_source_docs` / `spec_source_requests` frontmatter. You pointed it at a folder-note (`spec_role: status`), a `code-report.md` / `test-report.md` journal, or another file type instead.

**Fix**: Re-invoke `/lazy-spec.refresh-sources` against one of the five stage-bearing authored docs.

---

## `/lazy-spec.refresh-sources` skips the stats refresh

**Symptom**: The run completes and rewrites the `# Sources` sub-sections and précis, but reports that the container-stats refresh was skipped.

**Likely cause**: The `render-container-stats` CLI isn't on `PATH` — the specs tool isn't installed, or the shell environment can't see it.

**Fix**: Re-run `/lazy-spec.install` to restore the CLI, then re-invoke `/lazy-spec.refresh-sources` if you need the stats block refreshed too. The `# Sources` rewrite and précis already landed even without the stats step.

---
