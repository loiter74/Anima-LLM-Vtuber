"""Conftest for integration tests.

Auto-marks every test in this directory with @pytest.mark.integration so the
default pytest invocation (which uses `-m "not slow and not integration"`)
excludes them. Integration tests require a running server on port 12394 and
should be run separately with: pytest tests/integration/ -m integration
"""

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-mark only tests located under tests/integration/ with the integration marker."""
    integration_marker = pytest.mark.integration
    for item in items:
        # Only mark items whose file path is under tests/integration/
        if "integration" in str(item.fspath).replace("\\", "/"):
            item.add_marker(integration_marker)
