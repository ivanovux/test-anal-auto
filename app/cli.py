"""Командная строка:
    python -m app.cli init                   — создать БД и загрузить каталог
    python -m app.cli collect [--model camry] [--source drom] [--pages 3]
    python -m app.cli demo [--clear]         — синтетические данные для демонстрации
"""
import argparse
import logging

from sqlalchemy import select

from app.catalog import load_catalog
from app.collector import collect_all
from app.db import SessionLocal, init_db
from app.demo import clear_demo, seed_demo
from app.models import CarModel


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    c = sub.add_parser("collect")
    c.add_argument("--model", action="append", help="slug модели (можно несколько), по умолчанию — отслеживаемые")
    c.add_argument("--source", action="append", choices=["drom", "autoru"])
    c.add_argument("--pages", type=int)
    d = sub.add_parser("demo")
    d.add_argument("--clear", action="store_true")
    d.add_argument("--days", type=int, default=180)
    args = p.parse_args(argv)

    init_db()
    with SessionLocal() as s:
        load_catalog(s)
        if args.cmd == "init":
            print("БД и каталог готовы")
        elif args.cmd == "collect":
            if args.pages:
                from app import config
                config.MAX_PAGES = args.pages
            ids = None
            if args.model:
                ids = list(s.scalars(select(CarModel.id).where(CarModel.slug.in_(args.model))))
            for r in collect_all(s, ids, args.source):
                print(f"{r.source:7} model={r.model_id:<3} {r.status:8} найдено={r.listings_found} {r.message or ''}")
        elif args.cmd == "demo":
            if args.clear:
                print(f"Удалено демо-объявлений: {clear_demo(s)}")
            else:
                clear_demo(s)
                print(f"Создано демо-объявлений: {seed_demo(s, days=args.days)}")


if __name__ == "__main__":
    main()
