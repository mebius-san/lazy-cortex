---
name: lazy-review.configure
description: "Wizard to add a review class to .claude/lazy.settings.json — collects path globs, main / validation / terminal / history expert assignments under the new experts schema. Strict one-question-per-turn via AskUserQuestion."
allowed-tools: Read, Edit, Write, AskUserQuestion, Bash(python3 *), Bash(mkdir -p *), Bash(date *)
---
# lazy-review.configure

Interactive wizard. Adds (or appends to) `review.classes` in `.claude/lazy.settings.json` for the consumer's first or next document class. Calls the configure pipeline one question at a time via `AskUserQuestion`.

Prerequisite: `/lazy-review.install` has run (the settings file exists).

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step.

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. Canonical titles:
   - `Phase 1 — Verify install + load settings`
   - `Phase 2 — Collect class paths`
   - `Phase 3 — Collect writer groups`
   - `Phase 4 — Pick edit_marker_style`
   - `Phase 5 — Write back + run /lazy-review.audit`
   - `Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** Outcomes: `verified` / `collected` / `picked` / `written` / `audited` / `report-emitted`.
3. **Do not reach the Report step until every prior task is `completed`.**

## Phase 1 — Verify install + load settings

`Read` `.claude/lazy.settings.json`. If absent, abort with the message *"run `/lazy-review.install` first"* and stop. Otherwise hold the parsed object in memory for the wizard.

Outcome: `verified`.

## Phase 2 — Collect class paths

`AskUserQuestion`: *"What glob(s) does this class match?"* — operator types a comma-separated list (e.g. `requests/*.md, docs/specs/*.md`). Split on commas and trim.

Outcome: `collected`.

## Phase 3 — Collect writer groups

Pipeline-фазы (главные писатели и историк) и секционные writer'ы собираются отдельно. Каждый question-блок — отдельный `AskUserQuestion` call.

### 3a — Main writers

`AskUserQuestion` (multi-select из реестра экспертов в корневом `experts:` каталоге; preserve order): *"Кто будет главными писателями документа (могут быть несколько; запускаются цепочкой)?"*

Добавь в in-memory settings: `experts.main = [{"name": ..., "repo": ".", "role": "main"}]` (один объект на каждый выбранный экспертный профиль; `role` — свободная строка, которую агент получит в `request.json.role`).

### 3b — Historian

`AskUserQuestion` (single-select из реестра; default `historian`): *"Кто будет историком (пишет # History секцию)?"*

Добавь: `experts.history = {"name": ...}`.

### 3c — Sections (loop)

Цикл по секциям — каждая итерация строго через отдельные `AskUserQuestion` вызовы:

1. `AskUserQuestion`: *"Добавить ещё одну секцию?"* Варианты: «Добавить», «Готово».
2. Если «Готово» — выйти из цикла.
3. Если «Добавить»:
   a. `AskUserQuestion`: *"К какому типу относится секция?"* Варианты:
      - **`validation`** — post-approve проверка; секция блокирует finalize при наличии content'а (revert-to-main); стирается в финале.
      - **`terminal`** — post-approve операторский выбор; не блокирует finalize; переживает финализацию.
   b. `AskUserQuestion` (свободный текст): *"Введи section-id (стабильный идентификатор, формат `^[a-z][a-z0-9_-]*$`, например `final_check` или `routing`)"*. Валидация на месте: проверь регулярное выражение `^[a-z][a-z0-9_-]*$`. Если не подходит — переспроси. Проверь уникальность section-id в пределах класса (через обе umbrella'ы — `validation` и `terminal`). Если уже есть — переспроси.
   c. `AskUserQuestion` (свободный текст): *"Заголовок H1 для этой секции (произвольная строка, например `Final check` или `Маршрутизация`)"*.
   d. `AskUserQuestion`: *"Где разместить секцию относительно свободного тела оператора?"* Варианты:
      - **`top`** — секция показывается ВЫШЕ свободного тела (после баннера/статуса).
      - **`bottom`** — секция показывается НИЖЕ свободного тела (перед `# History`).
   e. `AskUserQuestion` (single-select из реестра): *"Кто пишет в эту секцию?"*.
   f. Добавь в in-memory settings: `experts.<umbrella>.<section-id> = {"name": ..., "repo": ".", "role": <umbrella>, "section": <заголовок из шага c>, "position": <top|bottom>}` (`role` по умолчанию — имя umbrella'ы: `validation` или `terminal`; операторы, ведущие специализированный персона-роутинг, могут заменить значение на любую другую строку — агент получит её в `request.json.role`).
4. Goto 1.

Outcome: `collected`.

## Phase 4 — Pick edit_marker_style

`AskUserQuestion`: four options — `simple`, `diff`, `criticmarkup`, `html`. Write the chosen value into `review.edit_marker_style`.

Outcome: `picked`.

## Phase 5 — Write back + run /lazy-review.audit

Serialize the updated settings via `Write` to `.claude/lazy.settings.json`. Then sync the `lazy-review.scan` routine's `paths:` list to the union of every `review.classes[].paths` glob in this file (dedupe, preserve insertion order). The runtime daemon's md-scan routine is what fires per-file dispatches at runtime, so the routine's `paths:` glob list MUST be kept in sync with the class definitions — otherwise the daemon never sees the new class's files. Then invoke `/lazy-review.audit` and surface its findings.

Outcome: `written`.

## Report

One line per task with its outcome word, followed by `configured: <paths>; experts={main: <count>, history: <count>, validation: <count>, terminal: <count>}; style=<style>; audit=<level>`.

## Failure modes

- **Phase 1 aborts on missing settings** — operator hasn't installed → run `/lazy-review.install` first, then re-run.
- **section-id fails validation loop** — operator keeps entering a string that doesn't match `^[a-z][a-z0-9_-]*$` or collides with an existing id → wizard re-asks until a valid unique id is provided.
- **Phase 5 audit reports FAIL** — wizard wrote inconsistent state (e.g. section-id in `validation` or `terminal` not matching the allowed alphabet, or expert name missing from top-level experts dict) → re-enter the wizard and complete the missing pieces.
