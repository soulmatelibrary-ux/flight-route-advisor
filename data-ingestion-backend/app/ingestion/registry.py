"""SkillDescriptor 레지스트리 — 표준화 설계의 핵심(작업계획서.md §4).

스킬 4종의 CLI 인자·입력 폴더 규칙·stdout 파싱·검증기 호출·컬럼 매핑 차이를 코드 분기
대신 이 모듈의 선언적 상수로 흡수한다. `workspace_builder`/`skill_runner`는 이 서술자를
인자로 받아 동일한 절차를 반복한다 — run_type별 특수 분기는 이 파일에만 존재한다.

LayoutRule 필드는 작업계획서 §4.1 스케치(문서 스스로 "구현 착수용 청사진"이라 명시)를
실제 배치 규칙(스킬연동_레퍼런스.md §5)에 맞춰 구체화했다: 슬롯별 하위폴더가 서로 달라
(예: 비행자료 분석/검색) 단일 subdir_template 문자열로는 표현할 수 없어 `slot_subdirs`
딕셔너리로 대체했다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UploadSlot:
    key: str
    required: bool
    accept: tuple[str, ...]
    file_type: str  # raw_files.file_type 값(DB스키마.md §3.1 CHECK 허용값과 반드시 일치)
    paired: bool = False


@dataclass(frozen=True)
class LayoutRule:
    # slot key -> <WS> 기준 하위폴더 템플릿. 플레이스홀더: {airport_ko}(ACDM 전용).
    # 방향은 플레이스홀더가 아니라 슬롯 자체(예: departure_file/arrival_file)가 결정한다 —
    # 사용자 입력으로 방향 문자열을 따로 받지 않아 검증 대상이 줄어든다.
    slot_subdirs: dict[str, str]
    # None이면 원본 파일명 유지, 아니면 "{prefix}_{date}{ext}" 형식으로 재명명
    # (prefix는 슬롯이 매핑된 subdir의 마지막 폴더명 — 예: "비행자료분석")
    filename_template: str | None
    needs_spatial: bool = False


@dataclass(frozen=True)
class ResultParse:
    mode: str  # "line" | "json"
    keys: tuple[str, ...]


@dataclass(frozen=True)
class ValidatorSpec:
    auto_run_by_skill: bool
    script: str | None  # SOURCE_PROJECT_ROOT 기준 상대경로
    arg_style: str | None  # "positional_csv" | "dep_arr" | "report"


@dataclass(frozen=True)
class OutputTableMap:
    logical_key: str  # ResultParse.keys 중 하나
    table: str  # processed_* 테이블명
    column_map: str  # app.db.column_map.PROCESSED_COLUMNS 키(다음 라운드 loaders.py용)


@dataclass(frozen=True)
class SkillDescriptor:
    run_type: str
    script: str
    extra_args: tuple[str, ...]
    upload_slots: tuple[UploadSlot, ...]
    layout: LayoutRule
    date_separator: str
    result: ResultParse
    validator: ValidatorSpec
    outputs: tuple[OutputTableMap, ...]


FLIGHT_DATA = SkillDescriptor(
    run_type="flight_data",
    script="skills/preprocess-flight-data/scripts/preprocess_flight_data.py",
    extra_args=(),
    upload_slots=(
        UploadSlot(
            "analysis", required=True, accept=(".xlsx", ".xls", ".csv"),
            file_type="flight_analysis", paired=True,
        ),
        UploadSlot(
            "search", required=True, accept=(".xlsx", ".xls", ".csv"),
            file_type="flight_search", paired=True,
        ),
    ),
    layout=LayoutRule(
        slot_subdirs={
            "analysis": "비행자료/비행자료분석",
            "search": "비행자료/비행자료검색",
        },
        filename_template="{prefix}_{date}{ext}",
        needs_spatial=True,
    ),
    date_separator="_",
    result=ResultParse(mode="line", keys=("OUTPUT",)),
    validator=ValidatorSpec(
        auto_run_by_skill=False,
        script="skills/preprocess-flight-data/scripts/validate_output.py",
        arg_style="positional_csv",
    ),
    outputs=(OutputTableMap("OUTPUT", "processed_flight_data", "processed_flight_data"),),
)

ACDM = SkillDescriptor(
    run_type="acdm",
    script="skills/preprocess-acdm/scripts/run_acdm_preprocessing.py",
    extra_args=(),
    # 실제 스킬(merge_acdm_data.py)은 한 번의 실행에서 출발/도착 CSV를 모두 만들며, 어느 한
    # 방향이라도 파일이 하나도 없으면 pd.concat([])에서 실패한다(수동 검증으로 확인) — 두 슬롯
    # 모두 필수다. 슬롯이 방향을 결정하므로 각 슬롯 파일은 서로 다른 공항이어도 된다
    # (UploadedFile.airport_ko로 파일별 재정의, 미지정 시 meta의 공통 airport_ko 사용).
    upload_slots=(
        UploadSlot(
            "departure_file", required=True, accept=(".csv", ".xlsx", ".xls"),
            file_type="acdm_departure",
        ),
        UploadSlot(
            "arrival_file", required=True, accept=(".csv", ".xlsx", ".xls"),
            file_type="acdm_arrival",
        ),
    ),
    layout=LayoutRule(
        slot_subdirs={
            "departure_file": "ACDM/{airport_ko}공항출발ACDM",
            "arrival_file": "ACDM/{airport_ko}공항도착ACDM",
        },
        filename_template=None,
        needs_spatial=False,
    ),
    date_separator="-",
    result=ResultParse(mode="json", keys=("departure_output", "arrival_output")),
    validator=ValidatorSpec(
        auto_run_by_skill=True,
        script="skills/preprocess-acdm/scripts/validate_outputs.py",
        arg_style="dep_arr",
    ),
    outputs=(
        OutputTableMap("departure_output", "processed_acdm_departure", "processed_acdm_departure"),
        OutputTableMap("arrival_output", "processed_acdm_arrival", "processed_acdm_arrival"),
    ),
)

FOIS = SkillDescriptor(
    run_type="fois",
    script="skills/preprocess-fois/scripts/run_fois_preprocessing.py",
    extra_args=(),
    # 실제 스킬(run_fois_preprocessing.py main())은 출발/도착 두 폴더를 모두 조회하며 어느
    # 한쪽이라도 xlsx가 없으면 FileNotFoundError를 낸다(수동 검증으로 확인) — 두 슬롯 모두 필수다.
    upload_slots=(
        UploadSlot(
            "departure", required=True, accept=(".xlsx", ".xls", ".csv"),
            file_type="fois_departure",
        ),
        UploadSlot(
            "arrival", required=True, accept=(".xlsx", ".xls", ".csv"),
            file_type="fois_arrival",
        ),
    ),
    layout=LayoutRule(
        slot_subdirs={
            "departure": "FOIS/비정상운항출발",
            "arrival": "FOIS/비정상운항도착",
        },
        filename_template=None,
        needs_spatial=False,
    ),
    date_separator="-",
    result=ResultParse(mode="line", keys=("DEPARTURE_OUTPUT", "ARRIVAL_OUTPUT")),
    validator=ValidatorSpec(
        auto_run_by_skill=False,
        script="skills/preprocess-fois/scripts/validate_outputs.py",
        arg_style="dep_arr",
    ),
    outputs=(
        OutputTableMap("DEPARTURE_OUTPUT", "processed_fois_departure", "processed_fois_departure"),
        OutputTableMap("ARRIVAL_OUTPUT", "processed_fois_arrival", "processed_fois_arrival"),
    ),
)

FLOW_MANAGEMENT = SkillDescriptor(
    run_type="flow_management",
    script="skills/preprocess-flow-management/scripts/run_flow_management_preprocessing.py",
    extra_args=("--no-integrate",),
    upload_slots=(
        UploadSlot(
            "file", required=True, accept=(".xlsx", ".xls", ".csv"),
            file_type="flow_management",
        ),
    ),
    layout=LayoutRule(
        slot_subdirs={"file": "흐름관리일지"},
        filename_template=None,
        needs_spatial=False,
    ),
    date_separator="-",
    result=ResultParse(mode="json", keys=("event_output",)),
    validator=ValidatorSpec(
        auto_run_by_skill=False,
        script="skills/preprocess-flow-management/scripts/validate_outputs.py",
        arg_style="report",
    ),
    outputs=(OutputTableMap("event_output", "processed_flow_management", "processed_flow_management"),),
)

_REGISTRY: dict[str, SkillDescriptor] = {
    "flight_data": FLIGHT_DATA,
    "acdm": ACDM,
    "fois": FOIS,
    "flow_management": FLOW_MANAGEMENT,
}


def get_descriptor(run_type: str) -> SkillDescriptor:
    try:
        return _REGISTRY[run_type]
    except KeyError:
        raise ValueError(f"알 수 없는 run_type: {run_type!r} (허용: {tuple(_REGISTRY)})") from None
