"""Парсер выдачи Drom.ru (auto.drom.ru/<марка>/<модель>/pageN/).

Карточки объявлений размечены атрибутами data-ftid — они стабильнее CSS-классов,
которые на drom генерируются. Если разметка поменяется, правки нужны только здесь.
"""
import re
from datetime import date

from bs4 import BeautifulSoup

from app import config
from app.normalize import parse_mileage, parse_price, parse_ru_date, trim_from_text
from app.scrapers.base import BaseScraper, BlockedError, PageResult, RawListing

_ID_RE = re.compile(r"/(\d{6,})\.html")
_YEAR_RE = re.compile(r",\s*((?:19|20)\d{2})")


def _text(node) -> str | None:
    return node.get_text(" ", strip=True) if node else None


def _ftid(card, name: str):
    return card.find(attrs={"data-ftid": name})


def parse_listing_page(html: str, today: date | None = None) -> PageResult:
    if re.search(r"captcha|не робот|доступ ограничен", html[:20000], re.I) and "bulls-list_bull" not in html:
        raise BlockedError("drom: капча/блокировка — задайте DROM_COOKIES или прокси с российским IP")
    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all(attrs={"data-ftid": "bulls-list_bull"})
    listings = []
    for card in cards:
        link = card if card.name == "a" else card.find("a", href=_ID_RE)
        href = link.get("href") if link else None
        m = _ID_RE.search(href or "")
        price = parse_price(_text(_ftid(card, "bull_price")))
        if not m or not price:
            continue
        title = _text(_ftid(card, "bull_title")) or _text(card.find(["h3", "h2"]))
        year_m = _YEAR_RE.search(title or "")
        desc_items = card.find_all(attrs={"data-ftid": "bull_description-item"})
        desc = ", ".join(i.get_text(" ", strip=True) for i in desc_items) or \
            _text(_ftid(card, "component_inline-bull-description")) or ""
        mileage = next((parse_mileage(i.get_text(" ", strip=True)) for i in desc_items
                        if "км" in i.get_text()), None)
        if mileage is None and "км" in desc:
            mileage = parse_mileage(desc.split(",")[-1])
        listings.append(RawListing(
            source="drom", external_id=m.group(1), url=href,
            price=price, title=title,
            year=int(year_m.group(1)) if year_m else None,
            mileage_km=mileage,
            city=_text(_ftid(card, "bull_location")),
            published_on=parse_ru_date(_text(_ftid(card, "bull_date")), today),
            trim=trim_from_text(desc),
        ))
    has_next = bool(soup.find(attrs={"data-ftid": "component_pagination-item-next"}))
    return PageResult(listings=listings, has_next=has_next)


class DromScraper(BaseScraper):
    source = "drom"

    def __init__(self, **kw):
        kw.setdefault("cookies", config.DROM_COOKIES)
        super().__init__(**kw)

    @staticmethod
    def page_url(model, page: int) -> str:
        host = f"{config.REGION_DROM}.drom.ru" if config.REGION_DROM else "auto.drom.ru"
        suffix = f"page{page}/" if page > 1 else ""
        return f"https://{host}/{model.drom_path.strip('/')}/{suffix}"

    def fetch_page(self, model, page: int) -> PageResult:
        if not model.drom_path:
            return PageResult([], False)
        resp = self.request("GET", self.page_url(model, page))
        if resp.status_code == 404:
            return PageResult([], False)
        if resp.status_code in (403, 401):
            raise BlockedError(f"drom: HTTP {resp.status_code}")
        resp.raise_for_status()
        return parse_listing_page(resp.text)
