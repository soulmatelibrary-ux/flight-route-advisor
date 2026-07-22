"""읽기전용 SQLAlchemy Core Table 리플렉션 (docs/05 §1).

스키마 소유자는 data-ingestion-backend(Alembic)이므로 이 앱은 컬럼 타입을 다시
정의하지 않고 실제 DB에서 리플렉션한다(드리프트 방지).

주의: SQLAlchemy의 Postgres 리플렉션은 `pg_catalog`를 직접 조회해 **컬럼 단위 GRANT와
무관하게 테이블의 모든 컬럼 이름을 되돌려준다**(information_schema.columns와 달리
권한으로 필터링되지 않음 — 실측 확인, 2026-07-22: advisor_readonly로 리플렉션해도
ingestion_runs의 16개 컬럼이 전부 보임). 그래서 `include_columns`로 `column_map.py`
화이트리스트만 리플렉션해 `.c`에 애초에 담기지 않게 한다 — 이후 실제 SELECT 시도는
여전히 DB GRANT로도 막히지만(defense-in-depth), 앱 코드가 화이트리스트 밖 컬럼을
속성으로조차 참조할 수 없게 하는 것이 1차 방어선이다(docs/06-conventions.md §8).
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from app.db import column_map
from app.db.session import get_engine

metadata = MetaData()

_tables: dict[str, Table] | None = None


def _reflect_all() -> dict[str, Table]:
    engine = get_engine()
    tables: dict[str, Table] = {}
    for name, expected_columns in column_map.TABLE_WHITELIST.items():
        # resolve_fks=False: processed_*의 run_id FK가 ingestion_runs를 자동으로
        # "전체 컬럼"으로 먼저 리플렉션해 metadata에 캐싱해버리면, 뒤이은
        # include_columns 제한이 무시된다(이미 캐싱된 Table을 그대로 반환) —
        # 실측으로 확인한 문제(2026-07-22). 조인은 SQL에서 직접 명시하므로
        # SQLAlchemy의 FK 자동 리플렉션이 필요 없다.
        table = Table(
            name,
            metadata,
            autoload_with=engine,
            include_columns=expected_columns,
            resolve_fks=False,
        )
        reflected_columns = set(table.c.keys())
        missing = set(expected_columns) - reflected_columns
        if missing:
            raise RuntimeError(
                f"{name}: column_map.py가 기대하는 컬럼이 DB에 없음: {sorted(missing)} "
                "(전처리 스키마 변경 여부를 DB스키마.md와 대조할 것)"
            )
        tables[name] = table
    return tables


def get_tables() -> dict[str, Table]:
    global _tables
    if _tables is None:
        _tables = _reflect_all()
    return _tables


def get_table(name: str) -> Table:
    if name not in column_map.TABLE_WHITELIST:
        raise ValueError(f"허용되지 않은 테이블: {name}")
    return get_tables()[name]
