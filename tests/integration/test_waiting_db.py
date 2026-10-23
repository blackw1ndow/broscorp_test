"""Documents waiting for the animal's answer (D26): each waits on its own, none is overwritten."""

import asyncio

import pytest

from forest_bot.db.repositories import users, waiting

pytestmark = pytest.mark.db

ANIMAL = 101
OTHER_ANIMAL = 202


@pytest.fixture
async def conn(pool):
    async with pool.acquire() as conn:
        await users.ensure_user(conn, ANIMAL)
        await users.ensure_user(conn, OTHER_ANIMAL)
        yield conn


async def test_a_waiting_document_is_taken_once_and_only_by_its_animal(conn):
    first = await waiting.add(conn, ANIMAL, waiting.PLACE, {"title": "Внески"})
    second = await waiting.add(conn, ANIMAL, waiting.PLACE, {"title": "Стежки"})

    assert await waiting.take(conn, OTHER_ANIMAL, waiting.PLACE, first) is None
    assert await waiting.take(conn, ANIMAL, waiting.PLACE, first) == {"title": "Внески"}
    # A second press of the same button finds nothing
    assert await waiting.take(conn, ANIMAL, waiting.PLACE, first) is None
    assert await waiting.take(conn, ANIMAL, waiting.PLACE, second) == {"title": "Стежки"}


async def test_a_document_waiting_for_the_name_is_not_taken_by_a_place_button(conn):
    for_name = await waiting.add(conn, ANIMAL, waiting.NAME, {"file_id": "f1"})
    assert await waiting.take(conn, ANIMAL, waiting.PLACE, for_name) is None


async def test_all_documents_waiting_for_the_name_come_back_in_order(conn):
    await waiting.add(conn, ANIMAL, waiting.NAME, {"file_id": "f1"})
    await waiting.add(conn, ANIMAL, waiting.PLACE, {"title": "Внески"})
    await waiting.add(conn, ANIMAL, waiting.NAME, {"file_id": "f2"})
    await waiting.add(conn, OTHER_ANIMAL, waiting.NAME, {"file_id": "f3"})

    assert await waiting.take_all(conn, ANIMAL, waiting.NAME) == [
        {"file_id": "f1"},
        {"file_id": "f2"},
    ]
    assert await waiting.take_all(conn, ANIMAL, waiting.NAME) == []
    assert await waiting.take_all(conn, OTHER_ANIMAL, waiting.NAME) == [{"file_id": "f3"}]


async def test_drop_all_forgets_every_waiting_document_of_the_animal(conn):
    await waiting.add(conn, ANIMAL, waiting.NAME, {"file_id": "f1"})
    await waiting.add(conn, ANIMAL, waiting.PLACE, {"title": "Внески"})
    other = await waiting.add(conn, OTHER_ANIMAL, waiting.PLACE, {"title": "Стежки"})

    assert await waiting.drop_all(conn, ANIMAL) == 2
    assert await waiting.drop_all(conn, ANIMAL) == 0
    assert await waiting.take(conn, OTHER_ANIMAL, waiting.PLACE, other) == {"title": "Стежки"}


async def test_an_album_processed_in_parallel_keeps_every_document(pool, conn):
    async def add(title: str) -> int:
        async with pool.acquire() as c:
            return await waiting.add(c, ANIMAL, waiting.PLACE, {"title": title})

    ids = await asyncio.gather(*(add(f"Документ {i}") for i in range(3)))

    taken = [await waiting.take(conn, ANIMAL, waiting.PLACE, i) for i in ids]
    assert taken == [{"title": f"Документ {i}"} for i in range(3)]
