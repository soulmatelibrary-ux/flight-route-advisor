/**
 * AI 근거화 프롬프트 빌더 (C1, docs/13-ai-reasoning-dev-plan.md STEP C1).
 * 프롬프트 문자열 자체는 하드코딩하지 않고 `frontend/prompts/route-reasoning.ko.txt`(config/파일
 * 리소스, §2 하드코딩 금지)에서 로드한다. `loadPromptTemplate`(fetch+모듈 캐시, 비순수)이 리소스를
 * 읽어오고, `parsePromptTemplate`/`buildPrompt`(순수)가 reasoningContext(B2 산출물, §7 스키마)를
 * 꽂아 넣는 조립만 한다 — 실제 AI 응답 수신·붙여넣기 UI는 C2, 파싱/검증·렌더는 C3의 몫(이 모듈은
 * AI를 호출하지 않는다 — D1은 수동 복붙, C4의 자동 호출 자체가 아직 비활성).
 */

const TEMPLATE_URL = "./prompts/route-reasoning.ko.txt";
const SYSTEM_MARKER = "===SYSTEM===";
const USER_MARKER = "===USER_TEMPLATE===";
const CONTEXT_PLACEHOLDER = "{{CONTEXT_JSON}}";

let cachedTemplate = null;

/** 템플릿 텍스트 파싱(순수) — 마커 2개로 system/user 섹션을 나눈다. */
export function parsePromptTemplate(text) {
  const sysIdx = text.indexOf(SYSTEM_MARKER);
  const userIdx = text.indexOf(USER_MARKER);
  if (sysIdx === -1 || userIdx === -1 || userIdx < sysIdx) {
    throw new Error("프롬프트 템플릿 형식 오류: 마커(===SYSTEM===/===USER_TEMPLATE===) 누락");
  }
  const system = text.slice(sysIdx + SYSTEM_MARKER.length, userIdx).trim();
  const user = text.slice(userIdx + USER_MARKER.length).trim();
  if (!system) throw new Error("프롬프트 템플릿 형식 오류: system 섹션이 비어 있음");
  if (!user) throw new Error("프롬프트 템플릿 형식 오류: user 섹션이 비어 있음");
  if (!user.includes(CONTEXT_PLACEHOLDER)) {
    throw new Error(`프롬프트 템플릿 형식 오류: ${CONTEXT_PLACEHOLDER} 자리표시자 누락`);
  }
  return { system, user };
}

/** 템플릿 리소스 로드(모듈 싱글턴 캐시 — config.js의 config.json 로드와 동일 패턴). */
export async function loadPromptTemplate() {
  if (cachedTemplate) return cachedTemplate;
  const res = await fetch(TEMPLATE_URL, { cache: "no-store" });
  if (!res.ok) throw new Error(`프롬프트 템플릿 로드 실패: HTTP ${res.status}`);
  const text = await res.text();
  cachedTemplate = parsePromptTemplate(text);
  return cachedTemplate;
}

/**
 * reasoningContext(§7 스키마 객체, buildReasoningContext 산출물)를 템플릿에 꽂아 최종 프롬프트를 만든다.
 * 순수 함수 — fetch·DOM 없음, 동일 입력에 항상 동일 출력(모드 C 서버 재사용 대비, §5.1 #5와 동일 원칙).
 * @param {{system: string, user: string}} template - loadPromptTemplate() 결과
 * @param {object} reasoningContext - buildReasoningContext()의 §7 스키마 객체
 * @returns {{system: string, user: string, combined: string}} combined은 D1 수동복붙(C2)용 — 시스템+유저를
 *   하나의 텍스트로 이어붙인 것(외부 AI 챗 UI는 대개 system/user 필드가 분리돼 있지 않으므로).
 */
export function buildPrompt(template, reasoningContext) {
  if (reasoningContext == null) {
    throw new Error("buildPrompt: reasoningContext가 없습니다(null/undefined)");
  }
  const contextJson = JSON.stringify(reasoningContext, null, 2);
  const user = template.user.split(CONTEXT_PLACEHOLDER).join(contextJson);
  const combined = `${template.system}\n\n${user}`;
  return { system: template.system, user, combined };
}
