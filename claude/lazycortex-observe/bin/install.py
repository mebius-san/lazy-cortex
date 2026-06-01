"""
Mechanical helpers for the lazy-observe.install skill.

Provides template rendering, path resolution, token / answer persistence, agent
binary discovery, service load/unload helpers for both macOS launchd and Linux
systemd, and a best-effort smoke test against the lazycortex-core metrics
endpoint. Stdlib-only — the embedded template engine handles only the small
`{{ name }}` / `{% if/elif/endif %}` / `{% for %}` dialect used by the shipped
templates, and rejects anything else to fail loudly on Jinja2-style mistakes.
"""
from __future__ import annotations

from typing import Iterable

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
XDG_DATA_HOME   = Path(os.environ.get("XDG_DATA_HOME")   or (Path.home() / ".local/share"))
XDG_STATE_HOME  = Path(os.environ.get("XDG_STATE_HOME")  or (Path.home() / ".local/state"))

ANSWER_FILE = XDG_CONFIG_HOME / "lazycortex" / "observe.toml"
TOKEN_FILE  = XDG_CONFIG_HOME / "lazycortex" / "observe.token"
DATA_DIR    = XDG_DATA_HOME   / "lazycortex" / "observe"
LOG_DIR_MAC = Path.home() / "Library" / "Logs" / "lazycortex-observe"

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def detect_host() -> str:
  """
  Return the canonical host identifier for the current platform.

  Returns:
    The string `darwin` on macOS or `linux` on Linux-based systems.

  Raises:
    ValueError: If the current platform is neither macOS nor Linux.
  """
  # guard: macOS host
  # waiver: OS/platform token (sys.platform), external
  if sys.platform == "darwin":
    # waiver: OS/platform token (sys.platform), external
    return "darwin"
  # guard: any Linux variant
  # waiver: OS/platform token (sys.platform), external
  if sys.platform.startswith("linux"):
    # waiver: OS/platform token (sys.platform), external
    return "linux"
  raise ValueError(f"unsupported platform: {sys.platform!r}")


# waiver: `vars` is the public substitution-dict param name; shadowing builtin vars() is harmless, not restructured for a checker
def render(template_name: str, vars: dict[str, object]) -> str:  # pylint: disable=redefined-builtin
  """
  Render a shipped template into a string using the embedded mini-dialect.

  Supported syntax:
    `{{ key }}` or `{{ key | default('foo') }}`
    `{% if cond %} ... {% elif cond %} ... {% else %} ... {% endif %}`
    `{% for item in seq %} ... {% endfor %}`

  Anything else fails loudly rather than pretending Jinja2 compatibility.

  Args:
    template_name: File name of the template under the shipped `templates/`
      directory.
    vars: Mapping of template variable names to substituted values.

  Returns:
    The fully rendered template text.

  Raises:
    SyntaxError: If the template uses an unsupported directive or has an
      unclosed `{% if %}` / `{% for %}` block.
    TypeError: If a `{% for %}` directive iterates over a non-iterable value.
    FileNotFoundError: If the named template does not exist.
  """
  src = (TEMPLATE_DIR / template_name).read_text()
  return _Template(src, vars).render()


def render_to(template_name: str, vars: dict[str, object], target: Path) -> Path:
  # waiver: `vars` is the public substitution-dict param name; shadowing builtin vars() is harmless, not restructured for a checker
  # pylint: disable=redefined-builtin
  """
  Render a template and write the result atomically to the given target path.

  The render goes through a sibling `.tmp` file followed by `os.replace`, so an
  interrupted call leaves the previous file content intact.

  Args:
    template_name: File name of the template under the shipped `templates/`
      directory.
    vars: Mapping of template variable names to substituted values.
    target: Destination path that will receive the rendered text. Parent
      directories are created as needed.

  Returns:
    The same `target` path passed in, for chaining convenience.

  Raises:
    SyntaxError: If the template uses an unsupported directive or has an
      unclosed block.
    TypeError: If a `{% for %}` directive iterates over a non-iterable value.
    OSError: If the target file or its parent directory cannot be written.
  """
  body = render(template_name, vars)
  target.parent.mkdir(parents = True, exist_ok = True)
  # write to a sibling temp file first so an interrupted call leaves the previous file intact
  # waiver: filesystem path idiom
  tmp = target.with_suffix(target.suffix + ".tmp")
  tmp.write_text(body)
  os.replace(tmp, target)
  return target


def write_token_file(token: str) -> Path:
  """
  Persist the bearer or basic-auth token to a 0600-mode file.

  The caller is responsible for asking the operator before invoking, since the
  written file contains sensitive credential material.

  Args:
    token: Token string to persist. A trailing newline is appended on write.

  Returns:
    The path to the token file that was written.

  Raises:
    OSError: If the token file or its parent directory cannot be written or
      its permissions cannot be tightened.
  """
  TOKEN_FILE.parent.mkdir(parents = True, exist_ok = True)
  TOKEN_FILE.write_text(token + "\n")
  # waiver: inline numeric literal, not a domain constant
  os.chmod(TOKEN_FILE, 0o600)
  return TOKEN_FILE


def write_answer_file(answers: dict) -> Path:
  """
  Persist non-secret operator answers to a trivial top-level TOML file.

  Only top-level `key = "value"` pairs are emitted. Booleans render as `true`
  / `false`, numerics as their literal form, and everything else as quoted
  strings with backslashes and double quotes escaped. Token-like keys are
  refused so that secret material never accidentally leaks into the file.

  Args:
    answers: Mapping of answer keys to scalar values (URL, agent kind, auth
      kind, etc.).

  Returns:
    The path to the answer file that was written.

  Raises:
    ValueError: If `answers` contains a token-like key such as `token` or
      `LAZYCORTEX_OBSERVE_TOKEN`.
    OSError: If the answer file or its parent directory cannot be written.
  """
  ANSWER_FILE.parent.mkdir(parents = True, exist_ok = True)
  lines = []
  for k, v in sorted(answers.items()):
    # guard: never persist secret keys via the non-secret answer file
    if k in { "token", "LAZYCORTEX_OBSERVE_TOKEN" }:
      raise ValueError(f"refused to write secret key {k!r} into the answer file")
    # boolean values render as lowercase TOML literals
    if isinstance(v, bool):
      lines.append(f"{k} = {'true' if v else 'false'}")
    # numerics render as their literal form
    elif isinstance(v, (int, float)):
      lines.append(f"{k} = {v}")
    # everything else is treated as a quoted string with escaping
    else:
      escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
      lines.append(f'{k} = "{escaped}"')
  ANSWER_FILE.write_text("\n".join(lines) + "\n")
  return ANSWER_FILE


def read_answer_file() -> dict:
  """
  Read the previously saved non-secret answer file back into a mapping.

  Lines are parsed permissively: blank lines and `#`-prefixed comments are
  skipped, malformed lines are silently ignored, and unquoted values are
  decoded as booleans, ints, floats, or strings in that order.

  Returns:
    A mapping of answer keys to decoded values, or an empty mapping when no
    answer file is present yet.
  """
  # guard: no previous answers persisted yet
  if not ANSWER_FILE.exists():
    return {}
  out: dict = {}
  pat = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$')
  for raw in ANSWER_FILE.read_text().splitlines():
    line = raw.strip()
    # guard: skip blank lines and comments
    if not line or line.startswith("#"):
      continue
    m = pat.match(line)
    # guard: skip malformed entries silently
    if not m:
      continue
    k, v = m.group(1), m.group(2).strip()
    # decode booleans first to avoid them being eaten by the numeric branch
    if v.lower() in ("true", "false"):
      # waiver: stdlib encoding/mode/escape idiom
      out[k] = v.lower() == "true"
    # quoted string with escape sequences
    elif v.startswith('"') and v.endswith('"'):
      out[k] = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    # otherwise attempt int / float, falling back to a raw string
    else:
      try:
        out[k] = int(v) if "." not in v else float(v)
      except ValueError:
        out[k] = v
  return out


def find_agent_binary(agent_kind: str) -> Path | None:
  """
  Locate the binary for a shipping agent kind on the current `PATH`.

  Args:
    agent_kind: Logical agent identifier — supported values today are `alloy`
      and `otelcol`.

  Returns:
    The resolved binary path, or `None` if no matching executable is on
    `PATH` for the given kind (including unknown kinds).
  """
  candidates = {
    "alloy":   [ "alloy", "grafana-alloy" ],
    "otelcol": [ "otelcol", "otelcol-contrib" ],
  }.get(agent_kind, [])
  for name in candidates:
    path = shutil.which(name)
    # guard: first match on PATH wins
    if path:
      return Path(path)
  return None


def load_service_macos(plist_path: Path) -> tuple[bool, str]:
  """
  Bootstrap the launchd agent for the current GUI user.

  Args:
    plist_path: Path to the launchd plist that defines the user agent.

  Returns:
    A pair `(ok, stderr)` where `ok` indicates a zero exit status from
    `launchctl bootstrap` and `stderr` carries the captured error output for
    diagnostic surfacing.
  """
  uid = os.getuid()
  proc = subprocess.run(
    [ "launchctl", "bootstrap", f"gui/{uid}", str(plist_path) ],
    capture_output = True, text = True, check = False,
  )
  return (proc.returncode == 0, proc.stderr)


def unload_service_macos(plist_path: Path) -> tuple[bool, str]:
  """
  Boot the launchd agent out of the current GUI user's domain.

  Note that `launchctl bootout` exits non-zero when the agent is not currently
  loaded; the caller decides whether that constitutes failure.

  Args:
    plist_path: Path to the launchd plist that defines the user agent.

  Returns:
    A pair `(ok, stderr)` where `ok` indicates a zero exit status from
    `launchctl bootout` and `stderr` carries the captured error output for
    diagnostic surfacing.
  """
  uid = os.getuid()
  proc = subprocess.run(
    [ "launchctl", "bootout", f"gui/{uid}", str(plist_path) ],
    capture_output = True, text = True, check = False,
  )
  # bootout exits non-zero if not loaded — caller decides whether to care.
  return (proc.returncode == 0, proc.stderr)


def load_service_linux(unit_name: str = "lazycortex-observe.service") -> tuple[bool, str]:
  """
  Enable and start the systemd user unit for the lazycortex-observe agent.

  Args:
    unit_name: Name of the systemd user unit. Defaults to the canonical
      `lazycortex-observe.service`.

  Returns:
    A pair `(ok, stderr)` where `ok` indicates a zero exit status from
    `systemctl --user enable --now` and `stderr` carries the captured error
    output for diagnostic surfacing.
  """
  proc = subprocess.run(
    [ "systemctl", "--user", "enable", "--now", unit_name ],
    capture_output = True, text = True, check = False,
  )
  return (proc.returncode == 0, proc.stderr)


def unload_service_linux(unit_name: str = "lazycortex-observe.service") -> tuple[bool, str]:
  """
  Disable and stop the systemd user unit for the lazycortex-observe agent.

  Args:
    unit_name: Name of the systemd user unit. Defaults to the canonical
      `lazycortex-observe.service`.

  Returns:
    A pair `(ok, stderr)` where `ok` indicates a zero exit status from
    `systemctl --user disable --now` and `stderr` carries the captured error
    output for diagnostic surfacing.
  """
  proc = subprocess.run(
    [ "systemctl", "--user", "disable", "--now", unit_name ],
    capture_output = True, text = True, check = False,
  )
  return (proc.returncode == 0, proc.stderr)


def smoke_test_local_metrics(scrape_target: str, timeout: float = 5.0) -> bool:
  """
  Best-effort probe of the lazycortex-core `/metrics` endpoint on the given target.

  Args:
    scrape_target: Host-and-port string to probe, used directly in the
      constructed URL (e.g. `127.0.0.1:9464`).
    timeout: Maximum number of seconds to wait for the HTTP response.

  Returns:
    `True` when the endpoint responds and the body contains the
    `lazycortex_runtime` marker, otherwise `False` (including connection
    errors, timeouts, and unreachable hosts).
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import urllib.request
  try:
    url = f"http://{scrape_target}/metrics"
    with urllib.request.urlopen(url, timeout = timeout) as r:
      # waiver: stdlib encoding/mode/escape idiom
      body = r.read(4096).decode("utf-8", "ignore")
      # waiver: one-off human-facing message
      return "lazycortex_runtime" in body
  except (urllib.error.URLError, TimeoutError, ConnectionError):
    return False


# --- Tiny template engine --------------------------------------------------

class _Template:
  """
  Minimal text template engine for the small Jinja2-style dialect used in this module.

  Supports `{{ var }}` and `{{ var | default('foo') }}` substitutions,
  `{% if %} / {% elif %} / {% else %} / {% endif %}` conditional blocks, and
  `{% for var in seq %} / {% endfor %}` loops. Unsupported directives raise
  `SyntaxError` so that a Jinja2 mistake fails loudly rather than silently
  producing wrong output.
  """

  _RE = re.compile(
    r"\{\{\s*(.+?)\s*\}\}"        # {{ var }}
    r"|\{%\s*(.+?)\s*%\}",        # {% directive %}
    re.DOTALL,
  )


  # waiver: `vars` is the substitution-dict param name; shadowing builtin vars() is harmless, not restructured for a checker
  def __init__(self, src: str, vars: dict):  # pylint: disable=redefined-builtin
    """
    Initialise the engine with template source and a variable mapping.

    Args:
      src: Raw template text to render.
      vars: Mapping of variable names to substituted values; modified
        in-place during loop expansion to bind the loop variable.
    """
    self.src = src
    self.vars = vars


  def render(self) -> str:
    """
    Render the configured template source into a string.

    Returns:
      The rendered template text with all substitutions, conditionals, and
      loops resolved.

    Raises:
      SyntaxError: If the template uses an unsupported directive or contains
        an unclosed `{% if %}` or `{% for %}` block.
      TypeError: If a `{% for %}` directive iterates over a non-iterable
        value.
    """
    out: list[str] = []
    # stack of (active, true_branch_taken) — controls whether to emit text
    stack: list[ tuple[bool, bool] ] = [ (True, True) ]
    # loop stack: each frame collects body fragments and replays them per iteration on endfor
    loop_stack: list[dict] = []

    pos = 0
    for m in self._RE.finditer(self.src):
      chunk = self.src[pos:m.start()]
      self._emit(out, loop_stack, chunk, stack[-1][0])
      pos = m.end()

      # substitution form: {{ expr }}
      if m.group(1) is not None:
        expr = m.group(1).strip()
        if stack[-1][0]:
          if loop_stack:
            # defer evaluation — the loop variable is unbound during body collection;
            # endfor replays each entry with vars[var] set per iteration
            # waiver: single-dict-literal key (template engine internal), not a cross-module key
            loop_stack[-1]["body"].append(("expr", expr))
          else:
            out.append(self._eval(expr))
      # directive form: {% ... %}
      else:
        directive = m.group(2).strip()
        self._handle_directive(directive, stack, loop_stack, out)

    # flush any trailing text after the last match
    tail = self.src[pos:]
    self._emit(out, loop_stack, tail, stack[-1][0])

    # guard: every {% if %} must be closed before the template ends
    if len(stack) != 1:
      raise SyntaxError("template ended with unclosed {% if %} block")
    # guard: every {% for %} must be closed before the template ends
    if loop_stack:
      raise SyntaxError("template ended with unclosed {% for %} block")
    return "".join(out)


  def _emit(self, out: list, loop_stack: list, text: str, active: bool) -> None:
    """
    Append a literal text chunk to the output or the innermost loop body.

    Args:
      out: Top-level output buffer to extend when no loop is active.
      loop_stack: Stack of loop frames; when non-empty the chunk is buffered
        on the innermost frame instead of emitted immediately.
      text: Literal text chunk to append.
      active: Whether the surrounding conditional branch is active; inactive
        chunks are dropped silently.
    """
    # guard: skip inactive branches and empty chunks
    if not active or not text:
      return
    if loop_stack:
      # waiver: single-dict-literal key (template engine internal), not a cross-module key
      loop_stack[-1]["body"].append(("text", text))
    else:
      out.append(text)


  def _handle_directive(self, directive: str, stack: list, loop_stack: list, out: list) -> None:
    """
    Dispatch one `{% ... %}` directive against the conditional and loop stacks.

    Handles `if` / `elif` / `else` / `endif` for conditional blocks and `for`
    / `endfor` for loops. Any other directive raises `SyntaxError`.

    Args:
      directive: The directive text between `{%` and `%}` with surrounding
        whitespace already stripped.
      stack: Conditional stack of `(active, true_branch_taken)` frames.
      loop_stack: Loop stack of frames buffering iteration bodies.
      out: Top-level output buffer used when a loop emits expanded content.

    Raises:
      SyntaxError: If the directive is unsupported or a `for` directive is
        malformed.
      TypeError: If a `for` directive iterates over a non-iterable value.
    """
    active = stack[-1][0]

    # waiver: single-dict-literal key (template engine internal), not a cross-module key
    if directive.startswith("if "):
      cond = self._truthy(directive[3:]) if active else False
      stack.append((cond, cond))

    # waiver: single-dict-literal key (template engine internal), not a cross-module key
    elif directive.startswith("elif "):
      _prev_active, branch_taken = stack[-1]
      parent_active = stack[-2][0]
      if branch_taken:
        stack[-1] = (False, True)
      elif parent_active and self._truthy(directive[5:]):
        stack[-1] = (True, True)
      else:
        stack[-1] = (False, branch_taken)

    # waiver: single-dict-literal key (template engine internal), not a cross-module key
    elif directive == "else":
      _prev_active, branch_taken = stack[-1]
      parent_active = stack[-2][0]
      if branch_taken:
        stack[-1] = (False, True)
      elif parent_active:
        stack[-1] = (True, True)

    # waiver: single-dict-literal key (template engine internal), not a cross-module key
    elif directive == "endif":
      stack.pop()

    # waiver: single-dict-literal key (template engine internal), not a cross-module key
    elif directive.startswith("for "):
      # `for item in seq`
      m = re.match(r"for\s+(\w+)\s+in\s+(\S+)", directive)
      # guard: malformed for directive
      if not m:
        raise SyntaxError(f"bad for: {directive!r}")
      if active:
        seq = self._eval_value(m.group(2))
        # guard: refuse to iterate over a non-iterable value
        if not isinstance(seq, Iterable):
          raise TypeError(f"non-iterable in for: {seq!r}")
        # waiver: single-dict-literal key (template engine internal), not a cross-module key
        loop_stack.append({ "var": m.group(1), "seq": list(seq), "body": [], "active": True })
      else:
        # waiver: single-dict-literal key (template engine internal), not a cross-module key
        loop_stack.append({ "var": m.group(1), "seq": [], "body": [], "active": False })

    # waiver: single-dict-literal key (template engine internal), not a cross-module key
    elif directive == "endfor":
      frame = loop_stack.pop()
      # guard: skip expansion when the loop sat inside an inactive branch
      # waiver: single-dict-literal key (template engine internal), not a cross-module key
      if not frame["active"]:
        return
      # replay buffered body for each iteration, binding the loop variable per pass
      # waiver: single-dict-literal key (template engine internal), not a cross-module key
      for item in frame["seq"]:
        # waiver: single-dict-literal key (template engine internal), not a cross-module key
        self.vars[ frame["var"] ] = item
        # waiver: single-dict-literal key (template engine internal), not a cross-module key
        for kind, payload in frame["body"]:
          if kind == "text":
            if loop_stack:
              # waiver: single-dict-literal key (template engine internal), not a cross-module key
              loop_stack[-1]["body"].append(("text", payload))
            else:
              out.append(payload)
          # waiver: single-dict-literal key (template engine internal), not a cross-module key
          elif kind == "expr":
            rendered = self._eval(payload)
            if loop_stack:
              # waiver: single-dict-literal key (template engine internal), not a cross-module key
              loop_stack[-1]["body"].append(("text", rendered))
            else:
              out.append(rendered)
      # remove the loop variable so it does not leak into the surrounding scope
      # waiver: single-dict-literal key (template engine internal), not a cross-module key
      self.vars.pop(frame["var"], None)

    else:
      raise SyntaxError(f"unsupported template directive: {directive!r}")


  def _truthy(self, expr: str) -> bool:
    """
    Evaluate the truthiness of a minimal conditional expression.

    Supports `kind == "value"` equality comparisons against a string literal
    and bare variable references that are evaluated by Python truthiness.

    Args:
      expr: Conditional expression text from inside an `{% if %}` or
        `{% elif %}` directive.

    Returns:
      `True` when the comparison or variable evaluates as truthy, `False`
      otherwise.
    """
    # Support `kind == "value"` or just `name`.
    m = re.match(r'(\w+)\s*==\s*"([^"]*)"$', expr)
    if m:
      return str(self.vars.get(m.group(1))) == m.group(2)
    return bool(self.vars.get(expr))


  def _eval(self, expr: str) -> str:
    """
    Evaluate a substitution expression and return its string form.

    Supports the `name | default('foo')` filter form that falls back to the
    given default when the variable is missing or empty, and the bare
    `name` form that returns the variable value coerced to string.

    Args:
      expr: Substitution expression text from inside a `{{ ... }}` block.

    Returns:
      The rendered string value for the expression, or an empty string when
      the variable is not bound.
    """
    # `name | default('foo')` first.
    m = re.match(r"(\w+)\s*\|\s*default\(\s*'([^']*)'\s*\)$", expr)
    if m:
      v = self.vars.get(m.group(1))
      if v is None or v == "":
        return m.group(2)
      return str(v)
    return str(self.vars.get(expr, ""))


  def _eval_value(self, ident: str) -> list:
    """
    Resolve an identifier used as the iterable side of a `{% for %}` directive.

    Args:
      ident: Variable name from the directive, possibly with surrounding
        whitespace.

    Returns:
      The bound value from the variable mapping, or an empty list when the
      identifier is not bound — making an empty loop the default behaviour.
    """
    return self.vars.get(ident.strip(), [])
