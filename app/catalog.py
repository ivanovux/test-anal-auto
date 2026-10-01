"""Загрузка каталога из JSON в БД (идемпотентно) и сопоставление поколений."""
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import Brand, CarModel, Generation


def load_catalog(session: Session, path: Path | None = None) -> None:
    data = json.loads(Path(path or config.CATALOG_PATH).read_text(encoding="utf-8"))
    for b in data["brands"]:
        brand = session.scalar(select(Brand).where(Brand.slug == b["slug"]))
        if not brand:
            brand = Brand(slug=b["slug"], name=b["name"])
            session.add(brand)
        brand.name = b["name"]
        session.flush()
        for m in b["models"]:
            model = session.scalar(select(CarModel).where(
                CarModel.brand_id == brand.id, CarModel.slug == m["slug"]))
            if not model:
                # флаг tracked задаётся только при первом создании — дальше им управляет пользователь
                model = CarModel(brand_id=brand.id, slug=m["slug"], tracked=m.get("tracked", False))
                session.add(model)
            model.name = m["name"]
            model.drom_path = m.get("drom_path")
            model.autoru_mark = m.get("autoru_mark")
            model.autoru_model = m.get("autoru_model")
            session.flush()
            existing = {g.name: g for g in model.generations}
            for g in m.get("generations", []):
                gen = existing.get(g["name"])
                if not gen:
                    gen = Generation(model_id=model.id, name=g["name"])
                    session.add(gen)
                gen.year_from = g["year_from"]
                gen.year_to = g.get("year_to")
                gen.aliases = "|".join(g.get("aliases", []))
    session.commit()


def _norm(s: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", "", s.lower().replace("ё", "е"))


def resolve_generation(generations: list[Generation], year: int | None,
                       source_gen_name: str | None = None) -> Generation | None:
    """Определяет поколение: сначала по названию поколения с площадки, затем по году выпуска."""
    if source_gen_name:
        name = _norm(source_gen_name)
        candidates = []
        for g in generations:
            for alias in filter(None, g.aliases.split("|")):
                a = _norm(alias)
                # точное совпадение или вхождение кода кузова ('XV70' в 'XV70 рестайлинг')
                if a and (a == name or (len(a) >= 3 and a in name)):
                    candidates.append(g)
                    break
        if len(candidates) == 1:
            return candidates[0]
        if candidates and year:
            generations = candidates
    if year:
        for g in generations:
            if g.year_from <= year <= (g.year_to or 9999):
                return g
    return None
