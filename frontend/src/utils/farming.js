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
