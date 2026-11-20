import { describe, expect, it } from 'vitest'
import { nextSort, sortRows } from '@/utils/tableSort'

const ROWS = [
  { market_name: '서울가락', avg_price: 1178, last_auction_at: '2026-11-19T02:32:00+09:00' },
  { market_name: '인천삼산', avg_price: null, last_auction_at: null },
  { market_name: '부산엄궁', avg_price: 1198, last_auction_at: '2026-11-19T04:28:00+09:00' },
  { market_name: '광주각화', avg_price: 287, last_auction_at: '2026-11-19T05:45:00+09:00' },
]
const names = (rows) => rows.map((r) => r.market_name)

describe('nextSort — 열 제목 누르기', () => {
  it('큰 값부터 → 작은 값부터 → 기본 순서로 돌아간다', () => {
    const first = nextSort(null, 'avg_price')
    expect(first).toEqual({ key: 'avg_price', dir: 'desc' })
    const second = nextSort(first, 'avg_price')
    expect(second).toEqual({ key: 'avg_price', dir: 'asc' })
    expect(nextSort(second, 'avg_price')).toBeNull()
  })

  it('이름 열은 가나다순부터, 다른 열을 누르면 그 열의 첫 방향부터', () => {
    const name = nextSort(null, 'market_name', 'asc')
    expect(name).toEqual({ key: 'market_name', dir: 'asc' })
    expect(nextSort(name, 'market_name', 'asc')).toEqual({ key: 'market_name', dir: 'desc' })
    expect(nextSort(name, 'avg_price')).toEqual({ key: 'avg_price', dir: 'desc' })
  })
})

describe('sortRows — 표 정렬', () => {
  it('정렬이 없으면 받은 순서 그대로', () => {
    expect(sortRows(ROWS, null)).toBe(ROWS)
  })

  it('숫자 열: 거래 없는 시장(null)은 방향과 상관없이 맨 아래', () => {
    expect(names(sortRows(ROWS, { key: 'avg_price', dir: 'desc' }))).toEqual(['부산엄궁', '서울가락', '광주각화', '인천삼산'])
    expect(names(sortRows(ROWS, { key: 'avg_price', dir: 'asc' }))).toEqual(['광주각화', '서울가락', '부산엄궁', '인천삼산'])
    expect(ROWS[0].market_name).toBe('서울가락') // 원본은 바꾸지 않는다
  })

  it('이름 열은 가나다순, 시각(ISO 글자) 열은 늦은 낙찰부터', () => {
    expect(names(sortRows(ROWS, { key: 'market_name', dir: 'asc' }))).toEqual(['광주각화', '부산엄궁', '서울가락', '인천삼산'])
    expect(names(sortRows(ROWS, { key: 'last_auction_at', dir: 'desc' }))).toEqual(['광주각화', '부산엄궁', '서울가락', '인천삼산'])
  })
})
