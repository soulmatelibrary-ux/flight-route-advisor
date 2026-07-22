# 검토 리포트 — `backend/` ↔ `data-ingestion-backend/` 통합 가능성 (2026-07-22)

- 관련: [../CLAUDE.md](../CLAUDE.md) §5(읽기 전용 소비·원본 무변경), [../docs/01-architecture.md](../docs/01-architecture.md), [../docs/02-db-integration.md](../docs/02-db-integration.md)
- 요청 배경: 두 폴더(`backend/`, `data-ingestion-backend/`)가 나란히 있는 걸 보고 "기능적으로 통합할 수 있는지" 검토 요청. **실행 아님 — 검토 결과만.**

---

## 결론

**하나의 프로세스/앱으로 합치는 것은 권장하지 않는다.** 기술적으로 못 합칠 이유는 없지만(버전 호환·경로 무충돌), 지금의 분리는 스타일 문제가 아니라 **실제로 한 번 발생했던 최소권한(least-privilege) 위반 사고를 고친 결과물**이기 때문이다.

---

## 조사한 사실

### 1. 배포/인프라
- [docker/docker-compose.yml](../docker/docker-compose.yml)에 `db`(공용 postgres)·`route-api`(backend)·`weather` 3개 서비스만 있고, **`data-ingestion-backend`는 compose에 아예 안 묶여 있다**(자체 Dockerfile만 존재). 두 앱은 이미 같은 Postgres를 보지만 프로세스·배포는 완전히 분리돼 있다.

### 2. 환경변수
- DB 접속 정보부터 분리: `ADVISOR_DATABASE_URL`(`advisor_readonly` role) vs `DATABASE_URL`(`aviation_admin` 쓰기 role). `.env.example`이 "이 둘은 절대 같은 값이면 안 된다"고 명시.
- 포트 분리(`ROUTE_API_PORT=8000` vs `INGESTION_PORT=8010`), rate-limit 설정 키도 분리(`RATE_LIMIT_PER_MINUTE` vs `INGESTION_RATE_LIMIT_PER_MINUTE`).
- `CORS_ALLOWED_ORIGINS`는 backend 전용(ingestion은 서버렌더 Jinja UI라 CORS 자체가 불필요).

### 3. 의존성
- `fastapi`/`sqlalchemy`/`psycopg2-binary`/`python-dotenv` 버전은 동일 — 병합 장벽 아님.
- 하지만 ingestion만 `pandas`·`openpyxl`·`shapely`·`xlrd`·`alembic`·`jinja2`·`python-multipart`를 무겁게 물고 있다. backend는 이 중 아무것도 안 쓴다.

### 4. 분리 근거 (문서에 명시된 설계 의도)
- [docs/02-db-integration.md](../docs/02-db-integration.md): "`ADVISOR_DATABASE_URL`과 ingestion의 `DATABASE_URL`은 서로 다른 값이어야 한다… 같은 값을 공유하면 Stage 0가 재적재를 위해 쓰기 계정을 쓰는 동안 이 서비스도 같은 쓰기 권한을 갖게 되어 **최소권한 원칙이 무너진다**."
- [docs/01-architecture.md](../docs/01-architecture.md): "(B, advisor)는 스키마를 소유하지 않는다. DDL·INSERT는 전적으로 (A, ingestion)의 책임… **두 백엔드는 별도 프로세스·별도 저장소로 독립 배포·운영된다.**"
- [docs/07-checklist.md](../docs/07-checklist.md)는 실제로 두 앱이 `DATABASE_URL`을 공유해 최소권한 위반이 발생했던 이력을 기록하고, 이를 고치려고 일부러 `ADVISOR_DATABASE_URL` + 컬럼단위 GRANT 마이그레이션을 새로 만들었다고 적혀 있다. 즉 **"분리 안 하면 생기는 문제"를 이미 한 번 겪고 고친 결과물**이 지금의 구조다.
- `CLAUDE.md` §5: advisor 백엔드는 `processed_*`에 DDL/INSERT/UPDATE 금지.

### 5. 라우트/테이블 충돌
- URL 경로 충돌 없음(backend는 `/api/routes`·`/api/reference`, ingestion은 `/uploads`·`/runs`·`/tables`).
- 테이블 접근은 DB role 레벨에서 강제됨: ingestion(`aviation_admin`)은 `raw_*`/`processed_*`/`ingestion_runs`에 쓰기, advisor(`advisor_readonly`)는 `processed_*` 전체 SELECT + `ingestion_runs` 컬럼 제한 SELECT만, `raw_*`/`ingestion_logs`는 아예 권한 없음.

### 6. 코드 중복
- 양쪽 다 자체 `db/column_map.py`를 갖고 있고 **의도적으로 서로 다르다**(backend는 물리컬럼 튜플만, ingestion은 논리↔물리 매핑+UI용 설명까지). backend `column_map.py` 주석에 "별도 프로세스/배포이므로 그 모듈을 임포트하지 않고 다시 옮겨 담는다"고 명시 — **중복이 실수가 아니라 프로세스 독립성을 지키기 위한 설계 선택**.
- `config.py`의 env 로딩 보일러플레이트(`_require_env`/`ConfigError`/`_mask_database_url` 등)는 양쪽이 거의 동일하게 중복돼 있음 — 이건 의도된 분리라기보다 그냥 공유 유틸을 안 뽑아서 생긴 우연한 중복.

---

## 판단 근거 — 왜 프로세스 병합을 권장하지 않는가

- **최소권한 원칙이 프로세스 분리에 기대고 있다.** 같은 프로세스 안에서도 엔진/세션을 분리해 흉내 낼 수는 있지만, "실수로 advisor 라우트가 쓰기 세션을 참조"하는 사고 가능성이 구조적으로 열린다.
- **장애 격리.** ingestion은 알려진 리스크가 있다(외부 스킬 subprocess 호출, 대용량 파일 처리, 큰 워크스페이스 I/O, 크래시 시 run 고착 — [review-2026-07-22.md](./review-2026-07-22.md) B-2·B-3 참고). advisor는 프론트 지도가 실시간으로 의존하는 경로다. 한 프로세스로 합치면 ingestion 쪽 문제가 advisor 가용성에 영향을 줄 수 있다. 지금처럼 분리돼 있으면 ingestion이 죽어도 지도는 계속 뜬다.
- **배포 성격이 다르다.** advisor는 가볍고 상시 가동(프론트가 매 요청 의존), ingestion은 무겁고(pandas/shapely/xlrd 등) 간헐적·관리자용(업로드할 때만 씀). 합치면 advisor 배포 이미지가 불필요하게 무거워진다.
- **문서가 이미 명시적 아키텍처 결정으로 못박아 뒀다.** 되돌리려면 `docs/01`·`docs/02`·`CLAUDE.md §5`도 함께 바꿔야 하는데, 그 근거(최소권한)가 여전히 유효하므로 되돌릴 이유가 약하다.

---

## 대안 — 프로세스를 합치지 않고도 가능한 가벼운 정리

"통합"이 코드 중복 제거나 배포 편의를 뜻한다면 아래로 충분하다:

1. `docker-compose.yml`에 `data-ingestion-backend`용 서비스를 추가해 `docker compose up`으로 둘 다 뜨게 하기(지금은 ingestion만 compose 밖에 있음) — 배포 편의만 개선, 프로세스는 그대로 분리.
2. 두 `config.py`의 거의 동일한 env-로딩 보일러플레이트(`_require_env`/`ConfigError`/`_mask_database_url`)를 작은 공유 패키지(예: `libs/common_config.py`)로 뽑기 — `db/column_map.py`처럼 "의도적 중복"인 부분은 손대지 않는다.
3. (선택) 두 앱을 하나의 uvicorn 프로세스가 아니라 **하나의 docker-compose 스택**으로만 묶어 "한 번에 뜨는 하나의 백엔드처럼" 운영 경험을 통합.

---

## 다음 단계 (사용자 결정 필요)

아래 중 어느 걸 원하는지에 따라 실행 계획이 완전히 달라진다:
- (a) 아무것도 안 함 — 지금 구조 유지.
- (b) 가벼운 정리만: docker-compose에 ingestion 서비스 추가 + config 보일러플레이트 공유화.
- (c) 실제로 프로세스를 하나로 합치고 싶다(위 리스크를 감수하더라도) — 이 경우 최소권한을 프로세스 내부에서 어떻게 재현할지(별도 엔진/세션 강제, 라우터별 의존성 주입 등) 별도 설계가 필요하다.
</content>
</invoke>
