---
since: 16.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-report-order, --check]}
writes:
  - "{spec_root}/**/code-report.md"
  - "{spec_root}/**/test-report.md"
---
## Why

A release's `code-report.md` and `test-report.md` hold one `#### build <k>` entry per run. An earlier version appended each new run's entry at the bottom, so the oldest run stood first. Now the entry of a new run goes first, right under the document's title, and the earlier entries stay below it unchanged. A report left in the old order mixes the two as soon as the next run lands: its newest entry sits on top and the older ones run oldest first below it. The `migrate-report-order` verb reverses the entries of every existing report once; in a report caught in that mixed shape it keeps the newest entry on top and turns the older ones below it. A report that is already newest first, holds one entry, or whose order cannot be told is left as it is and named with the reason. Every byte outside the entries stays, and the verb never commits.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-report-order --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-report-order --check --cwd "<repo-root>"` exits 1: no release's `code-report.md` or `test-report.md` still lists its build entries oldest first.
- A report the JSON answer of step 2 names under `skipped` with a reason other than `already newest first` is left as it was, for the operator to order by hand.
