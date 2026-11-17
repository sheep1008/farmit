import http from './http'

// 통합 검색 API (docs/api.md 2.9). 로그인 없이 쓴다.

/**
 * 검색 GET /api/search (REQ-SRC-001·002).
 * type: 'item'(품목 이름 일부) · 'market'(시장 이름 일부) · 'press'(보도자료 제목·요약, 형태소 검색)
 * 반환: { data: [...], meta: { type, q, total, page, size, license? } }
 *   item → { item_id, name, category }, market → { market_id, name, sido },
 *   press → { title, summary, published_date, source, url }
 * 결과가 없거나 보도자료 첫 수집 전이면 200 + []. 보도자료 저장소에 못 닿으면 503.
 */
export async function search(q, type, { page = 1, size = 20 } = {}) {
  const res = await http.get('/search', { params: { q, type, page, size } })
  return res.data
}
