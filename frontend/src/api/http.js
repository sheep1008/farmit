import axios from 'axios'

// 모든 API 요청이 지나가는 axios 인스턴스 (docs/api.md 1.4절, 4절).
// - baseURL '/api': Vue와 같은 출처로 보낸다. 개발 중에는 Vite 프록시가 backend로 넘겨 준다 (vite.config.js).
// - withCredentials: 세션 쿠키(sessionid)를 요청에 싣는다. 같은 출처라 기본으로도 실리지만 명세대로 명시한다.
// - xsrfCookieName/xsrfHeaderName: csrftoken 쿠키 값을 X-CSRFToken 헤더로 자동으로 붙인다 (Django 기본 이름).
const http = axios.create({
  baseURL: '/api',
  withCredentials: true,
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFToken',
})

export default http
