"""`/lazy-review.finalize <file>` — close out a fully-approved doc.

The finalizing commit:

1. Folds all edit-annotation markers into the final text (via
   :func:`edit_markup.strip_markers` in the configured style).
2. Drops the top banner block (whichever state it was in).
3. Drops the approve-checkbox line.
4. Drops every other system callout (`#review/<x>`) from the body
   but keeps `# History`.
5. Strips every transient `review_*` frontmatter key by prefix (everything except `review_result`).
6. Stamps the terminal `review_result` outcome
   (`approved` | `approved-with-concerns`) — the discriminator
   downstream apply-gate md-scan routines key off. The open
   transition unsets it on every fresh review.
7. Single atomic commit carrying `Doc-Review-Phase: finalize`
   trailer under the bot identity.

Idempotent: re-running finalize on an already-finalized document
(no transient `review_*` keys, `review_result` already stamped,
status callout already in place) produces byte-identical output →
no-op.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# deferred imports below module code; position intentional (ruff E402 noqa guards it)
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import body as _body  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import edit_markup as _edit_markup  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import frontmatter as _fm  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import git_ops as _git_ops  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from keys import JobKey, Paths, ResultValue, ReviewKey, Style  # noqa: E402


_BANNER_RE = re.compile(
    r"(?ms)^>\s*\[!\w+\][^\n]*"
    r"#review/(?:in-process|action-needed|ready|concerns-decision)"
    r"[^\n]*\n(?:>[^\n]*\n)*(?:\n)*"
)
_SYSTEM_CALLOUT_RE = re.compile(
    r"(?ms)^>\s*\[!\w+\][^\n]*#review/[a-z-]+[^\n]*\n(?:>[^\n]*\n)*\n?"
)
_APPROVE_LINE_RE = re.compile(
    r"^>\s*-\s*\[[ x]\]\s*"
    r"(?:approve the whole document"
    r"|approve with concerns"
    r"|continue review cycle)"
    r"[^\n]*\n",
    re.MULTILINE | re.IGNORECASE,
)


def _settings_edit_marker_style(file_path: Path) -> str:
  """
  Return the configured edit-marker style for the repo containing `file_path`.

  Returns:
    The `review.edit_marker_style` value from the nearest `.claude/lazy.settings.json`,
    or `"simple"` when no settings file is found or the key is absent.
  """
  cur = file_path.parent
  # waiver: inline numeric literal, not a domain constant
  for _ in range(10):
    candidate = cur / Paths.CLAUDE_DIR / Paths.SETTINGS_FILE
    if candidate.exists():
      try:
        data = json.loads(candidate.read_text())
        return (
            data.get(JobKey.REVIEW, {}).get(JobKey.EDIT_MARKER_STYLE, Style.SIMPLE)
        )
      except (OSError, json.JSONDecodeError):
        return Style.SIMPLE
    if cur.parent == cur:
      break
    cur = cur.parent
  return Style.SIMPLE


def finalize_text(
    text: str,
    *,
    style: str,
    preserve_section_ids: set[str] | None = None,
    with_concerns: bool = False,
    normalize_section_ids: set[str] | None = None,
) -> str:
  """
  Apply the finalize transforms to `text` and return the result.

  Args:
    text: Full document text including YAML frontmatter and body.
    style: Edit-marker style passed to the strip-markers step.
    preserve_section_ids: Optional set of section-id strings (keys under
      `experts.terminal.<id>` / `experts.validation.<id>`) whose owned H1
      sections survive the strip. Terminal section-ids are always included;
      validation section-ids are included only when `with_concerns=True`.
      The caller assembles the set; this function only consumes it.
    with_concerns: When `True`, stamp the `approved-with-concerns` status
      callout (info marker) instead of the clean `approved` (success marker).
      Validation-umbrella section-ids are assumed to already be in
      `preserve_section_ids` (caller's responsibility).
    normalize_section_ids: Optional set of section-id strings whose surviving
      H1 sections keep their content but lose the `#expert/<flat>/<id>`
      ownership-tag line. Pass the validation section-ids under `with_concerns`
      so preserved concerns read as plain prose.

  Returns:
    Finalized document text with review-machinery markers, transient frontmatter
    keys, and non-preserved expert sections removed, and `review_result` stamped.
  """
  meta, body = _fm.parse(text)
  fm_text = text[: len(text) - len(body)]
  # Lift foreign `#protected/<owner>/...` sections out before the body-wide passes so their
  # bytes (including any inner HTML markers a `strip_markers(style="html")` pass would eat)
  # survive finalize verbatim; restored after the status callout is stamped. They are owned
  # by another plugin (the cross-plugin protected-section contract), not by review.
  body, _protected_sections = _body.split_out_protected_sections(body)
  body = _edit_markup.strip_markers(body, style=style)
  body = _BANNER_RE.sub("", body, count=1)
  body = _APPROVE_LINE_RE.sub("", body)
  body = _SYSTEM_CALLOUT_RE.sub("", body)
  # Drop section-writer artefacts (Routing, Final check, Implementation
  # risks, …) — every H1 with `#expert/<flat>/<section-id>` ownership
  # tag whose section-id is NOT in `preserve_section_ids`. History is
  # always kept. Pre-approve sections are already empty on the
  # operator's gesture; post-approve sections are guaranteed empty by
  # the revert-to-main rule, but defence-in-depth: strip unconditionally
  # so a stray scaffold (e.g. an empty `# Final check\n#expert/...\n`)
  # doesn't leak into the finalized document. Terminal-action section-
  # ids declared in `preserve_section_ids` survive — the post-
  # finalize transition strips them once its work is done.
  body = _body.strip_owned_h1_sections(body, preserve_section_ids=preserve_section_ids)
  # Bug 88: validator sections preserved under `with_concerns` survive
  # as plain prose — strip their `#expert/<flat>/<section-id>` ownership-
  # tag line so the finalized document carries no review-machinery tags
  # (heading + concern content kept verbatim).
  if normalize_section_ids:
    body = _body.strip_ownership_tag(body, section_ids=normalize_section_ids)
  # Bug 36: stamp a visible terminal-state status callout above the
  # first H1 so the operator sees what the review concluded the
  # moment they open the document — without having to read frontmatter
  # or trace `# History` entries. The callout lives in its own
  # `#status/<state>` namespace (not under `#review/`) and
  # survives subsequent re-finalize passes (it's upserted, not
  # accumulated). Consumers that own a richer terminal state (e.g.
  # `spec.request-handler` apply-mode setting request_status to
  # accepted / rejected / spawned) overwrite this callout with their
  # own when their action lands; the default is the review-side
  # "approved & finalized" record below.
  status = _status_callout_for_finalize(meta, with_concerns=with_concerns)
  if status is not None:
    body = _body.upsert_status_callout(body, **status)
  # Restore the foreign protected sections lifted before the body-wide passes (verbatim).
  body = _body.restore_protected_sections(body, _protected_sections)
# Spec § Stage 7: strip ALL `review_*` keys from frontmatter. The
# finalized document carries no review-machinery metadata — the
# status callout above documents the outcome for humans, and the
# consumer's apply transition (if any) sets its own status fields.
# Order: status-callout decision was made above using the original
# `meta` dict (still has `review_approved` / `review_approved_with_concerns`),
# so the strip below is safe to run after.
# Idempotent: if the doc was already finalized (none of these keys
# present), every unset_field is a no-op and the function returns
# input bytes unchanged — the CLI's `already finalized` branch
# detects via input == output.
  for key in [k for k in meta if k.startswith(ReviewKey.PREFIX) and k != ReviewKey.RESULT]:
    fm_text = _fm.unset_field(fm_text, key)
# Drop the YAML frontmatter block entirely when no keys remain
# between the fences. A finalized review doc whose original
# frontmatter held only `review_*` keys ends up with `---\n---`
# after the unset loop — that empty block is visual noise.
# Consumer docs that carry non-review keys (`spec_role`,
# `request_status`, `tags`, etc.) keep their non-empty
# frontmatter unchanged. When emptied, `set_field` below
# re-synthesizes a clean `---\nreview_result: <value>\n---`
# block.
  if _fm.is_empty(fm_text):
    fm_text = ""
# Stamp the terminal `review_result` outcome — the apply-gate
# discriminator that downstream md-scan routines key off
# (e.g. `spec.request-handler` apply mode triggers on
# `review_result: [approved, approved-with-concerns]`). Written
# LAST so it survives the `review_*` prefix strip above. The open
# transition unsets this key when a doc re-enters the review
# loop, so its presence is a reliable signal of "review just
# closed". Stamp only when there is actual review evidence —
# either a fresh finalize (`review_approved` was in meta) or an
# idempotent re-run on an already-stamped doc. A doc with neither
# was never in the review loop; finalize is a no-op on it (input
# bytes == output bytes).
  if ReviewKey.APPROVED in meta:
    result_value = ResultValue.APPROVED_WITH_CONCERNS if with_concerns else ResultValue.APPROVED
    fm_text = _fm.set_field(fm_text, ReviewKey.RESULT, result_value)
  elif meta.get(ReviewKey.RESULT, "").strip() in (ResultValue.APPROVED, ResultValue.APPROVED_WITH_CONCERNS):
      # Idempotent re-run — preserve existing key (set_field call is
      # a byte-identical no-op when the value already matches).
    existing = meta[ReviewKey.RESULT].strip()
    fm_text = _fm.set_field(fm_text, ReviewKey.RESULT, existing)
  return fm_text + body


def _status_callout_for_finalize(meta: dict, *, with_concerns: bool = False) -> dict | None:
  """
  Return the status-callout kwargs the finalize transform should stamp on a document.

  Consumer-specific statuses (request accepted / rejected / spawned) are handled by
  the consumer's apply transition — this function only covers the generic review-side
  outcome.

  Args:
    meta: Parsed frontmatter dict for the document being finalized.
    with_concerns: When `True`, use the `approved-with-concerns` variant (info marker,
      distinct tag) so the callout reflects that the operator accepted outstanding
      concerns rather than driving them to zero.

  Returns:
    A dict with `state`, `marker`, `title`, and `body_lines` keys suitable for passing
    to `_body.upsert_status_callout`, or `None` when the document has no approval flag
    and therefore no terminal status to record.
  """
  approved_raw = str(meta.get(ReviewKey.APPROVED, "")).strip().lower()
  if approved_raw not in ("true", "yes", "1"):
    return None
  if with_concerns:
    return {
        JobKey.STATE:      ResultValue.APPROVED_WITH_CONCERNS,
        JobKey.MARKER:     "info",
        JobKey.TITLE:      "Document approved & finalized with outstanding concerns",
        JobKey.BODY_LINES: (),
    }
  return {
      JobKey.STATE:      ResultValue.APPROVED,
      JobKey.MARKER:     "success",
      JobKey.TITLE:      "Document approved & finalized",
      JobKey.BODY_LINES: (),
  }


def _commit_final(repo: Path, file_path: Path) -> str:
  return _git_ops.commit_final(
      repo, file_path,
      author={"name": "lazy-review", "email": "lazy-review@bot.invalid"},
      # waiver: one-off human-facing message
      message="review: finalize",
  )


def _repo_root_for(file_path: Path) -> Path:
  """
  Return the root directory of the git repository containing `file_path`.

  Returns:
    The nearest ancestor directory that contains a `.git` entry, or the
    immediate parent of `file_path` when no `.git` directory is found within
    twenty levels up.
  """
  cur = file_path.parent
  # waiver: inline numeric literal, not a domain constant
  for _ in range(20):
    if (cur / Paths.GIT_DIR).exists():
      return cur
    if cur.parent == cur:
      break
    cur = cur.parent
  return file_path.parent


def main(argv: list[str]) -> int:
  """
  Finalize a fully-approved review document from the command line.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success or when already finalized, 2 when the file is not found.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.finalize")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("file", type=Path)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-commit", action="store_true")
  args = parser.parse_args(argv)
  file_path: Path = args.file.resolve()
  if not file_path.exists():
    sys.stderr.write(f"file not found: {file_path}\n")
    return 2
  style = _settings_edit_marker_style(file_path)
  original = file_path.read_text()
  new_text = finalize_text(original, style=style)
  if new_text == original:
    print(f"already finalized: {file_path}")
    return 0
  file_path.write_text(new_text)
  if args.no_commit:
    print(f"finalized (uncommitted): {file_path}")
    return 0
  repo = _repo_root_for(file_path)
  sha = _commit_final(repo, file_path)
  print(f"finalized: {file_path} ({sha[:7]})")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
