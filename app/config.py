"""Настройки приложения из переменных окружения."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'app.db'}")
CATALOG_PATH = Path(os.getenv("CATALOG_PATH", BASE_DIR / "data" / "catalog.json"))

# Сбор данных
ENABLED_SOURCES = [s.strip() for s in os.getenv("SOURCES", "drom,autoru").split(",") if s.strip()]
MAX_PAGES = int(os.getenv("MAX_PAGES", "5"))            # страниц выдачи на модель и площадку
REQUEST_DELAY_MIN = float(os.getenv("REQUEST_DELAY_MIN", "2"))
REQUEST_DELAY_MAX = float(os.getenv("REQUEST_DELAY_MAX", "5"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))
HTTP_PROXY = os.getenv("SCRAPER_PROXY") or None        # например http://user:pass@host:port
AUTORU_COOKIES = os.getenv("AUTORU_COOKIES", "")      # строка Cookie из браузера (обход капчи)
DROM_COOKIES = os.getenv("DROM_COOKIES", "")
REGION_DROM = os.getenv("REGION_DROM", "")             # поддомен drom: '' = вся Россия, 'moscow', 'spb'...
REGION_AUTORU = os.getenv("REGION_AUTORU", "rossiya")  # 'rossiya', 'moskva', 'sankt-peterburg'...

# Планировщик: ежедневный сбор
ENABLE_SCHEDULER = _bool("ENABLE_SCHEDULER", True)
COLLECT_HOUR = int(os.getenv("COLLECT_HOUR", "4"))
COLLECT_MINUTE = int(os.getenv("COLLECT_MINUTE", "17"))

# Отсечение мусорных цен (запчасти, «1 рубль» и т.п.)
MIN_VALID_PRICE = int(os.getenv("MIN_VALID_PRICE", "50000"))
