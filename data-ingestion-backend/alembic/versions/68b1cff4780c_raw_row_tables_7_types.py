"""raw row tables 7 types

근거: data-ingestion-backend/docs/DB스키마.md §3.2. 계약 컬럼 목록은 app.db.column_map
(RAW_TABLE_COLUMNS)을 단일 출처로 사용해 이 파일에 컬럼명을 중복 나열하지 않는다(§9 규칙).

Revision ID: 68b1cff4780c
Revises: 82f408ef63f3
Create Date: 2026-07-21 19:36:24.674337

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.column_map import RAW_TABLE_COLUMNS

# revision identifiers, used by Alembic.
revision: str = '68b1cff4780c'
down_revision: Union[str, None] = '82f408ef63f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name, pairs in RAW_TABLE_COLUMNS.items():
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column(
                "raw_file_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("raw_files.id"),
                nullable=False,
            ),
            sa.Column(
                "run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("ingestion_runs.id"),
                nullable=False,
            ),
            sa.Column("source_row_number", sa.Integer, nullable=False),
            *(sa.Column(physical, sa.Text) for _logical, physical in pairs),
            sa.Column(
                "extra_columns",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "ingested_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(f"ix_{table_name}_run_id", table_name, ["run_id"])


def downgrade() -> None:
    for table_name in reversed(list(RAW_TABLE_COLUMNS)):
        op.drop_table(table_name)
