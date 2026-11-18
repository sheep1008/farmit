import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import http from '@/api/http'
import { requireAuth } from '@/router/guards'
import { useAuthStore } from '@/stores/auth'

// 실제 요청 대신 http.get을 가짜로 바꾼다
vi.mock('@/api/http', () => ({ default: { get: vi.fn() } }))

const unauthorized = () => Object.assign(new Error('401'), { response: { status: 401 } })

// 실제 router/index.js와 같은 방식(beforeEach(requireAuth))으로 작은 라우터를 만든다
function makeRouter() {
  const Empty = { render: () => null }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: Empty },
      { path: '/login', name: 'login', component: Empty },
      { path: '/mypage', name: 'mypage', component: Empty, meta: { requiresAuth: true } },
      { path: '/dash', name: 'dash', component: Empty, meta: { requiresAuth: true, guestRedirect: 'login' } },
      { path: '/error/:kind', name: 'error', component: Empty },
    ],
  })
  router.beforeEach(requireAuth)
  return router
}

beforeEach(() => {
  setActivePinia(createPinia())
  http.get.mockReset()
})

describe('로그인 상태 스토어 + 라우터 가드', () => {
  it('비로그인(/users/me 401)이면 회원 전용 화면에서 로그인 필요 안내(SCR-017)로 보낸다', async () => {
    http.get.mockImplementation(async (url) => {
      if (url === '/users/me') throw unauthorized()
    })
    const router = makeRouter()
    await router.push('/mypage?tab=1')
    expect(router.currentRoute.value.name).toBe('error')
    expect(router.currentRoute.value.params.kind).toBe('login-required')
    expect(router.currentRoute.value.query.next).toBe('/mypage?tab=1') // 로그인 뒤 돌아올 주소(쿼리 포함)
  })

  it('비로그인이 guestRedirect가 있는 화면(첫 화면)에 오면 안내 대신 그 공개 화면으로 보낸다', async () => {
    http.get.mockImplementation(async (url) => {
      if (url === '/users/me') throw unauthorized()
    })
    const router = makeRouter()
    await router.push('/dash')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('로그인 상태면 guestRedirect가 있어도 그 화면에 들어간다', async () => {
    http.get.mockImplementation(async (url) => (url === '/users/me' ? { data: { data: { username: 'farmer01' } } } : {}))
    const router = makeRouter()
    await router.push('/dash')
    expect(router.currentRoute.value.name).toBe('dash')
  })

  it('로그인 상태면 회원 전용 화면에 들어간다', async () => {
    http.get.mockImplementation(async (url) => (url === '/users/me' ? { data: { data: { username: 'farmer01' } } } : {}))
    const router = makeRouter()
    await router.push('/mypage')
    expect(router.currentRoute.value.name).toBe('mypage')
    expect(useAuthStore().user.username).toBe('farmer01')
  })

  it('앱 시작 순서는 csrf → users/me이고, 여러 번 이동해도 한 번만 부른다', async () => {
    http.get.mockResolvedValue({ data: { data: { username: 'farmer01' } } })
    const router = makeRouter()
    await router.push('/mypage')
    await router.push('/')
    await router.push('/mypage')
    expect(http.get.mock.calls.map((c) => c[0])).toEqual(['/auth/csrf', '/users/me'])
    expect(http.get.mock.calls[1][1]).toEqual({ skipAuthRedirect: true })
  })

  it('백엔드가 꺼져 있으면 비로그인으로 보고 로그인 필요 안내로 보낸다', async () => {
    http.get.mockRejectedValue(new Error('Network Error'))
    const router = makeRouter()
    await router.push('/mypage')
    expect(router.currentRoute.value.params.kind).toBe('login-required')
    expect(useAuthStore().isLoggedIn).toBe(false)
  })

  it('공개 화면은 로그인 확인 없이 들어간다', async () => {
    const router = makeRouter()
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('home')
    expect(http.get).not.toHaveBeenCalled()
  })
})
