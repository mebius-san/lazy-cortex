---
name: lazy-spec.request-classify
description: "Dispatched by the `spec.coordinator` agent during a request's review loop to label one body with a `request_class` token; not for direct use. Resolves the legal class set from `lazy.settings.json` on every dispatch, so an asset type declared via `lazy-spec.add-asset-type` is recognised on the next run without a rubric edit."
execution-discipline-waiver: "Single-purpose primitive — one input, one classification token."
---
# Classify a request

Read the body of a request file and classify it. Used by `spec.coordinator` during the review loop. The output is one lowercase token drawn from the open set defined by `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.request-protocol.md` → "Class taxonomy".

The class taxonomy and routing implications live there; this skill never restates them. The rubric below names which signals push a body into which class — the legal set of class values is what `lazy-spec.request-protocol.md` declares.

## Input

A markdown body OR a file path, optionally scoped to a product. The caller passes one of:

- **File path** — skill reads the file, strips frontmatter, classifies the body. The product whose `asset_types` apply is derived from the file path when the path lies under a `<vault-root>/<product>/…` subtree; otherwise the skill unions types across every configured product.
- **Inline body string** — skill classifies the supplied string directly. An optional `--product <key>` argument scopes the asset-type half to that product; absent, the skill unions types across every configured product.

## Dynamic resolution of the valid set

Closed meta classes are fixed: `task`, `spec`, `plan`, `feedback`, `unknown`. They never change between runs.

Asset types are read at dispatch time from two layers: the plugin's shipped declarations in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.asset-types.json` (`feature`, `change`, `bug`, `content`, `research`) and a product's own `products[<key>].asset_types` in `lazy.settings.json`, merged over the shipped set key-by-key. Operator-declared types appear alongside the shipped ones once `lazy-spec.add-asset-type` has written them (typical for non-software products: `characters`, `scenes`, `chapters`).

Resolution rules:

- **Product known** (from path or `--product`) — union the closed meta classes with the types visible on that one product (shipped, with the product's own merged over them).
- **Product unknown** (inline body, no `--product`) — union the closed meta classes with the union of visible asset types across every configured product. This is the conservative default: an unknown body should not get a token the host vault doesn't recognise downstream.
- **No product configured at all** (greenfield vault) — fall back to the closed meta classes plus the shipped types. The classifier still functions; `lazy-spec.add-asset-type` is the next step for the operator.

When the resolution returns an empty asset-type half (impossible in practice — the shipped types always seed), the classifier may only emit a closed meta class.

## Rubric

Apply in priority order. First match wins. The order is set so the most domain-specific signals win over generic ones — `bug` defeats `change` defeats operator-declared types defeats `plan` defeats `spec` defeats `task` defeats `feature` defeats `feedback`. `unknown` is the terminal fallback.

1. **`bug`** — body describes a defect: reproduction steps, observed vs expected behaviour, error messages, words like "broken", "fails", "regression", "throws", a stack trace, a screenshot mention.
2. **`change`** — body proposes modifying an EXISTING entity. Names a specific feature / change by name (or a clear synonym) AND uses words like "extend", "modify", "improve", "refactor", "tweak", "adjust".
3. **operator-declared asset types** — body's domain signals match a type declared in the product's `asset_types`. The match is by content-shape, not keyword count: a request describing a new character (name, appearance, role) on a product with a `characters` type classifies as `characters`; a request narrating a scene transition on a product with `scenes` classifies as `scenes`. When several declared types could fit, prefer the one whose stated purpose — the opening chapter of the type's `playbook`, or the `description` on its folder-note when the operator authored one — most closely matches the body's subject. Confidence threshold is similar to `bug` / `change` — the body should clearly fit the type's domain, not "could plausibly fit".
4. **`plan`** — body has a structured implementation plan: numbered steps, phases, or recognisable templates (`## Plan` / `## Phases` / `## Tasks` sections, fixed structure resembling a `superpowers:writing-plans` output).
5. **`spec`** — body is a complete specification: title-suffix `— design`, `## Goal` + `## Architecture` + `## Workflow` shape, or a behaviour description with section structure suggesting a fully-formed spec doc.
6. **`task`** — body describes a single implementation task without broader design intent: "add this endpoint", "rename foo to bar", "update the docs". Short, imperative, scoped to one mechanical action.
7. **`feature`** — body describes desired NEW behaviour at the product / feature level: "add CSV export", "support OAuth login". Default for new-product-functionality requests not matching the more specific classes above.
8. **`feedback`** — body is opinion or observation without a concrete ask: "this UX feels slow", "the docs don't explain X", "I find this confusing". No actionable request, just signal.
9. **`unknown`** — body is too short, too vague, or genuinely ambiguous between multiple categories. Triggers `[!question]` callouts in the coordinator's ambiguous-path flow.

## Boundary cases

- **Boundary between `feature` and `spec`** — prefer the more specific class (`spec`) when the body has section structure resembling a design doc. Routing is the same in both cases (see Class taxonomy).
- **Boundary between `plan` and `task`** — prefer `plan` when the body enumerates multiple steps; `task` for a single discrete action.
- **Boundary between `bug` and `change`** — prefer `bug` when the body describes broken behaviour; `change` when it describes an enhancement to working behaviour.
- **Boundary between an operator-declared type and `feature` / `change`** — prefer the operator-declared type when the body's domain signals match it cleanly. An operator who declared a `characters` type has declared that character work is coordinated under that type's playbook, not under `feature`'s. When the body genuinely fits both (a software-product request that names a UI character widget on a vault that ALSO has a `characters` content type), prefer the shipped type (`feature` / `change`) — operator-declared types are content domains, not software-feature aliases.
- **Pure clarification needed** — when the body has too little signal to classify, return `unknown`. Don't guess.

## Output

Return the classification as a single lowercase token from the resolved valid set. The sole caller is `spec.coordinator` during the review loop; it consumes the value in memory to drive candidate search and to surface the class to the operator inside its routing section. Neither the coordinator nor anything else writes the value directly to `request_class` from this skill's output — the apply gate (post-finalize) derives `request_class` from the routing section's content in the deterministic worker `apply_request.py`, not an LLM-dispatched agent.

## Verify

The classification SHOULD be reproducible: same body + same product config ⇒ same class. On boundary cases, prefer the more specific class. The caller treats `unknown` as a signal to ask the operator via `[!question]` callout rather than guess.

When the operator declares a new asset type mid-life-of-a-request, the classifier MAY return that new type on the next dispatch — that is by design, not a stability violation. The coordinator surfaces the change to the operator via its `# Routing` section.

## Failure modes

- **File path provided but file does not exist** — abort with a clear error naming the path. Do not fall back to the empty body.
- **Body has no readable content** (empty after frontmatter strip) — return `unknown`. The caller will treat this as "ask for content".
- **`lazy.settings.json` unreadable or missing** — fall back to the shipped asset types (`feature`, `change`, `bug`, `content`, `research`) plus the closed meta classes. Surface this as a `--verbose` log line (still emit the classification token; the caller decides whether to flag the config gap separately).

## Run logging

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/lazy-spec.request-classify/YYYY-MM-DD_HH-MM-SS.md` with the body excerpt (first 300 chars), the resolved valid set (closed meta + asset types from the dispatch), the chosen class, and one-sentence rationale.
