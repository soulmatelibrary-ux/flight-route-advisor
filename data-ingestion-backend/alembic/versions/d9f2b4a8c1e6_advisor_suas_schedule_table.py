"""advisor suas schedule table

근거: docs/13-ai-reasoning-dev-plan.md STEP A7(SUAS/MOA 통과시각 발효 판정, D23) — DAFIF
`SUAS_PAR.TXT`의 `EFF_TIMES`(발효시간)는 완성본 빌드 파이프라인조차 버린 필드라 사전빌드
`suas.json`/`suas_world.json`(→ 별도 세션이 이관한 `reference_suas`)에는 없다. doc13이
이 STEP을 "이식이 아니라 신규 파생"이라 명시하고 대상을 `backend/batch/build_suas.py`
(advisor 소유 배치, `build_odr2.py`/`build_flow.py`와 동일 계층)로 지정했으므로, 이 결과는
`reference_*`(Stage 0 소유)가 아니라 `advisor_*`(advisor 소유) 네임스페이스에 별도 테이블로
둔다 — 이렇게 하면 동시에 `reference_suas`를 다루던 별도 세션과 스키마 편집이 전혀 겹치지
않는다. 조인은 `ident`(DAFIF `SUAS_IDENT`, `reference_suas.ident`와 동일 값 — 실측 확인,
2026-07-24: 한국 240건 전부 `(RK)A2`류 포맷 일치)로 애플리케이션 레벨에서 한다(스키마
소유가 달라 FK는 걸지 않음).

역할은 기존 `advisor_artifact_writer`/`advisor_readonly`(d4f7a91c3e26)를 재사용 — 새 역할
불필요, 이 테이블에 대한 GRANT만 추가.

Revision ID: d9f2b4a8c1e6
Revises: c3e7a1f6b0d4
Create Date: 2026-07-24 13:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'd9f2b4a8c1e6'
down_revision: Union[str, None] = 'c3e7a1f6b0d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WRITER_ROLE = "advisor_artifact_writer"
_READONLY_ROLE = "advisor_readonly"
_TABLE = "advisor_suas_schedule"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("ident", sa.Text, nullable=False),
        sa.Column("eff_times_raw", sa.Text),
        # "structured"(요일+UTC 시간범위 정규식 파싱 성공) | "confirm_required"(SR-SS/BY NOTAM/
        # 자유서술 등 비정형 — 발효 여부 단정 금지, docs/13 STEP A7 안전 우선 원칙)
        sa.Column("status", sa.Text, nullable=False),
        # structured일 때만 채움: [{"days":["MON",...],"utc_start":2300,"utc_end":1300}, ...]
        sa.Column("segments", JSONB),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("ident"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {_TABLE} TO {_WRITER_ROLE};")
    op.execute(f"GRANT SELECT ON {_TABLE} TO {_READONLY_ROLE};")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON {_TABLE} FROM {_READONLY_ROLE};")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {_TABLE} FROM {_WRITER_ROLE};")
    op.drop_table(_TABLE)
