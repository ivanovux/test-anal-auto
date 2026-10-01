"""Демо-данные: синтетическая история цен для проверки интерфейса без доступа к площадкам.
Объявления помечаются источником с суффиксом '-demo' и удаляются командой `demo --clear`."""
import random
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import CarModel, Listing, PriceObservation
from app.normalize import Trim

BASE_PRICES = {"vesta": 1_350_000, "granta": 750_000, "camry": 2_900_000, "rav4": 3_100_000,
               "rio": 1_250_000, "sportage": 2_300_000, "solaris": 1_150_000, "creta": 2_000_000,
               "polo": 1_100_000, "octavia": 1_700_000, "jolion": 1_900_000, "tiggo-7-pro": 2_000_000,
               "coolray": 1_850_000, "x5": 6_500_000, "e-class": 4_200_000}
TRIMS = [Trim(1.6, 106, "бензин", "МКПП", "передний"), Trim(1.6, 123, "бензин", "АКПП", "передний"),
         Trim(2.0, 150, "бензин", "АКПП", "передний"), Trim(2.5, 181, "бензин", "АКПП", "полный")]
CITIES = ["Москва", "Санкт-Петербург", "Екатеринбург", "Казань", "Новосибирск", "Краснодар"]


def clear_demo(session: Session) -> int:
    ids = session.scalars(select(Listing.id).where(Listing.source.like("%-demo"))).all()
    if ids:
        session.execute(delete(PriceObservation).where(PriceObservation.listing_id.in_(ids)))
        session.execute(delete(Listing).where(Listing.id.in_(ids)))
    session.commit()
    return len(ids)


def seed_demo(session: Session, days: int = 180, per_model: int = 120, seed: int = 42) -> int:
    rnd = random.Random(seed)
    today = date.today()
    start = today - timedelta(days=days)
    created = 0
    for model in session.scalars(select(CarModel)).all():
        base = BASE_PRICES.get(model.slug, 2_000_000)
        trend = rnd.uniform(-0.12, 0.18)  # тренд рынка за весь период
        for i in range(per_model):
            gen = rnd.choice(model.generations) if model.generations else None
            year = rnd.randint(gen.year_from, min(gen.year_to or today.year, today.year)) if gen else 2020
            trim = rnd.choice(TRIMS)
            age = today.year - year
            price0 = base * (0.9 ** age) * (1 + (trim.engine_volume - 1.6) * 0.25) * rnd.uniform(0.85, 1.15)
            first = start + timedelta(days=rnd.randint(0, days))
            last = min(today, first + timedelta(days=rnd.randint(7, 90)))
            source = rnd.choice(["drom", "autoru"]) + "-demo"
            l = Listing(source=source, external_id=f"{model.slug}-{i}", model_id=model.id,
                        url="https://example.com/demo", generation_id=gen.id if gen else None,
                        trim_key=trim.key, trim_label=trim.label, title=f"{model.name}, {year}",
                        year=year, mileage_km=max(0, age * rnd.randint(10_000, 25_000)),
                        city=rnd.choice(CITIES), published_on=first, first_seen=first,
                        last_seen=last, last_price=0)
            session.add(l)
            session.flush()
            d, price = first, price0
            while d <= last:
                market = 1 + trend * (d - start).days / days
                if rnd.random() < 0.04:  # продавец снижает цену
                    price *= rnd.uniform(0.95, 0.99)
                p = int(round(price * market, -3))
                session.add(PriceObservation(listing_id=l.id, observed_on=d, price=p))
                l.last_price = p
                d += timedelta(days=1)
            created += 1
        session.commit()
    return created
