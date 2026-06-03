### 4.0.0 — 2026-05-16 UTC

- **Breaking:** the entire `bin/` was rewritten from scratch against a new functional spec. Direct importers of any old `bin/*.py` module name (`scaffold`, `cursor`, `iterate`, `webhook_server`, the old `parser`/`frontmatter` shapes) will break. Consumers driving the system through slash commands (`/lazy-review.start`, `/lazy-review.tick`, `/lazy-review.finalize`, `/lazy-review.stop`, `/lazy-review.status`) are unaffected — the verb surface is preserved.

- **Breaking:** the `review.classes[].experts` shape changed from a flat array with `role:` keys (`[{name: x, role: active_writer}, ...]`) to a dict keyed by writer group (`{main: [...], <section>: [...], history: [...], final: [...]}`). Re-run `/lazy-review.install` and `/lazy-review.configure` after upgrading to migrate the settings file shape.

- **Ownership isolation is now enforced in code, not in agent prompts.** A section writer that tries to mutate body content outside its owned H1 is silently restored to the operator's body by `reapply.py`; an agent overlay that tries to write `review_active` / `review_round` / `approved` is dropped by `payload.validate_frontmatter_overlay`. The protocol document (`references/lazy-review.doc-review-protocol.md`, now v2) only describes the wire shape; per-role mechanics live in the dispatcher.

- **Banner-tick invariant.** Every change to the top status banner is now its own mechanical tick — never bundled with an agent's content commit, never deferred to the "next tick anyway". This guarantees the operator sees "whose turn it is now" within ~5 seconds of any state change in the chain.

- **Frontmatter edits are surgical line-edits, not parse + render.** `frontmatter.set_field` and `frontmatter.unset_field` operate on raw text so block-style YAML values (`tags:\n  - foo`), inline arrays, and quoted strings survive byte-for-byte through dispatcher-side mutations.

- Eight slash commands ship the verb surface: `start`, `stop`, `finalize`, `status`, `iterate`, `install`, `audit`, `configure`. The first five are thin dispatchers over `bin/*.py` (single subprocess, atomic commit, clean working tree on exit); the last three drive the per-repo setup pipeline.

- 163 unit tests cover every primitive plus the ownership-isolation contract and the banner-tick invariant.

- Webhook server and standalone `lazy-review watch` polling mode are removed — `lazycortex-core`'s runtime daemon owns the polling loop and the git pull/push contract.

- **Migration steps:**
  1. `/plugin update lazycortex-review` to pull the new sources.
  2. `/lazy-review.install` — merges new defaults into `.claude/lazy.settings.json` without overwriting existing config.
  3. `/lazy-review.audit` — surfaces any FAIL findings from the schema change (e.g. classes still on the old flat-array `experts` shape).
  4. `/lazy-review.configure` — rebuild the affected `review.classes[]` entries against the new dict-keyed-by-writer-group shape.
  5. Optional: any in-flight reviewed docs from v3 keep working — `# History` entries persist, `review_active`/`review_round`/`approved` keys are honored. The first tick after the upgrade will repaint the banner under the new state-machine rules.

### 1.0.0 — 2026-05-03 UTC

- **Breaking:** The old Claude-agent dispatcher/process-file pair and the shell/MCP executor model are replaced by a pure-Python `lazy-review` CLI and an expert-runtime queue. Config moves from `.lazycortex-review.json` into `lazy.settings.json[lazycortex-review]`. Run `/lazy-review.install` after upgrading to migrate existing config automatically.

- `/lazy-review.install` bootstraps the full plugin on first run: registers 4 starter experts, wires the `lazy-review.tick` routine into `lazy-core.runtime.routines`, and migrates any legacy config to `lazy.settings.json` in one step.

- Eight user-facing skills cover the complete review lifecycle: `lazy-review.start`, `lazy-review.stop`, `lazy-review.status`, `lazy-review.finalize`, `lazy-review.audit`, `lazy-review.configure`, `lazy-review.iterate`, and the `/lazy-review.help` command.

- `lazy-review.configure` generates platform-specific service files (macOS launchd, Linux systemd) so the tick loop can run as an always-on background daemon without manual scripting.

- `lazy-review watch` runs the tick loop continuously with automatic `git pull`, suitable for long-lived daemon invocations; `lazy-review` (bare) runs a single tick for CI or hook use.

- Two plugin-shipped experts — `review_doctor` and `historian` — implement the doc-review protocol v1 and are registered automatically on install; additional experts can be added to `experts.settings.json`.

- `lazy-review.iterate` provides a local-LLM shortcut for quick iterative edits on a single file without triggering a full tick cycle.

- Git hooks (post-commit, post-merge, post-checkout) trigger review ticks automatically on every relevant repo event; a built-in loop guard prevents re-entrancy. An HTTP webhook server is also included for CI/CD-triggered ticks.

- The `lazy-review.markup` doc-markup convention and the `lazy-review.protocol` public protocol spec now ship with the plugin and are immediately available after install.

- Fixed: all plugin skills and agents were silently skipped by the Claude Code plugin loader because required frontmatter fields (`name`, `allowed-tools`) were missing. All 8 skills and 2 agents now load correctly.

- Fixed: `**` glob patterns in file-classification rules now correctly match files in nested subdirectories.
