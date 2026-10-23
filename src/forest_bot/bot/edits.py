"""Editing the message whose button was pressed. A double tap may have edited it already
("message is not modified"), and a message older than 48 hours cannot be edited at all, so
a failed edit must never stop the work the press was for."""

import logging
from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardMarkup

log = logging.getLogger(__name__)


async def drop_keyboard(callback: CallbackQuery) -> None:
    if _editable(callback):
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=None)


async def edit_text(
    callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    if _editable(callback):
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=reply_markup)


def _editable(callback: CallbackQuery) -> bool:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        log.info("Message of callback %s is no longer accessible", callback.id)
        return False
    return True
