"""SQLAlchemy Core Table 정의 (전체 13종).

물리 컬럼명은 `column_map.py`(단일 출처)를 그대로 따른다. 여기서 컬럼명 문자열을
다시 나열하지 않고 `column_map`의 매핑을 순회해 생성한다(DB스키마.md §9 규칙).
CHECK 제약·인덱스·FK는 DB스키마.md 2~6·8장 그대로.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from app.db.column_map import PROCESSED_COLUMNS, RAW_TABLE_COLUMNS

metadata = sa.MetaData()

_RUN_TYPES = ("flight_data", "acdm", "fois", "flow_management")
_RUN_STATUSES = ("QUEUED", "RUNNING", "SUCCESS", "VALIDATION_FAILED", "FAILED", "DELETED")
_RAW_FILE_TYPES = (
    "flight_analysis",
    "flight_search",
    "acdm_departure",
    "acdm_arrival",
    "fois_departure",
    "fois_arrival",
    "flow_management",
)


def _text_columns(pairs: tuple[tuple[str, str], ...]) -> list[sa.Column]:
    return [sa.Column(physical, sa.Text) for _logical, physical in pairs]


# --- 2. 실행 추적 테이블 (DB스키마.md §2) ---

ingestion_runs = sa.Table(
    "ingestion_runs",
    metadata,
    sa.Column("id", PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
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
    sa.Column("output_paths", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("validation_summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("error_message", sa.Text),
    # 삭제(재입력 전 정리) 시에만 채워진다 — run 자체를 물리 삭제하지 않고 감사 기록으로
    # 남긴다(status='DELETED', loaders.delete_run). 데이터/아카이브 파일만 실제로 지운다.
    sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("deleted_by", sa.Text),
    sa.CheckConstraint(
        "run_type IN ('flight_data','acdm','fois','flow_management')",
        name="ck_ingestion_runs_run_type",
    ),
    sa.CheckConstraint(
        "status IN ('QUEUED','RUNNING','SUCCESS','VALIDATION_FAILED','FAILED','DELETED')",
        name="ck_ingestion_runs_status",
    ),
)
sa.Index("ix_ingestion_runs_status", ingestion_runs.c.status)
sa.Index("ix_ingestion_runs_run_type", ingestion_runs.c.run_type)
sa.Index("ix_ingestion_runs_started_at", ingestion_runs.c.started_at)
sa.Index(
    "uq_ingestion_runs_idempotency_key",
    ingestion_runs.c.idempotency_key,
    unique=True,
    postgresql_where=sa.text("idempotency_key IS NOT NULL"),
)

raw_files = sa.Table(
    "raw_files",
    metadata,
    sa.Column("id", PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    sa.Column("file_type", sa.Text, nullable=False),
    sa.Column("original_filename", sa.Text, nullable=False),
    sa.Column("stored_relpath", sa.Text, nullable=False),
    sa.Column("sha256", sa.Text, nullable=False),
    sa.Column("sheet_name", sa.Text),
    sa.Column("row_count", sa.Integer, nullable=False),
    sa.Column(
        "uploaded_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint(
        "file_type IN ('flight_analysis','flight_search','acdm_departure','acdm_arrival',"
        "'fois_departure','fois_arrival','flow_management')",
        name="ck_raw_files_file_type",
    ),
    sa.CheckConstraint("row_count >= 0", name="ck_raw_files_row_count"),
    sa.CheckConstraint("char_length(sha256) = 64", name="ck_raw_files_sha256_len"),
)
sa.Index(
    "uq_raw_files_sha256_type_sheet",
    raw_files.c.sha256,
    raw_files.c.file_type,
    sa.func.coalesce(raw_files.c.sheet_name, ""),
    unique=True,
)

ingestion_run_files = sa.Table(
    "ingestion_run_files",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("run_id", PgUUID(as_uuid=True), sa.ForeignKey("ingestion_runs.id"), nullable=False),
    sa.Column("raw_file_id", PgUUID(as_uuid=True), sa.ForeignKey("raw_files.id"), nullable=False),
    sa.Column("role", sa.Text, nullable=False, server_default="input"),
    sa.UniqueConstraint("run_id", "raw_file_id", name="uq_ingestion_run_files_run_raw"),
)
sa.Index("ix_ingestion_run_files_run_id", ingestion_run_files.c.run_id)
sa.Index("ix_ingestion_run_files_raw_file_id", ingestion_run_files.c.raw_file_id)

ingestion_logs = sa.Table(
    "ingestion_logs",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("run_id", PgUUID(as_uuid=True), sa.ForeignKey("ingestion_runs.id"), nullable=False),
    sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("level", sa.Text, nullable=False),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("message", sa.Text, nullable=False),
    sa.CheckConstraint("level IN ('INFO','WARN','ERROR')", name="ck_ingestion_logs_level"),
    sa.CheckConstraint(
        "source IN ('stdout','stderr','validation')", name="ck_ingestion_logs_source"
    ),
)
sa.Index("ix_ingestion_logs_run_id", ingestion_logs.c.run_id)

# --- 3. Raw 계층 — 파일유형별 raw_*_rows 7종 (DB스키마.md §3.2) ---

RAW_ROW_TABLES: dict[str, sa.Table] = {}
for _name, _pairs in RAW_TABLE_COLUMNS.items():
    _table = sa.Table(
        _name,
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "raw_file_id", PgUUID(as_uuid=True), sa.ForeignKey("raw_files.id"), nullable=False
        ),
        sa.Column(
            "run_id", PgUUID(as_uuid=True), sa.ForeignKey("ingestion_runs.id"), nullable=False
        ),
        sa.Column("source_row_number", sa.Integer, nullable=False),
        *_text_columns(_pairs),
        sa.Column("extra_columns", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "ingested_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    sa.Index(f"ix_{_name}_run_id", _table.c.run_id)
    RAW_ROW_TABLES[_name] = _table

# --- 4. Processed 계층 — processed_* 6종 (DB스키마.md §4·§9) ---

_PROCESSED_EXTRA_INDEXES: dict[str, tuple[tuple[str, ...], ...]] = {
    "processed_flight_data": (("date",), ("callsign",), ("ssr",), ("unique_id",)),
    "processed_acdm_departure": (("operation_date",), ("airport_icao",), ("flight_icao",)),
    "processed_acdm_arrival": (("operation_date",), ("airport_icao",), ("flight_icao",)),
    "processed_fois_departure": (("dep_date",), ("dep_airport",)),
    "processed_fois_arrival": (("arr_date",), ("arr_airport",)),
    "processed_flow_management": (("flow_id",), ("record_date",), ("apply_start_dt",)),
}

PROCESSED_TABLES: dict[str, sa.Table] = {}
for _name, _pairs in PROCESSED_COLUMNS.items():
    _table = sa.Table(
        _name,
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", PgUUID(as_uuid=True), sa.ForeignKey("ingestion_runs.id"), nullable=False
        ),
        sa.Column("source_csv_path", sa.Text, nullable=False),
        *_text_columns(_pairs),
        sa.Column(
            "ingested_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    sa.Index(f"ix_{_name}_run_id", _table.c.run_id)
    for _cols in _PROCESSED_EXTRA_INDEXES.get(_name, ()):
        sa.Index(f"ix_{_name}_{'_'.join(_cols)}", *[_table.c[c] for c in _cols])
    PROCESSED_TABLES[_name] = _table

del _name, _pairs, _table, _cols
