"""Test configuration: make the shared ``_harness`` module importable from any test directory.

pytest puts each test file's own directory on ``sys.path`` (prepend import mode), so a test under
``tests/browser/`` could not otherwise ``import _harness`` from ``tests/``. Inserting the ``tests``
directory here — before any test module is collected — lets every test share the one harness.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest
from jsonschema import Draft7Validator

from _harness import czml_validator as _build_validator


@pytest.fixture(scope="session")
def czml_validator() -> Draft7Validator:
    """The official-CZML-schema validator, built once per session (187 vendored schema files)."""
    return _build_validator()
