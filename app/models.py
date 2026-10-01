"""Схема БД.

Каталог (марка → модель → поколение) — наш собственный, общий для всех площадок.
Комплектация (trim) формируется из параметров объявления: двигатель, КПП, привод.
Каждый проход сборщика пишет «снимок» цены объявления (PriceObservation) на дату —
из этих снимков и строится аналитика за период.
"""
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    models: Mapped[list["CarModel"]] = relationship(back_populates="brand", order_by="CarModel.name")


class CarModel(Base):
    __tablename__ = "car_models"
    __table_args__ = (UniqueConstraint("brand_id", "slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"))
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    drom_path: Mapped[str | None] = mapped_column(String(128))     # 'toyota/camry'
    autoru_mark: Mapped[str | None] = mapped_column(String(64))    # 'TOYOTA'
    autoru_model: Mapped[str | None] = mapped_column(String(64))   # 'CAMRY'
    tracked: Mapped[bool] = mapped_column(Boolean, default=False)  # собирать по расписанию
    brand: Mapped[Brand] = relationship(back_populates="models")
    generations: Mapped[list["Generation"]] = relationship(
        back_populates="model", order_by="Generation.year_from")


class Generation(Base):
    __tablename__ = "generations"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("car_models.id"))
    name: Mapped[str] = mapped_column(String(128))
    year_from: Mapped[int] = mapped_column(Integer)
    year_to: Mapped[int | None] = mapped_column(Integer)
    aliases: Mapped[str] = mapped_column(Text, default="")  # через '|' — коды поколений на площадках
    model: Mapped[CarModel] = relationship(back_populates="generations")


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "external_id"),
                      Index("ix_listing_model_gen", "model_id", "generation_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(512))
    model_id: Mapped[int] = mapped_column(ForeignKey("car_models.id"))
    generation_id: Mapped[int | None] = mapped_column(ForeignKey("generations.id"))
    trim_key: Mapped[str | None] = mapped_column(String(128), index=True)
    trim_label: Mapped[str | None] = mapped_column(String(256))
    complectation: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(256))
    year: Mapped[int | None] = mapped_column(Integer)
    mileage_km: Mapped[int | None] = mapped_column(Integer)
    city: Mapped[str | None] = mapped_column(String(128))
    published_on: Mapped[date | None] = mapped_column(Date)
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)
    last_price: Mapped[int] = mapped_column(Integer)
    observations: Mapped[list["PriceObservation"]] = relationship(
        back_populates="listing", order_by="PriceObservation.observed_on", cascade="all, delete-orphan")


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (UniqueConstraint("listing_id", "observed_on"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    observed_on: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[int] = mapped_column(Integer)
    listing: Mapped[Listing] = relationship(back_populates="observations")


class CollectRun(Base):
    __tablename__ = "collect_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(16))
    model_id: Mapped[int] = mapped_column(ForeignKey("car_models.id"))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|ok|error|blocked
    listings_found: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
