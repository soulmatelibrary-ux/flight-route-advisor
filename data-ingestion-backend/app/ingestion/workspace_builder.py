"""run별 격리 workspace 구성 (스킬연동_레퍼런스.md §5 배치 규칙).

코드는 SOURCE_PROJECT_ROOT의 원본 스킬을 그대로 호출하고, 데이터만 이 격리 workspace(<WS>)로
분리한다(§0). flight_data만 공간데이터를 원본에서 <WS>로 편도 복사한다(원본 무변경, CLAUDE.md §5).
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.ingestion.constants import (
    ACDM_DATE_SUFFIX_RE,
    AIRPORT_KO_TO_ICAO,
    DATE_YYYYMMDD_RE,
    FLIGHT_ANALYSIS_FILENAME_RE,
    FLIGHT_SEARCH_FILENAME_RE,
    PATH_INJECTION_RE,
    SOURCE_SUBDIR,
)
from app.ingestion.registry import SkillDescriptor

_FLIGHT_DATA_SLOT_FILENAME_RE = {
    "analysis": FLIGHT_ANALYSIS_FILENAME_RE,
    "search": FLIGHT_SEARCH_FILENAME_RE,
}


class WorkspaceBuildError(ValueError):
    """업로드 배치 실패(입력 검증 포함). 메시지는 사용자에게 노출 가능한 수준으로 유지한다."""


@dataclass(frozen=True)
class UploadedFile:
    """workspace_builder 입력 단위.

    `source_path`는 서버가 이미 저장한 임시 파일 경로. `original_filename`은 검증에만
    쓰고 저장 파일명으로 그대로 쓰지 않는다(경로주입 방지, docs/06-conventions.md §8).

    `airport_ko`는 ACDM 전용 — 파일별로 다른 공항일 수 있어(예: 출발 슬롯은 인천, 도착
    슬롯은 김포) 전역 `meta["airport_ko"]`보다 우선한다.
    `date`는 ACDM 전용(파일명에 8자리 날짜 접미가 없을 때의 파일별 재구성 날짜) —
    전역 `meta["date"]`보다 우선한다. flight_data는 날짜를 파일명(비행자료분석/검색_YYYYMMDD)
    에서 직접 파싱하므로 이 필드를 쓰지 않는다(여러 날짜를 한 번에 업로드해도 충돌하지 않도록).
    다음 라운드(Phase 6 업로드 API)에서 이 dataclass를 그대로 받아 넘긴다.
    """

    slot_key: str
    source_path: Path
    original_filename: str
    airport_ko: str | None = None
    date: str | None = None


def build_workspace(
    descriptor: SkillDescriptor,
    uploaded_files: Sequence[UploadedFile],
    meta: dict[str, str],
    workspace_root: Path,
    source_project_root: Path,
) -> Path:
    """run별 격리 `<WS>`를 만들고 서술자 layout에 따라 파일을 배치한다. 반환: workspace 경로."""

    _validate_required_slots(descriptor, uploaded_files)

    for uploaded in uploaded_files:
        _reject_path_injection(uploaded.original_filename)
        slot = _slot_by_key(descriptor, uploaded.slot_key)
        _reject_extension(uploaded.original_filename, slot.accept)
        if descriptor.run_type == "acdm":
            _validate_acdm_airport(_acdm_airport_ko(uploaded, meta))

    _validate_paired_dates(descriptor, uploaded_files, meta)

    ws = workspace_root / f"ws-{uuid.uuid4().hex}"
    ws.mkdir(parents=True, exist_ok=False)

    for uploaded in uploaded_files:
        subdir_template = descriptor.layout.slot_subdirs[uploaded.slot_key]
        subdir = _resolve_subdir(descriptor, subdir_template, uploaded, meta)
        dest_name = _resolve_filename(descriptor, uploaded, meta)
        _place_file(ws, subdir, dest_name, uploaded.source_path)

    if descriptor.layout.needs_spatial:
        _copy_spatial_data(source_project_root, ws)

    return ws


def _reject_path_injection(filename: str) -> None:
    if PATH_INJECTION_RE.search(filename):
        raise WorkspaceBuildError(f"파일명에 허용되지 않은 경로 문자 포함: {filename!r}")


def _reject_extension(filename: str, accept: tuple[str, ...]) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in accept:
        raise WorkspaceBuildError(f"허용되지 않은 확장자: {filename!r} (허용: {accept})")


def _slot_by_key(descriptor: SkillDescriptor, key: str):
    for slot in descriptor.upload_slots:
        if slot.key == key:
            return slot
    raise WorkspaceBuildError(f"{descriptor.run_type}에 정의되지 않은 업로드 슬롯: {key!r}")


def _validate_required_slots(descriptor: SkillDescriptor, uploaded_files: Sequence[UploadedFile]) -> None:
    present = {f.slot_key for f in uploaded_files}
    missing = [slot.key for slot in descriptor.upload_slots if slot.required and slot.key not in present]
    if missing:
        raise WorkspaceBuildError(
            f"{descriptor.run_type}: 필수 업로드 슬롯 누락: {missing} "
            f"(작업계획서.md §5-1 — 위반 시 run 생성 전 거부)"
        )


def _validate_paired_dates(
    descriptor: SkillDescriptor, uploaded_files: Sequence[UploadedFile], meta: dict[str, str]
) -> None:
    paired_slots = [slot.key for slot in descriptor.upload_slots if slot.paired]
    if len(paired_slots) != 2:
        return

    by_slot: dict[str, set[str]] = {key: set() for key in paired_slots}
    for uploaded in uploaded_files:
        if uploaded.slot_key in by_slot:
            by_slot[uploaded.slot_key].add(_file_date(descriptor, uploaded, meta))

    slot_a, slot_b = paired_slots
    only_a = by_slot[slot_a] - by_slot[slot_b]
    only_b = by_slot[slot_b] - by_slot[slot_a]
    if only_a or only_b:
        raise WorkspaceBuildError(
            f"{descriptor.run_type}: {slot_a}/{slot_b} 날짜별 1:1 쌍이 맞지 않음 — "
            f"{slot_a}만 있는 날짜: {sorted(only_a)}, {slot_b}만 있는 날짜: {sorted(only_b)} "
            "(스킬연동_레퍼런스.md §3.1 — 불일치 시 중단)"
        )


def _acdm_airport_ko(uploaded: UploadedFile, meta: dict[str, str]) -> str | None:
    return uploaded.airport_ko or meta.get("airport_ko")


def _validate_acdm_airport(airport_ko: str | None) -> None:
    if airport_ko not in AIRPORT_KO_TO_ICAO:
        raise WorkspaceBuildError(
            f"ACDM 공항 값이 올바르지 않음: {airport_ko!r} (허용: {tuple(AIRPORT_KO_TO_ICAO)})"
        )


def _resolve_subdir(
    descriptor: SkillDescriptor, template: str, uploaded: UploadedFile, meta: dict[str, str]
) -> str:
    airport_ko = _acdm_airport_ko(uploaded, meta) if descriptor.run_type == "acdm" else ""
    return template.format(airport_ko=airport_ko or "")


def _require_valid_date(context: str, date: str | None) -> str:
    if not date or not DATE_YYYYMMDD_RE.match(date):
        raise WorkspaceBuildError(f"{context}: 날짜(YYYYMMDD)가 없거나 형식이 틀림: {date!r}")
    return date


def _file_date(descriptor: SkillDescriptor, uploaded: UploadedFile, meta: dict[str, str]) -> str:
    """이 파일의 날짜를 결정한다. flight_data는 파일명에서, ACDM은 파일명 접미 또는
    파일별/전역 메타에서 얻는다 — 전역 메타 하나에만 의존하면 한 슬롯에 여러 날짜 파일을
    올릴 때 서로 다른 파일이 같은 날짜로 취급돼 배치 시 충돌한다(파일마다 실제 날짜를 쓴다).
    """
    if descriptor.run_type == "flight_data":
        pattern = _FLIGHT_DATA_SLOT_FILENAME_RE.get(uploaded.slot_key)
        match = pattern.match(uploaded.original_filename) if pattern else None
        if not match:
            raise WorkspaceBuildError(
                f"flight_data: 파일명이 규약과 다름(날짜를 파싱할 수 없음): {uploaded.original_filename!r} "
                "(스킬연동_레퍼런스.md §3.1)"
            )
        return match.group(1)

    if descriptor.run_type == "acdm":
        stem = Path(uploaded.original_filename).stem
        suffix_match = ACDM_DATE_SUFFIX_RE.search(stem)
        if suffix_match:
            return suffix_match.group(1)
        return _require_valid_date(
            f"acdm({uploaded.original_filename!r})", uploaded.date or meta.get("date")
        )

    raise WorkspaceBuildError(f"{descriptor.run_type}는 파일별 날짜 개념이 없음")


def _resolve_filename(descriptor: SkillDescriptor, uploaded: UploadedFile, meta: dict[str, str]) -> str:
    template = descriptor.layout.filename_template
    ext = Path(uploaded.original_filename).suffix

    if template is None:
        # ACDM: 파일명 끝에 이미 8자리 날짜가 있으면 그대로, 없으면 재구성한 날짜로 재명명한다
        # (스킬연동_레퍼런스 §3.2 — 파일명 끝 8자리 날짜 필수). 다른 run_type은 원본 파일명 유지.
        if descriptor.run_type == "acdm":
            stem = Path(uploaded.original_filename).stem
            if ACDM_DATE_SUFFIX_RE.search(stem):
                return uploaded.original_filename
            date = _file_date(descriptor, uploaded, meta)
            return f"{stem}_{date}{ext}"
        return uploaded.original_filename

    # flight_data: 파일명에서 파싱한 실제 날짜를 쓴다(전역 meta 날짜를 쓰면 여러 날짜를 한 번에
    # 올릴 때 모든 파일이 같은 이름으로 겹쳐써진다).
    date = _file_date(descriptor, uploaded, meta)
    subdir_template = descriptor.layout.slot_subdirs[uploaded.slot_key]
    prefix = _resolve_subdir(descriptor, subdir_template, uploaded, meta).rsplit("/", 1)[-1]
    return template.format(prefix=prefix, date=date, ext=ext)


def _place_file(ws: Path, subdir: str, dest_name: str, source_path: Path) -> Path:
    target_dir = ws / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / dest_name
    if target_path.exists():
        raise WorkspaceBuildError(f"동일 배치 대상 파일이 이미 존재함(파일명 충돌): {target_path}")
    shutil.copy2(source_path, target_path)
    return target_path


def _copy_spatial_data(source_project_root: Path, ws: Path) -> None:
    src = source_project_root / SOURCE_SUBDIR["spatial"]
    dst = ws / SOURCE_SUBDIR["spatial"]
    shutil.copytree(src, dst, dirs_exist_ok=True)
