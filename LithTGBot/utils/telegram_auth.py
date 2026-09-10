import asyncio


class TelegramSmsCodeProvider:
    """Bridges pymax SMS auth with Telegram user input."""

    def __init__(self):
        self._event = asyncio.Event()
        self._code: str = ""
        self._phone: str = ""

    async def get_code(self, phone: str) -> str:
        self._phone = phone
        self._event.clear()
        self._code = ""
        await self._event.wait()
        return self._code

    def set_code(self, code: str):
        self._code = code
        self._event.set()

    def clear(self):
        self._code = ""
        self._event.clear()


class TelegramPasswordProvider:
    """Bridges pymax 2FA password with Telegram user input."""

    def __init__(self):
        self._event = asyncio.Event()
        self._password: str = ""
        self._hint: str | None = None

    async def get_password(self, hint: str | None = None) -> str:
        self._hint = hint
        self._event.clear()
        self._password = ""
        await self._event.wait()
        return self._password

    def set_password(self, password: str):
        self._password = password
        self._event.set()

    def clear(self):
        self._password = ""
        self._event.clear()


sms_provider = TelegramSmsCodeProvider()
password_provider = TelegramPasswordProvider()
