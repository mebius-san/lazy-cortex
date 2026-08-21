---
chapter_type: block
summary: Thirteen aspect files (eight domain, five cross-cutting) that layer knowledge and rigor onto experts via lazy.settings.json composition.
last_regen: 2026-08-21
diagram_spec:
  anchor: "Domain aspects feed the composition entry"
  request: "Flow diagram: the eight domain aspect files — claude-plugin-aspect, game-dev-aspect, dotfiles-aspect, obsidian-plugin-aspect, data-pipeline-aspect, software-product-aspect, sci-fi-aspect, fantasy-aspect — each feed into a single lazy.settings.json[experts] composition entry node. The six technical domain aspects carry the edge label 'technical class'; the two genre aspects sci-fi-aspect and fantasy-aspect carry the edge label 'fiction class'. No other nodes."
  kind_hint: flow
source_skills:
  - lazy-experts.claude-plugin-aspect
  - lazy-experts.game-dev-aspect
  - lazy-experts.dotfiles-aspect
  - lazy-experts.obsidian-plugin-aspect
  - lazy-experts.data-pipeline-aspect
  - lazy-experts.software-product-aspect
  - lazy-experts.sci-fi-aspect
  - lazy-experts.fantasy-aspect
  - lazy-experts.discipline-aspect
  - lazy-experts.research-aspect
  - lazy-experts.tech-writing-aspect
  - lazy-experts.terms-aspect
  - lazy-experts.structure-aspect
  - lazy-experts.install
source_sha: 05f6f9a9fc372840e99c4cdcda9b7f182e336140
---
# Domain aspects and the cross-cutting aspects

The aspects block is a set of pure prompt layers — each one adds a body of knowledge or behavioral discipline to whichever generic expert (`interpreter`, `designer`, `architect`, `planner`, `implementer`, `debugger`, `reviewer`, `tester`, or `fiction-writer`) you pair it with. You declare the pairing in `lazy.settings.json[experts]` and the expert runtime merges the aspect bodies into the agent's system prompt at dispatch time. The result is a named specialist — for example a `claude-plugin-planner`, a `game-designer`, an `obsidian-plugin-implementer`, or a `sci-fi-writer` — without authoring a fresh agent for each domain.

`lazycortex-experts` ships thirteen aspects across two categories. Eight are **domain aspects**: you pick the ones relevant to a project and wire them into the specialists you want. Five are **cross-cutting aspects** that compose automatically per class rather than by hand-pick: `discipline` and `research` onto every seeded expert, and `tech-writing`, `terms`, and `structure` onto every seeded expert in a technical class only. `/lazy-experts.install` handles all of it — it asks which classes to register (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, `sci-fi`, `fantasy`), then seeds the roles the class map assigns for each chosen class, wiring `lazycortex-experts:lazy-experts.discipline-aspect` and `lazycortex-experts:lazy-experts.research-aspect` onto every entry, and `lazycortex-experts:lazy-experts.tech-writing-aspect`, `lazycortex-experts:lazy-experts.terms-aspect`, and `lazycortex-experts:lazy-experts.structure-aspect` onto technical-class entries only. All thirteen aspects are public-marketplace-safe and composable with aspects your own plugins ship.

## What's in this block

**`lazy-experts.discipline-aspect`** is a cross-cutting aspect that composes onto every seeded specialist regardless of class — technical or fiction. It adds four iron laws the expert holds itself to regardless of its role or domain: verify before claiming done (evidence must be named in the document, never implied, and re-checked pass after pass until one comes back clean — capped at five passes, a repeated finding, or a pass that breaks more than it fixes), never guess past an input gap (surface the gap and stop rather than inventing an answer and proceeding), no performative agreement (evaluate the operator's input technically; push back with reasons if it is wrong), and read decisions before starting work (declare only a genuine fork explicitly, with its reason and the alternatives honestly rejected, and never quietly revisit one already made). It also adds the async-translation principle: wherever a synchronous workflow would pause to ask a human, the expert translates that gate into an open point in the document instead, then stops and waits for the operator to answer there. Because it is role-independent, it carries no domain discovery and adds no tooling of its own; the shape of open-point callouts, checkboxes, and markers is always defined by the dispatching protocol, not by this aspect.

**`lazy-experts.research-aspect`** is the second universal cross-cutting aspect — it composes onto every seeded specialist alongside discipline, the active-research counterpart to a dispatch's own `source` / `context` bundle. It requires the expert to look beyond what it was handed before writing: read the product's own `design.md` / `tech.md` first, always, as the mandatory opening step; then walk sibling and ancestor docs in the surrounding spec tree; then discover whichever research-marked pull-skills exist in the current install (structure maps, domain trees, a term dictionary) by spotting the word "research" in a skill's description rather than by a hardcoded list; then query a covered wiki scope; and only then grep the code itself. An absent research route — a pull-skill not installed, no structure map built, no wiki scope covering the question — is treated as a configuration fact, not a knowledge gap: the expert degrades silently to reading the code and never recommends installing or configuring the missing tooling in its output. Only a gap that survives every route becomes a surfaced question, through the expert-signals channel the dispatching protocol defines, following the same async-translation principle discipline already applies.

**`lazy-experts.tech-writing-aspect`** is a cross-cutting aspect that composes onto technical-class specialists only — fiction classes (`sci-fi`, `fantasy`) never carry it, because its bans contradict literary craft. It governs the sentences a technical document is made of, not what the specialist produces: no metaphor or figurative imagery, no atmospheric openings, no evaluative epithets ("elegant", "robust") without a measurable property behind them, no emotional intensifiers, no shop talk or informal register, no invented abbreviations, and no filler sentence that carries no checkable fact or obligation. It also enforces a single-term-per-concept dictionary inherited verbatim from the upstream document the job carries (a spec inherits its terms from the brief, a plan from the spec) — except that when the repository's terms dictionary names the same concept differently, the dictionary's term wins and the disagreement is stated in the document rather than resolved silently. A new term gets one definition sentence at first use and stays fixed after that. Use it on any specialist that writes specs, plans, or reviews — never on `fiction-writer`.

**`lazy-experts.terms-aspect`** is a cross-cutting aspect that composes onto technical-class specialists only, alongside tech-writing. Where tech-writing enforces one term per concept *inside* a document, terms-aspect supplies the term from *outside* it, so documents written months apart by different experts converge on the same word: before naming a concept, the specialist asks the `lazy-wiki.terms` skill whether the repository dictionary already has a term for it, and uses the dictionary's word verbatim even when its own reads better. The specialist is forbidden from writing to the dictionary under any circumstance — not to add a term it just coined, not to fix a definition, not to correct a typo; the dictionary's curator reads finished documents and updates it later. When the dictionary and the job's upstream document name a concept differently, the dictionary's term wins and the specialist states the disagreement rather than resolving it silently. When the `lazy-wiki.terms` skill is absent, the repository has no dictionary and the specialist writes as it normally would, saying nothing about the gap.

**`lazy-experts.structure-aspect`** is a cross-cutting aspect that composes onto technical-class specialists only. It routes every "where does this live" or "where does new work belong" claim through the repository's structure map via the `lazy-wiki.structure` skill's `query [<path>]` mode — a targeted slice, never the whole map read into context. The specialist is forbidden from writing to `docs/structure.md`; a stale map entry is at most a remark in its own document, never a self-correction. When the map offers two plausible homes for new work, the specialist names the choice and its reason instead of picking silently. When the `lazy-wiki.structure` skill is absent, or reports no map configured, the specialist grounds the same placement claim by reading the tree directly and says nothing about the missing tooling.

**`lazy-experts.claude-plugin-aspect`** adds LazyCortex plugin authoring expertise to the composing agent. A specialist that includes this aspect knows the plugin directory layout, the marketplace registration contract, the per-artifact authoring contracts (agents, skills, rules, references, help chapters), the install and publish lifecycle, and the consumer-effort versioning semantics (patch / minor / major). The aspect anchors every design claim to a concrete contract file path and enforces obligations like tier-registration for new agents and scaffold-template use for new artifacts. Use it to build a specialist that interprets plugin-change requests, designs plugin additions, or plans plugin implementation as a sequence of conventional commits.

**`lazy-experts.game-dev-aspect`** adds general game-development expertise — core loop, progression, balance, telemetry, and content-versus-mechanics separation. The aspect is engine-agnostic, genre-agnostic, and platform-agnostic by design; when a brief pins Unity, Unreal, Godot, or a custom engine the specialist mirrors that pin literally. It obliges the agent to name the core loop explicitly, identify the progression curve, flag missing telemetry for every balance lever, separate mechanics from content in section structure, and schedule implementation plans in playable vertical slices. Use it to build a specialist that interprets a game-design request, writes a game-design document, or plans a game-implementation milestone list.

**`lazy-experts.dotfiles-aspect`** adds personal-computer and network configuration management expertise — dotfile-repo conventions, shell rc structure, host-versus-personal split, package-manager manifests, init systems, and secret-handling boundaries. The aspect is tool-neutral (chezmoi, yadm, stow, Nix home-manager, or ad-hoc); when a brief pins a tool the specialist honors that pin. It obliges the agent to push host-specific values behind template variables, never commit secrets, split shell rc files by responsibility, flag unversioned tools in package manifests, and declare init-system units with explicit run conditions. Use it to build a specialist that interprets a config-repo request, writes a config-repo design, or plans a dotfiles migration that keeps every machine in a working state.

**`lazy-experts.obsidian-plugin-aspect`** adds Obsidian community-plugin development expertise — plugin lifecycle hygiene, vault/workspace API boundaries, settings persistence, mobile compatibility, metadata-cache interplay, and the community release process. The aspect is neutral on bundler, language flavor, and testing framework; it is opinionated on the conceptual axes every Obsidian plugin must answer. It obliges the agent to design around `onload`/`onLayoutReady`/`onunload`, route every registered command, event, interval, and view through the matching `register*` cleanup helper, prefer `app.vault` over the raw adapter for note reads/writes, keep `data.json` settings separate from rebuildable runtime state, account for the metadata cache's asynchronous catch-up, decide mobile compatibility deliberately, and plan releases against the version-bump triple and community-registry submission step. Use it to build a specialist that interprets an Obsidian plugin request, writes a plugin design, or plans a release the community registry will accept.

**`lazy-experts.data-pipeline-aspect`** adds data-synchronization and pipeline engineering expertise — idempotency, incremental state, resumability, quota and rate-limit budgeting, integrity verification, and source-data safety. The aspect is neutral on transport, storage, and scheduler; it is opinionated on what state marks progress, what happens on re-run, what happens on interruption, and how the result is verified against the source. It obliges the agent to name the idempotency mechanism per stage, state the incremental-state model and when the progress marker is written relative to the side-effect, design for mid-batch interruption as the normal case, budget external quotas explicitly with a backoff strategy, keep source data read-only until the destination copy is proven, verify by reconciling counts/hashes/samples rather than by absence of errors, and park per-item failures in a visible quarantine instead of letting them block the run. Use it to build a specialist that interprets a sync or pipeline request, writes a pipeline design, or plans a migration that survives interruption.

**`lazy-experts.software-product-aspect`** adds general software-product expertise — the fallback technical class for a project whose domain doesn't match one of the other five shipped classes, or hasn't crystallized yet. It is neutral on language, stack, and delivery form (CLI, service, app, library); opinionated on the product-shaped questions any piece of software must answer regardless of domain — who uses it, where it runs, what its compatibility promises are, where its state lives, what its configuration surface costs, and what happens when it fails. It obliges the agent to name the user and their actual workflow in every design, declare supported platforms and runtime version floors explicitly, state each user-touchable change's compatibility effect and its deprecation or migration path when the surface was promised stable, give every persisted-format change a migration story (including what a half-migrated state looks like), budget new configuration knobs against a working default, design failure to be user-visible (what the user sees, what lands in logs, what a maintainer needs to reproduce it), and verify a shipped behavior change in its released form — a smoke check, version output, telemetry — not only in the test suite. A project whose domain later crystallizes keeps this class and stacks a repo-local domain aspect on top of it rather than replacing it. Use it to build a specialist for a project no narrower shipped class covers.

**`lazy-experts.sci-fi-aspect`** adds science-fiction genre expertise to whichever expert composes it — in practice, `fiction-writer`. It treats the story's speculative premise as a system with consequences rather than a backdrop: name the novum (the one invented difference the story runs on) and work its second-order effects through plot, society, and scene; keep extrapolation coherent with whatever the story has already stated about its own technology; let the technology's limits — cost, latency, scarcity, failure — create the dramatic pressure instead of dissolving it. It is neutral on subgenre (hard SF, space opera, cyberpunk, near-future) and matches its plausibility rigor to whichever pin the brief sets.

**`lazy-experts.fantasy-aspect`** adds fantasy genre expertise to whichever expert composes it — in practice, `fiction-writer`. It treats the invented world as a constraint on every scene: magic shows or implies a cost every time it's used, world details that don't change a character's choices or stakes are cut, and established rules, geography, history, and names bind every later sentence — a contradiction with earlier text or the story bible is a defect, not a creative choice. Names and languages stay coherent with their culture's established conventions, and wonder is anchored in what a marvel does to characters and stakes rather than in unattached adjectives. It is neutral on subgenre (epic, urban, dark, fairy-tale).

## How they work together

The five cross-cutting aspects and the eight domain aspects serve different purposes and compose along different rules.

**Discipline and research are universal; tech-writing, terms, and structure are class-gated.** `/lazy-experts.install` adds `lazycortex-experts:lazy-experts.discipline-aspect` and `lazycortex-experts:lazy-experts.research-aspect` to every entry it seeds, technical or fiction — both are role-independent working habits that apply whether the specialist writes a spec or a scene. It adds `lazycortex-experts:lazy-experts.tech-writing-aspect`, `lazycortex-experts:lazy-experts.terms-aspect`, and `lazycortex-experts:lazy-experts.structure-aspect` only to entries in a technical class (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, and any future non-fiction class) — fiction-class entries (`sci-fi`, `fantasy`) never receive any of the three, because banning metaphor and atmospheric openings would gut the craft `fiction-writer` exists to practice, and an obligation to call a thing by its registered term or ground every location claim in a repository map has nothing to say inside a scene. When you hand-author a specialist entry, follow the same rule: include discipline and research always, include tech-writing/terms/structure only if the specialist writes technical documents.

**Domain aspects split into two families that don't mix.** The six technical domain aspects (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`) compose onto the engineering roles the install skill's class map seeds — `interpreter`, `designer`, `system-designer`, `architect`, `planner`, `developer`, `debugger`, `reviewer`, `tester` (nine roles; `system-designer` shares the `designer` agent with the `designer` role under a second composed entry, and `developer` maps to the `implementer` agent). `game-dev` additionally seeds a `data-writer` role — mapped to the `data-implementer` agent, for writing entity data files — as an addition on top of the nine, not a replacement for any of them. `software-product` is the fallback of the six: reach for it when a project's own domain doesn't match one of the other five, or hasn't taken shape yet — stacking a repo-local domain aspect on top later, once it does, rather than dropping this one. The two genre aspects (`sci-fi`, `fantasy`) compose onto `fiction-writer`. You can combine multiple technical domain aspects on one engineering agent, and you can combine both genre aspects on `fiction-writer` for a story that blends sci-fi and fantasy elements, but a genre aspect on an engineering agent (or a technical domain aspect on `fiction-writer`) has no defined effect — the class map never seeds that pairing, and hand-authoring it does not make it meaningful. The aspect resolver (part of `lazycortex-core`'s expert runtime) merges whichever aspect bodies you list into the agent's system prompt before dispatch, in declaration order; order matters only when obligations conflict, and earlier aspects take precedence in any ambiguous obligation.

The `lazy.settings.json[experts]` entry is the composition point. A hand-authored technical entry names one engineering agent, discipline, research, tech-writing, terms, structure, and one or more domain aspects; a hand-authored fiction entry names `fiction-writer`, discipline, research, and one or more genre aspects with no tech-writing, terms, or structure:

```jsonc
"experts": {
  "_version": 1,
  "claude-plugin-planner": {
    "agent": "lazycortex-experts:lazy-experts.planner",
    "aspects": [
      "lazycortex-experts:lazy-experts.claude-plugin-aspect",
      "lazycortex-experts:lazy-experts.discipline-aspect",
      "lazycortex-experts:lazy-experts.research-aspect",
      "lazycortex-experts:lazy-experts.tech-writing-aspect",
      "lazycortex-experts:lazy-experts.terms-aspect",
      "lazycortex-experts:lazy-experts.structure-aspect",
      "lazycortex-core:lazy-memory.persona-aspect"
    ]
  },
  "sci-fi-writer": {
    "agent": "lazycortex-experts:lazy-experts.fiction-writer",
    "aspects": [
      "lazycortex-experts:lazy-experts.sci-fi-aspect",
      "lazycortex-experts:lazy-experts.discipline-aspect",
      "lazycortex-experts:lazy-experts.research-aspect",
      "lazycortex-core:lazy-memory.persona-aspect"
    ]
  }
}
```

Running `/lazy-experts.install` and choosing a technical class (say `data-pipeline`) seeds all nine engineering roles for that class — `data-pipeline.interpreter`, `data-pipeline.designer`, `data-pipeline.system-designer`, `data-pipeline.architect`, `data-pipeline.planner`, `data-pipeline.developer`, `data-pipeline.debugger`, `data-pipeline.reviewer`, `data-pipeline.tester` — each carrying the domain aspect plus all five cross-cutting aspects. Choosing a fiction class (say `sci-fi`) seeds only `fiction-writer` — named for the class — carrying the genre aspect plus discipline and research, with no tech-writing, terms, or structure. Every seeded entry also carries `lazycortex-core:lazy-memory.persona-aspect` so the specialist accumulates private memory under `.memory/<self>/` across runs, and a deterministic bot `git_author`. Install is idempotent — existing entries are never overwritten, so any specialist you hand-customized survives a re-run; when the `experts` list already has domain-class entries, install derives the classes already present from their `aspects` and completes only those, never re-asking and never silently adding a class you didn't choose. A re-run also completes any of the five mandatory cross-cutting aspects a pre-existing entry is missing — appending only, never reordering or removing an aspect you deliberately dropped — so a specialist seeded before `research`, `terms`, or `structure` shipped catches up to the current contract on the next `/lazy-experts.install` run.

The aspect bodies carry no side-effects and add no new write permissions beyond what their own obligations name (terms-aspect and structure-aspect each add one explicit prohibition: never write to the terms dictionary, never write to `docs/structure.md`). They expand what the agent knows, what it considers a complete or incomplete brief or draft, and the rigor or genre judgment it applies to its own output — they do not change where or how it writes its result, which remains governed by the protocol the dispatching routine supplies.

## Where this fits

- The **agents** block (`claude/lazycortex-experts/help/agents.md`) describes the generic agents that aspects compose onto — the engineering roles plus `fiction-writer`, the one that pairs with `sci-fi-aspect` and `fantasy-aspect`.
- The **composition** block describes how to assemble a named specialist end-to-end, including naming conventions and how to wire a dispatching routine.
- To register the model tier for a new specialist you author, run `/lazy-core.agent-models` — the skill writes the `lazy.settings.json[agent_models]` entry; do not hand-edit the file.

## Domain aspects feed the composition entry

Each domain aspect is a file the composition entry names; the six technical ones pair with the engineering agents, the two genre ones pair with `fiction-writer`.

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  claudePluginAspect["claude-plugin-aspect"]
  gameDevAspect["game-dev-aspect"]
  dotfilesAspect["dotfiles-aspect"]
  obsidianPluginAspect["obsidian-plugin-aspect"]
  dataPipelineAspect["data-pipeline-aspect"]
  softwareProductAspect["software-product-aspect"]
  sciFiAspect["sci-fi-aspect"]
  fantasyAspect["fantasy-aspect"]
  expertsCompositionEntry["lazy.settings.json[experts] composition entry"]

  claudePluginAspect -->|technical class| expertsCompositionEntry
  gameDevAspect -->|technical class| expertsCompositionEntry
  dotfilesAspect -->|technical class| expertsCompositionEntry
  obsidianPluginAspect -->|technical class| expertsCompositionEntry
  dataPipelineAspect -->|technical class| expertsCompositionEntry
  softwareProductAspect -->|technical class| expertsCompositionEntry
  sciFiAspect -->|fiction class| expertsCompositionEntry
  fantasyAspect -->|fiction class| expertsCompositionEntry

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  class claudePluginAspect entry
  class gameDevAspect entry
  class dotfilesAspect entry
  class obsidianPluginAspect entry
  class dataPipelineAspect entry
  class softwareProductAspect entry
  class sciFiAspect entry
  class fantasyAspect entry
  class expertsCompositionEntry action
```

## Cross-cutting aspects and the two outcomes

`discipline-aspect` and `research-aspect` land on every seeded entry. `tech-writing-aspect`, `terms-aspect`, and `structure-aspect` land on technical-class entries only, so a fiction specialist never carries them.

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  disciplineAspect["discipline-aspect"]
  researchAspect["research-aspect"]
  techWritingAspect["tech-writing-aspect"]
  termsAspect["terms-aspect"]
  structureAspect["structure-aspect"]
  expertsComposition["lazy.settings.json[experts] composition"]
  technicalSpecialist["Technical specialist"]
  fictionSpecialist["Fiction specialist"]

  disciplineAspect -->|every entry| expertsComposition
  researchAspect -->|every entry| expertsComposition
  techWritingAspect -->|technical entries only| expertsComposition
  termsAspect -->|technical entries only| expertsComposition
  structureAspect -->|technical entries only| expertsComposition
  expertsComposition -->|technical class| technicalSpecialist
  expertsComposition -->|fiction class| fictionSpecialist

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px

  class disciplineAspect entry
  class researchAspect entry
  class techWritingAspect entry
  class termsAspect entry
  class structureAspect entry
  class expertsComposition action
  class technicalSpecialist success
  class fictionSpecialist success
```
