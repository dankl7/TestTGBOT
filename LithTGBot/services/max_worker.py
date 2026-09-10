import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import async_session_maker
from database.models import Project, Group, Schedule, Log, Message
from database.repositories import repo
from utils.encryption import decrypt_token

logger = logging.getLogger(__name__)

WORKER_INTERVAL = 30
PING_INTERVAL = 300
CLEANUP_INTERVAL = 86400


class MaxAPIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def _get_client(project: Project):
    from pymax import Client
    from config import SESSIONS_DIR
    import os

    main_session = os.path.join(SESSIONS_DIR, "main_session.db")
    if os.path.exists(main_session):
        return Client(
            phone="00000000000",
            work_dir=str(SESSIONS_DIR),
            session_name="main_session.db",
        )

    from utils.encryption import decrypt_token
    token = decrypt_token(project.auth_token)
    return Client(
        phone="00000000000",
        work_dir=str(SESSIONS_DIR),
        session_name="main_session.db",
        extra_config={"token": token},
    )


async def send_with_retry(client, group_id: int, text: str, media_type: str | None = None, media_path: str | None = None) -> bool:
    delays = [5, 10, 15]
    for i, delay in enumerate(delays):
        try:
            await asyncio.sleep(random.uniform(2.0, 5.0))
            attachments = []
            if media_type and media_path:
                if media_type == "photo":
                    from pymax import Photo
                    attachments.append(Photo(path=media_path))
                elif media_type == "video":
                    from pymax import Video
                    attachments.append(Video(path=media_path))
                elif media_type == "document":
                    from pymax import File
                    attachments.append(File(path=media_path))
            if attachments:
                await client.send_message(chat_id=group_id, text=text, attachments=attachments)
            else:
                await client.send_message(chat_id=group_id, text=text)
            return True
        except Exception as e:
            error_msg = str(e)
            logger.warning("Send attempt %d failed for group %s: %s", i + 1, group_id, error_msg)
            if "401" in error_msg or "403" in error_msg:
                raise MaxAPIError(401, "Invalid token")
            if i == len(delays) - 1:
                return False
            await asyncio.sleep(delay)
    return False


async def process_group(group: Group) -> bool:
    async with async_session_maker() as session:
        project = await session.get(Project, group.project_id)
        if not project or not project.is_active:
            return False

        msg_id = group.custom_message_id or project.default_message_id
        if not msg_id:
            await repo.add_log(session, project.id, group_id=group.id, status="ERROR", message="No message configured")
            await session.commit()
            group.is_active = False
            await session.commit()
            await notify_owner(project.owner_id, f"⚠️ Рассылка в группу {group.max_group_id} остановлена: не задано ни кастомное, ни дефолтное сообщение.")
            return False

        msg = await session.get(Message, msg_id)
        if not msg:
            await repo.add_log(session, project.id, group_id=group.id, status="ERROR", message="Message not found")
            await session.commit()
            return False

        msg_text = msg.text_content or ""
        msg_media_type = msg.media_type
        msg_media_path = msg.media_path

        schedules_result = await session.execute(
            select(Schedule).where(Schedule.group_id == group.id)
        )
        schedules = list(schedules_result.scalars().all())

    client = _get_client(project)
    try:
        await client.start()
        success = await send_with_retry(client, group.max_group_id, msg_text, msg_media_type, msg_media_path)
    finally:
        try:
            await client.stop()
        except Exception:
            pass

    async with async_session_maker() as session:
        if success:
            await repo.add_log(session, project.id, group_id=group.id, status="SUCCESS", message="Message sent")
            for sched in schedules:
                if sched.schedule_type == "interval":
                    await repo.update_schedule_last_sent(session, sched.id, datetime.now(timezone.utc))
            await session.commit()
        else:
            await repo.add_log(session, project.id, group_id=group.id, status="ERROR", message="Failed after retries")
            g = await session.get(Group, group.id)
            if g:
                g.is_active = False
            await session.commit()
            await notify_owner(project.owner_id, f"❌ Ошибка отправки в группу {group.max_group_id} после ретраев. Группа остановлена.")

    return success


async def notify_owner(owner_id: int, text: str):
    try:
        from aiogram import Bot
        from aiogram.client.session.aiohttp import AiohttpSession
        session = None
        if settings.telegram_proxy_url:
            session = AiohttpSession(proxy=settings.telegram_proxy_url)
        bot = Bot(token=settings.telegram_bot_token, session=session)
        await bot.send_message(owner_id, text)
        await bot.session.close()
    except Exception as e:
        logger.error("Failed to notify owner %s: %s", owner_id, e)


async def check_schedules():
    async with async_session_maker() as session:
        result = await session.execute(
            select(Group)
            .join(Project, Project.id == Group.project_id)
            .where(Group.is_active.is_(True), Project.is_active.is_(True))
        )
        groups = list(result.scalars().all())

        for group in groups:
            schedules_result = await session.execute(
                select(Schedule).where(Schedule.group_id == group.id)
            )
            group._loaded_schedules = list(schedules_result.scalars().all())

            project = await session.get(Project, group.project_id)
            group._loaded_project = project

    now = datetime.now(timezone.utc)

    for group in groups:
        schedules = getattr(group, '_loaded_schedules', [])
        project = getattr(group, '_loaded_project', None)
        if not schedules or not project:
            continue

        for sched in schedules:
            should_send = False

            if sched.schedule_type == "interval":
                interval_hours = sched.schedule_value.get("hours", 1)
                last = sched.last_sent_at
                if last is None:
                    should_send = True
                else:
                    next_send = last + timedelta(hours=interval_hours)
                    if now >= next_send:
                        should_send = True

            elif sched.schedule_type == "exact":
                times = sched.schedule_value.get("times", [])
                user_tz_offset = 3
                owner = getattr(project, 'owner', None)
                if owner:
                    user_tz_offset = owner.timezone
                user_tz = timezone(timedelta(hours=user_tz_offset))

                for t_str in times:
                    h, m = map(int, t_str.split(":"))
                    local_now = now.astimezone(user_tz)
                    target_local = local_now.replace(hour=h, minute=m, second=0, microsecond=0)
                    target_utc = target_local.astimezone(timezone.utc)

                    if target_local < local_now:
                        target_utc += timedelta(days=1)

                    last = sched.last_sent_at
                    if last is None or last < target_utc - timedelta(minutes=1):
                        if now >= target_utc:
                            should_send = True
                            break

            if should_send:
                await process_group(group)
                break


async def ping_session(project: Project) -> bool:
    client = _get_client(project)
    try:
        await client.start()
        await client.send_message(chat_id=-0, text="ping")
        logger.debug("Ping OK for project %s", project.id)
        return True
    except Exception as e:
        logger.warning("Ping failed for project %s: %s", project.id, e)
        return False
    finally:
        try:
            await client.stop()
        except Exception:
            pass


async def pinger_loop():
    ping_failures: dict[UUID, int] = {}
    while True:
        await asyncio.sleep(PING_INTERVAL)
        async with async_session_maker() as session:
            result = await session.execute(select(Project).where(Project.is_active.is_(True)))
            projects = list(result.scalars().all())

        for project in projects:
            ok = await ping_session(project)
            if not ok:
                ping_failures[project.id] = ping_failures.get(project.id, 0) + 1
                if ping_failures[project.id] >= 3:
                    async with async_session_maker() as session:
                        p = await session.get(Project, project.id)
                        if p:
                            p.is_active = False
                            await session.commit()
                    await notify_owner(project.owner_id, f"🚨 Проект {project.name} остановлен: токен MAX невалиден (3 пинга подряд упали).")
                    ping_failures.pop(project.id, None)
            else:
                ping_failures.pop(project.id, None)


async def cleanup_loop():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        async with async_session_maker() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            result = await session.execute(delete(Log).where(Log.created_at < cutoff))
            await session.commit()
            logger.info("Cleaned up %d old logs", result.rowcount)


async def start_worker():
    logger.info("Worker started")
    await asyncio.gather(
        scheduler_loop(),
        pinger_loop(),
        cleanup_loop(),
    )


async def scheduler_loop():
    while True:
        start = datetime.now(timezone.utc)
        try:
            await check_schedules()
        except Exception as e:
            logger.error("Scheduler error: %s", e)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        await asyncio.sleep(max(1, WORKER_INTERVAL - elapsed))
