"""Plain text is a question (R3). If the advice depends on the mitten and it is not named,
the bot asks for it first (R10a) and keeps the question in the FSM."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from forest_bot.bot import texts
from forest_bot.bot.keyboards import Dialog, QuestionPlace, mittens_keyboard
from forest_bot.forest import PLACES
from forest_bot.qa.service import QAService

router = Router(name="questions")


@router.message(F.text & ~F.text.startswith("/"))
async def on_question(message: Message, state: FSMContext, bot: Bot, qa: QAService) -> None:
    # A question that waited for the mitten is in the history: a reply like «під дубом»
    # is understood as the follow-up (D8)
    await state.clear()
    user_id = message.from_user.id
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        route = await qa.route(user_id, message.text)
        if not route.is_forest_question:
            await message.answer(texts.NOT_ABOUT_FOREST)
            return
        if route.must_ask_place:
            await qa.remember_clarification(user_id, message.text, texts.ASK_MITTEN)
            await state.set_state(Dialog.question_mitten)
            await state.set_data(
                {
                    "question": route.question,
                    "doc_types": route.doc_types,
                    "asked_in": message.message_id,
                }
            )
            await message.answer(
                texts.ASK_MITTEN, reply_markup=mittens_keyboard(message.message_id)
            )
            return
        await _answer(
            message, qa, user_id, message.text, route.question, route.place, route.doc_types
        )


@router.callback_query(QuestionPlace.filter())
async def on_question_mitten(
    callback: CallbackQuery,
    callback_data: QuestionPlace,
    state: FSMContext,
    bot: Bot,
    qa: QAService,
) -> None:
    # Not filtered by state: /name or a document may change what the next text means,
    # but the question keeps waiting (D26). Only the last question's buttons work.
    place = PLACES.get(callback_data.code)
    data = await state.get_data()
    if place is None or data.get("asked_in") != callback_data.asked_in:
        await callback.answer(texts.STALE_BUTTON)
        return
    await state.set_data({})
    if await state.get_state() == Dialog.question_mitten.state:
        await state.set_state(None)
    await callback.answer()
    await callback.message.edit_text(f"{texts.ASK_MITTEN}\n— {place.name}")
    async with ChatActionSender.typing(bot=bot, chat_id=callback.message.chat.id):
        await _answer(
            callback.message,
            qa,
            callback.from_user.id,
            place.name,
            data["question"],
            place.code,
            tuple(data.get("doc_types", ())),
        )


async def _answer(
    message: Message,
    qa: QAService,
    user_id: int,
    asked: str,
    question: str,
    place: str | None,
    doc_types: tuple[str, ...] = (),
) -> None:
    result = await qa.answer(user_id, asked, question, place, doc_types)
    reply = texts.answer(result) if result.found else texts.NOT_FOUND
    for part in texts.split_message(reply):
        await message.answer(part)
