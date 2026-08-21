"""
Migrations for the `routines` section of `lazy.settings.json`.

v1 → v2 (`MIGRATIONS[1]`) rewrites every routine entry's flat
`frontmatter_filter` into the composite `filter.frontmatter` block, converting
each predicate value `<list-or-scalar>` into `{ in: <list>, not_in: [] }`. A
routine already on the new-shape `filter` is left untouched. The section dict is
the routines map itself, so the transform iterates routine entries directly,
skipping the `_version` key and any non-dict value.

v2 → v3 (`MIGRATIONS[2]`) drops the `spec.import-pull` entry, when present — its
command (`lazycortex-specs import-specs`) resolves to a retired subcommand
(`docs/tasks/lazycortex-specs.upstream.md` § import-pull removal; `lazy-spec.upstream-tick`
supersedes it), so every scheduled tick would otherwise fail with an unknown-
subcommand error forever. Idempotent: a section already carrying no
`spec.import-pull` key is passed through unchanged.

v3 → v4 (`MIGRATIONS[3]`) retrofits the personal bot `git_author` onto the
deterministic wiki command routines registered before the seed carried one:
entries whose command is `lazycortex-wiki` `prune-node` / `domain-tick` /
`mirror-sync` gain `{name: <family>, email: <family>@bot.invalid}` where the
family is the routine's canonical name for that subcommand. Entries already
carrying a `git_author` block, and every other routine, pass through unchanged.

v4 → v5 (`MIGRATIONS[4]`) moves the lazycortex-specs routines onto their own
plugin namespace: the keys `spec.gate-tick` / `spec.coordinator-watch` /
`spec.request-open` / `spec.request-apply` / `spec.upstream-tick` become their
`lazy-spec.` counterparts, and every `protocols[]` member naming a specs
protocol is re-prefixed to match the renamed reference files. Routines from
other plugins, and a section already on the new keys, pass through unchanged.

v5 → v6 (`MIGRATIONS[5]`) follows the `experts` v3 → v4 step: an expert-shaped
routine whose `expert:` field names one of the three recanonicalised keys is
pointed at the new key instead, so the dispatch still resolves. The routine's own
key is untouched — it belongs to a plugin and keeps that namespace. Add
`6: lambda data: <transformed>` here when a v6 → v7 migration is needed.
"""
from __future__ import annotations

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error
from constants import BOT_EMAIL_DOMAIN

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: one-off retired-routine name for this single unregister step, not a reusable domain value
_IMPORT_PULL_KEY = "spec.import-pull"

# Decision: the retrofitted identity is keyed on the wiki subcommand's family, not on the routine
# key — scope-bound siblings (`lazy-wiki.mirror-sync.<scope-id>`) share one bot address, because
# the routine key already names the scope and the operator fixed the family form in the
# routine-git-identity task; a per-key address would fragment loop-detect's author set per scope.

# waiver: wiki CLI subcommand → routine-family map local to this retrofit step, not reusable keys
_WIKI_COMMIT_FAMILIES = {
  "prune-node": "lazy-wiki.scan-deletes",
  "domain-tick": "lazy-wiki.domain-scan",
  "mirror-sync": "lazy-wiki.mirror-sync",
}


# waiver: retired routine keys for this single rename step, not reusable domain values
_SPEC_ROUTINE_RENAMES = {
  "spec.gate-tick": "lazy-spec.gate-tick",
  "spec.coordinator-watch": "lazy-spec.coordinator-watch",
  "spec.request-open": "lazy-spec.request-open",
  "spec.request-apply": "lazy-spec.request-apply",
  "spec.upstream-tick": "lazy-spec.upstream-tick",
}

# the reference prefix a specs protocol carried before the plugin took its own namespace
_SPEC_PROTOCOL_OLD_PREFIX = "lazycortex-specs:spec."
_SPEC_PROTOCOL_NEW_PREFIX = "lazycortex-specs:lazy-spec."

# waiver: routine-entry sub-key local to this rename step, mirroring this ladder's own convention
_PROTOCOLS_KEY = "protocols"


# waiver: routine-entry sub-key local to this rename step, mirroring this ladder's own convention
_EXPERT_KEY = "expert"

# The expert keys the `experts` v3 → v4 step recanonicalises. An expert-shaped routine names one
# in its own `expert:` field, so the two sections move together or the routine dispatches into a
# key that no longer exists.
_PRE_CANON_EXPERT_KEYS = {
  "lazy-review.coordinator": "review.coordinator",
  "lazy-runtime.doctor": "runtime.doctor",
  "lazy-core.autocheckup": "core.autocheckup",
}


def _recanon_expert_ref(entry: object) -> object:
  """
  Rewrite an expert-shaped routine's `expert:` reference onto the recanonicalised key.

  Args:
    entry: One routine entry from the section, or any non-dict value the section carries.

  Returns:
    The entry with its `expert` field moved to the canonical key, or the input unchanged when
    it names no expert or names one outside the closed pre-canon set.
  """
  # guard: a command-shaped routine carries no expert reference at all
  if not isinstance(entry, dict) or not isinstance(ref := entry.get(_EXPERT_KEY), str):
    return entry

  # guard: an expert outside the closed pre-canon set keeps whatever reference it has
  if (canon := _PRE_CANON_EXPERT_KEYS.get(ref)) is None:
    return entry

  # only the reference moves; the routine's own key stays in the plugin namespace
  return { **entry, _EXPERT_KEY: canon }


def _renamespace_spec_protocols(entry: object) -> object:
  """
  Rewrite a routine entry's specs-protocol references onto the plugin's own namespace.

  Args:
    entry: One routine entry from the section, or any non-dict value the section carries.

  Returns:
    The entry with every `protocols[]` member naming a lazycortex-specs protocol re-prefixed,
    or the input unchanged when it carries no such member.
  """
  # guard: only a routine entry with a protocol list can carry a specs reference
  if not isinstance(entry, dict) or not isinstance(entry.get(_PROTOCOLS_KEY), list):
    return entry

  # the rename is per-member; a protocol from any other plugin passes through untouched
  return { **entry, _PROTOCOLS_KEY: [
    _SPEC_PROTOCOL_NEW_PREFIX + p[len(_SPEC_PROTOCOL_OLD_PREFIX):]
    if isinstance(p, str) and p.startswith(_SPEC_PROTOCOL_OLD_PREFIX) else p
    for p in entry[_PROTOCOLS_KEY]
  ] }


def _retrofit_wiki_git_author(entry: object) -> object:
  """
  Attach the family bot identity to one committing wiki command routine, passing others through.

  Args:
    entry: One value from the `routines` section map.

  Returns:
    The entry with a `git_author` block added, or the input unchanged when the entry is not a
    dict, already carries one, or is not a committing `lazycortex-wiki` command routine.
  """
  # guard: version sentinel or non-dict value — pass through untouched
  if not isinstance(entry, dict):
    return entry

  # the command vector decides everything below, so it is fetched before any judgement
  # waiver: settings sub-key literal local to this ladder, not a reusable cross-module key
  command = entry.get("command")

  # guard: an operator-set identity is never overwritten, and a shapeless command cannot be judged
  # waiver: settings sub-key literal local to this ladder, not a reusable cross-module key
  if "git_author" in entry or not isinstance(command, list) or len(command) < 2:
    return entry

  # only the wiki CLI's committing subcommands resolve to a retrofit family
  # waiver: sibling-plugin binary name local to this retrofit step, not a reusable domain key
  family = _WIKI_COMMIT_FAMILIES.get(command[1]) if command[0] == "lazycortex-wiki" else None
  # guard: not one of the committing wiki subcommands
  if family is None:
    return entry

  # the family becomes both halves of the identity, on the canonical bot domain
  # waiver: settings sub-key literals local to this ladder, not reusable cross-module keys
  return { **entry, "git_author": { "name": family, "email": f"{family}{BOT_EMAIL_DOMAIN}" } }


MIGRATIONS = {
  # v1 → v2: frontmatter_filter -> filter.frontmatter with {in,not_in} predicates.
  1: lambda data: {
    rk: (
      {
        **{ k: v for k, v in rv.items() if k != "frontmatter_filter" },
        "filter": {
          **rv.get("filter", {}),
          "frontmatter": {
            pk: {
              "in": pv if isinstance(pv, list) else [ pv ],
              "not_in": [],
            }
            for pk, pv in rv["frontmatter_filter"].items()
          },
        },
      }
      if isinstance(rv, dict) and "frontmatter_filter" in rv
      else rv
    )
    for rk, rv in data.items()
  },
  # v2 → v3: drop the retired spec.import-pull routine entry, when present.
  2: lambda data: { rk: rv for rk, rv in data.items() if rk != _IMPORT_PULL_KEY },
  # v3 → v4: family bot git_author onto committing wiki command routines that predate the seed.
  3: lambda data: { rk: _retrofit_wiki_git_author(rv) for rk, rv in data.items() },
  # v4 → v5: lazycortex-specs routine keys and protocol refs onto the plugin's own namespace.
  4: lambda data: {
    _SPEC_ROUTINE_RENAMES.get(rk, rk): _renamespace_spec_protocols(rv)
    for rk, rv in data.items()
  },
  # v5 → v6: `expert:` refs onto the recanonicalised expert keys; routine keys untouched.
  5: lambda data: { rk: _recanon_expert_ref(rv) for rk, rv in data.items() },
}
