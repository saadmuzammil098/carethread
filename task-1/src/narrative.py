"""LLM-authored narrative summary layered on top of Task 1's deterministic note.

Task 2 work (the LiteLLM gateway, this narrative layer, response
caching), living in `task-1/src/` rather than a separate `task-2/src/`
package: every task folder in this roadmap names its package `src`
(relative imports inside each), and this module needs to import
Task 1's `care_flagger`/`note_drafter` directly, in the same running
Lambda process, on every request. A second top-level `src` package
would collide with Task 1's the moment both are imported (see
FleetPulse's `task-2/src/load_data.py` docstring for the same collision
hit there, and why that project's answer was "don't build an import
shim, avoid the cross-import"). Task 2 genuinely needs the live
objects, not just a data file, so the answer here is architectural
instead: this is the same deployed app Task 1 shipped, not a second
one, so its new files belong in Task 1's package. Task 2's own folder
holds its Terraform, load-test scripts, tests, and README, not source
that would re-collide.

The rule-based flag list stays the single source of truth, this module
never lets the LLM invent, drop, or reword which items are flagged, it
can only phrase the *same* structured flags as a readable paragraph.
Guarded two ways:

  1. Every flag's distinguishing detail (the condition/drug name) must
     appear in the LLM's output, or the whole narrative is discarded.
     A model that "cleans up" a flag out of the response, plausible
     phrasing that silently drops a real safety item, fails this check
     the same as one that hallucinates an extra one, both alter the
     original claim.
  2. If every provider in the gateway's fallback chain fails (a total
     outage), `generate_narrative` returns Task 1's deterministic
     bullet-point summary instead of raising. A coordination note
     always exists, LLM narrative is a presentation layer on top of it,
     never a dependency of it.
"""
from __future__ import annotations

import logging

from src.care_flagger import CareFlag
from src.llm_gateway import MODEL_GROUP, router
from src.note_drafter import draft_coordination_note

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You rephrase a clinician's structured care-coordination flags into one "
    "short plain-language paragraph for a coordination note. Rules: mention "
    "every flag given, exactly as described, do not add any flag, condition, "
    "medication, or recommendation not present in the input. Do not suggest "
    "next steps or dosing. Output only the paragraph, no preamble."
)


def _flag_key_terms(flag: CareFlag) -> str:
    # The condition/drug name is the first ": "-delimited segment of
    # `detail` (see care_flagger.py's f-strings), the part a narrative
    # must not drop or substitute.
    return flag.detail.split(":", 1)[0].strip().lower()


def _narrative_covers_all_flags(narrative: str, flags: list[CareFlag]) -> bool:
    narrative_lower = narrative.lower()
    return all(_flag_key_terms(flag) in narrative_lower for flag in flags)


def generate_narrative(patient_id: str, flags: list[CareFlag]) -> str:
    deterministic = draft_coordination_note(patient_id, flags).summary

    if not flags:
        return deterministic

    flag_lines = "\n".join(
        f"- {flag.flag_type.value}: {flag.detail}" for flag in flags
    )

    try:
        response = router.completion(
            model=MODEL_GROUP,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": flag_lines},
            ],
            timeout=15,
        )
        narrative = response.choices[0].message.content.strip()
    except Exception:  # noqa: BLE001 -- deliberately catch-all: any failure
        # from any provider in the fallback chain (litellm raises its own
        # exception hierarchy per-provider, not one common type) must fall
        # back to the deterministic summary, never surface as a 500.
        logger.warning(
            "LLM narrative generation failed for patient %s, all providers "
            "exhausted, falling back to deterministic summary.",
            patient_id,
        )
        return deterministic

    if not _narrative_covers_all_flags(narrative, flags):
        logger.warning(
            "LLM narrative for patient %s dropped or altered a flag, "
            "discarding and falling back to deterministic summary.",
            patient_id,
        )
        return deterministic

    return narrative
