import http from './http'

// 가격 API (docs/api.md 2.3). 로그인 없이 쓴다.

/**
 * 당일 경매 가격 GET /api/prices/realtime (K27).
 * 반환: { data: [{ market_id, market_name, avg_price, status, ... }], meta: { collected_at, price_unit } }
 * 오늘 수집 전이면 503 DATA_NOT_READY — 인터셉터가 토스트를 띄우지 않고 e.apiError로 넘긴다.
 */
export async function fetchRealtimePrices(itemId) {
  const res = await http.get('/prices/realtime', { params: { item_id: itemId } })
  return res.data
}
