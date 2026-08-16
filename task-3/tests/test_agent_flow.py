
from src.agent import run_chart_review_agent
from src.fhir_loader import Condition, Medication, PatientRecord


def _record():
    return PatientRecord(
        patient_id="p1",
        conditions=[Condition(code="1", display="Heart failure (disorder)")],
        medications=[
            Medication(code="1", display="warfarin"),
            Medication(code="2", display="aspirin"),
        ],
        encounters=[],
    )


def test_happy_path_calls_both_tools_then_finishes(monkeypatch):
    import src.agent as agent_module

    monkeypatch.setattr(
        agent_module,
        "check_interaction",
        lambda a, b: type(
            "R", (), {"interacts": True, "detail": "bleeding risk", "source": "live:rxground"}
        )(),
    )
    monkeypatch.setattr(
        agent_module,
        "retrieve_guideline",
        lambda q: type("G", (), {"condition": "Heart Failure", "text": "follow up every 90 days"})(),
    )

    script = [
        "Thought: check interaction.\nAction: check_drug_interaction[warfarin, aspirin]",
        "Thought: check guideline.\nAction: retrieve_guideline[heart failure]",
        "Thought: done.\nFinal Answer: Confirmed interaction, overdue follow-up per guideline.",
    ]
    calls = iter(script)

    def scripted_chat(messages):
        return next(calls)

    result = run_chart_review_agent(_record(), "Heart failure overdue", chat_fn=scripted_chat)

    assert result.status == "pending_signoff"
    assert result.hit_step_limit is False
    assert len(result.steps) == 3
    assert result.steps[0].tool == "check_drug_interaction"
    assert result.steps[1].tool == "retrieve_guideline"
    assert "Confirmed interaction" in result.note_summary


def test_malformed_response_gets_a_nudge_not_a_crash(monkeypatch):
    script = [
        "I don't know what format to use.",
        "Thought: ok now I remember.\nFinal Answer: Draft note.",
    ]
    calls = iter(script)

    def scripted_chat(messages):
        return next(calls)

    result = run_chart_review_agent(_record(), "some flag", chat_fn=scripted_chat)
    assert result.status == "pending_signoff"
    assert result.steps[0].type == "format_error"
    assert result.steps[1].type == "final"


def test_bracket_and_paren_syntax_both_accepted(monkeypatch):
    import src.agent as agent_module

    monkeypatch.setattr(
        agent_module,
        "retrieve_guideline",
        lambda q: type("G", (), {"condition": "Heart Failure", "text": "x"})(),
    )
    script = [
        "Thought: use parens like a confused model would.\nAction: retrieve_guideline(heart failure)",
        "Thought: done.\nFinal Answer: Draft note.",
    ]
    calls = iter(script)

    def scripted_chat(messages):
        return next(calls)

    result = run_chart_review_agent(_record(), "some flag", chat_fn=scripted_chat)
    assert result.steps[0].tool == "retrieve_guideline"
    assert result.steps[0].observation is not None
