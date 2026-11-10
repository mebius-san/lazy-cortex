#!/usr/bin/env python3
"""
Tag-page planning and generation for an Obsidian vault.

Keeps the pages under `Tags/` in step with the tags used in the vault's note frontmatter: `plan` reports which
pages are missing, current, or stale, and `apply` removes the stale pages and creates the missing ones from the
consumer's tag-page template. New pages are described either by written summaries or, with `--templated`, by a
fixed line naming the tag in the vault's language.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from iconize_sync import (  # pylint: disable=import-error
  FM_BLOCK_RE, IconizeError, find_vault, plugin_root_name, resolve_plugin_roots, walk_md_files,
)
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import vault_manifest  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The vault directory holding one page per tag, mirroring the tag hierarchy
TAGS_DIR = "Tags"

# The vault's system directory, whose notes never feed the tag set
SYSTEM_DIR = "Ω System"

# The consumer-owned tag-page template, relative to the vault root
TEMPLATE_REL = ".claude/templates/lazy-obsidian.tag-page-template.md"

# The two tokens the template carries
TAG_PATH_TOKEN, SUMMARY_TOKEN = "{{TAG_PATH}}", "{{SUMMARY}}"

# The markdown suffix of a note and of a tag page
NOTE_SUFFIX = ".md"

# Every note, template and page is UTF-8
ENCODING = "utf-8"

# The refusal a run without the template ends in
MISSING_TEMPLATE_REASON = (
  "Missing tag-page template at `.claude/templates/lazy-obsidian.tag-page-template.md`. "
  "Run `/lazy-obsidian.install` to scaffold the default from the plugin."
)

# The refusal a run ends in when a page to create has no description
MISSING_SUMMARY_REASON = "no summary for tag page(s) to create: {tags}"

# A `tags:` key line at the top level of the frontmatter, capturing its inline value
_TAGS_KEY_RE = re.compile(r"^tags\s*:(.*)$")

# A block-sequence item line under the key
_LIST_ITEM_RE = re.compile(r"^\s+-\s*(.*)$")

# The quote characters a YAML scalar may be wrapped in
_QUOTES = "\"'"

# The path segments a tag may not carry, since each would escape or blur the page path
_BAD_SEGMENTS = ("", ".", "..")

# The summaries file the agent writes between `plan` and `apply`, kept inside the git directory
SUMMARIES_NAME = "lazy-obsidian.tag-summaries.json"

# CLI statuses and exit code of a refused run
STATUS_PLANNED, STATUS_APPLIED, STATUS_REFUSED = "planned", "applied", "refused"
EXIT_REFUSED = 1

# The two subcommands
VERB_PLAN, VERB_APPLY = "plan", "apply"

# Refusal reasons the CLI adds on top of the module's own
NO_GIT_DIR_REASON = "{vault} is not inside a git repository; the summaries file has nowhere to live"
SUMMARIES_INVALID_REASON = "{path} is not a JSON object of tag -> summary strings"
NO_CORE_REASON = "lazycortex-core is not found, so --templated cannot learn the vault's language"
LANGUAGE_FAILED_REASON = "lazycortex-core resolve-language failed (exit {code}): {detail}"

# The core plugin that answers the vault's language, and its CLI inside the plugin root
CORE_PLUGIN = "lazycortex-core"
CORE_CLI_REL = Path("bin") / "lazycortex-core"

# The settings section whose own `language` key overrides the repo-wide one
SETTINGS_SECTION = "obsidian"

# The fixed description line of a templated page per language, and the line for every other language
TEMPLATED_LINES: dict[str, str] = { "ru": "Тег `{tag}`." }
TEMPLATED_DEFAULT_LINE = "Tag `{tag}`."


# ----------------------------------------------------------------------------------------
class TagPagesRefusedError(Exception):
  """
  Refusal to generate tag pages, raised before anything is written.

  Attributes:
    reason: One-line explanation of the refusal that the caller reports.
  """

  def __init__(self, reason: str) -> None:
    """
    Create a refusal carrying the reason to report.

    Args:
      reason: One-line explanation of why tag-page generation was refused.
    """
    super().__init__(reason)

    # The one-line reason the caller reports
    self.reason: str = reason


@dataclass
class TagEntry:
  """
  Tag that needs a page, with the notes that use it.

  Attributes:
    tag: Full slash-separated tag path.
    parent_only: Whether the tag exists only as a parent of other tags and no note uses it directly.
    notes: Vault-relative paths of the notes that carry the tag, sorted.
  """

  # The full slash-separated tag path
  tag: str
  # Whether only child tags make the page necessary
  parent_only: bool
  # Notes carrying the tag, sorted
  notes: list[str] = field(default_factory = list)


@dataclass
class TagPlan:
  """
  Difference between the tags the vault needs pages for and the pages that exist.

  Attributes:
    all_tags: Every tag that needs a page, parent tags included, sorted.
    create: Entries for tags whose page is missing, sorted by tag.
    keep: Tags whose page already exists and is still needed, sorted.
    delete: Tags whose page exists but is no longer needed, sorted.
  """

  # Every tag needing a page, sorted
  all_tags: list[str]
  # Tags whose page is missing
  create: list[TagEntry]
  # Tags whose page exists and is still needed
  keep: list[str]
  # Tags whose page exists but is no longer needed
  delete: list[str]


@dataclass
class ApplyResult:
  """
  Outcome of applying a tag-page plan to the vault.

  Attributes:
    created: Tags whose page was created.
    deleted: Tags whose page was deleted.
    kept: Number of existing pages left untouched.
    touched_paths: Vault-relative paths of every page deleted or created.
  """

  # Tags whose page was created
  created: list[str]
  # Tags whose page was deleted
  deleted: list[str]
  # Count of existing pages left untouched
  kept: int
  # Vault-relative paths of every page deleted or created
  touched_paths: list[str]


# ----------------------------------------------------------------------------------------
def _clean_tag(raw: str) -> str:
  """
  Normalize a raw frontmatter tag value to a bare tag path.

  Args:
    raw: Tag value as written in the frontmatter, possibly quoted or prefixed with `#`.

  Returns:
    The tag without surrounding whitespace, quotes, or a leading `#`.
  """
  value = raw.strip().strip(_QUOTES).strip()
  return value[1:] if value.startswith("#") else value


def parse_tags(text: str) -> list[str]:
  """
  Read the tags declared in a note's frontmatter.

  Accepts the `tags` key as a flow sequence, a comma-separated scalar, or a block sequence.

  Args:
    text: Full text of the note.

  Returns:
    The non-empty tags in declaration order, or an empty list when the note has no frontmatter or no tags.
  """
  # guard: a note without frontmatter carries no tags
  if (match := FM_BLOCK_RE.match(text)) is None:
    return []

  # scan the frontmatter lines for the `tags` key
  lines = match.group(1).splitlines()
  out: list[str] = []
  for index, line in enumerate(lines):
    # every other frontmatter key is skipped
    if (key := _TAGS_KEY_RE.match(line)) is None:
      continue

    # the value written on the key line itself decides the form
    inline = key.group(1).strip()

    # an inline value is a flow sequence or a comma-separated scalar
    if inline:
      body = inline[1:-1] if inline.startswith("[") and inline.endswith("]") else inline
      out.extend(_clean_tag(item) for item in body.split(","))
      break

    # an empty inline value opens a block sequence on the following lines
    for item_line in lines[index + 1:]:
      # the first line that is not a list item ends the sequence
      if (item := _LIST_ITEM_RE.match(item_line)) is None:
        break
      out.append(_clean_tag(item.group(1)))
    break
  return [ tag for tag in out if tag ]


def _is_usable_tag(tag: str) -> bool:
  """
  Tell whether a tag can become a tag page.

  Args:
    tag: Tag path to judge.

  Returns:
    True when the tag is not a template placeholder and has no empty, `.`, or `..` path segment.
  """

  # Domain(unfiled):
  # # Tags that never become tag pages
  # A tag written as a template placeholder, with angle brackets around a name, is not a real tag and gets no page.
  # A tag whose hierarchy contains an empty, `.` or `..` segment is skipped as well, because such a segment
  # would escape or blur the page path that mirrors the tag hierarchy.

  # a placeholder from a template is not a real tag
  if "<" in tag or ">" in tag:
    return False
  return not any(segment in _BAD_SEGMENTS for segment in tag.split("/"))


def _is_scanned_note(rel: str) -> bool:
  """
  Tell whether a note's tags count toward the vault's tag set.

  Args:
    rel: Vault-relative path of the note, with `/` separators.

  Returns:
    False for notes in the system directory, in the tag-page directory, or under a dot-directory; otherwise True.
  """

  # Domain(unfiled):
  # # Notes that feed the vault's tag set
  # Notes in the vault's system directory never contribute tags, and neither do the tag pages themselves, since a
  # page is derived from the tags and must not feed them back. Notes under any dot-directory are hidden
  # material and never contribute tags either.

  # judge the note by its path segments
  parts = rel.split("/")

  # the system directory and the tag pages themselves never feed the tag set
  if parts[0] in (SYSTEM_DIR, TAGS_DIR):
    return False
  return not any(part.startswith(".") for part in parts[:-1])


def collect_tags(vault: Path) -> dict[str, list[str]]:
  """
  Collect every usable tag used in the vault's notes.

  Notes that cannot be read are ignored.

  Guarantees:
    - Tags are returned in sorted order, and each tag's notes are sorted.

  Args:
    vault: Root directory of the vault.

  Returns:
    Mapping from each tag to the vault-relative paths of the notes that carry it.
  """

  # Contract:
  # The mapping iterates its tags in sorted order, and each tag's notes are sorted.

  # walk every note of the vault, gathering the notes under each tag they declare
  found: dict[str, set[str]] = {}
  for rel in walk_md_files(vault, None):
    # guard: notes outside the scanned tree contribute nothing
    if not _is_scanned_note(rel):
      continue

    # guard: a note that cannot be read as UTF-8 text contributes nothing
    try:
      text = (vault / rel).read_text(encoding = ENCODING)
    except (OSError, UnicodeDecodeError):
      continue

    # every usable tag the note declares records the note under it
    for tag in parse_tags(text):
      if _is_usable_tag(tag):
        found.setdefault(tag, set()).add(rel)
  return { tag: sorted(notes) for tag, notes in sorted(found.items()) }


def _find_all_pages(vault: Path) -> set[str]:
  """
  List the tag pages that exist in the vault.

  Args:
    vault: Root directory of the vault.

  Returns:
    The tag path of every markdown page under the tag-page directory, without the file suffix.
  """
  root = vault / TAGS_DIR
  out: set[str] = set()

  # every markdown file under the tag-page directory is a page
  for dirpath, _dirnames, filenames in os.walk(root):
    for filename in filenames:
      if filename.endswith(NOTE_SUFFIX):
        # its tag path is the relative path with forward slashes and no suffix
        rel = Path(dirpath, filename).relative_to(root)
        out.add("/".join(rel.parts)[:-len(NOTE_SUFFIX)])
  return out


def build_plan(vault: Path) -> TagPlan:
  """
  Work out which tag pages to create, keep, and delete.

  Every parent prefix of a used tag also needs a page. Nothing is written to the vault.

  Args:
    vault: Root directory of the vault.

  Returns:
    The plan comparing the pages the vault needs with the pages that exist.
  """

  # Domain(unfiled):
  # # Tag pages mirror the tag hierarchy
  # The tag pages form a tree that mirrors the tag hierarchy: a slash-separated tag lives at the matching path
  # under the tag-page directory. Every parent prefix of a used tag needs a page of its own, even when no note
  # uses that prefix directly, so a nested tag is always reachable from the pages above it. A page whose tag is
  # no longer needed, neither used nor a parent prefix of a used tag, is stale.

  # the tags the notes use directly
  collected = collect_tags(vault)

  # every tag implies a page for each of its parent prefixes
  all_tags: set[str] = set(collected)
  for tag in collected:
    segments = tag.split("/")
    all_tags.update("/".join(segments[:depth]) for depth in range(1, len(segments)))

  # compare the wanted pages against the pages already on disk
  existing = _find_all_pages(vault)
  create = [ TagEntry(tag = tag, parent_only = tag not in collected, notes = collected.get(tag, []))
             for tag in sorted(all_tags - existing) ]
  return TagPlan(all_tags = sorted(all_tags), create = create,
                 keep = sorted(all_tags & existing), delete = sorted(existing - all_tags))


def _format_page_rel_path(tag: str) -> str:
  """
  Build the vault-relative path of a tag's page.

  Args:
    tag: Full slash-separated tag path.

  Returns:
    The page path under the tag-page directory.
  """
  return f"{TAGS_DIR}/{tag}{NOTE_SUFFIX}"


def _prune_empty_dirs(root: Path) -> None:
  """
  Remove the empty directories beneath a root directory.

  Args:
    root: Directory whose empty subdirectories are removed; the directory itself is kept.
  """
  for dirpath, _dirnames, _filenames in os.walk(root, topdown = False):
    directory = Path(dirpath)
    if directory != root and not os.listdir(directory):
      directory.rmdir()


def apply(vault: Path, summaries: dict[str, str]) -> ApplyResult:
  """
  Bring the vault's tag pages in step with its tags.

  Deletes pages no longer needed, prunes the directories this empties, and creates the missing pages from the
  consumer's tag-page template. An existing page is never overwritten.

  Guarantees:
    - Nothing is written when the call is refused.
    - The set of changes is derived from the vault's current state, never from a plan supplied by the caller.
    - An existing page is never overwritten.

  Args:
    vault: Root directory of the vault.
    summaries: Summary text per tag, which must cover every tag whose page is to be created.

  Returns:
    The tags created and deleted, the number of pages kept, and the paths of every page written or removed.

  Raises:
    TagPagesRefusedError: If the vault has no tag-page template, or a page to create has no summary.
  """

  # Contract:
  # A refused call leaves the vault untouched: every refusal is raised before any page is deleted or created.

  # Contract:
  # The changes applied are derived from the vault's state at the time of the call; an earlier `plan` report
  # is never replayed, so edits made since then are respected.

  # Contract:
  # A page that already exists is never overwritten; only missing pages are created.

  # guard: the consumer's template is the only source a page is built from
  template_path = vault / TEMPLATE_REL
  if not template_path.is_file():
    raise TagPagesRefusedError(MISSING_TEMPLATE_REASON)

  # read the template and derive the changes from the vault as it is now
  template = template_path.read_text(encoding = ENCODING)
  current = build_plan(vault)

  # guard: every page to create needs its description before anything is written
  if missing := [ entry.tag for entry in current.create if entry.tag not in summaries ]:
    raise TagPagesRefusedError(MISSING_SUMMARY_REASON.format(tags = ", ".join(missing)))

  # stale pages go first, then the directories they leave empty
  touched: list[str] = []
  for tag in current.delete:
    (vault / _format_page_rel_path(tag)).unlink()
    touched.append(_format_page_rel_path(tag))
  if current.delete:
    _prune_empty_dirs(vault / TAGS_DIR)

  # every new page is the template with its two tokens filled in
  for entry in current.create:
    body = template.replace(TAG_PATH_TOKEN, entry.tag).replace(SUMMARY_TOKEN, summaries[entry.tag])
    vault_manifest.write_bytes(vault / _format_page_rel_path(entry.tag), body.encode(ENCODING))
    touched.append(_format_page_rel_path(entry.tag))
  return ApplyResult(created = [ entry.tag for entry in current.create ], deleted = list(current.delete),
                     kept = len(current.keep), touched_paths = touched)


def resolve_summaries_path(vault: Path) -> Path:
  """
  Locate the file that carries the tag summaries between `plan` and `apply`.

  The file lies inside the repository's git directory, so it never shows up in the worktree.

  Args:
    vault: Root directory of the vault.

  Returns:
    The absolute path of the summaries file, which may not exist yet.

  Raises:
    TagPagesRefusedError: If the vault is not inside a git repository.
  """
  # waiver: git CLI vocabulary, not domain constants
  try:
    proc = subprocess.run([ "git", "rev-parse", "--git-path", SUMMARIES_NAME ], cwd = vault, check = False,
                          capture_output = True, text = True, encoding = ENCODING)
  except OSError as error:
    raise TagPagesRefusedError(NO_GIT_DIR_REASON.format(vault = vault)) from error

  # guard: outside a repository there is no git directory to hold the file
  if proc.returncode != 0 or not proc.stdout.strip():
    raise TagPagesRefusedError(NO_GIT_DIR_REASON.format(vault = vault))
  return (vault / proc.stdout.strip()).resolve()


def resolve_language(vault: Path) -> str:
  """
  Ask the core plugin which language the vault's tag pages are written in.

  Guarantees:
    - Never invents a language: when the core plugin cannot be found, or its language verb exits non-zero or
      answers nothing, the call raises `TagPagesRefusedError` and never returns a default code.

  Args:
    vault: Root directory of the vault, passed to core as the repository root.

  Returns:
    The language code core answers for the plugin's settings section.

  Raises:
    TagPagesRefusedError: If the core plugin cannot be found, or its language verb fails or answers nothing.
  """

  # Contract:
  # The function never invents a language. When the core plugin cannot be found,
  # or its language verb exits non-zero or answers nothing, it MUST raise
  # `TagPagesRefusedError` and NEVER return a default language code. The templated
  # apply relies on this to refuse instead of writing pages in a guessed language.

  # the core CLI lives in the first visible root that is the core plugin
  cli = next(( root / CORE_CLI_REL for root in resolve_plugin_roots(vault)
               if plugin_root_name(root) == CORE_PLUGIN and (root / CORE_CLI_REL).is_file() ), None)

  # guard: without core there is no language to fall back on
  if cli is None:
    raise TagPagesRefusedError(NO_CORE_REASON)

  # ask core for the language of the plugin's own settings section
  # waiver: core CLI vocabulary, not domain constants
  argv = [ sys.executable, str(cli), "resolve-language", "--section", SETTINGS_SECTION, "--cwd", str(vault) ]
  try:
    proc = subprocess.run(argv, check = False, capture_output = True, text = True, encoding = ENCODING)
  except OSError as error:
    raise TagPagesRefusedError(LANGUAGE_FAILED_REASON.format(code = None, detail = error)) from error

  # guard: a failed or empty answer refuses rather than guessing a language
  if proc.returncode != 0 or not proc.stdout.strip():
    raise TagPagesRefusedError(LANGUAGE_FAILED_REASON.format(code = proc.returncode,
                                                             detail = proc.stderr.strip() or "no answer"))
  return proc.stdout.rstrip("\n")


def templated_summaries(tags: list[str], language: str) -> dict[str, str]:
  """
  Build the fixed description line of each tag in the given language.

  Args:
    tags: Tags that need a description.
    language: Language code the lines are written in.

  Returns:
    Mapping from each tag to its description line, in the language's own wording or the default wording for any
    other language.
  """

  # Domain(unfiled):
  # # Templated tag page description
  # When tag pages are generated without a model, each new page gets one fixed description line that names the tag.
  # The line is worded in the vault's language: Russian has its own wording, and every other language gets the
  # English wording. The language is read from the plugin's own settings section and falls back to the repo-wide
  # setting when that section names none. Only new pages receive this line; an existing page is never rewritten.

  # every tag gets the same line, worded for the language
  line = TEMPLATED_LINES.get(language, TEMPLATED_DEFAULT_LINE)
  return { tag: line.format(tag = tag) for tag in tags }


def _read_summaries(path: Path) -> dict[str, str]:
  """
  Read the tag summaries the agent wrote.

  Args:
    path: Location of the JSON summaries file.

  Returns:
    The summary text per tag, or an empty mapping when the file does not exist.

  Raises:
    TagPagesRefusedError: If the file is unreadable or is not a JSON object of strings.
  """
  # guard: no file yet means no summary was written
  if not path.exists():
    return {}

  # an unreadable or unparseable file is refused as invalid
  try:
    data = json.loads(path.read_text(encoding = ENCODING))
  except (OSError, ValueError) as error:
    raise TagPagesRefusedError(SUMMARIES_INVALID_REASON.format(path = path)) from error

  # guard: only a flat map of strings is a set of summaries
  if not isinstance(data, dict) or not all(isinstance(value, str) for value in data.values()):
    raise TagPagesRefusedError(SUMMARIES_INVALID_REASON.format(path = path))
  return data


def _emit(payload: dict[str, object]) -> None:
  """
  Print a result as a single JSON line on standard output.

  Args:
    payload: Result to report.
  """
  print(json.dumps(payload, ensure_ascii = False))


def _run_plan(vault: Path) -> dict[str, object]:
  """
  Run the `plan` verb.

  Nothing is written to the vault.

  Args:
    vault: Root directory of the vault.

  Returns:
    The report with the planned status, the number of tags found, the entries to create, the tags to keep and
    delete, and the path of the summaries file the agent fills in.

  Raises:
    TagPagesRefusedError: If the vault is not inside a git repository.
  """
  current = build_plan(vault)
  return {
    "status": STATUS_PLANNED, "tags_found": len(current.all_tags),
    "create": [ { "tag": entry.tag, "parent_only": entry.parent_only, "notes": entry.notes }
                for entry in current.create ],
    "keep": current.keep, "delete": current.delete, "summaries_path": str(resolve_summaries_path(vault)),
  }


def _run_apply(vault: Path, summaries_file: Path) -> dict[str, object]:
  """
  Run the `apply` verb.

  Args:
    vault: Root directory of the vault.
    summaries_file: JSON file mapping each tag to its summary.

  Returns:
    The report with the applied status, the tags created and deleted, the number of pages kept, and the paths
    touched.

  Raises:
    TagPagesRefusedError: If the summaries file is invalid, the template is missing, or a page to create has no
      summary.
  """
  result = apply(vault, _read_summaries(summaries_file))

  # the summaries served their one run
  summaries_file.unlink(missing_ok = True)
  return _apply_report(result)


def _run_apply_templated(vault: Path) -> dict[str, object]:
  """
  Run the `apply` verb with the fixed description line in place of written summaries.

  Args:
    vault: Root directory of the vault.

  Returns:
    The report with the applied status, the tags created and deleted, the number of pages kept, and the paths
    touched.

  Raises:
    TagPagesRefusedError: If the vault's language cannot be resolved or the template is missing.
  """
  # the language is settled before anything is written
  language = resolve_language(vault)
  return _apply_report(apply(vault, templated_summaries(build_plan(vault).all_tags, language)))


def _apply_report(result: ApplyResult) -> dict[str, object]:
  """
  Shape an applied run's outcome as the `apply` verb's report.

  Args:
    result: Outcome of the applied run.

  Returns:
    The report with the applied status, the tags created and deleted, the number of pages kept, and the paths
    touched.
  """
  return { "status": STATUS_APPLIED, "created": result.created, "deleted": result.deleted, "kept": result.kept,
           "touched_paths": result.touched_paths, "reason": None }


def main(argv: list[str]) -> int:
  """
  Run the `tag-pages` command line.

  Reports or applies the tag-page changes and writes the result as one JSON line on standard output; a refusal
  carries its reason there.

  Guarantees:
    - The summaries file is deleted only after the pages were applied successfully.

  Notes:
    - A refused run writes nothing.

  Args:
    argv: Command-line arguments after the program name: the verb, then `--vault` and, for `apply`, either
      `--summaries` or `--templated`, never both.

  Returns:
    The exit code: 0 on success, 1 when the run was refused. Invalid arguments exit with 2 through the parser.
  """

  # Contract:
  # The summaries file is deleted only after the `apply` verb applied the pages successfully;
  # a refused run leaves it in place.

  # parse the verb and its options
  # waiver: argparse CLI signature
  parser = argparse.ArgumentParser(prog = "lazycortex-obsidian tag-pages")
  # waiver: argparse CLI signature
  sub = parser.add_subparsers(dest = "command", required = True)
  for name, help_text in ((VERB_PLAN, "report the tag pages to create, keep and delete"),
                          (VERB_APPLY, "delete stale tag pages and create the missing ones")):
    child = sub.add_parser(name, help = help_text)
    # waiver: argparse CLI signature
    child.add_argument("--vault", help = "vault root (default: the git toplevel of the cwd)")
    if name == VERB_APPLY:
      source = child.add_mutually_exclusive_group()
      # waiver: argparse CLI signature
      source.add_argument("--summaries", help = "JSON map of tag -> summary (default: the plan's summaries_path)")
      # waiver: argparse CLI signature
      source.add_argument("--templated", action = "store_true",
                          help = "describe each new page with a fixed line naming its tag; no summaries needed")
  args = parser.parse_args(argv)

  # every refusal is one JSON line with its reason, and nothing written
  try:
    vault = find_vault(args.vault)
    if args.command == VERB_PLAN:
      _emit(_run_plan(vault))
    elif args.templated:
      _emit(_run_apply_templated(vault))
    else:
      _emit(_run_apply(vault, Path(args.summaries) if args.summaries else resolve_summaries_path(vault)))
  except (TagPagesRefusedError, IconizeError) as error:
    reason = error.reason if isinstance(error, TagPagesRefusedError) else str(error)
    empty: dict[str, object] = { "created": [], "deleted": [], "kept": 0, "touched_paths": [] } \
        if args.command == VERB_APPLY else {}
    _emit({ "status": STATUS_REFUSED, **empty, "reason": reason })
    return EXIT_REFUSED
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
