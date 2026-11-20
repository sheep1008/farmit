import { describe, expect, it } from 'vitest'
import { toggleInterestIds } from '@/utils/interest'
import { optionSections } from '@/utils/searchSelect'

const OPTIONS = [
  { value: 1, label: '콩', group: '두류' },
  { value: 2, label: '강낭콩', group: '두류' },
  { value: 3, label: '감자', group: '서류' },
  { value: 4, label: '고구마', group: '서류' },
  { value: 5, label: '사과', group: '과일' },
]
const names = (sections) => sections.map((s) => [s.label, s.options.map((o) => o.label)])

describe('optionSections — 검색 선택 상자 목록', () => {
  it('검색어가 없으면 묶음별로 나눈다 (목록에 나온 순서)', () => {
    expect(names(optionSections(OPTIONS))).toEqual([
      ['두류', ['콩', '강낭콩']],
      ['서류', ['감자', '고구마']],
      ['과일', ['사과']],
    ])
  })

  it('pinned(관심 품목)는 넣은 순서로 맨 위에 한 번 더 보여 준다', () => {
    const sections = optionSections(OPTIONS, { pinned: [5, 3], pinnedLabel: '관심 품목' })
    expect(names(sections)[0]).toEqual(['관심 품목', ['사과', '감자']])
    expect(sections).toHaveLength(4) // 나머지 묶음은 그대로
  })

  it('이름 일부로 찾는다 (앞뒤 공백 무시)', () => {
    expect(names(optionSections(OPTIONS, { query: ' 콩 ' }))).toEqual([['두류', ['콩', '강낭콩']]])
  })

  it('묶음 이름으로도 찾는다 (분류·시도)', () => {
    expect(names(optionSections(OPTIONS, { query: '서류' }))).toEqual([['서류', ['감자', '고구마']]])
  })

  it('검색 결과에 없는 pinned는 빼고, 결과가 없으면 빈 목록', () => {
    expect(names(optionSections(OPTIONS, { query: '감', pinned: [5, 3], pinnedLabel: '관심 품목' }))).toEqual([
      ['관심 품목', ['감자']],
      ['서류', ['감자']],
    ])
    expect(optionSections(OPTIONS, { query: '없는품목', pinned: [5] })).toEqual([])
  })

  it('목록에 없는 pinned 값은 건너뛴다', () => {
    expect(names(optionSections(OPTIONS, { pinned: [999], pinnedLabel: '관심 품목' }))[0][0]).toBe('두류')
  })
})

describe('toggleInterestIds — ★ 누르기', () => {
  it('없으면 맨 뒤에 넣고, 있으면 뺀다', () => {
    expect(toggleInterestIds([1, 2], 3)).toEqual([1, 2, 3])
    expect(toggleInterestIds([1, 2, 3], 2)).toEqual([1, 3])
  })

  it('이미 5개면 더 넣지 않는다 (null), 빼는 것은 된다', () => {
    expect(toggleInterestIds([1, 2, 3, 4, 5], 6)).toBeNull()
    expect(toggleInterestIds([1, 2, 3, 4, 5], 5)).toEqual([1, 2, 3, 4])
  })
})
