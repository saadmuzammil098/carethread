import json
from pathlib import Path

from fastapi.testclient import TestClient
from src.api import app

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "golden_patients"
client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_flag_endpoint_returns_pending_signoff_note():
    bundle = json.loads(next(DATA_DIR.glob("*.json")).read_text())
    resp = client.post("/flag", json={"bundle": bundle, "as_of": "2026-08-15"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["note"]["status"] == "pending_signoff"
    assert body["patient_id"]


def test_flag_endpoint_rejects_bundle_without_patient():
    resp = client.post(
        "/flag", json={"bundle": {"resourceType": "Bundle", "entry": []}}
    )
    assert resp.status_code == 422  # no Patient resource -> ValueError in loader
