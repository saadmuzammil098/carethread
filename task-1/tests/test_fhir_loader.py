from pathlib import Path

from src.fhir_loader import load_patient_record, load_patient_records

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "golden_patients"


def test_loads_every_golden_patient():
    records = load_patient_records(DATA_DIR)
    assert len(records) == 10
    for record in records:
        assert record.patient_id


def test_active_conditions_excludes_resolved():
    record = load_patient_record(next(DATA_DIR.glob("*.json")))
    resolved = [
        c for c in record.conditions if c.clinical_status == "resolved"
    ]
    if resolved:
        assert all(c not in record.active_conditions for c in resolved)


def test_last_encounter_date_is_max_of_encounters():
    record = load_patient_record(next(DATA_DIR.glob("*.json")))
    if record.encounters:
        assert record.last_encounter_date == max(
            e.date for e in record.encounters
        )
    else:
        assert record.last_encounter_date is None
