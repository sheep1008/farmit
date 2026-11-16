import http from './http'

// 알림 API (docs/api.md 2.4). 세 API 모두 로그인 필요 — 401이면 인터셉터가 로그인 화면으로 보낸다.

/** 알림 목록 GET /api/alerts. 반환: { data: [...], meta: { page, size, total } } 최신 발생순 */
export async function fetchAlerts({ unread = false, page = 1, size = 20 } = {}) {
  const res = await http.get('/alerts', { params: { unread, page, size } })
  return res.data
}

/** 알림 상세 + 대응 체크리스트 GET /api/alerts/{id}. 열기만 해서는 읽음 처리되지 않는다 */
export async function fetchAlert(id) {
  const res = await http.get(`/alerts/${id}`)
  return res.data.data
}

/** 읽음 처리 PATCH /api/alerts/{id}/read. 반환: 목록 항목 모양 (read_at 채워짐) */
export async function markAlertRead(id) {
  const res = await http.patch(`/alerts/${id}/read`)
  return res.data.data
}

/** 과거 사례 GET /api/cases (로그인 필요 없음). 반환: { data: [...], meta: { summary, notice, ... } } */
export async function fetchCases({ itemId, eventType } = {}) {
  const res = await http.get('/cases', { params: { item_id: itemId, event_type: eventType || undefined } })
  return res.data
}
