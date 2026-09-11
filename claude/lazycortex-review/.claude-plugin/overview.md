## Why this plugin

Reviewing a long markdown document with several expert lenses gets messy fast: whose turn it is, which sections are still pending, what an approve should do to the body, what to do when the file comes back half-broken. Doing it by hand in Claude Code means re-pasting the doc, re-running each expert, and re-tracking approval state in your head.

`lazycortex-review` puts one markdown file into an unattended review loop. You opt the doc in, define a class (paths + expert chain + section assignments), and from then on every decision belongs to `review.coordinator` — an LLM persona that wakes on a commit, reads the document and its own prose playbook, and makes the single move that wake calls for. It acts only through a closed set of Python verbs: `parse-note` reads the structure, `set-key` is the one door into frontmatter, `paint-banner` repaints the gesture banner, `collect-job` lands a finished expert payload. There is no state machine and no dispatcher — a new edge case is a new paragraph in the playbook, not a code change.

The split is deliberate: judgement in prose, mechanics in Python. The verbs never decide anything, and the coordinator never hand-edits the markup a verb owns.

## Who it's for

- **Spec / RFC authors** who want a multi-pass review (a designer reads structure, a developer reads implementability, a security lens reads threats) without copy-pasting each pass.
- **Engineering managers** running async doc-review loops — every transition is one commit, and the document carries its own state in frontmatter.
- **Plugin authors** who need a document to travel a review loop and come out with a machine-readable verdict a downstream routine can act on.

## How the loop turns

Nothing polls the document. The coordinator wakes on exactly four triggers: a commit turning `review_active` true (review entry, from any author — another plugin's bot opening a doc counts), an expert job finishing, a non-empty `> [!todo] #review/command` callout, and a commit by an identity outside the review system's own (an operator edit — a ticked option under a `[!question] #review/question` callout arrives exactly this way, and is not a trigger of its own). Three of the four are resolved by the `lazy-review.coordinator-watch` git-watch routine from the commit that just landed; the job-done wake is raised in the runtime marker sidecar and queues the coordinator directly.

The second routine, `lazy-review.collect`, is the postman: on its own interval it sweeps finished expert jobs, and it lands nothing and commits nothing. For a job whose outcome `collect-job` consumes it clears the runtime `active_job` marker, raises the job-done wake in its place, and dispatches the coordinator — the payload is still sitting in the job queue when the wake arrives, so the coordinator's own first move is `collect-job --no-commit`, and one commit carries the landed payload together with everything else the wake wrote. The postman carries no scheduling judgement of its own — a dead job, or one reporting an error, is left exactly as found for the coordinator to decide about. The third, `lazy-review.sanitize`, is a daily deterministic sweep that repairs the loop's stuck-state cases: a lost writer wake, an orphaned review, markers left behind on a document that no longer exists.

## Scenarios

- *"This RFC needs three pairs of eyes — designer, developer, security."* — `/lazy-review.configure` defines a class for `docs/specs/*.md` with three writers, then `/lazy-review.start <file>` opts the file in; the entry commit wakes the coordinator and the first writer round is dispatched.
- *"What state is this document in?"* — `/lazy-review.status <file>` prints one-line JSON with the round, the approval flags, the per-section owners, and the current banner state.
- *"The reviewer left a broken markdown block."* — the coordinator dispatches the `lazy-review.doc_doctor` agent for mechanical damage; for anything it cannot repair with confidence it writes a `[!question]` with concrete options instead of guessing.
- *"Redo the last round against my rewrite."* — drop the instruction into a `> [!todo] #review/command` callout. The coordinator unfolds it into a numbered mini-plan in the same callout, works through it, and files the finished block into `# History`.
- *"Round four was final — close it out."* — `/lazy-review.finalize` folds every edit-annotation marker into the final text, strips the banner, gesture checkboxes, and system callouts, and stamps `review_result` so a downstream apply gate can read the verdict.

## Blocks

- **review-cycle** — Run a multi-expert document review from opt-in to close-out: start a file, submit pre-authored content, check state, stop a cycle, and finalize the approved document. Members: lazy-review.start, lazy-review.submit, lazy-review.status, lazy-review.stop, lazy-review.finalize.
- **install-and-audit** — Bootstrap the plugin in a repo, define review classes and their expert chains, and audit the review config. Members: lazy-review.install, lazy-review.configure, lazy-review.audit.

## Walkthroughs

- **run-a-document-review** — Take one document through a full review cycle from opt-in to finalize. Path: lazy-review.start → lazy-review.status → lazy-review.finalize.

## Requirements

- **Claude Code** with plugin support.
- **`lazycortex-core`** installed and configured — the expert runtime, the job queue, the routine daemon, and the `lazy.settings.json` schema all live there. Hard dependency, declared in `plugin.json`.
- **A running core daemon** — all three routines are daemon-driven; with the daemon off the loop never wakes.
- **git** — every transition is one commit, and a commit is how each wake reaches the coordinator.
- **Python 3.12+** — the verbs are pure Python and follow the marketplace's tech-stack floor.

## Quick start

1. Install and configure `lazycortex-core` first (`/lazy-core.install`), and make sure its runtime daemon is running.
2. Run `/lazy-review.install` inside the repo. Seeds the `review` settings block, the coordinator's own expert identity, and the `lazy-review.collect` + `lazy-review.coordinator-watch` + `lazy-review.sanitize` routine trio; creates `.experts/.jobs/` and the log tree; installs the review callout styling into the vault when there is one.
3. Run `/lazy-review.configure` to define your first review class — the paths glob, the main-writer chain, any validation or terminal section owners, and the edit-marker style.
4. Run `/lazy-review.start <file>` to opt one doc in. The entry commit wakes the coordinator on the next watch tick.
5. Read what the writers propose, answer questions by ticking an option, tick approve when the document is right. When the post-approve barriers have run, `/lazy-review.finalize` seals it.

Day-to-day commands once configured:

```
/lazy-review.start    # opt a doc in (opens at the writing round)
/lazy-review.submit   # opt a doc in whose content is already written
/lazy-review.status   # one-line state
/lazy-review.stop     # opt a doc out (preserves round + history)
/lazy-review.audit    # validate the review block in lazy.settings.json
/lazy-review.finalize # strip the review markup, stamp the verdict, commit
```
