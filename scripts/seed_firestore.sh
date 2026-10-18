#!/usr/bin/env bash
# Seed Firestore with the dummy dataset (idempotent; pass --force to overwrite).
#   GOOGLE_CLOUD_PROJECT=my-proj ./scripts/seed_firestore.sh [--force]
# Works with the emulator too: FIRESTORE_EMULATOR_HOST=localhost:8085 ./scripts/seed_firestore.sh
set -euo pipefail
cd "$(dirname "$0")/../backend"
PY="${PY:-$( [[ -x .venv/bin/python ]] && echo .venv/bin/python || echo python3 )}"
"$PY" -m app.seed "$@"
