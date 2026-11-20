// 재배 정보(SCR-012) 화면에서 쓰는 순수 함수. 화면 컴포넌트와 떼어 테스트한다 (tests/farming.test.js).

const PERIODS = ['상순', '중순', '하순']
// 간트에서 위에서부터 보일 종류 순서 (api.md 2.8의 kind 값)
const KIND_ORDER = ['농작업', '생육 단계', '주의 시기']

/** 간트 칸 번호(0 = 1월 상순 … 35 = 12월 하순)를 "3월 상순"처럼 */
export function slotLabel(index) {
  return `${Math.floor(index / 3) + 1}월 ${PERIODS[index % 3]}`
}

/**
 * 간트 막대를 화면의 줄로 묶는다 (GET /api/farming/calendar 의 data.bars).
 * 해를 넘는 작업은 막대 두 개로 오므로, 같은 작업·종류는 한 줄에 조각(segments) 여러 개로 그린다.
 * 줄 순서: 농작업 → 생육 단계 → 주의 시기, 같은 종류 안에서는 가장 이른 시작 칸 순.
 */
export function ganttRows(bars) {
  const rows = new Map()
  for (const b of bars ?? []) {
    const key = `${b.kind}|${b.task}`
    if (!rows.has(key)) rows.set(key, { key, task: b.task, kind: b.kind, period: b.period, segments: [] })
    const row = rows.get(key)
    row.segments.push({ start: b.start, end: b.end })
    // 한 해에 두 번 하는 작업(예: 웃거름 5월·10월)은 기간 문구를 이어 붙인다. 해를 넘는 막대 두 개는 문구가 같다
    if (!row.period.split(', ').includes(b.period)) row.period += `, ${b.period}`
  }
  const kindRank = (k) => (KIND_ORDER.includes(k) ? KIND_ORDER.indexOf(k) : KIND_ORDER.length)
  const firstStart = (r) => Math.min(...r.segments.map((s) => s.start))
  return [...rows.values()].sort((a, b) => kindRank(a.kind) - kindRank(b.kind) || firstStart(a) - firstStart(b))
}

/** 증상 설명 최대 글자 수 (api.md 2.8 diagnose, symptom 1~300자) */
export const SYMPTOM_MAX_LENGTH = 300

/** 진단 후보의 근거 번호(evidence)를 응답의 출처 목록에서 찾아 붙인다. 목록에 없는 번호는 뺀다. */
export function candidateSources(candidate, sources) {
  const byN = new Map((sources ?? []).map((s) => [s.n, s]))
  return (candidate?.evidence ?? []).map((n) => byN.get(n)).filter(Boolean)
}

/** "채팅으로 이어 묻기"에 넣을 질문. 후보가 없으면 증상만으로 묻는다. 보내기는 사용자가 채팅 화면에서 누른다. */
export function diagnoseFollowUp(itemName, symptom, candidate = null) {
  return candidate
    ? `${itemName} ${candidate.name}에 대해 더 알려줘. 내 증상: ${symptom}`
    : `${itemName}에 이런 증상이 있어. 원인이 뭘까? ${symptom}`
}

/** 주간농사정보 기간 "2026-11-16"·"2026-11-22" → "11월 16일~22일" (달이 다르면 "9월 28일~10월 4일"). 기간이 없으면 '' */
export function weeklyPeriodText(start, end) {
  if (!start || !end) return ''
  const [, sm, sd] = start.split('-').map(Number)
  const [, em, ed] = end.split('-').map(Number)
  return `${sm}월 ${sd}일~${sm === em ? '' : `${em}월 `}${ed}일`
}

/** 요약 항목 "(과원 정비) 낙엽 제거" → { topic: '과원 정비', text: '낙엽 제거' }. 괄호로 시작하지 않으면 topic은 '' */
export function splitWeeklyItem(item) {
  const m = /^\(([^)]+)\)\s*(.*)$/s.exec(item ?? '')
  return m ? { topic: m[1], text: m[2] } : { topic: '', text: item ?? '' }
}

/** 재배 정보 탭: 내 품목 분야(focus)를 맨 앞에, 나머지는 원문 순서 그대로 (GET /api/farming/weekly 의 data) */
export function orderWeeklySections(data) {
  const sections = data?.sections ?? []
  return [...sections.filter((s) => s.section === data?.focus), ...sections.filter((s) => s.section !== data?.focus)]
}

/**
 * 홈 카드 요약: 내 품목 분야(없으면 첫 분야)의 항목을 limit개까지, 나머지는 hidden 수로만.
 * 요약을 읽지 못한 호는 section: null.
 */
export function summarizeWeeklyFarm(data, limit = 3) {
  const section = orderWeeklySections(data)[0]
  if (!section) return { section: null, items: [], hidden: 0 }
  return {
    section: section.section,
    items: section.items.slice(0, limit).map(splitWeeklyItem),
    hidden: Math.max(0, section.items.length - limit),
  }
}

// ── 마지막 증상 진단 보관 (REQ-CHT-010) ─────────────────
// 다른 화면에 갔다 와도 올린 사진과 결과가 보이게, 마지막 진단 1건을 이 브라우저(localStorage)에만 둔다.
// 서버는 사진을 저장하지 않는다. 로그아웃하면 지운다 (stores/auth.js).
const LAST_DIAGNOSIS_KEY = 'farmit.lastDiagnosis'

/** entry: { itemId, symptom, photo(data URL 또는 ''), data(응답의 data) } */
export function saveLastDiagnosis(entry) {
  try {
    globalThis.localStorage?.setItem(LAST_DIAGNOSIS_KEY, JSON.stringify(entry))
  } catch {
    // 저장 공간이 모자라면 보관하지 않는다 (진단 결과는 화면에 그대로 있다)
  }
}

/** 보관한 진단이 그 품목 것이면 돌려준다. 없거나 다른 품목이면 null */
export function loadLastDiagnosis(itemId) {
  try {
    const entry = JSON.parse(globalThis.localStorage?.getItem(LAST_DIAGNOSIS_KEY) ?? 'null')
    return entry && entry.itemId === itemId && entry.data ? entry : null
  } catch {
    return null
  }
}

export function clearLastDiagnosis() {
  try {
    globalThis.localStorage?.removeItem(LAST_DIAGNOSIS_KEY)
  } catch {
    // 저장소를 못 쓰는 브라우저: 넣은 것도 없다
  }
}
