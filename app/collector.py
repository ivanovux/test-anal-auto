"""Сбор объявлений: проходит по отслеживаемым моделям на каждой площадке и
сохраняет снимок цены каждого объявления на текущую дату."""
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.catalog import resolve_generation
from app.models import CarModel, CollectRun, Listing, PriceObservation
from app.scrapers import SCRAPERS
from app.scrapers.base import BlockedError, RawListing

log = logging.getLogger(__name__)


def save_listing(session: Session, model: CarModel, raw: RawListing, today: date) -> Listing | None:
    if raw.price < config.MIN_VALID_PRICE:
        return None
    listing = session.scalar(select(Listing).where(
        Listing.source == raw.source, Listing.external_id == raw.external_id))
    gen = resolve_generation(model.generations, raw.year, raw.generation_name)
    if listing is None:
        listing = Listing(source=raw.source, external_id=raw.external_id, model_id=model.id,
                          first_seen=today, last_seen=today, last_price=raw.price, url=raw.url)
        session.add(listing)
    listing.url = raw.url
    listing.generation_id = gen.id if gen else None
    listing.trim_key = raw.trim.key
    listing.trim_label = raw.trim.label
    listing.complectation = raw.complectation or listing.complectation
    listing.title = raw.title
    listing.year = raw.year or listing.year
    listing.mileage_km = raw.mileage_km if raw.mileage_km is not None else listing.mileage_km
    listing.city = raw.city or listing.city
    listing.published_on = listing.published_on or raw.published_on
    listing.last_seen = max(listing.last_seen, today)
    listing.first_seen = min(listing.first_seen, today)
    listing.last_price = raw.price
    session.flush()
    obs = session.scalar(select(PriceObservation).where(
        PriceObservation.listing_id == listing.id, PriceObservation.observed_on == today))
    if obs:
        obs.price = raw.price
    else:
        session.add(PriceObservation(listing_id=listing.id, observed_on=today, price=raw.price))
    return listing


def collect_model(session: Session, model: CarModel, source: str, max_pages: int | None = None,
                  scraper=None, today: date | None = None) -> CollectRun:
    today = today or date.today()
    run = CollectRun(started_at=datetime.now(), source=source, model_id=model.id)
    session.add(run)
    session.commit()
    own_scraper = scraper is None
    scraper = scraper or SCRAPERS[source]()
    seen = set()
    try:
        for raw in scraper.iter_listings(model, max_pages or config.MAX_PAGES):
            if raw.external_id in seen:
                continue
            seen.add(raw.external_id)
            save_listing(session, model, raw, today)
        run.status = "ok"
        if not seen:
            run.message = "объявлений не найдено — проверьте путь модели в каталоге"
    except BlockedError as e:
        run.status, run.message = "blocked", str(e)
        log.warning(str(e))
    except Exception as e:  # noqa: BLE001
        run.status, run.message = "error", f"{type(e).__name__}: {e}"
        log.exception("Ошибка сбора %s/%s", source, model.slug)
    finally:
        if own_scraper:
            scraper.close()
    run.listings_found = len(seen)
    run.finished_at = datetime.now()
    session.commit()
    return run


def collect_all(session: Session, model_ids: list[int] | None = None,
                sources: list[str] | None = None) -> list[CollectRun]:
    q = select(CarModel)
    q = q.where(CarModel.id.in_(model_ids)) if model_ids else q.where(CarModel.tracked.is_(True))
    runs = []
    for source in sources or config.ENABLED_SOURCES:
        blocked = False
        for model in session.scalars(q).all():
            if blocked:  # площадка заблокировала — не долбим её дальше в этом проходе
                break
            run = collect_model(session, model, source)
            runs.append(run)
            blocked = run.status == "blocked"
    return runs
