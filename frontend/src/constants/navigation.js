// 공통 메뉴 (docs/screens.md 1절). 사용자가 하려는 일 기준으로 5개 메뉴, 메뉴마다 하위 탭(화면)을 둔다.
// 헤더(PC), 하단 탭 바(모바일), 하위 탭이 모두 이 목록 하나를 읽는다 → 메뉴를 바꿀 때는 여기만 고친다.
// pages[].name = 라우트 이름. 회원 전용 여부는 라우트 meta.requiresAuth에서 읽는다 (router/index.js).
export const SECTIONS = [
  { key: 'home', label: '홈', icon: 'home', pages: [{ name: 'dashboard', label: '대시보드' }] },
  {
    key: 'market',
    label: '가격 통계',
    icon: 'chart',
    pages: [
      { name: 'prices', label: '가격 통계' },
      { name: 'cases', label: '날씨·사건 뒤 가격' },
    ],
  },
  {
    key: 'sell',
    label: '판매 추천',
    icon: 'tag',
    pages: [
      { name: 'recommend', label: '판매 추천' },
      { name: 'sales', label: '판매 기록' },
    ],
  },
  {
    key: 'farm',
    label: '재배 정보',
    icon: 'sprout',
    pages: [
      { name: 'farming', label: '재배 정보' },
      { name: 'diagnose', label: '증상 진단' },
    ],
  },
  { key: 'chat', label: 'AI 챗봇', icon: 'chat', pages: [{ name: 'chat', label: 'AI 챗봇' }] },
]

/**
 * 지금 사용자에게 보일 메뉴. 회원 전용 화면은 로그인했을 때만 보이고(REQ-USR-002),
 * 보이는 화면이 하나도 없는 메뉴는 통째로 숨긴다. 메뉴를 누르면 첫 번째로 보이는 화면으로 간다.
 * isMemberOnly(routeName) → boolean
 */
export function visibleSections(isLoggedIn, isMemberOnly) {
  return SECTIONS.map((s) => ({ ...s, pages: s.pages.filter((p) => isLoggedIn || !isMemberOnly(p.name)) })).filter(
    (s) => s.pages.length,
  )
}

/** 라우트 이름이 속한 메뉴 (없으면 null: 알림·검색·내 정보 등) */
export function sectionOf(sections, routeName) {
  return sections.find((s) => s.pages.some((p) => p.name === routeName)) ?? null
}
