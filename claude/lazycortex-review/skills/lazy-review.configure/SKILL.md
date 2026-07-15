---
name: lazy-review.configure
description: "Wizard to add a review class to .claude/lazy.settings.json — collects path globs, main / validation / terminal / history expert assignments under the new experts schema. Read-first: every value already persisted in lazy.settings.json is honoured silently and never re-asked. Strict one-question-per-turn via AskUserQuestion."
allowed-tools: Read, Edit, Write, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet, Bash(python3 *), Bash(mkdir -p *), Bash(date *)
---
# lazy-review.configure

Interactive wizard. Adds (or appends to) `review.classes` in `.claude/lazy.settings.json` for the consumer's first or next document class — globs, writer groups, sections, marker style — all of which are genuine project config that cannot be derived. The wizard is **read-first**: every value already persisted in the settings file is honoured silently and the matching question is skipped; only values with nothing on record are asked. Calls the configure pipeline one question at a time via `AskUserQuestion`.

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
2. **Mark each task `in_progress` on enter and `completed` on exit.** Outcomes: `verified` / `collected` / `read-from-record` / `picked` / `written` / `audited` / `report-emitted`.
3. **Do not reach the Report step until every prior task is `completed`.**

## Read-first principle (applies to every question below)

Every collecting phase first inspects the in-memory settings loaded in Phase 1. If the value the phase would ask for is **already persisted**, skip the `AskUserQuestion` and reuse the recorded value silently — state `read-from-record`. Ask **only** when nothing is on record. This makes the wizard idempotent and quiet on re-run: a fully-configured class is re-validated and re-audited without a single prompt. The questions below collect genuine project config (which globs enter the review loop, which experts play which role, where sections sit, which marker style) — none of it is derivable, so the wizard keeps every question, but each is gated on the absence of a persisted answer.

## Phase 1 — Verify install + load settings

`Read` `.claude/lazy.settings.json`. If absent, abort with the message *"run `/lazy-review.install` first"* and stop. Otherwise hold the parsed object in memory for the wizard.

Outcome: `verified`.

## Phase 2 — Collect class paths

If `review.classes` already holds a class whose paths the operator means to extend, reuse its `paths` silently (read-first). Otherwise `AskUserQuestion`: *"What glob(s) does this class match?"* — operator types a comma-separated list (e.g. `requests/*.md, docs/specs/*.md`). Split on commas and trim.

Outcome: `collected` (asked) or `read-from-record` (reused a persisted class's paths).

## Phase 3 — Collect writer groups

Pipeline-фазы (главные писатели и историк) и секционные writer'ы собираются отдельно. Каждый question-блок — отдельный `AskUserQuestion` call, и каждый пропускается, если значение уже записано в in-memory settings (read-first).

### 3a — Main writers

Если `experts.main` уже заполнен — переиспользуй его молча (read-first). Иначе `AskUserQuestion` (multi-select из реестра экспертов в корневом `experts:` каталоге; preserve order): *"Кто будет главными писателями документа (могут быть несколько; запускаются цепочкой)?"*

Добавь в in-memory settings: `experts.main = [{"name": ..., "repo": ".", "role": "main"}]` (один объект на каждый выбранный экспертный профиль; `role` — свободная строка, которую агент получит в `request.json.role`).

### 3b — Historian

Если `experts.history` уже записан — переиспользуй молча (read-first). Иначе `AskUserQuestion` (single-select из реестра; default `review.historian`): *"Кто будет историком (пишет # History секцию)?"*

Добавь: `experts.history = {"name": ...}`.

### 3c — Sections (loop)

Если секционные writer'ы (`experts.validation` / `experts.terminal`) уже записаны для этого класса — переиспользуй их молча и пропусти цикл (read-first). Иначе цикл по секциям — каждая итерация строго через отдельные `AskUserQuestion` вызовы:

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

Outcome: `collected` (asked) or `read-from-record` (every writer group reused from a persisted class).

## Phase 4 — Pick edit_marker_style

Если `review.edit_marker_style` уже записан — переиспользуй молча (read-first). Иначе `AskUserQuestion`: four options — `simple`, `diff`, `criticmarkup`, `html`. Write the chosen value into `review.edit_marker_style`.

Outcome: `picked` (asked) or `read-from-record` (reused the persisted style).

## Phase 5 — Write back + run /lazy-review.audit

Serialize the updated settings via `Write` to `.claude/lazy.settings.json`. Then normalize the `lazy-review.scan` routine — but only when the routine is present. The daemon-gated routine may be absent (a daemon-disabled project, per `/lazy-review.install` Step 2 outcome `skipped-daemon-disabled`); if `routines["lazy-review.scan"]` is missing, skip this normalization silently — there is no scan loop to feed. When present: (1) coarsen each of this class's `paths` globs — take the longest leading wildcard-free directory prefix; if the remaining tail is exactly `*.md`, keep the glob as-is; otherwise emit `<prefix>/**/*.md` (a literal file path coarsens via its parent dir; no literal prefix → `**/*.md`) — and union the coarse masks into the routine's `paths`. The emitted `**` mask is matched anchored at the repo root, so coarsen the REPO-ROOT-RELATIVE form of the glob — if this class's `paths` globs are relative to a content root (e.g. spec-plugin classes are relative to `spec.vault_root`), prepend that root before taking the prefix; a mask without its content-root prefix matches nothing; (2) dedupe and drop any mask subsumed by a broader one (`<p>/**/*.md` covers every mask whose prefix sits under `<p>` and every legacy filename-suffixed mask under `<p>` — remove those); (3) inside `filter.frontmatter` set `review_active` to `{"in": [true], "not_in": []}` (drop the legacy `null` leg — only opted-in files spawn a per-file dispatch; opt-in stamps `review_active: true` atomically and non-active files are no-op skips); (4) set `interval_sec` to `60` when it still carries the legacy `5` (coarse scans run at minute cadence; an operator-chosen value other than 5 stays untouched). Class `paths` stay precise: they are the dispatch-time routing that the coarse sieve deliberately delegates to. This rewrite is idempotent — re-running it on an already-normalized routine changes nothing. Then invoke `/lazy-review.audit` and surface its findings.

Outcome: `written`.

## Report

One line per task with its outcome word, followed by `configured: <paths>; experts={main: <count>, history: <count>, validation: <count>, terminal: <count>}; style=<style>; audit=<level>`.

## Failure modes

- **Phase 1 aborts on missing settings** — operator hasn't installed → run `/lazy-review.install` first, then re-run.
- **section-id fails validation loop** — operator keeps entering a string that doesn't match `^[a-z][a-z0-9_-]*$` or collides with an existing id → wizard re-asks until a valid unique id is provided.
- **Phase 5 audit reports FAIL** — wizard wrote inconsistent state (e.g. section-id in `validation` or `terminal` not matching the allowed alphabet, or expert name missing from top-level experts dict) → re-enter the wizard and complete the missing pieces.
