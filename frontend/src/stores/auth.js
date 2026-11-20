import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import http from '@/api/http'
import { clearChatPhotos } from '@/utils/chat'
import { clearLastDiagnosis } from '@/utils/farming'

// 로그인 상태. 세션은 쿠키(sessionid, HttpOnly)라 JS에서 볼 수 없으므로 GET /users/me 결과로 판단한다.
export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const isLoggedIn = computed(() => user.value !== null)
  let initPromise = null

  // 앱 시작 때 한 번: CSRF 쿠키 받기 → 내 정보 조회 (200 = 로그인, 401 = 비로그인). docs/api.md 4절.
  // 여러 곳(main.js, 라우터 가드)에서 불러도 실제 요청은 한 번만 가도록 Promise를 기억해 둔다.
  function init() {
    initPromise ??= (async () => {
      try {
        await http.get('/auth/csrf')
        await fetchMe()
      } catch {
        // 백엔드가 꺼져 있으면 비로그인으로 둔다. 토스트는 인터셉터가 띄운다.
        user.value = null
      }
    })()
    return initPromise
  }

  async function fetchMe() {
    try {
      const res = await http.get('/users/me', { skipAuthRedirect: true })
      user.value = res.data.data
    } catch (e) {
      if (e.response?.status !== 401) throw e
      user.value = null
    }
  }

  // 로그인·회원가입 성공 후 화면(K08)이 응답의 data를 넣는다. 로그아웃·세션 만료 때는 null.
  function setUser(data) {
    user.value = data
  }

  // 로그인 (SCR-001, docs/api.md 2.1). 실패하면 오류를 그대로 던진다 → 화면이 err.apiError.code로 안내 문구를 고른다.
  async function login(username, password) {
    const res = await http.post('/auth/login', { username, password })
    user.value = res.data.data // users/me와 같은 모양
  }

  // 로그아웃. 요청이 실패해도(백엔드 꺼짐 등) 화면에서는 비로그인으로 둔다. 토스트는 인터셉터가 띄운다.
  async function logout() {
    try {
      await http.post('/auth/logout')
    } catch {
      // 무시: 서버 세션이 남아 있어도 새로고침하면 /users/me로 다시 맞춰진다
    }
    user.value = null
    // 채팅에 올린 사진 사본과 마지막 증상 진단을 이 브라우저에서 지운다 (같은 PC를 다음 사람이 쓸 수 있다)
    clearChatPhotos()
    clearLastDiagnosis()
  }

  // 회원 탈퇴 (SCR-015, docs/api.md 2.1 DELETE /users/me). 실수 방지로 비밀번호를 다시 받는다.
  // 실패(401 INVALID_CREDENTIALS 등)는 그대로 던지고 로그인 상태를 유지한다 → 화면이 안내한다.
  async function withdraw(password) {
    await http.delete('/users/me', { data: { password } })
    user.value = null // 204: 서버가 계정·개인 데이터를 지우고 세션을 끝냈다
    clearChatPhotos()
    clearLastDiagnosis()
  }

  return { user, isLoggedIn, init, fetchMe, setUser, login, logout, withdraw }
})
