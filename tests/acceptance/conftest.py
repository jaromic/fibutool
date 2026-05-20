"""pytest configuration and fixtures for acceptance tests."""
from pathlib import Path
import pytest
from .journal_result import JournalResult

LAST_EXISTING_RECEIPT = 10


def pytest_addoption(parser):
    parser.addoption(
        "--after-xlsx",
        required=True,
        help="Path to the AFTER xlsx produced by the acceptance test pipeline run",
    )


@pytest.fixture(scope="session")
def result(request) -> JournalResult:
    path = Path(request.config.getoption("--after-xlsx"))
    return JournalResult.load(path, last_existing_receipt=LAST_EXISTING_RECEIPT)
