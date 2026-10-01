"""Аналитика цен за период.

Модель данных: объявление «живёт» с первого до последнего дня, когда мы его видели;
между снимками действует последняя наблюдённая цена. Опционально (use_published=True)
жизнь объявления продлевается назад до даты публикации с первой наблюдённой ценой —
это оценка, позволяющая получить историю ещё до начала сбора.
"""
import statistics
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Listing


@dataclass
class Query:
    model_id: int
    date_from: date
    date_to: date
    generation_id: int | None = None
    trim_key: str | None = None
    sources: list[str] | None = None
    year_from: int | None = None
    year_to: int | None = None
    exclude_outliers: bool = True
    use_published: bool = True


@dataclass
class _Track:
    listing: Listing
    start: date
    end: date
    dates: list[date]
    prices: list[int]

    def price_on(self, d: date) -> int | None:
        if d < self.start or d > self.end:
            return None
        i = bisect_right(self.dates, d) - 1
        return self.prices[max(i, 0)]  # до первого снимка — первая цена (оценка по дате публикации)


def _tracks(session: Session, q: Query) -> list[_Track]:
    stmt = select(Listing).where(Listing.model_id == q.model_id).options(selectinload(Listing.observations))
    if q.generation_id:
        stmt = stmt.where(Listing.generation_id == q.generation_id)
    if q.trim_key:
        stmt = stmt.where(Listing.trim_key == q.trim_key)
    if q.sources:
        stmt = stmt.where(Listing.source.in_(q.sources))
    if q.year_from:
        stmt = stmt.where(Listing.year >= q.year_from)
    if q.year_to:
        stmt = stmt.where(Listing.year <= q.year_to)
    tracks = []
    for l in session.scalars(stmt):
        obs = l.observations
        if not obs:
            continue
        start = l.first_seen
        if q.use_published and l.published_on and l.published_on < start:
            start = l.published_on
        end = l.last_seen
        if end < q.date_from or start > q.date_to:
            continue
        tracks.append(_Track(l, start, end, [o.observed_on for o in obs], [o.price for o in obs]))
    return tracks


def _fences(prices: list[int]) -> tuple[float, float]:
    if len(prices) < 8:
        return float("-inf"), float("inf")
    q1, _, q3 = statistics.quantiles(prices, n=4)
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def _stats(values: list[int]) -> dict | None:
    if not values:
        return None
    return {"count": len(values), "avg": round(statistics.fmean(values)),
            "median": round(statistics.median(values)), "min": min(values), "max": max(values)}


def _listing_dict(t: _Track, price: int, on: date | None = None) -> dict:
    l = t.listing
    return {"id": l.id, "source": l.source, "url": l.url, "title": l.title, "year": l.year,
            "mileage_km": l.mileage_km, "city": l.city, "trim": l.trim_label,
            "complectation": l.complectation, "price": price,
            "date": on.isoformat() if on else None}


def analyze(session: Session, q: Query) -> dict:
    if q.date_to < q.date_from:
        q.date_from, q.date_to = q.date_to, q.date_from
    tracks = _tracks(session, q)

    # Средняя цена каждого объявления за период — основа сводки (каждое объявление весит одинаково).
    days = [q.date_from + timedelta(days=i) for i in range((q.date_to - q.date_from).days + 1)]
    per_listing = []
    for t in tracks:
        ps = [p for d in days if (p := t.price_on(d)) is not None]
        if ps:
            per_listing.append((t, ps))
    lo, hi = _fences([round(statistics.fmean(ps)) for _, ps in per_listing])
    excluded = 0
    if q.exclude_outliers:
        kept = [(t, ps) for t, ps in per_listing if lo <= statistics.fmean(ps) <= hi]
        excluded = len(per_listing) - len(kept)
        per_listing = kept

    estimated_days = set()
    daily_values: dict[date, list[int]] = defaultdict(list)
    daily_by_source: dict[str, dict[date, list[int]]] = defaultdict(lambda: defaultdict(list))
    min_point = max_point = None
    for t, _ in per_listing:
        first_obs = t.dates[0]
        for d in days:
            p = t.price_on(d)
            if p is None:
                continue
            daily_values[d].append(p)
            daily_by_source[t.listing.source][d].append(p)
            if d < first_obs:
                estimated_days.add(d)
            if min_point is None or p < min_point[1]:
                min_point = (t, p, d)
            if max_point is None or p > max_point[1]:
                max_point = (t, p, d)

    series = []
    for d in days:
        s = _stats(daily_values.get(d, []))
        if s:
            series.append({"date": d.isoformat(), **s, "estimated": d in estimated_days})

    listing_avgs = [round(statistics.fmean(ps)) for _, ps in per_listing]
    summary = _stats(listing_avgs)
    if summary:
        summary["min_listing"] = _listing_dict(*min_point)
        summary["max_listing"] = _listing_dict(*max_point)
        by_avg = sorted(series, key=lambda r: r["avg"])
        summary["lowest_day"] = {"date": by_avg[0]["date"], "avg": by_avg[0]["avg"]}
        summary["peak_day"] = {"date": by_avg[-1]["date"], "avg": by_avg[-1]["avg"]}
        summary["change"] = _change(series)
        mileages = [t.listing.mileage_km for t, _ in per_listing if t.listing.mileage_km is not None]
        summary["avg_mileage_km"] = round(statistics.fmean(mileages)) if mileages else None
        summary["price_drops"] = sum(1 for t, _ in per_listing
                                     if any(b < a for a, b in zip(t.prices, t.prices[1:])))

    by_source = []
    for src in sorted({t.listing.source for t, _ in per_listing}):
        vals = [round(statistics.fmean(ps)) for t, ps in per_listing if t.listing.source == src]
        by_source.append({"source": src, **_stats(vals),
                          "series": [{"date": d.isoformat(), "median": round(statistics.median(v))}
                                     for d in days if (v := daily_by_source[src].get(d))]})

    by_year = []
    years = defaultdict(list)
    for t, ps in per_listing:
        if t.listing.year:
            years[t.listing.year].append(round(statistics.fmean(ps)))
    for y in sorted(years):
        by_year.append({"year": y, **_stats(years[y])})

    ranked = sorted(per_listing, key=lambda x: x[0].listing.last_price)
    cheapest = [_listing_dict(t, t.listing.last_price) for t, _ in ranked[:5]]
    priciest = [_listing_dict(t, t.listing.last_price) for t, _ in ranked[::-1][:5]]

    observed = [t.dates for t, _ in per_listing]
    return {
        "query": {"date_from": q.date_from.isoformat(), "date_to": q.date_to.isoformat()},
        "summary": summary,
        "series": series,
        "by_source": by_source,
        "by_year": by_year,
        "cheapest": cheapest,
        "priciest": priciest,
        "meta": {
            "listings": len(per_listing),
            "outliers_excluded": excluded,
            "estimated_days": len(estimated_days),
            "first_snapshot": min((d[0] for d in observed), default=None),
            "last_snapshot": max((d[-1] for d in observed), default=None),
        },
    }


def _change(series: list[dict]) -> dict | None:
    """Изменение медианы: первые 7 дней периода против последних 7 (или первый/последний день)."""
    if len(series) < 2:
        return None
    k = min(7, len(series) // 2) or 1
    start = statistics.median(r["median"] for r in series[:k])
    end = statistics.median(r["median"] for r in series[-k:])
    return {"start": round(start), "end": round(end), "abs": round(end - start),
            "pct": round((end - start) / start * 100, 2) if start else None, "window_days": k}
