import { describe, expect, it } from 'vitest'
import { addMonths, formatKstDateTime, mondayOf, periodsBetween, todayKst } from '@/utils/dates'

describe('날짜 도우미 (한국 시간 기준)', () => {
  it('todayKst: UTC 15시 이후는 한국에서 다음 날이다', () => {
    expect(todayKst(new Date('2026-11-14T14:59:00Z'))).toBe('2026-11-14')
    expect(todayKst(new Date('2026-11-14T15:00:00Z'))).toBe('2026-11-15')
  })

  it('addMonths: 없는 날짜는 그 달 말일로', () => {
    expect(addMonths('2026-03-31', -1)).toBe('2026-02-28')
    expect(addMonths('2026-11-14', -12)).toBe('2025-11-14')
  })

  it('mondayOf: 그 주 월요일 (일요일은 앞 주 월요일)', () => {
    expect(mondayOf('2026-11-15')).toBe('2026-11-09') // 일요일
    expect(mondayOf('2026-11-09')).toBe('2026-11-09') // 월요일
  })

  it('periodsBetween: API period 형식과 같은 x축을 만든다', () => {
    expect(periodsBetween('2026-11-01', '2026-11-03', 'day')).toEqual(['2026-11-01', '2026-11-02', '2026-11-03'])
    expect(periodsBetween('2026-11-04', '2026-11-16', 'week')).toEqual(['2026-11-02', '2026-11-09', '2026-11-16'])
    expect(periodsBetween('2026-09-15', '2026-11-14', 'month')).toEqual(['2026-09', '2026-10', '2026-11'])
  })

  it('formatKstDateTime: +09:00 시각을 한국 시간으로 보여 준다', () => {
    expect(formatKstDateTime('2026-11-01T06:10:00+09:00')).toContain('06:10')
    expect(formatKstDateTime(null)).toBe('')
  })
})
