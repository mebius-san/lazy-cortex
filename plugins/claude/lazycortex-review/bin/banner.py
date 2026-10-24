"""
Top-of-body status callout (the "banner").

Pure-function module. Recognises and renders the banner states
defined by the spec § Top-banner. The state machine owns the *when*
of repaints; this module owns the *what*.

Key invariants enforced here:

- Recognition keys on the `#review/<tag>` token in the callout's
  first line — never on the `[!hint]` / `[!caution]` / `[!success]`
  marker. Operator-authored callouts without the tag are invisible to
  this module.
- :func:`desired_state` for `OPERATOR_COMMITTED` and
  `CHAIN_IN_PROGRESS` dispatch states always returns
  :attr:`State.IN_PROCESS`: the operator's hand-off is unconditional
  ("Waiting" rules until the chain exhausts and is ready to hand back").
- :func:`render` for :attr:`State.READY` is the SOLE place the
  approval checkboxes appear. Every other state never carries one.
- The ready banner carries ONE approval checkbox when the autorun stopped clean or no validation round has run, and
  the three gestures only when a validation round has run and the autorun did not stop clean.
- Banner is anchored above the first H1 of the body. Mid-body banner-
  shaped callouts (stale, mis-pasted) are ignored by :func:`extract`.
"""
from __future__ import annotations

from typing import TypeVar

import enum
import re

# waiver: `import parser` is the local sibling parser.py, not the removed stdlib `parser` module
import parser as _parser  # pylint: disable=import-error,deprecated-module
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from keys import LANG_EN as _LANG_EN, AutorunState, Bucket, Phase  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# One entry of a per-language string table — a template string, or a table of them
_EntryType = TypeVar("_EntryType")


# ----------------------------------------------------------- enums


class State(enum.Enum):
  """
  Banner state rendered at the top of a review document.

  Callers read this to determine what the current document banner communicates to the operator
  and drive banner-repaint decisions.

  Attributes:
    IN_PROCESS: Agents are working; the operator waits for the chain to hand back control.
    ACTION_NEEDED: An open question or concern blocks progress until the operator responds.
    READY: The document is ready for the operator to approve.
    FINALIZING: The document has been approved and is being finalized.
  """

  # Agents are working; the operator waits for the chain to hand back control.
  IN_PROCESS = "in-process"
  # An open question or concern blocks progress until the operator responds.
  ACTION_NEEDED = "action-needed"
  # The document is ready for the operator to approve.
  READY = "ready"
  # The document has been approved and is being finalized.
  FINALIZING = "finalizing"


class DispatchState(enum.Enum):
  """
  Phase of the current dispatch cycle for a review document.

  Callers use this to determine whether agents are still working or whether the chain has
  returned control to the operator.

  Attributes:
    OPERATOR_COMMITTED: The operator just committed and the chain has not yet picked up work.
    CHAIN_IN_PROGRESS: An agent is currently working on the document.
    CHAIN_EXHAUSTED: The chain has drained and control has returned to the operator.
  """

  # The operator just committed and the chain has not yet picked up work.
  OPERATOR_COMMITTED = "operator-committed"
  # An agent is currently working on the document.
  CHAIN_IN_PROGRESS = "chain-in-progress"
  # The chain has drained and control has returned to the operator.
  CHAIN_EXHAUSTED = "chain-exhausted"


# --------------------------------------------------------- gestures


# The machine kinds of the ready banner's approval gestures, in the fixed order its checkbox
# lines render; a reader assigns each checkbox its kind by position, never by label text, so
# every language's banner yields the same kinds and a one-checkbox banner yields the first.
READY_GESTURE_KINDS: tuple[str, ...] = ( "approve", "approve-autorun", "approve-skip-validation" )


# --------------------------------------------------------- tag / shape


_TAG_TO_STATE = {
    "in-process": State.IN_PROCESS,
    "action-needed": State.ACTION_NEEDED,
    "ready": State.READY,
    "finalizing": State.FINALIZING,
}

_FIRST_LINE_RE = re.compile(r"^>\s*\[!\w+\][^#\n]*#review/([a-z-]+)\s*$")


# ------------------------------------------------------------ extract


def extract(body: str) -> State | None:
  """
  Find the banner above the first H1 of `body` and return its `State`, or `None` when no banner is present.

  Mid-body callouts (anything after the first H1) are scaffold logs or stale snapshots, never the banner.

  Guarantees:
    - Recognition depends only on the `#review/<tag>` token in the callout's first line; the
      callout's marker style (`[!hint]`, `[!caution]`, etc.) is never read.
    - Only the region above the document's first top-level heading is searched; a
      banner-shaped callout appearing later in the body is never recognized.

  Args:
    body: Full document text to search.

  Returns:
    The `State` encoded in the banner tag, or `None` if no banner is found above the first H1.
  """

  # Contract:
  # Recognition MUST depend only on the `#review/<tag>` token in a line's content, never on
  # the callout's marker style.

  # Contract:
  # Only the region above the document's first top-level heading MUST be searched; a
  # banner-shaped line appearing later in the body MUST NEVER be recognized.

  # Domain(review.markup):
  # # Banner recognition by tag, not by callout style
  # The status banner at the top of a review document is identified by its `#review/<tag>`
  # token, never by the surrounding callout's visual style. An operator-authored callout in the
  # same visual style but without the tag is not read as a banner at all. Only the region above
  # the document's first top-level heading is searched, because a banner-shaped line appearing
  # later in the body is a leftover scaffold trace or a stale snapshot, never the live status.

  headings = _parser.h1_headings(body)
  scan_end = headings[0][0] if headings else len(body)
  region = body[:scan_end]
  for line in region.splitlines():
    match = _FIRST_LINE_RE.match(line)

    # guard: skip non-banner lines in the pre-H1 region so only the first banner-tag line decides the state
    if match is None:
      continue
    return _TAG_TO_STATE.get(match.group(1))
  return None


def extract_block(body: str) -> str:
  """
  Return the banner callout block of `body`.

  Guarantees:
    - The returned text is the banner callout alone: its `#review/<state>` first line and the quoted lines that
      continue it.
    - The banner is taken only from the region above the first top-level heading, or from the whole body when
      there is none.
    - Any other callout, before or after the banner, is never part of the returned text.

  Args:
    body: Document body text to search for the banner callout.

  Returns:
    The banner callout block, including its continuation lines and any blank lines right after it, or an empty
    string when no banner callout sits above the first top-level heading.
  """

  # Contract:
  # The returned text MUST be the banner callout alone — its `#review/<state>` first line and
  # the quoted lines that continue it — taken only from the region above the first top-level
  # heading; any other callout, before or after the banner, MUST NEVER be part of it.

  # the banner lives only above the first H1, the same region `extract` reads; the strip pattern also matches
  # the retired concerns-decision callout, which carries no state, so only a block `extract` reads as a state
  # banner qualifies
  headings = _parser.h1_headings(body)
  scan_end = headings[0][0] if headings else len(body)
  found = next(
      ( block for block in _BANNER_BLOCK_RE.finditer(body[:scan_end]) if extract(block.group(0)) is not None ),
      None,
  )

  # guard: no state banner callout in that region
  if found is None:
    return ""
  return found.group(0)


# -------------------------------------------------------- desired_state


_QUESTION_OPEN_RE = re.compile(
    r"^>\s*\[!question\].*#review/question.*$",
    re.MULTILINE,
)
# A decision-candidate carries no #review/… tag — the type token itself is the whole match
# (lazy-core.markdown-style: the accept/reject pair is mandatory on every candidate).
_CANDIDATE_OPEN_RE = re.compile(
    r"^>\s*\[!decision-candidate\].*$",
    re.MULTILINE,
)
_TICKED_OPTION_RE = re.compile(r"^>\s*-\s*\[x\]", re.MULTILINE | re.IGNORECASE)


def _find_callout_block(body: str, header_match: re.Match[str]) -> str:
  """
  Return the full `> `-prefixed block starting at `header_match`.

  Args:
    body: Document text to slice from.
    header_match: Regex match whose `start()` marks the callout header line.

  Returns:
    All consecutive `>`-prefixed lines from the match position, joined by newlines.
  """
  start = header_match.start()
  lines = body[start:].splitlines()
  collected: list[str] = []
  for line in lines:
    # guard: the first line without a `>` prefix ends the callout block
    if not line.startswith(">"):
      break
    collected.append(line)
  return "\n".join(collected)


def _any_unanswered_question(body: str) -> bool:
  """
  Report whether `body` contains an open question callout with no operator tick.

  Args:
    body: Document text, scanned outside code fences for open `#review/question` callouts.

  Returns:
    True if at least one unanswered question callout is present, False otherwise.
  """
  # callout-shaped lines inside code fences are body content, never gating callouts, so fences are stripped first
  scan_body = _parser.strip_code_fences(body)
  for match in _QUESTION_OPEN_RE.finditer(scan_body):
    block = _find_callout_block(scan_body, match)
    if not _TICKED_OPTION_RE.search(block):
      return True
  return False


def _has_unanswered_candidate(body: str) -> bool:
  """
  Report whether `body` contains a decision-candidate callout with no operator tick.

  Args:
    body: Document text, scanned outside code fences for `[!decision-candidate]` callouts.

  Returns:
    True if at least one unanswered `[!decision-candidate]` callout is present, False otherwise.
  """

  # Domain(review.markup):
  # # Decision-candidate identity and answered state
  # A decision-candidate callout carries no `#review/…` tag; the callout type token itself is
  # its identity. Every candidate must carry the mandatory accept/reject option pair, and it
  # counts as answered only when a ticked option sits inside that same candidate's own block —
  # no carve-outs apply, per callout. An unanswered candidate is an operator-facing block that
  # holds the review banner at "Action needed" exactly like an unanswered question. Callout-
  # shaped lines that appear inside a code fence are inert body content, never a live candidate.

  # same per-callout gate as questions: a candidate is answered only by a tick inside its
  # own block (the coordination playbook's finalize gate has no carve-outs)
  scan_body = _parser.strip_code_fences(body)
  for match in _CANDIDATE_OPEN_RE.finditer(scan_body):
    block = _find_callout_block(scan_body, match)
    if not _TICKED_OPTION_RE.search(block):
      return True
  return False


def desired_state(
    *,
    body: str,
    dispatch_state: DispatchState,
    approved: bool = False,
    domain_ready: bool = True,
    review_phase: str | None = None,
) -> State:
  """
  Compute the banner state appropriate for the current tick.

  - `OPERATOR_COMMITTED` / `CHAIN_IN_PROGRESS` → always `State.IN_PROCESS` (agents work next; operator waits).
  - `CHAIN_EXHAUSTED` → recompute by the spec table:

    1. open `#review/question` or unanswered `[!decision-candidate]` → ACTION_NEEDED
    2. consumer's `domain_ready` predicate False → ACTION_NEEDED
    3. `approved == True` → phase-aware:
         - `review_phase in {"validators", "terminals"}` → `IN_PROCESS`. Validators (stage 5) and
           terminals (stage 6) are post-approve barriers that run BEFORE finalize; the caller passes
           a matching `waiting_context` to `replace_banner` so the rendered title reads "Waiting:
           validators" / "Waiting: terminals". Without this branch the generic post-tick repaint
           paints "Waiting: finalize" while validators or terminals are still in flight, which
           misrepresents the current phase to the operator.
         - `review_phase in {None, "finalizing"}` (or any other value) → `FINALIZING`. Finalize is
           in flight, no further waiting work; the chain is heading to the finalize commit, not
           back to the pre-approve `Ready to approve` callout. (Bug 114 — without this gate the
           post-approve banner-tick would repaint over the approved-mirror, showing
           `- [ ] approve the whole document` on top of a doc whose frontmatter already carries
           `review_approved: true`.)
    4. else → READY

  Guarantees:
    - Returns `State.IN_PROCESS` whenever `dispatch_state` is not `CHAIN_EXHAUSTED`,
      regardless of every other argument.
    - Once the dispatch has exhausted, the result follows a fixed priority: an unanswered
      question, an undecided candidate, or a failed `domain_ready` check outranks
      approval; and only once none of those hold does `approved` decide between
      `IN_PROCESS` / `FINALIZING` and `READY`.

  Args:
    body: Full document text, scanned for open questions and decision candidates.
    dispatch_state: Current phase of the dispatch cycle.
    approved: Frontmatter-mirrored approve flag; `True` after the dispatcher has mirrored the operator's
      `- [x] approve the whole document` tick into `review_approved`.
    domain_ready: Consumer-supplied predicate; `False` forces `ACTION_NEEDED`.
    review_phase: Frontmatter `review_phase` value (`validators` / `terminals` /
      `finalizing` / `main` / `awaiting-operator` / `bootstrapping`) or `None` when absent. When
      `approved == True` and `dispatch_state == CHAIN_EXHAUSTED`, drives the validators/terminals →
      `IN_PROCESS` vs finalizing → `FINALIZING` branch above. Ignored when `approved == False`.

  Returns:
    The `State` the banner should display for this tick.
  """

  # Contract:
  # When `dispatch_state` is not `CHAIN_EXHAUSTED`, the result MUST be `State.IN_PROCESS`
  # regardless of every other argument. Once exhausted, an open question, undecided
  # candidate, or a failed `domain_ready` check MUST outrank approval; and only once none
  # of those hold does `approved` decide between `IN_PROCESS` / `FINALIZING` and `READY`.

  # Domain(review.markup):
  # # Banner state priority once the work chain has emptied
  # While an agent action is still pending in the current round, the banner always reports
  # that work is in progress — the operator has nothing to decide yet. Once the chain has
  # drained, the state follows a fixed priority: an open question or an undecided proposal
  # holds the document at "action needed" first, and so does a failed domain-specific
  # readiness check even with no open callout. No separate pause for a decision about
  # validators' concerns exists: those concerns come back to the operator on the ordinary
  # ready-to-approve banner. Only once none of these hold does approval take over: an approved document
  # still reports work in progress while post-approval validation is still running, and only
  # reports "finalizing" once that work is done. A document that clears every gate without yet
  # being approved is simply ready for the operator to approve.

  if dispatch_state is not DispatchState.CHAIN_EXHAUSTED:
    return State.IN_PROCESS
  if _any_unanswered_question(body) or _has_unanswered_candidate(body):
    return State.ACTION_NEEDED
  if not domain_ready:
    return State.ACTION_NEEDED
  if approved:
    # guard: validators / terminals run BEFORE finalize; caller passes waiting_context to replace_banner
    if review_phase in ("validators", "terminals"):
      return State.IN_PROCESS
    return State.FINALIZING
  return State.READY


# ------------------------------------------------------------- render


# Spec § Top banner: the "Waiting" title is enriched with the phase the
# document is waiting on ("Waiting: validators" / ": writer" / ": terminals").
# A banner title is the same English label in every vault — it names the state
# the way the tag does, and only the body prose under it follows the repository
# language. Recognition keys on the `#review/in-process` TAG regardless, so an
# enriched and a bare title both extract to `State.IN_PROCESS`.
_WAITING_CONTEXT_LABELS: dict[str, str] = {
    Bucket.WRITER:     "Waiting: writer",
    Bucket.VALIDATORS: "Waiting: validators",
    Bucket.TERMINALS:  "Waiting: terminals",
    Phase.FINALIZE:    "Waiting: finalize",
}

# Bare "Waiting" title — what an unknown or absent waiting context renders.
_WAITING_BARE = "Waiting"

_TEMPLATES: dict[str, dict[State, str]] = {
    _LANG_EN: {
        State.IN_PROCESS: (
            "> [!hint] {title} #review/in-process\n"
            "{autorun}"
            "> To intervene, or to wake a document that looks stuck, write the instruction "
            "in a `[!todo] #review/command` callout.\n"
        ),
        State.ACTION_NEEDED: (
            "> [!caution] Action needed #review/action-needed\n"
            "> Answer the open question or the decision candidate below by ticking an option, "
            "then commit.\n"
        ),
        State.FINALIZING: "> [!hint] Waiting: finalize #review/finalizing\n",
    },
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    "ru": {  # noqa: RUF001
        State.IN_PROCESS: (
            "> [!hint] {title} #review/in-process\n"
            "{autorun}"
            "> Чтобы вмешаться или разбудить застрявший документ, напишите указание "
            "в коллауте `[!todo] #review/command`.\n"
        ),
        State.ACTION_NEEDED: (
            "> [!caution] Action needed #review/action-needed\n"
            "> Ответьте на открытый вопрос или кандидат решения ниже, отметив вариант, "
            "и закоммитьте.\n"
        ),
        # a title and nothing else: no body prose exists here to carry the language
        State.FINALIZING: "> [!hint] Waiting: finalize #review/finalizing\n",
    },
}

# The ready banner before any validation round, or after an autorun stopped clean: one approval checkbox, the
# `approve` gesture.
# `{autorun}` takes the stop line of an autorun that ended, or nothing.
_READY_SINGLE_TEMPLATE: dict[str, str] = {
    _LANG_EN: (
        "> [!success] Ready to approve #review/ready\n"
        "{autorun}"
        "> Tick the box below to approve the whole document.\n"
        "> To send it back for another writer round, edit the text and commit, "
        "or write the instruction in a `[!todo] #review/command` callout.\n"
        "> - [{tick}] approve the whole document\n"
    ),
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    "ru": (  # noqa: RUF001
        "> [!success] Ready to approve #review/ready\n"
        "{autorun}"
        "> Отметьте галочку ниже, чтобы утвердить документ целиком.\n"
        "> Чтобы отправить на доработку, поправьте текст и закоммитьте "
        "или напишите указание в коллауте `[!todo] #review/command`.\n"
        "> - [{tick}] утвердить документ целиком\n"
    ),
}

# The ready banner once a validation round has run, unless an autorun stopped clean: the three approval
# checkboxes, in `READY_GESTURE_KINDS` order. `{autorun}` takes the stop line of an autorun that ended, or nothing.
_READY_TRIPLE_TEMPLATE: dict[str, str] = {
    _LANG_EN: (
        "> [!success] Ready to approve #review/ready\n"
        "{autorun}"
        "> Tick ONE box: approve and send to the validators, approve and let the loop run to the end, "
        "or approve and finalize without another validation round.\n"
        "> To send it back for another writer round, edit the text and commit, "
        "or write the instruction in a `[!todo] #review/command` callout.\n"
        "> - [{tick}] approve this and previous rounds\n"
        "> - [ ] approve and run to the end without stops\n"
        "> - [ ] approve without further validation\n"
    ),
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    "ru": (  # noqa: RUF001
        "> [!success] Ready to approve #review/ready\n"
        "{autorun}"
        "> Отметьте ОДНУ галочку: утвердить и отдать валидаторам, утвердить и дать циклу дойти до конца, "
        "или утвердить и финализировать без ещё одного круга валидации.\n"
        "> Чтобы отправить на доработку, поправьте текст и закоммитьте "
        "или напишите указание в коллауте `[!todo] #review/command`.\n"
        "> - [{tick}] утвердить этот и предыдущие раунды\n"
        "> - [ ] утвердить и догнать до конца без остановок\n"
        "> - [ ] утвердить без дальнейшей валидации\n"
    ),
}

# The ready banner's opening line after an autorun stopped; `{reason}` comes from `_AUTORUN_STOP_REASONS`.
_AUTORUN_STOP_LINE: dict[str, str] = {
    _LANG_EN: "> Autorun stopped after {cycles} cycle(s): {reason}\n",
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    "ru": "> Автопрогон остановлен после {cycles} круг(ов): {reason}\n",  # noqa: RUF001
}

# Why an autorun stopped, keyed by its `review_autorun` stop state; a running or absent autorun has no entry.
_AUTORUN_STOP_REASONS: dict[str, dict[str, str]] = {
    _LANG_EN: {
        AutorunState.CLEAN: "the validators raised no concerns",
        AutorunState.CAP: "the cycle cap was reached",
        AutorunState.QUESTION: "an expert asked a question",
    },
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    "ru": {  # noqa: RUF001
        AutorunState.CLEAN: "валидаторы не подняли замечаний",
        AutorunState.CAP: "достигнут потолок кругов",
        AutorunState.QUESTION: "эксперт задал вопрос",
    },
}

# The in-process banner's progress line while an autorun is still turning.
_AUTORUN_RUNNING_LINE: dict[str, str] = {
    _LANG_EN: "> Autorun in progress: {cycles} cycle(s) done without operator stops.\n",
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    "ru": "> Идёт автопрогон: пройдено кругов без остановок: {cycles}.\n",  # noqa: RUF001
}


def _resolve_for_language(table: dict[str, _EntryType], lang: str) -> _EntryType:
  """
  Resolve a table's entry for a language, falling back to the shipped English one.

  Args:
    table: One of the per-language string tables.
    lang: Resolved language code; a code with no entry of its own falls back.

  Returns:
    The language's entry, or the English entry when the language has none.
  """
  # every table is complete for English, so the floor always answers
  return table.get(lang) or table[_LANG_EN]


def render(
    state: State,
    *,
    approved: bool = False,
    validation_seen: bool = False,
    autorun: str | None = None,
    autorun_cycles: int | None = None,
    waiting_context: str | None = None,
    lang: str = _LANG_EN,
) -> str:
  """
  Render the callout markdown for `state`.

  - For `State.READY`, one checkbox (`approve the whole document`) is rendered when the autorun stopped clean
    (`autorun` is `clean`, even after a validation round) or when no validation round has run. Three checkboxes
    are rendered in the order of `READY_GESTURE_KINDS` only when a validation round has run (`validation_seen`)
    and the autorun did not stop clean (no autorun, or a `cap` / `question` stop): `approve this and previous
    rounds`, `approve and run to the end without stops`, `approve without further validation`. `approved=True`
    ticks the first box (mirrors frontmatter `review_approved` for visual consistency).
  - For `State.READY` after an autorun stopped (`autorun` is `clean`, `cap` or `question`), the banner opens
    right under its title with `Autorun stopped after {n} cycle(s): {reason}`.
  - For `State.IN_PROCESS`, `waiting_context` enriches the title ("Waiting: validators" etc.);
    unknown or `None` → bare "Waiting". While `autorun` is `running`, the title is followed by
    `Autorun in progress: {n} cycle(s) done without operator stops.`

  Guarantees:
    - Approval checkbox lines appear in the rendered markup only when `state` is `State.READY`;
      every other state's output never carries one.
    - For `State.READY`, the markup carries one approval line before any validation round (`validation_seen` is
      false) and whenever `autorun` is `clean`, and the three gestures in `READY_GESTURE_KINDS` order otherwise
      (a validation round has run and `autorun` is absent, `cap`, or `question`).
    - The autorun stop line is painted above the approval line(s) for every stop state, `clean` included.

  Args:
    state: Banner state to render.
    approved: Ticks the first approval checkbox when rendering `State.READY`.
    validation_seen: Whether a validation round has run; with an `autorun` that did not stop clean, selects the
      three-checkbox `State.READY` banner.
    autorun: The `review_autorun` value (`running` / `clean` / `cap` / `question`), or `None` for no autorun;
      `clean` keeps the `State.READY` banner at one checkbox even when `validation_seen` is set.
    autorun_cycles: Autoapprovals done in the current autorun, shown as `n` in the autorun line; `None` counts as 0.
    waiting_context: Phase label inserted into the `State.IN_PROCESS` title; `None` yields bare "Waiting".
    lang: Resolved language code for the body prose; titles stay English, and a language with
      no table of its own renders the shipped English wording throughout.

  Returns:
    Callout markdown string for the given state, ready to embed in the document body.
  """

  # Contract:
  # The rendered markup MUST carry approval checkbox lines only when `state` is
  # `State.READY`. For `State.READY` it MUST carry ONE approval checkbox line before any
  # validation round (`validation_seen` is false) and whenever the autorun stopped clean
  # (`autorun` is `clean`), and the three gestures in `READY_GESTURE_KINDS` order otherwise
  # (a validation round has run and the autorun is absent, `cap`, or `question`). Every
  # other state's output MUST NEVER contain an approval checkbox.

  # Domain(review.markup):
  # # Approval checkbox scope
  # Approval checkboxes appear only in the ready-to-approve banner. It carries one box,
  # approving the whole document, in two situations: before validators have looked at the
  # document at all, and whenever a self-running loop stopped because the validators raised no
  # concerns, even after validation rounds have run. Once a validation round has run and the
  # loop did not stop clean, the banner carries three boxes instead, always in the same order:
  # approve this and the previous rounds and send the document to the validators again,
  # approve and let the loop run on its own to the end, or approve and finalize without
  # another validation round. That happens when no self-running loop was active, or when one
  # stopped at the cycle cap or because an expert asked a question. The three boxes are told
  # apart by their position, not by their wording, so every language's banner means the same
  # gestures. No other banner state ever renders an approval box — an operator cannot approve
  # mid-round, while a self-running loop is still turning, or once finalizing has already
  # started.

  # Domain(review.markup):
  # # Autorun status lines
  # A loop the operator let run on its own reports itself on the banner. While it turns, the
  # in-process banner says how many cycles have passed without an operator stop. Once it stops,
  # the ready-to-approve banner opens with how many cycles it ran and why it stopped: the
  # validators raised no concerns, the cycle cap was reached, or an expert asked a question.
  # The stop line opens the ready banner for every stop reason. After a clean stop it sits
  # above a single box that approves the whole document, since the validators have nothing
  # left to say; after the other stops the operator still gets the full set of boxes. Without
  # such a loop neither line appears.

  # the autorun cycle count both banners print; an absent count reads as zero
  cycles = autorun_cycles or 0

  # the ready banner: one box on a clean autorun stop or before any validation round, three otherwise, opened by
  # the stop line of an autorun that ended
  if state is State.READY:
    three_boxes = validation_seen and autorun != AutorunState.CLEAN
    ready = _resolve_for_language(_READY_TRIPLE_TEMPLATE if three_boxes else _READY_SINGLE_TEMPLATE, lang)
    reason = _resolve_for_language(_AUTORUN_STOP_REASONS, lang).get(autorun or "")
    stop_line = "" if reason is None else _resolve_for_language(_AUTORUN_STOP_LINE, lang).format(
        cycles = cycles, reason = reason,
    )
    return ready.format(tick = "x" if approved else " ", autorun = stop_line)

  # the waiting banner: a phase-enriched title, plus the progress line of an autorun still turning
  template = _resolve_for_language(_TEMPLATES, lang)[state]
  if state is State.IN_PROCESS:
    title =_WAITING_CONTEXT_LABELS.get(waiting_context or "", _WAITING_BARE)
    running_line = (
        _resolve_for_language(_AUTORUN_RUNNING_LINE, lang).format(cycles = cycles)
        if autorun == AutorunState.RUNNING else ""
    )
    return template.format(title = title, autorun = running_line)
  return template


# ---------------------------------------------------- replace_banner


_BANNER_BLOCK_RE = re.compile(
    r"(?ms)"  # multiline + dotall
    # `concerns-decision` is the retired pause banner: never a state, only stripped so a legacy one cannot linger
    r"^>\s*\[!\w+\][^\n]*#review/(?:in-process|action-needed|ready|finalizing|concerns-decision)[^\n]*\n"
    r"(?:>[^\n]*\n)*"  # continuation lines of the callout
    r"(?:\n)*"  # optional blank lines after the callout
)

# A leading YAML frontmatter block, when the caller passes a full-document
# body rather than a post-frontmatter one. The banner anchors BELOW it.
_LEADING_FRONTMATTER_RE = re.compile(r"(?s)\A---\n(.*?)\n---\n")

# A line a YAML frontmatter block can hold: a top-level key, an indented continuation, a list
# item, a comment, or a blank; any other line means the `---` pair is a pair of thematic breaks
_FRONTMATTER_LINE_RE = re.compile(r"[A-Za-z_][\w.-]*[ \t]*:(?:\s|$)|[ \t]|-(?:\s|$)|#|$")


def _leading_frontmatter(body: str) -> str:
  """
  Return the YAML frontmatter block leading `body`, fences included.

  Args:
    body: A full document or a post-frontmatter body.

  Returns:
    The leading frontmatter block, or an empty string when `body` does not open with one — a
    leading pair of `---` thematic breaks around prose is not frontmatter.
  """
  match = _LEADING_FRONTMATTER_RE.match(body)

  # guard: no fenced block at the top, or one holding prose rather than YAML
  if match is None or not all(_FRONTMATTER_LINE_RE.match(line) for line in match.group(1).split("\n")):
    return ""
  return match.group(0)


def replace_banner(
    body: str,
    state: State,
    *,
    approved: bool = False,
    validation_seen: bool = False,
    autorun: str | None = None,
    autorun_cycles: int | None = None,
    waiting_context: str | None = None,
    lang: str = _LANG_EN,
) -> str:
  """
  Return `body` with its banner replaced (or inserted, if absent).

  The new banner is rendered for `state` and anchored as the first non-empty content of the body, directly below
  a leading YAML frontmatter block when the caller passes one, never above it. Any existing banner block is
  removed first, wherever it sits, so the result carries exactly one banner. Leading blank lines ahead of the
  banner are dropped.

  Guarantees:
    - The result carries exactly one banner block, positioned as the first content directly below any leading
      frontmatter (or at the very top when there is none) — never above the frontmatter and never further down,
      regardless of where a prior banner sat in `body`.

  Args:
    body: Full document or post-frontmatter body whose banner is replaced.
    state: Banner state to render.
    approved: Ticks the first approval checkbox when rendering `State.READY`.
    validation_seen: Whether a validation round has run; with an `autorun` that did not stop clean, selects the
      three-checkbox banner.
    autorun: The `review_autorun` value (`running` / `clean` / `cap` / `question`), or `None` for no autorun;
      `clean` keeps the `State.READY` banner at one checkbox even when `validation_seen` is set.
    autorun_cycles: Autoapprovals done in the current autorun, shown in the autorun line; `None` counts as 0.
    waiting_context: Phase label inserted into the `State.IN_PROCESS` title; `None` yields bare "Waiting".
    lang: Resolved language code for the body prose.

  Returns:
    The body with exactly one banner block, anchored at the top of the content below any leading frontmatter.
  """

  # Contract:
  # The returned body MUST carry exactly one banner block, anchored as the first content
  # directly below any leading frontmatter (or at the very top when there is none) — never
  # above the frontmatter, never further down, and never duplicated.

  # Domain(review.markup):
  # # Banner anchoring invariant
  # A review document carries exactly one status banner, and it always sits at the very top of
  # the document's content — directly below the frontmatter block when one is present, never
  # above it and never further down. Whenever the banner is repainted, whatever occupies that
  # role is removed first, wherever it currently sits, because an earlier round can leave a
  # stray banner mis-anchored deeper in the body; only after that removal does the fresh banner
  # get placed at the top, so the document never ends up carrying two banners or one sitting
  # below its own content.

  new_banner = render(
      state,
      approved = approved,
      validation_seen = validation_seen,
      autorun = autorun,
      autorun_cycles = autorun_cycles,
      waiting_context = waiting_context,
      lang = lang,
  ) + "\n"

  # split off a leading frontmatter block so the banner never lands above it
  fm_prefix = _leading_frontmatter(body)
  rest = body[len(fm_prefix):]

  # Decision: strip the prior banner wherever it sits, not only above the first H1 — a round that assembled a
  # body without its title H1 leaves the banner mis-anchored below the content, and the old "above the first
  # H1" rule then picked `# History` as the anchor and parked the banner at the bottom (Bug 105), so a
  # head-only strip would duplicate it. Leading whitespace ahead of the banner is dropped so the
  # blank-line-or-not ambiguity (Bug 30 part a) cannot bleed in.

  # drop the old banner and anchor the fresh one at the top of the remaining content
  rest = _parser.sub_outside_fences(_BANNER_BLOCK_RE, "", rest, count = 1).lstrip("\n")
  return fm_prefix + new_banner + rest
