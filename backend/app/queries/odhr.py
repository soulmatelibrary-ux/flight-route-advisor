"""시간대별 교통량/소요시간 아티팩트 서빙 (docs/13-ai-reasoning-dev-plan.md STEP A2).
`batch/build_odhr.py` 산출물을 읽기만 한다(요청마다 재계산하지 않음, docs/02 §4.3과 동일 원칙).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "reference" / "artifacts" / "odhr.json"
_META_PATH = _ARTIFACT_PATH.with_name(_ARTIFACT_PATH.stem + "_meta.json")

_cache: dict[str, Any] | None = None
_meta_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cache
    if _cache is None:
        if not _ARTIFACT_PATH.exists():
            raise FileNotFoundError(f"{_ARTIFACT_PATH} 없음 — 먼저 `python -m batch.build_odhr` 실행 필요")
        with _ARTIFACT_PATH.open(encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def _load_meta() -> dict[str, Any]:
    global _meta_cache
    if _meta_cache is None:
        if _META_PATH.exists():
            with _META_PATH.open(encoding="utf-8") as f:
                _meta_cache = json.load(f)
        else:
            _meta_cache = {}
    return _meta_cache


def data_period() -> str | None:
    return _load_meta().get("data_period")


def reset_cache() -> None:
    global _cache, _meta_cache
    _cache = None
    _meta_cache = None


def _avg(total: int, count: int) -> float | None:
    return round(total / count, 1) if count else None


def delay_history_for(dep: str, arr: str, hour: int | None) -> dict[str, Any]:
    """OD 시간대별 교통량 + 평균 소요시간. `on_time_pct`는 항상 null(모듈 docstring 참고 —
    검증된 계산식이 없어 근사치를 지어내지 않는다). `hour` 지정 시 완성본과 동일한
    ±1시간 윈도우(`[hour-1, hour, hour+1]`)로 그 구간만 요약한 `window`를 덧붙인다.
    """
    artifact = _load()
    causes = artifact.get("CAUSES", [])
    entry = artifact.get("od", {}).get(f"{dep}|{arr}")
    if entry is None:
        return {"dep": dep, "arr": arr, "found": False, "causes": causes}

    n_hours = entry["n"]
    te_sum_hours = entry["teS"]
    te_n_hours = entry["teN"]
    hourly_avg_teet_min = [_avg(te_sum_hours[h], te_n_hours[h]) for h in range(24)]
    baseline_avg_teet_min = _avg(sum(te_sum_hours), sum(te_n_hours))

    result: dict[str, Any] = {
        "dep": dep,
        "arr": arr,
        "found": True,
        "hourly_flights": n_hours,
        "hourly_avg_teet_min": hourly_avg_teet_min,
        "on_time_pct": None,
        "window": None,
        "causes": causes,
    }
    if hour is not None:
        window_hours = [(hour - 1) % 24, hour, (hour + 1) % 24]
        window_flights = sum(n_hours[h] for h in window_hours)
        window_te_sum = sum(te_sum_hours[h] for h in window_hours)
        window_te_n = sum(te_n_hours[h] for h in window_hours)
        window_avg_teet_min = _avg(window_te_sum, window_te_n)
        delta_vs_baseline_min = (
            round(window_avg_teet_min - baseline_avg_teet_min, 1)
            if window_avg_teet_min is not None and baseline_avg_teet_min is not None
            else None
        )
        result["window"] = {
            "hour": hour,
            "flights": window_flights,
            "avg_teet_min": window_avg_teet_min,
            "delta_vs_baseline_min": delta_vs_baseline_min,
        }
    return result
