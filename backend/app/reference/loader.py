"""참조 데이터 bbox 필터 + 도형 가공 (docs/03-backend-api.md §3, docs/05 B5).

원천: `reference_*` DB 테이블(정적 JSON→DB 전환, `app/queries/reference.py`가 조회 담당).
이 모듈은 조회된 행을 문서화된 응답 키(§3 표)로 매핑하고 bbox 필터/도형 가공만 한다 —
행 자체는 `app/queries/reference.py`가 프로세스 생애주기 동안 메모리에 캐시하므로(예전
정적 JSON 캐시와 동일한 이유, §7 "월·분기 단위 갱신") 여기서는 별도로 캐시하지 않는다.
"""

from __future__ import annotations

import math

from app.queries import reference as reference_queries


def _parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    """bbox=minLat,minLon,maxLat,maxLon → (min_lat, min_lon, max_lat, max_lon). 형식 오류 시 ValueError."""
    if not bbox:
        return None
    parts = bbox.split(",")
    if len(parts) != 4:
        raise ValueError("bbox는 'minLat,minLon,maxLat,maxLon' 4개 값이어야 함")
    try:
        min_lat, min_lon, max_lat, max_lon = (float(p) for p in parts)
    except ValueError as exc:
        raise ValueError("bbox 값은 숫자여야 함") from exc
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise ValueError("bbox 위도는 -90~90 범위여야 함")
    if min_lat > max_lat:
        raise ValueError("bbox minLat은 maxLat보다 클 수 없음")
    if not (math.isfinite(min_lon) and math.isfinite(max_lon)):
        raise ValueError("bbox 경도는 유한한 값이어야 함(nan/inf 불가)")
    if min_lon > max_lon:
        # firs.json 등 참조 지오메트리는 날짜변경선 연속화를 위해 경도가 ±360까지
        # 이어져 있다(docs/08 "FR" 절, ±360 보정됨) — 그래서 여기서 경도를 -180~180로
        # 강제로 clamp하지 않는다(연속 좌표계로 -170~200처럼 180을 넘겨 querying하는
        # 것은 정상 사용). 다만 minLon>maxLon(뒤집힌 범위)은 어떤 좌표계에서도 항상
        # 사용자 오류이며, 걸러내는 폴리곤이 하나도 없어 조용히 빈 배열을 반환하던
        # 문제를 실측으로 발견했다(2026-07-22) — 명확히 에러로 알린다.
        raise ValueError("bbox minLon은 maxLon보다 클 수 없음(뒤집힌 범위) — 날짜변경선을 넘길 때는 연속 좌표계(예: 170~200)로 지정할 것")
    return (min_lat, min_lon, max_lat, max_lon)


def _point_in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    min_lat, min_lon, max_lat, max_lon = bbox
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def _flat_coords_bbox_overlaps(flat: list[float], bbox: tuple[float, float, float, float]) -> bool:
    """flat=[lat0,lon0,lat1,lon1,...] 폴리곤/폴리라인의 bbox가 조회 bbox와 겹치는지."""
    min_lat, min_lon, max_lat, max_lon = bbox
    lats = flat[0::2]
    lons = flat[1::2]
    if not lats:
        return False
    return not (
        max(lats) < min_lat
        or min(lats) > max_lat
        or max(lons) < min_lon
        or min(lons) > max_lon
    )


def _to_pairs(flat: list[float]) -> list[list[float]]:
    return [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]


def load_firs(bbox: str | None = None, icao: str | None = None) -> list[dict]:
    """FIR 폴리곤 + 라벨점 (docs/03 §3: FR + LBL). icao가 있으면 bbox 무시하고 그 목록만."""
    firs = reference_queries.fetch_firs()
    labels = {row[0]: (row[1], row[2]) for row in reference_queries.fetch_fir_labels()}

    if icao:
        wanted = {code.strip().upper() for code in icao.split(",") if code.strip()}
        rows = [row for row in firs if row[0] in wanted]
    else:
        parsed_bbox = _parse_bbox(bbox)
        rows = firs
        if parsed_bbox is not None:
            rows = [
                row
                for row in rows
                if any(_flat_coords_bbox_overlaps(poly, parsed_bbox) for poly in row[2])
            ]

    result = []
    for fir_icao, name_en, polygons in rows:
        label = labels.get(fir_icao)
        result.append(
            {
                "icao": fir_icao,
                "name_en": name_en,
                "polygons": [_to_pairs(poly) for poly in polygons],
                "label": {"lat": label[0], "lon": label[1]} if label else None,
            }
        )
    return result


def load_tca(bbox: str | None = None) -> list[dict]:
    """접근관제구역 (docs/03 §3: TCA + TCALBL)."""
    rows = reference_queries.fetch_tca()
    parsed_bbox = _parse_bbox(bbox)
    if parsed_bbox is not None:
        rows = [row for row in rows if _flat_coords_bbox_overlaps(row[2], parsed_bbox)]
    return [
        {"name": name, "name_ko": name_ko, "polygon": _to_pairs(flat)}
        for name, name_ko, flat in rows
    ]


def load_airways(bbox: str | None = None) -> list[dict]:
    """항공로 구간 (docs/03 §3: AW).

    bbox 필터는 세그먼트의 두 끝점이 **모두** bbox 안에 있을 때만 포함한다(2026-07-23
    수정). 예전에는 `_flat_coords_bbox_overlaps`(세그먼트 자신의 bbox가 조회 bbox와
    겹치기만 하면 포함)를 썼는데, 항로 구간은 웨이포인트 간격이 성긴 곳(대양 횡단 등)이
    있어 한쪽 끝만 조회 bbox 안에 있고 반대쪽 끝은 수천 km 밖인 세그먼트도 "겹침"으로
    잡혀 그대로 렌더링됐다 — 화면에 조회 영역 가장자리에서 화면 밖 먼 지점까지 이어지는
    긴 직선(사용자가 "이상하게 그려짐"으로 신고, 2026-07-23)으로 보이는 원인이었다.
    양끝점 모두 요구하면 그런 세그먼트는 빠지고(경계선을 살짝 스치는 짧은 세그먼트만
    누락되는 정도), 실제로 그 영역 안에서 끝나는 세그먼트만 남는다.
    """
    rows = reference_queries.fetch_airways_with_seq()
    parsed_bbox = _parse_bbox(bbox)
    if parsed_bbox is not None:
        rows = [
            row
            for row in rows
            if _point_in_bbox(row["a"][0], row["a"][1], parsed_bbox)
            and _point_in_bbox(row["b"][0], row["b"][1], parsed_bbox)
        ]
    return rows


_AIRPORT_CIVIL_PUBLIC_TYPES = ("A", "B")


def load_airports(
    bbox: str | None = None, type_filter: str | None = None, icao: str | None = None
) -> list[dict]:
    """공항 (docs/03 §3: AP). type_filter: A(민간)/B(민군 공용)/C(군용)/D(기타) 화이트리스트.
    icao가 있으면 bbox/type_filter 무시하고 그 목록만(load_firs와 동일 규약) — 특정 공항을
    타입 불문 단건 조회할 때 쓴다(예: 부트 시 A/B만 받은 목록에 없는 군용/기타 타입
    출도착 공항을 focus 모드에서 보강 조회, frontend/js/store.js selectOd 참고)."""
    rows = reference_queries.fetch_airports()
    if icao:
        wanted_icaos = {code.strip().upper() for code in icao.split(",") if code.strip()}
        rows = [row for row in rows if row["i"] in wanted_icaos]
    else:
        parsed_bbox = _parse_bbox(bbox)
        if parsed_bbox is not None:
            rows = [row for row in rows if _point_in_bbox(row["c"][0], row["c"][1], parsed_bbox)]
        if type_filter is not None:
            wanted_types = {t.strip().upper() for t in type_filter.split(",") if t.strip()}
            invalid = wanted_types - set(_AIRPORT_CIVIL_PUBLIC_TYPES + ("C", "D"))
            if invalid:
                raise ValueError(f"type 값이 올바르지 않음: {sorted(invalid)} (A/B/C/D만 허용)")
            rows = [row for row in rows if row["t"] in wanted_types]
    return [
        {
            "icao": row["i"],
            "name": row["n"],
            "lat": row["c"][0],
            "lon": row["c"][1],
            "elev_ft": row["e"],
            "type": row["t"],
        }
        for row in rows
    ]


def load_navaids(bbox: str | None = None) -> list[dict]:
    """항행시설 (docs/03 §3: NV)."""
    rows = reference_queries.fetch_navaids()
    parsed_bbox = _parse_bbox(bbox)
    if parsed_bbox is not None:
        rows = [row for row in rows if _point_in_bbox(row["c"][0], row["c"][1], parsed_bbox)]
    return [
        {
            "ident": row["i"],
            "name": row["n"],
            "type": row["t"],
            "lat": row["c"][0],
            "lon": row["c"][1],
            "freq": row["f"],
        }
        for row in rows
    ]


WAYPOINTS_LIMIT_MAX = 800


def load_waypoints(bbox: str | None = None, limit: int = WAYPOINTS_LIMIT_MAX) -> list[dict]:
    """항로 픽스 (docs/03 §3: WP). 상한 800(원본 문서/03 "픽스 z5+, 상한 800")."""
    if not (1 <= limit <= WAYPOINTS_LIMIT_MAX):
        raise ValueError(f"limit은 1~{WAYPOINTS_LIMIT_MAX} 범위여야 함")
    rows = reference_queries.fetch_waypoints()
    parsed_bbox = _parse_bbox(bbox)
    if parsed_bbox is not None:
        rows = [row for row in rows if _point_in_bbox(row[1], row[2], parsed_bbox)]
    rows = rows[:limit]
    return [
        {"ident": ident, "lat": lat, "lon": lon, "country": country}
        for ident, lat, lon, country in rows
    ]


def load_sidstar(airport: str | None = None) -> list[dict]:
    """SID/STAR 절차 (docs/03 §3: SS, 한국만 — Jeppesen 항행DB 이관, 2026-07-23).

    proc: 1=SID(파랑), 2=STAR(녹색). 좌표 조립(fix_id→[lat,lon] 해석)은
    `app/queries/reference.py`의 `fetch_sidstar`가 담당한다(터미널/엔루트 지점→navaid
    우선순위 조인, 승인된 계획 "핵심 설계 결정 3" 참고) — 이 함수는 그 결과를 그대로
    반환하는 얇은 래퍼다.
    """
    return reference_queries.fetch_sidstar(airport=airport)
