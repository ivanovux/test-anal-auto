import json
from datetime import date
from pathlib import Path

import pytest

from app.scrapers.autoru import parse_listing_html, parse_listing_json
from app.scrapers.base import BlockedError
from app.scrapers.drom import parse_listing_page

FIX = Path(__file__).parent / "fixtures"


def test_drom_listing_page():
    res = parse_listing_page((FIX / "drom_list.html").read_text(), today=date(2026, 9, 20))
    assert res.has_next
    assert len(res.listings) == 2
    a, b = res.listings
    assert (a.external_id, a.price, a.year, a.mileage_km, a.city) == ("12345678", 2_850_000, 2019, 75_000, "Москва")
    assert a.published_on == date(2026, 9, 12)
    assert a.trim.label == "2.5 л, 181 л.с., бензин, АКПП, передний"
    assert b.trim.transmission == "АКПП" and b.published_on == date(2026, 9, 19)


def test_drom_captcha():
    with pytest.raises(BlockedError):
        parse_listing_page("<html><title>Подтвердите, что вы не робот</title>captcha</html>")


def test_autoru_json():
    data = json.loads((FIX / "autoru_listing.json").read_text())
    res = parse_listing_json(data, page=1)
    assert res.has_next and len(res.listings) == 2
    a = res.listings[0]
    assert a.external_id == "1124567890-ab12cd34"
    assert a.url == "https://auto.ru/cars/used/sale/toyota/camry/1124567890-ab12cd34/"
    assert (a.price, a.year, a.mileage_km, a.city) == (2_950_000, 2020, 61_000, "Москва")
    assert a.generation_name == "XV70" and a.complectation == "Престиж Safety"
    assert a.trim.key == "2.5|200|бензин|АКПП|передний"
    assert a.published_on == date(2025, 9, 12)
    assert not parse_listing_json(data, page=3).has_next


def test_autoru_html_initial_state():
    data = json.loads((FIX / "autoru_listing.json").read_text())
    html = f'<html><script id="initial-state" type="application/json">{json.dumps({"listing": {"data": data}})}</script></html>'
    assert len(parse_listing_html(html, 1).listings) == 2
    with pytest.raises(BlockedError):
        parse_listing_html("<html>https://auto.ru/showcaptcha?retpath=...</html>", 1)
