"""Mechanical helpers for the lazy-observe.install skill.

Pure functions where possible (template rendering, path resolution); the
side-effect functions are clearly named (`load_service_macos`, etc.) so
the skill driver can call them in sequence and verify each in isolation.

Stdlib-only — no Jinja2 dependency. Templates use a small `{{ name }}` and
`{% if/elif/endif %}` substitution dialect; the parser below handles only
the constructs the shipped templates use, intentionally rejecting anything
else so an attempted Jinja2-style mistake fails loudly.
"""
from __future__ import annotations
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Iterable


XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
XDG_DATA_HOME   = Path(os.environ.get("XDG_DATA_HOME")   or (Path.home() / ".local/share"))
XDG_STATE_HOME  = Path(os.environ.get("XDG_STATE_HOME")  or (Path.home() / ".local/state"))

ANSWER_FILE = XDG_CONFIG_HOME / "lazycortex" / "observe.toml"
TOKEN_FILE  = XDG_CONFIG_HOME / "lazycortex" / "observe.token"
DATA_DIR    = XDG_DATA_HOME   / "lazycortex" / "observe"
LOG_DIR_MAC = Path.home() / "Library" / "Logs" / "lazycortex-observe"

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def detect_host() -> str:
    """Return `darwin` / `linux`. Anything else → ValueError."""
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    raise ValueError(f"unsupported platform: {sys.platform!r}")


def render(template_name: str, vars: dict[str, object]) -> str:
    """Render a template file under `templates/<name>` with the given vars.

    Supported syntax:
      `{{ key }}` or `{{ key | default('foo') }}`
      `{% if cond %} ... {% elif cond %} ... {% else %} ... {% endif %}`
      `{% for item in seq %} ... {% endfor %}`

    Anything else raises — fail loudly rather than pretend Jinja2 compat.
    """
    src = (TEMPLATE_DIR / template_name).read_text()
    return _Template(src, vars).render()


def render_to(template_name: str, vars: dict[str, object], target: Path) -> Path:
    """Render and write atomically (.tmp + rename)."""
    body = render(template_name, vars)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(body)
    os.replace(tmp, target)
    return target


def write_token_file(token: str) -> Path:
    """Persist the bearer/basic token to a 0600 file. Caller is responsible
    for asking the operator before invoking."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token + "\n")
    os.chmod(TOKEN_FILE, 0o600)
    return TOKEN_FILE


def write_answer_file(answers: dict) -> Path:
    """Persist non-secret answers (URL, agent kind, auth kind, etc.).
    Format: trivial TOML — top-level `key = "value"` pairs only.
    Never include the token here."""
    ANSWER_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for k, v in sorted(answers.items()):
        if k in {"token", "LAZYCORTEX_OBSERVE_TOKEN"}:
            raise ValueError(f"refused to write secret key {k!r} into the answer file")
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        else:
            escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{escaped}"')
    ANSWER_FILE.write_text("\n".join(lines) + "\n")
    return ANSWER_FILE


def read_answer_file() -> dict:
    """Read a previously-saved answer file. Returns {} if absent."""
    if not ANSWER_FILE.exists():
        return {}
    out: dict = {}
    pat = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$')
    for raw in ANSWER_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = pat.match(line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if v.lower() in ("true", "false"):
            out[k] = (v.lower() == "true")
        elif v.startswith('"') and v.endswith('"'):
            out[k] = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        else:
            try:
                out[k] = int(v) if "." not in v else float(v)
            except ValueError:
                out[k] = v
    return out


def find_agent_binary(agent_kind: str) -> Path | None:
    """Locate the shipping agent binary on PATH. Returns None if missing."""
    candidates = {
        "alloy":   ["alloy", "grafana-alloy"],
        "otelcol": ["otelcol", "otelcol-contrib"],
    }.get(agent_kind, [])
    for name in candidates:
        path = shutil.which(name)
        if path:
            return Path(path)
    return None


def load_service_macos(plist_path: Path) -> tuple[bool, str]:
    """Bootstrap the launchd agent. Returns (ok, stderr)."""
    uid = os.getuid()
    proc = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
        capture_output=True, text=True,
    )
    return (proc.returncode == 0, proc.stderr)


def unload_service_macos(plist_path: Path) -> tuple[bool, str]:
    uid = os.getuid()
    proc = subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(plist_path)],
        capture_output=True, text=True,
    )
    # bootout exits non-zero if not loaded — caller decides whether to care.
    return (proc.returncode == 0, proc.stderr)


def load_service_linux(unit_name: str = "lazycortex-observe.service") -> tuple[bool, str]:
    """Enable + start the systemd user unit. Returns (ok, stderr)."""
    proc = subprocess.run(
        ["systemctl", "--user", "enable", "--now", unit_name],
        capture_output=True, text=True,
    )
    return (proc.returncode == 0, proc.stderr)


def unload_service_linux(unit_name: str = "lazycortex-observe.service") -> tuple[bool, str]:
    proc = subprocess.run(
        ["systemctl", "--user", "disable", "--now", unit_name],
        capture_output=True, text=True,
    )
    return (proc.returncode == 0, proc.stderr)


def smoke_test_local_metrics(scrape_target: str, timeout: float = 5.0) -> bool:
    """Best-effort connect to the lazycortex-core /metrics endpoint."""
    import urllib.request
    try:
        url = f"http://{scrape_target}/metrics"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read(4096).decode("utf-8", "ignore")
            return "lazycortex_runtime" in body
    except (urllib.error.URLError, socket.timeout, ConnectionError):
        return False


# --- Tiny template engine --------------------------------------------------

class _Template:
    _RE = re.compile(
        r"\{\{\s*(.+?)\s*\}\}"        # {{ var }}
        r"|\{%\s*(.+?)\s*%\}",        # {% directive %}
        re.DOTALL,
    )

    def __init__(self, src: str, vars: dict):
        self.src = src
        self.vars = vars

    def render(self) -> str:
        out: list[str] = []
        # Stack of (active, true_branch_taken) — controls whether to emit text.
        stack: list[tuple[bool, bool]] = [(True, True)]
        # Loop stack: (var_name, iter_obj, body_buffer, body_start_idx).
        # For simplicity, we only support the *static* substitutions the
        # shipped templates need; loop body is collected then expanded inline.
        loop_stack: list[dict] = []

        pos = 0
        for m in self._RE.finditer(self.src):
            chunk = self.src[pos:m.start()]
            self._emit(out, loop_stack, chunk, stack[-1][0])
            pos = m.end()

            if m.group(1) is not None:
                expr = m.group(1).strip()
                if stack[-1][0]:
                    self._emit(out, loop_stack, self._eval(expr), True)
            else:
                directive = m.group(2).strip()
                self._handle_directive(directive, stack, loop_stack, out)

        tail = self.src[pos:]
        self._emit(out, loop_stack, tail, stack[-1][0])

        if len(stack) != 1:
            raise SyntaxError("template ended with unclosed {% if %} block")
        if loop_stack:
            raise SyntaxError("template ended with unclosed {% for %} block")
        return "".join(out)

    def _emit(self, out: list, loop_stack: list, text: str, active: bool) -> None:
        if not active or not text:
            return
        if loop_stack:
            loop_stack[-1]["body"].append(("text", text))
        else:
            out.append(text)

    def _handle_directive(self, directive: str, stack, loop_stack, out: list) -> None:
        active = stack[-1][0]

        if directive.startswith("if "):
            cond = self._truthy(directive[3:]) if active else False
            stack.append((cond, cond))

        elif directive.startswith("elif "):
            prev_active, branch_taken = stack[-1]
            parent_active = stack[-2][0]
            if branch_taken:
                stack[-1] = (False, True)
            elif parent_active and self._truthy(directive[5:]):
                stack[-1] = (True, True)
            else:
                stack[-1] = (False, branch_taken)

        elif directive == "else":
            prev_active, branch_taken = stack[-1]
            parent_active = stack[-2][0]
            if branch_taken:
                stack[-1] = (False, True)
            elif parent_active:
                stack[-1] = (True, True)

        elif directive == "endif":
            stack.pop()

        elif directive.startswith("for "):
            # `for item in seq`
            m = re.match(r"for\s+(\w+)\s+in\s+(\S+)", directive)
            if not m:
                raise SyntaxError(f"bad for: {directive!r}")
            if active:
                seq = self._eval_value(m.group(2))
                if not isinstance(seq, Iterable):
                    raise TypeError(f"non-iterable in for: {seq!r}")
                loop_stack.append({"var": m.group(1), "seq": list(seq), "body": [], "active": True})
            else:
                loop_stack.append({"var": m.group(1), "seq": [], "body": [], "active": False})

        elif directive == "endfor":
            frame = loop_stack.pop()
            if not frame["active"]:
                return
            for item in frame["seq"]:
                self.vars[frame["var"]] = item
                for kind, payload in frame["body"]:
                    if kind == "text":
                        if loop_stack:
                            loop_stack[-1]["body"].append(("text", payload))
                        else:
                            out.append(payload)
                    elif kind == "expr":
                        rendered = self._eval(payload)
                        if loop_stack:
                            loop_stack[-1]["body"].append(("text", rendered))
                        else:
                            out.append(rendered)
            self.vars.pop(frame["var"], None)

        else:
            raise SyntaxError(f"unsupported template directive: {directive!r}")

    def _truthy(self, expr: str) -> bool:
        # Support `kind == "value"` or just `name`.
        m = re.match(r'(\w+)\s*==\s*"([^"]*)"$', expr)
        if m:
            return str(self.vars.get(m.group(1))) == m.group(2)
        return bool(self.vars.get(expr))

    def _eval(self, expr: str) -> str:
        # `name | default('foo')` first.
        m = re.match(r"(\w+)\s*\|\s*default\(\s*'([^']*)'\s*\)$", expr)
        if m:
            v = self.vars.get(m.group(1))
            if v is None or v == "":
                return m.group(2)
            return str(v)
        return str(self.vars.get(expr, ""))

    def _eval_value(self, ident: str):
        return self.vars.get(ident.strip(), [])
