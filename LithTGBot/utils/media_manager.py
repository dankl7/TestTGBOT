import os
from uuid import UUID
from sqlalchemy import select, func
from database.session import async_session_maker
from database.models import Message, Project, Group


async def save_media(message_id: UUID, media_path: str) -> str:
    return media_path


async def delete_media_if_unreferenced(message_id: UUID) -> bool:
    async with async_session_maker() as session:
        project_count = await session.scalar(
            select(func.count(Project.id)).where(Project.default_message_id == message_id)
        )
        group_count = await session.scalar(
            select(func.count(Group.id)).where(Group.custom_message_id == message_id)
        )

        total_refs = (project_count or 0) + (group_count or 0)

        if total_refs == 0:
            msg = await session.get(Message, message_id)
            if msg and msg.media_path and os.path.exists(msg.media_path):
                os.remove(msg.media_path)
            await session.delete(msg)
            await session.commit()
            return True

    return False


async def set_project_default_message(project_id: UUID, message_id: UUID) -> UUID | None:
    async with async_session_maker() as session:
        project = await session.get(Project, project_id)
        if not project:
            return None

        old_msg_id = project.default_message_id
        project.default_message_id = message_id
        await session.commit()

        if old_msg_id and old_msg_id != message_id:
            await delete_media_if_unreferenced(old_msg_id)

        return old_msg_id


async def set_group_custom_message(group_id: UUID, message_id: UUID | None) -> UUID | None:
    async with async_session_maker() as session:
        group = await session.get(Group, group_id)
        if not group:
            return None

        old_msg_id = group.custom_message_id
        group.custom_message_id = message_id
        await session.commit()

        if old_msg_id and old_msg_id != message_id:
            await delete_media_if_unreferenced(old_msg_id)

        return old_msg_id