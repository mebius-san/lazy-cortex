"""
Centralized names for the vault-manifest worker.

The worker moves the same fixed vocabulary — Obsidian's on-disk filenames, the manifest's
own keys, the report envelope printed on stdout — across capture, deploy, and their tests.
Defining each name once here means a typo surfaces as an `AttributeError` at import time
rather than as a silently skipped plugin or a manifest key nobody reads back.
"""
from __future__ import annotations

from enum import StrEnum

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class VaultPath:
  """
  Names of the files and directories Obsidian keeps inside a vault's config directory.

  Attributes:
    OBSIDIAN: The vault config directory itself, at the repo root.
    MANIFEST: The tracked manifest file this worker owns, at the repo root.
    SNIPPETS: Directory holding CSS snippets.
    PLUGINS: Directory holding one subdirectory per community plugin.
    THEMES: Directory holding one subdirectory per installed theme.
    PLUGIN_MANIFEST: Per-plugin manifest naming the plugin's id and version.
    PLUGIN_MAIN: Per-plugin bundle entry point.
    PLUGIN_STYLES: Per-plugin optional stylesheet.
    PLUGIN_DATA: Per-plugin settings file.
    COMMUNITY_PLUGINS: List of enabled plugin ids, rebuilt by deploy.
    APPEARANCE: Theme, accent, and enabled-snippet settings.
    TMP_SUFFIX: Suffix of the scratch file every atomic write renames from.
    CSS_GLOB: Glob matching snippet files.
    JSON_GLOB: Glob matching top-level config files.
  """

  OBSIDIAN = ".obsidian"
  MANIFEST = ".obsidian.manifest.json"
  SNIPPETS = "snippets"
  PLUGINS = "plugins"
  THEMES = "themes"
  PLUGIN_MANIFEST = "manifest.json"
  PLUGIN_MAIN = "main.js"
  PLUGIN_STYLES = "styles.css"
  PLUGIN_DATA = "data.json"
  COMMUNITY_PLUGINS = "community-plugins.json"
  APPEARANCE = "appearance.json"
  TMP_SUFFIX = ".tmp"
  CSS_GLOB = "*.css"
  JSON_GLOB = "*.json"


# ----------------------------------------------------------------------------------------
class TemplatePath:
  """
  Path segments of the vault assets this plugin ships for deploy to restore from.

  Attributes:
    ROOT: Template directory under the plugin root.
    VAULT: Vault-shaped subtree inside the template directory.
  """

  ROOT = "templates"
  VAULT = "obsidian"


# ----------------------------------------------------------------------------------------
class CachePath:
  """
  Path segments of the persistent bundle cache, rooted at the XDG cache directory.

  Attributes:
    DEFAULT_ROOT: Fallback cache root when XDG_CACHE_HOME is unset.
    NAMESPACE: This plugin's directory inside the cache root.
    BUNDLES: Directory holding one vendored plugin bundle per id.
    CATALOG: Cached copy of the community-plugin catalog.
  """

  DEFAULT_ROOT = ".cache"
  NAMESPACE = "lazycortex-obsidian"
  BUNDLES = "plugin-bundles"
  CATALOG = "community-plugins.json"


# ----------------------------------------------------------------------------------------
class ManifestKey:
  """
  Top-level keys of `.obsidian.manifest.json`.

  Attributes:
    VERSION: Schema version of the manifest itself.
    GROUP: Palette group the vault was created from, carried as metadata.
    THEME: Name of the theme the vault renders with.
    CONFIG: Map of top-level Obsidian config filename to its whole content.
    SNIPPETS: Map of snippet filename to its provenance and body.
    PLUGINS: Map of plugin id to its enablement, captured version, and settings.
    SECRETS_OMITTED: Dotted paths of secret-looking values capture refused to record.
  """

  VERSION = "manifest_version"
  GROUP = "group"
  THEME = "theme"
  CONFIG = "config"
  SNIPPETS = "snippets"
  PLUGINS = "plugins"
  SECRETS_OMITTED = "secrets_omitted"


# ----------------------------------------------------------------------------------------
class PluginKey:
  """
  Keys of one plugin's entry in the manifest, and of a plugin's own manifest file.

  Attributes:
    ENABLED: Whether the vault has the plugin turned on.
    CAPTURED_VERSION: Version installed when the snapshot was taken; a warning source only.
    DATA: The plugin's whole settings payload, or None when its state is derived.
    REPO: Explicit `owner/name` override for a plugin outside the community catalog.
    ID: Plugin id as declared by the plugin's own manifest.
    VERSION: Plugin version as declared by the plugin's own manifest.
  """

  ENABLED = "enabled"
  CAPTURED_VERSION = "captured_version"
  DATA = "data"
  REPO = "repo"
  ID = "id"
  VERSION = "version"


# ----------------------------------------------------------------------------------------
class SnippetKey:
  """
  Keys of one snippet's entry in the manifest.

  Attributes:
    SOURCE: Who owns the snippet — this plugin, or the vault.
    BODY: The snippet's CSS, recorded only for vault-owned snippets.
  """

  SOURCE = "source"
  BODY = "body"


# ----------------------------------------------------------------------------------------
class SnippetSourceKind(StrEnum):
  """
  Values of a snippet entry's `source` key.

  Attributes:
    PLUGIN: Byte-identical to what this plugin ships; deploy re-copies it from the plugin.
    VAULT: Personal or edited; deploy writes the body recorded in the manifest.
  """

  PLUGIN = "plugin"
  VAULT = "vault"
  INVALID = "~inv~"


# ----------------------------------------------------------------------------------------
class BundleKey:
  """
  Keys of the envelope describing one resolved plugin bundle.

  Attributes:
    SOURCE: Where the bundle came from.
    VERSION: Version of the resolved bundle.
    MANIFEST_BYTES: Raw bytes of the plugin's manifest file.
    MAIN_BYTES: Raw bytes of the plugin's bundle entry point.
    STYLES_BYTES: Raw bytes of the plugin's stylesheet, or None when it ships none.
    ERROR: Why upstream was not used, set whenever a fallback was needed.
  """

  SOURCE = "source"
  VERSION = "version"
  MANIFEST_BYTES = "manifest_bytes"
  MAIN_BYTES = "main_bytes"
  STYLES_BYTES = "styles_bytes"
  ERROR = "error"


# ----------------------------------------------------------------------------------------
class BundleSourceKind(StrEnum):
  """
  Values of a resolved bundle's `source` key.

  Attributes:
    UPSTREAM: Fetched from the plugin's GitHub release.
    CACHE: Served from the vendored cache after upstream failed.
    BUNDLED: Copied from what this plugin ships, for plugins with no public release.
    NONE: Nothing could be resolved; the plugin was skipped.
  """

  # Domain(obsidian.plugin-bundling):
  # # Plugin bundle resolution fallback ladder
  # A community plugin's install bundle is resolved by trying, in order: the plugin's live upstream
  # release, then a copy vendored in the local cache from an earlier successful resolution, then a
  # copy bundled with this plugin for a plugin with no public release to fall back to, and finally
  # nothing when none of those has the bundle. Each source is pinned to the plugin's own id, so a
  # repository that has been renamed or repurposed can never serve as the bundle source for a
  # different plugin id than the one it originally shipped.

  UPSTREAM = "upstream"
  CACHE = "cache"
  BUNDLED = "bundled"
  NONE = "none"
  INVALID = "~inv~"


# ----------------------------------------------------------------------------------------
class ReportKey:
  """
  Keys of the JSON report the worker prints on stdout.

  Attributes:
    ACTION: Which subcommand produced the report.
    MANIFEST: Absolute path of the manifest written.
    CONFIG_FILES: Config filenames captured or deployed.
    SNIPPETS: Snippet filenames captured or written.
    PLUGINS: Plugin ids captured, or per-plugin install records on deploy.
    THEME: Theme name deploy restored or left in place.
    SECRETS_OMITTED: Dotted paths of values never recorded.
    DRIFT: Differences between the live config and what the manifest records.
    WARNINGS: Conditions worth the operator's attention that are not drift.
    ERRORS: Conditions the operator must resolve; a non-empty list fails the run.
  """

  # Domain(obsidian.vault-capture):
  # # Report severity model
  # The worker's report carries two independent kinds of condition worth surfacing after a run.
  # A warning names something the operator may want to look at, but the run still succeeded and
  # nothing about it needs fixing before the vault can be trusted. An error names something the
  # operator must resolve; a report carrying even one error means the run as a whole failed,
  # regardless of how much of the work it otherwise completed.

  ACTION = "action"
  MANIFEST = "manifest"
  CONFIG_FILES = "config_files"
  SNIPPETS = "snippets"
  PLUGINS = "plugins"
  THEME = "theme"
  SECRETS_OMITTED = "secrets_omitted"
  DRIFT = "drift"
  WARNINGS = "warnings"
  ERRORS = "errors"


# ----------------------------------------------------------------------------------------
class AppearanceKey:
  """
  Keys read out of Obsidian's appearance settings.

  Attributes:
    CSS_THEME: Name of the active theme.
    ZOOM_FACTOR: Window zoom, a per-device value never captured.
  """

  # Domain(obsidian.vault-capture):
  # # Device-local settings excluded from portable capture
  # A vault's captured configuration is meant to travel unchanged across machines and devices, so a
  # setting that only reflects the specific device or window the vault happened to be open on has no
  # place in it. The window zoom factor is such a setting: it is never written into the captured
  # record, so restoring the configuration on a different device leaves that device's own zoom
  # exactly where it already was rather than overwriting it with a value that belonged elsewhere.

  CSS_THEME = "cssTheme"
  ZOOM_FACTOR = "zoomFactor"


# ----------------------------------------------------------------------------------------
class CommandKind(StrEnum):
  """
  Subcommand names accepted on the worker's command line.

  Attributes:
    CAPTURE: Snapshot the vault config into the manifest.
    DEPLOY: Rebuild the vault config from the manifest.
    DRIFT: Report how the live vault config differs from the manifest, writing nothing.
  """

  CAPTURE = "capture"
  DEPLOY = "deploy"
  DRIFT = "drift"
  INVALID = "~inv~"


# ----------------------------------------------------------------------------------------
class Http:
  """
  Header names, media types, and environment variables used when fetching bundles.

  Attributes:
    ACCEPT: Accept header name.
    USER_AGENT: User-Agent header name.
    AUTHORIZATION: Authorization header name.
    AGENT_VALUE: User-Agent value identifying this worker upstream.
    JSON: Media type for catalog and manifest requests.
    OCTET_STREAM: Media type for release-asset downloads.
    ENV_TOKENS: Environment variables consulted for a GitHub token, in order.
    TOKEN_HOSTS: Hosts whose requests carry the token.
  """

  # Domain(obsidian.plugin-bundling):
  # # Credential scope for bundle fetches
  # A GitHub token, once found, is never attached to every outgoing request — only to a request
  # aimed at one of a fixed set of known GitHub hosts. A URL outside that set never carries the
  # token, however the token was obtained, so a compromised or unexpected release location can
  # never harvest the operator's credential merely by being asked for a bundle. When more than
  # one source of a token is available, the value already sitting in the environment always wins
  # over the one behind an external command, since reading the environment carries no risk of
  # side effects.

  ACCEPT = "Accept"
  USER_AGENT = "User-Agent"
  AUTHORIZATION = "Authorization"
  AGENT_VALUE = "lazycortex-obsidian/1.0"
  JSON = "application/json"
  OCTET_STREAM = "application/octet-stream"
  ENV_TOKENS = ("GH_TOKEN", "GITHUB_TOKEN")
  TOKEN_HOSTS = ("api.github.com", "github.com", "raw.githubusercontent.com")


# ----------------------------------------------------------------------------------------
class Encoding:
  """
  Text encodings used when reading and writing vault files.

  Attributes:
    UTF8: The only encoding Obsidian writes, and the one every file is read as.
  """

  UTF8 = "utf-8"
