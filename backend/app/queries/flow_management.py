"""흐름관리 조치 목록 조회 (docs/03-backend-api.md §4.4, 2단계 착수).

`processed_flow_management`을 "일자별 최신 run 우선" 윈도우(`latest_run.latest_view`)로
조회해 record_date/target_fir/target_route로 필터링한 조치 목록을 페이지네이션과 함께
반환한다. **비행편 영향 결합은 제외** — 그 기능은 전처리 측 통합데이터·영향상세 테이블에
의존하며 3단계 소관이다(docs/03 §4.4 각주, docs/02 §2). 이 조회는 자체 전처리분(조치
그 자체)만 다룬다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.db.session import get_engine
from app.queries.latest_run import latest_view

_TABLE_NAME = "processed_flow_management"

# 응답에 노출하는 컬럼만 명시(docs/03 §4.4 "응답/필터 물리 컬럼" 그대로) — source_file/
# raw_* 등 내부 추적용 컬럼은 API 계약 밖이라 노출하지 않는다.
_ITEM_COLUMNS: tuple[str, ...] = (
    "flow_id",
    "apply_start_dt",
    "apply_end_dt",
    "apply_minutes",
    "minit",
    "mit",
    "alt_speed_limit",
    "target_airport",
    "target_fir",
    "target_route",
    "target_fix",
    "restriction_summary",
    "quality_status",
)

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def list_flow_management(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    fir: str | None = None,
    airway: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> tuple[dict[str, Any], str | None]:
    """direction 없는 단일 테이블 목록 조회. 호출자(routers/flow_management.py)가 입력
    형식을 이미 검증했다고 신뢰한다(routers/fois.py와 동일한 책임 분리).

    반환: (응답 data dict, data_period). data_period는 페이지네이션 전 필터링된 전체
    집합의 record_date min/max(결과 0건이면 null) — total과 마찬가지로 이 페이지가
    아니라 필터 전체 기준.
    """
    window = latest_view(_TABLE_NAME).subquery("flow_window")
    date_col = window.c.record_date

    conditions = []
    if date_from is not None:
        conditions.append(date_col >= date_from)
    if date_to is not None:
        conditions.append(date_col <= date_to)
    if fir is not None:
        # target_fir/target_route는 실측상 단일 ICAO/항로 ident 값이라(콤마 목록 아님)
        # 부분일치가 아닌 대소문자 무시 완전일치로 비교한다.
        conditions.append(func.upper(window.c.target_fir) == fir)
    if airway is not None:
        conditions.append(func.upper(window.c.target_route) == airway)

    item_cols = [window.c[name] for name in _ITEM_COLUMNS]
    list_stmt = (
        select(*item_cols)
        .where(*conditions)
        # flow_id를 2차 정렬키로 둬 apply_start_dt 동률 시에도 결과 순서를 결정적으로
        # 만든다(batch/build_odr2.py·latest_run.py에서 발견된 동률 비결정성 함정과 동일 대비).
        .order_by(window.c.apply_start_dt.asc(), window.c.flow_id.asc())
        .limit(limit)
        .offset(offset)
    )
    count_stmt = select(func.count()).select_from(window).where(*conditions)
    period_stmt = select(func.min(date_col), func.max(date_col)).where(*conditions)

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(list_stmt).all()
        total = conn.execute(count_stmt).scalar_one()
        min_date, max_date = conn.execute(period_stmt).one()

    items = [dict(zip(_ITEM_COLUMNS, row, strict=True)) for row in rows]
    period = (
        f"{min_date.replace('-', '')}-{max_date.replace('-', '')}"
        if min_date and max_date
        else None
    )
    data = {"items": items, "total": total, "limit": limit, "offset": offset}
    return data, period
