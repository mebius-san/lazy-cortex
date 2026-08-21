"""
Domain-spec engine for lazycortex-wiki.

Materialises `Domain(…)` comment blocks found in code into the domain-spec
tree under the configured output directory. Provides the deterministic half
of the pipeline: configuration loading, dictionary parsing, block extraction,
per-group content hashing, changed/orphaned/unknown detection, and the
`domains.md` index render. The LLM writer that composes each group document
is dispatched by the CLI consumer, never from here.

Cross-plugin Python import is forbidden (per the inter-plugin boundary
contract), so all primitives used here are imported from within this
plugin's own `bin/`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import explainers as _explainers
import scope as _scope

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


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

# The reserved parking group — never generated, never listed in the dictionary.
RESERVED_GROUP = "unfiled"

# Index file name inside the output directory.
INDEX_NAME = "domains.md"

# Markdown extension of generated docs.
_MD_EXT = ".md"

# File encoding used throughout.
_ENCODING = "utf-8"

# Frontmatter key carrying the generation-time content hash of a group doc.
FM_DOMAIN_HASH = "domain_hash"

# Opening line of a `Domain(…)` block: `# Domain(<group>):` with optional tags after the colon.
_DOMAIN_HEADER_RE = re.compile(r"^\s*#\s*Domain\s*\(\s*([A-Za-z0-9_.-]+)\s*\)\s*:")

# Opening line of a `Contract:` block: bare marker, canon requires nothing after the colon.
_CONTRACT_HEADER_RE = re.compile(r"^\s*#\s*Contract:\s*$")

# A block-continuation line: any adjacent `#` comment line.
_COMMENT_LINE_RE = re.compile(r"^\s*#")

# Block-dict field names shared by scanner, planner, and CLI consumers.
BLOCK_GROUP  = "group"
BLOCK_PATH   = "path"
BLOCK_LINE   = "line"
BLOCK_TEXT   = "text"
BLOCK_SYMBOL = "symbol"

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

# Changed-group entry field names.
GROUP_KEY   = "group"
GROUP_HASH  = "hash"
GROUP_FILES = "files"
GROUP_DOC   = "doc_path"
GROUP_GLOSS = "gloss"
GROUP_BLOCKS = "blocks"
GROUP_CONTRACTS = "contracts"

# Why a generated doc is on the removal list.
DOC_REASON_NO_BLOCKS = "no-blocks"
DOC_REASON_UNLISTED  = "group-unlisted"


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

  def __init__(
    self,
    *,
    repo: Path,
    code: list[str],
    dictionary: str,
    output: str,
    language: str,
  ) -> None:
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

  def groups(self) -> dict[str, str]:
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
      # guard: prose outside any group, blank lines, sub-headings, Tags: lines, comments
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

  def scan(self) -> dict[str, list[dict]]:
    """
    Return every `Domain(…)` block found in the repo's code files, grouped by group key.

    Guarantees:
      - Blocks of one group are ordered by file path, then by line, on every
        scan of the same checkout.

    Returns:
      Mapping of group key to its block dicts (`group`, `path`, `line`,
      `text`), each list sorted by `(path, line)` for a stable order.
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
      check = False,
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

    # sweep line by line: a header opens a block, adjacent comment lines extend it
    blocks: list[dict] = []
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
      match = _DOMAIN_HEADER_RE.match(lines[idx])
      # guard: not a block header — keep sweeping
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
      blocks.append({
        BLOCK_GROUP: match.group(1),
        BLOCK_PATH:  rel,
        BLOCK_LINE:  start + 1,
        BLOCK_TEXT:  "\n".join(body),
      })
    return blocks

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
      Mapping of group key to its contract block dicts (`group`, `path`,
      `line`, `text`, `symbol`), each list sorted by `(path, line)`.
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

    # the AST symbol index this file's contracts anchor their `path:symbol` entry to
    symbol_spans = self._symbol_spans(text)

    # sweep line by line: a header opens a block, adjacent comment lines extend it
    blocks: list[dict] = []
    idx = 0
    while idx < len(lines):
      # guard: not a contract header — keep sweeping
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
      })
    return blocks

  @staticmethod
  def _symbol_spans(source: str) -> list[tuple[int, int, str]]:
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
class DomainLayout:
  """
  Path mapping between group keys and generated doc locations.

  Dot-separated key segments expand into subdirectories under the output
  directory; the last segment names the markdown file.

  Guarantees:
    - Mapping a group key to its doc path and back yields the original key,
      unless that path is the index file.
  """

  # Contract:
  # Mapping a group key to its doc path and back MUST yield the original key,
  # unless the path it lands on is the index file; the two directions of the
  # mapping stay each other's inverse.

  def __init__(self, *, output: str) -> None:
    """
    Initialise the layout for one output directory.

    Args:
      output: Repo-relative POSIX path of the output directory (no trailing slash).
    """
    # the tree root every doc path is derived under
    self._output = output

  def doc_rel(self, group: str) -> str:
    """
    Return the repo-relative doc path for a group key.

    Args:
      group: Dot-separated group key.

    Returns:
      Repo-relative POSIX path of the group's markdown doc.
    """
    segments = group.split(".")
    return "/".join([ self._output, *segments[:-1], segments[-1] + _MD_EXT ])

  def group_for(self, rel: str) -> str | None:
    """
    Map a repo-relative doc path back to its group key.

    Args:
      rel: Repo-relative POSIX path of a file under the output directory.

    Returns:
      The dot-separated group key, or `None` when the path is outside the
      output directory, is not markdown, or is the index file.
    """
    prefix = self._output + "/"
    # guard: outside the output tree or not a markdown doc
    if not rel.startswith(prefix) or not rel.endswith(_MD_EXT):
      return None
    inner = rel[len(prefix):-len(_MD_EXT)]
    # guard: the index file is never a group doc
    if inner + _MD_EXT == INDEX_NAME:
      return None
    return inner.replace("/", ".")


# ────────────────────────────────────────────────────────────────────────────
class DomainIndex:
  """
  Renderer of the `domains.md` index inside the output directory.

  Owns the title and the group listing, one line per generated doc linking its group
  key to the dictionary gloss; the rest of the file is operator or writer territory.

  Guarantees:
    - Preserves everything from the first `##` heading onward verbatim across rebuilds.
    - Seeds a brand-new index with a `## Context map` stub.
  """

  # Contract:
  # Everything from the index's first `##` heading onward is operator territory
  # and MUST survive every rebuild verbatim.

  # Contract:
  # An index rendered where none existed ALWAYS carries a `## Context map` stub,
  # so the operator half of the file is never missing.

  _TITLE           = "# Domains"
  _CONTEXT_HEADING = "## Context map"
  _STUB            = "<!-- Hand-written cross-domain relationships; the list above is engine-rendered. -->"
  _SECTION_PREFIX  = "## "

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
      doc exists, with the preserved (or stub) tail sections appended.
    """
    dictionary = DomainDictionary(path = self._cfg.repo / self._cfg.dictionary).groups()

    # Domain(wiki.domains):
    # # Who owns which half of the domain index
    # The index of the domain tree is shared between the engine and the operator. The engine owns the
    # head: the title, the self-describing line in the language the documents are written in, and one
    # entry per listed group whose document already exists, each carrying the gloss the dictionary
    # gave it — a group joins the listing only once it has a document to point at. Everything from
    # the first section heading onward belongs to the operator: cross-domain relationships that no
    # block states on its own are written there by hand and survive every rebuild.

    # one line per dictionary group whose generated doc exists on disk
    listing: list[str] = []
    for group in sorted(dictionary):
      rel = self._layout.doc_rel(group)
      # guard: doc not generated yet — the group joins the index after its writer runs
      if not (self._cfg.repo / rel).is_file():
        continue
      link = rel[len(self._cfg.output) + 1:]
      gloss = dictionary[group]
      listing.append(f"- [{group}]({link}) — {gloss}" if gloss else f"- [{group}]({link})")

    # the head is engine territory; the tail is whatever prose already follows the listing.
    # The italic line under the title self-describes the file for the operator, in the same
    # language the listed group docs are authored in (`wiki.domains.language`).
    explainer = _explainers.explainer_line(
        _explainers.SURFACE_DOMAINS_INDEX, _explainers.language_tag_for_name(self._cfg.language))
    head = self._TITLE + "\n" + explainer + "\n\n" + "\n".join(listing) + "\n"
    tail = self._preserved_tail()
    if tail:
      return head + "\n" + tail
    return head + "\n" + self._CONTEXT_HEADING + "\n\n" + self._STUB + "\n"

  def apply(self) -> bool:
    """
    Write the rendered index when it differs from the file on disk.

    Returns:
      True when the file was (re)written, False when it was already current.
    """
    index_abs = self._cfg.repo / self.index_rel()
    rendered = self.render()
    existing = index_abs.read_text(encoding = _ENCODING) if index_abs.is_file() else None
    # guard: index already current — nothing to write
    if existing == rendered:
      return False
    index_abs.parent.mkdir(parents = True, exist_ok = True)
    index_abs.write_text(rendered, encoding = _ENCODING)
    return True

  def _preserved_tail(self) -> str:
    """
    Return the existing index content from its first `##` heading onward.

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
      # guard: first section heading found — everything from here on is preserved
      if line.startswith(self._SECTION_PREFIX):
        return "\n".join(lines[idx:]) + "\n"
    return ""


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
    # config may be absent — `configured` reports it, `plan` requires it
    self._repo = Path(repo).resolve()
    self._cfg = DomainConfig.load(self._repo)

  @property
  def configured(self) -> bool:
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
    # guard: callers must check `configured` first
    if self._cfg is None:
      raise RuntimeError("wiki.domains is not configured")
    return self._cfg

  @staticmethod
  def group_hash(blocks: list[dict], contracts: list[dict] | None = None) -> str:
    """
    Compute the content hash of one group's blocks and attributed contracts.

    Guarantees:
      - Re-indenting code or reordering unrelated lines outside the group's blocks
        never changes the hash.
      - Omitting `contracts` reproduces the digest of `blocks` alone — a caller
        that never scans contracts sees no change in behaviour.

    Args:
      blocks: The group's `Domain(…)` block dicts, already sorted by `(path, line)`.
      contracts: The group's attributed `Contract:` block dicts, already sorted
        by `(path, line)`; omit, or pass an empty list, for a group with none.

    Returns:
      Hex sha256 digest of the canonical group text.
    """

    # Contract:
    # The digest covers ONLY the group's own block text plus the anchor and text
    # of each attributed contract; code outside those blocks never changes it.

    # Contract:
    # Omitting `contracts` (or passing an empty list) reproduces the exact digest
    # `group_hash(blocks)` always returned before contracts existed; a caller that
    # never scans contracts sees no change in behaviour.

    # Domain(wiki.domains):
    # # What counts as a change to a group's knowledge
    # A group's published document is rebuilt only when the knowledge behind it actually moved. The
    # measure is a digest over the group's own prose: every block of the group in file-and-line order,
    # followed by each guarantee attributed to the group together with the place it is anchored to.
    # Reformatting surrounding code or moving unrelated lines leaves the digest untouched, while
    # moving a guarantee to another place in the code changes it, because the published document
    # names that anchor. The digest of the last generation is kept inside the document itself, so
    # deciding what is stale needs no record outside the checkout.

    # the group's Domain(…) block text alone — this is the whole digest input pre-contracts
    canonical = "\n\n".join(blk[BLOCK_TEXT] for blk in blocks)
    # guard: no contracts to fold in — `canonical` above is already the full digest input
    if not contracts:
      return hashlib.sha256(canonical.encode(_ENCODING)).hexdigest()

    # Decision: a contract's `path:symbol` anchor is hashed alongside its guarantee text,
    # not the text alone as for a Domain block — the Contracts section renders that anchor,
    # so relocating a contract without touching its wording must still register as a change.

    # each contract's anchor and text, canonicalised the same way as the blocks text above
    contract_text = "\n\n".join(
      f"{contract[BLOCK_PATH]}:{contract.get(BLOCK_SYMBOL) or ''}\n{contract[BLOCK_TEXT]}"
      for contract in contracts
    )
    return hashlib.sha256(f"{canonical}\x00{contract_text}".encode(_ENCODING)).hexdigest()

  def plan(self) -> dict:
    """
    Compute the full domain-spec plan for the repo.

    Guarantees:
      - The returned plan is JSON-serialisable as it stands.

    Returns:
      Plan dict with `changed_groups` (group, hash, files, doc_path, gloss,
      blocks, contracts), `orphaned_docs`, `unlisted_docs` (the `orphaned_docs`
      subset dropped because their group left the dictionary), `unknown_groups`,
      `index_path`, `index_needs_update`, `language`, `dictionary`, and
      `output`.
    """

    # Contract:
    # The returned plan is ALWAYS JSON-serialisable as it stands; command-line
    # consumers write it out unchanged.

    # the inputs of the detect: declared groups, scanned knowledge, and the tree layout
    dictionary = DomainDictionary(path = self.cfg.repo / self.cfg.dictionary).groups()
    scanner = DomainScanner(repo = self.cfg.repo, code_globs = self.cfg.code)
    scanned = scanner.scan()
    scanned_contracts = scanner.scan_contracts()
    layout = DomainLayout(output = self.cfg.output)

    # changed groups: dictionary groups with blocks whose doc hash diverged
    changed: list[dict] = []
    for group in sorted(dictionary):
      blocks = scanned.get(group) or []
      # guard: no blocks left in code — the doc (if any) is an orphan, handled below
      if not blocks:
        continue
      contracts = scanned_contracts.get(group) or []
      digest = self.group_hash(blocks, contracts)
      doc_rel = layout.doc_rel(group)
      # guard: stored hash matches — the doc is current, zero work
      if self._stored_hash(self.cfg.repo / doc_rel) == digest:
        continue
      changed.append({
        GROUP_KEY:       group,
        GROUP_HASH:      digest,
        GROUP_FILES:     sorted({ blk[BLOCK_PATH] for blk in blocks }),
        GROUP_DOC:       doc_rel,
        GROUP_GLOSS:     dictionary[group],
        GROUP_BLOCKS:    blocks,
        GROUP_CONTRACTS: contracts,
      })

    # groups present in code but absent from the dictionary — the doctor's business
    unknown = sorted(grp for grp in scanned if grp not in dictionary and grp != RESERVED_GROUP)

    # index staleness: compare the fresh render against the file on disk
    index = DomainIndex(cfg = self.cfg)
    index_abs = self.cfg.repo / index.index_rel()
    current = index_abs.read_text(encoding = _ENCODING) if index_abs.is_file() else None

    # docs the tree should no longer carry, each with the reason it is dropped
    removals = self._removable_docs(scanned, dictionary, layout)

    # the whole plan is JSON-serialisable for the CLI wrapper
    return {
      PLAN_CHANGED:     changed,
      PLAN_ORPHANED:    sorted(removals),
      PLAN_UNLISTED:    sorted(rel for rel, why in removals.items() if why == DOC_REASON_UNLISTED),
      PLAN_UNKNOWN:     unknown,
      PLAN_INDEX_PATH:  index.index_rel(),
      PLAN_INDEX_STALE: index.render() != current,
      PLAN_LANGUAGE:    self.cfg.language,
      PLAN_DICTIONARY:  self.cfg.dictionary,
      PLAN_OUTPUT:      self.cfg.output,
    }

  def _removable_docs(
    self,
    scanned: dict[str, list[dict]],
    dictionary: dict[str, str],
    layout: DomainLayout,
  ) -> dict[str, str]:
    """
    Map every generated doc the tree should no longer carry to its removal reason.

    A doc is carried over only while its group is listed in the dictionary and still
    carries at least one block in code.

    Args:
      scanned: The scanner's group→blocks mapping.
      dictionary: Group→gloss mapping from the dictionary file.
      layout: Path mapper for the output directory.

    Returns:
      Mapping of repo-relative POSIX doc path to its removal reason
      (`no-blocks` or `group-unlisted`); empty when no output tree exists.
    """
    output_abs = self._repo / self.cfg.output
    # guard: no output tree yet — nothing can be removed
    if not output_abs.is_dir():
      return {}

    # Domain(wiki.domains):
    # # When a group's document is retired
    # A published document survives only while both of its supports hold: the group is still listed
    # in the dictionary, and at least one block of that group still exists in the code. A group the
    # dictionary no longer lists is never regenerated, so its document is retired as unlisted rather
    # than left to rot. A group whose last block left the code is retired as empty, because a
    # document must not outlive the knowledge it was written from. Retirement always carries the
    # reason it happened; a document is never dropped silently.

    # walk the output tree and judge every group doc against the dictionary and the code
    removals: dict[str, str] = {}
    for base, _dirs, files in os.walk(str(output_abs)):
      for fname in files:
        rel = (Path(base) / fname).relative_to(self._repo).as_posix()
        group = layout.group_for(rel)
        # guard: not a group doc (index, non-markdown)
        if group is None:
          continue
        # a group the dictionary no longer lists is never regenerated, so its doc can only rot
        if group not in dictionary:
          removals[rel] = DOC_REASON_UNLISTED
        elif not scanned.get(group):
          removals[rel] = DOC_REASON_NO_BLOCKS
    return removals

  @staticmethod
  def _stored_hash(doc_abs: Path) -> str | None:
    """
    Read the `domain_hash` frontmatter value of a generated doc.

    Args:
      doc_abs: Absolute path of the group doc.

    Returns:
      The stored hash string, or `None` when the doc or the key is absent.
    """
    # guard: doc not generated yet
    if not doc_abs.is_file():
      return None
    # waiver: sibling-module private frontmatter parser reused to keep one YAML notation (doctor precedent)
    frontmatter = _scope._parse_frontmatter(doc_abs.read_text(encoding = _ENCODING))
    value = frontmatter.get(FM_DOMAIN_HASH)
    return str(value) if value else None
