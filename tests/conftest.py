# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for charm tests."""


def pytest_addoption(parser):
    """Parse additional pytest options.

    Args:
        parser: Pytest parser.
    """
    parser.addoption("--charm-file", action="store")
    # no-op: CI reusable workflows still pass --keep-models.
    # pytest-jubilant already registers it, so only add if missing.
    try:
        parser.addoption("--keep-models", action="store_true", default=False)
    except ValueError:
        pass
