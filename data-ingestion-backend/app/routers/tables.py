"""테이블 전체 조회 페이지 — run 하나에 매인 게 아니라 raw_*_rows/processed_* 13종
전체를 run과 무관하게 훑어볼 수 있게 한다(사용자 요청: DB 클라이언트 없이 이 앱만으로
적재된 각 테이블을 확인). run 상세 페이지의 `/runs/{id}/data/{table}`(run 하나로 범위
한정, 화이트리스트도 그 run_type 것만)와 달리 여기는 테이블 자체가 화이트리스트다.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Iterator
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.db.column_map import PROCESSED_COLUMNS, RAW_TABLE_COLUMNS, COLUMN_DESCRIPTIONS
from app.db.models import PROCESSED_TABLES, RAW_ROW_TABLES
from app.db.session import get_engine

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_DATA_PAGE_SIZE_DEFAULT = 50
_DATA_PAGE_SIZE_MAX = 200
_CSV_EXPORT_CHUNK_SIZE = 5000

# run과 무관한 전체 목록이라 화이트리스트는 이 앱이 아는 테이블 전부(13종) — run_type별
# 제한은 여기서 의미가 없다(어차피 전체를 보여주는 게 목적).
_ALL_TABLES: dict[str, bool] = {**{name: True for name in RAW_ROW_TABLES}, **{name: False for name in PROCESSED_TABLES}}


def _resolve_table(table_name: str):
    if table_name not in _ALL_TABLES:
        raise HTTPException(404, f"알 수 없는 테이블: {table_name!r}")
    is_raw = _ALL_TABLES[table_name]
    table = RAW_ROW_TABLES[table_name] if is_raw else PROCESSED_TABLES[table_name]
    pairs = RAW_TABLE_COLUMNS[table_name] if is_raw else PROCESSED_COLUMNS[table_name]
    return table, pairs, is_raw


@router.get("/tables", response_class=HTMLResponse)
def list_tables(request: Request) -> HTMLResponse:
    engine = get_engine()
    rows = []
    with engine.connect() as conn:
        for name, is_raw in sorted(_ALL_TABLES.items()):
            table = RAW_ROW_TABLES[name] if is_raw else PROCESSED_TABLES[name]
            count = conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            rows.append({"name": name, "is_raw": is_raw, "count": count})
    return templates.TemplateResponse("tables.html", {"request": request, "tables": rows})


@router.get("/tables/{table_name}", response_class=HTMLResponse)
def table_data(
    request: Request, table_name: str, page: int = 1, page_size: int = _DATA_PAGE_SIZE_DEFAULT,
    run_id: UUID | None = None, partial: bool = False,
) -> HTMLResponse:
    """run과 무관하게 이 테이블의 전체 행을 페이지 단위로 보여준다. run_id 쿼리파라미터로
    특정 run만 좁혀볼 수도 있다(선택). partial=1이면 /tables 탭 UI가 fetch로 불러오는
    조각(제목·nav·스타일시트 없는 본문)만 렌더링한다(사용자 요청: 테이블 클릭 시 페이지
    이동 없이 바로 표시) — 사람이 브라우저로 직접 열어보는 용도가 아니라 tables.js
    전용이다."""
    table, pairs, is_raw = _resolve_table(table_name)
    engine = get_engine()

    page = max(page, 1)
    page_size = min(max(page_size, 1), _DATA_PAGE_SIZE_MAX)

    conds = [table.c.run_id == run_id] if run_id else []

    with engine.connect() as conn:
        total = conn.execute(sa.select(sa.func.count()).select_from(table).where(*conds)).scalar_one()
        rows = conn.execute(
            sa.select(table)
            .where(*conds)
            .order_by(table.c.id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).mappings().all()

    total_pages = max((total + page_size - 1) // page_size, 1)
    columns = [
        {
            "logical": logical,
            "physical": physical,
            "description": COLUMN_DESCRIPTIONS.get(physical, "")
        } for logical, physical in pairs
    ]

    template_name = "_table_data_content.html" if partial else "table_data.html"
    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "table_name": table_name,
            "is_raw": is_raw,
            "columns": columns,
            "rows": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "run_id": run_id,
            "partial": partial,
        },
    )


@router.get("/tables/{table_name}/download.csv")
def download_table_csv(table_name: str, run_id: UUID | None = None) -> StreamingResponse:
    """이 테이블 전체(또는 run_id로 좁힌 부분)를 CSV로 내려받는다. run_data.download_data_csv와
    동일하게 REPEATABLE READ 한 트랜잭션 + 커서 페이지네이션으로 스트리밍한다(동시 삭제로
    인한 조용한 중도절단 방지, 코드리뷰 2026-07-21)."""
    table, pairs, is_raw = _resolve_table(table_name)
    engine = get_engine()

    header = (["run_id", "source_row_number"] if is_raw else ["run_id"]) + [logical for logical, _ in pairs] + (
        ["extra_columns"] if is_raw else []
    )
    physical_cols = [physical for _, physical in pairs]
    conds = [table.c.run_id == run_id] if run_id else []

    def _rows() -> Iterator[str]:
        buf = io.StringIO()
        buf.write("﻿")
        writer = csv.writer(buf)
        writer.writerow(header)
        yield buf.getvalue()

        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
            last_id = 0
            while True:
                chunk = conn.execute(
                    sa.select(table)
                    .where(*conds, table.c.id > last_id)
                    .order_by(table.c.id)
                    .limit(_CSV_EXPORT_CHUNK_SIZE)
                ).mappings().all()
                if not chunk:
                    break
                buf = io.StringIO()
                writer = csv.writer(buf)
                for r in chunk:
                    extra = json.dumps(r["extra_columns"], ensure_ascii=False) if is_raw else None
                    line = (
                        [r["run_id"]] + ([r["source_row_number"]] if is_raw else [])
                        + [r[c] for c in physical_cols]
                        + ([extra] if is_raw else [])
                    )
                    writer.writerow(line)
                yield buf.getvalue()
                last_id = chunk[-1]["id"]

    filename = f"{table_name}.csv"
    return StreamingResponse(
        _rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
