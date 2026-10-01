from datetime import date, timedelta

from sqlalchemy import select

from app.analytics import Query, analyze
from app.catalog import resolve_generation
from app.collector import collect_model
from app.models import CarModel, Listing
from app.normalize import Trim
from app.scrapers.base import PageResult, RawListing

D0 = date(2026, 9, 1)


class FakeScraper:
    def __init__(self, pages):
        self.pages = pages

    def iter_listings(self, model, max_pages):
        for p in self.pages[:max_pages]:
            yield from p.listings

    def close(self):
        pass


def raw(i, price, year=2019, gen=None, published=None, trim=Trim(2.5, 181, "бензин", "АКПП", "передний")):
    return RawListing(source="drom", external_id=str(i), url=f"https://x/{i}", price=price,
                      year=year, trim=trim, generation_name=gen, published_on=published, city="Москва")


def camry(s):
    return s.scalar(select(CarModel).where(CarModel.slug == "camry"))


def test_resolve_generation(session):
    gens = camry(session).generations
    assert resolve_generation(gens, 2019).name.startswith("XV70")
    assert resolve_generation(gens, 2017, "XV70 рестайлинг").name.startswith("XV70")
    assert resolve_generation(gens, 2017).name.startswith("XV50")
    assert resolve_generation(gens, 1999) is None


def test_collect_and_analyze(session):
    m = camry(session)
    # День 0: три объявления + мусорная цена; день 10: одно снизило цену, одно ушло
    collect_model(session, m, "drom", scraper=FakeScraper([PageResult(
        [raw(1, 3_000_000, published=D0 - timedelta(days=5)), raw(2, 2_000_000), raw(3, 2_500_000),
         raw(4, 1000)], False)]), today=D0)
    collect_model(session, m, "drom", scraper=FakeScraper([PageResult(
        [raw(1, 2_800_000), raw(3, 2_500_000)], False)]), today=D0 + timedelta(days=10))
    assert session.query(Listing).count() == 3  # цена 1000 отброшена

    res = analyze(session, Query(model_id=m.id, date_from=D0, date_to=D0 + timedelta(days=10),
                                 exclude_outliers=False, use_published=False))
    s = res["summary"]
    assert res["meta"]["listings"] == 3
    assert s["min_listing"]["price"] == 2_000_000
    assert s["max_listing"]["price"] == 3_000_000
    assert s["price_drops"] == 1
    first, last = res["series"][0], res["series"][-1]
    assert first["count"] == 3 and first["avg"] == 2_500_000
    assert last["count"] == 2 and last["median"] == 2_650_000
    assert res["by_year"][0]["year"] == 2019

    # Достраивание истории по дате публикации
    res2 = analyze(session, Query(model_id=m.id, date_from=D0 - timedelta(days=7), date_to=D0,
                                  exclude_outliers=False, use_published=True))
    assert res2["meta"]["estimated_days"] == 5
    assert res2["series"][0]["date"] == (D0 - timedelta(days=5)).isoformat()


def test_filters_and_outliers(session):
    m = camry(session)
    items = [raw(i, 2_000_000 + i * 10_000) for i in range(12)] + [raw(99, 25_000_000)]
    items.append(raw(50, 1_500_000, year=2015, trim=Trim(2.0, 150, "бензин", "АКПП", "передний")))
    collect_model(session, m, "drom", scraper=FakeScraper([PageResult(items, False)]), today=D0)
    q = Query(model_id=m.id, date_from=D0, date_to=D0)
    res = analyze(session, q)
    assert res["meta"]["outliers_excluded"] >= 1
    assert res["summary"]["max_listing"]["price"] < 25_000_000

    xv50 = next(g for g in m.generations if g.name.startswith("XV50"))
    res = analyze(session, Query(model_id=m.id, date_from=D0, date_to=D0, generation_id=xv50.id))
    assert res["meta"]["listings"] == 1
    res = analyze(session, Query(model_id=m.id, date_from=D0, date_to=D0,
                                 trim_key="2.0|150|бензин|АКПП|передний"))
    assert res["summary"]["avg"] == 1_500_000
    assert analyze(session, Query(model_id=m.id, date_from=D0 + timedelta(days=30),
                                  date_to=D0 + timedelta(days=40)))["summary"] is None
