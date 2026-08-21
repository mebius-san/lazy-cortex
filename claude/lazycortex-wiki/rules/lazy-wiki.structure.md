---
description: Pointer to the project-structure map — consult it before placing a new file or directory, or when asked where something lives in this repo.
always_loaded: "knowing where a new file belongs is relevant on any turn that creates one, not only when a particular glob is touched"
---
# Project structure map

A `docs/structure.md` map of this repository may exist, describing what lives where and where new work belongs. Before placing a new file or directory, or answering "where does X live" / "where should Y go", query it via the `lazy-wiki.structure` skill (`/lazy-wiki.structure query [<path>]`) rather than scanning the tree with `Glob` — the skill returns just the slice you need, never the whole map.

If the skill reports no `structure` section configured, the map isn't set up in this repo — fall back to `Glob`/exploring as usual.
