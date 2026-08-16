from src import rxground_client
from src.rxground_client import check_interaction


class _FakeResponse:
    def __init__(self, json_body, status_code=200):
        self._json_body = json_body
        self.status_code = status_code

    def json(self):
        return self._json_body

    def raise_for_status(self):
        pass


def test_live_call_returns_interaction_when_not_refused(monkeypatch):
    def fake_post(url, json, timeout):
        return _FakeResponse(
            {
                "refused": False,
                "refusal_reason": None,
                "claims": [{"text": "increases bleeding risk", "cited_chunk_ids": ["x:y:1"], "groundedness": 0.5}],
                "groundedness_score": 0.5,
            }
        )

    monkeypatch.setattr(rxground_client.requests, "post", fake_post)
    result = check_interaction("warfarin", "aspirin")
    assert result.interacts is True
    assert result.source == "live:rxground"
    assert "bleeding" in result.detail


def test_live_call_returns_no_interaction_when_refused(monkeypatch):
    def fake_post(url, json, timeout):
        return _FakeResponse(
            {"refused": True, "refusal_reason": "not covered", "claims": [], "groundedness_score": 1.0}
        )

    monkeypatch.setattr(rxground_client.requests, "post", fake_post)
    result = check_interaction("drugx", "drugy")
    assert result.interacts is False
    assert result.source == "live:rxground"
    assert result.detail == "not covered"


def test_unreachable_service_falls_back_to_static_table(monkeypatch):
    def boom(url, json, timeout):
        raise rxground_client.requests.RequestException("connection refused")

    monkeypatch.setattr(rxground_client.requests, "post", boom)
    result = check_interaction("warfarin", "aspirin")
    assert result.interacts is True
    assert "fallback" in result.source


def test_unreachable_service_fallback_no_match_returns_no_interaction(monkeypatch):
    def boom(url, json, timeout):
        raise rxground_client.requests.RequestException("timeout")

    monkeypatch.setattr(rxground_client.requests, "post", boom)
    result = check_interaction("totally_unrelated_drug_a", "totally_unrelated_drug_b")
    assert result.interacts is False
    assert "fallback" in result.source
