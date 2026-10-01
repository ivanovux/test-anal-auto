import csv
import io
import logging
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import FastAPI, HTTPException, Query as Q
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select

from app import config
from app.analytics import Query, analyze
from app.catalog import load_catalog
from app.collector import collect_all
from app.db import SessionLocal, init_db
from app.models import Brand, CarModel, CollectRun, Generation, Listing

log = logging.getLogger(__name__)
STATIC = config.BASE_DIR / "app" / "static"
_collect_lock = threading.Lock()


def run_collection(model_ids: list[int] | None = None) -> None:
    if not _collect_lock.acquire(blocking=False):
        log.info("Сбор уже идёт — пропуск")
        return
    try:
        with SessionLocal() as s:
            collect_all(s, model_ids)
    finally:
        _collect_lock.release()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as s:
        load_catalog(s)
    scheduler = None
    if config.ENABLE_SCHEDULER:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone="Europe/Moscow")
        scheduler.add_job(run_collection, "cron", hour=config.COLLECT_HOUR,
                          minute=config.COLLECT_MINUTE, id="daily_collect")
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Аналитика цен на авто", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/brands")
def brands():
    with SessionLocal() as s:
        return [{"id": b.id, "name": b.name} for b in s.scalars(select(Brand).order_by(Brand.name))]


@app.get("/api/brands/{brand_id}/models")
def models(brand_id: int):
    with SessionLocal() as s:
        rows = s.scalars(select(CarModel).where(CarModel.brand_id == brand_id).order_by(CarModel.name))
        return [{"id": m.id, "name": m.name, "tracked": m.tracked} for m in rows]


@app.get("/api/models/{model_id}/generations")
def generations(model_id: int):
    with SessionLocal() as s:
        rows = s.scalars(select(Generation).where(Generation.model_id == model_id)
                         .order_by(Generation.year_from))
        return [{"id": g.id, "name": g.name, "year_from": g.year_from, "year_to": g.year_to} for g in rows]


@app.get("/api/models/{model_id}/trims")
def trims(model_id: int, generation_id: int | None = None):
    """Комплектации (модификации), реально встречающиеся в собранных объявлениях."""
    with SessionLocal() as s:
        stmt = (select(Listing.trim_key, func.max(Listing.trim_label), func.count())
                .where(Listing.model_id == model_id, Listing.trim_key.is_not(None))
                .group_by(Listing.trim_key).order_by(func.count().desc()))
        if generation_id:
            stmt = stmt.where(Listing.generation_id == generation_id)
        return [{"key": k, "label": lbl, "count": n} for k, lbl, n in s.execute(stmt)]


@app.get("/api/sources")
def sources():
    with SessionLocal() as s:
        return [r for (r,) in s.execute(select(Listing.source).distinct().order_by(Listing.source))]


def _query(model_id, date_from, date_to, generation_id, trim_key, sources, year_from, year_to,
           exclude_outliers, use_published) -> Query:
    if not date_to:
        date_to = date.today()
    if not date_from:
        date_from = date_to - timedelta(days=30)
    return Query(model_id=model_id, date_from=date_from, date_to=date_to, generation_id=generation_id,
                 trim_key=trim_key or None, sources=[x for x in (sources or []) if x] or None,
                 year_from=year_from, year_to=year_to, exclude_outliers=exclude_outliers,
                 use_published=use_published)


@app.get("/api/analytics")
def analytics(model_id: int, date_from: date | None = None, date_to: date | None = None,
              generation_id: int | None = None, trim_key: str | None = None,
              sources: list[str] | None = Q(None), year_from: int | None = None,
              year_to: int | None = None, exclude_outliers: bool = True, use_published: bool = True):
    q = _query(model_id, date_from, date_to, generation_id, trim_key, sources, year_from, year_to,
               exclude_outliers, use_published)
    with SessionLocal() as s:
        if not s.get(CarModel, model_id):
            raise HTTPException(404, "Модель не найдена")
        return analyze(s, q)


@app.get("/api/analytics.csv")
def analytics_csv(model_id: int, date_from: date | None = None, date_to: date | None = None,
                  generation_id: int | None = None, trim_key: str | None = None,
                  sources: list[str] | None = Q(None), year_from: int | None = None,
                  year_to: int | None = None, exclude_outliers: bool = True, use_published: bool = True):
    data = analytics(model_id, date_from, date_to, generation_id, trim_key, sources, year_from, year_to,
                     exclude_outliers, use_published)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Дата", "Объявлений", "Средняя", "Медиана", "Мин", "Макс", "Оценка"])
    for r in data["series"]:
        w.writerow([r["date"], r["count"], r["avg"], r["median"], r["min"], r["max"],
                    "да" if r["estimated"] else ""])
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=prices.csv"})


class TrackBody(BaseModel):
    tracked: bool


@app.post("/api/models/{model_id}/track")
def track(model_id: int, body: TrackBody):
    with SessionLocal() as s:
        m = s.get(CarModel, model_id)
        if not m:
            raise HTTPException(404, "Модель не найдена")
        m.tracked = body.tracked
        s.commit()
        return {"id": m.id, "tracked": m.tracked}


class CollectBody(BaseModel):
    model_ids: list[int] | None = None


@app.post("/api/collect", status_code=202)
def collect(body: CollectBody):
    if _collect_lock.locked():
        raise HTTPException(409, "Сбор уже выполняется")
    threading.Thread(target=run_collection, args=(body.model_ids,), daemon=True).start()
    return {"started": True}


@app.get("/api/collect/runs")
def runs(limit: int = 30):
    with SessionLocal() as s:
        rows = s.execute(select(CollectRun, CarModel.name).join(CarModel)
                         .order_by(CollectRun.id.desc()).limit(limit))
        return {"running": _collect_lock.locked(), "runs": [
            {"id": r.id, "source": r.source, "model": name, "status": r.status,
             "found": r.listings_found, "message": r.message,
             "started_at": r.started_at, "finished_at": r.finished_at} for r, name in rows]}
