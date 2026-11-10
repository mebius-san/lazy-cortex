---
description: How a curated wiki node is structured — its summary, topic tags, glossed See-also links, and how to find a node's backlinks.
---
# Wiki node format

Every wiki node carries a `wiki_summary` (one-line description) in its frontmatter and a `# See also` section (tagged `#protected/wiki/see-also` on its first line) with glossed relative-path links — each link followed by ` — <gloss>` that describes the target. Glosses let you decide whether to open a node without opening it. Topic tags live in `tags:` as `wiki/<axis>/<value>`.

**Neighbours** — `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-wiki" neighbours <path> --repo <repo-root>` prints `{"path", "scope", "neighbours"}` as JSON: the sorted repo-relative paths of the node's own See-also targets that exist on disk and of every node of the same scope whose See-also links to it. A path no scope claims prints `"scope": null` and an empty list; a missing file prints `{"error": ...}` and exits 2.

**Backlinks** — grep the node's repo-relative path across the scope. All links are local relative paths; external material a scope needs is mirrored into the vault (a scope's `mirror` block) and linked like any local node.
