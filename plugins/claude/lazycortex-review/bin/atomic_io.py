"""Crash-safe replacement of a document's text on disk."""
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import parser as _parser  # pylint: disable=import-error,deprecated-module

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# permission bits a fresh file gets before the process umask is applied
_DEFAULT_FILE_MODE = 0o666

# the temp file's name tail, so a crash leftover is recognisable beside its target
_TMP_SUFFIX = ".tmp"

# documents are always stored as UTF-8
_ENCODING = "utf-8"

# a line feed not preceded by a carriage return
_BARE_LF = re.compile(r"(?<!\r)\n")

# the two line endings a document is stored with, and patterns matching each
_LF = "\n"
_CRLF = "\r\n"
_LF_RE = re.compile(_LF)
_CRLF_RE = re.compile(_CRLF)

# the temp file is opened for text writing
_WRITE_MODE = "w"


def _current_umask() -> int:
  """
  Read the process umask without changing it.

  Returns:
    The umask currently in effect.
  """
  # the umask is only readable by setting it, so set it and put it straight back
  mask = os.umask(0)
  os.umask(mask)
  return mask


def read_text(path: Path) -> str:
  """
  Read the whole content of `path` as UTF-8 with no newline translation.

  `Path.read_text()` folds `\r\n` into `\n`, so a read-modify-write through it silently turns a
  CRLF document into LF; every read that feeds `write_text_atomic` goes through here instead.

  Args:
    path: The file to read.

  Returns:
    The file's text exactly as stored, line endings included.
  """
  with open(path, encoding = _ENCODING, newline = "") as handle:
    return handle.read()


def keep_line_endings(original: str, text: str) -> str:
  """
  Give `text` the line ending of the document it was derived from.

  When every line break of `original` outside fenced code blocks is CRLF, every bare `\n` in
  `text` outside its fenced code blocks becomes `\r\n`, so lines inserted as LF never leave the
  file with mixed endings; fenced lines keep their bytes. Any other `original` (LF, mixed outside
  fences, or single-line) leaves `text` unchanged.

  Args:
    original: The document text as read from disk.
    text: The new document text about to be written.

  Returns:
    `text`, CRLF outside its fenced code blocks when `original` was.
  """
  # guard: only a document that is CRLF on every line outside fences dictates CRLF
  if _parser.line_ending(original) != "\r\n":
    return text
  return _parser.sub_outside_fences(_BARE_LF, "\r\n", text)


def to_lf(text: str) -> tuple[str, str]:
  """
  Turn a document read from disk into the LF text every edit works on, plus its line ending.

  Guarantees:
    - `restore_ending(*to_lf(text))` reproduces `text` byte-for-byte.
    - A document that is not CRLF on every line outside fenced code blocks comes back unchanged.
    - Fenced code blocks keep their bytes.

  Args:
    text: The document text as read from disk.

  Returns:
    A `(lf_text, ending)` tuple: `text` with every CRLF outside fenced code blocks turned into LF
    when the document is CRLF there, and the line ending `restore_ending` writes it back with.
  """

  # Contract:
  # `restore_ending(*to_lf(text))` MUST reproduce `text` byte-for-byte; a document that is not
  # CRLF on every line outside fences comes back unchanged, and fenced code blocks keep their bytes.

  ending = _parser.line_ending(text)

  # guard: only a document that is CRLF on every line outside fences is converted
  if ending != _CRLF:
    return text, ending
  return _parser.sub_outside_fences(_CRLF_RE, _LF, text), ending


def restore_ending(text: str, ending: str) -> str:
  """
  Give LF text produced by an edit the line ending of the document it came from.

  Args:
    text: The edited document text, LF outside its fenced code blocks.
    ending: The line ending `to_lf` returned for the document.

  Returns:
    `text` with every LF outside fenced code blocks turned into CRLF when `ending` is CRLF, else
    `text` unchanged.
  """
  # guard: an LF or mixed document is written back as the edit left it
  if ending != _CRLF:
    return text
  return _parser.sub_outside_fences(_LF_RE, _CRLF, text)


def to_fence_ending(text: str, ending: str) -> str:
  """
  Give the fenced code blocks of LF text the document's line ending, leaving the rest as LF.

  An agent's payload lands in the document whole: its fenced blocks take the document's ending
  the way `restore_ending` gives it to every other line, which never reaches inside a fence.

  Args:
    text: LF text, typically an agent's payload.
    ending: The document's line ending, as `to_lf` returned it.

  Returns:
    `text` with every LF inside its fenced code blocks turned into `ending`.
  """
  return "".join(
      chunk.text.replace(_LF, ending) if chunk.fenced else chunk.text for chunk in _parser.split_fenced(text)
  )


def write_text_atomic(path: Path, text: str) -> None:
  """
  Replace the whole content of `path` with `text` so a reader never sees a partial write.

  Guarantees:
    - When the call raises, the file at `path` is left exactly as it was before the call.
    - An existing file keeps its permission bits.
    - When `path` is a symlink, the file it points at is replaced and the link itself is kept.
    - `text` is written byte-for-byte as UTF-8, with no newline translation.

  Args:
    path: The file to write; it may not exist yet, and it may be a symlink.
    text: The complete new content of the file.
  """

  # Contract:
  # When the call raises, the file at `path` MUST be left exactly as it was before the call;
  # an existing file MUST keep its permission bits; a symlink at `path` MUST survive, with the
  # file it points at replaced; `text` MUST land byte-for-byte as UTF-8, untranslated.

  # a symlink is written through: the temp file sits beside the real target, never the link
  target = Path(os.path.realpath(path))
  try:
    mode = stat.S_IMODE(target.stat().st_mode)
  except FileNotFoundError:
    mode = _DEFAULT_FILE_MODE & ~_current_umask()

  # write and flush to disk beside the target, then swap it in with one rename
  fd, tmp_name = tempfile.mkstemp(dir = target.parent, prefix = f".{target.name}.", suffix = _TMP_SUFFIX)
  try:
    with os.fdopen(fd, _WRITE_MODE, encoding = _ENCODING, newline = "") as handle:
      handle.write(text)
      handle.flush()
      os.fsync(handle.fileno())
    os.chmod(tmp_name, mode)
    os.replace(tmp_name, target)
  except BaseException:
    # a failed write leaves no temp file behind and the target untouched
    Path(tmp_name).unlink(missing_ok = True)
    raise
