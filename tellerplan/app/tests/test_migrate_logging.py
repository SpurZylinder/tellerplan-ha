"""Die Migration beim Start darf das Logging der App nicht verstellen."""

import logging
from collections.abc import Iterator

import pytest

from migrate import upgrade_to_head
from settings import Settings


@pytest.fixture
def root_at_info() -> Iterator[logging.Logger]:
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.INFO)
    yield root
    root.setLevel(old_level)


def test_upgrade_keeps_the_app_log_level(root_at_info: logging.Logger, settings: Settings) -> None:
    upgrade_to_head(settings, skip_data_migrations=True)

    assert root_at_info.level == logging.INFO
    assert logging.getLogger("settings").isEnabledFor(logging.INFO)
