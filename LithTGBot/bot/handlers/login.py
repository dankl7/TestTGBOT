import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.handlers.admin import is_admin
from config import SESSIONS_DIR
from utils.telegram_auth import sms_provider, password_provider

logger = logging.getLogger(__name__)
router = Router()

_active_login: dict[str, asyncio.Task | None] = {"task": None}


class MaxLogin(StatesGroup):
    phone = State()
    code = State()
    password = State()


@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    await state.clear()
    await message.answer(
        "📱 Введите номер телефона MAX\n"
        "Формат: <code>+79001234567</code>"
    )
    await state.set_state(MaxLogin.phone)


@router.message(MaxLogin.phone)
async def max_login_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not phone.startswith("+") or len(phone) < 10:
        await message.answer("❌ Неверный формат. Введите номер с + (например: <code>+79001234567</code>):")
        return

    await state.update_data(phone=phone)
    await message.answer(f"🔄 Подключение к MAX ({phone})...")
    await state.set_state(MaxLogin.code)

    async def run_auth():
        from pymax import Client, SmsAuthFlow, ExtraConfig
        client = Client(
            phone=phone,
            work_dir=str(SESSIONS_DIR),
            session_name="main_session.db",
            auth_flow=SmsAuthFlow(sms_provider, password_provider),
            extra_config=ExtraConfig(log_level="WARNING", reconnect=False),
        )
        try:
            await client.start()
            await message.answer("✅ Авторизация прошла успешно! Сессия сохранена.")
            await state.clear()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Login failed: %s", e)
            current = await state.get_state()
            if current:
                await message.answer(f"❌ Ошибка авторизации: {e}")
                await state.clear()
        finally:
            try:
                await client.stop()
            except Exception:
                pass
            _active_login["task"] = None

    prev = _active_login.get("task")
    if prev and not prev.done():
        prev.cancel()
    _active_login["task"] = asyncio.create_task(run_auth())
    await message.answer("📨 SMS-код отправлен. Введите его:")


@router.message(MaxLogin.code)
async def max_login_code(message: Message, state: FSMContext):
    code = message.text.strip()
    if not code.isdigit() or len(code) < 4:
        await message.answer("❌ Код должен быть числом (4+ цифр). Попробуйте ещё раз:")
        return
    sms_provider.set_code(code)
    await message.answer("🔄 Проверка кода...")
    await state.set_state(MaxLogin.password)


@router.message(MaxLogin.password)
async def max_login_password(message: Message, state: FSMContext):
    password = message.text.strip()
    password_provider.set_password(password)
    await message.answer("🔄 Проверка пароля...")
    await state.clear()
