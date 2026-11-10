"""
Domain-spec engine for lazycortex-wiki.

Materialises `Domain(…)` comment blocks found in code into the domain-spec
tree under the configured output directory. Provides the deterministic half
of the pipeline: configuration loading, dictionary parsing, block extraction,
per-group content hashing, changed/orphaned/unknown detection, the
`domains.md` index render, and the landing that places a writer's returned
document in the tree. The LLM writer that composes each group document
is dispatched by the CLI consumer, never from here.

Cross-plugin Python import is forbidden (per the inter-plugin boundary
contract), so all primitives used here are imported from within this
plugin's own `bin/`.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The flat bin/ directory goes first on sys.path once, so the sibling imports below resolve
_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import block_owner as _owner  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import explainers as _explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scope as _scope  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from textfile import TextFile  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# ────────────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────────────

# Settings file location and section keys.
_SETTINGS_PATH = ".claude/lazy.settings.json"
_WIKI_KEY      = "wiki"
_DOMAINS_KEY   = "domains"

# `wiki.domains` config keys and their defaults.
_KEY_CODE           = "code"
_KEY_DICTIONARY     = "dictionary"
_KEY_OUTPUT         = "output"
_KEY_LANGUAGE       = "language"
_DEFAULT_DICTIONARY = "docs/guidelines/domain-groups.md"
_DEFAULT_OUTPUT     = "docs/domains"
_DEFAULT_LANGUAGE   = "English"

# Error text raised when the loaded configuration is read without a `wiki.domains` section.
_MSG_UNCONFIGURED = "wiki.domains is not configured"

# The reserved parking group — never generated, never listed in the dictionary.
RESERVED_GROUP = "unfiled"

# Index file name inside the output directory.
INDEX_NAME = "domains.md"

# Markdown extension of generated docs.
_MD_EXT = ".md"

# What a markdown file under the output tree is: the note opening a group folder, or one block's doc.
KIND_FOLDER_NOTE = "folder-note"
KIND_BLOCK_DOC   = "block-doc"

# File encoding used throughout.
_ENCODING = "utf-8"

# Frontmatter key carrying the generation-time content hash of a group doc.
FM_DOMAIN_HASH = "domain_hash"

# Frontmatter keys naming the group a generated doc belongs to, and — on a block doc only — the
# title of the block it was written from.
FM_DOMAIN_GROUP = "domain_group"
FM_DOMAIN_BLOCK = "domain_block"

# Frontmatter key naming the folder an engine-written section note opens.
FM_DOMAIN_SECTION = "domain_section"

# Frontmatter key carrying a generated doc's tag list.
FM_TAGS = "tags"

# The tag a writer puts on a doc whose block disagrees with the code it describes.
DISCREPANCY_TAG = "domains/discrepancy"

# Settings key carrying the repository-wide tag-axis vocabulary (`wiki.tag_axes`).
_KEY_TAG_AXES = "tag_axes"

# Opening line of a `Domain(…)` block: `# Domain(<group>):` with optional tags after the colon.
_DOMAIN_HEADER_RE = re.compile(r"^\s*#\s*Domain\s*\(\s*([A-Za-z0-9_.-]+)\s*\)\s*:")

# Opening line of a `Contract:` block: bare marker, canon requires nothing after the colon.
_CONTRACT_HEADER_RE = re.compile(r"^\s*#\s*Contract:\s*$")

# A block-continuation line: any adjacent `#` comment line.
_COMMENT_LINE_RE = re.compile(r"^\s*#")

# The title line of a `Domain(…)` block: `# # <heading>`, the first body line after the header.
_BLOCK_TITLE_RE = re.compile(r"^\s*#\s*#\s*(.+?)\s*$")

# Block-dict field names shared by scanner, planner, and CLI consumers.
BLOCK_GROUP   = "group"
BLOCK_PATH    = "path"
BLOCK_LINE    = "line"
BLOCK_TEXT    = "text"
BLOCK_SYMBOL  = "symbol"
BLOCK_HEADING = "heading"
BLOCK_OWNER   = "owner_digest"

# Plan-dict field names (the `domain-plan` JSON contract).
PLAN_CHANGED    = "changed_groups"
PLAN_ORPHANED   = "orphaned_docs"
PLAN_UNLISTED   = "unlisted_docs"
PLAN_UNKNOWN    = "unknown_groups"
PLAN_INDEX_PATH = "index_path"
PLAN_INDEX_STALE = "index_needs_update"
PLAN_LANGUAGE   = "language"
PLAN_DICTIONARY = "dictionary"
PLAN_OUTPUT     = "output"
PLAN_ANCHOR_FIXES = "anchor_fixes"
PLAN_LINK_FIXES = "link_fixes"
PLAN_CONTRACT_DROPS = "contract_drops"
PLAN_ORPHAN_REASONS = "orphan_reasons"
PLAN_UNTITLED   = "untitled_blocks"
PLAN_CATALOG    = "catalog"

# Catalog field names: every document and every group of the tree, for the writer to link from.
CATALOG_BLOCKS = "blocks"
CATALOG_GROUPS = "groups"

# Anchor-fix entry field names (one per stale contract anchor a current doc prints), and the
# link-fix field naming one dead `## Related` line.
FIX_DOC  = "doc"
FIX_OLD  = "old"
FIX_NEW  = "new"
FIX_LINE = "line"

# Restamp result field names.
RESTAMP_DOCS    = "docs"
RESTAMP_ANCHORS = "anchors_repaired"

# The `## Contracts` heading of a generated doc, and the heading that closes its section.
_CONTRACTS_HEADING = "## Contracts"
_HEADING_RE = re.compile(r"^#{1,2} ")

# A contract anchor as the writer prints it at the end of a Contracts bullet: a parenthesised,
# backticked `path:symbol`, or a bare `path` for a symbol-less contract.
_ANCHOR_RE = re.compile(r"\(`([^`:]+)(?::([^`]+))?`\)\s*$")

# The `domain_hash:` line of a generated doc's frontmatter, rewritten in place by `restamp`.
_DOMAIN_HASH_LINE_RE = re.compile(rf"^{FM_DOMAIN_HASH}:")

# The frontmatter fence line.
_FENCE = "---"

# A doc's title heading, and a whole-line italic such as the explainer line under it.
_TITLE_PREFIX = "# "
_ITALIC_LINE_RE = re.compile(r"^\*[^*\s].*\*\s*$")

# Changed-group entry field names.
GROUP_KEY   = "group"
GROUP_HASH  = "hash"
GROUP_FILES = "files"
GROUP_DOC   = "doc_path"
GROUP_GLOSS = "gloss"
GROUP_BLOCKS = "blocks"
GROUP_CONTRACTS = "contracts"
GROUP_FOLDER_NOTE = "folder_note_path"
GROUP_DOCS  = "docs"
GROUP_STALE = "stale_docs"

# Document-entry field names beside the shared group ones (`doc_path`, `hash`, `blocks`, `contracts`).
DOC_HEADING = "heading"
DOC_SLUG    = "slug"

# Why a generated doc is on the removal list.
DOC_REASON_NO_BLOCKS  = "no-blocks"
DOC_REASON_UNLISTED   = "group-unlisted"
DOC_REASON_BLOCK_GONE = "block-gone"
DOC_REASON_LEGACY     = "legacy-layout"

# Domain-spec writer payload field names for the tag-canon inputs the writer consumes.
PAYLOAD_TAG_AXES       = "tag_axes"
PAYLOAD_EXISTING_TAGS  = "existing_tags"
PAYLOAD_TAG_DICTIONARY = "tag_dictionary"

# Domain-spec writer payload field carrying the display name of the configured language code.
PAYLOAD_LANGUAGE_NAME  = "language_name"

# Domain-spec writer payload fields carrying the tree-wide catalog the writer links from.
PAYLOAD_CATALOG_BLOCKS = "catalog_blocks"
PAYLOAD_CATALOG_GROUPS = "catalog_groups"

# The `## Related` heading of a generated doc, and the link target of a markdown link.
_RELATED_HEADING = "## Related"
_LINK_TARGET_RE = re.compile(r"\]\(([^)\s]+)\)")

# A comment line's leading marker, the first sentence of a prose run, and the gloss length cap.
_COMMENT_PREFIX_RE = re.compile(r"^\s*#\s?")
_SENTENCE_RE = re.compile(r"(.+?[.!?])(?:\s|$)")
_GLOSS_LIMIT = 220


# ────────────────────────────────────────────────────────────────────────────
class DomainConfig:
  """
  The `wiki.domains` configuration block of one repository.

  Attributes:
    repo: Absolute repository root the configuration belongs to.
    code: Glob patterns naming the code files scanned for `Domain(…)` blocks.
    dictionary: Repo-relative path of the domain-groups dictionary file.
    output: Repo-relative path of the generated domain-spec tree.
    language: Language the generated documents are written in.
  """

  def __init__(self, *,
               repo: Path,
               code: list[str],
               dictionary: str,
               output: str,
               language: str) -> None:
    """
    Initialise the configuration holder.

    Args:
      repo: Absolute repository root.
      code: Glob patterns for code files carrying `Domain(…)` blocks.
      dictionary: Repo-relative dictionary path.
      output: Repo-relative output directory path.
      language: Target language of generated documents.
    """
    # the loaded settings values, defaults already applied by `load`
    self.repo: Path = repo
    self.code: list[str] = code
    self.dictionary: str = dictionary
    self.output: str = output
    self.language: str = language

  @property
  def language_code(self) -> str:
    """
    The configured language narrowed to an ISO 639-1 code — a legacy free-form
    name is mapped through the compatibility table, a code passes through unchanged.
    """
    # the raw setting may still hold a pre-code free-form name for one release
    return _explainers.language_code(self.language)

  @classmethod
  def load(cls, repo: Path) -> DomainConfig | None:
    """
    Read `wiki.domains` from the repo's settings file.

    Args:
      repo: Absolute repository root that owns `.claude/lazy.settings.json`.

    Returns:
      A populated `DomainConfig`, or `None` when the settings file is absent
      or carries no usable `wiki.domains` section.
    """
    settings_file = Path(repo) / _SETTINGS_PATH

    # guard: settings file does not exist — domains are not configured
    if not settings_file.is_file():
      return None
    with settings_file.open(encoding = _ENCODING) as handle:
      data = json.load(handle)
    domains = data.get(_WIKI_KEY, {}).get(_DOMAINS_KEY)

    # guard: section absent or not a dict — domains are not configured
    if not isinstance(domains, dict) or not domains:
      return None

    # apply defaults for every key the operator may omit
    return cls(
      repo       = Path(repo).resolve(),
      code       = list(domains.get(_KEY_CODE) or []),
      dictionary = str(domains.get(_KEY_DICTIONARY) or _DEFAULT_DICTIONARY),
      output     = str(domains.get(_KEY_OUTPUT) or _DEFAULT_OUTPUT).rstrip("/"),
      language   = str(domains.get(_KEY_LANGUAGE) or _DEFAULT_LANGUAGE),
    )


# ────────────────────────────────────────────────────────────────────────────
class DomainDictionary:
  """
  Parser for the domain-groups dictionary markdown file.

  Each `## <group>` heading declares one group; the first non-empty prose
  line under it is the group's one-line gloss. The reserved `unfiled` group
  is never a dictionary entry and is dropped when present.
  """

  # The markdown markers the dictionary parser recognises: a group heading, its tag line, a comment line
  _HEADING_PREFIX = "## "
  _TAGS_PREFIX    = "Tags:"
  _COMMENT_PREFIX = "<!--"

  def __init__(self, *, path: Path) -> None:
    """
    Initialise the parser for one dictionary file.

    Args:
      path: Absolute path of the dictionary markdown file.
    """
    # the dictionary location; existence is checked lazily by the readers
    self._path = path

  def is_present(self) -> bool:
    """
    Report whether the dictionary file is present on disk.

    Returns:
      True when the file exists, False otherwise.
    """
    return self._path.is_file()

  def read_groups(self) -> dict[str, str]:
    """
    Parse the dictionary and return its group→gloss mapping.

    Guarantees:
      - The reserved `unfiled` group is never a key of the returned mapping,
        even when the dictionary file declares it.

    Returns:
      Mapping of group key to one-line gloss (empty string when a group has
      no prose line). Empty when the file is absent.
    """

    # Contract:
    # The reserved `unfiled` group is NEVER a key of the returned mapping,
    # even when the dictionary file declares it as an entry.

    # Domain(wiki.domains):
    # # How the dictionary declares a group
    # The dictionary is the project's registry of legal groups: each entry is announced by its own
    # heading, and the first line of prose beneath it is the group's one-line gloss, reused wherever
    # the group is listed. An entry without prose is legal and simply carries no gloss. A group name
    # is a dotted hierarchy, and that hierarchy is also the shape of the published tree, so naming a
    # group is a filing decision. The reserved parking group is the one name the registry may never
    # hold — it marks knowledge whose real group is not agreed yet, and admitting it as a declared
    # group would make the parking permanent instead of temporary.

    # guard: dictionary file absent — no groups
    if not self._path.is_file():
      return {}
    result: dict[str, str] = {}
    current: str | None = None
    for raw in self._path.read_text(encoding = _ENCODING).splitlines():
      line = raw.strip()

      # a `## <group>` heading opens a new group entry
      if line.startswith(self._HEADING_PREFIX):
        current = line[len(self._HEADING_PREFIX):].strip()

        # guard: the reserved parking group is never a dictionary entry
        if current == RESERVED_GROUP:
          current = None
          continue
        result[current] = ""
        continue

      # prose outside any group, blank lines, sub-headings, Tags: lines, comments
      if (
        current is None
        or not line
        or line.startswith(( "#", self._TAGS_PREFIX, self._COMMENT_PREFIX ))
      ):
        continue

      # the first prose line under the heading is the gloss
      if not result[current]:
        result[current] = line
    return result


# ────────────────────────────────────────────────────────────────────────────
class DomainScanner:
  """
  Extractor of `Domain(…)` blocks from the repo's code files.

  Only files tracked by the repository and matching the configured code globs are
  considered; the extracted blocks are returned grouped by their declared group key.
  """

  def __init__(self, *, repo: Path, code_globs: list[str]) -> None:
    """
    Initialise the scanner for one repository.

    Args:
      repo: Absolute repository root.
      code_globs: Glob patterns selecting the code files to sweep.
    """
    # the roots of the sweep: repo for git enumeration, globs for the file filter
    self._repo = Path(repo).resolve()
    self._globs = code_globs
    self._matcher = _scope.GlobMatcher()

    # opt: one owner index per distinct file text, shared by the block and the contract sweep so a file is
    # parsed once; correct because an index depends only on the text it was built from
    self._owners: dict[str, _owner.OwnerIndex] = {}

  def scan(self) -> dict[str, list[dict]]:
    """
    Return every `Domain(…)` block found in the repo's code files, grouped by group key.

    Guarantees:
      - Blocks of one group are ordered by file path, then by line, on every
        scan of the same checkout.

    Returns:
      Mapping of group key to its block dicts (`group`, `path`, `line`, `text`, `heading`,
      `owner_digest`), each list sorted by `(path, line)` for a stable order. `owner_digest` is the
      digest of the code that owns the block.
    """

    # Contract:
    # Blocks of one group are ALWAYS ordered by file path, then by line number;
    # callers that digest a group's text rely on that order being reproducible.

    # collect every block, bucketed by its group key
    groups: dict[str, list[dict]] = {}
    for rel in self._code_files():
      for block in self._extract_blocks(self._repo / rel, rel):
        groups.setdefault(block[BLOCK_GROUP], []).append(block)

    # stable order inside each group: file path, then position in the file
    for blocks in groups.values():
      blocks.sort(key = lambda blk: (blk[BLOCK_PATH], blk[BLOCK_LINE]))
    return groups

  def _code_files(self) -> list[str]:
    """
    Enumerate the repo-relative paths of code files matching the globs.

    Returns:
      Sorted list of repo-relative POSIX paths; empty when the repo is not a
      git checkout or no file matches.
    """
    proc = subprocess.run(
      [ "git", "ls-files" ],
      cwd = str(self._repo),
      capture_output = True,
      text = True,
      check = False, encoding = "utf-8",
    )

    # guard: not a git repo — nothing to scan
    if proc.returncode != 0:
      return []

    # keep only the files a configured code glob claims
    tracked = [ line for line in proc.stdout.splitlines() if line ]
    return sorted(
      rel for rel in tracked
      if any(self._matcher.match(rel, pat) for pat in self._globs)
    )

  def _extract_blocks(self, abs_path: Path, rel: str) -> list[dict]:
    """
    Extract every `Domain(…)` block from one file.

    Args:
      abs_path: Absolute path of the file to sweep.
      rel: Repo-relative POSIX path recorded on each block.

    Returns:
      List of block dicts in file order; empty when the file is unreadable
      or carries no block.
    """
    try:
      text = abs_path.read_text(encoding = _ENCODING)
    except (OSError, UnicodeDecodeError):
      # guard: unreadable or non-text file — nothing to extract
      return []

    # Domain(wiki.domains):
    # # What a knowledge block is and where it ends
    # A knowledge block is a run of adjacent comment lines opened by a header naming the group the
    # knowledge belongs to. The run continues while the following lines are comments and ends at the
    # first line that is not one, or at the next header — one uninterrupted comment paragraph carries
    # exactly one concept, so a blank line between two paragraphs separates two blocks. Every block is
    # recorded with the file and the line it was written at, so the published document can send a
    # reader back to the code the rule governs.

    # the code each block is about, looked up per block below
    owners = self._ensure_owner_index(text)

    # sweep line by line: a header opens a block, adjacent comment lines extend it
    blocks: list[dict] = []
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
      match = _DOMAIN_HEADER_RE.match(lines[idx])

      # not a block header — keep sweeping
      if not match:
        idx += 1
        continue
      start = idx
      body = [ lines[idx].strip() ]
      idx += 1
      while (
        idx < len(lines)
        and _COMMENT_LINE_RE.match(lines[idx])
        and not _DOMAIN_HEADER_RE.match(lines[idx])
      ):
        body.append(lines[idx].strip())
        idx += 1

      # Domain(wiki.domains):
      # # A block is named by its title line
      # The first body line of a knowledge block is its title, written as a second-level comment
      # heading. That title names the published document the block becomes and is the only name the
      # document has; a block whose first body line is not a title is recorded without a heading, and
      # the planner reports it instead of inventing a name for it.

      # the title line, when the block opens with one
      title = _BLOCK_TITLE_RE.match(body[1]) if len(body) > 1 else None
      blocks.append({
        BLOCK_GROUP:   match.group(1),
        BLOCK_PATH:    rel,
        BLOCK_LINE:    start + 1,
        BLOCK_TEXT:    "\n".join(body),
        BLOCK_HEADING: title.group(1) if title else None,
        BLOCK_OWNER:   owners.digest_at(start + 1),
      })
    return blocks

  @staticmethod
  def attribute_contracts(blocks: list[dict], contracts: list[dict]) -> list[list[dict]]:
    """
    Attribute every contract to the nearest block of its own file.

    Guarantees:
      - The result is index-aligned with `blocks`; a contract whose file carries
        no block is dropped.

    Args:
      blocks: One group's `Domain(…)` block dicts.
      contracts: The same group's attributed `Contract:` block dicts.

    Returns:
      One contract list per block, in `blocks` order; each contract appears in
      exactly one list, under the block nearest to it by line in the same file.
    """

    # Contract:
    # The returned list is ALWAYS index-aligned with `blocks`, and a contract whose
    # file carries no block of this group is dropped rather than attributed elsewhere.

    # nearest-by-line attribution within the contract's own file
    per_block: list[list[dict]] = [ [] for _blk in blocks ]
    for contract in contracts:
      distances = [
        (abs(blk[BLOCK_LINE] - contract[BLOCK_LINE]), idx)
        for idx, blk in enumerate(blocks)
        if blk[BLOCK_PATH] == contract[BLOCK_PATH]
      ]

      # guard: no block of this group in the contract's file — nothing to attribute to
      if not distances:
        continue
      per_block[min(distances)[1]].append(contract)
    return per_block

  def scan_contracts(self) -> dict[str, list[dict]]:
    """
    Return every `Contract:` block found in the repo's code files, grouped by
    the domain group it neighbours.

    The `Contract:` marker carries no group of its own — a block is attributed
    to the domain group of the nearest `Domain(…)` header in the same file (by
    line distance); a file with no `Domain(…)` header carries no attributable
    contract, so its `Contract:` blocks are dropped.

    Guarantees:
      - Every returned contract is filed under the group of the nearest
        `Domain(…)` header in its own file; a file with no such header
        contributes none.
      - Contracts of one group are ordered by file path, then by line, on every
        scan of the same checkout.

    Returns:
      Mapping of group key to its contract block dicts (`group`, `path`, `line`, `text`, `symbol`,
      `owner_digest`), each list sorted by `(path, line)`. `owner_digest` is the digest of the code
      that owns the block.
    """

    # Contract:
    # A returned contract is ALWAYS filed under the group of the nearest
    # `Domain(…)` header in its own file; a file carrying no such header
    # contributes no contract at all.

    # Contract:
    # Contracts of one group are ALWAYS ordered by file path, then by line
    # number; callers that digest a group's text rely on that order.

    # collect every attributable contract, bucketed by the group it neighbours
    groups: dict[str, list[dict]] = {}
    for rel in self._code_files():
      for block in self._extract_contract_blocks(self._repo / rel, rel):
        groups.setdefault(block[BLOCK_GROUP], []).append(block)

    # stable order inside each group: file path, then position in the file
    for blocks in groups.values():
      blocks.sort(key = lambda blk: (blk[BLOCK_PATH], blk[BLOCK_LINE]))
    return groups

  def _extract_contract_blocks(self, abs_path: Path, rel: str) -> list[dict]:
    """
    Extract every attributable `Contract:` block from one file.

    Args:
      abs_path: Absolute path of the file to sweep.
      rel: Repo-relative POSIX path recorded on each block.

    Returns:
      List of block dicts in file order; empty when the file is unreadable,
      carries no `Contract:` block, or carries no `Domain(…)` header to
      attribute one to.
    """
    try:
      text = abs_path.read_text(encoding = _ENCODING)
    except (OSError, UnicodeDecodeError):
      # guard: unreadable or non-text file — nothing to extract
      return []

    # the file's own lines are the sweep target for both headers and bodies below
    lines = text.splitlines()

    # Domain(wiki.domains):
    # # How a recorded guarantee inherits a group
    # A recorded guarantee names no group of its own, so it is filed under the concept it stands
    # nearest to: the group of the closest knowledge header in the same file, measured in lines. A
    # file that documents no concept offers nothing to attribute to, and the guarantees written in it
    # stay out of every published document until a knowledge block joins that file.

    # the neighbourhood a contract inherits its group from: every Domain header's position
    domain_lines = [
      (idx, match.group(1))
      for idx, line in enumerate(lines)
      if (match := _DOMAIN_HEADER_RE.match(line))
    ]

    # guard: no Domain header anywhere in the file — nothing to attribute to
    if not domain_lines:
      return []

    # the AST symbol index this file's contracts anchor their `path:symbol` entry to, and the code each
    # contract is about
    symbol_spans = self._collect_symbol_spans(text)
    owners = self._ensure_owner_index(text)

    # sweep line by line: a header opens a block, adjacent comment lines extend it
    blocks: list[dict] = []
    idx = 0
    while idx < len(lines):
      # not a contract header — keep sweeping
      if not _CONTRACT_HEADER_RE.match(lines[idx]):
        idx += 1
        continue
      start = idx
      body = [ lines[idx].strip() ]
      idx += 1
      while (
        idx < len(lines)
        and _COMMENT_LINE_RE.match(lines[idx])
        and not _DOMAIN_HEADER_RE.match(lines[idx])
        and not _CONTRACT_HEADER_RE.match(lines[idx])
      ):
        body.append(lines[idx].strip())
        idx += 1

      # Decision: nearest-Domain-header attribution, not an `unfiled`-style parking group —
      # a contract carries no dictionary entry of its own to grow, and `unfiled` already
      # means "a real group not yet known"; a file with zero Domain headers drops its
      # contracts above rather than parking them, since nothing would ever refile them.

      # record the block under its resolved group, with the anchor its Contracts entry needs
      group = min(domain_lines, key = lambda header: abs(header[0] - start))[1]
      blocks.append({
        BLOCK_GROUP:  group,
        BLOCK_PATH:   rel,
        BLOCK_LINE:   start + 1,
        BLOCK_TEXT:   "\n".join(body),
        BLOCK_SYMBOL: self._find_symbol_at(symbol_spans, start + 1),
        BLOCK_OWNER:  owners.digest_at(start + 1),
      })
    return blocks

  def _ensure_owner_index(self, text: str) -> _owner.OwnerIndex:
    """
    Return the owner index of one file text, building it on first request.

    Args:
      text: Full text of the file.

    Returns:
      The owner index of `text`.
    """
    return self._owners.setdefault(text, _owner.OwnerIndex(text))

  @staticmethod
  def _collect_symbol_spans(source: str) -> list[tuple[int, int, str]]:
    """
    Map every function/class body in a source file to its line span and qualified name.

    Args:
      source: Full text of the source file.

    Returns:
      List of `(start_line, end_line, qualname)` tuples, dotted (`Class.method`)
      for a nested definition; empty when the source does not parse as Python.
    """
    try:
      tree = ast.parse(source)
    except (SyntaxError, ValueError):
      # guard: not Python, or not parseable — no symbols to anchor to
      return []

    # accumulated as the recursive descent below finds each def/class node
    spans: list[tuple[int, int, str]] = []

    # descends the tree carrying the dotted qualname prefix of every class/def already entered
    def walk(node: ast.AST, prefix: str) -> None:
      for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
          qualname = f"{prefix}.{child.name}" if prefix else child.name
          spans.append((child.lineno, getattr(child, "end_lineno", child.lineno), qualname))
          walk(child, qualname)
        else:
          walk(child, prefix)

    # descend from the module root with an empty qualname prefix
    walk(tree, "")
    return spans

  @staticmethod
  def _find_symbol_at(spans: list[tuple[int, int, str]], line: int) -> str | None:
    """
    Resolve the innermost function/class enclosing a source line.

    Args:
      spans: This file's `(start_line, end_line, qualname)` spans.
      line: One-based source line to resolve.

    Returns:
      The innermost enclosing qualname, or `None` when no span covers the line.
    """
    covering = [ span for span in spans if span[0] <= line <= span[1] ]

    # guard: no enclosing function/class — module level, or unparsed source
    if not covering:
      return None

    # innermost = smallest span
    return min(covering, key = lambda span: span[1] - span[0])[2]


# ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen = True)
class DocRef:
  """
  What one markdown file under the output tree is, by its place in the tree.

  Attributes:
    kind: `KIND_FOLDER_NOTE` or `KIND_BLOCK_DOC`.
    group: Dot-separated key of the group whose folder holds the file; empty for a file
      directly under the output directory, which belongs to no group folder.
    slug: The file's stem for a block doc; `None` for a folder note.
  """

  kind: str
  group: str
  slug: str | None


# ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen = True)
class _Survey:
  """
  One read of the code and the dictionary, shared by the plan and the restamp.

  Attributes:
    dictionary: Group→gloss mapping from the dictionary file.
    scanned: Group→blocks mapping from the code scan.
    contracts: Group→contracts mapping from the code scan.
    layout: Path mapper for the output directory.
    folded: The documents of every listed group with blocks, in slug order.
    untitled: The `{group, path, line}` of every listed block without a title.
  """

  dictionary: dict[str, str]
  scanned: dict[str, list[dict]]
  contracts: dict[str, list[dict]]
  layout: DomainLayout
  folded: dict[str, list[dict]]
  untitled: list[dict]


# ────────────────────────────────────────────────────────────────────────────
class DomainLayout:
  """
  Path mapping between group keys, block slugs and generated doc locations.

  Every dot-separated key segment expands into a directory under the output
  directory; the group's folder holds its folder note, named like the folder,
  and one document per block, named by the block's slug.

  Guarantees:
    - Every derived folder-note or block-doc path classifies back to the group
      it was derived from; a block doc never lands on its group's folder note.
  """

  # Contract:
  # Every folder-note or block-doc path the layout derives MUST classify back to the
  # group it was derived from, and a block doc NEVER takes its folder note's path.

  # Suffix appended to a block slug that equals the folder name, so the doc misses the folder note.
  _CLASH_SUFFIX = "-block"

  # Runs of characters a slug never carries.
  _SLUG_SPLIT_RE = re.compile(r"[^a-z0-9]+")

  def __init__(self, *, output: str) -> None:
    """
    Initialise the layout for one output directory.

    Args:
      output: Repo-relative POSIX path of the output directory (no trailing slash).
    """
    # the tree root every doc path is derived under
    self._output = output

  def group_dir(self, group: str) -> str:
    """
    Return the repo-relative folder of a group.

    Args:
      group: Dot-separated group key.

    Returns:
      Repo-relative POSIX path of the group's folder.
    """
    return "/".join([ self._output, *group.split(".") ])

  def folder_note_rel(self, group: str) -> str:
    """
    Return the repo-relative path of a group's folder note.

    Args:
      group: Dot-separated group key.

    Returns:
      Repo-relative POSIX path of the note named like the group's folder, inside it.
    """
    return f"{self.group_dir(group)}/{group.rsplit('.', 1)[-1]}{_MD_EXT}"

  def doc_rel(self, group: str, slug: str) -> str:
    """
    Return the repo-relative path of one block's document.

    Args:
      group: Dot-separated group key.
      slug: The block's slug, from `slug_for`.

    Returns:
      Repo-relative POSIX path of the block doc inside the group's folder.
    """

    # Domain(wiki.domains):
    # # A block document never takes the folder note's place
    # Every group folder is opened by a note named like the folder itself. A block whose title folds to
    # that same name — letter case aside, since a file system may not tell them apart — would otherwise
    # overwrite the note, so its document takes the name with a fixed suffix instead, and the folder
    # keeps both.

    # a slug equal to the folder name, in any letter case, moves aside so the folder note keeps its path
    stem = slug + self._CLASH_SUFFIX if slug == group.rsplit(".", 1)[-1].lower() else slug
    return f"{self.group_dir(group)}/{stem}{_MD_EXT}"

  @staticmethod
  def compute_section_prefixes(groups: list[str]) -> list[str]:
    """
    List the folders above the given groups that are not groups themselves.

    Args:
      groups: Group keys whose folders exist.

    Returns:
      Every proper key prefix of a group that is not itself one of the groups, sorted.
    """

    # Domain(wiki.domains):
    # # A folder above the groups is a section
    # A group key lays out one folder per segment, so the folders of its leading segments hold other folders
    # rather than documents. Such a folder is a section of the tree: it carries no knowledge of its own and
    # is opened by a note the engine writes, listing the groups and sections directly inside it. A folder
    # that is itself a group's is opened by that group's own note instead.

    # every leading-segment prefix of every group, minus the groups themselves
    keys = set(groups)
    prefixes = {
      ".".join(segments[:depth])
      for segments in ( group.split(".") for group in groups )
      for depth in range(1, len(segments))
    }
    return sorted(prefixes - keys)

  def legacy_doc_rel(self, group: str) -> str:
    """
    Return the path the retired one-document-per-group layout gave a group.

    Args:
      group: Dot-separated group key.

    Returns:
      Repo-relative POSIX path of the flat doc beside the group's folder.
    """
    return self.group_dir(group) + _MD_EXT

  @classmethod
  def slug_for(cls, heading: str) -> str:
    """
    Fold a block heading into the file stem of its document.

    Args:
      heading: The block's title line text.

    Returns:
      Lowercase ASCII letters and digits joined by single hyphens; empty when the
      heading carries none.
    """
    return cls._SLUG_SPLIT_RE.sub("-", heading.lower()).strip("-")

  def classify(self, rel: str) -> DocRef | None:
    """
    Say what one file under the output tree is, by its place in the tree.

    Args:
      rel: Repo-relative POSIX path.

    Returns:
      The file's `DocRef`, or `None` when the path is outside the output
      directory, is not markdown, or is the index file.
    """
    prefix = self._output + "/"

    # guard: outside the output tree or not a markdown doc
    if not rel.startswith(prefix) or not rel.endswith(_MD_EXT):
      return None
    parts = rel[len(prefix):-len(_MD_EXT)].split("/")

    # guard: the index file is never a group doc
    if parts == [ INDEX_NAME[:-len(_MD_EXT)] ]:
      return None

    # a file named like the folder holding it opens that folder; anything else is a block doc
    if len(parts) > 1 and parts[-1] == parts[-2]:
      return DocRef(KIND_FOLDER_NOTE, ".".join(parts[:-1]), None)
    return DocRef(KIND_BLOCK_DOC, ".".join(parts[:-1]), parts[-1])


# ────────────────────────────────────────────────────────────────────────────
class DomainIndex:
  """
  Renderer of the `domains.md` index inside the output directory.

  Owns the title, the group listing — one line per group folder note, linking its group
  key with the dictionary gloss — and the `## Discrepancies` list of docs tagged as
  disagreeing with their code; the rest of the file is operator territory.

  Guarantees:
    - Preserves everything from the first `##` heading other than `## Discrepancies`
      onward verbatim across rebuilds.
    - Seeds a brand-new index with a `## Context map` stub.
  """

  # Contract:
  # Everything from the index's first `##` heading other than the engine's own
  # `## Discrepancies` list onward is operator territory and MUST survive every rebuild verbatim.

  # Contract:
  # An index rendered where none existed ALWAYS carries a `## Context map` stub,
  # so the operator half of the file is never missing.

  # The headings and the hand-written stub the index renders
  _TITLE           = "# Domains"
  _CONTEXT_HEADING = "## Context map"
  _STUB            = "<!-- Hand-written cross-domain relationships; the list above is engine-rendered. -->"
  _SECTION_PREFIX  = "## "
  _DISCREPANCIES_HEADING = "## Discrepancies"
  _GROUPS_HEADING  = "## Groups"

  def __init__(self, *, cfg: DomainConfig) -> None:
    """
    Initialise the renderer for one configuration.

    Args:
      cfg: The repo's domain configuration.
    """
    # the config carries repo root, output dir, and dictionary location
    self._cfg = cfg
    self._layout = DomainLayout(output = cfg.output)

  def index_rel(self) -> str:
    """
    Return the repo-relative path of the index file.

    Returns:
      Repo-relative POSIX path of `domains.md`.
    """
    return f"{self._cfg.output}/{INDEX_NAME}"

  def render(self) -> str:
    """
    Render the full index content.

    Returns:
      The complete index file content, listing every dictionary group whose
      folder note exists and every doc marked as disagreeing with its code, with
      the preserved (or stub) tail sections appended.
    """
    dictionary = DomainDictionary(path = self._cfg.repo / self._cfg.dictionary).read_groups()

    # Domain(wiki.domains):
    # # Who owns which half of the domain index
    # The index of the domain tree is shared between the engine and the operator. The engine owns the
    # head: the title, the self-describing line in the language the documents are written in, one entry
    # per listed group whose folder note already exists, each carrying the gloss the dictionary gave it,
    # and the list of documents marked as disagreeing with the code they describe. Everything from the
    # first other section heading onward belongs to the operator: cross-domain relationships that no
    # block states on its own are written there by hand and survive every rebuild.

    # one line per dictionary group whose folder note exists on disk
    listing: list[str] = []
    for group in sorted(dictionary):
      rel = self._layout.folder_note_rel(group)

      # guard: folder note not generated yet — the group joins the index after its writer runs
      if not (self._cfg.repo / rel).is_file():
        continue
      link = rel[len(self._cfg.output) + 1:]
      gloss = dictionary[group]
      listing.append(f"- [{group}]({link}) — {gloss}" if gloss else f"- [{group}]({link})")

    # the head is engine territory; the tail is whatever prose already follows it.
    # The italic line under the title self-describes the file for the operator, in the same
    # language the listed group docs are authored in (`wiki.domains.language`, as a code).
    explainer = _explainers.explainer_line(_explainers.SURFACE_DOMAINS_INDEX, self._cfg.language_code)
    head = self._TITLE + "\n" + explainer + "\n\n" + "\n".join(listing) + "\n"

    # the engine's list of docs marked as disagreeing with their code, only when there is one
    marked = self._render_discrepancy_lines()
    if marked:
      head += "\n" + self._DISCREPANCIES_HEADING + "\n\n" + "\n".join(marked) + "\n"

    # the operator's tail survives as it is; a brand-new index gets the stub in its place
    tail = self._read_preserved_tail()
    if tail:
      return head + "\n" + tail
    return head + "\n" + self._CONTEXT_HEADING + "\n\n" + self._STUB + "\n"

  def _render_discrepancy_lines(self) -> list[str]:
    """
    List every generated doc tagged as disagreeing with its code.

    Returns:
      One `- [<title>](<path>)` line per doc carrying the discrepancy tag, sorted by path,
      the path relative to the output directory and the title taken from the doc's H1.
    """
    output_abs = self._cfg.repo / self._cfg.output

    # guard: no output tree yet — nothing can be marked
    if not output_abs.is_dir():
      return []

    # every tagged markdown doc of the tree, titled by its own H1
    lines: list[tuple[str, str]] = []
    for base, _dirs, files in os.walk(str(output_abs)):
      for fname in files:
        doc_abs = Path(base) / fname
        rel = doc_abs.relative_to(self._cfg.repo).as_posix()

        # not a generated doc, or not tagged as disagreeing with its code
        if self._layout.classify(rel) is None or DISCREPANCY_TAG not in DomainPlanner.read_stored_tags(doc_abs):
          continue

        # the doc's own H1 names it, its file stem when it has none
        heads = [
          line[2:].strip() for line in doc_abs.read_text(encoding = _ENCODING).splitlines() if line.startswith("# ")
        ]
        title = heads[0] if heads else fname[:-len(_MD_EXT)]
        link = rel[len(self._cfg.output) + 1:]
        lines.append((link, f"- [{title}]({link})"))
    return [ line for _link, line in sorted(lines) ]

  def render_sections(self) -> dict[str, str]:
    """
    Render the note of every section folder of the tree.

    Returns:
      Repo-relative note path to its full content, one per folder above the groups that
      is not a group itself; a section lists the groups and sections directly inside it.
    """
    dictionary = DomainDictionary(path = self._cfg.repo / self._cfg.dictionary).read_groups()
    scanned = DomainScanner(repo = self._cfg.repo, code_globs = self._cfg.code).scan()

    # the groups whose folder note is written — the same ones the index lists — and the sections above them
    groups = sorted(
      group for group in dictionary
      if scanned.get(group) and (self._cfg.repo / self._layout.folder_note_rel(group)).is_file()
    )
    sections = DomainLayout.compute_section_prefixes(groups)
    explainer = _explainers.explainer_line(_explainers.SURFACE_DOMAIN_SECTION, self._cfg.language_code)

    # each section lists its direct children: groups with their gloss, sub-sections bare
    notes: dict[str, str] = {}
    for section in sections:
      # the section key has `count(".") + 1` segments, so a direct child's key has one more
      depth = section.count(".") + 2
      # every group or section key below this one, cut to that depth, once each
      children = sorted({
        ".".join(key.split(".")[:depth])
        for key in ( *groups, *sections )
        if key.startswith(section + ".")
      })

      # one link line per child, pointing at the folder note named after its last segment
      lines = []
      for child in children:
        last = child.rsplit(".", 1)[-1]
        link = f"./{last}/{last}{_MD_EXT}"
        # a group carries its dictionary gloss, a sub-section stays bare
        gloss = dictionary.get(child) if child in groups else None
        lines.append(f"- [{child}]({link}) — {gloss}" if gloss else f"- [{child}]({link})")

      # the note itself: section frontmatter, title and explainer, then the child list
      notes[self._layout.folder_note_rel(section)] = (
        f"{_FENCE}\n{FM_DOMAIN_SECTION}: {section}\n{_FENCE}\n# {section}\n{explainer}\n\n"
        + self._GROUPS_HEADING + "\n\n" + "\n".join(lines) + "\n"
      )
    return notes

  def has_stale_sections(self) -> bool:
    """
    Report whether any section note on disk differs from its render, or is missing.

    Returns:
      True when a section note needs writing.
    """
    return any(
      not (self._cfg.repo / rel).is_file() or (self._cfg.repo / rel).read_text(encoding = _ENCODING) != text
      for rel, text in self.render_sections().items()
    )

  def apply_sections(self) -> list[str]:
    """
    Write every section note that differs from its render.

    Returns:
      Sorted repo-relative paths of the notes written; empty when all were current.
    """
    written: list[str] = []
    for rel, text in sorted(self.render_sections().items()):
      target = self._cfg.repo / rel

      # the note is current — nothing to write
      if target.is_file() and target.read_text(encoding = _ENCODING) == text:
        continue

      # the whole note replaces what was there
      target.parent.mkdir(parents = True, exist_ok = True)
      TextFile(path = target).write(text)
      written.append(rel)
    return written

  def apply(self) -> bool:
    """
    Write the rendered index when it differs from the file on disk.

    Returns:
      True when the file was (re)written, False when it was already current.
    """
    index_abs = self._cfg.repo / self.index_rel()
    rendered = self.render()
    existing = index_abs.read_text(encoding = _ENCODING) if index_abs.is_file() else None

    # index already current — nothing to write
    if existing == rendered:
      return False
    index_abs.parent.mkdir(parents = True, exist_ok = True)
    TextFile(path = index_abs).write(rendered)
    return True

  def _read_preserved_tail(self) -> str:
    """
    Return the existing index content from its first operator `##` heading onward.

    Returns:
      The preserved tail text, or an empty string when the index does not
      exist or carries no `##` section.
    """
    index_abs = self._cfg.repo / self.index_rel()

    # guard: no index yet — nothing to preserve
    if not index_abs.is_file():
      return ""
    lines = index_abs.read_text(encoding = _ENCODING).splitlines()
    for idx, line in enumerate(lines):
      # not a section heading, or the engine's own discrepancy list — keep looking
      if not line.startswith(self._SECTION_PREFIX) or line.strip() == self._DISCREPANCIES_HEADING:
        continue
      return "\n".join(lines[idx:]) + "\n"
    return ""


# ────────────────────────────────────────────────────────────────────────────
class DomainLandingError(Exception):
  """
  A returned domain document the landing refuses to write.
  """


# ────────────────────────────────────────────────────────────────────────────
class DomainLanding:
  """
  The one route a domain-spec writer's document takes into the repository.

  Places a returned document at the path its dispatch named — a block doc or a folder note —
  stamped with the digest the dispatch carries for that path and the configured explainer line
  under the title heading. The bullet of a contract citation the dispatch attributed nothing to
  is removed from the document before it lands. It never refreshes the index and never
  commits — the caller owns both.

  Guarantees:
    - Writes only a doc inside a group folder of the configured output tree, never the
      index, and never an empty document; a refused landing writes nothing.
    - The landed doc's `domain_hash` is always the payload's digest for that path, never the
      writer's value, and the explainer line under the title heading is always the configured
      one for the doc's kind.
    - A returned document that cannot be stamped (no `domain_hash` key in a leading frontmatter
      block, no title heading, or no digest in the payload for its path) is refused, and
      nothing is written.
  """

  # Decision: deterministic code lands and commits the writer's document, not the writer agent
  # itself — an agent that skips its final step leaves an uncommitted file, and the runtime's
  # dirty-tree check then halts every queued job until an operator steps in.

  # Contract:
  # A landing writes ONLY a doc inside a group folder of the configured output tree — never
  # the index, never a path a parent hop carries outside the tree, never an empty document. A
  # refused landing writes nothing at all.

  # Contract:
  # A landed doc always carries, as its `domain_hash`, the digest the writer payload names for
  # that path — never a value the writer put in the document — and always carries, directly
  # under its title heading, the configured explainer line for the doc's kind.

  # Contract:
  # A returned document that cannot be stamped is refused and nothing is written: one with no
  # `domain_hash` key in a leading frontmatter block, one with no title heading, or one at a
  # path the payload names no digest for.

  def __init__(self, *, cfg: DomainConfig) -> None:
    """
    Initialise the landing for one configuration.

    Args:
      cfg: The repo's domain configuration.
    """
    # the config carries the repo root and the output tree every landing is bounded by
    self._cfg = cfg
    self._layout = DomainLayout(output = cfg.output)

  def save_doc(self, doc_rel: str, body: str, *, payload: dict) -> str:
    """
    Write one returned document at its doc path, stamped with its digest and explainer line.

    Args:
      doc_rel: Repo-relative doc path the dispatch named.
      body: The document text the writer returned.
      payload: The writer payload the dispatch carried.

    Returns:
      The normalised repo-relative POSIX doc path written.

    Raises:
      DomainLandingError: When the path, once normalised, is not a group doc inside the output
        tree, the payload names no digest for it, or the document is empty, carries no
        `domain_hash` frontmatter key, or has no title heading.
    """

    # Domain(wiki.domains):
    # # A returned domain document is stamped, not trusted
    # A generated document is judged stale by comparing the content digest stored in its frontmatter
    # with the digest of the code knowledge it describes as it stands now. The digest is computed
    # by the engine when it plans the document and travels with the writer's assignment, so the
    # value that lands is always the engine's own, never one the writer wrote. The writer is a
    # language model: a digest it copies or recomputes wrongly would make the document look out of
    # date forever, and it would be regenerated on every pass. The short fixed line under the
    # title that tells a reader what kind of document this is (a block document or a group's folder
    # note) is likewise fixed wording in the configured language, so it is stamped rather than
    # authored, and whatever the writer put in its place is replaced. A return that cannot carry
    # the stamps is refused whole and nothing is written: one with no digest field in its leading
    # frontmatter, one with no title to put the line under, or one for a path whose assignment
    # named no digest. The group then stays stale until its next generation.

    # refuse a return that cannot land or be stamped before anything is written
    rel = self.validate_doc(doc_rel, body, payload = payload)

    # the stamps: the payload's digest and the configured explainer line replace the writer's own
    stamped = DomainPlanner.stamp_hash(body, self._read_digest(payload, doc_rel))
    stamped = self._stamp_explainer(stamped, rel)

    # the whole document replaces whatever the previous generation left
    target = self._cfg.repo / rel
    target.parent.mkdir(parents = True, exist_ok = True)
    TextFile(path = target).write(stamped)
    return rel

  def validate_doc(self, doc_rel: str, body: str, *, payload: dict) -> str:
    """
    Check that one returned document may land and be stamped, without writing it.

    Args:
      doc_rel: Repo-relative doc path the dispatch named.
      body: The document text the writer returned.
      payload: The writer payload the dispatch carried.

    Returns:
      The normalised repo-relative POSIX doc path the document would land at.

    Raises:
      DomainLandingError: When the path, once normalised, is not a group doc inside the output
        tree, the payload names no digest for it, or the document is empty, carries no
        `domain_hash` frontmatter key, or has no title heading.
    """

    # Domain(wiki.domains):
    # # Where a returned domain document may land
    # A generated document is returned by its writer, never placed by it, and the landing decides
    # whether it may be placed at all. It lands only inside a group's own folder in the generated tree:
    # the index is the engine's, and any path reaching outside the tree — directly or through a parent
    # hop — names something the generated tree does not own. An empty return is no document,
    # so nothing is landed and the group stays stale until its next generation.

    # the resolved target with every `.` segment, parent hop, or absolute form collapsed, and its
    # normalised repo-relative spelling — the one every check below judges
    target = (self._cfg.repo / doc_rel).resolve()
    rel = target.relative_to(self._cfg.repo).as_posix() if target.is_relative_to(self._cfg.repo) else None

    # what the normalised path is inside the tree, when it is inside the repo at all
    ref = self._layout.classify(rel) if rel is not None else None

    # guard: refuse a path resolving outside the repo or the generated tree, the index file under any
    # spelling, and any path that is not a markdown doc inside a group folder
    if (
      rel is None
      or not target.is_relative_to((self._cfg.repo / self._cfg.output).resolve())
      or ref is None
      or not ref.group
    ):
      raise DomainLandingError(f"doc_path {doc_rel!r} is not a group doc under {self._cfg.output}/")

    # guard: an empty return is no document
    if not body.strip():
      raise DomainLandingError(f"returned document for {doc_rel!r} is empty")

    # guard: a return without the key in a leading frontmatter block has no place for the digest
    lines = body.splitlines(keepends = True)
    if DomainPlanner.locate_hash_line(lines) is None:
      raise DomainLandingError(f"returned document for {doc_rel!r} carries no {FM_DOMAIN_HASH} frontmatter key")

    # guard: a return without a title heading has no place for the explainer line
    if self._locate_title(lines) is None:
      raise DomainLandingError(f"returned document for {doc_rel!r} has no title heading")

    # the digest must be one the payload names, so a return never lands unstamped
    self._read_digest(payload, doc_rel)
    return rel

  @staticmethod
  def _read_digest(payload: dict, doc_rel: str) -> str:
    """
    Read the digest a writer payload carries for one doc path.

    Args:
      payload: The writer payload the dispatch carried.
      doc_rel: Repo-relative doc path the dispatch named.

    Returns:
      The group digest for the folder note path, or the matching doc entry's digest.

    Raises:
      DomainLandingError: When the payload names no digest for the path.
    """
    docs = payload.get(GROUP_DOCS)

    # every path the payload names, mapped to its digest: the folder note's, then each doc's
    digests = { str(payload.get(GROUP_FOLDER_NOTE, "")): payload.get(GROUP_HASH) }
    if isinstance(docs, list):
      digests.update({
        str(doc.get(GROUP_DOC, "")): doc.get(GROUP_HASH)
        for doc in docs
        if isinstance(doc, dict)
      })
    digest = digests.get(doc_rel)

    # guard: a path the payload carries no digest for cannot be stamped
    if not isinstance(digest, str) or not digest:
      raise DomainLandingError(f"payload names no {GROUP_HASH} for {doc_rel!r}")
    return digest

  @staticmethod
  def _locate_title(lines: list[str]) -> int | None:
    """
    Find the title heading of a returned document, below its frontmatter.

    Args:
      lines: The document's lines, line endings kept.

    Returns:
      The index of the first `# ` line after the frontmatter block; `None` when there is none.
    """
    start = 0

    # a leading frontmatter block is skipped up to its closing fence
    if lines and lines[0].strip() == _FENCE:
      start = next((idx + 1 for idx in range(1, len(lines)) if lines[idx].strip() == _FENCE), len(lines))
    return next((idx for idx in range(start, len(lines)) if lines[idx].startswith(_TITLE_PREFIX)), None)

  def _stamp_explainer(self, body: str, rel: str) -> str:
    """
    Put the configured explainer line for a doc's kind directly under its title heading.

    Args:
      body: The document text, with a title heading.
      rel: The normalised repo-relative doc path.

    Returns:
      The text with the line under the title replaced when it is a whole-line italic, and
      the explainer inserted under the title otherwise.
    """
    ref = self._layout.classify(rel)
    surface = _explainers.SURFACE_DOMAIN_FOLDER if ref is not None and ref.kind == KIND_FOLDER_NOTE \
      else _explainers.SURFACE_DOMAIN_DOC
    explainer = _explainers.explainer_line(surface, self._cfg.language_code) + "\n"
    lines = body.splitlines(keepends = True)
    title = self._locate_title(lines)

    # guard: no title heading — validation refuses such a return before it gets here
    if title is None:
      return body

    # a writer's italic line under the title is replaced; anything else stays and the line goes above it
    under = title + 1
    if under < len(lines) and _ITALIC_LINE_RE.match(lines[under]):
      lines[under] = explainer
    else:
      lines.insert(under, explainer)
    return "".join(lines)

  @staticmethod
  def strip_contracts(body: str, contracts: list[dict]) -> str:
    """
    Remove from a returned document every contracts bullet that cites a file no attributed contract lives in.

    Guarantees:
      - Only the `## Contracts` bullets whose cited file carries none of the attributed contracts are
        removed, each with its indented continuation lines; a section left without a bullet loses its
        heading too, and every other byte of the document is returned unchanged.
      - The bullet citing a file the dispatch attributed nothing to is removed and the document still lands.

    Args:
      body: The document text the writer returned.
      contracts: The contract block dicts the dispatch attributed to the document.

    Returns:
      `body` without those bullets, each with its continuation lines; without the whole contracts
      section when no bullet is left in it.
    """

    # Contract:
    # Only the bullets of a document's `## Contracts` section whose cited file carries none of the
    # attributed contracts are removed, each together with its indented continuation lines; a section
    # left with no bullet is removed whole, heading included, and every other byte of the document is
    # returned unchanged.

    # Contract:
    # A citation of a file the dispatch attributed nothing to never raises; the bullet is removed
    # and the document still lands.

    # Domain(wiki.domains):
    # # A document cites guarantees only from files that carry attributed guarantees
    # The guarantees a domain document lists are meant to be the ones the engine attributed to its
    # block, but the landing checks this by file, not guarantee by guarantee: every file a cited
    # guarantee lives in must also hold at least one guarantee attributed to the document. A cited
    # guarantee from such a file stays even when that particular guarantee was not attributed. The
    # check stops at the file because staleness is judged the same way, matching cited guarantees back
    # to the code by file; a cited file with no attributed guarantee would leave the document looking
    # out of date on every pass and rewritten forever, so such a citation is deleted before the
    # document lands, together with the rest of its entry. A section left with no entry goes whole.
    # The rest of the writer's return lands as written.

    # the bullets citing a file none of the attributed contracts lives in
    allowed = { contract.get(BLOCK_PATH) for contract in contracts }
    dead = { bullet for bullet, path, _symbol in DomainPlanner.parse_contract_bullets(body) if path not in allowed }
    return DomainPlanner.drop_section_lines(body, _CONTRACTS_HEADING, dead)


# ────────────────────────────────────────────────────────────────────────────
class DomainPlanner:
  """
  Full-detect planner over the repo's `Domain(…)` blocks and generated docs.

  Represents the work a caller must act on: which groups changed, which generated
  docs the tree should no longer carry, and which groups are undocumented.

  Guarantees:
    - Plans identically for the same checkout, because the detect baseline is the
      `domain_hash` already stored in each generated doc, not external state.
  """

  # Contract:
  # The staleness baseline is the `domain_hash` stored in each generated doc, so
  # planning the same checkout twice MUST produce the same plan; no state outside
  # the checkout is ever consulted.

  def __init__(self, *, repo: Path) -> None:
    """
    Initialise the planner for one repository.

    Args:
      repo: Absolute repository root.
    """
    # config may be absent — `is_configured` reports it, `plan` requires it
    self._repo = Path(repo).resolve()
    self._cfg = DomainConfig.load(self._repo)

  @property
  def is_configured(self) -> bool:
    """
    Whether the settings carry a usable `wiki.domains` section.
    """
    return self._cfg is not None

  @property
  def cfg(self) -> DomainConfig:
    """
    The loaded `wiki.domains` configuration.

    Raises:
      RuntimeError: When `wiki.domains` is not configured.
    """
    # guard: callers must check `is_configured` first
    if self._cfg is None:
      raise RuntimeError(_MSG_UNCONFIGURED)
    return self._cfg

  @staticmethod
  def compute_group_hash(blocks: list[dict], contracts: list[dict] | None = None) -> str:
    """
    Compute the content hash of one group's blocks and attributed contracts.

    Guarantees:
      - The hash covers the text of the group's blocks, the symbol and text of each
        attributed contract, and the code that owns each of them. Edits to code outside
        those owners never change it. In a file that parses as Python, reformatting,
        comments outside the blocks, docstrings and line positions of the owning code
        never change it. A file that does not parse as Python is compared whole.
      - Moving a contract's file without touching its text or its enclosing symbol
        never changes the hash; moving it to another symbol does.

    Args:
      blocks: The group's `Domain(…)` block dicts, already sorted by `(path, line)`.
      contracts: The group's attributed `Contract:` block dicts, already sorted
        by `(path, line)`; omit, or pass an empty list, for a group with none.

    Returns:
      Hex sha256 digest of the canonical group text.
    """

    # Contract:
    # The digest covers the text of the group's blocks, the symbol and text of each
    # attributed contract, and the code that owns each of those blocks and contracts.
    # Edits to code outside those owners never change it. In a file that parses as
    # Python, reformatting, comments outside the blocks, docstrings and line positions
    # of the owning code never change it. A file that does not parse as Python is
    # compared whole.

    # Contract:
    # A contract's file path is NEVER part of the digest: moving the file that
    # carries a contract, with its text and enclosing symbol unchanged, MUST
    # reproduce the digest the group had before the move.

    # Domain(wiki.domains):
    # # What counts as a change to a group's knowledge
    # A group's published document is rebuilt only when the knowledge behind it actually moved. The
    # measure is a digest over two things: the group's own prose, and the code that prose is about.
    # The prose is every block of the group in file-and-line order, followed by each guarantee
    # attributed to the group together with the symbol it is anchored to. The code is the code owning
    # each block and each attributed guarantee, so a document goes stale when the described code is
    # edited, not only when its comment is.
    # The code is compared by its structure, never by its text. Formatting, comments, docstrings and
    # line positions never count as a change, and neither does moving a whole file to another place
    # in the tree: a file move is a filing change, not a knowledge change, and the anchor the
    # published document prints is repaired in place instead. A file that cannot be read as code is
    # compared whole. Moving a guarantee to another symbol does change the digest, because the
    # guarantee then governs a different piece of code. The digest of the last generation is kept
    # inside the document itself, so deciding what is stale needs no record outside the checkout.

    # each block's text followed by the digest of the code that owns it — the whole digest input when no
    # contract is attributed
    canonical = "\n\n".join(DomainPlanner._append_owner_digest(blk[BLOCK_TEXT], blk) for blk in blocks)

    # no contracts to fold in — `canonical` above is already the full digest input
    if not contracts:
      return hashlib.sha256(canonical.encode(_ENCODING)).hexdigest()

    # Decision: a contract's enclosing symbol is hashed alongside its guarantee text, but its
    # file path is not — a whole-tree move (`claude/` → `plugins/claude/`) once marked 55 of 57
    # docs stale and queued an LLM rewrite for each although no wording moved; the path-only
    # part of the anchor is repaired mechanically by `plan()` / `restamp()` instead.

    # each contract's symbol and text, canonicalised the same way as the blocks text above
    contract_text = "\n\n".join(
      DomainPlanner._append_owner_digest(f"{contract.get(BLOCK_SYMBOL) or ''}\n{contract[BLOCK_TEXT]}", contract)
      for contract in contracts
    )
    return hashlib.sha256(f"{canonical}\x00{contract_text}".encode(_ENCODING)).hexdigest()

  @staticmethod
  def _append_owner_digest(text: str, block: dict) -> str:
    """
    Join a block's canonical text with the digest of the code that owns it.

    Args:
      text: The block's canonical text.
      block: The block dict, carrying `owner_digest` when the scanner resolved one.

    Returns:
      `text` followed by the owner digest, or `text` alone for a block without one.
    """
    owner = block.get(BLOCK_OWNER)
    return f"{text}\x01{owner}" if owner else text

  def plan(self, group: str | None = None) -> dict:
    """
    Compute the full domain-spec plan for the repo, or for one group of it.

    Guarantees:
      - The returned plan is JSON-serialisable as it stands.
      - A group filter narrows only the work lists (changed groups, anchor and link fixes,
        contract drops, orphans); the catalog, the unknown and untitled reports, and the
        index state always cover the whole tree.

    Args:
      group: Group key to restrict the work lists to; `None` plans every group.

    Returns:
      Plan dict with `changed_groups` (each: group, hash, gloss, files,
      folder_note_path, existing_tags, docs, stale_docs, tag_axes,
      tag_dictionary — `docs` lists every document of the group with its
      heading, slug, doc_path, hash, blocks, contracts and existing_tags;
      `stale_docs` names the slugs whose document must be rewritten),
      `anchor_fixes` (`{doc, old, new}` per stale contract anchor a current doc
      prints), `link_fixes` (`{doc, line}` per `## Related` line whose target
      no longer exists), `contract_drops` (`{doc, line}` per `## Contracts` bullet of an existing
      doc citing a guarantee no attributed contract accounts for; such a citation never makes a doc
      stale), `orphaned_docs` with `orphan_reasons`, `unlisted_docs`
      (the orphans whose group left the dictionary), `unknown_groups`,
      `untitled_blocks`, `catalog` (`blocks` and `groups` of the whole tree),
      `index_path`, `index_needs_update`, `language`, `dictionary`, and `output`.
    """

    # Contract:
    # The returned plan is ALWAYS JSON-serialisable as it stands; command-line
    # consumers write it out unchanged.

    # Contract:
    # A group filter narrows ONLY the work lists — changed groups, anchor and link fixes,
    # contract drops, orphans; the catalog, the unknown and untitled reports and the index
    # state stay whole.

    survey = self._read_survey()

    # tag-canon inputs shared by every changed entry: the vault's axis vocabulary and the
    # advisory dictionary path, resolved once rather than per group
    tag_axes = _scope.ScopeResolver(repo = self.cfg.repo).load_wiki().get(_KEY_TAG_AXES)
    tag_axes = list(tag_axes) if isinstance(tag_axes, list) else []
    tag_dictionary = _scope.read_dictionary_rel(self.cfg.repo)

    # Domain(wiki.domains):
    # # When a stale anchor is repaired instead of rewritten
    # A published document names, beside each guarantee, the place in the code the guarantee governs.
    # When the file carrying that place moves, the knowledge is unchanged and the document stays current,
    # but the place it names no longer exists. When some attributed guarantee accounts for the anchor, it
    # is repaired mechanically: the anchor is matched by its symbol against the guarantees whose file the
    # document does not yet name, and when exactly one destination file fits, the anchor is rewritten to
    # it. When the destination is ambiguous — two candidate files carry the same symbol, or two
    # symbol-less guarantees moved apart — no guess is made; the document is rebuilt in full instead, as
    # if the knowledge had changed. A citation that no attributed guarantee accounts for is dropped
    # rather than repaired.

    # Domain(wiki.domains):
    # # What makes a document stale
    # Every block document carries the digest of the blocks it was written from and of the guarantees
    # attributed to them; a document whose stored digest differs from the code, or which does not exist,
    # is rewritten. A current document whose printed anchor moved somewhere no symbol match can follow is
    # rewritten too. The folder note carries the digest of the whole group, so any change to any block of
    # the group — a block added, edited or removed — rewrites the folder note, while the documents of the
    # blocks that did not change are left as they are.

    # per group: which docs are stale, which current docs only need an anchor repair, and which bullets
    # of any existing doc cite a guarantee nothing accounts for
    changed: list[dict] = []
    fixes: list[dict] = []
    drops: list[dict] = []
    for key, docs in survey.folded.items():
      # a group filter is set and names another group
      if group is not None and key != group:
        continue

      # the slugs of the docs whose stored digest no longer matches, or whose anchors cannot be repaired
      stale: list[str] = []
      for doc in docs:
        # a cited guarantee nothing accounts for is dropped from every existing doc, current or stale
        drops.extend(self._read_contract_drops(doc[GROUP_DOC], doc[GROUP_CONTRACTS]))

        # a current doc needs no rewrite unless one of its anchors moved somewhere unrecoverable
        if self.read_stored_hash(self.cfg.repo / doc[GROUP_DOC]) == doc[GROUP_HASH]:
          doc_fixes = self._read_anchor_fixes(doc[GROUP_DOC], doc[GROUP_CONTRACTS])

          # every anchor resolves: the doc is current and needs at most a mechanical repair
          if doc_fixes is not None:
            fixes.extend(doc_fixes)
            continue
        stale.append(doc[DOC_SLUG])

      # the folder note follows the whole group's digest
      digest = self.compute_group_hash(survey.scanned[key], survey.contracts.get(key) or [])
      note_rel = survey.layout.folder_note_rel(key)

      # every doc and the folder note are current — nothing to write for this group
      if not stale and self.read_stored_hash(self.cfg.repo / note_rel) == digest:
        continue

      # the group's work for one writer job
      changed.append({
        GROUP_KEY:              key,
        GROUP_HASH:             digest,
        GROUP_GLOSS:            survey.dictionary[key],
        GROUP_FILES:            sorted({ blk[BLOCK_PATH] for blk in survey.scanned[key] }),
        GROUP_FOLDER_NOTE:      note_rel,
        PAYLOAD_EXISTING_TAGS:  self.read_stored_tags(self.cfg.repo / note_rel),
        GROUP_DOCS:             docs,
        GROUP_STALE:            stale,
        PAYLOAD_TAG_AXES:       tag_axes,
        PAYLOAD_TAG_DICTIONARY: tag_dictionary,
      })

    # groups present in code but absent from the dictionary — the doctor's business
    unknown = sorted(grp for grp in survey.scanned if grp not in survey.dictionary and grp != RESERVED_GROUP)

    # index staleness: compare the fresh render against the file on disk
    index = DomainIndex(cfg = self.cfg)
    index_abs = self.cfg.repo / index.index_rel()
    current = index_abs.read_text(encoding = _ENCODING) if index_abs.is_file() else None

    # docs the tree should no longer carry, and Related lines pointing at docs that will be gone
    removals = self._removable_docs(survey.dictionary, survey.folded, survey.layout)
    rewritten = {
      path
      for entry in changed
      for path in ( entry[GROUP_FOLDER_NOTE], *(
        doc[GROUP_DOC] for doc in entry[GROUP_DOCS] if doc[DOC_SLUG] in entry[GROUP_STALE]
      ) )
    }
    link_fixes = self._find_all_link_fixes(survey.folded, rewritten, survey.layout)

    # the filter narrows the work lists to the group's own folder — never a nested group's — and its
    # retired flat doc
    if group is not None:
      removals = { rel: why for rel, why in removals.items() if self._is_owned_by(rel, group, survey.layout) }
      link_fixes = [ fix for fix in link_fixes if self._is_owned_by(fix[FIX_DOC], group, survey.layout) ]

    # the whole plan is JSON-serialisable for the CLI wrapper
    return {
      PLAN_CHANGED:       changed,
      PLAN_ANCHOR_FIXES:  fixes,
      PLAN_LINK_FIXES:    link_fixes,
      PLAN_CONTRACT_DROPS: drops,
      PLAN_ORPHANED:      sorted(removals),
      PLAN_ORPHAN_REASONS: dict(sorted(removals.items())),
      PLAN_UNLISTED:      sorted(rel for rel, why in removals.items() if why == DOC_REASON_UNLISTED),
      PLAN_UNKNOWN:       unknown,
      PLAN_UNTITLED:      survey.untitled,
      PLAN_CATALOG:       self._build_catalog(survey.dictionary, survey.folded, survey.layout),
      PLAN_INDEX_PATH:    index.index_rel(),
      PLAN_INDEX_STALE:   index.render() != current or index.has_stale_sections(),
      PLAN_LANGUAGE:      self.cfg.language,
      PLAN_DICTIONARY:    self.cfg.dictionary,
      PLAN_OUTPUT:        self.cfg.output,
    }

  @staticmethod
  def _is_owned_by(rel: str, group: str, layout: DomainLayout) -> bool:
    """
    Report whether a path belongs to one group: a file in its own folder, or its retired flat doc.

    Args:
      rel: Repo-relative POSIX path under the output tree.
      group: The group key.
      layout: Path mapper for the output directory.

    Returns:
      True when the path is the group's own, never for a nested group's folder.
    """
    ref = layout.classify(rel)
    return rel == layout.legacy_doc_rel(group) or (ref is not None and ref.group == group)

  def build_payload(self, entry: dict, catalog: dict) -> dict:
    """
    Build the domain-spec writer payload for one changed-group plan entry.

    Guarantees:
      - The returned dict is JSON-serialisable as it stands; the CLI caller
        merges in only the dispatch-mechanism `kind` field before dispatch.

    Args:
      entry: One `changed_groups` entry from `plan()`.
      catalog: The `catalog` of the same plan.

    Returns:
      Payload dict carrying every field of `entry`, the configured `language`
      as a code and its `language_name`, and the tree-wide `catalog_blocks`
      and `catalog_groups` the writer chooses its links from.
    """

    # Contract:
    # The returned dict is JSON-serialisable as it stands; the CLI caller
    # merges in only the dispatch-mechanism `kind` field before dispatch.

    return {
      **entry,
      PLAN_LANGUAGE:          self.cfg.language_code,
      PAYLOAD_LANGUAGE_NAME:  _explainers.LANGUAGE_NAMES.get(self.cfg.language_code, self.cfg.language_code),
      PAYLOAD_CATALOG_BLOCKS: catalog[CATALOG_BLOCKS],
      PAYLOAD_CATALOG_GROUPS: catalog[CATALOG_GROUPS],
    }

  def apply_anchor_fixes(self, fixes: list[dict]) -> list[str]:
    """
    Rewrite stale contract anchors in place in the generated docs.

    Guarantees:
      - Only the anchor text named by each fix is replaced; the rest of the doc
        is left byte-identical.

    Notes:
      - Reads each named doc and writes the changed ones back to disk in place.

    Args:
      fixes: `anchor_fixes` entries from `plan()` — `{doc, old, new}` dicts.

    Returns:
      Sorted repo-relative paths of the docs whose content changed.
    """

    # Contract:
    # Only the anchor text a fix names is replaced, wherever it occurs in that doc;
    # every other byte of the doc is left as it was.

    # every fix of one doc is applied in a single read-modify-write pass
    touched: list[str] = []
    for doc_rel in sorted({ fix[FIX_DOC] for fix in fixes }):
      doc_file = TextFile(path = self.cfg.repo / doc_rel)
      text = doc_file.read()
      rewritten = text
      for fix in fixes:
        if fix[FIX_DOC] == doc_rel:
          rewritten = rewritten.replace(fix[FIX_OLD], fix[FIX_NEW])

      # nothing changed (already repaired) — do not touch the file
      if rewritten == text:
        continue
      doc_file.write(rewritten)
      touched.append(doc_rel)
    return touched

  def apply_link_fixes(self, fixes: list[dict]) -> list[str]:
    """
    Remove `## Related` lines whose target no longer exists from the generated docs.

    Guarantees:
      - Only the named lines inside the `## Related` section are removed; a section
        left without a link line loses its heading too, and every other byte stays.

    Notes:
      - Reads each named doc and writes the changed ones back to disk in place.

    Args:
      fixes: `link_fixes` entries from `plan()` — `{doc, line}` dicts.

    Returns:
      Sorted repo-relative paths of the docs whose content changed.
    """

    # Contract:
    # Only the named lines inside a doc's `## Related` section are removed; a section left
    # with no link line is removed whole, and nothing outside the section ever changes.

    # every fix of one doc is applied in a single read-modify-write pass
    touched: list[str] = []
    for doc_rel in sorted({ fix[FIX_DOC] for fix in fixes }):
      doc_file = TextFile(path = self.cfg.repo / doc_rel)
      text = doc_file.read()
      dead = { fix[FIX_LINE] for fix in fixes if fix[FIX_DOC] == doc_rel }
      rewritten = self.drop_section_lines(text, _RELATED_HEADING, dead)

      # nothing changed (already repaired) — do not touch the file
      if rewritten == text:
        continue
      doc_file.write(rewritten)
      touched.append(doc_rel)
    return touched

  def apply_contract_drops(self, drops: list[dict]) -> list[str]:
    """
    Remove the named `## Contracts` bullets from the generated docs.

    Guarantees:
      - Only the named bullets inside the `## Contracts` section are removed, each with its
        continuation lines; a section left without a bullet loses its heading too, and every
        other byte stays.

    Notes:
      - Reads each named doc and writes the changed ones back to disk in place.

    Args:
      drops: `contract_drops` entries from `plan()` — `{doc, line}` dicts.

    Returns:
      Sorted repo-relative paths of the docs whose content changed.
    """

    # Contract:
    # Only the named bullets inside a doc's `## Contracts` section are removed, each together with
    # its indented continuation lines; a section left with no bullet is removed whole, heading
    # included, and nothing outside the section ever changes.

    # every drop of one doc is applied in a single read-modify-write pass
    touched: list[str] = []
    for doc_rel in sorted({ drop[FIX_DOC] for drop in drops }):
      doc_file = TextFile(path = self.cfg.repo / doc_rel)
      text = doc_file.read()
      dead = { drop[FIX_LINE] for drop in drops if drop[FIX_DOC] == doc_rel }
      rewritten = self.drop_section_lines(text, _CONTRACTS_HEADING, dead)

      # nothing changed (already dropped) — do not touch the file
      if rewritten == text:
        continue
      doc_file.write(rewritten)
      touched.append(doc_rel)
    return touched

  def restamp(self) -> dict:
    """
    Repair every current doc's stale anchors and stamp it with the current digest, without
    regenerating any doc.

    Meant for a one-off run after the digest rule changes: every block doc and folder note
    whose group still has blocks in code is taken as current as written and re-anchored to
    the new digest.

    Guarantees:
      - No doc is created or regenerated; only the `domain_hash` frontmatter line and the
        stale contract anchors of existing docs are rewritten.

    Notes:
      - Scans the configured code tree, reads every existing generated doc, and writes the
        changed ones back to disk in place.

    Returns:
      Dict with `docs` (sorted repo-relative paths of the docs that changed) and
      `anchors_repaired` (count of anchors rewritten); JSON-serialisable as it stands.
    """

    # Contract:
    # No doc is ever created or regenerated by a restamp; only the `domain_hash`
    # frontmatter line and the stale contract anchors of docs that already exist change.

    survey = self._read_survey()

    # per existing file: repair what resolves, then overwrite the stored digest with the current one
    touched: set[str] = set()
    anchors = 0
    for key, docs in survey.folded.items():
      stamps = [ (doc[GROUP_DOC], doc[GROUP_HASH], doc[GROUP_CONTRACTS]) for doc in docs ]
      stamps.append((
        survey.layout.folder_note_rel(key),
        self.compute_group_hash(survey.scanned[key], survey.contracts.get(key) or []),
        [],
      ))
      for doc_rel, digest, contracts in stamps:
        doc_abs = self.cfg.repo / doc_rel

        # guard: no file to stamp
        if not doc_abs.is_file():
          continue

        # the anchor repair runs first, so the stamped text below already carries the new anchors
        fixes = (self._read_anchor_fixes(doc_rel, contracts) or []) if contracts else []
        anchors += len(fixes)
        touched.update(self.apply_anchor_fixes(fixes))

        # the stamp: the doc as it stands, re-anchored to the current digest
        doc_file = TextFile(path = doc_abs)
        text = doc_file.read()
        stamped = self.stamp_hash(text, digest)

        # the digest is already the current one — the anchors above were the whole change
        if stamped == text:
          continue
        doc_file.write(stamped)
        touched.add(doc_rel)
    return { RESTAMP_DOCS: sorted(touched), RESTAMP_ANCHORS: anchors }

  def _read_survey(self) -> _Survey:
    """
    Scan the code and the dictionary and fold every listed group's blocks into documents.

    Returns:
      The dictionary, the scanned blocks and contracts, the layout, the folded documents
      of every listed group that has blocks, and the blocks that carry no title.
    """
    dictionary = DomainDictionary(path = self.cfg.repo / self.cfg.dictionary).read_groups()
    scanner = DomainScanner(repo = self.cfg.repo, code_globs = self.cfg.code)
    scanned = scanner.scan()
    contracts = scanner.scan_contracts()
    layout = DomainLayout(output = self.cfg.output)

    # every listed group with blocks, folded into one document per distinct title
    folded: dict[str, list[dict]] = {}
    untitled: list[dict] = []
    for key in sorted(dictionary):
      blocks = scanned.get(key) or []

      # guard: no blocks left in code — the group's folder (if any) is an orphan
      if not blocks:
        continue

      # the group's documents, and the blocks no document can be named for
      docs, loose = self._fold_docs(key, blocks, contracts.get(key) or [], layout)
      folded[key] = docs
      untitled.extend(loose)
    return _Survey(
      dictionary = dictionary,
      scanned    = scanned,
      contracts  = contracts,
      layout     = layout,
      folded     = folded,
      untitled   = untitled,
    )

  def _fold_docs(self,
                 group: str,
                 blocks: list[dict],
                 contracts: list[dict],
                 layout: DomainLayout) -> tuple[list[dict], list[dict]]:
    """
    Fold one group's blocks into its documents, one per distinct title.

    Args:
      group: The group key.
      blocks: The group's block dicts, sorted by `(path, line)`.
      contracts: The group's contract dicts, sorted by `(path, line)`.
      layout: Path mapper for the output directory.

    Returns:
      The documents in slug order (heading, slug, doc_path, hash, blocks, contracts,
      existing_tags) and the `{group, path, line}` of every block without a title.
    """

    # Domain(wiki.domains):
    # # Blocks with one title make one document
    # Two blocks of one group whose titles name the same document describe one subject from two places in
    # the code, so they become one document holding both, and its digest covers both. Titles name the same
    # document when they fold to the same file name, which is also the case for two titles that differ only
    # in case or punctuation. A block with no title becomes no document at all: it is reported, because a
    # document cannot be named from nothing.

    # a block with no title, or a title with nothing to name a file by, is reported and never published
    titled: list[tuple[dict, str]] = []
    untitled: list[dict] = []
    for blk in blocks:
      heading = blk.get(BLOCK_HEADING)
      slug = layout.slug_for(heading) if heading else ""
      if slug:
        titled.append((blk, slug))
      else:
        untitled.append({ BLOCK_GROUP: group, BLOCK_PATH: blk[BLOCK_PATH], BLOCK_LINE: blk[BLOCK_LINE] })

    # every titled block joins the document its title names; each guarantee follows its nearest titled
    # block, so a guarantee written beside an untitled block is not lost with it
    by_path: dict[str, dict] = {}
    attributions = DomainScanner.attribute_contracts([ blk for blk, _slug in titled ], contracts)
    for (blk, slug), attributed in zip(titled, attributions, strict = True):
      heading = str(blk[BLOCK_HEADING])
      doc = by_path.setdefault(layout.doc_rel(group, slug), {
        DOC_HEADING:     heading,
        DOC_SLUG:        slug,
        GROUP_DOC:       layout.doc_rel(group, slug),
        GROUP_BLOCKS:    [],
        GROUP_CONTRACTS: [],
      })
      doc[GROUP_BLOCKS].append(blk)
      doc[GROUP_CONTRACTS].extend(attributed)

    # each document's own digest and the tags its current file carries
    docs: list[dict] = []
    for rel in sorted(by_path):
      doc = by_path[rel]
      doc[GROUP_HASH] = self.compute_group_hash(doc[GROUP_BLOCKS], doc[GROUP_CONTRACTS])
      doc[PAYLOAD_EXISTING_TAGS] = self._read_own_tags(self.cfg.repo / doc[GROUP_DOC])
      docs.append(doc)
    return docs, untitled

  @classmethod
  def _read_own_tags(cls, doc_abs: Path) -> list[str]:
    """
    Read the tags of a block doc, but only when the file at that path is a block doc.

    Args:
      doc_abs: Absolute path a block's document lands at.

    Returns:
      The file's stored tags when its frontmatter names a block; `[]` for a missing file
      or for another kind of file sitting at that path, such as a retired flat group doc.
    """

    # Domain(wiki.domains):
    # # A document inherits tags only from itself
    # A regenerated document keeps the tags its previous version carried. When the file at its path is
    # not a previous version of it — the single document per group the earlier layout wrote can sit
    # exactly where a block document of a parent group now lands — that file's tags describe another
    # subject and are not carried over.

    # guard: the file at this path names no block — not a previous version of this doc
    if cls.read_frontmatter(doc_abs).get(FM_DOMAIN_BLOCK) is None:
      return []
    return cls.read_stored_tags(doc_abs)

  @classmethod
  def _build_catalog(cls, dictionary: dict[str, str], folded: dict[str, list[dict]], layout: DomainLayout) -> dict:
    """
    List every document and every group of the tree for the writer to link from.

    Args:
      dictionary: Group→gloss mapping from the dictionary file.
      folded: The folded documents of every listed group with blocks.
      layout: Path mapper for the output directory.

    Returns:
      `{blocks: [{group, heading, doc_path, gloss}], groups: [{group, folder_note_path, gloss}]}`;
      a document's gloss is the first sentence of its first block.
    """
    return {
      CATALOG_BLOCKS: [
        {
          GROUP_KEY:   key,
          DOC_HEADING: doc[DOC_HEADING],
          GROUP_DOC:   doc[GROUP_DOC],
          GROUP_GLOSS: cls._extract_gloss(doc[GROUP_BLOCKS][0][BLOCK_TEXT]),
        }
        for key, docs in folded.items()
        for doc in docs
      ],
      CATALOG_GROUPS: [
        { GROUP_KEY: key, GROUP_FOLDER_NOTE: layout.folder_note_rel(key), GROUP_GLOSS: dictionary[key] }
        for key in folded
      ],
    }

  @classmethod
  def _extract_gloss(cls, text: str) -> str:
    """
    Return the first sentence of a block's prose.

    Args:
      text: The block's raw comment text, header and title included.

    Returns:
      The first sentence of the body, at most `_GLOSS_LIMIT` characters; empty when
      the block has no body.
    """
    # the body after the header, with the comment markers and the title line stripped
    body = [ _COMMENT_PREFIX_RE.sub("", line).strip() for line in text.splitlines()[1:] ]
    prose = " ".join(line for line in body if line and not line.startswith("#"))
    match = _SENTENCE_RE.match(prose)
    return (match.group(1) if match else prose)[:_GLOSS_LIMIT]

  def _find_all_link_fixes(self,
                           folded: dict[str, list[dict]],
                           rewritten: set[str],
                           layout: DomainLayout) -> list[dict]:
    """
    Find the `## Related` lines of kept docs whose link target will not exist.

    Args:
      folded: The folded documents of every listed group with blocks.
      rewritten: Paths the writers will regenerate this round; their lines are not fixed.
      layout: Path mapper for the output directory.

    Returns:
      One `{doc, line}` per dead line, in doc order.
    """

    # Domain(wiki.domains):
    # # A link to a document that is gone is removed, not guessed
    # A document links its neighbours by path. When a neighbour disappears — its block was removed or
    # renamed — the link is dropped from the related list mechanically, without waking a writer; a link is
    # dead when its target is neither a document the tree will hold nor a file outside the tree. Pointing
    # it at the renamed document is left to the next regeneration of the linking group.

    # what the tree will hold once this round is applied, the engine's index included
    live = { doc[GROUP_DOC] for docs in folded.values() for doc in docs }
    live.update(layout.folder_note_rel(key) for key in folded)
    live.add(f"{self.cfg.output}/{INDEX_NAME}")
    output_prefix = self.cfg.output + "/"

    # the section notes the engine writes are live targets too, though no Related list of theirs is judged here
    targets = live | { layout.folder_note_rel(key) for key in layout.compute_section_prefixes(list(folded)) }

    # every kept, current doc's Related lines, judged target by target
    fixes: list[dict] = []
    for rel in sorted(path for path in live if path not in rewritten):
      doc_abs = self.cfg.repo / rel

      # guard: the doc is not on disk yet — nothing printed
      if not doc_abs.is_file():
        continue

      # each Related line is dead as soon as one of its local targets is
      base = posixpath.dirname(rel)
      for line in self._read_related_lines(doc_abs.read_text(encoding = _ENCODING)):
        for target in _LINK_TARGET_RE.findall(line):
          # an external link is never judged
          if "://" in target:
            continue

          # the target as a repo-relative path, without its in-page anchor
          resolved = posixpath.normpath(posixpath.join(base, target.split("#", 1)[0]))

          # a live target — a doc the tree will hold, or a file outside the tree that exists
          if resolved in targets or (not resolved.startswith(output_prefix) and (self.cfg.repo / resolved).exists()):
            continue

          # one dead target condemns the whole line
          fixes.append({ FIX_DOC: rel, FIX_LINE: line })
          break
    return fixes

  @staticmethod
  def _read_related_lines(text: str) -> list[str]:
    """
    Collect the link lines of a doc's `## Related` section.

    Args:
      text: Full text of the generated doc.

    Returns:
      The section's lines that open with `- `, in order; empty when the doc has no section.
    """
    # the first section runs from its heading to the next H1/H2 heading — a second `## Related`
    # included — or the end of the doc
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
      # another heading closes the section
      if inside and _HEADING_RE.match(line):
        break

      # the heading opens the section; inside it, every item line is collected
      if line.strip() == _RELATED_HEADING:
        inside = True
      elif inside and line.startswith("- "):
        lines.append(line)
    return lines

  @staticmethod
  def drop_section_lines(text: str, heading: str, dead: set[str]) -> str:
    """
    Remove the named item lines from one section of a doc.

    Each removed item takes its indented continuation lines with it.

    Args:
      text: Full text of the generated doc.
      heading: The section's heading line, e.g. `## Related`.
      dead: The exact item lines to remove.

    Returns:
      The doc text without those lines; without the whole section when no item line
      is left in it.
    """
    lines = text.splitlines(keepends = True)
    start = next((idx for idx, line in enumerate(lines) if line.strip() == heading), None)

    # guard: no such section — nothing to remove
    if start is None:
      return text

    # the section ends at the next H1/H2 heading or the end of the doc
    end = next((idx for idx in range(start + 1, len(lines)) if _HEADING_RE.match(lines[idx])), len(lines))

    # a dead item goes with the indented continuation lines it wraps onto
    section: list[str] = []
    dropping = False
    for line in lines[start:end]:
      if line.startswith("- "):
        dropping = line.rstrip("\r\n") in dead
      elif not (line[:1].isspace() and line.strip()):
        dropping = False
      if not dropping:
        section.append(line)

    # a section with an item line left keeps its place; an empty one goes whole, and the text before it
    # stays byte for byte unless the section ended the doc
    if any(line.startswith("- ") for line in section):
      return "".join([ *lines[:start], *section, *lines[end:] ])
    head = "".join(lines[:start])
    rest = "".join(lines[end:])
    return head + rest if rest else head.rstrip("\r\n") + "\n"

  def _read_anchor_fixes(self, doc_rel: str, contracts: list[dict]) -> list[dict] | None:
    """
    Map every stale contract anchor a doc prints to the current path of its contract.

    An anchor is stale when its path is no longer the path of any current contract. A stale
    anchor that no attributed contract accounts for, neither by file nor by symbol, is skipped
    and left to the contract drops; any other stale anchor with anything but exactly one
    possible new home leaves the doc unrecoverable.

    Args:
      doc_rel: Repo-relative path of the group doc.
      contracts: The group's current contract block dicts.

    Returns:
      The `{doc, old, new}` fixes (empty when no anchor is stale), or `None` when at
      least one stale anchor that some attributed contract accounts for cannot be mapped to a
      single current path.
    """
    doc_abs = self.cfg.repo / doc_rel

    # guard: no doc yet — nothing printed, nothing stale
    if not doc_abs.is_file():
      return []

    # what the doc prints against what the code carries
    anchors = self.parse_doc_anchors(doc_abs.read_text(encoding = _ENCODING))
    current_paths = { contract[BLOCK_PATH] for contract in contracts }
    doc_paths = { path for _old, path, _symbol in anchors }

    # a stale anchor is mapped by symbol to the contracts whose path the doc does not print yet;
    # anything but exactly one candidate path makes the doc unrecoverable
    candidates = [ contract for contract in contracts if contract[BLOCK_PATH] not in doc_paths ]
    fixes: list[dict] = []
    for old, path, symbol in anchors:
      # the anchor's file still carries contracts — not stale
      if path in current_paths:
        continue

      # an anchor no attributed contract accounts for is dropped, not repaired
      if self._is_unattributed(path, symbol, contracts):
        continue

      # the files this symbol could have moved to
      targets = sorted({
        contract[BLOCK_PATH] for contract in candidates if contract.get(BLOCK_SYMBOL) == symbol
      })

      # no single destination carries this symbol — the doc must be rewritten instead
      if len(targets) != 1:
        return None

      # the repaired anchor keeps the doc's own rendering, bare path or path:symbol
      new = f"(`{targets[0]}:{symbol}`)" if symbol else f"(`{targets[0]}`)"
      fixes.append({ FIX_DOC: doc_rel, FIX_OLD: old, FIX_NEW: new })
    return fixes

  def _read_contract_drops(self, doc_rel: str, contracts: list[dict]) -> list[dict]:
    """
    Name every `## Contracts` bullet of a doc that cites a guarantee no attributed contract accounts for.

    Args:
      doc_rel: Repo-relative path of the group doc.
      contracts: The doc's attributed contract block dicts.

    Returns:
      The `{doc, line}` drops in doc order, each naming the bullet that holds an unaccounted anchor
      on its first line or on a continuation line; empty when the doc does not exist.
    """
    doc_abs = self.cfg.repo / doc_rel

    # guard: no doc yet — nothing printed, nothing to drop
    if not doc_abs.is_file():
      return []

    # Domain(wiki.domains):
    # # A guarantee nothing accounts for leaves the document
    # A guarantee a domain document cites must come from the code its block describes. When the file a
    # cited guarantee names carries none of the guarantees attributed to the document, and no attributed
    # guarantee has its name either, nothing in the code backs it: it was invented, or it has since been
    # removed. Such a citation is not a moved guarantee to repair but a line to delete. The line is deleted
    # from every existing document, current or stale, before any writer sees it, and the deletion leaves
    # the document's generation mark alone, so a document that was current stays current. A citation that
    # an attributed guarantee in another file does account for is not dropped; whether it is repaired or
    # the document rewritten is settled by the stale-anchor rule.

    # the bullet goes when nothing attributed to the doc accounts for its anchor
    return [
      { FIX_DOC: doc_rel, FIX_LINE: bullet }
      for bullet, path, symbol in self.parse_contract_bullets(doc_abs.read_text(encoding = _ENCODING))
      if self._is_unattributed(path, symbol, contracts)
    ]

  @staticmethod
  def parse_contract_bullets(text: str) -> list[tuple[str, str, str | None]]:
    """
    List every anchor a doc's `## Contracts` section prints, with the bullet that holds it.

    Args:
      text: Full text of the generated doc.

    Returns:
      `(bullet_line, path, symbol)` triples in doc order, `bullet_line` being the bullet's first
      line without its newline and `symbol` `None` for a bare-path anchor; empty when the doc has
      no such section.
    """
    # every bullet of the Contracts section, with the line each anchor sits on mapped to its bullet
    found: list[tuple[str, str, str | None]] = []
    inside = False
    bullet: str | None = None
    for line in text.splitlines():
      if line.strip() == _CONTRACTS_HEADING:
        inside = True
        continue

      # another heading closes the section
      if inside and _HEADING_RE.match(line):
        break

      # prose outside the section
      if not inside:
        continue

      # a bullet opens on its own line; an indented line continues the open bullet
      if line.startswith("- "):
        bullet = line
      elif not (line[:1].isspace() and line.strip()):
        bullet = None

      # a line carrying no anchor, or an anchor no bullet holds
      if bullet is None or not (match := _ANCHOR_RE.search(line)):
        continue

      # the anchor is recorded under the bullet that holds it
      found.append((bullet, match.group(1), match.group(2)))
    return found

  @staticmethod
  def _is_unattributed(path: str, symbol: str | None, contracts: list[dict]) -> bool:
    """
    Tell whether a cited anchor names neither the file nor the symbol of any attributed contract.

    Args:
      path: The anchor's file path.
      symbol: The anchor's symbol, `None` for a bare-path anchor.
      contracts: The doc's attributed contract block dicts.

    Returns:
      True when no attributed contract lives in `path` and none carries `symbol`; a bare-path anchor is
      accounted for whenever some attributed contract has no symbol.
    """
    # the anchor stands for nothing when both its file and its name are foreign to the attributed list
    return (
      path not in { contract.get(BLOCK_PATH) for contract in contracts }
      and symbol not in { contract.get(BLOCK_SYMBOL) for contract in contracts }
    )

  @staticmethod
  def parse_doc_anchors(text: str) -> list[tuple[str, str, str | None]]:
    """
    Collect the contract anchors printed in a doc's `## Contracts` section.

    Args:
      text: Full text of the generated doc.

    Returns:
      Distinct `(anchor_text, path, symbol)` triples in order of first appearance;
      `symbol` is `None` for a bare-path anchor. Empty when the doc has no section.
    """
    # the section runs from its heading to the next H1/H2 heading or the end of the doc
    anchors: list[tuple[str, str, str | None]] = []
    inside = False
    for line in text.splitlines():
      if line.strip() == _CONTRACTS_HEADING:
        inside = True
        continue

      # another heading closes the section
      if inside and _HEADING_RE.match(line):
        break

      # prose outside the section, or a line carrying no anchor
      if not inside or not (match := _ANCHOR_RE.search(line)):
        continue
      triple = (match.group(0).strip(), match.group(1), match.group(2))
      if triple not in anchors:
        anchors.append(triple)
    return anchors

  @staticmethod
  def stamp_hash(text: str, digest: str) -> str:
    """
    Replace the `domain_hash` value inside a doc's leading frontmatter block.

    Args:
      text: Full text of the generated doc.
      digest: The digest to write.

    Returns:
      The doc text with its `domain_hash:` line rewritten; unchanged when the doc has
      no frontmatter block or the block carries no such line.
    """
    lines = text.splitlines(keepends = True)
    idx = DomainPlanner.locate_hash_line(lines)

    # guard: no `domain_hash` line inside a leading frontmatter block — nothing to stamp
    if idx is None:
      return text

    # the key's line is replaced in place; every other line keeps its bytes
    lines[idx] = f"{FM_DOMAIN_HASH}: {digest}\n"
    return "".join(lines)

  @staticmethod
  def locate_hash_line(lines: list[str]) -> int | None:
    """
    Find the `domain_hash` line inside a doc's leading frontmatter block.

    Args:
      lines: The doc's lines, line endings kept.

    Returns:
      The index of the `domain_hash:` line; `None` when the doc has no leading frontmatter
      block or the block carries no such line.
    """

    # guard: no leading frontmatter — no key to find
    if not lines or lines[0].strip() != _FENCE:
      return None

    # the search runs inside the block; the closing fence ends it
    for idx in range(1, len(lines)):
      # closing fence reached without the key
      if lines[idx].strip() == _FENCE:
        return None
      if _DOMAIN_HASH_LINE_RE.match(lines[idx]):
        return idx
    return None

  def _removable_docs(self,
                      dictionary: dict[str, str],
                      folded: dict[str, list[dict]],
                      layout: DomainLayout) -> dict[str, str]:
    """
    Map every generated doc the tree should no longer carry to its removal reason.

    Args:
      dictionary: Group→gloss mapping from the dictionary file.
      folded: The documents of every listed group with blocks.
      layout: Path mapper for the output directory.

    Returns:
      Mapping of repo-relative POSIX doc path to its removal reason (`legacy-layout`,
      `group-unlisted`, `no-blocks`, or `block-gone`); empty when no output tree exists.
    """
    output_abs = self._repo / self.cfg.output

    # guard: no output tree yet — nothing can be removed
    if not output_abs.is_dir():
      return {}

    # Domain(wiki.domains):
    # # When a generated document is retired
    # A document survives only while everything it stands on still holds: its group is listed in the
    # dictionary, the group still has blocks in the code, and — for a block document — a block of the group
    # still carries the title it was named by. A group the dictionary no longer lists is retired as
    # unlisted, a group whose last block left the code as empty, and a document whose block was removed or
    # retitled as gone. The single document per group that the earlier layout wrote beside the group folder
    # is retired as legacy, so moving to the folder layout is an ordinary regeneration. Retirement always
    # carries its reason; a document is never dropped silently.

    # what the tree is meant to hold, and where the retired layout put each listed group's doc
    expected = { doc[GROUP_DOC] for docs in folded.values() for doc in docs }
    expected.update(layout.folder_note_rel(key) for key in folded)
    expected.update(layout.folder_note_rel(key) for key in layout.compute_section_prefixes(list(folded)))
    legacy = { layout.legacy_doc_rel(key) for key in dictionary }

    # walk the output tree and judge every doc against the dictionary and the code
    removals: dict[str, str] = {}
    for base, _dirs, files in os.walk(str(output_abs)):
      for fname in files:
        rel = (Path(base) / fname).relative_to(self._repo).as_posix()
        ref = layout.classify(rel)

        # not a generated doc (index, non-markdown), or one the tree is meant to hold
        if ref is None or rel in expected:
          continue

        # the first reason that holds is the one recorded
        if rel in legacy or self._is_flat_group_doc(self._repo / rel, ref):
          removals[rel] = DOC_REASON_LEGACY
        elif ref.group not in dictionary:
          removals[rel] = DOC_REASON_UNLISTED
        elif ref.group not in folded:
          removals[rel] = DOC_REASON_NO_BLOCKS
        else:
          removals[rel] = DOC_REASON_BLOCK_GONE
    return removals

  @classmethod
  def _is_flat_group_doc(cls, doc_abs: Path, ref: DocRef) -> bool:
    """
    Report whether a file in a block doc's place is a doc the retired one-per-group layout wrote.

    Args:
      doc_abs: Absolute path of the file.
      ref: The file's classification by place.

    Returns:
      True when the file sits where a block doc would and its frontmatter names a group but no
      block — the shape of a retired flat group doc, whatever its group's dictionary state.
    """
    frontmatter = cls.read_frontmatter(doc_abs)
    return ref.kind == KIND_BLOCK_DOC and FM_DOMAIN_GROUP in frontmatter and FM_DOMAIN_BLOCK not in frontmatter

  @staticmethod
  def read_frontmatter(doc_abs: Path) -> dict:
    """
    Read the frontmatter of a generated doc.

    Args:
      doc_abs: Absolute path of the doc.

    Returns:
      The parsed frontmatter mapping; empty when the doc is absent or carries none.
    """
    # guard: doc not generated yet
    if not doc_abs.is_file():
      return {}
    # waiver: `scope` owns this plugin's only frontmatter parser and exposes no public name for it; reusing it keeps
    # one YAML notation across the plugin
    frontmatter = _scope._parse_frontmatter(doc_abs.read_text(encoding = _ENCODING))
    return frontmatter if isinstance(frontmatter, dict) else {}

  @staticmethod
  def read_stored_hash(doc_abs: Path) -> str | None:
    """
    Read the `domain_hash` frontmatter value of a generated doc.

    Args:
      doc_abs: Absolute path of the group doc.

    Returns:
      The stored hash string, or `None` when the doc or the key is absent.
    """
    value = DomainPlanner.read_frontmatter(doc_abs).get(FM_DOMAIN_HASH)
    return str(value) if value else None

  @staticmethod
  def read_stored_tags(doc_abs: Path) -> list[str]:
    """
    Read the `tags` frontmatter list of a generated doc.

    Args:
      doc_abs: Absolute path of the group doc.

    Returns:
      The stored tag strings, or `[]` when the doc, the key, or a well-formed
      list value is absent.
    """
    value = DomainPlanner.read_frontmatter(doc_abs).get(FM_TAGS)
    return list(value) if isinstance(value, list) else []
