"""processed_flow_management + processed_flight_data → OD·경로별 흐름관리 영향률
배치 집계 (docs/13-ai-reasoning-dev-plan.md STEP A1).

이 배치가 이식하는 것은 완성본 `사전빌드_JSON/flow.json`이 아니라(그 파일을 만든 원본
계산 스크립트는 이식 패키지 어디에도 없음 — 2026-07-23 확인), `SOURCE_PROJECT_ROOT`의
`skills/preprocess-flow-management/scripts/run_flow_management_preprocessing.py`
(Stage 0에서 이미 이식한 흐름관리 전처리 스킬) 안의 `integrate_flights()` 함수다.
이 함수는 "항공편 하나가 흐름관리 조치 하나에 영향받았는가"를 판정하는 원본 로직이며,
실측으로 완성본 flow.json의 알려진 3개 OD(VHHH|RKSI, RKSI|ZMCK, RKSI|VVNB) 전부에서
nAff/nTot/pct가 **정확히 일치**함을 확인했다(2026-07-23 검증). 판정 로직만 그대로
포팅하고(원본 무수정, docs/CLAUDE.md §5), OD·경로 단위 집계(이 배치의 신규 부분)는
그 판정 결과 위에 새로 얹는다.

⚠ **미구현 범위(정직하게 명시)**: 완성본 flow.json의 `ponA`/`ponN`(영향군·평시 정시율)·
`dlyA`/`dlyN`(평균지연)은 이 배치에 없다. ACDM 도착 정시성(`processed_acdm_arrival`)과
여러 방식으로 조인해봤지만 완성본 수치(예: VHHH|RKSI ponA=43·ponN=36·dlyA=22.2·dlyN=21.9)와
1.5~2배 차이가 나 신뢰할 수 있는 계산식을 확정하지 못했다(2026-07-23, 사용자 확인 후
보류 — 검증 안 된 근사치를 내보내는 대신 null로 둔다). od 딕셔너리에 키는 존재하되
값은 항상 null이며, 소비 측(queries/flow_reasoning.py, 프론트)은 이를 "미구현"으로
표시해야 한다.

산출물은 advisor 전용 신규 role `advisor_artifact_writer`(processed_*/raw_*/reference_*
접근 권한 없음, data-ingestion-backend alembic `d4f7a91c3e26_*`)로 `advisor_flow_*` 6개
테이블에 truncate-and-reload 한다(전처리 DB `processed_*`에는 여전히 쓰지 않는다 — 읽기전용
소비 원칙, docs/CLAUDE.md §5). 파일 아티팩트 `flow.json`은 폐지(2026-07-23 사용자 요청으로
DB 통합). 조회 측(`app/queries/flow_reasoning.py`)은 기존 읽기전용 role(`advisor_readonly`)로
이 테이블을 SELECT한다.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from app.db import artifact_session
from app.db.session import get_engine
from app.queries.latest_run import latest_view
from batch.build_odr2 import _load_dafif_lookups

# --- advisor_flow_* 6종 (경량 Core 프록시, 스키마 단일 출처는 data-ingestion-backend
# alembic d4f7a91c3e26_*·column_map.ADVISOR_FLOW_COLUMNS) ---
_FLOW_OD = sa.table(
    "advisor_flow_od",
    sa.column("dep"), sa.column("arr"), sa.column("impact_pct"), sa.column("affected_flights"),
    sa.column("total_flights"), sa.column("on_time_affected"), sa.column("on_time_normal"),
    sa.column("delay_affected_min"), sa.column("delay_normal_min"), sa.column("data_period"),
    sa.column("generated_at"),
)
_FLOW_OD_REASON = sa.table(
    "advisor_flow_od_reason",
    sa.column("dep"), sa.column("arr"), sa.column("seq"), sa.column("reason_code"), sa.column("pct"),
)
_FLOW_OD_LIMIT = sa.table(
    "advisor_flow_od_limit",
    sa.column("dep"), sa.column("arr"), sa.column("seq"), sa.column("limit_text"),
)
_FLOW_OD_MEASURE = sa.table(
    "advisor_flow_od_measure",
    sa.column("dep"), sa.column("arr"), sa.column("seq"), sa.column("measure_id"),
)
_FLOW_OD_HOUR = sa.table(
    "advisor_flow_od_hour",
    sa.column("dep"), sa.column("arr"), sa.column("hour"), sa.column("impact_pct"),
)
_FLOW_ROUTE_GROUP = sa.table(
    "advisor_flow_route_group",
    sa.column("dep"), sa.column("arr"), sa.column("route_key"), sa.column("pct"),
)
_FLOW_TABLE_NAMES = (
    "advisor_flow_route_group",
    "advisor_flow_od_hour",
    "advisor_flow_od_measure",
    "advisor_flow_od_limit",
    "advisor_flow_od_reason",
    "advisor_flow_od",
)

# --- OD당 표시 상한(하드코딩 아님 — 결과 목록 길이 상한, 값 자체는 데이터 아님) ---
_MAX_REASONS = 5
_MAX_LIMITS = 3
_MAX_MEASURE_IDS = 4
_MIN_GROUP_FLIGHTS = 5  # 경로그룹 pct 노출 최소 표본(너무 적은 표본의 %는 노이즈)

_FLOW_COLUMNS = (
    "flow_id", "apply_start_dt", "apply_end_dt", "target_airport", "target_fir",
    "target_route", "target_fix", "excluded_airport", "special_scope",
    "reason_code", "restriction_summary",
)
_FLIGHT_COLUMNS = (
    "callsign", "date", "dept", "dest", "atd", "eobt", "teet",
    "entry_fir", "entry_datetime", "exit_fir", "exit_datetime",
    "ext_route", "full_route", "fir_enroute",
)


def _parse_dt(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _teet_minutes(value: str | None) -> int | None:
    m = re.match(r"^(\d{1,3}):(\d{2})", str(value or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9]{1,7}")


def _token_set(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.upper()))


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).upper()


def _split_values(value: str | None) -> set[str]:
    return {v for v in _clean(value).split("|") if v}


def _fetch_rows(table: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    stmt = latest_view(table)
    sub = stmt.subquery()
    cols = [sub.c[name] for name in columns]
    try:
        with get_engine().connect() as conn:
            return [dict(row) for row in conn.execute(select(*cols)).mappings()]
    except Exception as exc:
        raise RuntimeError(f"{table} 조회 실패: {exc}") from exc


class _Flight:
    __slots__ = (
        "callsign", "dep", "dest", "atd", "start", "end", "entry_fir", "entry_dt",
        "exit_fir", "exit_dt", "route_tokens", "ext_route_dedup", "hour",
    )

    def __init__(self, row: dict[str, Any]) -> None:
        self.callsign = row["callsign"] or ""
        self.dep = (row["dept"] or "").strip()
        self.dest = (row["dest"] or "").strip()
        atd = _parse_dt(row["atd"])
        eobt = _parse_dt(row["eobt"])
        entry_dt = _parse_dt(row["entry_datetime"])
        exit_dt = _parse_dt(row["exit_datetime"])
        teet = _teet_minutes(row["teet"])
        self.atd = atd
        self.start = atd or eobt or entry_dt
        self.end = (atd + timedelta(minutes=teet)) if (atd and teet is not None) else (exit_dt or self.start)
        self.entry_fir = _clean(row["entry_fir"])
        self.entry_dt = entry_dt
        self.exit_fir = _clean(row["exit_fir"])
        self.exit_dt = exit_dt
        combined = " ".join(
            (row.get(k) or "") for k in ("ext_route", "full_route", "fir_enroute", "entry_fir", "exit_fir")
        )
        self.route_tokens = _token_set(combined)
        # ext_route 연속 중복 제거(원본 integrate_flights는 원본 텍스트 토큰화만 하고
        # 그룹핑은 하지 않지만, "g"(경로별) 집계는 build_odr2.aggregate()와 동일한
        # 경로 식별자가 필요하다 — ext_route의 연속 중복 제거 토큰열).
        dedup: list[str] = []
        for tok in (row["ext_route"] or "").split():
            if not dedup or dedup[-1] != tok:
                dedup.append(tok)
        self.ext_route_dedup = dedup
        self.hour = self.atd.hour if self.atd else None


def _match_affected(
    flights: list[_Flight], flow_rows: list[dict[str, Any]]
) -> tuple[list[bool], dict[int, list[dict[str, Any]]]]:
    """integrate_flights()(run_flow_management_preprocessing.py) 포팅.

    반환: (항공편별 영향여부, 항공편 인덱스 -> 매칭된 흐름관리 이벤트 상세 목록).
    """
    n = len(flights)
    inverted: dict[str, set[int]] = defaultdict(set)
    dep_index: dict[str, set[int]] = defaultdict(set)
    dest_index: dict[str, set[int]] = defaultdict(set)
    for i, f in enumerate(flights):
        for tok in f.route_tokens:
            inverted[tok].add(i)
        if f.dep:
            dep_index[f.dep].add(i)
        if f.dest:
            dest_index[f.dest].add(i)

    landing_rk = {i for i, f in enumerate(flights) if f.dest.startswith("RK")}
    landing_rj = {i for i, f in enumerate(flights) if f.dest.startswith("RJ")}

    affected = [False] * n
    matched_events: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for row in flow_rows:
        s = _parse_dt(row["apply_start_dt"])
        e = _parse_dt(row["apply_end_dt"])
        if s is None or e is None:
            continue
        airports = _split_values(row["target_airport"])
        firs = _split_values(row["target_fir"])
        airways = _split_values(row["target_route"])
        fixes = _split_values(row["target_fix"])
        exclusions = _split_values(row["excluded_airport"])
        special = _split_values(row["special_scope"])

        dims: list[set[int]] = []
        if airports:
            cand: set[int] = set()
            for v in airports:
                cand |= dep_index[v] | dest_index[v]
            dims.append(cand)
        if firs:
            cand = set()
            for v in firs:
                cand |= inverted[v]
            if "LANDING_RKRR" in special:
                cand &= landing_rk
            if "LANDING_RJJJ" in special:
                cand &= landing_rj
            dims.append(cand)
        if airways:
            cand = set()
            for v in airways:
                cand |= inverted[v]
            dims.append(cand)
        if fixes:
            cand = set()
            for v in fixes:
                cand |= inverted[v]
            dims.append(cand)
        if not dims:
            continue
        candidates = dims[0]
        for d in dims[1:]:
            candidates = candidates & d
        if exclusions:
            excl_idx: set[int] = set()
            for v in exclusions:
                excl_idx |= dep_index[v] | dest_index[v]
            candidates = candidates - excl_idx

        for i in candidates:
            f = flights[i]
            check_time = None
            if f.entry_fir in fixes and f.entry_dt:
                check_time = f.entry_dt
            elif f.exit_fir in fixes and f.exit_dt:
                check_time = f.exit_dt
            elif f.dest in airports and f.end:
                check_time = f.end
            elif f.dep in airports and f.start:
                check_time = f.start

            if check_time is not None:
                match = s <= check_time <= e
            else:
                match = f.start is not None and f.end is not None and f.start <= e and f.end >= s
            if match:
                affected[i] = True
                matched_events[i].append(row)

    return affected, matched_events


def _od_aggregate(
    flights: list[_Flight], affected: list[bool], matched_events: dict[int, list[dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    by_od: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(flights):
        if f.dep and f.dest:
            by_od[f"{f.dep}|{f.dest}"].append(i)

    od_out: dict[str, dict[str, Any]] = {}
    for od, idxs in by_od.items():
        n_tot = len(idxs)
        aff_idxs = [i for i in idxs if affected[i]]
        n_aff = len(aff_idxs)
        if n_aff == 0:
            # 영향 기록 없음 — 완성본 routeFlowBrief와 동일하게 "기록 부족"으로 처리
            # (od 딕셔너리에 아예 키를 만들지 않아, 소비측이 없음/영향없음을 구분).
            continue

        reason_counter: Counter[str] = Counter()
        limit_counter: Counter[str] = Counter()
        measure_flight_count: Counter[str] = Counter()
        for i in aff_idxs:
            seen_reasons_this_flight: set[str] = set()
            seen_limits_this_flight: set[str] = set()
            for ev in matched_events[i]:
                code = (ev["reason_code"] or "").strip() or "미기재"
                if code not in seen_reasons_this_flight:
                    reason_counter[code] += 1
                    seen_reasons_this_flight.add(code)
                summary = (ev["restriction_summary"] or "").strip()
                if summary and summary not in seen_limits_this_flight:
                    limit_counter[summary] += 1
                    seen_limits_this_flight.add(summary)
                measure_flight_count[ev["flow_id"]] += 1

        rs = [
            [code, round(100 * count / n_aff)]
            for code, count in reason_counter.most_common(_MAX_REASONS)
        ]
        lim = [text for text, _ in limit_counter.most_common(_MAX_LIMITS)]
        mid = [fid for fid, _ in measure_flight_count.most_common(_MAX_MEASURE_IDS)]

        hr_p: list[int] = []
        for h in range(24):
            hour_idxs = [i for i in idxs if flights[i].hour == h]
            if not hour_idxs:
                hr_p.append(-1)
                continue
            hour_aff = sum(1 for i in hour_idxs if affected[i])
            hr_p.append(round(100 * hour_aff / len(hour_idxs)))

        od_out[od] = {
            "nAff": n_aff,
            "nTot": n_tot,
            "pct": round(100 * n_aff / n_tot),
            # 미구현(2026-07-23, 배치 docstring 참고): ACDM 조인 여러 방식 시도 결과
            # 완성본 대비 1.5~2배 어긋나 검증되지 않은 채로 내보내지 않는다.
            "ponA": None,
            "ponN": None,
            "dlyA": None,
            "dlyN": None,
            "rs": rs,
            "lim": lim,
            "mid": mid,
            "hrP": hr_p,
        }
    return od_out


def _route_group_aggregate(
    flights: list[_Flight], affected: list[bool], lookup: dict[str, list[tuple[float, float]]]
) -> dict[str, int]:
    """FLOW.g[dep|arr|pixes] — build_odr2.aggregate()와 동일한 경로 식별자(ext_route
    연속중복제거 토큰 중 DAFIF에 존재하는 것만)에 대한 영향률(%)."""
    groups: dict[tuple[str, str, str], list[int, int]] = defaultdict(lambda: [0, 0])
    for i, f in enumerate(flights):
        if not (f.dep and f.dest and f.ext_route_dedup):
            continue
        oknames = [nm for nm in f.ext_route_dedup if nm in lookup]
        if not oknames:
            continue
        key = (f.dep, f.dest, " ".join(oknames))
        entry = groups[key]
        entry[0] += 1
        if affected[i]:
            entry[1] += 1

    g_out: dict[str, int] = {}
    for (dep, dest, pixes), (n, n_aff) in groups.items():
        if n < _MIN_GROUP_FLIGHTS:
            continue
        g_out[f"{dep}|{dest}|{pixes}"] = round(100 * n_aff / n)
    return g_out


def _data_period(flow_rows: list[dict[str, Any]]) -> str | None:
    days = {row["record_date"] for row in flow_rows if row.get("record_date")}
    if not days:
        return None
    return f"{min(days).replace('-', '')}-{max(days).replace('-', '')}"


def _persist(od: dict[str, dict], g: dict[str, int], data_period: str | None) -> None:
    """{"od":.., "g":..} 를 `advisor_flow_*` 6종에 truncate-and-reload 한다(build_odr2._persist와
    동일한 이유·패턴 — 매 실행이 전체 재계산이라 증분이 아니라 통째로 교체)."""
    generated_at = datetime.now(timezone.utc)
    od_rows: list[dict[str, Any]] = []
    reason_rows: list[dict[str, Any]] = []
    limit_rows: list[dict[str, Any]] = []
    measure_rows: list[dict[str, Any]] = []
    hour_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []

    for key, entry in od.items():
        dep, arr = key.split("|")
        od_rows.append({
            "dep": dep, "arr": arr, "impact_pct": entry["pct"],
            "affected_flights": entry["nAff"], "total_flights": entry["nTot"],
            "on_time_affected": entry["ponA"], "on_time_normal": entry["ponN"],
            "delay_affected_min": entry["dlyA"], "delay_normal_min": entry["dlyN"],
            "data_period": data_period, "generated_at": generated_at,
        })
        for seq, (code, pct) in enumerate(entry["rs"]):
            reason_rows.append({"dep": dep, "arr": arr, "seq": seq, "reason_code": code, "pct": pct})
        for seq, text in enumerate(entry["lim"]):
            limit_rows.append({"dep": dep, "arr": arr, "seq": seq, "limit_text": text})
        for seq, measure_id in enumerate(entry["mid"]):
            measure_rows.append({"dep": dep, "arr": arr, "seq": seq, "measure_id": measure_id})
        for hour, pct in enumerate(entry["hrP"]):
            hour_rows.append({
                "dep": dep, "arr": arr, "hour": hour,
                "impact_pct": None if pct == -1 else pct,
            })

    for key, pct in g.items():
        dep, arr, route_key = key.split("|", 2)
        group_rows.append({"dep": dep, "arr": arr, "route_key": route_key, "pct": pct})

    engine = artifact_session.get_engine()
    with engine.begin() as conn:
        conn.execute(sa.text(f"TRUNCATE {', '.join(_FLOW_TABLE_NAMES)};"))
        if od_rows:
            conn.execute(sa.insert(_FLOW_OD), od_rows)
        if reason_rows:
            conn.execute(sa.insert(_FLOW_OD_REASON), reason_rows)
        if limit_rows:
            conn.execute(sa.insert(_FLOW_OD_LIMIT), limit_rows)
        if measure_rows:
            conn.execute(sa.insert(_FLOW_OD_MEASURE), measure_rows)
        if hour_rows:
            conn.execute(sa.insert(_FLOW_OD_HOUR), hour_rows)
        if group_rows:
            conn.execute(sa.insert(_FLOW_ROUTE_GROUP), group_rows)


def run() -> dict:
    flow_rows = _fetch_rows(
        "processed_flow_management",
        _FLOW_COLUMNS + ("record_date",),
    )
    flight_rows = _fetch_rows("processed_flight_data", _FLIGHT_COLUMNS)
    flights = [_Flight(r) for r in flight_rows]
    print(f"흐름관리 {len(flow_rows)}건, 항공편 {len(flights)}건 로드", file=sys.stderr)

    affected, matched_events = _match_affected(flights, flow_rows)
    od = _od_aggregate(flights, affected, matched_events)

    from app.config import settings

    lookup, _apc = _load_dafif_lookups(settings.porting_package_root)
    g = _route_group_aggregate(flights, affected, lookup)

    n_aff_total = sum(1 for v in affected if v)
    print(
        f"build_flow: 영향편 {n_aff_total}/{len(flights)} | OD {len(od)} | 경로그룹 {len(g)}",
        file=sys.stderr,
    )

    data_period = _data_period(flow_rows)
    _persist(od, g, data_period)

    print(f"flow DB 적재 완료: OD {len(od)}개 · 경로그룹 {len(g)}개", file=sys.stderr)
    return {"od": od, "g": g}


if __name__ == "__main__":
    run()
