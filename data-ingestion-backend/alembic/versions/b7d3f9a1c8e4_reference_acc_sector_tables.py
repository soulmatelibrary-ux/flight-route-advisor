"""reference acc sector tables

근거: docs/13-ai-reasoning-dev-plan.md STEP A4(실시간 섹터 교통·수요예측) 선행 —
`acc_sectors.json`(사전빌드, 한국 인천/대구 ACC만 커버)을 `reference_acc_sector`/
`reference_acc_boundary` 2개 테이블로 이관한다. 컬럼 정의는 app.db.reference_tables(단일
출처)를 그대로 복사(aee66ded869a와 동일 관례). 적재는
`scripts/migrate_static_reference_to_db.py`가 truncate-and-reload로 채운다.

advisor_readonly role에 이 2개 테이블 SELECT 권한을 추가로 부여한다.

Revision ID: b7d3f9a1c8e4
Revises: d4f7a91c3e26
Create Date: 2026-07-24 09:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.reference_tables import reference_acc_boundary, reference_acc_sector

# revision identifiers, used by Alembic.
revision: str = 'b7d3f9a1c8e4'
down_revision: Union[str, None] = 'd4f7a91c3e26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "advisor_readonly"
_TABLES = (reference_acc_sector, reference_acc_boundary)


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
