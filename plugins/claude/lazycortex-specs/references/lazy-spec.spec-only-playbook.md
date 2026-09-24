---
description: Spec-only mode — the definition-only ladder for products with mode "spec-only", gates closing as N/A, operator-word release, and the generalized spec_draft flag. Conditional chapter 17 of the coordination playbook.
---
# Spec-only mode — conditional chapter of the coordination playbook

Extracted chapter 17 of `lazy-spec.coordination-playbook.md`, loaded on demand: read this file when the owning product's record in the job's `payload["product"]` carries `mode: "spec-only"`. Every "Chapter N" cross-reference below names a chapter of that common playbook.

**Activation.** `products[<key>].mode: "spec-only"`, set by `/lazy-spec.product-config`'s wizard; absence means full mode (the ordinary ladder this playbook and the type playbooks describe). `_build_bundle` folds the owning product's whole record — mode included — into every coordinator job's `payload["product"]` unconditionally, so the profile check below never needs a separate settings read. The profile is a property of the PRODUCT, not of any asset type: it applies to every asset under that product whatever its `spec_asset_type`.

**The ladder is definition-only.** A spec-only asset's entire progression is: its type's starting document → review → operator approve → `spec_design_done`. Nothing past that exists for this asset — no architecture step, no plans, no implementation, no test run. No launch checkbox past the definition step ever hangs on a spec-only asset — their preconditions are simply never evaluated, not evaluated-and-refused, and the type playbook's own later chapters do not run.

**Gates close as N/A, never as a stall.** `spec_plan_done`, `spec_develop_done`, and `spec_tests_passing` are not flipped true and not left dangling as an unmet precondition either — this profile does not route through them at all on the way to the terminal state, so an operator reading the gate booleans on a spec-only asset should read the three middle gates as inapplicable, not as work still pending.

**Terminal state — `spec_released` by operator word.** Once the defining document is approved, the asset is functionally done from this repo's own perspective; `spec_released` flips true on an explicit operator signal (a ticked `[!question]` option, or a `# Coordinator commands` entry) — never derived from a checkbox completing, since this profile hangs none past the definition step.

**Draft flag, generalized.** `spec_draft` names one downstream consumer today (another repo's own `lazy-spec.upstream-tick`, when it configures this repo as one of its `spec.upstream` sources) but its documented meaning is not tied to that path — it is "this asset is NOT yet ready for a downstream consumer to pick up" (absent or false means ready), where a downstream repo mirrors THIS repo as its own upstream (whatever mechanism that consumer uses to pull). In a spec-only profile, the coordinator clears the flag after the defining document's approval AND the operator's own word (the same `[!question]`-or-command gesture the terminal state above uses) — never automatically the moment it approves.
