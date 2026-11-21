---
since: 14.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-specs, migrate-playbook-names, --check]}
writes:
  - ".claude/lazy.settings.json"
  - ".claude/lazy.settings.local.json"
---
## Why

The shipped playbooks are now named by what kind of file they are. The six asset-type playbooks end in `-type` (`lazy-spec.feature-playbook` became `lazy-spec.feature-type`, likewise `change`, `bug`, `content`, `research` and `release`), and the three job playbooks end in `-job` (`lazy-spec.tool-code-playbook` became `lazy-spec.build-job`, `lazy-spec.tool-test-playbook` became `lazy-spec.test-job`, `lazy-spec.tool-research-playbook` became `lazy-spec.research-job`). A consumer's settings may still name an old key: an asset type the operator declared with a shipped playbook, or the `protocols` of a review class. An old key no longer resolves, so the coordinator of such a type loads no playbook and a job dispatched with such a protocol runs without it. The step renames the old keys in the gitignored local overlay `.claude/lazy.settings.local.json` as well, reading and writing each file alone, never as the merged view, and never creating an overlay that does not exist.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<specs-cli>` is `bin/lazycortex-specs` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-playbook-names --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> migrate-playbook-names --check --cwd "<repo-root>"` exits 1: no value in `.claude/lazy.settings.json` or `.claude/lazy.settings.local.json` is one of the nine old `lazycortex-specs:lazy-spec.<old>` keys; every other value, and the order of keys and lists, is left as written.
- The JSON answer of step 2 reports the tracked file in `action` and `renamed`, and the local overlay in `local_action` and `local_renamed`.
