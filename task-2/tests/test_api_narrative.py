import json
from pathlib import Path

import src.api as api_module
from fastapi.testclient import TestClient
from src.api import app

DATA_DIR = Path(__file__).resolve().parents[2] / "task-1" / "data" / "golden_patients"
client = TestClient(app)


def _bundle_with_flags():
    return json.loads(
        (DATA_DIR / "d15b23ed-02d5-3e28-efbd-2604425317c5.json").read_text()
    )


def test_use_narrative_false_by_default_no_llm_call(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("generate_narrative should not run when use_narrative is False")

    monkeypatch.setattr(api_module, "generate_narrative", boom)
    resp = client.post("/flag", json={"bundle": _bundle_with_flags()})
    assert resp.status_code == 200
    assert resp.json()["narrative_cache_hit"] is False


def test_use_narrative_true_calls_narrative_and_caches(monkeypatch):
    calls = []

    def fake_generate_narrative(patient_id, flags):
        calls.append(patient_id)
        return "a narrative summary"

    monkeypatch.setattr(api_module, "generate_narrative", fake_generate_narrative)
    monkeypatch.setattr(api_module._cache, "get", lambda key: None)
    set_calls = []
    monkeypatch.setattr(
        api_module._cache, "set", lambda key, value: set_calls.append((key, value))
    )

    resp = client.post(
        "/flag", json={"bundle": _bundle_with_flags(), "use_narrative": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["note"]["summary"] == "a narrative summary"
    assert body["narrative_cache_hit"] is False
    assert len(calls) == 1
    assert len(set_calls) == 1


def test_use_narrative_true_with_cache_hit_skips_llm(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("generate_narrative should not run on a cache hit")

    monkeypatch.setattr(api_module, "generate_narrative", boom)
    monkeypatch.setattr(api_module._cache, "get", lambda key: "cached narrative")

    resp = client.post(
        "/flag", json={"bundle": _bundle_with_flags(), "use_narrative": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["note"]["summary"] == "cached narrative"
    assert body["narrative_cache_hit"] is True
