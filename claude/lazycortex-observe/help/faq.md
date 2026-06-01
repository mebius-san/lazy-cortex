---
chapter_type: faq
summary: Common operator questions about installing, running, and maintaining the lazycortex-observe metrics shipper.
last_regen: 2026-06-01
no_diagram: true
source_skills:
  - lazy-observe.install
  - lazy-observe.uninstall
  - lazy-observe.doctor
  - lazy-observe.audit
---
# Frequently asked questions

## What do I need before running the installer?

Three things must be in place. First, `lazycortex-core` version 1.2.0 or later must be running with `metrics.enabled: true` in the `lazy-core.runtime` block of your `lazy.settings.json` — the installer will check `http://127.0.0.1:9464/metrics` and abort if that endpoint isn't up. Second, either `grafana-alloy` or `otelcol-contrib` must be on your PATH; if it isn't, the installer prints the right install command for your platform and stops so you can install it yourself. Third, you need a Prometheus-compatible `remote_write` URL pointing at an observer you already run (Grafana Cloud, self-hosted Mimir, VictoriaMetrics, etc.) — the plugin does not stand up the observer side.

---

## Which agent should I pick — Alloy or otelcol?

Pick **Grafana Alloy** if you're already on the Grafana / Mimir stack. Pick **OpenTelemetry Collector** (`otelcol`) for everything else. Both agents scrape the same loopback endpoint and emit identical metric series shapes, so dashboards and alert rules work unchanged with either. You can switch later without losing continuity — re-run `/lazy-observe.install` and choose the other agent; the skill rewrites the rendered config and reloads the service.

---

## How do I rotate the bearer token?

Run `/lazy-observe.install` and when the wizard reaches the auth step, choose the same auth kind you used originally, then supply the new token. If you selected `file` storage, the skill overwrites the 0600 token file and reloads the service. If you selected `env` storage, update the environment variable in your shell profile or secret manager — the agent picks it up on its next restart. The token is never written into `observe.toml` or any tracked file; it lives only in the token file or your environment.

---

## The installer says `core-metrics-disabled` even though I set `metrics.enabled: true`. What's wrong?

The lazycortex-core daemon reads settings at startup. Setting `metrics.enabled: true` has no effect until you restart the daemon supervisor. On macOS, run `launchctl kickstart -k gui/$UID com.lazycortex.runtime`; on Linux, run `systemctl --user restart lazycortex-runtime.service`. Once the daemon is back, re-run the installer and Step 2 should clear.

---

## My observer was offline overnight. Will I lose those metrics?

No, as long as the agent's WAL (write-ahead log) is within its configured max-age (12 hours by default). The agent buffers unsent samples in the WAL directory at `~/.local/share/lazycortex/observe/wal/`. Once the observer is back online, the agent drains the WAL automatically — no intervention needed. Run `/lazy-observe.doctor` afterwards; if it reports `WARN oversized` on the WAL step, that's informational — it means the backlog was large but the drain is already under way. Do not delete the WAL directory manually unless you are willing to discard those samples.

---

## Can I run the shipper in a container without writing the token to disk?

Yes. When the installer asks for auth kind and token source, choose `env`. The agent will read the token from the `LAZYCORTEX_OBSERVE_TOKEN` environment variable at process start. Inject that variable from your container's secret manager (Kubernetes Secrets, Docker secrets, AWS Secrets Manager, etc.) — the token never lands on disk inside the container image or the WAL directory.

---

## Does uninstalling delete my observer URL and token?

No, not by default. `/lazy-observe.uninstall` removes the running service, the rendered agent config, and the service unit file. It asks whether to also delete the WAL and log directories (default: keep). It then asks separately whether to delete the answer file (`observe.toml`) and the token file — the default there is also keep. If you answer keep, a future `/lazy-observe.install` picks up your existing URL, auth choice, and username automatically and only asks for confirmation. Choose wipe only if you want a completely clean slate.

---

## How do I check whether the pipeline is working end-to-end?

Run `/lazy-observe.doctor`. It performs seven checks in sequence without touching any file or service state: reads your answer file, confirms the service unit is loaded and the agent process is up, verifies the local `/metrics` endpoint contains `lazycortex_runtime_*` series, checks the agent's own self-metrics for a non-zero remote_write success rate, reaches out to your observer URL to confirm it's reachable, and reports the WAL directory size. Each check resolves to `PASS`, `WARN`, or `FAIL` with a one-line suggested fix. It is safe to run at any time.

---

## Doctor reports `FAIL no-lazycortex-series` even though the endpoint is up. What's happening?

The `/metrics` endpoint is serving data from the lazycortex-core daemon, but no routine has dispatched yet in this session, so the daemon hasn't produced any `lazycortex_runtime_*` samples. Wait for the first tick — once Claude Code runs a skill or the daemon's own heartbeat fires, samples will appear. Re-run `/lazy-observe.doctor` after the first activity and Step 4 should clear to `PASS`.

---

## What does the audit skill check, and when should I run it?

`/lazy-observe.audit` is a read-only consistency check on the plugin's own artifact conventions. It verifies that each skill and agent file carries the required execution-discipline preamble and references the correct log directory. It is primarily useful after a plugin upgrade (a minor-bump re-install) or if you suspect a file was edited manually. For production health questions — is my shipper actually delivering metrics? — use `/lazy-observe.doctor` instead.

---

## I already have a shipper loaded under the same launchctl label. What do I do?

Run `/lazy-observe.uninstall` first. The uninstaller will call `launchctl bootout` (or `systemctl --user disable` on Linux) to remove the existing service cleanly, then you can re-run `/lazy-observe.install`. If you skipped uninstall and the installer failed with "already loaded", the service may still be running normally — check with `/lazy-observe.doctor` before uninstalling to decide whether the existing config is worth keeping.
