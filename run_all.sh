#!/usr/bin/env bash
#
# Full path from raw data to every table and figure.
#
#   ./run_all.sh              refresh both plans from the web, then analyse
#   ./run_all.sh --offline    analyse from the cached snapshot archive only
#
# --offline exists because the archive is the reproducible part and the network
# is not. Oregon rotates old quarters off its site and CalPERS publishes only
# the current table, so a run six months from now would silently analyse a
# different sample. Offline mode reproduces the committed results exactly.
#
# Every random procedure is seeded (bootstrap, permutation tests, simulation),
# so two runs on the same archive produce identical numbers. tests/test_repro.py
# asserts that.

set -euo pipefail

OFFLINE=0
for arg in "$@"; do
  case "$arg" in
    --offline) OFFLINE=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")"

if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# A virtualenv built at a different path still activates but leaves PATH
# pointing at a directory that no longer exists, so the first python call fails
# with a bare "command not found". Say what actually happened instead.
if ! command -v python >/dev/null 2>&1; then
  echo "python not found on PATH." >&2
  if [ -d .venv ]; then
    echo "A .venv exists here but does not work - it was most likely built" >&2
    echo "under a different path. Rebuild it:" >&2
    echo "  rm -rf .venv && python3 -m venv .venv" >&2
    echo "  .venv/bin/pip install -r requirements.txt" >&2
  else
    echo "Create one:  python3 -m venv .venv" >&2
    echo "             .venv/bin/pip install -r requirements.txt" >&2
  fi
  exit 1
fi

step() { printf '\n\033[1m=== %s\033[0m\n' "$1"; }

step "Tests"
python -m pytest -q

if [ "$OFFLINE" -eq 1 ]; then
  step "Offline mode: skipping network fetches"
  # The working copy is gitignored; a fresh clone has only the dated capture
  # in the archive, which the analysis scripts fall back to.
  if [ ! -f data/calpers_raw.csv ] && ! ls data/snapshots/calpers_raw_*.csv >/dev/null 2>&1; then
    echo "no CalPERS capture found in data/ or data/snapshots/;" >&2
    echo "run once without --offline first" >&2
    exit 1
  fi
  if ! ls data/snapshots/oregon_*.csv >/dev/null 2>&1; then
    echo "no Oregon snapshots cached; run once without --offline first" >&2
    exit 1
  fi
  echo "using $(ls data/snapshots/oregon_*.csv | wc -l | tr -d ' ') Oregon snapshots"
else
  step "Fetch CalPERS"
  python analysis/fetch_calpers.py

  step "Fetch Oregon PERS archive"
  python analysis/fetch_oregon.py
fi

step "Family-matching review"
python analysis/build_family_review.py

step "Persistence estimates (headline output)"
python analysis/run_real_analysis.py

step "Sample splits: by plan and by era"
python analysis/run_sample_split.py

step "Family-name numeral diagnostic"
python analysis/diagnose_numerals.py

step "Cross-plan measurement error"
python analysis/run_overlap.py

step "Vintage-label error simulation"
python analysis/simulate_vintage_error.py

step "Minimum detectable effect"
python analysis/minimum_detectable_effect.py

step "PME from the snapshot archive"
python analysis/run_pme.py

step "Validation on simulated data"
python analysis/run_analysis.py

step "Figures"
python analysis/make_figures.py

step "Done"
echo "Tables  -> data/*.csv"
echo "Figures -> figures/*.png"
echo "Log     -> DEVELOPMENT_LOG.md"
