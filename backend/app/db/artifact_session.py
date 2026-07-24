"""쓰기 SQLAlchemy Engine — odr2/flow 배치 산출물 전용(docs/02-db-integration.md §4.3).

`advisor_artifact_writer` role(신규 테이블 12종에만 GRANT, data-ingestion-backend alembic
`d4f7a91c3e26_*`)로만 접속한다. `db/session.py`(읽기전용, `advisor_readonly`)와는 완전히
분리된 별도 연결이다 — 최소권한 원칙상 API 프로세스(main.py 이하)는 이 엔진을 쓰지 않고,
`backend/batch/{build_odr2,build_flow}.py`만 임포트한다.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from app.config import ConfigError, settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        if not settings.advisor_artifact_database_url:
            raise ConfigError(
                "ADVISOR_ARTIFACT_DATABASE_URL 미설정 — 배치 전용 쓰기 env, "
                ".env.example 참고(docs/08-setup-and-dev-order.md §1)"
            )
        connect_args = {}
        if settings.db_ssl_mode:
            connect_args["sslmode"] = settings.db_ssl_mode
        _engine = create_engine(
            settings.advisor_artifact_database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            connect_args=connect_args,
        )
    return _engine
