### 3.0.0 — 2026-05-12 UTC

- **`lazycortex-log` absorbed.** The retired `lazycortex-log` plugin has been folded into `lazycortex-core` as a single-cut release. All `lazy-log.*` agents (`bullets`, `distill`, `recall`, `summary`, `timeline`), the `lazy-log.clean` skill, the `lazy-log.logging` rule, and the commit-recorder hook now ship from core; namespaces are unchanged. `lazy-log.audit` and `lazy-log.install` were absorbed into `lazy-core.audit` and `lazy-core.install` respectively.

- **`/lazy-core.setup` migrates stale hook registrations.** Re-running setup strips `${CLAUDE_PLUGIN_ROOT}/lazycortex-log/hooks/*` entries from `settings.json` and registers core's new commit-recorder. Idempotent.

- **Consumer migration.** After `/plugin update`: run `/lazy-core.setup`, then restart any active sessions — Claude Code holds hook paths in memory, and existing sessions will error on commits until restarted. New sessions pick up the consolidated hook cleanly.

- **`.logs/` bootstrap.** `lazy-core.install` now creates `.logs/` and adds the `.gitignore` entry unconditionally (previously this was `lazy-log.install`'s job).

- **`lazy-core.audit` gains a logging compliance phase.** Inline Phase 1 (sub-checks L1–L4): logging rule installed, `.logs/` exists, `.gitignore` covers `.logs/`, logging-waiver values valid. Absorbed from the retired `lazy-log.audit` skill.
