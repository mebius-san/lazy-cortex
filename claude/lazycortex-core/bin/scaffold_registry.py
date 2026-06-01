#!/usr/bin/env python3

"""
scaffold_registry — dependency-free owner of the lazy-core.scaffold `## Registry` block.

Parses / renders / surgical splices the rigid 3-level YAML mapping
(plugin -> template-path -> [globs]) without a YAML library, and exposes
upsert / remove / list / validate as the `lazycortex-core scaffold` subcommand.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


REGISTRY_HEADING = "## Registry"
_FENCE_OPEN = "```yaml"
_FENCE_CLOSE = "```"
# YAML-reserved leading characters: a plain scalar starting with one of these must be quoted.
_RESERVED_LEAD = set("*&!|>%@`[]{},?\"'#:")


def _locate_block(md: str) -> tuple[list[str], int, int]:
  """
  Return the line list, open-fence index, and close-fence index for the Registry block.

  Locate the single `## Registry` heading, then find the ```yaml fence that follows
  it and its matching closing fence.

  Args:
    md: Full markdown source to search.

  Returns:
    A tuple of (lines, open_idx, close_idx).

  Raises:
    ValueError: If the heading is missing or appears more than once, if no ```yaml
      fence is found under the heading, or if the fence is unterminated.
  """
  lines = md.splitlines()
  headings = [ idx for idx, line in enumerate(lines) if line.strip() == REGISTRY_HEADING ]
  # guard: exactly one Registry heading required
  if len(headings) != 1:
    raise ValueError(
      f"expected exactly one '{REGISTRY_HEADING}' heading, found {len(headings)}"
    )
  head_idx = headings[0]
  open_idx = None
  for pos in range(head_idx + 1, len(lines)):
    if lines[pos].strip() == _FENCE_OPEN:
      open_idx = pos
      break
    if lines[pos].strip() and not lines[pos].startswith("#"):
      break
  # guard: a ```yaml fence must follow the heading
  if open_idx is None:
    raise ValueError("no ```yaml fence found under ## Registry")
  close_idx = None
  for pos in range(open_idx + 1, len(lines)):
    if lines[pos].strip() == _FENCE_CLOSE:
      close_idx = pos
      break
  # guard: the fence must be closed
  if close_idx is None:
    raise ValueError("unterminated ```yaml fence under ## Registry")
  return lines, open_idx, close_idx


def _unquote(val: str) -> str:
  """
  Strip a single layer of surrounding double- or single-quotes from a YAML scalar.

  Args:
    val: Raw scalar string, possibly quoted.

  Returns:
    The unquoted value, or the trimmed input unchanged if it is not quoted.
  """
  val = val.strip()
  if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
    return val[1:-1]
  return val


def parse_registry_block(md: str) -> dict:
  """
  Parse the `## Registry` ```yaml block into {plugin: {path: [globs]}}.

  The shape is rigid: top-level keys at column 0 (`key:`), template paths at
  2-space indent (`path:`), globs at 4-space indent (`- glob`). `{}` means empty.
  Anything outside this shape raises ValueError.

  Args:
    md: Full markdown source containing exactly one `## Registry` ```yaml block.

  Returns:
    Nested dict mapping plugin key → template path → list of glob strings.

  Raises:
    ValueError: If the heading, fence, or block structure is invalid, or if a
      duplicate top-level key is encountered.
  """
  lines, open_idx, close_idx = _locate_block(md)
  body = lines[open_idx + 1 : close_idx]
  nonblank = [ line for line in body if line.strip() ]
  if nonblank == ["{}"]:
    return {}
  data: dict = {}
  cur_plugin: str | None = None
  cur_path: str | None = None
  for raw in body:
    # guard: skip blank lines
    if not raw.strip():
      continue
    if raw == raw.lstrip():  # column 0 -> top-level key
      # guard: top-level line must end with ':' to be a valid key mapping
      if not raw.rstrip().endswith(":"):
        raise ValueError(f"top-level line is not a 'key:' mapping: {raw!r}")
      cur_plugin = raw.rstrip()[:-1].strip()
      # guard: reject duplicate top-level keys
      if cur_plugin in data:
        raise ValueError(f"duplicate top-level key: {cur_plugin}")
      data[cur_plugin] = {}
      cur_path = None
    elif raw.startswith("    - "):  # 4-space glob item
      # guard: a glob item requires an enclosing template path to be active
      if cur_path is None:
        raise ValueError(f"glob item before any template path: {raw!r}")
      data[cur_plugin][cur_path].append(_unquote(raw[len("    - "):]))
    elif raw.startswith("  ") and not raw.startswith("   "):  # exactly 2-space -> template path
      # guard: a template path requires an enclosing plugin key to be active
      if cur_plugin is None:
        raise ValueError(f"template path before any plugin key: {raw!r}")
      # guard: template path line must end with ':' to be a valid mapping
      if not raw.rstrip().endswith(":"):
        raise ValueError(f"template line is not a 'path:' mapping: {raw!r}")
      cur_path = raw.strip()[:-1].strip()
      data[cur_plugin][cur_path] = []
    else:
      raise ValueError(f"unexpected indentation in registry block: {raw!r}")
  return data


def _scalar(val: str) -> str:
  """
  Render a glob/path as a YAML plain scalar, quoting only when necessary.

  Quote only when `val` starts with a YAML-reserved character (e.g. a leading `*`).
  Mid-string reserved characters stay plain.

  Args:
    val: Glob or path string to render.

  Returns:
    The input wrapped in double-quotes if the leading character is reserved, otherwise the input unchanged.
  """
  if val and val[0] in _RESERVED_LEAD:
    return f'"{val}"'
  return val


def render_key(plugin: str, entries: dict) -> str:
  """
  Serialize one top-level key's sub-block into YAML text.

  Emit `<plugin>:` then 2-space-indented `path:` lines each followed by 4-space
  `- glob` lines, in insertion order. The result ends with a newline.

  Args:
    plugin: Top-level plugin key (e.g. `lazycortex-core` or `_local`).
    entries: Mapping of template paths to lists of glob strings.

  Returns:
    The serialized sub-block as a string with a trailing newline.
  """
  out = [ f"{plugin}:" ]
  for path, globs in entries.items():
    out.append(f"  {path}:")
    for glob in globs:
      out.append(f"    - {_scalar(glob)}")
  return "\n".join(out) + "\n"


def _key_line_span(body_lines: list[str], plugin: str) -> tuple[int, int] | None:
  """
  Locate the contiguous line range for a top-level plugin key in the block body.

  Scans for a column-0 `<plugin>:` heading line, then extends the span downward
  to include all blank lines and indented child lines that follow it.

  Args:
    body_lines: Lines between the opening and closing fence markers (exclusive).
    plugin: Top-level key name to search for (e.g. `lazycortex-core`).

  Returns:
    A `(start, end)` pair where `start` is the index of the `<plugin>:` line and
    `end` (exclusive) is the first line that belongs to the next sibling key or
    to trailing blank space after the last key. Returns `None` when the key is
    absent.
  """
  start = None
  for idx, line in enumerate(body_lines):
    stripped = line.rstrip()
    # guard: must be at column 0, end with ':', and name the target plugin
    if line == line.lstrip() and stripped.endswith(":") and stripped[:-1].strip() == plugin:
      start = idx
      break
  # guard: key not present
  if start is None:
    return None
  end = start + 1
  while end < len(body_lines) and (not body_lines[end].strip() or body_lines[end].startswith(" ")):
    end += 1
  return start, end


def _body_lines(md: str) -> list[str]:
  """
  Extract the lines that live between the fence markers of the Registry block.

  An empty block (`{}` or genuinely blank) returns an empty list so callers can
  treat it uniformly as "no keys present yet".

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.

  Returns:
    The list of raw lines between the opening and closing fence (exclusive).
    Returns an empty list when the block contains only `{}` or only blank lines.
  """
  lines, open_idx, close_idx = _locate_block(md)
  body = lines[open_idx + 1 : close_idx]
  non_blank = [ line for line in body if line.strip() ]
  # guard: treat an empty-dict sentinel as an empty body
  if non_blank == ["{}"] or not non_blank:
    return []
  return body


def _rewrite_block(md: str, body_lines: list[str]) -> str:
  """
  Reconstruct the markdown source with a replacement Registry block body.

  Replaces the lines between the opening and closing fence markers with
  `body_lines`, preserving every other byte in the source including the final
  newline when originally present.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.
    body_lines: Replacement lines to place between the fence markers.

  Returns:
    The full markdown source with the block body replaced by `body_lines`.
  """
  lines, open_idx, close_idx = _locate_block(md)
  new_lines = lines[: open_idx + 1] + body_lines + lines[close_idx:]
  text = "\n".join(new_lines)
  if md.endswith("\n"):
    text += "\n"
  return text


def splice_upsert(md: str, plugin: str, entries: dict) -> str:
  """
  Replace or insert a plugin key-region inside the Registry block.

  When the key already exists, its entire line span is replaced with a freshly
  rendered block. When the key is absent, the rendered block is appended after
  the last existing key. All other key regions and every byte outside the fence
  markers are preserved verbatim.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.
    plugin: Top-level key name to upsert (e.g. `lazycortex-core` or `_local`).
    entries: Mapping of template paths to lists of glob strings for this key.

  Returns:
    The updated markdown source with the plugin key-region replaced or appended.
  """
  body = _body_lines(md)
  rendered = render_key(plugin, entries).splitlines()
  span = _key_line_span(body, plugin)
  if span is None:
    new_body = body + rendered
  else:
    span_start, span_end = span
    new_body = body[:span_start] + rendered + body[span_end:]
  return _rewrite_block(md, new_body)


def validate(md: str) -> list[dict]:
  """
  Return a list of findings for the Registry block; an empty list means the block is clean.

  Checks structural invariants (every plugin entry is a proper mapping, every
  template path maps to a list of glob strings, no template path uses the
  `${CLAUDE_PLUGIN_ROOT}` variable) and cross-key overlap (two keys that share
  at least one identical glob string).

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.

  Returns:
    A list of finding dicts, each with keys `code`, `severity` (`"FAIL"` or `"WARN"`),
    and `msg`. Returns an empty list when the block is structurally valid and no
    overlaps are detected.
  """
  findings: list[dict] = []
  try:
    data = parse_registry_block(md)
  except ValueError as err:
    return [ {"code": "parse_error", "severity": "FAIL", "msg": str(err)} ]
  globs_by_key: dict[str, set] = {}
  for plugin, entries in data.items():
    # guard: top-level value must be a dict (mapping of template paths)
    if not isinstance(entries, dict):
      findings.append({"code": "bad_shape", "severity": "FAIL", "msg": f"{plugin} not a mapping"})
      continue
    gset: set = set()
    for path, globs in entries.items():
      if "${CLAUDE_PLUGIN_ROOT}" in path:
        findings.append({
          "code": "plugin_root_var",
          "severity": "FAIL",
          "msg": f"{plugin}: template path uses ${{CLAUDE_PLUGIN_ROOT}}: {path}",
        })
      # guard: glob list must be a list
      if not isinstance(globs, list):
        findings.append({
          "code": "bad_shape",
          "severity": "FAIL",
          "msg": f"{plugin}/{path}: globs not a list",
        })
        continue
      gset.update(globs)
    globs_by_key[plugin] = gset
  keys = list(globs_by_key)
  for idx_a, key_a in enumerate(keys):
    for idx_b in range(idx_a + 1, len(keys)):
      common = globs_by_key[key_a] & globs_by_key[keys[idx_b]]
      if common:
        findings.append({
          "code": "glob_overlap",
          "severity": "WARN",
          "msg": f"{key_a} and {keys[idx_b]} share globs: {sorted(common)}",
        })
  return findings


def splice_remove(md: str, plugin: str) -> str:
  """
  Delete a plugin key-region from the Registry block.

  Removes the `<plugin>:` heading line and all of its indented child lines.
  Has no effect when the key is absent. All other key regions and every byte
  outside the fence markers are preserved verbatim.

  Args:
    md: Full markdown source containing a `## Registry` ```yaml block.
    plugin: Top-level key name to remove (e.g. `lazycortex-core` or `_local`).

  Returns:
    The updated markdown source with the plugin key-region removed, or the
    original source unchanged when the key was not present.
  """
  body = _body_lines(md)
  span = _key_line_span(body, plugin)
  # guard: key absent — nothing to remove
  if span is None:
    return md
  span_start, span_end = span
  new_body = body[:span_start] + body[span_end:]
  return _rewrite_block(md, new_body)


# Minimal scaffold rule template used when creating a registry file from scratch.
_MINIMAL = (
  "---\n"
  "description: Scaffold registry — authoring templates a plugin registers.\n"
  "always_loaded: fires at create-time; path-scoped contracts don't trigger on Write\n"
  "---\n"
  "# Scaffold\n\n"
  "Before composing any **new** file whose path matches a glob below, `Read` the matching "
  "template first. Contract: `claude/lazycortex-core/references/lazy-core.scaffold-registry-contract.md`.\n\n"
  "When several globs match the same path, the most-specific wins (within a key and across "
  "keys); on an equal-specificity tie, `_local` overrides plugin keys.\n\n"
  "## Registry\n\n```yaml\n{}\n```\n"
)


def _atomic_write(path: str, text: str) -> None:
  """
  Write `text` to `path` atomically via a same-directory temp file.

  Creates the parent directory if absent. The write is completed by an
  atomic rename so a concurrent reader never observes a partial file.

  Args:
    path: Destination file path (created or overwritten).
    text: Full text content to write.
  """
  dir_path = os.path.dirname(os.path.abspath(path)) or "."
  os.makedirs(dir_path, exist_ok = True)
  # waiver: stdlib idiom, not a domain constant
  tmp_fd, tmp = tempfile.mkstemp(dir = dir_path, suffix = ".tmp")
  try:
    # waiver: stdlib idiom, not a domain constant
    with os.fdopen(tmp_fd, "w", encoding = "utf-8") as fle:
      fle.write(text)
    os.replace(tmp, path)
  finally:
    if os.path.exists(tmp):
      os.unlink(tmp)


def _emit(obj: dict) -> int:
  """
  Serialise `obj` as JSON to stdout and return a shell exit code.

  Returns 0 for all statuses except `"error"`, which returns 1.

  Args:
    obj: Result dict to emit; must contain a `"status"` key.

  Returns:
    0 on success, 1 when `obj["status"] == "error"`.
  """
  print(json.dumps(obj))
  # waiver: external-result schema field name, not an internal key
  if obj.get("status") == "error":
    return 1
  return 0


def _load_entries(arg: str) -> dict:
  """
  Deserialise a plugin entries mapping from a CLI argument string.

  Accepts two forms: a bare JSON object string, or `@<path>` where `<path>`
  is a file containing the JSON object.

  Args:
    arg: JSON string or `@<filepath>` reference.

  Returns:
    The deserialised mapping of template paths to glob lists.
  """
  if arg.startswith("@"):
    with open(arg[1:], encoding = "utf-8") as fle:
      return json.load(fle)
  return json.loads(arg)


# waiver: four cmd branches each with explicit early returns; linear dispatch is clearest here
# pylint: disable=too-many-return-statements,too-many-branches
def main(argv: list[str]) -> int:
  """
  Entry point for the `lazycortex-core scaffold` CLI.

  Dispatches to one of four subcommands — `upsert`, `remove`, `list`, or
  `validate` — each operating on a registry markdown file. All output is
  emitted as a single JSON object on stdout. Exits with code 0 on success
  and 1 on error.

  Args:
    argv: Argument list (typically `sys.argv[1:]`).

  Returns:
    Shell exit code: 0 for success, 1 for error.
  """
  # waiver: deferred import for optional dependency — argparse is stdlib but
  # deferred here so the module can be imported without triggering parser construction
  # noinspection PyUnresolvedReferences
  import argparse  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
  arg_parser = argparse.ArgumentParser(prog = "lazycortex-core scaffold")
  # waiver: argparse CLI signature, not a domain key
  sub = arg_parser.add_subparsers(dest = "cmd", required = True)
  for name in ("upsert", "remove", "list", "validate"):
    sparser = sub.add_parser(name)
    # waiver: argparse CLI signature, not a domain key
    sparser.add_argument("--registry", required = True)
    if name in ("upsert", "remove"):
      # waiver: argparse CLI signature, not a domain key
      sparser.add_argument("--plugin", required = True)
    # waiver: argparse CLI signature, not a domain key
    if name == "upsert":
      # waiver: argparse CLI signature, not a domain key
      sparser.add_argument("--entries", required = True)
  args = arg_parser.parse_args(argv)

  exists = os.path.exists(args.registry)
  # waiver: argparse CLI signature, not a domain key
  if args.cmd == "upsert":
    if not exists:
      new_md = splice_upsert(_MINIMAL, args.plugin, _load_entries(args.entries))
      _atomic_write(args.registry, new_md)
      return _emit({"status": "created-and-registered", "plugin": args.plugin})
    with open(args.registry, encoding = "utf-8") as fle:
      md = fle.read()
    # waiver: external-result schema field name, not an internal key
    errs = [ fnd for fnd in validate(md) if fnd["severity"] == "FAIL" ]
    # guard: existing file must parse cleanly before upsert can proceed
    if errs:
      print(json.dumps({"status": "error", "findings": errs}), file = sys.stderr)
      return 1
    new_md = splice_upsert(md, args.plugin, _load_entries(args.entries))
    if new_md == md:
      return _emit({"status": "unchanged", "plugin": args.plugin})
    _atomic_write(args.registry, new_md)
    return _emit({"status": "registered", "plugin": args.plugin})

  # waiver: argparse CLI signature, not a domain key
  if args.cmd == "remove":
    if not exists:
      return _emit({"status": "absent", "plugin": args.plugin})
    with open(args.registry, encoding = "utf-8") as fle:
      md = fle.read()
    new_md = splice_remove(md, args.plugin)
    if new_md == md:
      return _emit({"status": "absent", "plugin": args.plugin})
    _atomic_write(args.registry, new_md)
    return _emit({"status": "removed", "plugin": args.plugin})

  # waiver: argparse CLI signature, not a domain key
  if args.cmd == "list":
    if exists:
      with open(args.registry, encoding = "utf-8") as fle:
        md = fle.read()
    else:
      md = _MINIMAL
    return _emit({"status": "ok", "registry": parse_registry_block(md)})

  # waiver: argparse CLI signature, not a domain key
  if args.cmd == "validate":
    if exists:
      with open(args.registry, encoding = "utf-8") as fle:
        md = fle.read()
    else:
      md = _MINIMAL
    return _emit({"status": "ok", "findings": validate(md)})

  return 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
