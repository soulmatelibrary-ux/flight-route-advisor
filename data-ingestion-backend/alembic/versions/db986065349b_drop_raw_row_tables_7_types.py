"""drop raw row tables 7 types

근거: 사용자 요청 — raw_*_rows 7종(68b1cff4780c)은 업로드 원본 파일을 행 단위로 그대로
DB에 복제한 것인데, 원본 파일 자체가 이미 `raw_files.stored_relpath`로 디스크에 보존되고
있어(+ sha256 무결성 검증) 순수 중복이었다. 로컬 DB 실측 기준 245MB(전체 DB의 절반 이상)를
차지해 Supabase 이전 시 용량 부담이 가장 컸다(docs/02-db-integration.md §1, §6).

이 테이블들을 참조하는 다른 테이블은 없다(raw_*_rows.id를 FK로 참조하는 테이블 없음,
실측 확인) — drop 순서는 문제되지 않는다. raw_files/ingestion_run_files/ingestion_runs는
그대로 유지되어 "어떤 파일이 언제·어떤 run으로 적재됐는지"는 계속 추적 가능하다.

애플리케이션 코드(app/db/models.py의 RAW_ROW_TABLES, app/db/column_map.py의
RAW_TABLE_COLUMNS, app/ingestion/loaders.py의 raw_*_rows 적재 로직, 원본 행 단위
브라우징 UI(/tables, /runs/{id}/data/{table}))는 이 리비전과 별개로 이미 제거됨.

Revision ID: db986065349b
Revises: d9f2b4a8c1e6
Create Date: 2026-07-24 13:40:23.336123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'db986065349b'
down_revision: Union[str, None] = 'd9f2b4a8c1e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 68b1cff4780c의 스냅샷과 동일 — downgrade에서 원래 스키마 그대로 복원하기 위함
# (데이터 자체는 drop과 함께 사라지며 복원되지 않는다, 구조만 복원).
_RAW_TABLE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "raw_flight_analysis_rows": (
        ("DATE", "date"), ("CALLSIGN", "callsign"), ("SSR", "ssr"), ("DEPT", "dept"),
        ("DEST", "dest"), ("D_EOBT", "d_eobt"), ("EOBT", "eobt"), ("D_ATD", "d_atd"),
        ("ATD", "atd"), ("ENTRY_DATE", "entry_date"), ("ENTRY_TIME", "entry_time"),
        ("EXIT_DATE", "exit_date"), ("EXIT_TIME", "exit_time"), ("RFL", "rfl"),
        ("AFL", "afl"), ("XFL", "xfl"), ("CFL", "cfl"), ("FIR_ENROUTE", "fir_enroute"),
    ),
    "raw_flight_search_rows": (
        ("DATE", "date"), ("CALLSIGN", "callsign"), ("SSR", "ssr"),
        ("REG NO", "reg_no"), ("OTHER", "other"),
    ),
    "raw_acdm_departure_rows": (
        ("source_file", "source_file"), ("source_date", "source_date"),
        ("편명", "flight_no"), ("등록부호", "reg_no"),
    ),
    "raw_acdm_arrival_rows": (
        ("source_file", "source_file"), ("source_date", "source_date"),
        ("편명", "flight_no"), ("등록부호", "reg_no"),
    ),
    "raw_fois_departure_rows": (
        ("번호", "no"), ("운항구분", "category"), ("출발일자", "dep_date"),
        ("편명", "flight_no"), ("기종", "aircraft_type"), ("등록부호", "reg_no"),
        ("출발공항", "dep_airport"), ("STD", "std"), ("ATD", "atd"),
        ("출발지연시간원본", "delay_raw"), ("도착공항", "arr_airport"),
        ("도착일자", "arr_date"), ("STA", "sta"), ("ATA", "ata"),
        ("도착지연시간원본", "delay_raw2"), ("지연기준구분", "delay_basis_category"),
        ("사유", "reason"),
    ),
    "raw_fois_arrival_rows": (
        ("번호", "no"), ("운항구분", "category"), ("출발일자", "dep_date"),
        ("편명", "flight_no"), ("기종", "aircraft_type"), ("등록부호", "reg_no"),
        ("출발공항", "dep_airport"), ("STD", "std"), ("ATD", "atd"),
        ("출발지연시간원본", "delay_raw"), ("도착공항", "arr_airport"),
        ("도착일자", "arr_date"), ("STA", "sta"), ("ATA", "ata"),
        ("도착지연시간원본", "delay_raw2"), ("지연기준구분", "delay_basis_category"),
        ("사유", "reason"),
    ),
    "raw_flow_management_rows": (
        ("Seq", "seq"), ("Date", "date"), ("RTime", "rtime"), ("Sender", "sender"),
        ("Receiver", "receiver"), ("Reasons", "reasons"), ("Start", "start_dt"),
        ("End", "end_dt"), ("Run", "run"), ("MINIT", "minit"), ("MIT", "mit"),
        ("Level Capping & G/S", "level_capping_gs"), ("Destination", "destination"),
        ("Route", "route"), ("Fix", "fix"), ("Remarks", "remarks"), ("Dir", "dir"),
        ("CTOT/Note", "ctot_note"), ("CTOT Pub", "ctot_pub"),
    ),
}


def upgrade() -> None:
    for table_name in _RAW_TABLE_COLUMNS:
        op.drop_table(table_name)


def downgrade() -> None:
    for table_name, pairs in reversed(list(_RAW_TABLE_COLUMNS.items())):
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
