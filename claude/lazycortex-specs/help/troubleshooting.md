---
chapter_type: troubleshooting
summary: Common failure modes across lazycortex-specs skills — symptoms, likely causes, and targeted fixes.
last_regen: 2026-07-26
no_diagram: true
source_skills:
  - spec.create-asset
  - spec.create-feature
  - spec.create-change
  - spec.create-bug
  - spec.add-asset-category
  - spec.create-from-code
  - spec.create-request
  - spec.flip-gate
  - spec.gate-tick
  - spec.set-stage
  - spec.sync-with-code
  - spec.finalize-branch
  - spec.resolve-repo
  - spec.resolve-dependency
  - spec.source-url
  - spec.request-router
  - spec.request-classify
  - spec.request-find-candidates
  - spec.request-attach
  - spec.request-spawn
  - spec.install
  - spec.product-config
  - spec.doctor
---
# Troubleshooting

## `/spec.product-config` aborts pointing at `lazycortex-experts`

**Symptom**: The wizard reaches the expert-assignment step and aborts with a message saying a chosen expert name is not registered.

**Likely cause**: The designer, developer, tester, or historian persona you selected is not a key in the `experts` settings section. This happens when the persona has not been composed yet or the name was mistyped.

**Fix**: Compose the missing persona via `lazycortex-experts` first, then re-run `/spec.product-config`. Do not type a free-form name that does not exist in the registry — the skill validates every name against `settings-get experts`.

---

## `/spec.product-config` refuses because the `spec_path` is nested

**Symptom**: The wizard rejects the derived path with a message that the `spec_path` sits inside another product's `spec_path`.

**Likely cause**: Products in lazycortex-specs are flat siblings — one product's folder must not be a subdirectory of another product's folder. A path like `Server/products/api/auth` would be rejected if `Server/products/api` is already registered.

**Fix**: Choose a sibling path at the same level as the other product, or introduce an optional namespace folder (e.g. `Server/products/backend/auth` alongside `Server/products/backend/api`). Re-run `/spec.product-config` with the corrected path.

---

## `/spec.product-config` refuses because the compound-key already exists

**Symptom**: The wizard aborts saying the derived `<subsystem>[-<namespace>]-<leaf>` key is already present in `products`.

**Likely cause**: A product with the same subsystem/namespace/leaf combination was registered previously.

**Fix**: If you want to edit the existing product, re-invoke `/spec.product-config` with that product's key or path — the skill enters edit mode. If you genuinely need a new sibling product, pick a different leaf or namespace so the compound-key is unique.

---

## `/spec.product-config` aborts at Step 10 before writing review classes

**Symptom**: After finishing the wizard — icon, experts, categories all answered — the skill aborts right before the review-class write, naming a dangling expert. No `products` or `review` settings are written.

**Likely cause**: Immediately before the write, the skill re-checks every expert name the generated classes are about to carry (every `main` writer, every `validation`/`terminal` writer, the historian) against the registered experts one more time. This catches a case the earlier per-role questions don't — for example an expert removed from the registry between answering the wizard and reaching this step, or a reconciled legacy class carrying an expert name that is no longer registered.

**Fix**: Compose the missing persona via `lazycortex-experts`, then re-run `/spec.product-config`. Nothing was written on the abort, so there is no partial state to clean up.

---

## `/lazy-review.audit` reports FAIL after `/spec.product-config` writes review classes

**Symptom**: The final report includes an `audit: FAIL` line from `lazy-review.audit`, naming a schema violation in the generated classes.

**Likely cause**: The expert re-verification immediately before the write (above) already rules out dangling expert names, so a post-write audit FAIL points at something else — a section-writer schema violation in the generated `experts.validation` / `experts.terminal` structure.

**Fix**: Read the audit output for the offending class and field, then re-run `/spec.product-config` — Step 10 regenerates the four behavior-keyed classes fresh each time, so fixing the upstream cause (e.g. correcting a role assignment) resolves it on the next pass.

---

## `/spec.create-asset` refuses naming an unknown product

**Symptom**: The skill prints a refusal naming the product key and suggesting `/spec.product-config`.

**Likely cause**: The product compound-key you passed has no record in `lazy.settings.json[products]`. The product was never registered, or the key was mistyped.

**Fix**: Run `/spec.product-config` to register the product, then re-invoke `/spec.create-asset <product> <category> <slug>`. Verify the compound-key matches exactly what the wizard wrote into config. This applies equally to `/spec.create-feature`, `/spec.create-change`, and `/spec.create-bug` — all three are thin wrappers over `/spec.create-asset` and refuse the same way.

---

## `/spec.create-asset` refuses naming an unknown category

**Symptom**: The skill rejects the category name, saying it is neither a built-in nor a declared `asset_categories` key for the product.

**Likely cause**: You passed a category that does not exist in `products[<key>].asset_categories`. The built-in set is `feature`, `change`, `bug`; anything else must be declared first.

**Fix**: Run `/spec.add-asset-category <product> <category-name>` to register the new category, then re-invoke `/spec.create-asset`.

---

## `/spec.add-asset-category` refuses because the category already exists

**Symptom**: The skill rejects the new category name, saying it is already a key in the product's `asset_categories`.

**Likely cause**: A category with that exact name was registered before — re-running the skill with the same name does not overwrite it.

**Fix**: Pick a different category name, or edit the existing category's declaration and folder-note directly if you only meant to change its icon or description.

---

## `/spec.add-asset-category` aborts saying an icon is required

**Symptom**: The wizard aborts after you decline every icon option, saying a category cannot be registered without one.

**Likely cause**: You declined both the iconize suggestion and the emoji fallback without supplying either.

**Fix**: Re-run `/spec.add-asset-category` and answer the icon question with an iconize icon name or an emoji — the category is not written until an icon is set.

---

## `/spec.create-from-code` refuses an unregistered product or no-ops on a design-only product

**Symptom**: The skill either refuses with "product not registered" or prints "product has no code binding" and stops without writing any files.

**Likely cause**: For the "not registered" case, the product key is not in `products`. For the "design-only" case, the product record exists but has no `source` block binding it to a code repo.

**Fix**: For an unregistered product, run `/spec.product-config` first. For a design-only product, re-run `/spec.product-config` in edit mode to attach a source repo — the wizard adds the `source.repo` and `source.paths` block without clobbering any existing asset categories.

---

## `/spec.create-request` aborts with nothing to capture

**Symptom**: The skill aborts saying it has no idea to capture.

**Likely cause**: You ran the skill without giving it a raw idea, and didn't supply one when the wizard asked.

**Fix**: Re-invoke `/spec.create-request` and give it a sentence or two describing the idea before the wizard's clarifying questions run.

---

## `/spec.flip-gate` refuses with "precondition not met"

**Symptom**: The primitive exits with an error message naming a specific gate whose precondition does not hold, rather than performing the flip.

**Likely cause**: The five gates are a strict ladder (`spec_design_done` → `spec_plan_done` → `spec_develop_done` → `spec_tests_passing` → `spec_released`). Flipping a gate requires all earlier gates to already be `true`, and for derived gates (`spec_design_done`, `spec_plan_done`) the corresponding authored doc must be in `approved` stage first.

**Fix**: Satisfy the precondition named in the refusal. For `spec_design_done`, the asset's `design.md` (or `bug.md` for a bug) must reach `spec_stage: approved` — use `/spec.set-stage` after the doc is reviewed and accepted. For `spec_plan_done`, `plan.md` must be `approved` or `cancelled`. Then re-invoke `/spec.flip-gate`.

---

## `/spec.flip-gate` refuses with "asset cancelled"

**Symptom**: The gate flip is refused with a message that the asset is cancelled.

**Likely cause**: `spec_cancelled: true` on the asset's status folder-note freezes all gate progression. No flip — on or off — is allowed while an asset is cancelled.

**Fix**: Uncancel the asset by running `/spec.flip-gate <asset> spec_cancelled --off` if you want to resume it, or leave it cancelled if the work is truly abandoned. After uncancelling, gate flips proceed normally.

---

## `/spec.flip-gate` cannot resolve the asset

**Symptom**: The skill prints a refusal saying the input matches zero or more than one asset.

**Likely cause**: The path or slug you passed is ambiguous — it could map to multiple products or categories — or it does not match any asset folder.

**Fix**: Pass the unambiguous asset directory path (e.g. `Server/products/api/features/csv-export`).

---

## `/spec.set-stage` refuses: file's role isn't an authored doc

**Symptom**: The skill refuses, saying the target file's `spec_role` is not an authored-doc role.

**Likely cause**: `spec_stage` only applies to `design.md`, `tech.md`, `plan.md`, and `bug.md` — you pointed the skill at a folder-note or another file type instead.

**Fix**: Re-invoke `/spec.set-stage` against one of the four authored docs.

---

## `/spec.set-stage` refuses: stage isn't in the closed set

**Symptom**: The skill refuses, saying the stage value isn't in the closed set.

**Likely cause**: You passed a stage outside `empty | draft | approved | rejected | cancelled` — often a leftover from an older model (`review`, `done`, `wtr`).

**Fix**: Pass `draft` and set `review_active: true` for a doc that's currently in review, `approved` once it's accepted, or whichever closed-set value matches your intent.

---

## `/spec.set-stage` refuses: cancelled isn't allowed on this file

**Symptom**: The skill refuses to set `cancelled` on the target file.

**Likely cause**: `design.md` and `bug.md` are mandatory docs and can't be cancelled individually — cancellation belongs on `tech.md` (a docs-only feature) or `plan.md` (a no-code bug fix).

**Fix**: Set `cancelled` on `tech.md` or `plan.md` instead, whichever fits the asset. If the whole asset is abandoned, cancel it at the asset level via `/spec.flip-gate` instead of a single file.

---

## `/spec.sync-with-code` refuses or no-ops for a product

**Symptom**: The skill either refuses naming an unregistered product, or prints "product is design-only — no code binding to sync" and stops without syncing.

**Likely cause**: The product is missing from `products` or has no `source` block.

**Fix**: Register the product via `/spec.product-config`, or attach a source repo in edit mode. Then re-run `/spec.sync-with-code`.

---

## `/spec.sync-with-code` aborts with "fetch failed"

**Symptom**: The sync aborts early with a message that `git fetch --prune` failed.

**Likely cause**: The source repo's remote is unreachable — network error, authentication failure, or no remote configured at `local_path`.

**Fix**: Confirm network connectivity and credentials for the source repo. If the repo has no remote, add one (`git remote add origin <url>`). The skill refuses to operate on stale refs, so fix connectivity first, then re-run.

---

## A proposed `spec_develop_done` flip during `/spec.sync-with-code` is refused

**Symptom**: After approving the gate proposal in the sync wizard, the skill surfaces a `flip_gate` refusal message rather than advancing the gate.

**Likely cause**: The gate's precondition (`spec_plan_done: true`) does not hold. The plan doc has not yet been approved and its gate has not been derived.

**Fix**: Settle the plan first — the asset's `plan.md` must reach `spec_stage: approved` and `spec_plan_done` must be `true`. Once the plan gate is set, re-run `/spec.sync-with-code` to re-propose the `spec_develop_done` flip.

---

## `/spec.finalize-branch` aborts with "fetch failed"

**Symptom**: The skill aborts before scanning any pinned specs, with an error naming a repo where `git fetch --prune` failed.

**Likely cause**: Network error, auth failure, or no remote configured in `lazy.settings.json[repos]` for one of the registered repos.

**Fix**: Fix connectivity or credentials for the affected repo, then re-run `/spec.finalize-branch`. The skill never operates on stale remote refs.

---

## `/spec.finalize-branch` reports "still open" for a named branch

**Symptom**: When invoked with an explicit branch name, the skill reports "still open" and makes no changes.

**Likely cause**: The branch is not yet an ancestor of the default branch and still exists on the remote — it has not been merged.

**Fix**: Merge the branch via your normal workflow. If the merge used a squash and the ancestry check therefore fails, re-run `/spec.finalize-branch <branch> --force-merged` after confirming the squash was deliberate. Alternatively, delete the branch — after `fetch --prune` the skill treats a deleted branch as merged.

---

## A proposed `spec_released` flip during `/spec.finalize-branch` is refused

**Symptom**: After approving the release proposal for an asset, the skill surfaces a `flip_gate` refusal rather than setting `spec_released`.

**Likely cause**: The release precondition (`spec_tests_passing: true`) does not hold. The full ladder must be satisfied: design done → plan done → develop done → tests passing → released.

**Fix**: Settle the holding gate. For `spec_tests_passing`, flip it once a green test report exists for the asset's code by running `/spec.flip-gate <asset> spec_tests_passing`. The branch rebase from `spec.finalize-branch` is already applied — only the release flip is held back. Re-run `/spec.finalize-branch` to re-propose the release once the gate is set.

---

## `/spec.resolve-repo` aborts: repo key not registered

**Symptom**: The primitive aborts, naming `<key>` as not present in `lazy.settings.json[repos]`.

**Likely cause**: The repo key was never registered, or was mistyped.

**Fix**: Register the repo via `/spec.product-config` — its inline repo wizard writes the `repos[<key>]` record — then re-invoke `/spec.resolve-repo <key>`.

---

## `/spec.resolve-repo` aborts: missing `local_path` or `branch`

**Symptom**: The primitive aborts saying the `repos[<key>]` record is incomplete.

**Likely cause**: The repo record is missing `local_path` and/or `branch` — an incomplete manual edit, or a partially-completed inline repo wizard run.

**Fix**: Re-run `/spec.product-config` and complete the repo wizard for `<key>`, supplying both `local_path` and `branch`, then re-invoke.

---

## `/spec.resolve-repo` aborts: `local_path` is `.` but the current directory is not a git repo

**Symptom**: The primitive aborts saying `git rev-parse --show-toplevel` failed for the record's same-repo (`.`) form.

**Likely cause**: The repo record uses `local_path: "."` (meaning "the same checkout the skill is running in"), but the command was run from outside a git checkout, or outside the checkout that holds `.claude/lazy.settings.json`.

**Fix**: Run the command from inside the checkout that holds `.claude/lazy.settings.json`, or set an explicit absolute `local_path` on the repo record via `/spec.product-config` instead of relying on `"."`.

---

## `/spec.resolve-repo` aborts: no git remotes configured

**Symptom**: The primitive aborts with "no git remotes configured" for the checkout at `local_path`.

**Likely cause**: `git remote` returns nothing for that checkout — the repo was cloned without a remote, or the remote was removed.

**Fix**: Add a remote inside the checkout (`git remote add origin <url>`), then re-invoke `/spec.resolve-repo <key>`.

---

## `/spec.resolve-repo` aborts: nested GitLab subgroup path

**Symptom**: The primitive aborts saying the remote URL path has more than two segments.

**Likely cause**: The repo lives in a nested GitLab subgroup (`owner/group/repo`) — nested subgroups aren't supported by the automatic path parser yet.

**Fix**: Set an explicit `forge:` override on the repo record via `/spec.product-config` and use a flattened two-segment owner/repo reference, or wait for subgroup support.

---

## `/spec.resolve-repo` aborts: unknown forge

**Symptom**: The primitive aborts saying the remote's hostname is not in the known-forges table.

**Likely cause**: The repo is hosted on a forge instance (self-hosted GitLab, Gitea, Forgejo, …) whose hostname the plugin can't classify automatically, and no explicit override is set on the record.

**Fix**: Add `forge: <key>` (one of `github`, `gitlab`, `bitbucket`, `gitea`, `forgejo`, `sourcehut`) to the repo's record via `/spec.product-config`, then re-invoke.

---

## `/spec.resolve-dependency` refuses with a malformed dependency entry

**Symptom**: The primitive refuses, naming a dependency entry that lacks a required key.

**Likely cause**: The entry in the product's `dependencies` array doesn't match any of the three documented shapes — it's missing a `product:`, `repo:`, or `external:` key.

**Fix**: Fix the entry via `/spec.product-config` (edit mode) so it matches one of the three shapes, then re-invoke `/spec.resolve-dependency`.

---

## `/spec.resolve-dependency` refuses: product or repo not found

**Symptom**: The primitive refuses, naming a product or repo key from a dependency entry that doesn't resolve.

**Likely cause**: A `product:` entry points at a key that isn't in `products`, or a `repo:` entry points at a key that isn't in `repos` — unregistered, or mistyped.

**Fix**: Register the missing product or repo via `/spec.product-config`, or correct the key spelling in the dependency entry.

---

## `/spec.request-find-candidates` refuses when the request's class is unknown

**Symptom**: The candidate search refuses, saying the request hasn't been classified yet.

**Likely cause**: Classification runs before candidate search in the request-routing flow — an `unknown` class means that step hasn't settled.

**Fix**: Let the routing pass classify the request first, then let candidate search run again on the classified request.

---

## `/spec.request-attach` aborts: request or target path doesn't exist

**Symptom**: The skill aborts, pointing at a request or target path that isn't on disk.

**Likely cause**: The request file's path is wrong, or the target you passed isn't a folder-note carrying `role: status`.

**Fix**: Double-check the request file's path, and pass the folder-note path of the entity you want to attach to — not a wikilink and not a bare folder name.

---

## `/spec.request-attach` aborts: target entity is cancelled

**Symptom**: The skill aborts, saying the target entity is cancelled.

**Likely cause**: The feature/change/bug you're trying to attach the request to has `spec_cancelled: true` — attaching to a cancelled entity isn't allowed.

**Fix**: Pick a different, active target for the attach, or spawn a fresh entity instead of reusing the cancelled one.

---

## `/spec.request-spawn` refuses: target folder already exists

**Symptom**: The skill refuses, saying the target folder for the new entity already exists.

**Likely cause**: The slug picked for the new feature/change/bug collides with an existing asset folder in the same category.

**Fix**: Pick a different, unique slug and re-invoke.

---

## `/spec.install` aborts: plugin not installed

**Symptom**: The skill aborts saying `lazycortex-specs@lazycortex` isn't in your installed plugins.

**Likely cause**: The plugin was never enabled, or enablement didn't survive a settings edit.

**Fix**: Add `"lazycortex-specs@lazycortex": true` to `enabledPlugins` in your `settings.json`, restart Claude Code, then re-run `/spec.install`.

---

## `/spec.install` reports the gate-tick routine is already registered

**Symptom**: Running `/spec.install` again prints that the `spec.gate-tick` routine is already registered, and nothing else changes.

**Likely cause**: A prior install already wired the routine — re-running install never overwrites an existing routine registration.

**Fix**: This is the expected outcome, not an error — nothing to fix. If you need to change the routine's shape, unregister it first via `/lazy-routine.unregister spec.gate-tick`, then re-run `/spec.install`.

---

## `/spec.doctor` reports the product is not registered

**Symptom**: The audit stops immediately, saying the product key isn't in `lazy.settings.json[products]`.

**Likely cause**: The product was never registered, or the key you passed to `/spec.doctor` doesn't match what's registered.

**Fix**: Register the product via `/spec.product-config`, then re-run `/spec.doctor <product>`.

---

## `/spec.doctor` reports the product folder name collides with `design`/`tech`

**Symptom**: The audit reports a failure saying the product's folder leaf name is reserved, with no auto-fix offered even under `--apply`.

**Likely cause**: The product's folder is named `design` or `tech` — that collides with the product-level `design.md` / `tech.md` files that sit at the same level.

**Fix**: Rename the product's folder to a non-reserved name by hand. `/spec.doctor --apply` won't rewrite it for you.
