"""Voice, photos, stickers and the rest: the bot explains what it understands (D10)."""

from aiogram import F, Router
from aiogram.types import Message

from forest_bot.bot import texts

router = Router(name="fallback")


@router.message(F.text.startswith("/"))
async def on_unknown_command(message: Message) -> None:
    await message.answer(texts.UNKNOWN_COMMAND)


@router.message()
async def on_anything_else(message: Message) -> None:
    await message.answer(texts.NOT_UNDERSTOOD)
