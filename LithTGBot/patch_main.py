import sys

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

import_str = 'from aiogram.client.session.aiohttp import AiohttpSession\n'

session_str = '''
    # Настройка прокси
    session = None
    if settings.telegram_proxy_url:
        logger.info(f"Используется прокси для Telegram: {settings.telegram_proxy_host}:{settings.telegram_proxy_port}")
        session = AiohttpSession(proxy=settings.telegram_proxy_url)

    # Инициализация бота с дефолтными настройками
    bot = Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
'''

content = content.replace('from aiogram import Bot, Dispatcher', 'from aiogram import Bot, Dispatcher\n' + import_str)
content = content.replace('''    # Инициализация бота с дефолтными настройками
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )''', session_str)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
