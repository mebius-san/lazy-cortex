---
name: <aspect-short-name>
description: <one-line — what behavior layer this aspect adds and to which experts it composes>
---
# <aspect-short-name> aspect

<One paragraph: what behavior this aspect adds on top of an expert's protocol-defined work. Aspects shape behavior; protocols define request/response contracts. An aspect is composed into the system context of every expert whose `lazy.settings.json[experts][<expert>].aspects[]` lists `<plugin>:<name>-aspect`.>

## Purpose

<What does carrying this aspect change about how the expert acts? One paragraph.>

## Side-effect rules

The universal expert-runtime contract forbids writes outside the job dir. Aspects MAY carve out exceptions.

- The expert MAY write to: <enumerate paths outside the job dir, e.g. `.memory/<self>/` via `<plugin>:<skill>`>.
- The expert MUST NOT write to: <enumerate forbidden paths beyond the standard "outside job dir" rule>.

## Kind / role / outcome additions (optional)

If this aspect introduces new universal `kind` values, `role` strings, or `outcome` enum values that any composing expert must handle, list them here. Otherwise: state "No additions."

- **Kinds added**: <kind-1> — <description>; <kind-2> — <description>.
- **Roles added**: <role-1> — <description>.
- **Outcomes added (per kind)**: <kind-1> → <outcome-1>, <outcome-2>.

## Discovery and tooling

| Question | Action |
|---|---|
| <question 1> | <Glob/Read path or skill> |
| <question 2> | <Glob/Read path or skill> |

Skills / CLIs available to the expert: <list, with short purpose>.

## Obligations

Explicit "you must …" statements that bind every expert composing this aspect. Each obligation is a one-liner; group under sub-headings only if there are more than five.

- Before <X>, do <Y>.
- When <kind=…>, write <Z>.
- Never <forbidden action>.

<!--
Authoring notes (delete before saving):

- Placement: `<plugin>/references/<name>-aspect.md`. The suffix triggers this template via `lazy-core.scaffold`.
- Reference key: `<plugin>:<name>-aspect` in `lazy.settings.json[experts][<expert>].aspects[]` resolves via `reference_resolver.resolve(..., category="aspects", ...)`.
- Versioning by filename: incompatible changes ship as a new file (e.g. `<name>-v2-aspect.md`); the old file stays until consumers migrate. No version field, no version syntax in reference strings.
- Contract source of truth: `claude/lazycortex-core/references/lazy-core.expert-aspects-contract.md` — read it before authoring a new aspect.
- Worked example: `claude/lazycortex-core/references/lazy-memory.persona-aspect.md`.
-->
