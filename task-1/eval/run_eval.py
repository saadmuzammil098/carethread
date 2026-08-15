"""Eval-gate for the CareThread care flagger.

Runs `generate_flags` against a fixed set of 10 real Synthea-generated
patients (trimmed to Patient/Condition/MedicationRequest/Encounter
resources, see task-1/README.md) with hand-verified expected flags in
`golden_set.json`, scores exact-match precision/recall/F1 on flag
(patient_id, flag_type, detail) triples, and fails (nonzero exit) if the
score drops below the committed baseline in `baseline_score.json`.

This is what CI runs on every PR (see ../../.github/workflows/ci.yml):
a PR that quietly makes the flagger less accurate — a broken keyword, a
narrowed follow-up window, a typo in an interaction pair — lowers this
score below the baseline and the PR fails, before a human has to notice
by reading the diff.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.care_flagger import generate_flags
from src.fhir_loader import load_patient_record

EVAL_DIR = Path(__file__).resolve().parent
DATA_DIR = EVAL_DIR.parent / "data" / "golden_patients"
GOLDEN_SET_PATH = EVAL_DIR / "golden_set.json"
BASELINE_PATH = EVAL_DIR / "baseline_score.json"


def _flag_triples(flags: list[dict], patient_id: str) -> set[tuple[str, str, str]]:
    return {(patient_id, f["flag_type"], f["detail"]) for f in flags}


def run_eval() -> dict:
    golden = json.loads(GOLDEN_SET_PATH.read_text())
    as_of = date.fromisoformat(golden["as_of"])

    expected: set[tuple[str, str, str]] = set()
    predicted: set[tuple[str, str, str]] = set()

    for patient_id, entry in golden["patients"].items():
        expected |= _flag_triples(entry["expected_flags"], patient_id)

        record = load_patient_record(DATA_DIR / entry["file"])
        actual_flags = generate_flags(record, as_of)
        predicted |= {
            (patient_id, f.flag_type.value, f.detail) for f in actual_flags
        }

    true_positives = expected & predicted
    false_positives = predicted - expected
    false_negatives = expected - predicted

    precision = (
        len(true_positives) / len(predicted) if predicted else 1.0
    )
    recall = (
        len(true_positives) / len(expected) if expected else 1.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": len(true_positives),
        "false_positives": sorted(str(fp) for fp in false_positives),
        "false_negatives": sorted(str(fn) for fn in false_negatives),
        "n_patients": len(golden["patients"]),
    }


def main() -> int:
    result = run_eval()
    baseline = json.loads(BASELINE_PATH.read_text())

    print(json.dumps(result, indent=2))

    regressed = result["f1"] < baseline["f1"]
    if regressed:
        print(
            f"\nFAIL: f1={result['f1']} is below baseline f1={baseline['f1']} "
            "(quality-gate regression, PR blocked).",
            file=sys.stderr,
        )
        return 1

    print(
        f"\nPASS: f1={result['f1']} >= baseline f1={baseline['f1']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
