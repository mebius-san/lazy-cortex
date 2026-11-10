from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  # waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
  import domains as _domains  # pylint: disable=import-error


# Section headings of the navigation rule the two coverage renderings land under.
COVERAGE_HEADING = "## Coverage"
DOMAIN_COVERAGE_HEADING = "## Domain coverage"

# Scope config keys a coverage bullet is built from.
_KEY_PATHS = "paths"
_KEY_EXCLUDE_PATHS = "exclude_paths"

# The domain-tree index file name under the output directory.
_DOMAINS_INDEX = "domains.md"

# The line the domain-coverage section carries when no domain tree is configured.
NO_DOMAINS_LINE = "No domain tree is configured in this repo."

# Prefix every section heading of the rule opens with, and the line break the rule is assembled with.
_SECTION_PREFIX = "## "
_NL = "\n"
_GLOB_SEP = ", "


# ----------------------------------------------------------------------------------------
def render_coverage(scopes: dict) -> str | None:
  """
  Render the coverage bullet list of the configured wiki scopes.

  The list has one bullet per scope in id order, in the form `- **<id>** — <glob>, <glob>`. A scope that
  has `exclude_paths` extends its bullet with `(excluding <glob>, <glob>)`; a scope without them carries
  no parenthetical.

  Args:
    scopes: Scope configurations keyed by scope id.

  Returns:
    The bullets joined by line breaks, or `None` when there are no scopes.
  """
  # guard: no scopes — nothing to render, the caller decides what the section then says
  if not scopes:
    return None

  # one bullet per scope in id order; the parenthetical appears only when the scope excludes anything
  bullets = []
  for scope_id in sorted(scopes):
    cfg = scopes[scope_id]
    line = f"- **{scope_id}** — {_GLOB_SEP.join(cfg.get(_KEY_PATHS) or [])}"
    if excludes := cfg.get(_KEY_EXCLUDE_PATHS) or []:
      line += f" (excluding {_GLOB_SEP.join(excludes)})"
    bullets.append(line)
  return _NL.join(bullets)


def render_domain_coverage(cfg: _domains.DomainConfig | None) -> str:
  """
  Render the domain-coverage line of the configured domain tree.

  Args:
    cfg: Domain tree configuration, or `None` when no domain tree is configured.

  Returns:
    The line `- **domains** — <glob>, … (index: <output>/domains.md)`, or the line stating that no domain
    tree is configured.
  """
  # without a domain tree the rule states that none is configured
  if cfg is None:
    return NO_DOMAINS_LINE

  # a configured tree is named by its globs and its index
  return f"- **domains** — {_GLOB_SEP.join(cfg.code)} (index: {cfg.output}/{_DOMAINS_INDEX})"


def compose(source_text: str, *, coverage: str | None, domain_coverage: str | None) -> str:
  """
  Fill the coverage sections of a navigation rule text with their renderings.

  Args:
    source_text: Full text of the navigation rule.
    coverage: Rendering for the coverage section, or `None` to keep that section as it is.
    domain_coverage: Rendering for the domain-coverage section, or `None` to keep that section as it is.

  Returns:
    The rule text with each given rendering in place of its section body.
  """
  # each section that has a rendering is replaced; one without keeps the source text
  text = source_text
  if coverage is not None:
    text = replace_section(text, COVERAGE_HEADING, coverage)
  if domain_coverage is not None:
    text = replace_section(text, DOMAIN_COVERAGE_HEADING, domain_coverage)
  return text


def replace_section(text: str, heading: str, body: str) -> str:
  """
  Replace the body of one `## ` section of a markdown text.

  Everything between the heading and the next `## ` heading, or the end of the text, is replaced.

  Args:
    text: Markdown text holding the section.
    heading: Exact heading line of the section to replace.
    body: New section body; an empty body leaves the section blank.

  Returns:
    The text with the section body replaced, or the text unchanged when it has no such heading.
  """
  lines = text.split(_NL)

  # guard: a rule without the heading has no section to replace
  if heading not in lines:
    return text

  # the section runs from the line after its heading to the next section heading, or the end of the text
  start = lines.index(heading) + 1
  end = next(
    (index for index in range(start, len(lines)) if lines[index].startswith(_SECTION_PREFIX)), len(lines),
  )

  # the body sits between one blank line after the heading and one before the next heading
  replacement = [ "", body, "" ] if body else [ "" ]
  return _NL.join([ *lines[:start], *replacement, *lines[end:] ])
