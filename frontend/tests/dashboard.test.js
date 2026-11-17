import { describe, expect, it } from 'vitest'
import { CHAT_MAX_LENGTH, chatPrefillRoute } from '@/utils/chat'
import { formatWon, sortRealtimeRows, summarizeMonthly } from '@/utils/dashboard'

describe('채팅 입력창 카드', () => {
  it('앞뒤 공백을 지우고 /chat?q=로 보낸다', () => {
    expect(chatPrefillRoute('  사과 잎에 반점이 있어요 \n')).toEqual({ name: 'chat', query: { q: '사과 잎에 반점이 있어요' } })
  })

  it('공백뿐이면 이동하지 않는다', () => {
    expect(chatPrefillRoute('  \n ')).toBeNull()
    expect(chatPrefillRoute(undefined)).toBeNull()
  })

  it('채팅 화면 최대 글자 수까지만 넘긴다', () => {
    expect(chatPrefillRoute('가'.repeat(CHAT_MAX_LENGTH + 5)).query.q).toHaveLength(CHAT_MAX_LENGTH)
  })
})

describe('이번 달 할 일 카드', () => {
  const t = (task) => ({ task, kind: '농작업', period: '11월 상순~11월 하순' })

  it('이번 달 시작 → 계속 순서로 limit개까지, 나머지는 개수만', () => {
    const s = summarizeMonthly(
      { start: [t('A'), t('B')], continue: [t('C'), t('D'), t('E')], caution: [t('X'), t('Y'), t('Z')] },
      { limit: 3 },
    )
    expect(s.tasks.map((x) => `${x.tag}:${x.task}`)).toEqual(['시작:A', '시작:B', '계속:C'])
    expect(s.hidden).toBe(2)
    expect(s.cautions.map((x) => x.task)).toEqual(['X', 'Y']) // 주의 시기는 기본 2개
  })

  it('다음 달 작업(next)·생육 단계(growth)는 넣지 않는다', () => {
    const s = summarizeMonthly({ start: [], continue: [], next: [t('N')], growth: [t('G')], caution: [] })
    expect(s).toEqual({ tasks: [], hidden: 0, cautions: [] })
  })

  it('데이터가 없어도 빈 요약', () => {
    expect(summarizeMonthly(null)).toEqual({ tasks: [], hidden: 0, cautions: [] })
  })
})

describe('오늘 경매가 카드', () => {
  it('거래가 있는 시장을 위로 올리고, 같은 상태끼리는 API 순서를 지킨다', () => {
    const rows = [
      { market_id: 'a', status: 'no_trade' },
      { market_id: 'b', status: 'closed' },
      { market_id: 'c', status: 'live' },
      { market_id: 'd', status: 'closed' },
    ]
    expect(sortRealtimeRows(rows).map((r) => r.market_id)).toEqual(['c', 'b', 'd', 'a'])
    expect(rows[0].market_id).toBe('a') // 원본 배열은 건드리지 않는다
  })

  it('목록이 없으면 빈 배열', () => {
    expect(sortRealtimeRows(undefined)).toEqual([])
  })

  it('가격은 반올림해 천 단위 쉼표, 없으면 -', () => {
    expect(formatWon(3420.4)).toBe('3,420원')
    expect(formatWon(null)).toBe('-')
  })
})
