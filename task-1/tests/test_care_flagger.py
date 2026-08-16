from datetime import date

from src.care_flagger import (
    FlagType,
    flag_drug_interactions,
    flag_overdue_follow_up,
    generate_flags,
)
from src.fhir_loader import Condition, Encounter, Medication, PatientRecord

AS_OF = date(2026, 8, 15)


def _record(**kwargs) -> PatientRecord:
    defaults = {"patient_id": "p1", "conditions": [], "medications": [], "encounters": []}
    defaults.update(kwargs)
    return PatientRecord(**defaults)


def test_overdue_follow_up_flagged_past_window():
    record = _record(
        conditions=[Condition(code="1", display="Essential hypertension (disorder)")],
        encounters=[Encounter(date=date(2025, 1, 1))],  # ~591 days before AS_OF
    )
    flags = flag_overdue_follow_up(record, AS_OF)
    assert len(flags) == 1
    assert flags[0].flag_type == FlagType.OVERDUE_FOLLOW_UP


def test_not_overdue_within_window():
    record = _record(
        conditions=[Condition(code="1", display="Essential hypertension (disorder)")],
        encounters=[Encounter(date=date(2026, 7, 1))],  # 45 days before AS_OF
    )
    assert flag_overdue_follow_up(record, AS_OF) == []


def test_no_encounter_at_all_is_overdue():
    record = _record(
        conditions=[Condition(code="1", display="Heart failure (disorder)")],
    )
    flags = flag_overdue_follow_up(record, AS_OF)
    assert len(flags) == 1
    assert "no recorded encounter" in flags[0].detail


def test_resolved_condition_not_flagged():
    record = _record(
        conditions=[
            Condition(
                code="1",
                display="Essential hypertension (disorder)",
                clinical_status="resolved",
            )
        ],
    )
    assert flag_overdue_follow_up(record, AS_OF) == []


def test_condition_outside_keyword_table_never_flagged():
    record = _record(
        conditions=[Condition(code="1", display="Viral sinusitis (disorder)")],
    )
    assert flag_overdue_follow_up(record, AS_OF) == []


def test_drug_interaction_flagged_when_both_present():
    record = _record(
        medications=[
            Medication(code="1", display="Warfarin Sodium 5 MG"),
            Medication(code="2", display="Aspirin 81 MG"),
        ],
    )
    flags = flag_drug_interactions(record)
    assert len(flags) == 1
    assert flags[0].flag_type == FlagType.DRUG_INTERACTION
    assert "stub" in flags[0].source  # source honestly labeled, not a live RxGround call


def test_no_interaction_flagged_when_only_one_drug_present():
    record = _record(medications=[Medication(code="1", display="Warfarin Sodium 5 MG")])
    assert flag_drug_interactions(record) == []


def test_inactive_medication_not_considered_for_interactions():
    record = _record(
        medications=[
            Medication(code="1", display="Warfarin Sodium 5 MG", status="stopped"),
            Medication(code="2", display="Aspirin 81 MG"),
        ],
    )
    assert flag_drug_interactions(record) == []


def test_generate_flags_combines_both_flag_types():
    record = _record(
        conditions=[Condition(code="1", display="Heart failure (disorder)")],
        medications=[
            Medication(code="1", display="Warfarin Sodium 5 MG"),
            Medication(code="2", display="Aspirin 81 MG"),
        ],
    )
    flags = generate_flags(record, AS_OF)
    types = {f.flag_type for f in flags}
    assert types == {FlagType.OVERDUE_FOLLOW_UP, FlagType.DRUG_INTERACTION}
