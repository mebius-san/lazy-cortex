---
since: 4.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-wiki, terms-sweep, --check]}
writes:
  - ".state/lazy-wiki.terms-sweep.*.json"
---
## Why

Links to terms in document text are placed only by the terms curator, never by code that matches the dictionary. A document migrated to the per-term dictionary therefore has no term link at all until the curator has passed over it, and a document under review, which the curator's routine skips, would keep its old `## Terms` section until the review closes. After the migration the curator needs one job per document directory of every scope.

The `terms-sweep --dispatch --mark --include-review` verb takes every scope that has no marker yet: it queues those scopes' jobs through core's job queue and writes the tracked marker `.state/lazy-wiki.terms-sweep.<scope>.json` for each of them, which records that this repository has run the step for that scope. A scope that already carries its marker is neither queued nor counted. The step runs after step 001 has landed its commit, so a curator that takes a job never commits half-migrated documents. The verb queues the jobs itself when the migrated checkout is the checkout where the daemon works. When the daemon works in another checkout, the step queues nothing and its last output line, a JSON object, names that checkout in `deferred_to`. The operator then pushes the migration commits from the migrated checkout, pulls them in the daemon checkout, and runs `terms-sweep --dispatch --include-review --repo <daemon checkout>` there. Without a daemon the operator runs `/lazy-runtime.tick --drain`.

The `writes` list holds no `{terms}` token, so the step also applies where step 001 received no territory. A scope whose dictionary is not migrated yet is left out and named in the answer under `unmigrated`; a document it shares with a migrated scope belongs to the migrated one and is swept with it, whatever order the settings list the scopes in. After migrating such a scope by hand with `terms-migrate`, the operator runs the sweep command by hand.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<wiki-cli>` is `bin/lazycortex-wiki` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-wiki --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> terms-sweep --dispatch --mark --include-review --repo "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> terms-sweep --check --migrated --repo "<repo-root>"` exits 1: every migrated scope that has documents carries its marker.
