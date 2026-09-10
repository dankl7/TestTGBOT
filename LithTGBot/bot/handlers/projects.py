import asyncio
import io
import os
import random
from datetime import datetime, time, timezone, timedelta
from uuid import UUID

from aiogram import F, Router, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, BufferedInputFile

from config import settings, MEDIA_DIR
from database.session import async_session_maker
from database.repositories import repo
from database.models import Project, Group, Message, Schedule
from bot.keyboards.project import (
    projects_list_kb,
    project_detail_kb,
    project_messages_kb,
    groups_list_kb,
    group_detail_kb,
    group_message_kb,
    schedule_type_kb,
    schedule_interval_kb,
    schedule_exact_kb,
    confirm_delete_kb,
    admin_menu_kb,
    fsm_back_kb,
)
from utils.media_manager import save_media, set_project_default_message, set_group_custom_message, delete_media_if_unreferenced

router = Router()
_active_auth_task: asyncio.Task | None = None


class AddProject(StatesGroup):
    name = State()
    phone = State()
    sms_code = State()
    password = State()


class SetDefaultMessage(StatesGroup):
    waiting = State()


class SetGroupMessage(StatesGroup):
    waiting = State()


class AddGroup(StatesGroup):
    group_id = State()


class SetScheduleExact(StatesGroup):
    waiting = State()


async def _delete_msg(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


async def _delete_prev_bot_msg(state: FSMContext, message: Message):
    data = await state.get_data()
    prev_id = data.get("bot_msg_id")
    if prev_id:
        try:
            await message.bot.delete_message(message.chat.id, prev_id)
        except Exception:
            pass


async def _send_and_track(message: Message, text: str, state: FSMContext, reply_markup=None) -> Message:
    await _delete_prev_bot_msg(state, message)
    msg = await message.answer(text, reply_markup=reply_markup)
    await state.update_data(bot_msg_id=msg.message_id)
    return msg


async def _can_manage(user_id: int) -> bool:
    return user_id in settings.admin_user_ids


@router.message(Command("start"))
@router.message(F.text == "📋 Проекты")
async def cmd_projects(message: Message):
    if not await _can_manage(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    async with async_session_maker() as session:
        projects = await repo.get_projects_by_owner(session, message.from_user.id)
    page = 0
    per_page = 8
    total_pages = max(1, (len(projects) + per_page - 1) // per_page)
    page_projects = projects[page * per_page : (page + 1) * per_page]
    await message.answer("📦 <b>Проекты</b>", reply_markup=projects_list_kb(page_projects, page, total_pages))


@router.callback_query(F.data == "pj:home")
async def cb_home(callback: CallbackQuery):
    try:
        await callback.message.edit_text("🏠 <b>Главное меню</b>", reply_markup=admin_menu_kb())
    except Exception:
        await callback.message.answer("🏠 <b>Главное меню</b>", reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "pj:noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "pj:cancel_fsm")
async def cb_cancel_fsm(callback: CallbackQuery, state: FSMContext):
    from utils.telegram_auth import sms_provider, password_provider
    sms_provider.set_code("")
    password_provider.set_password("")
    global _active_auth_task
    if _active_auth_task and not _active_auth_task.done():
        _active_auth_task.cancel()
        _active_auth_task = None
    await state.clear()
    async with async_session_maker() as session:
        projects = await repo.get_projects_by_owner(session, callback.from_user.id)
    per_page = 8
    total_pages = max(1, (len(projects) + per_page - 1) // per_page)
    page_projects = projects[:per_page]
    await callback.message.edit_text(
        "📦 <b>Проекты</b>",
        reply_markup=projects_list_kb(page_projects, 0, total_pages),
    )
    await callback.answer()


@router.callback_query(F.data == "pj:fsm_back:phone")
async def cb_fsm_back_phone(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddProject.name)
    data = await state.get_data()
    name = data.get("name", "")
    await callback.message.edit_text(
        f"📝 Введите название проекта:\nТекущее: <b>{name}</b>",
        reply_markup=fsm_back_kb("pj:home")
    )
    await callback.answer()


@router.callback_query(F.data == "pj:fsm_back:sms_code")
async def cb_fsm_back_sms_code(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddProject.phone)
    data = await state.get_data()
    phone = data.get("phone", "")
    await callback.message.edit_text(
        f"📱 Введите номер телефона MAX\nТекущий: <code>{phone}</code>\n\n"
        "⚠️ Будет отправлен новый SMS-код",
        reply_markup=fsm_back_kb("pj:fsm_back:phone")
    )
    await callback.answer()


@router.callback_query(F.data == "pj:fsm_back:password")
async def cb_fsm_back_password(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddProject.sms_code)
    await callback.message.edit_text(
        "🔄 Код не подходит? Введите другой SMS-код:",
        reply_markup=fsm_back_kb("pj:fsm_back:sms_code")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pj:"))
async def cb_projects(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    action = parts[1]

    if not await _can_manage(callback.from_user.id):
        await callback.answer("❌ Нет доступа.", show_alert=True)
        return

    if action == "list":
        await _list_projects(callback)
    elif action == "page":
        await _list_projects(callback, int(parts[2]))
    elif action == "open":
        await _show_project(callback, UUID(parts[2]))
    elif action == "toggle":
        await _toggle_project(callback, UUID(parts[2]))
    elif action == "messages":
        await _show_messages(callback, UUID(parts[2]))
    elif action == "set_default_msg":
        await _prompt_default_msg(callback, UUID(parts[2]), state)
    elif action == "del_default_msg":
        await _del_default_msg(callback, UUID(parts[2]))
    elif action == "groups":
        await _show_groups(callback, UUID(parts[2]))
    elif action == "add_group":
        await _prompt_add_group(callback, UUID(parts[2]), state)
    elif action == "group":
        await _show_group(callback, UUID(parts[2]))
    elif action == "group_toggle":
        await _toggle_group(callback, UUID(parts[2]))
    elif action == "group_msg":
        await _show_group_msg(callback, UUID(parts[2]))
    elif action == "set_group_msg":
        await _prompt_group_msg(callback, UUID(parts[2]), state)
    elif action == "del_group_msg":
        await _del_group_msg(callback, UUID(parts[2]))
    elif action == "group_sched":
        await _show_group_sched(callback, UUID(parts[2]))
    elif action == "sched_interval":
        await _show_sched_interval(callback, UUID(parts[2]))
    elif action == "set_interval":
        await _set_interval(callback, UUID(parts[2]), int(parts[3]))
    elif action == "sched_exact":
        await _show_sched_exact(callback, UUID(parts[2]))
    elif action == "set_exact":
        await _set_exact(callback, UUID(parts[2]), parts[3])
    elif action == "group_del":
        await _confirm_del_group(callback, UUID(parts[2]))
    elif action == "confirm_del":
        await _do_delete(callback, parts[2], UUID(parts[3]))
    elif action == "delete":
        await _confirm_del_project(callback, UUID(parts[2]))
    elif action == "add":
        await _add_project_prompt(callback, state)
    elif action == "logs":
        await _send_logs_file(callback.message, UUID(parts[2]))
        await callback.answer()
    else:
        await callback.answer("Неизвестное действие", show_alert=True)


async def _list_projects(cb: CallbackQuery, page: int = 0):
    async with async_session_maker() as session:
        projects = await repo.get_projects_by_owner(session, cb.from_user.id)
    per_page = 8
    total_pages = max(1, (len(projects) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    page_projects = projects[page * per_page : (page + 1) * per_page]
    await cb.message.edit_text("📦 <b>Проекты</b>", reply_markup=projects_list_kb(page_projects, page, total_pages))


async def _show_project(cb: CallbackQuery, project_id: UUID):
    async with async_session_maker() as session:
        project = await repo.get_project(session, project_id)
    if not project:
        await cb.answer("❌ Проект не найден", show_alert=True)
        return
    status = "🟢 Активен" if project.is_active else "🔴 Остановлен"
    has_default = project.default_message_id is not None
    lines = [
        f"<b>{project.name}</b>",
        f"Статус: {status}",
        f"Дефолтное сообщение: {'✅ есть' if has_default else '❌ нет'}",
        f"Владелец: <code>{project.owner_id}</code>",
    ]
    await cb.message.edit_text("\n".join(lines), reply_markup=project_detail_kb(project))


async def _toggle_project(cb: CallbackQuery, project_id: UUID):
    async with async_session_maker() as session:
        project = await repo.get_project(session, project_id)
        if not project:
            await cb.answer("❌ Не найден", show_alert=True)
            return
        new_status = not project.is_active
        await repo.update_project(session, project_id, is_active=new_status)
        if new_status:
            groups = await repo.get_groups_by_project(session, project_id)
            for g in groups:
                if g.is_active:
                    schedules = await repo.get_schedules_for_group(session, g.id)
                    for s in schedules:
                        await repo.update_schedule_last_sent(session, s.id, datetime.now(timezone.utc))
        await session.commit()
    await cb.answer(f"{'▶️ Запущен' if new_status else '⏹ Остановлен'}")
    await _show_project(cb, project_id)


async def _show_messages(cb: CallbackQuery, project_id: UUID):
    async with async_session_maker() as session:
        project = await repo.get_project(session, project_id)
        if not project:
            await cb.answer("❌ Не найден", show_alert=True)
            return
        has_default = project.default_message_id is not None
        lines = [f"📨 <b>Сообщения проекта</b> — {project.name}\n"]
        if has_default:
            msg = await repo.get_message(session, project.default_message_id)
            if msg:
                preview = (msg.text_content or "")[:80].replace("\n", " ")
                lines.append(f"Дефолтное: {preview}...")
        else:
            lines.append("Дефолтное: не задано")
    await cb.message.edit_text("\n".join(lines), reply_markup=project_messages_kb(project_id, has_default))


async def _prompt_default_msg(cb: CallbackQuery, project_id: UUID, state: FSMContext):
    await state.update_data(project_id=str(project_id))
    await cb.message.answer(
        "📝 Отправьте текст сообщения (поддерживается HTML).\n"
        "Для медиа — отправьте фото/видео/документ с подписью.\n"
        "/cancel для отмены."
    )
    await state.set_state(SetDefaultMessage.waiting)


async def _del_default_msg(cb: CallbackQuery, project_id: UUID):
    async with async_session_maker() as session:
        project = await repo.get_project(session, project_id)
        if project and project.default_message_id:
            old_id = project.default_message_id
            await repo.update_project(session, project_id, default_message_id=None)
            await session.commit()
            await delete_media_if_unreferenced(old_id)
    await cb.answer("✅ Дефолтное сообщение удалено")
    await _show_messages(cb, project_id)


@router.message(SetDefaultMessage.waiting)
async def fsm_default_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    project_id = UUID(data["project_id"])

    text_content = message.html_text if message.html_text else message.text
    media_type = None
    media_path = None

    if message.photo:
        media_type = "photo"
        file = await message.bot.get_file(message.photo[-1].file_id)
        media_path = f"MEDIA_DIR/{file.file_unique_id}.jpg"
        await message.bot.download_file(file.file_path, media_path)
    elif message.video:
        media_type = "video"
        file = await message.bot.get_file(message.video.file_id)
        media_path = f"MEDIA_DIR/{file.file_unique_id}.mp4"
        await message.bot.download_file(file.file_path, media_path)
    elif message.document:
        media_type = "document"
        file = await message.bot.get_file(message.document.file_id)
        ext = os.path.splitext(message.document.file_name)[1] or ""
        media_path = f"MEDIA_DIR/{file.file_unique_id}{ext}"
        await message.bot.download_file(file.file_path, media_path)

    async with async_session_maker() as session:
        msg = await repo.create_message(
            session,
            text_content=text_content or "",
            media_type=media_type,
            media_path=media_path,
        )
        await session.commit()
        await set_project_default_message(project_id, msg.id)

    await message.answer("✅ Дефолтное сообщение сохранено!")
    await state.clear()


async def _show_groups(cb: CallbackQuery, project_id: UUID):
    async with async_session_maker() as session:
        groups = await repo.get_groups_by_project(session, project_id)
        project = await repo.get_project(session, project_id)
    lines = [f"👥 <b>Группы</b> — {project.name}\n"]
    if not groups:
        lines.append("Нет добавленных групп.")
    else:
        for g in groups:
            icon = "🟢" if g.is_active else "🔴"
            custom = " 📝" if g.custom_message_id else ""
            lines.append(f"{icon} <code>{g.max_group_id}</code>{custom}")
    await cb.message.edit_text("\n".join(lines), reply_markup=groups_list_kb(groups, project_id))


async def _prompt_add_group(cb: CallbackQuery, project_id: UUID, state: FSMContext):
    await state.update_data(project_id=str(project_id))
    await cb.message.answer(
        "📥 Введите ID группы MAX (строго отрицательное число, например: -1001234567890).\n"
        "Ссылки и алиасы не принимаются."
    )
    await state.set_state(AddGroup.group_id)


@router.message(AddGroup.group_id)
async def fsm_add_group(message: Message, state: FSMContext):
    data = await state.get_data()
    project_id = UUID(data["project_id"])
    text = message.text.strip()
    try:
        max_group_id = int(text)
    except ValueError:
        await message.answer("❌ Это не число. Введите ID группы (отрицательное число):")
        return
    if max_group_id >= 0:
        await message.answer("❌ ID группы должен быть отрицательным числом (например: -1001234567890):")
        return
    async with async_session_maker() as session:
        await repo.create_group(session, project_id, max_group_id)
        await session.commit()
    await message.answer(f"✅ Группа <code>{max_group_id}</code> добавлена!")
    await state.clear()
    async with async_session_maker() as session:
        groups = await repo.get_groups_by_project(session, project_id)
        project = await repo.get_project(session, project_id)
    lines = [f"👥 <b>Группы</b> — {project.name}\n"]
    if not groups:
        lines.append("Нет добавленных групп.")
    else:
        for g in groups:
            icon = "🟢" if g.is_active else "🔴"
            custom = " 📝" if g.custom_message_id else ""
            lines.append(f"{icon} <code>{g.max_group_id}</code>{custom}")
    await message.answer("\n".join(lines), reply_markup=groups_list_kb(groups, project_id))


async def _show_group(cb: CallbackQuery, group_id: UUID):
    async with async_session_maker() as session:
        group = await repo.get_group(session, group_id)
        if not group:
            await cb.answer("❌ Группа не найдена", show_alert=True)
            return
        msg_id = group.custom_message_id or (await repo.get_project(session, group.project_id)).default_message_id if group.custom_message_id else None
        if not msg_id:
            project = await repo.get_project(session, group.project_id)
            msg_id = project.default_message_id if project else None
        msg_text = ""
        has_msg = False
        media_info = ""
        if msg_id:
            msg = await repo.get_message(session, msg_id)
            if msg:
                has_msg = True
                msg_text = (msg.text_content or "")[:100].replace("\n", " ")
                if msg.media_type:
                    media_info = f"\n📎 Медиа: {msg.media_type}"
        schedules = await repo.get_schedules_for_group(session, group_id)

    status = "🟢 Активна" if group.is_active else "🔴 Остановлена"
    source = "📝 Кастомное" if group.custom_message_id else "📋 Дефолтное проекта"
    lines = [
        f"👥 <b>Группа</b> <code>{group.max_group_id}</code>",
        f"Статус: {status}",
        f"\n📨 <b>Сообщение:</b> {source}",
    ]
    if has_msg:
        lines.append(f"<code>{msg_text}...</code>")
        if media_info:
            lines.append(media_info)
    else:
        lines.append("⚠️ Сообщение не задано!")
    if schedules:
        lines.append("\n📅 <b>Расписания:</b>")
        for s in schedules:
            if s.schedule_type == "interval":
                lines.append(f"  🔁 Каждые {s.schedule_value.get('hours')}ч")
            else:
                lines.append(f"  🕐 {', '.join(s.schedule_value.get('times', []))}")
            if s.last_sent_at:
                lines.append(f"     Последняя: {s.last_sent_at.strftime('%d.%m %H:%M')}")
    else:
        lines.append("\n⚠️ Расписание не настроено.")
    await cb.message.edit_text("\n".join(lines), reply_markup=group_detail_kb(group))


async def _toggle_group(cb: CallbackQuery, group_id: UUID):
    async with async_session_maker() as session:
        group = await repo.get_group(session, group_id)
        if not group:
            await cb.answer("❌ Не найдена", show_alert=True)
            return
        schedules = await repo.get_schedules_for_group(session, group_id)
        if not schedules:
            await cb.answer("⚠️ Сначала настройте расписание!", show_alert=True)
            return
        new_status = not group.is_active
        if new_status:
            project = await repo.get_project(session, group.project_id)
            if project:
                for s in schedules:
                    await repo.update_schedule_last_sent(session, s.id, datetime.now(timezone.utc))
        await repo.update_group(session, group_id, is_active=new_status)
        await session.commit()
    await cb.answer(f"{'▶️ Запущена' if new_status else '⏹ Остановлена'}")
    await _show_group(cb, group_id)


async def _show_group_msg(cb: CallbackQuery, group_id: UUID):
    async with async_session_maker() as session:
        group = await repo.get_group(session, group_id)
    if not group:
        await cb.answer("❌ Не найдена", show_alert=True)
        return
    has_custom = group.custom_message_id is not None
    await cb.message.edit_text(
        f"📨 <b>Сообщение для группы</b> <code>{group.max_group_id}</code>\n\n"
        f"Текущее: {'кастомное' if has_custom else 'дефолтное проекта'}",
        reply_markup=group_message_kb(group_id, has_custom),
    )


async def _prompt_group_msg(cb: CallbackQuery, group_id: UUID, state: FSMContext):
    await state.update_data(group_id=str(group_id))
    await cb.message.answer(
        "📝 Отправьте текст сообщения (HTML).\n"
        "Медиа — фото/видео/документ с подписью.\n"
        "/cancel для отмены."
    )
    await state.set_state(SetGroupMessage.waiting)


async def _del_group_msg(cb: CallbackQuery, group_id: UUID):
    async with async_session_maker() as session:
        group = await repo.get_group(session, group_id)
        if group and group.custom_message_id:
            old_id = group.custom_message_id
            await repo.update_group(session, group_id, custom_message_id=None)
            await session.commit()
            await delete_media_if_unreferenced(old_id)
    await cb.answer("✅ Кастомное сообщение удалено, используется дефолт проекта")
    await _show_group_msg(cb, group_id)


@router.message(SetGroupMessage.waiting)
async def fsm_group_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    group_id = UUID(data["group_id"])

    text_content = message.html_text if message.html_text else message.text
    media_type = None
    media_path = None

    if message.photo:
        media_type = "photo"
        file = await message.bot.get_file(message.photo[-1].file_id)
        media_path = f"MEDIA_DIR/{file.file_unique_id}.jpg"
        await message.bot.download_file(file.file_path, media_path)
    elif message.video:
        media_type = "video"
        file = await message.bot.get_file(message.video.file_id)
        media_path = f"MEDIA_DIR/{file.file_unique_id}.mp4"
        await message.bot.download_file(file.file_path, media_path)
    elif message.document:
        media_type = "document"
        file = await message.bot.get_file(message.document.file_id)
        ext = os.path.splitext(message.document.file_name)[1] or ""
        media_path = f"MEDIA_DIR/{file.file_unique_id}{ext}"
        await message.bot.download_file(file.file_path, media_path)

    async with async_session_maker() as session:
        msg = await repo.create_message(
            session,
            text_content=text_content or "",
            media_type=media_type,
            media_path=media_path,
        )
        await session.commit()
        await set_group_custom_message(group_id, msg.id)

    await message.answer("✅ Кастомное сообщение сохранено!")
    await state.clear()


async def _show_group_sched(cb: CallbackQuery, group_id: UUID):
    async with async_session_maker() as session:
        group = await repo.get_group(session, group_id)
        schedules = await repo.get_schedules_for_group(session, group_id)
    if not group:
        await cb.answer("❌ Не найдена", show_alert=True)
        return
    lines = [f"⏰ <b>Расписание</b> — <code>{group.max_group_id}</code>\n"]
    if not schedules:
        lines.append("Расписаний нет.")
    else:
        for s in schedules:
            if s.schedule_type == "interval":
                lines.append(f"🔁 Интервал: каждые {s.schedule_value.get('hours')}ч")
            else:
                lines.append(f"🕐 Точное время: {', '.join(s.schedule_value.get('times', []))}")
            if s.last_sent_at:
                lines.append(f"   Последняя отправка: {s.last_sent_at.strftime('%d.%m %H:%M')}")
    await cb.message.edit_text("\n".join(lines), reply_markup=schedule_type_kb(group_id))


async def _show_sched_interval(cb: CallbackQuery, group_id: UUID):
    await cb.message.edit_text(
        "Выберите интервал:",
        reply_markup=schedule_interval_kb(group_id),
    )


async def _set_interval(cb: CallbackQuery, group_id: UUID, hours: int):
    async with async_session_maker() as session:
        await repo.create_schedule(session, group_id, "interval", {"hours": hours})
        await session.commit()
    await cb.answer(f"✅ Интервал {hours}ч добавлен")
    await _show_group_sched(cb, group_id)


async def _show_sched_exact(cb: CallbackQuery, group_id: UUID):
    await cb.message.edit_text(
        "Выберите время (UTC) или введите своё (HH:MM):",
        reply_markup=schedule_exact_kb(group_id),
    )


async def _set_exact(cb: CallbackQuery, group_id: UUID, time_str: str):
    async with async_session_maker() as session:
        await repo.create_schedule(session, group_id, "exact", {"times": [time_str]})
        await session.commit()
    await cb.answer(f"✅ Время {time_str} добавлено")
    await _show_group_sched(cb, group_id)


async def _confirm_del_group(cb: CallbackQuery, group_id: UUID):
    await cb.message.edit_text(
        f"❓ Удалить группу <code>{group_id}</code>?",
        reply_markup=confirm_delete_kb("group", group_id),
    )


async def _confirm_del_project(cb: CallbackQuery, project_id: UUID):
    await cb.message.edit_text(
        "❓ Удалить проект? Это удалит все группы и сообщения.",
        reply_markup=confirm_delete_kb("project", project_id),
    )


async def _do_delete(cb: CallbackQuery, action: str, id: UUID):
    async with async_session_maker() as session:
        if action == "group":
            group = await repo.get_group(session, id)
            pid = group.project_id if group else None
            ok = await repo.delete_group(session, id)
            if not ok:
                await cb.answer("❌ Не найдено", show_alert=True)
                return
            await cb.answer("✅ Группа удалена")
            await _show_groups(cb, pid)
        elif action == "project":
            ok = await repo.delete_project(session, id)
            if not ok:
                await cb.answer("❌ Не найден", show_alert=True)
                return
            await cb.answer("✅ Проект удалён")
            await _list_projects(cb)


async def _add_project_prompt(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.delete()
    except Exception:
        pass
    msg = await cb.message.answer(
        "📝 Введите название проекта:",
        reply_markup=fsm_back_kb("pj:home")
    )
    await state.set_state(AddProject.name)
    await state.update_data(bot_msg_id=msg.message_id)


@router.message(AddProject.name)
async def fsm_project_name(message: Message, state: FSMContext):
    await _delete_msg(message)
    await _delete_prev_bot_msg(state, message)
    name = message.text.strip()
    if len(name) > 100:
        msg = await message.answer("❌ Имя слишком длинное (макс. 100 символов). Введите короткое название:")
        await state.update_data(bot_msg_id=msg.message_id)
        return
    if any(kw in name.lower() for kw in ("token", "auth", "__oneme", "session")):
        msg = await message.answer("❌ Это похоже на токен, а не на имя проекта.\n\n📝 Введите <b>название</b> проекта (например: «Мои рассылки»):")
        await state.update_data(bot_msg_id=msg.message_id)
        return
    await state.update_data(name=name)
    msg = await message.answer(
        "📱 Введите номер телефона MAX\nФормат: <code>+79001234567</code>",
        reply_markup=fsm_back_kb("pj:fsm_back:phone")
    )
    await state.set_state(AddProject.phone)
    await state.update_data(bot_msg_id=msg.message_id)


@router.message(AddProject.phone)
async def fsm_project_phone(message: Message, state: FSMContext):
    await _delete_msg(message)
    await _delete_prev_bot_msg(state, message)
    if message.text and message.text.strip().lower() in ("/cancel", "отмена"):
        await state.clear()
        async with async_session_maker() as session:
            projects = await repo.get_projects_by_owner(session, message.from_user.id)
        per_page = 8
        total_pages = max(1, (len(projects) + per_page - 1) // per_page)
        page_projects = projects[:per_page]
        await message.answer(
            "📦 <b>Проекты</b>",
            reply_markup=projects_list_kb(page_projects, 0, total_pages),
        )
        return
    phone = message.text.strip()
    if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 10 or len(phone) > 15:
        msg = await message.answer(
            "❌ Неверный формат номера.\n\n"
            "Введите номер телефона MAX:\n"
            "Формат: <code>+79001234567</code>\n"
            "(от 10 до 15 цифр с +)\n\n"
            "/cancel — отмена"
        )
        await state.update_data(bot_msg_id=msg.message_id)
        return
    from utils.telegram_auth import sms_provider, password_provider

    await state.update_data(phone=phone)
    await state.set_state(AddProject.sms_code)

    async def run_auth():
        from pymax import Client, SmsAuthFlow, ExtraConfig
        from config import SESSIONS_DIR
        client = Client(
            phone=phone,
            work_dir=str(SESSIONS_DIR),
            session_name="main_session.db",
            auth_flow=SmsAuthFlow(sms_provider, password_provider),
            extra_config=ExtraConfig(log_level="WARNING", reconnect=False),
        )
        try:
            await client.start()
            data = await state.get_data()
            name = data["name"]
            async with async_session_maker() as session:
                await repo.create_project(session, message.from_user.id, name, "")
                await session.commit()
            await message.answer("✅ Проект создан! Авторизация MAX прошла успешно.")
            await state.clear()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            current = await state.get_state()
            if current:
                await message.answer(f"❌ Ошибка авторизации: {e}")
        finally:
            try:
                await client.stop()
            except Exception:
                pass

    import asyncio
    global _active_auth_task
    if _active_auth_task and not _active_auth_task.done():
        _active_auth_task.cancel()
    _active_auth_task = asyncio.create_task(run_auth())
    msg = await message.answer(
        "📨 SMS-код отправлен. Введите его:",
        reply_markup=fsm_back_kb("pj:fsm_back:sms_code")
    )
    await state.update_data(bot_msg_id=msg.message_id)


@router.message(AddProject.sms_code)
async def fsm_project_sms_code(message: Message, state: FSMContext):
    await _delete_msg(message)
    await _delete_prev_bot_msg(state, message)
    if message.text and message.text.strip().lower() in ("/cancel", "отмена"):
        await state.clear()
        async with async_session_maker() as session:
            projects = await repo.get_projects_by_owner(session, message.from_user.id)
        per_page = 8
        total_pages = max(1, (len(projects) + per_page - 1) // per_page)
        page_projects = projects[:per_page]
        await message.answer(
            "📦 <b>Проекты</b>",
            reply_markup=projects_list_kb(page_projects, 0, total_pages),
        )
        return
    code = message.text.strip()
    if not code.isdigit() or len(code) < 4:
        msg = await message.answer("❌ Код должен быть числом (4+ цифр). Попробуйте ещё раз:\n/cancel — отмена")
        await state.update_data(bot_msg_id=msg.message_id)
        return
    from utils.telegram_auth import sms_provider
    sms_provider.set_code(code)
    await state.set_state(AddProject.password)
    msg = await message.answer(
        "🔑 Если включена 2FA — введите пароль MAX.\n"
        "Если нет — введите любой символ для пропуска.",
        reply_markup=fsm_back_kb("pj:fsm_back:password")
    )
    await state.update_data(bot_msg_id=msg.message_id)


@router.message(AddProject.password)
async def fsm_project_password(message: Message, state: FSMContext):
    await _delete_msg(message)
    await _delete_prev_bot_msg(state, message)
    if message.text and message.text.strip().lower() in ("/cancel", "отмена"):
        await state.clear()
        async with async_session_maker() as session:
            projects = await repo.get_projects_by_owner(session, message.from_user.id)
        per_page = 8
        total_pages = max(1, (len(projects) + per_page - 1) // per_page)
        page_projects = projects[:per_page]
        await message.answer(
            "📦 <b>Проекты</b>",
            reply_markup=projects_list_kb(page_projects, 0, total_pages),
        )
        return
    from utils.telegram_auth import password_provider
    password_provider.set_password(message.text.strip())
    await message.answer("🔄 Проверка пароля...")
    await state.clear()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.delete()
    async with async_session_maker() as session:
        projects = await repo.get_projects_by_owner(session, message.from_user.id)
    per_page = 8
    total_pages = max(1, (len(projects) + per_page - 1) // per_page)
    page_projects = projects[:per_page]
    await message.answer(
        "📦 <b>Проекты</b>",
        reply_markup=projects_list_kb(page_projects, 0, total_pages),
    )


async def _send_logs_file(message: Message, project_id: UUID):
    async with async_session_maker() as session:
        logs = await repo.get_logs_by_project(session, project_id, limit=200, days=7)
    if not logs:
        await message.answer("📜 Логов за последние 7 дней нет.")
        return
    lines = []
    for log in reversed(logs):
        icon = "✅" if log.status == "SUCCESS" else "❌"
        group_info = f" [{log.group_id}]" if log.group_id else ""
        lines.append(f"{icon} {log.created_at.strftime('%d.%m %H:%M')}{group_info} {log.status}")
        if log.message:
            lines.append(f"   {log.message}")
    content = "\n".join(lines)
    file = BufferedInputFile(content.encode(), filename=f"logs_{project_id}.txt")
    await message.answer_document(file, caption=f"📜 Логи за последние 7 дней")


