import { describe, expect, it } from 'vitest'
import { compareSentence, formatVsAvg, saleRange } from '@/utils/sales'

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
