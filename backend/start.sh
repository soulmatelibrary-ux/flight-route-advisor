#!/usr/bin/env bash
# backend(Stage 1 advisor, 읽기 전용) 로컬 실행 스크립트.
#
# 사용법: ./start.sh
# http://127.0.0.1:${ROUTE_API_PORT:-8088}/api/* , /docs(OpenAPI)
#
# data-ingestion-backend/start.sh와 동일 패턴(포트 하드코딩 금지, 저장소 루트 .env 사용,
# docs/06 §1). 두 백엔드는 의도적으로 별도 프로세스로 유지한다
# (근거: ../result/backend-integration-review-2026-07-22.md — 최소권한·장애격리).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [ ! -x "$SCRIPT_DIR/.venv/bin/uvicorn" ]; then
  echo "가상환경이 없음: $SCRIPT_DIR/.venv (README/docs/08-setup-and-dev-order.md 참고해 먼저 만드세요)" >&2
  exit 1
fi

PORT="${ROUTE_API_PORT:-8088}"
HOST="${ROUTE_API_HOST:-127.0.0.1}"

cd "$SCRIPT_DIR"
# --reload는 개발용 — data-ingestion-backend/start.sh와 동일 원칙으로 기본 off,
# 로컬 개발 시에만 명시적으로 켠다. (빈 배열 "${arr[@]}" 전개는 macOS 기본 bash 3.2에서
# `set -u`와 함께 "unbound variable"로 죽는다 — 배열 대신 분기로 처리)
if [ "${ROUTE_API_RELOAD:-0}" = "1" ]; then
  exec "$SCRIPT_DIR/.venv/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" --reload
else
  exec "$SCRIPT_DIR/.venv/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT"
fi
