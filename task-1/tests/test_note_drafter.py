from src.care_flagger import CareFlag, FlagType
from src.note_drafter import draft_coordination_note


def test_no_flags_produces_clean_note():
    draft = draft_coordination_note("p1", [])
    assert draft.status == "pending_signoff"
    assert draft.flag_count == 0
    assert "No care-coordination items" in draft.summary


def test_flags_produce_pending_signoff_draft_never_sent():
    flags = [
        CareFlag(
            patient_id="p1",
            flag_type=FlagType.OVERDUE_FOLLOW_UP,
            detail="Heart failure: overdue.",
            source="rule:follow_up_window",
        )
    ]
    draft = draft_coordination_note("p1", flags)
    assert draft.status == "pending_signoff"
    assert draft.flag_count == 1
    assert "requires clinician sign-off" in draft.summary


def test_draft_has_no_send_method_or_attribute():
    draft = draft_coordination_note("p1", [])
    assert not hasattr(draft, "send")
    assert not hasattr(draft, "sent")
