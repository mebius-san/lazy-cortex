"""
Canonical per-language texts the wiki emits into generated files.

Every file the wiki engine rebuilds wholesale carries one asterisk-italic
one-liner under its title, in the vault's language, so the operator never has
to guess what the file is or whether hand edits survive (they do not). Longer
fixed passages — a generated file's whole preamble, a message a skill reports
— live here under their own keys.

This module is the only place any of that wording exists. A writer that needs
a passage asks the CLI's `text` verb for it by key and pastes what comes back;
no agent or skill body carries a copy, so a new language is one entry here and
touches nothing a model reads.

Language resolves through the settings chain `wiki.language` (plugin key),
top-level `language` (repo-wide default), floor `en`. The domain surfaces
instead follow the language their documents are authored in, read from
`wiki.domains.language` through `language_code` — so the index always
matches the docs it lists. Every language key holds an ISO 639-1 code;
`language_code` still accepts the free-form names that key used to hold,
for one release, and `LANGUAGE_NAMES` expands a code back into a name
wherever a sender puts a language into a model's prompt.
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

# One surface key per generated file kind; the agent-authored domain doc fetches
# its line through the CLI's `text` verb rather than carrying a copy.
SURFACE_TOPICS = "topics"
SURFACE_DOMAINS_INDEX = "domains-index"
SURFACE_DOMAIN_DOC = "domain-doc"

# Keys for fixed passages that are not one-line explainers: a whole preamble a
# writer pastes under a title, a message a skill reports back to the operator.
TEXT_TAG_DICTIONARY_INTRO = "tag-dictionary-intro"
TEXT_QUERY_NO_RESULTS = "query-no-results"

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

TEXTS: dict[tuple[str, str], str] = {
    (TEXT_TAG_DICTIONARY_INTRO, LANG_EN): (
        "# Tag values\n"
        "\n"
        "Advisory dictionary of the wiki's canonical tag values, maintained by the wiki tag curator.\n"
        "It records what each value covers so a later classification reuses a settled value instead of\n"
        "coining a synonym beside it. It constrains nothing: a classification may coin a value the\n"
        "dictionary does not list, and the next canon pass records it here."
    ),
    (TEXT_TAG_DICTIONARY_INTRO, "ru"): (
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "# Значения тегов\n"  # noqa: RUF001
        "\n"
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Справочный словарь канонических значений тегов вики, который ведёт куратор тегов. Он\n"  # noqa: RUF001
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "записывает, что покрывает каждое значение, чтобы следующая классификация переиспользовала\n"  # noqa: RUF001
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "уже устоявшееся значение, а не завела рядом синоним. Он ничего не ограничивает:\n"  # noqa: RUF001
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "классификация вправе завести значение, которого в словаре нет, и следующий проход канона\n"  # noqa: RUF001
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "запишет его сюда."  # noqa: RUF001
    ),
    (TEXT_QUERY_NO_RESULTS, LANG_EN): "No wiki material matched this question.",
    (TEXT_QUERY_NO_RESULTS, "ru"):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Ни один материал вики не подошёл под этот вопрос.",  # noqa: RUF001
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


# Legacy free-form values `wiki.domains.language` carried before the key held a code.
# Dropped one release after the doctor's rewrite offer; nothing new may be added here.
_LEGACY_NAME_CODES: dict[str, str] = {
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    "русский": "ru",  # noqa: RUF001
    "russian": "ru",
    "english": LANG_EN,
}

# Display name per code — the expansion a sender applies when it puts a language
# into a model's prompt. There is no reverse reading of these anywhere.
LANGUAGE_NAMES: dict[str, str] = {
    LANG_EN: "English",
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    "ru": "русский",  # noqa: RUF001
}


def language_code(value: str) -> str:
  """
  Narrow a configured language value to an ISO 639-1 code.

  Guarantees:
    - Always returns a non-empty code; an empty or whitespace-only value
      resolves to the `en` floor.

  Args:
    value: The configured value — a code, or one of the legacy free-form
      names the setting carried before codes.

  Returns:
    The matching code for a known legacy name; otherwise the value stripped
    and lowercased, so a code passes through unchanged.
  """

  # Contract:
  # The returned code is never empty: an empty or whitespace-only value
  # resolves to the `en` floor rather than to an empty string.

  cleaned = value.strip().lower()

  # guard: nothing configured — `en` is the shipped floor
  if not cleaned:
    return LANG_EN
  return _LEGACY_NAME_CODES.get(cleaned, cleaned)


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


def text_keys() -> list[str]:
  """
  List every key `text_for` answers, for a caller that has to validate one.

  Returns:
    The surface keys followed by the fixed-passage keys, each once, in a stable order.
  """
  surfaces = [ SURFACE_TOPICS, SURFACE_DOMAINS_INDEX, SURFACE_DOMAIN_DOC ]
  return surfaces + sorted({ key for key, _ in TEXTS })


def text_for(key: str, lang: str) -> str:
  """
  Render one canonical passage in the given language.

  This is the single reader every writer goes through, so no agent or skill body
  carries wording of its own. A surface key renders its italic explainer line; a
  fixed-passage key renders its text verbatim, newlines and all.

  Guarantees:
    - Every key `text_keys` lists renders in some language; a language carrying no
      text of its own falls back to English.

  Args:
    key: One of the keys `text_keys` returns.
    lang: The resolved language tag; unknown languages fall back to English.

  Returns:
    The passage, without a trailing newline.

  Raises:
    KeyError: The key belongs to neither table.
  """

  # Contract:
  # Every key `text_keys` lists MUST render in some language: a language tag carrying
  # no text of its own falls back to the English wording.

  # guard: a surface renders through the explainer form, which wraps it in asterisks
  if ( key, LANG_EN ) in EXPLAINERS:
    return explainer_line( key, lang )
  return TEXTS.get( ( key, lang ) ) or TEXTS[ ( key, LANG_EN ) ]
