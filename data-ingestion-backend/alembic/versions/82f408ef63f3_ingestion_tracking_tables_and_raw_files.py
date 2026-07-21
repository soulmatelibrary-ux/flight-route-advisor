"""ingestion tracking tables and raw_files

근거: data-ingestion-backend/docs/DB스키마.md §2(실행 추적 테이블), §3.1(raw_files).
raw_files를 이 리비전에 포함하는 이유: ingestion_run_files가 raw_files.id를 FK로
참조하므로 raw_files가 먼저 존재해야 한다(§3.1의 raw_*_rows 7종은 다음 리비전).

Revision ID: 82f408ef63f3
Revises:
Create Date: 2026-07-21 19:36:24.474951

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '82f408ef63f3'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.Text),
        sa.Column("error_code", sa.Text),
        sa.Column("triggered_by", sa.Text, nullable=False),
        sa.Column("workspace_path", sa.Text),
        sa.Column("skill_version", sa.Text),
        sa.Column("cli_command", sa.Text),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "output_paths", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "validation_summary",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text),
        sa.CheckConstraint(
            "run_type IN ('flight_data','acdm','fois','flow_management')",
            name="ck_ingestion_runs_run_type",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCESS','VALIDATION_FAILED','FAILED')",
            name="ck_ingestion_runs_status",
        ),
    )
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])
    op.create_index("ix_ingestion_runs_run_type", "ingestion_runs", ["run_type"])
    op.create_index("ix_ingestion_runs_started_at", "ingestion_runs", ["started_at"])
    op.create_index(
        "uq_ingestion_runs_idempotency_key",
        "ingestion_runs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "raw_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("file_type", sa.Text, nullable=False),
        sa.Column("original_filename", sa.Text, nullable=False),
        sa.Column("stored_relpath", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("sheet_name", sa.Text),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column(
            "uploaded_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "file_type IN ('flight_analysis','flight_search','acdm_departure','acdm_arrival',"
            "'fois_departure','fois_arrival','flow_management')",
            name="ck_raw_files_file_type",
        ),
        sa.CheckConstraint("row_count >= 0", name="ck_raw_files_row_count"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_raw_files_sha256_len"),
    )
    op.create_index(
        "uq_raw_files_sha256_type_sheet",
        "raw_files",
        [sa.text("sha256"), sa.text("file_type"), sa.text("coalesce(sheet_name, '')")],
        unique=True,
    )

    op.create_table(
        "ingestion_run_files",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "raw_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_files.id"),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False, server_default="input"),
        sa.UniqueConstraint("run_id", "raw_file_id", name="uq_ingestion_run_files_run_raw"),
    )
    op.create_index("ix_ingestion_run_files_run_id", "ingestion_run_files", ["run_id"])
    op.create_index("ix_ingestion_run_files_raw_file_id", "ingestion_run_files", ["raw_file_id"])

    op.create_table(
        "ingestion_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "ts", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("level", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.CheckConstraint("level IN ('INFO','WARN','ERROR')", name="ck_ingestion_logs_level"),
        sa.CheckConstraint(
            "source IN ('stdout','stderr','validation')", name="ck_ingestion_logs_source"
        ),
    )
    op.create_index("ix_ingestion_logs_run_id", "ingestion_logs", ["run_id"])


def downgrade() -> None:
    op.drop_table("ingestion_logs")
    op.drop_table("ingestion_run_files")
    op.drop_table("raw_files")
    op.drop_table("ingestion_runs")
