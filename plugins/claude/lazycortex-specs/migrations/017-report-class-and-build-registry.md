---
since: 16.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-report-class, --check]}
writes:
  - ".claude/lazy.settings.json"
  - ".claude/lazy.settings.local.json"
---
## Why

A build report `code-report.md` is now a report review: the operator discusses it with the implementer and then accepts the build, sends it back for rework or sends it to a new plan. The review plugin runs that flow only for a class that carries `report: true`. The implementer discusses the report under the build's own protocol, `lazycortex-specs:lazy-spec.build-job`. It reads the build's branch from the context file `build-branch.json`, which `context_from_verbs` computes with `build-registry get` on the report. Install seeds these three keys on a new `code-report` class only. A consumer whose settings already hold the class keeps it without them, so its build reports are reviewed as ordinary documents with no verdict and no branch. The same holds for a `code-report` class kept in the gitignored local overlay `.claude/lazy.settings.local.json`. The step migrates each file alone and never creates an overlay that does not exist. Every build also goes through the per-release build registry `.state/lazy-spec.builds.<product-key>.<release>.json` now. A release that built before the registry existed has none, so a plain `build-registry get` refuses its report. The step does not create that registry: the build branches live only in the daemon's own checkout, since the daemon pushes only the base branch, so a registry backfilled in another checkout would record every past build as accepted and deleted. The registry is created lazily in the daemon's checkout instead: the spec coordinator runs `build-registry backfill` on the "no registry" refusal and repeats the call, and the review's own read is `build-registry get --backfill`, which does the same by itself. A `build-branch.json` entry an earlier run of this step wrote with the plain `get` command gains the flag; an entry with any other command is the operator's and stays as it is. The old per-test branches `spec/*/releases/*/test-*` are no longer used, and the tester never creates or commits anything, so none of them holds work anyone needs. The step therefore deletes every one of them, merged or not. Every other branch stays: the build branches `build-<k>` belong to `build-registry prune`. A per-test branch that is checked out in any worktree is never deleted: the verb then exits 2 before writing anything, names the branch and the worktree, and the step is run again once that worktree holds another branch or is removed.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-report-class --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-report-class --check --cwd "<repo-root>"` exits 1. No local branch named `spec/<product>/releases/<release>/test-<k>` is left. The check also covers `.claude/lazy.settings.json` and, when it exists, `.claude/lazy.settings.local.json`. In each, the shared `code-report` class and every product-scoped `code-report@<key>` class carry a `report` key. Their `protocols` include `lazycortex-specs:lazy-spec.build-job` unless the operator set `protocols` to something that is not a list. Their `context_from_verbs` holds a `build-branch.json` entry unless the operator set it to something that is not a list, and that entry no longer carries the plain `build-registry get {doc}` command without `--backfill`. A missing local overlay is never created.
- A value the operator already set is left as written, and so are every other key, the key order and a class the operator renamed.
- The step writes no build registry under `.state/`; the spec coordinator, or the review's `build-registry get --backfill` read, creates the registry of a release that built before it existed, in the daemon's checkout, the first time a `build-registry` call refuses that release for want of one.
- The JSON answer of step 2 names the changed classes in `classes_updated` and the deleted per-test branches in `deleted_test_branches`. Every other branch, the build branches included, is still in git.
