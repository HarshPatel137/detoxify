#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "Usage: scripts/build_model.sh /path/to/hurtlex_EN.tsv[.gz]"
  exit 1
fi
python -m src.training.build_hurtlex_model --tsv "$1"
