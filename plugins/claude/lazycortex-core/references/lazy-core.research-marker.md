---
description: Research-marker convention for search/pull skills — which skills qualify, the two-place marker, how consumers discover the live set, and the broken-marker case.
---
# Research-marker convention

§ 10 of `lazy-core.skill-writing`, extracted and read on demand: open this file before marking a skill as a research skill, and before writing an aspect, rule, or skill that consumes research skills.

## 1. What qualifies

A **research skill** is any skill that exposes a mode whose contract is to return a bounded knowledge slice on demand — given a question or a path, hand back the matched slice of an existing map, tree, dictionary, or index, never the whole document (`lazy-wiki.structure`'s `query [<path>]` mode is the canonical shape). A skill that only ever writes or rebuilds, with no such query mode, does not qualify; one mixing a rebuild mode and a query mode qualifies on the strength of its query mode alone.

## 2. Marker

Every research skill carries the discipline in two places, both mandatory together:

- Frontmatter: `research: true`.
- `description:`: the word "research" appears in the trigger sentence, so the marker is visible in the skill listing a consuming agent already sees — no extra `Read` needed to spot a candidate.

## 3. Discovery, not enumeration

Nothing that consumes research skills — an aspect, a rule, another skill's body — may hardcode the current set by name; the set grows and a hardcoded list goes stale the day after the next one lands. Every consumer discovers the live set the same way. Primary, portable to any executor: spot the word "research" in a skill's `description:` in the ambient skill listing every session already carries. Secondary, dev-vault verification: `Glob` `.claude/skills/*/SKILL.md`, `plugins/claude/*/skills/*/SKILL.md`, and, for installed plugins (the first two globs alone miss them), the `installPath` of each record in `~/.claude/plugins/installed_plugins.json`, then `<installPath>/skills/*/SKILL.md`; `Grep` each frontmatter for `research: true`. Globs alone are not portable to a consumer session, which never sees the dev-vault tree — the skill listing is the one route every executor has.

## 4. Obligation

Marking a skill `research: true` without also documenting a query-mode contract (an invocation shape that returns a bounded slice, not the whole tree) is a broken marker — it tells a consumer "ask me a question" with no way to actually ask one narrowly.
