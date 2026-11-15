import { describe, expect, it } from 'vitest'
import { REGIONS } from '@/constants/regions'

describe('위치 선택지 (REGIONS)', () => {
  it('17개 시도가 있고, 시도마다 시군구가 한 개 이상이며 겹치지 않는다', () => {
    expect(Object.keys(REGIONS)).toHaveLength(17)
    for (const [sido, list] of Object.entries(REGIONS)) {
      expect(list.length, sido).toBeGreaterThan(0)
      expect(new Set(list).size, sido).toBe(list.length)
    }
  })

  it('DB 컬럼 길이(varchar 20)를 넘는 이름이 없다', () => {
    for (const [sido, list] of Object.entries(REGIONS)) {
      expect(sido.length).toBeLessThanOrEqual(20)
      for (const g of list) expect(g.length).toBeLessThanOrEqual(20)
    }
  })
})
