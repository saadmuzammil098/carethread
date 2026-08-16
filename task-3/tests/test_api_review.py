import json
from pathlib import Path

import src.api as api_module
from fastapi.testclient import TestClient
from src.agent import AgentResult, AgentStep
from src.api import app

DATA_DIR = Path(__file__).resolve().parents[2] / "task-1" / "data" / "golden_patients"
client = TestClient(app)


def _bundle():
    return json.loads(
        (DATA_DIR / "d15b23ed-02d5-3e28-efbd-2604425317c5.json").read_text()
    )


def test_review_endpoint_wires_precomputed_flags_and_returns_forced_status(monkeypatch):
    captured = {}

    def fake_run_agent(record, overdue_flags_text, chat_fn=None, max_steps=8):
        captured["overdue_flags_text"] = overdue_flags_text
        captured["patient_id"] = record.patient_id
        return AgentResult(
            patient_id=record.patient_id,
            note_summary="draft note",
            status="pending_signoff",
            steps=[AgentStep(step=1, type="final", content="Final Answer: draft note")],
        )

    monkeypatch.setattr(api_module, "run_chart_review_agent", fake_run_agent)

    resp = client.post("/review", json={"bundle": _bundle(), "as_of": "2026-08-15"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_signoff"
    assert body["note_summary"] == "draft note"
    # the real, rule-based overdue flags were computed and handed to the
    # agent, this patient has two (prediabetes, heart failure)
    assert "Prediabetes" in captured["overdue_flags_text"]
    assert "Heart failure" in captured["overdue_flags_text"]


def test_review_endpoint_rejects_bundle_without_patient(monkeypatch):
    resp = client.post(
        "/review", json={"bundle": {"resourceType": "Bundle", "entry": []}}
    )
    assert resp.status_code == 422
