"""
Note canonization verbs for `spec.coordinator`.

`spec.coordinator` canonizes an asset status folder-note with two tools: its own pen for body
prose (`# Status brief`, `[!question]` callouts, `# Coordinator commands` locking — see
`lazy-spec.coordinator.md`'s "Your pen" section) and these two CLI verbs for everything else.

`note-set-key` validates and writes one frontmatter key drawn from the CLOSED schema the
coordinator is allowed to own — the five gate booleans plus `spec_cancelled`, the halt flag, the
cascade-target and dependency-graph lists (`spec_targets`, `spec_depends_on`), the change-cascade
keys, the draft flag, the derived `spec_state` token, and the `spec_tools` verdict list. Every
other frontmatter key on a status
folder-note (`spec_role`, `tags`, `spec_source_requests`) belongs to a different worker's own
primitive and is
refused here. The two job markers are not frontmatter at all — they live in `spec_job_markers.py`'s
runtime sidecar and are written through `mark-job`, so this verb refuses their names like any
other key outside its schema.

`note-check` is a read-only structural scan: unrecognized or mistyped frontmatter keys, and a
missing or misordered required section from the canonical roster (`# Gates`, `# Status brief`
with its `#protected/spec/status-brief` marker, `# Coordinator rules`, `# Coordinator commands`,
`# History`). It reports violations as JSON and fixes nothing — repairing a broken note is the
coordinator's own job, done through its pen and through `note-set-key`. Its result also carries
the note's `job_markers` sidecar entry, so a reader that used to find the two markers in
frontmatter still gets them from one call.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_tick  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import iconize_inline  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402
    BOOL_TRUE,
    PROTECTED_ATTACHMENTS,
    PROTECTED_COORD_COMMANDS,
    PROTECTED_COORD_RULES,
    PROTECTED_STATUS_BRIEF,
    AnsweredQuestionKey,
    AssetTypeKey,
    DraftKey,
    Gate,
    Section,
    SpecCascadeKey,
    SpecCoordinatorDocStateKey,
    SpecCoordinatorReadyStateKey,
    SpecDependsOnKey,
    SpecHaltKey,
    SpecKey,
    SpecStateKey,
    SpecTargetsKey,
)


# ----------------------------------------------------------------------------------------
class _Kind:
  """
  Frontmatter value-shape tokens used to type-check and serialize a schema key's value.

  Attributes:
    BOOL: The `true`/`false` literal shape written by `flip_gate._set_bool`.
    STR: The bare single-line scalar shape written by this module's own `_set_fm_scalar`.
    LIST: The YAML block-list shape, or the empty inline-list shape (`key: []`), that
      `gate_tick._write_fm_list` writes.
    DICT: The compact single-line JSON object shape `gate_tick._set_fm_json` writes.
  """

  BOOL = "bool"
  STR = "str"
  LIST = "list"
  DICT = "dict"


# The frontmatter boolean-false literal, paired with `spec_keys.BOOL_TRUE` to validate/parse a
# `_Kind.BOOL` value without a bare string literal at each comparison site.
_BOOL_FALSE = "false"


# ----------------------------------------------------------------------------------------
class _ResultKey:
  """
  Result-dict field names shared by this module's own returned dicts.

  Attributes:
    STATUS: The `note_set_key` outcome-field key.
    OK: The `note_check` overall-pass field key.
    JOB_MARKERS: The `note_check` field carrying the note's runtime job-marker sidecar entry.
  """

  STATUS = "status"
  OK = "ok"
  JOB_MARKERS = "job_markers"


# ----------------------------------------------------------------------------------------
class _SetKeyStatus:
  """
  `_ResultKey.STATUS` values `note_set_key` returns.

  Attributes:
    SET: A fresh frontmatter write landed.
    NOOP: The value already matched what was on disk — no write, no commit.
    REFUSED: The key or value was rejected — no write.
  """

  SET = "set"
  NOOP = "noop"
  REFUSED = "refused"


# The closed schema `note-set-key` may write — exactly the coordinator's own frontmatter-owned
# keys per `lazy-spec.coordinator.md`'s verb table: the five gate booleans plus `spec_cancelled`, the
# halt flag, the cascade-target and dependency-graph lists (`spec_targets`, `spec_depends_on`),
# the change-cascade keys, the draft flag, the derived `spec_state` token the coordinator
# rewrites on every wake that rebuilds `# Status brief`, and the `spec_tools` verdict list the
# coordinator determines once the defining documents settle. Every other frontmatter key on a status
# folder-note is written by a different worker's own primitive and stays out of this verb's
# reach; the two job markers are written through `mark-job` into the runtime sidecar instead.
_WRITABLE_SCHEMA = {
    Gate.DESIGN_DONE: _Kind.BOOL,
    Gate.PLAN_DONE: _Kind.BOOL,
    Gate.DEVELOP_DONE: _Kind.BOOL,
    Gate.TESTS_PASSING: _Kind.BOOL,
    Gate.RELEASED: _Kind.BOOL,
    Gate.SPEC_CANCELLED: _Kind.BOOL,
    SpecHaltKey.HALTED: _Kind.BOOL,
    SpecTargetsKey.TARGETS: _Kind.LIST,
    SpecDependsOnKey.DEPENDS_ON: _Kind.LIST,
    SpecCascadeKey.DONE: _Kind.BOOL,
    SpecCascadeKey.TARGETS_DONE: _Kind.LIST,
    DraftKey.DRAFT: _Kind.BOOL,
    SpecStateKey.STATE: _Kind.STR,
    # the coordinator's tool verdict — LIST of open-vocabulary tool names (products declare
    # their own beyond the shipped four), so no member regex; an empty list is a legal verdict
    AssetTypeKey.TOOLS: _Kind.LIST,
}

# Member-shape regex for the two `<category>/<slug>` token lists — `spec_targets` and
# `spec_depends_on` are the only `_Kind.LIST` keys whose members name another asset folder
# (`gate_tick._target_asset_dir`'s own `raw_target.split("/")` contract); every other LIST-kind
# key (`spec_cascade_targets_done`, `spec_tools`, `tags`, `spec_source_requests`) keeps its own
# shape and is unchecked here (M8).
_CATEGORY_SLUG_TOKEN_RE = re.compile(r"^[^/]+/[^/]+$")
_TOKEN_LIST_KEYS = frozenset({ SpecTargetsKey.TARGETS, SpecDependsOnKey.DEPENDS_ON })


# Mirrored `tags` / `spec_source_requests` frontmatter key names, duplicated here rather than
# imported per this bin/ tree's own per-file small-constant convention (`apply_request.py`'s
# `_K.TAGS`, `coordinator_dispatch.py`'s `_SPEC_SOURCE_REQUESTS` do the same).
_TAGS_KEY = "tags"
_SPEC_SOURCE_REQUESTS_KEY = "spec_source_requests"

# `note-check`'s recognized-key superset: every `_WRITABLE_SCHEMA` entry plus the other
# legitimate frontmatter keys a status folder-note carries that this verb never writes itself —
# the scaffold-time `spec_role` / `tags`, the `spec_source_requests` slot `apply_request.py`
# owns, and `coordinator_dispatch.py`'s own worker-internal answered-question fingerprint,
# sibling-doc review-result marker, and readiness-gate snapshot (all three deliberately outside
# `_WRITABLE_SCHEMA` — the coordinator persona never writes any of them itself). The busy-guard's
# own declined/job-done wake lives in the runtime sidecar (`spec_job_markers.py`), never
# frontmatter, so it carries no entry here. Recognizing them here means their ordinary presence
# never reads as a "garbage key" finding.
_NOTE_SCHEMA = {
    **_WRITABLE_SCHEMA,
    SpecKey.ROLE: _Kind.STR,
    _TAGS_KEY: _Kind.LIST,
    _SPEC_SOURCE_REQUESTS_KEY: _Kind.LIST,
    AnsweredQuestionKey.FINGERPRINT: _Kind.STR,
    SpecCoordinatorDocStateKey.STATE: _Kind.DICT,
    SpecCoordinatorReadyStateKey.STATE: _Kind.DICT,
    AssetTypeKey.TYPE: _Kind.STR,
}

# Canonical required-section roster and order, per `lazy-spec.coordinator.md`'s asset-note templates
# (Task 4). `# Summary` is template-present but plugin-owned (`summary_render.py`), not part of
# the coordinator's own canonization concern, so it is not required here; an optional
# `# Sources` section (`lazy-spec.sources-protocol.md`) is neither required nor flagged.
_REQUIRED_SECTIONS = (
    Section.GATES,
    Section.STATUS_BRIEF,
    Section.COORD_RULES,
    Section.COORD_COMMANDS,
    Section.HISTORY,
)

# Sections that must carry their `#protected/<owner>/<region>` tag as the very next line
# — a scaffolded placeholder is never a legitimate substitute.
_PROTECTED_MARKERS = {
    Section.STATUS_BRIEF: PROTECTED_STATUS_BRIEF,
    Section.COORD_RULES: PROTECTED_COORD_RULES,
    Section.COORD_COMMANDS: PROTECTED_COORD_COMMANDS,
}

# Sections the plugin owns but does not require — absent without complaint, marker-checked
# when present. `# Attachments` only exists once an asset actually has one, and pre-existing
# notes predate it, so requiring it would fail every existing asset.
_OPTIONAL_PROTECTED_MARKERS = {
    Section.ATTACHMENTS: PROTECTED_ATTACHMENTS,
}

# Bot identity for this verb's own commit (frontmatter write + History line), mirroring
# `flip_gate`'s `_FLIP_AUTHOR_NAME` / `_FLIP_AUTHOR_EMAIL` shape. The `@bot.` substring is what
# `coordinator_dispatch._resolve_wake_trigger`'s self-suppression check relies on to never
# re-wake the coordinator on this verb's own writes.
_AUTHOR_NAME = "lazy-spec.note-set-key"
_AUTHOR_EMAIL = f"{_AUTHOR_NAME}@bot.invalid"

# Regex template for locating a frontmatter key's line, mirroring `flip_gate._set_bool`'s own.
_FM_KEY_RE_TEMPLATE = r"(?m)^{key}\s*:.*$"


def _set_fm_scalar(fm_text: str, key: str, value: str) -> str:
  """
  Add or replace a bare scalar `key: value` line inside a frontmatter block.

  The value is written unquoted, not JSON-encoded — a str-typed key is read back elsewhere as a
  bare scalar, so a quoted form would silently break that comparison.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The scalar frontmatter key to set.
    value: The replacement value, written verbatim (no quoting).

  Returns:
    The updated frontmatter text.
  """
  pat = re.compile(_FM_KEY_RE_TEMPLATE.format(key = re.escape(key)))
  if pat.search(fm_text):
    return pat.sub(f"{key}: {value}", fm_text, count = 1)
  close_idx = fm_text.rfind("---\n")
  # guard: malformed frontmatter without a closing fence
  if close_idx < 0:
    return fm_text
  return fm_text[:close_idx] + f"{key}: {value}\n" + fm_text[close_idx:]


def _parse_value(kind: str, raw: str, key: str) -> tuple[object, str | None]:
  """
  Parse and validate a CLI-supplied value string against a schema key's expected shape.

  Args:
    kind: The `_Kind` token naming the expected shape.
    raw: The raw CLI argument — `true`/`false` for `_Kind.BOOL`, a bare string for `_Kind.STR`, a
      JSON array of strings for `_Kind.LIST`.
    key: The frontmatter key being written — threaded through to the member-shape check the two
      `<category>/<slug>` token lists carry.

  Returns:
    A `(value, error)` pair — `value` is the parsed Python object (bool / str / list[str]) on
    success with `error` None; on failure `value` is None and `error` names what was wrong.
  """
  if kind == _Kind.BOOL:
    # guard: only the two literal tokens `flip_gate._set_bool` writes are accepted
    if raw not in (BOOL_TRUE, _BOOL_FALSE):
      return None, f"expected 'true' or 'false', got {raw!r}"
    return raw == BOOL_TRUE, None
  if kind == _Kind.STR:
    # guard: an empty scalar is never a legitimate value for a str-typed key
    if not raw:
      return None, "expected a non-empty string"
    return raw, None
  # only _Kind.LIST remains — every key in `_WRITABLE_SCHEMA` maps to one of the three kinds
  # left once the two dict-valued job markers moved to the runtime sidecar
  try:
    parsed = json.loads(raw)
  except json.JSONDecodeError:
    return None, f"expected a JSON list of strings, got {raw!r}"
  # guard: not a list, or a list with a non-string member — neither is a legal `spec_targets`
  if not isinstance(parsed, list) or not all(isinstance(member, str) for member in parsed):
    return None, f"expected a JSON list of strings, got {raw!r}"
  # guard: `spec_targets` / `spec_depends_on` carry `<category>/<slug>` tokens — a member
  # missing that shape (empty, no slash, more than one slash) is refused here rather than
  # writing clean and only surfacing as a silent context-fold-in miss later (M8)
  if key in _TOKEN_LIST_KEYS and not all(_CATEGORY_SLUG_TOKEN_RE.match(member) for member in parsed):
    return None, f"expected every member to match '<category>/<slug>', got {raw!r}"
  return parsed, None


def _apply_value(fm_text: str, key: str, kind: str, value: object) -> str:
  """
  Write a parsed value into the frontmatter block through the shape-appropriate helper.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).
    key: The frontmatter key to write.
    kind: The `_Kind` token naming `value`'s shape.
    value: The parsed value, as returned by `_parse_value`.

  Returns:
    The updated frontmatter text.

  Raises:
    TypeError: When `value`'s runtime type does not match `kind`.
  """
  if kind == _Kind.BOOL and isinstance(value, bool):
    return flip_gate._set_bool(fm_text, key, value)
  if kind == _Kind.STR and isinstance(value, str):
    return _set_fm_scalar(fm_text, key, value)
  if kind == _Kind.LIST and isinstance(value, list):
    return gate_tick._write_fm_list(fm_text, key, [str(item) for item in value])
  raise TypeError(f"value {value!r} does not match kind {kind!r}")


def _format_value(kind: str, value: object) -> str:
  """
  Render a parsed value back to the string form recorded in the `# History` line.

  Args:
    kind: The `_Kind` token naming `value`'s shape.
    value: The parsed value, as returned by `_parse_value`.

  Returns:
    `"true"`/`"false"` for `_Kind.BOOL`, the compact JSON text for `_Kind.LIST`, or the bare
    string itself for `_Kind.STR`.
  """
  if kind == _Kind.BOOL:
    return str(value).lower()
  if kind == _Kind.LIST:
    return json.dumps(value)
  return str(value)


def _commit(asset_dir: Path, note: Path, key: str, value_str: str) -> None:
  """
  Atomically commit the rewritten status folder-note under the `lazy-spec.note-set-key` bot identity.

  Skipped silently when the asset does not live inside a git repository (the unit-test fixture
  path) — the file write remains, and is the entire mutation that path observes.

  Args:
    asset_dir: The asset folder; used to resolve the enclosing repo root for the `git` cwd.
    note: The folder-note path that was just rewritten.
    key: The frontmatter key that was set, folded into the commit subject.
    value_str: The value's `_format_value` rendering, folded into the commit subject.

  Raises:
    subprocess.CalledProcessError: When `git add` or `git commit` exits non-zero.
  """
  top = flip_gate._git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")
  # guard: asset is not inside a git repository — skip commit (test-fixture path); the file
  # write above remains and is the entire mutation the bare-fixture caller observes
  if not top:
    return
  repo = Path(top)

  # fold the note's icon repaint into this same commit so no separate icons commit follows
  extra_paths = iconize_inline.repaint_paths(repo, [str(note.resolve().relative_to(repo.resolve()))])

  # stage the rewritten folder-note so the tree is clean for the next daemon iteration
  subprocess.run(
      ["git", "add", "--", str(note), *extra_paths],
      cwd = str(repo), check = True, capture_output = True,
  )

  # commit under the dedicated bot identity so the operator's authorship stays untouched
  subprocess.run(
      [
          "git",
          "-c", f"user.name={_AUTHOR_NAME}",
          "-c", f"user.email={_AUTHOR_EMAIL}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", f"{_AUTHOR_NAME}: {key} → {value_str} on {asset_dir.name}",
          "--", str(note), *extra_paths,
      ],
      cwd = str(repo), check = True, capture_output = True,
  )


def note_set_key(asset_dir: Path, key: str, raw_value: str, *, today: str | None = None) -> dict:
  """
  Validate and write one frontmatter key on an asset's status folder-note.

  Refuses (no file mutation) when `key` is outside the coordinator's closed writable schema, or
  when `raw_value` does not parse into the key's expected shape. A value that already matches
  what is on disk is a no-op — no write, no commit. On a genuine change, the frontmatter is
  rewritten, one `# History` line is appended, and the note is committed under the
  `lazy-spec.note-set-key` bot identity.

  Args:
    asset_dir: The asset folder holding `<asset_dir.name>.md`.
    key: The `spec_*` frontmatter key to set.
    raw_value: The value as a CLI argument string — `true`/`false` for a bool-typed key, a bare
      string for a str-typed key, a JSON array of strings for a list-typed key.
    today: Optional ISO date pinned into the `# History` line.

  Returns:
    `{"status": "set", "key", "value"}` on a fresh write, `{"status": "noop", "key"}` when the
    value already matched, or `{"status": "refused", "key", "reason"}` when the key is unknown
    or the value fails to parse.

  Raises:
    subprocess.CalledProcessError: When the commit of the rewritten note fails — propagated
      from `_commit`.
  """
  kind = _WRITABLE_SCHEMA.get(key)
  # guard: key outside the coordinator's closed writable schema — clean refusal, no write
  if kind is None:
    return {_ResultKey.STATUS: _SetKeyStatus.REFUSED, "key": key, "reason": f"unknown key: {key}"}

  # validate and parse the CLI value against the key's declared shape
  value, error = _parse_value(kind, raw_value, key)
  # guard: value does not parse into the key's expected shape — clean refusal, no write
  if error is not None:
    return {_ResultKey.STATUS: _SetKeyStatus.REFUSED, "key": key, "reason": error}

  # read the note's current frontmatter so the value write lands precisely
  note = asset_dir / f"{asset_dir.name}.md"
  text = note.read_text()
  _, fm_end = flip_gate._parse_frontmatter(text)
  fm_text = text[:fm_end]

  # apply the parsed value through the shape-appropriate writer
  new_fm_text = _apply_value(fm_text, key, kind, value)
  # guard: the value already matches what is on disk — nothing to write or commit
  if new_fm_text == fm_text:
    return {_ResultKey.STATUS: _SetKeyStatus.NOOP, "key": key}

  # render the value, append the audit trail, and refresh the section explainers before writing
  value_str = _format_value(kind, value)
  hist = f"- {flip_gate._today(today)} — {_AUTHOR_NAME} · {key} → {value_str}"
  body = flip_gate._append_under_heading(text[fm_end:], Section.HISTORY, hist)
  note.write_text(new_fm_text + note_explainers.ensure_explainers(body, note_explainers.lang_for_note(note)))
  _commit(asset_dir, note, key, value_str)
  return {_ResultKey.STATUS: _SetKeyStatus.SET, "key": key, "value": value_str}


def _is_value_ok(raw: str, kind: str) -> bool:
  """
  Check whether a frontmatter key's raw same-line value matches its schema-declared shape.

  A block-form list parses to an empty same-line value, which is accepted for `_Kind.LIST`
  without re-walking the body for its bullet lines.

  Args:
    raw: The key's same-line value, already stripped.
    kind: The `_Kind` token this key is declared as in `_NOTE_SCHEMA`.

  Returns:
    True when the value's shape matches `kind`; False otherwise.
  """
  if kind == _Kind.BOOL:
    return raw.lower() in (BOOL_TRUE, _BOOL_FALSE)
  if kind == _Kind.STR:
    return bool(raw)
  if kind == _Kind.LIST:
    # guard: empty same-line value is the block-list form — accepted without a body re-walk
    if not raw:
      return True
    return raw.startswith("[") and raw.endswith("]")
  # only _Kind.DICT remains
  try:
    return isinstance(json.loads(raw), dict)
  except json.JSONDecodeError:
    return False


def _find_section_line_index(body: str, heading: str) -> int | None:
  """
  Find the line index of an exact-match H1 heading in the folder-note body.

  Args:
    body: The folder-note body text (post-frontmatter) to search.
    heading: The exact heading line to locate (e.g. `# Coordinator commands`).

  Returns:
    The zero-based line index of the heading, or None when absent.
  """
  for idx, line in enumerate(body.splitlines()):
    if line.strip() == heading:
      return idx
  return None


def note_check(asset_note: Path) -> dict:
  """
  Structurally check an asset's status folder-note: frontmatter schema + required sections.

  Read-only — reports every violation found, applies no fix. An unrecognized frontmatter key is
  an "unknown-key" violation — which is how a job marker written into frontmatter surfaces, since
  both markers belong to the runtime sidecar and neither is in the recognized schema; a
  recognized key shaped wrong for its declared kind is "bad-type";
  a missing required section (`# Gates`, `# Status brief`, `# Coordinator rules`,
  `# Coordinator commands`, `# History`) is "missing-section"; a present protected section
  (`# Status brief`, `# Coordinator rules`, `# Coordinator commands`) whose very next line is
  not its own protected-owner tag is "missing-marker"; the optional `# Attachments` section is
  never "missing-section" when absent, but a present one whose very next line is not its own
  protected-owner tag is "missing-marker" just like the required sections, and it takes no part
  in the section-order check; the required sections found out of canonical order is one
  "section-order" violation.

  Args:
    asset_note: The status folder-note path to check.

  Returns:
    `{"note": <path>, "ok": <bool>, "violations": [...], "job_markers": {...}}` — `ok` is True
    exactly when `violations` is empty; `job_markers` is the note's sidecar entry, every field of
    the closed marker schema present, unrecorded ones as `None`.
  """
  text = asset_note.read_text()
  fm, fm_end = flip_gate._parse_frontmatter(text)
  body = text[fm_end:]
  violations: list[dict] = []

  # check every present frontmatter key against the recognized schema
  for key, raw in fm.items():
    kind = _NOTE_SCHEMA.get(key)
    if kind is None:
      violations.append({"kind": "unknown-key", "key": key})
      continue
    if not _is_value_ok(raw, kind):
      violations.append({"kind": "bad-type", "key": key, "expected": kind, "value": raw})

  # locate each required section's line, recording its position for the order check below
  positions: dict[str, int] = {}
  for heading in _REQUIRED_SECTIONS:
    idx = _find_section_line_index(body, heading)
    if idx is None:
      violations.append({"kind": "missing-section", "section": heading})
    else:
      positions[heading] = idx

  # verify each protected section's next line carries its own owner tag
  lines = body.splitlines()
  for section, marker in _PROTECTED_MARKERS.items():
    # guard: section itself was never found — nothing to check its marker against
    if section not in positions:
      continue
    marker_idx = positions[section] + 1
    if marker_idx >= len(lines) or lines[marker_idx] != marker:
      violations.append({ "kind": "missing-marker", "section": section, "marker": marker })

  # an optional section is never a missing-section finding, but a present one still has to
  # carry its owner tag — an untagged block means some other writer has claimed the heading
  for section, marker in _OPTIONAL_PROTECTED_MARKERS.items():
    idx = _find_section_line_index(body, section)
    # guard: the optional section is absent — nothing to validate
    if idx is None:
      continue
    if idx + 1 >= len(lines) or lines[idx + 1] != marker:
      violations.append({ "kind": "missing-marker", "section": section, "marker": marker })

  # order is checked only over the sections that were actually found — a missing one is already
  # reported above and must not also trip a spurious order violation
  present_order = [positions[heading] for heading in _REQUIRED_SECTIONS if heading in positions]
  if present_order != sorted(present_order):
    violations.append({"kind": "section-order", "sections": list(_REQUIRED_SECTIONS)})

  # the coordinator branches on `ok` alone to decide whether a repair pass is owed at all, and
  # reads the sidecar block for the two markers it used to find in the frontmatter above
  return {
      "note": str(asset_note),
      _ResultKey.OK: not violations,
      "violations": violations,
      _ResultKey.JOB_MARKERS: spec_job_markers.read(flip_gate._repo_root(asset_note.parent), asset_note),
  }


def main_set_key(argv: list[str]) -> int:
  """
  Run `note-set-key` from the command line, printing the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name and subcommand.

  Returns:
    Exit code: 0 on a fresh write or a no-op, 1 on a refusal, 2 when the asset note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs note-set-key")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_dir", type = Path)
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("key")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("value")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--today", default = None,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "ISO date pinned into the emitted history line")
  args = parser.parse_args(argv)
  asset_dir: Path = args.asset_dir.resolve()
  note = asset_dir / f"{asset_dir.name}.md"
  # guard: asset status folder-note must exist
  if not note.is_file():
    sys.stderr.write(f"no status folder-note: {note}\n")
    return 2

  # run the write and report the result the same way every other lazycortex-specs verb does
  result = note_set_key(asset_dir, args.key, args.value, today = args.today)
  print(json.dumps(result))
  return 0 if result[_ResultKey.STATUS] != _SetKeyStatus.REFUSED else 1


def main_check(argv: list[str]) -> int:
  """
  Run `note-check` from the command line, printing the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name and subcommand.

  Returns:
    Exit code: 0 when the note carries no violations, 1 when it does, 2 when the note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs note-check")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_note", type = Path)
  asset_note: Path = parser.parse_args(argv).asset_note.resolve()
  # guard: asset status folder-note must exist
  if not asset_note.is_file():
    sys.stderr.write(f"no status folder-note: {asset_note}\n")
    return 2

  # run the check and report the result the same way every other lazycortex-specs verb does
  result = note_check(asset_note)
  print(json.dumps(result))
  return 0 if result[_ResultKey.OK] else 1
