from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.handlers.admin import is_admin
from bot.keyboards.menu import get_main_menu
from database.session import async_session_maker
from database.repositories import repo

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    try:
        await message.delete()
    except Exception:
        pass
    async with async_session_maker() as session:
        await repo.get_or_create_user(session, message.from_user.id)
        await session.commit()
    await message.answer(
        "👋 <b>Панель управления проектами</b>\n\n"
        "Управляй проектами рассылок в MAX прямо из этого бота.",
        reply_markup=get_main_menu(is_admin=is_admin(message.from_user.id)),
    )


@router.message(F.text == "🔧 Админ")
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    await message.answer("🔧 <b>Админ-панель</b>\n\nРаздел в разработке.")
