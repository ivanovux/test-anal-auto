"""Нормализация сырых значений с площадок: цены, пробег, даты, параметры комплектации."""
import re
from dataclasses import dataclass
from datetime import date, timedelta

_MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
           "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}


def parse_int(text: str | None) -> int | None:
    if text is None:
        return None
    digits = re.sub(r"\D", "", str(text))
    return int(digits) if digits else None


def parse_price(text: str | None) -> int | None:
    return parse_int(text)


def parse_mileage(text: str | None) -> int | None:
    """'75 тыс. км' → 75000, '120 000 км' → 120000, 'новый' → 0."""
    if not text:
        return None
    t = text.lower().replace("\xa0", " ")
    if "нов" in t and not re.search(r"\d", t):
        return 0
    m = re.search(r"(\d[\d\s]*)\s*(тыс)?", t)
    if not m:
        return None
    value = int(re.sub(r"\s", "", m.group(1)))
    return value * 1000 if m.group(2) else value


def parse_ru_date(text: str | None, today: date | None = None) -> date | None:
    """'сегодня', 'вчера', '12 сентября', '12 сентября 2024', '12.09.2024', '3 часа назад'."""
    if not text:
        return None
    today = today or date.today()
    t = text.strip().lower()
    if "сегодня" in t or "назад" in t and ("час" in t or "мин" in t):
        return today
    if "вчера" in t:
        return today - timedelta(days=1)
    if m := re.search(r"(\d+)\s*(дн|день|дня)\S*\s*назад", t):
        return today - timedelta(days=int(m.group(1)))
    if m := re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", t):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return _safe_date(y, int(m.group(2)), int(m.group(1)))
    if m := re.search(r"(\d{1,2})\s+([а-я]+)\s*(\d{4})?", t):
        month = next((v for k, v in _MONTHS.items() if m.group(2).startswith(k)), None)
        if month:
            y = int(m.group(3)) if m.group(3) else today.year
            d = _safe_date(y, month, int(m.group(1)))
            if d and not m.group(3) and d > today:  # «28 декабря» в январе — прошлый год
                d = _safe_date(y - 1, month, int(m.group(1)))
            return d
    return None


def _safe_date(y: int, mth: int, d: int) -> date | None:
    try:
        return date(y, mth, d)
    except ValueError:
        return None


# --- комплектация (модификация) ---

_TRANS = [("вариатор", "вариатор"), ("cvt", "вариатор"), ("variator", "вариатор"),
          ("робот", "робот"), ("robot", "робот"), ("amt", "робот"), ("dct", "робот"),
          ("механ", "МКПП"), ("мкпп", "МКПП"), ("mechanical", "МКПП"),
          ("акпп", "АКПП"), ("автомат", "АКПП"), ("automatic", "АКПП")]
_FUEL = [("гибрид", "гибрид"), ("hybrid", "гибрид"), ("дизел", "дизель"), ("diesel", "дизель"),
         ("электро", "электро"), ("electro", "электро"), ("газ", "газ"), ("lpg", "газ"),
         ("бензин", "бензин"), ("gasoline", "бензин")]
_DRIVE = [("4wd", "полный"), ("полн", "полный"), ("all_wheel", "полный"),
          ("задн", "задний"), ("rear", "задний"),
          ("передн", "передний"), ("forward", "передний"), ("front", "передний")]


def _match(text: str, table) -> str | None:
    t = text.lower()
    return next((v for k, v in table if k in t), None)


@dataclass
class Trim:
    engine_volume: float | None = None   # литры
    power_hp: int | None = None
    fuel: str | None = None
    transmission: str | None = None
    drive: str | None = None

    @property
    def key(self) -> str | None:
        parts = [f"{self.engine_volume:.1f}" if self.engine_volume else "",
                 str(self.power_hp or ""), self.fuel or "", self.transmission or "", self.drive or ""]
        return "|".join(parts) if any(parts) else None

    @property
    def label(self) -> str | None:
        parts = []
        if self.engine_volume:
            parts.append(f"{self.engine_volume:.1f} л")
        if self.power_hp:
            parts.append(f"{self.power_hp} л.с.")
        parts += [p for p in (self.fuel, self.transmission, self.drive) if p]
        return ", ".join(parts) or None


def trim_from_text(text: str | None) -> Trim:
    """Разбор строки Drom: '2.5 л (181 л.с.), бензин, АКПП, передний, 75 тыс. км'."""
    if not text:
        return Trim()
    t = text.replace("\xa0", " ")
    vol = re.search(r"(\d+[.,]\d)\s*л(?![а-я])", t)
    hp = re.search(r"(\d{2,4})\s*л\.?\s*с", t)
    return Trim(engine_volume=float(vol.group(1).replace(",", ".")) if vol else None,
                power_hp=int(hp.group(1)) if hp else None,
                fuel=_match(t, _FUEL), transmission=_match(t, _TRANS), drive=_match(t, _DRIVE))


def trim_from_fields(displacement_cc: int | None, power_hp: int | None, engine_type: str | None,
                     transmission: str | None, gear_type: str | None) -> Trim:
    """Разбор структурированных полей Auto.ru (tech_param)."""
    vol = round(displacement_cc / 1000, 1) if displacement_cc else None
    return Trim(engine_volume=vol, power_hp=power_hp,
                fuel=_match(engine_type or "", _FUEL), transmission=_match(transmission or "", _TRANS),
                drive=_match(gear_type or "", _DRIVE))
