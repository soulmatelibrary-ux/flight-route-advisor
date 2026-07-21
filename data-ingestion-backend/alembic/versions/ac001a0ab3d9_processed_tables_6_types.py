"""processed tables 6 types

근거: data-ingestion-backend/docs/DB스키마.md §4·§9. 컬럼 목록은 app.db.column_map
(PROCESSED_COLUMNS)을 단일 출처로 사용. 인덱스는 §6 권장 인덱스 그대로.

Revision ID: ac001a0ab3d9
Revises: 68b1cff4780c
Create Date: 2026-07-21 19:36:24.947665

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.column_map import PROCESSED_COLUMNS

# revision identifiers, used by Alembic.
revision: str = 'ac001a0ab3d9'
down_revision: Union[str, None] = '68b1cff4780c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EXTRA_INDEXES: dict[str, tuple[tuple[str, ...], ...]] = {
    "processed_flight_data": (("date",), ("callsign",), ("ssr",), ("unique_id",)),
    "processed_acdm_departure": (("operation_date",), ("airport_icao",), ("flight_icao",)),
    "processed_acdm_arrival": (("operation_date",), ("airport_icao",), ("flight_icao",)),
    "processed_fois_departure": (("dep_date",), ("dep_airport",)),
    "processed_fois_arrival": (("arr_date",), ("arr_airport",)),
    "processed_flow_management": (("flow_id",), ("record_date",), ("apply_start_dt",)),
}


def upgrade() -> None:
    for table_name, pairs in PROCESSED_COLUMNS.items():
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column(
                "run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("ingestion_runs.id"),
                nullable=False,
            ),
            sa.Column("source_csv_path", sa.Text, nullable=False),
            *(sa.Column(physical, sa.Text) for _logical, physical in pairs),
            sa.Column(
                "ingested_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(f"ix_{table_name}_run_id", table_name, ["run_id"])
        for cols in _EXTRA_INDEXES.get(table_name, ()):
            op.create_index(f"ix_{table_name}_{'_'.join(cols)}", table_name, list(cols))


def downgrade() -> None:
    for table_name in reversed(list(PROCESSED_COLUMNS)):
        op.drop_table(table_name)
