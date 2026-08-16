"""Drafts a coordination note from a patient's flags. Never sends anything.

CareThread's one hard rule, stated in the roadmap for every later task
too: the system drafts, a human signs off. `draft_coordination_note`
returns a draft object with `status="pending_signoff"` and nothing in
this module has a send-path. There's no channel to remove later, on
purpose, sending was never wired up in the first place.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.care_flagger import CareFlag, FlagType


class CoordinationNoteDraft(BaseModel):
    patient_id: str
    status: str = "pending_signoff"
    summary: str
    flag_count: int


_FLAG_LABELS = {
    FlagType.OVERDUE_FOLLOW_UP: "Overdue follow-up",
    FlagType.DRUG_INTERACTION: "Potential drug interaction",
}


def draft_coordination_note(
    patient_id: str, flags: list[CareFlag]
) -> CoordinationNoteDraft:
    if not flags:
        summary = "No care-coordination items identified at this time."
    else:
        lines = [
            f"- {_FLAG_LABELS[flag.flag_type]}: {flag.detail}" for flag in flags
        ]
        summary = (
            "Care-coordination items identified for review (draft, "
            "requires clinician sign-off before any action is taken):\n"
            + "\n".join(lines)
        )

    return CoordinationNoteDraft(
        patient_id=patient_id,
        summary=summary,
        flag_count=len(flags),
    )
