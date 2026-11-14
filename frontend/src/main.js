import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import http from './api/http'
import { setupInterceptors } from './api/interceptors'
import { useAuthStore } from './stores/auth'
import { useToastStore } from './stores/toast'

const app = createApp(App)

app.use(createPinia())

// 인터셉터는 pinia를 붙인 뒤, 첫 화면 이동(app.use(router)) 전에 단다
const auth = useAuthStore()
const toast = useToastStore()
setupInterceptors(http, {
  onUnauthenticated: () => {
    auth.setUser(null) // 세션 만료
    const current = router.currentRoute.value
    if (current.name !== 'login') {
      router.push({ name: 'login', query: { next: current.fullPath } })
    }
  },
  notify: toast.show,
})
auth.init() // CSRF 쿠키 → 내 정보. 회원 전용 화면의 가드는 이 결과를 기다린다

app.use(router)

app.mount('#app')
