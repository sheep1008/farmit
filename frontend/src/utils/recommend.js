// 판매 추천 화면(SCR-005)의 입력·표시 도우미 (docs/api.md 2.5 POST /api/recommendations).
import { addDays, mondayOf } from './dates'

const COST_FIELDS = ['transport_cost_per_km', 'storage_cost_per_week', 'loss_rate']

// 처음 폼 값. 비용 칸은 내 정보(SCR-015) 값으로 채우고, 없으면 빈 칸(= 서버가 내 정보 값 → 기본값을 쓴다)
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

// ── 4단계: 판매 판단 배치 (요약 카드·예측 차트·추천 한 줄) ─────────────────

export const DEFAULT_VOLUME_KG = 10 // 처음 들어오면 이 물량으로 바로 계산해 보여 준다 (조건 바꾸기에서 바꾼다)

const pctChange = (now, before) => (now != null && before ? (now / before - 1) * 100 : null)

/**
 * 한 시장의 주간 실제 가격(GET /api/prices/daily unit=week)과 예측(GET /api/forecasts) → 차트 계열.
 * baseWeek(예측 기준 주 = horizon 1 대상 주)는 아직 끝나지 않은 주라 실제 값에서 뺀다.
 * 예측·범위 선은 마지막 실제 주에서 이어 그린다. 반환 배열은 모두 periods와 길이가 같다 (없으면 null).
 */
export function forecastSeries(weekly, forecasts, marketId, baseWeek) {
  const actualRows = weekly.filter((r) => r.period < baseWeek && r.avg_price != null)
  const preds = forecasts.filter((r) => r.market_id === marketId).sort((a, b) => a.horizon - b.horizon)
  const blanks = (n) => Array(n).fill(null)
  const last = actualRows.at(-1)
  // 마지막 실제 주를 예측 선의 시작점으로 (범위도 그 점에서 벌어진다)
  const head = () => [...blanks(Math.max(actualRows.length - 1, 0)), ...(last ? [last.avg_price] : [])]
  return {
    periods: [...actualRows.map((r) => r.period), ...preds.map((r) => r.target_week)],
    actual: [...actualRows.map((r) => r.avg_price), ...blanks(preds.length)],
    pred: [...head(), ...preds.map((r) => r.pred_price)],
    lower: [...head(), ...preds.map((r) => r.lower80)],
    upper: [...head(), ...preds.map((r) => r.upper80)],
    splitIndex: actualRows.length - 1, // 마지막 실제 주 (차트의 "지금" 선)
  }
}

/**
 * 요약 카드 세 개: 지난주 평균가(전주 대비) · 2주 후 예측가(범위) · 지난주 거래 물량(전주 대비).
 * 실제 값은 끝난 주(baseWeek 전)만 쓴다. 값이 없으면 그 칸은 null.
 */
export function summaryCards(weekly, forecasts, marketId, baseWeek) {
  const done = weekly.filter((r) => r.period < baseWeek && r.avg_price != null)
  const [prev, last] = done.slice(-2).length === 2 ? done.slice(-2) : [null, done.at(-1) ?? null]
  const h3 = forecasts.find((r) => r.market_id === marketId && r.horizon === 3) // horizon 3 = 2주 후
  return {
    lastWeek: last && { period: last.period, price: last.avg_price, changePct: pctChange(last.avg_price, prev?.avg_price) },
    twoWeeks: h3 && { targetWeek: h3.target_week, price: h3.pred_price, lower: h3.lower80, upper: h3.upper80 },
    volume: last && { period: last.period, kg: last.volume_kg, changePct: pctChange(last.volume_kg, prev?.volume_kg) },
  }
}

/**
 * 추천 한 줄: 예상 수령액 1위와, 그것이 이번 주 판매가 아니면 이번 주 최고안보다 얼마 더 남는지.
 * rows는 POST /api/recommendations 의 results (rank 순). 없으면 null
 */
export function bestPick(rows) {
  const top = rows[0]
  if (!top) return null
  const thisWeek = rows.filter((r) => r.horizon === 1).sort((a, b) => b.net_won - a.net_won)[0]
  const gain = thisWeek && top.horizon !== 1 ? top.net_won - thisWeek.net_won : null
  return { top, gain }
}

// ── 예측 성적표 (K47, REQ-PRD-005, GET /api/forecasts/history) ─────────────────

export const SCORE_MIN_WEEKS = 8 // 끝난 주가 이보다 적으면 "참고만" 안내를 붙인다

// 그 예측을 대상 주보다 얼마나 먼저 했는지. horizon 1은 대상 주 월요일에 한 예측
export const scoreHorizonLabel = (h) => (h === 1 ? '그 주 초 예측' : `${h - 1}주 전 예측`)

/**
 * 성적표에서 한 horizon만 골라 화면용으로. history = { data, meta } (API 응답 그대로).
 * 반환: { rows, count, maePct, hitPct, hits } · 그 horizon의 행이 없으면 null
 */
export function scorecard(history, horizon) {
  const summary = history.meta.summary.find((s) => s.horizon === horizon)
  if (!summary) return null
  const rows = history.data.filter((r) => r.horizon === horizon)
  return {
    rows,
    count: summary.count,
    maePct: summary.mean_abs_error_pct,
    hitPct: summary.in_range_rate_pct,
    hits: rows.filter((r) => r.in_range).length,
  }
}
