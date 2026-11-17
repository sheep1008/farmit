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

/** 원/kg 가격을 "3,420원"처럼. 값이 없으면 "-" */
export function formatWon(v) {
  return v == null ? '-' : `${Math.round(v).toLocaleString('ko-KR')}원`
}
