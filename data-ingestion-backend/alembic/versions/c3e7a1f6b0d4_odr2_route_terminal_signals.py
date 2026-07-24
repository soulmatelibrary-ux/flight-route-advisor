"""odr2 route terminal signals (gate_in/gate_out/runway distribution)

근거: docs/13-ai-reasoning-dev-plan.md STEP A6(터미널 신호 이식, D20 확정) — 완성본
ODR2 `odInfo`/경로옵션의 진출입 게이트(`ext`)·출발 활주로 분포(`rwd`)를 advisor 경로
응답에 이식한다.

- `gate_in`/`gate_out`은 스칼라(경로그룹의 최빈 진출입 게이트 픽스명)라 `advisor_odr2_route`에
  컬럼 2개만 추가(`ALTER TABLE`) — d4f7a91c3e26이 이미 만든 테이블이라 GRANT 재부여 불필요
  (테이블 단위 GRANT가 새 컬럼에도 자동 적용됨).
- 출발 활주로 분포는 **리스트**라 이 저장소의 "완전 정규화"(d4f7a91c3e26 결정, 서로게이트
  id 없이 업무 키 합성 PK) 원칙을 그대로 따라 JSONB 블롭 대신 `advisor_odr2_route_fir`/
  `_route_fix`와 동일한 모양의 자식 테이블(`advisor_odr2_route_runway`)로 추가한다. 이
  테이블은 새로 생기므로 두 role(`advisor_artifact_writer`/`advisor_readonly`) GRANT가
  필요(d4f7a91c3e26과 동일 패턴, role 자체는 이미 있으므로 재생성하지 않음).

Revision ID: c3e7a1f6b0d4
Revises: f1a4c6b9d2e8
Create Date: 2026-07-24 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3e7a1f6b0d4'
down_revision: Union[str, None] = 'f1a4c6b9d2e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WRITER_ROLE = "advisor_artifact_writer"
_READONLY_ROLE = "advisor_readonly"
_NEW_TABLE = "advisor_odr2_route_runway"


def upgrade() -> None:
    op.add_column("advisor_odr2_route", sa.Column("gate_in", sa.Text, nullable=True))
    op.add_column("advisor_odr2_route", sa.Column("gate_out", sa.Text, nullable=True))

    op.create_table(
        _NEW_TABLE,
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("runway", sa.Text, nullable=False),
        sa.Column("pct", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "rank", "seq"),
        sa.ForeignKeyConstraint(
            ["dep", "arr", "rank"],
            ["advisor_odr2_route.dep", "advisor_odr2_route.arr", "advisor_odr2_route.rank"],
            ondelete="CASCADE",
        ),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {_NEW_TABLE} TO {_WRITER_ROLE};")
    op.execute(f"GRANT SELECT ON {_NEW_TABLE} TO {_READONLY_ROLE};")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON {_NEW_TABLE} FROM {_READONLY_ROLE};")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {_NEW_TABLE} FROM {_WRITER_ROLE};")
    op.drop_table(_NEW_TABLE)
    op.drop_column("advisor_odr2_route", "gate_out")
    op.drop_column("advisor_odr2_route", "gate_in")
