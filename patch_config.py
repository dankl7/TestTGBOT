import sys

with open('config.py', 'r', encoding='utf-8') as f:
    content = f.read()

proxy_fields = '''
    telegram_proxy_host: str | None = None
    telegram_proxy_port: int | None = None
    telegram_proxy_user: str | None = None
    telegram_proxy_pass: str | None = None
    telegram_proxy_type: str | None = None

    @property
    def telegram_proxy_url(self) -> str | None:
        if self.telegram_proxy_host and self.telegram_proxy_port:
            if self.telegram_proxy_user and self.telegram_proxy_pass:
                return f"http://{self.telegram_proxy_user}:{self.telegram_proxy_pass}@{self.telegram_proxy_host}:{self.telegram_proxy_port}"
            return f"http://{self.telegram_proxy_host}:{self.telegram_proxy_port}"
        return None
'''

content = content.replace('    # Window of Light API', proxy_fields + '\n    # Window of Light API')

with open('config.py', 'w', encoding='utf-8') as f:
    f.write(content)
