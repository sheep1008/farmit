import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '../views/DashboardView.vue'
import ErrorView from '../views/ErrorView.vue' // 오류 화면은 네트워크가 나빠도 떠야 하므로 처음부터 같이 싣는다
import { requireAuth } from './guards'

// 아직 만들지 않은 화면은 PlaceholderView로 자리만 잡는다. 화면 카드에서 component만 바꾸면 된다.
const Placeholder = () => import('../views/PlaceholderView.vue')

// 회원 전용 화면은 route에 meta: { requiresAuth: true }를 단다 (guards.js가 막는다). 접근 구분은 docs/screens.md 2절.
// meta.title은 빈 화면 제목과 메뉴 이름에 쓴다.
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'dashboard', // SCR-003 (K20: 알림·특수 상황 카드, 예측 카드 자리)
      component: DashboardView,
      meta: { title: '대시보드', requiresAuth: true },
    },
    { path: '/prices', name: 'prices', component: () => import('../views/PriceView.vue'), meta: { title: '가격' } }, // SCR-004
    {
      path: '/recommend', // SCR-005
      name: 'recommend',
      component: Placeholder,
      meta: { title: '판매 추천', requiresAuth: true },
    },
    {
      path: '/sales', // SCR-006
      name: 'sales',
      component: () => import('../views/SalesView.vue'),
      meta: { title: '판매 기록', requiresAuth: true },
    },
    { path: '/farming', name: 'farming', component: Placeholder, meta: { title: '재배 정보' } }, // SCR-012
    {
      path: '/chat', // SCR-011
      name: 'chat',
      component: () => import('../views/ChatView.vue'),
      meta: { title: '채팅', requiresAuth: true },
    },
    { path: '/search', name: 'search', component: Placeholder, meta: { title: '검색' } }, // SCR-014
    {
      path: '/alerts', // SCR-008
      name: 'alerts',
      component: () => import('../views/AlertListView.vue'),
      meta: { title: '알림', requiresAuth: true },
    },
    {
      path: '/alerts/:id(\\d+)', // SCR-009
      name: 'alert-detail',
      component: () => import('../views/AlertDetailView.vue'),
      props: true,
      meta: { title: '알림 상세', requiresAuth: true },
    },
    { path: '/cases', name: 'cases', component: () => import('../views/CaseView.vue'), meta: { title: '과거 사례' } }, // SCR-010
    {
      path: '/mypage', // SCR-015
      name: 'mypage',
      component: () => import('../views/MyPageView.vue'),
      meta: { title: '내 정보', requiresAuth: true },
    },
    {
      // SCR-016 한 화면의 세 탭: terms(이용약관) · privacy(개인정보처리방침) · sources(데이터 출처)
      path: '/policies/:tab(terms|privacy|sources)',
      name: 'policies',
      component: Placeholder,
      meta: { title: '약관·개인정보·데이터 출처' },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { title: '로그인' },
    },
    {
      path: '/signup', // SCR-002
      name: 'signup',
      component: () => import('../views/SignupView.vue'),
      meta: { title: '회원가입' },
    },
    {
      // SCR-017 오류·안내. 화면에서 보낼 때: router.push({ name: 'error', params: { kind: 'chat-limit' } })
      path: '/error/:kind(login-required|server-error|chat-limit)',
      name: 'error',
      component: ErrorView,
      props: true,
      meta: { title: '안내' },
    },
    {
      // 위 어느 주소에도 맞지 않으면 404 화면. 반드시 맨 마지막에 둔다
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: ErrorView,
      props: { kind: 'not-found' },
      meta: { title: '페이지 없음' },
    },
  ],
})

router.beforeEach(requireAuth)

export default router
