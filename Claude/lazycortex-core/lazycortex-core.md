---
role: plugin-status
stage: major
plugin: lazycortex-core
current_version: 1.3.0
published_version: 0.6.4
generated_at: 2026-05-06 10:57:45 UTC
iconize_icon: LiFileClock
iconize_color: "#fca5a5"
---
# lazycortex-core — pending changes

**Status**: changed — `plugin.json` version `1.3.0` has not been published yet (last recorded release: `0.6.4`).

## Highlights since `0.6.4`

- Cleaner hook naming — the `agent-model-router` PreToolUse hook is now `model-router` — and a refreshed user-facing help layout: six functional blocks (install-and-audit, guardian, runtime, experts, agent-models, git-coordination) plus four end-to-end walkthroughs (make-repo-public, setup-runtime, setup-routine, setup-expert) replace the prior per-skill walkthrough tree.

## Commits since `0.6.4` (54)

- `77de0b7` chore(lazycortex-core): bump minor to 1.3.0 — lazy-core.git staging mutex
- `8075a0b` feat(lazycortex-core): /lazy-core.git-unlock skill (confirmed manual break)
- `550c57d` fix(lazycortex-core): /lazy-core.git-status SKILL.md — add Execution discipline preamble and Report section
- `ea16ec1` feat(lazycortex-core): /lazy-core.git-status skill (read-only inspect)
- `890aaa7` fix(lazycortex-core): re-apply lazy-core.git-guard hook registration
- `acd5a89` feat(lazycortex-core): add lazy-core.git rule (always-loaded staging mutex advisory)
- `4f51c1c` feat(lazycortex-core): register lazy-core.git-guard for git Pre/PostToolUse
- `e5ac56f` feat(lazycortex-core): git-guard event logging to .logs/claude/lazy-core.git-guard/
- `7d4c64a` feat(lazycortex-core): git-guard PostToolUse handler (release if index empty)
- `11b598b` feat(lazycortex-core): git-guard PreToolUse handler (acquire/refuse/diagnostic)
- `dc1dd38` feat(lazycortex-core): scaffold lazy-core.git-guard hook with stdin/gate/dispatch
- `0f1142f` feat(lazycortex-core): release_if_index_empty + load_config (lazy-core.git section)
- `61eefca` feat(lazycortex-core): acquire() with reentry, jittered wait, break, refuse
- `0cc41f2` feat(lazycortex-core): break-the-lock heuristics (dead pid / host / stale-idle)
- `90f58d7` feat(lazycortex-core): inspect() + git-state helpers (branch, index mtime, empty)
- `a7e71d4` feat(lazycortex-core): atomic lock file IO with tolerant read
- `f17bf6b` feat(lazycortex-core): staging_lock.resolve_session_id with ancestor-PID fallback
- `c5cb5b8` feat(lazycortex-core): scaffold staging_lock helper module
- `c8e2b0d` docs: refresh READMEs + marketplace via pub.sync-readmes
- `89f673f` feat(lazycortex-observe): scaffold new public plugin (Task D1)
- `c881a10` fix(lazycortex-core): add retention to runtime log directory
- `53af734` feat(lazycortex-core): capture token usage from claude -p in expert pump
- `8d7cd6f` docs(lazycortex-core): document runtime metrics + bump 1.2.0 (minor)
- `afbf4a0` feat(lazycortex-core): wire metrics into runtime daemon (opt-in)
- `b4f82b8` feat(lazycortex-core): add stdlib-only runtime metrics primitive
- `243d227` docs(specs): add lazy-core.git staging-window mutex spec
- `a682b36` feat(lazycortex-core): scaffold + writing rule for protocol/schema/contract references
- `adff099` chore(lazycortex-core): bump major to 1.0.0 — routine types + working-tree protection
- `5c0a94c` docs(lazycortex-core): document routine types + state + halt + contract
- `79f99d6` feat(lazycortex-core): add lazy-runtime.recover skill + recover.py
- `d34fac6` feat(lazycortex-core): type-aware lazy-routine.register wizard
- `823a727` feat(lazycortex-core): inject expert runtime contract into every expert run
- `5fa52ef` feat(hook-writing): codify § 5 no-foreign-staged + Fix 1 + scaffold
- `2a348c8` feat(lazycortex-core): add expert runtime contract template
- `06aa0d2` feat(lazycortex-core): per-job halt detection in expert_pump
- `95c4bc8` feat(lazycortex-core): daemon-wide halt on uncommitted working tree
- `eb21907` feat(lazycortex-core): git routine type (watch new_commits|new_files|...)
- `1db4223` feat(lazycortex-core): schedule routine type with stdlib cron parser
- `e196363` feat(lazycortex-core): inbox routine type
- `37211a3` feat(lazycortex-core): persist last_run + introduce dispatcher
- `4780b53` feat(lazycortex-core): introduce routine type taxonomy + validator
- `4e8490a` feat(lazycortex-core): add runtime_state module (atomic state.json)
- `b9c629c` refactor(pub.help): redesign help-doc model — blocks + walkthroughs + per-plugin lifecycle
- `3b1ccb1` feat(lazy-core.audit): Agent B — dirty-tree write-without-commit heuristic
- `bc6f2d6` chore(lazycortex-core): bump 0.7.0 — new hook-writing rule
- `1f39b0c` feat(lazy-core.hook-writing): new authoring rule for Claude Code lifecycle hooks
- `bd60ea4` feat(lazy-core.agent-writing): cross-reference skill-writing § 6 (no dirty tree)
- `f7f6745` feat(lazy-core.skill-writing): § 6 no dirty working tree + renumber
- `ecaa0a3` fix(pub.status): drop blank line in render_note — flap zone with iconize-sync rewriter
- `38101c5` docs(lazycortex-review): 1.0.0 release docs — README/CHANGELOG/marketplace
- `dd75363` feat(lazycortex-review,lazycortex-core): register lazycortex-review settings section v1 + legacy-config migrator
- `dcac5c7` feat(lazycortex-review): plugin-shipped review_doctor + historian experts for doc-review protocol
- `cc4561f` fix(lazycortex-core): decouple lazy-core.install runtime steps from plugin scope
- `5b54252` docs(lazycortex-core): regenerate help docs + CHANGELOG 0.6.4 + README sync

---
*Generated by `pub.status`. Do not hand-edit — re-run the agent to refresh.*
