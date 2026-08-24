#!/usr/bin/env python3

"""
Vault-config manifest worker for the lazycortex-obsidian plugin.

Captures a vault's Obsidian config directory into one tracked manifest file, and deploys
that manifest back onto a checkout that has no config directory at all. The config then
travels as a single reviewed file instead of the hundred-odd files the mobile app rewrites
behind git's back.

Backs the `lazy-obsidian.capture` and `lazy-obsidian.deploy` skills.
"""

# Decision: a plain script rather than skill-driven steps — the deploy path has to run over ssh on
# a phone, where no model is present, and duplicating the bundle-download logic the update-plugin
# skill already describes in prose is the price of that.

from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from vault_keys import (
  AppearanceKey, BundleKey, BundleSourceKind, CachePath, CommandKind, Encoding, Http,
  ManifestKey, PluginKey, ReportKey, SnippetKey, SnippetSourceKind, TemplatePath, VaultPath,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Any


MANIFEST_VERSION = 1

# Top-level config files never captured.
# - workspace* / graph.json: per-device session state, rewritten on every layout change.
# - community-plugins.json: derived — the manifest's plugin map carries enablement, and
#   deploy rebuilds the file from it. Two writers for one fact is one too many.
CONFIG_DENYLIST = {
  "workspace.json",
  "workspace-mobile.json",
  "workspaces.json",
  "graph.json",
  VaultPath.COMMUNITY_PLUGINS,
}

# Per-device keys inside the appearance settings: window zoom belongs to the screen.
APPEARANCE_DEVICE_KEYS = { AppearanceKey.ZOOM_FACTOR }

# Plugins whose settings file is derived state restored by its own writer rather than by
# deploy. Iconize's database is rebuilt by iconize-reloader from note frontmatter.
PLUGIN_DATA_SKIP = { "obsidian-icon-folder" }

# Key names whose string value is a credential by the name alone. A bare `token` is
# deliberately absent: plugins use it for syntax-highlighting classes and other harmless
# identifiers, and dropping those corrupts the settings deploy lays back down.
SECRET_KEY_RE = re.compile(
  r"password|passwd|secret|api[-_]?key|credential|bearer"
  r"|(access|auth|refresh|api|personal)[-_]?token|token[-_]?(value|string)"
  r"|private[-_]?key", re.I)

# Value shapes that are a credential whatever key they sit under: provider-issued tokens,
# AWS access keys, JWTs, and long unbroken base64-alphabet strings.
# limit: the final alternative matches any 40-plus-character base64-shaped value, so a long
# opaque non-credential setting is dropped too; tighten with a character-class mix test if a
# real setting is ever lost to it.
SECRET_VALUE_RE = re.compile(
  r"^(gh[pousr]_[A-Za-z0-9]{16,}"
  r"|github_pat_[A-Za-z0-9_]{20,}"
  r"|sk-[A-Za-z0-9_-]{16,}"
  r"|xox[baprs]-[A-Za-z0-9-]{10,}"
  r"|AKIA[0-9A-Z]{12,}"
  r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
  r"|[A-Za-z0-9+/]{40,}={0,2})$")

COMMUNITY_LIST_URL = (
  "https://raw.githubusercontent.com/obsidianmd/obsidian-releases/master/community-plugins.json"
)
HEAD_MANIFEST_URL = "https://raw.githubusercontent.com/{repo}/HEAD/manifest.json"
RELEASE_ASSET_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"
CATALOG_TTL_SEC = 24 * 60 * 60

ENV_CACHE_HOME = "XDG_CACHE_HOME"
GH_TOKEN_COMMAND = ("gh", "auth", "token")
GH_TOKEN_TIMEOUT_SEC = 5
HTTP_TIMEOUT_SEC = 30


# ----------------------------------------------------------------------------------------
class WorkerError(Exception):
  """
  A condition the caller must fix before the run can proceed.

  Raised for a missing vault or an unreadable manifest — never for a single plugin that
  failed to resolve, which is reported and survived.
  """


# ----------------------------------------------------------------------------------------
def load_json(path: Path) -> Any:  # waiver: arbitrary JSON payload — Obsidian config shape is not ours
  """
  Read and parse a JSON file.

  Args:
    path: File to read.

  Returns:
    The parsed content, or None when the file is absent or does not parse.
  """
  try:
    return json.loads(path.read_text(encoding = Encoding.UTF8))
  except (OSError, ValueError):
    return None


def dump_json(path: Path,
              obj: Any,  # waiver: arbitrary JSON payload — Obsidian config shape is not ours
              *, trailing_newline: bool = False) -> None:
  """
  Write an object as indented JSON, atomically.

  Obsidian writes its own config with a serializer that ends at the closing brace. Adding
  a trailing newline there makes every vault re-dirty the file on next launch, so the
  newline is opt-in and used only for the manifest — a repo file, not Obsidian's.

  Args:
    path: File to write; parent directories are created.
    obj: Value to serialize.
    trailing_newline: Whether to end the file with a newline.
  """
  path.parent.mkdir(parents = True, exist_ok = True)
  text = json.dumps(obj, indent = 2, ensure_ascii = False)
  if trailing_newline:
    text += "\n"
  write_bytes(path, text.encode(Encoding.UTF8))


def write_bytes(path: Path, data: bytes) -> None:
  """
  Write bytes to a file atomically, creating parent directories.

  Guarantees:
    - A reader of `path` never observes a partially written file: the payload lands on a
      sibling temporary file and is renamed into place in one step.

  Args:
    path: File to write.
    data: Payload to write.
  """

  # Contract:
  # A reader of the target path never observes a partially written file — the payload is written
  # to a sibling temporary file and renamed into place, so the path holds either its previous
  # content or the complete new content, never a prefix of it.

  path.parent.mkdir(parents = True, exist_ok = True)
  tmp = path.with_name(path.name + VaultPath.TMP_SUFFIX)
  tmp.write_bytes(data)
  tmp.replace(path)


def find_all_matching(directory: Path, pattern: str) -> list[Path]:
  """
  List a directory's files matching a filename pattern, in name order.

  Args:
    directory: Directory to list; a missing one yields nothing.
    pattern: Filename glob matched against each entry's name.

  Returns:
    Matching file paths, sorted by name.
  """
  # guard: a vault without the directory simply has none of these files
  if not directory.is_dir():
    return []
  return [directory / name for name in sorted(os.listdir(directory))
          if fnmatch.fnmatch(name, pattern) and (directory / name).is_file()]


def is_safe_name(name: object) -> bool:
  """
  Decide whether a manifest-supplied name may be used as a filename.

  The manifest is a tracked file that reaches a checkout through git, so a name in it is
  untrusted input: anything carrying a path separator or a parent reference would let
  deploy write outside the vault.

  Guarantees:
    - Every name this accepts resolves inside the directory it is joined onto: no separator,
      no parent reference, no empty name.

  Args:
    name: Candidate name read from the manifest.

  Returns:
    True when the name is a plain filename safe to join onto the vault path.
  """

  # Contract:
  # A name this accepts always resolves inside the directory it is joined onto. Every deploy path
  # that turns a manifest-supplied name into a filesystem path checks it first, which is what keeps
  # a manifest arriving through git from writing outside the vault.

  # guard: only a plain non-empty string can name a file
  if not isinstance(name, str) or not name or name in (".", ".."):
    return False
  return "/" not in name and "\\" not in name and os.sep not in name


def is_secret(key: object,
              value: object) -> bool:
  """
  Decide whether one settings entry carries a credential.

  An entry qualifies either because its key names a credential outright, or because its
  value has the shape of one — a provider-issued token, an access key, or a long opaque
  string — under a key too ambiguous to judge on its own.

  Args:
    key: The entry's key, of whatever type the payload carried.
    value: The entry's value, of whatever type the payload carried.

  Returns:
    True when the entry must never reach the manifest.
  """

  # Domain(unfiled):
  # # Recognising a credential in captured configuration
  # A configuration entry counts as a credential on either of two independent signals: the name of
  # the entry says so outright, or the value itself has the shape of a credential a provider issues.
  # The two signals are needed together because neither is sufficient — an entry named for a secret
  # may hold a harmless flag, and an entry with a neutral name may hold a real token.
  # One name is deliberately excluded from the first signal: a bare "token" is used across the
  # ecosystem for syntax-highlighting classes and similar identifiers, so treating it as a credential
  # by name alone removes settings that are not secret and corrupts the configuration on restore.
  # Only text values are ever removed. A boolean that merely names a credential is a behaviour
  # switch, and removing it would change what the restored configuration does.

  # guard: only a non-empty string can be the credential itself
  if not isinstance(value, str) or not value.strip():
    return False
  if isinstance(key, str) and SECRET_KEY_RE.search(key):
    return True
  return bool(SECRET_VALUE_RE.match(value.strip()))


def strip_secrets(obj: Any,  # waiver: arbitrary JSON payload — plugin settings shape is not ours
                  path: str,
                  omitted: list[str]) -> Any:  # waiver: mirrors the input payload's shape
  """
  Drop credential values, recording where each one was.

  Only string values are dropped: a boolean flag naming a token is not one, and blanking
  it would change behaviour on deploy.

  Args:
    obj: Value to scan, of any JSON shape.
    path: Dotted path of `obj` within its file, used to report omissions.
    omitted: Accumulator the dotted path of every dropped value is appended to.

  Returns:
    A copy of `obj` with credential values removed.
  """
  if isinstance(obj, dict):
    out: dict[str, Any] = {}  # waiver: arbitrary JSON payload
    for key, value in obj.items():
      here = f"{path}.{key}"
      # guard: a credential never enters the manifest, by its key or by its own shape
      if is_secret(key, value):
        omitted.append(here)
        continue
      out[key] = strip_secrets(value, here, omitted)
    return out
  if isinstance(obj, list):
    return [strip_secrets(item, f"{path}[{index}]", omitted)
            for index, item in enumerate(obj)]
  return obj


def plugin_root() -> Path:
  """
  Locate the lazycortex-obsidian plugin root.

  Returns:
    The directory holding this plugin's `bin/` and `templates/`.
  """
  return Path(__file__).resolve().parent.parent


def template_root() -> Path:
  """
  Locate the vault-shaped template subtree this plugin ships.

  Returns:
    The directory whose children mirror a vault's config directory.
  """
  return plugin_root() / TemplatePath.ROOT / TemplatePath.VAULT


def cache_root() -> Path:
  """
  Locate the persistent bundle cache, honouring the XDG cache variable.

  Returns:
    This plugin's directory inside the user's cache root.
  """
  base = os.environ.get(ENV_CACHE_HOME) or str(Path.home() / CachePath.DEFAULT_ROOT)
  return Path(base) / CachePath.NAMESPACE


# ----------------------------------------------------------------------------------------
def resolve_github_token() -> str:
  """
  Resolve a GitHub token for authenticated requests.

  Returns:
    A token from the environment or the `gh` CLI, or an empty string when neither has one.
  """
  for name in Http.ENV_TOKENS:
    token = os.environ.get(name)
    if token:
      return token
  try:
    # waiver: the `gh` CLI is the operator's own credential store, not an injected command
    result = subprocess.run(
      list(GH_TOKEN_COMMAND), capture_output = True, text = True,
      timeout = GH_TOKEN_TIMEOUT_SEC, check = False)
    return result.stdout.strip()
  except (OSError, subprocess.SubprocessError):
    return ""


def fetch_bytes(url: str, *, accept: str = Http.JSON) -> bytes:
  """
  Fetch a URL.

  Args:
    url: Absolute URL to request.
    accept: Media type to ask for.

  Returns:
    The response body.

  Raises:
    urllib.error.URLError: When the request fails or the server returns an error status.
  """
  request = urllib.request.Request(
    url, headers = { Http.ACCEPT: accept, Http.USER_AGENT: Http.AGENT_VALUE })

  # authenticate only to GitHub's own hosts, and only when a token was found at all
  token = resolve_github_token()
  if token and any(host in url for host in Http.TOKEN_HOSTS):
    request.add_header(Http.AUTHORIZATION, f"Bearer {token}")
  # waiver: fixed https endpoints built from constants above, not caller-supplied schemes
  with urllib.request.urlopen(request, timeout = HTTP_TIMEOUT_SEC) as response:
    return response.read()


def fetch_community_catalog() -> dict[str, dict]:  # waiver: catalog entries are upstream JSON
  """
  Load the community-plugin catalog, refreshing a day-old cached copy.

  Returns:
    Catalog entries keyed by plugin id; empty when upstream is unreachable and nothing was
    ever cached.
  """
  cached = cache_root() / CachePath.CATALOG
  fresh = cached.is_file() and cached.stat().st_mtime + CATALOG_TTL_SEC > time.time()
  if not fresh:
    try:
      write_bytes(cached, fetch_bytes(COMMUNITY_LIST_URL))
    except (urllib.error.URLError, OSError):
      # guard: an unreachable catalog is survivable only when a stale copy exists
      if not cached.is_file():
        return {}
  entries = load_json(cached) or []
  return { entry[PluginKey.ID]: entry for entry in entries
           if isinstance(entry, dict) and entry.get(PluginKey.ID) }


def resolve_bundle(pid: str, repo: str | None) -> dict:  # waiver: mixed bytes/str envelope
  """
  Resolve a plugin's latest bundle, falling back to the vendored cache.

  Upstream is the repo's HEAD manifest version — the same signal Obsidian uses for update
  checks — and a rebranded repo can never pass itself off as the source for a different plugin's id.

  Args:
    pid: Plugin id to resolve.
    repo: Owner/name of the plugin's GitHub repo, or None when it is unknown.

  Returns:
    An envelope carrying the bundle's source, version, asset bytes, and the upstream error
    whenever a fallback was needed.
  """
  cache_dir = cache_root() / CachePath.BUNDLES / pid

  # a plugin outside the catalog needs an explicit repo in its manifest entry to be resolvable
  if not repo:
    # waiver: one-off diagnostic text, not a shared constant
    error: str | None = "not in the community catalog and no repo override in the manifest entry"
  else:
    version, error = _head_version(_fetch_head_manifest(repo), pid)
    if version is not None:
      tried: list[str] = []
      for tag in (version, f"v{version}"):
        assets = _fetch_release(repo, tag, pid, tried)
        if assets is not None:
          _write_cache(cache_dir, assets)
          return { BundleKey.SOURCE: BundleSourceKind.UPSTREAM, BundleKey.VERSION: version,
                   **assets, BundleKey.ERROR: None }
      error = f"release assets unavailable ({', '.join(tried)})"

  # fall back to the vendored bundle when upstream could not serve this plugin
  cached = _read_cache(cache_dir, pid)
  if cached is not None:
    return { BundleKey.SOURCE: BundleSourceKind.CACHE, **cached, BundleKey.ERROR: error }
  return {
    BundleKey.SOURCE: BundleSourceKind.NONE, BundleKey.VERSION: "",
    BundleKey.MANIFEST_BYTES: None, BundleKey.MAIN_BYTES: None, BundleKey.STYLES_BYTES: None,
    BundleKey.ERROR: error,
  }


def _fetch_head_manifest(repo: str) -> dict | None:  # waiver: upstream manifest JSON
  """
  Read a repo's default-branch plugin manifest.

  Args:
    repo: Owner/name of the plugin's GitHub repo.

  Returns:
    The parsed manifest, or None when it is unreachable or unparseable.
  """
  try:
    return json.loads(fetch_bytes(HEAD_MANIFEST_URL.format(repo = repo)))
  except (urllib.error.URLError, OSError, ValueError):
    return None


def _head_version(head: dict | None,  # waiver: upstream manifest JSON
                  pid: str) -> tuple[str | None, str | None]:
  """
  Read the version a repo's HEAD manifest offers, or say why it cannot be trusted.

  Args:
    head: Parsed HEAD manifest, or None when it could not be read.
    pid: Plugin id the manifest must declare.

  Returns:
    The version paired with None, or None paired with the reason upstream is unusable.
  """
  # guard: nothing to trust without a readable manifest
  if head is None:
    # waiver: one-off diagnostic text, not a shared constant
    return None, "no readable manifest at repo HEAD"
  # guard: id mismatch means the repo was rebranded and now ships a different plugin
  if head.get(PluginKey.ID) != pid:
    return None, f"repo HEAD manifest id is {head.get(PluginKey.ID)!r} (rebranded)"
  version = head.get(PluginKey.VERSION)
  # guard: an unversioned manifest cannot name a release tag
  if not version:
    # waiver: one-off diagnostic text, not a shared constant
    return None, "repo HEAD manifest has no version"
  return version, None


def _fetch_release(repo: str,
                   tag: str,
                   pid: str,
                   tried: list[str]) -> dict | None:  # waiver: asset bytes envelope
  """
  Download one release's assets when that release really serves this plugin.

  Args:
    repo: Owner/name of the plugin's GitHub repo.
    tag: Release tag to try.
    pid: Plugin id the release must declare.
    tried: Accumulator each failed attempt appends its reason to.

  Returns:
    The asset bytes, or None when this tag does not serve the plugin.
  """
  def fetch_asset(name: str) -> bytes:
    return fetch_bytes(
      RELEASE_ASSET_URL.format(repo = repo, tag = tag, asset = name), accept = Http.OCTET_STREAM)

  # the manifest and the entry point are mandatory for a usable release
  try:
    manifest_bytes = fetch_asset(VaultPath.PLUGIN_MANIFEST)
    released = json.loads(manifest_bytes)
    # guard: the release must declare the id we asked for
    if released.get(PluginKey.ID) != pid:
      tried.append(f"{tag}: id is {released.get(PluginKey.ID)!r}")
      return None
    main_bytes = fetch_asset(VaultPath.PLUGIN_MAIN)
  except urllib.error.HTTPError as exc:
    tried.append(f"{tag}: HTTP {exc.code}")
    return None
  except (urllib.error.URLError, OSError, ValueError) as exc:
    # waiver: exception class name as diagnostic text, not a domain class id
    tried.append(f"{tag}: {type(exc).__name__}")
    return None

  # the stylesheet is optional, so its absence does not rule the tag out
  styles_bytes: bytes | None = None
  try:
    styles_bytes = fetch_asset(VaultPath.PLUGIN_STYLES)
  except (urllib.error.URLError, OSError):
    pass  # a plugin without a stylesheet is normal
  return {
    BundleKey.MANIFEST_BYTES: manifest_bytes,
    BundleKey.MAIN_BYTES: main_bytes,
    BundleKey.STYLES_BYTES: styles_bytes,
  }


def _write_cache(cache_dir: Path, assets: dict) -> None:  # waiver: asset bytes envelope
  """
  Mirror a freshly fetched bundle into the vendored cache.

  Args:
    cache_dir: Per-plugin cache directory.
    assets: Asset bytes as returned by a release fetch.
  """
  write_bytes(cache_dir / VaultPath.PLUGIN_MANIFEST, assets[BundleKey.MANIFEST_BYTES])
  write_bytes(cache_dir / VaultPath.PLUGIN_MAIN, assets[BundleKey.MAIN_BYTES])
  styles = cache_dir / VaultPath.PLUGIN_STYLES
  if assets[BundleKey.STYLES_BYTES] is not None:
    write_bytes(styles, assets[BundleKey.STYLES_BYTES])
  elif styles.exists():
    # upstream dropped its stylesheet, so the cached one must go with it
    styles.unlink()


def _read_cache(cache_dir: Path, pid: str) -> dict | None:  # waiver: asset bytes envelope
  """
  Read the vendored bundle for a plugin.

  Args:
    cache_dir: Per-plugin cache directory.
    pid: Plugin id the cached manifest must declare.

  Returns:
    The cached version and asset bytes, or None when the cache is absent or foreign.
  """
  manifest_path = cache_dir / VaultPath.PLUGIN_MANIFEST
  main_path = cache_dir / VaultPath.PLUGIN_MAIN
  if not (manifest_path.is_file() and main_path.is_file()):
    return None
  manifest = load_json(manifest_path)
  # guard: a cache entry that names another plugin is not this plugin's fallback
  if not isinstance(manifest, dict) or manifest.get(PluginKey.ID) != pid \
      or not manifest.get(PluginKey.VERSION):
    return None
  styles = cache_dir / VaultPath.PLUGIN_STYLES
  return {
    BundleKey.VERSION: manifest[PluginKey.VERSION],
    BundleKey.MANIFEST_BYTES: manifest_path.read_bytes(),
    BundleKey.MAIN_BYTES: main_path.read_bytes(),
    BundleKey.STYLES_BYTES: styles.read_bytes() if styles.is_file() else None,
  }


# ----------------------------------------------------------------------------------------
def build_manifest(root: Path) -> dict:  # waiver: manifest of mixed JSON shapes
  """
  Read a vault's whole config surface into a manifest value.

  The palette group is preserved from whatever manifest the repo already carries: it names
  the template the vault grew from, which the config directory itself does not record.

  Args:
    root: Vault repo root, the directory holding the config directory.

  Returns:
    The manifest describing the vault's current configuration.

  Raises:
    WorkerError: When the repo root has no config directory to read.
  """
  vault = root / VaultPath.OBSIDIAN
  # guard: nothing to read without a config directory
  if not vault.is_dir():
    raise WorkerError(f"no {VaultPath.OBSIDIAN}/ under {root}")

  # collect the whole config surface before assembling anything
  omitted: list[str] = []
  config = _capture_config(vault, omitted)
  previous = load_json(root / VaultPath.MANIFEST) or {}
  appearance = config.get(VaultPath.APPEARANCE) or {}

  # assemble the manifest from the captured parts
  return {
    ManifestKey.VERSION: MANIFEST_VERSION,
    ManifestKey.GROUP: previous.get(ManifestKey.GROUP),
    ManifestKey.THEME: appearance.get(AppearanceKey.CSS_THEME) or None,
    ManifestKey.CONFIG: config,
    ManifestKey.SNIPPETS: _capture_snippets(vault),
    ManifestKey.PLUGINS: _capture_plugins(vault, omitted),
    ManifestKey.SECRETS_OMITTED: omitted,
  }


def capture(root: Path) -> dict:  # waiver: report envelope of mixed shapes
  """
  Snapshot a vault's config directory into its manifest.

  Args:
    root: Vault repo root, the directory holding the config directory.

  Returns:
    A report naming the manifest written and what it now carries.

  Raises:
    WorkerError: When the repo root has no config directory to capture.
  """
  manifest = build_manifest(root)
  dump_json(root / VaultPath.MANIFEST, manifest, trailing_newline = True)

  # report what the manifest now carries
  return {
    ReportKey.ACTION: CommandKind.CAPTURE,
    ReportKey.MANIFEST: str(root / VaultPath.MANIFEST),
    ReportKey.CONFIG_FILES: sorted(manifest[ManifestKey.CONFIG]),
    ReportKey.SNIPPETS: sorted(manifest[ManifestKey.SNIPPETS]),
    ReportKey.PLUGINS: sorted(manifest[ManifestKey.PLUGINS]),
    ReportKey.THEME: manifest[ManifestKey.THEME],
    ReportKey.SECRETS_OMITTED: manifest[ManifestKey.SECRETS_OMITTED],
    ReportKey.ERRORS: [],
  }


def _capture_config(vault: Path, omitted: list[str]) -> dict:  # waiver: Obsidian config JSON
  """
  Snapshot every top-level config file that is neither derived nor per-device.

  Args:
    vault: The vault's config directory.
    omitted: Accumulator for the dotted paths of secret-looking values.

  Returns:
    A map of config filename to its captured content.
  """
  config: dict[str, Any] = {}  # waiver: Obsidian config JSON
  for path in find_all_matching(vault, VaultPath.JSON_GLOB):
    # guard: derived and per-device files never enter the manifest
    if path.name in CONFIG_DENYLIST:
      continue
    data = load_json(path)
    # guard: an unparseable file is left to the operator, not half-captured
    if data is None:
      continue
    if path.name == VaultPath.APPEARANCE and isinstance(data, dict):
      data = { key: value for key, value in data.items()
               if key not in APPEARANCE_DEVICE_KEYS }
    config[path.name] = strip_secrets(data, path.name, omitted)
  return config


def _capture_snippets(vault: Path) -> dict:  # waiver: snippet entries of mixed shapes
  """
  Snapshot CSS snippets, recording plugin-shipped ones by name only.

  A snippet byte-identical to what this plugin ships is the plugin's file: storing its
  body would pin today's version and stop plugin updates from reaching the vault. A
  snippet that differs — personal, or an edited copy — travels with its body.

  Args:
    vault: The vault's config directory.

  Returns:
    A map of snippet filename to its provenance and, for vault-owned snippets, its body.
  """

  # Domain(unfiled):
  # # Provenance of a stylesheet snippet in a captured configuration
  # A snippet that is byte-identical to the one the tooling itself installs belongs to the tooling,
  # not to the vault, and travels by name alone. Recording its text instead would freeze the copy
  # taken on the day of the capture, so a later improvement to that snippet would never reach any
  # vault restored from the record.
  # A snippet whose text differs — written by hand, or an installed one since edited — belongs to
  # the vault, and travels with its full text. The comparison is what decides ownership: there is
  # no separate list of which snippets are whose, so an edit silently transfers ownership to the
  # vault, and reverting the edit transfers it back.

  shipped = template_root() / VaultPath.SNIPPETS
  snippets: dict[str, Any] = {}  # waiver: snippet entries of mixed shapes
  for path in find_all_matching(vault / VaultPath.SNIPPETS, VaultPath.CSS_GLOB):
    reference = shipped / path.name
    if reference.is_file() and reference.read_bytes() == path.read_bytes():
      snippets[path.name] = { SnippetKey.SOURCE: SnippetSourceKind.PLUGIN, SnippetKey.BODY: None }
    else:
      snippets[path.name] = {
        SnippetKey.SOURCE: SnippetSourceKind.VAULT,
        SnippetKey.BODY: path.read_text(encoding = Encoding.UTF8),
      }
  return snippets


def _capture_plugins(vault: Path, omitted: list[str]) -> dict:  # waiver: plugin settings JSON
  """
  Snapshot every installed community plugin.

  Args:
    vault: The vault's config directory.
    omitted: Accumulator for the dotted paths of secret-looking values.

  Returns:
    A map of plugin id to its enablement, captured version, and whole settings payload.
  """
  enabled = set(load_json(vault / VaultPath.COMMUNITY_PLUGINS) or [])
  plugins_dir = vault / VaultPath.PLUGINS
  plugins: dict[str, Any] = {}  # waiver: plugin settings JSON
  for directory in (sorted(plugins_dir.iterdir()) if plugins_dir.is_dir() else []):
    # guard: only plugin directories carry a bundle
    if not directory.is_dir():
      continue
    pid = directory.name
    installed = load_json(directory / VaultPath.PLUGIN_MANIFEST) or {}
    data = (
      None if pid in PLUGIN_DATA_SKIP
      else strip_secrets(load_json(directory / VaultPath.PLUGIN_DATA), pid, omitted))
    plugins[pid] = {
      PluginKey.ENABLED: pid in enabled,
      # Not a pin — deploy always installs latest. Kept so the audit can warn that the
      # snapshot was taken under an older schema than the version now installed.
      PluginKey.CAPTURED_VERSION: installed.get(PluginKey.VERSION) or "",
      PluginKey.DATA: data,
    }
  return plugins


# ----------------------------------------------------------------------------------------
def drift(root: Path) -> dict:  # waiver: report envelope of mixed shapes
  """
  Report how a vault's live configuration differs from what its manifest records.

  Writes nothing: the operator decides whether the live vault is right (re-capture) or the
  manifest is (re-deploy).

  Args:
    root: Vault repo root, the directory holding the manifest.

  Returns:
    A report listing every difference, plus warnings that are not differences.

  Raises:
    WorkerError: When the repo root carries no readable manifest or no config directory.
  """
  stored = load_json(root / VaultPath.MANIFEST)
  # guard: there is nothing to compare the vault against
  if not isinstance(stored, dict):
    raise WorkerError(f"no readable {VaultPath.MANIFEST} at {root}")
  live = build_manifest(root)

  # accumulate the differences, and the notes that are not differences
  findings: list[str] = []
  warnings: list[str] = []

  # the theme is a single value, so it reports as one line naming both sides
  if stored.get(ManifestKey.THEME) != live[ManifestKey.THEME]:
    findings.append(
      f"theme: manifest {stored.get(ManifestKey.THEME)!r}, vault {live[ManifestKey.THEME]!r}")

  # compare every section that maps a name to a whole value
  findings += _compare_maps(ManifestKey.CONFIG, stored, live)
  findings += _compare_maps(ManifestKey.SNIPPETS, stored, live)
  findings += _compare_plugins(stored, live, warnings)

  # a manifest that omitted a credential leaves the vault permanently different from it
  if live[ManifestKey.SECRETS_OMITTED]:
    warnings.append(
      f"{len(live[ManifestKey.SECRETS_OMITTED])} credential value(s) live in the vault and "
      f"never in the manifest: {', '.join(live[ManifestKey.SECRETS_OMITTED])}")

  # report the differences for the operator to arbitrate
  return {
    ReportKey.ACTION: CommandKind.DRIFT,
    ReportKey.DRIFT: findings,
    ReportKey.WARNINGS: warnings,
    ReportKey.ERRORS: [],
  }


def _compare_maps(section: str, stored: dict, live: dict) -> list[str]:
  """
  Compare one manifest section that maps a name to a whole value.

  Args:
    section: Manifest key of the section to compare.
    stored: The manifest as recorded in the repo.
    live: The manifest as the vault stands now.

  Returns:
    One line per name that was added, removed, or changed.
  """
  before = stored.get(section) or {}
  after = live.get(section) or {}
  findings = [f"{section}.{name}: in the vault, not in the manifest"
              for name in sorted(set(after) - set(before))]
  findings += [f"{section}.{name}: in the manifest, not in the vault"
               for name in sorted(set(before) - set(after))]
  findings += [f"{section}.{name}: differs"
               for name in sorted(set(before) & set(after)) if before[name] != after[name]]
  return findings


def _compare_plugins(stored: dict, live: dict, warnings: list[str]) -> list[str]:
  """
  Compare the plugin map, separating settings drift from a version that moved on.

  Args:
    stored: The manifest as recorded in the repo.
    live: The manifest as the vault stands now.
    warnings: Accumulator for versions that advanced past what was captured.

  Returns:
    One line per plugin that was added, removed, re-enabled, or whose settings changed.
  """
  before = stored.get(ManifestKey.PLUGINS) or {}
  after = live.get(ManifestKey.PLUGINS) or {}
  findings = [f"plugins.{pid}: installed, not in the manifest"
              for pid in sorted(set(after) - set(before))]
  findings += [f"plugins.{pid}: in the manifest, not installed"
               for pid in sorted(set(before) - set(after))]

  # a version that moved on is context for the settings drift, not drift itself
  for pid in sorted(set(before) & set(after)):
    was, now = before[pid], after[pid]
    if was.get(PluginKey.ENABLED) != now.get(PluginKey.ENABLED):
      findings.append(f"plugins.{pid}: enabled {was.get(PluginKey.ENABLED)} "
                      f"in the manifest, {now.get(PluginKey.ENABLED)} in the vault")
    if was.get(PluginKey.DATA) != now.get(PluginKey.DATA):
      findings.append(f"plugins.{pid}: settings differ")
    captured, installed = was.get(PluginKey.CAPTURED_VERSION), now.get(PluginKey.CAPTURED_VERSION)
    # a settings snapshot taken under an older plugin may predate that plugin's own migration
    if captured and installed and captured != installed:
      warnings.append(f"plugins.{pid}: captured under {captured}, {installed} installed")
  return findings


# ----------------------------------------------------------------------------------------
def deploy(root: Path) -> dict:  # waiver: report envelope of mixed shapes
  """
  Rebuild a vault's config directory from its manifest.

  Guarantees:
    - A plugin id reaches the enablement file only when this run wrote that plugin's bundle
      into the vault; every skipped plugin is named in the report's error list instead.

  Args:
    root: Vault repo root, the directory holding the manifest.

  Returns:
    A report naming what was written, with a non-empty error list when anything was
    skipped.

  Raises:
    WorkerError: When the repo root carries no readable manifest.
  """
  manifest = load_json(root / VaultPath.MANIFEST)
  # guard: deploy has no other source of truth
  if not isinstance(manifest, dict):
    raise WorkerError(f"no readable {VaultPath.MANIFEST} at {root}")

  # the config directory may not exist at all on a fresh checkout
  vault = root / VaultPath.OBSIDIAN
  vault.mkdir(parents = True, exist_ok = True)

  # unpack the sections deploy writes, and the accumulator for what it has to skip
  errors: list[str] = []
  config = manifest.get(ManifestKey.CONFIG) or {}
  plugins = manifest.get(ManifestKey.PLUGINS) or {}

  # lay down every top-level config file the manifest carries
  written_config: list[str] = []
  for name, data in config.items():
    # guard: derived and per-device files are rebuilt, never restored
    if name in CONFIG_DENYLIST:
      continue
    # guard: a name that is not a plain filename would escape the config directory
    if not is_safe_name(name):
      errors.append(f"config {name!r}: not a plain filename, skipped")
      continue
    dump_json(vault / name, data)
    written_config.append(name)

  # snippets, plugins, enablement, and theme complete the vault
  snippets = _deploy_snippets(vault, manifest.get(ManifestKey.SNIPPETS) or {}, errors)
  installed = _deploy_plugins(vault, plugins, errors)

  # Contract:
  # A plugin id appears in the enablement file only when this run wrote that plugin's
  # bundle into the vault; a skipped plugin is never enabled.

  # enable only what actually landed, so the vault never turns on a plugin with no bundle
  landed = { record[PluginKey.ID] for record in installed }
  dump_json(vault / VaultPath.COMMUNITY_PLUGINS,
            [pid for pid, entry in plugins.items()
             if entry.get(PluginKey.ENABLED) and pid in landed])
  theme = _deploy_theme(vault, manifest.get(ManifestKey.THEME), errors)

  # report what was written, naming everything that was skipped
  return {
    ReportKey.ACTION: CommandKind.DEPLOY,
    ReportKey.CONFIG_FILES: sorted(written_config),
    ReportKey.SNIPPETS: snippets,
    ReportKey.PLUGINS: installed,
    ReportKey.THEME: theme,
    ReportKey.SECRETS_OMITTED: manifest.get(ManifestKey.SECRETS_OMITTED) or [],
    ReportKey.ERRORS: errors,
  }


def _deploy_snippets(vault: Path, snippets: dict, errors: list[str]) -> list[str]:
  """
  Write vault-owned snippet bodies and re-copy plugin-shipped ones from the plugin.

  Args:
    vault: The vault's config directory.
    snippets: The manifest's snippet map.
    errors: Accumulator for snippets that could not be written.

  Returns:
    The filenames actually written, sorted.
  """
  shipped = template_root() / VaultPath.SNIPPETS
  written: list[str] = []
  for name, entry in sorted(snippets.items()):
    # guard: a name that is not a plain filename would escape the snippets directory
    if not is_safe_name(name):
      errors.append(f"snippet {name!r}: not a plain filename, skipped")
      continue
    target = vault / VaultPath.SNIPPETS / name
    if entry.get(SnippetKey.SOURCE) == SnippetSourceKind.PLUGIN:
      reference = shipped / name
      # guard: the manifest claims this plugin ships the snippet, and it no longer does
      if not reference.is_file():
        errors.append(f"snippet {name}: recorded as plugin-shipped but this plugin has none")
        continue
      write_bytes(target, reference.read_bytes())
    else:
      body = entry.get(SnippetKey.BODY)
      # guard: a vault-owned snippet without a body cannot be reconstructed
      if not isinstance(body, str):
        errors.append(f"snippet {name}: no body recorded")
        continue
      write_bytes(target, body.encode(Encoding.UTF8))
    written.append(name)
  return written


def _deploy_plugins(vault: Path, plugins: dict, errors: list[str]) -> list[dict]:
  """
  Install every plugin in the manifest and lay its captured settings back down.

  Args:
    vault: The vault's config directory.
    plugins: The manifest's plugin map.
    errors: Accumulator for plugins that could not be resolved.

  Returns:
    One record per installed plugin, naming where its bundle came from and at which
    version.
  """
  catalog = fetch_community_catalog()
  bundled_root = template_root() / VaultPath.PLUGINS
  installed: list[dict] = []

  # a bundle this plugin ships wins over anything upstream could serve
  for pid, entry in plugins.items():
    # guard: a plugin id that is not a plain name would escape the plugins directory
    if not is_safe_name(pid):
      errors.append(f"plugin {pid!r}: not a plain plugin id, skipped")
      continue
    destination = vault / VaultPath.PLUGINS / pid
    bundled = bundled_root / pid
    if bundled.is_dir():
      version = _install_bundled(bundled, destination)
      installed.append({ PluginKey.ID: pid, BundleKey.SOURCE: BundleSourceKind.BUNDLED,
                         BundleKey.VERSION: version })
    else:
      repo = entry.get(PluginKey.REPO) or (catalog.get(pid) or {}).get(PluginKey.REPO)
      resolved = resolve_bundle(pid, repo)
      # guard: an unresolvable plugin is reported and skipped, never half-written
      if resolved[BundleKey.SOURCE] == BundleSourceKind.NONE:
        errors.append(f"plugin {pid}: {resolved[BundleKey.ERROR]}")
        continue
      _install_resolved(resolved, destination)
      if resolved[BundleKey.ERROR]:
        errors.append(f"plugin {pid}: served from cache ({resolved[BundleKey.ERROR]})")
      installed.append({ PluginKey.ID: pid, BundleKey.SOURCE: resolved[BundleKey.SOURCE],
                         BundleKey.VERSION: resolved[BundleKey.VERSION] })

    # captured settings land after the bundle, so the plugin reads them on first launch
    data = entry.get(PluginKey.DATA)
    if data is not None:
      dump_json(destination / VaultPath.PLUGIN_DATA, data)
  return installed


def _install_bundled(bundled: Path, destination: Path) -> str:
  """
  Copy a bundle this plugin ships into the vault.

  Args:
    bundled: Source directory inside the plugin's templates.
    destination: Per-plugin directory inside the vault.

  Returns:
    The bundled version, or an empty string when its manifest declares none.
  """
  for name in (VaultPath.PLUGIN_MANIFEST, VaultPath.PLUGIN_MAIN, VaultPath.PLUGIN_STYLES):
    source = bundled / name
    if source.is_file():
      write_bytes(destination / name, source.read_bytes())
  manifest = load_json(bundled / VaultPath.PLUGIN_MANIFEST) or {}
  return manifest.get(PluginKey.VERSION) or ""


def _install_resolved(resolved: dict, destination: Path) -> None:  # waiver: asset bytes envelope
  """
  Write a resolved bundle's assets into the vault.

  Args:
    resolved: Envelope returned by bundle resolution.
    destination: Per-plugin directory inside the vault.
  """
  write_bytes(destination / VaultPath.PLUGIN_MANIFEST, resolved[BundleKey.MANIFEST_BYTES])
  write_bytes(destination / VaultPath.PLUGIN_MAIN, resolved[BundleKey.MAIN_BYTES])
  if resolved[BundleKey.STYLES_BYTES] is not None:
    write_bytes(destination / VaultPath.PLUGIN_STYLES, resolved[BundleKey.STYLES_BYTES])


def _deploy_theme(vault: Path, theme: str | None, errors: list[str]) -> str | None:
  """
  Restore the recorded theme from the plugin's bundled themes when the vault lacks it.

  Args:
    vault: The vault's config directory.
    theme: Theme name recorded in the manifest, or None when the vault uses the default.
    errors: Accumulator for a theme neither installed nor bundled.

  Returns:
    The theme name, or None when the manifest recorded none or named one this refuses to
    join onto a path.
  """
  if not theme:
    return None
  # guard: a theme name that is not a plain name would escape the themes directory
  if not is_safe_name(theme):
    errors.append(f"theme {theme!r}: not a plain theme name, skipped")
    return None
  target = vault / VaultPath.THEMES / theme
  # guard: an already-installed theme is left exactly as it is
  if target.is_dir():
    return theme
  shipped = template_root() / VaultPath.THEMES / theme
  if not shipped.is_dir():
    errors.append(f"theme {theme!r}: not installed and not bundled — install it from Obsidian")
    return theme
  for source in shipped.iterdir():
    if source.is_file():
      write_bytes(target / source.name, source.read_bytes())
  return theme


# ----------------------------------------------------------------------------------------
def main(argv: list[str]) -> int:
  """
  Run one subcommand and print its JSON report.

  Args:
    argv: Command-line arguments without the program name.

  Returns:
    Zero when the run reported no errors, one otherwise.
  """
  # waiver: argparse CLI signature
  parser = argparse.ArgumentParser(prog = "vault_manifest", description = __doc__)
  # waiver: argparse CLI signature
  sub = parser.add_subparsers(dest = "command", required = True)
  for name, help_text in (
      (CommandKind.CAPTURE, "snapshot the vault config into the manifest"),
      (CommandKind.DEPLOY, "rebuild the vault config from the manifest"),
      (CommandKind.DRIFT, "report how the vault config differs from the manifest")):
    child = sub.add_parser(name, help = help_text)
    # waiver: argparse CLI signature
    child.add_argument("root", nargs = "?", default = ".", help = "vault repo root (default: cwd)")

  # resolve the vault root before any subcommand touches disk
  args = parser.parse_args(argv)
  root = Path(args.root).expanduser().resolve()
  handlers = { CommandKind.CAPTURE: capture, CommandKind.DEPLOY: deploy, CommandKind.DRIFT: drift }
  try:
    report = handlers[args.command](root)
  except WorkerError as error:
    print(json.dumps({ ReportKey.ACTION: args.command, ReportKey.ERRORS: [str(error)] }, indent = 2))
    return 1
  print(json.dumps(report, indent = 2, ensure_ascii = False))
  return 1 if report[ReportKey.ERRORS] else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
