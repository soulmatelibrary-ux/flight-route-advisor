# ⚠ 미러(사본) 고지

이 폴더(`flight-route-advisor/data-ingestion-backend/`)는 **전처리 적재 백엔드 문서의 사본**이다.
경로추천 서비스(advisor)와 데이터 적재(ingestion)를 한곳에서 함께 개발·참조하기 위해 복사해 두었다.

- **진실원(source of truth)**: `데이터전처리기술이식/data-ingestion-backend/docs/`
- **복사 시점**: 2026-07-21 (원본 문서 완료 시점 기준)
- **복사 범위**: `docs/` 6개 문서 (README·작업계획서·스킬연동_레퍼런스·DB스키마·기술스택_결정·체크리스트)

## 규칙

1. **`docs/`(이 폴더 하위)는 읽기 참조용 사본**이다. 여기서 수정하지 말 것 — 문서 수정은 진실원에서 하고, 갱신 시 **재복사**로 동기화한다. (예: `cp <진실원>/docs/*.md flight-route-advisor/data-ingestion-backend/docs/`)
2. **Stage 0 코드는 이 저장소에서 새로 개발**한다(사용자 결정). 위치: `flight-route-advisor/data-ingestion-backend/`(현재 `docs/`만 있음 → `app/`·`docker/` 등 신규 생성). 상세 구조는 미러 `docs/작업계획서.md` §8을 이 저장소 관점으로 따른다.
3. 이 백엔드가 쓰는 **스킬·원본데이터는 외부**(진실원 프로젝트)에 있으므로 **상대경로가 아니라 env 루트 `SOURCE_PROJECT_ROOT`로 참조**한다(하드코딩 금지). 그 외부 자산은 **읽기 전용**([../docs/08-setup-and-dev-order.md](../docs/08-setup-and-dev-order.md) §1). 즉 "코드를 옮기지 말라"가 아니라 "외부 스킬/데이터를 복사·수정하지 말고 env로 참조하라"가 규칙이다.

## 미러 범위 정리 (혼동 방지)

- **문서(`docs/`)** = 미러(읽기 전용). 진실원 = `<SOURCE_PROJECT_ROOT>/data-ingestion-backend/docs`.
- **코드(`app/`·`docker/` 등)** = 이 저장소에서 신규 개발(Stage 0). 진실원 아님.
- **스킬·원본데이터** = 외부, `SOURCE_PROJECT_ROOT` env로 참조, 읽기 전용.
- Stage 1·2(advisor)는 Stage 0가 로컬 pgsql에 적재한 `processed_*`를 읽기 전용 소비([../docs/02-db-integration.md](../docs/02-db-integration.md)).
