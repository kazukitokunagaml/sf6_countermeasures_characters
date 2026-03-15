#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  uv venv
fi

source .venv/bin/activate
uv pip install -r requirements.txt

python app.py watch "$@"
