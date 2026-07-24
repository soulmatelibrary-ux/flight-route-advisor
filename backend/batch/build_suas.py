"""SUAS/MOA 통과시각 발효 판정 — EFF_TIMES 파생 배치 (docs/13-ai-reasoning-dev-plan.md STEP A7).

완성본 빌드 파이프라인조차 DAFIF `SUAS_PAR.TXT`의 `EFF_TIMES`(발효시간) 컬럼을 `suas.json`
생성 단계에서 버렸다 — 이 STEP은 "이식"이 아니라 doc13이 명시한 "신규 파생"이다. 사전빌드
JSON(`reference_suas` DB 테이블, 별도 세션이 이관)에는 이 필드가 없으므로, 원본
`PORTING_PACKAGE_ROOT/원본데이터/DAFIFT/SUAS/SUAS_PAR.TXT`를 **직접** 읽어(§0.1 읽기전용
외부자산) 파싱한다.

**안전 우선 파싱 규약(창작·억측 금지, docs/13 STEP A7)**:
- 구조화 가능(1단계 반영): 요일 키워드(MON~SUN 단일/범위, DLY/DAILY/CONT=매일) + UTC
  시간범위(HHMM-HHMMZ, 콤마로 여러 구간 나열 가능) 조합 → `status="structured"` +
  `segments:[{days,utc_start,utc_end}, ...]`.
- 비정형(1단계 미반영, 발효 여부 단정 금지): `SR`/`SS`(일출·일몰, 위치·계절 종속) ·
  `NOTAM` · `HOL`(공휴일 예외 — 실제 공휴일 날짜를 검증할 근거가 없어 이 컬럼만으로는
  판정 불가) · 그 외 정규식이 못 알아본 자유서술 → `status="confirm_required"`.
  파싱 실패를 "비활성으로 간주" 같은 임의 기본값으로 채우지 않는다(안전 사고 방지 원칙).

산출은 `advisor_suas_schedule`(advisor 소유, `backend/app/db/column_map.py`
`ADVISOR_SUAS_COLUMNS`, 스키마 단일 출처는 data-ingestion-backend alembic `d9f2b4a8c1e6_*`)에
truncate-and-reload — `reference_suas`(별도 세션 소유)는 건드리지 않고 `ident`로만 애플리케이션
레벨 조인(`reference/loader.py:load_suas`).

읽기 전용 원칙(docs/CLAUDE.md §5): 원본 DAFIF 파일은 수정하지 않는다.
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.config import settings
from app.db import artifact_session

_DAFIF_SUAS_FILE = "원본데이터/DAFIFT/SUAS/SUAS_PAR.TXT"

# `segments`는 리스트-of-딕트(중첩 구조)라 build_odr2.py/build_flow.py가 스칼라 컬럼에 쓰는
# 타입 없는 sa.table()/sa.column() 프록시로는 못 쓴다(리뷰에서 이미 겪은 함정 — 타입 정보가
# 없으면 psycopg2가 Python list/dict를 Postgres ARRAY로 오인하거나 아예 바인딩을 못 한다,
# docs/07-checklist.md A6 항목의 `runway_dist` 시행착오와 동일 원인). `reference_tables.py`가
# JSONB 컬럼에 쓰는 것과 동일하게 명시적 타입의 Table 객체를 쓴다(컬럼명 자체는 여전히
# column_map.ADVISOR_SUAS_COLUMNS가 단일 출처 — 아래 컬럼 목록이 그 튜플과 어긋나면 안 됨).
_metadata = sa.MetaData()
_SUAS_SCHEDULE = sa.Table(
    "advisor_suas_schedule",
    _metadata,
    sa.Column("ident", sa.Text),
    sa.Column("eff_times_raw", sa.Text),
    sa.Column("status", sa.Text),
    sa.Column("segments", JSONB),
    sa.Column("generated_at", sa.TIMESTAMP(timezone=True)),
)

_DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_DAY_INDEX = {d: i for i, d in enumerate(_DAY_ORDER)}
_ALWAYS_DAILY = {"DLY", "DAILY", "CONT"}
_NON_STRUCTURED_MARKERS = ("NOTAM", "SR", "SS", "HOL")
_TIME_RANGE_RE = re.compile(r"(\d{4})-(\d{4})Z")


def _expand_day_token(token: str) -> list[str] | None:
    """"MON" → ["MON"], "MON-FRI" → ["MON",...,"FRI"](요일순 랩어라운드 지원). 못 알아보면 None."""
    token = token.strip()
    if token in _ALWAYS_DAILY:
        return list(_DAY_ORDER)
    if "-" in token:
        a, _, b = token.partition("-")
        if a in _DAY_INDEX and b in _DAY_INDEX:
            start, end = _DAY_INDEX[a], _DAY_INDEX[b]
            return _DAY_ORDER[start:] + _DAY_ORDER[: end + 1] if start > end else _DAY_ORDER[start : end + 1]
        return None
    return [token] if token in _DAY_INDEX else None


def parse_eff_times(raw: str | None) -> dict[str, Any]:
    """DAFIF EFF_TIMES 원문 → {"status": "structured", "segments":[...]} 또는
    {"status": "confirm_required", "reason": "..."}. 순수 함수(단위테스트 대상)."""
    text = (raw or "").strip()
    if not text:
        return {"status": "confirm_required", "reason": "EFF_TIMES 결측"}
    upper = text.upper()
    if any(marker in upper for marker in _NON_STRUCTURED_MARKERS):
        return {"status": "confirm_required", "reason": "비정형(일출몰/NOTAM/공휴일 예외 등 위치·날짜 종속)"}
    if upper in _ALWAYS_DAILY:  # "CONT"뿐 아니라 "DLY"/"DAILY" 단독(시간범위 없음)도 매일 24시간(리뷰 지적, 일관성)
        return {"status": "structured", "segments": [{"days": list(_DAY_ORDER), "utc_start": 0, "utc_end": 2400}]}

    segments: list[dict[str, Any]] = []
    # 콤마로 나열된 여러 구간 중 요일 지정이 없는 구간은 **직전 구간의 요일을 물려받는다**
    # (예: "MON-FRI 0600-0900Z, 1300-1600Z" — 두 시간대 모두 월~금이지 매일이 아니다).
    # 리뷰에서 발견(2026-07-24): 이전 버전은 요일 생략 구간을 무조건 매일로 채워, 원문이
    # 명시하지 않은 주말 활성을 조용히 지어내는 "허위 구조화" 버그였다(doc13 안전 우선
    # 원칙 위반 방향). 맨 첫 구간이 요일 생략이면 실측 패턴대로 매일(예: "2100-1300Z" 단독).
    current_days: list[str] | None = None
    for idx, chunk in enumerate(text.split(",")):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _TIME_RANGE_RE.search(chunk)
        if not m:
            return {"status": "confirm_required", "reason": f"시간범위 패턴 불일치: {chunk!r}"}
        utc_start, utc_end = int(m.group(1)), int(m.group(2))
        day_part = chunk[: m.start()].replace("++", "").strip()
        if not day_part:
            if idx == 0:
                days = list(_DAY_ORDER)
            elif current_days is not None:
                days = current_days
            else:
                return {"status": "confirm_required", "reason": f"요일 정보 없음: {text!r}"}
        else:
            days = []
            for tok in day_part.upper().split():
                expanded = _expand_day_token(tok)
                if expanded is None:
                    return {"status": "confirm_required", "reason": f"요일 패턴 불일치: {day_part!r}"}
                days.extend(expanded)
        current_days = days
        segments.append({"days": days, "utc_start": utc_start, "utc_end": utc_end})

    if not segments:
        return {"status": "confirm_required", "reason": f"패턴 불일치: {text!r}"}
    return {"status": "structured", "segments": segments}


def _read_dafif_suas_rows() -> list[dict[str, str]]:
    path = settings.porting_package_root / _DAFIF_SUAS_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"DAFIF SUAS_PAR.TXT 누락: {path} (PORTING_PACKAGE_ROOT 경로 확인, docs/08 §1)"
        )
    with path.open(encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def build_suas_schedule() -> list[dict[str, Any]]:
    """DAFIF 전체 행 → (ident, eff_times_raw, status, segments) 목록. 같은 ident가 여러 번
    나오면(실측 확인 2026-07-24: 18,426건 중 61개 ident가 중복 — DAFIF 리비전 이력으로 보임)
    파일에 등장한 순서상 마지막 값으로 덮어쓴다(결정적 — csv.DictReader는 파일 순서 그대로 읽음)."""
    rows = _read_dafif_suas_rows()
    by_ident: dict[str, dict[str, Any]] = {}
    for r in rows:
        ident = (r.get("SUAS_IDENT") or "").strip()
        if not ident:
            continue
        raw = r.get("EFF_TIMES")
        parsed = parse_eff_times(raw)
        by_ident[ident] = {
            "ident": ident,
            "eff_times_raw": raw,
            "status": parsed["status"],
            "segments": parsed.get("segments"),
        }
    return list(by_ident.values())


def _persist(schedule_rows: list[dict[str, Any]]) -> None:
    # DAFIF 파일이 비정상적으로 비었거나(손상·빈 파일) 파싱이 전부 실패한 경우, 여기서
    # 그냥 진행하면 TRUNCATE가 기존 정상 데이터를 지우고 아무것도 다시 채우지 않아 이후
    # 모든 SUAS가 조용히 발효시간 없는 상태(schedule_status=null)로 보인다 — 데이터
    # 결측과 배치 고장을 구분 못 하게 되므로, 0건이면 여기서 명시적으로 실패시킨다
    # (리뷰 지적, 2026-07-24). DAFIF SUAS_PAR.TXT는 항상 18,000건 이상이라 정상 상황에서
    # 0건이 나올 수 없다.
    if not schedule_rows:
        raise RuntimeError("SUAS 발효시간 파싱 결과 0건 — DAFIF SUAS_PAR.TXT 손상/빈 파일 의심, 기존 데이터 보존을 위해 적재 중단")
    generated_at = datetime.now(timezone.utc)
    for row in schedule_rows:
        row["generated_at"] = generated_at
    engine = artifact_session.get_engine()
    with engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE advisor_suas_schedule;"))
        conn.execute(sa.insert(_SUAS_SCHEDULE), schedule_rows)


def run() -> list[dict[str, Any]]:
    schedule_rows = build_suas_schedule()
    _persist(schedule_rows)
    structured = sum(1 for r in schedule_rows if r["status"] == "structured")
    print(
        f"suas 발효시간 DB 적재: 총 {len(schedule_rows)}건 (구조화 {structured} · 확인필요 {len(schedule_rows) - structured})",
        file=sys.stderr,
    )
    return schedule_rows


if __name__ == "__main__":
    run()
