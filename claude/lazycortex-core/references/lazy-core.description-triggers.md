# Description triggers — how to write and judge a `description:`

Companion to `lazy-core.skill-writing § 8` and `lazy-core.agent-writing § 1`. Read before authoring a skill or agent description, and before ruling on a batch of them in `lazy-core.audit`.

## Why the field is not documentation

`description:` is the routing table. Claude Code shows the model a list of skill names and descriptions and nothing else; the same is true of `subagent_type` selection for agents. Whatever is not in the description does not exist at the moment of choosing. A description that narrates internals — how many subagents it dispatches, which primitive it wraps, what its output looks like — spends the entire budget on facts the model does not need until *after* it has already chosen. The result is a working skill nobody invokes: the model does the job by hand, badly, and the skill's author concludes the model "ignores" it.

The body is where mechanism belongs. It is read only after selection, and it has no size pressure.

## The three trigger shapes

Every description opens with one of these. Pick by who invokes the artifact.

### 1. User-request trigger

For anything a user's own words should be able to summon.

```
Use when <the request or situation that should fire it>.
```

Name the shapes a user actually types. "Use when the user asks why something is built the way it is, where a topic is described, or what relates to what" beats "associative Q&A over the wiki graph", because the first contains the words the user will use.

### 2. Caller trigger

For primitives, sub-steps, and wrappers with exactly one legitimate caller.

```
Dispatched by /<skill> as <step>; not for direct use.
```

This *is* a trigger. It tells the router the artifact is spoken for, which stops it from being offered for unrelated requests — the failure mode a mechanism-only primitive description actually causes. Naming the caller also gives a maintainer the call graph for free.

### 3. Operator-verb trigger

For slash-invoked utilities where the operator names the verb: install, uninstall, configure, unlock, status, audit.

```
Run when the operator asks to <verb>.
```

Do not stop at the verb the filename already carries. `lazy-wiki.install` is not summoned by "install" alone — it is summoned by "set up the wiki here", "why doesn't `/wiki.query` work", "the wiki rule isn't in my repo". Put those in.

## After the trigger

Mechanism follows, and earns its place only by **disambiguating from a sibling whose trigger overlaps**. Two audit skills, two install skills, two create-* skills in the same namespace must each say in the description what separates them; a skill with no near-neighbour says nothing about mechanism at all.

One clause about a load-bearing property is fair even without a sibling — "so the topic index never enters the calling context" tells the model this is cheap to call. A paragraph is not.

## What does not count as a trigger

- **Purpose restated.** `Use to resolve a dependency` names what the skill is for. The model already inferred that from the name. `Use when a spec names a dependency that must resolve before the gate can flip` names when to reach for it.
- **A condition that cannot be evaluated without doing the work.** `Use when the wiki covers the question` requires opening the wiki to find out whether to open the wiki. Circular conditions read as triggers and function as nothing.
- **A feature list of the skill's own output.** "Shows sizes, loading behaviour, optimization opportunities, preamble presence, …" describes a report, not an occasion.
- **`<example>` blocks instead of a trigger sentence.** Examples after the trigger are good — they carry request shapes verbatim. Examples doing the trigger's whole job leave the model matching on a transcript.

## Worked rewrites

| Before | After |
|---|---|
| `Associative Q&A over the wiki graph. Thin dispatcher: a per-scope seeker subagent picks entry points from topics.md…` | `Use when a question needs material the wiki curates — 'why is it built this way', 'where is X described', 'what relates to Y'. Run it BEFORE grepping a covered scope.` |
| `Wraps expert_runtime.cancel_job.` | `Dispatched by /lazy-expert.list-jobs when the operator picks a job to cancel; not for direct use.` |
| `Bootstrap the plugin for the current project. Creates the template dir, syncs the rule, seeds settings…` | `Run when the operator asks to set up the wiki in a repo, or when wiki skills fail because the rule or settings section is missing.` |
| `Generic reviewer expert — reviews a change and returns ranked findings into a working journal.` | `Use when a change needs an independent correctness review before it lands. Dispatched by the expert runtime for the `reviewer` expert; also dispatchable directly with a file list.` |

## Judging a batch (audit)

Read the description alone, without the file's name or body, and ask: *given only this line and a user request, could I decide whether to fire it?* If the answer needs the body, it is `WARN`. Phrasing is free — a description that states its occasion in its own words passes without matching any template above.

Absent `description:` is `FAIL`, not `WARN`.
