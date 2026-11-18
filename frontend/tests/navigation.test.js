import { describe, expect, it } from 'vitest'
import { SECTIONS, sectionOf, visibleSections } from '@/constants/navigation'

// router/index.js의 회원 전용 화면 (requiresAuth)
const MEMBER_ONLY = new Set(['dashboard', 'recommend', 'sales', 'diagnose', 'chat'])
const isMemberOnly = (name) => MEMBER_ONLY.has(name)

describe('공통 메뉴 (docs/screens.md 1절)', () => {
  it('로그인하면 5개 메뉴와 하위 화면이 모두 보인다', () => {
    const s = visibleSections(true, isMemberOnly)
    expect(s.map((x) => x.label)).toEqual(['홈', '시세', '판매', '농사', 'AI 상담'])
    expect(s.find((x) => x.key === 'farm').pages.map((p) => p.name)).toEqual(['farming', 'diagnose'])
  })

  it('비회원에게는 회원 전용 화면을 숨기고, 다 숨겨진 메뉴는 뺀다 (REQ-USR-002)', () => {
    const s = visibleSections(false, isMemberOnly)
    expect(s.map((x) => x.key)).toEqual(['market', 'farm'])
    expect(s.find((x) => x.key === 'farm').pages.map((p) => p.name)).toEqual(['farming']) // 증상 진단은 회원 전용
  })

  it('라우트가 속한 메뉴를 찾는다 (메뉴 밖 화면은 null)', () => {
    expect(sectionOf(SECTIONS, 'cases').key).toBe('market')
    expect(sectionOf(SECTIONS, 'sales').key).toBe('sell')
    expect(sectionOf(SECTIONS, 'alerts')).toBeNull()
  })
})
