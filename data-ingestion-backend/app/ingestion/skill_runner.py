"""subprocess로 기존 스킬 4종을 호출·결과 파싱·검증 실행.

근거: data-ingestion-backend/docs/스킬연동_레퍼런스.md §1~§3·§6, 기술스택_결정.md §2.9.
스킬 스크립트(SOURCE_PROJECT_ROOT/skills/*/scripts/*.py)는 절대 수정하지 않고 블랙박스
CLI로 취급한다. 백엔드는 (1) 종료 코드 (2) stdout/stderr (3) 스킬이 만든 CSV/JSON 산출물
경로만으로 결과를 판단한다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.ingestion.constants import SKILL_SUBPROCESS_ENV_EXTRA
from app.ingestion.registry import SkillDescriptor


class SkillExecutionError(RuntimeError):
    """스킬 subprocess 실행/파싱 실패. 메시지에 자격증명 등 민감정보를 담지 않는다."""


@dataclass(frozen=True)
class SkillResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class ValidationSummary:
    status: str  # "PASS" | "FAIL"
    detail: dict


_KEY_VALUE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _skill_env() -> dict[str, str]:
    # 스킬연동_레퍼런스 §1.6: 한글 경로/출력 안정성을 위해 4종 모두 동일하게 주입.
    # 부모 프로세스 환경을 통째로 넘기지 않는다 — DATABASE_URL 등 이 앱의 비밀정보가
    # 외부 스킬 subprocess(그리고 그 stdout/stderr 캡처 로그)에 노출되는 것을 막는다
    # (docs/06-conventions.md §8 비밀정보 비노출). 스킬 실행에 필요한 최소 환경만 전달한다.
    minimal = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "LC_ALL")
        if key in os.environ
    }
    return {**minimal, **SKILL_SUBPROCESS_ENV_EXTRA}


def _run_subprocess(args: list[str], cwd: Path) -> SkillResult:
    # 인자 리스트 방식만 사용(shell=True 금지, docs/06-conventions.md §8 시큐어코딩).
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_skill_env(),
        cwd=str(cwd),
    )
    return SkillResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def run_skill(
    descriptor: SkillDescriptor, workspace: Path, source_project_root: Path
) -> SkillResult:
    """스킬연동_레퍼런스 §2 표준 호출 형태. cwd=SOURCE_PROJECT_ROOT, --workspace=<WS>.

    스크립트 경로는 항상 registry.py(화이트리스트 상수)에서만 오므로, 외부 입력이
    실행 대상 경로를 결정하지 못한다.
    """
    script_path = source_project_root / descriptor.script
    if not script_path.is_file():
        raise SkillExecutionError(f"스킬 스크립트가 존재하지 않음: {descriptor.script}")

    args = [sys.executable, str(script_path), "--workspace", str(workspace), *descriptor.extra_args]
    return _run_subprocess(args, cwd=source_project_root)


def parse_result(descriptor: SkillDescriptor, stdout: str) -> dict:
    """서술자 result.mode(line|json)에 따라 stdout을 파싱해 결과 딕셔너리를 반환한다.

    line/json 모드 모두 stdout에 담긴 전체 키를 반환한다(descriptor.result.keys는 필수
    존재 확인용) — 검증기 호출에 필요한 부가 키(예: flow_management의 validation_output)도
    함께 넘어와야 하기 때문이다.
    """
    payload = _extract_json_object(stdout) if descriptor.result.mode == "json" else _parse_key_value_lines(stdout)
    missing = [key for key in descriptor.result.keys if key not in payload]
    if missing:
        raise SkillExecutionError(
            f"{descriptor.run_type} stdout에서 필수 결과 키를 찾지 못함: {missing}"
        )
    return payload


def _parse_key_value_lines(stdout: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in stdout.splitlines():
        match = _KEY_VALUE_RE.match(line.strip())
        if match:
            found[match.group(1)] = match.group(2).strip()
    return found


def _extract_json_object(stdout: str) -> dict:
    # ACDM처럼 내부적으로 여러 스테이지를 subprocess 체이닝하는 스킬은 각 스테이지의 stdout
    # JSON이 함께 캡처되어, 최종 종합 리포트가 stdout 마지막에 오는 경우가 있다(수동 검증으로
    # 확인). '{' 위치마다 raw_decode를 시도해 유효한 JSON 객체를 모두 모으고, 그중 가장 뒤에
    # 있는 것(최종 리포트)을 반환한다.
    decoder = json.JSONDecoder()
    objects: list[dict] = []
    idx = stdout.find("{")
    while idx != -1:
        try:
            obj, end = decoder.raw_decode(stdout, idx)
            objects.append(obj)
            idx = stdout.find("{", end)
        except json.JSONDecodeError:
            idx = stdout.find("{", idx + 1)
    if not objects:
        raise SkillExecutionError("stdout에서 JSON 결과를 찾지 못함")
    return objects[-1]


def run_validator(
    descriptor: SkillDescriptor, parsed_result: dict, source_project_root: Path
) -> ValidationSummary:
    """auto_run_by_skill=False인 3종만 별도 실행한다(스킬연동_레퍼런스 §6).

    ACDM(auto_run_by_skill=True)은 메인 스크립트가 이미 검증기를 자동 호출해 실패 시
    RuntimeError로 전체 중단시키므로, run_skill 성공 자체가 1차 검증 통과 신호다.
    """
    if descriptor.validator.auto_run_by_skill:
        raise SkillExecutionError(
            f"{descriptor.run_type}은 메인이 검증기를 자동 실행함 — run_validator 호출 불필요"
        )
    if descriptor.validator.script is None:
        raise SkillExecutionError(f"{descriptor.run_type}에 검증기 스크립트가 정의되지 않음")

    script_path = source_project_root / descriptor.validator.script
    if not script_path.is_file():
        raise SkillExecutionError(f"검증기 스크립트가 존재하지 않음: {descriptor.validator.script}")

    args = [sys.executable, str(script_path), *_validator_args(descriptor, parsed_result)]
    result = _run_subprocess(args, cwd=source_project_root)

    if not result.succeeded:
        return ValidationSummary(
            status="FAIL", detail={"stderr": result.stderr, "returncode": result.returncode}
        )

    payload = _extract_json_object(result.stdout)
    status = payload.get("status", "PASS")
    return ValidationSummary(status=status, detail=payload)


def _validator_args(descriptor: SkillDescriptor, parsed_result: dict) -> list[str]:
    style = descriptor.validator.arg_style
    if style == "positional_csv":
        return [_require_key(parsed_result, "OUTPUT")]
    if style == "dep_arr":
        return [
            "--departure",
            parsed_result[_find_key(parsed_result, "depart")],
            "--arrival",
            parsed_result[_find_key(parsed_result, "arriv")],
        ]
    if style == "report":
        return ["--report", _require_key(parsed_result, "validation_output")]
    raise SkillExecutionError(f"알 수 없는 validator arg_style: {style!r}")


def _require_key(parsed_result: dict, key: str) -> str:
    # descriptor.result.keys가 보장하지 않는 부가 키(예: flow_management의 validation_output)에
    # 대해서도 KeyError 대신 이 모듈의 예외 타입으로 통일해 원인을 명확히 남긴다.
    if key not in parsed_result:
        raise SkillExecutionError(f"결과에 {key!r} 키가 없음: {list(parsed_result)}")
    return parsed_result[key]


def _find_key(parsed_result: dict, substring: str) -> str:
    for key in parsed_result:
        if substring in key.lower():
            return key
    raise SkillExecutionError(f"결과에서 {substring!r}를 포함하는 키를 찾지 못함: {list(parsed_result)}")
