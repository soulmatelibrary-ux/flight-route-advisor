"""SQLAlchemy Engine 팩토리. DB 접근을 이 파일로 캡슐화한다(드라이버 교체 지점,
data-ingestion-backend/docs/작업계획서.md §6). 이 앱은 raw/processed 적재를 수행하는
쓰기 엔진이다 — Stage 1(advisor)의 읽기전용 세션(backend/app)과는 별개 프로세스.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from app.config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine
