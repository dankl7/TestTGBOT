#!/usr/bin/env python3
"""
Container Watcher — следит что все Docker-контейнеры проекта работают
и реально способны общаться с Telegram через SOCKS5.

Запускается через crontab @reboot:
    @reboot /usr/bin/python3 /home/dankl/my-project/Window of Light/container_watcher.py \\
             >> /home/dankl/my-project/Window of Light/container_watcher.log 2>&1

Основной мониторинг VPN делает proxy_health_monitor.py (systemd).
Этот скрипт — дополнительная страховка:
  - если контейнер упал — поднимает;
  - если SOCKS-прокси не отвечает — перезапускает VPN;
  - если proxy-monitor.service умер — поднимает его обратно.
"""

import os
import re
import subprocess
import sys
import time
import logging
import shutil
from logging.handlers import RotatingFileHandler

LOG_FILE = "/home/dankl/my-project/Window of Light/container_watcher.log"
CHECK_INTERVAL = 60
STUCK_RESTART_THRESHOLD = 50  # restartCount > N → контейнер застрял в retry-loop
SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 1080

PROXY_MONITOR_SERVICE = "proxy-monitor.service"


def _resolve_vpn_cli() -> str:
    found = shutil.which("adguardvpn-cli")
    if found:
        return found
    for p in ("/home/dankl/.local/bin/adguardvpn-cli",
              "/usr/local/bin/adguardvpn-cli",
              "/usr/bin/adguardvpn-cli",
              "/root/.local/bin/adguardvpn-cli"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return "adguardvpn-cli"


VPN_CLI = _resolve_vpn_cli()
HAS_SUDO = shutil.which("sudo") is not None

CONTAINERS = {
    "wol_app": "/home/dankl/my-project/Window of Light/Window of Light",
    "lithtgbot": "/home/dankl/my-project/Window of Light/LithTGBot",
    "lithtgbot_worker": "/home/dankl/my-project/Window of Light/LithTGBot",
    "lithtgbot_beat": "/home/dankl/my-project/Window of Light/LithTGBot",
}


# ─── Логирование (без дублей) ────────────────────────────────────────────────

class DedupRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler, который не пишет одну и ту же запись подряд."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_msg = None

    def emit(self, record):
        try:
            msg = self.format(record)
            if msg == self._last_msg:
                return
            self._last_msg = msg
            super().emit(record)
        except Exception:
            self.handleError(record)


log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

file_handler = DedupRotatingFileHandler(
    LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
file_handler.setFormatter(log_formatter)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)

logger = logging.getLogger("container_watcher")
logger.setLevel(logging.INFO)
logger.handlers.clear()
logger.addHandler(file_handler)
logger.addHandler(stream_handler)
logger.propagate = False


# ─── Утилиты ─────────────────────────────────────────────────────────────────

def _run_list(args: list, timeout: int = 30) -> tuple[int, str]:
    """Запустить argv-список без shell, вернуть (rc, output).

    Безопасная альтернатива _run() — никаких shell-инъекций.
    """
    try:
        r = subprocess.run(
            args, shell=False, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def _run(cmd, timeout: int = 30, shell: bool = False):
    """Legacy helper. По умолчанию shell=False; разрешено True только для
    полностью зашитых в коде строк (см. _ensure_vpn: pkill -9 -f).
    """
    try:
        r = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


# Регексп для имён контейнеров / systemd-юнитов — всё, что не alnum._- отвергаем.
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


def _docker_state(name: str) -> dict:
    if not _SAFE_NAME.match(name):
        logger.warning("Refusing to inspect container with suspicious name: %r", name)
        return {"status": "missing", "restarts": 0}
    code, out = _run_list(
        ["docker", "inspect", "--format", "{{.State.Status}}|{{.RestartCount}}", name],
        timeout=10,
    )
    if code != 0 or "|" not in out:
        return {"status": "missing", "restarts": 0}
    parts = out.split("|", 1)
    try:
        return {"status": parts[0].strip(), "restarts": int(parts[1].strip() or 0)}
    except (ValueError, IndexError):
        return {"status": parts[0].strip(), "restarts": 0}


def _socks_listening() -> bool:
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            return s.connect_ex((SOCKS_HOST, SOCKS_PORT)) == 0
    except Exception:
        return False


def _socks_reachable() -> bool:
    """Проверить, что SOCKS реально выводит в Telegram (а не просто слушает)."""
    code, _ = _run_list(
        [
            "curl", "-s", "--max-time", "10",
            "--socks5-hostname", f"{SOCKS_HOST}:{SOCKS_PORT}",
            "https://api.telegram.org",
            "-o", "/dev/null", "-w", "%{http_code}",
        ],
        timeout=15,
    )
    if code != 0:
        return False
    return True


def _vpn_status() -> str:
    code, out = _run_list([VPN_CLI, "status"], timeout=10)
    s = out.lower()
    if code == 0 and "connected" in s and "disconnected" not in s and "not connected" not in s:
        return "connected"
    if "disconnected" in s or "not connected" in s:
        return "disconnected"
    return "unknown"


def _ensure_vpn() -> bool:
    """Перезапустить VPN, если он не отвечает или SOCKS не работает."""
    if not _socks_listening():
        logger.warning("SOCKS port not listening, reconnecting VPN...")
        # shell=True допустим — аргументы полностью зашиты в код.
        _run("pkill -9 -f adguardvpn-cli 2>/dev/null", timeout=5, shell=True)
        time.sleep(3)
        _run_list([VPN_CLI, "connect", "-f", "-y"], timeout=45)
        time.sleep(8)
        return _socks_listening()
    if not _socks_reachable():
        logger.warning("SOCKS listening but unreachable, reconnecting VPN...")
        _run("pkill -9 -f adguardvpn-cli 2>/dev/null", timeout=5, shell=True)
        time.sleep(3)
        _run_list([VPN_CLI, "connect", "-f", "-y"], timeout=45)
        time.sleep(8)
        return _socks_reachable()
    return True


def _detect_docker_compose() -> str:
    """v2 (`docker compose`) → v1 (`docker-compose`).

    Под root на этом хосте есть только v1 — см. комментарий в proxy_health_monitor.py.
    """
    try:
        r = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return "v2"
    except Exception:
        pass
    v1 = shutil.which("docker-compose")
    return v1 or "v2"


DOCKER_COMPOSE_CMD = _detect_docker_compose()


def _ensure_container(project_dir: str, container: str) -> bool:
    if not _SAFE_NAME.match(container) or ".." in project_dir or not project_dir.startswith("/"):
        logger.error("Refusing to manage container with suspicious path/name: %r in %r",
                     container, project_dir)
        return False
    if DOCKER_COMPOSE_CMD == "v2":
        argv = ["docker", "compose", "-f", f"{project_dir}/docker-compose.yml", "up", "-d"]
    else:
        argv = [DOCKER_COMPOSE_CMD, "-f", f"{project_dir}/docker-compose.yml", "up", "-d"]
    code, out = _run_list(argv, timeout=180)
    if code == 0:
        logger.info("Started/restarted %s in %s", container, project_dir)
        return True
    logger.error("Failed to start %s in %s: %s", container, project_dir, out)
    return False


def _restart_container_directly(container: str) -> bool:
    """Жёсткий docker restart одного контейнера (быстрее compose up)."""
    if not _SAFE_NAME.match(container):
        logger.error("Refusing to restart container with suspicious name: %r", container)
        return False
    code, out = _run_list(["docker", "restart", container], timeout=60)
    if code == 0:
        logger.info("docker restart %s → OK", container)
        return True
    logger.warning("docker restart %s failed: %s", container, out)
    return False


def _ensure_proxy_monitor_service() -> None:
    """Поднять systemd-сервис proxy-monitor, если он умер."""
    if shutil.which("systemctl") is None:
        return
    code, _ = _run_list(
        ["systemctl", "is-active", "proxy-monitor.service"], timeout=10
    )
    if code == 0:
        return
    logger.warning("proxy-monitor.service is NOT active, trying to start it...")
    if HAS_SUDO:
        _run_list(
            ["sudo", "-n", "systemctl", "reset-failed", "proxy-monitor.service"],
            timeout=10,
        )
        _run_list(
            ["sudo", "-n", "systemctl", "restart", "proxy-monitor.service"],
            timeout=10,
        )
        time.sleep(2)
        code2, _ = _run_list(
            ["systemctl", "is-active", "proxy-monitor.service"], timeout=10
        )
        if code2 == 0:
            logger.info("proxy-monitor.service restarted")
        else:
            logger.error("Failed to restart proxy-monitor.service — check sudoers NOPASSWD")
    else:
        logger.error("systemctl present but no sudo — cannot restart proxy-monitor.service")


# ─── Главный цикл ────────────────────────────────────────────────────────────

def check_and_restart():
    # 1. VPN и SOCKS
    _ensure_vpn()

    # 2. systemd-сервис мониторинга
    _ensure_proxy_monitor_service()

    # 3. Контейнеры
    bad = []
    for container, project_dir in CONTAINERS.items():
        s = _docker_state(container)
        if s["status"] != "running":
            bad.append((container, project_dir, f"{s['status']}"))
        elif s["restarts"] > STUCK_RESTART_THRESHOLD:
            bad.append((container, project_dir, f"stuck({s['restarts']} restarts)"))

    for container, project_dir, why in bad:
        logger.warning("Container %s UNHEALTHY (%s) — restarting", container, why)
        # Сначала пробуем лёгкий restart, если не помогло — compose up -d
        if not _restart_container_directly(container):
            _ensure_container(project_dir, container)


def main():
    logger.info("=== Container Watcher started (interval: %ds) ===", CHECK_INTERVAL)
    time.sleep(15)

    while True:
        try:
            check_and_restart()
        except Exception as e:
            logger.exception("Error in check loop: %s", e)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
