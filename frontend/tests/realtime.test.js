import { describe, expect, it } from 'vitest'
import { realtimeStatusText } from '@/utils/realtime'

// docs/api.md 2.3 GET /api/prices/realtime 의 status 표대로 보여 주는지
describe('당일 경매 상태 문구', () => {
  it('경매 중이면 마지막 수집 시각(한국 시간)을 붙인다', () => {
    expect(realtimeStatusText('live', '2026-11-02T09:05:00+09:00')).toBe('경매 중 · 09:05 기준')
    expect(realtimeStatusText('live', '2026-11-02T00:05:00Z')).toBe('경매 중 · 09:05 기준') // UTC로 와도 KST로
  })

  it('경매가 끝났으면 확정 전, 거래가 없으면 거래 없음', () => {
    expect(realtimeStatusText('closed', null)).toBe('오늘 경매 종료 · 확정 전')
    expect(realtimeStatusText('no_trade', null)).toBe('오늘 거래 없음')
  })
})
