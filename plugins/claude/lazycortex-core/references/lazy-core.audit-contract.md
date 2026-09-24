---
description: "The shape every `<namespace>.audit` skill follows — read-only execution, one severity vocabulary, and a finding that carries its own repair route."
---
# audit-skill contract

Every lazycortex plugin ships at most one audit skill, named `<namespace>.audit`. A plugin maintainer authors it; `lazy-core.doctor` Phase 3 delegates to it and folds its findings into one merged table, and an operator reads that table. Because those findings are merged across plugins, they must be comparable: the same severity words, the same read-only guarantee, and the same finding shape. This contract states that shape. The checks themselves stay in each plugin's own audit — nothing here says what to look for.

---

## 1. What an audit skill is

An audit skill is a `SKILL.md` at:

```
plugins/claude/<plugin>/skills/<namespace>.audit/SKILL.md
```

`<namespace>` is the plugin's own dot-namespace (`lazy-core`, `lazy-wiki`, `lazy-spec`, …). An operator invokes it as `/<namespace>.audit`; `lazy-core.doctor` Phase 3 reaches it through the availability probe described there. A skill declares conformance by naming this file in its body instead of restating the severity vocabulary.

---

## 2. Required structure

### 2.1 Read-only execution

An audit reads and reports. It changes no configuration and asks the operator nothing. It carries no apply-style flag and runs no fix loop of its own.

It writes no file at all: an audit's report is its return value, and it does not opt into `lazy-log.logging`.

Repair belongs to a separate run the operator starts: the plugin's own install or fix skill, or the per-finding loop in `lazy-core.doctor`. An audit names that run inside the finding; it never performs it.

### 2.2 Severity vocabulary

Exactly four words, and no others:

- `PASS` — the check ran and found nothing wrong.
- `INFO` — a measurement or an observation that calls for no action.
- `WARN` — a divergence: something drifted, is stale, or is advisory.
- `FAIL` — a violation: a structural defect or an unresolvable reference.

### 2.3 Finding shape

A finding is one line carrying four things: the severity word, the artifact or path it concerns, what is wrong, and the repair route. The repair route stands in that same line.

An audit has no separate recommendations section at the end of its report. A route that applies to a whole class of findings is repeated in each line of that class, never lifted out of them.

### 2.4 No estimate of effect

A finding states what is, never what acting on it would save or change. An audit measures the current state; the difference before and after a repair shows up in the next run.

A measurement of the current state is not an estimate and stays allowed. The size of what loads today is a fact; the size freed by a repair nobody has run is not.

---

## 3. Schema

A finding line, as rendered into the report:

```
[<SEVERITY>] <path-or-artifact> — <what is wrong>; <repair route>
```

The summary line closing a report or one of its sections:

```
audit: <PASS|WARN|FAIL> (<n> findings)
```

The verdict is the highest severity present, with `INFO` counted as `PASS`.

---

## 4. Versioning

This contract carries no version field and is edited in place for clarifications. An audit skill declares conformance by naming this file, so a clarification reaches every conforming skill at once.

Adding a check, or a new output within the four severity words, is backward-compatible. Changing the severity vocabulary or the finding shape is not: such a change ships as a new contract file, and the audit skills migrate to it.

---

## 5. Validation expectations

`lazy-core.audit` enforces, over every `plugins/claude/*/skills/*.audit/SKILL.md` in scope:

- **Severity vocabulary** — a severity word outside the four is `FAIL`.
- **Read-only execution** — a body that writes any file other than its own run log, declares an apply-style flag, or contains an `AskUserQuestion` is `FAIL`.
- **No separate recommendations section** — a heading naming recommendations, saving opportunities, or repair routes as its own report section is `WARN`. A section the skill declares an internal lookup, never rendered to the operator, is exempt.
- **Contract declared** — an audit skill that does not name this contract is `WARN`.

Findings surface in the `lazy-core.audit` report and, through delegation, in `lazy-core.doctor` Phase 3.
