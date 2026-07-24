"""reference tables 11 types

근거: 참조 데이터(공역/항공로/지점/SID·STAR) 정적 JSON → DB 전환. 컬럼 정의는
app.db.reference_tables(단일 출처)를 그대로 복사해 생성한다(column_map.py 기반
processed_*/raw_* 마이그레이션과 동일한 관례). 이 10개 테이블은 processed_*와 달리
run_id/최신-run 윈도잉이 없는 정적 마스터 데이터로, `scripts/migrate_static_reference_to_db.py`
/`scripts/ingest_jepp_nav.py`가 truncate-and-reload로 채운다.

advisor_readonly role은 이미 `360c8b394406`에서 생성돼 있으므로 여기서는 이 10개 테이블에
대한 SELECT 권한만 추가로 부여한다.

Revision ID: aee66ded869a
Revises: 9e2a5d7c1b4f
Create Date: 2026-07-23 12:30:20.200424

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.reference_tables import REFERENCE_TABLES

# revision identifiers, used by Alembic.
revision: str = 'aee66ded869a'
down_revision: Union[str, None] = '9e2a5d7c1b4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "advisor_readonly"


def upgrade() -> None:
    for table_name, table in REFERENCE_TABLES.items():
        op.create_table(table_name, *[column.copy() for column in table.columns])
        for index in table.indexes:
            op.create_index(
                index.name,
                table_name,
                [col.name for col in index.columns],
                unique=index.unique,
            )
        op.execute(f"GRANT SELECT ON {table_name} TO {_ROLE};")


def downgrade() -> None:
    for table_name in reversed(list(REFERENCE_TABLES)):
        op.execute(f"REVOKE SELECT ON {table_name} FROM {_ROLE};")
        op.drop_table(table_name)
