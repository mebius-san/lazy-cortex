## Why this plugin

The lazycortex-core daemon emits a rich set of Prometheus-format metrics — routine throughput, tick duration histograms, error rates by reason, queue depth by expert, daemon halt status, and Anthropic API token usage — but only on a loopback `/metrics` endpoint. `lazycortex-observe` ships those metrics to a self-hosted Prometheus-compatible observer (Grafana Cloud / Mimir, self-hosted Prometheus, VictoriaMetrics, anything that accepts Prometheus `remote_write`) so an operator running multiple repos across multiple machines can chart and alert on runtime health from a single place.

The plugin is **observer-server-blind**: every shipped file (templates, dashboard, alert rules) is a generic skeleton with placeholders. Operator-private values — observer URL, bearer / basic-auth credentials, optional repo-label override — live exclusively under `${XDG_CONFIG_HOME:-~/.config}/lazycortex/`. Nothing identifies the operator's stack in the plugin tree.

## Who it's for

- Operators running lazycortex-core daemons on developer laptops, headless Linux servers, or in containers — anyone who wants visibility into daemon health and Anthropic spend without writing scrape glue from scratch.
- Vendor-neutral: works with Grafana Alloy (recommended for Grafana-stack users) or the OpenTelemetry Collector (recommended for everyone else). Operator picks at install time.

## Blocks

- **install-and-audit** — Bootstrap, verify, repair, and tear down the metrics shipper on this host. Members: lazy-observe.install, lazy-observe.uninstall, lazy-observe.doctor, lazy-observe.audit.

## Walkthroughs

- **ship-metrics-end-to-end** — Ship your first runtime metric to a self-hosted Prometheus stack. From a clean checkout to charts in your observer — bring up the runtime daemon, enable the metrics endpoint in `lazy.settings.json`, install the shipper, dispatch a first expert job to produce traffic, verify the pipeline. Path: lazy-core.install → /lazy-expert.dispatch-job → /lazy-observe.install → /lazy-observe.doctor.

## Requirements

- **Claude Code** with plugin support.
- **lazycortex-core ≥ 1.2.0** with `lazy-core.runtime.metrics.enabled: true` in `lazy.settings.json` — see `claude/lazycortex-core/references/lazy-core.runtime-schema.md § 12` for the full settings reference.
- **One of**: `grafana-alloy` or `otelcol-contrib` on PATH (operator installs via `brew` / distro package — install skill prints the right command if missing).
- **A Prometheus-compatible `remote_write` endpoint** the operator already runs — this plugin does not stand up the observer side.

## Quick start

1. Enable metrics in lazycortex-core: add `"metrics": {"enabled": true}` to the `lazy-core.runtime` block in `.claude/lazy.settings.json`, then restart the daemon supervisor.
2. Verify locally: `curl -fsS http://127.0.0.1:9464/metrics | head` should show `lazycortex_runtime_*` series.
3. Run `/lazy-observe.install` — answer the wizard prompts (agent kind, remote_write URL, auth kind, token).
4. Import `claude/lazycortex-observe/dashboards/lazycortex-runtime.json` into Grafana (or your observer's equivalent).
5. Add `claude/lazycortex-observe/alerts/lazycortex-runtime.rules.yml` to your Prometheus rule_files glob.
6. `/lazy-observe.doctor` to verify the pipeline is healthy.

## Scenarios

<!-- Legacy marketing-summary section. Read by humans browsing the README; NOT read by pub.help-draft (Principle 5 says ## Blocks is the source of truth). -->

- *"Ship runtime metrics from a developer laptop to a self-hosted Prometheus + Grafana"* — `/lazy-observe.install` walks through agent kind (Alloy vs otelcol), remote_write URL, bearer token storage, then renders the agent config + a launchd plist, loads the service, and smoke-tests the pipeline end-to-end.
- *"Run on a headless Linux server (systemd) with no GUI"* — same install skill detects the platform automatically and installs a systemd user unit with `ProtectSystem=strict` + `ProtectHome=read-only` hardening. Token sourced from a 0600 file or `LAZYCORTEX_OBSERVE_TOKEN` env var — no Keychain or GUI dependency.
- *"Recover after the observer endpoint was offline overnight"* — the agent's WAL (12h max-age default for Alloy) buffers samples while the observer is down; once it's back, samples drain automatically. `/lazy-observe.doctor` reports `WARN oversized` if WAL grew unusually large during the outage.
- *"Run in a container that injects `LAZYCORTEX_OBSERVE_TOKEN` from a secret manager"* — install accepts `auth_kind=bearer-env`, in which case the agent reads the token from its environment at process start. Token never lands on disk in the container; secret manager handles rotation.
- *"Switch from Alloy to otelcol without losing metric continuity"* — re-run `/lazy-observe.install` and pick the new agent. The skill rewrites the rendered config and reloads the service. The two agents emit identical metric series shape, so dashboards and alerts continue working unchanged.
