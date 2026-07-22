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

읽기 전용 원칙(docs/02 §4.3): 이 배치의 산출물은 전처리 DB에 쓰지 않고 이 서비스
소유의 파일 아티팩트(`app/reference/artifacts/odr2.json`)로 둔다.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.db.session import get_engine
from app.queries.latest_run import latest_view

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


def aggregate(rows: list[dict[str, Any]]) -> tuple[dict, dict]:
    """processed_flight_data 행들 → (agg, votes). 3_agg_csv.py의 집계 로직 그대로."""
    agg: dict[tuple[str, str], dict[tuple[str, str], dict]] = defaultdict(
        lambda: defaultdict(
            lambda: {"n": 0, "tsum": 0, "tn": 0, "dly": 0, "hv": 0, "pO": 0, "pE": 0, "fr": defaultdict(int)}
        )
    )
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

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

    out: dict[str, dict] = {}
    for (dep, dst), groups in agg.items():
        o: dict[str, dict] = {}
        for k, v in groups.items():
            v = dict(v)
            frc = v.pop("fr")
            v["fr"] = max(frc.items(), key=lambda x: x[1])[0] if frc else ""
            o[k[0] + "§" + k[1]] = v
        out[f"{dep}|{dst}"] = o

    print(f"agg: 행 {total_rows} → 사용 {used} | OD {len(out)}", file=sys.stderr)
    return out, {k: dict(v) for k, v in votes.items()}


# --- 4_build_routes2.py 포팅 ---


def _load_dafif_lookups(porting_root: Path) -> tuple[dict[str, list[tuple[float, float]]], dict[str, tuple[float, float]]]:
    """WPT.TXT + NAV.TXT → ident별 후보 좌표 목록, ARPT.TXT → 공항 좌표. 원본 그대로."""
    base = porting_root / "원본데이터" / "DAFIFT"
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
            routes.append([e["n"], avg, e["dly"], e["hv"], seq, oknames, track, frc, par])
            n_routes += 1
        if routes:
            odr2[od] = [total, routes]

    print(f"build_odr2: 최종 OD {len(odr2)} | 경로 그룹 {n_routes}", file=sys.stderr)
    return odr2


# --- 엔드투엔드 실행 ---

_FLIGHT_DATA_COLUMNS = (
    "date", "dept", "dest", "fir_enroute", "ext_route", "teet", "eobt", "atd", "a_type", "rfl", "full_route",
)


def _fetch_flight_data_rows() -> list[dict[str, Any]]:
    stmt = latest_view("processed_flight_data")
    sub = stmt.subquery()
    cols = [sub.c[name] for name in _FLIGHT_DATA_COLUMNS]
    # id(적재 순번) 기준 정렬 — 동률(같은 편수) 그룹의 대표/순위 결정이 원본 스크립트처럼
    # "원본 파일에 등장한 순서"를 따르도록 한다(원본은 csv.DictReader로 파일 순서대로 읽음).
    # 정렬을 안 하면 DB가 반환하는 순서가 매 실행마다 달라질 수 있어 동률 시 결과가
    # 비결정적이게 된다(실측으로 확인 — 동률 그룹 2건에서 순서가 뒤바뀜, 2026-07-22).
    with get_engine().connect() as conn:
        return [dict(row) for row in conn.execute(select(*cols).order_by(sub.c.id)).mappings()]


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


def run(output_path: Path | None = None) -> dict:
    rows = _fetch_flight_data_rows()
    data_period = _data_period(rows)
    agg, votes = aggregate(rows)

    firs_path = settings.porting_package_root / "사전빌드_JSON" / "firs.json"
    with firs_path.open(encoding="utf-8") as f:
        fir_set = {row[0] for row in json.load(f)}

    lookup, apc = _load_dafif_lookups(settings.porting_package_root)
    odr2 = build_odr2(agg, votes, fir_set, lookup, apc)

    output_path = output_path or (Path(__file__).resolve().parent.parent / "app" / "reference" / "artifacts" / "odr2.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(odr2, f, separators=(",", ":"), ensure_ascii=False)

    # odr2.json 자체는 원본 파이프라인과 필드 단위로 정확히 일치해야 하는 산출물이라
    # ({"DEP|ARR": [total, routes]} 그대로, phase8/ODR2 기준선 대조 대상) 메타데이터를
    # 그 안에 섞지 않고 별도 사이드카 파일로 둔다(docs/03 §2 run_id/data_period 계약).
    meta_path = output_path.with_name(output_path.stem + "_meta.json")
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump({"data_period": data_period}, f, ensure_ascii=False)

    print(
        f"odr2 저장: {output_path} ({output_path.stat().st_size / 1e6:.2f} MB), "
        f"data_period={data_period}",
        file=sys.stderr,
    )
    return odr2


if __name__ == "__main__":
    run()
