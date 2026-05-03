---
role: plugin-status
stage: minor
plugin: lazycortex-core
current_version: 0.6.4
published_version: 0.3.0
generated_at: 2026-05-03 16:29:09 UTC
iconize_icon: LiFileClock
iconize_color: "#fde68a"
---

# lazycortex-core — pending changes

**Status**: changed — `plugin.json` version `0.6.4` has not been published yet (last recorded release: `0.3.0`).

## Commits since `0.3.0` (56)

- `4736e0f` docs(lazycortex-core): add 5 expert-runtime walkthroughs + 2 new scenarios
- `87a0fd5` refactor(lazycortex-core): move runtime shim to .claude/bin/lazy.runtime.sh
- `ac5a41c` fix(lazycortex-core): runtime daemon stabilization + .experts/ FS layout
- `7bcf21e` refactor(pub.status): convert from skill to agent
- `9a71ab0` fix(lazycortex-core): drop stale SKILL.md leftovers from incomplete expert→lazy-expert rename
- `0e0a654` refactor(lazycortex-core)!: rename loop→runtime everywhere (loop_daemon.py, templates/loop/, plist, service, CLI subcommand, prose)
- `858bf76` refactor(lazycortex-core): rename lazy-core.loop → lazy-core.runtime + lazy-core.routine-* → lazy-routine.*
- `b8f041a` refactor(lazycortex-core): rename lazy-core.expert* skills and routine to lazy-expert.* namespace
- `fcc515f` docs(specs): brainstorm expert runtime + review architecture redesign
- `5a0c5a3` chore(lazycortex-core): sync READMEs and marketplace.json after expert runtime addition
- `59afe3f` fix(lazycortex-core): restore A3+A4 fix-ups silently reverted by C2 commit
- `7a72d1f` chore(lazycortex-core): sync READMEs and marketplace.json after expert runtime addition
- `db4ca7a` docs(lazycortex-core): add expert runtime + loop daemon to overview and README
- `09d1aaa` feat(lazycortex-core): bump minor version for expert runtime + loop daemon
- `69e9f7d` feat(lazycortex-core): add loop runtime fix offers to lazy-core.doctor
- `a7442ec` feat(lazycortex-core): extend lazy-core.audit with expert + loop runtime checks
- `982945b` feat(lazycortex-core): extend lazy-core.install with loop bootstrap, expert wizard, and supervisor offer
- `519e4e7` feat(lazycortex-core): add lazy-core.routine-unregister skill
- `0dafbaf` feat(lazycortex-core): add lazy-core.routine-register skill
- `dd158e7` feat(lazycortex-core): add lazy-core.expert-cancel-job skill
- `c6c89e1` feat(lazycortex-core): add lazy-core.expert-list-jobs skill
- `5991248` feat(lazycortex-core): add lazy-core.expert-collect-job skill
- `f2a5b6a` feat(lazycortex-core): add lazy-core.expert-dispatch-job skill
- `a59cc9f` docs(lazycortex-core): add lazy-core.settings-v2 architecture reference
- `7220087` docs(lazycortex-core): add lazy-core.loop-runtime architecture reference
- `eb0972c` docs(lazycortex-core): add expert-protocols-contract reference
- `d7d9eae` fix(lazycortex-core): correct resolve_routine_command cache layout (registry/plugin/version/bin)
- `89e0f22` test(lazycortex-core): e2e loop daemon integration test
- `50e61cf` feat(lazycortex-core): bootstrap default expert-pump routine in loop registry
- `22e52c3` feat(lazycortex-core): add CLI dispatcher with expert-pump-once and loop subcommands
- `3975074` feat(lazycortex-core): implement expert-pump-once with retry policy and cleanup
- `4850148` fix(lazycortex-core): correct reference_resolver cache layout (registry/plugin/version/category)
- `0d8d9fe` feat(lazycortex-core): add reference_resolver for agent/protocol references
- `0575441` feat(lazycortex-core): add expert_runtime helpers (dispatch/collect/list/cancel/register_routine)
- `902b52a` feat(lazycortex-core): add launchd plist and systemd unit templates for loop daemon
- `7049d24` feat(lazycortex-core): structured per-routine logs under .logs/lazy-core/loop/
- `40b2d94` docs(lazycortex-core): clarify retry boundary lives in routine implementations, not loop daemon
- `174c1c3` test(lazycortex-core): cover routine timeout enforcement; add daemon -B intent comment + git stderr passthrough
- `0cdfd70` feat(lazycortex-core): add daemon.git checkout/pull/push at iteration boundaries
- `b011709` feat(lazycortex-core): resolve routine commands via plugin cache and run via subprocess
- `5cecabf` feat(lazycortex-core): scaffold loop_daemon.py with serial scheduling primitives
- `5b4cc2a` fix(lazycortex-core): correct lazy-core.doctor root-version check ordering (raw Read before load_section)
- `c410e2d` refactor(lazycortex-core): route lazy-core.doctor through lazy_settings helper
- `0ba7b00` refactor(lazycortex-core): route lazy-core.audit through lazy_settings helper
- `15766cc` fix(lazycortex-core): correct lazy-core.agent-models prose to use ${CLAUDE_PLUGIN_ROOT}, drop stale sub-section
- `7e0c3eb` refactor(lazycortex-core): route lazy-core.agent-models through lazy_settings helper
- `36b7365` fix(lazycortex-core): make load_section write-only-on-migration; add hook diagnostic for malformed settings
- `db6b087` refactor(lazycortex-core): route agent-model-router through lazy_settings helper
- `e3dc60a` feat(lazycortex-core): scaffold migration ladder for agent_models and lazy-core.loop
- `bde3ba0` feat(lazycortex-core): add lazy_settings helper with per-section _version migration ladder
- `9b508b6` docs(lazycortex-core): add 4 walkthroughs + faq, expand troubleshooting, regen help-block
- `d211a6b` docs(lazycortex-core): regen help/ trial diagrams via /lazy-diagram.draw
- `0b41f27` fix(lazycortex-diagram): use diagramPadding:5 for sequence/timeline, not diagramMarginX/Y
- `934c827` fix(lazycortex-diagram): populate sequence themeVariables in scheme, regenerate walkthrough diagram
- `b6dc0ab` fix(lazycortex-diagram): add semicolon forbidden pattern, fix pub.help-writer dispatch
- `9c7110a` refactor(lazycortex-diagram): three-layer separation — rule/template/scheme with <<init>> sentinel

---
*Generated by `pub.status`. Do not hand-edit — re-run the agent to refresh.*
