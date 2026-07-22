#!/usr/bin/env bash
# data-ingestion-backend 로컬 실행 스크립트.
#
# 사용법: ./start.sh
# 브라우저에서 http://127.0.0.1:${INGESTION_PORT:-8010} 접속(업로드 폼),
# /runs 에서 처리 로그·적재 데이터 조회.
#
# 포트는 하드코딩하지 않고 저장소 루트 .env의 INGESTION_PORT를 읽는다(docs/06 §1).
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

PORT="${INGESTION_PORT:-8010}"
HOST="${INGESTION_HOST:-127.0.0.1}"

# --reload는 개발용 — 이 앱은 프로세스 전역 threading.Lock(단일 워커 전제) +
# in-memory BackgroundTasks로 처리 상태를 들고 있어, reloader 재시작 중 진행 중이던
# run이 유실될 수 있다(리뷰 2026-07-22 B-4). 기본은 off, 로컬 개발 시에만 명시적으로 켠다.
# (빈 배열 "${arr[@]}" 전개는 macOS 기본 /bin/bash 3.2에서 set -u와 함께 unbound
# variable로 죽으므로 배열 대신 if/else로 분기한다.)
cd "$SCRIPT_DIR"
if [ "${INGESTION_RELOAD:-0}" = "1" ]; then
  exec "$SCRIPT_DIR/.venv/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" --reload
else
  exec "$SCRIPT_DIR/.venv/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT"
fi
