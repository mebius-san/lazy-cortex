from __future__ import annotations

from functools import cache
import json
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# The directory holding one lockit file per language, beside the plugin's `bin/`
_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

# The language every other one falls back to
_FLOOR_LANGUAGE = "en"

# The suffix of a lockit file; its stem is the language code
_LOCALE_SUFFIX = ".json"

# Every lockit file is UTF-8
_ENCODING = "utf-8"


# ----------------------------------------------------------------------------------------
class Lockit:
  """
  Source of the plugin's user-visible strings per language.

  Answers the text shown to the user for a string key in a requested language, with English as the fallback
  language. Callers format any placeholders themselves.

  Guarantees:
    - Strings are returned verbatim, with placeholders left unformatted.
    - A key that English holds is answered for every language, including a language with no strings of its own.
  """

  # opt: the locale files do not change while the process runs, so each language's file is read once
  @classmethod
  @cache
  def _load_table(cls, lang: str) -> dict[str, str]:
    """
    Load the strings one language holds.

    Args:
      lang: Language code whose strings are loaded.

    Returns:
      The mapping of string key to string; empty when the language has no lockit file.
    """
    path = _LOCALES_DIR / f"{lang}{_LOCALE_SUFFIX}"

    # guard: a language without a file has no strings of its own
    if not path.is_file():
      return {}

    # the file is one flat object of key -> string
    # waiver: the annotated local narrows the `Any` that `json.loads` returns, which mypy refuses to return as is
    table: dict[str, str] = json.loads(path.read_text(encoding = _ENCODING))
    return table


  @classmethod
  def text(cls, key: str, lang: str) -> str:
    """
    Return the string for a key in a language, falling back to English.

    Guarantees:
      - English defines the key set: a key absent from the English file raises `KeyError` naming the key, whatever
        the asked language's file holds.
      - The asked language's own string wins when its file exists and holds the key.
      - A language with no file, or a key its file lacks, gives the English string.
      - The string comes back verbatim, with placeholders unformatted.

    Args:
      key: String key to look up.
      lang: Language code the string is wanted in.

    Returns:
      The string verbatim, with placeholders unformatted.

    Raises:
      KeyError: If English holds no string for the key.
    """

    # Contract:
    # English defines the key set: a key absent from the English file MUST raise `KeyError` naming the key,
    # whatever the asked language's file holds.
    # The asked language's own string MUST win when its file exists and holds the key.
    # A language with no file, or a key its file lacks, MUST give the English string.
    # The string MUST come back verbatim, with placeholders unformatted.

    english = cls._load_table(_FLOOR_LANGUAGE)

    # guard: English defines the key set — a key it lacks is refused whatever the asked language holds
    if key not in english:
      raise KeyError(f"lockit key not found: {key}")

    # the asked language's own string wins; a language with no file, or without the key, gives the English one
    return cls._load_table(lang).get(key, english[key])
