import { describe, expect, it } from 'vitest'
import { compareSentence, formatVsAvg, monthBars, overallSentence, saleRange } from '@/utils/sales'

// docs/api.md 2.6 판매 기록 — 기간 필터 쿼리와 "평균 대비 %" 표시
describe('판매 기록 기간 필터', () => {
  it('n개월이면 n개월 전 다음 날부터 오늘까지', () => {
    expect(saleRange('1m', '2026-11-15')).toEqual({ from: '2026-10-16', to: '2026-11-15' })
    expect(saleRange('1y', '2026-11-15')).toEqual({ from: '2025-11-16', to: '2026-11-15' })
  })

  it('전체는 from·to를 보내지 않는다', () => {
    expect(saleRange('all', '2026-11-15')).toEqual({})
  })
})

describe('평균 대비 % 표시', () => {
  it('높게·낮게 받았으면 부호와 소수 첫째 자리', () => {
    expect(formatVsAvg(10)).toEqual({ text: '+10.0%', tone: 'up' })
    expect(formatVsAvg(-5.2)).toEqual({ text: '−5.2%', tone: 'down' })
  })

  it('평균이 없으면(null) 안내 문구, 0이면 같음', () => {
    expect(formatVsAvg(null)).toEqual({ text: '비교할 평균 없음', tone: 'none' })
    expect(formatVsAvg(0)).toEqual({ text: '평균과 같음', tone: 'same' })
  })
})

describe('판매 성적 리포트 (REQ-SAL-005)', () => {
  it('월별 막대는 가장 큰 %를 100으로 본 너비와 방향', () => {
    const bars = monthBars([
      { month: '2026-09', vs_avg_pct: -10 },
      { month: '2026-10', vs_avg_pct: 5 },
      { month: '2026-11', vs_avg_pct: 0 },
    ])
    expect(bars.map((b) => [b.label, b.text, b.tone, b.width])).toEqual([
      ['2026.09', '−10.0%', 'down', 100],
      ['2026.10', '+5.0%', 'up', 50],
      ['2026.11', '평균과 같음', 'same', 0],
    ])
  })

  it('모든 달이 0%여도 0으로 나누지 않는다', () => {
    expect(monthBars([{ month: '2026-11', vs_avg_pct: 0 }])[0].width).toBe(0)
    expect(monthBars([])).toEqual([])
  })

  it('전체 한 문장', () => {
    expect(overallSentence(3.8)).toBe('시장 평균보다 3.8% 높게 받았습니다.')
    expect(overallSentence(-2)).toBe('시장 평균보다 2.0% 낮게 받았습니다.')
    expect(overallSentence(0)).toBe('시장 평균과 같게 받았습니다.')
  })
})

describe('저장 후 같은 날 평균 비교 문장', () => {
  const base = { market_name: '청주', unit_price: 4200, avg_price: 3834.5 }

  it('평균보다 높게·낮게 받았는지 말해 준다', () => {
    expect(compareSentence({ ...base, vs_avg_pct: 9.5 })).toBe(
      'kg당 4,200원. 같은 날 청주 평균 3,835원보다 9.5% 높게 받았습니다.',
    )
    expect(compareSentence({ ...base, vs_avg_pct: -7.1 })).toContain('7.1% 낮게 받았습니다.')
  })

  it('평균이 아직 없으면(오늘 판매 등) 나중에 확인하라고 안내한다', () => {
    expect(compareSentence({ ...base, avg_price: null, vs_avg_pct: null })).toContain('평균 가격이 아직 없습니다')
  })
})
