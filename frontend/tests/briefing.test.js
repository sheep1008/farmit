import { describe, expect, it } from 'vitest'
import { BRIEFING_CHANGE_THRESHOLD_PCT, buildBriefing, weeklyChange } from '@/utils/briefing'

// 2026-11-19는 목요일, 그 주 월요일은 11-16
const TODAY = '2026-11-19'
const week = (period, avg_price) => ({ period, avg_price })
const item = { item_id: 1, name: '사과' }
const market = { market_id: '110001', name: '가락' }
const task = (name) => ({ task: name, kind: '농작업', period: '11월 상순' })

describe('주간 평균가 변화', () => {
  it('이번 주와 지난주를 비교한다', () => {
    const c = weeklyChange([week('2026-11-09', 3000), week('2026-11-16', 3240)], TODAY)
    expect(c.pct).toBeCloseTo(8)
    expect(c.latestIsThisWeek).toBe(true)
  })

  it('이번 주 정산이 아직 없으면(월요일) 지난주와 그 전주를 비교한다', () => {
    const c = weeklyChange([week('2026-11-02', 3000), week('2026-11-09', 2700)], '2026-11-16')
    expect(c.pct).toBeCloseTo(-10)
    expect(c.latestIsThisWeek).toBe(false)
  })

  it('행 순서가 섞여 있어도 기간 순으로 본다', () => {
    expect(weeklyChange([week('2026-11-16', 3240), week('2026-11-09', 3000)], TODAY).pct).toBeCloseTo(8)
  })

  it('비교할 수 없으면 null: 한 주뿐, 사이에 빈 주, 오래된 데이터, 데이터 없음', () => {
    expect(weeklyChange([week('2026-11-16', 3000)], TODAY)).toBeNull()
    expect(weeklyChange([week('2026-11-02', 3000), week('2026-11-16', 3300)], TODAY)).toBeNull()
    expect(weeklyChange([week('2026-10-26', 3000), week('2026-11-02', 3300)], TODAY)).toBeNull()
    expect(weeklyChange(null, TODAY)).toBeNull()
  })
})

describe('오늘의 한 줄 브리핑', () => {
  const weekly = [week('2026-11-09', 3000), week('2026-11-16', 3240)]
  const monthly = { start: [task('A'), task('B'), task('C')], continue: [task('D')] }
  const texts = (parts) => parts.map((p) => p.text)

  it('회원: 시세 → 알림 → 할 일 순서, 마지막 조각만 문장을 끝맺는다', () => {
    const parts = buildBriefing({ item, market, weekly, today: TODAY, unreadAlerts: 2, monthly })
    expect(texts(parts)).toEqual([
      '사과 가락 평균가가 지난주보다 8% 올랐고',
      '읽지 않은 알림이 2건',
      '이번 달 새로 시작할 작업이 3개 있어요',
    ])
    expect(parts.map((p) => p.to)).toEqual([
      { name: 'prices', query: { item_id: 1, market_id: '110001' } },
      { name: 'alerts' },
      { name: 'farming', query: { item_id: 1 } },
    ])
  })

  it('비회원(unreadAlerts null)은 알림 조각 없이 시세·할 일만', () => {
    const parts = buildBriefing({ item, market, weekly, today: TODAY, unreadAlerts: null, monthly })
    expect(parts.map((p) => p.key)).toEqual(['price', 'tasks'])
  })

  it('기준값보다 작게 움직이면 "비슷하다", 내리면 "내렸다"', () => {
    const near = 3000 * (1 + (BRIEFING_CHANGE_THRESHOLD_PCT - 0.5) / 100)
    expect(texts(buildBriefing({ item, market, weekly: [week('2026-11-09', 3000), week('2026-11-16', near)], today: TODAY }))).toEqual([
      '사과 가락 평균가가 지난주와 비슷해요',
    ])
    expect(texts(buildBriefing({ item, market, weekly: [week('2026-11-09', 3000), week('2026-11-16', 2700)], today: TODAY }))).toEqual([
      '사과 가락 평균가가 지난주보다 10% 내렸어요',
    ])
  })

  it('이번 주 정산이 없으면 "지난주 평균가가 그 전주보다"로 말한다', () => {
    const parts = buildBriefing({ item, market, weekly: [week('2026-11-02', 3000), week('2026-11-09', 3300)], today: '2026-11-16' })
    expect(texts(parts)).toEqual(['사과 가락 지난주 평균가가 그 전주보다 10% 올랐어요'])
  })

  it('알림이 마지막 조각이면 "있어요"로 끝난다, 0건이면 뺀다', () => {
    expect(texts(buildBriefing({ item, market, weekly, today: TODAY, unreadAlerts: 2 }))).toEqual([
      '사과 가락 평균가가 지난주보다 8% 올랐고',
      '읽지 않은 알림이 2건 있어요',
    ])
    expect(buildBriefing({ item, market, weekly, today: TODAY, unreadAlerts: 0 }).map((p) => p.key)).toEqual(['price'])
  })

  it('새로 시작할 작업이 없으면 이어서 할 작업 수를 말한다, 둘 다 없으면 뺀다', () => {
    expect(texts(buildBriefing({ item, today: TODAY, monthly: { start: [], continue: [task('D'), task('E')] } }))).toEqual([
      '이번 달 이어서 할 작업이 2개 있어요',
    ])
    expect(buildBriefing({ item, today: TODAY, monthly: { available: false } })).toEqual([])
  })

  it('관심 품목이 없는 회원은 알림 조각만', () => {
    const parts = buildBriefing({ item: null, market, weekly, today: TODAY, unreadAlerts: 1, monthly })
    expect(texts(parts)).toEqual(['읽지 않은 알림이 1건 있어요'])
  })

  it('데이터가 하나도 없으면 빈 배열 (화면이 안내 문장을 보여 준다)', () => {
    expect(buildBriefing({ today: TODAY })).toEqual([])
    expect(buildBriefing({ item, market, weekly: [], today: TODAY, unreadAlerts: 0, monthly: null })).toEqual([])
  })
})
