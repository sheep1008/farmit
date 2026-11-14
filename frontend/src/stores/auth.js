import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import http from '@/api/http'

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

  return { user, isLoggedIn, init, fetchMe, setUser }
})
