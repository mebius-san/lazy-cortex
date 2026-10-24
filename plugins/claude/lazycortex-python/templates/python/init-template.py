"""
<PACKAGE_SUMMARY_ONE_SENTENCE>

<PACKAGE_EXTENDED_DESCRIPTION_OPTIONAL_1_TO_3_SENTENCES_ON_ROLE_AND_MEMBER_PATTERN>

This template encodes coding_guidelines.md § __init__.py File Patterns.
Replace placeholders, omit empty sections entirely, and remove this
authoring block. Never enumerate the package's submodules, subpackages,
or classes by name — the import chain is the inventory. Module
docstrings are required in __init__.py and optional elsewhere — a
regular source file that defines classes scaffolds from
python-template.py without one.
"""
from __future__ import annotations

from .submodule import *
