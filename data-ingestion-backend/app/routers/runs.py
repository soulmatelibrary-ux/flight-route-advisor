"""로그 조회 페이지 (작업계획서.md §5 9단계, §6).

GET /runs(목록·상태뱃지), GET /runs/{id}(입력파일·검증요약·실패로그·다운로드),
GET /runs/{id}/download/{artifact}(최종 CSV/검증 JSON 다운로드).
"""

from __future__ import annotations

import csv
import hmac
import io
from pathlib import Path
from typing import Iterator
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db.column_map import PROCESSED_COLUMNS, RAW_TABLE_COLUMNS
from app.db.models import (
    PROCESSED_TABLES,
    RAW_ROW_TABLES,
    ingestion_logs,
    ingestion_run_files,
    ingestion_runs,
    raw_files,
)
from app.db.session import get_engine
from app.ingestion.loaders import LoaderError, delete_run
from app.ingestion.registry import get_descriptor

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# ingestion_runs는 append-only라 무제한으로 누적된다. LIMIT 없이 전체를 조회하면 run이
# 쌓일수록 쿼리·렌더링이 선형으로 느려지므로(코드리뷰 2026-07-21 발견), 로그 조회 페이지
# 목적(최근 상태 확인)에 맞게 최근 N건만 노출한다.
_RUN_LIST_LIMIT = 200
_DATA_PAGE_SIZE_DEFAULT = 50
_DATA_PAGE_SIZE_MAX = 200
_CSV_EXPORT_CHUNK_SIZE = 5000


def _tables_for_run_type(run_type: str) -> dict[str, bool]:
    """이 run_type이 실제로 쓰는 테이블명만 화이트리스트로 반환한다(값: raw 테이블 여부).

    /runs/{id}/data/{table_name}이 임의 테이블명을 받아 그대로 조회하면 이 앱이 아는 모든
    테이블(다른 run_type 것 포함)을 조회할 수 있게 되므로, run_type의 SkillDescriptor가
    선언한 테이블로만 제한한다(경로주입은 아니지만 동일한 "신뢰 못 할 입력으로 임의 리소스
    접근" 부류라 화이트리스트로 막는다, docs/06-conventions.md §8).
    """
    descriptor = get_descriptor(run_type)
    tables: dict[str, bool] = {name: True for name in descriptor.raw_tables}
    tables.update({output.table: False for output in descriptor.outputs})
    return tables


@router.get("/runs", response_class=HTMLResponse)
def list_runs(request: Request) -> HTMLResponse:
    stmt = (
        sa.select(ingestion_runs)
        .order_by(ingestion_runs.c.started_at.desc().nulls_first())
        .limit(_RUN_LIST_LIMIT)
    )
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return templates.TemplateResponse(
        "runs.html", {"request": request, "runs": rows, "run_list_limit": _RUN_LIST_LIMIT}
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: UUID) -> HTMLResponse:
    engine = get_engine()
    with engine.connect() as conn:
        run = conn.execute(
            sa.select(ingestion_runs).where(ingestion_runs.c.id == run_id)
        ).mappings().first()
        if run is None:
            raise HTTPException(404, "run을 찾을 수 없음")

        input_files = conn.execute(
            sa.select(raw_files.c.original_filename, raw_files.c.file_type, raw_files.c.row_count, raw_files.c.uploaded_at)
            .select_from(ingestion_run_files.join(raw_files, ingestion_run_files.c.raw_file_id == raw_files.c.id))
            .where(ingestion_run_files.c.run_id == run_id)
            .order_by(raw_files.c.uploaded_at)
        ).mappings().all()

        logs = conn.execute(
            sa.select(ingestion_logs).where(ingestion_logs.c.run_id == run_id).order_by(ingestion_logs.c.ts)
        ).mappings().all()

    data_tables = sorted(_tables_for_run_type(run["run_type"]))

    return templates.TemplateResponse(
        "run_detail.html",
        {"request": request, "run": run, "input_files": input_files, "logs": logs, "data_tables": data_tables},
    )


def _resolve_run_table(engine, run_id: UUID, table_name: str):
    """run_id가 실제로 존재하고, table_name이 그 run_type이 쓰는 테이블(화이트리스트)인지
    확인한 뒤 (table, pairs, is_raw)를 반환한다. run_data/download_data_csv가 공유한다.
    """
    with engine.connect() as conn:
        run = conn.execute(
            sa.select(ingestion_runs.c.run_type).where(ingestion_runs.c.id == run_id)
        ).mappings().first()
    if run is None:
        raise HTTPException(404, "run을 찾을 수 없음")

    allowed = _tables_for_run_type(run["run_type"])
    if table_name not in allowed:
        raise HTTPException(404, f"이 run에 속하지 않는 테이블: {table_name!r}")

    is_raw = allowed[table_name]
    table = RAW_ROW_TABLES[table_name] if is_raw else PROCESSED_TABLES[table_name]
    pairs = RAW_TABLE_COLUMNS[table_name] if is_raw else PROCESSED_COLUMNS[table_name]
    return table, pairs, is_raw


@router.get("/runs/{run_id}/data/{table_name}", response_class=HTMLResponse)
def run_data(request: Request, run_id: UUID, table_name: str, page: int = 1, page_size: int = _DATA_PAGE_SIZE_DEFAULT) -> HTMLResponse:
    """이 run이 적재한 raw_*_rows/processed_* 실제 행 데이터를 페이지 단위로 보여준다
    (DataGrip 등 외부 DB 클라이언트 없이도 적재 결과를 바로 확인할 수 있게).
    """
    engine = get_engine()
    table, pairs, is_raw = _resolve_run_table(engine, run_id, table_name)

    page = max(page, 1)
    page_size = min(max(page_size, 1), _DATA_PAGE_SIZE_MAX)

    with engine.connect() as conn:
        total = conn.execute(
            sa.select(sa.func.count()).select_from(table).where(table.c.run_id == run_id)
        ).scalar_one()
        rows = conn.execute(
            sa.select(table)
            .where(table.c.run_id == run_id)
            .order_by(table.c.id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).mappings().all()

    total_pages = max((total + page_size - 1) // page_size, 1)
    columns = [{"logical": logical, "physical": physical} for logical, physical in pairs]

    return templates.TemplateResponse(
        "run_data.html",
        {
            "request": request,
            "run_id": run_id,
            "table_name": table_name,
            "is_raw": is_raw,
            "columns": columns,
            "rows": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/runs/{run_id}/data/{table_name}/download.csv")
def download_data_csv(run_id: UUID, table_name: str) -> StreamingResponse:
    """이 run이 적재한 raw_*_rows/processed_* 테이블 데이터 전체(페이지 제한 없이)를
    CSV로 내려받는다. 대량 행도 메모리에 한번에 올리지 않도록 청크 단위로 스트리밍한다.
    """
    engine = get_engine()
    table, pairs, is_raw = _resolve_run_table(engine, run_id, table_name)

    header = (["source_row_number"] if is_raw else []) + [logical for logical, _ in pairs] + (["extra_columns"] if is_raw else [])
    physical_cols = [physical for _, physical in pairs]

    def _rows() -> Iterator[str]:
        buf = io.StringIO()
        buf.write("﻿")  # BOM — 이 저장소의 다른 CSV 산출물과 동일하게 Excel 한글 호환
        writer = csv.writer(buf)
        writer.writerow(header)
        yield buf.getvalue()

        offset = 0
        while True:
            with engine.connect() as conn:
                chunk = conn.execute(
                    sa.select(table)
                    .where(table.c.run_id == run_id)
                    .order_by(table.c.id)
                    .limit(_CSV_EXPORT_CHUNK_SIZE)
                    .offset(offset)
                ).mappings().all()
            if not chunk:
                break
            buf = io.StringIO()
            writer = csv.writer(buf)
            for r in chunk:
                line = ([r["source_row_number"]] if is_raw else []) + [r[c] for c in physical_cols] + (
                    [r["extra_columns"]] if is_raw else []
                )
                writer.writerow(line)
            yield buf.getvalue()
            offset += _CSV_EXPORT_CHUNK_SIZE

    filename = f"{table_name}_{run_id}.csv"
    return StreamingResponse(
        _rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/runs/{run_id}/download/{artifact}")
def download_artifact(run_id: UUID, artifact: str):
    engine = get_engine()
    with engine.connect() as conn:
        run = conn.execute(
            sa.select(ingestion_runs.c.workspace_path, ingestion_runs.c.output_paths).where(
                ingestion_runs.c.id == run_id
            )
        ).mappings().first()
    if run is None:
        raise HTTPException(404, "run을 찾을 수 없음")

    output_paths = run["output_paths"] or {}
    if artifact not in output_paths:
        raise HTTPException(404, f"다운로드 가능한 산출물이 아님: {artifact!r}")

    path = Path(output_paths[artifact])
    workspace_path = run["workspace_path"]
    # 다운로드 대상은 이 run 자신의 workspace 하위여야 한다(경로주입/임의 파일 읽기 방지,
    # docs/06-conventions.md §8) — output_paths는 스킬 stdout에서 온 값이라 별도 신뢰 경계.
    if workspace_path is None or not _is_within(path, Path(workspace_path)):
        raise HTTPException(400, "잘못된 다운로드 경로")
    if not path.is_file():
        raise HTTPException(404, "산출 파일이 존재하지 않음")

    return FileResponse(path, filename=path.name)


@router.post("/runs/{run_id}/delete")
def delete_run_route(run_id: UUID, deleted_by: str = Form(...), admin_token: str = Form(...)):
    """run 삭제(재입력 전 정리) — SUCCESS/VALIDATION_FAILED/FAILED terminal 상태만 가능하다.
    run 메타데이터·로그는 감사 기록으로 남고, raw_*_rows/processed_*/아카이브 파일만 지운다.

    이 앱 전체에 인증이 없어(코드리뷰 2026-07-21 발견) 되돌릴 수 없는 삭제만은 별도
    최소 게이트를 둔다 — INGESTION_DELETE_TOKEN이 설정돼 있어야 하고(미설정 시 삭제
    기능 자체 비활성화, fail-closed), 폼에 그 토큰을 정확히 입력해야 한다.
    """
    if not settings.delete_token:
        raise HTTPException(503, "삭제 기능이 비활성화됨(INGESTION_DELETE_TOKEN 미설정)")
    if not hmac.compare_digest(admin_token, settings.delete_token):
        raise HTTPException(403, "삭제 토큰이 올바르지 않음")

    deleted_by = deleted_by.strip()
    if not deleted_by:
        raise HTTPException(400, "삭제자(deleted_by)를 입력해야 함")
    try:
        delete_run(get_engine(), run_id, deleted_by=deleted_by)
    except LoaderError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
