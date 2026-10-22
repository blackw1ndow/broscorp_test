import asyncpg
from pgvector.asyncpg import register_vector


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Must be called after migrations: the vector type has to exist already."""
    return await asyncpg.create_pool(database_url, min_size=1, max_size=5, init=_init_connection)
