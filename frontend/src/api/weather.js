import http from './http'

// 날씨 API (docs/api.md 2.9). 회원 전용.

/**
 * 내 위치의 현재 날씨 GET /api/weather/current (REQ-HOM-002).
 * 반환: { location, summary, sky, precip_type, temp_c, humidity_pct, rain_mm_1h, wind_ms, observed_at }
 * 날씨를 못 받으면 503 DATA_NOT_READY (공통 토스트 없음, 화면이 날씨만 감춘다).
 */
export async function fetchCurrentWeather() {
  const res = await http.get('/weather/current')
  return res.data.data
}
