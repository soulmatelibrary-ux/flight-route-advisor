"""run_ingestion — 업로드 접수 이후의 처리 파이프라인 오케스트레이션(작업계획서.md §5 5~8단계).

트리거(업로드 접수, routers/upload.py)와 실행(이 모듈)을 분리해 둔다 — 향후 업로드 빈도가
늘어 BackgroundTasks를 Celery/RQ로 교체하더라도 이 함수 시그니처만 그대로 큐에 넘기면 된다
(기술스택_결정.md §4-1).

동시에 2개 이상의 run이 겹치지 않도록 프로세스 전역 락으로 순차 처리한다(같은 결론,
§2.6) — Celery 같은 별도 브로커 없이 단일 프로세스(uvicorn worker 1개) 전제로 충분하다.
"""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from app.config import settings
from app.db.session import get_engine
from app.ingestion.loaders import LoaderError, add_log, finish_run, load_processed, mark_running
from app.ingestion.registry import get_descriptor
from app.ingestion.skill_runner import SkillExecutionError, parse_result, run_skill, run_validator

logger = logging.getLogger(__name__)

_PIPELINE_LOCK = threading.Lock()


def run_ingestion(run_id: uuid.UUID, run_type: str, workspace_path: str) -> None:
    """BackgroundTasks가 호출하는 진입점. 예외를 밖으로 던지지 않는다 — 실패는 항상
    ingestion_runs.status/error_message로 기록한다(오류 응답에 내부정보 비노출, docs/06 §8)."""
    engine = get_engine()
    with _PIPELINE_LOCK:
        try:
            mark_running(engine, run_id)
            _run_ingestion_locked(engine, run_id, run_type, Path(workspace_path))
        except Exception:  # noqa: BLE001 - 파이프라인 최상위: mark_running 실패까지 포함해
            # 예상 못 한 예외도 반드시 FAILED로 기록한다(QUEUED에 영원히 멈추는 것을 방지).
            logger.exception("run_ingestion 처리 중 예상하지 못한 예외: run_id=%s", run_id)
            finish_run(
                engine, run_id, "FAILED",
                error_code="UNEXPECTED_ERROR",
                error_message="내부 오류로 처리가 중단됨(상세는 서버 로그 참조)",
            )


def _run_ingestion_locked(engine, run_id: uuid.UUID, run_type: str, workspace: Path) -> None:
    descriptor = get_descriptor(run_type)

    try:
        result = run_skill(descriptor, workspace, settings.source_project_root)
    except SkillExecutionError as exc:
        finish_run(engine, run_id, "FAILED", error_code="SKILL_INVOCATION_ERROR", error_message=str(exc))
        return

    if result.stdout.strip():
        add_log(engine, run_id, "INFO", "stdout", result.stdout[-8000:])
    if result.stderr.strip():
        add_log(engine, run_id, "INFO" if result.succeeded else "ERROR", "stderr", result.stderr[-8000:])

    if not result.succeeded:
        finish_run(
            engine, run_id, "FAILED",
            error_code="SKILL_EXIT_NONZERO",
            error_message=result.stderr[-4000:] or f"종료코드 {result.returncode}",
        )
        return

    try:
        parsed = parse_result(descriptor, result.stdout)
    except SkillExecutionError as exc:
        finish_run(engine, run_id, "FAILED", error_code="RESULT_PARSE_ERROR", error_message=str(exc))
        return

    validation_summary: dict = {}
    if not descriptor.validator.auto_run_by_skill:
        try:
            summary = run_validator(descriptor, parsed, settings.source_project_root)
        except SkillExecutionError as exc:
            finish_run(engine, run_id, "FAILED", error_code="VALIDATOR_INVOCATION_ERROR", error_message=str(exc))
            return
        validation_summary = summary.detail
        add_log(engine, run_id, "INFO" if summary.status == "PASS" else "ERROR", "validation", str(summary.detail)[:8000])
        if summary.status != "PASS":
            finish_run(engine, run_id, "VALIDATION_FAILED", validation_summary=validation_summary)
            return
    else:
        # ACDM: 메인 스크립트가 검증기를 자동 실행해 실패 시 이미 위에서 SKILL_EXIT_NONZERO로
        # 처리됨. 성공 종료코드 자체가 검증 통과 신호이므로 stdout에 포함된 validation 객체를
        # 그대로 기록만 한다.
        validation_summary = parsed.get("validation", {}) if isinstance(parsed.get("validation"), dict) else {}

    output_paths = {key: parsed[key] for key in descriptor.result.keys if key in parsed}
    try:
        load_processed(engine, descriptor, run_id, output_paths)
    except LoaderError as exc:
        finish_run(
            engine, run_id, "FAILED",
            error_code="PROCESSED_LOAD_ERROR",
            error_message=str(exc),
            validation_summary=validation_summary,
        )
        return

    finish_run(engine, run_id, "SUCCESS", output_paths=output_paths, validation_summary=validation_summary)
