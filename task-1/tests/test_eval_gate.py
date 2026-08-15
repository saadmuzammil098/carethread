import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from run_eval import run_eval


def test_eval_matches_committed_baseline_exactly():
    # Golden set was generated from generate_flags itself, so a passing
    # flagger should score a perfect match against it. If this ever
    # isn't 1.0, either the flagger changed or golden_set.json is stale.
    result = run_eval()
    assert result["f1"] == 1.0
    assert result["false_positives"] == []
    assert result["false_negatives"] == []


def test_eval_covers_both_flag_types():
    result = run_eval()
    assert result["true_positives"] >= 2  # at least one overdue + one interaction
