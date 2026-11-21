---
since: 2.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-experts, rename-implementer-agent, --check]}
writes:
  - ".claude/lazy.settings.json"
  - ".claude/lazy.settings.local.json"
---
## Why

The agent `lazycortex-experts:lazy-experts.implementer` is now `lazycortex-experts:lazy-experts.developer`, so the agent's name matches the role `developer` it registers under. An expert in `lazy.settings.json[experts]` whose `agent` still names the old agent dispatches to nothing, and an `agent_models` tier keyed by the old dispatch string no longer applies to any agent. The word "implementer" keeps its meaning of the release-build position: `release.implementer` and `release.implementer_chain` of a product are not renamed.

The `rename-implementer-agent` verb rewrites every `experts.<key>.agent` value that is exactly the old agent to the new one, and moves each `agent_models` tier keyed by the old dispatch string to the new key with its value as it is. When a group already carries the new key, that value stays and only the old key is removed. An agent the operator already pointed elsewhere, and every other key and value, are left alone. The verb applies the same rename to the gitignored local overlay `.claude/lazy.settings.local.json`, where an operator may keep `experts` and `agent_models` entries of their own: each file is read and written alone, never as the merged view, and an overlay that does not exist is never created. The user-scope file `~/.claude/lazy.settings.json` is migrated the same way: its `agent_models` tiers apply to every repository of the machine, and an old key there stops applying just as silently. It sits outside the repository, so it is not among `writes` and the migration's commit never carries it; it is written through the core `settings-set --home`, and a home directory without the file gets none.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<experts-cli>` is `bin/lazycortex-experts` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated. Step 2 migrates the repository's two settings files and the user-scope `~/.claude/lazy.settings.json` of the user who runs it.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-experts --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <experts-cli> rename-implementer-agent --core-cli "<core-cli>" --cwd "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <experts-cli> rename-implementer-agent --check --cwd "<repo-root>"` exits 1: in none of `.claude/lazy.settings.json`, `.claude/lazy.settings.local.json` and `~/.claude/lazy.settings.json` does an expert name `lazycortex-experts:lazy-experts.implementer` as its agent, or an `agent_models` group carry that dispatch string as a key.
- The JSON answer of step 2 lists the tracked file's changes in `experts_renamed`, `tiers_renamed` and `tiers_dropped`, the local overlay's in `local_experts_renamed`, `local_tiers_renamed` and `local_tiers_dropped`, and the user-scope file's in `home_experts_renamed`, `home_tiers_renamed` and `home_tiers_dropped`.
