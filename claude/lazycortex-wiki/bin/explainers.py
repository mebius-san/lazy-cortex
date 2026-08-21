"""
Italic explainer lines for wiki-generated files.

Every file the wiki engine rebuilds wholesale carries one asterisk-italic
one-liner under its title, in the vault's language, so the operator never has
to guess what the file is or whether hand edits survive (they do not). The
texts live here; the renderers (`index.py`, `domains.py`, the domain-spec
writer agent) read them per surface.

Language resolves through the settings chain `wiki.language` (plugin key),
top-level `language` (repo-wide default), floor `en`. The domain surfaces
instead follow the language their documents are authored in — the free-form
`wiki.domains.language` name, mapped to a tag via `language_tag_for_name` —
so the index always matches the docs it lists.
"""
from __future__ import annotations

import json
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_WIKI_SECTION = "wiki"
_LANGUAGE_KEY = "language"

LANG_EN = "en"

# One surface key per generated file kind; the agent-authored domain doc reads
# its line from here too (quoted verbatim in the agent's instructions).
SURFACE_TOPICS = "topics"
SURFACE_DOMAINS_INDEX = "domains-index"
SURFACE_DOMAIN_DOC = "domain-doc"

EXPLAINERS: dict[tuple[str, str], str] = {
    (SURFACE_TOPICS, LANG_EN): "The topic catalog for this scope. Rebuilt automatically — do not edit by hand.",
    (SURFACE_TOPICS, "ru"):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Каталог тем этого раздела. Пересобирается автоматически — руками не править.",  # noqa: RUF001
    (SURFACE_DOMAINS_INDEX, LANG_EN): "The rule-group index. Rebuilt automatically — do not edit by hand.",
    (SURFACE_DOMAINS_INDEX, "ru"):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Указатель групп правил. Пересобирается автоматически — руками не править.",  # noqa: RUF001
    (SURFACE_DOMAIN_DOC, LANG_EN):
        "This group's reference: terms, principles, formulas. Rebuilt automatically — do not edit by hand.",
    (SURFACE_DOMAIN_DOC, "ru"):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Справка по этой группе: термины, принципы, формулы. Пересобирается автоматически — руками не править.",  # noqa: RUF001
}


def resolve_language(repo: Path) -> str:
  """
  Resolve the wiki explainer language from the repo settings.

  Guarantees:
    - Always returns a language tag; a missing, unreadable, or malformed
      settings document resolves to English instead of raising.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.

  Returns:
    The first non-empty value among `wiki.language`, the top-level `language`
    key, and the floor `en`.
  """

  # Contract:
  # Resolution MUST always yield a language tag: a missing, unreadable, or
  # malformed settings document falls back to English instead of raising.

  # Domain(wiki.surfaces):
  # # Language of generated wiki surfaces
  # Every file the wiki rebuilds wholesale speaks one language, chosen by a fixed precedence: the
  # wiki's own configured language wins, the repository-wide language is the fallback, and English
  # is the floor when neither is set. The domain surfaces are the exception — the group index and
  # the group references speak the language their documents are authored in, so a reader never
  # meets an index in one language listing documents written in another.

  # settings document carrying both language keys
  settings_path = repo / _SETTINGS_REL

  # guard: no settings file — English is the shipped floor
  if not settings_path.is_file():
    return LANG_EN
  try:
    settings = json.loads(settings_path.read_text())
  except (OSError, json.JSONDecodeError):
    return LANG_EN
  # guard: a malformed settings document falls back the same way a missing one does
  if not isinstance(settings, dict):
    return LANG_EN

  # first the plugin's own key, then the repo-wide default
  wiki = settings.get(_WIKI_SECTION)
  plugin_lang = wiki.get(_LANGUAGE_KEY) if isinstance(wiki, dict) else None
  root_lang = settings.get(_LANGUAGE_KEY)
  for value in (plugin_lang, root_lang):
    if isinstance(value, str) and value:
      return value
  return LANG_EN


def language_tag_for_name(name: str) -> str:
  """
  Map a free-form language name from `wiki.domains.language` to an explainer tag.

  Args:
    name: The configured language name (e.g. `English`, `Russian`, or already a tag).

  Returns:
    `ru` for a Russian name or tag; `en` for everything else — the only two
    languages the explainer table carries.
  """
  # waiver: the two spellings are the closed key set of EXPLAINERS, not domain constants
  return "ru" if name.strip().lower() in ("russian", "ru") else LANG_EN


def explainer_line(surface: str, lang: str) -> str:
  """
  Render the asterisk-italic explainer line for one generated surface.

  Guarantees:
    - Every `SURFACE_*` key renders a line in some language; a language tag
      with no text of its own falls back to English.

  Args:
    surface: One of the `SURFACE_*` keys.
    lang: The resolved language tag; unknown languages fall back to English.

  Returns:
    The `*...*` line, without a trailing newline.
  """

  # Contract:
  # Every `SURFACE_*` key MUST render a line in some language: a language tag
  # carrying no text of its own falls back to the English wording.

  text = EXPLAINERS.get((surface, lang)) or EXPLAINERS[(surface, LANG_EN)]
  return f"*{text}*"
