"""Minimal FastAPI service exposing the Task 1 rule-based care flagger.

Deliberately thin: `/flag` accepts a trimmed FHIR Bundle (the same
Patient/Condition/MedicationRequest/Encounter shape `fhir_loader` reads)
and returns flags plus a draft coordination note, `status` always
"pending_signoff", nothing here has a send-path. This is what task-9's
Terraform deploys, the actual point of Task 1 having a real deploy
target instead of only a local eval script.
"""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from mangum import Mangum
from pydantic import BaseModel

from src.care_flagger import CareFlag, generate_flags
from src.fhir_loader import load_patient_record
from src.note_drafter import draft_coordination_note

app = FastAPI(title="CareThread API", version="0.1.0")


class FlagRequest(BaseModel):
    bundle: dict
    as_of: date | None = None


class FlagResponse(BaseModel):
    patient_id: str
    flags: list[CareFlag]
    note: dict


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/flag", response_model=FlagResponse)
def flag_patient(request: FlagRequest) -> FlagResponse:
    as_of = request.as_of or datetime.now(timezone.utc).date()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp:
        json.dump(request.bundle, tmp)
        tmp_path = Path(tmp.name)

    try:
        record = load_patient_record(tmp_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    flags = generate_flags(record, as_of)
    note = draft_coordination_note(record.patient_id, flags)

    return FlagResponse(
        patient_id=record.patient_id, flags=flags, note=note.model_dump(mode="json")
    )


handler = Mangum(app, lifespan="auto")
