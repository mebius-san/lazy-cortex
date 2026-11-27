---
since: 3.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-experts, unbranch-tester, --check]}
writes:
  - ".claude/lazy.settings.json"
  - ".claude/lazy.settings.local.json"
---
## Why

The tester now checks the deployed product and returns only its report through `result/`: it writes nothing into the product's repository and commits nothing, so it needs neither a job branch nor commit rights. An older install seeded its entry in `lazy.settings.json[experts]` with `workspace: "branch"` and `can_commit_in_repo: true`, and a tester job on that entry fails the runtime's branch rule, because it never commits to the branch it is given.

The `unbranch-tester` verb removes `workspace` and `can_commit_in_repo` from every expert whose `agent` is `lazycortex-experts:lazy-experts.tester`, in the tracked settings and in the gitignored local overlay `.claude/lazy.settings.local.json`. Each file is read and written alone, an overlay that does not exist is never created, every other key and the key order stay as they are, and an expert the operator pointed at another agent is left alone.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<experts-cli>` is `bin/lazycortex-experts` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-experts --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <experts-cli> unbranch-tester --core-cli "<core-cli>" --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <experts-cli> unbranch-tester --check --cwd "<repo-root>"` exits 1: no expert naming `lazycortex-experts:lazy-experts.tester` as its agent carries `workspace` or `can_commit_in_repo` in `.claude/lazy.settings.json` or `.claude/lazy.settings.local.json`.
- The JSON answer of step 2 lists the removed `<expert key>/<key>` pairs of the tracked file in `tester_unbranched` and of the overlay in `local_tester_unbranched`.
