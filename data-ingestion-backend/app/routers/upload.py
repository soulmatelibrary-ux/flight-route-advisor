"""업로드 폼 페이지 + 접수 API (작업계획서.md §5 1~4단계).

입력검증(확장자/필수·쌍요건)은 `workspace_builder.build_workspace`에 위임한다(단일 출처,
서술자 기반). 여기서는 그 앞단(용량 제한·XLSX 압축폭탄·저장)과 그 뒤(run 생성·raw 적재·
BackgroundTasks 트리거)만 다룬다.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.session import get_engine
from app.ingestion.constants import AIRPORT_KO_TO_ICAO
from app.ingestion.loaders import (
    LoaderError,
    create_run,
    find_active_run_by_idempotency_key,
    finish_run,
    load_raw,
)
from app.ingestion.pipeline import run_ingestion
from app.ingestion.registry import get_descriptor
from app.ingestion.workspace_builder import UploadedFile, WorkspaceBuildError, build_workspace

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_RUN_TYPES = ("flight_data", "acdm", "fois", "flow_management")

# XLSX(zip) 압축 해제 후 크기 상한 — 원본 크기 제한(MAX_UPLOAD_MB)만으로는 decompression
# bomb을 막지 못한다(docs/06-conventions.md §8 "업로드 폭탄"). zip 중앙 디렉터리의 file_size는
# 공격자가 조작할 수 있으므로 신뢰하지 않고, 실제로 스트리밍 압축 해제하며 누적 바이트가
# 상한을 넘는 즉시 중단한다(전체를 다 풀지 않음).
_MAX_XLSX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
_MAX_XLSX_ZIP_ENTRIES = 20_000

# 요청 전체(여러 파일 합산) 상한 — 개별 파일 상한만으로는 슬롯당 파일을 아주 많이 붙여
# 총량을 우회할 수 있다.
_MAX_TOTAL_REQUEST_MB = 20 * settings.max_upload_mb


@router.get("/", response_class=HTMLResponse)
def upload_form(request: Request) -> HTMLResponse:
    descriptors = {rt: get_descriptor(rt) for rt in _RUN_TYPES}
    return templates.TemplateResponse(
        "upload.html",
        {
            "request": request,
            "run_types": _RUN_TYPES,
            "descriptors": descriptors,
            "airports": tuple(AIRPORT_KO_TO_ICAO),
            "max_upload_mb": settings.max_upload_mb,
        },
    )


@router.post("/uploads")
async def create_upload(request: Request, background_tasks: BackgroundTasks):
    # Content-Length 선검사 — request.form()이 본문 전체를 디스크에 스풀하기 전에, 선언된
    # 총 크기가 명백히 과도하면 즉시 거부한다(청크 전송처럼 Content-Length가 없는 요청까지
    # 막지는 못하지만, 흔한 경우의 조기 차단은 된다).
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_TOTAL_REQUEST_MB * 1024 * 1024:
                raise HTTPException(413, f"요청 본문이 너무 큼(최대 {_MAX_TOTAL_REQUEST_MB}MB)")
        except ValueError:
            pass

    form = await request.form()
    try:
        return await _handle_upload(request, background_tasks, form)
    finally:
        await form.close()


async def _handle_upload(request: Request, background_tasks: BackgroundTasks, form):
    run_type = form.get("run_type")
    if run_type not in _RUN_TYPES:
        raise HTTPException(400, f"알 수 없는 처리유형: {run_type!r} (허용: {_RUN_TYPES})")

    descriptor = get_descriptor(run_type)
    engine = get_engine()

    idempotency_key = _clean_str(form.get("idempotency_key"))
    if idempotency_key:
        existing = find_active_run_by_idempotency_key(engine, idempotency_key)
        if existing:
            return RedirectResponse(f"/runs/{existing}", status_code=303)

    triggered_by = _clean_str(form.get("triggered_by")) or "web-operator"
    meta = {
        "airport_ko": _clean_str(form.get("airport_ko")) or "",
        "date": _clean_str(form.get("date")) or "",
    }
    meta = {k: v for k, v in meta.items() if v}

    tmp_dir = Path(tempfile.mkdtemp(prefix="upload-", dir=settings.workspace_root))
    ws: Path | None = None
    try:
        uploaded_files = await _collect_uploaded_files(descriptor, form, tmp_dir)

        try:
            ws = build_workspace(
                descriptor, uploaded_files, meta, settings.workspace_root, settings.source_project_root
            )
        except WorkspaceBuildError as exc:
            raise HTTPException(400, str(exc)) from exc

        try:
            run_id = create_run(
                engine, run_type, triggered_by=triggered_by,
                workspace_path=str(ws), idempotency_key=idempotency_key,
            )
        except IntegrityError:
            # idempotency_key 부분 unique 인덱스 위반 — 동시에 같은 키로 두 요청이 들어와
            # 이 시점에야 충돌이 드러난 경우(위의 조회는 check-then-act라 완전한 방어가 아님).
            # 이미 만들어진 workspace는 어느 run에도 연결되지 않으므로 정리한다.
            existing = idempotency_key and find_active_run_by_idempotency_key(engine, idempotency_key)
            if existing:
                if ws is not None:
                    shutil.rmtree(ws, ignore_errors=True)
                return RedirectResponse(f"/runs/{existing}", status_code=303)
            raise HTTPException(409, "동일 재시도 키로 처리 중인 요청과 충돌함, 잠시 후 다시 시도") from None

        try:
            load_raw(engine, descriptor, run_id, uploaded_files)
        except LoaderError as exc:
            finish_run(engine, run_id, "FAILED", error_code="RAW_LOAD_ERROR", error_message=str(exc))
            raise HTTPException(400, f"원본 적재 실패: {exc}") from exc
    except Exception:
        if ws is not None:
            shutil.rmtree(ws, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    background_tasks.add_task(run_ingestion, run_id, run_type, str(ws))
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


def _clean_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def _collect_uploaded_files(descriptor, form, tmp_dir: Path) -> list[UploadedFile]:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    total_max_bytes = _MAX_TOTAL_REQUEST_MB * 1024 * 1024
    total_so_far = 0
    uploaded_files: list[UploadedFile] = []
    for slot in descriptor.upload_slots:
        for upload_file in form.getlist(slot.key):
            if not hasattr(upload_file, "filename") or not upload_file.filename:
                continue
            original_filename = upload_file.filename
            dest = tmp_dir / f"{uuid.uuid4().hex}{Path(original_filename).suffix}"
            size, total_so_far = await _stream_to_file(
                upload_file, dest, max_bytes, total_so_far, total_max_bytes, original_filename
            )
            if dest.suffix.lower() == ".xlsx":
                _check_xlsx_safe(dest, original_filename)
            uploaded_files.append(
                UploadedFile(slot_key=slot.key, source_path=dest, original_filename=original_filename)
            )
            del size
    if not uploaded_files:
        raise HTTPException(400, "업로드된 파일이 없음")
    return uploaded_files


async def _stream_to_file(
    upload_file, dest: Path, max_bytes: int, total_so_far: int, total_max_bytes: int, original_filename: str
) -> tuple[int, int]:
    total = 0
    with dest.open("wb") as out:
        while chunk := await upload_file.read(1024 * 1024):
            total += len(chunk)
            total_so_far += len(chunk)
            if total > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    400, f"업로드 용량 초과: {original_filename!r} (최대 {max_bytes // (1024 * 1024)}MB)"
                )
            if total_so_far > total_max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"요청 전체 업로드 용량 초과(최대 {total_max_bytes // (1024 * 1024)}MB)")
            out.write(chunk)
    return total, total_so_far


def _check_xlsx_safe(path: Path, original_filename: str) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_XLSX_ZIP_ENTRIES:
                raise HTTPException(400, f"XLSX 내부 파일 수가 너무 많음: {original_filename!r}")
            total = 0
            for info in infos:
                with zf.open(info) as member:
                    while chunk := member.read(1024 * 1024):
                        total += len(chunk)
                        if total > _MAX_XLSX_UNCOMPRESSED_BYTES:
                            raise HTTPException(
                                400, f"XLSX 압축 해제 크기가 상한을 초과함: {original_filename!r}"
                            )
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, f"손상되었거나 XLSX 형식이 아님: {original_filename!r}") from exc
