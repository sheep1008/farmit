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
