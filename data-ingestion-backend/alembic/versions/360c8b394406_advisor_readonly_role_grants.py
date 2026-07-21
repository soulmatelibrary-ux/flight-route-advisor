"""advisor readonly role grants

근거: docs/07-checklist.md 공통 게이트 "최소권한 role(테이블 명시 GRANT)".
Stage 1(advisor)이 이 role로 processed_* 6종만 SELECT하도록 분리한다(DDL/쓰기 권한 없음).
비밀번호는 마이그레이션 파일에 리터럴로 두지 않고 ADVISOR_READONLY_PASSWORD 환경변수에서
실행 시점에만 읽는다(docs/06 §8 비밀정보 비커밋). DB명은 하드코딩하지 않고 현재 연결의
current_database()로 조회한다.

Revision ID: 360c8b394406
Revises: ac001a0ab3d9
Create Date: 2026-07-21 19:36:25.214214

"""
import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '360c8b394406'
down_revision: Union[str, None] = 'ac001a0ab3d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "advisor_readonly"
_PASSWORD_ENV = "ADVISOR_READONLY_PASSWORD"
_SAFE_PASSWORD_RE = re.compile(r"^[A-Za-z0-9]{16,64}$")

_PROCESSED_TABLES = (
    "processed_flight_data",
    "processed_acdm_departure",
    "processed_acdm_arrival",
    "processed_fois_departure",
    "processed_fois_arrival",
    "processed_flow_management",
)


def _readonly_password() -> str:
    password = os.environ.get(_PASSWORD_ENV)
    if not password:
        raise RuntimeError(
            f"{_PASSWORD_ENV} 환경변수가 없음 — 저장소 루트 .env에 설정 후 재실행"
        )
    if not _SAFE_PASSWORD_RE.match(password):
        # 영숫자만 허용해 DDL 문자열 조립 시 인젝션 여지를 없앤다(이 값은 role 생성 1회용).
        raise RuntimeError(f"{_PASSWORD_ENV}는 영숫자 16~64자여야 함")
    return password


def _current_database() -> str:
    bind = op.get_bind()
    return bind.execute(sa.text("SELECT current_database()")).scalar()


def upgrade() -> None:
    password = _readonly_password()
    dbname = _current_database()

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_ROLE}') THEN
                CREATE ROLE {_ROLE} LOGIN PASSWORD '{password}';
            END IF;
        END
        $$;
        """
    )
    op.execute(f'GRANT CONNECT ON DATABASE "{dbname}" TO {_ROLE};')
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE};")
    for table in _PROCESSED_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {_ROLE};")


def downgrade() -> None:
    dbname = _current_database()
    for table in _PROCESSED_TABLES:
        op.execute(f"REVOKE SELECT ON {table} FROM {_ROLE};")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_ROLE};")
    op.execute(f'REVOKE CONNECT ON DATABASE "{dbname}" FROM {_ROLE};')
    op.execute(f"DROP ROLE IF EXISTS {_ROLE};")
