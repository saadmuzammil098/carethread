"""Rule-based care-coordination flagger.

Task 1 deliberately keeps this rule-based, not an LLM agent, an agent
arrives in CareThread Task 3. The point of Task 1 is the eval-gated
CI/CD pipeline around a flagging system, and a rule-based flagger is
enough to prove that pipeline works, is fully deterministic (required
for a stable eval baseline), and is cheap to run on every PR.

Two flag types:
  - overdue_follow_up: a chronic condition with no encounter inside its
    condition-specific follow-up window.
  - drug_interaction: an active-medication pair matching a known
    interaction. `KNOWN_INTERACTIONS` below is a small static table
    standing in for a live call into RxGround's drug-interaction RAG
    index, that live cross-project call is CareThread Task 3's job (see
    roadmap: "a live call into RxGround for drug-interaction checks, a
    genuine cross-project integration"). Wiring it here would couple
    Task 1's eval determinism to RxGround's index and network
    availability, exactly what a CI-run eval suite can't depend on.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel

from src.fhir_loader import PatientRecord

# Condition keyword -> max days since last encounter before "overdue".
# Matched case-insensitively against Condition.display. A real system
# would match on SNOMED CT codes, not display text; Synthea's condition
# codes are SNOMED already, but matching the human-readable display
# keeps this table legible without a SNOMED code lookup table alongside
# it. Narrow keyword list, deliberately not exhaustive.
FOLLOW_UP_WINDOWS_DAYS: dict[str, int] = {
    "diabetes": 180,
    "hypertension": 180,
    "heart failure": 90,
    "chronic kidney disease": 180,
    "chronic obstructive pulmonary disease": 120,
    "coronary heart disease": 180,
}

# (drug_a, drug_b) -> human-readable reason. Matched case-insensitively,
# order-independent, against Medication.display substrings. Stand-in
# table only, see module docstring.
KNOWN_INTERACTIONS: list[tuple[str, str, str]] = [
    ("warfarin", "aspirin", "combined bleeding risk"),
    ("lisinopril", "spironolactone", "hyperkalemia risk"),
    ("simvastatin", "clarithromycin", "myopathy/rhabdomyolysis risk"),
    ("metformin", "iodinated contrast", "lactic acidosis risk"),
]


class FlagType(str, Enum):
    OVERDUE_FOLLOW_UP = "overdue_follow_up"
    DRUG_INTERACTION = "drug_interaction"


class CareFlag(BaseModel):
    patient_id: str
    flag_type: FlagType
    detail: str
    source: str


def flag_overdue_follow_up(record: PatientRecord, as_of: date) -> list[CareFlag]:
    flags: list[CareFlag] = []
    last_encounter = record.last_encounter_date

    for condition in record.active_conditions:
        display_lower = condition.display.lower()
        for keyword, window_days in FOLLOW_UP_WINDOWS_DAYS.items():
            if keyword not in display_lower:
                continue

            if last_encounter is None:
                days_since = None
            else:
                days_since = (as_of - last_encounter).days

            if last_encounter is None or days_since > window_days:
                since_text = (
                    "no recorded encounter"
                    if last_encounter is None
                    else f"last encounter {days_since} days ago"
                )
                flags.append(
                    CareFlag(
                        patient_id=record.patient_id,
                        flag_type=FlagType.OVERDUE_FOLLOW_UP,
                        detail=(
                            f"{condition.display}: follow-up window is "
                            f"{window_days} days, {since_text}."
                        ),
                        source="rule:follow_up_window",
                    )
                )
            break  # one flag per condition, first matching keyword

    return flags


def flag_drug_interactions(record: PatientRecord) -> list[CareFlag]:
    flags: list[CareFlag] = []
    active_meds = [m.display.lower() for m in record.active_medications]

    for drug_a, drug_b, reason in KNOWN_INTERACTIONS:
        has_a = any(drug_a in med for med in active_meds)
        has_b = any(drug_b in med for med in active_meds)
        if has_a and has_b:
            flags.append(
                CareFlag(
                    patient_id=record.patient_id,
                    flag_type=FlagType.DRUG_INTERACTION,
                    detail=f"{drug_a} + {drug_b}: {reason}.",
                    # Labeled as a stub explicitly: Task 3 replaces this
                    # source string (and the static table above) with a
                    # real RxGround retrieval call.
                    source="stub:known_interactions (RxGround call arrives Task 3)",
                )
            )

    return flags


def generate_flags(record: PatientRecord, as_of: date) -> list[CareFlag]:
    return flag_overdue_follow_up(record, as_of) + flag_drug_interactions(record)
