---
chapter_type: faq
summary: Common operator questions about installing, running, and maintaining the lazycortex-observe metrics shipper.
last_regen: 2026-07-10
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

Pick **Grafana Alloy** if you're already on the Grafana / Mimir stack. Pick **OpenTelemetry Collector** (`otelcol`) for everything else. Both agents scrape the same loopback endpoint and emit identical metric series shapes, so dashboards and alert rules work unchanged with either. Your choice is genuine config — it's collected once, persisted, and reused silently on every later `/lazy-observe.install` run (you won't be asked again). To switch agents later, see "How do I change my agent kind, remote_write URL, or auth after the first install?" below.

---

## How do I change my agent kind, remote_write URL, or auth after the first install?

Agent kind, remote_write URL, and auth kind are all **read-first**: once `/lazy-observe.install` has collected and persisted a value, every later run reuses it silently — the wizard does not re-ask, and it does not offer a keep-or-overwrite choice either.

To change any of them, run `/lazy-observe.uninstall` first. At the "wipe answer file + token" step, choose **wipe** instead of the default `keep`. That clears `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml` and `observe.token`. Then re-run `/lazy-observe.install` — with nothing on record, the wizard asks every question fresh (agent kind, remote_write URL, auth kind, and a new token if applicable), and the two agents emit identical metric series shapes so dashboards and alerts continue working across the switch.

---

## How do I rotate the bearer token?

Depends on how the token is sourced, which you chose during install:

- **`env` source**: nothing to do in the plugin. Update `LAZYCORTEX_OBSERVE_TOKEN` in your shell profile or secret manager and restart the agent process — it reads the token fresh at startup. `/lazy-observe.install` isn't involved.
- **`file` source (0600 file)**: because `auth_kind` is read-first (see above), simply re-running `/lazy-observe.install` will NOT prompt for a new token — it reuses the existing auth config silently. To rotate, run `/lazy-observe.uninstall`, choose to wipe the answer file and token at Step 5, then re-run `/lazy-observe.install`. The fresh wizard asks for auth kind and token again and writes the new 0600 token file.

The token is never written into `observe.toml` or any tracked file; it lives only in the token file or your environment.

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

No, not by default. `/lazy-observe.uninstall` removes the running service, the rendered agent config, and the service unit file. It asks whether to also delete the WAL and log directories (default: keep). It then asks separately whether to delete the answer file (`observe.toml`) and the token file — the default there is also keep. If you answer keep, a future `/lazy-observe.install` picks up your existing URL, auth choice, and username automatically and silently — no confirmation question, no re-asking. Choose wipe only if you want a completely clean slate or need to change a previously-recorded value (see "How do I change my agent kind, remote_write URL, or auth after the first install?" above).

---

## What happens if I run `/lazy-observe.uninstall` on a host where the shipper was never installed?

Nothing breaks. Every step treats an already-absent target as a silent no-op, never an error — the service unload step reports `absent`, the config-removal step reports `absent`, and the WAL/log/answer-file steps skip their confirmation questions entirely because there's nothing to delete. It's safe to run `/lazy-observe.uninstall` speculatively, e.g. before a fresh install, without first checking whether anything is there.

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
