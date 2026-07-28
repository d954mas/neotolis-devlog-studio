"""Studio v3 test configuration."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "slow: real-subprocess or timing-sensitive test",
    )
