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

The wiki's language is resolved by core's language verb with the wiki's own
section, so `wiki.language` outranks the repo-wide `language`, and `en` is the
floor. The domain surfaces
instead follow the language their documents are authored in, read from
`wiki.domains.language` through `language_code` — so the index always
matches the docs it lists. Every language key holds an ISO 639-1 code;
`language_code` still accepts the free-form names that key used to hold,
for one release, and `LANGUAGE_NAMES` expands a code back into a name
wherever a sender puts a language into a model's prompt.
"""
from __future__ import annotations

import subprocess
import sys
from enum import StrEnum
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import axes as _axes  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The wiki's own settings section, passed to core's language verb so `wiki.language` outranks the root key.
_WIKI_SECTION = "wiki"
# Core CLI verb that owns the language-resolution chain.
_SUB_RESOLVE_LANGUAGE = "resolve-language"
# Core CLI flag naming the caller's own settings section.
_ARG_SECTION = "--section"
# Core CLI flag naming the repository root.
_ARG_CWD = "--cwd"


# ----------------------------------------------------------------------------------------
class LangId(StrEnum):
  """
  The ISO 639-1 codes the wiki carries texts in.

  Attributes:
    EN: English — the floor every lookup falls back to.
    RU: Russian.
  """

  EN = "en"
  RU = "ru"


# One surface key per generated file kind; the agent-authored domain doc and folder
# note fetch their lines through the CLI's `text` verb rather than carrying a copy.
SURFACE_TOPICS = "topics"
SURFACE_DOMAINS_INDEX = "domains-index"
SURFACE_DOMAIN_DOC = "domain-doc"
SURFACE_DOMAIN_FOLDER = "domain-folder"
SURFACE_DOMAIN_SECTION = "domain-section"

# Keys for fixed passages that are not one-line explainers: a whole preamble a
# writer pastes under a title, a message a skill reports back to the operator.
TEXT_TAG_DICTIONARY_INTRO = "tag-dictionary-intro"
TEXT_QUERY_NO_RESULTS = "query-no-results"

EXPLAINERS: dict[tuple[str, str], str] = {
    (SURFACE_TOPICS, LangId.EN): "The topic catalog for this scope. Rebuilt automatically — do not edit by hand.",
    (SURFACE_TOPICS, LangId.RU):
        "Каталог тем этого раздела. Пересобирается автоматически — руками не править.",
    (SURFACE_DOMAINS_INDEX, LangId.EN): "The rule-group index. Rebuilt automatically — do not edit by hand.",
    (SURFACE_DOMAINS_INDEX, LangId.RU):
        "Указатель групп правил. Пересобирается автоматически — руками не править.",
    (SURFACE_DOMAIN_DOC, LangId.EN):
        "A domain knowledge document: principles, mechanics, contracts. Rebuilt automatically — do not edit by hand.",
    (SURFACE_DOMAIN_DOC, LangId.RU):
        "Документ доменного знания: принципы, механика, контракты. Пересобирается автоматически — руками не править.",
    (SURFACE_DOMAIN_FOLDER, LangId.EN):
        "This group's folder: overview and document list. Rebuilt automatically — do not edit by hand.",
    (SURFACE_DOMAIN_FOLDER, LangId.RU):
        "Папка группы: обзор и список документов. Пересобирается автоматически — руками не править.",
    (SURFACE_DOMAIN_SECTION, LangId.EN):
        "A section of the domain tree: the groups it holds. Rebuilt automatically — do not edit by hand.",
    (SURFACE_DOMAIN_SECTION, LangId.RU):
        "Раздел доменного дерева: группы внутри него. Пересобирается автоматически — руками не править.",
}

TEXTS: dict[tuple[str, str], str] = {
    (TEXT_TAG_DICTIONARY_INTRO, LangId.EN): (
        "# Tag values\n"
        "\n"
        "Advisory dictionary of the wiki's canonical tag values, maintained by the wiki tag curator.\n"
        "It records what each value covers so a later classification reuses a settled value instead of\n"
        "coining a synonym beside it. It constrains nothing: a classification may coin a value the\n"
        "dictionary does not list, and the next canon pass records it here."
    ),
    (TEXT_TAG_DICTIONARY_INTRO, LangId.RU): (
        "# Значения тегов\n"
        "\n"
        "Справочный словарь канонических значений тегов вики, который ведёт куратор тегов. Он\n"
        "записывает, что покрывает каждое значение, чтобы следующая классификация переиспользовала\n"
        "уже устоявшееся значение, а не завела рядом синоним. Он ничего не ограничивает:\n"
        "классификация вправе завести значение, которого в словаре нет, и следующий проход канона\n"
        "запишет его сюда."
    ),
    (TEXT_QUERY_NO_RESULTS, LangId.EN): "No wiki material matched this question.",
    (TEXT_QUERY_NO_RESULTS, LangId.RU):
        "Ни один материал вики не подошёл под этот вопрос.",
}


def resolve_language(repo: Path) -> str:
  """
  Resolve the wiki explainer language from the repo settings.

  Guarantees:
    - Always returns a language tag once the core CLI runs successfully with a non-empty answer; a missing,
      unreadable, or malformed settings document resolves to English instead of raising.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.

  Returns:
    The first non-empty value among `wiki.language`, the top-level `language`
    key, and the floor `en`.

  Raises:
    RuntimeError: If the core CLI cannot be resolved, exits with a non-zero status, or answers nothing.
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

  # core owns the chain; the wiki only names its own section
  proc = subprocess.run(
    [
      sys.executable, str(_axes.resolve_core_cli()), _SUB_RESOLVE_LANGUAGE,
      _ARG_SECTION, _WIKI_SECTION, _ARG_CWD, str(repo),
    ],
    capture_output = True, text = True, check = False, encoding = "utf-8",
  )

  # guard: a non-zero exit or an empty answer — surface stdout+stderr instead of inventing a language
  if proc.returncode != 0 or not proc.stdout.strip():
    raise RuntimeError(
      f"lazycortex-core {_SUB_RESOLVE_LANGUAGE} exit={proc.returncode} "
      f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
  return proc.stdout.removesuffix("\n")


# Legacy free-form values `wiki.domains.language` carried before the key held a code.
# Dropped one release after the doctor's rewrite offer; nothing new may be added here.
_LEGACY_NAME_CODES: dict[str, str] = {
    "русский": LangId.RU,
    "russian": LangId.RU,
    "english": LangId.EN,
}

# Display name per code — the expansion a sender applies when it puts a language
# into a model's prompt. There is no reverse reading of these anywhere.
LANGUAGE_NAMES: dict[str, str] = {
    LangId.EN: "English",
    LangId.RU: "русский",
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
    return LangId.EN
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

  text = EXPLAINERS.get((surface, lang)) or EXPLAINERS[(surface, LangId.EN)]
  return f"*{text}*"


def text_keys() -> list[str]:
  """
  List every key `text_for` answers, for a caller that has to validate one.

  Returns:
    The surface keys followed by the fixed-passage keys, each once, in a stable order.
  """
  surfaces = [
    SURFACE_TOPICS, SURFACE_DOMAINS_INDEX, SURFACE_DOMAIN_DOC, SURFACE_DOMAIN_FOLDER, SURFACE_DOMAIN_SECTION,
  ]
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
  if ( key, LangId.EN ) in EXPLAINERS:
    return explainer_line( key, lang )
  return TEXTS.get( ( key, lang ) ) or TEXTS[ ( key, LangId.EN ) ]
