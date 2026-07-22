"""'최신본 뷰' 규약 — 일자별 최신 run 우선 (docs/02-db-integration.md §3).

`processed_*`는 append-only라 여러 run이 쌓일 수 있다. 이 모듈은 각 테이블의 날짜
컬럼(column_map.DATE_COLUMNS) 값별로, 그 값을 포함하는 SUCCESS run들 중
`finished_at`이 가장 늦은 run의 행만 골라내는 SELECT를 만든다(사용자 확정 정책,
2026-07-22). 겹치지 않는 날짜(신규 월 추가)는 그대로 누적되고, 같은 날짜 정정
재업로드는 최신 run이 그 날짜만 통째로 대체한다.

주의(구현상 흔한 함정): 날짜 컬럼 값 자체로 바로
`ROW_NUMBER() OVER (PARTITION BY 날짜컬럼 ...)`을 원본 행에 걸면 안 된다 — 그러면
같은 날짜의 여러 행(하루에 여러 편)이 1행으로 뭉개진다. 반드시 먼저 (날짜, run_id)
조합만 distinct로 추린 뒤 그 위에서 날짜별 승자 run_id를 정하고, 마지막에 원본
테이블과 (날짜, 승자 run_id)로 다시 조인해 그 run의 전체 행을 되돌려줘야 한다.
"""

from __future__ import annotations

from sqlalchemy import Select, and_, func, select

from app.db import column_map
from app.db.tables import get_table


def latest_view(table_name: str) -> Select:
    """table_name의 '일자별 최신 run 우선' 현재본 SELECT를 만든다.

    반환된 Select는 table_name의 전체 컬럼(화이트리스트, column_map.py)을 담고
    있으며, 호출자가 추가 WHERE/컬럼 선택을 이어붙여 쓸 수 있다.
    """
    if table_name not in column_map.PROCESSED_COLUMNS:
        raise ValueError(f"latest_view는 processed_* 테이블만 지원: {table_name}")

    table = get_table(table_name)
    runs = get_table("ingestion_runs")

    date_col = table.c[column_map.DATE_COLUMNS[table_name]]
    day_key = (
        func.left(date_col, 10)
        if table_name in column_map.TABLES_NEEDING_DAY_TRUNCATION
        else date_col
    )
    run_type = column_map.TABLE_RUN_TYPE[table_name]

    # 1단계: (날짜, run_id) 조합만 distinct로 추림 — 원본 행 개수와 무관하게 만든다.
    day_runs = (
        select(day_key.label("day_key"), table.c.run_id, runs.c.finished_at)
        .select_from(table.join(runs, table.c.run_id == runs.c.id))
        .where(runs.c.run_type == run_type, runs.c.status == "SUCCESS")
        .distinct()
        .subquery("day_runs")
    )

    # 2단계: 날짜별로 finished_at이 가장 늦은 run_id를 승자로 뽑는다. finished_at이
    # 동률(같은 타임스탬프)일 경우를 대비해 run_id를 2차 정렬키로 둬 결과를
    # 결정적으로 만든다(동률 시 승자가 실행마다 바뀌는 문제 방지 — batch/build_odr2.py에서
    # 같은 종류의 비결정성을 발견해 ORDER BY id로 고친 전례와 동일한 함정).
    ranked = select(
        day_runs.c.day_key,
        day_runs.c.run_id,
        func.row_number()
        .over(
            partition_by=day_runs.c.day_key,
            order_by=(day_runs.c.finished_at.desc(), day_runs.c.run_id.desc()),
        )
        .label("rn"),
    ).subquery("ranked")
    winners = (
        select(ranked.c.day_key, ranked.c.run_id).where(ranked.c.rn == 1).subquery("winners")
    )

    # 3단계: 원본 테이블을 (날짜, 승자 run_id)로 다시 조인 — 그 run의 전체 행을 되돌려준다.
    return select(table).select_from(
        table.join(
            winners,
            and_(day_key == winners.c.day_key, table.c.run_id == winners.c.run_id),
        )
    )
