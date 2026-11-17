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

/**
 * 주간 가격 예측 GET /api/forecasts (docs/api.md 2.5, K13). 가장 최근 기준 주의 시장 × horizon 1~4 행.
 * 반환: { data: [{ market_name, horizon, pred_price, lower80, upper80, last_week_price, holiday_notice, ... }],
 *        meta: { forecast_available, base_week, is_stale, message? } }
 * 예측 대상이 아닌 품목은 200 + forecast_available false, 예측 행이 아직 없으면 503 DATA_NOT_READY.
 */
export async function fetchForecasts(itemId) {
  const res = await http.get('/forecasts', { params: { item_id: itemId } })
  return res.data
}
