from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# File encoding used for every read and write.
_ENCODING = "utf-8"

# Line endings a file can be read with; the text handed to callers always uses the first.
_LF = "\n"
_CRLF = "\r\n"

# Permission bits a freshly created file starts from before the umask is applied.
_NEW_FILE_MODE = 0o666

# Suffix of the temporary file a write stages its content in.
_TMP_SUFFIX = ".tmp"

# Binary write mode for the staged content — line endings are already applied by hand.
_WRITE_BINARY = "wb"

# Binary read-write mode for the in-place fallback — the existing file is overwritten, never recreated.
_UPDATE_BINARY = "r+b"

# Byte-order mark some editors put at the head of a UTF-8 file; callers never see it.
_BOM = "\ufeff"


# ----------------------------------------------------------------------------------------
class TextFile:
  """
  One UTF-8 text file read with normalised line endings and written back atomically.

  Guarantees:
    - A write never leaves a partially written file: readers see either the old or the new content,
      except when the file's directory refuses a temporary file, where a writable existing file is
      instead overwritten in place. A failed in-place write restores the file's previous bytes
      before the error propagates, but a concurrent reader may still observe a partial write while
      it is in progress, and a process crash mid-write can still leave partial content. A file that
      does not yet exist still fails rather than falling back.
    - A symlinked path stays a symlink, and an existing file keeps its own permission bits.
    - A file read as uniformly CRLF is written back as CRLF, one read as LF is written back as LF, and
      one read with mixed line endings is written back with its per-line endings untouched.
    - The text handed to callers never carries a leading byte-order mark; a write restores the mark
      only for a file that was last read with one.
  """

  def __init__(self, *, path: Path) -> None:
    """
    Bind the helper to one file path.

    Args:
      path: Path of the file to read or write; it need not exist yet.
    """
    # the file this helper reads and replaces
    self._path = Path(path)

    # the line ending a write restores; LF until a read finds CRLF
    self._newline = _LF

    # the byte-order mark a write restores; empty until a read finds one
    self._bom = ""

  @property
  def newline(self) -> str:
    """
    Line ending the next write uses: the one the last read found, LF by default.
    """
    return self._newline

  def read(self) -> str:
    """
    Read the file and return its text, normalised to LF when uniformly CRLF, with a leading byte-order mark removed.

    Guarantees:
      - A file whose every line ends in CRLF comes back with every CRLF replaced by LF; an LF file
        comes back unchanged; a file with mixed line endings comes back exactly as it is, so its
        per-line endings survive untouched into a later write.
      - The returned text never carries a leading byte-order mark, whether or not the file had one.

    Returns:
      The file text without a leading byte-order mark; a uniformly CRLF file comes back with every
      CRLF replaced by LF, and a file with mixed line endings comes back unchanged.
    """

    # Contract:
    # The returned text NEVER carries a leading byte-order mark; a write restores the mark only for a
    # file that was read with one.

    raw = self._path.read_bytes().decode(_ENCODING)

    # remember a leading byte-order mark so a write can restore it
    self._bom = _BOM if raw.startswith(_BOM) else ""
    raw = raw[len(self._bom):]

    # Contract:
    # A file whose every line ends in CRLF is returned with every CRLF replaced by LF; an LF file is
    # returned unchanged; a file with MIXED line endings is returned exactly as it is, never partially
    # converted — its per-line endings survive untouched into a later write.

    # a CRLF count equal to the LF count means every line ends in CRLF
    crlf = raw.count(_CRLF)
    self._newline = _CRLF if crlf and crlf == raw.count(_LF) else _LF

    # guard: an LF or mixed file is handed over exactly as it is
    if self._newline == _LF:
      return raw
    return raw.replace(_CRLF, _LF)

  def write(self, text: str) -> None:
    """
    Replace the file's content with `text` in one atomic step.

    Guarantees:
      - A write is atomic whenever the file's directory admits a temporary file: a reader sees either
        the old content or the new content, never a partial write, and a failed write leaves no
        temporary file behind. When the directory refuses a temporary file, a writable existing file
        is instead overwritten in place; a failed in-place write restores the file's previous bytes
        before the error propagates, but this path is not atomic — a concurrent reader may still
        observe a partial write while it is in progress, and a process crash mid-write can still
        leave partial content. A file that does not yet exist still fails rather than falling back.
      - A symlinked path stays a symlink, and an existing file keeps its own permission bits.
      - The write restores the line ending established by the last read: a file read as uniformly
        CRLF is written back as CRLF; one read as LF, or with mixed endings, is written back exactly
        as its text already stands, never converted wholesale.
      - The write restores the leading byte-order mark the file was last read with; a file read
        without one is written without one.

    Args:
      text: New content with LF line endings.
    """

    # Contract:
    # When the file's directory admits a temporary file, the replace is atomic: a reader sees either the
    # old content or the new one, never a partial write, and a failed write leaves the old file and no
    # temporary file behind. When the directory refuses a temporary file, a writable existing file is
    # instead overwritten in place, keeping its inode and mode; a failed in-place write restores the
    # file's previous bytes before the exception propagates. This in-place path is NOT atomic — a
    # concurrent reader may observe a partial write while it is in progress, and a process crash
    # mid-write, as opposed to a raised exception, can still leave partial content. A file that does
    # not yet exist in such a directory still fails rather than falling back.

    # Contract:
    # A symlinked path stays a symlink: the link's real target is what gets replaced, and an existing
    # file keeps its permission bits.

    # Contract:
    # A write restores the line ending established by the last read: a file read as uniformly CRLF is
    # written back with every line ending in CRLF; a file read as LF, or with MIXED endings, is written
    # back exactly as its text already stands — never converted wholesale.

    # Contract:
    # A write restores the leading byte-order mark the file was last read with; a file read without one
    # is written without one.

    target = Path(os.path.realpath(self._path))
    data = (self._bom + (text if self._newline == _LF else text.replace(_LF, self._newline))).encode(_ENCODING)
    mode = self._mode_for(target)

    # the temporary file lives beside the target so the final rename never crosses a filesystem
    try:
      fd, tmp_name = tempfile.mkstemp(dir = target.parent, prefix = f".{target.name}.", suffix = _TMP_SUFFIX)
    except PermissionError:
      # guard: a missing file cannot be overwritten in place — the refusal stands
      if not target.is_file():
        raise
      self._write_in_place(target, data)
      return
    try:
      with os.fdopen(fd, _WRITE_BINARY) as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
      os.chmod(tmp_name, mode)
      os.replace(tmp_name, target)
    except BaseException:
      Path(tmp_name).unlink(missing_ok = True)
      raise

  @staticmethod
  def _write_in_place(target: Path, data: bytes) -> None:
    """
    Overwrite an existing file's content in place, for a directory that refuses a temporary file.

    Args:
      target: Real path of the existing file to overwrite.
      data: Encoded bytes of the new content.

    Raises:
      OSError: If the new content cannot be written; the original bytes are back on disk first.
    """
    original = target.read_bytes()
    try:
      # write first, then cut the old tail, then flush to disk — the file keeps its inode and mode
      with open(target, _UPDATE_BINARY) as handle:
        handle.write(data)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
    except BaseException:
      # a failed write (full disk, file-size limit) must not leave a truncated file: put the old bytes back
      with open(target, _UPDATE_BINARY) as handle:
        handle.write(original)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
      raise

  @staticmethod
  def _mode_for(target: Path) -> int:
    """
    Return the permission bits the replaced file should carry.

    Args:
      target: Real path of the file about to be replaced.

    Returns:
      The existing file's permission bits, or the default new-file mode under the current umask.
    """
    # guard: an existing file keeps its own permission bits
    if target.exists():
      return stat.S_IMODE(target.stat().st_mode)

    # the umask can only be read by setting it, so it is restored at once
    umask = os.umask(0)
    os.umask(umask)
    return _NEW_FILE_MODE & ~umask
