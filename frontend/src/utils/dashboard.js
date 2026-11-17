// 대시보드(SCR-003) 카드에서 쓰는 순수 함수. 화면 컴포넌트와 떼어 테스트한다 (tests/dashboard.test.js).

const STATUS_ORDER = { live: 0, closed: 1, no_trade: 2 }

/**
 * 당일 경매가 카드에 보일 시장 줄. 거래가 있는 시장(경매 중 → 종료)을 위로, 거래 없는 시장은 아래로.
 * 같은 상태끼리는 API 순서를 지킨다 (Array.prototype.sort는 안정 정렬).
 */
export function sortRealtimeRows(rows) {
  return [...(rows ?? [])].sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9))
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
