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

import pandas as pd
from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine

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


def has_running_run(engine: Engine) -> bool:
    """이미 RUNNING인 run이 있는지 확인한다(순차 처리 가드, 기술스택_결정.md §2.6)."""
    stmt = select(ingestion_runs.c.id).where(ingestion_runs.c.status == "RUNNING").limit(1)
    with engine.connect() as conn:
        return conn.execute(stmt).first() is not None


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
        raise LoaderError(
            f"{descriptor.run_type}: 원본 파일 파싱 실패: {uploaded.original_filename!r} ({exc})"
        ) from exc


def _read_raw_dataframe_unsafe(descriptor: SkillDescriptor, slot: UploadSlot, uploaded: UploadedFile) -> pd.DataFrame:
    if descriptor.run_type == "flight_data":
        return pd.read_excel(uploaded.source_path, **_READ_CSV_KW)

    if descriptor.run_type == "fois":
        df = pd.read_excel(uploaded.source_path, header=None, skiprows=1, **_READ_CSV_KW)
        if df.shape[1] != len(FOIS_SOURCE_COLUMNS):
            raise LoaderError(
                f"FOIS 원본 열 수가 {len(FOIS_SOURCE_COLUMNS)}개가 아님: {uploaded.original_filename!r} "
                f"({df.shape[1]}열)"
            )
        df.columns = list(FOIS_SOURCE_COLUMNS)
        return df

    if descriptor.run_type == "flow_management":
        return _read_flow_management_raw(uploaded.source_path)

    if descriptor.run_type == "acdm":
        suffix = uploaded.source_path.suffix.lower()
        if suffix == ".csv":
            # 실측 샘플은 UTF-8이지만, utf-8-sig로 읽으면 BOM 유무와 무관하게 안전하다.
            return pd.read_csv(uploaded.source_path, encoding="utf-8-sig", **_READ_CSV_KW)
        return pd.read_excel(uploaded.source_path, **_READ_CSV_KW)

    raise LoaderError(f"알 수 없는 run_type: {descriptor.run_type!r}")


def _read_flow_management_raw(path: Path) -> pd.DataFrame:
    # run_flow_management_preprocessing.py의 locate_header()와 동일 규칙: 시트별 상위
    # FLOW_MANAGEMENT_HEADER_SCAN_ROWS행 내에서 필수 토큰이 모두 있는 행을 헤더로 삼는다.
    xls = pd.ExcelFile(path)
    frames = []
    for sheet in xls.sheet_names:
        preview = pd.read_excel(
            xls, sheet_name=sheet, header=None, nrows=FLOW_MANAGEMENT_HEADER_SCAN_ROWS
        )
        header_row = None
        for row_idx in range(len(preview)):
            values = {str(v).strip() for v in preview.iloc[row_idx].tolist()}
            if FLOW_MANAGEMENT_HEADER_TOKENS.issubset(values):
                header_row = row_idx
                break
        if header_row is None:
            raise LoaderError(f"흐름관리일지 헤더를 찾지 못함: {path.name} 시트 {sheet!r}")
        frames.append(pd.read_excel(xls, sheet_name=sheet, header=header_row, **_READ_CSV_KW))
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


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


def _load_processed_one(conn: Connection, table_name: str, path: Path, run_id: uuid.UUID) -> int:
    pairs = PROCESSED_COLUMNS[table_name]
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", **_READ_CSV_KW)
    except Exception as exc:
        raise LoaderError(f"{table_name}: 산출 CSV 파싱 실패: {path} ({exc})") from exc

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
