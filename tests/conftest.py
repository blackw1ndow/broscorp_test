from pathlib import Path

import pytest

ARCHIVE_DIR = Path(__file__).resolve().parents[1] / "archive"


@pytest.fixture
def archive_dir() -> Path:
    return ARCHIVE_DIR
