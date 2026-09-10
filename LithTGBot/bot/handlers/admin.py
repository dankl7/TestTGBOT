import logging

from aiogram import Router
from aiogram.types import Message

from config import settings

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_user_ids
