import pytest
from sqlalchemy.orm import sessionmaker

from app.catalog import load_catalog
from app.db import init_db, make_engine


@pytest.fixture
def session(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(eng)
    s = sessionmaker(bind=eng, expire_on_commit=False)()
    load_catalog(s)
    yield s
    s.close()
