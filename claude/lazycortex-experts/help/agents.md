---
chapter_type: block
summary: Eleven persona-only agents — four design-time, six execution-stage, and one literary agent for fiction deliverables.
last_regen: 2026-08-21
diagram_spec:
  anchor: "The agent lineup"
  request: "Flow diagram showing eleven agents. Top row left-to-right: Interpreter → Designer → Architect → Planner (design-time pipeline, edges carry 'gap-free brief', 'design spec', and a dashed 'architecture doc (optional)' edge from Architect down to Planner). Middle row left-to-right: Implementer, Data Implementer, Docs Writer, Debugger, Reviewer, Tester (execution-stage agents, no mandatory ordering between them). A 'Dispatching Routine' node at the top points down with dashed 'protocol' edges to all eleven, including a separate standalone Fiction Writer node off to one side that has no edges to or from the other ten. A dashed 'implementation plan' edge connects Planner down to Implementer, a dashed 'approved design' edge connects Designer down to Data Implementer, and a dashed 'approved design' edge connects Designer down to Docs Writer. Label the top row 'Design-time', the middle row 'Execution-stage', and the Fiction Writer node 'Literary'."
source_skills:
  - lazy-experts.interpreter
  - lazy-experts.designer
  - lazy-experts.architect
  - lazy-experts.planner
  - lazy-experts.implementer
  - lazy-experts.data-implementer
  - lazy-experts.docs-writer
  - lazy-experts.debugger
  - lazy-experts.reviewer
  - lazy-experts.tester
  - lazy-experts.fiction-writer
source_sha: 363c10b71ead3c2a5577cc0c34d87fb3879699fe
---
# Generic lifecycle agents

The `agents` block gives you eleven building blocks. Ten span the full lifecycle of a piece of technical or content work — from a vague idea to reviewed, tested, committed code, data, or documentation. The eleventh is a literary specialist for fiction deliverables. Four design-time agents transform a raw request into a structured brief, a scoped design spec, an optional code-structure design, and an ordered implementation plan. Six execution-stage agents carry that plan — or, for data-only or documentation work, the approved design directly — into code, data files, or user-facing documentation with test-first discipline, root-cause debugging, evidence-ranked review, mechanism-grounded testing, and reader-facing prose. The eleventh, the fiction writer, produces narrative prose, dialogue, and lyrical fragments from a brief or outline — it stands apart from the technical pipeline. All eleven are persona-only: each agent knows who it is and what its output must look like, but it waits for a dispatching routine to hand it a protocol before doing any work. The protocol is the only source of truth for what the agent reads as input and what it writes as output.

## What's in this block

**lazy-experts.interpreter** — The interpreter's job is to find every gap before any solution-shaped thinking begins. It reads whatever you give it — a free-form request, a rough note, an old document — and returns a structured brief that leads with the *why* before the *what*. On every round it surveys the whole document and surfaces one question per independent axis of uncertainty, all gaps raised together, never serialized across rounds. Anything it cannot confidently assert becomes a callout question embedded in the brief; you answer those questions by editing the document directly in your editor and re-invoking. When the input admits more than one viable direction, it surfaces two or three candidates with one recommended, rather than letting a single direction harden into the brief unchallenged. The interpreter never asks interactively and never proposes a solution.

**lazy-experts.designer** — The designer reads a gap-free brief and writes a design specification: a document that says *what is being built and why*, with strict scope discipline. It writes declaratively — specs state facts about the system, not imperative instructions — and it designs the target the brief asks for, never the current implementation's gaps, shortcuts, or half-built paths; the only thing that narrows scope is an explicit operator decision recorded in the brief. When a brief surfaces multiple goals it pushes back: one goal gets scoped in, the others get deferred. It refuses to drift into implementation choices (file paths, function names, data structures) and surfaces any underspecified area as a callout against the brief rather than inventing an answer. Three things block shipping outright: a spec that states no goals, or draws no boundary between what the thing does and what it deliberately does not, is incomplete; an imperative sentence in spec content is a defect; and a scope limit justified only by "that's how the code currently works" is a defect too.

**lazy-experts.architect** — The architect reads an approved design spec — behavior already settled, never an open brief — and writes an architecture document: which modules exist, which way the dependencies point, what is public contract versus internal, what data has to migrate, and what it costs to callers that already exist. It grounds every boundary in the project's actual structure map before naming one — reading `docs/structure.md` if the job carries it, querying the `lazy-wiki.structure` skill otherwise, or reading the touched code directly when neither is available — and classifies every touched unit as a subsystem (its own public contract, state, and lifecycle) or plain service code, with the structure it proposes following that classification. Every dependency reversal, new abstraction, and change to stored data gets called out explicitly: a document that names modules without naming the direction between them is incomplete, and so is one that changes stored data without naming the migration. Dispatch it when the behavior is decided and only the shape of the code is still open; it stays out of both the designer's lane (what the system does) and the planner's (how the work is sequenced into tasks).

**lazy-experts.planner** — The planner reads a design spec and produces an ordered implementation plan at file-level granularity. Tasks run in an explicit sequence; every task names the exact files it touches before the steps begin, so the working-tree diff is predictable from the task header alone. Every plan includes a test command with expected output and a rollback procedure — a plan without both is, by the planner's own standard, incomplete. The planner translates decisions; it does not make them. When the spec leaves something underspecified, the planner raises a callout against the spec rather than guessing. No placeholder — "TBD", "handle errors appropriately" — ever appears in a finished plan.

**lazy-experts.implementer** — The implementer reads an ordered implementation plan and carries it out one task at a time, test-first. Code is a side-effect of its work; the dialogue about that work — progress, blockers, questions it cannot resolve from the plan — lives in the working journal it is dispatched against. The test-first iron law is non-negotiable: no production code without a failing test first. It completes the full red-green-refactor cycle and commits before moving to the next task. When a task is ambiguous or depends on something absent, it surfaces the open point in the journal and stops rather than guessing forward. The plan is a read-only input; the implementer never edits it.

**lazy-experts.data-implementer** — The data implementer takes an approved design of one entity — a race, a skill, an item, a rule table — and writes it directly into the product's own data files, in the schemas the project already uses. There is no plan document between the design and the work: the design is the specification. It reads the design whole before touching a file and looks at existing entities of the same kind before inventing a shape for its own, so field order, naming, and how optional values are spelled all match what the project already does. Where the schema cannot express what the design asks for, or the design leaves a value genuinely unsettled, it records the conflict as a decision candidate in its report and leaves the field out rather than inventing a number nobody decided. Every file it writes is checked against the repository's own validators before it calls the work finished. Pick it over the implementer when there's no plan to follow because the design itself is the specification, and over the tester when the job is producing data rather than validating it.

**lazy-experts.docs-writer** — The docs writer takes the approved design of one asset and writes what it delivers into the product's own user-facing documentation — in whatever place, format, and voice that documentation already lives. There is no plan document between the design and the work: the design is the specification. It reads the design whole before writing the first line, and reads the documentation that already exists before adding to it, since the product's own docs are the most reliable statement of where a topic belongs, how deep a page goes, and how the established voice sounds. The product's documentation conventions are the law — when the design asks for something the docs' shape cannot express, it records the conflict in its report rather than bending the docs into an approximation. Where the design leaves user-visible behavior genuinely unsettled, it leaves that passage unwritten and records the gap as a decision candidate rather than inventing a claim nobody made. It runs whatever check the project provides for its documentation — a linter, a link checker, a site build — before calling the work finished, and says so when no such check exists. Pick it over the implementer when the deliverable is documentation rather than code, and over the fiction writer when the text is user-facing product documentation rather than literary prose.

**lazy-experts.debugger** — The debugger investigates a bug to its root cause before changing anything. The fix is the last step, not the first. Investigation moves through four phases: read the error exactly and reproduce it consistently; compare a working example against the broken path, listing every difference; state one hypothesis at a time and test it minimally; then write a failing test that captures the bug, make one change, and verify. "While I'm here" edits bundled with the fix are forbidden. When a series of fix attempts do not converge, the debugger surfaces the architecture itself as the open point in the journal rather than trying yet another patch. It never pretends to understand something it does not.

**lazy-experts.reviewer** — The reviewer takes a change — a diff, a finished task, a feature branch — and returns ranked findings with evidence into the working journal. Every finding names the location (path and line), the cause, and the severity: critical (breaks correctness or safety), important (should be fixed before proceeding), minor (cleanup, defer). Before asserting a finding the reviewer verifies it against the actual codebase — a plausible-but-unchecked finding wastes the operator's time. The reviewer prefers small, frequent reviews over waiting for a large change to accumulate. It does not implement fixes; it describes the problem precisely enough that the fix is obvious and leaves the implementing to the implementer.

**lazy-experts.tester** — The tester establishes what actually works, what actually breaks, and exactly how to make it break again — for a change, a feature, or a suspicion. It never invents a testing setup: before writing or running anything, it surveys the mechanisms the repository actually ships — runners and their configs, test directories and fixtures, harnesses, Makefile / CI targets, project test skills — and builds only on what it verified exists. A test plan step naming an unconfirmed mechanism is, by its own standard, a defect. It executes plans literally, one step at a time, recording the actual result against the expected one — a step it could not run is recorded as blocked, never silently skipped or imagined green. Its bug reports carry environment, exact action, expected versus actual, and the verbatim decisive output. From any failure it drives toward the shortest deterministic reproduction, removing one variable at a time; a flaky repro is reported as flaky, with the observed rate, never rounded up to deterministic. It finds and documents defects; it never fixes them, edits existing tests, or makes "while I'm here" cleanups — the fix belongs to the implementer, the root cause to the debugger.

**lazy-experts.fiction-writer** — The fiction writer takes a brief or story outline and produces the actual prose: narrative text, dialogue, lyrical fragments. It owns the craft of the sentence and the scene — deliberate point-of-view and psychic distance, showing state through action and sense detail rather than naming an emotion, dialogue that works on two levels at once, sentence rhythm that varies with the moment. It writes against the default failure modes of machine prose: sentiment that skews warm regardless of context, grief that resolves within its own paragraph, endings that summarize the emotional meaning the reader just felt instead of landing on action or image. It stays out of story architecture entirely — what happens, to whom, in what order — treating that as an upstream decision; when the brief or outline is missing or contradictory, it raises a question against the document rather than inventing plot. Dispatch it for fiction deliverables only, never for technical documents.

## How they work together

The ten technical agents divide into two stages that connect at the implementation plan boundary — or, for data-only or documentation work, directly at the design boundary.

The design-time agents form a linear pipeline. Your routine dispatches the interpreter with the raw request and a protocol; the interpreter writes a structured brief. You review the brief, answer any callout questions by editing the file in your editor, and signal readiness. Your routine dispatches the designer with the resolved brief and a protocol; the designer writes a scoped design spec. When the work also needs a code-structure design — module boundaries, dependency direction, migration cost — your routine dispatches the architect with the approved spec and a protocol; the architect writes the architecture document. Your routine dispatches the planner with the spec (and the architecture document, when one exists) and a protocol; the planner writes the ordered task list, test plan, and rollback procedure that hands off to execution.

The execution-stage agents share the implementation plan as their common read-only input but operate more flexibly. The implementer works through the plan task by task in sequence. For data-only work — an entity fully described by an approved design rather than by a plan — the data-implementer writes the data files straight from that design, skipping the planner's task breakdown entirely. For documentation work, the docs-writer works the same way — writing straight from the approved design into the product's own user-facing documentation, with no plan document in between. The debugger, reviewer, and tester can be dispatched at any point — the reviewer after any task's output, the debugger whenever a failure surfaces, the tester whenever you need mechanism-grounded verification of what actually works — rather than waiting for the full plan to be complete. A common loop: your routine dispatches the implementer (or data-implementer, or docs-writer) for a task, then dispatches the tester against its output; if the tester's bug report can't be resolved from the plan or design alone, the debugger investigates, and the reviewer checks the resulting change before it lands.

Each of the ten technical agents is independently dispatchable. If you already have a well-formed brief and want to jump straight to design, dispatch the designer. If the behavior is already decided and only the code's shape is open, dispatch the architect directly with the design spec. If you already have an approved entity design and just need it written into data files, dispatch the data-implementer directly. If you already have an approved design and just need the user-facing documentation written, dispatch the docs-writer directly. If you want to review an existing change without running the full pipeline, dispatch the reviewer directly. If you just need a test plan against an existing feature, dispatch the tester directly. The ten-stage sequence is a convention, not a constraint.

The fiction writer stands apart from that pipeline entirely. It doesn't sit downstream of the interpreter, designer, architect, or planner — you dispatch it directly against whatever brief or outline your own workflow produces, and it hands back prose. Because it composes with the fiction-oriented domain aspects (sci-fi, fantasy) rather than the technical ones, and because `/lazy-experts.install` seeds it with the discipline aspect only (no tech-writing aspect — that aspect is for dry technical prose, the opposite of what the fiction writer produces), it never appears in the same specialist entry as the ten technical agents.

The only thing each agent requires from its dispatcher is the protocol document — the single source of truth for what it reads and what it writes. The agents themselves carry no hardwired I/O contract, which is what makes it possible to compose them with domain aspects without the agents needing to know about each other.

## Where this fits

- Run `/lazy-core.agent-models` to adjust which model tier each agent uses. The implementer, data-implementer, docs-writer, debugger, reviewer, and tester have Bash access and perform heavier work than the design-time quartet (interpreter, designer, architect, planner); the fiction writer defaults to the highest tier as well, since prose quality benefits most from the strongest model. You may want to route any of these to a different tier.
- The **aspects** block composes domain knowledge (e.g. `lazy-experts.claude-plugin-aspect`, `lazy-experts.game-dev-aspect`) into the ten technical agents, and genre knowledge (e.g. `lazy-experts.sci-fi-aspect`, `lazy-experts.fantasy-aspect`) into the fiction writer, via your `lazy.settings.json[experts]` entry. Aspects shape how an agent interprets, designs, architects, plans, implements, debugs, reviews, tests, documents, or writes — they do not change which agent runs or what protocol it follows.
- The **composition** block shows how to wire a concrete specialist — pairing one agent with one or more aspects — in `lazy.settings.json[experts]`.
- The dispatching routine is not part of this plugin. You bring your own routine (consumer-side), or a future `lazycortex-specs` integration dispatches these agents as part of a spec workflow.

## The agent lineup

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  dispatchingRoutine["Dispatching Routine"]

  subgraph designTime["Design-time"]
    interpreter["Interpreter"]
    designer["Designer"]
    architect["Architect"]
    planner["Planner"]
  end

  subgraph executionStage["Execution-stage"]
    implementer["Implementer"]
    dataImplementer["Data Implementer"]
    docsWriter["Docs Writer"]
    debugger["Debugger"]
    reviewer["Reviewer"]
    tester["Tester"]
  end

  subgraph literary["Literary"]
    fictionWriter["Fiction Writer"]
  end

  interpreter -->|gap-free brief| designer
  designer -->|design spec| architect
  architect -.->|architecture doc optional| planner

  dispatchingRoutine -.->|protocol| interpreter
  dispatchingRoutine -.->|protocol| designer
  dispatchingRoutine -.->|protocol| architect
  dispatchingRoutine -.->|protocol| planner
  dispatchingRoutine -.->|protocol| implementer
  dispatchingRoutine -.->|protocol| dataImplementer
  dispatchingRoutine -.->|protocol| docsWriter
  dispatchingRoutine -.->|protocol| debugger
  dispatchingRoutine -.->|protocol| reviewer
  dispatchingRoutine -.->|protocol| tester
  dispatchingRoutine -.->|protocol| fictionWriter

  planner -.->|implementation plan| implementer
  designer -.->|approved design| dataImplementer
  designer -.->|approved design| docsWriter

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff

  class dispatchingRoutine entry
  class interpreter action
  class designer action
  class architect action
  class planner action
  class implementer action
  class dataImplementer action
  class docsWriter action
  class debugger action
  class reviewer action
  class tester action
  class fictionWriter action
```
