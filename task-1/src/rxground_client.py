"""Live HTTP client for RxGround's Task 7 query service.

The genuine cross-project integration the roadmap's CareThread Task 3
asks for: a real network call, at agent runtime, into a separate git
repository's separately deployed process (`rxground/task-7/service.py`,
run via `uvicorn service:app --port 8100`), not a shared library import
and not a copy of RxGround's data. Task 1's `care_flagger.py` originally
shipped a static `KNOWN_INTERACTIONS` table explicitly labeled a stub
"RxGround call arrives Task 3", this module is that call.

Fails closed to Task 1's original static table, not to a hallucinated
answer or a 500: if RxGround's service is unreachable (down, wrong
port, network partition), `check_interaction` falls back to the same
static pairs `care_flagger.py` already had, degraded but never silent,
`RxGroundCheckResult.source` always says which path actually answered.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

RXGROUND_URL = os.environ.get("RXGROUND_URL", "http://localhost:8100")
RXGROUND_TIMEOUT_SECONDS = float(os.environ.get("RXGROUND_TIMEOUT_SECONDS", "60"))

# Fallback table only, used when RxGround's live service can't be
# reached at all. Identical to care_flagger.py's original
# KNOWN_INTERACTIONS, kept here (not imported) since it's this module's
# fallback path, not the flagger's primary one anymore.
_FALLBACK_INTERACTIONS: list[tuple[str, str, str]] = [
    ("warfarin", "aspirin", "combined bleeding risk"),
    ("lisinopril", "spironolactone", "hyperkalemia risk"),
    ("simvastatin", "clarithromycin", "myopathy/rhabdomyolysis risk"),
    ("metformin", "iodinated contrast", "lactic acidosis risk"),
]


class RxGroundCheckResult:
    def __init__(
        self,
        interacts: bool,
        detail: str,
        source: str,
        groundedness_score: float | None = None,
    ) -> None:
        self.interacts = interacts
        self.detail = detail
        self.source = source
        self.groundedness_score = groundedness_score

    def __repr__(self) -> str:
        return (
            f"RxGroundCheckResult(interacts={self.interacts!r}, "
            f"source={self.source!r})"
        )


def _fallback_check(drug_a: str, drug_b: str) -> RxGroundCheckResult:
    a, b = drug_a.lower(), drug_b.lower()
    for known_a, known_b, reason in _FALLBACK_INTERACTIONS:
        if {known_a, known_b} <= {a, b} or (known_a in a and known_b in b) or (
            known_a in b and known_b in a
        ):
            return RxGroundCheckResult(
                interacts=True,
                detail=reason,
                source="fallback:static_table (RxGround unreachable)",
            )
    return RxGroundCheckResult(
        interacts=False,
        detail="no known interaction in the static fallback table",
        source="fallback:static_table (RxGround unreachable)",
    )


def check_interaction(drug_a: str, drug_b: str) -> RxGroundCheckResult:
    try:
        response = requests.post(
            f"{RXGROUND_URL}/check_interaction",
            json={"drug_a": drug_a, "drug_b": drug_b},
            timeout=RXGROUND_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.warning(
            "RxGround service unreachable at %s, falling back to the static "
            "interaction table.",
            RXGROUND_URL,
            exc_info=True,
        )
        return _fallback_check(drug_a, drug_b)

    body = response.json()

    if body["refused"]:
        return RxGroundCheckResult(
            interacts=False,
            detail=body["refusal_reason"] or "not covered by RxGround's indexed labels",
            source="live:rxground",
        )

    claim_texts = " ".join(claim["text"] for claim in body["claims"])
    return RxGroundCheckResult(
        interacts=True,
        detail=claim_texts,
        source="live:rxground",
        groundedness_score=body["groundedness_score"],
    )
