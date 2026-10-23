"""Integration tests need Postgres from docker compose: `docker compose run --rm bot pytest`.

Every test gets a freshly migrated `forest_test` database; without Postgres they are skipped.
"""

import os
from pathlib import Path

import asyncpg
import numpy as np
import pytest

from forest_bot.db.migrate import run_migrations
from forest_bot.db.pool import create_pool
from forest_bot.embeddings import DIMENSIONS

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
TEST_DB = "forest_test"


def _urls() -> tuple[str, str]:
    url = os.environ.get("DATABASE_URL", "postgresql://forest:forest@localhost:5432/forest")
    base, _, _ = url.rpartition("/")
    return url, f"{base}/{TEST_DB}"


@pytest.fixture
async def pool():
    admin_url, test_url = _urls()
    try:
        admin = await asyncpg.connect(admin_url, timeout=3)
    except (OSError, asyncpg.PostgresError) as e:
        pytest.skip(f"Postgres is not available: {e}")
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        await admin.execute(f"CREATE DATABASE {TEST_DB}")
    finally:
        await admin.close()

    await run_migrations(test_url, MIGRATIONS_DIR)
    pool = await create_pool(test_url)
    yield pool
    await pool.close()


class FakeEmbedder:
    """Same vector for every text: these tests check filters and versions, not similarity."""

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [np.ones(DIMENSIONS, dtype=np.float32) for _ in texts]


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()
