"""Parses a Synthea-generated FHIR R4 Bundle into a simplified PatientRecord.

Only pulls the four resource types the Task 1 flagger actually reads
(Patient, Condition, MedicationRequest, Encounter). A real FHIR bundle
carries dozens of resource types (Claim, Immunization, DocumentReference,
...); this loader is deliberately narrow, not a general-purpose FHIR
client.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel


class Condition(BaseModel):
    code: str
    display: str
    onset_date: date | None = None
    clinical_status: str | None = None


class Medication(BaseModel):
    code: str
    display: str
    authored_on: date | None = None
    status: str | None = None


class Encounter(BaseModel):
    date: date
    class_code: str | None = None
    reason: str | None = None


class PatientRecord(BaseModel):
    patient_id: str
    birth_date: date | None = None
    conditions: list[Condition] = []
    medications: list[Medication] = []
    encounters: list[Encounter] = []

    @property
    def active_conditions(self) -> list[Condition]:
        return [
            c
            for c in self.conditions
            if c.clinical_status is None or c.clinical_status == "active"
        ]

    @property
    def active_medications(self) -> list[Medication]:
        return [
            m for m in self.medications if m.status is None or m.status == "active"
        ]

    @property
    def last_encounter_date(self) -> date | None:
        if not self.encounters:
            return None
        return max(e.date for e in self.encounters)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    # Synthea emits both bare dates ("2023-05-01") and full FHIR
    # instants ("2023-05-01T10:15:00-04:00"); datetime.fromisoformat
    # handles both once we strip a trailing "Z".
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def load_patient_record(bundle_path: Path) -> PatientRecord:
    bundle = json.loads(Path(bundle_path).read_text())
    if bundle.get("resourceType") != "Bundle":
        raise ValueError(f"{bundle_path} is not a FHIR Bundle")

    patient_id: str | None = None
    birth_date: date | None = None
    conditions: list[Condition] = []
    medications: list[Medication] = []
    encounters: list[Encounter] = []

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        rtype = resource.get("resourceType")

        if rtype == "Patient":
            patient_id = resource.get("id")
            birth_date = _parse_date(resource.get("birthDate"))

        elif rtype == "Condition":
            coding = (resource.get("code", {}).get("coding") or [{}])[0]
            conditions.append(
                Condition(
                    code=coding.get("code", "unknown"),
                    display=coding.get("display", resource.get("code", {}).get("text", "unknown")),
                    onset_date=_parse_date(resource.get("onsetDateTime")),
                    clinical_status=(
                        resource.get("clinicalStatus", {}).get("coding", [{}])[0].get("code")
                    ),
                )
            )

        elif rtype == "MedicationRequest":
            med_coding = (
                resource.get("medicationCodeableConcept", {}).get("coding") or [{}]
            )[0]
            medications.append(
                Medication(
                    code=med_coding.get("code", "unknown"),
                    display=med_coding.get(
                        "display",
                        resource.get("medicationCodeableConcept", {}).get("text", "unknown"),
                    ),
                    authored_on=_parse_date(resource.get("authoredOn")),
                    status=resource.get("status"),
                )
            )

        elif rtype == "Encounter":
            period = resource.get("period", {})
            enc_date = _parse_date(period.get("start"))
            if enc_date is None:
                continue
            reason = None
            reason_codes = resource.get("reasonCode") or []
            if reason_codes:
                reason = reason_codes[0].get("text") or (
                    reason_codes[0].get("coding", [{}])[0].get("display")
                )
            encounters.append(
                Encounter(
                    date=enc_date,
                    class_code=resource.get("class", {}).get("code"),
                    reason=reason,
                )
            )

    if patient_id is None:
        raise ValueError(f"{bundle_path} has no Patient resource")

    return PatientRecord(
        patient_id=patient_id,
        birth_date=birth_date,
        conditions=conditions,
        medications=medications,
        encounters=encounters,
    )


def load_patient_records(directory: Path) -> list[PatientRecord]:
    return [
        load_patient_record(p) for p in sorted(Path(directory).glob("*.json"))
    ]
