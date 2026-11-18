import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { pickItemId, useCurrentItemStore } from '@/stores/currentItem'
import { useAuthStore } from '@/stores/auth'

const ITEMS = [
  { item_id: 1, name: '배추', is_forecast: false },
  { item_id: 10, name: '사과', is_forecast: true },
  { item_id: 20, name: '감자', is_forecast: true },
]

describe('pickItemId — 처음 보여 줄 품목', () => {
  it('주소 → 고른 품목 → 관심 품목 → 예측 대상 → 첫 품목 순서', () => {
    expect(pickItemId(ITEMS, { queryId: 20, currentId: 1, interestIds: [10] })).toBe(20)
    expect(pickItemId(ITEMS, { currentId: 1, interestIds: [20] })).toBe(1)
    expect(pickItemId(ITEMS, { interestIds: [1] })).toBe(1)
    expect(pickItemId(ITEMS)).toBe(10) // 관심 품목이 없으면 예측 대상(사과)
    expect(pickItemId([{ item_id: 5, is_forecast: false }])).toBe(5)
  })

  it('목록에 없는 id는 건너뛰고, 목록이 비면 null', () => {
    expect(pickItemId(ITEMS, { queryId: 999, interestIds: [404, 1] })).toBe(1)
    expect(pickItemId([], { queryId: 1 })).toBeNull()
  })
})

describe('지금 보는 품목 스토어', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('관심 품목으로 시작하고, 다른 화면에서 고른 품목을 이어 받는다', () => {
    useAuthStore().setUser({ interest_items: [{ item_id: 1, name: '배추' }] })
    const store = useCurrentItemStore()
    expect(store.initial(ITEMS, undefined)).toBe(1) // 가격 화면 첫 진입: 관심 품목(배추)
    store.set('20') // 가격 화면에서 감자로 바꿈 (select 값은 문자열일 수 있다)
    expect(store.initial(ITEMS, undefined)).toBe(20) // 재배 정보로 옮겨도 감자
    expect(store.initial(ITEMS, '10')).toBe(10) // 링크가 품목을 정해 주면 그 품목
  })

  it('reset하면 다시 관심 품목부터 고른다', () => {
    useAuthStore().setUser({ interest_items: [{ item_id: 1, name: '배추' }] })
    const store = useCurrentItemStore()
    store.set(20)
    store.reset()
    expect(store.initial(ITEMS, undefined)).toBe(1)
  })
})
