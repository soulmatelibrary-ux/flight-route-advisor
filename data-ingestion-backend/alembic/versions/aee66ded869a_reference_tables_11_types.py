"""reference tables 11 types

근거: 참조 데이터(공역/항공로/지점/SID·STAR) 정적 JSON → DB 전환. 컬럼 정의는
app.db.reference_tables(단일 출처)를 그대로 복사해 생성한다(column_map.py 기반
processed_*/raw_* 마이그레이션과 동일한 관례). 이 10개 테이블은 processed_*와 달리
run_id/최신-run 윈도잉이 없는 정적 마스터 데이터로, `scripts/migrate_static_reference_to_db.py`
/`scripts/ingest_jepp_nav.py`가 truncate-and-reload로 채운다.

advisor_readonly role은 이미 `360c8b394406`에서 생성돼 있으므로 여기서는 이 10개 테이블에
대한 SELECT 권한만 추가로 부여한다.

2026-07-24 수정: 원래 `app.db.reference_tables.REFERENCE_TABLES`(전체 딕셔너리)를 그대로
순회했으나, 이후 리비전(`b7d3f9a1c8e4`가 acc_sector/acc_boundary, `f1a4c6b9d2e8`가 suas
추가)이 같은 딕셔너리에 항목을 계속 추가해 왔다 — 즉 이 리비전이 "그 시점에 실제로 만든
테이블"이 아니라 "지금 이 딕셔너리에 들어있는 모든 테이블"을 만들게 되어 있었다. 신규 DB에
처음부터 마이그레이션을 재생하면(Supabase 이전이 정확히 이 시나리오) 이 리비전이 acc_sector
등을 먼저 만들어버려 뒤의 `b7d3f9a1c8e4`/`f1a4c6b9d2e8`가 "relation already exists"로
실패한다(Supabase 이전 중 실측 발견). 이 10개 테이블을 이름으로 명시해 이후 딕셔너리 추가와
무관하게 고정한다 — 테이블 객체 자체(컬럼 정의)는 계속 `reference_tables.py`를 단일
출처로 참조하되(모듈이 삭제된 것은 아님, 68b1cff4780c의 RAW_TABLE_COLUMNS 삭제 케이스와는
다름), "이 리비전이 담당하는 테이블 집합"만 스냅샷으로 고정한다.

Revision ID: aee66ded869a
Revises: 9e2a5d7c1b4f
Create Date: 2026-07-23 12:30:20.200424

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.reference_tables import (
    reference_fir,
    reference_tca,
    reference_airway,
    reference_airport,
    reference_navaid,
    reference_waypoint,
    reference_sid,
    reference_star,
    reference_waypoint_enroute,
    reference_waypoint_terminal,
)

# revision identifiers, used by Alembic.
revision: str = 'aee66ded869a'
down_revision: Union[str, None] = '9e2a5d7c1b4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "advisor_readonly"

# 이 리비전이 실제로 담당하는 10개 테이블(고정) — acc_sector/acc_boundary는 b7d3f9a1c8e4,
# suas는 f1a4c6b9d2e8이 각각 별도로 담당한다.
_TABLES = (
    reference_fir,
    reference_tca,
    reference_airway,
    reference_airport,
    reference_navaid,
    reference_waypoint,
    reference_sid,
    reference_star,
    reference_waypoint_enroute,
    reference_waypoint_terminal,
)


def upgrade() -> None:
    for table in _TABLES:
        op.create_table(table.name, *[column.copy() for column in table.columns])
        for index in table.indexes:
            op.create_index(
                index.name,
                table.name,
                [col.name for col in index.columns],
                unique=index.unique,
            )
        op.execute(f"GRANT SELECT ON {table.name} TO {_ROLE};")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"REVOKE SELECT ON {table.name} FROM {_ROLE};")
        op.drop_table(table.name)
