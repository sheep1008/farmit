import { describe, expect, it } from 'vitest'
import {
  bestPick,
  closedText,
  desiredWeekOptions,
  forecastSeries,
  harvestPeriods,
  holidayNotices,
  horizonLabel,
  myPayRatio,
  recentAlerts,
  recommendBody,
  recommendChatQuestion,
  recommendForm,
  sellNowBody,
  summaryCards,
  vsLastWeek,
  weekRange,
} from '@/utils/recommend'

// docs/api.md 2.5 POST /api/recommendations — 판매 추천 입력·표시
describe('판매 추천 입력 폼', () => {
  it('비용 칸은 내 정보 값으로 채우고, 없으면 빈 칸', () => {
    const user = { transport_cost_per_km: 500, storage_cost_per_week: null, loss_rate: 2.5 }
    expect(recommendForm(user, 10)).toEqual({
      item_id: 10,
      volume_kg: '',
      desired_week: '',
      transport_cost_per_km: 500,
      storage_cost_per_week: '',
      loss_rate: 2.5,
    })
  })

  it('빈 칸은 본문에 넣지 않는다 (서버가 내 정보 값 → 0을 쓴다)', () => {
    const form = { ...recommendForm(null, 10), volume_kg: 100, loss_rate: 0 }
    expect(recommendBody(form)).toEqual({ item_id: 10, volume_kg: 100, loss_rate: 0 })
  })
})

describe('시점 표시', () => {
  it('horizon 1은 이번 주, 4는 3주 후', () => {
    expect(horizonLabel(1)).toBe('이번 주')
    expect(horizonLabel(4)).toBe('3주 후')
  })

  it('희망 시기 선택지는 이번 주 월요일부터 4주', () => {
    // 2026-11-18(수) → 이번 주 월요일 11-16
    expect(desiredWeekOptions('2026-11-18').map((o) => o.value)).toEqual([
      '2026-11-16',
      '2026-11-23',
      '2026-11-30',
      '2026-12-07',
    ])
  })

  it('대상 주는 월~일 범위로 보여 준다 (달이 바뀌어도)', () => {
    expect(weekRange('2026-11-30')).toBe('11/30~12/6')
  })
})

describe('추천 근거·주의 표시', () => {
  it('예측가를 지난주 시세와 비교한다 (시세가 없으면 null)', () => {
    expect(vsLastWeek(3300, 3000)).toEqual({ text: '+10.0%', tone: 'up' })
    expect(vsLastWeek(2850, 3000)).toEqual({ text: '−5.0%', tone: 'down' })
    expect(vsLastWeek(3000, null)).toBeNull()
  })

  it('휴장일은 월/일로, 명절 주의 문구는 한 번만', () => {
    expect(closedText(['2026-11-20', '2026-11-21'])).toBe('휴장 11/20, 11/21')
    const notice = '명절 급등 폭은 낮게 예측될 수 있음'
    expect(holidayNotices([{ holiday_notice: notice }, { holiday_notice: null }, { holiday_notice: notice }])).toEqual([
      notice,
    ])
  })

  it('수확 시기는 농작업 중 "수확"이 든 것만', () => {
    const bars = [
      { task: '수분', kind: '농작업', period: '3월 상순~4월 하순' },
      { task: '만생종수확', kind: '농작업', period: '10월 중순~11월 상순' },
      { task: '성숙 착색', kind: '생육 단계', period: '8월 하순~11월 상순' },
    ]
    expect(harvestPeriods(bars)).toEqual([{ task: '만생종수확', period: '10월 중순~11월 상순' }])
  })

  it('내 평균 수취율은 평균가가 있는 기록 3건 이상일 때 물량 가중으로', () => {
    const sale = (amount_won, avg_price, volume_kg = 100) => ({ item_id: 10, amount_won, avg_price, volume_kg })
    const two = [sale(330000, 3000), sale(300000, 3000)]
    expect(myPayRatio([...two, sale(1, null)], 10)).toBeNull() // 평균가 없는 기록은 세지 않는다
    // (330000 + 300000 + 270000) ÷ (3000 × 300) = 100%
    expect(myPayRatio([...two, sale(270000, 3000)], 10)).toEqual({ pct: 100, count: 3 })
    expect(myPayRatio([...two, sale(270000, 3000)], 11)).toBeNull() // 다른 품목
  })

  it('최근 2주 안에 생긴 알림만', () => {
    const alerts = [{ occurred_at: '2026-11-10T09:00:00+09:00' }, { occurred_at: '2026-10-30T09:00:00+09:00' }]
    expect(recentAlerts(alerts, '2026-11-17')).toHaveLength(1)
  })
})

describe('"지금 팔면"·채팅', () => {
  it('지금 팔면 본문에는 희망 시기·보관비를 넣지 않는다', () => {
    const form = { ...recommendForm(null, 1), volume_kg: 50, desired_week: '2026-11-23', storage_cost_per_week: 1000 }
    expect(sellNowBody(form)).toEqual({ item_id: 1, volume_kg: 50 })
  })

  it('채팅 질문에 품목·물량과 1위 결과를 넣는다', () => {
    expect(recommendChatQuestion('사과', 100, null)).toBe('사과 100kg을 언제, 어느 시장에 팔면 좋을까요?')
    expect(recommendChatQuestion('사과', 100, { market_name: '청주', horizon: 4, net_won: 316988 })).toContain(
      '1위는 3주 후 청주(예상 316,988원)',
    )
    expect(recommendChatQuestion('배추', 30, { market_name: '천안', net_won: 1000 })).toContain('1위는 지금 천안(예상 1,000원)')
  })
})

describe('판매 판단 배치 (요약 카드·예측 차트·추천 한 줄)', () => {
  const weekly = [
    { period: '2026-10-26', avg_price: 3000, volume_kg: 100 },
    { period: '2026-11-02', avg_price: 3100, volume_kg: 120 },
    { period: '2026-11-09', avg_price: 3300, volume_kg: 90 },
    { period: '2026-11-16', avg_price: 3600, volume_kg: 10 }, // 아직 끝나지 않은 이번 주 → 빼야 한다
  ]
  const fc = (horizon, target_week, pred_price, market_id = '250001') => ({
    market_id,
    horizon,
    target_week,
    pred_price,
    lower80: pred_price - 100,
    upper80: pred_price + 100,
  })
  const forecasts = [
    fc(2, '2026-11-23', 3400),
    fc(1, '2026-11-16', 3350),
    fc(3, '2026-11-30', 3450),
    fc(4, '2026-12-07', 3500),
    fc(1, '2026-11-16', 9999, '110001'), // 다른 시장
  ]

  it('차트: 이번 주 실제 값은 빼고, 예측 선은 마지막 실제 주에서 이어진다', () => {
    const s = forecastSeries(weekly, forecasts, '250001', '2026-11-16')
    expect(s.periods).toEqual(['2026-10-26', '2026-11-02', '2026-11-09', '2026-11-16', '2026-11-23', '2026-11-30', '2026-12-07'])
    expect(s.actual).toEqual([3000, 3100, 3300, null, null, null, null])
    expect(s.pred).toEqual([null, null, 3300, 3350, 3400, 3450, 3500])
    expect(s.lower[3]).toBe(3250)
    expect(s.splitIndex).toBe(2)
  })

  it('요약 카드: 끝난 주 기준 전주 대비 변화와 2주 후(horizon 3) 예측', () => {
    const c = summaryCards(weekly, forecasts, '250001', '2026-11-16')
    expect(c.lastWeek.price).toBe(3300)
    expect(c.lastWeek.changePct).toBeCloseTo(6.45, 1)
    expect(c.volume.changePct).toBeCloseTo(-25, 5)
    expect(c.twoWeeks).toMatchObject({ targetWeek: '2026-11-30', price: 3450, lower: 3350, upper: 3550 })
    expect(summaryCards([], [], '250001', '2026-11-16')).toEqual({ lastWeek: null, twoWeeks: undefined, volume: null })
  })

  it('추천 한 줄: 1위가 이번 주가 아니면 이번 주 최고안보다 더 남는 돈', () => {
    const rows = [
      { horizon: 3, net_won: 28400 },
      { horizon: 1, net_won: 27200 },
      { horizon: 1, net_won: 26500 },
    ]
    expect(bestPick(rows).gain).toBe(1200)
    expect(bestPick([{ horizon: 1, net_won: 100 }]).gain).toBeNull()
    expect(bestPick([])).toBeNull()
  })
})
