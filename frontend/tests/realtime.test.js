import { describe, expect, it } from 'vitest'
import { realtimeState, realtimeStatusText, sortRealtime } from '@/utils/realtime'

// docs/api.md 2.3 GET /api/prices/realtime 의 status 표대로 보여 주는지
const now = new Date('2026-11-19T13:00:00+09:00')
const live = (last_auction_at, extra = {}) => ({ status: 'live', last_auction_at, ...extra })

describe('당일 경매 상태 문구', () => {
  it('최근 1시간 안에 낙찰이 있으면 경매 중과 마지막 낙찰 시각(한국 시간)', () => {
    expect(realtimeStatusText(live('2026-11-19T12:35:00+09:00'), now)).toBe('경매 중 · 12:35')
    expect(realtimeStatusText(live('2026-11-19T03:35:00Z'), now)).toBe('경매 중 · 12:35') // UTC로 와도 KST로
    expect(realtimeState(live('2026-11-19T12:00:00+09:00'), now)).toBe('active') // 딱 1시간 전까지
  })

  it('1시간 넘게 낙찰이 없으면 끝났다고 하지 않고 마지막 낙찰 시각만', () => {
    expect(realtimeStatusText(live('2026-11-19T08:42:00+09:00'), now)).toBe('08:42 낙찰')
    expect(realtimeState(live('2026-11-19T11:59:00+09:00'), now)).toBe('quiet')
  })

  it('마지막 낙찰이 전날 저녁이면 어제를 붙인다', () => {
    expect(realtimeStatusText(live('2026-11-18T22:10:00+09:00'), now)).toBe('어제 22:10 낙찰')
    const midnight = new Date('2026-11-19T00:20:00+09:00')
    expect(realtimeStatusText(live('2026-11-18T23:50:00+09:00'), midnight)).toBe('경매 중 · 어제 23:50')
  })

  it('경매가 끝났으면 확정 전, 거래가 없으면 거래 없음', () => {
    expect(realtimeStatusText({ status: 'closed', last_auction_at: '2026-11-19T12:35:00+09:00' }, now)).toBe(
      '오늘 경매 종료 · 확정 전',
    )
    expect(realtimeStatusText({ status: 'no_trade', last_auction_at: null }, now)).toBe('오늘 거래 없음')
  })
})

describe('당일 경매 정렬', () => {
  it('경매 중 → 그 밖의 거래 시장 → 거래 없음 순, 같은 묶음은 받은 순서 그대로', () => {
    const rows = [
      live('2026-11-19T08:42:00+09:00', { market_id: 'a' }),
      { status: 'no_trade', last_auction_at: null, market_id: 'b' },
      live('2026-11-19T12:35:00+09:00', { market_id: 'c' }),
      live('2026-11-19T07:55:00+09:00', { market_id: 'd' }),
      live('2026-11-19T12:45:00+09:00', { market_id: 'e' }),
    ]
    expect(sortRealtime(rows, now).map((r) => r.market_id)).toEqual(['c', 'e', 'a', 'd', 'b'])
    expect(rows[0].market_id).toBe('a') // 원본은 바꾸지 않는다
  })
})
