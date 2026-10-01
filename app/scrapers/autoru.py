"""Парсер Auto.ru.

Основной путь — JSON-эндпоинт, который использует сам сайт при листании выдачи
(POST /-/ajax/desktop/listing/, нужен csrf-токен из cookie `_csrf_token`).
Запасной путь — JSON начального состояния, встроенный в HTML страницы выдачи.
У Auto.ru агрессивная антибот-защита: при капче сборщик останавливается по этой
площадке и пишет статус «blocked». Помогает российский IP и cookies из браузера
(переменная AUTORU_COOKIES).
"""
import json
import re
from datetime import datetime, timezone

from app import config
from app.normalize import parse_int, trim_from_fields
from app.scrapers.base import BaseScraper, BlockedError, PageResult, RawListing

AJAX_URL = "https://auto.ru/-/ajax/desktop/listing/"


def _get(d, *path, default=None):
    for key in path:
        if not isinstance(d, dict):
            return default
        d = d.get(key)
    return default if d is None else d


def parse_offer(offer: dict) -> RawListing | None:
    price = _get(offer, "price_info", "RUR") or _get(offer, "price_info", "price")
    price = parse_int(price)
    offer_id, offer_hash = offer.get("id"), offer.get("hash")
    if not price or not offer_id:
        return None
    vi = offer.get("vehicle_info") or {}
    tp = vi.get("tech_param") or {}
    mark = (_get(vi, "mark_info", "code") or "").lower()
    model = (_get(vi, "model_info", "code") or "").lower()
    section = offer.get("section") or "used"
    ext_id = f"{offer_id}-{offer_hash}" if offer_hash else str(offer_id)
    url = offer.get("url") or f"https://auto.ru/cars/{section}/sale/{mark}/{model}/{ext_id}/"
    created = _get(offer, "additional_info", "creation_date")
    published = None
    if created:
        try:
            published = datetime.fromtimestamp(int(created) / 1000, tz=timezone.utc).date()
        except (TypeError, ValueError):
            pass
    gen = vi.get("super_gen") or {}
    title_parts = [_get(vi, "mark_info", "name"), _get(vi, "model_info", "name"), gen.get("name")]
    return RawListing(
        source="autoru", external_id=ext_id, url=url, price=price,
        title=" ".join(p for p in title_parts if p) or None,
        year=parse_int(_get(offer, "documents", "year")),
        mileage_km=parse_int(_get(offer, "state", "mileage")),
        city=_get(offer, "seller", "location", "region_info", "name"),
        published_on=published,
        trim=trim_from_fields(parse_int(tp.get("displacement")), parse_int(tp.get("power")),
                              tp.get("engine_type"), tp.get("transmission"), tp.get("gear_type")),
        complectation=_get(vi, "complectation", "name") or None,
        generation_name=gen.get("name") or gen.get("ru_name"),
    )


def parse_listing_json(data: dict, page: int) -> PageResult:
    offers = data.get("offers") or []
    listings = [l for l in (parse_offer(o) for o in offers) if l]
    total_pages = _get(data, "pagination", "total_page_count", default=page)
    return PageResult(listings=listings, has_next=int(total_pages) > page)


def _find_offers_container(obj, depth=0):
    """Ищет в произвольном JSON словарь, у которого есть список 'offers' с объявлениями."""
    if depth > 8:
        return None
    if isinstance(obj, dict):
        offers = obj.get("offers")
        if isinstance(offers, list) and offers and isinstance(offers[0], dict) and "price_info" in offers[0]:
            return obj
        for v in obj.values():
            if found := _find_offers_container(v, depth + 1):
                return found
    elif isinstance(obj, list):
        for v in obj[:50]:
            if found := _find_offers_container(v, depth + 1):
                return found
    return None


def parse_listing_html(html: str, page: int) -> PageResult:
    if _is_captcha(html):
        raise BlockedError("auto.ru: капча — задайте AUTORU_COOKIES из браузера или российский прокси")
    for m in re.finditer(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        if container := _find_offers_container(data):
            return parse_listing_json(container, page)
    return PageResult([], False)


def _is_captcha(text: str) -> bool:
    return "showcaptcha" in text[:5000] or "SmartCaptcha" in text[:20000]


class AutoRuScraper(BaseScraper):
    source = "autoru"

    def __init__(self, **kw):
        kw.setdefault("cookies", config.AUTORU_COOKIES)
        super().__init__(**kw)
        self._warmed = False
        self._ajax_ok = True

    @staticmethod
    def page_url(model, page: int) -> str:
        url = (f"https://auto.ru/{config.REGION_AUTORU}/cars/"
               f"{model.autoru_mark.lower()}/{model.autoru_model.lower()}/all/")
        return url + (f"?page={page}" if page > 1 else "")

    def _get_html(self, model, page: int):
        resp = self.request("GET", self.page_url(model, page))
        if "showcaptcha" in str(resp.url) or _is_captcha(resp.text):
            raise BlockedError("auto.ru: капча — задайте AUTORU_COOKIES из браузера или российский прокси")
        return resp

    def fetch_page(self, model, page: int) -> PageResult:
        if not (model.autoru_mark and model.autoru_model):
            return PageResult([], False)
        if not self._warmed:  # первая загрузка HTML выдаёт cookies, включая csrf-токен
            resp = self._get_html(model, page)
            self._warmed = True
            result = parse_listing_html(resp.text, page)
            if result.listings:
                return result
        if self._ajax_ok:
            try:
                return self._fetch_ajax(model, page)
            except BlockedError:
                raise
            except Exception:  # noqa: BLE001 — переходим на HTML-разбор
                self._ajax_ok = False
        return parse_listing_html(self._get_html(model, page).text, page)

    def _fetch_ajax(self, model, page: int) -> PageResult:
        csrf = self.client.cookies.get("_csrf_token", "")
        body = {"catalog_filter": [{"mark": model.autoru_mark, "model": model.autoru_model}],
                "section": "all", "category": "cars", "output_type": "list",
                "sort": "cr_date-desc", "page": page}
        resp = self.request("POST", AJAX_URL, json=body, headers={
            "x-csrf-token": csrf, "x-requested-with": "XMLHttpRequest",
            "content-type": "application/json", "origin": "https://auto.ru",
            "referer": self.page_url(model, page)})
        if _is_captcha(resp.text):
            raise BlockedError("auto.ru: капча на JSON-эндпоинте")
        resp.raise_for_status()
        return parse_listing_json(resp.json(), page)
