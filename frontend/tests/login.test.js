import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import http from '@/api/http'
import { safeNext } from '@/router/next'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/http', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

beforeEach(() => {
  setActivePinia(createPinia())
  http.post.mockReset()
})

describe('로그인·로그아웃 (auth 스토어)', () => {
  it('로그인 성공이면 응답 data로 로그인 상태가 된다', async () => {
    http.post.mockResolvedValue({ data: { data: { id: 1, username: 'farmer01' } } })
    const auth = useAuthStore()
    await auth.login('farmer01', 'apple2026!')
    expect(http.post).toHaveBeenCalledWith('/auth/login', { username: 'farmer01', password: 'apple2026!' })
    expect(auth.isLoggedIn).toBe(true)
    expect(auth.user.username).toBe('farmer01')
  })

  it('로그인 실패는 오류를 던지고 비로그인으로 남는다 (화면이 apiError.code로 안내)', async () => {
    const err = Object.assign(new Error('401'), { apiError: { code: 'INVALID_CREDENTIALS' } })
    http.post.mockRejectedValue(err)
    const auth = useAuthStore()
    await expect(auth.login('farmer01', 'wrong')).rejects.toBe(err)
    expect(auth.isLoggedIn).toBe(false)
  })

  it('로그아웃하면 비로그인이 된다. 요청이 실패해도 마찬가지', async () => {
    const auth = useAuthStore()
    auth.setUser({ username: 'farmer01' })
    http.post.mockRejectedValue(new Error('Network Error'))
    await auth.logout()
    expect(http.post).toHaveBeenCalledWith('/auth/logout')
    expect(auth.isLoggedIn).toBe(false)
  })
})

describe('safeNext: 로그인 뒤 돌아갈 주소', () => {
  it('앱 안 경로는 그대로 쓴다', () => {
    expect(safeNext('/mypage?tab=1')).toBe('/mypage?tab=1')
  })

  it('없거나 밖으로 나가는 주소면 대시보드로', () => {
    for (const bad of [undefined, '', 'https://evil.com', '//evil.com', '/\\evil.com', ['/a', '/b']]) {
      expect(safeNext(bad)).toEqual({ name: 'dashboard' })
    }
  })
})
