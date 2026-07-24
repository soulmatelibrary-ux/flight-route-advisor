"""참조 데이터 엔드포인트 (docs/03-backend-api.md §3). reference_* DB 조회, 장기 캐시."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy.exc import DBAPIError, OperationalError

from app.config import settings
from app.envelope import envelope
from app.reference import loader

router = APIRouter(prefix="/api/reference", tags=["reference"])

_CACHE_CONTROL = f"public, max-age={{ttl}}"

# ValueError(잘못된 bbox 등 클라이언트 입력 오류, 400)와 DB 연결 실패(503)를 구분한다
# (routers/fois.py·airport_ops.py와 동일한 관례).
_DB_ERRORS = (OperationalError, DBAPIError)


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
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-db")


@router.get("/tca")
def get_tca(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
):
    try:
        data = loader.load_tca(bbox=bbox)
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-db")


@router.get("/airways")
def get_airways(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    zoom: int | None = Query(default=None, ge=0, le=20),
):
    try:
        data = loader.load_airways(bbox=bbox)
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-db")


@router.get("/airports")
def get_airports(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    zoom: int | None = Query(default=None, ge=0, le=20),
    type: str | None = Query(
        default=None,
        description=(
            "A/B/C/D 콤마 목록. icao와 동시에 오면 icao가 우선이라 이 값은 쓰이지 않으므로 "
            "형식 검증도 icao가 없을 때만 적용된다(loader.load_airports, 아래 icao 무시 규약과 "
            "동일선상 — Query pattern으로 여기서 먼저 걸면 icao가 있어도 무조건 422가 나 "
            "'icao 있으면 type 무시' 규약이 깨진다, 2026-07-23 리뷰 발견)"
        ),
    ),
    icao: str | None = Query(default=None, description="콤마로 구분된 공항 ICAO 목록 (있으면 bbox/type 완전히 무시)"),
):
    try:
        data = loader.load_airports(bbox=bbox, type_filter=type, icao=icao)
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-db")


@router.get("/navaids")
def get_navaids(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    zoom: int | None = Query(default=None, ge=0, le=20),
):
    try:
        data = loader.load_navaids(bbox=bbox)
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-db")


@router.get("/waypoints")
def get_waypoints(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    zoom: int | None = Query(default=None, ge=0, le=20),
    limit: int = Query(default=loader.WAYPOINTS_LIMIT_MAX, ge=1, le=loader.WAYPOINTS_LIMIT_MAX),
):
    try:
        data = loader.load_waypoints(bbox=bbox, limit=limit)
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-db")


@router.get("/acc-sectors")
def get_acc_sectors(response: Response):
    try:
        data = loader.load_acc_sectors()
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    _set_long_cache(response)
    return envelope(data, source="reference-db")


@router.get("/sidstar")
def get_sidstar(
    response: Response,
    airport: str | None = Query(default=None, description="공항 ICAO(한국만 데이터 있음, docs/03 §3 SS)"),
):
    try:
        data = loader.load_sidstar(airport=airport)
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    _set_long_cache(response)
    return envelope(data, source="reference-db")


@router.get("/suas")
def get_suas(
    response: Response,
    bbox: str | None = Query(default=None, description="minLat,minLon,maxLat,maxLon"),
    region: str | None = Query(default=None, description="kr(한국)|world(세계), 생략 시 전체"),
):
    """SUAS/MOA 특수공역(docs/03 §3 신규, 2026-07-24). 발효시간(`eff_times_raw`/`schedule_status`/
    `schedule_segments`)은 `loader.load_suas()`가 STEP A7 배치(`advisor_suas_schedule`)와
    `ident` 조인으로 덧붙인다 — 그 배치가 아직 안 돌았으면 전부 `null`."""
    try:
        data = loader.load_suas(bbox=bbox, region=region)
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=503, detail="DB에 연결할 수 없음") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_long_cache(response)
    return envelope(data, source="reference-db")
