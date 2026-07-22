"""CSV/원본 파일 → DB 적재 (Phase 4 raw, Phase 5 processed).

`column_map.py`(단일 출처)를 그대로 따라 DataFrame 컬럼을 물리 컬럼으로 매핑한다. raw
계층은 "계약 컬럼(TEXT) + 여분 컬럼(JSONB)" 하이브리드(DB스키마.md §1) — 계약에 없는
나머지 컬럼은 모두 `extra_columns`로 흡수해, 원본 실제 헤더가 문서 요약과 달라도(실측으로
여러 건 확인됨) 데이터 손실이 없다. raw 적재와 processed 적재는 별도 트랜잭션이다(§8-3) —
단, 한 run이 다루는 여러 파일/출력은 각각 하나의 트랜잭션으로 묶어 부분 커밋을 막는다.
"""

from __future__ import annotations

import hashlib
import math
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging

import pandas as pd
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

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
from app.ingestion.constants import (
    ACDM_DATE_SUFFIX_RE,
    DATE_YYYYMMDD_RE,
    FLOW_MANAGEMENT_HEADER_SCAN_ROWS,
    FLOW_MANAGEMENT_HEADER_TOKENS,
    FOIS_SOURCE_COLUMNS,
)
from app.ingestion.registry import SkillDescriptor, UploadSlot
from app.ingestion.workspace_builder import UploadedFile

# raw/processed 문자열 셀은 원본 충실도 우선 — 빈 문자열만 결측으로 취급하고, 그 외 pandas
# 기본 NA 토큰("NA","N/A" 등)은 문자 그대로 보존한다(docs/06-conventions.md §7 원본 충실도 계승).
_READ_CSV_KW = {"dtype": "string", "keep_default_na": False, "na_values": [""]}

logger = logging.getLogger(__name__)


class LoaderError(RuntimeError):
    """적재 실패. 메시지에 자격증명 등 민감정보를 담지 않는다."""


# --- run 수명주기 (상태 전이: QUEUED -> RUNNING -> SUCCESS|VALIDATION_FAILED|FAILED,
#     DB스키마.md §8. 종료 상태에서 역전이는 이 모듈이 강제하지 않고 DB CHECK가 최종 방어선) ---


def create_run(
    engine: Engine,
    run_type: str,
    triggered_by: str,
    workspace_path: str | None = None,
    idempotency_key: str | None = None,
) -> uuid.UUID:
    """새 run을 QUEUED로 생성한다. RUNNING 전이는 pipeline.py가 실제 처리를 시작할 때 한다."""
    run_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(ingestion_runs),
            [
                {
                    "id": run_id,
                    "run_type": run_type,
                    "status": "QUEUED",
                    "triggered_by": triggered_by,
                    "workspace_path": workspace_path,
                    "idempotency_key": idempotency_key,
                }
            ],
        )
    return run_id


def find_active_run_by_idempotency_key(engine: Engine, idempotency_key: str) -> uuid.UUID | None:
    """같은 idempotency_key로 QUEUED/RUNNING/SUCCESS인 run이 있으면 그 id를 반환한다
    (기술스택_결정.md §5-2 — 동일 요청 재시도 시 중복 run 생성 방지)."""
    stmt = select(ingestion_runs.c.id).where(
        ingestion_runs.c.idempotency_key == idempotency_key,
        ingestion_runs.c.status.in_(("QUEUED", "RUNNING", "SUCCESS")),
    )
    with engine.connect() as conn:
        row = conn.execute(stmt).first()
    return row.id if row else None


def recover_interrupted_runs(engine: Engine) -> list[uuid.UUID]:
    """앱 기동 시 1회 호출한다. run 진행 상태는 프로세스 메모리 `BackgroundTasks`로만
    관리되므로(pipeline.py), 이전 프로세스가 QUEUED/RUNNING을 남긴 채 죽으면(재시작/OOM)
    그 run은 영원히 처리중으로 고착되고 삭제도 불가능해진다(terminal 상태만 삭제 가능,
    `_DELETABLE_STATUSES`). 재개를 시도하지 않고 FAILED로 확정해, 운영자가 원인 확인 후
    같은 데이터를 재업로드하도록 유도한다(리뷰 2026-07-22 B-3).
    """
    with engine.begin() as conn:
        stale_ids = conn.execute(
            select(ingestion_runs.c.id).where(ingestion_runs.c.status.in_(("QUEUED", "RUNNING")))
        ).scalars().all()
        if stale_ids:
            conn.execute(
                update(ingestion_runs)
                .where(ingestion_runs.c.id.in_(stale_ids))
                .values(
                    status="FAILED",
                    error_code="INTERRUPTED",
                    error_message="서버 재시작으로 처리가 중단됨(재업로드 필요)",
                    finished_at=datetime.now(timezone.utc),
                )
            )
    return stale_ids


def mark_running(engine: Engine, run_id: uuid.UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(ingestion_runs)
            .where(ingestion_runs.c.id == run_id)
            .values(status="RUNNING", started_at=datetime.now(timezone.utc))
        )


def finish_run(engine: Engine, run_id: uuid.UUID, status: str, **extra: Any) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(ingestion_runs)
            .where(ingestion_runs.c.id == run_id)
            .values(status=status, finished_at=datetime.now(timezone.utc), **extra)
        )


def add_log(engine: Engine, run_id: uuid.UUID, level: str, source: str, message: str) -> None:
    """로그 조회 페이지의 "펼쳐보기"용 상세 로그 한 줄(DB스키마.md §2.3)."""
    with engine.begin() as conn:
        conn.execute(
            insert(ingestion_logs),
            [{"run_id": run_id, "ts": datetime.now(timezone.utc), "level": level, "source": source, "message": message}],
        )


# --- Phase 4: raw 적재 ---


def load_raw(
    engine: Engine,
    descriptor: SkillDescriptor,
    run_id: uuid.UUID,
    uploaded_files: list[UploadedFile],
    meta: dict[str, str] | None = None,
) -> dict[str, int]:
    """업로드 원본 파일을 raw_files + raw_*_rows에 적재한다. 반환: 파일명별 적재 행수.

    파일 하나하나가 아니라 이 run이 다루는 모든 파일을 하나의 트랜잭션으로 묶는다 — 중간
    파일에서 실패하면 이전 파일의 부분 적재도 함께 롤백된다.
    """
    meta = meta or {}
    loaded: dict[str, int] = {}
    with engine.begin() as conn:
        for uploaded in uploaded_files:
            slot = _slot_by_key(descriptor, uploaded.slot_key)
            df = _read_raw_dataframe(descriptor, slot, uploaded)

            raw_file_id = uuid.uuid4()
            stored_relpath = _archive_upload(uploaded, raw_file_id)
            sha256 = _sha256_of(uploaded.source_path)

            try:
                conn.execute(
                    insert(raw_files),
                    [
                        {
                            "id": raw_file_id,
                            "file_type": slot.file_type,
                            "original_filename": uploaded.original_filename,
                            "stored_relpath": stored_relpath,
                            "sha256": sha256,
                            "sheet_name": None,
                            "row_count": len(df),
                        }
                    ],
                )
            except IntegrityError as exc:
                # uq_raw_files_sha256_type_sheet 위반 — 동일 내용 파일이 이미 적재됨(재시도
                # 시나리오 포함). 그대로 두면 IntegrityError가 여기서 새어나가 upload.py의
                # `except LoaderError`에 걸리지 않고 처리되지 않은 500 + run이 QUEUED에
                # 영구 정지한다(코드리뷰 2026-07-21 발견). LoaderError로 통일해 정상 FAILED
                # 전이 경로를 타게 한다.
                raise LoaderError(
                    f"{descriptor.run_type}: 이미 동일한 내용의 파일이 적재됨(중복): "
                    f"{uploaded.original_filename!r}"
                ) from exc
            conn.execute(
                insert(ingestion_run_files),
                [{"run_id": run_id, "raw_file_id": raw_file_id, "role": "input"}],
            )
            records = _build_raw_records(descriptor, slot, df, raw_file_id, run_id, uploaded, meta)
            if records:
                conn.execute(insert(RAW_ROW_TABLES[slot.raw_table]), records)

            loaded[uploaded.original_filename] = len(df)
    return loaded


def _archive_upload(uploaded: UploadedFile, raw_file_id: uuid.UUID) -> str:
    """원본을 서버 생성 파일명으로 `UPLOAD_DIR`에 복사하고, 그 안에서의 상대경로를 반환한다.

    사용자가 올린 파일명을 저장 경로에 그대로 쓰지 않는다(경로주입 방지, docs/06 §8).
    원본 파일명은 `raw_files.original_filename`에만 메타로 남긴다.
    """
    dest_name = f"{raw_file_id}{Path(uploaded.original_filename).suffix.lower()}"
    dest_path = settings.upload_dir / dest_name
    shutil.copy2(uploaded.source_path, dest_path)
    return dest_name


def _slot_by_key(descriptor: SkillDescriptor, key: str) -> UploadSlot:
    for slot in descriptor.upload_slots:
        if slot.key == key:
            return slot
    raise LoaderError(f"{descriptor.run_type}에 정의되지 않은 업로드 슬롯: {key!r}")


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_raw_dataframe(descriptor: SkillDescriptor, slot: UploadSlot, uploaded: UploadedFile) -> pd.DataFrame:
    try:
        return _read_raw_dataframe_unsafe(descriptor, slot, uploaded)
    except LoaderError:
        raise
    except Exception as exc:  # pandas/openpyxl이 던지는 다양한 예외를 일관된 타입으로 통일
        # pandas/openpyxl 원본 예외 메시지에는 서버 내부 임시경로가 포함될 수 있어(코드리뷰
        # 2026-07-21 발견) 클라이언트로 나가는 메시지에는 담지 않는다. 상세는 서버 로그에만
        # 남긴다(오류 응답 내부정보 비노출, docs/06-conventions.md §8).
        logger.exception(
            "%s: 원본 파일 파싱 실패: %s", descriptor.run_type, uploaded.original_filename
        )
        raise LoaderError(
            f"{descriptor.run_type}: 원본 파일 파싱 실패(형식 확인 필요, 상세는 서버 로그 참조): "
            f"{uploaded.original_filename!r}"
        ) from exc


def _read_raw_dataframe_unsafe(descriptor: SkillDescriptor, slot: UploadSlot, uploaded: UploadedFile) -> pd.DataFrame:
    # 원본 파일(사용자가 실제로 올린 그대로의 포맷)을 읽는다 — 워크스페이스 배치용으로
    # 변환한 사본이 아니라 항상 `uploaded.source_path`(원본)를 읽어야 raw 계층 원본 충실도가
    # 유지된다(변환은 스킬 입력용일 뿐, DB 적재는 원본 기준).
    suffix = uploaded.source_path.suffix.lower()

    if descriptor.run_type == "flight_data":
        if suffix == ".csv":
            return _read_csv_with_encoding_fallback(uploaded.source_path, **_READ_CSV_KW)
        return pd.read_excel(uploaded.source_path, **_READ_CSV_KW)

    if descriptor.run_type == "fois":
        # 알려진 한계(코드리뷰 2026-07-21): xlsx 원본은 맨 위에 버려지는 행이 있어
        # skiprows=1로 위치 기반으로 건너뛴다(FOIS_SOURCE_COLUMNS 컬럼 순서 계약, 헤더
        # 텍스트가 "지연시간" 중복이라 이름으로는 구분 불가). 이 CSV 분기는 "독립적으로
        # 만들어진 FOIS CSV도 xlsx와 동일하게 맨 위에 버려지는 행이 있다"고 가정한다 —
        # 실제 그런 CSV 원본이 없어 검증하지 못했다. 만약 그 행이 없는 CSV가 들어오면
        # skiprows=1이 진짜 첫 데이터 행을 조용히 삼켜버리고, 열 수는 우연히 17개로
        # 맞아 아래 검증도 통과할 수 있다(행 수만 1 적어짐) — 이 계약이 실제 운영에서
        # 깨지면 열 수 검증이 아니라 값 기반 검증(예: 첫 행이 실제 편명/일자 패턴인지)을
        # 추가해야 한다.
        if suffix == ".csv":
            df = _read_csv_with_encoding_fallback(uploaded.source_path, header=None, skiprows=1, **_READ_CSV_KW)
        else:
            df = pd.read_excel(uploaded.source_path, header=None, skiprows=1, **_READ_CSV_KW)
        if df.shape[1] != len(FOIS_SOURCE_COLUMNS):
            raise LoaderError(
                f"FOIS 원본 열 수가 {len(FOIS_SOURCE_COLUMNS)}개가 아님: {uploaded.original_filename!r} "
                f"({df.shape[1]}열)"
            )
        df.columns = list(FOIS_SOURCE_COLUMNS)
        return df

    if descriptor.run_type == "flow_management":
        if suffix == ".csv":
            return _read_flow_management_raw_csv(uploaded.source_path)
        return _read_flow_management_raw(uploaded.source_path)

    if descriptor.run_type == "acdm":
        if suffix == ".csv":
            return _read_csv_with_encoding_fallback(uploaded.source_path, **_READ_CSV_KW)
        return pd.read_excel(uploaded.source_path, **_READ_CSV_KW)  # .xlsx/.xls(엔진 자동 선택)

    raise LoaderError(f"알 수 없는 run_type: {descriptor.run_type!r}")


# 코드리뷰 2026-07-21 지적: utf-8-sig 고정이라 국내 레거시 관제 시스템이 흔히 쓰는
# CP949/EUC-KR로 뽑은 CSV가 새로 연 CSV 업로드 기능 자체에서 전면 실패했다(처음에는
# FOIS만 수정했으나 4종 CSV 경로 전부 같은 문제라 공통 헬퍼로 통일한다). CP949 바이트열은
# UTF-8 연속바이트 규칙과 맞지 않아 utf-8-sig 디코딩이 거의 항상 UnicodeDecodeError로
# 즉시 드러나므로(깨진 문자로 조용히 성공하는 경우는 사실상 없음), 순서대로 시도해 첫
# 성공을 쓴다.
_CSV_ENCODING_FALLBACKS = ("utf-8-sig", "cp949")


def _read_csv_with_encoding_fallback(path: Path, **read_kwargs: Any) -> pd.DataFrame:
    df, _encoding = _read_csv_with_encoding_fallback_detect(path, **read_kwargs)
    return df


def _read_csv_with_encoding_fallback_detect(path: Path, **read_kwargs: Any) -> tuple[pd.DataFrame, str]:
    """인코딩을 순서대로 시도해 첫 성공을 반환한다(성공한 인코딩도 함께 반환 —
    flow_management처럼 미리보기 읽기와 최종 읽기를 같은 인코딩으로 맞춰야 하는 경우용).
    """
    last_exc: UnicodeDecodeError | None = None
    for encoding in _CSV_ENCODING_FALLBACKS:
        try:
            return pd.read_csv(path, encoding=encoding, **read_kwargs), encoding
        except UnicodeDecodeError as exc:
            last_exc = exc
    raise LoaderError(
        f"CSV 인코딩을 확인할 수 없음(UTF-8/CP949 모두 실패): {path.name!r}"
    ) from last_exc


def _find_flow_management_header_row(preview: pd.DataFrame) -> int | None:
    # run_flow_management_preprocessing.py의 locate_header()와 동일 규칙: 상위
    # FLOW_MANAGEMENT_HEADER_SCAN_ROWS행 내에서 필수 토큰이 모두 있는 행을 헤더로 삼는다.
    for row_idx in range(len(preview)):
        values = {str(v).strip() for v in preview.iloc[row_idx].tolist()}
        if FLOW_MANAGEMENT_HEADER_TOKENS.issubset(values):
            return row_idx
    return None


def _read_flow_management_raw(path: Path) -> pd.DataFrame:
    xls = pd.ExcelFile(path)  # .xlsx/.xls 모두 확장자로 엔진 자동 선택(openpyxl/xlrd)
    frames = []
    for sheet in xls.sheet_names:
        preview = pd.read_excel(
            xls, sheet_name=sheet, header=None, nrows=FLOW_MANAGEMENT_HEADER_SCAN_ROWS
        )
        header_row = _find_flow_management_header_row(preview)
        if header_row is None:
            raise LoaderError(f"흐름관리일지 헤더를 찾지 못함: {path.name} 시트 {sheet!r}")
        frames.append(pd.read_excel(xls, sheet_name=sheet, header=header_row, **_READ_CSV_KW))
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def _read_flow_management_raw_csv(path: Path) -> pd.DataFrame:
    # CSV는 시트 개념이 없으므로 파일 전체를 단일 시트처럼 취급해 동일한 헤더 탐지 규칙을 쓴다.
    # 미리보기 읽기에서 확정된 인코딩을 최종 읽기에도 그대로 써야 한다(둘이 어긋나면
    # 헤더 위치를 찾은 좌표가 최종 읽기에서는 다른 내용을 가리킬 수 있음).
    preview, encoding = _read_csv_with_encoding_fallback_detect(
        path, header=None, nrows=FLOW_MANAGEMENT_HEADER_SCAN_ROWS, dtype=str, keep_default_na=False
    )
    header_row = _find_flow_management_header_row(preview)
    if header_row is None:
        raise LoaderError(f"흐름관리일지 헤더를 찾지 못함(csv): {path.name}")
    return pd.read_csv(path, header=header_row, encoding=encoding, **_READ_CSV_KW)


def _build_raw_records(
    descriptor: SkillDescriptor,
    slot: UploadSlot,
    df: pd.DataFrame,
    raw_file_id: uuid.UUID,
    run_id: uuid.UUID,
    uploaded: UploadedFile,
    meta: dict[str, str],
) -> list[dict[str, Any]]:
    if descriptor.run_type == "acdm":
        return _build_acdm_raw_records(df, raw_file_id, run_id, uploaded, meta)

    contract_pairs = RAW_TABLE_COLUMNS[slot.raw_table]
    logical_to_physical = dict(contract_pairs)
    contract_logicals = set(logical_to_physical)

    records = []
    for row_number, row in enumerate(df.to_dict(orient="records")):
        mapped: dict[str, Any] = {physical: None for _, physical in contract_pairs}
        extra: dict[str, Any] = {}
        for column, value in row.items():
            if column in contract_logicals:
                mapped[logical_to_physical[column]] = _json_safe(value)
            else:
                extra[str(column)] = _json_safe(value)
        records.append(
            {
                "raw_file_id": raw_file_id,
                "run_id": run_id,
                "source_row_number": row_number,
                "extra_columns": extra,
                **mapped,
            }
        )
    return records


def _build_acdm_raw_records(
    df: pd.DataFrame, raw_file_id: uuid.UUID, run_id: uuid.UUID, uploaded: UploadedFile, meta: dict[str, str]
) -> list[dict[str, Any]]:
    # ACDM은 공항마다 원본 컬럼명이 달라 raw 단계에서 완전한 원본 충실도를 추구하지 않는다
    # (DB스키마.md §3.2) — source_file/source_date만 타입 컬럼으로 두고 나머지는 전부
    # extra_columns로 흡수한다. flight_no/reg_no 컬럼은 공항별 원본 헤더가 제각각이라 이번
    # 라운드는 채우지 않는다(향후 공항별 별칭 매핑이 필요하면 여기서 값만 채우면 되고
    # DB 스키마 변경은 불필요 — column_map.py에 이미 typed 컬럼으로 정의돼 있다).
    source_date = _acdm_source_date(uploaded, meta)
    records = []
    for row_number, row in enumerate(df.to_dict(orient="records")):
        extra = {str(column): _json_safe(value) for column, value in row.items()}
        records.append(
            {
                "raw_file_id": raw_file_id,
                "run_id": run_id,
                "source_row_number": row_number,
                "source_file": uploaded.original_filename,
                "source_date": source_date,
                "flight_no": None,
                "reg_no": None,
                "extra_columns": extra,
            }
        )
    return records


def _acdm_source_date(uploaded: UploadedFile, meta: dict[str, str]) -> str | None:
    stem = Path(uploaded.original_filename).stem
    match = ACDM_DATE_SUFFIX_RE.search(stem)
    if match:
        return match.group(1)
    # workspace_builder._file_date와 동일한 우선순위: 파일별 재정의 -> 전역 meta.
    candidate = uploaded.date or meta.get("date")
    if candidate and DATE_YYYYMMDD_RE.match(candidate):
        return candidate
    return None


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy 스칼라(int64/float64 등) -> 파이썬 네이티브
        return value.item()
    return value


# --- Phase 5: processed 적재 ---


def load_processed(
    engine: Engine, descriptor: SkillDescriptor, run_id: uuid.UUID, output_paths: dict[str, str]
) -> dict[str, int]:
    """스킬 최종 CSV를 processed_* 테이블에 run_id 태깅하여 적재한다. 반환: 테이블별 적재 행수.

    이 run의 모든 출력(예: ACDM 출발+도착)을 하나의 트랜잭션으로 묶는다.
    """
    loaded: dict[str, int] = {}
    with engine.begin() as conn:
        for output in descriptor.outputs:
            if output.logical_key not in output_paths:
                raise LoaderError(f"{descriptor.run_type}: 결과에 {output.logical_key!r} 경로가 없음")
            path = Path(output_paths[output.logical_key])
            if not path.is_file():
                raise LoaderError(f"산출 CSV가 존재하지 않음: {path}")

            loaded[output.table] = _load_processed_one(conn, output.table, path, run_id)
    return loaded


# --- run 삭제(삭제 후 재입력 루틴) ---

_DELETABLE_STATUSES = ("SUCCESS", "VALIDATION_FAILED", "FAILED")


def delete_run(engine: Engine, run_id: uuid.UUID, deleted_by: str) -> dict[str, int]:
    """이 run이 적재한 raw_*_rows/processed_*/아카이브 파일을 지우고 run을 'DELETED'로
    표시한다(감사 기록으로 남김 — ingestion_runs/ingestion_logs/raw_files 메타데이터 행
    자체는 지우지 않는다, run 물리 삭제 아님). 반환: 테이블별 삭제 행수.

    같은 날짜/파일을 다시 처리하고 싶을 때(사용자 요청 "삭제 후 재입력") 이 함수로 이전
    run의 데이터를 비운 뒤 업로드 폼으로 정상 재업로드하면 새 run_id가 생성된다 — 자동으로
    "같은 날짜면 덮어쓴다"는 정책은 두지 않는다(Stage 1의 최신 run 선택 정책이 아직
    미확정이라 append-only 원칙과 충돌 소지가 있다, docs/02-db-integration.md §3). 대신
    운영자가 명시적으로 지울 run을 고르는 이 루틴만 제공한다.
    """
    with engine.begin() as conn:
        run = conn.execute(
            select(ingestion_runs.c.status, ingestion_runs.c.workspace_path)
            .where(ingestion_runs.c.id == run_id)
            .with_for_update()
        ).mappings().first()
        if run is None:
            raise LoaderError(f"run을 찾을 수 없음: {run_id}")
        if run["status"] not in _DELETABLE_STATUSES:
            raise LoaderError(
                f"이 상태의 run은 삭제할 수 없음: {run['status']!r} "
                f"(삭제 가능: {_DELETABLE_STATUSES})"
            )

        raw_file_rows = conn.execute(
            select(raw_files.c.id, raw_files.c.stored_relpath)
            .select_from(ingestion_run_files.join(raw_files, ingestion_run_files.c.raw_file_id == raw_files.c.id))
            .where(ingestion_run_files.c.run_id == run_id)
        ).all()

        deleted: dict[str, int] = {}
        for table_name, table in {**RAW_ROW_TABLES, **PROCESSED_TABLES}.items():
            result = conn.execute(delete(table).where(table.c.run_id == run_id))
            if result.rowcount:
                deleted[table_name] = result.rowcount

        conn.execute(delete(ingestion_run_files).where(ingestion_run_files.c.run_id == run_id))
        raw_file_ids = [r.id for r in raw_file_rows]
        if raw_file_ids:
            conn.execute(delete(raw_files).where(raw_files.c.id.in_(raw_file_ids)))

        conn.execute(
            update(ingestion_runs)
            .where(ingestion_runs.c.id == run_id)
            .values(status="DELETED", deleted_at=datetime.now(timezone.utc), deleted_by=deleted_by)
        )

    _cleanup_run_files(raw_file_rows, run["workspace_path"])
    return deleted


def _cleanup_run_files(raw_file_rows, workspace_path: str | None) -> None:
    """DB 트랜잭션 커밋 후 실제 디스크 파일을 정리한다(best-effort — 파일 정리가
    실패해도 이미 커밋된 삭제 자체를 되돌리지 않는다, 실패는 서버 로그에만 남긴다).
    """
    for row in raw_file_rows:
        blob_path = settings.upload_dir / row.stored_relpath
        try:
            blob_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("삭제된 run의 아카이브 파일 정리 실패: %s", blob_path)

    if workspace_path:
        try:
            shutil.rmtree(Path(workspace_path), ignore_errors=True)
        except OSError:
            logger.exception("삭제된 run의 workspace 정리 실패: %s", workspace_path)


def _load_processed_one(conn: Connection, table_name: str, path: Path, run_id: uuid.UUID) -> int:
    pairs = PROCESSED_COLUMNS[table_name]
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", **_READ_CSV_KW)
    except Exception as exc:
        # 원본 pandas 예외 텍스트는 클라이언트에 노출하지 않는다(코드리뷰 2026-07-21 발견 —
        # _read_raw_dataframe에 이미 적용한 것과 동일한 원칙, docs/06-conventions.md §8).
        logger.exception("%s: 산출 CSV 파싱 실패: %s", table_name, path)
        raise LoaderError(
            f"{table_name}: 산출 CSV 파싱 실패(형식 확인 필요, 상세는 서버 로그 참조): {path}"
        ) from exc

    expected_logicals = [logical for logical, _ in pairs]
    missing = [logical for logical in expected_logicals if logical not in df.columns]
    if missing:
        raise LoaderError(f"{table_name}: CSV에 없는 필수 컬럼: {missing} (경로: {path})")
    extra_columns = [col for col in df.columns if col not in set(expected_logicals)]
    if extra_columns:
        # processed는 스킬 CSV와 1:1 미러가 계약이므로(§9), 예상 밖 컬럼은 스킬 산출물
        # 스키마가 드리프트했다는 신호 — 조용히 버리지 않고 실패시켜 즉시 드러낸다.
        raise LoaderError(
            f"{table_name}: CSV에 예상 밖 컬럼이 있음(스킬 산출물 스키마 변경 의심): "
            f"{extra_columns} (경로: {path})"
        )

    logical_to_physical = dict(pairs)
    renamed = df.rename(columns=logical_to_physical)[[physical for _, physical in pairs]]
    records = [
        {**{k: _json_safe(v) for k, v in record.items()}, "run_id": run_id, "source_csv_path": str(path)}
        for record in renamed.to_dict(orient="records")
    ]

    if records:
        conn.execute(insert(PROCESSED_TABLES[table_name]), records)
    return len(records)
