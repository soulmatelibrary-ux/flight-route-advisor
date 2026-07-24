#!/usr/bin/env python3
"""SUAS/MOA(특수공역) 사전빌드 JSON → `reference_suas` DB 테이블 1회 이관.

`PORTING_PACKAGE_ROOT/사전빌드_JSON/{suas,suas_world}.json`을 읽어 `app.db.reference_tables`
(단일 출처) 스키마에 맞춰 truncate-and-reload한다. 두 파일은 완성본 빌드 파이프라인이 DAFIF
원본(SUAS_PAR.TXT/SUAS.TXT, 세그먼트+SHAP 코드 기반 원시 지오메트리)을 이미 폴리곤으로 풀어놓은
산출물이라 이 스크립트는 원시 DAFIF 텍스트를 다시 파싱하지 않는다. `suas.json`(한국)과
`suas_world.json`(세계)은 ident 기준 완전히 겹치지 않는 별도 데이터라 `region` 컬럼으로
태깅해 한 테이블에 합친다(중복 제거 불필요).

`scripts/migrate_static_reference_to_db.py`(다른 세션이 동시에 작업 중)와 별도 파일로 분리해
편집 충돌을 피한다 — 로직은 그 스크립트와 동일한 truncate-and-reload 패턴.

사용법: python scripts/migrate_suas_to_db.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, insert  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.reference_tables import reference_suas  # noqa: E402
from app.db.session import get_engine  # noqa: E402

_SOURCES: tuple[tuple[str, str], ...] = (
    ("kr", "suas.json"),
    ("world", "suas_world.json"),
)


def _load_json(filename: str) -> list:
    path = settings.porting_package_root / "사전빌드_JSON" / filename
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _to_pairs(flat: list[float]) -> list[list[float]]:
    return [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]


def _build_suas_rows() -> list[dict]:
    rows = []
    for region, filename in _SOURCES:
        for ident, name, type_, upper, lower, flat in _load_json(filename):
            rows.append(
                {
                    "ident": ident,
                    "name": name,
                    "type": type_,
                    "upper": upper,
                    "lower": lower,
                    "polygon": _to_pairs(flat),
                    "region": region,
                }
            )
    return rows


def main() -> None:
    rows = _build_suas_rows()
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(delete(reference_suas))
        if rows:
            conn.execute(insert(reference_suas), rows)
    print(f"{reference_suas.name}: {len(rows)}행 적재")


if __name__ == "__main__":
    main()
