#!/usr/bin/env bash
# Run the VentTRACE pipeline, in order, logging each step.
#
#   ./run_all.sh            # 01 .. 07
#   ./run_all.sh 02 03      # only those steps
#
# Always launches from the repo root: config's output_directory is "./output",
# a path relative to the working directory, so where you start decides where
# results land. Tests are separate: uv run pytest tests/

set -euo pipefail
cd "$(dirname "$0")"

[ -f config/config.json ] || {
  echo "config/config.json missing — cp config/config_template.json config/config.json" >&2
  exit 1
}

STEPS=(01_cohort 02_index_paralytic 03_context 04_covariates 05_table_one 06_reference_cpt 07_artifact_manifest)

if [ $# -gt 0 ]; then
  picked=()
  for want in "$@"; do
    for step in "${STEPS[@]}"; do
      [[ $step == "$want"* ]] && picked+=("$step")
    done
  done
  [ ${#picked[@]} -gt 0 ] || { echo "no step matches: $*" >&2; exit 1; }
  STEPS=("${picked[@]}")
fi

LOG_DIR="output/logs/run_$(date -u +%Y%m%dT%H%M%SZ)"   # UTC, never the OS zone
mkdir -p "$LOG_DIR"

uv sync --quiet
echo "logs: $LOG_DIR"

for step in "${STEPS[@]}"; do
  echo; echo "=== $step ==="
  start=$SECONDS
  if ! uv run python "code/$step.py" 2>&1 | tee "$LOG_DIR/$step.log"; then
    echo "FAILED at $step — see $LOG_DIR/$step.log" >&2
    exit 1
  fi
  echo "--- $step ok in $((SECONDS - start))s"
done

artifact_count=$(uv run python -c 'from pathlib import Path; print(sum(p.is_file() for p in Path("output/final_no_phi").rglob("*")))')
echo; echo "done: ${#STEPS[@]} steps, $artifact_count artifacts in output/final_no_phi"
