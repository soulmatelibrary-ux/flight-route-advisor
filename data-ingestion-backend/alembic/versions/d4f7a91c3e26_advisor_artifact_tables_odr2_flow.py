"""advisor artifact tables (odr2 + flow) — 파일 아티팩트 → DB 통합

근거: 사용자 요청(2026-07-23) — `backend/batch/{build_odr2,build_flow}.py`가 파일
아티팩트(`odr2.json`/`flow.json` + `_meta.json`)로만 쓰던 산출물을 로컬 Docker DB로
완전 정규화 편입한다(docs/02-db-integration.md §4.3 결정 갱신). advisor(Stage 1)는
여전히 읽기전용 원칙을 지켜야 하므로(CLAUDE.md §5, 과거 role 혼용 사고 이력), 이 배치
전용 쓰기 role을 `advisor_readonly`와 완전히 분리해 신설한다.

- `advisor_artifact_writer`: 아래 12개 테이블에만 SELECT/INSERT/UPDATE/DELETE/TRUNCATE.
  `processed_*`/`raw_*`/`reference_*`/`ingestion_*`에는 GRANT 없음(최소권한).
- `advisor_readonly`(기존, `360c8b394406`): 동일 12개 테이블에 SELECT만 추가로 받아
  `backend/app/queries/{routes,flow_reasoning}.py`가 기존 읽기전용 엔진 그대로 조회.
- 비밀번호는 `ADVISOR_ARTIFACT_WRITER_PASSWORD` 환경변수에서만 읽는다(`360c8b394406`과
  동일 관례, docs/06-conventions.md §8 비밀정보 비커밋).
- 스키마는 서로게이트 id 없이 업무 키(dep/arr/rank 등) 합성 PK로 구성 — 시퀀스 GRANT가
  필요 없고 쓰기 role 권한 관리가 테이블 단위로만 끝난다.

Revision ID: d4f7a91c3e26
Revises: aee66ded869a
Create Date: 2026-07-23 15:00:00.000000

"""
import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4f7a91c3e26'
down_revision: Union[str, None] = 'aee66ded869a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WRITER_ROLE = "advisor_artifact_writer"
_READONLY_ROLE = "advisor_readonly"
_PASSWORD_ENV = "ADVISOR_ARTIFACT_WRITER_PASSWORD"
_SAFE_PASSWORD_RE = re.compile(r"^[A-Za-z0-9]{16,64}$")

_TABLES: tuple[str, ...] = (
    "advisor_odr2_od",
    "advisor_odr2_route",
    "advisor_odr2_route_fir",
    "advisor_odr2_route_fix",
    "advisor_odr2_track_point",
    "advisor_odr2_full_route_point",
    "advisor_flow_od",
    "advisor_flow_od_reason",
    "advisor_flow_od_limit",
    "advisor_flow_od_measure",
    "advisor_flow_od_hour",
    "advisor_flow_route_group",
)


def _writer_password() -> str:
    password = os.environ.get(_PASSWORD_ENV)
    if not password:
        raise RuntimeError(
            f"{_PASSWORD_ENV} 환경변수가 없음 — 저장소 루트 .env에 설정 후 재실행"
        )
    if not _SAFE_PASSWORD_RE.match(password):
        raise RuntimeError(f"{_PASSWORD_ENV}는 영숫자 16~64자여야 함")
    return password


def _current_database() -> str:
    bind = op.get_bind()
    return bind.execute(sa.text("SELECT current_database()")).scalar()


def upgrade() -> None:
    # --- ODR2 (backend/batch/build_odr2.py 소스) ---
    op.create_table(
        "advisor_odr2_od",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("total_flights", sa.Integer, nullable=False),
        sa.Column("data_period", sa.Text),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr"),
    )
    op.create_table(
        "advisor_odr2_route",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("flights", sa.Integer, nullable=False),
        sa.Column("avg_min", sa.Integer),
        sa.Column("delay_count", sa.Integer, nullable=False),
        sa.Column("heavy_count", sa.Integer, nullable=False),
        sa.Column("cruise_parity", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "rank"),
        sa.ForeignKeyConstraint(
            ["dep", "arr"], ["advisor_odr2_od.dep", "advisor_odr2_od.arr"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "advisor_odr2_route_fir",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("fir_icao", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "rank", "seq"),
        sa.ForeignKeyConstraint(
            ["dep", "arr", "rank"],
            ["advisor_odr2_route.dep", "advisor_odr2_route.arr", "advisor_odr2_route.rank"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "advisor_odr2_route_fix",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("fix_name", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "rank", "seq"),
        sa.ForeignKeyConstraint(
            ["dep", "arr", "rank"],
            ["advisor_odr2_route.dep", "advisor_odr2_route.arr", "advisor_odr2_route.rank"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "advisor_odr2_track_point",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lon", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "rank", "seq"),
        sa.ForeignKeyConstraint(
            ["dep", "arr", "rank"],
            ["advisor_odr2_route.dep", "advisor_odr2_route.arr", "advisor_odr2_route.rank"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "advisor_odr2_full_route_point",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lon", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "rank", "seq"),
        sa.ForeignKeyConstraint(
            ["dep", "arr", "rank"],
            ["advisor_odr2_route.dep", "advisor_odr2_route.arr", "advisor_odr2_route.rank"],
            ondelete="CASCADE",
        ),
    )

    # --- Flow (backend/batch/build_flow.py 소스) ---
    op.create_table(
        "advisor_flow_od",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("impact_pct", sa.Integer, nullable=False),
        sa.Column("affected_flights", sa.Integer, nullable=False),
        sa.Column("total_flights", sa.Integer, nullable=False),
        sa.Column("on_time_affected", sa.Integer),
        sa.Column("on_time_normal", sa.Integer),
        sa.Column("delay_affected_min", sa.Float),
        sa.Column("delay_normal_min", sa.Float),
        sa.Column("data_period", sa.Text),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr"),
    )
    op.create_table(
        "advisor_flow_od_reason",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("reason_code", sa.Text, nullable=False),
        sa.Column("pct", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "seq"),
        sa.ForeignKeyConstraint(
            ["dep", "arr"], ["advisor_flow_od.dep", "advisor_flow_od.arr"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "advisor_flow_od_limit",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("limit_text", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "seq"),
        sa.ForeignKeyConstraint(
            ["dep", "arr"], ["advisor_flow_od.dep", "advisor_flow_od.arr"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "advisor_flow_od_measure",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("measure_id", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "seq"),
        sa.ForeignKeyConstraint(
            ["dep", "arr"], ["advisor_flow_od.dep", "advisor_flow_od.arr"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "advisor_flow_od_hour",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("hour", sa.SmallInteger, nullable=False),
        sa.Column("impact_pct", sa.Integer),
        sa.PrimaryKeyConstraint("dep", "arr", "hour"),
        sa.ForeignKeyConstraint(
            ["dep", "arr"], ["advisor_flow_od.dep", "advisor_flow_od.arr"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "advisor_flow_route_group",
        sa.Column("dep", sa.Text, nullable=False),
        sa.Column("arr", sa.Text, nullable=False),
        sa.Column("route_key", sa.Text, nullable=False),
        sa.Column("pct", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("dep", "arr", "route_key"),
    )

    # --- roles ---
    password = _writer_password()
    dbname = _current_database()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_WRITER_ROLE}') THEN
                CREATE ROLE {_WRITER_ROLE} LOGIN PASSWORD '{password}';
            END IF;
        END
        $$;
        """
    )
    op.execute(f'GRANT CONNECT ON DATABASE "{dbname}" TO {_WRITER_ROLE};')
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_WRITER_ROLE};")
    for table in _TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {table} TO {_WRITER_ROLE};")
        op.execute(f"GRANT SELECT ON {table} TO {_READONLY_ROLE};")


def downgrade() -> None:
    dbname = _current_database()
    for table in _TABLES:
        op.execute(f"REVOKE SELECT ON {table} FROM {_READONLY_ROLE};")
        op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {table} FROM {_WRITER_ROLE};")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_WRITER_ROLE};")
    op.execute(f'REVOKE CONNECT ON DATABASE "{dbname}" FROM {_WRITER_ROLE};')
    op.execute(f"DROP ROLE IF EXISTS {_WRITER_ROLE};")

    for table_name in (
        "advisor_flow_route_group",
        "advisor_flow_od_hour",
        "advisor_flow_od_measure",
        "advisor_flow_od_limit",
        "advisor_flow_od_reason",
        "advisor_flow_od",
        "advisor_odr2_full_route_point",
        "advisor_odr2_track_point",
        "advisor_odr2_route_fix",
        "advisor_odr2_route_fir",
        "advisor_odr2_route",
        "advisor_odr2_od",
    ):
        op.drop_table(table_name)
