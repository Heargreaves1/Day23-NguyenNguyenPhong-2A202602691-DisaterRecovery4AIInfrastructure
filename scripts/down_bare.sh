#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
python3 scripts/down_bare.py "$@"
