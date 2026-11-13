"""
Canonical per-language texts the wiki emits into generated files.

Every file the wiki engine rebuilds wholesale carries one asterisk-italic
one-liner under its title, in the vault's language, so the operator never has
to guess what the file is or whether hand edits survive (they do not). Longer
fixed passages — a generated file's whole preamble, a message a skill reports
— live here under their own keys.

The wording itself lives in the plugin's locale files, one per language, and
the rest of the wiki reaches it through this module. A writer that needs a
passage asks the CLI's `text` verb for it by key and pastes what comes back;
no agent or skill body carries a copy, so a new language is one locale file
and touches nothing a model reads.

The wiki's language is resolved by core's language verb with the wiki's own
section, so `wiki.language` outranks the repo-wide `language`, and `en` is the
floor. The domain surfaces instead follow the language their documents are
authored in, read from `wiki.domains.language` through `language_code` — so
the index always matches the docs it lists. Every language key holds an
ISO 639-1 code, and `language_name` expands a code back into a name wherever a
sender puts a language into a model's prompt.
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
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import wiki_lockit as _lockit  # noqa: E402  # pylint: disable=import-error,wrong-import-position


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

# Every surface key, in the order the CLI's `text` verb lists them.
SURFACES: tuple[str, ...] = (
  SURFACE_TOPICS, SURFACE_DOMAINS_INDEX, SURFACE_DOMAIN_DOC, SURFACE_DOMAIN_FOLDER, SURFACE_DOMAIN_SECTION,
)

# Every fixed-passage key.
TEXT_KEYS: tuple[str, ...] = ( TEXT_TAG_DICTIONARY_INTRO, TEXT_QUERY_NO_RESULTS )

# Lockit key prefix of a surface's explainer text; the surface key follows it.
EXPLAINER_KEY_PREFIX = "explainers."
# Lockit key prefix of a fixed passage; the passage key follows it.
TEXT_KEY_PREFIX = "texts."
# Lockit key of a language's display name, written in that language.
LANGUAGE_NAME_KEY = "language-name"


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


def language_name(code: str) -> str:
  """
  Expand a language code into the display name a sender puts into a model's prompt.

  Args:
    code: An ISO 639-1 code.

  Returns:
    The language's name written in that language, for a language the wiki carries
    texts in; any other code unchanged.
  """
  # guard: a language the wiki carries no texts in has no name of its own — the code stands in
  if code not in { lang.value for lang in LangId }:
    return code
  return _lockit.Lockit.text(LANGUAGE_NAME_KEY, code)


def language_code(value: str) -> str:
  """
  Narrow a configured language value to an ISO 639-1 code.

  Guarantees:
    - Always returns a non-empty code; an empty or whitespace-only value
      resolves to the `en` floor.

  Args:
    value: The configured language value, an ISO 639-1 code.

  Returns:
    The value stripped and lowercased, so a code passes through unchanged.
  """

  # Contract:
  # The returned code is never empty: an empty or whitespace-only value
  # resolves to the `en` floor rather than to an empty string.

  cleaned = value.strip().lower()

  # guard: nothing configured — `en` is the shipped floor
  if not cleaned:
    return LangId.EN
  return cleaned


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

  Raises:
    KeyError: The surface key has no English explainer text.
  """

  # Contract:
  # Every `SURFACE_*` key MUST render a line in some language: a language tag
  # carrying no text of its own falls back to the English wording.

  return f"*{_lockit.Lockit.text(EXPLAINER_KEY_PREFIX + surface, lang)}*"


def text_keys() -> list[str]:
  """
  List every key `text_for` answers, for a caller that has to validate one.

  Returns:
    The surface keys followed by the fixed-passage keys, each once, in a stable order.
  """
  return list(SURFACES) + sorted(TEXT_KEYS)


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
    KeyError: The key is neither a surface key nor a fixed-passage key.
  """

  # Contract:
  # Every key `text_keys` lists MUST render in some language: a language tag carrying
  # no text of its own falls back to the English wording.

  # a surface renders through the explainer form, which wraps it in asterisks; a passage renders verbatim
  if key in SURFACES:
    return explainer_line(key, lang)
  return _lockit.Lockit.text(TEXT_KEY_PREFIX + key, lang)
