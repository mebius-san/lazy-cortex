"""
Migrations for the `experts` section of `lazy.settings.json`.

v1 → v2 (`MIGRATIONS[1]`) canonicalises every expert entry's `git_author.email`
domain to `@bot.invalid`: the legacy domains `@lazycortex.local` and
`@bot.lazy-cortex` are rewritten with the local part kept as-is. Entries already
on `@bot.invalid`, entries without a `git_author` block, and non-dict values are
passed through unchanged.

v2 → v3 (`MIGRATIONS[2]`) moves each entry's lazycortex-specs `agent` reference
onto the plugin's own namespace (`lazycortex-specs:spec.<name>` becomes
`lazycortex-specs:lazy-spec.<name>`). The expert key itself never moves — it
stays `<domain>.<role>` by marketplace convention — and neither does the entry's
`git_author`, which derives from that key.

v3 → v4 (`MIGRATIONS[3]`) strips the plugin namespace off the three expert keys
seeded before `lazy-core.install` derived the key from the agent name instead of
copying it: `lazy-review.coordinator`, `lazy-runtime.doctor` and
`lazy-core.autocheckup` become `review.coordinator`, `runtime.doctor` and
`core.autocheckup`. Each entry's `git_author.email` moves with its key, since the
commit recogniser matches on that address; the display name moves only when it
still spelled the old key, and the `agent` reference stays on the artifact's own
namespaced name. A key the operator renamed by hand, and an entry whose address
is not the pre-canon default, are both left alone. Add
`4: lambda data: <transformed>` here when a v4 → v5 migration is needed.
"""
from __future__ import annotations

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error
from constants import BOT_EMAIL_DOMAIN

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# the retired identity domains this ladder rewrites onto the canonical `BOT_EMAIL_DOMAIN`
_LEGACY_DOMAINS = ( "@lazycortex.local", "@bot.lazy-cortex" )

# waiver: settings sub-key literal local to this ladder, not a reusable cross-module key
_AGENT_KEY = "agent"

# the agent-reference prefix a specs expert carried before the plugin took its own namespace
_SPEC_AGENT_OLD_PREFIX = "lazycortex-specs:spec."
_SPEC_AGENT_NEW_PREFIX = "lazycortex-specs:lazy-spec."

# waiver: settings sub-key literals local to this ladder, not reusable cross-module keys
_GIT_AUTHOR_KEY = "git_author"
_NAME_KEY = "name"
_EMAIL_KEY = "email"

# The three keys `lazy-core.install` seeded from the agent name before it derived the
# `<domain>.<role>` form. Closed set on purpose: a key is renamed only where the pre-canon
# name is known, never by pattern — an operator's own `lazy-`-shaped key is not this
# ladder's business.
_PRE_CANON_EXPERT_KEYS = {
  "lazy-review.coordinator": "review.coordinator",
  "lazy-runtime.doctor": "runtime.doctor",
  "lazy-core.autocheckup": "core.autocheckup",
}


def _canon_email(email: str) -> str:
  """
  Rewrite a legacy identity domain to the canonical one, keeping the local part.

  Args:
    email: The `git_author.email` value to canonicalise.

  Returns:
    The email with a legacy domain replaced by `@bot.invalid`, or the input unchanged.
  """
  for domain in _LEGACY_DOMAINS:
    # guard: only a legacy-domain email is rewritten
    if email.endswith(domain):
      return email[: -len(domain)] + BOT_EMAIL_DOMAIN
  return email


def _canon_entry(entry: object) -> object:
  """
  Canonicalise one expert entry's `git_author.email`, passing non-conforming shapes through.

  Args:
    entry: One value from the `experts` section map.

  Returns:
    The entry with its `git_author.email` canonicalised, or the input unchanged when the entry
    is not a dict or carries no string email.
  """
  # guard: version sentinel or hand-written non-dict value — pass through untouched
  if not isinstance(entry, dict):
    return entry

  # the identity block is the only part of the entry this ladder ever judges
  # waiver: settings sub-key literal local to this ladder, not a reusable cross-module key
  author = entry.get("git_author")

  # guard: no git_author block, or no string email inside it — nothing to canonicalise
  # waiver: settings sub-key literal local to this ladder, not a reusable cross-module key
  if not isinstance(author, dict) or not isinstance(author.get("email"), str):
    return entry

  # only the email moves; the name and every sibling key survive verbatim
  # waiver: settings sub-key literals local to this ladder, not reusable cross-module keys
  return { **entry, "git_author": { **author, "email": _canon_email(author["email"]) } }


def _renamespace_spec_agent(entry: object) -> object:
  """
  Rewrite one expert entry's lazycortex-specs agent reference onto the plugin's own namespace.

  Args:
    entry: One value from the `experts` section map.

  Returns:
    The entry with its `agent` reference re-prefixed, or the input unchanged when the entry is
    not a dict or its agent belongs to another plugin.
  """
  # guard: version sentinel or hand-written non-dict value — pass through untouched
  if not isinstance(entry, dict):
    return entry

  # guard: an agent from any other plugin, or an entry already on the new prefix — the agent
  # reference is the only field this ladder judges; the expert key itself never moves
  if not isinstance(agent := entry.get(_AGENT_KEY), str) or not agent.startswith(_SPEC_AGENT_OLD_PREFIX):
    return entry

  # only the prefix changes; the agent's own name and every sibling key survive verbatim
  return { **entry, _AGENT_KEY: _SPEC_AGENT_NEW_PREFIX + agent[len(_SPEC_AGENT_OLD_PREFIX):] }


def _recanon_identity(name: str, entry: object) -> object:
  """
  Move a renamed expert's bot identity onto its new key, leaving a customised one alone.

  Args:
    name: The entry's current key, before the rename this ladder applies to it.
    entry: One value from the `experts` section map.

  Returns:
    The entry with `git_author.email` rebuilt from the canonical key, and `git_author.name`
    rebuilt too when it still spelled the old key; the input unchanged when the key is not
    being renamed or the address is one the operator chose.
  """
  # guard: only the closed pre-canon set moves, and only a dict entry carries an identity
  if (canon := _PRE_CANON_EXPERT_KEYS.get(name)) is None or not isinstance(entry, dict):
    return entry

  # guard: an address the operator picked is theirs — the whole identity is left as written
  author = entry.get(_GIT_AUTHOR_KEY)
  if not isinstance(author, dict) or author.get(_EMAIL_KEY) != f"{name}{BOT_EMAIL_DOMAIN}":
    return entry

  # the address must track the key — the commit recogniser matches on it — while a display
  # name the operator wrote over the seeded one survives
  renamed = { **author, _EMAIL_KEY: f"{canon}{BOT_EMAIL_DOMAIN}" }
  if author.get(_NAME_KEY) == name:
    renamed[_NAME_KEY] = canon
  return { **entry, _GIT_AUTHOR_KEY: renamed }


MIGRATIONS = {
  # v1 → v2: legacy git_author.email domains -> @bot.invalid, local part kept.
  1: lambda data: { name: _canon_entry(entry) for name, entry in data.items() },
  # v2 → v3: lazycortex-specs agent refs onto the plugin's own namespace; expert keys untouched.
  2: lambda data: { name: _renamespace_spec_agent(entry) for name, entry in data.items() },
  # v3 → v4: the three pre-canon expert keys onto `<domain>.<role>`, identity following the key.
  3: lambda data: {
    _PRE_CANON_EXPERT_KEYS.get(name, name): _recanon_identity(name, entry)
    for name, entry in data.items()
  },
}
