"""run 삭제·재입력 루틴 지원

근거: 사용자 요청("동일 자료 재입력/삭제 후 재입력 루틴 확인·추가"). 지금까지는
processed_*/raw_*가 append-only라 같은 날짜를 다시 올려도 예전 데이터가 남아 중복이
쌓였다(삭제 루틴 부재). 이 리비전은 `ingestion_runs.status`에 'DELETED'를 추가하고,
누가/언제 지웠는지 남기는 `deleted_at`/`deleted_by` 컬럼을 추가한다 — run 자체(메타데이터)는
감사 기록으로 남기고, 실제 raw_*_rows/processed_*/아카이브 파일만 지운다(loaders.delete_run).

Revision ID: 7c1e4a9b2f6d
Revises: 360c8b394406
Create Date: 2026-07-21 22:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7c1e4a9b2f6d'
down_revision: Union[str, None] = '360c8b394406'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ingestion_runs", sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)))
    op.add_column("ingestion_runs", sa.Column("deleted_by", sa.Text))
    op.drop_constraint("ck_ingestion_runs_status", "ingestion_runs", type_="check")
    op.create_check_constraint(
        "ck_ingestion_runs_status",
        "ingestion_runs",
        "status IN ('QUEUED','RUNNING','SUCCESS','VALIDATION_FAILED','FAILED','DELETED')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ingestion_runs_status", "ingestion_runs", type_="check")
    op.create_check_constraint(
        "ck_ingestion_runs_status",
        "ingestion_runs",
        "status IN ('QUEUED','RUNNING','SUCCESS','VALIDATION_FAILED','FAILED')",
    )
    op.drop_column("ingestion_runs", "deleted_by")
    op.drop_column("ingestion_runs", "deleted_at")
