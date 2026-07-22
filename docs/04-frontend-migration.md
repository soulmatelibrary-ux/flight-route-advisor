# 04. 프론트엔드 전환 설계 (임베드 → 동적 fetch)

- 문서 버전: 1.1
- 작성일: 2026-07-21
- 대상: 지도 프론트를 구현할 개발자
- 관련 문서: [01-architecture](./01-architecture.md), [03-backend-api](./03-backend-api.md), [06-conventions](./06-conventions.md), [07-checklist](./07-checklist.md)
- 원본 근거: `비행경로추천서비스_이식패키지/문서/{03_지도앱_기능명세, 04_핵심알고리즘, 08_임베드데이터_스키마}.md`

이 문서는 기존 단일 HTML 지도 앱을 **데이터만 동적으로 바꾸는** 최소 침습 전환 설계다. 렌더링·상호작용 로직(04-A~G)은 **보존**하고, 데이터 공급 지점만 교체한다.

## 1. 전환 원칙

1. **로직 보존, 공급원만 교체.** 04-A 사전투영 캔버스 렌더링, 경로 기하, 기상 계산은 그대로 둔다. `const AW/AP/...`를 채우던 방식만 `fetch`로 바꾼다.
2. **어댑터 경계 신설.** API의 키 기반 JSON을 앱이 기대하는 형태로 변환하는 **어댑터 계층**을 하나 만들어, 앱 내부의 인덱스 의존 코드가 최소한으로만 남게 한다.
3. **하드코딩 최소화.** API 베이스 URL·기상 프록시 URL·타일 URL·줌 임계·표시 상한·색상 토큰 등 모든 상수는 **런타임 설정(config)** 으로 뺀다(§5).
4. **점진 전환.** 정적 임베드본을 정답지로 두고, 레이어 단위로 하나씩 fetch로 옮기며 시각 회귀를 비교한다.

## 2. 현재 → 목표 구조

**현재** (`전세계_항공로_지도.html` 단일 파일):
```
<head> CSS/폰트/Leaflet
<body> DOM
<script>
  const AW = [...];  const AP = [...];  ... const ODR2 = {...};  // 임베드 ~15MB
  // 파생 상수: AWC, SUTYPE, APNAME, APIDX, APBY, FIRB, firByIcao ...
  // 앱 로직 (렌더/상호작용) — route[4], a[5] 처럼 인덱스로 접근
</script>
```

**목표** (모듈 분리, 데이터는 런타임 로딩):
```
index.html          최소 DOM + config 주입 지점
/js
  config.js         런타임 설정(빌드시 주입 또는 /config.json fetch)
  api.js            fetch 래퍼 (baseURL, 캐시, 에러, 재시도)
  adapters.js       API 키기반 JSON ↔ 앱 내부 구조(08 배열) 변환
  store.js          로딩된 데이터 보관 + 파생 상수 재계산(APIDX/FIRB/firByIcao 등)
  render/*.js       04-A 사전투영 캔버스 등 기존 렌더 로직(보존)
  layers/*.js       레이어별 로딩·표시 규칙
  weather.js        기존 폴백 체인(직접→프록시) 보존
```
> 한 파일 유지가 필요하면 위 모듈을 `<script type="module">` 번들로 합쳐도 된다. 핵심은 **데이터 로딩과 어댑터를 분리**하는 것.

## 3. 로딩 전략

### 3.1 초기 부트 순서 (기본 모드 = 결정 포커스, [10](./10-ui-and-realtime.md) §2.1)

기본 화면은 전세계 참조 레이어를 부팅 시 전부 그리지 않는다. **결정 포커스 모드가 필요로 하는 최소 데이터만** 부팅 시 로드하고, 전세계 8종 벌크 프리페치는 사용자가 "전세계"(또는 "지역 컨텍스트") 모드로 전환할 때 온디맨드로 수행한다.

```
1) config 로드 (config.js 또는 GET /config.json)
2) 결정 포커스 최소 부트 (병렬):
     GET /api/routes/od-pairs   (ROUTE 패널 OD select 채움)
     GET /api/reference/airports?type=civil  (OD 지점 표시용 저배율만, 전량 아님)
3) 어댑터로 앱 내부 구조 생성 → store에 적재 → 파생 상수 재계산(APIDX 등 부팅 시점 가용분)
4) 04-A 사전투영 1회 수행 → 첫 렌더(빈 지도 + OD 선택 UI)
5) 사용자 상호작용 시 온디맨드:
     OD 선택 → GET /api/routes?dep=&arr= → 응답의 enroute_firs로
       GET /api/reference/firs?icao=<enroute_firs>, /api/reference/airways?bbox=<경로 bbox> 등
       경유 FIR·항공로만 조회 → 결정 포커스 맵 렌더(자동 fit-bounds, [10](./10-ui-and-realtime.md) §2.2)
     공항 클릭 → 기상(Node 프록시) + GET /api/airports/{icao}/ops(2단계)
6) 뷰모드 전환("지역 컨텍스트"/"전세계", F9) 시에만 전세계 벌크 프리페치 (병렬):
     GET /api/reference/firs, /airways, /airports, /navaids, /waypoints, /tca, /acc-sectors, /firko
     (전세계 모드는 완성본과 동일한 전 레이어 — 04-A 렌더 경로 그대로 재사용)
7) 필요 시 지연 로드: sidstar/suas(2단계)
```
> 전세계 벌크 프리페치(6번)는 한 번 로드되면 store에 캐시해 모드 재전환 시 재요청하지 않는다(장기 캐시 헤더, §3.2).

### 3.2 참조 지오메트리 성능 (구분 서빙 대응)
- 초기엔 **벌크 프리페치 + 클라이언트 사전투영**(현행 방식과 동일한 렌더 경로) 유지 → 시각 회귀 위험 최소.
- 응답에 장기 캐시 헤더가 있어 재방문 시 네트워크 비용 감소.
- bbox/zoom 필터 파라미터를 지원하되, MVP에서는 저배율 대량 레이어(항로/픽스)에만 우선 적용(원본 표시 상한: 픽스 800 등).
- 2단계 최적화(타일화)는 [05-mvp-scope](./05-mvp-scope.md) 참조. 프론트 렌더 재작성이 필요하므로 MVP 범위 아님.

## 4. 어댑터 — 인덱스 의존 제거

원본 앱은 `route[4]`, `a[5]`처럼 **배열 인덱스**로 데이터를 읽는다(08 문서 경고). API는 키 기반 JSON을 주므로, 어댑터가 둘을 잇는다.

### 4.1 방향
- **API(키) → 앱 내부(08 배열)**: 기존 렌더 로직을 최소 수정하려면, 어댑터가 API 응답을 08 배열 형태로 되돌려 넣는 방법이 가장 침습이 적다.
- 또는 렌더 로직을 키 접근으로 리팩터링(더 깨끗하나 작업량 큼). **MVP는 전자(배열 복원)** 권장.

> **실제 채택(2026-07-22, `frontend/js/adapters.js`)**: 완성본 HTML의 원본 렌더 소스 자체가 이 저장소에 없다(15MB, 열람·재사용 금지 대상이자 회귀 비교용 정답지, [docs/06 §7](./06-conventions.md)). "기존 코드를 최소 수정"할 대상이 없으므로 후자(키 접근 신규 작성)를 택했다 — 처음부터 새로 쓰는 렌더 코드에는 전자 채택 사유("작업량 큼")가 적용되지 않는다. 단, ODR2 경로옵션은 원본 인덱스 의미가 배치 집계·향후 2단계 이식과 직접 연결되므로 `adapters.js`가 `toOptArray()`로 08 배열 형태도 함께 제공해 규약을 보존한다.

### 4.2 예시 (airways)
```js
// API: {ident, seq, a:[lat,lon], b:[lat,lon], upper, lower}
// 앱 내부(AW): [ident, seqId, lat1, lon1, lat2, lon2, upper, lower]
export const toAW = (r) => [r.ident, r.seq, r.a[0], r.a[1], r.b[0], r.b[1], r.upper, r.lower];
```
### 4.3 파생 상수 재계산
로딩 후 store가 원본과 동일한 파생 상수를 만든다: `APIDX[ICAO]=[lat,lon]`, `APBY`, `APNAME`, `FIRB`(폴리곤 bbox), `firByIcao`, `SUTYPE`, 세계 SUAS 사전투영 캐시(`SUWCNT/SUWP/...`). 원본 `08` "파생 상수" 절과 동일하게.

### 4.4 ODR2 옵션
```js
// API options[i] → 앱 경로옵션 배열 [n,avg,delay,heavy,firs,fixes,track,frc,parity]
const toOpt = (o) => [o.flights,o.avg_min,o.delay_count,o.heavy_count,
  o.enroute_firs,o.incheon_track_fixes,
  flatten(o.track_coords), flatten(o.full_route_coords), o.cruise_parity];
```

## 5. 설정(config) — 하드코딩 최소화

앱 내 상수를 코드에 박지 않고 **config 객체 하나**로 모은다. 값은 배포 환경별로 주입(빌드 치환 또는 `GET /config.json`).

```js
// config.js (예시 — 값은 환경에서 주입)
export const CONFIG = {
  apiBaseUrl: window.__ENV__?.API_BASE_URL ?? "/api",
  weatherProxyUrl: window.__ENV__?.WEATHER_PROXY_URL ?? "http://localhost:3000/proxy",
  tileUrl: window.__ENV__?.TILE_URL,            // CARTO light_nolabels 등
  map: { center: [30,127], zoom: 3, minZoom: 2, maxBounds: [[-78,-400],[85,400]] },
  display: { waypointLimit: 800, labelZoom: { airway: 7, fix: 7, airportICAO: 8 } },
  tokens: { ink:"#22303c", inkSoft:"#7a8a99", paper:"#fbfbf9", orange:"#e8590c", blue:"#1d5fae" },
  externalApis: { /* 브라우저 직접 호출 대상 — URL은 여기서만 정의 */ }
};
```
- 지도 중심/줌/바운즈, 표시 상한·라벨 줌 임계, 디자인 토큰(원본 §5), 외부 API URL, 프록시 폴백 순서 → 전부 config.
- **금지**: 컴포넌트 곳곳에 `http://localhost:3000`, `800`, `#e8590c` 같은 리터럴을 직접 쓰는 것. 반드시 config 참조.
- 외부 API 목록·프록시 화이트리스트는 기상서버(`07`)의 화이트리스트와 **한 소스에서 일치**시킨다(불일치가 CORS 폴백 실패의 원인).

> **표시 정책(결정 중심, [10](./10-ui-and-realtime.md))**: 부트 순서(§3.1)가 이 정책의 구현이다 — 기본은 결정 포커스 최소 로드, 전세계 벌크는 모드 전환(F9) 시에만. 04-A 사전투영 렌더는 두 모드 공통 보존.

## 6. 레이어별 데이터 소스 매핑 (원본 03의 10개 레이어)

| # | 레이어 | 소스 | 로딩 시점 | 비고 |
|---|---|---|---|---|
| 1 | 전세계 FIR | `/api/reference/firs`(+firko) | 결정 포커스: OD 선택 시 `icao=enroute_firs`만 · 전세계 모드: 벌크 | ±360 복제, nonzero 채움 유지 |
| 2 | 접근관제구역 TCA | `/api/reference/tca` | 전세계/지역 컨텍스트 모드 전환 시 | 한국어 라벨 z7+ |
| 3 | 항공로 | `/api/reference/airways` | 결정 포커스: OD 선택 시 `bbox`(경로 범위)만 · 전세계 모드: 벌크 | 캔버스 단일색 배치 스트로크 |
| 4 | 항로 픽스 | `/api/reference/waypoints` | 전세계/지역 컨텍스트 모드 전환 시 | 상한 800(config) |
| 5 | 공항 | `/api/reference/airports` | 부팅 시 저배율 민간/공용만(OD select용) · 전세계 모드에서 전량 | 저배율 민간/공용만 |
| 6 | 항행시설 | `/api/reference/navaids` | 전세계/지역 컨텍스트 모드 전환 시 | 삼각형 마커 |
| 7 | SID/STAR(한국) | `/api/reference/sidstar` | 지연/2단계 | |
| 8 | SUAS 한국/세계 | `/api/reference/suas` | 지연/2단계 | 세계는 사전투영 캐시 |
| 9 | 실시간 항공기(ADS-B) | 외부 API 직접 | 12초 폴링 | Node 프록시 폴백 |
| 10 | 기상 레이더 | RainViewer 외부 | 사용자 재생 | maxNativeZoom 6 |
| — | ROUTE 경로추천 | `/api/routes*` (DB 집계) | OD 선택 시 | ODR2 어댑터 |
| — | 공항 기상 팝업 | Node 기상서버(METAR/TAF) | 공항 클릭 | `07` 계약 |
| — | 공항 운항 KPI | `/api/airports/{icao}/ops` | 공항 클릭(2단계) | ACDM |

## 7. 보존해야 할 알고리즘 (재작성 금지 — 원본 04 그대로)
- **04-A** 사전투영(projX/projY)·rAF 스로틀·zoomanim transform·색상별 배치 스트로크
- **04-B/C** FULL_ROUTE 3단계 좌표해석·인천 FIR 트랙 splice → **배치(백엔드)로 이동**, 프론트는 좌표 받기만
- **04-D** buildGeo(FIR 경유 기하) → 2단계
- **04-E** 상층풍/시어(Open-Meteo) → 2단계, 외부 API 직접
- **04-F** FIR 면 nonzero 채움
- **04-G** TAF 타임라인·ACC 관제량·FIR 기상 심각도

## 8. 회귀 검증
- **전세계 모드**에서 정적 완성본 HTML을 정답지로, 레이어별 도형/마커 개수와 위치를 비교(기대 건수: FIR 247·항공로 89,555·픽스 58,812·공항 10,030·OD 1,487·경로 3,083, [06 §7](./06-conventions.md)). 결정 포커스 모드는 별도로 "선택 OD의 enroute_firs 개수만큼만 FIR 렌더" 여부를 검증.
- `node --check` 문법 검증 + DOM/Leaflet 스텁 하네스로 클릭 흐름(그려진 폴리라인/마커 수) 시뮬레이션(원본 07 검증 원칙 계승).
