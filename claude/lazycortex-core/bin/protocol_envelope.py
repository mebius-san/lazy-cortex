"""
Audit of protocol files against the response envelope they are forbidden to redefine.

`outcome` / `error` / `result` belong to the expert-runtime contract and reach every
expert through its system prompt. A protocol declares which values `outcome` takes and
which extra fields it adds; a protocol that prescribes a status key of its own leaves the
runtime without a discriminator, so every failure the expert reports classifies as a
success. This module finds those protocols by reading them, and is the static half of the
defence — the runtime half rejects the responses themselves.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import JobFile, JobResponseKey  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Consumer-scope directories protocol files live in, relative to a repo root and to $HOME.
_REFERENCE_DIRS = ( ".claude/references", )
# Filename suffix that marks a wire-contract document.
_PROTOCOL_SUFFIX = "-protocol.md"
# The meta-contract necessarily quotes the shapes it forbids, so it is never a finding.
_EXEMPT_NAMES = frozenset({ "lazy-core.expert-protocols-contract.md" })
# A heading that introduces the response section of a protocol.
_RESPONSE_HEADING = re.compile(r"^#{1,6}\s.*(response\.json|response shape|output)", re.IGNORECASE)
# Any other heading closes the response section opened above.
_ANY_HEADING = re.compile(r"^#{1,6}\s")
# Status-like keys a protocol may not introduce in place of the envelope's discriminator.
_RIVAL_KEY = re.compile(r"""["']?(status|state)["']?\s*[:=]""", re.IGNORECASE)


def _find_rival_key(text: str) -> str | None:
  """
  Find a status-like key prescribed inside a protocol's own response section.

  Args:
    text: Full text of the protocol file.

  Returns:
    The offending line, stripped, or None when the response section names no rival key.
  """
  in_section = False
  for line in text.splitlines():
    # a heading either opens the response section or closes the one in progress
    if _ANY_HEADING.match(line):
      in_section = bool(_RESPONSE_HEADING.match(line))
      continue
    # guard: only the response section can misdeclare the response
    if not in_section:
      continue
    if _RIVAL_KEY.search(line):
      return line.strip()
  return None


def _audit_file(path: Path) -> dict | None:
  """
  Audit one protocol file against the response envelope.

  Args:
    path: Path to the `*-protocol.md` file to read.

  Returns:
    A `{path, detail}` finding, or None when the protocol leaves the envelope alone.
  """
  try:
    text = path.read_text()
  except OSError:
    return None
  # guard: a protocol that never mentions the response file declares nothing about it
  if JobFile.RESPONSE not in text:
    return None
  rival = _find_rival_key(text)
  names_outcome = JobResponseKey.OUTCOME in text
  if rival is not None and not names_outcome:
    return { "path": str(path), "detail": f"prescribes `{rival}` and never names `outcome`" }
  if rival is not None:
    return { "path": str(path), "detail": f"names a rival status key beside `outcome`: `{rival}`" }
  if not names_outcome:
    return { "path": str(path), "detail": "declares response.json but never names `outcome`" }
  return None


def audit(repo: Path) -> list[dict]:
  """
  Audit every protocol file reachable from a repository against the response envelope.

  Scans the repository's own reference directory and the same directory under the user's
  home, so protocols authored at either scope are covered by one call.

  Args:
    repo: Path to the repository root whose protocols are audited.

  Returns:
    One `{path, detail}` finding per offending protocol, in scan order.
  """
  findings: list[dict] = []
  for root in ( Path(repo), Path.home() ):
    for rel in _REFERENCE_DIRS:
      ref_dir = root / rel
      # guard: a scope may have no references directory at all
      if not ref_dir.is_dir():
        continue
      for name in sorted(os.listdir(ref_dir)):
        # guard: only protocol files carry the wire contract, and the meta-contract is exempt
        if not name.endswith(_PROTOCOL_SUFFIX) or name in _EXEMPT_NAMES:
          continue
        finding = _audit_file(ref_dir / name)
        if finding is not None:
          findings.append(finding)
  return findings
