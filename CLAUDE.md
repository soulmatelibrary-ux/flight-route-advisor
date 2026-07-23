# CLAUDE.md

이 파일은 **flight-route-advisor 저장소에서 개발할 때 항상 지키는 개발 원칙**이다.
**기능 명세·구현 내용은 넣지 않는다**(그건 `docs/`에). 여기에는 일관된 원칙만 둔다.

---

## 0. 이 폴더만 보고 개발한다 — 문서 지도

개발에 필요한 설계·계획은 모두 이 폴더 안에 있다. 아래 순서로 읽는다.

| 문서 | 용도 |
|---|---|
| [docs/00-plan.md](docs/00-plan.md) | 목표·범위·로드맵·리스크 |
| [docs/01-architecture.md](docs/01-architecture.md) | 아키텍처·데이터 흐름 |
| [docs/02-db-integration.md](docs/02-db-integration.md) | 전처리 DB(`processed_*`) 연동 |
| [docs/03-backend-api.md](docs/03-backend-api.md) | FastAPI API 명세 |
| [docs/04-frontend-migration.md](docs/04-frontend-migration.md) | 지도 앱 전환 |
| [docs/05-mvp-scope.md](docs/05-mvp-scope.md) | 범위·코드 구조·로드맵 |
| [docs/06-conventions.md](docs/06-conventions.md) | 규약·함정·하드코딩 금지·**시큐어코딩** |
| [docs/07-checklist.md](docs/07-checklist.md) | **진행 기준점**(순차 개발 체크리스트) |
| [docs/08-setup-and-dev-order.md](docs/08-setup-and-dev-order.md) | env 루트·로컬 pgsql 기동·순차 개발 순서 |
| [docs/09-review-notes.md](docs/09-review-notes.md) | 문서 리뷰 문제점·개선점 로그 |
| [docs/10-ui-and-realtime.md](docs/10-ui-and-realtime.md) | UI 방향(결정 중심)·실시간 로드맵 |
| [docs/11-ai-route-reasoning-proposal.md](docs/11-ai-route-reasoning-proposal.md) | AI 경로추천 근거화 — 분석·결정표(§12 확정, [14]가 단일출처) |
| [docs/12-operational-goal-and-scenarios.md](docs/12-operational-goal-and-scenarios.md) | 운영 목표·의사결정 시나리오(프로젝트의 "왜") |
| [docs/13-ai-reasoning-dev-plan.md](docs/13-ai-reasoning-dev-plan.md) | AI 근거화 **구현 스펙**(방향 A, STEP·수용기준·보안 단일출처) |
| [docs/14-improvement-request.md](docs/14-improvement-request.md) | AI 근거화 **개선요구서 v1.0**(결정 확정 단일출처) |
| [data-ingestion-backend/docs/](data-ingestion-backend/docs/) | 전처리 적재 백엔드 문서(미러) — Stage0 근거 |

> ⚠ **docs 11~14는 "AI 경로추천 근거화" 추가개발 묶음**(현재 빌드 완료 후 착수, [13 §0](docs/13-ai-reasoning-dev-plan.md) 게이트). 읽는 순서: **12(왜) → 11(분석) → 14(확정 결정) → 13(구현 STEP)**.

## 0.1 외부 자산은 env 경로로 참조한다 (복사·수정 금지)

이 저장소는 코드/문서의 중심이고, **데이터·스킬·참조자산은 외부에 있다**. 절대경로를 코드에 박지 말고 env로 받는다(상세 [docs/08](docs/08-setup-and-dev-order.md)).

- `SOURCE_PROJECT_ROOT` → 전처리 원본 프로젝트(스킬 `skills/`, 원본데이터 `ACDM/·FOIS/·비행자료/·흐름관리일지/·공간데이터/`, `outputs/`). 기본값 `…/project/result/데이터전처리기술이식`.
- `PORTING_PACKAGE_ROOT` → 지도 이식 패키지(참조 지오메트리 `사전빌드_JSON/`, 기상서버 `기상서버/`, 집계 스크립트 `전처리스크립트/`, 원본 기능/알고리즘 문서 `문서/03·04·07·08`). 기본값 `…/project/result/비행경로추천서비스_이식패키지`.
- 이 외부 자산은 **읽기 전용**. 수정·삭제하지 않는다.

> **백데이터(입력 자산)는 `project/result/`에 있다.** ⚠ 이 저장소의 `result/`(완료검증 출력)와는 **다른 폴더**다(§8). `project/result/`에는 아무것도 쓰지 않는다.

## 1. 순차 개발 순서 (DB는 로컬 PostgreSQL 먼저)

**Stage 0 전처리 적재** → **Stage 1 advisor 백엔드** → **Stage 2 프론트**.
- Stage 0: 원본 파일 업로드→기존 스킬 실행→로컬 pgsql `processed_*` 적재(근거: [data-ingestion-backend/docs](data-ingestion-backend/docs/)).
- Stage 1·2는 Stage 0가 채운 **동일 로컬 pgsql**을 소비한다(핸드오프 [docs/08](docs/08-setup-and-dev-order.md)).
- 향후 Supabase 이전은 `DATABASE_URL` 교체로 대응(설계만, 상세 [docs/02](docs/02-db-integration.md)).
- **진행 기준점은 [docs/07-checklist.md](docs/07-checklist.md)** 이다.

## 2. 하드코딩 금지 (설정 주도)

URL·포트·임계값·색상·컬럼명·경로·자격증명을 코드에 박지 않는다. 모두 env·config·매핑 단일출처(`column_map`)로 뺀다. 자격증명은 커밋 금지(`.env`는 `.gitignore`, `.env.example`만 커밋). 상세 [docs/06 §1](docs/06-conventions.md).

## 3. 시큐어코딩 필수

모든 코드는 다음을 지킨다(상세 [docs/06](docs/06-conventions.md)).
- 입력 검증(타입·범위·화이트리스트). 신뢰 못 할 입력을 그대로 쓰지 않는다.
- **SQL 인젝션 방지**: 문자열 조립 금지, 파라미터라이즈드 쿼리/SQLAlchemy Core 바인딩만.
- 업로드/경로: 확장자·크기 제한, 서버생성 파일명, `../` 경로주입 차단.
- 비밀정보: 코드·문서·로그에 노출 금지, 환경변수로만.
- DB는 **최소권한 role**(advisor는 읽기 전용).
- CORS 화이트리스트, 의존성 버전 고정, 오류 응답에 내부 구현/스택 비노출.

## 4. 리뷰에이전트 기반 리뷰 (완료 전 필수 게이트)

구현 단위([docs/07](docs/07-checklist.md)의 각 항목)를 마칠 때마다 **리뷰에이전트**(`code-reviewer`/`senior-code-reviewer`)로 다음을 점검하고, **지적사항을 고친 뒤에만** 체크한다.
1. 기능 버그  2. 논리 버그  3. 예외처리 누락  4. 보안 취약점(시큐어코딩 §3 위반)

리뷰·수정 결과를 **요약 보고**한다. 리뷰 없이 "완료"로만 끝내지 않는다.

## 5. 읽기 전용 소비 · 원본 무변경

- advisor 백엔드는 전처리 DB에 **DDL/INSERT/UPDATE 금지** — `processed_*`를 읽기만 한다.
- `SOURCE_PROJECT_ROOT`/`PORTING_PACKAGE_ROOT`의 외부 자산, `data-ingestion-backend/` 미러, `project/result/` 백데이터는 **수정·삭제하지 않는다**(미러는 원본에서 재복사로만 동기화).
- `processed_*`는 append-only이므로 **항상 최신 SUCCESS run/기간으로 조회**한다(단순 `SELECT *` 금지, [docs/02 §3](docs/02-db-integration.md)).

## 6. 대용량 파일 직접 읽기 금지

CSV·XLSX·완성본 HTML(15MB) 등을 `Read`로 통째로 열지 않는다(토큰 과소비). 짧은 pandas/스크립트로 필요한 행/열/구조만 확인한다.

## 7. 좌표·시간 규약

- 좌표는 항상 `[lat, lon]`(GeoJSON과 반대). flat 폴리곤 형태 유지.
- 시각은 **KST 고정**, `+9` 재변환 금지. 상세 [docs/06](docs/06-conventions.md).

## 8. 개발 완료 시 검증 (`flight-route-advisor/result/`)

개발이 끝나면 **`result/`**(이 저장소 하위, `project/result/`와 다름)에 초기 설계 문서 대비 구현 대조 리뷰를 작성한다. 절차·템플릿은 [result/README.md](result/README.md).
- docs/03(API)·04(레이어)·05·07(작업/Stage)·02(DB 연동)의 기능/범위가 **모두 구현·일치**하는지, 리뷰에이전트(기능·논리·예외·보안)를 최종 통과했는지 확인.
- **불일치·미구현이 있으면 사용자에게 차이를 설명하고 처리 방법(문서 갱신 vs 코드 보완)을 질문**한다. 임의로 문서나 코드를 바꾸지 않는다.

## 9. 개발 중단 → 재개

1. **[docs/07-checklist.md](docs/07-checklist.md)** 의 체크 상태를 본다 = 진행 기준점.
2. 마지막 완료 Stage/항목의 관련 문서를 재확인한다.
3. **다음 미체크 항목부터** 이어서 진행한다.
4. (선택) 세부 진행 메모는 `result/PROGRESS.md`에 남긴다.

## 10. 체크리스트 외 추가 변경도 관련 문서에 동기화

[docs/07-checklist.md](docs/07-checklist.md)에 없던 항목이라도, **사용자의 추가 요청**이나 **리뷰 과정에서 드러난 문제점 개선**으로 발생한 기능 추가·수정은 작업과 동시에 관련 문서(§0 문서 지도 기준 `docs/00~10`, 필요시 `data-ingestion-backend/docs/`)를 갱신한다. 코드만 바꾸고 문서 갱신을 나중으로 미루지 않는다. 어느 문서가 관련 있는지 애매하면 사용자에게 질문한다.

## 11. 가이드 추가 규칙

새 개발 원칙이 필요하면 **이 파일에 추가**한다. 단, **기능 구현/명세는 여기 넣지 않고** `docs/`에 둔다. 이 파일은 "어떻게 일관되게 개발하는가"만 다룬다.
