// 판매 추천 화면(SCR-005)의 입력·표시 도우미 (docs/api.md 2.5 POST /api/recommendations).
import { addDays, mondayOf } from './dates'

const COST_FIELDS = ['transport_cost_per_km', 'storage_cost_per_week', 'loss_rate']

// 처음 폼 값. 비용 칸은 내 정보(SCR-015) 값으로 채우고, 없으면 빈 칸(= 서버가 내 정보 값 → 0을 쓴다)
export function recommendForm(user, itemId) {
  const form = { item_id: itemId, volume_kg: '', desired_week: '' }
  for (const key of COST_FIELDS) form[key] = user?.[key] ?? ''
  return form
}

// 폼 값 → 요청 본문. 빈 칸은 보내지 않는다 (서버 기본값을 쓰게)
export function recommendBody(form) {
  const body = { item_id: form.item_id, volume_kg: form.volume_kg }
  for (const key of ['desired_week', ...COST_FIELDS]) {
    if (form[key] !== '' && form[key] != null) body[key] = form[key]
  }
  return body
}

// horizon 1 = 이번 주 … 4 = 3주 후 (api.md 2.5)
export const horizonLabel = (h) => (h === 1 ? '이번 주' : `${h - 1}주 후`)

// 희망 시기 선택지: 이번 주~3주 후 월요일. 값은 그 주 월요일 날짜(서버는 그 날짜가 든 주에 is_desired 표시)
export function desiredWeekOptions(today) {
  const monday = mondayOf(today)
  return [1, 2, 3, 4].map((h) => ({ value: addDays(monday, (h - 1) * 7), label: horizonLabel(h) }))
}

// 'YYYY-MM-DD' 월요일 → '11/16~11/22' (대상 주 범위)
export function weekRange(monday) {
  const md = (s) => `${Number(s.slice(5, 7))}/${Number(s.slice(8, 10))}`
  return `${md(monday)}~${md(addDays(monday, 6))}`
}

// ── 2단계: 근거·주의 (REQ-REC-004·005·006, REQ-PRD-002·003, REQ-SAL-003) ──────────

// 예측가가 지난주 시세보다 몇 % 다른지. 지난주 시세가 없으면 null
export function vsLastWeek(pred, last) {
  if (!last) return null
  const pct = (pred / last - 1) * 100
  const text = `${pct >= 0 ? '+' : '−'}${Math.abs(pct).toFixed(1)}%`
  return { text, tone: pct > 0 ? 'up' : pct < 0 ? 'down' : 'same' }
}

// 휴장일 목록 → '휴장 11/20, 11/21'
export function closedText(dates) {
  return `휴장 ${dates.map((d) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`).join(', ')}`
}

// 결과에 나온 명절 주의 문구 (같은 문구는 한 번만)
export function holidayNotices(results) {
  return [...new Set(results.map((r) => r.holiday_notice).filter(Boolean))]
}

// 연간 작업 일정(GET /api/farming/calendar)의 막대 중 수확 작업만 [{ task, period }]
export function harvestPeriods(bars) {
  return bars.filter((b) => b.kind === '농작업' && b.task.includes('수확')).map(({ task, period }) => ({ task, period }))
}

export const PAY_RATIO_MIN_RECORDS = 3 // 기록이 3건 이상일 때만 보여 준다 (REQ-SAL-003)

// 내 평균 수취율: 이 품목 판매 기록 중 같은 날 평균가가 있는 것으로
// 받은 금액 합 ÷ (평균가 × 물량) 합 × 100. 큰 거래가 더 크게 반영된다. 기록이 모자라면 null
export function myPayRatio(sales, itemId) {
  const rows = sales.filter((s) => s.item_id === itemId && s.avg_price)
  if (rows.length < PAY_RATIO_MIN_RECORDS) return null
  const paid = rows.reduce((sum, s) => sum + s.amount_won, 0)
  const market = rows.reduce((sum, s) => sum + s.avg_price * s.volume_kg, 0)
  return { pct: Math.round((paid / market) * 1000) / 10, count: rows.length }
}

// 최근 days일 안에 생긴 알림만 (occurred_at은 KST ISO 문자열, today는 'YYYY-MM-DD')
export function recentAlerts(alerts, today, days = 14) {
  const from = addDays(today, -days)
  return alerts.filter((a) => a.occurred_at.slice(0, 10) >= from)
}

// ── 3단계: "지금 팔면" · 채팅 (REQ-REC-003·007) ─────────────────────

// "지금 팔면"(POST /api/recommendations/now) 본문: 지금 파는 것이라 희망 시기·보관비는 없다
export function sellNowBody(form) {
  const body = recommendBody(form)
  delete body.desired_week
  delete body.storage_cost_per_week
  return body
}

// "채팅으로 물어보기"에 미리 채울 질문. 판매 상담은 품목·물량이 있어야 계산하므로 꼭 넣는다 (api.md 2.7)
// top: 지금 보고 있는 표의 1위 행 (주간 추천이면 horizon이 있다). 없으면 질문만
export function recommendChatQuestion(itemName, volumeKg, top) {
  const ask = `${itemName} ${volumeKg}kg을 언제, 어느 시장에 팔면 좋을까요?`
  if (!top) return ask
  const when = top.horizon ? ` ${horizonLabel(top.horizon)}` : ' 지금'
  const won = Math.round(top.net_won).toLocaleString('ko-KR')
  return `${ask} 판매 추천 1위는${when} ${top.market_name}(예상 ${won}원)인데, 그 이유와 주의할 점이 궁금해요.`
}
