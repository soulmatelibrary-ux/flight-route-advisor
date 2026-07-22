"""ODR2 아티팩트 서빙 (docs/03-backend-api.md §4.1). `batch/build_odr2.py` 산출물을
읽기만 한다 — 요청마다 재계산하지 않는다(docs/02 §4.3).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "reference" / "artifacts" / "odr2.json"
_META_PATH = _ARTIFACT_PATH.with_name(_ARTIFACT_PATH.stem + "_meta.json")

_cache: dict[str, Any] | None = None
_meta_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cache
    if _cache is None:
        if not _ARTIFACT_PATH.exists():
            raise FileNotFoundError(
                f"{_ARTIFACT_PATH} 없음 — 먼저 `python -m batch.build_odr2` 실행 필요"
            )
        with _ARTIFACT_PATH.open(encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def _load_meta() -> dict[str, Any]:
    """odr2_meta.json(batch/build_odr2.py._data_period 산출) — 없으면 빈 dict(구버전
    아티팩트 호환, data_period는 그냥 null로 응답)."""
    global _meta_cache
    if _meta_cache is None:
        if _META_PATH.exists():
            with _META_PATH.open(encoding="utf-8") as f:
                _meta_cache = json.load(f)
        else:
            _meta_cache = {}
    return _meta_cache


def data_period() -> str | None:
    """이 ODR2 아티팩트가 실제로 집계한 날짜 범위(docs/03 §2 data_period). run_id는
    "일자별 최신 run 우선" 윈도우 특성상 날짜별로 승자 run이 다를 수 있어 단일 값으로
    환원할 수 없으므로 null로 둔다(참조 데이터와 동일하게 처리, docs/03 §2)."""
    return _load_meta().get("data_period")


def reset_cache() -> None:
    """새 아티팩트가 생성된 뒤(재배치) 다음 요청에 다시 읽게 한다."""
    global _cache, _meta_cache
    _cache = None
    _meta_cache = None


def _to_pairs(flat: list[float]) -> list[list[float]]:
    return [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]


def _shape_option(route: list) -> dict[str, Any]:
    n, avg_min, delay_count, heavy_count, firs, pixes, track, frc, parity = route
    return {
        "flights": n,
        "avg_min": avg_min,
        "delay_count": delay_count,
        "heavy_count": heavy_count,
        "enroute_firs": firs,
        "incheon_track_fixes": pixes,
        "track_coords": _to_pairs(track),
        "full_route_coords": _to_pairs(frc),
        "cruise_parity": parity,
    }


def od_pairs() -> list[dict[str, Any]]:
    """출발/도착 OD 쌍 목록, 편수순(docs §4.1 od-pairs)."""
    odr2 = _load()
    rows = []
    for od, (total, _routes) in odr2.items():
        dep, arr = od.split("|")
        rows.append({"dep": dep, "arr": arr, "total_flights": total})
    rows.sort(key=lambda r: -r["total_flights"])
    return rows


def routes_for(dep: str, arr: str) -> dict[str, Any] | None:
    """특정 OD의 경로옵션 목록(docs §4.1 응답 예시 형태). 없으면 None."""
    odr2 = _load()
    entry = odr2.get(f"{dep}|{arr}")
    if entry is None:
        return None
    total, routes = entry
    return {
        "dep": dep,
        "arr": arr,
        "total_flights": total,
        "options": [_shape_option(r) for r in routes],
    }
