import uuid
from uuid import UUID
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.models import Group, Project


def project_detail_kb(project: Project) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    icon = "⏹" if project.is_active else "▶️"
    b.row(
        InlineKeyboardButton(text=f"{icon} {'Остановить' if project.is_active else 'Запустить'}", callback_data=f"pj:toggle:{project.id}"),
        InlineKeyboardButton(text="📨 Сообщения", callback_data=f"pj:messages:{project.id}"),
    )
    b.row(
        InlineKeyboardButton(text="👥 Группы", callback_data=f"pj:groups:{project.id}"),
        InlineKeyboardButton(text="📜 Логи", callback_data=f"pj:logs:{project.id}"),
    )
    b.row(InlineKeyboardButton(text="❌ Удалить", callback_data=f"pj:delete:{project.id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="pj:list"))
    return b.as_markup()


def project_messages_kb(project_id: UUID, has_default: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    label = "✏️ Изменить дефолтное" if has_default else "✏️ Установить дефолтное"
    b.button(text=label, callback_data=f"pj:set_default_msg:{project_id}")
    if has_default:
        b.button(text="🗑 Удалить дефолтное", callback_data=f"pj:del_default_msg:{project_id}")
    b.button(text="🔙 Назад", callback_data=f"pj:open:{project_id}")
    b.adjust(1)
    return b.as_markup()


def groups_list_kb(groups: list[Group], project_id: UUID) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for g in groups:
        icon = "🟢" if g.is_active else "🔴"
        msg_icon = "📝" if g.custom_message_id else ""
        b.button(text=f"{icon} {g.max_group_id} {msg_icon}", callback_data=f"pj:group:{g.id}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text="➕ Добавить группу", callback_data=f"pj:add_group:{project_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"pj:open:{project_id}"))
    return b.as_markup()


def group_detail_kb(group: Group) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    icon = "⏹" if group.is_active else "▶️"
    b.row(
        InlineKeyboardButton(text=f"{icon} {'Остановить' if group.is_active else 'Запустить'}", callback_data=f"pj:group_toggle:{group.id}"),
        InlineKeyboardButton(text="📨 Сообщение", callback_data=f"pj:group_msg:{group.id}"),
    )
    b.row(
        InlineKeyboardButton(text="⏰ Расписание", callback_data=f"pj:group_sched:{group.id}"),
    )
    b.row(InlineKeyboardButton(text="❌ Удалить", callback_data=f"pj:group_del:{group.id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"pj:groups:{group.project_id}"))
    return b.as_markup()


def group_message_kb(group_id: UUID, has_custom: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    label = "✏️ Изменить кастомное" if has_custom else "✏️ Установить кастомное"
    b.button(text=label, callback_data=f"pj:set_group_msg:{group_id}")
    if has_custom:
        b.button(text="🗑 Удалить кастомное (упадёт на дефолт)", callback_data=f"pj:del_group_msg:{group_id}")
    b.button(text="🔙 Назад", callback_data=f"pj:group:{group_id}")
    b.adjust(1)
    return b.as_markup()


def schedule_type_kb(group_id: UUID) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔁 Интервал (1/2/4/24ч)", callback_data=f"pj:sched_interval:{group_id}")
    b.button(text="🕐 Точное время (HH:MM)", callback_data=f"pj:sched_exact:{group_id}")
    b.button(text="🔙 Назад", callback_data=f"pj:group:{group_id}")
    b.adjust(1)
    return b.as_markup()


def schedule_interval_kb(group_id: UUID) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for h in ["1", "2", "4", "24"]:
        b.button(text=f"{h}ч", callback_data=f"pj:set_interval:{group_id}:{h}")
    b.button(text="🔙 Назад", callback_data=f"pj:group:{group_id}")
    b.adjust(3, 1)
    return b.as_markup()


def schedule_exact_kb(group_id: UUID) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for h in ["00:00", "06:00", "12:00", "18:00", "08:00", "20:00", "22:00"]:
        b.button(text=h, callback_data=f"pj:set_exact:{group_id}:{h}")
    b.button(text="🔙 Назад", callback_data=f"pj:group:{group_id}")
    b.adjust(3, 3, 2, 1)
    return b.as_markup()


def confirm_delete_kb(action: str, id: UUID) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, удалить", callback_data=f"pj:confirm_del:{action}:{id}")
    b.button(text="❌ Отмена", callback_data=f"pj:open:{id}")
    b.adjust(2)
    return b.as_markup()


def admin_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📦 Проекты", callback_data="pj:list")
    return b.as_markup()


def projects_list_kb(projects: list[Project], page: int, total_pages: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in projects:
        icon = "🟢" if p.is_active else "🔴"
        b.button(text=f"{icon} {p.name}", callback_data=f"pj:open:{p.id}")
    b.adjust(1)
    if total_pages > 1:
        nav = InlineKeyboardBuilder()
        if page > 0:
            nav.button(text="⬅️", callback_data=f"pj:page:{page - 1}")
        nav.button(text=f"{page + 1}/{total_pages}", callback_data="pj:noop")
        if page < total_pages - 1:
            nav.button(text="➡️", callback_data=f"pj:page:{page + 1}")
        b.row(*nav.buttons)
    b.row(InlineKeyboardButton(text="➕ Добавить проект", callback_data="pj:add"))
    return b.as_markup()


def fsm_back_kb(back_callback: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔙 Назад", callback_data=back_callback)
    b.button(text="❌ Отмена", callback_data="pj:cancel_fsm")
    return b.as_markup()