import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// /api 요청을 넘길 backend 주소. compose 안에서는 http://backend:8000 (docker-compose.yml에서 넣는다),
// 내 PC에서 npm run dev 할 때는 기본값 localhost:8000 을 쓴다.
const apiTarget = process.env.API_PROXY_TARGET || 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0', // 컨테이너 밖(내 PC 브라우저)에서 접속할 수 있게
    port: 5173,
    proxy: {
      // 브라우저는 localhost:5173/api 만 보므로 세션 쿠키·CSRF가 같은 출처로 동작한다.
      // changeOrigin을 켜지 않아 Host가 localhost:5173 그대로 간다
      // → Django ALLOWED_HOSTS(DEBUG 기본 localhost)와 CSRF Origin 검사를 그대로 통과한다.
      '/api': {
        target: apiTarget,
      },
    },
    watch: {
      // Windows에서 바인드 마운트한 폴더는 파일 변경 알림이 컨테이너에 전달되지 않아 폴링으로 감지한다
      usePolling: process.env.VITE_USE_POLLING === 'true',
    },
  },
})
