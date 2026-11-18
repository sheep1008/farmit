import { describe, expect, it } from 'vitest'
import { DATA_SOURCES } from '@/constants/dataSources'

const all = DATA_SOURCES.flatMap((g) => g.items)

describe('SCR-016 데이터 출처 목록 (REQ-NFR-007)', () => {
  it('모든 출처에 이름·제공 기관·쓰는 곳·이용 조건이 있다', () => {
    expect(all.length).toBeGreaterThan(0)
    for (const s of all) {
      expect(s.name, JSON.stringify(s)).toBeTruthy()
      expect(s.provider, s.name).toBeTruthy()
      expect(s.use, s.name).toBeTruthy()
      expect(s.terms, s.name).toBeTruthy()
    }
  })

  it('공공누리 제3·4유형 자료는 원문 링크만 쓴다고 적혀 있다', () => {
    const restricted = all.filter((s) => /제[34]유형/.test(s.terms))
    expect(restricted.length).toBeGreaterThan(0) // 농업기술길잡이
    for (const s of restricted) expect(s.terms, s.name).toContain('링크만')
  })

  it('링크는 https 주소다', () => {
    for (const s of all.filter((x) => x.url)) expect(s.url, s.name).toMatch(/^https:\/\//)
  })
})
