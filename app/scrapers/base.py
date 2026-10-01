import logging
import random
import time
from dataclasses import dataclass, field
from datetime import date

import httpx

from app import config
from app.normalize import Trim

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
]


class BlockedError(RuntimeError):
    """Площадка отдала капчу/блокировку — дальше по этой площадке не идём."""


@dataclass
class RawListing:
    source: str
    external_id: str
    url: str
    price: int
    title: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    city: str | None = None
    published_on: date | None = None
    trim: Trim = field(default_factory=Trim)
    complectation: str | None = None
    generation_name: str | None = None   # название/код поколения с площадки, если есть


@dataclass
class PageResult:
    listings: list[RawListing]
    has_next: bool


def parse_cookie_string(raw: str) -> dict[str, str]:
    cookies = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


class BaseScraper:
    source = ""

    def __init__(self, client: httpx.Client | None = None, delay: tuple[float, float] | None = None,
                 cookies: str = ""):
        self.delay = delay if delay is not None else (config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX)
        self.client = client or httpx.Client(
            headers={"User-Agent": random.choice(USER_AGENTS),
                     "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
                     "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"},
            cookies=parse_cookie_string(cookies),
            proxy=config.HTTP_PROXY, timeout=config.REQUEST_TIMEOUT, follow_redirects=True)
        self._last_request = 0.0

    def _throttle(self) -> None:
        wait = random.uniform(*self.delay) - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        for attempt in range(3):
            self._throttle()
            try:
                resp = self.client.request(method, url, **kw)
            except httpx.TransportError as e:
                log.warning("%s: сетевая ошибка %s (попытка %d)", self.source, e, attempt + 1)
                time.sleep(2 ** attempt * 3)
                continue
            if resp.status_code in (429, 503):
                time.sleep(2 ** attempt * 10)
                continue
            return resp
        raise RuntimeError(f"{self.source}: не удалось получить {url}")

    def fetch_page(self, model, page: int) -> PageResult:  # pragma: no cover - реализуют наследники
        raise NotImplementedError

    def iter_listings(self, model, max_pages: int):
        for page in range(1, max_pages + 1):
            result = self.fetch_page(model, page)
            yield from result.listings
            if not result.has_next or not result.listings:
                break

    def close(self) -> None:
        self.client.close()
