"""processed_flight_data → ODR2 배치 집계 (docs/02-db-integration.md §4).

원본 `PORTING_PACKAGE_ROOT/전처리스크립트/3_agg_csv.py`(OD 집계) +
`4_build_routes2.py`(병합·출발FIR 보정·FULL_ROUTE 3단계 좌표해석·인천 트랙 매칭·짝홀
배정)를 그대로 포팅했다. 원본은 정적 CSV(`원본데이터/비행자료_전처리_*.csv`)를
읽었지만, 이 배치는 같은 컬럼을 `processed_flight_data`의 "일자별 최신 run 우선"
현재본([queries/latest_run.py](../app/queries/latest_run.py))에서 읽는다(입력 컬럼
매핑: docs/02 §4.1). 원본 스크립트는 참고용으로만 두고 수정하지 않는다
(docs/CLAUDE.md §5 원본 무변경).

산출 스키마는 원본 `문서/08_임베드데이터_스키마.md` ODR2(§4.2)를 그대로 유지한다 —
`{"DEP|ARR": [총편수, [경로옵션, ...]]}`, 경로옵션 9필드
`[n, avgMin, delayCnt, heavyCnt, firs, pixes, track, frc, parity]`.
(참고: `사전빌드_JSON/odr2.json`에는 상층풍/ACDM 유래로 보이는 추가 필드가 더 있으나,
그건 04-E(상층풍) 등 2단계 기능 소관이라 이 배치의 범위가 아니다 — docs/05 §3.)

**터미널 신호 추가(A6, docs/13 STEP A6, 2026-07-24)**: `gate_in`/`gate_out`(경로그룹의 최빈
진출입 게이트, `processed_flight_data.entry_fir`/`exit_fir`에서 — 컬럼명과 달리 실측상 FIR
코드가 아니라 5자 픽스명, `advisor_odr2_route` 스칼라 컬럼 2개)·출발 활주로 분포(`processed_
acdm_departure.runway`를 callsign=flight_icao·date=operation_date·dep=airport_icao 3중 키로
조인 — 신규 조인, 리뷰에서 airport_icao 누락 시 편명 재사용에 값이 뒤섞일 수 있음이 지적돼
추가함, 실측 매칭률 99.9%. 리스트라 route_fir/route_fix와 동일하게 `advisor_odr2_route_runway`
자식 테이블로 — 완전 정규화 원칙). 원본
완성본은 이 셋을 OD 단위 `odInfo`(rec[2])에 뒀지만([14 §8 C-2](../../docs/14-improvement-request.md)
D20 확정에 따라) advisor는 **경로그룹 단위**로 노출한다 — 경로옵션마다 실제 진출입 게이트/
활주로 분포가 다를 수 있어 OD 전체로 뭉치면 정보 손실이 있기 때문(doc13 STEP A6 스펙이
이미 이 위치로 지정).

읽기 전용 원칙(docs/02 §4.3): 이 배치의 산출물은 전처리 DB(`processed_*`)에 쓰지 않는다.
대신 이 서비스 전용 신규 role `advisor_artifact_writer`(processed_*/raw_*/reference_*
접근 권한 없음, data-ingestion-backend alembic `d4f7a91c3e26_*`/`c3e7a1f6b0d4_*`)로만
`advisor_odr2_*` 7개 테이블에 truncate-and-reload 한다(파일 아티팩트 `odr2.json`은 폐지,
2026-07-23 사용자 요청으로 DB 통합). 조회 측(`app/queries/routes.py`)은 기존 읽기전용 role
(`advisor_readonly`)로 이 테이블을 SELECT한다.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from app.config import settings
from app.db import artifact_session
from app.db import column_map
from app.db.session import get_engine
from app.queries.latest_run import latest_view


def _proxy(table_name: str):
    """`column_map.ADVISOR_ODR2_COLUMNS`를 단일 출처로 삼는 경량 Core 프록시.

    컬럼명을 여기 다시 타이핑하면 alembic DDL(d4f7a91c3e26_*)이나 column_map이 바뀔 때
    조용히 어긋날 수 있다(리뷰 지적사항, 2026-07-23) — 조회 측(`db/tables.py`)이 이미
    이 화이트리스트로 리플렉션하듯, 쓰기 측도 같은 화이트리스트에서 컬럼명을 가져온다.
    """
    return sa.table(table_name, *(sa.column(c) for c in column_map.ADVISOR_ODR2_COLUMNS[table_name]))


# --- advisor_odr2_* 7종 (스키마 단일 출처는 data-ingestion-backend alembic
# d4f7a91c3e26_*/c3e7a1f6b0d4_*·column_map.ADVISOR_ODR2_COLUMNS) ---
_ODR2_OD = _proxy("advisor_odr2_od")
_ODR2_ROUTE = _proxy("advisor_odr2_route")
_ODR2_ROUTE_FIR = _proxy("advisor_odr2_route_fir")
_ODR2_ROUTE_FIX = _proxy("advisor_odr2_route_fix")
_ODR2_ROUTE_RUNWAY = _proxy("advisor_odr2_route_runway")
_ODR2_TRACK_POINT = _proxy("advisor_odr2_track_point")
_ODR2_FULL_ROUTE_POINT = _proxy("advisor_odr2_full_route_point")
_ODR2_TABLE_NAMES = (
    "advisor_odr2_full_route_point",
    "advisor_odr2_track_point",
    "advisor_odr2_route_runway",
    "advisor_odr2_route_fix",
    "advisor_odr2_route_fir",
    "advisor_odr2_route",
    "advisor_odr2_od",
)

# --- 외부 자산 경로 상수 (env 기반, docs/CLAUDE.md §0.1) ---
_REFERENCE_DIR = "사전빌드_JSON"
_DAFIF_BASE_DIR = "원본데이터/DAFIFT"

# --- 3_agg_csv.py 포팅 (컬럼명만 물리 컬럼으로 치환, docs/02 §4.1) ---

_HEAVY = re.compile(r"^(A33|A34|A35|A38|B74|B76|B77|B78|MD1|IL7|K35)")


def _parse_datetime(value: str | None) -> datetime | None:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _teet_minutes(value: str | None) -> int | None:
    m = re.match(r"^(\d{1,3}):(\d{2})", str(value or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def aggregate(
    rows: list[dict[str, Any]], runway_index: dict[tuple[str, str, str], str] | None = None
) -> tuple[dict, dict]:
    """processed_flight_data 행들 → (agg, votes). 3_agg_csv.py의 집계 로직 그대로.

    `runway_index`(선택, docs/13 STEP A6): (callsign, date, dep) → runway. 3_agg_csv.py에는
    없던 신규 집계(터미널 신호 이식) — 완성본 계산 스크립트가 이식 패키지 어디에도 없어
    (A1/A2와 동일한 갭) processed_flight_data.entry_fir/exit_fir(진출입 게이트, 실측상
    FIR 코드가 아니라 5자 픽스명 — 컬럼명은 오해의 소지가 있으나 물리 스키마 그대로)와
    processed_acdm_departure.runway(callsign=flight_icao·date=operation_date·dep=airport_icao
    3중 키 조인, `_fetch_acdm_departure_runways()` 참고 — 이 저장소에 기존 전례가 있는
    조인이 아니라 이번에 새로 검증한 조인)로 직접 계산했다."""
    agg: dict[tuple[str, str], dict[tuple[str, str], dict]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "n": 0, "tsum": 0, "tn": 0, "dly": 0, "hv": 0, "pO": 0, "pE": 0, "fr": defaultdict(int),
                "gi": defaultdict(int), "go": defaultdict(int), "rwy": defaultdict(int),
            }
        )
    )
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    runway_index = runway_index or {}

    total_rows = 0
    used = 0
    for r in rows:
        total_rows += 1
        dep = (r["dept"] or "").strip()
        dst = (r["dest"] or "").strip()
        if len(dep) != 4 or len(dst) != 4:
            continue
        firs = [t for t in (r["fir_enroute"] or "").split() if len(t) == 4]
        seq: list[str] = []
        for t in firs:
            if not seq or seq[-1] != t:
                seq.append(t)
        rt: list[str] = []
        for t in (r["ext_route"] or "").split():
            if not rt or rt[-1] != t:
                rt.append(t)
        if not seq and not rt:
            continue
        used += 1
        if seq:
            votes[dst][seq[-1]] += 1
        key = ("|".join(seq), "|".join(rt))
        e = agg[(dep, dst)][key]
        e["n"] += 1
        tm = _teet_minutes(r["teet"])
        if tm is not None:
            e["tsum"] += tm
            e["tn"] += 1
        eo = _parse_datetime(r["eobt"])
        at = _parse_datetime(r["atd"])
        if eo and at:
            d = (at - eo).total_seconds() / 60
            if 15 < d < 600:
                e["dly"] += 1
        if _HEAVY.match((r["a_type"] or "").strip()):
            e["hv"] += 1
        try:
            fl = int(float(str(r["rfl"]).strip())) // 100
            if fl >= 100:
                if (fl // 10) % 2 == 1:
                    e["pO"] += 1
                else:
                    e["pE"] += 1
        except (ValueError, TypeError):
            pass
        fr = (r["full_route"] or "").strip()
        if fr and len(fr) < 2000:
            e["fr"][fr] += 1
        gi = (r["entry_fir"] or "").strip()
        if gi:
            e["gi"][gi] += 1
        go = (r["exit_fir"] or "").strip()
        if go:
            e["go"][go] += 1
        rwy = runway_index.get(((r["callsign"] or "").strip(), (r["date"] or "")[:10], dep))
        if rwy:
            e["rwy"][rwy] += 1

    out: dict[str, dict] = {}
    for (dep, dst), groups in agg.items():
        o: dict[str, dict] = {}
        for k, v in groups.items():
            v = dict(v)
            frc = v.pop("fr")
            v["fr"] = max(frc.items(), key=lambda x: x[1])[0] if frc else ""
            # 진출입 게이트(최빈값, A6) — 동률이면 max()가 먼저 나온 키를 고르는데, dict
            # 삽입 순서(=처음 관측된 순서)를 그대로 따르므로 다른 최빈값 처리(fr)와 동일한
            # 결정성 특성을 가진다(재실행해도 같은 결과).
            gi_counts, go_counts, rwy_counts = v.pop("gi"), v.pop("go"), v.pop("rwy")
            v["gate_in"] = max(gi_counts.items(), key=lambda x: x[1])[0] if gi_counts else None
            v["gate_out"] = max(go_counts.items(), key=lambda x: x[1])[0] if go_counts else None
            rwy_total = sum(rwy_counts.values())
            v["runway_dist"] = (
                sorted(
                    ([rwy, round(100 * cnt / rwy_total)] for rwy, cnt in rwy_counts.items()),
                    key=lambda pair: -pair[1],
                )
                if rwy_total
                else []
            )
            o[k[0] + "§" + k[1]] = v
        out[f"{dep}|{dst}"] = o

    print(f"agg: 행 {total_rows} → 사용 {used} | OD {len(out)}", file=sys.stderr)
    return out, {k: dict(v) for k, v in votes.items()}


# --- 4_build_routes2.py 포팅 ---


def _load_dafif_lookups(porting_root: Path) -> tuple[dict[str, list[tuple[float, float]]], dict[str, tuple[float, float]]]:
    """WPT.TXT + NAV.TXT → ident별 후보 좌표 목록, ARPT.TXT → 공항 좌표. 원본 그대로 (경로 상수화, docs/CLAUDE.md §0.1)."""
    base = porting_root / _DAFIF_BASE_DIR
    # 필수 파일 존재 확인
    for subdir, filename in [("WPT", "WPT.TXT"), ("NAV", "NAV.TXT"), ("ARPT", "ARPT.TXT")]:
        file_path = base / subdir / filename
        if not file_path.exists():
            raise FileNotFoundError(
                f"DAFIF {filename} 누락: {file_path} "
                "(PORTING_PACKAGE_ROOT 경로 확인, docs/08-setup-and-dev-order.md §1)"
            )
    lookup: dict[str, list[tuple[float, float]]] = {}
    with (base / "WPT" / "WPT.TXT").open(encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            try:
                lookup.setdefault(row["WPT_IDENT"].strip(), []).append(
                    (float(row["WGS_DLAT"]), float(row["WGS_DLONG"]))
                )
            except (ValueError, TypeError):
                pass
    with (base / "NAV" / "NAV.TXT").open(encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            try:
                lookup.setdefault(row["NAV_IDENT"].strip(), []).append(
                    (float(row["WGS_DLAT"]), float(row["WGS_DLONG"]))
                )
            except (ValueError, TypeError):
                pass
    apc: dict[str, tuple[float, float]] = {}
    with (base / "ARPT" / "ARPT.TXT").open(encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            icao = row["ICAO"].strip()
            if not icao:
                continue
            try:
                apc[icao] = (float(row["WGS_DLAT"]), float(row["WGS_DLONG"]))
            except ValueError:
                pass
    return lookup, apc


def _dist2(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = a[0] - b[0]
    dlon = (a[1] - b[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    return dlat * dlat + dlon * dlon


_AWY_RE = re.compile(r"^[A-Z]{1,2}\d{1,4}[A-Z]?$")
_COORD_RE = re.compile(r"^(\d{2})(\d{2})?([NS])(\d{3})(\d{2})?([EW])$")


def _dist_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = a[0] - b[0]
    dlon = (a[1] - b[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dlat, dlon) * 60


def _resolve_full_route_coords(
    full_route: str,
    dep: str,
    dst: str,
    lookup: dict[str, list[tuple[float, float]]],
    apc: dict[str, tuple[float, float]],
) -> list[float]:
    """FULL_ROUTE 실궤적 3단계 좌표 해석 (docs/04-B, 4_build_routes2.py 그대로)."""
    items: list[tuple[str, Any]] = []
    for tok in full_route.split():
        tok = tok.split("/")[0].strip()
        if not tok or tok in ("DCT", "VFR", "IFR") or _AWY_RE.match(tok):
            continue
        m = _COORD_RE.match(tok)
        if m:
            lat = int(m.group(1)) + (int(m.group(2) or 0)) / 60
            if m.group(3) == "S":
                lat = -lat
            lon = int(m.group(4)) + (int(m.group(5) or 0)) / 60
            if m.group(6) == "W":
                lon = -lon
            items.append(("F", (lat, lon)))
        else:
            cands = lookup.get(tok)
            if cands:
                items.append(("C", cands))
    if not items:
        return []

    # 1차: 직전 지점 탐욕 매칭
    prev = apc.get(dep)
    chosen: list[tuple[float, float]] = []
    for kind, val in items:
        c = val if kind == "F" else (val[0] if prev is None else min(val, key=lambda x: _dist2(x, prev)))
        chosen.append(c)
        prev = c

    # 2차: 앞뒤 문맥 재선택 (×3회)
    arr_c = apc.get(dst)
    for _ in range(3):
        changed = False
        for i, (kind, val) in enumerate(items):
            if kind != "C" or len(val) < 2:
                continue
            pv = chosen[i - 1] if i > 0 else (apc.get(dep) or chosen[i])
            nx = chosen[i + 1] if i + 1 < len(chosen) else (arr_c or chosen[i])
            best = min(val, key=lambda x: _dist2(x, pv) + _dist2(x, nx))
            if best != chosen[i]:
                chosen[i] = best
                changed = True
        if not changed:
            break

    # 3차: 스파이크 제거 반복
    changed = True
    while changed and len(chosen) > 3:
        changed = False
        out = [chosen[0]]
        i = 1
        while i < len(chosen) - 1:
            a2, b2, c2 = out[-1], chosen[i], chosen[i + 1]
            legs = _dist_nm(a2, b2) + _dist_nm(b2, c2)
            direct = _dist_nm(a2, c2)
            if legs > 120 and legs > 2.2 * max(direct, 1.0):
                i += 1
                changed = True
                continue
            out.append(chosen[i])
            i += 1
        out.append(chosen[-1])
        chosen = out

    frc: list[float] = []
    for c in chosen:
        frc += [round(c[0], 3), round(c[1], 3)]
    return frc


def build_odr2(
    agg: dict[str, dict],
    votes: dict[str, dict],
    fir_set: set[str],
    lookup: dict[str, list[tuple[float, float]]],
    apc: dict[str, tuple[float, float]],
) -> dict:
    airport_fir = {ap: max(v.items(), key=lambda x: x[1])[0] for ap, v in votes.items()}

    def dep_fir(dep: str, first: str | None) -> str | None:
        lf = airport_fir.get(dep)
        if lf and (lf == first or first is None):
            return lf
        cand = [ic for ic in fir_set if ic.startswith(dep[:2])]
        if len(cand) == 1:
            return cand[0]
        return lf

    odr2: dict[str, list] = {}
    n_routes = 0
    for od, groups in agg.items():
        dep, dst = od.split("|")
        top = sorted(groups.items(), key=lambda x: -x[1]["n"])[:8]
        total = sum(e["n"] for e in groups.values())
        routes = []
        for k, e in top:
            seqs, rts = k.split("§")
            seq = [t for t in seqs.split("|") if t in fir_set] if seqs else []
            rt = rts.split("|") if rts else []
            df = dep_fir(dep, seq[0] if seq else None)
            if df and (not seq or seq[0] != df):
                seq = [df] + seq
            if len(seq) < 1:
                continue

            prev = apc.get(dep)
            track: list[float] = []
            oknames: list[str] = []
            for nm in rt:
                cands = lookup.get(nm)
                if not cands:
                    continue
                c = cands[0] if prev is None else min(cands, key=lambda x: _dist2(x, prev))
                track += [round(c[0], 3), round(c[1], 3)]
                oknames.append(nm)
                prev = c

            avg = round(e["tsum"] / e["tn"]) if e["tn"] else None
            frc = _resolve_full_route_coords(e.get("fr", ""), dep, dst, lookup, apc)
            if len(frc) < 6:
                frc = []
            par = "O" if e.get("pO", 0) > e.get("pE", 0) else ("E" if e.get("pE", 0) > e.get("pO", 0) else "")
            routes.append([
                e["n"], avg, e["dly"], e["hv"], seq, oknames, track, frc, par,
                e.get("gate_in"), e.get("gate_out"), e.get("runway_dist", []),
            ])
            n_routes += 1
        if routes:
            odr2[od] = [total, routes]

    print(f"build_odr2: 최종 OD {len(odr2)} | 경로 그룹 {n_routes}", file=sys.stderr)
    return odr2


# --- 엔드투엔드 실행 ---

_FLIGHT_DATA_COLUMNS = (
    "date", "dept", "dest", "fir_enroute", "ext_route", "teet", "eobt", "atd", "a_type", "rfl", "full_route",
    # 터미널 신호(A6) — 진출입 게이트 조인 키 불필요(같은 행에 이미 있음), 활주로 분포는
    # callsign+date로 processed_acdm_departure와 조인(아래 _fetch_acdm_departure_runways).
    "callsign", "entry_fir", "exit_fir",
)


def _fetch_acdm_departure_runways() -> dict[tuple[str, str, str], str]:
    """(callsign, date, dep) → 출발 활주로. processed_acdm_departure 최신본에서(docs/13 STEP A6).

    조인 키(callsign=flight_icao, date=operation_date, dep=airport_icao)로 processed_flight_data
    행과 매칭 — 실측 확인(2026-07-24): RKSI→RJBB 1,209편 중 1,208편이 매칭됨(runway 결측 1건
    제외 전부). **airport_icao(dep)를 키에 반드시 포함**해야 한다(리뷰 지적, 2026-07-24) —
    같은 편명이 같은 날 다른 공항에서 출발하는 경우(예: 회항 후 재출발, 코드셰어 재사용)
    airport_icao 없이는 서로 다른 두 항공편의 활주로가 조용히 뒤섞인다. `id` 순 정렬은
    `_fetch_flight_data_rows()`와 동일한 이유(동률 키 발생 시 재실행해도 항상 같은 값이
    이기도록 — 정렬 없이 dict 컴프리헨션만 쓰면 DB가 반환하는 행 순서에 따라 승자가
    실행마다 달라질 수 있다)."""
    stmt = latest_view("processed_acdm_departure")
    sub = stmt.subquery()
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                select(sub.c.flight_icao, sub.c.operation_date, sub.c.airport_icao, sub.c.runway, sub.c.id)
                .where(sub.c.runway.is_not(None))
                .order_by(sub.c.id)
            ).all()
    except Exception as exc:
        raise RuntimeError(f"processed_acdm_departure 조회 실패: {exc}") from exc
    index: dict[tuple[str, str, str], str] = {}
    for flight_icao, operation_date, airport_icao, runway, _id in rows:
        if flight_icao and airport_icao:
            index[(flight_icao, operation_date, airport_icao)] = runway
    return index


def _fetch_flight_data_rows() -> list[dict[str, Any]]:
    stmt = latest_view("processed_flight_data")
    sub = stmt.subquery()
    cols = [sub.c[name] for name in _FLIGHT_DATA_COLUMNS]
    # id(적재 순번) 기준 정렬 — 동률(같은 편수) 그룹의 대표/순위 결정이 원본 스크립트처럼
    # "원본 파일에 등장한 순서"를 따르도록 한다(원본은 csv.DictReader로 파일 순서대로 읽음).
    # 정렬을 안 하면 DB가 반환하는 순서가 매 실행마다 달라질 수 있어 동률 시 결과가
    # 비결정적이게 된다(실측으로 확인 — 동률 그룹 2건에서 순서가 뒤바뀜, 2026-07-22).
    try:
        with get_engine().connect() as conn:
            return [dict(row) for row in conn.execute(select(*cols).order_by(sub.c.id)).mappings()]
    except Exception as exc:
        raise RuntimeError(f"processed_flight_data 조회 실패: {exc}") from exc


def _data_period(rows: list[dict[str, Any]]) -> str | None:
    """이 배치가 실제로 집계한 날짜 범위 "YYYYMMDD-YYYYMMDD"(docs/03 §2 형식).

    processed_flight_data.date는 "YYYY-MM-DD HH:MM:SS" 타임스탬프 문자열이라 앞 10자만
    달력 날짜로 쓴다(column_map.TABLES_NEEDING_DAY_TRUNCATION과 동일 규칙). 응답 소비 측
    (routers/routes.py)이 어느 run_id 하나로 환원할 수 없는(§3.2 "일자별 최신 run 우선"
    윈도우라 날짜별로 승자 run이 다를 수 있음) 데이터의 실제 커버리지를 알 수 있게 한다.
    """
    days = {r["date"][:10] for r in rows if r.get("date")}
    if not days:
        return None
    return f"{min(days).replace('-', '')}-{max(days).replace('-', '')}"


def _persist(odr2: dict[str, list], data_period: str | None) -> None:
    """odr2 dict(§4.2 스키마 그대로)를 `advisor_odr2_*` 7종(A6가 추가한 route_runway 포함)에
    truncate-and-reload 한다.

    이 배치는 매번 `processed_flight_data` 전체를 다시 집계하는 전체 재계산이지
    증분(append)이 아니므로, 예전 파일 아티팩트를 통째로 덮어쓰던 것과 동일하게
    테이블도 통째로 비우고 다시 채운다(`reference_*` 정적 테이블과 동일한
    truncate-and-reload 패턴, docs/02-db-integration.md §2 각주). 하나의 트랜잭션으로
    묶어 조회 측(advisor_readonly)이 교체 중간의 반쪽 상태를 보는 일이 없게 한다.
    """
    generated_at = datetime.now(timezone.utc)
    od_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    fir_rows: list[dict[str, Any]] = []
    fix_rows: list[dict[str, Any]] = []
    runway_rows: list[dict[str, Any]] = []
    track_rows: list[dict[str, Any]] = []
    frc_rows: list[dict[str, Any]] = []

    for od, (total, routes) in odr2.items():
        dep, arr = od.split("|")
        od_rows.append({
            "dep": dep, "arr": arr, "total_flights": total,
            "data_period": data_period, "generated_at": generated_at,
        })
        for rank, route in enumerate(routes):
            n, avg_min, delay_count, heavy_count, firs, pixes, track, frc, parity, gate_in, gate_out, runway_dist = route
            route_rows.append({
                "dep": dep, "arr": arr, "rank": rank, "flights": n, "avg_min": avg_min,
                "delay_count": delay_count, "heavy_count": heavy_count, "cruise_parity": parity,
                "gate_in": gate_in, "gate_out": gate_out,
            })
            for seq, fir_icao in enumerate(firs):
                fir_rows.append({"dep": dep, "arr": arr, "rank": rank, "seq": seq, "fir_icao": fir_icao})
            for seq, fix_name in enumerate(pixes):
                fix_rows.append({"dep": dep, "arr": arr, "rank": rank, "seq": seq, "fix_name": fix_name})
            # 출발 활주로 분포(A6) — 리스트라 route_fir/route_fix와 동일하게 자식 테이블로
            # (완전 정규화 원칙, JSONB 블롭 대신).
            for seq, (runway, pct) in enumerate(runway_dist):
                runway_rows.append({"dep": dep, "arr": arr, "rank": rank, "seq": seq, "runway": runway, "pct": pct})
            for i in range(0, len(track), 2):
                track_rows.append({
                    "dep": dep, "arr": arr, "rank": rank, "seq": i // 2,
                    "lat": track[i], "lon": track[i + 1],
                })
            for i in range(0, len(frc), 2):
                frc_rows.append({
                    "dep": dep, "arr": arr, "rank": rank, "seq": i // 2,
                    "lat": frc[i], "lon": frc[i + 1],
                })

    engine = artifact_session.get_engine()
    with engine.begin() as conn:
        conn.execute(sa.text(f"TRUNCATE {', '.join(_ODR2_TABLE_NAMES)};"))
        if od_rows:
            conn.execute(sa.insert(_ODR2_OD), od_rows)
        if route_rows:
            conn.execute(sa.insert(_ODR2_ROUTE), route_rows)
        if fir_rows:
            conn.execute(sa.insert(_ODR2_ROUTE_FIR), fir_rows)
        if fix_rows:
            conn.execute(sa.insert(_ODR2_ROUTE_FIX), fix_rows)
        if runway_rows:
            conn.execute(sa.insert(_ODR2_ROUTE_RUNWAY), runway_rows)
        if track_rows:
            conn.execute(sa.insert(_ODR2_TRACK_POINT), track_rows)
        if frc_rows:
            conn.execute(sa.insert(_ODR2_FULL_ROUTE_POINT), frc_rows)


def run() -> dict:
    rows = _fetch_flight_data_rows()
    data_period = _data_period(rows)
    runway_index = _fetch_acdm_departure_runways()
    agg, votes = aggregate(rows, runway_index)

    # FIR 아티팩트 로드 (경로 상수화, 파일 검증 추가)
    try:
        firs_path = settings.porting_package_root / _REFERENCE_DIR / "firs.json"
        if not firs_path.exists():
            raise FileNotFoundError(
                f"FIR 아티팩트 누락: {firs_path} "
                "(PORTING_PACKAGE_ROOT/사전빌드_JSON 경로 확인, docs/08-setup-and-dev-order.md §1)"
            )
        with firs_path.open(encoding="utf-8") as f:
            fir_set = {row[0] for row in json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"FIR 데이터 로드 실패: {exc}") from exc

    lookup, apc = _load_dafif_lookups(settings.porting_package_root)
    odr2 = build_odr2(agg, votes, fir_set, lookup, apc)

    _persist(odr2, data_period)

    n_routes = sum(len(routes) for _total, routes in odr2.values())
    print(
        f"odr2 DB 적재: OD {len(odr2)}개 · 경로그룹 {n_routes}개, data_period={data_period}",
        file=sys.stderr,
    )
    return odr2


if __name__ == "__main__":
    run()
