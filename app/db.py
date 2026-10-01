from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url.startswith("sqlite:///") and ":memory:" not in url:
            from pathlib import Path
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _pragma(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return eng


engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(eng=None) -> None:
    from app import models  # noqa: F401  регистрирует таблицы
    Base.metadata.create_all(eng or engine)
