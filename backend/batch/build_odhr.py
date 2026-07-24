"""processed_flight_data + processed_fois_* → 시간대별 교통량/소요시간 배치 집계
(docs/13-ai-reasoning-dev-plan.md STEP A2).

완성본 `사전빌드_JSON/odhr.json`을 만든 원본 계산 스크립트도 flow.json과 마찬가지로
이식 패키지 어디에도 없다. 이번엔 A1(`build_flow.py`)처럼 대체 스킬 코드도 찾지
못했다 — `SOURCE_PROJECT_ROOT`의 4개 전처리 스킬 스크립트 전체를 "정시율"/"on_time"/
"ODHR" 키워드로 검색해도 결과가 없다(2026-07-23 확인).

이 배치는 완성본 `od[dep|arr].hr[hour]`의 6원소 튜플(`[n, dly, txS, txN, teS, teN]`)
중 실측으로 **완전히 검증된** 3개 필드만 재현한다(golden VHHH|RKSI 24시간대 값과 전부
정확히 일치 확인):
- `n`(그 시간대 편수), `teS`/`teN`(그 시간대 TEET 합/유효건수 — 평균 소요시간 계산용).
`ap[icao]`(공항별 시간대 출발량)도 ATD 시간대 히스토그램으로 완전히 일치 검증됨.

⚠ **미구현(정직하게 명시)**: `dly`(지연편수, "이 시간대 정시율"의 근거)는 제외한다.
ACDM 도착/출발 정시성(여러 임계값)·FOIS 등재 여부(당일/익일)로 여러 차례 시도했지만
golden 수치와 전혀 맞지 않았고, 매칭 로직 자체도 어디에서도 찾지 못했다(build_flow.py의
`ponA`/`ponN`과 같은 종류의 갭이지만, 이번엔 대체 스킬조차 없어 근사치 시도도 보류했다
— 2026-07-23 사용자 확인). 소비 측(queries/odhr.py, 라우터)은 `on_time_pct`를 항상
`null`로 반환해야 한다.

`CAUSES`는 완성본과 달리 고정 사전이 아니라 `processed_fois_departure`/`processed_fois_arrival`의
`cause_major`(원인대분류) 실측 값을 그대로 집계한다 — DB 실제 값이 골든 목록 13종과
정확히 일치함을 확인(전수 대조, 2026-07-23).
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.session import get_engine
from app.queries.latest_run import latest_view


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


def _fetch_rows(table: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    stmt = latest_view(table)
    sub = stmt.subquery()
    cols = [sub.c[name] for name in columns]
    try:
        with get_engine().connect() as conn:
            return [dict(row) for row in conn.execute(select(*cols)).mappings()]
    except Exception as exc:
        raise RuntimeError(f"{table} 조회 실패: {exc}") from exc


def _build_ap_and_od(flight_rows: list[dict[str, Any]]) -> tuple[dict[str, list[int]], dict[str, dict[str, Any]]]:
    ap: dict[str, list[int]] = defaultdict(lambda: [0] * 24)
    od_n: dict[str, list[int]] = defaultdict(lambda: [0] * 24)
    od_te_sum: dict[str, list[int]] = defaultdict(lambda: [0] * 24)
    od_te_n: dict[str, list[int]] = defaultdict(lambda: [0] * 24)

    for row in flight_rows:
        dep = (row["dept"] or "").strip()
        dst = (row["dest"] or "").strip()
        dt = _parse_dt(row["atd"])
        if dt is None:
            continue
        if dep:
            ap[dep][dt.hour] += 1
        if not (dep and dst):
            continue
        od = f"{dep}|{dst}"
        od_n[od][dt.hour] += 1
        tm = _teet_minutes(row["teet"])
        if tm is not None:
            od_te_sum[od][dt.hour] += tm
            od_te_n[od][dt.hour] += 1

    od: dict[str, dict[str, Any]] = {}
    for key, n_hours in od_n.items():
        od[key] = {
            "n": n_hours,
            "teS": od_te_sum[key],
            "teN": od_te_n[key],
            # 미구현(모듈 docstring 참고) — 근사치를 지어내지 않고 항상 null.
            "onTimePct": [None] * 24,
        }
    return dict(ap), od


def _build_causes(fois_departure: list[dict[str, Any]], fois_arrival: list[dict[str, Any]]) -> list[str]:
    causes: set[str] = set()
    for row in fois_departure:
        v = (row["cause_major"] or "").strip()
        if v:
            causes.add(v)
    for row in fois_arrival:
        v = (row["cause_major"] or "").strip()
        if v:
            causes.add(v)
    return sorted(causes)


def _data_period(flight_rows: list[dict[str, Any]]) -> str | None:
    days = {r["date"][:10] for r in flight_rows if r.get("date")}
    if not days:
        return None
    return f"{min(days).replace('-', '')}-{max(days).replace('-', '')}"


def run(output_path: Path | None = None) -> dict:
    flight_rows = _fetch_rows("processed_flight_data", ("date", "dept", "dest", "atd", "teet"))
    fois_dep_rows = _fetch_rows("processed_fois_departure", ("cause_major",))
    fois_arr_rows = _fetch_rows("processed_fois_arrival", ("cause_major",))
    print(
        f"항공편 {len(flight_rows)}건, FOIS 출발 {len(fois_dep_rows)}건, FOIS 도착 {len(fois_arr_rows)}건 로드",
        file=sys.stderr,
    )

    ap, od = _build_ap_and_od(flight_rows)
    causes = _build_causes(fois_dep_rows, fois_arr_rows)
    print(f"build_odhr: 공항 {len(ap)} | OD {len(od)} | CAUSES {len(causes)}", file=sys.stderr)

    output_path = output_path or (
        Path(__file__).resolve().parent.parent / "app" / "reference" / "artifacts" / "odhr.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {"CAUSES": causes, "od": od, "ap": ap}
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(artifact, f, separators=(",", ":"), ensure_ascii=False)

    meta_path = output_path.with_name(output_path.stem + "_meta.json")
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump({"data_period": _data_period(flight_rows)}, f, ensure_ascii=False)

    print(f"odhr 저장: {output_path} ({output_path.stat().st_size / 1e3:.1f} KB)", file=sys.stderr)
    return artifact


if __name__ == "__main__":
    run()
