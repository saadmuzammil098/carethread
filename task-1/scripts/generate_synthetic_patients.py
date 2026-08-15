"""Regenerates the raw Synthea population this task's golden set was drawn from.

Not run in CI, not run automatically, this is a one-time (or occasional,
if you want a different population) data-generation step, documented
here so the exact command is reproducible rather than only living in
shell history. `data/golden_patients/` is what's actually committed and
what tests/eval run against; this script's output is scratch, never
committed (see ../../.gitignore's `task-1/data/synthea_raw/`).

Requires a JDK (Synthea is a real Java tool, not a Docker Hub image,
`synthetichealth/synthea` on Docker Hub is a years-stale pre-rewrite
Ruby image, confirmed by inspecting it, not what this project uses) and
downloads the current `synthea-with-dependencies.jar` from Synthea's
GitHub releases (~190MB) into this directory on first run.

Usage:
    python scripts/generate_synthetic_patients.py
"""
from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parents[1]
JAR_PATH = TASK_DIR / "scripts" / "synthea-with-dependencies.jar"
JAR_URL = (
    "https://github.com/synthetichealth/synthea/releases/download/"
    "master-branch-latest/synthea-with-dependencies.jar"
)
OUTPUT_DIR = TASK_DIR / "data" / "synthea_raw"

# -p is a target *living* population (Synthea also emits patients who
# die during simulation, past run counts total ~35 for -p 30), -s pins
# the RNG seed for a reproducible population, -a bounds current age so
# every patient has enough encounter history for the follow-up-window
# rules in src/care_flagger.py to have something to evaluate.
SYNTHEA_ARGS = ["-p", "30", "-s", "42", "-a", "25-85"]
STATE = "Massachusetts"


def download_jar() -> None:
    if JAR_PATH.exists():
        return
    print(f"Downloading Synthea jar to {JAR_PATH} ...")
    urllib.request.urlretrieve(JAR_URL, JAR_PATH)


def run_synthea() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "java",
        "-jar",
        str(JAR_PATH),
        *SYNTHEA_ARGS,
        "--exporter.fhir.export=true",
        f"--exporter.baseDirectory={OUTPUT_DIR}",
        STATE,
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    download_jar()
    run_synthea()
    print(
        f"\nDone. FHIR bundles written to {OUTPUT_DIR / 'fhir'}.\n"
        "This is raw, untrimmed output (dozens of resource types per "
        "patient, tens of MB); golden_patients/ was hand-selected and "
        "trimmed from a run of this script, see README.md's "
        "'Why the golden set is 10 real (trimmed) Synthea patients'."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
