import asyncio
import logging
import os
import socket
import subprocess
import shutil

logger = logging.getLogger(__name__)

SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 1080
CHECK_INTERVAL = 45
FAIL_THRESHOLD = 2
TELEGRAM_CHECK_URL = "https://api.telegram.org"

_VPN_CLI: str | None = None


def _resolve_vpn():
    global _VPN_CLI
    if _VPN_CLI:
        return _VPN_CLI
    found = shutil.which("adguardvpn-cli")
    if found:
        _VPN_CLI = found
        return found
    for p in (
        "/home/dankl/.local/bin/adguardvpn-cli",
        "/usr/local/bin/adguardvpn-cli",
        "/usr/bin/adguardvpn-cli",
    ):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            _VPN_CLI = p
            return p
    _VPN_CLI = ""
    return None


def _run(args: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, str(e)


def socks_alive() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            return s.connect_ex((SOCKS_HOST, SOCKS_PORT)) == 0
    except Exception:
        return False


async def telegram_reachable() -> bool:
    cli = shutil.which("curl") or "/usr/bin/curl"
    try:
        proc = await asyncio.create_subprocess_exec(
            cli, "--silent", "--show-error",
            "--socks5-hostname", f"{SOCKS_HOST}:{SOCKS_PORT}",
            "--max-time", "10", "--connect-timeout", "8",
            "-o", "/dev/null", "-w", "%{http_code}",
            TELEGRAM_CHECK_URL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return False
        code = stdout.decode().strip()
        return code.isdigit() and int(code) > 0
    except Exception as e:
        logger.debug("Telegram reachability check: %s", e)
        return False


def vpn_connected() -> bool:
    cli = _resolve_vpn()
    if not cli:
        return False
    rc, out = _run([cli, "status"], timeout=8)
    s = out.lower()
    if "connected" in s and "not connected" not in s and "disconnected" not in s:
        return True
    return False


def vpn_connect() -> str:
    cli = _resolve_vpn()
    if not cli:
        return "vpn CLI not found"
    _run([cli, "disconnect"], timeout=8)
    rc, out = _run([cli, "connect"], timeout=25)
    return "ok" if rc == 0 else out[-200:]


def vpn_disconnect() -> str:
    cli = _resolve_vpn()
    if not cli:
        return "vpn CLI not found"
    rc, out = _run([cli, "disconnect"], timeout=8)
    return "ok" if rc == 0 else out[-200:]


async def check_and_repair() -> str:
    """Full check cycle: port → Telegram → if down, reconnect VPN. Returns status."""
    if not socks_alive():
        logger.warning("SOCKS5 port %s:%s not listening", SOCKS_HOST, SOCKS_PORT)
        if vpn_connected():
            logger.info("VPN claims connected but port is dead — reconnecting")
            r = vpn_connect()
            await asyncio.sleep(3)
        else:
            logger.info("VPN disconnected, connecting...")
            r = vpn_connect()
            await asyncio.sleep(3)
        if socks_alive():
            return "recovered (port)"
        return "failed (port down)"

    if not await telegram_reachable():
        logger.warning("SOCKS5 port open but Telegram unreachable through proxy")
        if vpn_connected():
            logger.info("Reconnecting VPN to get fresh proxy route...")
            vpn_disconnect()
            await asyncio.sleep(1)
            vpn_connect()
            await asyncio.sleep(5)
        else:
            vpn_connect()
            await asyncio.sleep(5)
        if await telegram_reachable():
            return "recovered (telegram)"
        return "failed (telegram unreachable)"

    return "ok"


async def proxy_watchdog():
    """Background task: check proxy every CHECK_INTERVAL, auto-repair."""
    logger.info("Proxy watchdog started (interval=%ds)", CHECK_INTERVAL)
    fails = 0
    while True:
        try:
            status = await check_and_repair()
            if status == "ok":
                fails = 0
            else:
                fails += 1
                logger.error("Proxy check #%d: %s", fails, status)
                if fails >= FAIL_THRESHOLD:
                    logger.warning("Proxy down for %d checks, aggressive recovery...", fails)
                    vpn_disconnect()
                    await asyncio.sleep(2)
                    vpn_connect()
                    await asyncio.sleep(5)
                    fails = 0
        except Exception as e:
            logger.error("Proxy watchdog error: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)
