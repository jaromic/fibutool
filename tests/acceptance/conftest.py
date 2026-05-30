"""pytest configuration and fixtures for acceptance tests."""
from pathlib import Path

import pytest
import yaml

from .journal_result import JournalResult


def pytest_addoption(parser):
    parser.addoption(
        "--after-xlsx",
        required=True,
        help="Path to the AFTER xlsx produced by the acceptance test pipeline run",
    )
    parser.addoption(
        "--config",
        required=True,
        help="Path to the config.yaml used in the acceptance test pipeline run",
    )


@pytest.fixture(scope="session")
def config(request) -> dict:
    path = Path(request.config.getoption("--config"))
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="session")
def result(request, config) -> JournalResult:
    path = Path(request.config.getoption("--after-xlsx"))
    return JournalResult.load(path, last_existing_receipt=config["last_receipt_number"])
