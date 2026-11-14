import { useAuthStore } from '@/stores/auth'

// 회원 전용 화면(meta.requiresAuth)은 로그인 상태를 확인한 뒤에만 들여보낸다.
// 로그인 뒤 원래 가려던 곳으로 돌아오도록 next에 주소를 담는다 (K08 로그인 화면이 사용).
export async function requireAuth(to) {
  if (!to.meta.requiresAuth) return true
  const auth = useAuthStore()
  await auth.init() // 새로고침 직후에는 아직 /users/me 결과가 없으므로 기다린다
  if (auth.isLoggedIn) return true
  return { name: 'login', query: { next: to.fullPath } }
}
