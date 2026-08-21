---
chapter_type: block
summary: Keep one repo-wide map, docs/structure.md, current — rebuild it wholesale, query a slice of it, or let git-watch routines patch it per commit.
last_regen: 2026-08-19
diagram_spec:
  anchor: "How the pieces fit together"
  request: "Flow diagram of the structure block: (1) /lazy-wiki.configure structure sets depth_profiles + exclude and registers three git-watch routines (structure-scan for changed files, structure-scan-deletes for deleted files, structure-scan-renames for renamed files); (2) each routine dispatches lazy-wiki.structure-curator per changed path with kind=curate or kind=rename; (3) the curator edits docs/structure.md incrementally and commits; (4) separately, an operator or agent runs /lazy-wiki.structure rebuild for a wholesale resync (walks git ls-files, classifies by depth_profiles, fans out to Explore subagents on a large tree, writes and commits the whole map), or /lazy-wiki.structure query [<path>] to read back just one slice without loading the whole file. Show rebuild and the curator's incremental path as two ways of reaching the same file, and query as the read-only path that never touches routines."
source_skills:
  - lazy-wiki.structure
  - lazy-wiki.structure-curator
  - lazy-wiki.configure
source_sha: e758792cb8f978c3f3e230b8233d46a2da076903
---
# Structure

`docs/structure.md` is one file that answers "what lives where, and where does new work go" for the whole repository — written compactly enough for an agent to read before deciding where to place a file or search for one. This block is everything that creates, updates, and answers questions against that map: the skill that builds and queries it, the curator that keeps it current automatically, and the configuration wizard that sets both up.

## What's in this block

**`lazy-wiki.structure`** is the entry point for both directions of the map. `/lazy-wiki.structure rebuild` walks the tracked tree (`git ls-files`), classifies each directory against your configured `depth_profiles`, and rewrites `docs/structure.md` from scratch — the tool for an initial build, a map that drifted before the routines existed, or a hand edit that bypassed them. On a tree with more than roughly 12 top-level tracked directories, rebuild fans the work out to one `Explore` subagent per directory (batches of at most 4 concurrent), so no single context has to hold the whole tree. `/lazy-wiki.structure query [<path>]` is the read side — it returns only the matched slice of the map (top-level bullets when `<path>` is omitted, or the bullet plus its nested children for a given path), never the whole file. Any agent doing research — deciding where a new file belongs, or asking "where does X live" — should query through this skill rather than reading `docs/structure.md` directly.

**`lazy-wiki.structure-curator`** is the expert that keeps the map current one change at a time, so a full rebuild is rarely needed once the map exists. It runs in three modes: `curate` (a path was added or modified — decide whether it earns its own entry, and whether the change shifts what its parent directory is for), `rename` (a path moved — remove the old entry, re-enter the new one at the class its new path resolves to, since a rename can cross depth-profile boundaries), and `report` (a read-only pass, dispatched by the structure section of `/lazy-wiki.doctor`, that compares the map against the tracked tree and returns findings without writing anything). The curator never edits the files and directories it describes, and it never creates `docs/structure.md` — only `rebuild` does that, so one incremental entry never gets mistaken for the whole repository's map.

**`/lazy-wiki.configure structure`** is the wizard that wires the other two together: it collects your `depth_profiles` (which path globs get per-file entries, which get a directory-only line, which get a half-line note) and `exclude` globs, writes them into `lazy.settings.json[structure]`, and registers the three git-watch routines that dispatch the curator automatically. `docs/structure.md` itself is always force-included in `exclude`, silently — without it, the curator's own commit describing the map would wake the very routine that just fired, and the map would try to describe itself.

## How they work together

Two independent paths keep `docs/structure.md` accurate, and you rarely have to think about which one is running.

The **incremental path** is the default once the block is configured. Three routines — `lazy-wiki.structure-scan` (changed files), `lazy-wiki.structure-scan-deletes` (deleted files), `lazy-wiki.structure-scan-renames` (renamed files) — watch every commit on your configured branch and dispatch `lazy-wiki.structure-curator` per matching path, one commit at a time. The curator reads only the real path that changed (never the whole tree), decides whether the map's description of it — or its parent directory's — needs to change, applies the edit by anchoring on the existing entry line, and commits under your operator identity. A change that doesn't alter what the map says about a path is a no-op: nothing written, nothing committed. This is why the map stays current without you ever running a command for it.

The **wholesale path** is `/lazy-wiki.structure rebuild`, which you reach for directly: the first time you set the block up (there is no map yet to patch incrementally), after a rebase or history rewrite the routines never saw, or when you suspect drift the incremental path can't self-heal (a duplicated anchor line, for instance — the curator refuses to guess which one is authoritative and reports an error instead of picking one). Rebuild reads the whole tracked tree once and replaces the whole file; the routines then resume patching it per commit from that clean baseline.

Both paths write the same file in the same shape, so `/lazy-wiki.structure query` works identically regardless of which one produced the current state. If the daemon that runs the routines is disabled in your project, the map still works — you just rebuild it by hand whenever it drifts, since nothing is watching commits to patch it automatically.

`/lazy-wiki.configure structure` is where you land to change any of this: add a new `depth_profiles` class when a directory that used to get a one-line summary now needs per-file entries, widen `exclude` when a generated directory starts polluting the map, or re-register the routines if `/lazy-wiki.doctor` reports one missing. Running it again on an already-configured project edits in place — persisted values are shown, pressing Enter keeps them.

## Where this fits

The structure map is repo-wide and file-and-directory shaped — it answers "where", not "what does this concept mean" or "how do these pieces connect". That makes it a companion to, not a replacement for, the wiki's other blocks: `curation` builds a graph of per-node summaries and See-also links for research questions about a specific document or code file, and `terms` maintains a vocabulary dictionary so a concept doesn't grow a second name across documents. Reach for structure when the question is about placement or discovery; reach for curation or terms when the question is about meaning or naming.

## How the pieces fit together
