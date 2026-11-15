import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { profileForm, profilePatch } from '@/utils/profile'

vi.mock('@/api/http', () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))

// docs/api.md 2.1 GET·PATCH·DELETE /api/users/me (SCR-015 내 정보)
const me = {
  id: 2,
  username: 'farmer01',
  sido: '충청북도',
  sigungu: '충주시',
  interest_items: [{ item_id: 10, name: '사과' }],
  transport_cost_per_km: null,
  storage_cost_per_week: 3000,
  loss_rate: 0,
  chat_remaining_today: 20,
}

describe('내 정보 폼 ↔ PATCH 본문', () => {
  it('비어 있는 숫자(null)는 빈 칸으로 보여 준다', () => {
    const form = profileForm(me)
    expect(form.transport_cost_per_km).toBe('')
    expect(form.storage_cost_per_week).toBe(3000)
    expect(form.loss_rate).toBe(0)
  })

  it('관심 품목은 item_id 목록으로, 빈 숫자 칸은 보내지 않는다 (서버가 null을 받지 않음)', () => {
    expect(profilePatch(profileForm(me))).toEqual({
      sido: '충청북도',
      sigungu: '충주시',
      interest_item_ids: [10],
      storage_cost_per_week: 3000,
      loss_rate: 0, // 0은 빈 칸이 아니다
    })
  })
})

describe('회원 탈퇴 (auth 스토어)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    http.delete.mockReset()
  })

  it('비밀번호를 본문에 담아 보내고, 성공하면 비로그인이 된다', async () => {
    http.delete.mockResolvedValue({ status: 204 })
    const auth = useAuthStore()
    auth.setUser(me)
    await auth.withdraw('apple2026!')
    expect(http.delete).toHaveBeenCalledWith('/users/me', { data: { password: 'apple2026!' } })
    expect(auth.isLoggedIn).toBe(false)
  })

  it('비밀번호가 틀리면 오류를 던지고 로그인 상태를 유지한다', async () => {
    const err = Object.assign(new Error('401'), { apiError: { code: 'INVALID_CREDENTIALS' } })
    http.delete.mockRejectedValue(err)
    const auth = useAuthStore()
    auth.setUser(me)
    await expect(auth.withdraw('wrong')).rejects.toBe(err)
    expect(auth.isLoggedIn).toBe(true)
  })
})
