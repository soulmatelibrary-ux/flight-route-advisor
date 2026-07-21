"""로그 조회 페이지 (작업계획서.md §5 9단계, §6).

GET /runs(목록·상태뱃지), GET /runs/{id}(입력파일·검증요약·실패로그·다운로드),
GET /runs/{id}/download/{artifact}(최종 CSV/검증 JSON 다운로드).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db.models import ingestion_logs, ingestion_run_files, ingestion_runs, raw_files
from app.db.session import get_engine

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/runs", response_class=HTMLResponse)
def list_runs(request: Request) -> HTMLResponse:
    stmt = sa.select(ingestion_runs).order_by(ingestion_runs.c.started_at.desc().nulls_first())
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return templates.TemplateResponse("runs.html", {"request": request, "runs": rows})


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

    return templates.TemplateResponse(
        "run_detail.html",
        {"request": request, "run": run, "input_files": input_files, "logs": logs},
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


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
