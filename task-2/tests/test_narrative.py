from types import SimpleNamespace

import pytest
import src.narrative as narrative_module
from src.care_flagger import CareFlag, FlagType
from src.narrative import generate_narrative


def _flags():
    return [
        CareFlag(
            patient_id="p1",
            flag_type=FlagType.OVERDUE_FOLLOW_UP,
            detail="Heart failure (disorder): follow-up window is 90 days, last encounter 200 days ago.",
            source="rule:follow_up_window",
        )
    ]


def _fake_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def test_empty_flags_never_calls_the_llm(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not call the LLM when there are no flags")

    monkeypatch.setattr(narrative_module.router, "completion", boom)
    result = generate_narrative("p1", [])
    assert "No care-coordination items" in result


def test_llm_output_used_when_it_covers_every_flag(monkeypatch):
    monkeypatch.setattr(
        narrative_module.router,
        "completion",
        lambda **kwargs: _fake_response(
            "Patient has heart failure (disorder) noted as overdue for follow-up."
        ),
    )
    result = generate_narrative("p1", _flags())
    assert result == "Patient has heart failure (disorder) noted as overdue for follow-up."


def test_falls_back_to_deterministic_when_llm_drops_a_flag(monkeypatch):
    monkeypatch.setattr(
        narrative_module.router,
        "completion",
        lambda **kwargs: _fake_response("Everything looks fine, no concerns."),
    )
    result = generate_narrative("p1", _flags())
    assert "requires clinician sign-off" in result  # Task 1's deterministic template


def test_falls_back_to_deterministic_when_every_provider_fails(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("all providers exhausted")

    monkeypatch.setattr(narrative_module.router, "completion", boom)
    result = generate_narrative("p1", _flags())
    assert "requires clinician sign-off" in result


@pytest.mark.parametrize("bad_output", ["", "   "])
def test_blank_llm_output_falls_back(monkeypatch, bad_output):
    monkeypatch.setattr(
        narrative_module.router,
        "completion",
        lambda **kwargs: _fake_response(bad_output),
    )
    result = generate_narrative("p1", _flags())
    assert "requires clinician sign-off" in result
