from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import config, db, main
from app.demo import seed_demo


def test_api_smoke(tmp_path, monkeypatch):
    eng = db.make_engine(f"sqlite:///{tmp_path / 'api.db'}")
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(main, "SessionLocal", Session)
    monkeypatch.setattr(config, "ENABLE_SCHEDULER", False)
    with TestClient(main.app) as c:
        with Session() as s:
            seed_demo(s, days=30, per_model=10)
        brands = c.get("/api/brands").json()
        toyota = next(b for b in brands if b["name"] == "Toyota")
        camry = next(m for m in c.get(f"/api/brands/{toyota['id']}/models").json() if m["name"] == "Camry")
        assert c.get(f"/api/models/{camry['id']}/generations").json()
        assert c.get(f"/api/models/{camry['id']}/trims").json()
        r = c.get("/api/analytics", params={"model_id": camry["id"]})
        assert r.status_code == 200 and r.json()["summary"]["count"] > 0
        assert c.get("/api/analytics.csv", params={"model_id": camry["id"]}).text.startswith("﻿Дата")
        assert c.post(f"/api/models/{camry['id']}/track", json={"tracked": False}).json()["tracked"] is False
        assert c.get("/").status_code == 200
