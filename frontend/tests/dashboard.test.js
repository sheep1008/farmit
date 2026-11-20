import { describe, expect, it } from 'vitest'
import { CHAT_MAX_LENGTH, chatAskRoute, chatPrefillRoute } from '@/utils/chat'
import { formatWon, summarizeForecast, summarizeMonthly, summarizeRealtime, weatherDetails, weatherIcon } from '@/utils/dashboard'
import { formatKstClock } from '@/utils/dates'

describe('이번 주 예측 카드', () => {
  const row = (market_id, horizon, pred_price, last_week_price, holiday_notice = null) => ({
    market_id, market_name: market_id, horizon, target_week: '2026-11-16', pred_price,
    lower80: pred_price - 100, upper80: pred_price + 100, last_week_price, holiday_notice,
  })

  it('이번 주(horizon 1)만 보고 예측가가 높은 시장 3곳, 지난주 대비 %', () => {
    const s = summarizeForecast([
      row('a', 1, 3000, 3000), row('b', 1, 3500, 2800), row('c', 1, 2000, 2500), row('d', 1, 3200, null),
      row('b', 2, 9999, 2800), // 다음 주 예측은 순위에 넣지 않는다
    ])
    expect(s.top.map((r) => r.market_id)).toEqual(['b', 'd', 'a'])
    expect(s.top[0].change_pct).toBeCloseTo(25)
    expect(s.top[1].change_pct).toBeNull() // 지난주 가격이 없으면 계산하지 않는다
    expect(s.marketCount).toBe(4)
    expect(s.targetWeek).toBe('2026-11-16')
  })

  it('명절 주의 문구가 있으면 하나 꺼낸다', () => {
    expect(summarizeForecast([row('a', 1, 3000, 3000, '설 21일 전')]).holidayNotice).toBe('설 21일 전')
    expect(summarizeForecast([row('a', 1, 3000, 3000)]).holidayNotice).toBeNull()
  })

  it('예측이 없으면 빈 요약', () => {
    expect(summarizeForecast([])).toEqual({ top: [], marketCount: 0, targetWeek: null, holidayNotice: null })
  })
})

describe('홈 현재 날씨·시각', () => {
  it('아이콘: 강수가 하늘 상태보다 먼저, 맑은 밤은 달', () => {
    expect(weatherIcon({ precip_type: '눈', sky: '흐림' })).toBe('🌨️')
    expect(weatherIcon({ precip_type: '빗방울', sky: '흐림' })).toBe('🌧️')
    expect(weatherIcon({ precip_type: null, sky: '맑음', observed_at: '2026-11-20T11:00:00+09:00' })).toBe('☀️')
    expect(weatherIcon({ precip_type: null, sky: '맑음', observed_at: '2026-11-20T21:00:00+09:00' })).toBe('🌙')
    expect(weatherIcon({ precip_type: null, sky: '흐림' })).toBe('☁️')
    expect(weatherIcon({ precip_type: null, sky: null })).toBe('🌡️')
  })

  it('보조 값: 비가 올 때만 강수량, 없는 값은 뺀다', () => {
    expect(weatherDetails({ rain_mm_1h: 0, humidity_pct: 68, wind_ms: 2.4 })).toEqual(['습도 68%', '바람 2.4m/s'])
    expect(weatherDetails({ rain_mm_1h: 0.5, humidity_pct: 90.4, wind_ms: null })).toEqual(['강수 0.5mm', '습도 90%'])
    expect(weatherDetails({ rain_mm_1h: null, humidity_pct: null, wind_ms: null })).toEqual([])
  })

  it('시각은 한국 시간 초 단위', () => {
    expect(formatKstClock(new Date('2026-11-20T02:03:04Z'))).toBe('11:03:04')
  })
})

describe('채팅 입력창 카드', () => {
  it('앞뒤 공백을 지우고 /chat?q=로 보낸다', () => {
    expect(chatPrefillRoute('  사과 잎에 반점이 있어요 \n')).toEqual({ name: 'chat', query: { q: '사과 잎에 반점이 있어요' } })
  })

  it('공백뿐이면 이동하지 않는다', () => {
    expect(chatPrefillRoute('  \n ')).toBeNull()
    expect(chatPrefillRoute(undefined)).toBeNull()
  })

  it('홈 입력창 질문은 바로 보내라는 표시를 주소가 아닌 history.state에 싣는다', () => {
    expect(chatAskRoute(' 사과를 언제 팔까? ')).toEqual({ name: 'chat', query: { q: '사과를 언제 팔까?' }, state: { autoSend: true } })
    expect(chatAskRoute('  ')).toBeNull()
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
  it('거래 있는 시장만 경매 중 → 종료, 같은 상태는 거래량 순으로 4곳, 나머지는 hidden', () => {
    const rows = [
      { market_id: 'a', status: 'no_trade', volume_kg: 0 },
      { market_id: 'b', status: 'closed', volume_kg: 100 },
      { market_id: 'c', status: 'live', volume_kg: 10 },
      { market_id: 'd', status: 'closed', volume_kg: 500 },
      { market_id: 'e', status: 'closed', volume_kg: 50 },
      { market_id: 'f', status: 'closed', volume_kg: 1 },
    ]
    const s = summarizeRealtime(rows)
    expect(s.rows.map((r) => r.market_id)).toEqual(['c', 'd', 'b', 'e'])
    expect(s.hidden).toBe(1)
    expect(rows[0].market_id).toBe('a') // 원본 배열은 건드리지 않는다
  })

  it('목록이 없으면 빈 요약', () => {
    expect(summarizeRealtime(undefined)).toEqual({ rows: [], hidden: 0 })
  })

  it('가격은 반올림해 천 단위 쉼표, 없으면 -', () => {
    expect(formatWon(3420.4)).toBe('3,420원')
    expect(formatWon(null)).toBe('-')
  })
})
