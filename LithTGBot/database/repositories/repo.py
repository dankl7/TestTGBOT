from uuid import UUID
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import User, Project, Message, Group, Schedule, Log


async def get_or_create_user(session: AsyncSession, telegram_id: int, tz: int = 3) -> User:
    user = await session.get(User, telegram_id)
    if not user:
        user = User(telegram_id=telegram_id, timezone=tz)
        session.add(user)
        await session.flush()
    return user


async def create_project(
    session: AsyncSession,
    owner_id: int,
    name: str,
    auth_token_encrypted: str,
    default_message_id: UUID | None = None,
) -> Project:
    await get_or_create_user(session, owner_id)
    project = Project(
        owner_id=owner_id,
        name=name,
        auth_token=auth_token_encrypted,
        default_message_id=default_message_id,
        is_active=False,
    )
    session.add(project)
    await session.flush()
    return project


async def get_project(session: AsyncSession, project_id: UUID) -> Project | None:
    return await session.get(Project, project_id)


async def get_projects_by_owner(session: AsyncSession, owner_id: int) -> list[Project]:
    result = await session.execute(
        select(Project).where(Project.owner_id == owner_id).order_by(Project.created_at)
    )
    return list(result.scalars().all())


async def update_project(
    session: AsyncSession,
    project_id: UUID,
    **kwargs,
) -> Project | None:
    project = await session.get(Project, project_id)
    if not project:
        return None
    for k, v in kwargs.items():
        if hasattr(project, k):
            setattr(project, k, v)
    await session.flush()
    return project


async def delete_project(session: AsyncSession, project_id: UUID) -> bool:
    project = await session.get(Project, project_id)
    if not project:
        return False
    await session.delete(project)
    await session.commit()
    return True


async def create_message(
    session: AsyncSession,
    text_content: str,
    media_type: str | None = None,
    media_path: str | None = None,
) -> Message:
    msg = Message(text_content=text_content, media_type=media_type, media_path=media_path)
    session.add(msg)
    await session.flush()
    return msg


async def get_message(session: AsyncSession, message_id: UUID) -> Message | None:
    return await session.get(Message, message_id)


async def create_group(
    session: AsyncSession,
    project_id: UUID,
    max_group_id: int,
    custom_message_id: UUID | None = None,
) -> Group:
    if max_group_id >= 0:
        raise ValueError("MAX group ID must be negative")
    group = Group(
        project_id=project_id,
        max_group_id=max_group_id,
        custom_message_id=custom_message_id,
        is_active=False,
    )
    session.add(group)
    await session.flush()
    return group


async def get_group(session: AsyncSession, group_id: UUID) -> Group | None:
    return await session.get(Group, group_id)


async def get_groups_by_project(session: AsyncSession, project_id: UUID) -> list[Group]:
    result = await session.execute(
        select(Group).where(Group.project_id == project_id).order_by(Group.created_at)
    )
    return list(result.scalars().all())


async def get_active_groups_with_schedules(session: AsyncSession) -> list[tuple[Group, list[Schedule]]]:
    result = await session.execute(
        select(Group)
        .options(selectinload(Group.schedules))
        .join(Project, Project.id == Group.project_id)
        .where(Group.is_active.is_(True), Project.is_active.is_(True))
    )
    groups = list(result.scalars().all())
    return [(g, list(g.schedules)) for g in groups]


async def update_group(session: AsyncSession, group_id: UUID, **kwargs) -> Group | None:
    group = await session.get(Group, group_id)
    if not group:
        return None
    for k, v in kwargs.items():
        if hasattr(group, k):
            setattr(group, k, v)
    await session.flush()
    return group


async def delete_group(session: AsyncSession, group_id: UUID) -> bool:
    group = await session.get(Group, group_id)
    if not group:
        return False
    await session.delete(group)
    await session.commit()
    return True


async def create_schedule(
    session: AsyncSession,
    group_id: UUID,
    schedule_type: str,
    schedule_value: dict,
) -> Schedule:
    sched = Schedule(group_id=group_id, schedule_type=schedule_type, schedule_value=schedule_value)
    session.add(sched)
    await session.flush()
    return sched


async def get_schedules_for_group(session: AsyncSession, group_id: UUID) -> list[Schedule]:
    result = await session.execute(
        select(Schedule).where(Schedule.group_id == group_id).order_by(Schedule.created_at)
    )
    return list(result.scalars().all())


async def update_schedule_last_sent(session: AsyncSession, schedule_id: UUID, dt: datetime) -> None:
    sched = await session.get(Schedule, schedule_id)
    if sched:
        sched.last_sent_at = dt
        await session.flush()


async def add_log(
    session: AsyncSession,
    project_id: UUID,
    status: str,
    message: str | None = None,
    group_id: UUID | None = None,
    user_id: int | None = None,
) -> Log:
    log = Log(
        project_id=project_id,
        group_id=group_id,
        user_id=user_id,
        status=status,
        message=message,
    )
    session.add(log)
    await session.flush()
    return log


async def get_logs_by_project(session: AsyncSession, project_id: UUID, limit: int = 50, days: int | None = None) -> list[Log]:
    query = select(Log).where(Log.project_id == project_id)
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.where(Log.created_at >= cutoff)
    query = query.order_by(Log.created_at.desc()).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())