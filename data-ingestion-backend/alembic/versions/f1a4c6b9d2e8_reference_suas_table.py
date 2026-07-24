"""reference suas table

근거: 사용자 요청(2026-07-24) — 공역 관련 좌표는 모두 DB에서 조회해야 한다는 요청에 따라
SUAS/MOA(특수공역) 참조 레이어 신규 구현. `사전빌드_JSON/{suas,suas_world}.json`(완성본 빌드
파이프라인이 DAFIF 원본 SUAS_PAR.TXT/SUAS.TXT를 이미 폴리곤으로 풀어놓은 산출물)을
`reference_suas` 1개 테이블로 이관한다. 컬럼 정의는 app.db.reference_tables(단일 출처)를
그대로 복사(aee66ded869a/b7d3f9a1c8e4와 동일 관례). 적재는 `scripts/migrate_suas_to_db.py`
(신규, 공유 이관 스크립트와 분리)가 truncate-and-reload로 채운다.

advisor_readonly role에 이 테이블 SELECT 권한을 추가로 부여한다.

Revision ID: f1a4c6b9d2e8
Revises: b7d3f9a1c8e4
Create Date: 2026-07-24 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

from app.db.reference_tables import reference_suas

# revision identifiers, used by Alembic.
revision: str = 'f1a4c6b9d2e8'
down_revision: Union[str, None] = 'b7d3f9a1c8e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "advisor_readonly"


def upgrade() -> None:
    op.create_table(reference_suas.name, *[column.copy() for column in reference_suas.columns])
    for index in reference_suas.indexes:
        op.create_index(
            index.name,
            reference_suas.name,
            [col.name for col in index.columns],
            unique=index.unique,
        )
    op.execute(f"GRANT SELECT ON {reference_suas.name} TO {_ROLE};")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON {reference_suas.name} FROM {_ROLE};")
    op.drop_table(reference_suas.name)
