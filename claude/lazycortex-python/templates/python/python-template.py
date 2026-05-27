"""
<MODULE_SUMMARY_ONE_SENTENCE>

<MODULE_EXTENDED_DESCRIPTION_OPTIONAL>

This template encodes coding_guidelines.md § Module Structure +
§ Import Organization. Replace placeholders, remove this scaffolding
docstring's authoring block, and start filling in real content.
"""
from __future__ import annotations

# typing imports (block 3)
# from typing import TypeVar, Generic

# standard library imports (block 4)
# from pathlib import Path

# third-party imports (block 5)
# import numpy as np

# local project imports (block 6)
# from myproject.core import BaseClass

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# module-level constants, TypeVars, TypeAliases, enums go here.


# ----------------------------------------------------------------------------------------
class ExampleClass:
  """
  <CLASS_SUMMARY_ONE_SENTENCE>

  <CLASS_EXTENDED_DESCRIPTION_OPTIONAL>
  """

  def __init__(self, *, name: str) -> None:
    self.name: str = name
