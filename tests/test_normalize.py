from datetime import date

from app.normalize import parse_mileage, parse_price, parse_ru_date, trim_from_fields, trim_from_text

TODAY = date(2026, 1, 10)


def test_price_and_mileage():
    assert parse_price("2\xa0850\xa0000 ₽") == 2_850_000
    assert parse_mileage("75 тыс. км") == 75_000
    assert parse_mileage("120 000 км") == 120_000
    assert parse_mileage("новый") == 0


def test_dates():
    assert parse_ru_date("сегодня", TODAY) == TODAY
    assert parse_ru_date("вчера", TODAY) == date(2026, 1, 9)
    assert parse_ru_date("5 января", TODAY) == date(2026, 1, 5)
    assert parse_ru_date("28 декабря", TODAY) == date(2025, 12, 28)  # прошлый год
    assert parse_ru_date("12.09.2025", TODAY) == date(2025, 9, 12)
    assert parse_ru_date("3 часа назад", TODAY) == TODAY


def test_trim_text_and_fields_match():
    a = trim_from_text("2.5 л (181 л.с.), бензин, АКПП, передний, 75 тыс. км")
    b = trim_from_fields(2494, 181, "GASOLINE", "AUTOMATIC", "FORWARD_CONTROL")
    assert a.key == b.key == "2.5|181|бензин|АКПП|передний"
    assert trim_from_text("1.6 л (106 л.с.), бензин, механика, передний").transmission == "МКПП"
    assert trim_from_text("2.0 л, дизель, робот, 4WD").drive == "полный"
