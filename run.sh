#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

source .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo "경고: .env 파일이 없습니다. .env.example을 복사해 AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY를 채워 주세요." >&2
fi

uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
