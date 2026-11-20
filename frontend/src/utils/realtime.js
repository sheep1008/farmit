import { formatKstTime, todayKst } from './dates'

// 당일 경매 가격의 상태 문구 (docs/api.md 2.3 GET /api/prices/realtime 의 status 표).
// API는 "이 시장 경매가 끝났다"는 신호를 주지 않는다 (status: live 는 17시 전이라는 뜻일 뿐).
// 그래서 마지막 낙찰 시각(last_auction_at)으로 나눠 보여 준다.

// 마지막 낙찰이 이 시간 안이면 "경매 중"으로 본다. API 반영이 30분쯤 묶여 늦게 오므로 넉넉히 1시간
const ACTIVE_MS = 60 * 60 * 1000

// 화면에서 쓰는 상태: active(낙찰이 들어오는 중) · quiet(한동안 낙찰 없음) · closed · no_trade
export function realtimeState(row, now = new Date()) {
  if (row.status !== 'live') return row.status
  return now - new Date(row.last_auction_at) <= ACTIVE_MS ? 'active' : 'quiet'
}

// 마지막 낙찰 시각. 정산일자에는 전날 오후 경매분도 들어 있어, 오늘이 아니면 "어제"를 붙인다
function auctionTime(iso, now) {
  const time = formatKstTime(iso)
  return todayKst(new Date(iso)) === todayKst(now) ? time : `어제 ${time}`
}

export function realtimeStatusText(row, now = new Date()) {
  const state = realtimeState(row, now)
  if (state === 'active') return `경매 중 · ${auctionTime(row.last_auction_at, now)}`
  if (state === 'quiet') return `${auctionTime(row.last_auction_at, now)} 낙찰`
  if (state === 'closed') return '오늘 경매 종료 · 확정 전'
  if (state === 'no_trade') return '오늘 거래 없음'
  return ''
}

const STATE_ORDER = { active: 0, quiet: 1, closed: 1, no_trade: 2 }

// 경매 중인 시장 → 그 밖의 거래 시장 → 거래 없는 시장 순. 같은 묶음 안에서는 받은 순서 그대로
export function sortRealtime(rows, now = new Date()) {
  const order = (r) => STATE_ORDER[realtimeState(r, now)] ?? 9
  return [...rows].sort((a, b) => order(a) - order(b))
}
