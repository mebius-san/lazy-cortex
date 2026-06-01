---
description: Show lazycortex-observe purpose and a one-line summary of each skill it ships
execution-discipline-waiver: "help command — static text, no multi-step logic"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-observe** — ship lazycortex-core runtime metrics to a Prometheus-compatible observer (Grafana Alloy or OpenTelemetry Collector) — vendor-neutral, observer-server-blind, headless-portable.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-observe.audit` — audit the lazycortex-observe plugin: verify any rule files still encode their invariants and cross-check artifact conventions. Read-first; presents findings, asks before fixing. Severity: PASS / WARN / FAIL.
- `lazy-observe.doctor` — read-only health check for the lazycortex-observe shipper on this host. Verifies service status, agent process, local /metrics endpoint, agent's own remote_write success counter, observer URL reachability, and WAL bounds. Reports each as PASS / WARN / FAIL with a one-line fix suggestion. Never mutates filesystem or service state.
- `lazy-observe.install` — bootstrap the lazycortex-observe shipper for this host: pick agent kind (Alloy / otelcol), collect remote_write URL + auth, render the agent config + service unit from shipped templates, install + load the supervised service, smoke-test the local /metrics endpoint. Operator-private values stay in `${XDG_CONFIG_HOME:-~/.config}/lazycortex/`. Idempotent — re-running rewrites the rendered configs and reloads the service.
- `lazy-observe.uninstall` — tear down the lazycortex-observe shipper on this host: unload the launchd agent or systemd user unit, remove rendered configs and the WAL dir. Operator-private state under `${XDG_CONFIG_HOME:-~/.config}/lazycortex/` is preserved by default — re-installing later picks it up. Idempotent — re-running on an already-clean host is a no-op.

No agents. No other commands.

<!-- help-block:start -->
**Documentation:**

- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-observe/help/install-and-audit.md) — Install, verify health, and tear down the lazycortex-observe metrics shipper on any host.
- [ship-metrics-end-to-end](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-observe/help/walkthroughs/ship-metrics-end-to-end.md) — From a clean checkout to your first dashboard panel — bring up the runtime daemon, install the shipper, produce traffic, verify the pipeline.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-observe/help/troubleshooting.md) — Common failure modes across lazycortex-observe install, uninstall, and doctor — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-observe/help/faq.md) — Common operator questions about installing, running, and maintaining the lazycortex-observe metrics shipper.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-observe/help/`.
<!-- help-block:end -->

See `README.md` in the plugin for full scenarios and requirements.
