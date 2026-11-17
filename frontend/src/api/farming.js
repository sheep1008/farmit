import http from './http'

// 재배 API (docs/api.md 2.8). 증상 진단만 회원 전용이고 나머지는 로그인 없이 쓴다.

/**
 * 이번 달 할 일 GET /api/farming/monthly (REQ-RAG-002). month를 빼면 서버가 한국 시간 오늘의 월로 계산한다.
 * 반환: { data: { item, month, available, start, continue, next, growth, caution }, meta: { source, license, message? } }
 * 일정이 없는 품목도 200 + available: false + meta.message.
 */
export async function fetchMonthlyTasks(itemId, month) {
  const res = await http.get('/farming/monthly', { params: { item_id: itemId, month } })
  return res.data
}

/**
 * 연간 작업 일정 GET /api/farming/calendar (REQ-RAG-003). 월 × 상·중·하순 36칸 간트 막대.
 * 반환: { data: { item, available, bars: [{ task, kind, period, start, end }] }, meta: { today_index, slots, source, license } }
 * end는 끝 칸의 다음 칸(막대 길이 = end − start). 해를 넘는 작업은 막대 두 개로 온다.
 */
export async function fetchCalendar(itemId) {
  const res = await http.get('/farming/calendar', { params: { item_id: itemId } })
  return res.data
}

/**
 * 품목 요약 GET /api/farming/summary (REQ-RAG-006).
 * 반환: { data: { item, crop_name, pest_count, fieldtech_count, schedule: { available, task_count, first_task, last_task } }, meta }
 */
export async function fetchSummary(itemId) {
  const res = await http.get('/farming/summary', { params: { item_id: itemId } })
  return res.data
}

/**
 * 처음 할 일 GET /api/farming/guide (REQ-RAG-004). 농작업을 시작 시기 순으로.
 * 반환: { data: { item, available, steps: [{ task, kind, period, start_month }] }, meta }
 */
export async function fetchGuide(itemId) {
  const res = await http.get('/farming/guide', { params: { item_id: itemId } })
  return res.data
}

/**
 * 증상 진단 POST /api/farming/diagnose (REQ-RAG-001, 회원). 채팅 하루 한도에 포함된다 (429 CHAT_DAILY_LIMIT).
 * 반환: { data: { item, symptom, candidates: [{ name, matching, distinguish, action, evidence: [n] }],
 *                sources: [{ n, title, source_label, url, license }], notice, disclaimer, message? },
 *        meta: { remaining_today } }
 * 근거가 없으면 candidates: [] + data.message. 진단 자료가 없는 품목은 400.
 */
export async function diagnose(itemId, symptom) {
  const res = await http.post('/farming/diagnose', { item_id: itemId, symptom })
  return res.data
}
