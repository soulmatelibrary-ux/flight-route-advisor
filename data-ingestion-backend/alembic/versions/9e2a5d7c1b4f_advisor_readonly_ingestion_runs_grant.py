"""advisor_readonly ingestion_runs column grant

근거: docs/02-db-integration.md §3·§6 "최신본 뷰" 규약 — Stage 1(advisor)이
processed_*를 조회할 때 run_type/status/finished_at 기준으로 ingestion_runs와
조인해야 하는데, `360c8b394406`(advisor_readonly role 생성)은 processed_* 6종에만
SELECT를 부여하고 ingestion_runs는 빠뜨렸다(실측: advisor_readonly로 SELECT 시
permission denied 확인). §6 예시 SQL은 "필요한 최소 컬럼만" GRANT하라고 명시하므로
테이블 전체가 아니라 조인/필터/정렬에 실제로 쓰는 컬럼만 컬럼 단위로 연다 —
workspace_path·cli_command·error_message 등 서버 내부 경로/오류 상세는 제외
(docs/06-conventions.md §8 "오류 응답에 내부 구현 비노출").

Revision ID: 9e2a5d7c1b4f
Revises: 7c1e4a9b2f6d
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9e2a5d7c1b4f'
down_revision: Union[str, None] = '7c1e4a9b2f6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "advisor_readonly"
_COLUMNS = ("id", "run_type", "status", "finished_at", "validation_summary")


def upgrade() -> None:
    op.execute(
        f"GRANT SELECT ({', '.join(_COLUMNS)}) ON ingestion_runs TO {_ROLE};"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT ({', '.join(_COLUMNS)}) ON ingestion_runs FROM {_ROLE};"
    )
