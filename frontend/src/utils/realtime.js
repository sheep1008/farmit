import { formatKstTime } from './dates'

// 당일 경매 가격의 상태 문구 (docs/api.md 2.3 GET /api/prices/realtime 의 status 표).
// collectedAt: meta.collected_at (마지막 수집 시각). 경매 중일 때 "몇 시 기준"으로 보여 준다.
export function realtimeStatusText(status, collectedAt) {
  if (status === 'live') return `경매 중 · ${formatKstTime(collectedAt)} 기준`
  if (status === 'closed') return '오늘 경매 종료 · 확정 전'
  if (status === 'no_trade') return '오늘 거래 없음'
  return ''
}
