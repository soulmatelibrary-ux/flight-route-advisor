#!/usr/bin/env bash
# 통합 실행 스크립트 — db+weather(docker compose) → Stage 0(ingestion)·Stage 1(advisor,
# 프론트 동일 오리진 서빙 포함)를 한 번에 띄운다.
#
# 사용법: ./start.sh
# 종료: Ctrl+C (ingestion·advisor 프로세스만 정리, db/weather 컨테이너는 계속 실행
#       — 완전 종료하려면 `docker compose -f docker/docker-compose.yml down`)
#
# 주의: 이건 "하나의 앱으로 합치는" 스크립트가 아니다. 두 프로세스(ingestion API/
# advisor API)는 여전히 독립적으로 뜬다 — advisor는 읽기전용 role, ingestion은 쓰기
# role로 최소권한이 분리돼 있고(docs/02-db-integration.md), 이 분리를 유지하는 게
# 맞다는 검토 결과가 result/backend-integration-review-2026-07-22.md에 있다. 이
# 스크립트는 그 결론의 "가벼운 정리"(운영 편의) 옵션 — 실행 편의만 하나로 묶는다.
# 프론트는 별도 서버 없이 advisor가 같은 포트("/")에서 서빙한다(완료검증 §D-4).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$REPO_ROOT/.env"
COMPOSE_FILE="$REPO_ROOT/docker/docker-compose.yml"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  echo "루트 .env가 없음: $ENV_FILE (.env.example을 복사해 먼저 값을 채우세요)" >&2
  exit 1
fi

# --- 사전 점검 ---
command -v docker >/dev/null 2>&1 || { echo "docker가 필요합니다." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose(v2 플러그인)가 필요합니다." >&2; exit 1; }

if [ ! -x "$REPO_ROOT/data-ingestion-backend/.venv/bin/uvicorn" ]; then
  echo "가상환경이 없음: data-ingestion-backend/.venv (docs/08-setup-and-dev-order.md 참고)" >&2
  exit 1
fi
if [ ! -x "$REPO_ROOT/backend/.venv/bin/uvicorn" ]; then
  echo "가상환경이 없음: backend/.venv (docs/08-setup-and-dev-order.md 참고)" >&2
  exit 1
fi

# TCP 포트가 이미 리스닝 중인지 확인(이 저장소 프로세스든 무관한 다른 프로세스든) —
# 이미 떠 있으면 중복 기동을 시도하지 않고, 무관한 프로세스가 점유 중이면 크래시
# 대신 명확히 경고한다.
port_listening() {
  (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null || return 1
  exec 3>&- 3<&-
  return 0
}

# --- db(필수) 기동 ---
echo "docker compose: db 기동 중..."
docker compose -f "$COMPOSE_FILE" up -d db

# --- weather(선택 — 실패해도 계속 진행. net.js가 공개 프록시로 폴백하므로 non-fatal) ---
if [ -n "${PORTING_PACKAGE_ROOT:-}" ] && [ -d "${PORTING_PACKAGE_ROOT}/기상서버" ]; then
  echo "docker compose: weather 기동 중..."
  if ! docker compose -f "$COMPOSE_FILE" up -d weather; then
    echo "경고: weather 컨테이너 기동 실패 — 계속 진행합니다" \
      "(공항 기상은 net.js의 공개 프록시 폴백으로만 동작). 로그: docker compose -f docker/docker-compose.yml logs weather" >&2
  fi
else
  echo "경고: PORTING_PACKAGE_ROOT/기상서버 경로를 찾을 수 없어 weather 컨테이너는 건너뜁니다" \
    "(공항 기상은 net.js의 공개 프록시 폴백으로만 동작)." >&2
fi

echo "db 준비 대기 중..."
DB_READY=0
for _ in $(seq 1 30); do
  if docker compose -f "$COMPOSE_FILE" exec -T db \
    pg_isready -U "${POSTGRES_USER:-aviation_admin}" -d "${POSTGRES_DB:-aviation}" >/dev/null 2>&1; then
    DB_READY=1
    break
  fi
  sleep 1
done
if [ "$DB_READY" -ne 1 ]; then
  echo "db가 30초 내 준비되지 않음 — docker compose -f docker/docker-compose.yml logs db 로 확인하세요." >&2
  exit 1
fi
echo "db 준비 완료"

# --- 두 백엔드 기동(독립 유지 — 병합 아님) ---
INGESTION_PORT_VAL="${INGESTION_PORT:-8010}"
INGESTION_PID=""
if port_listening 127.0.0.1 "$INGESTION_PORT_VAL"; then
  echo "ingestion API(포트 ${INGESTION_PORT_VAL})가 이미 실행 중 — 재기동하지 않습니다."
else
  "$REPO_ROOT/data-ingestion-backend/start.sh" &
  INGESTION_PID=$!
fi

ROUTE_API_PORT_VAL="${ROUTE_API_PORT:-8088}"
BACKEND_PID=""
if port_listening 127.0.0.1 "$ROUTE_API_PORT_VAL"; then
  echo "경고: advisor API 포트(${ROUTE_API_PORT_VAL})가 이미 다른 프로세스에서 사용 중이라" \
    "advisor를 기동하지 않습니다. 누가 쓰는지: lsof -nP -iTCP:${ROUTE_API_PORT_VAL} -sTCP:LISTEN" \
    "— 다른 프로세스라면 이 저장소 .env의 ROUTE_API_PORT를 빈 포트로 바꿔 재실행하세요." >&2
else
  "$REPO_ROOT/backend/start.sh" &
  BACKEND_PID=$!
fi

cleanup() {
  echo ""
  echo "종료 중 — 이 스크립트가 띄운 ingestion/advisor 프로세스만 정리(db/weather 컨테이너는 유지)..."
  for pid in "$INGESTION_PID" "$BACKEND_PID"; do
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  echo "완전 종료하려면: docker compose -f docker/docker-compose.yml down"
}
trap cleanup EXIT

echo ""
echo "=== 기동 완료 ==="
echo "프론트+advisor API : http://localhost:${ROUTE_API_PORT_VAL}/ (API는 /api/*, 문서는 /docs)"
echo "ingestion 업로드   : http://localhost:${INGESTION_PORT_VAL}"
echo "Ctrl+C로 이 스크립트가 띄운 프로세스만 종료(db/weather는 계속 실행)."
echo ""

wait
