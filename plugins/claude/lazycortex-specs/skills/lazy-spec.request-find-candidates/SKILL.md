---
name: lazy-spec.request-find-candidates
description: "Dispatched by the `spec.coordinator` agent, after `lazy-spec.request-classify` has settled the class, to find the existing features / changes / bugs a request could attach to; not for direct use. Read-only — returns a ranked list with rationale that the coordinator turns into its attach-vs-spawn decision."
execution-discipline-waiver: "Single-purpose primitive — read-only search; no multi-phase orchestration."
---
# Find candidate entities for a request

Given a request body and inferred `request_class`, search the vault for existing entities that are plausible attach targets. Used by `spec.coordinator` when deciding clear-path attach vs spawn vs ambiguous-path multi-select routing.

The class taxonomy + per-class allowed attach targets live in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.request-protocol.md` → "Class taxonomy". This skill never restates them.

## Input

- **`body`** — request body text (after frontmatter stripped)
- **`request_class`** — one of `feature` | `change` | `bug` | `task` | `spec` | `plan` | `feedback`. The `unknown` class is rejected — caller should clarify class first.
- **`product`** (optional) — product compound-key (e.g. `dashboards`) when extractable from body. When absent, search all products.

## Search scope (filtered by class)

Per the class → routing table in `lazy-spec.request-protocol.md`:

| Class | Search globs (relative to vault root) |
|---|---|
| `feature` | `<product>/<slug>/<slug>.md` (a feature lives at the product root by default) |
| `change` | `<product>/changes/<slug>/<slug>.md` |
| `bug` | `<product>/bugs/<slug>/<slug>.md` |
| `task` | `<product>/<slug>/<slug>.md`, `<product>/{changes,bugs}/<slug>/<slug>.md` |
| `spec` | `<product>/<slug>/<slug>.md` |
| `plan` | `<product>/<slug>/<slug>.md`, `<product>/changes/<slug>/<slug>.md` |
| `feedback` | `<product>/<slug>/<slug>.md`, `<product>/{changes,bugs}/<slug>/<slug>.md` |

The folder-note filename matches its parent folder basename (per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.file-roles-protocol.md` — `csv-export/csv-export.md`, not `csv-export/folder-note.md`). To enumerate candidates, walk each `<product>/<kind>/` directory for a category with its own folder (`changes/`, `bugs/`); for a feature, walk `<product>/` itself — any subdirectory that is not one of the product's declared group folders is a candidate. For each subdir `<slug>/`, the folder-note is the file `<slug>/<slug>.md` if present — **keep only notes whose `spec_role` is `status`**: the root glob's shape (`<slug>/<slug>.md`) also matches a nested product's own level note (`spec_role: product`), which is never a candidate.

If `product` is None, expand `<product>` to `*` (across-product search). The vault layout is `<vault-root>/<product>/<slug>/<slug>.md` for a feature at the product root, or `<vault-root>/<product>/{changes,bugs}/<slug>/<slug>.md` for a change or bug, per the canonical convention.

## Ranking

For each candidate folder-note, compute a similarity score:

1. **Term overlap** — set intersection of word stems between request body and the candidate's primary doc body (`design.md` for feature/change folders; `bug.md` for bug folders). Stems are lowercased, stopword-filtered, length ≥ 3 chars. Score is the Jaccard overlap (|A ∩ B| / |A ∪ B|), normalised 0..1.

2. **Title overlap** — words in the request title (H1 if present, else first non-empty body line) vs candidate folder name + primary doc H1. Same Jaccard normalisation.

3. **Existing source-request signal** — if the candidate's folder-note already lists a similar request in its `## Source requests` block (term overlap with the new request body ≥ 0.4), that's a strong "this is a continuation" signal. Boolean → 1.0 or 0.0.

Compose: `score = 0.5 * term_overlap + 0.4 * title_overlap + 0.1 * source_request_signal`.

## Output

Top-5 candidates as a JSON list, sorted by score descending. Empty list when no matches above the cutoff threshold (`score >= 0.3`):

```json
[
  {
    "folder_note_path": "products/dashboards/csv-export/csv-export.md",
    "wikilink": "[[products/dashboards/csv-export/csv-export|dashboards feature: csv-export]]",
    "score": 0.72,
    "rationale": "70% term overlap; design.md mentions CSV export and date filters"
  }
]
```

Rationale string is one sentence, names the strongest signal.

## Caller decision rules

The caller (`spec.coordinator`) interprets the output:

- **Top score ≥ 0.7 with significant gap (≥ 0.2) to the second** ⇒ clear attach (single obvious target).
- **Multiple candidates ≥ 0.5** ⇒ ambiguous — write multi-select `# Routing` checkboxes.
- **No candidates ≥ 0.3 AND class allows spawn** ⇒ spawn new entity.
- **No candidates ≥ 0.3 AND class is attach-only** (`task` / `plan` / `feedback`) ⇒ ask via `[!question]` to disambiguate or reject.

These thresholds are heuristics; the caller may adjust per its own prompt logic. This skill returns the ranked list and lets the caller decide.

## Failure modes

- **Class is `unknown`** — refuse with a clear message: `unknown` class means classify-first is incomplete; caller must classify before searching candidates.
- **Product specified but not registered** — resolve the product via `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" resolve-product by-key <product>` (reads `lazy.settings.json[products]`). A null `record` means the product is not registered → refuse with the list of configured products from the `products` section.
