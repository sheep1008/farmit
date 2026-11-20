// 대시보드(SCR-003) 카드에서 쓰는 순수 함수. 화면 컴포넌트와 떼어 테스트한다 (tests/dashboard.test.js).

const STATUS_ORDER = { live: 0, closed: 1, no_trade: 2 }

/**
 * 당일 경매가 카드에 보일 시장 줄. 수집 시장이 전국 32곳이라 거래가 있는 시장만, 경매 중 → 종료 순,
 * 같은 상태끼리는 거래량이 많은 순으로 limit곳까지. hidden은 거래가 있지만 카드에 못 넣은 시장 수.
 */
export function summarizeRealtime(rows, limit = 4) {
  const traded = (rows ?? [])
    .filter((r) => r.status !== 'no_trade')
    .sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) || (b.volume_kg ?? 0) - (a.volume_kg ?? 0))
  return { rows: traded.slice(0, limit), hidden: Math.max(0, traded.length - limit) }
}

/**
 * 이번 달 할 일 카드 요약 (GET /api/farming/monthly 의 data).
 * 농작업은 이번 달 시작 → 계속 순서로 limit개까지, 나머지는 hidden 수로만. 주의 시기는 cautionLimit개까지.
 */
export function summarizeMonthly(data, { limit = 4, cautionLimit = 2 } = {}) {
  const tasks = [
    ...(data?.start ?? []).map((t) => ({ ...t, tag: '시작' })),
    ...(data?.continue ?? []).map((t) => ({ ...t, tag: '계속' })),
  ]
  const cautions = data?.caution ?? []
  return {
    tasks: tasks.slice(0, limit),
    hidden: Math.max(0, tasks.length - limit),
    cautions: cautions.slice(0, cautionLimit),
  }
}

/**
 * 이번 주 예측 카드 요약 (GET /api/forecasts 의 data, 시장 × horizon 1~4 행).
 * 이번 주(horizon 1) 예측가가 높은 시장 limit곳과 지난주 대비 변화율(%), 예측이 있는 시장 수, 명절 주의 문구.
 */
export function summarizeForecast(rows, { limit = 3 } = {}) {
  const thisWeek = (rows ?? []).filter((r) => r.horizon === 1 && r.pred_price != null)
  const top = [...thisWeek]
    .sort((a, b) => b.pred_price - a.pred_price)
    .slice(0, limit)
    .map((r) => ({
      ...r,
      // 지난주 실제 가격이 없거나 0이면 변화율을 계산하지 않는다
      change_pct: r.last_week_price ? (r.pred_price / r.last_week_price - 1) * 100 : null,
    }))
  return {
    top,
    marketCount: thisWeek.length,
    targetWeek: thisWeek[0]?.target_week ?? null,
    holidayNotice: thisWeek.find((r) => r.holiday_notice)?.holiday_notice ?? null,
  }
}

/** 원/kg 가격을 "3,420원"처럼. 값이 없으면 "-" */
export function formatWon(v) {
  return v == null ? '-' : `${Math.round(v).toLocaleString('ko-KR')}원`
}

/**
 * 현재 날씨 아이콘 (GET /api/weather/current). 강수가 있으면 강수 형태, 없으면 하늘 상태로 고른다.
 * 맑은 밤(관측 시각이 한국 시간 19시~다음 날 6시 전)은 달로 보여 준다.
 */
export function weatherIcon(w) {
  const p = w.precip_type
  if (p) return p.includes('눈') ? '🌨️' : '🌧️'
  if (w.sky === '맑음') {
    const hour = Number((w.observed_at ?? '').slice(11, 13) || 12) // 응답은 한국 시간 ISO (…T11:00:00+09:00)
    return hour >= 19 || hour < 6 ? '🌙' : '☀️'
  }
  if (w.sky === '구름 많음') return '⛅'
  if (w.sky === '흐림') return '☁️'
  return '🌡️'
}

/** 현재 날씨의 보조 값 목록. 예: ['강수 0.5mm', '습도 68%']. 비·눈이 없으면 강수는 뺀다. */
export function weatherDetails(w) {
  return [
    w.rain_mm_1h > 0 ? `강수 ${w.rain_mm_1h}mm` : null,
    w.humidity_pct == null ? null : `습도 ${Math.round(w.humidity_pct)}%`,
    w.wind_ms == null ? null : `바람 ${w.wind_ms}m/s`,
  ].filter(Boolean)
}
