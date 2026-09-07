"""
Candidate-request drafting — the Python primitive backing the `lazycortex-specs request-draft` verb.

The catalog coordinator calls this verb when a re-approved system document at the catalog root or
at a product level no longer agrees with what sits below it: each divergence it finds becomes one
candidate request dropped into the content root's `requests/` inbox. The emitted file is exactly
what an operator-written request looks like, so the existing intake pipeline picks it up unaided —
the `lazy-spec.request-open` md-scan routine opens its review, the interpreter refines it, the
operator accepts or rejects it, and the root coordinator routes it. The coordinator that dropped
the candidate never touches it again.

CLI: `request-draft --source <doc> --title <text> --body <file> [--cwd <dir>]
[--author-name <name>] [--author-email <email>]`. The request lands at
`<content-root>/requests/<slug>.md`, its slug derived from the title and given a numeric suffix
when that name is taken. The title becomes the document's H1 and the body file follows it
verbatim; `spec_source_docs` attributes the candidate to the system document that raised it.

Stdout: a JSON object with `outcome` (always `created`) and the request's repo-relative path
under `request`. The write is committed under a bot identity, defaulting to the catalog
coordinator's own; a vault outside a git checkout is written but not committed.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import flip_gate
import scaffold_asset
import spec_paths
from spec_keys import SpecKey, SpecValue

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class _K:
  """
  Literals this verb writes, matches, and reports.

  Attributes:
    DOC_TYPE: The `spec_doc_type` frontmatter key.
    SOURCE_DOCS: The `spec_source_docs` frontmatter key carrying the attribution wikilink.
    DOC_TYPE_REQUEST: The `spec_doc_type` value every request file carries.
    REQUESTS_DIR: The inbox directory under the content root.
    MD_SUFFIX: The markdown filename suffix.
    SLUG_FALLBACK: The filename stem used when a title carries no slug-bearing character.
    COLLISION_START: The first numeric suffix a colliding slug takes.
    GIT_TOPLEVEL: The git query resolving the enclosing checkout's root.
    AUTHOR_NAME: The default git author name for the drafting commit.
    AUTHOR_EMAIL: The default git author email for the drafting commit.
    OUT_OUTCOME: Output JSON key naming what the run did.
    OUT_REQUEST: Output JSON key carrying the request's repo-relative path.
    OUTCOME_CREATED: The only outcome this verb reports.
    PROG: CLI program name shown in `--help` output.
    ARG_SOURCE: CLI flag naming the system document that raised the candidate.
    ARG_TITLE: CLI flag carrying the candidate's title.
    ARG_BODY: CLI flag naming the file holding the candidate's body.
    ARG_CWD: CLI flag overriding the repo root.
    ARG_AUTHOR_NAME: CLI flag overriding the commit's author name.
    ARG_AUTHOR_EMAIL: CLI flag overriding the commit's author email.
  """

  # Frontmatter keys and values not already carried by `spec_keys`
  DOC_TYPE = "spec_doc_type"
  SOURCE_DOCS = "spec_source_docs"
  DOC_TYPE_REQUEST = "request"
  # Path segments
  REQUESTS_DIR = "requests"
  MD_SUFFIX = ".md"
  # Slug rule
  SLUG_FALLBACK = "untitled"
  COLLISION_START = 2
  # Commit
  GIT_TOPLEVEL = "--show-toplevel"
  AUTHOR_NAME = "spec.catalog-coordinator"
  AUTHOR_EMAIL = "spec.catalog-coordinator@bot.invalid"
  # Output JSON keys
  OUT_OUTCOME = "outcome"
  OUT_REQUEST = "request"
  OUTCOME_CREATED = "created"
  # CLI argparse
  PROG = "lazycortex-specs request-draft"
  ARG_SOURCE = "--source"
  ARG_TITLE = "--title"
  ARG_BODY = "--body"
  ARG_CWD = "--cwd"
  ARG_AUTHOR_NAME = "--author-name"
  ARG_AUTHOR_EMAIL = "--author-email"


# Everything that is neither a letter nor a digit collapses to a single hyphen. The class is
# unicode-aware on purpose: a vault whose documents are written in a non-latin script would
# otherwise reduce every title to `SLUG_FALLBACK` and collide with itself on every candidate.
_SLUG_SEPARATOR_RE = re.compile(r"[\W_]+", re.UNICODE)

# waiver: one-off human-facing messages -- argparse help text and the two stderr refusal lines
_HELP_SOURCE = "System document that raised the candidate, absolute or repo-relative"
_HELP_TITLE = "Candidate title; becomes the H1 and the filename slug"
_HELP_BODY = "File holding the candidate's body, written verbatim below the H1"
_HELP_CWD = "Override repo root"
_HELP_AUTHOR_NAME = "git author name for the drafting commit"
_HELP_AUTHOR_EMAIL = "git author email for the drafting commit"
_ERR_SOURCE = "source document not found: {path}\n"
_ERR_BODY = "body file not found: {path}\n"
_ERR_OUTSIDE = "source document is outside the spec content root {root}: {path}\n"


def _slug(title: str) -> str:
  """
  Convert a candidate's title into its deterministic filename stem.

  Args:
    title: Free-form candidate title as the coordinator wrote it.

  Returns:
    The lowercased title with every run of non-alphanumeric characters collapsed to a single
    hyphen and the outer hyphens stripped; `untitled` when nothing slug-bearing remains. The
    result is not unique under the inbox — pair it with `_unique_path`.
  """
  return _SLUG_SEPARATOR_RE.sub("-", title.strip().lower()).strip("-") or _K.SLUG_FALLBACK


def _unique_path(requests_dir: Path, slug: str) -> Path:
  """
  Resolve a collision-free request filename under the inbox.

  Args:
    requests_dir: The content root's `requests/` inbox.
    slug: The candidate's preferred filename stem.

  Returns:
    `requests_dir/<slug>.md`, or the first `requests_dir/<slug>-<n>.md` (from `-2` upwards) that
    is not already on disk.
  """
  candidate = requests_dir / f"{slug}{_K.MD_SUFFIX}"
  suffix = _K.COLLISION_START
  while candidate.exists():
    candidate = requests_dir / f"{slug}-{suffix}{_K.MD_SUFFIX}"
    suffix += 1
  return candidate


def _render(source_link: str, title: str, body: str) -> str:
  """
  Render the request document a hand-written candidate is indistinguishable from.

  Guarantees:
    - Neither `review_active` nor `review_result` is ever written, so the emitted candidate
      enters the intake pipeline's review loop exactly as a hand-written request does.

  Args:
    source_link: Suffix-free content-root-relative path of the document that raised the candidate.
    title: The candidate's title, written as the document's H1.
    body: The candidate's body text, written verbatim below the H1.

  Returns:
    The complete file text: the spec-side frontmatter, the title heading, and the body.
  """

  # Contract:
  # Neither `review_active` nor `review_result` is written. `open_request` reads the first as
  # "already opted in" and the second as "post-finalize", so either key would strand the
  # candidate outside the review loop the intake pipeline is supposed to pull it into.

  # the candidate's whole file text, assembled in one expression so no half-written
  # frontmatter shape can escape this function
  return (
      "---\n"
      f"{SpecKey.ROLE}: {SpecValue.ROLE_REQUEST}\n"
      f"{_K.DOC_TYPE}: {_K.DOC_TYPE_REQUEST}\n"
      f"{SpecKey.STATUS}: {SpecValue.STATUS_DRAFT}\n"
      f"{SpecKey.CLASS}: {SpecValue.CLASS_UNKNOWN}\n"
      f"{_K.SOURCE_DOCS}:\n"
      f'  - "[[{source_link}]]"\n'
      "tags:\n"
      f"  - {SpecValue.TAG_DRAFT}\n"
      "---\n"
      f"# {title}\n"
      "\n"
      f"{body}"
  )


def _commit(repo: Path, request_path: Path, author_name: str, author_email: str) -> None:
  """
  Commit the freshly written request under a bot identity, staging nothing else.

  Skipped silently when the vault does not live inside a git checkout — the file write remains,
  and is the entire mutation that path observes.

  Args:
    repo: The settings root the request was resolved under; the git command's working directory.
    request_path: The request file just written.
    author_name: Git author name recorded on the commit.
    author_email: Git author email recorded on the commit.

  Raises:
    subprocess.CalledProcessError: When either git invocation exits non-zero.
  """
  top = flip_gate._git_field(repo, [ "rev-parse", _K.GIT_TOPLEVEL ], "")
  # guard: vault is not inside a git checkout — the write above is the whole mutation
  if not top:
    return
  path = str(request_path)

  # register the path without staging its content: the index belongs to the operator, and a
  # pathspec commit takes the worktree bytes from there
  subprocess.run(
      [ "git", "add", "-N", "--", path ],
      cwd = str(top), check = True, capture_output = True,
  )

  # commit under the bot identity so the operator's authorship stays untouched, and under a
  # pathspec so nothing the operator parked in the index rides along
  subprocess.run(
      [
          "git",
          "-c", f"user.name={author_name}",
          "-c", f"user.email={author_email}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", f"spec: draft request {request_path.name}", "--", path,
      ],
      cwd = str(top), check = True, capture_output = True,
  )


def draft(
    repo: Path,
    *,
    source: Path,
    title: str,
    body: str,
    author_name: str = _K.AUTHOR_NAME,
    author_email: str = _K.AUTHOR_EMAIL,
) -> dict:
  """
  Write one candidate request into the vault's inbox and commit it.

  Guarantees:
    - The emitted file is byte-shaped like an operator-written request, so the intake pipeline
      opens and reviews it with no knowledge that a coordinator wrote it.

  Args:
    repo: The settings root holding `.claude/lazy.settings.json`.
    source: The system document that raised the candidate, inside `repo`.
    title: The candidate's title; becomes the H1 and the filename slug.
    body: The candidate's body text, written verbatim below the H1.
    author_name: Git author name recorded on the drafting commit.
    author_email: Git author email recorded on the drafting commit.

  Returns:
    `{"outcome": "created", "request": <repo-relative path>}`.

  Raises:
    subprocess.CalledProcessError: When either git invocation of the drafting commit exits
      non-zero, leaving the written file in the worktree uncommitted.
    ValueError: When `source` lies outside the spec content root, so no content-root-relative
      attribution wikilink exists for it. `main` refuses such a call before reaching here.
  """

  # Contract:
  # The emitted file is byte-shaped like an operator-written request, so the intake pipeline
  # opens and reviews it with no knowledge that a coordinator wrote it.

  # the inbox may not exist yet in a vault whose first request this is
  content_root = spec_paths.spec_content_root(repo)
  requests_dir = content_root / _K.REQUESTS_DIR
  requests_dir.mkdir(parents = True, exist_ok = True)

  # attribution follows the catalog's own wikilink convention: content-root-relative, suffix-free
  source_link = str(source.resolve().relative_to(content_root.resolve()).with_suffix(""))
  request_path = _unique_path(requests_dir, _slug(title))
  request_path.write_text(_render(source_link, title, body))
  _commit(repo, request_path, author_name, author_email)
  return {
      _K.OUT_OUTCOME: _K.OUTCOME_CREATED,
      _K.OUT_REQUEST: str(request_path.relative_to(repo.resolve())),
  }


def main(argv: list[str]) -> int:
  """
  Run the `request-draft` subcommand from the command line, printing the result as JSON.

  Args:
    argv: Subcommand argv tail — `--source <doc> --title <text> --body <file> [--cwd <dir>]
      [--author-name <name>] [--author-email <email>]`.

  Returns:
    Exit code: 0 on success, 2 when the source document or the body file does not exist, or
    when the source lies outside the spec content root.
  """
  parser = argparse.ArgumentParser(prog = _K.PROG)
  # waiver: argparse CLI signature -- option flags, required-ness, and per-flag defaults
  parser.add_argument(_K.ARG_SOURCE, required = True, type = Path, help = _HELP_SOURCE)
  parser.add_argument(_K.ARG_TITLE, required = True, help = _HELP_TITLE)
  parser.add_argument(_K.ARG_BODY, required = True, type = Path, help = _HELP_BODY)
  parser.add_argument(_K.ARG_CWD, default = None, help = _HELP_CWD)
  parser.add_argument(_K.ARG_AUTHOR_NAME, default = _K.AUTHOR_NAME, help = _HELP_AUTHOR_NAME)
  parser.add_argument(_K.ARG_AUTHOR_EMAIL, default = _K.AUTHOR_EMAIL, help = _HELP_AUTHOR_EMAIL)
  args = parser.parse_args(argv)

  # a relative --source names a repo-relative document, so the verb reads the same from any cwd
  repo = Path(args.cwd).resolve() if args.cwd else scaffold_asset._repo_root(Path.cwd())
  source: Path = args.source if args.source.is_absolute() else repo / args.source
  # guard: a source that does not exist would be attributed as a dangling wikilink
  if not source.is_file():
    sys.stderr.write(_ERR_SOURCE.format(path = source))
    return 2
  # guard: an unreadable body file would emit a titled request with nothing under it
  if not args.body.is_file():
    sys.stderr.write(_ERR_BODY.format(path = args.body))
    return 2
  # guard: the attribution wikilink is content-root-relative, so a source outside that root has
  # no expressible link — refused here rather than raised out of `draft` as a bare ValueError
  content_root = spec_paths.spec_content_root(repo)
  if not source.resolve().is_relative_to(content_root.resolve()):
    sys.stderr.write(_ERR_OUTSIDE.format(root = content_root, path = source))
    return 2

  # the body reaches the verb as text, so a caller holding it in memory needs no temporary file
  print(json.dumps(draft(
      repo, source = source, title = args.title, body = args.body.read_text(),
      author_name = args.author_name, author_email = args.author_email,
  )))
  return 0
