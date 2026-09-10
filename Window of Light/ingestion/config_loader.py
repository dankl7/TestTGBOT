import yaml
import structlog
from pathlib import Path
from typing import List, Dict, Any

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = None

logger = structlog.get_logger(__name__)


class ChannelConfigLoader:
    """
    Загрузчик конфигурации каналов
    Поддерживает добавление каналов по ссылке
    """
    
    def __init__(self, config_path: str = "config/channels.yaml"):
        self.config_path = Path(config_path)
        self._channels: List[Dict[str, Any]] = []
        self._callbacks: list = []
        self._observer = None
        
    def load(self) -> List[Dict[str, Any]]:
        """Загружает каналы из YAML конфигурации"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                self._channels = config.get('channels', [])
                logger.info("Channels loaded", count=len(self._channels))
                return self._channels
        except Exception as e:
            logger.error("Failed to load channels", error=str(e))
            return self._channels
    
    def add_channel(self, channel_link: str, title: str = None) -> Dict[str, Any]:
        """
        Добавить канал по ссылке
        
        Args:
            channel_link: Ссылка на канал (например, https://t.me/durov или @durov)
            title: Опциональное название
            
        Returns:
            Dict: Информация о добавленном канале
        """
        channel = {
            "link": channel_link,
            "title": title or channel_link,
            "is_active": True
        }
        
        # Проверяем, есть ли уже такой канал
        for ch in self._channels:
            if ch.get('link') == channel_link:
                logger.info("Channel already exists", link=channel_link)
                return ch
        
        self._channels.append(channel)
        self._save()
        logger.info("Channel added", link=channel_link)
        
        # Уведомляем callback'и
        self._notify_callbacks()
        
        return channel
    
    def remove_channel(self, channel_link: str) -> bool:
        """Удалить канал из конфигурации"""
        initial_count = len(self._channels)
        self._channels = [
            ch for ch in self._channels 
            if ch.get('link') != channel_link
        ]
        
        if len(self._channels) < initial_count:
            self._save()
            logger.info("Channel removed", link=channel_link)
            self._notify_callbacks()
            return True
        
        return False
    
    def start_watching(self):
        """Запуск слежения за изменениями конфига"""
        if not WATCHDOG_AVAILABLE:
            logger.warning("Watchdog not available, config hot-reload disabled")
            return
        
        class ConfigChangeHandler(FileSystemEventHandler):
            def __init__(self, loader):
                self.loader = loader
            
            def on_modified(self, event):
                if Path(event.src_path) == self.loader.config_path:
                    logger.info("Config file changed, reloading...")
                    self.loader.load()
                    self.loader._notify_callbacks()
        
        self._observer = Observer()
        self._observer.schedule(
            ConfigChangeHandler(self),
            str(self.config_path.parent),
            recursive=False
        )
        self._observer.start()
        logger.info("Config watcher started", path=str(self.config_path))
    
    def stop_watching(self):
        """Остановка слежения"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
    
    def add_callback(self, callback):
        """Добавить callback для изменений конфигурации"""
        self._callbacks.append(callback)
    
    def _notify_callbacks(self):
        """Уведомить все callback'и"""
        for callback in self._callbacks:
            try:
                callback(self._channels)
            except Exception as e:
                logger.error("Callback error", error=str(e))
    
    def _save(self):
        """Сохранить конфигурацию"""
        try:
            config = {"channels": self._channels}
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            logger.error("Failed to save config", error=str(e))
    
    def get_active_channels(self) -> List[Dict[str, Any]]:
        """Получить только активные каналы"""
        return [ch for ch in self._channels if ch.get('is_active', True)]
    
    def get_all_channels(self) -> List[Dict[str, Any]]:
        """Получить все каналы"""
        return self._channels
