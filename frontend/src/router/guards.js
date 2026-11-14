import { useAuthStore } from '@/stores/auth'

// 회원 전용 화면(meta.requiresAuth)은 로그인 상태를 확인한 뒤에만 들여보낸다.
// 비로그인이면 SCR-017 '로그인 필요' 안내 화면으로 보낸다. 그 화면의 '로그인하기'가 next를 로그인 화면(K08)에 넘겨
// 로그인 뒤 원래 가려던 곳으로 돌아온다. (세션 만료 401은 main.js가 안내 없이 바로 로그인으로 보낸다)
export async function requireAuth(to) {
  if (!to.meta.requiresAuth) return true
  const auth = useAuthStore()
  await auth.init() // 새로고침 직후에는 아직 /users/me 결과가 없으므로 기다린다
  if (auth.isLoggedIn) return true
  return { name: 'error', params: { kind: 'login-required' }, query: { next: to.fullPath } }
}
