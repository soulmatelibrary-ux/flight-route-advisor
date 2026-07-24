"""AI 근거화 모드 C(백엔드 프록시) 스켈레톤 (docs/13-ai-reasoning-dev-plan.md STEP C4, D9).

**이 라우터는 비활성이다.** 어떤 요청도 실제로 외부 LLM을 호출하지 않는다 — 아래 두 게이트가
전부 501을 반환한다: ① `REASONING_PROXY_ENABLED`(기본 false) ② 제공자/모델 미확정([14 §8.1]
(../../../docs/14-improvement-request.md) C-7, 값이 있어도 실제 호출 로직 자체가 스텁). 목표는
"향후 모드 C를 켤 때 갈아끼울 자리"를 지금 만들어 두는 것뿐이다(STEP C4 목표).

## 경계(수용기준: "reasoning-context.js(순수)·프롬프트 빌더를 서버에서 재사용할 수 있는 경계가
문서화됨") — 이 서버는 `reasoning-context.js`(B2)·`reasoning-prompt.js`(C1)를 Python으로
재구현하지 않는다. 프론트가 그 두 순수 함수로 이미 만들어 둔 `buildPrompt()`의 반환값
`{system, user, combined}` 중 **`system`/`user` 두 필드만**(`combined`은 D1 수동복붙 UI 전용,
이 엔드포인트는 쓰지 않음) 요청 본문으로 받을 뿐이다 — 즉 "컨텍스트 조립 + 프롬프트 조립"은
항상 프론트(JS, 이미 리뷰·검증됨)가 단일 출처로 담당하고, 이 서버는 "그 결과를 제공자 API로
전달 + 응답을 그대로 반환"만 한다. 이렇게 하면 D1(수동복붙)과 모드 C(자동호출)가 완전히 동일한
프롬프트 생성 경로를 공유하며, 로직이 두 언어(JS/Python)로 중복되지 않는다.

**호출 주체는 여전히 브라우저 세션이다.** "자동 호출"은 doc13 §1이 뜻하는 대로 "사람이
프롬프트를 복사해 외부 AI에 붙여넣는 수작업을 자동화"하는 것뿐 — `reasoningContext` 자체는
실시간 ADS-B·상층풍(Open-Meteo) 조회에 의존하므로(A3/A4) 여전히 살아있는 브라우저 탭에서만
조립 가능하다. 이 서버가 헤드리스로 컨텍스트를 스스로 재생성할 수 있다는 뜻이 아니다.

응답 검증도 마찬가지로 중복하지 않는다 — 이 라우터는 업스트림 응답을 있는 그대로(`raw`)
반환하고, D6 스키마 검증·길이 상한·XSS 방어는 프론트의 기존 `reasoning-response.js`(C3, 이미
리뷰·단위테스트 완료)가 D1과 동일하게 수행한다. 모드 C 활성화가 "새 검증 로직"을 요구하지 않도록
하는 것이 이 경계의 핵심이다.

## 향후 실제 구현 시 지킬 것(주석/스텁으로만 남김, docs/06-conventions.md §3 시큐어코딩)
- **키·엔드포인트는 env로만**(`REASONING_PROXY_API_KEY`/`REASONING_PROXY_PROVIDER_URL`,
  `app/config.py` 참고) — 코드에 리터럴 금지, 커밋 금지(.env.example엔 빈 값만).
  `Settings.__repr__`가 키를 `***set***`으로만 마스킹하는 것처럼, 실제 구현도 키를 로그·에러
  메시지·응답 본문에 절대 포함하지 않아야 한다.
- **요청량 제한**: `main.py`에 이미 전역 적용된 `RateLimitMiddleware`(모든 라우트 공통, IP별
  슬라이딩 윈도우)가 이 라우터에도 그대로 적용된다 — 별도 리미터 불필요. 다만 외부 LLM
  API는 자체 요금제/쿼터가 있으므로, 실제 구현 시 업스트림 429/한도초과를 503으로 변환해
  (기존 DB 연결실패 패턴과 동일) 내부 사정을 노출하지 않을 것.
- **로그 규약**: `main.py`의 `RequestLoggingMiddleware`는 method/path/status/elapsed만 기록하고
  요청/응답 본문은 남기지 않는다(이미 안전) — 실제 구현이 디버깅용으로 별도 로깅을 추가한다면
  프롬프트 원문(경로·기상·흐름관리 등 운영 데이터 포함)과 API 키를 로그에 남기지 않을 것.
- **타임아웃**: `Settings.reasoning_proxy_timeout_s`(기본 20초) — 업스트림 호출에 반드시 적용해
  응답 없는 요청이 워커를 무기한 점유하지 않게 할 것(`net.js`의 `netTimeoutMs`와 동일한 이유).
- **입력 검증**: 아래 `ReasoningPromptRequest`가 이미 최소 길이 상한을 강제한다(신뢰 못 할 클라이언트
  입력이므로) — 실제 구현 시 이 상한을 낮추기보다 프론트 `CONFIG.reasoning`(C3) 상한과의 정합을
  먼저 확인할 것.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter(prefix="/api/reasoning", tags=["reasoning"])

# 실제 프롬프트는 system(템플릿, 수 KB)+user(reasoningContext JSON 포함) 형태(C1 실측 5,473자
# 수준) — 넉넉한 상한이되 무제한은 아니게(신뢰 못 할 클라이언트 입력, docs/06 §3).
_MAX_PROMPT_LEN = 50_000


class ReasoningPromptRequest(BaseModel):
    """C1 `buildPrompt()`의 반환값 `{system, user}`을 그대로 받는다(위 모듈 docstring "경계" 참고)."""

    system: str = Field(..., min_length=1, max_length=_MAX_PROMPT_LEN)
    user: str = Field(..., min_length=1, max_length=_MAX_PROMPT_LEN)


@router.post("/complete")
def post_reasoning_complete(payload: ReasoningPromptRequest):
    """모드 C(자동 호출) — 현재 항상 501. `payload`는 스키마 검증(길이 상한)까지만 거치고,
    실제 업스트림 호출은 하지 않는다(스텁)."""
    if not settings.reasoning_proxy_enabled:
        raise HTTPException(
            status_code=501,
            detail="모드 C(자동 호출)는 비활성 상태(REASONING_PROXY_ENABLED=false) — D1 수동복붙만 지원",
        )
    raise HTTPException(
        status_code=501,
        detail="제공자/모델 미확정(docs/14-improvement-request.md §8.1 C-7) — 실제 호출 로직 미구현",
    )
