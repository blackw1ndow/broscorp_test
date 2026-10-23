"""aiogram FSM storage in Postgres: a pending question or document survives a bot restart."""

import json
from collections.abc import Mapping
from typing import Any

import asyncpg
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import (
    BaseStorage,
    DefaultKeyBuilder,
    KeyBuilder,
    StateType,
    StorageKey,
)


class PostgresStorage(BaseStorage):
    def __init__(self, pool: asyncpg.Pool, key_builder: KeyBuilder | None = None) -> None:
        self._pool = pool
        self._key_builder = key_builder or DefaultKeyBuilder()

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        await self._pool.execute(
            """
            INSERT INTO fsm_state (key, state) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET state = EXCLUDED.state
            """,
            self._key_builder.build(key),
            value,
        )

    async def get_state(self, key: StorageKey) -> str | None:
        return await self._pool.fetchval(
            "SELECT state FROM fsm_state WHERE key = $1", self._key_builder.build(key)
        )

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await self._pool.execute(
            """
            INSERT INTO fsm_state (key, data) VALUES ($1, $2::jsonb)
            ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data
            """,
            self._key_builder.build(key),
            json.dumps(dict(data), ensure_ascii=False),
        )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        raw = await self._pool.fetchval(
            "SELECT data FROM fsm_state WHERE key = $1", self._key_builder.build(key)
        )
        return json.loads(raw) if raw else {}

    async def close(self) -> None:
        # The pool belongs to the application and is closed there
        pass
