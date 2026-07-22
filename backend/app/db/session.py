"""읽기전용 SQLAlchemy Engine (docs/02-db-integration.md §6).

이 서비스는 전처리 DB의 읽기 전용 소비자다. `advisor_readonly` role(테이블 명시
GRANT, data-ingestion-backend alembic `360c8b394406_*`)로만 접속하고, 그 위에
커넥션 레벨 read-only 트랜잭션까지 걸어 이중으로 쓰기를 막는다(role 권한 누락·오설정
시에도 앱 레벨에서 막히도록 하는 defense-in-depth — docs/06-conventions.md §3).
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from app.config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args = {}
        if settings.db_ssl_mode:
            connect_args["sslmode"] = settings.db_ssl_mode
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            connect_args=connect_args,
        ).execution_options(postgresql_readonly=True)
    return _engine
