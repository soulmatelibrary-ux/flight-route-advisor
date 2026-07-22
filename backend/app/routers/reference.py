"""참조 데이터 엔드포인트 (docs/03-backend-api.md §3). 정적 아티팩트, DB 미경유, 장기 캐시."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Response

from app.config import settings
from app.envelope import envelope
from app.reference import loader

router = APIRouter(prefix="/api/reference", tags=["reference"])

_CACHE_CONTROL = f"public, max-age={{ttl}}"

# json.JSONDecodeError는 ValueError의 서브클래스라 순서상 먼저 잡아야 한다 — 잘못된
# bbox 같은 클라이언트 입력 오류(400)와, 사전빌드 자산 손상/누락 같은 서버측 문제(503)를
# 구분해야 하기 때문(실측으로 두 경우가 뒤섞여 있던 것을 발견, 2026-07-22).
_ASSET_ERRORS = (FileNotFoundError, OSError, json.JSONDecodeError)


def _set_long_cache(response: Response) -> None:
    response.headers["Cache-Control"] = _CACHE_CONTROL.format(
        ttl=settings.reference_cache_ttl_seconds
    )


@router.get("/firs")
def get_firs(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    icao: str | None = Query(default=None, description="콤마로 구분된 FIR ICAO 목록"),
):
    try:
        data = loader.load_firs(bbox=bbox, icao=icao)
    except _ASSET_ERRORS as exc:
        raise HTTPException(status_code=503, detail="참조 데이터 자산을 불러올 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-static")


@router.get("/tca")
def get_tca(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
):
    try:
        data = loader.load_tca(bbox=bbox)
    except _ASSET_ERRORS as exc:
        raise HTTPException(status_code=503, detail="참조 데이터 자산을 불러올 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-static")


@router.get("/airways")
def get_airways(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    zoom: int | None = Query(default=None, ge=0, le=20),
):
    try:
        data = loader.load_airways(bbox=bbox)
    except _ASSET_ERRORS as exc:
        raise HTTPException(status_code=503, detail="참조 데이터 자산을 불러올 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-static")


@router.get("/airports")
def get_airports(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    zoom: int | None = Query(default=None, ge=0, le=20),
    type: str | None = Query(
        default=None,
        pattern=r"^[A-D](,[A-D])*$",
        description="A/B/C/D 콤마 목록 (라우터 레벨 검증, docs/06-conventions.md §8)",
    ),
):
    try:
        data = loader.load_airports(bbox=bbox, type_filter=type)
    except _ASSET_ERRORS as exc:
        raise HTTPException(status_code=503, detail="참조 데이터 자산을 불러올 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-static")


@router.get("/navaids")
def get_navaids(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    zoom: int | None = Query(default=None, ge=0, le=20),
):
    try:
        data = loader.load_navaids(bbox=bbox)
    except _ASSET_ERRORS as exc:
        raise HTTPException(status_code=503, detail="참조 데이터 자산을 불러올 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-static")


@router.get("/waypoints")
def get_waypoints(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    zoom: int | None = Query(default=None, ge=0, le=20),
    limit: int = Query(default=loader.WAYPOINTS_LIMIT_MAX, ge=1, le=loader.WAYPOINTS_LIMIT_MAX),
):
    try:
        data = loader.load_waypoints(bbox=bbox, limit=limit)
    except _ASSET_ERRORS as exc:
        raise HTTPException(status_code=503, detail="참조 데이터 자산을 불러올 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-static")
