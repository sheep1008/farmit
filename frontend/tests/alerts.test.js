import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { alertDetailRows, caseSeries, caseTypeForAlert, caseTypeLabel, formatPct, nearHoliday, regionText } from '@/utils/alerts'

vi.mock('@/api/alerts', () => ({
  fetchAlerts: vi.fn(async () => ({ data: [], meta: { page: 1, size: 1, total: 3 } })),
  markAlertRead: vi.fn(async (id) => ({ id, is_read: true, read_at: '2026-11-16T10:00:00+09:00' })),
}))

// docs/api.md 2.4 알림 — 상세 detail 표시, 과거 사례 연결, 읽음 처리 뒤 안 읽은 수
describe('caseTypeForAlert', () => {
  it('기상특보는 한파·폭염·호우만 과거 사례로 잇는다', () => {
    expect(caseTypeForAlert({ event_type: 'WARNING', detail: { warning_type: '한파' } })).toBe('COLD_WAVE')
    expect(caseTypeForAlert({ event_type: 'WARNING', detail: { warning_type: '호우' } })).toBe('HEAVY_RAIN')
    expect(caseTypeForAlert({ event_type: 'WARNING', detail: { warning_type: '태풍' } })).toBeNull()
  })

  it('수입량 급증·예찰 증가는 같은 이름, 정부 발표는 없음', () => {
    expect(caseTypeForAlert({ event_type: 'IMPORT_SURGE', detail: {} })).toBe('IMPORT_SURGE')
    expect(caseTypeForAlert({ event_type: 'PEST_INCREASE', detail: {} })).toBe('PEST_INCREASE')
    expect(caseTypeForAlert({ event_type: 'GOV_NOTICE', detail: {} })).toBeNull()
  })

  it('사건 이름은 서버 이름 대신 화면 이름(예찰 증가 → 병해충 증가), 모르는 종류는 서버 이름', () => {
    expect(caseTypeLabel('PEST_INCREASE', '예찰 증가')).toBe('병해충 증가')
    expect(caseTypeLabel('COLD_WAVE', '한파')).toBe('한파')
    expect(caseTypeLabel('TYPHOON', '태풍')).toBe('태풍')
  })
})

describe('formatPct', () => {
  it('부호와 소수 첫째 자리, 값이 없으면 –', () => {
    expect(formatPct(10.12)).toBe('+10.1%')
    expect(formatPct(-3)).toBe('−3.0%')
    expect(formatPct(0)).toBe('0.0%')
    expect(formatPct(null)).toBe('–')
  })
})

describe('alertDetailRows', () => {
  const t = (iso) => `T(${iso})`

  it('기상특보는 종류·단계·구역·발표 시각', () => {
    const rows = alertDetailRows(
      {
        event_type: 'WARNING',
        detail: { warning_type: '한파', level: '주의보', status: '발표', region_name: '가평군', announced_at: 'A' },
      },
      t,
    )
    expect(rows).toEqual([
      ['특보 종류', '한파주의보'],
      ['상태', '발표'],
      ['특보 구역', '가평군'],
      ['발표 시각', 'T(A)'],
    ])
  })

  it('수입량 급증은 수입량과 작년 대비', () => {
    const rows = alertDetailRows(
      { event_type: 'IMPORT_SURGE', detail: { ym: '2026-03', import_kg: 120000, prev_year_kg: 80000, yoy_pct: 50 } },
      t,
    )
    expect(rows).toContainEqual(['수입량', '120,000kg'])
    expect(rows).toContainEqual(['작년 대비', '+50.0%'])
  })

  it('예찰 증가는 병해충마다 한 줄, 정부 발표·빈 detail은 줄 없음', () => {
    const rows = alertDetailRows(
      {
        event_type: 'PEST_INCREASE',
        detail: { pests: [{ pest_name: '탄저병(피해과율)', value: 2.5, prev_value: 1, avg_5y: 0.8 }] },
      },
      t,
    )
    expect(rows).toEqual([['탄저병(피해과율)', '2.5 (지난 조사 1 · 평년 0.8)']])
    expect(alertDetailRows({ event_type: 'GOV_NOTICE', detail: {} }, t)).toEqual([])
    expect(alertDetailRows({ event_type: 'WARNING', detail: null }, t)).toEqual([])
  })
})

describe('caseSeries', () => {
  it('1~4주 변화율·평년을 배열로, 없는 값은 null', () => {
    expect(caseSeries({ change_w1: 8.2, change_w2: null, normal_w1: 1.4 })).toEqual({
      change: [8.2, null, null, null],
      normal: [1.4, null, null, null],
    })
    expect(caseSeries(null).change).toEqual([null, null, null, null])
  })
})

describe('nearHoliday', () => {
  it('설(1/10~2/25)·추석(9/1~10/12) 전후만', () => {
    expect(nearHoliday('2026-01-19')).toBe(true)
    expect(nearHoliday('2025-09-29')).toBe(true)
    expect(nearHoliday('2025-07-21')).toBe(false)
    expect(nearHoliday('2026-03-02')).toBe(false)
  })
})

describe('regionText', () => {
  it('시군구가 없으면 시도만', () => {
    expect(regionText({ sido: '경기도', sigungu: '가평군' })).toBe('경기도 가평군')
    expect(regionText({ sido: '서울특별시', sigungu: null })).toBe('서울특별시')
  })
})

describe('알림 스토어', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('안 읽은 수는 unread=true의 meta.total, 처음 읽을 때만 하나 줄인다', async () => {
    const { useAlertStore } = await import('@/stores/alerts')
    const store = useAlertStore()
    await store.refreshUnread()
    expect(store.unreadCount).toBe(3)

    await store.markRead({ id: 1, is_read: false })
    expect(store.unreadCount).toBe(2)

    await store.markRead({ id: 1, is_read: true }) // 이미 읽은 알림을 다시 열어도 그대로
    expect(store.unreadCount).toBe(2)
  })
})
