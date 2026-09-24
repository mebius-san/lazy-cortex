"""
Provider-registry verbs for the `lazycortex-core` CLI.

This module backs the `provider-validate` / `provider-token` subcommands the
`lazy-core.providers` and `lazy-core.doctor` skills call instead of embedding Python:
`provider-validate` checks one candidate provider entry against the registry schema and
prints the error list as JSON, `provider-token` reports whether a provider's auth token is
resolvable and, on request, prints the token itself for a shell to splice into a request
header.
"""
from __future__ import annotations

import argparse
import json

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from provider_env import ProviderConfigError, resolve_token, validate_entry  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def cmd_provider_validate(argv: list[str]) -> int:
  """
  Run the `provider-validate` subcommand: print the entry's error list as JSON.

  Args:
    argv: Argument vector after the subcommand name (provider name plus `--entry <json>`).

  Returns:
    Process exit code: 0 when the entry is valid, 1 when it is malformed or invalid.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the provider name and its candidate entry
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core provider-validate")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("name")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--entry", required = True, help = "Candidate provider entry as a JSON object")
  args = parser.parse_args(argv)

  # a malformed entry is reported in the same list shape as a schema error, never as a traceback
  try:
    entry = json.loads(args.entry)
  except json.JSONDecodeError as error:
    print(json.dumps([ f"entry parse: {error}" ]))
    return 1

  # a schema rejection is reported in the same list shape, one message per run
  try:
    validate_entry(args.name, entry)
  except ProviderConfigError as error:
    print(json.dumps([ str(error) ]))
    return 1

  # a valid entry prints an empty list so the caller can test emptiness rather than parse prose
  print(json.dumps([]))
  return 0


def cmd_provider_token(argv: list[str]) -> int:
  """
  Run the `provider-token` subcommand: report whether a provider token resolves.

  Args:
    argv: Argument vector after the subcommand name (env-var name plus optional `--print`).

  Returns:
    Process exit code: 0 when the token is present, 1 when it is missing.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the token's env-var name and the echo switch
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core provider-token")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("token_env")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--print", dest = "print_value", action = "store_true",
                      help = "Print the token value instead of present/missing")
  args = parser.parse_args(argv)

  # guard: a missing token prints the outcome word even under --print so a shell splice stays visible
  if not (token := resolve_token(args.token_env)):
    # waiver: CLI outcome token read by the calling skill, not a reusable domain key
    print("missing")
    return 1

  # a present token is echoed only on request; the outcome word is the default
  # waiver: CLI outcome token read by the calling skill, not a reusable domain key
  print(token if args.print_value else "present")
  return 0
