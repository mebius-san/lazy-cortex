---
since: 15.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-journals, --check]}
writes:
  - "{spec_root}/**/*.md"
---
## Why

A release build or test job writes the release's `code-report.md` or `test-report.md` from scratch on its first run, and an earlier version landed that text as it came. A journal landed that way carries none of the keys every spec document carries: no `spec_role`, no `spec_doc_type`, no product tag, no `wiki_pinned_topics`, no `iconize_icon`. With those keys missing, the type's icon never matches, a journal parked for the operator shows no icon at all, and the tag and topic views leave the journal out. The collector now gives a landing journal the frontmatter a fresh seed of it carries. The `migrate-journals` verb does the same for every journal already on disk. It keeps every key the journal already has, review keys included, and leaves the body untouched.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-journals --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-journals --check --cwd "<repo-root>"` exits 1: no `code-report.md` or `test-report.md` in a release folder still lacks `spec_role` in its frontmatter.
