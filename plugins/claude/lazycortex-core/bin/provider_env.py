"""
Provider registry resolution and spawn-environment construction.

Resolves and validates provider registry entries declared in project settings, then builds
the environment variable overrides needed to spawn a Claude Code process against a foreign
OpenAI- or Anthropic-compatible endpoint instead of Anthropic's own.
"""
from __future__ import annotations

import os
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import EnvVar, SettingsFile, SettingsKey  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


PROVIDER_TIERS = ( "fable", "opus", "sonnet", "haiku" )

_TIER_ENV = {
  "fable":  "ANTHROPIC_DEFAULT_FABLE_MODEL",
  "opus":   "ANTHROPIC_DEFAULT_OPUS_MODEL",
  "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
  "haiku":  "ANTHROPIC_DEFAULT_HAIKU_MODEL",
}


class ProviderKey:
  """
  Field-key holder for one provider configuration block.

  Attributes:
    NAME: The key naming the provider entry's dict field.
    BASE_URL: The key naming the provider's endpoint URL field.
    TOKEN_ENV: The key naming the field holding the auth token's environment variable name.
    MODELS: The key naming the field mapping each tier in `PROVIDER_TIERS` to a model alias.
  """
  # The key naming the provider entry's dict field.
  NAME = "name"
  # The key naming the provider's endpoint URL field.
  BASE_URL = "base_url"
  # The key naming the field holding the auth token's environment variable name.
  TOKEN_ENV = "token_env"
  # The key naming the field mapping each tier in `PROVIDER_TIERS` to a model alias.
  MODELS = "models"


class ProviderConfigError(ValueError):
  """
  Configuration error for an invalid provider registry entry.

  Raised for an entry that is missing, incomplete, or violates a naming constraint —
  for example a literal `claude-*` model alias, or the `openai` provider's tiers omitting
  the required `rt-openai/` prefix.
  """
  pass


def validate_entry(name: str, entry: object) -> dict:
  """
  Validate one provider entry and resolve it to a configuration block.

  Confirms a provider configuration is complete and safe to spawn against, independent
  of any settings file, so a candidate configuration can be checked before it is ever
  persisted.

  Args:
    name: Provider key the entry is declared under, used to identify it in error messages.
    entry: Candidate provider configuration to validate.

  Returns:
    The resolved configuration block, with every tier in `PROVIDER_TIERS` covered and
    stringified.

  Raises:
    ProviderConfigError: If `entry` is not a dict, if `base_url` or `token_env` is missing
      or blank, if any tier in `PROVIDER_TIERS` is missing from `models`, if any tier value
      starts with `claude-`, or if `name` is `openai` and any tier value does not start
      with `rt-openai/`.
  """
  # guard: a provider the settings never declared cannot be spawned against
  if not isinstance(entry, dict):
    raise ProviderConfigError(f"provider {name!r} is not declared in settings [providers]")

  # both endpoint facts are mandatory strings — a blank one would silently spawn against Anthropic
  base_url = entry.get(ProviderKey.BASE_URL)
  token_env = entry.get(ProviderKey.TOKEN_ENV)

  # guard: refuse a partial endpoint declaration
  if not base_url or not isinstance(base_url, str):
    raise ProviderConfigError(f"provider {name!r}: base_url is required")

  # guard: refuse a provider with no named token variable
  if not token_env or not isinstance(token_env, str):
    raise ProviderConfigError(f"provider {name!r}: token_env is required")

  # Domain(runtime.providers):
  # # Foreign-provider routing completeness
  # Spawning against a non-Anthropic endpoint only works when every model-selection surface the
  # harness can address is pinned to that provider's own alias; a gap falls through to the
  # literal Claude alias name, and a literal Claude name is meaningless to a foreign endpoint —
  # the spawn ends up silently talking to whatever the endpoint treats that name as, not to what
  # the operator configured. A provider's model mapping must therefore cover every tier the
  # harness can emit, and none of those tiers may be a literal Claude-owned name. The one
  # provider that also serves the operator's own interactive traffic under a separate route
  # additionally requires every runtime-facing tier to carry that route's own prefix, so
  # automated work can never be misrouted onto the operator's personal route by omission.

  # the tier map must cover every alias the harness can emit, or an uncovered
  # tier leaks to the foreign endpoint under its Claude alias name
  models = entry.get(ProviderKey.MODELS) or {}
  missing = [ tier for tier in PROVIDER_TIERS if not models.get(tier) ]

  # guard: incomplete tier coverage
  if missing:
    raise ProviderConfigError(f"provider {name!r}: models must cover tiers {missing}")

  # literal claude-* pins do not pass through a foreign endpoint or the proxy
  # waiver: the claude-* namespace is Anthropic's, checked as an opaque prefix — a constant
  # would restate it without adding meaning
  bad_literal = [ tier for tier in PROVIDER_TIERS if str(models[tier]).startswith("claude-") ]

  # guard: claude-* literals are Anthropic-only names
  if bad_literal:
    raise ProviderConfigError(f"provider {name!r}: claude-* literal in tiers {bad_literal}")

  # Decision: the rt-openai/ prefix rule is named for the one provider it governs, not
  # generalised into config — the proxy reserves openai/* for the interactive key and the
  # runtime must never borrow it (spec, section Validation and Rejections — see lazy-core.provider-abstraction spec).

  # the openai/* route is the operator's interactive key — runtime traffic must never borrow it
  if name == "openai":
    # waiver: proxy route names fixed by the LiteLLM contract, not this module's vocabulary
    off_prefix = [ tier for tier in PROVIDER_TIERS if not str(models[tier]).startswith("rt-openai/") ]

    # guard: runtime traffic must ride the rt-openai/ wildcard route only
    if off_prefix:
      raise ProviderConfigError(f"provider 'openai': tiers {off_prefix} must use the rt-openai/ prefix")

  # the resolved block is the config.json snapshot shape the pump consumes verbatim
  return {
    ProviderKey.NAME: name,
    ProviderKey.BASE_URL: base_url,
    ProviderKey.TOKEN_ENV: token_env,
    ProviderKey.MODELS: { tier: str(models[tier]) for tier in PROVIDER_TIERS },
  }


# waiver: `model` is typed `object` because it is the raw, unvalidated settings value — any JSON type can
# arrive, and rejecting a non-tier value of any type is this function's job
def validate_expert_model(name: str, model: object) -> None:
  """
  Validate the explicit model pinned on an expert bound to a provider.

  Guarantees:
    - A set `model` that is not one of the tier aliases in `PROVIDER_TIERS` always raises
      `ProviderConfigError`.
    - An unset `model` always passes.

  Args:
    name: Provider key the expert is bound to, used to identify it in the error message.
    model: The expert's own `model` value, or a falsy value when the expert pins none.

  Raises:
    ProviderConfigError: If `model` is set and is not one of the tier aliases in `PROVIDER_TIERS`.
  """

  # Contract:
  # A provider-bound expert's explicit `model` MUST be one of the tier aliases, otherwise
  # `ProviderConfigError` is raised; an expert that pins no model MUST pass.

  # Domain(runtime.providers):
  # # A provider-bound expert names a tier, never a model
  # An expert sent to a foreign endpoint reaches that endpoint's models only through the provider's
  # tier map, so the one model choice it may make for itself is which tier to run on. A full model
  # name pinned on the expert would skip the map: a Claude-owned name would reach an endpoint that
  # does not know it, and a hand-written route name could borrow a route reserved for other traffic.
  # An expert that pins nothing takes its agent's tier, which is already a tier.

  # guard: no explicit model — the agent's tier applies, and a tier always passes through the map
  if not model:
    return

  # guard: only a tier alias reaches the provider's tier map
  if model not in PROVIDER_TIERS:
    raise ProviderConfigError(
      f"provider {name!r}: expert model {model!r} must be one of the tier aliases {list(PROVIDER_TIERS)}"
    )


def resolve_provider(repo: Path, name: str) -> dict:
  """
  Resolve and validate the named provider entry from project settings.

  Args:
    repo: Absolute path to the repository whose settings hold the providers registry.
    name: Provider key to look up in the registry.

  Returns:
    The resolved configuration block, with every tier in `PROVIDER_TIERS` covered and
    stringified.

  Raises:
    ProviderConfigError: Under the same conditions as `validate_entry`, including when
      `name` is not declared in settings.
  """
  # the merged providers registry is the single source of truth for endpoints
  providers = load_section(Path(repo) / SettingsFile.REL, SettingsKey.PROVIDERS)
  return validate_entry(name, providers.get(name))


def resolve_token(token_env: str, *, env_file: Path | None = None) -> str | None:
  """
  Resolve a provider's auth token from the environment or a fallback file.

  Checks the process environment first, then falls back to reading an env file, favoring
  its last assignment of the variable when several are present.

  Guarantees:
    - The process environment always takes precedence over the fallback file.
    - When the fallback file is read, its last assignment of the variable wins over earlier ones.

  Args:
    token_env: Name of the environment variable that carries the provider's token.
    env_file: Fallback file to read when the token is not in the process environment;
      defaults to `~/.claude/.env`.

  Returns:
    The resolved token, or `None` if it is found in neither place.
  """

  # Contract:
  # The process environment MUST take precedence over the fallback env file; when the file
  # is consulted and holds several assignments of the same variable, the last one MUST win.

  # check process environment first
  value = os.environ.get(token_env)

  # the process environment wins — an exported token is this run's explicit choice, the file only a fallback
  if value:
    return value

  # resolve the env file path (override or daemon-canonical default)
  # waiver: .claude, .env paths are daemon-canonical, not config
  path = env_file if env_file is not None else Path.home() / ".claude" / ".env"

  # guard: no fallback file means no token
  if not path.is_file():
    return None

  # parse the env file, favoring the last assignment of the variable
  for line in reversed(path.read_text(encoding = "utf-8").splitlines()):
    # waiver: export prefix and quote chars are file-format literals
    stripped = line.strip().removeprefix("export ").strip()
    if stripped.startswith(f"{token_env}="):
      return (
        stripped.split("=", 1)[1].strip().strip('"').strip("'") or None
      )
  return None


def build_spawn_env(provider: dict, token: str) -> dict[str, str]:
  """
  Build the environment variable overrides needed to spawn against a provider's endpoint.

  Guarantees:
    - Every model-selection surface the harness can address is redirected to the provider,
      including a built-in subagent that names no tier of its own.

  Notes:
    - Removing `CLAUDE_CODE_OAUTH_TOKEN` from the caller's environment remains the
      caller's own responsibility; this function only adds variables.

  Args:
    provider: Resolved provider configuration block to spawn against.
    token: Auth token to use for this provider's endpoint.

  Returns:
    The environment variable overrides to apply — tier-alias remaps, `ANTHROPIC_BASE_URL`,
    `ANTHROPIC_AUTH_TOKEN`, and `CLAUDE_CODE_SUBAGENT_MODEL`.
  """

  # Contract:
  # The returned overrides MUST redirect every model-selection surface the harness can
  # address to the given provider — including a built-in subagent that names no tier of
  # its own — so no request tied to this provider can fall back to the operator's own
  # Anthropic account.

  # build tier-to-env mappings for model selection aliases
  # the alias-remap variables cover --model tiers AND subagent frontmatter tiers;
  # CLAUDE_CODE_SUBAGENT_MODEL backstops built-in subagents with no model: at all
  models = provider[ProviderKey.MODELS]
  overrides = { _TIER_ENV[tier]: models[tier] for tier in PROVIDER_TIERS }

  # add the provider endpoint and token
  # waiver: ANTHROPIC_BASE_URL is a harness-canonical env var name
  overrides["ANTHROPIC_BASE_URL"] = provider[ProviderKey.BASE_URL]
  # waiver: ANTHROPIC_AUTH_TOKEN is a harness-canonical env var name
  overrides["ANTHROPIC_AUTH_TOKEN"] = token

  # Domain(runtime.providers):
  # # Subagent backstop against routing completeness
  # A built-in subagent that names no tier of its own is not covered by the per-tier alias
  # remaps above, so left alone it would run against the harness's own default model — an
  # Anthropic model, reached even while the job around it is deliberately spawned against a
  # foreign endpoint. Pinning every such subagent to one fixed, provider-specific tier closes
  # that last gap, so no subagent of a foreign-endpoint job can fall back onto the operator's
  # own account.

  # Decision: sonnet tier backstops built-in subagents (not haiku, not the job's own tier) —
  # mid-tier matches the harness's own subagent default class; the backstop must be
  # deterministic per provider map

  # pin the subagent default so every foreign-endpoint job gets the same deterministic backstop
  # waiver: CLAUDE_CODE_SUBAGENT_MODEL is a harness-canonical env var name
  overrides["CLAUDE_CODE_SUBAGENT_MODEL"] = models["sonnet"]
  return overrides


# waiver: `daemon_token_env` is typed `object` because it is the raw `daemon.token_env` settings value — any
# JSON type can arrive, and a non-string is treated as unset
def apply_spawn_env(env: dict[str, str], provider: dict, token: str, *, daemon_token_env: object) -> None:
  """
  Point a spawn environment at a provider's endpoint and strip the operator's own credentials from it.

  Guarantees:
    - Every override `build_spawn_env` returns is present, so every model-selection surface the
      harness can address is redirected to the provider.
    - Neither the operator's Anthropic credentials, nor the daemon's own token variable, nor its token
      digest marker remain in the environment.

  Args:
    env: Spawn environment to rewrite in place.
    provider: Resolved provider configuration block to spawn against.
    token: Auth token to use for this provider's endpoint.
    daemon_token_env: The `daemon.token_env` settings value naming the daemon's own token variable, or any
      non-string value when none is configured.
  """

  # Contract:
  # The rewritten environment MUST carry every override `build_spawn_env` returns, so every
  # model-selection surface the harness can address is redirected to the provider.

  # Contract:
  # The rewritten environment MUST NOT carry `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, the
  # daemon's token digest marker, or the variable `daemon_token_env` names — no credential of
  # the operator's own reaches a foreign endpoint.

  # redirect every model-selection surface to the provider
  env.update(build_spawn_env(provider, token))

  # the Anthropic OAuth token and API key must never travel to a foreign endpoint
  # waiver: CLAUDE_CODE_OAUTH_TOKEN and ANTHROPIC_API_KEY are harness-canonical env var names
  env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
  # waiver: ANTHROPIC_API_KEY is a harness-canonical env var name
  env.pop("ANTHROPIC_API_KEY", None)

  # nor may the daemon's own token source variable or its digest marker
  env.pop(EnvVar.DAEMON_TOKEN_MARK, None)
  if isinstance(daemon_token_env, str) and daemon_token_env.strip():
    env.pop(daemon_token_env.strip(), None)
