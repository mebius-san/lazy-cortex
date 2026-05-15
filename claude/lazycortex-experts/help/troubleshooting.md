---
chapter_type: troubleshooting
summary: Common failure modes during lazycortex-experts setup — symptoms, likely causes, and fixes.
last_regen: 2026-05-15
no_diagram: true
source_skills:
  - lazy-experts.install
---
# Troubleshooting

## `/lazy-experts.install` aborts with "plugin not enabled"

**Symptom**: Running `/lazy-experts.install` immediately stops with a message like `lazycortex-experts not enabled — add "lazycortex-experts@lazycortex": true to enabledPlugins in your settings.json and run /plugin install lazycortex/lazycortex-experts.`

**Likely cause**: `lazycortex-experts@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json`. This happens when the plugin was never installed or the install did not complete.

**Fix**: Add `"lazycortex-experts@lazycortex": true` to `enabledPlugins` in your `settings.json`, restart Claude Code, run `/plugin install lazycortex/lazycortex-experts` to complete the install, then re-run `/lazy-experts.install`.

---

## `/lazy-experts.install` aborts with "lazycortex-core not installed"

**Symptom**: Running `/lazy-experts.install` stops with `lazycortex-core not installed; install it before /lazy-experts.install`.

**Likely cause**: The defaults file that `lazy-experts.install` reads from `lazycortex-core`'s plugin cache was not found. This means `lazycortex-core` is either not installed or its cache is missing.

**Fix**: Install `lazycortex-core` first by running `/plugin install lazycortex/lazycortex-core`, then re-run `/lazy-experts.install`. `lazycortex-core` is a declared dependency of `lazycortex-experts` and must be present before install can seed agent-model tiers.
